"""Counter

Keep a running total of arbitrary occurrences or statements made in ZeroBot's
presence and announce when they happen.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from importlib import resources
from string import Template
from typing import Iterable

from ZeroBot.common import CommandParser
from ZeroBot.common.enums import CmdErrorType
from ZeroBot.database import Participant

MODULE_NAME = "Counter"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.1"
MODULE_LICENSE = "MIT"
MODULE_DESC = "Keep a running total of arbitrary events or statements and announce when they happen."

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit(".", 1)[-1]

logger = logging.getLogger("ZeroBot.Feature.Counter")

SPECIAL_NUMBERS = {
    21: "TWENTY ONE! I WON! SUCK MY DICK!",
    42: "Ah, the meaning of life. It was right here the whole time.",
    64: "Ohhh, BANANA.",
    69: "Lmao, nice.",
    76: "It just works.",
    100: "No longer a low-level counter!",
    104: "The World ends with Shibuya.",
    256: "We 8-bit now.",
    300: "THIS. IS. **SPARTA!**",
    314: "Mmmm, pie.",
    358: "*Donald Duck screeches incessently in the background*",
    420: "Blaze it. 🔥",
    451: "Do you smell something burning?",
    500: "Okay, we're getting somewhere now.",
    666: "*death metal sounds in the distance*",
    777: "A meteor for mother.",
    833: "🐝",
    1000: "Impressive.",
    1337: "5!(|< //!13570z3, |3|20",
    1999: "It's time to party 🎉",
    8008: "BOOBA.",
    9999: "Hit the damage cap!",
    10000: "Absolutely astonishing. We've made it here through either great spam or much time. Or both.",
}
counters = {}


class Counter:
    """A `Counter` keeps track of how many times a particular event occurred.

    Counters are either based on a series of trigger patterns or are manually
    triggered. Whenever a counter is triggered, it is incremented, and the time
    and location of the trigger is recorded.
    """

    def __init__(
        self,
        name: str,
        description: str,
        announcement: str | None = None,
        count: int = 0,
        *,
        enabled: bool = True,
        announce: bool = False,
        match_case: bool = False,
        triggers: list[str] | None = None,
        restrictions: list[str] | None = None,
        blacklist: list[str] | None = None,
        created_at: datetime | None = None,
        last_triggered: datetime | None = None,
        last_user: Participant = None,
        last_channel: str | None = None,
    ):
        now = datetime.utcnow()
        self.name = name
        self.description = description
        if announcement is not None:
            self.announcement = Template(announcement)
        else:
            self.announcement = None
        self.count = count
        self.enabled = enabled
        self.announce = announce
        self.match_case = match_case
        self.triggers = [re.compile(trigger, (re.I if not match_case else 0)) for trigger in (triggers or [])]
        self.restrictions = restrictions or []
        self.blacklist = blacklist or []
        self.created_at = created_at or now.replace(microsecond=0)
        self.last_triggered = last_triggered
        self.last_user = last_user
        self.last_channel = last_channel

    def __repr__(self):
        attrs = [
            "name",
            "count",
            "created_at",
            "last_triggered",
            "last_user",
            "last_channel",
        ]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    async def fetch_data(self) -> bool:
        """Fetch this counter's data from the database.

        Returns `True` if the counter existed and data was fetched, or `False`
        if it doesn't exist.
        """
        async with DB.cursor() as cur:
            await cur.execute("SELECT * FROM counter WHERE name = ?", (self.name,))
            row = await cur.fetchone()
        if row is None:
            return False
        self.last_user = await Participant.from_id(DB, row["last_user"])
        for attr in ("count", "created_at", "last_triggered", "last_channel"):
            setattr(self, attr, row[attr])
        return True

    def can_trigger(self, name: str) -> bool:
        """Return whether `name` can trigger this `Counter`.

        If this counter's `restrictions` list is non-empty, then `name` must be
        in the list. Regardless, the result is always `False` if `name` is in
        the blacklist.
        """
        if name in self.blacklist or name in CFG["Blacklist"]:
            return False
        return len(self.restrictions) == 0 or name in self.restrictions

    def check(self, string: str) -> bool:
        """Check if `string` matches one of this counter's triggers."""
        return any(trigger.search(string) for trigger in self.triggers)

    def get_announcement(self, **kwargs) -> str:
        """Return the expanded announcement string for this counter.

        If given, `kwargs` are passed to the template substitution for the
        announcement string.
        """
        if "user" not in kwargs:
            raise ValueError("Missing required 'user' kwarg")
        kwargs["r_all"] = or_join(self.restrictions)
        kwargs["r_user"] = kwargs["user"] if kwargs["user"] in self.restrictions else kwargs["r_all"]
        return self.announcement.safe_substitute(kwargs, count=self.count)

    def should_announce(self) -> bool:
        """Check whether this counter should be announced or not.

        Counter announcements can be disabled globally or per-counter.
        """
        return CFG["Announce"] and self.announce

    async def increment(
        self,
        n: int = 1,
        participant: Participant | str = None,
        channel: str | None = None,
    ):
        """Increment the counter and update its metadata and the database.

        Ensures that the counter's last trigger time, channel, and so on are
        updated and written to the database.

        Parameters
        ----------
        n : int, optional
            The number to increment the counter by. Defaults to 1.
        participant : Participant or str, optional
            The user that caused the increment.
        channel : str, optional
            Where the increment occurred.
        """
        self.count += n
        now = datetime.utcnow()
        self.last_triggered = now.replace(microsecond=0)
        async with DB.cursor() as cur:
            if isinstance(participant, str):
                await cur.execute(
                    """
                    SELECT participant_id FROM participants_all_names
                    WHERE name = ?
                """,
                    (participant,),
                )
                row = await cur.fetchone()
                participant = await Participant.from_id(DB, row["participant_id"])
            self.last_user = participant

            await cur.execute(
                """
                UPDATE counter SET
                    count = ?,
                    last_triggered = ?,
                    last_user = ?,
                    last_channel = ?
                WHERE name = ?
            """,
                (self.count, now, participant.id, channel, self.name),
            )
            await DB.commit()


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB, counters
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config("modules")[MODULE_NAME]

    DB = await core.database_connect(MOD_ID)
    await DB.executescript(resources.files("ZeroBot").joinpath("sql/schema/counter.sql").read_text())
    loaded = await load_counters()
    if loaded:
        logger.info(f"Loaded {loaded} Counters")
    else:
        logger.warning("No Counters loaded.")

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_count = CommandParser("count", "Manually increment a counter.")
    cmd_count.add_argument("counter", help="The name of the counter to increment.")
    cmd_count.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="The number of times to increment the counter. Default is once.",
    )
    cmd_count.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Increment the counter without announcing it.",
    )
    cmds.append(cmd_count)

    cmd_counter = CommandParser("counter", "List available counters or show their current counts.")
    add_subcmd = cmd_counter.make_adder(metavar="OPERATION", dest="subcmd", required=True)
    subcmd_announce = add_subcmd(
        "announce",
        "Show the current count for a counter without incrementing it.",
        aliases=["show"],
    )
    subcmd_announce.add_argument("counter", help="The name of the counter to announce.")
    subcmd_list = add_subcmd("list", "List available counters and their current counts.", aliases=["ls"])
    subcmd_list.add_argument(
        "counter",
        nargs="*",
        help="Get counts only for the specified counters. If omitted, all available counters will be lsited.",
    )
    subcmd_list.add_argument(
        "-f",
        "--full",
        action="store_true",
        help="Show current count and descriptions for each counter as well.",
    )
    subcmd_info = add_subcmd("info", "Show information about available counters.")
    subcmd_info.add_argument("counter", help="The counter to show info for.")
    cmds.append(cmd_counter)

    CORE.command_register(MOD_ID, *cmds)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == "modules":
        await load_counters()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == "modules" and key.startswith("Counter.Instance"):
        counter_name, attr = key.split(".", maxsplit=3)[2:]
        counter = counters[counter_name]
        logger.info(f"Setting Counter '{counter_name}' attribute {attr} to {new} (was {old}).")
        setattr(counter, attr, new)


