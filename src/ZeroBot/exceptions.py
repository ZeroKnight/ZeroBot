"""exceptions.py

Exceptions specific to ZeroBot.
"""

from __future__ import annotations


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

    def __init__(self, *args, mod_id: str, name: str = None, path: str = None, exc: ImportError = None):
        if exc:
            name, path = exc.name, exc.path
        super().__init__(*args, mod_id=mod_id)
        ImportError.__init__(self, *args, name=name, path=path)


class NoSuchModule(ModuleLoadError, ModuleNotFoundError):
    """Raised when a requested module could not be found.

    Subclass of `ModuleLoadError`. Extension of `ModuleNotFoundError`.
    """

    def __init__(self, *args, mod_id: str, name: str = None, path: str = None, exc: ModuleNotFoundError = None):
        if exc:
            name, path = exc.name, exc.path
        super().__init__(*args, mod_id=mod_id, name=name, path=path)


class ModuleRegisterError(ZeroBotModuleError):
    """Raised when a module fails to register.

    Usually, this means something in its `module_register` raised an exception.
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


# Config


class ZeroBotConfigError(ZeroBotException):
    """Base exception for ZeroBot config errors.

    Attributes
    ----------
    config_name : str
        The name of the config file.
    """

    def __init__(self, *args, config_name: str):
        super().__init__(*args)
        self.config_name = config_name


class ConfigReadError(ZeroBotConfigError):
    """Unable to read a config file from disk.

    *Note*: This exception means that the file itself could not be read,
    and *not* that it was an invalid config. See `ConfigDecodeError` for
    the latter.
    """


class ConfigWriteError(ZeroBotConfigError):
    """Unable to write a config file to disk.

    *Note*: This exception means that the file itself could not be written,
    and *not* that it was an invalid config. See `ConfigEncodeError` for
    the latter.
    """


class ConfigDecodeError(ZeroBotConfigError):
    """Unable to successfully parse and decode a config file.

    In other words, the config file could be *read*, but it was
    invalid.
    """


class ConfigEncodeError(ZeroBotConfigError):
    """Unable to successfully encode a `ZeroBot.Config` object."""


# Database


class ZeroBotDatabaseError(ZeroBotException):
    """Base exception for ZeroBot database errors.

    Attributes
    ----------
    database_name : str
        The name of the database file.
    """

    def __init__(self, *args, database_name: str):
        super().__init__(*args)
        self.database_name = database_name
