"""Obit

A clone of redroid's obituary generator. Users can "kill" one another (or
themselves) in amusing ways by randomly combining weapons, methods, and other
modifiers.
"""

import logging
import random
import re
import sqlite3
from collections import deque
from datetime import datetime
from enum import Enum, unique
from string import Template, punctuation
from typing import Optional, Set, Union

from ZeroBot.common import CommandParser, rand_chance
from ZeroBot.database import DBUser, Participant

MODULE_NAME = 'Obit'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = ('Obituary generator. "Kill" users in amusing ways with '
               'randomly assembled obituaries from a pool of weapons and '
               'styles.')

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

logger = logging.getLogger('ZeroBot.Feature.Obit')

DEFAULT_COOLDOWN = 0.1
DEFAULT_SUICIDE_CHANCE = 0.33
DEFAULT_ZEROBOT_SUICIDE_CHANCE = 0.02

recent_parts = {}
victim_placeholder_pat = re.compile(r'\$(?:\{victim\}|victim)')


@unique
class ObitPart(Enum):
    Weapon = 1
    Kill = 2
    Closer = 3
    Suicide = 4


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules').get(MODULE_NAME)
    cooldown = CFG.get('PartCooldown', DEFAULT_COOLDOWN)
    for otype in ObitPart:
        recent_parts[otype.name] = deque(maxlen=cooldown)

    DB = await core.database_connect(MOD_ID)
    await DB.create_function('cooldown', 0, lambda: cooldown)
    await _init_database()

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_database():
    await DB.executescript(f"""
        CREATE TABLE IF NOT EXISTS "obit" (
            "participant_id" INTEGER NOT NULL DEFAULT 0,
            "kills"          INTEGER NOT NULL DEFAULT 0,
            "deaths"         INTEGER NOT NULL DEFAULT 0,
            "suicides"       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY ("participant_id"),
            FOREIGN KEY ("participant_id")
                REFERENCES "{Participant.table_name}" ("participant_id")
                ON DELETE SET DEFAULT
                ON UPDATE CASCADE
        );
        CREATE TABLE IF NOT EXISTS "obit_strings" (
            "content"    TEXT NOT NULL,
            "type"       INTEGER NOT NULL DEFAULT 1,
            "submitter"  INTEGER NOT NULL DEFAULT 0,
            "date_added" DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY ("content", "type"),
            FOREIGN KEY ("submitter")
                REFERENCES "{Participant.table_name}" ("participant_id")
                ON DELETE SET DEFAULT
                ON UPDATE CASCADE
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS "idx_obit_strings_type"
        ON "obit_strings" ("type" ASC);
    """)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_obit = CommandParser(
        'obit', '"Kill" someone and generate a random obituary.')
    cmd_obit.add_argument(
        'victim', nargs='*', help='The poor sap to destroy')
    cmds.append(cmd_obit)

    type_list = 'kill method, weapon, closer, or suicide'
    cmd_obitdb = CommandParser(
        'obitdb', 'Modify or query the obituary database.')
    add_subcmd = cmd_obitdb.make_adder(
        metavar='OPERATION', dest='subcmd', required=True)
    subcmd_add = add_subcmd(
        'add', f'Add a new {type_list} to the database.', aliases=['new'])
    subcmd_add.add_argument(
        'type', choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower, help='The type of obituary part to add.')
    subcmd_add.add_argument(
        'content', nargs='+',
        help=('The content to add. The following placeholders are recognized '
              'and will be expanded appropriately: `$killer`, `$victim`, and '
              '`$zerobot`. Wrap the placeholder name in curly braces to '
              'expand them within a word, e.g. `${killer}Man`. Reference '
              'existing obituaries to see how to phrase your content.'))
    subcmd_del = add_subcmd(
        'del', f'Remove a {type_list} from the database.',
        aliases=['rm', 'remove', 'delete'])
    subcmd_del.add_argument(
        'type', choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower, help='The type of obituary part to remove.')
    subcmd_del.add_argument(
        'content', nargs='+',
        help=('The content to remove. Must exactly match an existing entry, '
              'with placeholders NOT expanded, i.e. `$killer` as-is. Refer to '
              'the `add` subcommand help for more details.'))
    subcmd_edit = add_subcmd(
        'edit', f'Edit an existing {type_list} in the database.')
    subcmd_edit.add_argument(
        'type', choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower, help='The type of obituary part to edit.')
    subcmd_edit.add_argument(
        'substitution',
        help=('A sed-like substitution expression, e.g. '
              '`s/pattern/replacement/flags`, where `pattern` is a regular '
              'expression that specifies what to replace and `replacement` '
              'contains the text to replace. `flags` is an optional set of '
              'flags that modifies the edit. Including `i` enables '
              'case-insensitive matching. A number limits how many matches '
              'are replaced (or `g` to replace all matches). By default, only '
              "the first match is replaced. Substitution uses Python's "
              '`re.sub` internally, so all of its syntax applies.'))
    subcmd_edit.add_argument(
        'content', nargs='+',
        help=('The content to edit. Must exactly match an existing entry, '
              'with placeholders NOT expanded, i.e. `$killer` as-is. Refer to '
              'the `add` subcommand help for more details.'))
    cmds.append(cmd_obitdb)

    # TODO: stats command

    CORE.command_register(MOD_ID, *cmds)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'modules':
        _resize_part_deques()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == 'modules' and key == 'Obit.PartCooldown':
        _resize_part_deques()


