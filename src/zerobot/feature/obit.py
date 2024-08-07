"""Obit

A clone of redroid's obituary generator. Users can "kill" one another (or
themselves) in amusing ways by randomly combining weapons, methods, and other
modifiers.
"""

from __future__ import annotations

import logging
import random
import re
from collections import deque
from datetime import datetime, timezone
from enum import Enum, unique
from functools import partial
from importlib import resources
from string import Template, punctuation
from typing import TYPE_CHECKING

from zerobot.command import CmdResult, CommandParser
from zerobot.database import Participant
from zerobot.database import find_participant as findpart
from zerobot.database import get_participant as getpart
from zerobot.util import rand_chance

if TYPE_CHECKING:
    import sqlite3

MODULE_NAME = "Obit"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.1"
MODULE_LICENSE = "MIT"
MODULE_DESC = (
    'Obituary generator. "Kill" users in amusing ways with '
    "randomly assembled obituaries from a pool of weapons and "
    "styles."
)

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit(".", 1)[-1]
get_participant = None
find_participant = None

logger = logging.getLogger("ZeroBot.Feature.Obit")

DEFAULT_COOLDOWN = 0.1
DEFAULT_SUICIDE_CHANCE = 0.33
DEFAULT_ZEROBOT_SUICIDE_CHANCE = 0.02

recent_parts = {}
victim_placeholder_pat = re.compile(r"\$(?:\{victim\}|victim)")


@unique
class ObitPart(Enum):
    Weapon = 1
    Kill = 2
    Closer = 3
    Suicide = 4


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB, get_participant, find_participant
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config("modules").get(MODULE_NAME)
    cooldown = CFG.get("PartCooldown", DEFAULT_COOLDOWN)
    for otype in ObitPart:
        recent_parts[otype.name] = deque(maxlen=cooldown)

    DB = await core.database_connect(MOD_ID)
    await DB.create_function("cooldown", 0, lambda: cooldown)
    await DB.executescript(resources.files("zerobot").joinpath("sql/schema/obit.sql").read_text())

    get_participant = partial(getpart, DB)
    find_participant = partial(findpart, DB)

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_obit = CommandParser("obit", '"Kill" someone and generate a random obituary.')
    cmd_obit.add_argument("victim", nargs="*", help="The poor sap to destroy")
    cmds.append(cmd_obit)

    type_list = "kill method, weapon, closer, or suicide"
    cmd_obitdb = CommandParser("obitdb", "Modify or query the obituary database.")
    add_subcmd = cmd_obitdb.make_adder(metavar="OPERATION", dest="subcmd", required=True)
    subcmd_add = add_subcmd("add", f"Add a new {type_list} to the database.", aliases=["new"])
    subcmd_add.add_argument(
        "type",
        choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower,
        help="The type of obituary part to add.",
    )
    subcmd_add.add_argument(
        "content",
        nargs="+",
        help=(
            "The content to add. The following placeholders are recognized "
            "and will be expanded appropriately: `$killer`, `$victim`, and "
            "`$zerobot`. Wrap the placeholder name in curly braces to "
            "expand them within a word, e.g. `${killer}Man`. Reference "
            "existing obituaries to see how to phrase your content."
        ),
    )

    subcmd_del = add_subcmd(
        "del",
        f"Remove a {type_list} from the database.",
        aliases=["rm", "remove", "delete"],
    )
    subcmd_del.add_argument(
        "type",
        choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower,
        help="The type of obituary part to remove.",
    )
    subcmd_del.add_argument(
        "content",
        nargs="+",
        help=(
            "The content to remove. Must exactly match an existing entry, "
            "with placeholders NOT expanded, i.e. `$killer` as-is. Refer to "
            "the `add` subcommand help for more details."
        ),
    )

    subcmd_edit = add_subcmd("edit", f"Edit an existing {type_list} in the database.")
    subcmd_edit.add_argument(
        "type",
        choices=[otype.name.lower() for otype in ObitPart],
        type=str.lower,
        help="The type of obituary part to edit.",
    )
    subcmd_edit.add_argument(
        "substitution",
        help=(
            "A sed-like substitution expression, e.g. "
            "`s/pattern/replacement/flags`, where `pattern` is a regular "
            "expression that specifies what to replace and `replacement` "
            "contains the text to replace. `flags` is an optional set of "
            "flags that modifies the edit. Including `i` enables "
            "case-insensitive matching. A number limits how many matches "
            "are replaced (or `g` to replace all matches). By default, only "
            "the first match is replaced. Substitution uses Python's "
            "`re.sub` internally, so all of its syntax applies."
        ),
    )
    subcmd_edit.add_argument(
        "content",
        nargs="+",
        help=(
            "The content to edit. Must exactly match an existing entry, "
            "with placeholders NOT expanded, i.e. `$killer` as-is. Refer to "
            "the `add` subcommand help for more details."
        ),
    )
    cmds.append(cmd_obitdb)

    cmd_obitstats = CommandParser("obitstats", "Show various stats about obit kills")
    cmd_obitstats.add_argument(
        "user",
        nargs="?",
        help="Retrieve stats for the given user. If omitted, return stats for yourself.",
    )
    cmd_obitstats.add_argument(
        "-g",
        "--global",
        action="store_true",
        help="Retrieve general stats about the obit database as a whole.",
    )
    cmds.append(cmd_obitstats)

    CORE.command_register(MOD_ID, *cmds)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == "modules":
        _resize_part_deques()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == "modules" and key == "Obit.PartCooldown":
        _resize_part_deques()


