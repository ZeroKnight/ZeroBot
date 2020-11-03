"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

import random
import re
from collections import deque
from enum import Enum, unique
from typing import Iterable, Tuple

from ZeroBot.common import CommandParser

MODULE_NAME = 'Chat'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Allows ZeroBot to chat and respond to conversation in various ways.'

CORE = None
CFG = None
DB = None
MOD_ID = __name__.rsplit('.', 1)[-1]

# \xa1 and \xbf are the inverted variants of ! and ?
# \x203D is the interrobang
DOTCHARS = '.!?\xA1\xBF\u203D'

PATTERN_WAT = re.compile(r'(?:h+w+|w+h*)[aou]+t\s*\??\s*$')
PATTERN_DOTS = re.compile(r'^\s*[' + DOTCHARS + r']+\s*$')

tables = ['berate', 'greetings', 'mentioned', 'questioned']
recent_phrases = {}
kicked_from = set()


@unique
class QuestionResponse(Enum):
    Negative = 0
    Positive = 1
    Neutral = 2


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB, recent_phrases
    CORE = core

    # make database connection and initialize tables if necessary
    DB = await core.database_connect(MOD_ID)
    await DB.create_function('cooldown', 0, lambda: CFG['PhraseCooldown'])

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]
    for table in tables:
        recent_phrases[table] = deque(maxlen=CFG['PhraseCooldown'])

    # check for existence of 'fortune' command in environment

    _register_commands()


async def module_unregister():
    """Prepare for shutdown."""
    await CORE.database_disconnect(MOD_ID)


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

    cmd_fortune = CommandParser(
        'fortune', "Read a fortune from the *nix 'fortune' command")
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
    results = await DB.execute(
        f"""SELECT {', '.join(columns)} FROM chat_{table}
        {query}
        ORDER BY RANDOM() LIMIT cooldown() + 1""", parameters)
    row = await results.fetchone()
    while row[0] in recent_phrases[table]:
        row = await results.fetchone()
    recent_phrases[table].append(row[0])
    return row


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    # Don't respond to our own messages.
    if ctx.user == message.source:
        return

    # Berate
    if CFG['Berate.Enabled'] and message.source.name in CFG['Berate.UserList']:
        if random.random() <= CFG['Berate.Chance'] / 100:
            phrase, action = await fetch_phrase('berate', ['action'])
            phrase.replace('%0', message.source.name)
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
        # Do not use '.' as a possible output
        char = random.choice(DOTCHARS[1:])
        await ctx.module_message(
            message.destination, f'{message.content}{char}')
        return

    # Answer Questions
    for pattern in CFG.get('Questioned.Triggers'):
        # Check against bare name and mention string to handle protocols where
        # these may differ, like Discord.
        pattern = pattern.replace(r'\z', f'{ctx.user.mention_pattern()}')
        if re.search(pattern, message.content, re.I):
            if re.search(r'would you kindly', message.content, re.I):
                phrase, action = await fetch_phrase(
                    'questioned', ['action'],
                    'WHERE response_type = ?',
                    (QuestionResponse.Positive.value,))
            else:
                phrase, action = await fetch_phrase('questioned', ['action'])
            await ctx.module_message(message.destination, phrase, action)
            return

    # Respond to being mentioned... oddly
    # NOTE: Needs to be LOW priority
    if ctx.user.mentioned(message):
        phrase, action = await fetch_phrase('mentioned', ['action'])
        await ctx.module_message(message.destination, phrase, action)


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    if user == ctx.user:
        if channel in kicked_from:
            # Don't greet if we've been kicked from here
            kicked_from.remove(channel)
    else:
        phrase, action = await fetch_phrase('greetings', ['action'])
        await ctx.module_message(channel, phrase, action)


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
                target = await ctx.get_target(target)
            targets.append(target)
    else:
        targets.append(parsed.msg.destination)
    for target in targets:
        await ctx.module_message(
            target, ' '.join(parsed.args['msg']), parsed.args['action'])
