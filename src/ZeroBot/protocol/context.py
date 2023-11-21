"""protocol/context.py

A Context represents an individual connection over an arbitrary protocol. There
may be any number of contexts per protocol, each connection representing
a particular user, server, network, etc.

Contexts are passed between protocol and feature modules by way of ZeroBot's
core. In order for feature modules to respond to events created by protocol
modules, they must necessarily be able to send some kind of data back to the
protocol; Contexts facilitate this by acting as a handle of sorts to the
protocol.

Every protocol must implement a Context; the specifics are up to the protocol
in question as each one is unique. Typically, however, this is done by
specializing the Context abstract base class and the protocol's typical
connection or client type class. This way, a protocol may be implemented in its
usual way, but can still properly integrate with ZeroBot. For example:

    # Foo protocol implementation (protocol/foo/protocol.py)

    from ..context import Context

    class FooContext(Context, foo.Client):
        # Usual implementation of foo.Client ...
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any

from ZeroBot.common import ParsedCommand
from ZeroBot.common.abc import Channel, Message, User


class Context(metaclass=ABCMeta):
    """An ABC representing an individual connection over an arbitrary protocol.

    A Context represents an individual connection over an arbitrary protocol.
    There may be any number of contexts per protocol, each connection
    representing a particular user, server, network, etc.

    Attributes
    ----------
    channels_zb : dict of Channel objects
        A dict of ZeroBot `Channel`s that this context is connected to. These
        objects are part of ZeroBot's API, and not the underlying protocol
        implementaiton.
    server : Server
        A `Server`  object representing the server this context is connected
        to.
    user : User
        A `User`  object representing the user this context is connected as.
    users_zb : dict of User objects
        A dict of ZeroBot `User`s that are known on this context. These objects
        are part of ZeroBot's API, and not the underlying protocol
        implementaiton.

    Notes
    -----
    Protocol implementations should implement a Context by subclassing this
    class and their typical connection or client type class. For example:

    class FooContext(Context, foo.Client):
        # Usual implementation of foo.Client ...
    """

    @property
    @abstractmethod
    def protocol(self):
        """The protocol that this context belongs to.

        Feature modules may check against this property to implement
        protocol-specific behavior.
        """

    @property
    @abstractmethod
    def owner(self) -> User:
        """The primary, owning user that controls ZeroBot.

        This property is initalized by the ``Owner`` setting in the protocol
        configuration file. The "owner" is the user that has ultimate authority
        over ZeroBot, typically the user running ZeroBot.

        Returns
        -------
        User
            An instance of a `User` implementation specific to this context.

        Notes
        -----
        The initializing value varies between protocols, but should uniquely
        identify a user or account on the protocol for this context. Examples
        would be a Discord user ID, or an IRC services account name.
        """

    @owner.setter
    @abstractmethod
    def owner(self, user: User): ...

    @abstractmethod
    async def module_message(self, destination: Any, message: str):
        """Send a message through this context.

        The type of ``destination`` is protocol-dependent, and can often be
        given via `Message.destination`.
        """

    @abstractmethod
    async def module_join(self, where: Channel, password: str | None = None):
        """Join the given channel, with optional password."""

    @abstractmethod
    async def module_leave(self, where: Channel, reason: str | None = None):
        """Leave the given channel, with optional reason."""

    @abstractmethod
    async def reply_command_result(self, command: ParsedCommand, result: str | Message):
        """Called by feature modules to display command output.

        This method should handle formatting the result best suited for the
        protocol, i.e. some protocols support various markup and formatting
        features that others don't; this interface allows command output
        formatting on a per-protocol basis.
        """
