"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

from ZeroBot.common import CommandParser

MODULE_NAME = 'Chat'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Allows ZeroBot to chat and respond to conversation in various ways.'

CORE = None
MOD_ID = 'chat'
DB = None

# \xa1 and \xbf are the inverted variants of ! and ?
# \x203D is the interrobang
DOTCHARS = '.!?\xA1\xBF\u203D'


async def module_register(core):
    """Initialize mdoule."""
    global CORE, DB
    CORE = core

    # make database connection and initialize tables if necessary
    DB = await core.database_connect(MOD_ID)

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
    # This is all temporary


async def module_on_join(ctx, channel, user):
    """Handle `Core` join event."""
    if user.name == 'ZeroBot':  # TODO: get nick from config
        await ctx.module_message(channel.name, f'Hello, world!')
    else:
        await ctx.module_message(channel.name, f'Hi there, {user.name}')
