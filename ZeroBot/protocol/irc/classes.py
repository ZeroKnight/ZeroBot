"""protocol/irc/classes.py

IRC implementation of ZeroBot.common.abc classes.
"""

import datetime
import re
from typing import Dict, Optional, Union

from dateutil.parser import isoparse

import ZeroBot.common.abc as abc

from .util import irc_time_format


class IRCUser(abc.User):
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
    away : bool
    away_msg : str or None
    mask : str
    """

    def __init__(self, name: str, username: str = None, realname: str = None,
                 *, hostname: Optional[str] = None, modes: dict = None,
                 bot: bool = False):
        self._away_msg = None
        self.name = name
        self.username = username or name.lower()
        self.realname = realname or name
        self.hostname = hostname
        self.modes = modes
        self.bot = bot

    @classmethod
    def from_mask(cls, mask: str, realname: str, bot: bool = False):
        """Constructs an User object from a user/host mask.

        The mask should be in the form of `nick!user@host`.
        """
        nick, user, host = re.split(r'[!@]', mask, maxsplit=2)
        return cls(nick, user, realname, hostname=host, bot=bot)

    def __repr__(self):
        attrs = ['mask', 'realname', 'modes', 'away', 'away_msg', 'bot']
        return f"<{self.__class__.__name__} {' '.join(f'{a}={getattr(self, a)}' for a in attrs)}>"

    def __str__(self):
        return self.name

    @property
    def original(self):
        return self

    @property
    def away(self) -> bool:
        """Whether or not this user is currently marked as away.

        Pass a string to set this user as away with the string as the away
        message.
        """
        return self._away_msg is not None

    @property
    def away_msg(self) -> Optional[str]:
        """The user's away message, if they're marked as away.

        If the user is not currently marked as away, returns `None` instead.
        """
        return self._away_msg

    @property
    def mask(self):
        """The user/host mask of this user, in the form of `nick!user@host`."""
        return f'{self.name}!{self.username}@{self.hostname}'

    def mention(self):
        """Returns a string appropriate to "mention" a user.

        Mentioning a user on IRC is also referred to as "pinging" a user, as it
        causes their client to alert them to the message.
        """
        return f'{self.name}:'

    def mentioned(self, message: 'IRCMessage'):
        """Check if the user was mentioned in the given message."""
        raise NotImplementedError('Need to implement Message class')

    def idented(self):
        """Check if the user supplied an ident response on connecting.

        This is a naive check, as a server may not check for an ident response,
        and server-enforced username prefixes are not standardized.
        """
        return not self.username.startswith('~')

    def set_away(self, message: str):
        """Set this user as away with the given message."""
        self._away_msg = message

    def set_back(self):
        """Set this user as no longer away."""
        self._away_msg = None


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
        The IRC network that this server belongs to, which equals the name from
        the ``Network`` section of the IRC configuration file.
    reported_network : str
        This is the name that shows up in the "Welcome to the <name> IRC
        Network" message on connection in ``RPL_WELCOME`` and the ``NETWORK``
        key in ``RPL_ISUPPORT``.
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
        return f"<{self.__class__.__name__} {' '.join(f'{a}={getattr(self, a)}' for a in attrs)}>"

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
    name : str
        The name of the channel, including the prefix.
    password : str, optional
        The password (or "key") used to gain access to channels with mode +k
        enabled, or `None` otherwise.
    modes : dict
        The modes set on the channel.
    """

    # Match valid channel prefixes
    _chanprefix = re.compile(r'^[#&!+]#?')

    def __init__(self, name: str, *, password: str = None, modes=None):
        self.name = name
        self.password = password
        self.modes = modes or {}

    def __repr__(self):
        attrs = ['name', 'password', 'modes']
        return f"<{self.__class__.__name__} {' '.join(f'{a}={getattr(self, a)}' for a in attrs)}>"

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
        return self._chanprefix.sub('', self.name)


class IRCMessage(abc.Message):
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
    tags : Dict[str, Optional[str]]
        A dictionary containing any IRCv3 tags present in the message, mapped
        to their optional values. A tag with no value is assigned `None`.
    """

    def __init__(self, source: Union[IRCUser, IRCServer],
                 destination: Union[IRCUser, IRCChannel],
                 content: str, *, time: datetime.datetime = None,
                 tags: Dict[str, Optional[str]] = None):
        self.source = source
        self.destination = destination
        self.content = content
        self.tags = tags or {}
        if time:
            self.time = time
        elif 'time' in self.tags:
            self.time = isoparse(self.tags['time'])
        else:
            self.time = datetime.datetime.now(datetime.timezone.utc)
        if 'time' not in self.tags:
            self.tags['time'] = irc_time_format(self.time)

    def __repr__(self):
        attrs = ['source', 'destination', 'content', 'tags']
        return f"<{self.__class__.__name__} {' '.join(f'{a}={getattr(self, a)}' for a in attrs)}>"

    def __str__(self):
        return self.content

    def __eq__(self, other):
        return self.content == other.content

    @property
    def original(self):
        return self