def _resize_part_deques():
    for name in ObitPart.__members__:
        new_len = CFG.get("PartCooldown", DEFAULT_COOLDOWN)
        if new_len == recent_parts[name].maxlen:
            break
        recent_parts[name] = deque(recent_parts[name].copy(), maxlen=new_len)


async def fetch_part(otype: ObitPart) -> sqlite3.Row | None:
    """Fetch an obit string of a particular type."""
    async with DB.cursor() as cur:
        await cur.execute(
            """
            SELECT content, type, submitter, date_added FROM obit_strings
            WHERE type = ?
            ORDER BY RANDOM() LIMIT cooldown() + 1;
        """,
            (otype.value,),
        )
        rows = await cur.fetchall()
        if len(rows) == 0:
            return None
        if CFG.get("PartCooldown", DEFAULT_COOLDOWN):
            for row in rows:
                if row["content"] not in recent_parts[otype.name]:
                    part = row
                    recent_parts[otype.name].append(row["content"])
                    break
            else:
                # We have fewer phrases than the cooldown limit, so ignore it
                part = rows[0]
        else:
            part = rows[0]
        return part


async def update_death_toll(killer: Participant, victim: Participant):
    """Update the obit table's kill counts."""
    killer_params = (killer.id, 1, 0, 0)
    victim_params = (victim.id, 0, 1, 0)
    date = datetime.now(tz=timezone.utc)
    async with DB.cursor() as cur:
        if killer == victim:
            values = "VALUES (?, ?, ?, ?)"
            params = (killer.id, 0, 0, 1)
        else:
            values = "VALUES (?, ?, ?, ?), (?, ?, ?, ?)"
            params = killer_params + victim_params

        await cur.execute(
            f"""
            INSERT INTO obit (participant_id, kills, deaths, suicides)
            {values}
            ON CONFLICT (participant_id) DO UPDATE SET
                kills = kills + excluded.kills,
                deaths = deaths + excluded.deaths,
                suicides = suicides + excluded.suicides
        """,
            params,
        )
        await cur.execute(
            """
            UPDATE obit SET last_victim = ?, last_kill = ?
            WHERE participant_id = ?
        """,
            (victim.id, date, killer.id),
        )
        await cur.execute(
            """
            UPDATE obit SET last_murderer = ?, last_death = ?
            WHERE participant_id = ?
        """,
            (killer.id, date, victim.id),
        )
    await DB.commit()


