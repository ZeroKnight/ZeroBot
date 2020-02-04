"""protocol/discord/protocol.py

Discord protocol implementation.
"""

import asyncio

import discord

def module_register(core):
    global CORE
    CORE = core

    print('hit module_register in discord')
    pass # do stuff

def module_unregister():
    pass

def module_get_context(eventloop: asyncio.AbstractEventLoop):
    # TEMP: get this stuff from config later
    print(f'module_get_context: eventloop={eventloop}')
    ctx = Context(loop=eventloop)
    coro = ctx.start('token goes here')
    return (ctx, coro)

class Context(discord.Client):
    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        print('Message from {0.author}: {0.content}'.format(message))
