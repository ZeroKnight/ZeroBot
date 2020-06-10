"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio
import logging

import pydle

import ZeroBot.common.abc as abc
from ZeroBot.protocol.context import Context

from .classes import IRCChannel, IRCMessage, IRCServer, IRCUser

MODULE_NAME = 'IRC'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'IRC protocol implementation'

# TODO: get this programatically and include network name
logger = logging.getLogger('ZeroBot.IRC')


def module_register(core):
    global CORE
    CORE = core

    # TEMP: get this stuff from config later
    user = IRCUser('ZeroBot__')
    server = IRCServer('irc.freenode.net')

    ctx = IRCContext(user.name, [], user.username, user.realname,
                     eventloop=core.eventloop)
    ctx.server = server
    ctx.user = user
    coro = ctx.connect(ctx.server.hostname)
    return (ctx, coro)


def module_unregister():
    pass


class IRCContext(Context, pydle.Client):
    """blah
    """

    async def on_raw_001(self, message):
        """Handle RPL_WELCOME."""
        await super().on_raw_001(message)
        self.server.servername = message.source

    # NOTE: pydle.features.ISUPPORTSupport defines on_raw_005 to set some
    # attributes like self.network and implement the on_isupport_* methods. Be
    # sure to call it if extending here.

    async def on_isupport_network(self, value):
        await super().on_isupport_network(value)
        self.server.network = value

    async def on_connect(self):
        await super().on_connect()

        # Get our user/host as reported by the server
        await self.rawmsg('USERHOST', self.user.name)

        logger.info(
            f'Connected to {self.server.network} at {self.server.hostname}')
        await CORE.module_send_event('connect', self)

        # TEMP: get channels from config
        await self.module_join('##zerobot')

    async def on_raw_302(self, message):
        """Handle RPL_USERHOST."""
        # Update self.users for pydle
        for user in message.params[1].rstrip().split(' '):
            nickname, userhost = user.split('=', 1)
            username, hostname = userhost[1:].split('@', 1)
            self._sync_user(nickname, {
                'username': username,
                'hostname': hostname
            })

            # Update user/host for ZeroBot and pydle
            if nickname == self.user.name:
                self.user.username = username
                self.user.hostname = hostname
                # pylint: disable=attribute-defined-outside-init
                self.username = username

    async def on_join(self, channel, user):
        await super().on_join(channel, user)

        channel = IRCChannel(channel)
        # TODO: pydle only passes the nickname, so we need pull the other values
        # from the server (cache this somewhere?)
        user = IRCUser(user, '', '', hostname='')
        await CORE.module_send_event('join', self, channel, user)

    async def on_message(self, destination: str, source: str, message: str):
        await super().on_message(destination, source, message)

        # TODO: time attribute, ircv3 tags
        msg = IRCMessage(source, destination, message, None, {})
        await CORE.module_send_event('message', self, msg)

    async def module_join(self, where, password=None):
        logger.info(f'Joining channel {where}')
        await self.join(where, password)

    async def module_message(self, destination, message):
        await self.message(destination, message)
