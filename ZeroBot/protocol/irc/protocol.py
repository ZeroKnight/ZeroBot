"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio

import pydle

def module_register():
    print('hit module_register')
    pass # do stuff

def module_unregister():
    pass

def module_get_instance(eventloop):
    # TEMP: get this stuff from config later
    print(f'module_get_instance: eventloop={eventloop}')
    return Instance('ZeroBot', eventloop=eventloop)

# TBD: Include a ZeroBot-API level ABC in inheritance?
class Instance(pydle.Client):
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
