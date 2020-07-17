"""core.py

ZeroBot's core provides a foundation for protocol and feature modules to build
off of, collecting and orchestrating events among them.

ZeroBot's core doesn't directly do much of anything on its own, instead relying
on protocol modules to enable ZeroBot to connect to and communicate somewhere,
and feature modules to do something meaningful with that connection.
"""

import asyncio
import datetime
import logging
import logging.config
from argparse import ArgumentError, ArgumentTypeError, _SubParsersAction
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator, List, Optional, Tuple, Type, Union

import appdirs
from toml import TomlDecodeError

import ZeroBot
from ZeroBot.common import (CommandAlreadyRegistered, CommandHelp,
                            CommandParser, HelpType, ParsedCommand, abc)
from ZeroBot.config import Config
from ZeroBot.module import CoreModule, Module, ProtocolModule
from ZeroBot.protocol.context import Context

# Minimal initial logging format for any messages before the config is read and
# user logging configuration is applied.
logging.basicConfig(style='{', format='{asctime} {levelname:7} {message}',
                    datefmt='%T', level=logging.ERROR)


class CommandRegistry:
    """Registry of commands and the modules that registered them.

    Supports lookup of all commands registered to a module, or what module
    a particular command is registered to.
    """

    def __init__(self):
        self._registry = {'by_name': {}, 'by_module': {}}

    def __getitem__(self, name: str) -> CommandParser:
        return self._registry['by_name'][name]

    def __iter__(self):
        return iter(self._registry['by_name'])

    def iter_by_module(self, module_id: str) -> Iterator[CommandParser]:
        """Generator that yields all commands registered to a module.

        Parameters
        ----------
        module_id : str
            The identifier of the module.

        Raises
        ------
        KeyError
            The requested module has no registered commands.
        """
        yield from self._registry['by_module'][module_id]

    def pairs(self) -> Iterator[Tuple[str, List[CommandParser]]]:
        """Generator that yields pairs of module identifiers their parsers."""
        for module, cmds in self._registry['by_module'].items():
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
            raise CommandAlreadyRegistered(command.name, command.module)
        self._registry['by_name'][command.name] = command
        self._registry['by_module'].setdefault(module_id, []).append(command)

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
            del self._registry['by_name'][command]
            for module, cmd in self.pairs():
                if cmd.name == command:
                    self._registry['by_registry'][module].remove(cmd)
                    return
        except KeyError:
            raise KeyError(f"Command '{command}' is not registered")

    def modules_registered(self) -> List[Module]:
        """Return a list of `Module`s that have registered commands."""
        return [cmds[0].module
                for cmds in self._registry['by_module'].values()]


@dataclass
class VersionInfo:
    """Version and miscellaneous build information for ZeroBot."""

    version: str
    release_date: datetime.date
    author: str


