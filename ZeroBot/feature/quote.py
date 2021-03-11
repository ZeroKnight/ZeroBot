"""Quote

Archive, search, and recite humorous, inspiring, or out-of-context quotes.
Includes a variety of commands for searching and managing quotes, as well as
reporting quote database statistics.
"""

import itertools
import re
import sqlite3
import textwrap
from collections import deque
from datetime import datetime
from enum import IntEnum, unique
from typing import Any, List, Optional, Tuple, Union

from ZeroBot.common import CommandParser
from ZeroBot.common.abc import Message
from ZeroBot.database import Connection, DBModel, DBUser, Participant
from ZeroBot.protocol.discord.classes import DiscordMessage  # TEMP
from ZeroBot.util import flatten

MODULE_NAME = 'Quote'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.4'
MODULE_LICENSE = 'MIT'
MODULE_DESC = ('Archive, search, and recite humorous, inspiring, or '
               '(especially) out-of-context quotes.')

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

MULTILINE_SEP = re.compile(r'(?:\n|\\n)\s*')
MULTILINE_AUTHOR = re.compile(r'(?:<(.+)>|(.+):)')
AUTHOR_PLACEHOLDER = re.compile(r'\\(\d+)')
WILDCARD_MAP = {
    ord('*'): '%',
    ord('?'): '_',
    ord('%'): '\\%',
    ord('_'): '\\_',
    ord('\\'): r'\\'
}

recent_quotes = {}
last_messages = {}


@unique
class QuoteStyle(IntEnum):
    Standard = 1
    Epigraph = 2
    Unstyled = 3


class QuoteLine(DBModel):
    """A single—possibly the only—line of a quote.

    `QuoteLine` objects make up the body of a given quote. Each line may have
    its own author and may or may not be an action.

    Parameters
    - ---------
    quote_id: int
        The ID of the `Quote` that this line belongs to.
    body: str
        The quoted text.
    author: Participant
        The entity being quoted for this line.
    line_num: int, optional
        The position of this line in the `Quote`. For single-line quotes this
        is always `1`, and is also the default.
    author_num: int, optional
        The * Nth * unique author to be part of the associated `Quote`. For
        single-line quotes this is always `1`, and is also the default.
    action: bool, optional
        Whether or not the body should be interpreted as an "action" rather
        than something written or spoken. Defaults to `False`.
    """

    table_name = 'quote_lines'

    def __init__(self, conn: Connection, quote_id: int, body: str,
                 author: Participant, *, quote: 'Quote' = None,
                 line_num: int = 1, author_num: int = 1, action: bool = False):
        super().__init__(conn)
        self.quote_id = quote_id
        self.body = body
        self.author = author
        self.line_num = line_num
        self.author_num = author_num
        self.action = action
        if quote is not None and quote.id != self.quote_id:
            raise ValueError(
                'The given quote.id does not match quote_id: '
                f'{quote.id=} {self.quote_id}')
        self.quote = quote

    def __repr__(self):
        attrs = ['quote_id', 'line_num', 'body', 'author', 'author_num',
                 'action']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        if self.action:
            return f'* {self.author} {self.body}'
        return f'<{self.author}> {self.body}'

    @classmethod
    async def from_row(cls, conn: Connection, row: sqlite3.Row) -> 'QuoteLine':
        """Construct a `QuoteLine` from a database row.

        Parameters
        -----------
        conn : Connection
            The database connection to use.
        row: sqlite3.Row
            A row returned from the database.
        """
        attrs = {
            name: row[name] for name in
            ('quote_id', 'line_num', 'author_num', 'action')
        }
        author = await Participant.from_id(conn, row['participant_id'])
        return cls(conn, body=row['line'], author=author, **attrs)


