"""context.py

A Context represents an individual connection over an arbitrary protocol. There
may be any number of contexts per protocol depending on how it is architected,
with each connection representing a particular user, server, network, etc.

Contexts act as a sort of handle into a protocol for features; they allow a
protocol to pass data to a feature and vice versa. ZeroBot's core is in charge
of passing contexts to feature modules as part of its event orchestration. When
a context emits an event, that context is passed to all feature modules that
can handle it.

Every protocol must implement a Context; the specifics are up to the protocol
in question as each one is unique. Typically, however, this is done by
specializing the Context abstract base class and the protocol's typical
connection or client type class. This way, a protocol may be implemented in its
usual way, but can still properly integrate with ZeroBot. For example:

    # Foo protocol implementation (protocol/foo/protocol.py)

    import foo
    from ZeroBot.context import Context

    class FooContext(Context, foo.Client):
        # Usual implementation of foo.Client ...
"""

from __future__ import annotations

import datetime
import functools
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncIterator
from enum import Flag, auto
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from ZeroBot.common import CommandHelp, ParsedCommand
    from ZeroBot.core import ConfigCmdResult, ModuleCmdResult, VersionInfo
from ZeroBot.common.enums import CmdResult


class ProtocolSupport(Flag):
    """Enum of functionality that varies between protocols.

    Protocols can be quite different from one another in terms of what can be
    done within them; this enumeration allows them to specify support of
    generally known features among chat protocols.
    """

    MessageMultiLine = auto()
    MessageColor = auto()
    StatusMessage = auto()
    AwayMessage = auto()
    Visibility = auto()  # Online, Away/Idle, Invisible, Offline, etc.
    Roles = auto()
    VoiceChat = auto()
    VideoChat = auto()
    ScreenShare = auto()
    Attachments = auto()
    Embeds = auto()


def protocolobj(cls):
    """Decorator for ZeroBot's protocol entity classes.

    Adds common functionality allowing decorated classes to refererence the
    context that created them and the original protocol object. Any unknown
    attributes are forwarded to the original protocol object.
    """

    @functools.wraps(cls, updated=())
    class Wrapped(cls):
        def __init__(self, context: Context, original) -> None:
            self._context = context
            self._original = original

        def __getattr__(self, name):
            return getattr(self._original, name)

        @property
        def context(self) -> Context:
            """A reference to the Context that created this object."""
            return self._context

        @property
        def original(self) -> cls:
            """A reference to the original protocol object.

            This is the specialized, non-generic version created by the protocol
            itself.
            """
            return self._original

    return Wrapped


@protocolobj
class User(metaclass=ABCMeta):
    """An ABC representing an individual that is connected on a protocol.

    This is a general interface that is protocol-agnostic and must be
    specialized by protocol modules.
    """

    def __str__(self):
        return self.name

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the User.

        Should represent the display name or nickname of the User; specifically
        the name that may freely change and does not uniquely identify them on
        the protocol.
        """

    @property
    @abstractmethod
    def username(self) -> str:
        """The username of the User.

        The username should uniquely identify the user on the protocol, such
        as an account name, email, UUID, etc. Unlike the `name` property, the
        username should never change.
        """

    @property
    def bot(self) -> bool:
        """Whether or not this User is a bot."""
        raise NotImplementedError

    @abstractmethod
    def mention(self) -> str:
        """Returns a string appropriate to "mention" a user.

        Mentioning a user typically notifies or alerts them in some way; the
        proper syntax varies between protocols.
        """

    @abstractmethod
    def mentioned(self, message: Message) -> bool:
        """Check if the user was mentioned in the given message."""

    @abstractmethod
    def mention_pattern(self) -> str:
        """Return a pattern that matches the bare name or a mention.

        On some protocols, a mention may be formatted specially in the actual
        message content, e.g. Discord. The returned pattern should match the
        user display name as-is or its mention-form, if applicable.
        """


@protocolobj
class Server(metaclass=ABCMeta):
    """Represents an arbitrary host that can be connected to.

    The specifics of what constitutes a Server is highly dependent upon the
    implementing protocol. In the most general sense, a Server represents some
    collection of Channels where Users can communicate. This could be an
    arbitrary host, a named instance provided by a SaaS entity, or some other
    protocol-dependent endpoint. As such, this interface is rather bare.
    """

    def __str__(self):
        return self.name

    @property
    @abstractmethod
    def name(self) -> str:
        """An identifier that uniquely represents a server via the protocol.

        Typically a hostname where the server is running, a simple identifier,
        UUID, etc.
        """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether or not the Server is currently connected."""


