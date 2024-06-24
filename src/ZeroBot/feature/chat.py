"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import re
import shutil
from collections import deque
from enum import Enum, unique
from importlib import resources
from typing import Iterable

from ZeroBot.common import CommandParser, rand_chance
from ZeroBot.common.enums import CmdResult

try:
    import discord
    import discord.ext.tasks

    _discord_available = True
except ImportError:
    _discord_available = False

MODULE_NAME = "Chat"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.1"
MODULE_LICENSE = "MIT"
MODULE_DESC = "Allows ZeroBot to chat and respond to conversation in various ways."

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit(".", 1)[-1]

logger = logging.getLogger("ZeroBot.Feature.Chat")

DOT_CHARS = ".·․‥…⋯"
EXCLAMATION_CHARS = "!¡❕❗﹗！"
QUESTION_CHARS = "?¿‽⁇⁈⁉❓❔⸮﹖？"
ALL_CHARS = DOT_CHARS + EXCLAMATION_CHARS + QUESTION_CHARS
ALL_CHARS_EXCEPT_PERIOD = DOT_CHARS[1:] + EXCLAMATION_CHARS + QUESTION_CHARS

PATTERN_WAT = re.compile(rf"(?:h+w+|w+h*)[aou]+t\s*[{ALL_CHARS}]*\s*$", re.I)
PATTERN_DOTS = re.compile(
    rf"""
    (?:  # Line is only punctuation
        ^\s*
        ([{ALL_CHARS}]+)
        \s*$
    ) |
    (?:  # Message ends with at least 2 punctuation or excessive ellipses-periods
        [-\w()]+\s*
        ([{ALL_CHARS_EXCEPT_PERIOD}]{{2,}} | [{ALL_CHARS}]{{5,}})
        \s*$
    )
""",
    re.X,
)

DEFAULT_ACTIVITY_INTERVAL = 1800
DEFAULT_BERATE_CHANCE = 0.5
DEFAULT_VAGUE_CHANCE = 0.5

tables = ["activity", "badcmd", "berate", "greetings", "mentioned", "questioned"]
recent_phrases = {}
kicked_from = set()
shuffler_tasks = []


@unique
class ActivityType(Enum):
    Playing = 1
    Listening = 2
    Watching = 3
    Competing = 4

    def as_discord(self) -> discord.ActivityType:
        """Translate this enum value into one that Discord expects."""
        return discord.ActivityType.__members__[self.name.lower()]


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
    await DB.create_function("cooldown", 0, lambda: CFG.get("PhraseCooldown", 0))
    await DB.executescript(resources.files("ZeroBot").joinpath("sql/schema/chat.sql").read_text())

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config("modules")[MODULE_NAME]
    for table in tables:
        recent_phrases[table] = deque(maxlen=CFG.get("PhraseCooldown", 0))

    _register_commands()

    # Schedule Activity Shufflers
    if _discord_available:
        interval = CFG.get("Activity.Interval", DEFAULT_ACTIVITY_INTERVAL)
        for ctx in filter(lambda x: x.protocol == "discord", CORE.get_contexts()):
            global shuffler_tasks
            logger.debug(f"Adding Activity Shuffler task for context {ctx}")
            task = discord.ext.tasks.Loop(
                shuffle_discord_activity,
                time=discord.ext.tasks.MISSING,  # XXX: This interface got a bit silly in 2.0
                seconds=interval,
                minutes=0,
                hours=0,
                count=None,
                reconnect=True,
            )
            shuffler_tasks.append(task)
            task.start(ctx)