class Quote(DBModel):
    """A ZeroBot quote.

    Parameters
    ----------
    quote_id : int or None
        The ID of the quote.
    submitter : Participant
        The person that submitted this quote.
    date : datetime, optional
        The date and time that the quoted content occurred. Defaults to the
        current date/time.
    style : QuoteStyle, optional
        How the quote should be formatted when displayed. Defaults to
        `QuoteStyle.Standard`.

    Attributes
    ----------
    id
    """

    table_name = 'quote'

    def __init__(self, conn: Connection, quote_id: Optional[int],
                 submitter: Participant, *, date: datetime = datetime.utcnow(),
                 style: QuoteStyle = QuoteStyle.Standard):
        super().__init__(conn)
        self.id = quote_id
        self.submitter = submitter
        self.date = date
        self.style = style
        self.lines = []
        self.authors = []

    def __repr__(self):
        attrs = ['id', 'submitter', 'date', 'style', 'lines']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        if self.style is QuoteStyle.Standard:
            return '\n'.join(str(line) for line in self.lines)
        if self.style is QuoteStyle.Epigraph:
            formatted = '\n'.join(line.body for line in self.lines)
            return f'"{formatted}" —{self.lines[0].author.name}'
        if self.style is QuoteStyle.Unstyled:
            return '\n'.join(line.body for line in self.lines)
        raise ValueError(f'Invalid QuoteStyle: {self.style}')

    @classmethod
    async def from_row(cls, conn: Connection, row: sqlite3.Row) -> 'Quote':
        """Construct a `Quote` from a database row.

        Also fetches the associated `QuoteLine`s.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        """
        submitter = await Participant.from_id(conn, row['submitter'])
        quote = cls(
            conn, quote_id=row['quote_id'], submitter=submitter,
            date=row['submission_date'], style=QuoteStyle(row['style'])
        )
        await quote.fetch_lines()
        return quote

    async def fetch_lines(self) -> List[QuoteLine]:
        """Fetch the `QuoteLine`s that make up the quote body.

        Sets `self.lines` to the fetched lines and returns them.
        """
        async with self._connection.cursor() as cur:
            await cur.execute(f"""
                SELECT * FROM {QuoteLine.table_name} WHERE quote_id = ?
                ORDER BY line_num
            """, (self.id,))
            self.lines = [
                await QuoteLine.from_row(self._connection, row)
                for row in await cur.fetchall()
            ]
        return self.lines

    async def fetch_authors(self) -> List[Participant]:
        """Fetch the authors that are part of this quote.

        Authors in the list are ordered by their `author_num` value. Sets
        `self.authors` to the fetched authors and returns them.
        """
        async with self._connection.cursor() as cur:
            await cur.execute(f"""
                SELECT DISTINCT participant_id FROM {QuoteLine.table_name}
                WHERE quote_id = ?
                ORDER BY author_num
            """, (self.id))
            self.authors = [
                await Participant.from_id(self._connection, pid)
                for pid in await cur.fetchall()
            ]
        return self.authors

    def get_author_num(self, author: Participant) -> int:
        """Get the ordinal of the given author for this quote.

        In other words, return `QuoteLine.author_num` for this author. If the
        given author isn't among the quote lines, returns the next available
        ordinal value. If there are no lines yet, returns ``1``.

        Parameters
        ----------
        author : Participant
            The author to return an ordinal for.
        """
        if not self.lines:
            return 1
        seen = set()
        for line in self.lines:
            if line.author == author:
                return line.author_num
            seen.add(line.author_num)
        return max(seen) + 1

    async def add_line(self, body: str, author: Participant,
                       action: bool = False):
        """Add a line to this quote.

        Parameters
        ----------
        body : str
            The contents of the line.
        author : Participant
            The author of the line.
        action : bool, optional
            Whether or not this line is an action. Defaults to `False`.
        """
        line_num = len(self.lines) + 1
        author_num = self.get_author_num(author)
        self.lines.append(
            QuoteLine(self._connection, self.id, body, author, quote=self,
                      line_num=line_num, author_num=author_num, action=action))

    async def save(self):
        """Save this `Quote` to the database."""
        async with self._connection.cursor() as cur:
            await cur.execute('BEGIN TRANSACTION')
            await cur.execute(f"""
                INSERT INTO {self.table_name} VALUES (?, ?, ?, ?)
                ON CONFLICT (quote_id) DO UPDATE SET
                    submitter = excluded.submitter,
                    submission_date = excluded.submission_date,
                    style = excluded.style
            """, (self.id, self.submitter.id, self.date, self.style.value))

            self.id = cur.lastrowid
            for line in self.lines:
                line.quote_id = self.id

            await cur.execute(
                f'DELETE FROM {QuoteLine.table_name} WHERE quote_id = ?',
                (self.id,))
            params = [(self.id, ql.line_num, ql.body, ql.author.id,
                       ql.author_num, ql.action) for ql in self.lines]
            await cur.executemany(
                f'INSERT INTO {QuoteLine.table_name} VALUES(?, ?, ?, ?, ?, ?)',
                params)

            await cur.execute('COMMIT TRANSACTION')

    async def delete(self):
        """Remove this `Quote` from the database."""
        async with self._connection.cursor() as cur:
            await cur.execute(
                f'DELETE FROM {Quote.table_name} WHERE quote_id = ?',
                (self.id,))
        await self._connection.commit()


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB, recent_quotes
    CORE = core

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]
    recent_quotes['global'] = deque(maxlen=CFG.get('Cooldown.Count', 0))
    # TODO: per-author cooldowns

    def cooldown() -> int:
        if CFG.get('Cooldown.PerAuthor', False):
            return CFG.get('Cooldown.CountPerAuthor', 0)
        return CFG.get('Cooldown.Count', 0)

    DB = await core.database_connect(MOD_ID)
    await DB.create_function('cooldown', 0, cooldown)
    await _init_database()

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_database():
    await DB.executescript(f"""
        CREATE TABLE IF NOT EXISTS "{Quote.table_name}" (
            "quote_id"        INTEGER NOT NULL,
            "submitter"       INTEGER NOT NULL DEFAULT 0,
            "submission_date" DATETIME DEFAULT CURRENT_TIMESTAMP,
            "style"           INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY ("quote_id")
            FOREIGN KEY ("submitter")
                REFERENCES "{Participant.table_name}" ("participant_id")
                ON DELETE SET DEFAULT
        );
        CREATE TABLE IF NOT EXISTS "{QuoteLine.table_name}" (
            "quote_id"       INTEGER NOT NULL,
            "line_num"       INTEGER NOT NULL DEFAULT 1,
            "line"           TEXT NOT NULL,
            "participant_id" INTEGER NOT NULL DEFAULT 0,
            "author_num"     INTEGER NOT NULL DEFAULT 1,
            "action"         BOOLEAN NOT NULL DEFAULT 0 CHECK(action IN (0,1)),
            PRIMARY KEY ("quote_id", "line_num"),
            FOREIGN KEY ("quote_id") REFERENCES "quote" ("quote_id")
                ON DELETE CASCADE,
            FOREIGN KEY ("participant_id")
                REFERENCES "{Participant.table_name}" ("participant_id")
                ON DELETE SET DEFAULT
                ON UPDATE CASCADE
        ) WITHOUT ROWID;

        CREATE VIEW IF NOT EXISTS quote_leaderboard AS
        SELECT authors.name AS "Name",
               COUNT(DISTINCT quote_id) AS "Number of Quotes",
                   ifnull(numsubs, 0) AS "Number of Submissions",
                   ROUND(100.0 * COUNT(DISTINCT quote_id) / (SELECT COUNT(*) FROM {Quote.table_name}), 1) || '%' AS "Quote %",
                   ROUND(100.0 * ifnull(numsubs, 0) / (SELECT COUNT(*) FROM {Quote.table_name}), 1) || '%' AS "Submission %"
        FROM {QuoteLine.table_name}
        JOIN {Participant.table_name} AS "authors" USING (participant_id)
        LEFT JOIN (
                SELECT name, COUNT(quote_id) AS "numsubs"
                FROM {Quote.table_name}
                JOIN {Participant.table_name} ON participant_id = submitter
                GROUP BY submitter
        ) AS "submissions"
                ON authors.name = submissions.name
        GROUP BY authors.name;

        CREATE VIEW IF NOT EXISTS quote_merged AS
        SELECT quote_id AS "Quote ID",
               line_num AS "Line #",
                   authors.name AS "Author",
                   line AS "Line",
               submission_date AS "Submission Date",
                   submitters.name AS "Submitter",
                   action AS "Action?",
                   style AS "Style"
        FROM {Quote.table_name}
        JOIN {QuoteLine.table_name} USING (quote_id)
        JOIN {Participant.table_name} AS "submitters" ON submitter = submitters.participant_id
        JOIN {Participant.table_name} AS "authors" USING (participant_id);

        CREATE VIEW IF NOT EXISTS quote_stats_global AS
        WITH self AS (
            SELECT quote_id, 1 AS "selfsub"
            FROM {Quote.table_name}
            JOIN {QuoteLine.table_name} USING (quote_id)
                GROUP BY quote_id
            HAVING submitter = participant_id AND COUNT(line_num) = 1
        )
        SELECT COUNT(DISTINCT top.quote_id) AS "Number of Quotes",
               COUNT(DISTINCT submitter) AS "Number of Submitters",
                   COUNT(selfsub) AS "Self-Submissions",
                   ROUND(100.0 * COUNT(selfsub) / COUNT(DISTINCT top.quote_id), 1) || '%' AS "Self-Sub %",
                   "Quotes in Year" AS "Quotes this Year",
                   "Avg. Yearly Quotes"
        FROM {Quote.table_name} AS "top"
        LEFT JOIN self ON top.quote_id = self.quote_id
        JOIN quote_yearly_quotes ON Year = strftime('%Y', 'now')
        JOIN (
            SELECT AVG("Quotes in Year") AS "Avg. Yearly Quotes"
                FROM quote_yearly_quotes
        ) AS "avg";

        CREATE VIEW IF NOT EXISTS quote_stats_user AS
        WITH submissions AS (
                SELECT name, COUNT(quote_id) AS "numsubs"
                FROM {Quote.table_name}
                JOIN {Participant.table_name} ON participant_id = submitter
                GROUP BY submitter
        ),
        self AS (
            SELECT quote_id, 1 AS "selfsub"
            FROM {Quote.table_name}
            JOIN {QuoteLine.table_name} USING (quote_id)
                GROUP BY quote_id
            HAVING submitter = participant_id AND COUNT(line_num) = 1
        ),
        year_quotes AS (
                SELECT name,
                           COUNT(DISTINCT quote_id) AS "Quotes in Year",
                           strftime('%Y', submission_date) AS "Year"
                FROM {Quote.table_name}
                JOIN {QuoteLine.table_name} USING (quote_id)
                JOIN {Participant.table_name} USING (participant_id)
                GROUP BY name, Year
        ),
        year_subs AS (
                SELECT name,
                           COUNT(DISTINCT quote_id) AS "Submissions in Year",
                           strftime('%Y', submission_date) AS "Year"
                FROM {Quote.table_name}
                JOIN {Participant.table_name} ON submitter = participant_id
                GROUP BY name, Year
        ),
        avg_year_quotes AS (
            SELECT name, AVG("Quotes in Year") AS "Avg. Yearly Quotes"
                FROM year_quotes
                GROUP BY name
        ),
        avg_year_subs AS (
            SELECT name, AVG("Submissions in Year") AS "Avg. Yearly Subs"
                FROM year_subs
                GROUP BY name
        )

        SELECT authors.name AS "Name",
               "Number of Quotes",
                   ROUND(100.0 * COUNT(DISTINCT top.quote_id) / (SELECT COUNT(*) FROM {Quote.table_name}), 1) || '%' AS "Quote %",
               "Number of Submissions",
                   ROUND(100.0 * ifnull(numsubs, 0) / (SELECT COUNT(*) FROM {Quote.table_name}), 1) || '%' AS "Submission %",
                   COUNT(selfsub) AS "Self-Submissions",
                   ROUND(100.0 * COUNT(selfsub) / COUNT(DISTINCT top.quote_id), 1) || '%' AS "Self-Sub %",
                   ifnull("Quotes in Year", 0) AS "Quotes this Year",
                   ifnull("Submissions in Year", 0) AS "Submissions this Year",
                   ROUND(ifnull("Avg. Yearly Quotes", 0), 2) AS "Avg. Yearly Quotes",
                   ROUND(ifnull("Avg. Yearly Subs", 0), 2) AS "Avg. Yearly Subs"
        FROM {Quote.table_name} AS "top"
        JOIN {QuoteLine.table_name} USING (quote_id)
        JOIN {Participant.table_name} AS "authors" USING (participant_id)
        JOIN quote_leaderboard AS "lb" ON authors.name = lb.name
        LEFT JOIN submissions ON authors.name = submissions.name
        LEFT JOIN self ON top.quote_id = self.quote_id
        LEFT JOIN year_quotes ON year_quotes.name = authors.name AND year_quotes.Year = strftime('%Y', 'now')
        LEFT JOIN year_subs ON year_subs.name = authors.name AND year_subs.Year = strftime('%Y', 'now')
        LEFT JOIN avg_year_quotes AS "ayq" ON ayq.name = authors.name
        LEFT JOIN avg_year_subs AS "ays" ON ays.name = authors.name
        GROUP BY authors.name;

        CREATE VIEW IF NOT EXISTS quote_yearly_quotes AS
        SELECT COUNT(quote_id) AS "Quotes in Year",
               strftime('%Y', submission_date) AS "Year"
        FROM {Quote.table_name}
        GROUP BY Year;
    """)


