"""common/enums.py

Various enumerations used throughout ZeroBot's codebase.
"""

from __future__ import annotations

from enum import Enum, unique


@unique
class CmdResult(Enum):
    """Enum of command result types.

    Indicates how a command ultimately completed, successfully or otherwise.
    Commonly used with `invalid_command` events and `reply_command_result`
    callbacks in protocol modules.
    """

    Success = 0  # Command completed successfully
    Unspecified = 1  # Generic or unspecified failure
    NotFound = 2  # Command yielded no results or something requested wasn't found
    BadSyntax = 3  # A command was ill-formed in some way
    AmbiguousArgument = 4  # A command argument was ambiguous
    TooLong = 6  # A command either returned or received too much information
    BadTarget = 7  # A command was well-formed, but its target was invalid
    NotImplemented = 8  # Something is not implemented, so the command cannot be executed
    Unavailable = 9  # Something is unavailable, missing, etc.
    NoPermission = 10  # Insufficient permission to use or perform a specific action with a command
    Exists = 11  # Something already exists

    def failed(self) -> bool:
        """Whether the command result is any of the failure results."""
        return self is not self.Success


@unique
class HelpType(Enum):
    """Enum representing the type of response to a command help request.

    A help request is for a specific command, module, or for an overview of
    available modules and commands. This enumeration also denotes problematic
    help requests, such as when the requested command or module does not exist.
    """

    CMD = 1
    MOD = 2
    ALL = 3
    NO_SUCH_MOD = 4
    NO_SUCH_CMD = 5
    NO_SUCH_SUBCMD = 6


@unique
class ModuleCmdStatus(Enum):
    """Enum denoting the result of a ``module`` core command invokation.

    Attempting to (re)load a module, for example, can succeed, fail, or the
    requested module might not exist, already be loaded, or isn't yet loaded.
    """

    LOAD_OK = 1
    RELOAD_OK = 2
    LOAD_FAIL = 3
    RELOAD_FAIL = 4
    NO_SUCH_MOD = 5
    ALREADY_LOADED = 6
    NOT_YET_LOADED = 7
    QUERY = 8

    @classmethod
    def is_ok(cls, status: ModuleCmdStatus) -> bool:
        """Return whether the given status is an "OK" type."""
        return status is cls.LOAD_OK or status is cls.RELOAD_OK

    @classmethod
    def is_reload(cls, status: ModuleCmdStatus) -> bool:
        """Return whether the given status is a "RELOAD" type."""
        return status in {cls.RELOAD_OK, cls.RELOAD_FAIL, cls.NOT_YET_LOADED}


@unique
class ConfigCmdStatus(Enum):
    """Enum denoting the result of a ``config`` core command invokation."""

    GET_OK = 1
    SET_OK = 2
    RESET_OK = 3
    SAVE_OK = 4
    RELOAD_OK = 5
    NO_SUCH_KEY = 6
    NO_SUCH_CONFIG = 7
    SAVE_FAIL = 8
    RELOAD_FAIL = 9

    @classmethod
    def is_ok(cls, status: ConfigCmdStatus) -> bool:
        """Return whether the given status is an "OK" type."""
        return status in {
            cls.GET_OK,
            cls.SET_OK,
            cls.RESET_OK,
            cls.SAVE_OK,
            cls.RELOAD_OK,
        }