async def module_unregister():
    """Prepare for shutdown."""
    # Cancel Activity Shufflers
    for task in shuffler_tasks:
        task.cancel()
    await CORE.database_disconnect(MOD_ID)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_say = CommandParser("say", "Force ZeroBot to say something")
    cmd_say.add_argument("msg", nargs="+", help="The message to send")
    cmd_say.add_argument(
        "-t",
        "--to",
        action="append",
        metavar="target",
        help=(
            "Where to send the message. Can be given more than once to "
            "include multiple targets. The default target is the channel "
            "where the command was sent."
        ),
    )
    cmd_say.add_argument(
        "-a",
        "--action",
        action="store_true",
        help='If specified, the message will be sent as an "action" instead of a normal message.',
    )
    cmds.append(cmd_say)

    cmd_fortune = CommandParser("fortune", "Crack open a UNIX fortune cookie")
    # NOTE: Due to a bug(?) in argparse, this has to be an option, since a lone
    # positional argument with nargs=REMAINDER still rejects unknown options.
    cmd_fortune.add_argument(
        "-a",
        "--args",
        nargs=argparse.REMAINDER,
        help="Arguments to pass to the system `fortune` command",
    )
    cmds.append(cmd_fortune)

    CORE.command_register(MOD_ID, *cmds)


async def fetch_phrase(
    table: str, columns: Iterable[str], query: str | None = None, parameters: tuple | None = None
) -> tuple:
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
    columns = ("phrase", *columns)
    async with DB.cursor() as cur:
        await cur.execute(
            f"""SELECT {", ".join(columns)} FROM chat_{table}
            {query}
            ORDER BY RANDOM() LIMIT cooldown() + 1""",
            parameters,
        )
        row = await cur.fetchone()
        while row["phrase"] in recent_phrases[table]:
            row = await cur.fetchone()
    recent_phrases[table].append(row["phrase"])
    return row


