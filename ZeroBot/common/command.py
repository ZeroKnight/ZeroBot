"""common/command.py

Classes and utility functions for working with and creating ZeroBot commands.
"""

from __future__ import annotations

from argparse import ArgumentParser, _SubParsersAction
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Optional, Union

from ZeroBot.common.abc import Channel, Message, User
from ZeroBot.common.enums import HelpType
from ZeroBot.exceptions import CommandAlreadyRegistered, CommandParseError
from ZeroBot.module import Module
from ZeroBot.util import gen_repr

__all__ = [
    'CommandHelp',
    'CommandParser',
    'ParsedCommand'
]


class _NoExitArgumentParser(ArgumentParser):
    """Modified `argparse.ArgumentParser` that doesn't exit on errors."""

    # NOTE: Python 3.9 will add an `exit_on_error` parameter that will stop
    # argparse from exiting instead of having to override exit and error.

    def exit(self, status=0, message=None):
        pass

    def error(self, message):
        raise CommandParseError(message, cmd_name=self.prog)


class CommandParser(_NoExitArgumentParser):
    """Definition and parser for ZeroBot commands.

    Creation of a `CommandParser` object necessarily entails defining the
    command itself: its name, what arguments and options it accepts, how they
    behave, etc. It is both the blueprint and interpreter for a command.

    Attributes
    ----------
    name : str, optional
        The name of the command, i.e. how the command will be invoked. May be
        omitted, but this only makes sense when creating a parent parser for
        another parser.
    description : str, optional
        A short description of the command. May be omitted.
    usage : str, optional
        The text shown as the "usage" line in the command's help text. If
        omitted, it will be automatically generated by `argparse`.
    kwargs
        Any extra keyword arguments are passed to the underlying
        `argparse.ArgumentParser` constructor.

    Notes
    -----
    Under the hood, `CommandParser` is simply a wrapper around an
    `argparse.ArgumentParser` with some ZeroBot-related members.
    """

    def __init__(self, name: Optional[str] = None,
                 description: Optional[str] = None,
                 usage: Optional[str] = None, **kwargs):
        # NOTE: Might be able to make use of formatter_class if need be
        if not name:
            name = kwargs.get('name', kwargs.get('prog'))
        kwargs.update({
            'prog': name,
            'description': description,
            'usage': usage,
            'add_help': False
        })
        super().__init__(**kwargs)
        self.name = name
        self._module = None

        # More minimal default argument grouping
        blank_group = self.add_argument_group()
        self._optionals = blank_group
        self._positionals = blank_group

    def __repr__(self):
        attrs = ['name', 'description', 'module']
        return gen_repr(self, attrs)

    def __str__(self):
        return self.name

    def make_adder(self, *args, **kwargs):
        """Helper shortcut for creating subcommands.

        Accepts arguments for `add_subparsers`, creating a new subparser and
        returning a partial function wrapping `add_subcommand` for the new
        subparser. If the `dest` argument isn't specified, it defaults to
        `'subcmd'`.

        Example
        -------
        cmd_foo = CommandParser('foo', 'Does foo stuff')
        foo_adder = cmd_foo.make_adder(metavar='OPERATION', required=True)
        bar_subcmd = foo_adder('bar', description='Does bar stuff to foo')
        """
        kwargs.setdefault('dest', 'subcmd')
        subp = self.add_subparsers(*args, **kwargs)
        return partial(self.add_subcommand, subp)

    @staticmethod
    def add_subcommand(subp: _SubParsersAction, name: str,
                       description: Optional[str] = None,
                       **kwargs) -> 'CommandParser':
        """Helper method for adding subcommands.

        Wrapper around `add_parser` that simplifies adding subcommands to
        ZeroBot commands. The same string is used for both the `description`
        and `help` parameters of `add_parser`.

        Parameters
        ----------
        subp : Result of calling the `add_subparsers` method.
            The subparser object returned from the `add_subparsers` method.
        name : str
            The name of the subcommand.
        description : str, optional
            A short description of the command. May be omitted. The `help`
            parameter will be set to this value automatically.
        kwargs
            Extra arguments to pass to the `CommandParser` constructor.
        """
        desc_help = {'description': description, 'help': description}
        return subp.add_parser(name, **desc_help, **kwargs)

    @property
    def module(self) -> Optional[Module]:
        """The module that this command is registered to.

        Will return `None` if this command has not yet been registered.
        """
        return self._module


