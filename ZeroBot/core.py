"""core.py

ZeroBot's core provides a foundation for protocol and feature modules to build
off of, collecting and orchestrating events among them.

ZeroBot's core doesn't directly do much of anything on its own, instead relying
on protocol modules to enable ZeroBot to connect to and communicate somewhere,
and feature modules to do something meaningful with that connection.
"""

import asyncio
import importlib


class Core:
    """blah

    Attributes
    ----------
    """

    # NOTE: For post-init runtime loading of protocol/feature modules, it will
    # be necessary to run importlib.invalidate_caches() so that in the event of
    # a module being newly written/added while ZeroBot is running, the import
    # mechanism will see the new file.

    # TODO: Decide on an interface that protocol modules must implement in
    # order for the core to Initialize them, provide a config, and request any
    # number of contexts so that the core may orchestrate them into an event
    # loop

    # TODO: How do we go about dynamically adding/removing "contexts" from the
    # event loop? Ideally the interface would be something like:
    # add_context(...) and remove_context(...), but how do we do this on the
    # asyncio level?
    # IIUC, the former can just be done with asyncio.ensure_future, and the
    # latter will probably require stashing the Future of each context and
    # calling cancel() or something

    def __init__(self):
        self.eventloop = asyncio.get_event_loop()
        self._protocols = {}  # maps protocol names to their module
        self._modules = {}  # maps feature module names to their module
        self._contexts = []

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
            # TODO: figure out how to properly "quit"
            raise RuntimeError('Could not load any protocol modules.')

        # Register protocols
        # TBD: Should this be done in _load_protocols? Or its own method?
        for name, proto in self._protocols.items():
            print(f'init {proto}')
            proto.module_register(self)
            self._contexts.append(
                self._protocols[name].module_get_context(self.eventloop))
            # do other stuff, error checking, etc

        modules_loaded = self._load_modules()
        # log that `loaded` number of modules were loaded, then list them
        print(f'loaded {modules_loaded} modules')

    def run(self):
        # TODO: stub
        for context in self._contexts:
            asyncio.ensure_future(context[1], loop=self.eventloop)
        return self.eventloop

    def _load_protocols(self) -> int:
        """Get list of requested protocols from config and load them.

        Returns the number of protocols that were successfully loaded.

        TEMP: Currently just a stub until config is implemented
        """
        num_loaded = 0
        # normally we'd pull from the config here
        stub_list = ['irc', 'discord']
        for proto in stub_list:
            try:
                module = importlib.import_module(
                    f'ZeroBot.protocol.{proto}.protocol')
            except ModuleNotFoundError:
                # log failure to find protocol module or one of its
                # dependencies self.log_error(...)
                raise  # TEMP
            else:
                self._protocols[proto] = module
                num_loaded += 1
        return num_loaded

    def _load_modules(self) -> int:
        """Get list of requested feature modules from config and laod them.

        Returns the number of feature modules that were successfull loaded.

        TEMP: Currently just a stub until config is implemented
        """
        num_loaded = 0
        stub_list = ['chat']
        for feature in stub_list:
            try:
                module = importlib.import_module(f'ZeroBot.feature.{feature}')
            except ModuleNotFoundError:
                # log failure to find feature module or one of its dependencies
                # self.log_error(...)
                raise  # TEMP
            else:
                self._modules[feature] = module
                num_loaded += 1
        return num_loaded

    async def module_send_event(self, event: str, ctx, *args, **kwargs):
        """|coro|

        Push an arbitrary event to all feature modules, specified by ``event``.

        To receive the event, feature modules must have a coroutine defined
        following the pattern: `module_on_<event>`, where `<event>` is the
        event of interest.

        For example, assume fooprotocol.py makes the following call:

            CORE.module_send_event('join', ctx, who, where)

        Then all registered feature modules will be checked for a definition of
        `module_on_join`, and call it if it exists, passing all arguments that
        were passed to `module_send_event`.

        Parameters
        ----------
        event: str
            The event to send to feature modules. Will try to call a function
            matching `module_on_<event>`.
        ctx: 'Context'
            The protocol context where the event originated.
        *args, **kwargs: Any
            Any remaining arguments are passed on to the module event handler.
        """
        for module in self._modules.values():
            method = getattr(module, f'module_on_{event}', None)
            if callable(method):
                await method(ctx, *args, **kwargs)