def _resize_phrase_deques():
    for table in tables:
        new_len = CFG["PhraseCooldown"]
        if new_len == recent_phrases[table].maxlen:
            break
        recent_phrases[table] = deque(recent_phrases[table].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name != "modules":
        return

    _resize_phrase_deques()

    interval = CFG.get("Activity.Interval", DEFAULT_ACTIVITY_INTERVAL)
    for task in shuffler_tasks:
        task.change_interval(seconds=interval)


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name != "modules" or not key.startswith(MODULE_NAME):
        return
    key = key[len(MODULE_NAME) + 1 :]

    if key == "PhraseCooldown":
        _resize_phrase_deques()
    elif key == "Activity.Interval":
        interval = new if new is not None else DEFAULT_ACTIVITY_INTERVAL
        for task in shuffler_tasks:
            task.change_interval(seconds=interval)


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    sender = message.source

    # Don't respond to our own messages.
    if ctx.user == sender or not CFG.get("Enabled"):
        return

    # Berate
    if CFG.get("Berate.Enabled") and sender.name in CFG.get("Berate.UserList"):
        if rand_chance(CFG.get("Berate.Chance", DEFAULT_BERATE_CHANCE)):
            phrase, action = await fetch_phrase("berate", ["action"])
            phrase.replace("%0", sender.name)
            await ctx.module_message(phrase, message.destination, action)
            return

    # wat
    if PATTERN_WAT.search(message.content):
        await ctx.module_message(random.choice(("wat", "wut", "wot", "what", "whut")), message.destination)
        return

    # Answer Questions
    if CFG.get("Questioned.Enabled"):
        for pattern in CFG.get("Questioned.Triggers"):
            # Check against bare name and mention string to handle protocols
            # where these may differ, like Discord.
            pattern = pattern.replace(r"\z", f"{ctx.user.mention_pattern()}")
            pattern = pattern.replace(r"\q", f"[{QUESTION_CHARS}]")
            if re.search(pattern, message.content, re.I):
                if re.search(r"would you kindly", message.content, re.I):
                    if rand_chance(0.95):
                        phrase, action = await fetch_phrase(
                            "questioned",
                            ["action"],
                            "WHERE response_type = ?",
                            (QuestionResponse.Positive.value,),
                        )
                    else:
                        phrase = f"beats {sender.name} to death with a golf club"
                        action = True
                else:
                    phrase, action = await fetch_phrase("questioned", ["action"])
                await ctx.module_message(phrase, message.destination, action)
                return

    # Respond to being mentioned... oddly
    if CFG.get("Mentioned.Enabled") and ctx.user.mentioned(message):
        phrase, action = await fetch_phrase("mentioned", ["action"])
        await ctx.module_message(phrase, message.destination, action)
        return

    # Dots...!
    if match := PATTERN_DOTS.search(message.content):
        dots = "".join(random.choices(EXCLAMATION_CHARS + QUESTION_CHARS, k=random.randint(1, 3)))
        await ctx.module_message(f"{match[1] or match[2]}{dots}", message.destination)
        return


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    if not (CFG.get("Enabled") and CFG.get("Greet.Enabled")):
        return
    if user == ctx.user:
        if channel in kicked_from:
            # Don't greet if we've been kicked from here
            kicked_from.remove(channel)
    else:
        phrase, action = await fetch_phrase("greetings", ["action"])
        await ctx.module_message(phrase, channel, action)


async def module_on_invalid_command(ctx, cmd_msg, err=CmdResult.Unspecified):
    """Handle `Core` invalid_command event."""
    # Insult a user when they enter a malformed or invalid command.
    if not (CFG.get("Enabled") and CFG.get("BadCmd.Enabled")):
        return
    vague_chance = CFG.get("BadCmd.VagueChance", DEFAULT_VAGUE_CHANCE)
    if err != CmdResult.Unspecified and rand_chance(vague_chance):
        # ZeroBot might still be vague regardless
        err = CmdResult.Unspecified
    phrase, action = await fetch_phrase("badcmd", ["action"], "WHERE error_type = ?", (err.value,))
    await ctx.module_message(phrase, cmd_msg.destination, action)


async def module_on_kick(ctx, channel, user):
    """Handle `Core` kick event."""
    if user == ctx.user:
        # Note where we've been kicked from
        kicked_from.add(channel)


async def module_command_say(ctx, parsed):
    """Handle `say` command."""
    targets = []
    if parsed.args["to"]:
        for target in parsed.args["to"]:
            if ctx.protocol == "discord":
                target = ctx.get_target(target)
            targets.append(target)
    else:
        targets.append(parsed.msg.destination)
    for target in targets:
        await ctx.module_message(" ".join(parsed.args["msg"]), target, parsed.args["action"])


async def module_command_fortune(ctx, parsed):
    """Handle `fortune` command."""
    fortune_path = shutil.which("fortune")
    if not fortune_path:
        await ctx.reply_command_result("fortune is not available. No cookie for you :(", parsed, CmdResult.Unavailable)
        return
    try:
        lines = []
        args = parsed.args["args"] or []
        proc = await asyncio.create_subprocess_exec(
            fortune_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        while data := await proc.stdout.readline():
            lines.append(data.decode().rstrip())
        await proc.wait()
        if proc.returncode != 0:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
            return
        await ctx.reply_command_result(lines, parsed)
    except OSError:
        await ctx.reply_command_result("Your fortune cookie seems to have crumbled...", parsed, CmdResult.Unspecified)


async def shuffle_discord_activity(ctx):
    """Set a random activity from the database.

    This is for Discord contexts, and sets the "Playing", "Listening to",
    "Watching", etc. status.
    """
    if not (CFG.get("Enabled") and CFG.get("Activity.Enabled")):
        return
    await ctx.wait_until_ready()
    async with DB.cursor() as cur:
        await cur.execute(
            """
            SELECT type, activity, emoji FROM chat_activity
            ORDER BY RANDOM() LIMIT cooldown() + 1
        """
        )
        row = await cur.fetchone()
        while row["activity"] in recent_phrases["activity"]:
            row = await cur.fetchone()
    recent_phrases["activity"].append(row["activity"])

    name = row["activity"]
    if row["emoji"]:
        name += f" {row['emoji']}"
    activity = discord.Activity(type=ActivityType(row["type"]).as_discord(), name=name)
    logger.info(f"Shuffling activity to: {name}")
    await ctx.change_presence(activity=activity)
