"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio

import pydle

def module_register(core):
    global CORE
    CORE = core

    print('hit module_register')
    pass # do stuff

def module_unregister():
    pass

def module_get_context(eventloop: asyncio.AbstractEventLoop):
    # TEMP: get this stuff from config later
    print(f'module_get_context: eventloop={eventloop}')
    ctx = Context('ZeroBot', eventloop=eventloop)
    coro = ctx.connect('wazu.info.tm')
    return (ctx, coro)

# TBD: Include a ZeroBot-API level ABC in inheritance?
class Context(pydle.Client):
    """blah
    """

    async def on_connect(self):
        await super().on_connect()
        print('!! connected')
        await self.join('#zerobot')

    async def on_join(self, channel, user):
        await super().on_join(channel, user)
        if user == self.nickname:
            await self.message(channel, 'Hello, world!')
        else:
            await self.message(channel, f'Hi there, {user}!')
