"""exceptions.py

Exceptions specific to ZeroBot.
"""


class ZeroBotException(Exception):
    """Base exception for ZeroBot.

    Can be used to catch any exception that ZeroBot may throw.
    """


# Modules

class ZeroBotModuleError(ZeroBotException):
    """Base exception for ZeroBot module errors.

    Attributes
    ----------
    mod_id : str
        The module identifier.
    """

    def __init__(self, *args, mod_id: str):
        super().__init__(*args)
        self.mod_id = mod_id


class ModuleLoadError(ZeroBotModuleError, ImportError):
    """Raised when a requested module could not be loaded.

    Extension of `ImportError`.
    """

    def __init__(self, *args, mod_id: str, name: str = None, path: str = None):
        ImportError.__init__(self, *args, name=name, path=path)
        ZeroBotModuleError.__init__(self, mod_id=mod_id)


class NoSuchModule(ZeroBotModuleError, ModuleNotFoundError):
    """Raised when a requested module could not be found.

    Extension of `ModuleNotFoundError`.
    """


class ModuleNotLoaded(ZeroBotModuleError):
    """Attempted to reload a module that has not yet been loaded."""


class ModuleAlreadyLoaded(ZeroBotModuleError):
    """Attempted to load a module that has already been loaded."""


class ModuleHasNoCommands(ZeroBotModuleError):
    """Attempted to manage commands for a module with none regsitered."""


# Commands

class ZeroBotCommandError(ZeroBotException):
    """Base exception for ZeroBot command errors.

    Attributes
    ----------
    cmd_name : str
        The name of the command.
    """

    def __init__(self, *args, cmd_name: str):
        super().__init__(*args)
        self.cmd_name = cmd_name


class CommandParseError(ZeroBotCommandError):
    """The given command could not be parsed.

    Malformed commands, or commands with missing required parameters will cause
    this exception.
    """


class NotACommand(CommandParseError):
    """Attempted to parse a string that didn't contain a command."""

    def __init__(self, *args):
        super().__init__(*args, cmd_name=None)


class CommandNotRegistered(ZeroBotCommandError):
    """Raised when a request is made for a command that isn't registered."""


class CommandAlreadyRegistered(ZeroBotCommandError):
    """Command is already registered.

    Raised by `ZeroBot.Core` when attempting to register a command that has
    already been registered.

    Attributes
    ----------
    mod_id : str
        The the identifier of the module that has registered the command.
    """

    def __init__(self, *args, cmd_name: str, mod_id: str):
        super().__init__(*args, cmd_name=cmd_name)
        self.mod_id = mod_id
