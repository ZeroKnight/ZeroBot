"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio
import logging
from typing import List

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

    ctx = IRCContext(user, server, eventloop=core.eventloop)
    coro = ctx.connect(ctx.server.hostname)
    return (ctx, coro)


def module_unregister():
    pass


class IRCContext(Context, pydle.Client):
    """blah
    """

    def __init__(self, user: IRCUser, server: IRCServer, *,
                 eventloop: asyncio.AbstractEventLoop,
                 fallback_nicknames: List = None):
        self.channels_zb = {}
        self.user = user
        self.server = server
        self.users_zb = {}
        super(pydle.Client, self).__init__(
            user.name, fallback_nicknames or [], user.username, user.realname,
            eventloop=eventloop
        )

    def _create_channel(self, channel):
        super()._create_channel(channel)
        self.channels_zb[channel] = IRCChannel(channel)

    def _sync_user(self, nick, metadata):
        super()._sync_user(nick, metadata)
        # Keep ZeroBot User objects in sync
        if nick not in self.users:
            return
        info = self.users[nick]
        if nick not in self.users_zb:
            self.users_zb[nick] = IRCUser(nick, info['username'],
                                          info['realname'],
                                          hostname=info['hostname'])
        else:
            zb_user = self.users_zb[nick]
            zb_user.name = nick
            for attr in ['user', 'real', 'host']:
                setattr(zb_user, f'{attr}name', info[f'{attr}name'])

    def _sync_channel_modes(self, channel):
        """Sync ZeroBot `Channel` modes with pydle."""
        self.channels_zb[channel].modes = self.channels[channel]['modes']

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

    async def on_mode_change(self, channel, modes, nick):
        """Handle channel mode change."""
        await super().on_mode_change(channel, modes, nick)
        self._sync_channel_modes(channel)

    async def on_user_mode_change(self, modes):
        """Handle user mode change."""
        await super().on_user_mode_change(modes)
        self.user.modes = modes

    async def on_raw_324(self, message):
        """Handle RPL_CHANNELMODEIS."""
        await super().on_raw_324(message)
        self._sync_channel_modes(message.params[1])

    async def on_join(self, channel, who):
        """Handle someone joining a channel."""
        await super().on_join(channel, who)

        zb_channel = self.channels_zb[channel]
        zb_user = self.users_zb[who]
        await CORE.module_send_event('join', self, zb_channel, zb_user)

    async def on_message(self, destination: str, source: str, message: str):
        await super().on_message(destination, source, message)

        # TODO: time attribute, ircv3 tags
        msg = IRCMessage(source, destination, message, None, {})
        await CORE.module_send_event('message', self, msg)

    async def module_join(self, where, password=None):
        logger.info(f'Joining channel {where}')
        await self.join(where, password)

    # TODO: use default part message from config, if available
    async def module_leave(self, where, reason=None):
        if reason is None:
            reason = 'No reason given.'
        logger.info(f'Leaving channel {where} ({reason})')
        await self.part(where, reason)

    async def module_message(self, destination, message):
        await self.message(destination, message)
