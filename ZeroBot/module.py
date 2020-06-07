"""module.py

Provides abstractions for ZeroBot modules and their associated files.
"""

import importlib
from typing import Optional

from ZeroBot.protocol.context import Context


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
    handle : types.ModuleType
        A reference to the loaded Python module.

    Raises
    ------
    ModuleNotFoundError
        If the specified module could not be found.
    """

    def __init__(self, import_str: str):
        self._import_name = import_str
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
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        return f'{self.name} v{self.version}'

    def fq_name(self) -> str:
        """Get the fully qualified name of the associated Python module."""
        return self._import_name


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
