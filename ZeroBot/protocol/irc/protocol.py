"""protocol/irc/protocol.py

IRC protocol implementation.
"""

import asyncio
import logging
from typing import Any, List

import pydle
from pydle.features.ircv3.tags import TaggedMessage

from ZeroBot.protocol.context import Context

from .classes import IRCChannel, IRCMessage, IRCServer, IRCUser

MODULE_NAME = 'IRC'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'IRC protocol implementation'

CORE = None
CFG = None

# TODO: get this programatically and include network name
logger = logging.getLogger('ZeroBot.IRC')


def module_register(core, cfg):
    """Initialize module."""
    global CORE, CFG
    CORE = core
    CFG = cfg

    def network_fallback(section: dict, key: str, fallback: Any = None) -> Any:
        try:
            return section[key]
        except KeyError:
            return CFG['Network_Defaults'].get(key, fallback)

    networks = {}
    if 'Network' in CFG:
        for network, settings in CFG['Network'].items():
            networks[network] = {}
            if not settings.get('AutoConnect', False):
                continue  # TEMP
            if 'Servers' not in settings:
                logger.error(f'No servers specified for network {network}!')
                continue
            networks[network]['fallback_nicks'] = network_fallback(
                settings, 'Fallback_Nicks', [])
            networks[network]['servers'] = []
            for server in settings['Servers']:
                host, *port = server.split(':')
                server_info = {
                    'network': network,
                    'hostname': host,
                    'port': port or None,
                    'password': settings.get('Password', None),
                    'tls': network_fallback(settings, 'UseTLS'),
                    'ipv6': network_fallback(settings, 'UseIPv6')
                }
                networks[network]['servers'].append(IRCServer(**server_info))
            user_info = {
                'name': network_fallback(settings, 'Nickname'),
                'username': network_fallback(settings, 'Username'),
                'realname': network_fallback(settings, 'Realname')
            }
            networks[network]['user'] = IRCUser(**user_info)
    else:
        # TODO: how to handle failed module init?
        logger.warning('No networks defined in configuration.')
        raise NotImplementedError

    connections = set()
    for network in networks.values():
        ctx = IRCContext(network['user'], network['servers'][0],
                         fallback_nicknames=network['fallback_nicks'],
                         eventloop=core.eventloop)
        coro = ctx.connect(ctx.server.hostname)
        connections.add((ctx, coro))
    return connections


def module_unregister():
    """Prepare for shutdown."""