async def load_counters() -> int:
    """Load created `Counter`s from configuration and the database.

    Returns the number of loaded `Counter`s.
    """
    loaded = 0
    for name, instance in CFG["Instance"].items():
        args = {
            "name": name,
            "description": instance.get("Description", "No description"),
            "announcement": instance.get("AnnounceString"),
            "enabled": instance.get("Enabled", True),
            "announce": instance.get("Announce", True),
            "match_case": instance.get("MatchCase", False),
            "triggers": instance.get("Triggers", []),
            "restrictions": instance.get("RestrictedTo", []),
            "blacklist": instance.get("Blacklist", []),
        }
        counter = Counter(**args)
        if not await counter.fetch_data():
            logger.info(f"Creating new Counter '{name}'")
            await add_counter(counter)
        counters[name] = counter
        loaded += 1
    return loaded


async def add_counter(counter):
    """Add a new counter to the database."""
    async with DB.cursor() as cur:
        parameters = tuple(
            getattr(counter, attr)
            for attr in (
                "name",
                "count",
                "created_at",
                "last_triggered",
                "last_user",
                "last_channel",
            )
        )
        await cur.execute("INSERT INTO counter VALUES(?, ?, ?, ?, ?, ?)", parameters)
        await DB.commit()


def or_join(iterable: Iterable, separator: str = ", ") -> str:
    """Pretty print a list of names.

    Similar to `str.join`, but the final element is prefixed with "or ".
    If `iterable` contains only two elements, no separator will be included,
    only the "or ".

    Parameters
    ----------
    iterable : Iterable
        An iterable of elements to join.
    separator : str, optional
        A string to separate each element of `iterable`. Defaults to ", ".

    Returns
    -------
    str
        A string of joined elements similar to `str.join`.
    """
    length = len(iterable)
    if not length:
        return ""
    if length == 1:
        return str(iterable[0])
    if length == 2:
        return f"{iterable[0]} or {iterable[1]}"
    return separator.join(iterable[:-1]) + f" or {iterable[-1]}"


