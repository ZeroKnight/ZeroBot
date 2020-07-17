"""common/enums.py

Various enumerations used throughout ZeroBot's codebase.
"""

from enum import Enum, unique


@unique
class HelpType(Enum):
    """Enumeration representing the type of response to a command help request.

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
    """Enumeration denoting the result of a ``module`` core command invokation.

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

    @classmethod
    def is_ok(cls, status: 'ModuleCmdStatus') -> bool:
        """Return whether the given status is an "OK" type."""
        return status is cls.LOAD_OK or status is cls.RELOAD_OK

    @classmethod
    def is_reload(cls, status: 'ModuleCmdStatus') -> bool:
        """Return whether the given status is a "RELOAD" type."""
        return status in (cls.RELOAD_OK, cls.RELOAD_FAIL, cls.NOT_YET_LOADED)