async def module_command_obit(ctx, parsed):
    """Handle `obit` command."""
    killer = await get_participant(parsed.invoker.name)
    if not parsed.args["victim"]:
        # No victim specified, so the invoker dies. Random chance dictates
        # whether it's a suicide, or the killer is chosen at random from the
        # current channel.
        suicide_chance = CFG.get("SuicideChance", DEFAULT_SUICIDE_CHANCE)
        if rand_chance(suicide_chance):
            bot_suicide_chance = CFG.get("ZeroBotSuicideChance", DEFAULT_ZEROBOT_SUICIDE_CHANCE)
            if rand_chance(bot_suicide_chance):
                # Being an idiot, ZeroBot may kill himself instead.
                killer = await get_participant(ctx.user.name)
            victim = killer
        else:
            if parsed.source.is_dm:
                chosen = random.choice((ctx.user, parsed.invoker))
            else:
                chosen = random.choice(await parsed.source.users())
            victim = killer
            killer = await get_participant(chosen.name)
    else:
        victim = await get_participant(" ".join(parsed.args["victim"]).lstrip("@"))

    killed = (await fetch_part(ObitPart.Kill))["content"]
    weapon = (await fetch_part(ObitPart.Weapon))["content"]
    placeholders = {
        "killer": killer.name,
        "victim": victim.name,
        "zerobot": ctx.user.name,
    }
    if victim == killer:
        closer = (await fetch_part(ObitPart.Suicide))["content"]
        placeholders["victim"] = "themself"
    else:
        closer = (await fetch_part(ObitPart.Closer))["content"]
    obit_template = Template(f"{killer} {killed} with {weapon} {closer}")
    obituary = obit_template.safe_substitute(placeholders).replace("themself's", "their")

    await update_death_toll(killer, victim)
    await ctx.module_message(obituary, parsed.source)


async def module_command_obitdb(ctx, parsed):
    """Handle `obitdb` command."""

    def _parse_sed_substitution(sub_str: str) -> tuple[str, str, set[str] | None]:
        if sub_str and sub_str.startswith("s/"):
            pattern, repl, *flags = re.split(r"(?<!\\)/", sub_str[2:])
            if flags and flags[0]:
                flags = flags[0]
                if "-" in flags:
                    raise ValueError("Bad sed flags")
                flags = set(re.findall(r"([a-zA-z]|\d+)", flags))
            else:
                flags = None
        else:
            raise ValueError("Bad sed pattern")
        return pattern, repl, flags

    content = " ".join(parsed.args["content"]).strip()
    content = re.sub(r"\B@(\S+)", r"\1", content)
    if not content:
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return
    otype = getattr(ObitPart, parsed.args["type"].title())
    if parsed.subcmd in {"add", "del"}:
        await globals()[f"obit_{parsed.subcmd}"](ctx, parsed, otype, content)
    elif parsed.subcmd == "edit":
        sub = parsed.args["substitution"].lstrip()
        try:
            pattern, repl, flags = _parse_sed_substitution(sub)
        except ValueError:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        else:
            await obit_edit(ctx, parsed, otype, content, pattern, repl, flags)
    else:
        ...  # TODO


