"""protocol/irc/user.py

Implementation of User ABC for the IRC protocol.
"""

import re

import ZeroBot.common

class User(common.User):
    """Represents a user connected to an IRC server.

    Attributes
    ----------
    name: str
        The nickname of the user.
    username: str
        The username of the user, typically the reported username of their host
        device.
    realname: str
        The real name of the user.
    hostname: str
        The hostname of the user, i.e. their source address.
    mask: str
        The user/host mask of this user, in the form of `nick!user@host`.
    bot: bool
        Whether or not this user is a bot; False by default.
    """

    def __init__(self, name: str, username: str, realname: str, hostname: str,
                 bot: bool=False):
        self.name = name
        self.username = username
        self.realname = realname
        self.hostname = hostname
        self.bot = bot
        self.mask = f'{self.name}!{self.username}@{self.hostname}'

    @classmethod
    def from_mask(cls, mask: str, realname: str, bot: bool=False):
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

    def mention(self):
        """Returns a string appropriate to "mention" a user.

        Mentioning a user on IRC is also referred to as "pinging" a user, as it
        causes their client to alert them to the message.
        """
        return f'{self.name}:'

    def mentioned(self, message: Message):
        """Check if the user was mentioned in the given message."""
        raise NotImplementedError('Need to implement Message class')

    def idented(self):
        """Check if the user supplied an ident response on connecting.

        This is a naive check, as a server may not check for an ident response,
        and server-enforced username prefixes are not standardized.
        """
        return not self.username.startswith('~')