@protocolobj
class Channel(metaclass=ABCMeta):
    """Represents some kind of communication destination for Messages.

    The specifics of what constitutes a Channel is dependent upon the
    implementing protocol. In general, a Channel represents a medium that can
    pass along messages between Users, e.g. an IRC or Discord channel, group
    chat, or even a single User.
    """

    def __str__(self):
        return self.name

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the Channel."""

    @property
    @abstractmethod
    def server(self) -> Server | None:
        """The server that this Channel belongs to.

        In some protocols, some channels may not be tied to a server, e.g.
        direct message channels in Discord.
        """

    @property
    def password(self) -> str | None:
        """The password required to communicate on the Channel.

        Can be `None` if no password is required, or is not applicable.
        """
        return None

    @property
    @abstractmethod
    def is_dm(self) -> bool:
        """Whether this channel represents a direct message with another User."""

    @abstractmethod
    async def history(
        self,
        *,
        limit: int | None = 100,
        before: Message | datetime.datetime | None = None,
        after: Message | datetime.datetime | None = None,
        authors: list[User | str] | None = None,
    ) -> AsyncIterator[Message]:
        """Iterate over messages in the channel history.

        Returns an AsyncIterator that can be looped over with `async for`.
        A maximum of `limit` messages will be yielded before iteration stops,
        or infinitely if `limit` is None.

        History search can be narrowed down by specifying date ranges with
        `before` and `after` or by specifying one or more users that must have
        authored the messages.
        """

    @abstractmethod
    async def users(self) -> list[User]:
        """Returns all Users in the channel."""


@protocolobj
class Message(metaclass=ABCMeta):
    """Represents a message sent by a network entity via a protocol.

    Messages consist of a source and a destination, either of which could be
    a User, Channel, or a Server, depending on the type and context of the
    message.
    """

    def __str__(self):
        return self.content

    def __len__(self):
        return len(self.content)

    @property
    @abstractmethod
    def content(self) -> str:
        """The contents of the message."""

    @property
    @abstractmethod
    def source(self) -> User | Channel | Server:
        """Where the message came from, i.e. the sender.

        Depending on the protocol, messages can come directly from users, from
        a user in a channel, or from the server itself.
        """

    @property
    @abstractmethod
    def destination(self) -> User | Channel | Server:
        """Where the message is being sent.

        Depending on the protocol, messages can be sent directly to users, to
        a channel, or to the server itself (though this would be uncommon).
        """

    @property
    @abstractmethod
    def time(self) -> datetime.datetime:
        """The time that the message was sent, in UTC."""

    @property
    @abstractmethod
    def server(self) -> Server | None:
        """The Server where this message originated from.

        In some protocols, some messages may not be tied to a server, e.g.
        direct messages in Discord.
        """

    @staticmethod
    def is_action_str(string: str) -> bool:
        """Check if the given string is an action."""
        raise NotImplementedError

    @staticmethod
    def as_action_str(string: str) -> str:
        """Returns the given string as an action."""
        raise NotImplementedError

    @staticmethod
    def strip_action_str(string: str) -> str:
        """Strip the action formatting from the given string."""
        raise NotImplementedError

    @property
    @abstractmethod
    def clean_content(self) -> str:
        """Return a "clean" version of the message content.

        Specifically, mentions are converted into the proper name they
        represent. For example, in Discord, `<@{id}>` becomes `username`.
        """

    def is_action(self) -> bool:
        """Check whether the message is an action."""
        return self.is_action_str(self.content)

    def as_action(self) -> str:
        """Returns the message as an action."""
        return self.as_action_str(self.content)

    def strip_action(self) -> str:
        """Strip the action formatting from the message."""
        return self.strip_action_str(self.content)


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

    # TODO: registering a protocol should track this identifier in core to
    # prevent loading more than one implementation of a protocol
    @property
    @abstractmethod
    def protocol(self) -> str:
        """The protocol that this context belongs to.

        Should return a string that identifies the protocol. Feature modules may
        check against this property to implement protocol-specific behavior.
        """

    @property
    @abstractmethod
    def owner(self) -> User | None:
        """The primary, owning user that controls ZeroBot.

        This property is initalized by the ``Owner`` setting in the protocol
        configuration file. The "owner" is the user that has ultimate authority
        over ZeroBot, typically the user running ZeroBot.

        May return None if the Owner was not set or could not be found.

        Notes
        -----
        The initializing value varies between protocols, but should uniquely
        identify a user or account on the protocol for this context. Examples
        would be a Discord user ID, or an IRC services account name.
        """

    @owner.setter
    @abstractmethod
    def owner(self, user: User): ...

    @property
    @abstractmethod
    def user(self) -> User:
        """The User representing ZeroBot associated with this context."""

    @property
    @abstractmethod
    def support(self) -> ProtocolSupport:
        """A set of `ProtocolSupport` flags that this protocol supports.

        While each protocol implementation can offer flexibility in what it
        accepts versus what it explicitly supports, feature modules may check
        these flags to alter their behavior accordingly.
        """

    @property
    def server(self) -> Server | None:
        """The server that this context originates from.

        May be `None` if not applicable for a particular protocol.
        """
        return None

    # TODO: Refactor/rethink the `action` param. It doesn't make sense to
    # have both action and mention_user, nor does it make sense with
    # multi-line messages
    @abstractmethod
    async def module_message(
        self,
        content: str,
        destination: MessageTarget,
        *,
        action: bool = False,
        mention_user: User = None,
        **kwargs,
    ):
        """Send a message through this context.

        If `mention_user` is not None, the given user will be "mentioned" in the
        message in such a way that that user will be notified. Any extra
        keyword arguments can be used at the discretion of the protocol that is
        implementing this method.
        """

    @abstractmethod
    async def module_reply(self, content: str, referent: Message, *, action: bool = False, **kwargs):
        """Send a message as a reply to another through this context.

        The exact behavior varies between protocols, but when possible, the
        `referent` message is linked to or backreferenced in some way alongside
        the usual message. Typically, this also notifies the sender of the
        referent message similar to a mention.

        Any extra keyword arguments can be used at the discretion of the
        protocol that is implementing this method.
        """

    @abstractmethod
    async def module_join(self, where: Channel, password: str | None = None):
        """Join the given channel, with optional password."""

    @abstractmethod
    async def module_leave(self, where: Channel, reason: str | None = None):
        """Leave the given channel, with optional reason."""

    @abstractmethod
    async def reply_command_result(
        self, message: str | list[str], command: ParsedCommand, result: CmdResult = CmdResult.Success
    ):
        """Called by feature modules to display command output.

        Sends a reply to the command invoker about the result of the command.

        This method should handle formatting the result best suited for the
        protocol, i.e. some protocols support various markup and formatting
        features that others don't; this interface allows command output
        formatting on a per-protocol basis.
        """

    @abstractmethod
    async def core_command_help(self, command: ParsedCommand, result: CommandHelp) -> None:
        """Display results from the Core `help` command.

        The Core creates a `CommandHelp` object that holds the individual
        parts of a command that constitute its structure. Protocols can disect
        this object to format help message output.

        The parsed help command that initiated this callback is also passed.
        """

    @abstractmethod
    async def core_command_module(self, command: ParsedCommand, results: list[ModuleCmdResult]) -> None:
        """Display results from the Core `module` command.

        The Core creates `ModuleCmdResult` objects that hold information
        about the result of the invoked module command. Protocols can disect
        this object to format these results.

        The parsed module command that initiated this callback is also passed.
        """

    @abstractmethod
    async def core_command_config(self, command: ParsedCommand, results: list[ConfigCmdResult]) -> None:
        """Display results from the Core `config` command.

        The Core creates `ConfigCmdResult` objects that hold information
        about the result of the invoked config command. Protocols can disect
        this object to format these results.

        The parsed config command that initiated this callback is also passed.
        """

    @abstractmethod
    async def core_command_version(self, command: ParsedCommand, info: VersionInfo) -> None:
        """Display results from the Core `version` command.

        The Core creates a `VersionInfo` object that holds information about
        the running build of ZeroBot. Protocols can disect this object to
        format these results.

        The parsed version command that initiated this callback is also passed.
        """

    @abstractmethod
    async def core_command_cancel(self, command: ParsedCommand, cancelled: bool, wait_id: int, waiting) -> None:
        """Display results from the Core `cancel` command."""

    @abstractmethod
    async def core_command_backup(self, command: ParsedCommand, file: Path) -> None:
        """Display results from the Core `backup` command.

        The resultant backup file and the parsed backup command that initiated
        this callback are passed.
        """


MessageTarget: TypeAlias = str | User | Channel | Server