async def announce(ctx, destination, counter: Counter, /, **kwargs):
    """Announce the current count of a `Counter` somewhere."""
    announcement = counter.get_announcement(**kwargs)
    await ctx.module_message(announcement, destination)
    if (msg := SPECIAL_NUMBERS.get(counter.count)) is not None:
        await asyncio.sleep(1)
        action = msg.startswith("*") and msg.endswith("*")
        await ctx.module_message(msg, destination, action)


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    sender = message.source
    # TODO: Proper 'DirectMessage' class
    try:
        channel = message.destination.name
    except AttributeError:
        channel = sender.name
    if not CFG["Enabled"] or ctx.user == sender:
        return

    for counter in counters.values():
        if not counter.enabled:
            continue
        if counter.can_trigger(sender.name) and counter.check(message.clean_content):
            await counter.increment(participant=sender.name, channel=channel)
            if counter.should_announce():
                await announce(ctx, message.destination, counter, user=sender.name)


async def module_command_count(ctx, parsed):
    """Handle `count` command."""
    sender = parsed.invoker
    try:
        counter = counters[parsed.args["counter"]]
    except KeyError:
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdErrorType.NoResults)
        return
    # TODO: Proper 'DirectMessage' class
    try:
        channel = parsed.source.name
    except AttributeError:
        channel = parsed.invoker.name
    await counter.increment(parsed.args["count"], participant=sender.name, channel=channel)
    if parsed.args["quiet"]:
        await ctx.module_message("Okay, done.", parsed.source)
    else:
        await announce(ctx, parsed.source, counter, user=sender.name)


async def module_command_counter(ctx, parsed):
    """Handle `counter` command."""
    subcmd = parsed.subcmd
    if subcmd == "announce":
        try:
            counter = counters[parsed.args["counter"]]
        except KeyError:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdErrorType.NoResults)
            return
        response = counter.get_announcement(user=counter.last_user.name)
    elif subcmd == "list":
        lines, found, not_found = [], [], []
        if parsed.args["counter"]:
            for counter in parsed.args["counter"]:
                if counter in counters:
                    found.append(counter)
                else:
                    not_found.append(counter)
        else:
            found = counters.keys()
        if found:
            lines.append("**Available Counters**")
            if parsed.args["full"]:
                for name in found:
                    counter = counters[name]
                    lines.append(f"[**{name}**] ({counter.count}) - {counter.description}")
            else:
                lines.append(", ".join(found))
        if not_found:
            lines.append("\n**No such Counter**: " + ", ".join(not_found))
        response = "\n".join(lines)
    elif subcmd == "info":
        try:
            counter = counters[parsed.args["counter"]]
        except KeyError:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdErrorType.NoResults)
            return
        last_user = counter.last_user.name if counter.last_user is not None else "N/A"
        last_triggered = str(counter.last_triggered) if counter.last_triggered is not None else "Never"
        response = (
            f"Information for Counter [**{counter.name}**]\n"
            f"**Current Count**: {counter.count}\n"
            f"**Description**: {counter.description}\n"
            f"**Created**: {counter.created_at}\n"
            f"**Last Triggered**: {last_triggered} by {last_user}\n"
        )
    await ctx.module_message(response, parsed.source)
