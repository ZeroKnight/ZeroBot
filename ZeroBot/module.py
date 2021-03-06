"""module.py

Provides abstractions for ZeroBot modules and their associated files.
"""

import importlib
from importlib.abc import MetaPathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import List

from ZeroBot.util import gen_repr


def module_available(module_id: str, mtype: str) -> bool:
    """Checks for the existence of a given module.

    Parameters
    ----------
    module_id : str
        The identifier of the module to check for.
    mtype : str
        The type of module to look for; either `'protocol'` or `'feature'`.

    Returns
    -------
    bool
        Whether or not the given module is availble to load.
    """
    return importlib.util.find_spec(f'ZeroBot.{mtype}.{module_id}') is not None


class ZeroBotModuleFinder(MetaPathFinder):
    """Meta path finder for ZeroBot modules.

    Will search for ZeroBot modules in the locations specified in ZeroBot's
    configuration as well as the usual places in `sys.path`.

    Parameters
    ----------
    search_dirs : list of paths
        The list of paths to search for ZeroBot modules.
    """

    def __init__(self, search_dirs: List):
        self.search_dirs = search_dirs

    def find_spec(self, fullname, path, target=None):
        spec = None
        parts = fullname.split('.')
        if (parts[0] != 'ZeroBot'
                or parts[1] not in ('feature', 'protocol')
                or len(parts) < 3):
            return None
        for loc in self.search_dirs:
            filename = Path(loc, *parts[1:]).with_suffix('.py')
            if filename.exists():
                spec = spec_from_file_location(fullname, str(filename))
                if spec is not None:
                    break
        return spec


class Module:
    """Base class for ZeroBot modules.

    Parameters
    ----------
    import_str : str
        The name of the module to as given to `import`.

    Attributes
    ----------
    name : str
        A friendly name for the module.
    description : str
        A description of the module.
    author : str
        The author of the module.
    version : str
        The version string of the module.
    license : str
        The name of the license that the module is written under.
    identifier: str
        The identifier used to initially load the module. For example, the
        identifier for ``ZeroBot.feature.chat`` would be ``'chat'``.
    handle : types.ModuleType
        A reference to the loaded Python module.

    Raises
    ------
    ModuleNotFoundError
        If the specified module could not be found.
    """

    def __init__(self, import_str: str):
        try:
            self.handle = importlib.import_module(import_str)
        except ModuleNotFoundError:
            # Look for newly added modules and try again
            importlib.invalidate_caches()
            self.handle = importlib.import_module(import_str)
        self.name = self.handle.MODULE_NAME
        self.description = self.handle.MODULE_DESC
        self.author = self.handle.MODULE_AUTHOR
        self.version = self.handle.MODULE_VERSION
        self.license = self.handle.MODULE_LICENSE

    def __repr__(self):
        attrs = ['name', 'version', 'handle']
        return gen_repr(self, attrs)

    def __str__(self):
        return f'{self.name} v{self.version}'

    @staticmethod
    def get_type() -> str:
        """Return a string representing the module type."""
        return 'feature'

    @property
    def identifier(self) -> str:
        """Get the module identifier, i.e. the name used to load it."""
        return self.handle.__name__.split('.')[-1]

    @property
    def fq_name(self) -> str:
        """Get the fully qualified name of the associated Python module."""
        return self.handle.__name__

    def reload(self) -> 'Module':
        """Reload the associated Python module.

        Returns
        -------
        Module or None
            If the reload was successful, returns the new module handle.
            Otherwise, it raises an exception.
        """
        current_handle = self.handle
        self.handle = importlib.reload(current_handle)
        return self.handle


class ProtocolModule(Module):
    """A ZeroBot Protocol module.

    Encapsulates a module that implements a protocol that ZeroBot may
    connect over. An arbitrary number of `Contexts` may be associated with
    a `ProtocolModule` object.

    Attributes
    ----------
    contexts : List of `Context` objects
        Contains the `Context` objects associated with this protocol.
    """

    def __init__(self, import_str: str):
        super().__init__(import_str)

        self.contexts = []

    @staticmethod
    def get_type() -> str:
        """Return a string representing the module type."""
        return 'protocol'

    @property
    def identifier(self) -> str:
        return self.handle.__name__.split('.')[-2]

    def reload(self):
        """Not yet implemented for protocol modules!"""
        raise NotImplementedError(
            'Reloading protocol modules is not yet implemented.')


class CoreModule(Module):
    """Dummy module representing ZeroBot's Core."""

    # pylint: disable=super-init-not-called
    def __init__(self, core, version: str):
        self.handle = core
        self.name = 'Core'
        self.description = 'ZeroBot Core'
        self.author = 'ZeroKnight'
        self.version = version
        self.license = 'MIT'

    @property
    def identifier(self) -> str:
        return 'core'