def _resize_part_deques():
    for name in ObitPart.__members__.keys():
        new_len = CFG.get('PartCooldown', DEFAULT_COOLDOWN)
        if new_len == recent_parts[name].maxlen:
            break
        recent_parts[name] = deque(
            recent_parts[name].copy(), maxlen=new_len)


async def get_participant(target: Union[int, str]) -> Optional[Participant]:
    """Fetch the given participant by name or ID.

    If `target` is a `str` and there's no matching participant, create a new
    one and return that. If `target` is an `int` and no match was found, `None`
    is returned instead.

    Parameters
    ----------
    target : int or str
        A Participant ID or name to look up.
    """
    if isinstance(target, str):
        if target.strip() == '':
            raise ValueError('Name is empty or whitespace')
        what = 'an.name = ?1 OR lower(an.name) = lower(?1)'
    elif isinstance(target, int):
        what = 'participant_id = ?1'
    else:
        raise TypeError('target must be either int or str')

    async with DB.cursor() as cur:
        await cur.execute(f"""
            SELECT participant_id, participants.name, user_id
            FROM participants
            JOIN participants_all_names AS "an" USING (participant_id)
            WHERE {what}
        """, (target,))
        row = await cur.fetchone()
        if row is None:
            if isinstance(target, int):
                return None
            # Create a new Participant
            participant = Participant(DB, None, target)
            await participant.save()
        else:
            participant = Participant.from_row(DB, row)
            try:
                await participant.fetch_user()
            except ValueError:
                pass
    return participant


async def fetch_part(otype: ObitPart) -> Optional[sqlite3.Row]:
    """Fetch an obit string of a particular type."""
    async with DB.cursor() as cur:
        await cur.execute("""
            SELECT content, type, submitter, date_added FROM obit_strings
            WHERE type = ?
            ORDER BY RANDOM() LIMIT cooldown() + 1;
        """, (otype.value,))
        rows = await cur.fetchall()
        if len(rows) == 0:
            return None
        if CFG.get('PartCooldown', DEFAULT_COOLDOWN):
            for row in rows:
                if row['content'] not in recent_parts[otype.name]:
                    part = row
                    recent_parts[otype.name].append(row['content'])
                    break
            else:
                # We have fewer phrases than the cooldown limit, so ignore it
                part = rows[0]
        else:
            part = rows[0]
        return part


# TODO: Add "last_victim", "last_murderer", "last_kill" (time), and
# "last_death" (time) columns
async def update_death_toll(killer: Participant, victim: Participant):
    """Update the obit table's kill counts."""
    killer_params = (killer.id, 1, 0, 0)
    victim_params = (victim.id, 0, 1, 0)
    async with DB.cursor() as cur:
        if killer == victim:
            values = 'VALUES (?, ?, ?, ?)'
            params = (killer.id, 0, 0, 1)
        else:
            values = 'VALUES (?, ?, ?, ?), (?, ?, ?, ?)'
            params = killer_params + victim_params

        await cur.execute(f"""
            INSERT INTO obit
            {values}
            ON CONFLICT (participant_id) DO UPDATE SET
                kills = kills + excluded.kills,
                deaths = deaths + excluded.deaths,
                suicides = suicides + excluded.suicides
        """, params)
    await DB.commit()


async def module_command_obit(ctx, parsed):
    """Handle `obit` command."""
    killer = await get_participant(parsed.invoker.name)
    if not parsed.args['victim']:
        # No victim specified, so the invoker dies. Random chance dictates
        # whether it's a suicide, or the killer is chosen at random from the
        # current channel.
        suicide_chance = CFG.get('SuicideChance', DEFAULT_SUICIDE_CHANCE)
        if rand_chance(suicide_chance):
            bot_suicide_chance = CFG.get(
                'ZeroBotSuicideChance', DEFAULT_ZEROBOT_SUICIDE_CHANCE)
            if rand_chance(bot_suicide_chance):
                # Being an idiot, ZeroBot may kill himself instead.
                killer = await get_participant(ctx.user.name)
            victim = killer
        else:
            # TODO: protocol agnostic
            import discord
            if isinstance(parsed.source, discord.DMChannel):
                chosen = random.choice((ctx.user, parsed.source.recipient))
            else:
                chosen = random.choice(parsed.source.members)
            victim = killer
            killer = await get_participant(chosen.name)
    else:
        victim = await get_participant(
            ' '.join(parsed.args['victim']).lstrip('@'))

    killed = (await fetch_part(ObitPart.Kill))['content']
    weapon = (await fetch_part(ObitPart.Weapon))['content']
    placeholders = {
        'killer': killer.name,
        'victim': victim.name,
        'zerobot': ctx.user.name
    }
    if victim == killer:
        closer = (await fetch_part(ObitPart.Suicide))['content']
        placeholders['victim'] = 'themself'
    else:
        closer = (await fetch_part(ObitPart.Closer))['content']
    obit_template = Template(f'{killer} {killed} with {weapon} {closer}')
    obituary = obit_template.safe_substitute(placeholders) \
                            .replace("themself's", 'their')

    await update_death_toll(killer, victim)
    await ctx.module_message(parsed.source, obituary)