def _register_commands():
    """Create and register our commands."""
    cmds = []
    cmd_quote = CommandParser(
        'quote', 'Recite a random quote or interact with the quote database.')
    add_subcmd = cmd_quote.make_adder(metavar='OPERATION', dest='subcmd',
                                      required=False)

    # Common arguments/options
    adding_options = CommandParser()
    adding_options.add_argument(
        '-d', '--date',
        help=('Submits the quote with the following datestamp instead of the '
              'current (or deduced) date and time. **Time is interpreted as '
              'UTC.** Expects either a Unix timestamp or an ISO 8601 '
              'formatted date string.'))
    adding_options.add_argument(
        '-s', '--style', choices=[style.name.lower() for style in QuoteStyle],
        type=str.lower, default='standard',
        help=('Specify the quote style. The default, **standard** styles the '
              'quote like a typical IRC client message, e.g. `<Foo> hello`. '
              '**epigraph** styles the quote as in writing, e.g. '
              '`"Hello." ―Foo`. **unstyled** applies no formatting and is '
              'displayed exactly as entered.'))
    adding_options.add_argument(
        '-u', '--submitter',
        help='Submit a quote on behalf of someone else.')
    pattern_options = CommandParser()
    pattern_options.add_argument(
        '-b', '--basic', action='store_true',
        help=('Patterns are interpreted as simple wildcard strings rather '
              'than regular expressions. `*`, `?`, and `[...]` are '
              'supported.'))
    pattern_options.add_argument(
        '-c', '--case-sensitive', action='store_true',
        help='Forces search pattern to be case sensitive.')

    subcmd_add = add_subcmd('add', 'Submit a new quote', aliases=['new'],
                            parents=[adding_options])
    subcmd_add.add_argument(
        'author',
        help=('The author of the quote, i.e. the entity being quoted. Must be '
              'wrapped in quotation marks if it contains spaces.'))
    subcmd_add.add_argument(
        'body', nargs='+', help='The contents of the quote')
    subcmd_add.add_argument(
        '-a', '--author', action='append', dest='extra_authors',
        help='Specifies additional authors for a multi-line quote')
    subcmd_add.add_argument(
        '-m', '--multi', action='store_true',
        help=('Create a multi-line quote. Each line may be separated with a '
              'literal newline or a `\\n` sequence. A line can be designated '
              'as an action by starting it with a `\\a` sequence.'))
    subcmd_del = add_subcmd('del', 'Remove a quote from the database',
                            aliases=['rm', 'remove', 'delete'])
    subcmd_del.add_argument(
        'quote', nargs='+',
        help=('The quote to remove. Must exactly match the body of a quote. '
              'If the `id` option is used, this is the desired quote ID.'))
    subcmd_del.add_argument(
        '-i', '--id', action='store_true',
        help='Specify the target quote by ID instead.')
    # TBD: Maybe not include this and just do such replaces in SQL by hand.
    # subcmd_del.add_argument(
    #     '-r', '--regex', action='store_true',
    #     help=('The `quote` argument is interpreted as a regular expression '
    #           'and all matching quotes will be removed. Use with caution!'))
    subcmd_recent = add_subcmd(
        'recent', 'Display the most recently added quotes',
        parents=[pattern_options])
    subcmd_recent.add_argument(
        'pattern', nargs='?',
        help=('Show the most recent quotes by the author matching the given '
              'pattern. If omitted, shows the most recently added quotes '
              'instead.'))
    subcmd_recent.add_argument(
        '-n', '--count', type=int, default=1,
        help=('Display the `n` most recent quotes. Defaults to 1, with 5 '
              'being the maximum.'))
    subcmd_recent.add_argument(
        '-u', '--submitter', action='store_true',
        help='Show the most recent quotes by submitter instead of by author.')
    subcmd_search = add_subcmd(
        'search', 'Search the quote database for a specific quote',
        aliases=['find'], parents=[pattern_options])
    subcmd_search.add_argument(
        'pattern', nargs='*',
        help=('The search pattern used to match quote body content. If the '
              'pattern contains spaces, they must be escaped or the pattern '
              'must be wrapped in quotation marks.'))
    subcmd_search.add_argument(
        '-a', '--author',
        help=('Filter results to the author matching this pattern. The '
              '`pattern` argument may be omitted if this option is given.'))
    subcmd_search.add_argument(
        '-i', '--id', type=int,
        help='Fetch the quote with the given ID.')
    subcmd_search.add_argument(
        '-u', '--submitter',
        help=('Filter results to the submitter matching this pattern. The '
              '`pattern` argument may be omitted if this option is given.'))
    subcmd_stats = add_subcmd(
        'stats', 'Query various statistics about the quote database.')
    subcmd_stats.add_argument(
        'user', nargs='?',
        help=('Retrieve stats for the given user. If omitted, return stats '
              'for yourself.'))
    subcmd_stats.add_argument(
        '-g', '--global', action='store_true',
        help='Retrieve general stats about the quote database as a whole.')
    subcmd_stats.add_argument(
        '-l', '--leaderboard', '--top', action='store_true',
        help='Shows the top users for the chosen criteria.')
    subcmd_stats.add_argument(
        '-n', '--count', type=int, default=3,
        help='Influences the number of results displayed. Defaults to 3.')
    subcmd_stats.add_argument(
        '-s', '--sort',
        help=('Determines how the stats output should be sorted. This option '
              'expects a comma-delimited list of criteria to sort on, where '
              'each criteria is given as its respective option short name. '
              'Ex: `--sort q,u` to sort by quotes, then submissions.'))
    subcmd_stats.add_argument(
        '-q', '--quotes', action='store_true',
        help='Show total number of quotes in stats output.')
    subcmd_stats.add_argument(
        '-u', '--submissions', action='store_true',
        help='Show total number of submissions in stats output.')
    subcmd_stats.add_argument(
        '-e', '--self-submissions', action='store_true',
        help='Show total number of self-submitted quotes in stats output.')
    subcmd_stats.add_argument(
        '-p', '--percent', action='store_true',
        help='Show percentage of database totals for displayed criteria.')
    subcmd_stats.add_argument(
        '-y', '--per-year', action='store_true',
        help='Show number per year for displayed criteria.')
    subcmd_quick = add_subcmd(
        'quick',
        ('Shortcut to quickly add a quote of the last thing someone said '
         'or create one automatically from an existing message.'),
        aliases=['grab'], parents=[adding_options])
    subcmd_quick_group = subcmd_quick.add_mutually_exclusive_group()
    subcmd_quick_group.add_argument(
        'user', nargs='?',
        help=('The user to quote. If omitted, will quote the last message in '
              'the channel.'))
    subcmd_quick_group.add_argument(
        '-i', '--id', type=int,
        help=('For protocols that support it (like Discord), specify a '
              'message ID to add a quote automatically. Determines author, '
              'body, and date/time from the message data.'))
    subcmd_quick.add_argument(
        '-n', '--num-previous', type=int, default=0,
        help=('Include `n` messages before the target messsage to make a '
              'multi-line quote.'))
    cmds.append(cmd_quote)

    CORE.command_register(MOD_ID, *cmds)


