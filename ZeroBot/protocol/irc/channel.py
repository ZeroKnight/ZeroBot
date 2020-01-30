"""protocol/irc/channel.py

Implementation of Channel ABC for the IRC protocol.
"""

import re

import ZeroBot.common

class Channel(common.Channel):
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

    def __init__(self, name: str, password: str=None):
        self.name = name
        self.password = password

    def __repr__(self):
        attrs = ['name', 'password']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    def prefix(self):
        """Return the channel prefix."""
        return _chanprefix.match(self.name).group()

    def unprefixed(self):
        """Return the bare channel name, i.e. with no prefix."""
        return _chanprefix.sub('', self.name)