async def module_command_obitdb(ctx, parsed):
    """Handle `obitdb` command."""
    content = ' '.join(parsed.args['content']).strip()
    content = re.sub(r'\B@(\S+)', r'\1', content)
    if not content:
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return
    otype = getattr(ObitPart, parsed.args['type'].title())
    if parsed.subcmd in ('add', 'del'):
        await globals()[f'obit_{parsed.subcmd}'](ctx, parsed, otype, content)
    elif parsed.subcmd == 'edit':
        sub = parsed.args['substitution'].lstrip()
        try:
            if sub and sub.startswith('s/'):
                pattern, repl, *flags = re.split(r'(?<!\\)/', sub[2:])
                if flags and flags[0]:
                    flags = flags[0]
                    if '-' in flags:
                        raise ValueError('Bad sed flags')
                    flags = set(re.findall(r'([a-zA-z]|\d+)', flags))
                else:
                    flags = None
            else:
                raise ValueError('Bad sed pattern')
        except ValueError:
            await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        else:
            await obit_edit(ctx, parsed, otype, content, pattern, repl, flags)
    else:
        ...  # TODO


async def obit_exists(otype: ObitPart, content: str) -> bool:
    """Check if the given obituary part content exists."""
    async with DB.cursor() as cur:
        await cur.execute("""
            SELECT EXISTS(
                SELECT 1 FROM obit_strings
                WHERE type = ? AND content = ?
            )
        """, (otype.value, content))
        return bool((await cur.fetchone())[0])


async def obit_add(ctx, parsed, otype: ObitPart, content: str):
    """Add an obituary part to the database."""
    # Quality heuristics
    if len(content) > 200:
        await ctx.reply_command_result(
            parsed, "That's too long, cut it down some.")
    if otype is ObitPart.Kill:
        if content.endswith(' with'):
            content = content[:-5]
        if not victim_placeholder_pat.search(content):
            content += ' $victim'
    elif otype in (ObitPart.Closer, ObitPart.Suicide):
        if content[0] in punctuation and not content.startswith('...'):
            await ctx.reply_command_result(
                parsed,
                "Don't start closers with punctuation (ellipses are fine).")
            return

    if await obit_exists(otype, content):
        await ctx.reply_command_result(
            parsed, f'There is already a {otype.name}: `{content}`')
        return
    date = datetime.utcnow().replace(microsecond=0)
    submitter = await get_participant(parsed.invoker.name)

    async with DB.cursor() as cur:
        await cur.execute(
            'INSERT INTO obit_strings VALUES(?, ?, ?, ?)',
            (content, otype.value, submitter.id, date))
    await DB.commit()
    await ctx.module_message(
        parsed.source, f'Okay, adding {otype.name}: `{content}`')


async def obit_del(ctx, parsed, otype: ObitPart, content: str):
    """Remove an obituary part from the database."""
    if not await obit_exists(otype, content):
        await ctx.reply_command_result(
            parsed, f"Couldn't find {otype.name}: `{content}`")
        return
    async with DB.cursor() as cur:
        await cur.execute(
            'DELETE FROM obit_strings WHERE type = ? AND content = ?',
            (otype.value, content))
    await DB.commit()
    await ctx.module_message(
        parsed.source, f'Okay, removed {otype.name}: `{content}`')


async def obit_edit(ctx, parsed, otype: ObitPart, content: str,
                    pattern: str, repl: str, flags: Set[str] = None):
    """Edit an obituary part in the database."""
    if not await obit_exists(otype, content):
        await ctx.reply_command_result(
            parsed, f"Couldn't find {otype.name}: `{content}`")
        return
    count, re_flags = 1, 0
    if flags is not None:
        for flag in flags:
            if flag == 'g':
                count = 0
            elif flag == 'i':
                re_flags = re.I
            elif flag.isdigit():
                count = int(flag)
    edited = re.sub(pattern, repl, content, count, re_flags)
    async with DB.cursor() as cur:
        await cur.execute("""
            UPDATE obit_strings SET content = ?
            WHERE type = ? AND content = ?
        """, (edited, otype.value, content))
    await ctx.module_message(
        parsed.source, f'Okay, content is now: `{edited}`')
