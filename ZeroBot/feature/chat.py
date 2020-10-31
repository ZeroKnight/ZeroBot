"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

import random
import re
from enum import Enum, unique

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

recent_phrases = None


@unique
class QuestionResponse(Enum):
    Negative = 0
    Positive = 1
    Neutral = 2


async def module_register(core):
    """Initialize mdoule."""
    global CORE, CFG, DB
    CORE = core

    # make database connection and initialize tables if necessary
    DB = await core.database_connect(MOD_ID)

    # TEMP: TODO: decide between monolithic modules.toml or per-feature config
    CFG = core.load_config('modules')[MODULE_NAME]

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


async def module_on_message(ctx, message):
    """Handle `Core` message event."""
    # Don't respond to our own messages.
    if ctx.user == message.source:
        return

    # berate
    # TODO

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
                result = await DB.execute(
                    """SELECT phrase, action FROM chat_questioned
                    WHERE response_type = ?
                    ORDER BY RANDOM() LIMIT 1""",
                    (QuestionResponse.Positive.value,))
            else:
                result = await DB.execute(
                    """SELECT phrase, action FROM chat_questioned
                    ORDER BY RANDOM() LIMIT 1""")
            phrase, action = await result.fetchone()
            await ctx.module_message(message.destination, phrase, bool(action))
            return

    # Respond to being mentioned... oddly
    # NOTE: Needs to be LOW priority
    if ctx.user.mentioned(message):
        result = await DB.execute(
            """SELECT * FROM chat_mentioned
            ORDER BY RANDOM() LIMIT 1""")
        phrase, action = await result.fetchone()
        await ctx.module_message(message.destination, phrase, bool(action))


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    if user == ctx.user:
        await ctx.module_message(channel.name, 'Hello, world!')
    else:
        await ctx.module_message(channel.name, f'Hi there, {user.mention}!')
