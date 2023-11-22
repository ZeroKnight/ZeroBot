"""common/enums.py

Various enumerations used throughout ZeroBot's codebase.
"""

from __future__ import annotations

from enum import Enum, unique


@unique
class CmdErrorType(Enum):
    """Enum of different error categories for invalid or failed commands.

    Primarily passed to `invalid_command` events to give a general idea of
    why a command was invalid or why it failed.
    """

    Unspecified = 1
    NotFound = 2
    BadSyntax = 3
    AmbiguousArgument = 4
    NoResults = 5
    OutputTooLong = 6
    BadTarget = 7


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
