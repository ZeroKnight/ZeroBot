"""protocol/discord/protocol.py

Discord protocol implementation.
"""

import asyncio

import discord

def module_register():
    print('hit module_register in discord')
    pass # do stuff

def module_unregister():
    pass

def module_get_instance(eventloop):
    # TEMP: get this stuff from config later
    print(f'module_get_instance: eventloop={eventloop}')
    inst = Instance(loop=eventloop)
    coro = inst.start('token goes here')
    return (inst, coro)

class Instance(discord.Client):
    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        print('Message from {0.author}: {0.content}'.format(message))
