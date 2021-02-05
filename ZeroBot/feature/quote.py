"""Quote

Archive, search, and recite humorous, inspiring, or out-of-context quotes.
Includes a variety of commands for searching and managing quotes, as well as
reporting quote database statistics.
"""

import asyncio
import random
import re
import textwrap
from collections import deque
from datetime import datetime
from enum import IntEnum, unique
from typing import List, Optional, Tuple, Union

from ZeroBot.common import CommandParser
from ZeroBot.common.abc import Message
from ZeroBot.database import DBUser
from ZeroBot.protocol.discord.classes import DiscordMessage  # TEMP

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


class Participant():
    """A `Quote` participant: either an author or a submitter.

    Participants may or may not be linked to a `DBUser`.

    Parameters
    ----------
    participant_id : int
        The participant's ID.
    name : str
        The name of the participant.
    user_id : int, optional
        The participant's user ID, if it has one.
    user : DBUser, optional
        The user linked to this participant.

    Attributes
    ----------
    id
    """

    def __init__(self, participant_id: int, name: str, user_id: int = None,
                 user: DBUser = None):
        self.id = participant_id
        self.name = name
        self.user_id = user_id
        if user is not None and user.id != self.user_id:
            raise ValueError(
                'The given user.id does not match user_id: '
                f'{user.id=} {self.user_id=}')
        self.user = user

    def __repr__(self):
        attrs = ['id', 'name', 'user']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.id == other.id

    @classmethod
    async def from_id(cls, participant_id: int) -> Optional['Participant']:
        """Construct a `Participant` by ID from the database.

        Returns `None` if there was no `Participant` with the given ID.

        Parameters
        ----------
        participant_id : int
            The ID of the participant to fetch.
        """
        async with DB.cursor() as cur:
            await cur.execute(
                'SELECT * FROM quote_participants WHERE participant_id = ?',
                (participant_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        user = await DBUser.from_id(row[-1], DB)
        return cls(*row[:-1], user)

    @classmethod
    async def from_name(cls, name) -> Optional['Participant']:
        """Construct a `Participant` by name from the database.

        Parameters
        ----------
        name : str
            The name of the participant to fetch.
        """
        async with DB.cursor() as cur:
            await cur.execute(
                'SELECT * FROM quote_participants WHERE name = ?', (name,))
            row = await cur.fetchone()
        if row is None:
            return None
        user = await DBUser.from_id(row[-1], DB)
        return cls(*row, user)

    @classmethod
    async def from_user(cls, user: Union[DBUser, int]) -> 'Participant':
        """Construct a `Participant` linked to the given user.

        Parameters
        ----------
        user : DBUser or int
            The linked user to search for. May be a `DBUser` object or an `int`
            referring to a user ID.
        """
        try:
            user_id = user.id
        except AttributeError:
            user_id = int(user)
        async with DB.cursor() as cur:
            await cur.execute(
                'SELECT * FROM quote_participants WHERE user_id = ?',
                (user_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        if not isinstance(user, DBUser):
            user = await DBUser.from_id(row[-1], DB)
        return cls(*row, user)

    async def fetch_user(self) -> DBUser:
        """Fetch the database user linked to this participant.

        Sets `self.user` to the fetched `DBUser` and returns it.
        """
        if self.user_id is None:
            raise ValueError('Participant has no linked user.')
        self.user = await DBUser.from_id(self.user_id, DB)
        return self.user

    async def save(self):
        """Save this `Participant` to the database."""
        async with DB.cursor() as cur:
            await cur.execute("""
                INSERT INTO quote_participants VALUES (?, ?, ?)
                ON CONFLICT (participant_id) DO UPDATE SET
                    name = excluded.name,
                    user_id = excluded.user_id
            """, (self.id, self.name, self.user_id))
            self.id = cur.lastrowid
            await DB.commit()


class QuoteLine:
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

    def __init__(self, quote_id: int, body: str, author: Participant, *,
                 quote: 'Quote' = None, line_num: int = 1, author_num: int = 1,
                 action: bool = False):
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
        else:
            return f'<{self.author}> {self.body}'

    @classmethod
    async def from_row(cls, row: Tuple) -> 'QuoteLine':
        """Construct a `QuoteLine` from a database row.

        Parameters
        - ---------
        row: Tuple
            A row returned from the database.
        """
        author = await Participant.from_id(row[3])
        return cls(
            quote_id=row[0], line_num=row[1], body=row[2],
            author=author, author_num=row[4], action=row[5]
        )


class Quote:
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

    def __init__(self, quote_id: Optional[int], submitter: Participant, *,
                 date: datetime = datetime.utcnow(),
                 style: QuoteStyle = QuoteStyle.Standard):
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
    async def from_row(cls, row: Tuple) -> 'Quote':
        """Construct a `Quote` from a database row.

        Also fetches the associated `QuoteLine`s.

        Parameters
        ----------
        row : Tuple
            A row returned from the database.
        """
        submitter = await Participant.from_id(row[1])
        quote = cls(
            quote_id=row[0], submitter=submitter, date=row[2],
            style=QuoteStyle(row[3])
        )
        await quote.fetch_lines()
        return quote

    async def fetch_lines(self) -> List[QuoteLine]:
        """Fetch the `QuoteLine`s that make up the quote body.

        Sets `self.lines` to the fetched lines and returns them.
        """
        async with DB.cursor() as cur:
            await cur.execute("""
                SELECT * FROM quote_lines WHERE quote_id = ?
                ORDER BY line_num
            """, (self.id,))
            self.lines = [
                await QuoteLine.from_row(row) for row in await cur.fetchall()]
        return self.lines

    async def fetch_authors(self) -> List[Participant]:
        """Fetch the authors that are part of this quote.

        Authors in the list are ordered by their `author_num` value. Sets
        `self.authors` to the fetched authors and returns them.
        """
        async with DB.cursor() as cur:
            await cur.execute("""
                SELECT DISTINCT participant_id FROM quote_lines
                WHERE quote_id = ?
                ORDER BY author_num
            """, (self.id))

            self.authors = [
                await Participant.from_id(pid) async for pid in cur.fetchall()]
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
            QuoteLine(self.id, body, author, quote=self, line_num=line_num,
                      author_num=author_num, action=action))

    async def save(self):
        """Save this `Quote` to the database."""
        async with DB.cursor() as cur:
            await cur.execute('BEGIN TRANSACTION')
            await cur.execute("""
                INSERT INTO quote VALUES (?, ?, ?, ?)
                ON CONFLICT (quote_id) DO UPDATE SET
                    submitter = excluded.submitter,
                    submission_date = excluded.submission_date,
                    style = excluded.style
            """, (self.id, self.submitter.id, self.date, self.style.value))

            self.id = cur.lastrowid
            for line in self.lines:
                line.quote_id = self.id

            await cur.execute(
                'DELETE FROM quote_lines WHERE quote_id = ?', (self.id,))
            params = [(self.id, ql.line_num, ql.body, ql.author.id,
                       ql.author_num, ql.action) for ql in self.lines]
            await cur.executemany(
                'INSERT INTO quote_lines VALUES(?, ?, ?, ?, ?, ?)', params)

            await cur.execute('COMMIT TRANSACTION')


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
    await _init_tables()

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


async def _init_tables():
    await DB.executescript("""
        CREATE TABLE IF NOT EXISTS "quote_participants" (
            "participant_id"  INTEGER NOT NULL,
            "name"            TEXT NOT NULL UNIQUE,
            "user_id"         INTEGER,
            FOREIGN KEY("user_id") REFERENCES "users"("user_id")
                ON DELETE SET NULL,
            PRIMARY KEY("participant_id")
        );
        CREATE TABLE IF NOT EXISTS "quote" (
            "quote_id"         INTEGER NOT NULL,
            "submitter"        INTEGER NOT NULL DEFAULT 0,
            "submission_date"  DATETIME DEFAULT CURRENT_TIMESTAMP,
            "style"            INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY("quote_id")
            FOREIGN KEY("submitter")
                REFERENCES "quote_participants"("participant_id")
                ON DELETE SET DEFAULT
        );
        CREATE TABLE IF NOT EXISTS "quote_lines" (
            "quote_id"        INTEGER NOT NULL,
            "line_num"        INTEGER NOT NULL DEFAULT 1,
            "line"            TEXT NOT NULL,
            "participant_id"  INTEGER NOT NULL DEFAULT 0,
            "author_num"      INTEGER NOT NULL DEFAULT 1,
            "action"          BOOLEAN NOT NULL DEFAULT 0
                              CHECK(action IN (0,1)),
            PRIMARY KEY("quote_id", "line_num"),
            FOREIGN KEY("quote_id") REFERENCES "quote"("quote_id")
                ON DELETE CASCADE,
            FOREIGN KEY("participant_id")
                REFERENCES "quote_participants"("participant_id")
                ON DELETE SET DEFAULT
                ON UPDATE CASCADE
        ) WITHOUT ROWID;
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
        help=('The quote to remove. Must exactly match the body of a quote '
              '(or a single line of multi-line quote). If the `id` option is '
              'specified, this is the desired quote ID.'))
    subcmd_del.add_argument(
        '-i', '--id', action='store_true',
        help=('Specify the target quote by ID instead. Multiple IDs may be '
              'specified this way.'))
    subcmd_del.add_argument(
        '-r', '--regex', action='store_true',
        help=('The `quote` argument is interpreted as a regular expression and'
              'all matching quotes will be removed. Use with caution!'))
    subcmd_del.add_argument(
        '-l', '--line', nargs='?',
        help=('For multi-line quotes, only remove the line specified by this '
              'option. If specifying a quote by its body, the value may be '
              'omitted.'))
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
    new_len = CFG['QuoteCooldown']
    if new_len == recent_quotes[...].maxlen:
        return
    recent_quotes[...] = deque(
        recent_quotes[...].copy(), maxlen=new_len)


async def module_on_config_reloaded(ctx, name):
    """Handle `Core` config reload event."""
    if name == 'modules':
        _resize_quote_deque()


async def module_on_config_changed(ctx, name, key, old, new):
    """Handle `Core` config change event."""
    if name == 'modules' and key == 'Quote.QuoteCooldown':
        _resize_quote_deque()


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    # Don't keep track of ZeroBot's lines
    if ctx.user == message.source:
        return
    if not message.content or message.content.isspace():
        return
    server = message.server.name or '__DM__'
    channel = message.destination.name
    last_messages.setdefault(ctx.protocol, {}) \
                 .setdefault(server, {})[channel] = message


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    # TODO: quote on join
    ...


async def module_command_quote(ctx, parsed):
    """Handle `quote` command."""
    # NOTE: restrict deletion to owner
    # TODO: make regex deletion a two-step command; upon invoking, return how
    # many quotes would be deleted and a list of relevant ids (up to X amount)
    # require a !quote confirm delete or something like that to actually go
    # through with it.
    # TODO: "preview" or "confirm" option? leverage `wait_for` or reactions to
    # confirm/cancel adding/removing a quote before actually doing it, and give
    # a preview of what would be added/removed
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


async def fetch_quote(sql: str, params: Tuple = None,
                      case_sensitive: bool = False) -> Optional[Quote]:
    """Fetch a quote from the database, respecting cooldowns.

    The parameters are the same as in an `aiosqlite.Cursor.execute` call, which
    this coroutine wraps. All quote fetches should use this coroutine as
    a base, as it handles quote cooldowns and other necessary state.
    """
    if not all(token in sql for token in ('LIMIT', 'cooldown()')):
        raise ValueError("Query must include a LIMIT with 'cooldown()'")
    # TODO: per-author cooldowns
    async with DB.cursor() as cur:
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 1')
        await cur.execute(sql, params)
        if case_sensitive:
            await cur.execute('PRAGMA case_sensitive_like = 0')
        row = await cur.fetchone()
        while row and row[0] in recent_quotes['global']:
            row = await cur.fetchone()
    if row is not None:
        quote = await Quote.from_row(row)
        recent_quotes['global'].append(row[0])
    else:
        quote = None
    return quote


async def get_random_quote() -> Optional[Quote]:
    """Fetch a random quote from the database."""
    return await fetch_quote("""
        SELECT * FROM quote
        ORDER BY RANDOM() LIMIT cooldown() + 1
    """)


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
        - ``quote_participants``

    Parameters
    ----------
    name : str
        The name to search for.
    """
    user = None
    async with DB.cursor() as cur:
        await cur.execute("""
            SELECT user_id FROM (
                SELECT user_id, name FROM users_all_names
                UNION
                SELECT user_id, name FROM quote_participants
            )
            WHERE name = ?
        """, (name,))
        row = await cur.fetchone()
        if row is not None:
            user = await DBUser.from_id(row[0], DB)
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
        participant = await Participant.from_user(user)
        if participant is not None:
            # Sync Participant.name with DBUser.name
            if participant.name != user.name:
                participant.name = user.name
                await participant.save()
        else:
            async with DB.cursor() as cur:
                await cur.execute("""
                    SELECT * FROM quote_participants AS "qp"
                    WHERE qp.name IN (
                        SELECT name FROM users_all_names AS "u"
                        WHERE u.user_id = ?
                    )
                """, (user.id,))
                row = await cur.fetchone()
            if row is not None:
                # A user's name or alias matched a Participant's name. Link the
                # Participant with this user.
                assert row[-1] is None, \
                    f"Participant shouldn't have a user_id here ({row[-1]})"
                participant_id = row[0]
            else:
                # The user has no matching Participant, so create a new one.
                participant_id = None
            participant = Participant(participant_id, user.name, user.id, user)
            await participant.save()
    else:
        # Non-user Participant
        participant = await Participant.from_name(name)
        if participant is None:
            # Completely new to the database
            participant = Participant(None, name)
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
    quote = Quote(None, submitter, date=date, style=style)

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


async def quote_recent(ctx, parsed):
    """Fetch the most recently added quotes."""
    pattern = parsed.args['pattern']
    case_sensitive = parsed.args['case_sensitive']
    basic = parsed.args['basic']
    count = min(parsed.args['count'], 5)
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
            FROM quote_participants_all_names
            GROUP BY participant_id
        )
        SELECT quote_id, submitter, submission_date, style
        FROM (
            SELECT *, row_number() OVER (PARTITION BY quote_id) AS "seqnum"
            FROM quote
            JOIN quote_lines USING (quote_id)
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
        quotes = [await Quote.from_row(row) for row in await cur.fetchall()]
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
        query = ("""
            SELECT * FROM quote WHERE quote_id = ?
            ORDER BY RANDOM() LIMIT cooldown() + 1
        """, (parsed.args['id'],))
    else:
        sql = """
            WITH participant_names AS (
                SELECT participant_id,
                       group_concat(name, char(10)) AS "name_list"
                FROM quote_participants_all_names
                GROUP BY participant_id
            )
            SELECT quote_id, submitter, submission_date, style
            FROM (
                SELECT *, row_number() OVER (PARTITION BY quote_id) AS "seqnum"
                FROM quote
                JOIN quote_lines USING (quote_id)
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
        query = (sql, (pattern, author_pat, submitter_pat), case_sensitive)
    quote = await fetch_quote(*query)
    if quote is None:
        await ctx.reply_command_result(
            parsed, "Couldn't find any quotes matching that pattern.")
        return
    await ctx.module_message(parsed.msg.destination, quote)


async def quote_quick(ctx, parsed):
    """Shortcuts for adding a quote to the database."""
    lines = []
    cached = False
    user = parsed.args['user']
    if user is not None:
        user = user.lstrip('@')
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
    async for msg in msg.channel.history(limit=nprev, before=msg):
        author = await get_participant(msg.author.name)
        action, body = handle_action_line(msg.content, DiscordMessage(msg))
        lines.append((body, author, action))

    quote = Quote(None, submitter, date=date, style=style)
    for line in reversed(lines):
        await quote.add_line(*line)
    await quote.save()
    await ctx.module_message(parsed.msg.destination, f'Okay, adding: {quote}')
