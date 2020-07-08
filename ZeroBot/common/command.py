"""common/command.py

Classes and utility functions for working with and creating ZeroBot commands.
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from ZeroBot.common.abc import Channel, User
from ZeroBot.module import Module
from ZeroBot.util import gen_repr


class _NoExitArgumentParser(ArgumentParser):
    """Modified `argparse.ArgumentParser` that doesn't exit on errors."""

    # NOTE: Python 3.9 will add an `exit_on_error` parameter that will stop
    # argparse from exiting instead of having to override exit and error.

    def exit(self, status=0, message=None):
        pass

    def error(self, message):
        raise Exception(f'{self.prog}: {message}')


class CommandAlreadyRegistered(Exception):
    """Command is already registered.

    Raised by `ZeroBot.Core` when attempting to register a command that has
    already been registered.

    Attributes
    ----------
    cmd_name : str
        The name of the command.
    module_id : str
        The the identifier of the module that has registered the command.
    """

    def __init__(self, cmd_name: str, module_id: str):
        msg = (f"Command '{cmd_name}' has already been registered by "
               f"module '{module_id}'")
        super().__init__(msg)
        self.cmd_name = cmd_name
        self.module_id = module_id


class CommandParser(_NoExitArgumentParser):
    """Definition and parser for ZeroBot commands.

    Creation of a `CommandParser` object necessarily entails defining the
    command itself: its name, what arguments and options it accepts, how they
    behave, etc. It is both the blueprint and interpreter for a command.

    Attributes
    ----------
    name : str
        The name of the command, i.e. how the command will be invoked.
    description : str, optional
        A short description of the command. May be omitted.
    usage : str, optional
        The text shown as the "usage" line in the command's help text. If
        omitted, it will be automatically generated by `argparse`.

    Notes
    -----
    Under the hood, `CommandParser` is simply a wrapper around an
    `argparse.ArgumentParser` with some ZeroBot-related members.
    """

    def __init__(self, name: str, description: Optional[str] = None,
                 usage: Optional[str] = None):
        # NOTE: Might be able to make use of formatter_class if need be
        super().__init__(
            prog=name, usage=usage, description=description, add_help=False)
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
    invoker : User
        The user that invoked the command.
    source : User or Channel
        Where the command was sent from, either directly from a user, or from
        within a channel.
    """

    name: str
    args: Dict[str, Any]
    parser: CommandParser
    invoker: User
    source: Union[User, Channel]
