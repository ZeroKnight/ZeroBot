"""common/abc.py

Provides protocol-agnostic abstract base classes used throughout ZeroBot.
"""

from abc import ABCMeta, abstractmethod
from datetime import datetime

class ProtocolDetails(metaclass=ABCMeta):
    """An abstract mixin that refers back to a specialized protocol object.

    Used in all of ZeroBot's generic protocol entity abstract classes.
    """

    @property
    def protocol(self):
        """str: The protocol where this protocol object originated from.

        Feature modules may check against this property to implement
        protocol-specific behavior.
        """
        return __name__

    @property
    @abstractmethod
    def original(self):
        """Any: A reference to the original protocol object.

        This is the specialized, non-generic version created by the protocol
        itself.
        """
        raise NotImplementedError


class User(ProtocolDetails, metaclass=ABCMeta):
    """An ABC representing an individual that is connected on a protocol.

    This is a general interface that is protocol-agnostic and must be
    specialized by protocol modules.

    Attributes
    ----------
    name: str
        The name of the User; should represent the display name or nickname,
        depending on the protocol.
    username: Optional[str]
        The username of the User; should represent some kind of login or account
        name associated with the User. If username is ``None``, then it should
        be equal to the nickname.
    bot: bool
        Whether or not this user is a bot; False by default.
    """

    @abstractmethod
    def mention(self):
        """Returns a string appropriate to "mention" a user.

        Mentioning a user typically notifies or alerts them in some way; the
        proper syntax varies between protocols.
        """
        raise NotImplementedError

    @abstractmethod
    def mentioned(self, message: 'Message') -> bool:
        """Check if the user was mentioned in the given message."""
        raise NotImplementedError


class Server(ProtocolDetails, metaclass=ABCMeta):
    """Represents an arbitrary host that can be connected to.

    The specifics of what constitutes a Server is dependent upon the
    implementing protocol. In general, a Server represents an arbitrary host
    that must be connected to in order to interact with Users and/or Channels.

    Attributes
    ----------
    hostname: str
        An address or unique identifier that is used to reach the Server.
    port: int
        The port to connect on. Default ports vary between protocols.
    name: str
        User-defined friendly name for this server; may be any arbitrary name.
        If ``None``, will fall back to hostname.
    ipv6: bool
        Whether or not the connection uses IPv6.
    """

    @abstractmethod
    def __eq__(self, other):
        raise NotImplementedError

    @abstractmethod
    def connected(self) -> bool:
        """Whether or not the Server is currenlty connected."""
        raise NotImplementedError


class Message(ProtocolDetails, metaclass=ABCMeta):
    """Represents a message sent by a network entity via a protocol.

    Messages consist of a source and a destination, either of which could be
    a User, Channel, or a Server, depending on the type and context of the
    message.

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
    """

    @abstractmethod
    def __eq__(self, other):
        raise NotImplementedError

    def __len__(self):
        return len(self.contents)


class Channel(ProtocolDetails, metaclass=ABCMeta):
    """Represents some kind of communication destination for Messages.

    The specifics of what constitutesa Channel is dependent upon the
    implementing protocol. In general, a Channel represents a medium that can
    pass along messages between Users, e.g. an IRC or Discord channel, group
    chat, or even a single User.

    Attributes
    ----------
    name: str
        The name of the Channel.
    password: Optional[str]
        The password required to communicate on the Channel. Can be ``None`` if
        no password is required, or is not applicable.
    """

    @abstractmethod
    def __eq__(self, other):
        raise NotImplementedError
