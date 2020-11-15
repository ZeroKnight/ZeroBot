"""Quote

Archive, search, and recite humorous, inspiring, or out-of-context quotes.
Includes a variety of commands for searching and managing quotes, as well as
reporting quote database statistics.
"""

import asyncio
import random
import re
from collections import deque
from enum import Enum, unique

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


@unique
class QuoteStyle(Enum):
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
    cmd_quote = CommandParser('quote', 'Recite a quote.')
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
    # TODO: Keep track of the the last thing a user said (and the last thing
    # said period) to facilitate quick quoting with the `grab` command.
    ...


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    # TODO: quote on join
    ...


async def module_command_quote(ctx, parsed):
    """Handle `quote` command."""
