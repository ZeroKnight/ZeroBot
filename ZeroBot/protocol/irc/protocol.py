"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio

import pydle

import ZeroBot.common.abc as abc
from ZeroBot.protocol.context import Context

from .classes import IRCChannel, IRCMessage, IRCServer, IRCUser


def module_register(core):
    global CORE
    CORE = core

    print('hit module_register')


def module_unregister():
    pass


def module_get_context(eventloop: asyncio.AbstractEventLoop):
    # TEMP: get this stuff from config later
    print(f'module_get_context: eventloop={eventloop}')
    ctx = IRCContext('ZeroBot', eventloop=eventloop)
    coro = ctx.connect('wazu.info.tm')
    return (ctx, coro)


class IRCContext(Context, pydle.Client):
    """blah
    """

    async def on_connect(self):
        await super().on_connect()

        # TODO: call something like Core.module_on_connect

        print('[irc] connected to blahblah')
        await self.join('#zerobot')

    async def on_join(self, channel, user):
        await super().on_join(channel, user)

        channel = IRCChannel(channel)
        # TODO: pydle only passes the nickname, so we need pull the other values
        # from the server (cache this somewhere?)
        user = IRCUser(user, '', '', '', False)
        await CORE.module_send_event('join', self, channel, user)

    async def on_message(self, destination: str, source: str, message: str):
        await super().on_message(destination, source, message)

        # TODO: time attribute, ircv3 tags
        msg = IRCMessage(source, destination, message, None, {})
        await CORE.module_send_event('message', self, msg)

    async def module_message(self, destination, message):
        await self.message(destination, message)