class IRCContext(Context, pydle.Client):
    """IRC implementation of a ZeroBot `Context`."""

    def __init__(self, user: IRCUser, server: IRCServer, *,
                 eventloop: asyncio.AbstractEventLoop,
                 fallback_nicknames: List = None):
        self.channels_zb = {}
        self.server = server
        self.user = user
        self.users_zb = {user.name: user}
        super().__init__(
            user.name, fallback_nicknames or [], user.username, user.realname,
            eventloop=eventloop
        )

    def _create_channel(self, channel):
        super()._create_channel(channel)
        self.channels_zb[channel] = IRCChannel(channel)

    def _sync_user(self, nickname, metadata):
        super()._sync_user(nickname, metadata)
        # Keep ZeroBot User objects in sync
        if nickname not in self.users:
            return
        info = self.users[nickname]
        if nickname not in self.users_zb:
            zb_user = IRCUser(
                nickname, info['username'], info['realname'],
                hostname=info['hostname']
            )
            self.users_zb[nickname] = zb_user
        else:
            zb_user = self.users_zb[nickname]
            zb_user.name = nickname
            for attr in ['user', 'real', 'host']:
                setattr(zb_user, f'{attr}name', info[f'{attr}name'])
        if metadata.get('away', False):
            zb_user.set_away(metadata['away_message'])
        else:
            zb_user.set_back()

    def _rename_user(self, user, new):
        super()._rename_user(user, new)
        # Keep ZeroBot objects in sync
        self.users_zb[user].name = new
        self.users_zb[new] = self.users_zb[user]
        del self.users_zb[user]
        if self.is_same_nick(new, self.user.name):
            self.user = self.users_zb[new]
        for channel in self.channels_zb:
            self._sync_channel_modes(channel)

    def _sync_channel_modes(self, channel):
        """Sync ZeroBot `Channel` modes with pydle."""
        self.channels_zb[channel].modes = self.channels[channel]['modes']

    def _create_zbmessage(self, message: TaggedMessage) -> IRCMessage:
        """Create a `IRCMessage` based on a pydle `TaggedMessage`."""
        name = self._parse_user(message.source)[0]
        destination, content = message.params
        try:
            source = self.users_zb[name]
        except KeyError:
            if '.' in name:
                source = self.server
            else:
                raise
        return IRCMessage(source, destination, content, tags=message.tags)

    # Pydle handlers

    async def on_raw(self, message):
        """Handle raw IRC message."""
        logger.debug(f"[RAW] {message}".rstrip())
        await super().on_raw(message)

    async def on_raw_001(self, message):
        """Handle ``RPL_WELCOME``."""
        await super().on_raw_001(message)
        self.server.servername = message.source

    # NOTE: pydle.features.ISUPPORTSupport defines on_raw_005 to set some
    # attributes like self.reported_network and implement the on_isupport_*
    # methods. Be sure to call it if extending here.

    async def on_isupport_network(self, value):
        """Handle ``NETWORK`` key in ``RPL_ISUPPORT``."""
        await super().on_isupport_network(value)
        self.server.reported_network = value

    async def on_connect(self):
        """Handle successful connection registration.

        Pydle calls this after ``RPL_ENDOFMOTD`` or ``ERR_NOMOTD``.
        """
        await super().on_connect()

        # Get our user info as reported by the server
        await self.rawmsg('WHOIS', self.user.name)

        logger.info(
            f'Connected to {self.server.network} at {self.server.hostname}')
        await CORE.module_send_event('connect', self)

        to_join = CFG['Network'][self.server.network].get('Channels', [])
        for channel in to_join:
            await self.module_join(channel)

    async def on_raw_302(self, message):
        """Handle ``RPL_USERHOST``."""
        # Update self.users for pydle
        for user in message.params[1].rstrip().split(' '):
            nickname, userhost = user.split('=', 1)
            username, hostname = userhost[1:].split('@', 1)
            self._sync_user(nickname, {
                'username': username,
                'hostname': hostname
            })

    async def on_mode_change(self, channel, modes, nick):
        """Handle channel mode change."""
        await super().on_mode_change(channel, modes, nick)
        self._sync_channel_modes(channel)

    async def on_user_mode_change(self, modes):
        """Handle user mode change."""
        await super().on_user_mode_change(modes)
        self.user.modes = modes

    async def on_nick_change(self, old, new):
        """Handle nickname change (NICK)."""
        if self.is_same_nick(self.user.name, old):
            # NOTE: on_raw_nick handles updating self.user
            logger.info(f'Nick changed from {old} to {new}')

    async def on_raw_324(self, message):
        """Handle ``RPL_CHANNELMODEIS``."""
        await super().on_raw_324(message)
        self._sync_channel_modes(message.params[1])

    async def on_raw_352(self, message):
        """Handle ``RPL_WHOREPLY``."""
        metadata = {
            'username': message.params[2],
            'hostname': message.params[3],
            'nickname': message.params[5],
            'realname': message.params[7].split(' ', 1)[1]
        }
        self._sync_user(metadata['nickname'], metadata)

    async def on_raw_421(self, message):
        """Handle ``ERR_UNKNOWNCOMMAND``."""
        await super().on_raw_421(message)
        logger.warning(f'Unknown command: {message.params[1]}')

    async def on_raw_432(self, message):
        """Handle ``ERR_ERRONEOUSNICKNAME``."""
        super().on_raw_432(message)
        logger.error(
            f"Invalid nickname: '{message.params[1]}'. Trying next fallback.")

    async def on_raw_433(self, message):
        """Handle ``ERR_NICKNAMEINUSE``."""
        super().on_raw_433(message)
        logger.error(f"Nickname is already in use: '{message.params[1]}'. "
                     'Trying next fallback.')

    async def on_join(self, channel, who):
        """Handle someone joining a channel."""
        await super().on_join(channel, who)

        # Get user information
        await self.rawmsg('WHO', channel)

        zb_channel = self.channels_zb[channel]
        zb_user = self.users_zb[who]
        await CORE.module_send_event('join', self, zb_channel, zb_user)

    async def on_raw_privmsg(self, message: TaggedMessage):
        """Handler for all messages (PRIVMSG)."""
        await super().on_raw_privmsg(message)
        zb_msg = self._create_zbmessage(message)
        await CORE.module_send_event('message', self, zb_msg)

    async def on_raw_notice(self, message: TaggedMessage):
        """Handler for all notices (NOTICE)."""
        await super().on_raw_notice(message)
        zb_msg = self._create_zbmessage(message)
        await CORE.module_send_event('irc_notice', self, zb_msg)

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

        # If echo-message is unavailable, pydle works around this by explicitly
        # calling on_*message for messages it sends. However, pydle does not
        # (yet) send the time tag to these callbacks; it is only available in
        # on_raw_privmsg. We'll do basically the same here. Supplying our own
        # timestamp is not technically correct, but better than none at all.
        if not self._capabilities.get('echo-message', False):
            zb_msg = IRCMessage(self.user.name, destination, message)
            await CORE.module_send_event('message', self, zb_msg)