@dataclass
class ParsedCommand:
    """A successfully parsed command with invoker and destination info.

    ZeroBot's `Core` will send these as the payload of `module_command_*`
    events.

    Attributes
    ----------
    name : str
        The command name.
    args : dict
        A dictionary of the resultant parsed arguments and options and their
        values.
    parser : CommandParser
        The parser that created this instance.
    msg : Message
        The original message encompassing the command.
    invoker
    source
    subcmd
    """

    name: str
    args: dict[str, Any]
    parser: CommandParser
    msg: Message

    def __post_init__(self):
        # pylint: disable=protected-access
        try:
            action = self.parser._actions[0]
            if isinstance(action, _SubParsersAction):
                name_map = action.choices
                canon_parser = name_map[self.args[action.dest]]
                self._subcmd = canon_parser.name.split()[-1]
            else:
                self._subcmd = None
        except (KeyError, IndexError):
            self._subcmd = None

    @property
    def invoker(self) -> User:
        """The User that invoked the command."""
        return self.msg.source

    @property
    def source(self) -> Union[User, Channel]:
        """Where the command was sent from.

        Can be either directly from a user, or from a user within a channel.
        """
        return self.msg.destination

    @property
    def subcmd(self) -> Optional[str]:
        """The invoked subcommand name, if one was invoked.

        For subcommands with aliases, the name returned is always the canonical
        name that the aliases are associated with. For this reason, this
        attribute should be preferred to extracting the subcommand name from
        `ParsedCommand.args`.
        """
        return self._subcmd

    def nested_subcmd(self, depth: int = 2) -> Optional[str]:
        """Get the name of a nested subcommand.

        Like the `subcmd` property, the name returned is always the canonical
        name for the subcommand. The `depth` parameter determines how many
        levels of nesting to traverse; the default of ``2`` gets the first
        nested subcommand. As a consequence, a value of ``1`` is the same as
        `subcmd`.
        """
        # pylint: disable=protected-access
        current = 0
        subparser = self.parser
        try:
            while current < depth:
                action = subparser._actions[0]
                if isinstance(action, _SubParsersAction):
                    subparser = action.choices[self.args[action.dest]]
                    current += 1
                else:
                    return None
            return subparser.name.split()[-1]
        except (IndexError, KeyError, TypeError):
            return None


@dataclass
class CommandHelp:
    """Encapsulates the result of a command help request.

    ZeroBot's `Core` will create and pass these to `core_command_help`
    callbacks.

    Attributes
    ----------
    type : HelpType
        An enum type representing the type of help request.
    name : str, optional
        The command or module name that the help is about.
    aliases : list, optional
        If applicable, a list of aliases for this command.
    description : str, optional
        The command or module description
    usage : str, optional
        The "usage" string for the command
    args : dict, optional
        A dictionary mapping each positional argument name and a tuple of their
        help strings and a boolean flag denoting whether or not the argument
        represents a subcommand.
        Only set when `type` is `CMD`.
    opts : dict, optional
        A dictionary mapping a tuple of option names representing a particular
        option to a tuple of the option's value name and its help strings.
    cmds : dict, optional
        A dictionary mapping module names to another dictionary of command
        names and their help strings. Only set when `type` is `MOD` or `ALL`.
    subcmds : dict, optional
        If applicable, a dictionary of subcommand names and their own
        `CommandHelp` objects.
    parent : CommandHelp
        Only set when `type` is `NO_SUCH_SUBCMD`, and refers to the parent
        `CommandHelp` object.
    """

    type: HelpType
    name: str = None
    description: str = None
    usage: str = None
    aliases: list[str] = field(default_factory=list)
    args: dict[str, tuple[Optional[str], bool]] = field(default_factory=dict)
    opts: dict[tuple[str, ...],
               Optional[
                   tuple[str, Optional[str]]]] = field(default_factory=dict)
    cmds: dict[str, dict[str, str]] = field(default_factory=dict)
    subcmds: dict[str, 'CommandHelp'] = field(default_factory=dict, repr=False)
    parent: 'CommandHelp' = None

    def get_subcmd(self, name: str) -> 'CommandHelp':
        """Get the `CommandHelp` object for the given subcommand.

        `name` may be an alias, in which case it is resolved to the appropriate
        subcommand.
        """
        try:
            return self.subcmds[name]
        except KeyError:
            # Try looking up by alias
            for sub_name, sub_help in self.subcmds.items():
                for alias in sub_help.aliases:
                    if name == alias:
                        return self.subcmds[sub_name]
            raise
