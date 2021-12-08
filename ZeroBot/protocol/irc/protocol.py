"""protocol/irc/protocol.py

IRC protocol implementation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

import pydle
from pydle.features.ircv3.tags import TaggedMessage

from ZeroBot.config import Config

from ..context import Context
from .classes import IRCChannel, IRCMessage, IRCServer, IRCUser

MODULE_NAME = "IRC"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.1"
MODULE_LICENSE = "MIT"
MODULE_DESC = "IRC protocol implementation"

CORE = None
CFG = None

logger = logging.getLogger("ZeroBot.IRC")


async def module_register(core, cfg):
    """Initialize module."""
    global CORE, CFG
    CORE = core
    CFG = cfg

    connections = set()
    for network in _configure(CFG):
        ctx = IRCContext(
            network["user"],
            network["servers"],
            fallback_nicknames=network["alt_nicks"],
            request_umode=network["request_umode"],
            **network["sasl"],
            eventloop=core.eventloop,
        )
        coro = ctx._connect_loop()
        connections.add((ctx, coro))
    return connections


async def module_unregister(contexts, reason: str = None):
    """Prepare for shutdown."""
    for ctx in contexts:
        await ctx.quit(reason)


def _configure(cfg: Config) -> list[dict]:
    """Set up IRC connections based on the given parsed configuration."""

    settings_default = {
        "Settings": {
            "ConnectTimeout": 30,
            "AutoReconnect": {
                "Enabled": True,
                "Delay": {"Seconds": 10, "GrowthFactor": 2, "MaxSeconds": 900},
            },
        }
    }
    CFG["Settings"] = {**settings_default, **CFG.get("Settings", {})}

    networks = []
    if "Network" not in cfg or len(cfg["Network"]) == 0:
        msg = "No networks defined in configuration."
        logger.error(msg)
        raise RuntimeError(msg)
    for name, settings in cfg["Network"].items():
        settings = cfg.make_fallback(settings, cfg["Network_Defaults"])
        if not settings.get("AutoConnect", False):
            continue  # TEMP
        if "Servers" not in settings:
            logger.error(f"No servers specified for network '{name}'!")
            continue
        servers = []
        for server in settings["Servers"]:
            host, _, port = server.partition(":")
            server_info = {
                "network": name,
                "hostname": host,
                "port": port or None,
                "password": settings.get("Password", None),
                "tls": settings.get("UseTLS", False),
                "ipv6": settings.get("UseIPv6", False),
            }
            servers.append(IRCServer(**server_info))
        user_info = {
            "name": settings["Nickname"],
            "username": settings["Username"],
            "realname": settings["Realname"],
        }
        sasl_settings = cfg.make_fallback(settings.get("SASL", {}), cfg["Network_Defaults"].get("SASL", {}))
        network = {
            "user": IRCUser(**user_info),
            "servers": servers,
            "alt_nicks": settings.get("Alt_Nicks", None),
            "request_umode": settings.get("UMode", None),
            "sasl": {
                "sasl_username": sasl_settings.get("Username", None),
                "sasl_password": sasl_settings.get("Password", None),
                "sasl_mechanism": sasl_settings.get("Mechanism", None),
            },
        }
        networks.append(network)
    return networks


class IRCContext(Context, pydle.Client):
    """IRC implementation of a ZeroBot `Context`."""

    def __init__(
        self,
        user: IRCUser,
        servers: list[IRCServer],
        *,
        eventloop: asyncio.AbstractEventLoop,
        request_umode: str = None,
        fallback_nicknames: list = None,
        **kwargs,
    ):
        super().__init__(
            user.name,
            fallback_nicknames or [],
            user.username,
            user.realname,
            eventloop=eventloop,
            **kwargs,
        )
        self._request_umode = request_umode
        self.channels_zb = {}
        self.servers = servers
        self._server = servers[0]
        self.user = user
        self.users_zb = {user.name: user}
        self.logger = logging.getLogger(f"ZeroBot.IRC.{self.server.network}")

    @property
    def server(self) -> IRCServer:
        """Get the active `IRCServer` connection."""
        return self._server

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
            zb_user = IRCUser(nickname, info["username"], info["realname"], hostname=info["hostname"])
            self.users_zb[nickname] = zb_user
        else:
            zb_user = self.users_zb[nickname]
            zb_user.name = nickname
            for attr in ["user", "real", "host"]:
                setattr(zb_user, f"{attr}name", info[f"{attr}name"])
        if metadata.get("away", False):
            zb_user.set_away(metadata["away_message"])
        else:
            zb_user.set_back()
        if metadata.get("identified", False):
            zb_user.set_auth(metadata["account"])
        else:
            zb_user.set_auth(None)

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
        self.channels_zb[channel].modes = self.channels[channel]["modes"]

    def _create_zbmessage(self, message: TaggedMessage) -> IRCMessage:
        """Create a `IRCMessage` based on a pydle `TaggedMessage`."""
        name = self._parse_user(message.source)[0]
        destination, content = message.params
        try:
            source = self.users_zb[name]
        except KeyError:
            if "." in name:
                source = self.server
            else:
                raise
        return IRCMessage(source, destination, content, tags=message.tags)

    # TODO: External way to stop loop
    async def _connect_loop(self, reconnect: bool = False):
        """Attempt to (re)connect to the configured network.

        If a server connection fails and ``Settings.AutoReconnect.Enabled`` is
        `True`, the next server in `self.servers` is tried until one
        successfully connects. If we run out of servers to try, then try the
        server list over again with a growing delay.
        """
        reconn_settings = CFG["Settings"]["AutoReconnect"]
        delay_settings = reconn_settings["Delay"]
        delay = delay_settings["Seconds"]
        growth = delay_settings["GrowthFactor"]
        delay_max = delay_settings["MaxSeconds"]

        autoreconnect = True
        while autoreconnect:
            autoreconnect = reconn_settings["Enabled"]
            for server in self.servers:
                established = await self.connect(
                    server.hostname,
                    server.port,
                    server.tls,
                    tls_verify=False,
                    reconnect=reconnect,
                    timeout=CFG["Settings"]["ConnectTimeout"],
                )
                if established:
                    self._server = server
                    return
            self.logger.info(f"Attempting to reconnect in {delay} seconds.")
            await asyncio.sleep(delay)
            delay = min(delay_max, delay * growth)

    async def connect(
        self,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        tls: bool = False,
        timeout: Union[int, float] = 30,
        **kwargs,
    ) -> bool:
        """Connect to an IRC server.

        Attempts to connect to an IRC server and begin handling IRC events.

        Parameters
        ----------
        hostname : str, optional
            The host to connect to. If omitted and `reconnect` is `True`,
            Pydle will try to reconnect to the current host.
        port : int, optional
            The port to connect on.
        tls : bool, optional
            Whether or not to connect securely via TLS; `False` by default.
        timeout : int or float, optional
            Maximum time to wait for the connection to succeed before giving
            up; 30 seconds by default.
        **kwargs
            Any extra keyword arguments are passed to `pydle.Client.connect`.

        Returns
        -------
        bool
            Whether or not the connection succeeded.
        """
        addr = hostname + (f":{port}" if port else "")
        self.logger.info(f"Connecting to server {addr} ...")
        # Preserve our logger so we receive pydle log records
        logger_save = self.logger
        try:
            await asyncio.wait_for(super().connect(hostname, port, tls, **kwargs), timeout)
        except OSError as ex:
            self.logger.error(f"Connection to {addr} failed: {ex}")
            return False
        except asyncio.TimeoutError:
            self.logger.error(f"Connection to {addr} timed out.")
            return False
        self.logger = logger_save
        return True

    # Pydle handlers

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
        self.server.connected = True

        # Get our user info as reported by the server
        await self.rawmsg("WHOIS", self.user.name)

        logger.info(f"Connected to {self.server.network} at {self.server.hostname}")
        await CORE.module_send_event("connect", self)
        if self._request_umode:
            await self.rawmsg("MODE", self.user.name, self._request_umode)

        config = CFG["Network"][self.server.network]
        for target in config.get("Monitor", []):
            await self.monitor(target)
        for channel in config.get("Channels", []):
            await self.module_join(channel)

    async def on_disconnect(self, expected: bool):
        """Handle disconnection from server."""
        if not expected:
            msg = f"Lost connection to network {self._server.network}."
            if CFG["Settings"]["AutoReconnect"]["Enabled"]:
                delay = CFG["Settings"]["AutoReconnect"]["Delay"]["Seconds"]
                self.logger.error(f"{msg} Retrying in {delay} seconds.")
                asyncio.sleep(delay)
                await self._connect_loop(True)
            else:
                self.logger.error(msg)

    async def on_raw_302(self, message):
        """Handle ``RPL_USERHOST``."""
        # Update self.users for pydle
        for user in message.params[1].rstrip().split(" "):
            nickname, userhost = user.split("=", 1)
            username, hostname = userhost[1:].split("@", 1)
            self._sync_user(nickname, {"username": username, "hostname": hostname})

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
            logger.info(f"Nick changed from {old} to {new}")

    async def on_raw_324(self, message):
        """Handle ``RPL_CHANNELMODEIS``."""
        await super().on_raw_324(message)
        self._sync_channel_modes(message.params[1])

    async def on_raw_352(self, message):
        """Handle ``RPL_WHOREPLY``."""
        metadata = {
            "username": message.params[2],
            "hostname": message.params[3],
            "nickname": message.params[5],
            "realname": message.params[7].split(" ", 1)[1],
        }
        self._sync_user(metadata["nickname"], metadata)

    async def on_raw_432(self, message):
        """Handle ``ERR_ERRONEOUSNICKNAME``."""
        super().on_raw_432(message)
        logger.error(f"Invalid nickname: '{message.params[1]}'. Trying next fallback.")

    async def on_raw_433(self, message):
        """Handle ``ERR_NICKNAMEINUSE``."""
        super().on_raw_433(message)
        logger.error(f"Nickname is already in use: '{message.params[1]}'. Trying next fallback.")

    async def on_join(self, channel, who):
        """Handle someone joining a channel."""
        await super().on_join(channel, who)

        # Get user information
        await self.rawmsg("WHO", channel)

        zb_channel = self.channels_zb[channel]
        zb_user = self.users_zb[who]
        await CORE.module_send_event("join", self, zb_channel, zb_user)

    async def on_raw_privmsg(self, message: TaggedMessage):
        """Handler for all messages (PRIVMSG)."""
        await super().on_raw_privmsg(message)
        zb_msg = self._create_zbmessage(message)
        await CORE.module_send_event("message", self, zb_msg)

    async def on_raw_notice(self, message: TaggedMessage):
        """Handler for all notices (NOTICE)."""
        await super().on_raw_notice(message)
        zb_msg = self._create_zbmessage(message)
        await CORE.module_send_event("irc_notice", self, zb_msg)

    async def on_raw_730(self, message: TaggedMessage):
        """Handler for ``RPL_MONONLINE``."""
        await super().on_raw_730(message)
        for user in message.params[1].split(","):
            nick, user, host = IRCUser.parse_mask(user)
            if user and host:
                self.logger.info(f"{nick} ({user}@{host}) is online.")
            else:
                self.logger.info(f"{nick} is online.")
            await CORE.module_send_event("user_online", self, self.users_zb[nick])

    async def on_raw_731(self, message: TaggedMessage):
        """Handler for ``RPL_MONOFFLINE``."""
        await super().on_raw_731(message)
        for target in message.params[1].split(","):
            nick, user, host = IRCUser.parse_mask(target)
            if user and host:
                self.logger.info(f"{nick} ({user}@{host}) is offline.")
            else:
                self.logger.info(f"{nick} is offline.")
            if nick in self.users_zb:
                zb_user = self.users_zb[nick]
            else:
                zb_user = IRCUser(nick, user, hostname=host)
            await CORE.module_send_event("user_offline", self, zb_user)

    # ZeroBot Interface

    async def module_join(self, where, password=None):
        logger.info(f"Joining channel {where}")
        await self.join(where, password)

    async def module_leave(self, where, reason=None):
        if reason is None:
            cfg = CFG.make_fallback(CFG["Network"][self._server.network], CFG["Network_Defaults"])
            reason = cfg.get("PartMsg", "No reason given.")
        logger.info(f"Leaving channel {where} ({reason})")
        await self.part(where, reason)

    async def module_quit(self, reason=None):
        if reason is None:
            cfg = CFG.make_fallback(CFG["Network"][self._server.network], CFG["Network_Defaults"])
            reason = cfg.get("QuitMsg", "No reason given.")
        network = self._server.network
        logger.info(f"Quitting from network {network} ({reason})")
        await self.quit(reason)

    async def module_message(self, destination, message):
        await self.message(destination, message)

        # If echo-message is unavailable, pydle works around this by explicitly
        # calling on_*message for messages it sends. However, pydle does not
        # (yet) send the time tag to these callbacks; it is only available in
        # on_raw_privmsg. We'll do basically the same here. Supplying our own
        # timestamp is not technically correct, but better than none at all.
        if not self._capabilities.get("echo-message", False):
            zb_msg = IRCMessage(self.user.name, destination, message)
            await CORE.module_send_event("message", self, zb_msg)
