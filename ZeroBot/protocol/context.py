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

from abc import ABCMeta
from typing import Any

from ZeroBot.common.abc import Channel


class Context(metaclass=ABCMeta):
    """An ABC representing an individual connection over an arbitrary protocol.

    A Context represents an individual connection over an arbitrary protocol.
    There may be any number of contexts per protocol, each connection
    representing a particular user, server, network, etc.

    Attributes
    ----------
    server : Server
        A `Server`  object representing the server this context is connected
        to.
    user : User
        A `User`  object representing the user this context is connected as.

    Notes
    -----
    Protocol implementations should implement a Context by subclassing this
    class and their typical connection or client type class. For example:

    class Context(Context, foo.Client):
        # Usual implementation of foo.Client ...
    """

    @property
    def protocol(self):
        """The protocol that this context belongs to.

        Feature modules may check against this property to implement
        protocol-specific behavior.
        """
        return __name__

    async def module_message(self, destination: Any, message: str):
        """Send a message through this context.

        The type of ``destination`` is protocol-dependent, and can often be
        given via `Message.destination`.
        """
        raise NotImplementedError

    async def module_join(self, where: Channel, password: str = None):
        """Join the given channel, with optional password."""
        raise NotImplementedError

    async def module_leave(self, where: Channel, reason: str = None):
        """Leave the given channel, with optional reason."""
        raise NotImplementedError
