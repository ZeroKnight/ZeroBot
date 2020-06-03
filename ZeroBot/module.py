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
    name : str
        The name of the module to as given to `import`.
    title : str, optional
        A friendly name for the module. If `None`, the name specified by
        ``MODULE_NAME`` defined in the module `name` will be used; if it isn't
        defined, then `title` will be set equal to the module name.

    Attributes
    ----------
    name
    title
    handle : types.ModuleType
        A reference to the loaded Python module.

    Raises
    ------
    ModuleNotFoundError
        If the given module name could not be found.
    """

    def __init__(self, name: str, title: Optional[str] = None):
        self._name = name
        self.handle = importlib.import_module(self._name)
        if title:
            self._title = title
        else:
            self._title = getattr(self.handle, 'MODULE_NAME', self._name)

    def __repr__(self):
        attrs = ['name', 'title', 'handle']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        return self.name

    @property
    def name(self) -> str:
        """Get the name of the associated Python module."""
        return self._name

    @property
    def title(self) -> str:
        """Get the title (friendly name) of this module."""
        return self._title


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

    def __init__(self, name: str, title: Optional[str] = None):
        super().__init__(name, title)

        self.contexts = []
