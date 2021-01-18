"""Quote

Archive, search, and recite humorous, inspiring, or out-of-context quotes.
Includes a variety of commands for searching and managing quotes, as well as
reporting quote database statistics.
"""

import asyncio
import random
import re
from collections import deque
from enum import IntEnum, unique

from ZeroBot.common import CommandParser

MODULE_NAME = 'Quote'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.2'
MODULE_LICENSE = 'MIT'
MODULE_DESC = ('Archive, search, and recite humorous, inspiring, or '
               '(especially) out-of-context quotes.')

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

# TBD: track per author, or globally by id?
recent_quotes = {}
last_lines = {}


@unique
class QuoteStyle(IntEnum):
    Standard = 1
    Epigraph = 2
    Unstyled = 3


async def module_register(core):
    """Initialize module."""
    global CORE, CFG, DB, recent_quotes
    CORE = core

    DB = await core.database_connect(MOD_ID)
    await DB.create_function(
        'cooldown', 0, lambda: CFG.get('QuoteCooldown', 0))
    await _init_tables()

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]
    # recent_quotes[...] = deque(maxlen=CFG.get('QuoteCooldown', 0))

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
    subcmd_add = add_subcmd('add', 'Submit a new quote', aliases=['new'])
    subcmd_add.add_argument(
        'author',
        help=('The author of the quote, i.e. the entity being quoted. Must be '
              'wrapped in quotation marks if it contains spaces.'))
    subcmd_add.add_argument(
        'body', nargs='+', help='The contents of the quote')
    subcmd_add.add_argument(
        '-s', '--style', choices=[style.name.lower() for style in QuoteStyle],
        type=str.lower, default='standard',
        help=('Specify the quote style. The default, "standard" styles the '
              'quote like a typical IRC client message, e.g. `<Foo> hello`. '
              '"epigraph" styles the quote as in writing, e.g. '
              '`"Hello." ―Foo`. "unstyled" applies no formatting and is '
              'displayed exactly as entered.'))
    subcmd_add.add_argument(
        '-m', '--multi', action='store_true',
        help=('Create a multi-line quote. Each line may be separated with a '
              'literal newline or a `\\n` sequence. A line can be designated '
              'as an action by starting it with a `\\a` sequence.'))
    subcmd_add.add_argument(
        '-a', '--author', action='append',
        help='Specifies additional authors for a multi-line quote')
    subcmd_add.add_argument(
        '-d', '--date',
        help=('Submits the quote with the following datestamp instead of the '
              'current date and time. Time is interpreted as UTC. Expects '
              'either a Unix timestamp or an ISO 8601 formatted date string.'))
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
    subcmd_search = add_subcmd(
        'search', 'Search the quote database for a specific quote',
        aliases=['find'])
    subcmd_search.add_argument(
        'pattern', nargs='?',
        help=('The search pattern used to match quote body content. If the '
              'pattern contains spaces, they must be escaped or the pattern '
              'must be wrapped in quotation marks.'))
    subcmd_search.add_argument(
        '-a', '--author',
        help=('Filter results to the author matching this pattern. The '
              '`pattern` argument may be omitted if this option is given.'))
    subcmd_search.add_argument(
        '-s', '--simple', action='store_true',
        help=('Patterns are interpreted as simple wildcard strings rather '
              'than regular expressions. `*`, `?`, and `[...]` are '
              'supported.'))
    subcmd_quick = add_subcmd(
        'quick',
        'Shortcut to quickly add a quote of the last thing someone said',
        aliases=['grab'])
    subcmd_quick.add_argument(
        'user', nargs='?',
        help=('The user to quote. If omitted, will quote the last message in '
              'the channel.'))
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
    server = message.server.name
    channel = message.destination.name
    user = message.source.name
    last_lines.setdefault(server, {}) \
              .setdefault(channel, {})[user] = message


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
    ...
