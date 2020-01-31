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

    # TODO: Decide on an interface that protocol modules must implement in order
    # for the core to Initialize them, provide a config, and request any number
    # of instances so that the core may orchestrate them into an event loop

    # TODO: How do we go about dynamically adding/removing "instances" from the
    # event loop? Ideally the interface would be something like:
    # add_instance(...) and remove_instance(...), but how do we do this on the
    # asyncio level?
    # IIUC, the former can just be done with asyncio.ensure_future, and the
    # latter will probably require stashing the Future of each instance and
    # calling cancel() or something

    def __init__(self):
        self.eventloop = asyncio.get_event_loop()
        # TBD: name tentative
        # put ZeroBot-API wrapped protocol objects here, e.g. pydle client
        # then put them all into a Future via asyncio.gather and run in
        # self.eventloop, similar to pydle's ClientPool
        self._instances = []
        self._protocols = {} # maps protocol names to their module

        # do config loading stuff

        # IDEA: As part of module registration, the core could send the relevant
        # config section data structure to the module, removing the burden from
        # them to load it themselves. Since they will be passed a reference to
        # the data structure, both the module and the core would see the most
        # up to date changes.

        loaded = self._load_protocols()
        if loaded:
            # log that `loaded` number of protocols were loaded, then list them
            print(f'loaded {loaded} protocols')
            pass
        else:
            # log an error that no protocols were able to be loaded and quit
            # TODO: figure out how to properly "quit"
            raise RuntimeError('Could not load any protocol modules.')

        # Register protocols
        # TBD: Should this be done in _load_protocols? Or its own method?
        for name, proto in self._protocols.items():
            print(f'init {proto}')
            proto.module_register()
            self._instances.append(self._protocols[name].module_get_instance(self.eventloop))
            # do other stuff, error checking, etc

    def run(self):
        # TODO: stub
        for instance in self._instances:
            asyncio.ensure_future(instance[1], loop=self.eventloop)
        return self.eventloop

    def _load_protocols(self) -> int:
        """Get list of requested protocols from configuration and load them.

        Returns the number of protocols that were successfully loaded.

        TEMP: Currently just a stub until config is implemented
        """
        num_loaded = 0
        stub_list = ['irc', 'discord'] # normally we'd pull from the config here
        for proto in stub_list:
            try:
                module = importlib.import_module(f'ZeroBot.protocol.{proto}.protocol')
            except ModuleNotFoundError:
                # log failure to find protocol module or one of its dependencies
                # self.log_error(...)
                raise # TEMP
            else:
                self._protocols[proto] = module
                num_loaded += 1
        return num_loaded


