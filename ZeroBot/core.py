"""core.py

ZeroBot's core provides a foundation for protocol and feature modules to build
off of, collecting and orchestrating events among them.

ZeroBot's core doesn't directly do much of anything on its own, instead relying
on protocol modules to enable ZeroBot to connect to and communicate somewhere,
and feature modules to do something meaningful with that connection.
"""

import asyncio
import logging
import logging.config
from pathlib import Path
from types import ModuleType
from typing import List, Optional, Type, Union

import appdirs
import toml

from ZeroBot.module import Module, ProtocolModule
from ZeroBot.protocol.context import Context

# Minimal initial logging format for any messages before the config is read and
# user logging configuration is applied.
logging.basicConfig(style='{', format='{asctime} {levelname:7} {message}',
                    datefmt='%T', level=logging.ERROR)


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
    config : Dict[str, Any]
        A dictionary containing the parsed configuration from ZeroBot's main
        configuration file.
    config_dir : Path
    config_file : Path
        The path to ZeroBot's main configuration file: ``ZeroBot.toml``.
    eventloop

    Notes
    -----
    There should generally be only one `Core` instance, as it represents
    ZeroBot in his entirety. However, there's nothing stopping you from running
    multiple cores in separate threads, if for some reason you wanted to.
    """

    # NOTE: For post-init runtime loading of protocol/feature modules, it will
    # be necessary to run importlib.invalidate_caches() so that in the event of
    # a module being newly written/added while ZeroBot is running, the import
    # mechanism will see the new file.

    # TODO: Need to make sure that modules are stopped correctly when quitting
    # ZeroBot, or sending a Ctrl-C. Discord should call close(), pydle should
    # disconnect(), etc.

    def __init__(self, config_dir: Union[str, Path] = None,
                 eventloop: asyncio.AbstractEventLoop = None):
        self.eventloop = eventloop if eventloop else asyncio.get_event_loop()
        self.logger = logging.getLogger('ZeroBot')
        self._protocols = {}  # maps protocol names to their ProtocolModule
        self._features = {}  # maps feature module names to their Module

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

        # Load configured protocols
        protocols_loaded = self._load_protocols()
        if protocols_loaded:
            self.logger.info(f'Loaded {protocols_loaded} protocols.')
        else:
            msg = 'Could not load any protocol modules.'
            self.logger.critical(msg)
            raise RuntimeError(msg)  # TBD: Make this a custom exception?

        # Load configured features
        features_loaded = self._load_features()
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

    @property
    def config_file(self) -> Path:
        """Get the path to ZeroBot's config file."""
        return self._config_dir / 'ZeroBot.toml'

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

    def _load_protocols(self) -> int:
        """Get list of requested protocols from config and load them.

        Returns the number of protocols that were successfully loaded.
        """
        for proto in self.config['Core'].get('Protocols', []):
            self.load_protocol(proto)
        return len(self._protocols)

    def _load_features(self) -> int:
        """Get list of requested feature modules from config and laod them.

        Returns the number of feature modules that were successfully loaded.
        """
        for feature in self.config['Core'].get('Modules', []):
            self.load_feature(feature)
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

    def load_protocol(self, name: str) -> Optional[ProtocolModule]:
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
        try:
            config = self.load_config(name)
        except toml.TomlDecodeError:
            config = {}
        try:
            connections = module.handle.module_register(self, config)
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

    def load_feature(self, name) -> Optional[Module]:
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
            module.handle.module_register(self)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(
                f'Failed to register feature module {module!r}')
            return None
        self.logger.info(f"Loaded feature module '{name}'")
        return module

    # TODO: reload_protocol will be more complicated to pull off, as we have
    # connections to manage.

    def reload_feature(self, feature: Union[str, Module]) -> Optional[Module]:
        """Reload a ZeroBot feature module.

        Allows for changes to feature modules to be dynamically introduced at
        runtime, without having to restart ZeroBot.

        Parameters
        ----------
        feature : str or Module object
            A string with the module short-name (e.g. 'chat' for features.chat)
            or a loaded `Module` object.

        Returns
        -------
        Module or None
            A reference to the module if reloading was successful, else `None`.
        """
        if isinstance(feature, Module):
            module = feature
            name = module.short_name
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
            module.handle.module_unregister()
            module.reload()
            module.handle.module_register(self)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception(f"Failed to reload feature module '{name}'")
            return None
        self.logger.info(f"Reloaded feature module '{name}'")
        return module

    def load_config(self, name: str) -> dict:
        """Load a configuration file .

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
        try:
            config = toml.load(path)
        except FileNotFoundError:
            self.logger.warning(f"Config file '{path.name}' doesn't exist; "
                                'defaults will be assumed where applicable.')
            config = {}
        except toml.TomlDecodeError as ex:
            self.logger.error(
                f"Failed to load config file '{path.name}': {ex}")
            raise
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
        finally:
            self.logger.debug('Stopping event loop')
            self.eventloop.stop()

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
