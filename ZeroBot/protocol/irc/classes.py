"""protocol/irc/classes.py

IRC implementation of ZeroBot.common.abc classes.
"""

import re
from datetime import datetime
from typing import Dict, Optional, Union

import ZeroBot.common.abc as abc


class IRCUser(abc.User):
    """Represents a user connected to an IRC server.

    Parameters
    ----------
    name: str
        The nickname of the user.
    username: str, optional
        The username of the user, typically the reported username of their host
        device. If `None`, defaults to a lowercase version of `name`.
    realname: str, optional
        The real name of the user. If `None`, defaults to `name`.
    hostname: str, optional
        The hostname of the user, i.e. their source address. If unspecified,
        will be set to `None` to indicate that it is not yet known, and may be
        set later.
    bot: bool, optional
        Whether or not this user is a bot; `False` by default.

    Attributes
    ----------
    mask: str
        The user/host mask of this user, in the form of `nick!user@host`.
    """

    def __init__(self, name: str, username: str = None, realname: str = None,
                 *, hostname: Optional[str] = None, bot: bool = False):
        self.name = name
        self.username = username or name.lower()
        self.realname = realname or name
        self.hostname = hostname
        self.bot = bot
        self.mask = f'{self.name}!{self.username}@{self.hostname}'

    @classmethod
    def from_mask(cls, mask: str, realname: str, bot: bool = False):
        """Constructs an User object from a user/host mask.

        The mask should be in the form of `nick!user@host`.
        """
        nick, user, host = re.split(r'[!@]', mask, maxsplit=2)
        return cls(nick, user, realname, host, bot)

    def __repr__(self):
        attrs = ['name', 'username', 'realname', 'hostname', 'mask', 'bot']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.name

    @property
    def original(self):
        return self

    def mention(self):
        """Returns a string appropriate to "mention" a user.

        Mentioning a user on IRC is also referred to as "pinging" a user, as it
        causes their client to alert them to the message.
        """
        return f'{self.name}:'

    def mentioned(self, message: 'Message'):
        """Check if the user was mentioned in the given message."""
        raise NotImplementedError('Need to implement Message class')

    def idented(self):
        """Check if the user supplied an ident response on connecting.

        This is a naive check, as a server may not check for an ident response,
        and server-enforced username prefixes are not standardized.
        """
        return not self.username.startswith('~')


class IRCServer(abc.Server):
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
        The IRC network that this server belongs to. This is the name that
        shows up in the "Welcome to the <name> IRC Network" message on
        connection in ``RPL_WELCOME`` and the ``NETWORK`` key in
        ``RPL_ISUPPORT``.
    """

    def __init__(self, hostname: str, port: int = None, *, name: str = None,
                 ipv6: bool = False, tls: bool = False, password: str = None,
                 network: str = None):
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
        attrs = ['hostname', 'port', 'tls', 'password', 'name']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.name if self.name is not None else self.hostname

    def __eq__(self, other):
        return ((self.hostname, self.port, self.tls) ==
                (other.hostname, other.port, other.tls))

    @property
    def original(self):
        return self

    def connected(self) -> bool:
        """Whether or not the Server is currenlty connected."""
        raise NotImplementedError('TODO')


class IRCChannel(abc.Channel):
    """Represents a channel on an IRC network.

    Attributes
    ----------
    name: str
        The name of the channel, including the prefix.
    password: Optional[str]
        The password (or "key") used to gain access to channels with mode +k
        enabled, or ``None`` otherwise.
    """

    # Match valid channel prefixes
    _chanprefix = r'[#&!+]#?'

    def __init__(self, name: str, password: str = None):
        self.name = name
        self.password = password

    def __repr__(self):
        attrs = ['name', 'password']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    @property
    def original(self):
        return self

    def prefix(self):
        """Return the channel prefix."""
        return _chanprefix.match(self.name).group()

    def unprefixed(self):
        """Return the bare channel name, i.e. with no prefix."""
        return _chanprefix.sub('', self.name)


class IRCMessage(abc.Message):
    """Represents a message on an IRC network.

    Attributes
    ----------
    source: Union[User, Channel, Server]
        Where the message came from.
    destination: Union[User, Channel, Server]
        Where the message is being sent.
    content: str
        The contents of the message.
    time: datetime
        The time that the message was sent, in UTC.
    tags: Dict[str, Optional[str]]
        A dictionary containing any IRCv3 tags present in the message, mapped to
        their optional values. A tag with no value is assigned ``None``.
    """

    def __init__(self, source: Union[IRCUser, IRCChannel, IRCServer],
                 destination: Union[IRCUser, IRCChannel, IRCServer],
                 content: str, time: datetime, tags: Dict[str, Optional[str]]):
        self.source = source
        self.destination = destination
        self.content = content
        self.time = time
        self.tags = tags

    def __repr__(self):
        attrs = ['source', 'destination', 'content', 'time']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.content

    def __eq__(self, other):
        return self.content == other.content

    @property
    def original(self):
        return self
