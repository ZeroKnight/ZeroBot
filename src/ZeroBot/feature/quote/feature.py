"""Quote

Archive, search, and recite humorous, inspiring, or out-of-context quotes.
Includes a variety of commands for searching and managing quotes, as well as
reporting quote database statistics.
"""

from __future__ import annotations

import itertools
import logging
import re
import sqlite3
import textwrap
from collections import deque
from datetime import datetime
from functools import partial
from importlib import resources
from typing import Any

from ZeroBot.common.enums import CmdResult
from ZeroBot.common.util import parse_iso_format
from ZeroBot.context import Message
from ZeroBot.database import Participant
from ZeroBot.database import get_participant as getpart
from ZeroBot.util import flatten

from .classes import Quote, QuoteLine, QuoteStyle
from .commands import define_commands

MODULE_NAME = "Quote"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.4"
MODULE_LICENSE = "MIT"
MODULE_DESC = "Archive, search, and recite humorous, inspiring, or (especially) out-of-context quotes."

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit(".", 2)[-2]
get_participant = None

logger = logging.getLogger("ZeroBot.Feature.Quote")

MULTILINE_SEP = re.compile(r"(?:\n|\\n)\s*")
MULTILINE_AUTHOR = re.compile(r"(?:<(.+)>|(.+):)")
AUTHOR_PLACEHOLDER = re.compile(r"\\(\d+)")
WILDCARD_MAP = {
    ord("*"): "%",
    ord("?"): "_",
    ord("%"): "\\%",
    ord("_"): "\\_",
    ord("\\"): r"\\",
}

recent_quotes = {}
last_messages = {}


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB, recent_quotes, get_participant
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config("modules")[MODULE_NAME]
    recent_quotes["global"] = deque(maxlen=CFG.get("Cooldown.Count", 0))
    # TODO: per-author cooldowns

    def cooldown() -> int:
        if CFG.get("Cooldown.PerAuthor", False):
            return CFG.get("Cooldown.CountPerAuthor", 0)
        return CFG.get("Cooldown.Count", 0)

    DB = await core.database_connect(MOD_ID)
    await DB.create_function("cooldown", 0, cooldown)
    await DB.executescript(resources.files("ZeroBot").joinpath("sql/schema/quote.sql").read_text())
    get_participant = partial(getpart, DB)

    CORE.command_register(MOD_ID, *define_commands())


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


