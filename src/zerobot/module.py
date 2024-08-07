"""module.py

Provides abstractions for ZeroBot modules and their associated files.
"""

from __future__ import annotations

import importlib
import sys
from importlib.abc import MetaPathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING

from zerobot.exceptions import ModuleLoadError
from zerobot.util import gen_repr

if TYPE_CHECKING:
    from types import ModuleType


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
    return importlib.util.find_spec(f"zerobot.{mtype}.{module_id}") is not None


class ZeroBotModuleFinder(MetaPathFinder):
    """Meta path finder for ZeroBot modules.

    Will search for ZeroBot modules in the locations specified in ZeroBot's
    configuration as well as the usual places in `sys.path`.

    Parameters
    ----------
    search_dirs : list of paths
        The list of paths to search for ZeroBot modules.
    """

    def __init__(self, search_dirs: list):
        self.search_dirs = search_dirs

    def find_spec(self, fullname, path, target=None):
        spec = None
        parts = fullname.split(".")
        if parts[0] != "zerobot" or parts[1] not in {"feature", "protocol"} or len(parts) < 3:
            return None
        for loc in self.search_dirs:
            filename = Path(loc, *parts[1:]).with_suffix(".py")
            if filename.exists():
                spec = spec_from_file_location(fullname, str(filename))
                if spec is not None:
                    break
        return spec


def _load_zerobot_module(import_str: str) -> tuple[ModuleType, bool]:
    module = importlib.import_module(import_str)
    is_package = False
    if hasattr(module, "__path__"):
        # This Module is a package, so load the entry point. E.g. if given
        # 'zerobot.feature.foo', then load 'zerobot.feature.foo.feature'
        module_type = import_str.split(".", 2)[1]
        module = importlib.import_module(f"{import_str}.{module_type}")
        is_package = True
    return module, is_package


class Module:
    """Base class for ZeroBot modules.

    Not intended to be directly instantiated; use a derived class instead.

    Parameters
    ----------
    import_str : str
        The name of the module to as given to an ``import`` statement.

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
        identifier for ``zerobot.feature.chat`` would be ``'chat'``.
    handle : types.ModuleType
        A reference to the loaded Python module.

    Raises
    ------
    ModuleNotFoundError
        If the specified module could not be found.
    """

    def __init__(self, import_str: str):
        try:
            self.handle, self._is_package = _load_zerobot_module(import_str)
        except ModuleNotFoundError:
            # Look for newly added modules and try again
            importlib.invalidate_caches()
            self.handle, self._is_package = _load_zerobot_module(import_str)
        try:
            self.name = self.handle.MODULE_NAME
            self.description = self.handle.MODULE_DESC
            self.author = self.handle.MODULE_AUTHOR
            self.version = self.handle.MODULE_VERSION
            self.license = self.handle.MODULE_LICENSE
        except AttributeError as ex:
            name = import_str.rsplit(".", 1)[-1]
            var = ex.args[0].rsplit(" ", 1)[-1]
            raise ModuleLoadError(
                f"Missing module info variable {var}",
                mod_id=name,
                name=import_str,
                path=self.handle.__file__,
            ) from None
        self._identifier = self.handle.__name__.split(".", 3)[2]

    def __repr__(self):
        attrs = ["name", "version", "handle"]
        return gen_repr(self, attrs)

    def __str__(self):
        return f"{self.name} v{self.version}"

    @property
    def identifier(self) -> str:
        """Get the module identifier, i.e. the name used to load it."""
        return self._identifier

    @property
    def fq_name(self) -> str:
        """Get the fully qualified name of the associated Python module."""
        return self.handle.__name__


class FeatureModule(Module):
    """A Zerobot Feature module.

    As its name would suggest, a feature module gives ZeroBot the ability
    to do something. Without any feature modules, ZeroBot does nothing
    aside from idling on any open connections. A feature module can add any
    arbitrary functionality to ZeroBot, from responding to chat to providing
    various utility services.
    """

    def reload(self) -> ModuleType:
        """Reload the associated Python module.

        Returns
        -------
        ModuleType
            If the reload was successful, returns the new module handle.
            Otherwise, an exception is raised depending on what caused the
            reload to fail.
        """
        current_handle = self.handle
        if self._is_package:

            def _filter(name):
                return not name.endswith("feature") and name.startswith(f"{self.handle.__package__}.")

            for module in [mod for name, mod in sys.modules.items() if _filter(name)]:
                importlib.reload(module)
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

    def reload(self):
        """Not yet implemented for protocol modules!"""
        raise NotImplementedError("Reloading protocol modules is not yet implemented.")


class CoreModule(Module):
    """Dummy module representing ZeroBot's Core."""

    def __init__(self, core, version: str):
        self.handle = core
        self.name = "Core"
        self.description = "ZeroBot Core"
        self.author = "ZeroKnight"
        self.version = version
        self.license = "MIT"

    @property
    def identifier(self) -> str:
        return "core"
