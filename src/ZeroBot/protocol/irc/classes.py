"""protocol/irc/classes.py

IRC implementation of ZeroBot.context classes.
"""

from __future__ import annotations

import datetime
import re
from itertools import chain, islice, repeat

import ZeroBot.context as zctx
from ZeroBot.util import gen_repr, parse_iso_format

from .util import UserTuple, irc_time_format


class IRCUser(zctx.User):
    """Represents a user connected to an IRC server.

    Parameters
    ----------
    name : str
        The nickname of the user.
    username : str, optional
        The username of the user, typically the reported username of their host
        device. If `None`, defaults to a lowercase version of `name`.
    realname : str, optional
        The real name of the user. If `None`, defaults to `name`.
    hostname : str, optional
        The hostname of the user, i.e. their source address. If unspecified,
        will be set to `None` to indicate that it is not yet known, and may be
        set later.
    modes : dict or None
        The modes set on this user. **Note**: In practice, this only known for
        ZeroBot, as you cannot see other users' modes.
    bot : bool, optional
        Whether or not this user is a bot; `False` by default.

    Attributes
    ----------
    authenticated : bool
    auth_id : str
    away : bool
    away_msg : str or None
    mask : str
    """

    def __init__(
        self,
        name: str,
        username: str | None = None,
        realname: str | None = None,
        *,
        hostname: str | None = None,
        modes: dict | None = None,
        bot: bool = False,
    ):
        self._auth_id = None
        self._away_msg = None
        self.name = name
        self.username = username or name.lower()
        self.realname = realname or name
        self.hostname = hostname
        self.modes = modes
        self.bot = bot

    @classmethod
    def parse_mask(cls, mask: str) -> UserTuple:
        """Parse a user/host mask into a 3-tuple of its parts.

        Parameters
        ----------
        mask : str
            A user/host mask of the form ``nick[!user[@host]]``.

        Returns
        -------
        UserTuple
            A 3-tuple consisting of the nickname, username, and hostname of the
            given mask. Each value may be `None` if not present in the mask.
        """
        parts = re.split(r"[!@]", mask, maxsplit=2)
        return tuple(islice(chain(parts, repeat(None, 3)), 3))

    @classmethod
    def from_mask(cls, mask: str, realname: str, bot: bool = False):
        """Constructs an User object from a user/host mask.

        The mask should be in the form of `nick!user@host`.
        """
        nick, user, host = cls.parse_mask(mask)
        return cls(nick, user, realname, hostname=host, bot=bot)

    def __repr__(self):
        attrs = ["mask", "realname", "modes", "auth_id", "away_msg", "bot"]
        return gen_repr(self, attrs)

    def __str__(self):
        return self.name

    @property
    def original(self):
        return self

    @property
    def authenticated(self) -> bool:
        """Whether or not this user is authenticated with services."""
        return self._auth_id is not None

    @property
    def auth_id(self) -> str:
        """The account that this user is authenticated as."""
        return self._auth_id

    @property
    def away(self) -> bool:
        """Whether or not this user is currently marked as away.

        Pass a string to set this user as away with the string as the away
        message.
        """
        return self._away_msg is not None

    @property
    def away_msg(self) -> str | None:
        """The user's away message, if they're marked as away.

        If the user is not currently marked as away, returns `None` instead.
        """
        return self._away_msg

    @property
    def mask(self):
        """The user/host mask of this user, in the form of `nick!user@host`."""
        return f"{self.name}!{self.username}@{self.hostname}"

    def mention(self):
        """Returns a string appropriate to "mention" a user.

        Mentioning a user on IRC is also referred to as "pinging" a user, as it
        causes their client to alert them to the message.
        """
        return f"{self.name}:"

    def mentioned(self, message: IRCMessage):
        """Check if the user was mentioned in the given message."""
        return self.name in message.content

    def idented(self):
        """Check if the user supplied an ident response on connecting.

        This is a naive check, as a server may not check for an ident response,
        and server-enforced username prefixes are not standardized.
        """
        return not self.username.startswith("~")

    def set_auth(self, account: str | None):
        """Set this user as authenticated with the given account name."""
        self._auth_id = account

    def set_away(self, message: str):
        """Set this user as away with the given message."""
        self._away_msg = message

    def set_back(self):
        """Set this user as no longer away."""
        self._away_msg = None


