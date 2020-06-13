"""protocol/discord/protocol.py

Discord protocol implementation.
"""

import asyncio

import discord

import ZeroBot.common.abc as abc
from ZeroBot.protocol.context import Context

CORE = None
MODULE_NAME = 'Discord'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Discord protocol implementation'


def module_register(core):
    global CORE
    CORE = core

    # TEMP: get this stuff from config later
    ctx = DiscordContext(loop=core.eventloop)
    coro = ctx.start('')
    return (ctx, coro)


def module_unregister():
    pass


class DiscordMessage(abc.Message):
    def __init__(self, message: discord.Message):
        self.source = message.author
        self.destination = message.channel
        self.content = message.content
        self.time = message.created_at
        self._original = message

    @property
    def original(self):
        return self._original

    def __eq__(self, other):
        pass  # TODO


class DiscordContext(Context, discord.Client):
    """blah
    """

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        print('Message from {0.author}: {0.content}'.format(message))
        msg = DiscordMessage(message)
        await CORE.module_send_event('message', self, msg)

    async def module_message(self, destination, message):
        await destination.send(message)