class Core:
    """A class representing ZeroBot's core functionality.

    The core is more or less the brain (if you could call it that) of ZeroBot;
    it is responsible for loading and orchestrating the protocol and feature
    modules that actually provide functionality, as well as directly handling
    configuration.

    Parameters
    ----------
    config_path : str or Path object, optional
        Specifies the path to ZeroBot's configuration directory; defaults to
        ``<user_config_dir>/ZeroBot``.
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
    eventloop

    Notes
    -----
    There should generally be only one `Core` instance, as it represents
    ZeroBot in his entirety. However, there's nothing stopping you from running
    multiple cores in separate threads, if for some reason you wanted to.
    """

    def __init__(self, config_dir: Union[str, Path] = None,
                 eventloop: asyncio.AbstractEventLoop = None):
        self.eventloop = eventloop if eventloop else asyncio.get_event_loop()
        self.logger = logging.getLogger('ZeroBot')
        self._protocols = {}  # maps protocol names to their ProtocolModule
        self._features = {}  # maps feature module names to their Module
        self._dummy_module = CoreModule(self, ZeroBot.__version__)
        self._commands = CommandRegistry()
        self._shutdown_reason = None

        # Read config
        if config_dir:
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = Path(appdirs.user_config_dir(
                'ZeroBot', appauthor=False, roaming=True))
        self.config = self.load_config('ZeroBot')
        if 'Core' not in self.config:
            self.config['Core'] = {}

        # Configure logging
        self._init_logging()

        self._cmdprefix = self.config['Core'].get('CmdPrefix', '!')

        # Register core commands
        self._register_commands()

        # Load configured protocols
        protocols_loaded = self.eventloop.run_until_complete(
            self._load_protocols())
        if protocols_loaded:
            self.logger.info(f'Loaded {protocols_loaded} protocols.')
        else:
            msg = 'Could not load any protocol modules.'
            self.logger.critical(msg)
            raise RuntimeError(msg)  # TBD: Make this a custom exception?

        # Load configured features
        features_loaded = self.eventloop.run_until_complete(
            self._load_features())
        if features_loaded:
            self.logger.info(f'Loaded {features_loaded} feature modules.')
        else:
            self.logger.warning('No feature modules were loaded.')

    @property
    def cmdprefix(self) -> str:
        """Get the command prefix."""
        return self._cmdprefix

    @property
    def config_dir(self) -> Path:
        """Get the path to ZeroBot's configuration directory."""
        return self._config_dir

    def _init_logging(self):
        """Initialize logging configuration."""
        defaults = {
            'Level': 'INFO',
            'Enabled': ['console'],
            'Formatters': {
                'default': {
                    'style': '{',
                    'format': '{asctime} {levelname:7} [{name}] {message}',
                    'datefmt': '%T'
                }
            },
            'Handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'level': 'INFO',
                    'formatter': 'default'
                }
            }
        }

        log_sec = self.config.get('Logging', defaults)
        # Ensure the default formatter is always available
        log_sec['Formatters'] = {**log_sec.get('Formatters', {}),
                                 **defaults['Formatters']}
        for handler in log_sec['Handlers'].values():
            # Normalize file paths
            if 'filename' in handler:
                handler['filename'] = Path(handler['filename']).expanduser()

        logging.config.dictConfig({
            'version': 1,  # dictConfig schema version (required)
            'loggers': {
                'ZeroBot': {
                    'level': log_sec['Level'],
                    'handlers': log_sec['Enabled'],
                    'propagate': False
                }
            },
            'formatters': log_sec['Formatters'],
            'handlers': log_sec['Handlers']
        })

    def _register_commands(self):
        """Create and register core commands."""
        cmds = []
        cmd_help = CommandParser('help', 'Show help for a command.')
        cmd_help.add_argument(
            'command', nargs='*',
            help=('The command to get help for. Specify multiple names to get '
                  'help for subcommands.'))
        cmd_help.add_argument(
            '-m', '--module', help='List all commands from the given module')
        cmd_help.add_argument(
            '-f', '--full', action='store_true',
            help='Include descriptions in the "all" help output.')
        cmds.append(cmd_help)

        target_mod = CommandParser()
        target_mod.add_argument('module', nargs='+', help='Target module(s)')
        target_mod.add_argument(
            '-p', '--protocol', action='store_true',
            help='Target is a protocol module')
        cmd_module = CommandParser('module',
                                   'Manage and query ZeroBot modules')
        subp = cmd_module.add_subparsers(metavar='OPERATION', required=True)
        add_subcmd = cmd_module.add_subcommand
        add_subcmd(subp, 'load', description='Load a module',
                   parents=[target_mod])
        add_subcmd(subp, 'reload', description='Reload a module',
                   parents=[target_mod])
        subcmd_list = add_subcmd(subp, 'list',
                                 description='List available modules')
        subcmd_list.add_argument(
            '-l', '--loaded', action='store_true', help='Only loaded modules')
        cmd_help = subcmd_list.add_mutually_exclusive_group()
        cmd_help.add_argument(
            '-f', '--feature', action='store_true',
            help='Only feature modules')
        cmd_help.add_argument(
            '-p', '--protocol', action='store_true',
            help='Only protocol modules')
        add_subcmd(subp, 'info', description='Show module information',
                   parents=[target_mod])
        cmds.append(cmd_module)

        cmd_version = CommandParser('version', 'Show version information')
        cmds.append(cmd_version)

        cmd_quit = CommandParser('quit', 'Shut down ZeroBot.')
        cmd_quit.add_argument(
            'msg', nargs='*',
            help='Message sent to protocol modules as a reason')
        cmds.append(cmd_quit)

        # TODO: WeeChat wait command
        # TODO: restart command

        self.command_register('core', *cmds)

    async def _load_protocols(self) -> int:
        """Load all protocols specified in ZeroBot's main config.

        Returns the number of protocols that were successfully loaded.
        """
        for proto in self.config['Core'].get('Protocols', []):
            await self.load_protocol(proto)
        return len(self._protocols)

    async def _load_features(self) -> int:
        """Load all features specified in ZeroBot's main config.

        Returns the number of feature modules that were successfully loaded.
        """
        for feature in self.config['Core'].get('Modules', []):
            await self.load_feature(feature)
        return len(self._features)

    def _handle_load_module(self, name: str,
                            module_type: Type[Module]) -> ModuleType:
        """Handle instantiation of `Module` objects.

        Parameters
        ----------
        name : str
            The module name as given to `import`.
        module_type : type
            Either `Module` or `ProtocolModule`.

        Returns
        -------
        types.ModuleType or None
            The module object if the import was successful, else `None`.
        """
        if module_type not in [Module, ProtocolModule]:
            raise TypeError(f"Invalid type '{module_type}'")
        type_str = 'feature' if module_type is Module else 'protocol'

        try:
            if module_type is ProtocolModule:
                module = ProtocolModule(f'ZeroBot.protocol.{name}.protocol')
            else:
                module = Module(f'ZeroBot.feature.{name}')
        except ModuleNotFoundError as ex:
            self.logger.error(
                f"Could not find {type_str} module '{name}': {ex}")
            return None
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(f"Failed to load {type_str} module '{name}'")
            return None
        self.logger.debug(f'Imported {type_str} module {module!r}')
        return module

    async def load_protocol(self, name: str) -> Optional[ProtocolModule]:
        """Load and register a protocol module.

        Parameters
        ----------
        name : str
            The name of the protocol module to load. Note that this should
            **not** be the full module name given to an import statement;
            instead, it should be a simple name such as ``irc``.

        Returns
        -------
        ProtocolModule or None
            A class representing the loaded protocol, or `None` if the module
            could not be loaded.
        """
        module = self._handle_load_module(name, ProtocolModule)
        if module is None:
            return None
        config = self.load_config(name)
        try:
            connections = await module.handle.module_register(self, config)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(
                f'Failed to register protocol module {module!r}')
            return None
        self.logger.info(f"Loaded protocol module '{name}'")
        for ctx, coro in connections:
            module.contexts.append(ctx)
            self.eventloop.create_task(coro)  # TODO: meaningful name
        self._protocols[name] = module
        return module

    async def load_feature(self, name) -> Optional[Module]:
        """Load and register a ZeroBot feature module.

        Parameters
        ----------
        name : str
            The name of the feature module to load. Note that this should
            **not** be the full module name given to an import statement;
            instead, it should be a simple name such as ``chat``.

        Returns
        -------
        Module or None
            A class representing the loaded feature, or `None` if the module
            could not be loaded.
        """
        module = self._handle_load_module(name, Module)
        if module is None:
            return None
        self._features[name] = module
        try:
            await module.handle.module_register(self)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(
                f'Failed to register feature module {module!r}')
            return None
        self.logger.info(f"Loaded feature module '{name}'")
        return module

    # TODO: reload_protocol will be more complicated to pull off, as we have
    # connections to manage.

    async def reload_feature(self,
                             feature: Union[str, Module]) -> Optional[Module]:
        """Reload a ZeroBot feature module.

        Allows for changes to feature modules to be dynamically introduced at
        runtime, without having to restart ZeroBot.

        Parameters
        ----------
        feature : str or Module object
            A string with the module identifier (e.g. 'chat' for features.chat)
            or a loaded `Module` object.

        Returns
        -------
        Module or None
            A reference to the module if reloading was successful, else `None`.
        """
        if isinstance(feature, Module):
            module = feature
            name = module.identifier
        elif isinstance(feature, str):
            name = feature
            try:
                module = self._features[feature]
            except KeyError:
                self.logger.error(
                    (f"Cannot reload feature module '{feature}' that is not ",
                     'already loaded.'))
                return None
        else:
            raise TypeError(("feature type expects 'str' or 'Module', not ",
                             f"'{type(feature)}'"))
        try:
            await module.handle.module_unregister()
            module.reload()
            await module.handle.module_register(self)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(f"Failed to reload feature module '{name}'")
            return None
        self.logger.info(f"Reloaded feature module '{name}'")
        return module

    def load_config(self, name: str) -> dict:
        """Load a configuration file.

        Parameters
        ----------
        name : str
            The name of the configuration file to load, **without** the
            extension. Files are searched for in ZeroBot's configuration
            directory: `self.config_dir`.

        Returns
        -------
        dict
            A dictionary representing a parsed TOML config file.
        """
        path = self._config_dir / Path(name).with_suffix('.toml')
        config = Config(path)
        try:
            config.load()
        except FileNotFoundError:
            self.logger.warning(f"Config file '{path.name}' doesn't exist; "
                                'defaults will be assumed where applicable.')
        except TomlDecodeError as ex:
            self.logger.error(
                f"Failed to load config file '{path.name}': {ex}")
        else:
            self.logger.info(f"Loaded config file '{path.name}'")
        return config

    def protocol_loaded(self, name: str) -> bool:
        """Return whether the given protocol is loaded or not.

        Parameters
        ----------
        name : str
            The name of the protocol to check.
        """
        return name in self._protocols

    def feature_loaded(self, name: str) -> bool:
        """Return whether the given feature is loaded or not.

        Parameters
        ----------
        name : str
            The name of the feature to check.
        """
        return name in self._features

    def get_loaded_protocols(self) -> List[ProtocolModule]:
        """Get a list of loaded protocol modules.

        Returns
        -------
        List of `ProtocolModule` objects
        """
        return list(self._protocols.values())

    def get_loaded_features(self) -> List[Module]:
        """Get a list of loaded feature modules.

        Returns
        -------
        List of `Module` objects
        """
        return list(self._features.values())

    def run(self):
        """Start ZeroBot's event loop."""
        try:
            self.eventloop.run_forever()
        except KeyboardInterrupt:
            self.logger.info('Interrupt received, shutting down.')
        except Exception:  # pylint: disable=broad-except
            self.logger.exception('Unhandled exception raised, shutting down.')
        finally:
            self._shutdown()
            self.logger.debug('Closing event loop')
            self.eventloop.close()

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
        ValueError
            The specified module isn't loaded or currently being loaded.
        """
        if len(cmds) == 0:
            raise TypeError('Must provide at least one command')
        if module_id == 'core':
            module = self._dummy_module
        else:
            try:
                module = self._features[module_id]
            except KeyError:
                raise ValueError(
                    f"Module '{module}' is not loaded or being loaded.")
        for cmd in cmds:
            cmd._module = module  # pylint: disable=protected-access
            self._commands.add(module_id, cmd)

    def command_unregister(self, command: str):
        """Unregister the given command.

        Parameters
        ----------
        command : str
            The name of the command to unregister.

        Raises
        ------
        KeyError
            The given command is not registered.
        """
        self._commands.remove(command)

    def command_unregister_module(self, module_id: str):
        """Unregister all commands registered to a module.

        Parameters
        ----------
        module_id : str
            The identifier of the module whose commands are to be unregistered.
        """
        # TODO: raise ModuleNotLoaded if needed
        for cmd in self._commands.iter_by_module(module_id):
            self.command_unregister(cmd.name)

    def command_registered(self, command: str) -> bool:
        """Return whether the given command is registered or not.

        Parameters
        ----------
        command : str
            The name of the command.
        """
        return command in self._commands

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
        self.logger.debug(
            f"Sending event '{event}', {ctx=}, {args=}, {kwargs=}")
        for module in self._features.values():
            method = getattr(module.handle, f'module_on_{event}', None)
            if callable(method):
                await method(ctx, *args, **kwargs)

    async def module_delay_event(self, delay: Union[int, float], event: str,
                                 ctx: Context, *args, **kwargs):
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
        self.logger.debug(f'Delaying event {event} for {delay} seconds')
        await asyncio.sleep(delay)
        await self.module_send_event(event, ctx, *args, **kwargs)

    async def module_commanded(self, cmd_msg: abc.Message, ctx: Context):
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
        cmd_str = cmd_msg.content
        if not cmd_str.startswith(self.cmdprefix):
            # TODO: proper NotACommand exception
            raise Exception(f'Not a command string: {cmd_str}')
        try:
            name, *args = cmd_str.split(' ')
            name = name.lstrip(self.cmdprefix)
            cmd = self._commands[name]
            namespace = cmd.parse_args(args)
        except (KeyError, ArgumentError, ArgumentTypeError):
            await self.module_send_event('invalid_command', ctx, cmd_msg)
            return
        method = getattr(cmd.module.handle, f'module_command_{name}', None)
        if callable(method):
            parsed = ParsedCommand(
                name, vars(namespace), cmd, cmd_msg.source,
                cmd_msg.destination)
            await method(ctx, parsed)

    def quit(self, reason: str = None):
        """Shut down ZeroBot.

        Automatically handles unregistering all protocol and feature modules.
        If `reason` is given, it is passed along to protocol modules as the
        quit reason.
        """
        self.logger.debug('Stopping event loop')
        self.eventloop.stop()
        self.logger.info('Shutting down ZeroBot'
                         + f' with reason "{reason}"' if reason else '')
        self._shutdown_reason = reason

    def _shutdown(self):
        """Unregisters all feature and protocol modules.

        Called when ZeroBot is shutting down.
        """
        self.logger.debug('Unregistering feature modules.')
        for feature in self._features.values():
            try:
                self.eventloop.run_until_complete(
                    feature.handle.module_unregister())
            except Exception:  # pylint: disable=broad-except
                self.logger.exception(
                    'Exception occurred while unregistering feature '
                    f"module '{feature.name}'.")
        self.logger.debug('Unregistering protocol modules.')
        for protocol in self._protocols.values():
            try:
                self.eventloop.run_until_complete(
                    protocol.handle.module_unregister(protocol.contexts,
                                                      self._shutdown_reason))
            except Exception:  # pylint: disable=broad-except
                self.logger.exception(
                    'Exception occurred while unregistering protocol '
                    f"module '{protocol.name}'.")

    # Core command implementations

    async def module_command_help(self, ctx, parsed):
        """Implementation for Core `help` command."""
        def _create_commandhelp(request):
            usage, desc = request.format_help().split('\n\n')[:2]
            usage = usage.partition(' ')[2]
            desc = desc.rstrip()
            args, opts, subcmds = {}, {}, {}
            for arg in request._get_positional_actions():
                name = arg.metavar or arg.dest
                if isinstance(arg, _SubParsersAction):
                    args[name] = (arg.help, True)
                    for subname, subparser in arg.choices.items():
                        subcmds[subname] = _create_commandhelp(subparser)
                        # Don't include parent command in subcommand name
                        subcmds[subname].name = subname
                else:
                    args[name] = (arg.help, False)
            for opt in request._get_optional_actions():
                names = tuple(opt.option_strings)
                metavar = opt.metavar or opt.dest
                opts[names] = (metavar, opt.help)
            return CommandHelp(HelpType.CMD, request.name, desc, usage,
                               args=args, opts=opts, subcmds=subcmds)

        if parsed.args['command']:
            help_args = parsed.args['command']
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
                        subcmd = cmd_help.subcmds[sub_request]
                    except KeyError:
                        cmd_help = CommandHelp(HelpType.NO_SUCH_SUBCMD,
                                               sub_request, parent=parent)
                        break
                else:
                    cmd_help = subcmd
        elif parsed.args['module']:
            mod_id = parsed.args['module']
            if mod_id not in self._features and mod_id != 'core':
                cmd_help = CommandHelp(HelpType.NO_SUCH_MOD, mod_id)
            else:
                try:
                    parsers = [parser for parser in
                               self._commands.iter_by_module(mod_id)]
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

    async def module_command_version(self, ctx, parsed):
        """Implementation for Core `version` command."""
        info = VersionInfo(ZeroBot.__version__, 'N/A', ZeroBot.__author__)
        await ctx.core_command_version(parsed, info)

    async def module_command_quit(self, ctx, parsed):
        """Implementation for Core `quit` command."""
        reason = ' '.join(parsed.args['msg'] or []) or 'Shutting down'
        self.quit(reason)
