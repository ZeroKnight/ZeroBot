"""core.py

ZeroBot's core provides a foundation for protocol and feature modules to build
off of, collecting and orchestrating events among them.

ZeroBot's core doesn't directly do much of anything on its own, instead relying
on protocol modules to enable ZeroBot to connect to and communicate somewhere,
and feature modules to do something meaningful with that connection.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import logging.config
import os
import signal
import sys
import time
from argparse import ArgumentError, ArgumentTypeError, _SubParsersAction
from collections import ChainMap, namedtuple
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator, Type, Union

import appdirs
from toml import TomlDecodeError

import ZeroBot
import ZeroBot.database as zbdb
from ZeroBot.common import ConfigCmdStatus, HelpType, ModuleCmdStatus, abc
from ZeroBot.common.command import CommandHelp, CommandParser, ParsedCommand
from ZeroBot.common.enums import CmdErrorType
from ZeroBot.config import Config
from ZeroBot.database import DBUser, DBUserAlias, Participant, Source
from ZeroBot.exceptions import (
    CommandAlreadyRegistered,
    CommandNotRegistered,
    CommandParseError,
    ModuleAlreadyLoaded,
    ModuleHasNoCommands,
    ModuleLoadError,
    ModuleNotLoaded,
    ModuleRegisterError,
    NoSuchModule,
    NotACommand,
    ZeroBotConfigError,
    ZeroBotModuleError,
)
from ZeroBot.module import (
    CoreModule,
    FeatureModule,
    Module,
    ProtocolModule,
    ZeroBotModuleFinder,
)
from ZeroBot.protocol.context import Context
from ZeroBot.util import shellish_split

# Minimal initial logging format for any messages before the config is read and
# user logging configuration is applied.
logging.basicConfig(
    style="{",
    format="{asctime} {levelname:7} {message}",
    datefmt="%T",
    level=logging.ERROR,
)


class CommandRegistry:
    """Registry of commands and the modules that registered them.

    Supports lookup of all commands registered to a module, or what module
    a particular command is registered to.
    """

    def __init__(self):
        self._registry = {"by_name": {}, "by_module": {}}

    def __getitem__(self, name: str) -> CommandParser:
        return self._registry["by_name"][name]

    def __iter__(self):
        return iter(self._registry["by_name"])

    def iter_by_module(self, module_id: str) -> Iterator[CommandParser]:
        """Generator that yields all commands registered to a module.

        Parameters
        ----------
        module_id : str
            The identifier of the module.

        Raises
        ------
        ModuleHasNoCommands
            The requested module has no registered commands.
        """
        try:
            yield from self._registry["by_module"][module_id]
        except KeyError:
            raise ModuleHasNoCommands(
                f"Module '{module_id}' does not have any registered commands.",
                mod_id=module_id,
            ) from None

    def pairs(self) -> Iterator[tuple[str, list[CommandParser]]]:
        """Generator that yields pairs of module identifiers their parsers."""
        for module, cmds in self._registry["by_module"].items():
            yield (module, cmds)

    def add(self, module_id: str, command: CommandParser):
        """Add a command to the registry.

        Parameters
        ----------
        module_id : str
            The module identifier to register the command to.
        command : CommandParser
            The command to add.

        Raises
        ------
        CommandAlreadyRegistered
            The command has already been registered.
        """
        if command.name in self:
            raise CommandAlreadyRegistered(
                f"Command '{command.name}' has already been registered by module '{module_id}'",
                cmd_name=command.name,
                mod_id=module_id,
            )
        self._registry["by_name"][command.name] = command
        self._registry["by_module"].setdefault(module_id, []).append(command)

    def remove(self, command: str):
        """Remove a command from the registry.

        Parameters
        ----------
        command : str
            The name of the command to remove.

        Raises
        ------
        KeyError
            The given command is not registered.
        """
        try:
            cmd = self._registry["by_name"].pop(command)
            for module in self._registry["by_module"]:
                try:
                    self._registry["by_module"][module].remove(cmd)
                except ValueError:
                    continue
                else:
                    return
        except KeyError:
            raise CommandNotRegistered(f"Command '{command}' is not registered", cmd_name=command) from None

    def modules_registered(self) -> list[Module]:
        """Return a list of `Module`s that have registered commands."""
        return [cmds[0].module for cmds in self._registry["by_module"].values()]


@dataclass
class VersionInfo:
    """Version and miscellaneous build information for ZeroBot."""

    version: str
    release_date: datetime.date
    author: str
    home: str


ModuleCmdResult = namedtuple("ModuleCmdResult", "module, status, mtype, info", defaults=[None])
ConfigCmdResult = namedtuple("ConfigCmdResult", "config, status, key, value, new_path", defaults=[None] * 3)
WaitingCmdInfo = namedtuple("WaitingCmdInfo", "id, cmd, delay, invoker, source, started")


class Core:
    """A class representing ZeroBot's core functionality.

    The core is more or less the brain (if you could call it that) of ZeroBot;
    it is responsible for loading and orchestrating the protocol and feature
    modules that actually provide functionality, as well as directly handling
    configuration.

    Parameters
    ----------
    config_dir : str or Path, optional
        Specifies the path to ZeroBot's configuration directory; defaults to
        ``<user_config_dir>/ZeroBot``.
    data_dir : str or Path, optional
        Specifies the path to ZeroBot's data directory; defaults to
        ``<user_data_dir>/ZeroBot``.
    eventloop : asyncio.AbstractEventLoop, optional
        The asyncio event loop to use. If unspecified, the default loop will be
        used, i.e. `asyncio.get_event_loop()`.

    Attributes
    ----------
    cmdprefix : str
        The prefix required to designate a command invokation. The prefix may
        be any number of arbitrary characters, but must be at least one
        character. Defaults to ``!``.
    config : Config
        A `Config` object representing ZeroBot's main configuration file.
    config_dir : Path
    data_dir : Path
    eventloop

    Notes
    -----
    There should generally be only one `Core` instance, as it represents
    ZeroBot in his entirety. However, there's nothing stopping you from running
    multiple cores in separate threads, if for some reason you wanted to.
    """

    def __init__(
        self,
        config_dir: Union[str, Path] = None,
        data_dir: Union[str, Path] = None,
        eventloop: asyncio.AbstractEventLoop = None,
    ):
        self.eventloop = eventloop if eventloop else asyncio.get_event_loop()
        self.logger = logging.getLogger("ZeroBot")
        self._protocols = {}  # maps protocol names to their ProtocolModule
        self._features = {}  # maps feature module names to their Module
        self._all_modules = ChainMap(self._protocols, self._features)
        self._db_connections = {}
        self._configs = {}  # maps config file names to their Config
        self._dummy_module = CoreModule(self, ZeroBot.__version__)
        self._commands = CommandRegistry()
        self._delayed_commands = {}
        self._delayed_command_count = 0
        self._shutdown_reason = None
        self._restarting = False

        signal.signal(signal.SIGTERM, lambda x, y: self.quit("Terminated"))

        # Read config
        if config_dir:
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = Path(appdirs.user_config_dir("ZeroBot", appauthor=False, roaming=True))
        self.config = self.load_config("ZeroBot")
        if "Core" not in self.config:
            self.config["Core"] = {}

        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path(appdirs.user_data_dir("ZeroBot", appauthor=False, roaming=True))

        # Set up our meta path finder for ZeroBot modules
        try:
            module_dirs = self.config["Core"]["ModuleDirs"]
            if not isinstance(module_dirs, list):
                module_dirs = [Path(module_dirs).expanduser()]
            else:
                module_dirs = [Path(d).expanduser() for d in module_dirs]
        except KeyError:
            module_dirs = [Path(appdirs.user_data_dir("ZeroBot", appauthor=False, roaming=True))]
        self.config["Core"]["ModuleDirs"] = module_dirs
        # Add before built-in PathFinder
        sys.meta_path.insert(2, ZeroBotModuleFinder(module_dirs))

        # Configure logging
        self._init_logging()

        # Database Setup
        if "Database" not in self.config:
            self.config["Database"] = {}
        self.config["Database"].setdefault("Backup", {})
        self._db_path = self._config_dir.joinpath(self.config["Database"].get("Filename", "zerobot.sqlite"))
        self.database = self.eventloop.run_until_complete(
            zbdb.create_connection(self._db_path, self._dummy_module, self.eventloop)
        )
        self.eventloop.run_until_complete(self._init_database())

        # Register core commands
        self._register_commands()

        # Load configured protocols
        protocols_loaded = self.eventloop.run_until_complete(self._load_protocols())
        if protocols_loaded:
            self.logger.info(f"Loaded {protocols_loaded} protocols.")
        else:
            self.logger.warning("No protocol modules were loaded.")

        # Load configured features
        features_loaded = self.eventloop.run_until_complete(self._load_features())
        if features_loaded:
            self.logger.info(f"Loaded {features_loaded} feature modules.")
        else:
            self.logger.warning("No feature modules were loaded.")

    @property
    def cmdprefix(self) -> str:
        """Get the command prefix."""
        return self.config["Core"].get("CmdPrefix", "!")

    @property
    def config_dir(self) -> Path:
        """Get the path to ZeroBot's configuration directory."""
        return self._config_dir

    @property
    def configs(self) -> list[Config]:
        """Get a list of currently loaded `Config`s."""
        return self._configs

    @property
    def data_dir(self) -> Path:
        """Get the path to ZeroBot's data directory."""
        return self._data_dir

    def _init_logging(self):
        """Initialize logging configuration."""
        defaults = {
            "Level": "INFO",
            "Enabled": ["console"],
            "Formatters": {
                "default": {
                    "style": "{",
                    "format": "{asctime} {levelname:7} [{name}] {message}",
                    "datefmt": "%T",
                }
            },
            "Handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "default",
                }
            },
        }

        log_sec = self.config.get("Logging", defaults)
        # Ensure the default formatter is always available
        log_sec["Formatters"] = {
            **log_sec.get("Formatters", {}),
            **defaults["Formatters"],
        }
        for handler in log_sec["Handlers"].values():
            # Normalize file paths
            if "filename" in handler:
                log_file = Path(handler["filename"]).expanduser()
                log_file.parent.mkdir(parents=True, exist_ok=True)
                handler["filename"] = log_file

        logging.config.dictConfig({
            "version": 1,  # dictConfig schema version (required)
            "loggers": {
                "ZeroBot": {
                    "level": log_sec["Level"],
                    "handlers": log_sec["Enabled"],
                    "propagate": False,
                }
            },
            "formatters": log_sec["Formatters"],
            "handlers": log_sec["Handlers"],
        })

    async def _init_database(self):
        """Create core database objects."""
        await self.database.executescript(f"""
            CREATE TABLE IF NOT EXISTS "{DBUser.table_name}" (
                "user_id"           INTEGER PRIMARY KEY AUTOINCREMENT,
                "name"              TEXT NOT NULL UNIQUE,
                "created_at"        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                "creation_flags"    INTEGER NOT NULL DEFAULT 0,
                "creation_metadata" TEXT,
                "comment"           TEXT
            );
            CREATE TABLE IF NOT EXISTS "{DBUserAlias.table_name}" (
                "user_id"           INTEGER NOT NULL,
                "alias"             TEXT NOT NULL,
                "case_sensitive"    BOOLEAN NOT NULL DEFAULT 0 CHECK(case_sensitive IN (0,1)),
                "created_at"        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                "creation_flags"    INTEGER NOT NULL DEFAULT 0,
                "creation_metadata" TEXT,
                "comment"           TEXT,
                PRIMARY KEY ("user_id", "alias"),
                FOREIGN KEY ("user_id") REFERENCES "{DBUser.table_name}" ("user_id")
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS "{Participant.table_name}" (
                "participant_id" INTEGER NOT NULL,
                "name"           TEXT NOT NULL UNIQUE,
                "user_id"        INTEGER,
                PRIMARY KEY ("participant_id"),
                FOREIGN KEY ("user_id") REFERENCES "{DBUser.table_name}" ("user_id")
                    ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS "protocols" (
                "identifier" TEXT NOT NULL,
                "name"       TEXT NOT NULL,
                PRIMARY KEY ("identifier")
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS "{Source.table_name}" (
                "source_id" INTEGER NOT NULL,
                "protocol"  TEXT NOT NULL,
                "server"    TEXT,
                "channel"   TEXT,
                PRIMARY KEY ("source_id"),
                FOREIGN KEY ("protocol") REFERENCES "protocols" ("identifier")
                    ON UPDATE CASCADE
            );

            CREATE VIEW IF NOT EXISTS users_all_names (
                user_id, name, case_sensitive
            ) AS
                SELECT user_id, name, 1 FROM "{DBUser.table_name}"
                UNION
                SELECT user_id, alias, case_sensitive FROM "{DBUserAlias.table_name}";

            CREATE VIEW IF NOT EXISTS participants_all_names (
                participant_id, user_id, name, case_sensitive
            ) AS
                SELECT participant_id, user_id, name, 1 FROM "{Participant.table_name}"
                UNION
                SELECT participant_id, user_id, alias, case_sensitive FROM "{DBUserAlias.table_name}"
                JOIN "{Participant.table_name}" USING(user_id);

            CREATE UNIQUE INDEX IF NOT EXISTS "idx_participants_user_id"
            ON "{Participant.table_name}" ("user_id");

            CREATE TRIGGER IF NOT EXISTS tg_update_participant_name_from_user
            AFTER UPDATE OF name ON "{DBUser.table_name}"
            BEGIN
                UPDATE "{Participant.table_name}"
                SET name = new.name
                WHERE user_id = new.user_id;
            END;

            CREATE TRIGGER IF NOT EXISTS tg_update_user_name_from_participant
            AFTER UPDATE OF name ON "{Participant.table_name}"
            BEGIN
                UPDATE "{DBUser.table_name}"
                SET name = new.name
                WHERE user_id = new.user_id;
            END;

            CREATE TRIGGER IF NOT EXISTS tg_new_user_upsert_participants
            AFTER INSERT ON "{DBUser.table_name}"
            BEGIN
                INSERT INTO "{Participant.table_name}" (name, user_id)
                VALUES (new.name, new.user_id)
                ON CONFLICT (name) DO UPDATE
                    SET user_id = new.user_id;
            END;

            CREATE TRIGGER IF NOT EXISTS tg_prevent_linked_participant_delete
            BEFORE DELETE ON "{Participant.table_name}"
            BEGIN
                SELECT RAISE(FAIL, 'Can''t delete participant that is linked to a user')
                FROM "{Participant.table_name}"
                WHERE participant_id = old.participant_id
                    AND user_id IS NOT NULL;
            END;
        """)

    def _register_commands(self):
        """Create and register core commands."""
        cmds = []
        cmd_help = CommandParser("help", "Show help for a command.")
        cmd_help.add_argument(
            "command",
            nargs="*",
            help="The command to get help for. Specify multiple names to get help for subcommands.",
        )
        cmd_help.add_argument("-m", "--module", help="List all commands from the given module")
        cmd_help.add_argument(
            "-f",
            "--full",
            action="store_true",
            help='Include descriptions in the "all" help output.',
        )
        cmds.append(cmd_help)

        target_mod = CommandParser()
        target_mod.add_argument("module", nargs="+", help="Target module(s)")
        target_mod.add_argument(
            "-p",
            "--protocol",
            action="store_const",
            const="protocol",
            default="feature",
            dest="mtype",
            help="Target is a protocol module",
        )
        cmd_module = CommandParser("module", "Manage and query ZeroBot modules")
        add_subcmd = cmd_module.make_adder(metavar="OPERATION", dest="subcmd", required=True)
        add_subcmd("load", description="Load a module", parents=[target_mod])
        add_subcmd("reload", description="Reload a module", parents=[target_mod])
        subcmd_list = add_subcmd("list", description="List available modules")
        subcmd_list.add_argument("-l", "--loaded", action="store_true", help="Only loaded modules")
        list_group = subcmd_list.add_mutually_exclusive_group()
        default_categories = ["protocol", "feature"]
        list_group.add_argument(
            "-f",
            "--feature",
            action="store_const",
            const=["feature"],
            dest="category",
            default=default_categories,
            help="Only feature modules",
        )
        list_group.add_argument(
            "-p",
            "--protocol",
            action="store_const",
            const=["protocol"],
            dest="category",
            default=default_categories,
            help="Only protocol modules",
        )
        add_subcmd("info", description="Show module information", parents=[target_mod])
        cmds.append(cmd_module)

        save_reload_args = CommandParser()
        save_reload_args.add_argument(
            "config_file",
            nargs="*",
            help="Name of config file (without .toml extension). Omit to affect all loaded config files.",
        )
        set_reset_args = CommandParser()
        set_reset_args.add_argument("config_file", help="Name of config file (without .toml extension)")
        cmd_config = CommandParser("config", "Manage configuration")
        add_subcmd = cmd_config.make_adder(metavar="OPERATION", dest="subcmd", required=True)
        add_subcmd("save", description="Save config files to disk", parents=[save_reload_args])
        subcmd_savenew = add_subcmd("savenew", description="Save config file to a new path")
        subcmd_savenew.add_argument("config_file", help="Name of config file (without .toml extension)")
        subcmd_savenew.add_argument("new_path", help="The path to save the config file to")
        add_subcmd(
            "reload",
            description="Reload config files from disk",
            parents=[save_reload_args],
        )
        subcmd_set = add_subcmd("set", description="Modify config settings", parents=[set_reset_args])
        subcmd_set.add_argument(
            "key_path",
            help="The config key to set. Subkeys are separated by dots, e.g. 'Core.Backup.Filename'",
        )
        subcmd_set.add_argument("value", nargs="?", help="The new value. Omit to show the current value.")
        subcmd_reset = add_subcmd(
            "reset",
            description="Reset config settings to last loaded value",
            parents=[set_reset_args],
        )
        subcmd_reset.add_argument(
            "key_path",
            nargs="?",
            help=(
                "The config key to set. Subkeys are separated by dots, "
                "e.g. 'Core.Backup.Filename'. If omitted, the entire "
                "config will be reset."
            ),
        )
        subcmd_reset.add_argument(
            "-d",
            "--default",
            action="store_true",
            help="Set the key to its default value instead. Effectively unsets a config key.",
        )
        cmds.append(cmd_config)

        cmd_version = CommandParser("version", "Show version information")
        cmds.append(cmd_version)

        cmd_restart = CommandParser("restart", "Restart ZeroBot.")
        cmd_restart.add_argument("msg", nargs="*", help="Message sent to protocol modules as a reason")
        cmds.append(cmd_restart)

        cmd_quit = CommandParser("quit", "Shut down ZeroBot.")
        cmd_quit.add_argument("msg", nargs="*", help="Message sent to protocol modules as a reason")
        cmds.append(cmd_quit)

        cmd_wait = CommandParser("wait", "Execute a command after a delay")
        cmd_wait.add_argument(
            "delay",
            help="Amount of time to delay. Accepts the following modifier suffixes: 'ms', 's' (default), 'm', 'h'.",
        )
        cmd_wait.add_argument("command", help="Command to delay")
        cmd_wait.add_argument("args", nargs=argparse.REMAINDER, help="Command arguments")
        cmds.append(cmd_wait)

        cmd_cancel = CommandParser("cancel", "Cancel a waiting command")
        cancel_group = cmd_cancel.add_mutually_exclusive_group()
        cancel_group.add_argument("id", type=int, nargs="?", help="The ID of a waiting command")
        cancel_group.add_argument("-l", "--list", action="store_true", help="List currently waiting commands")
        cmds.append(cmd_cancel)

        cmd_backup = CommandParser("backup", "Create a database backup")
        cmd_backup.add_argument("name", type=Path, help="Backup filename")
        cmds.append(cmd_backup)

        self.command_register("core", *cmds)

    async def _load_protocols(self) -> int:
        """Load all protocols specified in ZeroBot's main config.

        Returns the number of protocols that were successfully loaded.
        """
        for proto in self.config["Core"].get("Protocols", []):
            try:
                await self.load_protocol(proto)
            except ZeroBotModuleError as ex:
                self.logger.exception(ex)
        return len(self._protocols)

    async def _load_features(self) -> int:
        """Load all features specified in ZeroBot's main config.

        Returns the number of feature modules that were successfully loaded.
        """
        for feature in self.config["Core"].get("Modules", []):
            try:
                await self.load_feature(feature)
            except ZeroBotModuleError as ex:
                self.logger.exception(ex)
        return len(self._features)

    def _handle_load_module(self, name: str, module_type: Type[Module]) -> ModuleType:
        """Handle instantiation of `Module` objects.

        Parameters
        ----------
        name : str
            The module name as given to `import`.
        module_type : Type[Module]
            Either `FeatureModule` or `ProtocolModule`.

        Returns
        -------
        types.ModuleType
            The module object if the import was successful.
        """
        if module_type not in [FeatureModule, ProtocolModule]:
            raise TypeError(f"Invalid type '{module_type}'")
        type_str = "feature" if module_type is FeatureModule else "protocol"
        try:
            module = module_type(f"ZeroBot.{type_str}.{name}")
        except ModuleNotFoundError as ex:
            raise NoSuchModule(f"Could not find {type_str} module '{name}': {ex}", mod_id=name, exc=ex) from None
        except Exception as ex:
            raise ModuleLoadError(f"Failed to load {type_str} module '{name}'", mod_id=name) from ex
        self.logger.debug(f"Imported {type_str} module {module!r}")
        return module

    async def load_protocol(self, name: str) -> ProtocolModule:
        """Load and register a protocol module.

        Parameters
        ----------
        name : str
            The name of the protocol module to load. Note that this should
            **not** be the full module name given to an import statement;
            instead, it should be a simple name such as ``irc``.

        Returns
        -------
        ProtocolModule
            Represents the loaded protocol if it was loaded successfully.

        Raises
        ------
        ModuleLoadError
            The module could not be loaded.
        ModuleAlreadyLoaded
            The module is already loaded.
        NoSuchModule
            The module could not be found.
        """
        if name in self._protocols:
            raise ModuleAlreadyLoaded(f"Protocol module '{name}' is already loaded.", mod_id=name)
        module = self._handle_load_module(name, ProtocolModule)
        config = self.load_config(name)
        try:
            connections = await module.handle.module_register(self, config)
        except Exception as ex:
            msg = f"Failed to register protocol module {module!r}"
            raise ModuleRegisterError(msg, mod_id=name) from ex
        self.logger.info(f"Loaded protocol module '{name}'")
        for ctx, coro in connections:
            module.contexts.append(ctx)
            self.eventloop.create_task(coro)  # TODO: meaningful name
        self._protocols[name] = module
        return module

    async def load_feature(self, name) -> FeatureModule:
        """Load and register a ZeroBot feature module.

        Parameters
        ----------
        name : str
            The name of the feature module to load. Note that this should
            **not** be the full module name given to an import statement;
            instead, it should be a simple name such as ``chat``.

        Returns
        -------
        FeatureModule
            Represents the loaded feature module if it was loaded successfully.

        Raises
        ------
        ModuleLoadError
            The module could not be loaded.
        ModuleAlreadyLoaded
            The module is already loaded.
        NoSuchModule
            The module could not be found.
        """
        if name in self._features:
            raise ModuleAlreadyLoaded(f"Feature module '{name}' is already loaded.", mod_id=name)
        module = self._handle_load_module(name, FeatureModule)
        self._features[name] = module
        try:
            await module.handle.module_register(self)
        except Exception as ex:
            del self._features[name]
            msg = f"Failed to register feature module {module!r}"
            raise ModuleRegisterError(msg, mod_id=name) from ex
        self.logger.info(f"Loaded feature module '{name}'")
        return module

    # TODO: reload_protocol will be more complicated to pull off, as we have
    # connections to manage.

    async def reload_feature(self, feature: Union[str, FeatureModule]) -> FeatureModule:
        """Reload a ZeroBot feature module.

        Allows for changes to feature modules to be dynamically introduced at
        runtime, without having to restart ZeroBot.

        Parameters
        ----------
        feature : str or FeatureModule object
            A string with the module identifier (e.g. 'chat' for features.chat)
            or a loaded `FeatureModule` object.

        Returns
        -------
        FeatureModule
            A reference to the module if reloading was successful.
        """
        if isinstance(feature, FeatureModule):
            module = feature
            name = module.identifier
        elif isinstance(feature, str):
            name = feature
            try:
                module = self._features[feature]
            except KeyError:
                msg = f"Cannot reload feature module '{feature}' that is not already loaded."
                raise ModuleNotLoaded(msg, mod_id=name) from None
        else:
            raise TypeError(f"feature type expects 'str' or 'FeatureModule', not '{type(feature)}'")
        try:
            if hasattr(module.handle, "module_unregister"):
                await module.handle.module_unregister()
        except Exception:
            self.logger.warning("Ignoring exception in module_unregister", exc_info=True)
        try:
            try:
                await self._db_connections[name].close()
            except KeyError:
                pass
            self.command_unregister_module(name)
            module.reload()
        except Exception as ex:
            msg = f"Failed to reload feature module '{name}'"
            raise ModuleLoadError(msg, mod_id=name) from ex
        try:
            await module.handle.module_register(self)
        except Exception as ex:
            msg = f"Failed to re-register feature module '{name}'"
            raise ModuleRegisterError(msg, mod_id=name) from ex

        self.logger.info(f"Reloaded feature module '{name}'")
        return module

    def load_config(self, name: str) -> Config:
        """Load a configuration file.

        Parameters
        ----------
        name : str
            The name of the configuration file to load, **without** the
            extension. Files are searched for in ZeroBot's configuration
            directory: `self.config_dir`.

        Returns
        -------
        ZeroBot.Config
            A dictionary-like object representing a parsed TOML config file.
        """
        path = self._config_dir / Path(name).with_suffix(".toml")
        config = Config(path)
        self._configs[path.stem] = config
        try:
            config.load()
        except FileNotFoundError:
            self.logger.warning(f"Config file '{path.name}' doesn't exist; defaults will be assumed where applicable.")
        except TomlDecodeError as ex:
            self.logger.error(f"Failed to load config file '{path.name}': {ex}")
        else:
            self.logger.info(f"Loaded config file '{path.name}'")
        return config

    def protocol_loaded(self, module_id: str) -> bool:
        """Check if a protocol module is currently loaded.

        Parameters
        ----------
        module_id : str
            The identifier of the protocol to check for.
        """
        return module_id in self._protocols

    def feature_loaded(self, module_id: str) -> bool:
        """Check if a feature module is currently loaded.

        Parameters
        ----------
        module_id : str
            The identifier of the feature to check for.
        """
        return module_id in self._features

    def get_loaded_protocols(self) -> list[ProtocolModule]:
        """Get a list of loaded protocol modules.

        Returns
        -------
        List of `ProtocolModule` objects
        """
        return list(self._protocols.values())

    def get_loaded_features(self) -> list[FeatureModule]:
        """Get a list of loaded feature modules.

        Returns
        -------
        List of `FeatureModule` objects
        """
        return list(self._features.values())

    def protocol_available(self, module_id: str) -> bool:
        """Check if a protocol module is available to load.

        Parameters
        ----------
        module_id : str
            The identifier of the protocol to check for.
        """
        return self.protocol_loaded(module_id) or ZeroBot.module.module_available(module_id, "protocol")

    def feature_available(self, module_id: str) -> bool:
        """Check if a feature module is available to load.

        Parameters
        ----------
        module_id : str
            The identifier of the feature to check for.
        """
        return self.feature_loaded(module_id) or ZeroBot.module.module_available(module_id, "feature")

    def get_available_protocols(self) -> list[str]:
        """Get a list of all available protocol modules.

        Returns
        -------
        List of strings
            List of protocol module identifiers.
        """
        modules = []
        for mdir in [ZeroBot.__path__[0]] + self.config["Core"]["ModuleDirs"]:
            mdir = Path(mdir)
            modules += [child.parent.name for child in mdir.glob("protocol/*/protocol.py")]
        return modules

    def get_available_features(self) -> list[str]:
        """Get a list of all available feature modules.

        Returns
        -------
        List of strings
            List of feature module identifiers.
        """
        modules = []
        for mdir in [ZeroBot.__path__[0]] + self.config["Core"]["ModuleDirs"]:
            mdir = Path(mdir)
            modules += [child.stem for child in mdir.glob("feature/*.py")]
        return modules

    def get_contexts(self) -> list[Context]:
        """Get a list of all active protocol `Context`s."""
        return [ctx for proto in self._protocols.values() for ctx in proto.contexts]

    def run(self) -> int:
        """Start ZeroBot's event loop."""
        try:
            self.eventloop.run_forever()
        except KeyboardInterrupt:
            self.logger.info("Interrupt received, shutting down.")
        except Exception:
            self.logger.exception("Unhandled exception raised, shutting down.")
        finally:
            retcode = self._shutdown()
            self.logger.debug("Closing event loop")
            self.eventloop.close()
        if self._restarting:
            self.logger.info(f"Restarting with command line: {sys.argv}")
            os.execl(sys.executable, sys.executable, *sys.argv)
        return retcode

    async def run_async(self, func, *args):
        """Run a synchronous function on the `Core` event loop."""
        return await self.eventloop.run_in_executor(None, func, *args)

    def command_register(self, module_id: str, *cmds: CommandParser):
        """Register requested commands from a module.

        Consecutive calls with the same module will add commands to the
        registry.

        Parameters
        ----------
        module_id : str
            The module identifier to register commands to, e.g. ``'chat'``.
        cmds : One or more `argparse.ArgumentParser` objects
            The commands to register.

        Raises
        ------
        CommandAlreadyRegistered
            The given command has already been registered.
        TypeError
            No commands were given.
        ModuleNotLoaded
            The specified module isn't loaded or currently being loaded.
        """
        if len(cmds) == 0:
            raise TypeError("Must provide at least one command")
        if module_id == "core":
            module = self._dummy_module
        else:
            try:
                module = self._features[module_id]
            except KeyError:
                raise ModuleNotLoaded(
                    f"Module '{module_id}' is not loaded or being loaded.",
                    mod_id=module_id,
                ) from None
        for cmd in cmds:
            cmd._module = module
            self._commands.add(module_id, cmd)

    def command_unregister(self, command: str):
        """Unregister the given command.

        Parameters
        ----------
        command : str
            The name of the command to unregister.

        Raises
        ------
        CommandNotRegistered
            The given command is not registered.
        """
        self._commands.remove(command)

    def command_unregister_module(self, module_id: str):
        """Unregister all commands registered to a module.

        Parameters
        ----------
        module_id : str
            The identifier of the module whose commands are to be unregistered.

        Raises
        ------
        ModuleNotLoaded
            The given module is not loaded.
        ModuleHasNoCommands
            The requested module has no registered commands.
        """
        if module_id not in self._all_modules:
            raise ModuleNotLoaded(f"Module '{module_id}' is not loaded.", mod_id=module_id)
        for cmd in list(self._commands.iter_by_module(module_id)):
            self.command_unregister(cmd.name)

    def command_registered(self, command: str) -> bool:
        """Return whether the given command is registered or not.

        Parameters
        ----------
        command : str
            The name of the command.
        """
        return command in self._commands

    async def database_connect(self, module_id: str, readonly: bool = False) -> zbdb.Connection:
        """Open a new module connection to ZeroBot's database.

        When done, modules should close this connection via
        `Core.database_disconnect` instead of calling the connection object's
        `close` method so that `Core` may clean up any references to the
        object.

        Parameters
        ----------
        module_id : str
            The identifier of the module that is opening a connection.
        readonly : bool, optional
            Whether the connection is read-only. Defaults to `False`.

        Returns
        -------
        ZeroBot.database.Connection
            A connection object for the requested database.

        Raises
        ------
        ModuleNotLoaded
            The specified module isn't loaded or currently being loaded.
        """
        if module_id not in self._all_modules:
            raise ModuleNotLoaded(f"Module '{module_id}' is not loaded.", mod_id=module_id)
        module = self._all_modules[module_id]
        connection = await zbdb.create_connection(self._db_path, module, self.eventloop, readonly)
        self._db_connections[module_id] = connection
        return connection

    async def database_disconnect(self, module_id: str):
        """Closes a module database connection.

        Modules should call this method instead of the `close` method on their
        `Connection` object so that Core may clean up any references to the
        object.

        Parameters
        ----------
        module_id : str
            The identifier of the module whose database connection shall be
            closed.

        Raises
        ------
        ModuleNotLoaded
            The specified module isn't loaded.
        """
        try:
            await self._db_connections[module_id].close()
            del self._db_connections[module_id]
        except KeyError:
            raise ModuleNotLoaded(f"Module {module_id} is not loaded.", mod_id=module_id) from None

    async def database_create_backup(self, target: Union[str, Path] = None):
        """Create a full backup of ZeroBot's active database.

        The `target` parameter and configuration settings for database backups
        control how and where the backup is created.

        Parameters
        ----------
        target : str or Path, optional
            Where to write the backup. If the given path is relative, the
            backup will be relative to the ``Database.Backup.BackupDir``
            setting. If `target` is omitted, both the ``Format`` and
            ``BackupDir`` settings will be used.

        Notes
        -----
        The ``Database.Backup.Format`` option is a format specification for
        `strftime`.
        """
        bcfg = self.config["Database"]["Backup"]
        backup_dir = Path(bcfg.get("BackupDir", f"{self._data_dir}/backup")).expanduser()
        if not backup_dir.is_absolute():
            backup_dir = self._data_dir / backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        if target is None:
            fmt = bcfg.get("Format", "%FT%H%M%S_zerobot.sqlite")
            now = datetime.datetime.now()
            target = backup_dir / now.strftime(fmt)
        else:
            if not isinstance(target, Path):
                target = Path(target)
            if not target.is_absolute():
                target = backup_dir / target
        # TODO: MaxBackups
        await zbdb.create_backup(self.database, target, self.eventloop)

    async def module_send_event(self, event: str, ctx, *args, **kwargs):
        """|coro|

        Push an arbitrary event to all feature modules.

        Parameters
        ----------
        event: str
            The event to send to feature modules. Will try to call a function
            matching `module_on_<event>`.
        ctx: Context
            The protocol context where the event originated.
        *args, **kwargs: Any
            Any remaining arguments are passed on to the module event handler.

        Notes
        -----
        To receive the event, feature modules must have a coroutine defined
        following the pattern: ``module_on_<event>``, where ``<event>`` is the
        event of interest.

        For example, assume fooprotocol.py makes the following call:

            CORE.module_send_event('join', ctx, who, where)

        Then all registered feature modules will be checked for a definition of
        ``module_on_join``, and call it if it exists, passing all arguments
        that were passed to ``module_send_event``.

        """
        self.logger.debug(f"Sending event '{event}', {ctx=}, {args=}, {kwargs=}")
        for module in self._features.values():
            method = getattr(module.handle, f"module_on_{event}", None)
            if callable(method):
                await method(ctx, *args, **kwargs)

    async def module_delay_event(self, delay: Union[int, float], event: str, ctx: Context, *args, **kwargs):
        """|coro|

        Push an arbitrary event to all feature modules after a delay.

        Parameters
        ----------
        delay : float
            The amount of time in seconds to delay the event.
        event: str
            The event to send to feature modules. Will try to call a function
            matching `module_on_<event>`.
        ctx: Context
            The protocol context where the event originated.
        *args, **kwargs: Any
            Any remaining arguments are passed on to the module event handler.
        """
        self.logger.debug(f"Delaying event {event} for {delay} seconds")
        await asyncio.sleep(delay)
        await self.module_send_event(event, ctx, *args, **kwargs)

    async def module_commanded(self, cmd_msg: abc.Message, ctx: Context, delay: float = None):
        """|coro|

        Parse a raw command string using a registered command parser.

        If the command is valid, a `command_<name>` event is sent to the module
        that registered the command. If the command fails to parse, or is not
        registered, an `invalid_command` event is sent to all modules.

        Parameters
        ----------
        cmd_msg : Message
            A ZeroBot `Message` whose content is a command string, likley sent
            by a user on a connected protocol.
        ctx : Context
            The protocol context where the command was sent.
        delay : float, optional
            The amount of time in seconds to delay execution of this command.

        Notes
        -----
        To receive the parsed command, modules must have a coroutine defined
        following the pattern: ``module_command_<name>``, where ``<name>`` is
        the name of the command.

        The coroutine acts as the command handler. It is passed the name of the
        command, a dictionary of options and any values, and a list of
        positional arguments.

        Example
        -------
        Assume a user on FooProtocol sends the following message::

            !frobnicate --color green baz biz

        Then in ``fooprotocol``'s message handler, it has something like this::

            if message.content.startswith(CORE.cmdprefix):
                CORE.module_commanded(message.content, self)

        This passes the command string to ZeroBot's core, which will check if
        ``frobnicate`` has been registered, and attempt to parse it. Assuming
        it succeeds, it then makes a call to the appropriate handler in the
        module that registered ``frobnicate`` with the parsed elements of the
        command as an `argparse.Namespace` object.
        """

        async def delay_wrapper(seconds: float, coro):
            try:
                await asyncio.sleep(seconds)
                await coro
            except asyncio.CancelledError:
                coro.close()

        invoker = cmd_msg.source
        dest = cmd_msg.destination
        cmd_str = cmd_msg.clean_content
        if not cmd_str.startswith(self.cmdprefix):
            raise NotACommand(f"Not a command string: {cmd_str}")
        try:
            name, *args = shellish_split(cmd_str)
        except ValueError:
            await self.module_send_event("invalid_command", ctx, cmd_msg, CmdErrorType.BadSyntax)
            return
        name = name.lstrip(self.cmdprefix)
        if delay:
            self.logger.debug(
                f"Received delayed command from '{invoker}' at '{dest}': "
                f"{name=}, {args=}. Executing in {delay} seconds."
            )
        else:
            self.logger.debug(f"Received command from '{invoker}' at '{dest}': {name=}, {args=}")
        try:
            cmd = self._commands[name]
            namespace = cmd.parse_args(args)
        except KeyError:
            await self.module_send_event("invalid_command", ctx, cmd_msg, CmdErrorType.NotFound)
            return
        except (ArgumentError, ArgumentTypeError, CommandParseError):
            await self.module_send_event("invalid_command", ctx, cmd_msg, CmdErrorType.BadSyntax)
            return
        method = getattr(cmd.module.handle, f"module_command_{name}", None)
        if callable(method):
            parsed = ParsedCommand(name, vars(namespace), cmd, cmd_msg)
            if delay:
                self._delayed_command_count += 1
                wait_id = self._delayed_command_count
                info = WaitingCmdInfo(wait_id, cmd_str, delay, invoker, dest, time.time())
                task = self.eventloop.create_task(
                    delay_wrapper(delay, method(ctx, parsed)),
                    name=f"ZeroBot_Wait_Cmd_{wait_id}",
                )
                self._delayed_commands[wait_id] = (task, info)
                await task
                del self._delayed_commands[wait_id]
            else:
                await method(ctx, parsed)

    def quit(self, reason: str = None):
        """Shut down ZeroBot.

        Automatically handles unregistering all protocol and feature modules.
        If `reason` is given, it is passed along to protocol modules as the
        quit reason.
        """
        self.logger.debug("Stopping event loop")
        self.eventloop.stop()
        self.logger.info("Shutting down ZeroBot" + f' with reason "{reason}"' if reason else "")
        self._shutdown_reason = reason

    # TODO: Proper set of return codes
    def _shutdown(self) -> int:
        """Unregisters all feature and protocol modules.

        Called when ZeroBot is shutting down.
        """
        retcode = 0
        self.logger.debug("Unregistering feature modules.")
        for feature in self._features.values():
            try:
                if hasattr(feature.handle, "module_unregister"):
                    self.eventloop.run_until_complete(feature.handle.module_unregister())
            except Exception:
                self.logger.exception(f"Exception occurred while unregistering feature module '{feature.name}'.")
                retcode = 1
        self.logger.debug("Unregistering protocol modules.")
        for protocol in self._protocols.values():
            try:
                if hasattr(protocol.handle, "module_unregister"):
                    self.eventloop.run_until_complete(
                        protocol.handle.module_unregister(protocol.contexts, self._shutdown_reason)
                    )
            except Exception:
                self.logger.exception(f"Exception occurred while unregistering protocol module '{protocol.name}'.")
                retcode = 1
        self.eventloop.run_until_complete(self.database.close())
        if len(self._db_connections) > 0:
            self.logger.debug("Cleaning up unclosed database connections")
            for module in list(self._db_connections):
                self.eventloop.run_until_complete(self.database_disconnect(module))
        return retcode

    # Core command implementations

    async def module_command_help(self, ctx, parsed):
        """Implementation for Core `help` command."""

        def _create_commandhelp(request):
            usage, desc = request.format_help().split("\n\n")[:2]
            usage = usage.partition(" ")[2]
            desc = desc.rstrip()
            args, opts, subcmds, aliases = {}, {}, {}, []
            prev_arg = ()
            for arg in request._get_positional_actions():
                name = arg.metavar or arg.dest
                if isinstance(arg, _SubParsersAction):
                    args[name] = (arg.help, True)
                    prev_sub = ()
                    for subname, subparser in arg.choices.items():
                        # Aliases follow the canonical name
                        if prev_sub and subparser is prev_sub[1]:
                            subcmds[prev_sub[0]].aliases.append(subname)
                        else:
                            subcmds[subname] = _create_commandhelp(subparser)
                            # Don't include parent command in subcommand name
                            subcmds[subname].name = subname
                            prev_sub = (subname, subparser)
                else:
                    # Aliases follow the canonical name
                    if prev_arg and arg is prev_arg[1]:
                        args[prev_arg[0]].aliases.append(name)
                    else:
                        args[name] = (arg.help, False)
                        prev_arg = (name, arg)
            for opt in request._get_optional_actions():
                names = tuple(opt.option_strings)
                if opt.nargs == 0 or opt.const:
                    # Don't make it seem like flag options take a value
                    metavar = None
                else:
                    metavar = opt.metavar or opt.dest
                opts[names] = (metavar, opt.help)
            return CommandHelp(
                HelpType.CMD,
                request.name,
                desc,
                usage,
                aliases=aliases,
                args=args,
                opts=opts,
                subcmds=subcmds,
            )

        if parsed.args["command"]:
            help_args = parsed.args["command"]
            if len(help_args) > 1 and help_args[0:2] == ["help"] * 2:
                await ctx.reply_command_result(parsed, "I'm afraid that you're far beyond any help...")
                return
            try:
                request = self._commands[help_args[0]]
            except KeyError:
                cmd_help = CommandHelp(HelpType.NO_SUCH_CMD, help_args[0])
            else:
                cmd_help = _create_commandhelp(request)
                help_args.pop(0)
                subcmd = cmd_help
                for sub_request in help_args:
                    try:
                        parent = subcmd
                        subcmd = cmd_help.get_subcmd(sub_request)
                    except KeyError:
                        cmd_help = CommandHelp(HelpType.NO_SUCH_SUBCMD, sub_request, parent=parent)
                        break
                else:
                    cmd_help = subcmd
        elif parsed.args["module"]:
            mod_id = parsed.args["module"]
            if mod_id not in self._features and mod_id != "core":
                cmd_help = CommandHelp(HelpType.NO_SUCH_MOD, mod_id)
            else:
                try:
                    parsers = [parser for parser in self._commands.iter_by_module(mod_id)]
                except KeyError:
                    parsers = []
                desc = parsers[0].module.description
                cmds = {}
                for parser in parsers:
                    mod = cmds.setdefault(mod_id, {})
                    mod[parser.name] = parser.description
                cmd_help = CommandHelp(HelpType.MOD, mod_id, desc, cmds=cmds)
        else:
            cmds = {}
            for mod_id, parsers in self._commands.pairs():
                for parser in parsers:
                    mod = cmds.setdefault(mod_id, {})
                    mod[parser.name] = parser.description
            cmd_help = CommandHelp(HelpType.ALL, cmds=cmds)
        await ctx.core_command_help(parsed, cmd_help)

    async def module_command_module(self, ctx, parsed):
        """Implementation for Core `module` command."""
        mcs = ModuleCmdStatus
        results = []
        subcmd = parsed.subcmd
        if subcmd.endswith("load"):  # load, reload
            mtype = parsed.args["mtype"]
            if parsed.args["mtype"] == "protocol" and subcmd == "reload":
                await ctx.reply_command_result(parsed, "Reloading protocol modules is not yet implemented.")
                return
            for mod_id in parsed.args["module"]:
                try:
                    module = await getattr(self, f"{subcmd}_{mtype}")(mod_id)
                except NoSuchModule:
                    status = mcs.NO_SUCH_MOD
                except (ModuleLoadError, ModuleRegisterError) as ex:
                    status = getattr(mcs, f"{subcmd.upper()}_FAIL")
                    self.logger.exception(ex)
                except ModuleAlreadyLoaded:
                    status = mcs.ALREADY_LOADED
                except ModuleNotLoaded:
                    status = mcs.NOT_YET_LOADED
                else:
                    status = getattr(mcs, f"{subcmd.upper()}_OK")
                results.append(ModuleCmdResult(mod_id, status, mtype))
        elif subcmd == "list":
            status = mcs.QUERY
            for category in parsed.args["category"]:
                if parsed.args["loaded"]:
                    pool = (mod.identifier for mod in getattr(self, f"get_loaded_{category}s")())
                else:
                    pool = getattr(self, f"get_available_{category}s")()
                results.extend(ModuleCmdResult(mod, status, category) for mod in pool)
        elif subcmd == "info":
            status = mcs.QUERY
            mtype = parsed.args["mtype"]
            for mod_id in parsed.args["module"]:
                info = {}
                try:
                    module = getattr(self, f"_{mtype}s")[mod_id]
                except KeyError:
                    if getattr(self, f"{mtype}_available")(mod_id):
                        status = mcs.NOT_YET_LOADED
                    else:
                        status = mcs.NO_SUCH_MOD
                else:
                    for attr in ("name", "description", "author", "version", "license"):
                        info[attr] = getattr(module, attr)
                results.append(ModuleCmdResult(mod_id, status, mtype, info))
        await ctx.core_command_module(parsed, results)

    async def module_command_config(self, ctx, parsed):
        """Implementation for Core `config` command."""
        if parsed.invoker != ctx.owner:
            return
        ccs = ConfigCmdStatus
        results = []
        subcmd = parsed.subcmd
        value = None
        if subcmd.endswith("set"):  # set, reset
            key = parsed.args["key_path"]
            name = parsed.args["config_file"]
            try:
                config = self.configs[name]
            except KeyError:
                status = ccs.NO_SUCH_CONFIG
            else:
                try:
                    old = config.get(key, None) if key is not None else None
                    if subcmd.startswith("re"):
                        if parsed.args["default"]:
                            config.unset(key)
                        else:
                            config.reset(key)
                        status = ccs.RESET_OK
                        if key is not None:
                            new = config.get(key, None)
                            try:
                                await self.module_send_event("config_changed", ctx, name, key, old, new)
                            except Exception:
                                self.logger.exception("Uncaught exception in config_changed handler")
                        else:
                            try:
                                await self.module_send_event("config_reloaded", ctx, name)
                            except Exception:
                                self.logger.exception("Uncaught exception in config_reloaded handler")
                    else:
                        value = parsed.args["value"]
                        if value:
                            config[key] = value
                            status = ccs.SET_OK
                            try:
                                await self.module_send_event("config_changed", ctx, name, key, old, value)
                            except Exception:
                                self.logger.exception("Uncaught exception in config_changed handler")
                        else:
                            value = config.get(key)
                            status = ccs.GET_OK
                except KeyError:
                    status = ccs.NO_SUCH_KEY
            results.append(ConfigCmdResult(config, status, key, value))
        elif subcmd == "save":
            pool = parsed.args["config_file"]
            if not pool:
                pool = self.configs.values()
            for config in pool:
                try:
                    config = self.configs[config]
                    config.save()
                except KeyError:
                    status = ccs.NO_SUCH_CONFIG
                except ZeroBotConfigError as ex:
                    self.logger.exception(ex)
                    status = ccs.SAVE_FAIL
                else:
                    status = ccs.SAVE_OK
                results.append(ConfigCmdResult(config, status))
        elif subcmd == "savenew":
            new_path = parsed.args["new_path"]
            try:
                config = self.configs[parsed.args["config_file"]]
            except KeyError:
                status = ccs.NO_SUCH_CONFIG
            else:
                if new_path is not None:
                    Path(new_path).parent.mkdir(parents=True, exist_ok=True)
                try:
                    config.save(new_path)
                except ZeroBotConfigError as ex:
                    self.logger.exception(ex)
                    status = ccs.SAVE_FAIL
                else:
                    status = ccs.SAVE_OK
            results.append(ConfigCmdResult(config, status, None, None, new_path))
        elif subcmd == "reload":
            pool = parsed.args["config_file"]
            if not pool:
                pool = self.configs.keys()
            for name in pool:
                try:
                    config = self.configs[name]
                    config.load()
                except KeyError:
                    status = ccs.NO_SUCH_CONFIG
                except ZeroBotConfigError as ex:
                    self.logger.exception(ex)
                    status = ccs.RELOAD_FAIL
                else:
                    status = ccs.RELOAD_OK
                    try:
                        await self.module_send_event("config_reloaded", ctx, name)
                    except Exception:
                        self.logger.exception("Uncaught exception in config_reloaded handler")
                results.append(ConfigCmdResult(config, status))
        await ctx.core_command_config(parsed, results)

    async def module_command_version(self, ctx, parsed):
        """Implementation for Core `version` command."""
        info = VersionInfo(
            ZeroBot.__version__,
            "N/A",
            ZeroBot.__author__,
            "https://github.com/ZeroKnight/ZeroBot",
        )
        await ctx.core_command_version(parsed, info)

    async def module_command_quit(self, ctx, parsed):
        """Implementation for Core `quit` command."""
        if parsed.invoker != ctx.owner:
            return
        reason = " ".join(parsed.args["msg"] or []) or "Shutting down"
        self.quit(reason)

    async def module_command_restart(self, ctx, parsed):
        """Implementation for Core `restart` command."""
        if parsed.invoker != ctx.owner:
            return
        reason = " ".join(parsed.args["msg"] or []) or "Restarting"
        self.quit(reason)
        self._restarting = True

    async def module_command_wait(self, ctx, parsed):
        """Implementation for Core `wait` command."""
        factor = {"ms": 1e-3, "s": 1, "m": 60, "h": 3600}
        delay = parsed.args["delay"]
        try:
            delay = float(delay)
        except ValueError:
            suffix = "".join(filter(str.isalpha, delay[-2:]))
            if suffix not in factor.keys():
                await ctx.reply_command_result(
                    parsed,
                    f"Invalid delay suffix. Valid suffixes: {', '.join(factor.keys())}",
                )
            delay = float(delay.replace(suffix, "")) * factor[suffix]
        cmd = parsed.args["command"]
        args = " ".join(parsed.args["args"]) or None
        # XXX: Should have a proper way to do this in abc.Message
        parsed.msg.content = f"{self.cmdprefix}{cmd}"
        parsed.msg.content += f" {args}" if args else ""
        parsed.msg.clean_content = parsed.msg.content
        await self.module_commanded(parsed.msg, ctx, delay)

    async def module_command_cancel(self, ctx, parsed):
        """Implementation for Core `cancel` command."""
        waiting = []
        wait_id = None
        cancelled = False
        if parsed.args["list"]:
            waiting = [pair[1] for pair in self._delayed_commands.values()]
        else:
            wait_id = parsed.args["id"]
            try:
                cancelled = True
                task, waiting = self._delayed_commands[wait_id]
                task.cancel()
            except KeyError:
                pass
        await ctx.core_command_cancel(parsed, cancelled, wait_id, waiting)

    async def module_command_backup(self, ctx, parsed):
        """Implementation for Core `backup` command."""
        if parsed.invoker != ctx.owner:
            return
        file = parsed.args["name"]
        file = file.with_suffix(f"{file.suffix}.sqlite")
        await self.database_create_backup(file)
        await ctx.core_command_backup(parsed, file)