class IRCServer(zctx.Server):
    """Represents a server on an IRC network.

    Attributes
    ----------
    hostname : str
        The hostname of server to connect to.
    port : int
        The port to connect on, defaults to 6667 (or 6697 for TLS connections).
    name : str
        User-defined friendly name for this server; may be any arbitrary name.
        If `None`, will fall back to hostname.
    ipv6 : bool
        Whether or not the connection uses IPv6.
    tls : bool
        Whether or not the connection is using TLS.
    password : str, optional
        The password required to connect to the server, or `None` if a password
        isn't required.
    servername : str
        The name returned by the server. This is typically the same as the
        hostname, however a server can report whatever name it wants, which may
        not match the hostname. Will be `None` until successful connection.
    network : str
        The IRC network that this server belongs to, which equals the name from
        the ``Network`` section of the IRC configuration file.
    reported_network : str
        This is the name that shows up in the "Welcome to the <name> IRC
        Network" message on connection in ``RPL_WELCOME`` and the ``NETWORK``
        key in ``RPL_ISUPPORT``.
    """

    def __init__(
        self,
        hostname: str,
        port: int | None = None,
        *,
        name: str | None = None,
        ipv6: bool = False,
        tls: bool = False,
        password: str | None = None,
        network: str | None = None,
    ):
        self._connected = False
        self.hostname = hostname
        if port is None:
            self.port = 6697 if tls else 6667
        else:
            self.port = port
        self.ipv6 = ipv6
        self.tls = tls
        self.password = password
        self.servername = None
        self.network = network
        self.name = name if name is not None else self.hostname

    def __repr__(self):
        attrs = ["hostname", "port", "password", "tls", "ipv6", "name"]
        return gen_repr(self, attrs)

    def __str__(self):
        return self.name if self.name is not None else self.hostname

    def __eq__(self, other):
        return (self.hostname, self.port, self.tls) == (
            other.hostname,
            other.port,
            other.tls,
        )

    @property
    def original(self):
        return self

    @property
    def connected(self) -> bool:
        """Whether or not the Server is currenlty connected."""
        return self._connected

    @connected.setter
    def connected(self, state: bool):
        self._connected = state


class IRCChannel(zctx.Channel):
    """Represents a channel on an IRC network.

    Attributes
    ----------
    name : str
        The name of the channel, including the prefix.
    password : str, optional
        The password (or "key") used to gain access to channels with mode +k
        enabled, or `None` otherwise.
    modes : dict
        The modes set on the channel.
    """

    # Match valid channel prefixes
    _chanprefix = re.compile(r"^[#&!+]#?")

    def __init__(self, name: str, *, password: str | None = None, modes=None):
        self.name = name
        self.password = password
        self.modes = modes or {}

    def __repr__(self):
        attrs = ["name", "password", "modes"]
        return gen_repr(self, attrs)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    @property
    def original(self):
        return self

    def prefix(self):
        """Return the channel prefix."""
        return self._chanprefix.match(self.name).group()

    def unprefixed(self):
        """Return the bare channel name, i.e. with no prefix."""
        return self._chanprefix.sub("", self.name)


class IRCMessage(zctx.Message):
    """Represents a message on an IRC network.

    Attributes
    ----------
    source : User or Server
        Where the message came from.
    destination : User or Channel
        Where the message is being sent.
    content : str
        The contents of the message.
    time : datetime.datetime
        The time that the message was sent, in UTC.
    tags : dict[str, Optional[str]]
        A dictionary containing any IRCv3 tags present in the message, mapped
        to their optional values. A tag with no value is assigned `None`.
    """

    def __init__(
        self,
        source: IRCUser | IRCServer,
        destination: IRCUser | IRCChannel,
        content: str,
        *,
        time: datetime.datetime | None = None,
        tags: dict[str, str | None] | None = None,
    ):
        self.source = source
        self.destination = destination
        self.content = content
        self.tags = tags or {}
        if time:
            self.time = time
        elif "time" in self.tags:
            self.time = parse_iso_format(self.tags["time"])
        else:
            self.time = datetime.datetime.now(datetime.timezone.utc)
        if "time" not in self.tags:
            self.tags["time"] = irc_time_format(self.time)

    def __repr__(self):
        attrs = ["source", "destination", "content", "tags"]
        return gen_repr(self, attrs)

    def __str__(self):
        return self.content

    def __eq__(self, other):
        return self.content == other.content

    @property
    def original(self):
        return self