def _resize_quote_deque():
    new_len = CFG.get('Cooldown.Count', 30)
    if new_len == recent_quotes['global'].maxlen:
        return
    recent_quotes['global'] = deque(
        recent_quotes['global'].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'modules':
        _resize_quote_deque()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == 'modules' and key == 'Quote.Cooldown.Count':
        _resize_quote_deque()


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    # Don't keep track of ZeroBot's lines
    if ctx.user == message.source:
        return
    if not message.content or message.content.isspace():
        return
    # TODO: Proper 'DirectMessage' class
    try:
        server = message.server.name
    except AttributeError:
        server = '__DM__'
        channel = message.destination.recipient.name
    else:
        channel = message.destination.name
    last_messages.setdefault(ctx.protocol, {}) \
                 .setdefault(server, {})[channel] = message


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    # TODO: quote on join
    ...


async def module_command_quote(ctx, parsed):
    """Handle `quote` command."""
    if parsed.subcmd:
        await globals()[f'quote_{parsed.subcmd}'](ctx, parsed)
    else:
        # Recite a random quote
        quote = await get_random_quote()
        if quote is None:
            await ctx.reply_command_result(
                parsed, 'Uh, there are no quotes...')
            return
        await ctx.module_message(parsed.msg.destination, quote)


async def fetch_quote(sql: str, params: Tuple = None, *,
                      cooldown: bool = True,
                      case_sensitive: bool = False) -> Optional[Quote]:
    """Fetch a quote from the database, respecting cooldowns.

    The parameters are the same as in an `aiosqlite.Cursor.execute` call, which
    this coroutine wraps. All quote fetches should use this coroutine as
    a base, as it handles quote cooldowns and other necessary state.
    """
    if cooldown and not all(token in sql for token in ('LIMIT', 'cooldown()')):
        raise ValueError("Query must include a LIMIT with 'cooldown()'")
    # TODO: per-author cooldowns
    async with DB.cursor() as cur:
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 1')
        await cur.execute(sql, params)
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 0')
        row = await cur.fetchone()
        if cooldown:
            while row and row['quote_id'] in recent_quotes['global']:
                row = await cur.fetchone()
    if row is not None:
        quote = await Quote.from_row(DB, row)
        if cooldown:
            recent_quotes['global'].append(row['quote_id'])
    else:
        quote = None
    return quote


async def get_random_quote() -> Optional[Quote]:
    """Fetch a random quote from the database."""
    return await fetch_quote(f"""
        SELECT * FROM {Quote.table_name}
        ORDER BY RANDOM() LIMIT cooldown() + 1
    """)


async def get_quote_by_id(quote_id: int) -> Optional[Quote]:
    """Fetch the quote with the given ID from the database."""
    return await fetch_quote(
        f'SELECT * FROM {Quote.table_name} WHERE quote_id = ?',
        (quote_id,), cooldown=False)


def read_datestamp(datestamp: str) -> Optional[datetime]:
    """Try to create a `datetime` object from `datestamp`.

    Expects an ISO 8601 formatted date/time string or a UNIX timestamp. Returns
    `None` if the string could not be converted.
    """
    try:
        date = datetime.fromisoformat(datestamp)
    except ValueError:
        try:
            date = datetime.utcfromtimestamp(int(datestamp))
        except ValueError:
            return None
    return date.replace(microsecond=0)


async def lookup_user(name: str) -> Optional[DBUser]:
    """Return the `DBUser` associated with `name`, if one exists.

    Searches for `name` in all relevant tables:
        - ``users``
        - ``aliases``
        - ``participants``

    Parameters
    ----------
    name : str
        The name to search for.
    """
    user = None
    async with DB.cursor() as cur:
        await cur.execute(f"""
            SELECT user_id FROM (
                SELECT user_id, name FROM users_all_names
                UNION
                SELECT user_id, name FROM {Participant.table_name}
            )
            WHERE name = ?
        """, (name,))
        row = await cur.fetchone()
        if row is not None:
            user = await DBUser.from_id(DB, row[0])
        return user


async def get_participant(name: str) -> Participant:
    """Get an existing `Participant` or create a new one.

    Parameters
    ----------
    name : str
        The name to look up.
    """
    user = await lookup_user(name)
    if user is not None:
        participant = await Participant.from_user(DB, user)
        if participant is not None:
            # Sync Participant.name with DBUser.name
            if participant.name != user.name:
                participant.name = user.name
                await participant.save()
        else:
            async with DB.cursor() as cur:
                await cur.execute(f"""
                    SELECT * FROM {Participant.table_name} AS "qp"
                    WHERE qp.name IN (
                        SELECT name FROM users_all_names AS "u"
                        WHERE u.user_id = ?
                    )
                """, (user.id,))
                row = await cur.fetchone()
            if row is not None:
                # A user's name or alias matched a Participant's name. Link the
                # Participant with this user.
                assert row['user_id'] is None, (
                    "Participant shouldn't have a user_id here "
                    f"({row['user_id']})")
                participant_id = row['participant_id']
            else:
                # The user has no matching Participant, so create a new one.
                participant_id = None
            participant = Participant(
                DB, participant_id, user.name, user.id, user)
            await participant.save()
    else:
        # Non-user Participant
        participant = await Participant.from_name(DB, name)
        if participant is None:
            # Completely new to the database
            participant = Participant(DB, None, name)
            await participant.save()
    return participant


def handle_action_line(line: str, msg: Message) -> Tuple[bool, str]:
    """Handles action checking and line modification for ``quote add``.

    Returns a 2-tuple of (is_action, strip_action).
    """
    action = False
    if match := re.match(r'\\a *', line):
        action = True
        line = line[match.end():]
    elif msg.is_action_str(line):
        action = True
        line = msg.strip_action_str(line)
    return action, line


def prepare_pattern(pattern: str, case_sensitive: bool = False,
                    basic: bool = False) -> str:
    """Prepare a pattern from a command for use in a query."""
    if basic:
        pattern = (pattern or '*').translate(WILDCARD_MAP)
        pattern = f'%{pattern}%' if pattern != '%' else '%'
    else:
        # The `m` flag is included because of the use of
        # `group_concat(name, char(10))` in queries needing to match aliases.
        re_flags = 'm' if case_sensitive else 'mi'
        pattern = f"(?{re_flags}:{pattern or '.*'})"
    return pattern


def generate_table(rows: List[sqlite3.Row],
                   target: Tuple[int, Any] = None) -> List[str]:
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
    min_widths = [max(x) for x in zip(*widths)]
    line, rule = '', ''
    for i, col in enumerate(headers):
        # Create header
        line += f'| {col:^{min_widths[i]}} '
        min_width = max(len(headers[i]), min_widths[i])
        rule += f"|{'-' * (min_width + 2)}"
    lines.append(f'{line}|')
    lines.append(f'{rule}|')
    for row in rows:
        line = ''
        is_target = target is not None and row[target[0]] == target[1]
        for i, col in enumerate(row):
            min_width = max(len(headers[i]), min_widths[i])
            if i == 0 and is_target:
                col = f'* {col}'
                line += f'| {col:>{min_width}} '
            else:
                line += f'| {col:{min_width}} '
        lines.append(f'{line}|')
    return lines


async def quote_exists(content: Union[str, List[str]]) -> bool:
    """Check if the given quote exists."""
    if isinstance(content, list):
        content = '\n'.join(content)
    async with DB.cursor() as cur:
        await cur.execute(f"""
            SELECT EXISTS (
                SELECT group_concat(line, char(10)) AS "body"
                FROM {QuoteLine.table_name}
                GROUP BY quote_id
                HAVING body = ?
            )
        """, (content,))
        return bool((await cur.fetchone())[0])


# TODO: protocol-agnostic
async def quote_add(ctx, parsed):
    """Add a quote to the database."""
    submitter = await get_participant(
        parsed.args['submitter'] or parsed.invoker.name)
    style = getattr(QuoteStyle, parsed.args['style'].title())
    if parsed.args['date']:
        date = read_datestamp(parsed.args['date'])
        if date is None:
            await CORE.module_send_event('invalid_command', ctx, parsed.msg)
            return
    else:
        date = datetime.utcnow().replace(microsecond=0)
    author = await get_participant(parsed.args['author'])
    body = ' '.join(parsed.args['body'])
    quote = Quote(DB, None, submitter, date=date, style=style)

    if parsed.args['multi']:
        extra = parsed.args['extra_authors'] or []
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
                    line_author = next(
                        a for a in authors if a.name == line_author)
                    if style is QuoteStyle.Unstyled:
                        line_body = line
            action, line_body = handle_action_line(line_body, parsed.msg)
            await quote.add_line(line_body, line_author, action)
    else:
        action, body = handle_action_line(body, parsed.msg)
        await quote.add_line(body, author, action)

    await quote.save()
    await ctx.module_message(parsed.msg.destination, f'Okay, adding: {quote}')


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
            parsed, f'Sorry, currently only {ctx.owner.name} can do that.')
        return
    body = ' '.join(parsed.args['quote'])
    if parsed.args['id']:
        quote = await get_quote_by_id(int(body))
    else:
        lines = MULTILINE_SEP.split(body)
        quote = await fetch_quote(f"""
            WITH target AS (
                SELECT quote_id, group_concat(line, char(10)) AS "body"
                FROM {QuoteLine.table_name}
                GROUP BY quote_id
                HAVING body = ?
            )
            SELECT * FROM {Quote.table_name}
            WHERE quote_id = (SELECT quote_id FROM target)
        """, ('\n'.join(lines),), cooldown=False)
    if quote is None:
        criteria = 'ID' if parsed.args['id'] else 'content'
        await ctx.reply_command_result(
            parsed, f"Couldn't find a quote with that {criteria}.")
        return
    await quote.delete()
    await ctx.module_message(parsed.source, f'Okay, removed quote: {quote}')