def _resize_quote_deque():
    new_len = CFG.get("Cooldown.Count", 30)
    if new_len == recent_quotes["global"].maxlen:
        return
    recent_quotes["global"] = deque(recent_quotes["global"].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == "modules":
        _resize_quote_deque()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == "modules" and key == "Quote.Cooldown.Count":
        _resize_quote_deque()


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    # Don't keep track of ZeroBot's lines
    if ctx.user == message.source:
        return
    if not message.content or message.content.isspace():
        return
    server = "__DM__" if not message.server else message.server.name
    channel = message.destination
    last_messages.setdefault(ctx.protocol, {}).setdefault(server, {})[channel.name] = message


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    # TODO: quote on join


async def module_command_quote(ctx, parsed):
    """Handle `quote` command."""
    if parsed.subcmd:
        await globals()[f"quote_{parsed.subcmd}"](ctx, parsed)
    else:
        # Recite a random quote
        quote = await get_random_quote()
        if quote is None:
            await ctx.reply_command_result("Uh, there are no quotes...", parsed, CmdResult.NotFound)
            return
        await ctx.module_message(quote, parsed.msg.destination)


async def execute_opt_case(cursor, sql: str, params: tuple | None = None, *, case_sensitive: bool = False):
    """Execute a query with optional case-sensitive ``LIKE`` operator."""
    if case_sensitive:
        await cursor.execute("PRAGMA case_sensitive_like = 1")
    await cursor.execute(sql, params)
    if case_sensitive:
        await cursor.execute("PRAGMA case_sensitive_like = 0")


async def fetch_quote(
    sql: str,
    params: tuple | None = None,
    *,
    cooldown: bool = True,
    case_sensitive: bool = False,
) -> Quote | None:
    """Fetch a quote from the database, respecting cooldowns.

    The parameters are the same as in an `aiosqlite.Cursor.execute` call, which
    this coroutine wraps. All quote fetches should use this coroutine as
    a base, as it handles quote cooldowns and other necessary state.
    """
    if cooldown and not all(token in sql for token in ("LIMIT", "cooldown()")):
        raise ValueError("Query must include a LIMIT with 'cooldown()'")
    # TODO: per-author cooldowns
    async with DB.cursor() as cur:
        await execute_opt_case(cur, sql, params, case_sensitive=case_sensitive)
        row = await cur.fetchone()
        if cooldown:
            while row and row["quote_id"] in recent_quotes["global"]:
                row = await cur.fetchone()
    if row is not None:
        quote = await Quote.from_row(DB, row)
        if cooldown:
            recent_quotes["global"].append(row["quote_id"])
    else:
        quote = None
    return quote


async def get_random_quote() -> Quote | None:
    """Fetch a random quote from the database."""
    return await fetch_quote(
        f"""
        SELECT * FROM {Quote.table_name}
        WHERE hidden = 0
        ORDER BY RANDOM() LIMIT cooldown() + 1
    """
    )


async def get_quote_by_id(quote_id: int) -> Quote | None:
    """Fetch the quote with the given ID from the database.

    If `quote_id` is negative, the *nth* most recent quote is returned.
    """
    if quote_id < 0:
        async with DB.cursor() as cur:
            await cur.execute(f"SELECT * FROM {Quote.table_name} ORDER BY quote_id DESC")
            row = (await cur.fetchall())[-quote_id - 1]
        if row is not None:
            quote = await Quote.from_row(DB, row)
        else:
            quote = None
    else:
        quote = await fetch_quote(
            f"SELECT * FROM {Quote.table_name} WHERE quote_id = ?",
            (quote_id,),
            cooldown=False,
        )
    return quote


def read_datestamp(datestamp: str) -> datetime | None:
    """Try to create a `datetime` object from `datestamp`.

    Expects an ISO 8601 formatted date/time string or a UNIX timestamp. Returns
    `None` if the string could not be converted.
    """
    try:
        date = parse_iso_format(datestamp)
    except ValueError:
        try:
            date = datetime.utcfromtimestamp(int(datestamp))
        except ValueError:
            return None
    return date


def handle_action_line(line: str, msg: Message) -> tuple[bool, str]:
    """Handles action checking and line modification for ``quote add``.

    Returns a 2-tuple of (is_action, strip_action).
    """
    action = False
    if match := re.match(r"\\a *", line):
        action = True
        line = line[match.end() :]
    elif msg.is_action_str(line):
        action = True
        line = msg.strip_action_str(line)
    return action, line


def prepare_pattern(pattern: str, *, case_sensitive: bool = False, basic: bool = False) -> str:
    """Prepare a pattern from a command for use in a query."""
    if basic:
        pattern = (pattern or "*").translate(WILDCARD_MAP)
        pattern = f"%{pattern}%" if pattern != "%" else "%"
    else:
        # The `m` flag is included because of the use of
        # `group_concat(name, char(10))` in queries needing to match aliases.
        re_flags = "m" if case_sensitive else "mi"
        pattern = f"(?{re_flags}:{pattern or '.*'})"
    return pattern


def generate_table(rows: list[sqlite3.Row], target: tuple[int, Any] | None = None) -> list[str]:
    """Generate a Markdown-like table out of the given rows.

    The optional `target` parameter expects a tuple of the form
    ``(col#, value)``. If the given column number in any row has a value that
    matches `value`, the first column in that row will include a `*` to mark
    the column of interest.
    """
    # Generate table
    # TODO: factor out into function
    lines = []
    headers = rows[0].keys()
    widths = [[len(str(col)) for col in row] for row in rows]
    min_widths = [max(x) for x in zip(*widths, strict=True)]
    line, rule = "", ""
    for i, col in enumerate(headers):
        # Create header
        line += f"| {col:^{min_widths[i]}} "
        min_width = max(len(headers[i]), min_widths[i])
        rule += f"|{'-' * (min_width + 2)}"
    lines.append(f"{line}|")
    lines.append(f"{rule}|")
    for row in rows:
        line = ""
        is_target = target is not None and row[target[0]] == target[1]
        for i, col in enumerate(row):
            min_width = max(len(headers[i]), min_widths[i])
            if i == 0 and is_target:
                col = f"* {col}"
                line += f"| {col:>{min_width}} "
            else:
                line += f"| {col:{min_width}} "
        lines.append(f"{line}|")
    return lines


async def quote_exists(content: str | list[str]) -> bool:
    """Check if the given quote exists."""
    if isinstance(content, list):
        content = "\n".join(content)
    async with DB.cursor() as cur:
        await cur.execute(
            f"""
            SELECT EXISTS (
                SELECT group_concat(line, char(10)) AS "body"
                FROM {QuoteLine.table_name}
                GROUP BY quote_id
                HAVING body = ?
            )
        """,
            (content,),
        )
        return bool((await cur.fetchone())[0])


# TODO: This interface kinda sucks; redesign it.
# TODO: Support non-MultiLine protocols
async def quote_add(ctx, parsed):
    """Add a quote to the database."""
    submitter = await get_participant(parsed.args["submitter"] or parsed.invoker.name)
    style = getattr(QuoteStyle, parsed.args["style"].title())
    if parsed.args["date"]:
        if (date := read_datestamp(parsed.args["date"])) is None:
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
            return
    else:
        date = datetime.utcnow()
    author = await get_participant(parsed.args["author"])
    body = " ".join(parsed.args["body"])
    quote = Quote(DB, None, submitter, date=date, style=style)

    if parsed.args["multi"]:
        extra = parsed.args["extra_authors"] or []
        authors = [author] + [await get_participant(a) for a in extra]
        lines = MULTILINE_SEP.split(body)
        first = True
        for line in lines:
            line = line.strip()
            if first:
                # Handle first line specially
                line_author, line_body = author, line
                first = False
            else:
                # Successive lines; extract line authors
                line_author, line_body = line.split(maxsplit=1)
                if match := AUTHOR_PLACEHOLDER.match(line_author):
                    line_author = authors[int(match[1]) - 1]
                    if style is QuoteStyle.Unstyled:
                        line_body = AUTHOR_PLACEHOLDER.sub(line_author, line)
                else:
                    if match := MULTILINE_AUTHOR.match(line_author):
                        line_author = match[1] or match[2]
                    line_author = next(a for a in authors if a.name == line_author)
                    if style is QuoteStyle.Unstyled:
                        line_body = line
            action, line_body = handle_action_line(line_body, parsed.msg)
            await quote.add_line(line_body, line_author, action)
    else:
        action, body = handle_action_line(body, parsed.msg)
        await quote.add_line(body, author, action)

    await quote.save()
    await ctx.module_message(f"Okay, adding: {quote}", parsed.msg.destination)


async def quote_del(ctx, parsed):
    """Remove one or more quotes from the database."""
    # TODO: make regex deletion a two-step command; upon invoking, return how
    # many quotes would be deleted and a list of relevant ids (up to X amount)
    # require a !quote confirm delete or something like that to actually go
    # through with it.
    # TODO: "preview" or "confirm" option? leverage `wait_for` or reactions to
    # confirm/cancel adding/removing a quote before actually doing it, and give
    # a preview of what would be added/removed

    if parsed.invoker != ctx.owner:
        await ctx.reply_command_result(
            f"Sorry, currently only {ctx.owner.name} can do that.", parsed, CmdResult.NoPermission
        )
        return
    body = " ".join(parsed.args["quote"])
    if parsed.args["id"]:
        quote = await get_quote_by_id(int(body))
    else:
        lines = MULTILINE_SEP.split(body)
        quote = await fetch_quote(
            f"""
            WITH target AS (
                SELECT quote_id, group_concat(line, char(10)) AS "body"
                FROM {QuoteLine.table_name}
                GROUP BY quote_id
                HAVING body = ?
            )
            SELECT * FROM {Quote.table_name}
            WHERE quote_id = (SELECT quote_id FROM target)
        """,
            ("\n".join(lines),),
            cooldown=False,
        )
    if quote is None:
        criteria = "ID" if parsed.args["id"] else "content"
        await ctx.reply_command_result(f"Couldn't find a quote with that {criteria}.", parsed, CmdResult.NotFound)
        return
    await quote.delete()
    await ctx.module_message(f"Okay, removed quote: {quote}", parsed.source)


async def quote_recent(ctx, parsed):
    """Fetch the most recently added quotes."""
    pattern = parsed.args["pattern"]
    case_sensitive = parsed.args["case_sensitive"]
    basic = parsed.args["basic"]
    count = min(parsed.args["count"], CFG["MaxCount"])
    if count < 1:
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return
    if pattern:
        target = "submitters" if parsed.args["submitter"] else "authors"
        search_method = "LIKE" if basic else "REGEXP"
        where = f"WHERE {target}.name_list {search_method} ?"
    else:
        where = ""
    sql = f"""
        WITH participant_names AS (
            SELECT participant_id,
                   group_concat(name, char(10)) AS "name_list"
            FROM participants_all_names
            GROUP BY participant_id
        )
        SELECT quote_id, submitter, submission_date, style
        FROM (
            SELECT *, row_number() OVER (PARTITION BY quote_id) AS "seqnum"
            FROM {Quote.table_name}
            JOIN {QuoteLine.table_name} USING (quote_id)
            JOIN participant_names AS "authors" USING (participant_id)
            JOIN participant_names AS "submitters"
                ON submitter = submitters.participant_id
            {where}
        )
        WHERE seqnum = 1  -- Don't include multiple lines from the same quote
        ORDER BY submission_date DESC LIMIT ?
    """
    if pattern:
        pattern = prepare_pattern(pattern, basic=basic, case_sensitive=case_sensitive)
        query = (sql, (pattern, count))
    else:
        query = (sql, (count,))
    async with DB.cursor() as cur:
        await execute_opt_case(cur, *query, case_sensitive=case_sensitive)
        quotes = [await Quote.from_row(DB, row) for row in await cur.fetchall()]
    if count > 1:
        wrapper = textwrap.TextWrapper(width=160, max_lines=1, placeholder=" **[...]**")
        results = [f"**[{n}]** {wrapper.fill(str(quote))}" for n, quote in enumerate(quotes, 1)]
    else:
        results = [str(quotes[0])]
    await ctx.reply_command_result(results, parsed)


async def quote_search(ctx, parsed):
    """Fetch a quote from the database matching search criteria."""
    if not any(parsed.args[a] for a in ("pattern", "id", "author", "submitter")):
        # Technically equivalent to `!quote` but less efficient
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return
    basic = parsed.args["basic"]
    case_sensitive = parsed.args["case_sensitive"]
    if parsed.args["id"]:
        result = await get_quote_by_id(parsed.args["id"])
    else:
        selection = "COUNT(*)" if parsed.args["count"] else "quote_id, submitter, submission_date, style"
        sql = f"""
            WITH participant_names AS (
                SELECT participant_id,
                       group_concat(name, char(10)) AS "name_list"
                FROM participants_all_names
                GROUP BY participant_id
            )
            SELECT {selection}
            FROM (
                SELECT *, row_number() OVER (PARTITION BY quote_id) AS "seqnum"
                FROM {Quote.table_name}
                JOIN {QuoteLine.table_name} USING (quote_id)
                JOIN participant_names AS "authors" USING (participant_id)
                JOIN participant_names AS "submitters"
                    ON submitter = submitters.participant_id
        """
        pattern = prepare_pattern(" ".join(parsed.args["pattern"] or []), basic=basic, case_sensitive=case_sensitive)
        author_pat = prepare_pattern(parsed.args["author"], basic=basic, case_sensitive=case_sensitive)
        submitter_pat = prepare_pattern(parsed.args["submitter"], basic=basic, case_sensitive=case_sensitive)
        search_method = "LIKE" if basic else "REGEXP"
        sql += f"""
                WHERE hidden = 0 AND
                      line {search_method} ? AND
                      authors.name_list {search_method} ? AND
                      submitters.name_list {search_method} ?
            )
            WHERE seqnum = 1  -- Don't include multiple lines from the same quote
            ORDER BY RANDOM() LIMIT cooldown() + 1
        """
        query = (sql, (pattern, author_pat, submitter_pat))
        if parsed.args["count"]:
            async with DB.cursor() as cur:
                await execute_opt_case(cur, *query, case_sensitive=case_sensitive)
                result = (await cur.fetchone())[0]
        else:
            result = await fetch_quote(*query, case_sensitive=case_sensitive)
    criteria = "ID" if parsed.args["id"] else "pattern"
    if not result:
        await ctx.reply_command_result(f"Couldn't find any quotes matching that {criteria}", parsed, CmdResult.NotFound)
    elif isinstance(result, int):
        await ctx.reply_command_result(f"I found {result} quotes matching that {criteria}", parsed)
    else:
        await ctx.module_message(result, parsed.msg.destination)


async def quote_stats(ctx, parsed):
    """Query various statistics about the quote database."""
    count = min(parsed.args["count"], CFG["MaxCount"])
    if count < 1:
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return
    if parsed.args["leaderboard"]:
        await quote_stats_leaderboard(ctx, parsed, count)
        return
    if parsed.args["global"] and parsed.args["user"]:
        # These are mutually exclusive arguments
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return

    selection = [parsed.args[x] for x in ("quotes", "submissions", "self_submissions", "per_year", "percent")]
    if selection[:-1] == [False] * 4:
        # No criteria given, use defaults
        selection = [True] * 5

    # This logic is a bit ugly, but I don't have a better idea at the moment.
    percents = []
    criteria = {
        "q": "Number of Quotes",
        "u": "Number of Submitters",
        "e": "Self-Submissions",
        "y": ["Quotes this Year", "Avg. Yearly Quotes"],
        "p": percents,
    }
    percent_names = ["Self-Sub %"]
    if not parsed.args["global"]:
        criteria["u"] = "Number of Submissions"
        criteria["y"] += ["Submissions this Year", "Avg. Yearly Subs"]
        percent_names = ["Quote %", "Submission %", "Self-Sub %"]
        if selection[-2]:  # Show year stats
            criteria["y"] = list(itertools.compress(criteria["y"], flatten([[selection[0]] * 2, [selection[1]] * 2])))
    if selection[-1]:  # Show percentages
        percents.extend(itertools.compress(percent_names, selection[:-2]))

    chosen = flatten(itertools.compress(criteria.values(), selection))
    chosen = ", ".join(f'"{x}"' for x in chosen)

    if parsed.args["global"]:
        async with DB.cursor() as cur:
            await cur.execute(f"SELECT {chosen} FROM quote_stats_global")
            row = await cur.fetchone()
        result = ["**Database Stats**"]
        zipped = zip(row.keys(), row, strict=True)
    else:
        pattern = prepare_pattern(parsed.args["user"] or parsed.invoker.name)
        async with DB.cursor() as cur:
            await cur.execute(
                f"""
                WITH participant_names AS (
                    SELECT participant_id,
                           group_concat(name, char(10)) AS "name_list"
                    FROM participants_all_names
                    GROUP BY participant_id
                )
                SELECT stats.Name, {chosen}
                FROM quote_stats_user AS "stats"
                JOIN {Participant.table_name} USING (name)
                JOIN participant_names AS "pn" USING (participant_id)
                WHERE pn.name_list REGEXP ?
            """,
                (pattern,),
            )
            row = await cur.fetchone()
        result = [f"**Stats for {row['Name']}**"]
        zipped = zip(row.keys()[1:], row[1:], strict=True)
    result.append("```")
    pairs = list(zip(*[iter(zipped)] * 2, strict=True))
    max_n, max_v = [], []
    for i in range(2):
        max_n.append(max(len(str(x[i][0])) for x in pairs) + 1)
        max_v.append(max(len(str(x[i][1])) for x in pairs))
    for stat1, stat2 in pairs:
        line = (
            f"{stat1[0] + ':':<{max_n[0]}} {stat1[1]:<{max_v[0]}}   {stat2[0] + ':':<{max_n[1]}} {stat2[1]:<{max_v[1]}}"
        )
        result.append(line)
    result.append("```")
    await ctx.module_message("\n".join(result), parsed.msg.destination)


async def quote_stats_leaderboard(ctx, parsed, count):
    """Leaderboard statistics."""
    percents = []
    criteria = {"q": "Number of Quotes", "u": "Number of Submissions", "p": percents}
    selection = [parsed.args[x] for x in ("quotes", "submissions", "percent")]
    if selection[:2] == [False] * 2:
        # No criteria given, use defaults
        selection = [True, True, selection[-1]]
        if parsed.args["sort"] is None:
            sort = ["q", "u"]

    if selection[2]:  # Show percentages
        percent_names = ["Quote %", "Submission %"]
        percents.extend(itertools.compress(percent_names, selection[:2]))

    chosen = list(flatten(itertools.compress(criteria.values(), selection)))
    if parsed.args["sort"] is not None:
        sort = parsed.args["sort"].split(",")
        try:
            # pseudo-criteria; the actual sort is based on the chosen criteria
            sort.remove("p")
        except ValueError:
            pass
        if not all(key in criteria for key in sort):
            await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
            return
        chosen_sort = ", ".join(f'"{criteria[x]}" DESC' for x in sort)
    else:
        # No sort specified, so mirror the chosen criteria
        chosen_sort = ", ".join(f'"{x}" DESC' for x in chosen)
    chosen = ", ".join(f'"{x}"' for x in chosen)

    if parsed.args["global"]:
        # Show `count` top users
        async with DB.cursor() as cur:
            await cur.execute(
                f"""
                WITH ranked AS (
                    SELECT *, row_number() OVER (
                        ORDER BY {chosen_sort}
                    ) AS "Rank"
                    FROM quote_leaderboard
                )
                SELECT Rank, Name, {chosen}
                FROM ranked
                ORDER BY {chosen_sort}
                LIMIT ?
            """,
                (count,),
            )
            rows = await cur.fetchall()
        table = "\n".join(generate_table(rows))
    else:
        # Show `count` users around target user
        pattern = prepare_pattern(parsed.args["user"] or parsed.invoker.name)
        async with DB.cursor() as cur:
            await cur.execute(
                f"""
                WITH participant_names AS (
                    SELECT participant_id,
                           group_concat(name, char(10)) AS "name_list"
                    FROM participants_all_names
                    GROUP BY participant_id
                ),
                pivot AS (
                    SELECT *, count() FILTER (WHERE name_list REGEXP ?1) OVER (
                        ORDER BY {chosen_sort}
                        ROWS BETWEEN ?2 PRECEDING AND ?2 FOLLOWING
                    ) AS "included",
                    row_number() OVER (
                        ORDER BY {chosen_sort}
                    ) AS "Rank"
                    FROM quote_leaderboard
                    JOIN {Participant.table_name} USING (name)
                    JOIN participant_names USING (participant_id)
                )
                SELECT Rank, Name, {chosen}
                FROM pivot
                WHERE included = 1
                ORDER BY {chosen_sort}
            """,
                (pattern, parsed.args["count"]),
            )
            rows = await cur.fetchall()
        for row in rows:
            if re.match(pattern, row["Name"]):
                name = row["Name"]
                break
        table = "\n".join(generate_table(rows, (1, name)))
    await ctx.module_message(f"```\n{table}\n```", parsed.msg.destination)


async def quote_quick(ctx, parsed):
    """Shortcuts for adding a quote to the database."""
    lines = []
    cached = False
    if (user := parsed.args["user"]) is not None:
        user = user.lstrip("@")
    submitter = await get_participant(parsed.args["submitter"] or parsed.invoker.name)
    style = getattr(QuoteStyle, parsed.args["style"].title())
    if parsed.args["date"] and (date := read_datestamp(parsed.args["date"])) is None:
        await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadSyntax)
        return

    # Try cache first
    if not parsed.args["id"] and not user:
        server = parsed.msg.server.name or "__DM__"
        channel = parsed.msg.destination.name
        try:
            msg = last_messages[ctx.protocol][server][channel]
        except KeyError:
            pass
        else:
            if msg is not None:
                cached = True

    if not cached:
        channels = [parsed.msg.destination]  # Search origin channel first
        channels.extend(c for c in (await parsed.server.channels()) if c != channels[0])
        if parsed.args["id"]:
            for channel in channels:
                if (msg := await channel.get_message(parsed.args["id"])) is not None:
                    break
            else:  # No message found
                await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadTarget)
                return
        elif user:
            # Last message in channel by user
            if (user := parsed.msg.server.get_user(user)) is None:
                # Don't bother checking history if given a bad username
                await CORE.module_send_event("invalid_command", ctx, parsed.msg, CmdResult.BadTarget)
                return
            limit = 100
            msg = await anext(await channels[0].history(limit=limit, author=user))
            if not msg:
                await ctx.reply_command_result(
                    f"Couldn't find a message from that user in the last {limit} messages.", parsed, CmdResult.NotFound
                )
                return
        else:
            # Last message in channel
            msg = [channel async for channel in channels[0].history(limit=2)][-1]

    author = await get_participant(msg.author.name)
    if not parsed.args["date"]:
        date = msg.time
    action, body = handle_action_line(msg.clean_content, msg)
    lines.append((body, author, action))

    nprev = parsed.args["num_previous"]
    async for prev_msg in msg.destination.history(limit=nprev, before=msg):
        author = await get_participant(prev_msg.author.name)
        action, body = handle_action_line(prev_msg.clean_content, prev_msg)
        lines.append((body, author, action))

    quote = Quote(DB, None, submitter, date=date, style=style)
    for line in reversed(lines):
        await quote.add_line(*line)
    await quote.save()
    await ctx.module_message(f"Okay, adding: {quote}", parsed.msg.destination)
