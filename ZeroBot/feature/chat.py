"""Chat

Allows ZeroBot to chat and respond to conversation in various ways. Also allows
privileged users to puppet ZeroBot, sending arbitrary messages and actions.
"""

MODULE_NAME = 'Chat'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Allows ZeroBot to chat and respond to conversation in various ways.'

# \xa1 and \xbf are the inverted variants of ! and ?
# \x203D is the interrobang
DOTCHARS = '.!?\xA1\xBF\u203D'

def module_register():
    # make database connection and initialize tables if necessary
    # check for existence of 'fortune' command in environment
    pass

def module_unregister():
    # close database connection
    pass

async def module_on_message(ctx, message):
    if message.content.startswith('ZeroBot'):
        await ctx.module_message(message.destination, "DON'T TALK SHIT ABOUT TOTAL")

async def module_on_join(ctx, channel, user):
    if user.name == 'ZeroBot': # TODO: get nick from config
        await ctx.module_message(channel.name, f'Hello, world!')
    else:
        await ctx.module_message(channel.name, f'Hi there, {user.name}')