async def quote_recent(ctx, parsed):
    """Fetch the most recently added quotes."""
    pattern = parsed.args['pattern']
    case_sensitive = parsed.args['case_sensitive']
    basic = parsed.args['basic']
    count = min(parsed.args['count'], CFG['MaxCount'])
    if count < 1:
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return
    if pattern:
        target = 'submitters' if parsed.args['submitter'] else 'authors'
        search_method = 'LIKE' if basic else 'REGEXP'
        where = f'WHERE {target}.name_list {search_method} ?'
    else:
        where = ''
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
        pattern = prepare_pattern(pattern, case_sensitive, basic)
        query = (sql, (pattern, count))
    else:
        query = (sql, (count,))
    async with DB.cursor() as cur:
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 1')
        await cur.execute(*query)
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 0')
        quotes = [
            await Quote.from_row(DB, row) for row in await cur.fetchall()]
    results = []
    if count > 1:
        wrapper = textwrap.TextWrapper(
            width=160, max_lines=1, placeholder=' **[...]**')
        for n, quote in enumerate(quotes, 1):
            results.append(f'**[{n}]** {wrapper.fill(str(quote))}')
    else:
        results.append(str(quotes[0]))
    await ctx.reply_command_result(parsed, results)


async def quote_search(ctx, parsed):
    """Fetch a quote from the database matching search criteria."""
    if not any(
            parsed.args[a] for a in ('pattern', 'id', 'author', 'submitter')):
        # Technically equivalent to `!quote` but less efficient
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return
    case_sensitive = parsed.args['case_sensitive']
    if parsed.args['id']:
        quote = await get_quote_by_id(parsed.args['id'])
    else:
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
        """
        if parsed.args['basic']:
            pattern = prepare_pattern(
                ' '.join(parsed.args['pattern'] or []), basic=True)
            author_pat = prepare_pattern(
                parsed.args['author'], basic=True)
            submitter_pat = prepare_pattern(
                parsed.args['submitter'], basic=True)
            search_method = 'LIKE'
        else:
            pattern = prepare_pattern(
                ' '.join(parsed.args['pattern'] or []), case_sensitive)
            author_pat = prepare_pattern(parsed.args['author'], case_sensitive)
            submitter_pat = prepare_pattern(
                parsed.args['submitter'], case_sensitive)
            search_method = 'REGEXP'
        sql += f"""
                WHERE line {search_method} ? AND
                      authors.name_list {search_method} ? AND
                      submitters.name_list {search_method} ?
            )
            WHERE seqnum = 1  -- Don't include multiple lines from the same quote
            ORDER BY RANDOM() LIMIT cooldown() + 1
        """
        query = (sql, (pattern, author_pat, submitter_pat))
        quote = await fetch_quote(*query, case_sensitive=case_sensitive)
    if quote is None:
        criteria = 'ID' if parsed.args['id'] else 'pattern'
        await ctx.reply_command_result(
            parsed, f"Couldn't find any quotes matching that {criteria}")
        return
    await ctx.module_message(parsed.msg.destination, quote)


async def quote_stats(ctx, parsed):
    """Query various statistics about the quote database."""
    count = min(parsed.args['count'], CFG['MaxCount'])
    if count < 1:
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return
    if parsed.args['leaderboard']:
        await quote_stats_leaderboard(ctx, parsed, count)
        return
    if parsed.args['global'] and parsed.args['user']:
        # These are mutually exclusive arguments
        await CORE.module_send_event('invalid_command', ctx, parsed.msg)
        return

    selection = [parsed.args[x] for x in (
        'quotes', 'submissions', 'self_submissions', 'per_year', 'percent'
    )]
    if selection[:-1] == [False] * 4:
        # No criteria given, use defaults
        selection = [True] * 5

    # This logic is a bit ugly, but I don't have a better idea at the moment.
    percents = []
    criteria = {
        'q': 'Number of Quotes',
        'u': 'Number of Submitters',
        'e': 'Self-Submissions',
        'y': ['Quotes this Year', 'Avg. Yearly Quotes'],
        'p': percents
    }
    percent_names = ['Self-Sub %']
    if not parsed.args['global']:
        criteria['u'] = 'Number of Submissions'
        criteria['y'] += ['Submissions this Year', 'Avg. Yearly Subs']
        percent_names = ['Quote %', 'Submission %', 'Self-Sub %']
        if selection[-2]:  # Show year stats
            criteria['y'] = list(itertools.compress(
                criteria['y'],
                flatten([[selection[0]] * 2, [selection[1]] * 2])))
    if selection[-1]:  # Show percentages
        percents.extend(itertools.compress(percent_names, selection[:-2]))

    chosen = flatten(itertools.compress(criteria.values(), selection))
    chosen = ', '.join(f'"{x}"' for x in chosen)

    if parsed.args['global']:
        async with DB.cursor() as cur:
            await cur.execute(f'SELECT {chosen} FROM quote_stats_global')
            row = await cur.fetchone()
        result = ['**Database Stats**']
        zipped = zip(row.keys(), row)
    else:
        pattern = prepare_pattern(
            parsed.args['user'] or parsed.invoker.name)
        async with DB.cursor() as cur:
            await cur.execute(f"""
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
            """, (pattern,))
            row = await cur.fetchone()
        result = [f"**Stats for {row['Name']}**"]
        zipped = zip(row.keys()[1:], row[1:])
    result.append('```')
    pairs = list(zip(*[iter(zipped)] * 2))
    max_n, max_v = [], []
    for i in range(2):
        max_n.append(max(len(str(x[i][0])) for x in pairs) + 1)
        max_v.append(max(len(str(x[i][1])) for x in pairs))
    for stat1, stat2 in pairs:
        line = (f"{stat1[0] + ':':<{max_n[0]}} {stat1[1]:<{max_v[0]}}   "
                f"{stat2[0] + ':':<{max_n[1]}} {stat2[1]:<{max_v[1]}}")
        result.append(line)
    result.append('```')
    await ctx.module_message(parsed.msg.destination, '\n'.join(result))


async def quote_stats_leaderboard(ctx, parsed, count):
    """Leaderboard statistics."""
    percents = []
    criteria = {
        'q': 'Number of Quotes',
        'u': 'Number of Submissions',
        'p': percents
    }
    selection = [parsed.args[x] for x in ('quotes', 'submissions', 'percent')]
    if selection[:2] == [False] * 2:
        # No criteria given, use defaults
        selection = [True, True, selection[-1]]
        if parsed.args['sort'] is None:
            sort = ['q', 'u']

    if selection[2]:  # Show percentages
        percent_names = ['Quote %', 'Submission %']
        percents.extend(itertools.compress(percent_names, selection[:2]))

    chosen = list(flatten(itertools.compress(criteria.values(), selection)))
    if parsed.args['sort'] is not None:
        sort = parsed.args['sort'].split(',')
        try:
            # pseudo-criteria; the actual sort is based on the chosen criteria
            sort.remove('p')
        except ValueError:
            pass
        if not all(key in criteria.keys() for key in sort):
            await CORE.module_send_event('invalid_command', ctx, parsed.msg)
            return
        chosen_sort = ', '.join(f'"{criteria[x]}" DESC' for x in sort)
    else:
        # No sort specified, so mirror the chosen criteria
        chosen_sort = ', '.join(f'"{x}" DESC' for x in chosen)
    chosen = ', '.join(f'"{x}"' for x in chosen)

    if parsed.args['global']:
        # Show `count` top users
        async with DB.cursor() as cur:
            await cur.execute(f"""
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
            """, (count,))
            rows = await cur.fetchall()
        table = '\n'.join(generate_table(rows))
    else:
        # Show `count` users around target user
        pattern = prepare_pattern(
            parsed.args['user'] or parsed.invoker.name)
        async with DB.cursor() as cur:
            await cur.execute(f"""
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
            """, (pattern, parsed.args['count']))
            rows = await cur.fetchall()
        for row in rows:
            if re.match(pattern, row['Name']):
                name = row['Name']
                break
        table = '\n'.join(generate_table(rows, (1, name)))
    await ctx.module_message(parsed.msg.destination, f'```\n{table}\n```')


async def quote_quick(ctx, parsed):
    """Shortcuts for adding a quote to the database."""
    lines = []
    cached = False
    if (user := parsed.args['user']) is not None:
        user = user.lstrip('@')
    submitter = await get_participant(
        parsed.args['submitter'] or parsed.invoker.name)
    style = getattr(QuoteStyle, parsed.args['style'].title())
    if parsed.args['date']:
        if (date := read_datestamp(parsed.args['date'])) is None:
            await CORE.module_send_event('invalid_command', ctx, parsed.msg)
            return
    else:
        date = datetime.utcnow().replace(microsecond=0)

    # Try cache first
    if not parsed.args['id'] and not user:
        server = parsed.msg.server.name or '__DM__'
        channel = parsed.msg.destination.name
        try:
            msg = last_messages[ctx.protocol][server][channel]
        except KeyError:
            pass
        else:
            if msg is not None:
                cached = True

    if not cached:
        # TODO: Protocol-agnostic interface
        import discord
        types = [discord.ChannelType.text, discord.ChannelType.private]
        channels = [parsed.msg.destination]  # Search origin channel first
        for channel in ctx.get_all_channels():
            if channel.type in types and channel != channels[0]:
                channels.append(channel)
        if parsed.args['id']:
            for channel in channels:
                try:
                    msg = await channel.fetch_message(parsed.args['id'])
                    break
                except (discord.NotFound, discord.Forbidden):
                    continue
            else:
                # No message found
                await CORE.module_send_event(
                    'invalid_command', ctx, parsed.msg)
                return
        elif user:
            # Last message in channel by user
            user = parsed.msg.server.get_member_named(user)
            if user is None:
                # Don't bother checking history if given a bad username
                await CORE.module_send_event(
                    'invalid_command', ctx, parsed.msg)
                return
            limit = 100
            msg = await channels[0].history(limit=limit).get(author=user)
            if not msg:
                await ctx.reply_command_result(
                    parsed, ("Couldn't find a message from that user in "
                             f'the last {limit} messages.'))
                return
        else:
            # Last message in channel
            msg = (await channels[0].history(limit=2).flatten())[-1]

    author = await get_participant(msg.author.name)
    if parsed.args['date'] is None:
        date = msg.created_at.replace(microsecond=0)
    action, body = handle_action_line(msg.clean_content, DiscordMessage(msg))
    lines.append((body, author, action))

    # TODO: protocol-agnostic
    nprev = parsed.args['num_previous']
    async for prev_msg in msg.channel.history(limit=nprev, before=msg):
        author = await get_participant(prev_msg.author.name)
        action, body = handle_action_line(
            prev_msg.content, DiscordMessage(prev_msg))
        lines.append((body, author, action))

    quote = Quote(DB, None, submitter, date=date, style=style)
    for line in reversed(lines):
        await quote.add_line(*line)
    await quote.save()
    await ctx.module_message(parsed.msg.destination, f'Okay, adding: {quote}')
