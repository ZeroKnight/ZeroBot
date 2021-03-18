"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

import argparse
import asyncio
import random
import re
import shutil
from collections import deque
from enum import Enum, unique
from typing import Iterable, Tuple

from ZeroBot.common import CommandParser, rand_chance

MODULE_NAME = 'Chat'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Allows ZeroBot to chat and respond to conversation in various ways.'

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

DOT_CHARS = '.·․‥…⋯'
EXCLAMATION_CHARS = '!¡❕❗﹗！'
QUESTION_CHARS = '?¿‽⁇⁈⁉❓❔⸮﹖？'
ALL_CHARS = DOT_CHARS + EXCLAMATION_CHARS + QUESTION_CHARS

PATTERN_WAT = re.compile(r'(?:h+w+|w+h*)[aou]+t\s*\??\s*$')
PATTERN_DOTS = re.compile(r'^\s*[' + ALL_CHARS + r']+\s*$')

DEFAULT_BERATE_CHANCE = 0.5

tables = ['badcmd', 'berate', 'greetings', 'mentioned', 'questioned']
recent_phrases = {}
kicked_from = set()


@unique
class QuestionResponse(Enum):
    Positive = 1
    Negative = 2
    Neutral = 3


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, recent_phrases
    CORE = core

    DB = await core.database_connect(MOD_ID)
    await DB.create_function(
        'cooldown', 0, lambda: CFG.get('PhraseCooldown', 0))
    await _init_database()

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]
    for table in tables:
        recent_phrases[table] = deque(maxlen=CFG.get('PhraseCooldown', 0))

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_database():
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS "chat_badcmd" (
            "phrase"    TEXT NOT NULL UNIQUE,
            "action"    BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            PRIMARY KEY("phrase")
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS "chat_berate" (
            "phrase"    TEXT NOT NULL UNIQUE,
            "action"    BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            PRIMARY KEY("phrase")
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS "chat_greetings" (
            "phrase"    TEXT NOT NULL UNIQUE,
            "action"    BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            PRIMARY KEY("phrase")
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS "chat_mentioned" (
            "phrase"    TEXT NOT NULL UNIQUE,
            "action"    BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            PRIMARY KEY("phrase")
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS "chat_questioned" (
            "phrase"    TEXT NOT NULL UNIQUE,
            "action"    BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            "response_type"     INTEGER NOT NULL,
            PRIMARY KEY("phrase")
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS "idx_chat_questioned_response_type"
        ON "chat_questioned" ("response_type" ASC);
    """)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_say = CommandParser('say', 'Force ZeroBot to say something')
    cmd_say.add_argument('msg', nargs='+', help='The message to send')
    cmd_say.add_argument(
        '-t', '--to', action='append', metavar='target',
        help=('Where to send the message. Can be given more than once to '
              'include multiple targets. The default target is the channel '
              'where the command was sent.')
    )
    cmd_say.add_argument(
        '-a', '--action', action='store_true',
        help=('If specified, the message will be sent as an "action" instead '
              'of a normal message.')
    )
    cmds.append(cmd_say)

    cmd_fortune = CommandParser('fortune', 'Crack open a UNIX fortune cookie')
    # NOTE: Due to a bug(?) in argparse, this has to be an option, since a lone
    # positional argument with nargs=REMAINDER still rejects unknown options.
    cmd_fortune.add_argument(
        '-a', '--args', nargs=argparse.REMAINDER,
        help='Arguments to pass to the system `fortune` command')
    cmds.append(cmd_fortune)

    CORE.command_register(MOD_ID, *cmds)


async def fetch_phrase(table: str, columns: Iterable[str],
                       query: str = None, parameters: Tuple = None) -> Tuple:
    """Convenient wrapper for fetching phrases.

    Wraps a query intended to return a phrase from one of the Chat tables.
    Automatically takes the recent phrases list into consideration; selecting
    a different phrase if needed.

    Parameters
    ----------
    table : str
        The table to pull from, *without* the module identifier prefix.
    columns : Iterable[str]
        The columns to select, *except* the ``phrase`` column, which is
        implied.
    query : str, optional
        The body of the query, placed after ``FROM table`` and before
        ``ORDER BY``.
    parameters : tuple, optional
        Parameters to use use with `query`.

    Returns
    -------
    tuple
        A tuple of values for each requested column.

    Notes
    -----
    This wrapper will take care of the ``ORDER BY`` and ``LIMIT`` clauses, so
    they should not be included in `query`. The limit is chosen based on the
    current value of the ``Chat.PhraseCooldown`` setting.
    """
    columns = ('phrase', *columns)
    async with DB.cursor() as cur:
        await cur.execute(
            f"""SELECT {', '.join(columns)} FROM chat_{table}
            {query}
            ORDER BY RANDOM() LIMIT cooldown() + 1""", parameters)
        row = await cur.fetchone()
        while row['phrase'] in recent_phrases[table]:
            row = await cur.fetchone()
    recent_phrases[table].append(row['phrase'])
    return row


def _resize_phrase_deques():
    for table in tables:
        new_len = CFG['PhraseCooldown']
        if new_len == recent_phrases[table].maxlen:
            break
        recent_phrases[table] = deque(
            recent_phrases[table].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'modules':
        _resize_phrase_deques()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == 'modules' and key == 'Chat.PhraseCooldown':
        _resize_phrase_deques()


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    sender = message.source

    # Don't respond to our own messages.
    if ctx.user == sender or not CFG.get('Enabled'):
        return

    # Berate
    if CFG.get('Berate.Enabled') and sender.name in CFG.get('Berate.UserList'):
        if rand_chance(CFG.get('Berate.Chance', DEFAULT_BERATE_CHANCE)):
            phrase, action = await fetch_phrase('berate', ['action'])
            phrase.replace('%0', sender.name)
            await ctx.module_message(message.destination, phrase, action)
            return

    # wat
    if PATTERN_WAT.search(message.content):
        await ctx.module_message(
            message.destination,
            random.choice(('wat', 'wut', 'wot', 'what', 'whut')))
        return

    # Dots...!
    if PATTERN_DOTS.match(message.content):
        char = random.choice(EXCLAMATION_CHARS + QUESTION_CHARS)
        await ctx.module_message(
            message.destination, f'{message.content}{char}')
        return

    # Answer Questions
    if CFG.get('Questioned.Enabled'):
        for pattern in CFG.get('Questioned.Triggers'):
            # Check against bare name and mention string to handle protocols
            # where these may differ, like Discord.
            pattern = pattern.replace(r'\z', f'{ctx.user.mention_pattern()}')
            pattern = pattern.replace(r'\q', f'[{QUESTION_CHARS}]')
            if re.search(pattern, message.content, re.I):
                if re.search(r'would you kindly', message.content, re.I):
                    phrase, action = await fetch_phrase(
                        'questioned', ['action'],
                        'WHERE response_type = ?',
                        (QuestionResponse.Positive.value,))
                else:
                    phrase, action = await fetch_phrase(
                        'questioned', ['action'])
                await ctx.module_message(message.destination, phrase, action)
                return

    # Respond to being mentioned... oddly
    # NOTE: Needs to be LOW priority
    if CFG.get('Mentioned.Enabled') and ctx.user.mentioned(message):
        phrase, action = await fetch_phrase('mentioned', ['action'])
        await ctx.module_message(message.destination, phrase, action)


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    if not (CFG.get('Enabled') and CFG.get('Greet.Enabled')):
        return
    if user == ctx.user:
        if channel in kicked_from:
            # Don't greet if we've been kicked from here
            kicked_from.remove(channel)
    else:
        phrase, action = await fetch_phrase('greetings', ['action'])
        await ctx.module_message(channel, phrase, action)


async def module_on_invalid_command(ctx, cmd_msg):
    """Handle `Core` invalid-command event."""
    # Insult a user when they enter a malformed or invalid command.
    if not (CFG.get('Enabled') and CFG.get('BadCmd.Enabled')):
        return
    phrase, action = await fetch_phrase('badcmd', ['action'])
    await ctx.module_message(cmd_msg.destination, phrase, action)


async def module_on_kick(ctx, channel, user):
    """Handle `Core` kick event."""
    if user == ctx.user:
        # Note where we've been kicked from
        kicked_from.add(channel)


async def module_command_say(ctx, parsed):
    """Handle `say` command."""
    targets = []
    if parsed.args['to']:
        for target in parsed.args['to']:
            if ctx.protocol == 'discord':
                target = ctx.get_target(target)
            targets.append(target)
    else:
        targets.append(parsed.msg.destination)
    for target in targets:
        await ctx.module_message(
            target, ' '.join(parsed.args['msg']), parsed.args['action'])


async def module_command_fortune(ctx, parsed):
    """Handle `fortune` command."""
    fortune_path = shutil.which('fortune')
    if not fortune_path:
        await ctx.reply_command_result(
            parsed, 'fortune is not available. No cookie for you :(')
        return
    try:
        lines = []
        args = parsed.args['args'] or []
        proc = await asyncio.create_subprocess_exec(
            fortune_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        while data := await proc.stdout.readline():
            lines.append(data.decode().rstrip())
        await proc.wait()
        if proc.returncode != 0:
            await CORE.module_send_event('invalid_command', ctx, parsed.msg)
            return
        await ctx.reply_command_result(parsed, lines)
    except OSError:
        await ctx.reply_command_result(
            parsed, 'Your fortune cookie seems to have crumbled...')