async def obit_exists(otype: ObitPart, content: str) -> bool:
    """Check if the given obituary part content exists."""
    async with DB.cursor() as cur:
        await cur.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM obit_strings
                WHERE type = ? AND content = ?
            )
        """,
            (otype.value, content),
        )
        return bool((await cur.fetchone())[0])


async def obit_add(ctx, parsed, otype: ObitPart, content: str):
    """Add an obituary part to the database."""
    # Quality heuristics
    if len(content) > 200:
        await ctx.reply_command_result("That's too long, cut it down some.", parsed, CmdResult.TooLong)
    if otype is ObitPart.Kill:
        if content.endswith(" with"):
            content = content[:-5]
        if not victim_placeholder_pat.search(content):
            content += " $victim"
    elif otype in {ObitPart.Closer, ObitPart.Suicide}:
        if content[0] in punctuation and not content.startswith("..."):
            await ctx.reply_command_result(
                "Don't start closers with punctuation (ellipses are fine).", parsed, CmdResult.BadSyntax
            )
            return

    if await obit_exists(otype, content):
        await ctx.reply_command_result(f"There is already a {otype.name}: `{content}`", parsed, CmdResult.Exists)
        return
    date = datetime.now(tz=timezone.utc)
    submitter = await get_participant(parsed.invoker.name)

    async with DB.cursor() as cur:
        await cur.execute(
            "INSERT INTO obit_strings VALUES(?, ?, ?, ?)",
            (content, otype.value, submitter.id, date),
        )
    await DB.commit()
    await ctx.module_message(f"Okay, adding {otype.name}: `{content}`", parsed.source)


async def obit_del(ctx, parsed, otype: ObitPart, content: str):
    """Remove an obituary part from the database."""
    if not await obit_exists(otype, content):
        await ctx.reply_command_result(f"Couldn't find {otype.name}: `{content}`", parsed, CmdResult.NotFound)
        return
    async with DB.cursor() as cur:
        await cur.execute(
            "DELETE FROM obit_strings WHERE type = ? AND content = ?",
            (otype.value, content),
        )
    await DB.commit()
    await ctx.module_message(f"Okay, removed {otype.name}: `{content}`", parsed.source)


async def obit_edit(
    ctx,
    parsed,
    otype: ObitPart,
    content: str,
    pattern: str,
    repl: str,
    flags: set[str] | None = None,
):
    """Edit an obituary part in the database."""
    if not await obit_exists(otype, content):
        await ctx.reply_command_result(f"Couldn't find {otype.name}: `{content}`", parsed, CmdResult.NotFound)
        return
    count, re_flags = 1, 0
    if flags is not None:
        for flag in flags:
            if flag == "g":
                count = 0
            elif flag == "i":
                re_flags = re.I
            elif flag.isdigit():
                count = int(flag)
    edited = re.sub(pattern, repl, content, count=count, flags=re_flags)
    async with DB.cursor() as cur:
        await cur.execute(
            """
            UPDATE obit_strings SET content = ?
            WHERE type = ? AND content = ?
        """,
            (edited, otype.value, content),
        )
    await DB.commit()
    await ctx.module_message(f"Okay, content is now: `{edited}`", parsed.source)


async def module_command_obitstats(ctx, parsed):
    """Get stats about the obit database."""

    def _format_last_kd(user: Participant, victim: tuple, murderer: tuple):
        last_msg = []
        try:
            if victim[0] == murderer[0] == user:
                return f"Their last victim was ...themself at {victim[1]}"
        except AttributeError:
            pass
        if victim[0]:
            last_msg.append(f"Their last victim was {victim[0]} at {victim[1]}.")
        if murderer[0]:
            last_msg.append(f"They were last killed by {murderer[0]} at {murderer[1]}.")
        return " ".join(last_msg)

    if parsed.args["global"] and parsed.args["user"]:
        # These are mutually exclusive arguments
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return
    if parsed.args["global"]:
        async with DB.cursor() as cur:
            await cur.execute(
                """
                WITH ranks AS (
                    SELECT name AS "User",
                           rank() OVER (ORDER BY kills DESC) AS "Kill Rank",
                           kills AS "Kills",
                           rank() OVER (ORDER BY deaths DESC) AS "Death Rank",
                           deaths AS "Deaths",
                           rank() OVER (ORDER BY suicides DESC) AS "Suicide Rank",
                           suicides AS "Suicides"
                    FROM obit
                    JOIN participants USING (participant_id)
                )
                SELECT * FROM ranks
                WHERE "Kill Rank" = 1 OR "Death Rank" = 1 OR "Suicide Rank" = 1
            """
            )
            rows = await cur.fetchall()
        if not rows:
            await ctx.module_message("Amazingly, not a single soul has perished yet.", parsed.source)
            return
        kills, deaths, suicides = [], [], []
        for row in rows:
            if row["Kill Rank"] == 1:
                kills.append((row["User"], row["Kills"]))
            if row["Death Rank"] == 1:
                deaths.append((row["User"], row["Deaths"]))
            if row["Suicide Rank"] == 1:
                suicides.append((row["User"], row["Suicides"]))
        msg = []
        for category, top_ranks in zip(("Kills", "Deaths", "Suicides"), (kills, deaths, suicides), strict=False):
            if top_ranks:
                users = ", ".join(f"{user[0]} ({user[1]})" for user in top_ranks)
                msg.append(f"**Most {category}**: {users}")
        await ctx.module_message("\n".join(msg), parsed.source)
    else:
        try:
            user = await find_participant(parsed.args["user"].lstrip("@"))
        except AttributeError:
            user = await find_participant(parsed.invoker.name)
        except ValueError:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
            return
        async with DB.cursor() as cur:
            await cur.execute("SELECT * FROM obit WHERE participant_id = ?", (user.id,))
            row = await cur.fetchone()
        if row is None:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadTarget)
            return
        victim = await Participant.from_id(DB, row["last_victim"])
        murderer = await Participant.from_id(DB, row["last_murderer"])
        msg = [f"{user.name} has {row['kills']} kills, {row['deaths']} deaths, and {row['suicides']} suicides."]
        msg.append(_format_last_kd(user, (victim, row["last_kill"]), (murderer, row["last_death"])))
        await ctx.module_message(" ".join(msg), parsed.source)
