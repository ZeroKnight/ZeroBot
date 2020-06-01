"""core.py

ZeroBot's core provides a foundation for protocol and feature modules to build
off of, collecting and orchestrating events among them.

ZeroBot's core doesn't directly do much of anything on its own, instead relying
on protocol modules to enable ZeroBot to connect to and communicate somewhere,
and feature modules to do something meaningful with that connection.
"""

import asyncio
from typing import Union

from ZeroBot.module import Module, ProtocolModule
from ZeroBot.protocol.context import Context


class Core:
    """blah

    Attributes
    ----------
    """

    # NOTE: For post-init runtime loading of protocol/feature modules, it will
    # be necessary to run importlib.invalidate_caches() so that in the event of
    # a module being newly written/added while ZeroBot is running, the import
    # mechanism will see the new file.

    # TODO: Need to make sure that modules are stopped correctly when quitting
    # ZeroBot, or sending a Ctrl-C. Discord should call close(), pydle should
    # disconnect(), etc.

    def __init__(self, eventloop=None):
        self.eventloop = eventloop if eventloop else asyncio.get_event_loop()
        self._protocols = {}  # maps protocol names to their ProtocolModule
        self._features = {}  # maps feature module names to their Module

        # do config loading stuff

        # IDEA: As part of module registration, the core could send the
        # relevant config section data structure to the module, removing the
        # burden from them to load it themselves. Since they will be passed
        # a reference to the data structure, both the module and the core would
        # see the most up to date changes.

        protocols_loaded = self._load_protocols()
        if protocols_loaded:
            # log that `loaded` number of protocols were loaded, then list them
            print(f'loaded {protocols_loaded} protocols')
        else:
            # log an error that no protocols were able to be loaded and quit
            # use logging.exception() ?
            raise RuntimeError('Could not load any protocol modules.')

        features_loaded = self._load_features()
        # log that `loaded` number of modules were loaded, then list them
        print(f'loaded {features_loaded} modules')

    def _load_protocols(self) -> int:
        """Get list of requested protocols from config and load them.

        Returns the number of protocols that were successfully loaded.

        TEMP: Currently just a stub until config is implemented
        """
        # normally we'd pull from the config here
        stub_list = ['irc', 'discord']
        for proto in stub_list:
            self.load_protocol(proto)
        return len(self._protocols)

    def _load_features(self) -> int:
        """Get list of requested feature modules from config and laod them.

        Returns the number of feature modules that were successfull loaded.

        TEMP: Currently just a stub until config is implemented
        """
        stub_list = ['chat']
        for feature in stub_list:
            self.load_feature(feature)
        return len(self._features)

    def load_protocol(self, name: str) -> ProtocolModule:
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
            A class representing the loaded protocol.
        """
        # TODO: module search path?
        try:
            module = ProtocolModule(f'ZeroBot.protocol.{name}.protocol')
        except ModuleNotFoundError:
            # log failure to find protocol module or one of itss
            # dependencies self.log_error(...)
            raise  # TEMP
        else:
            self._protocols[name] = module

        ctx, coro = module.handle.module_register(self)
        module.contexts.append(ctx)
        self.eventloop.create_task(coro)  # TODO: meaningful name
        return module

    def load_feature(self, name) -> Module:
        """Load and register a ZeroBot feature module.

        Parameters
        ----------
        name : str
            The name of the feature module to load. Note that this should
            **not** be the full module name given to an import statement;
            instead, it should be a simple name such as ``chat``.

        Returns
        -------
        Module
            A class representing the loaded feature.
        """
        # TODO: module search path?
        try:
            module = Module(f'ZeroBot.feature.{name}')
        except ModuleNotFoundError:
            # log failure to find feature module or one of its dependencies
            # self.log_error(...)
            raise  # TEMP
        else:
            self._features[name] = module

        module.handle.module_register()
        return module

    def run(self):
        """Start ZeroBot's event loop."""
        try:
            self.eventloop.run_forever()
        finally:
            print('Stopping event loop')
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
        print(f'Delaying event [{event}] for {delay} seconds...')
        await asyncio.sleep(delay)
        print(f'Sending delayed event [{event}]: {ctx=}, {args=}, {kwargs=}')
        await self.module_send_event(event, ctx, *args, **kwargs)
