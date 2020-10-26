"""config.py

Interface for ZeroBot's configuration and config files.
"""

from collections import ChainMap, UserDict
from pathlib import Path
from string import Template
from typing import Any, Iterable, Mapping, Optional, Union
from functools import reduce
import operator

import toml

import ZeroBot

_configvars = {
    'botversion': ZeroBot.__version__
}


class ConfigDict(UserDict):  # pylint: disable=too-many-ancestors
    """Wrapper around a `dict` useful for deserialized config files.

    See `Config` documentation for more details.
    """

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, str):
            value = Template(value).safe_substitute(_configvars)
        return value

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value = ConfigDict(value)
        self.data[key] = value

    def __repr__(self):
        return f'<{self.__class__.__name__} {super().__repr__()}>'

    @staticmethod
    def make_fallback(section: Mapping, fallback: Mapping) -> ChainMap:
        """Create a fallback-aware copy of a section.

        Attempting to retrieve a value for a key in `section` that doesn't
        exist will look for the same key in `fallback`. This modifies key
        lookup for this object as a whole; see *Notes* for details.

        Parameters
        ----------
        section : Mapping
            The section to set a fallback for.
        fallback : Mapping
            The section to use as a fallback.

        Returns
        -------
        ChainMap
            Returns `section`, but as a `ChainMap` with the `fallback` section.

        Notes
        -----
        A `ChainMap` extends *all* key lookups to each `dict` in the chain. As
        an example, consider the `get` method with a default value::

            foo = cfg.set_fallback(cfg['Foo'], cfg['Foo_Fallback'])
            foo.get('Bar', 'default setting')

        First, the key ``Bar`` will be looked up in ``Foo`` as normal. If not
        found, then the fallback section ``Foo_Fallback`` will be searched.
        Finally, if not found in the fallback section, the default value from
        `get` will be returned.
        """
        if not isinstance(section, ConfigDict):
            raise TypeError(
                f"section type expects 'ConfigDict', not '{type(section)}")
        if not isinstance(fallback, ConfigDict):
            raise TypeError(
                f"fallback type expects 'ConfigDict', not '{type(fallback)}")
        return ChainMap(section, fallback)

    # pylint: disable=arguments-differ
    def get(self, key: str, default: Any = None, *,
            template_vars: Mapping = None) -> Any:
        """Extended `dict.get` with optional template substitution.

        Behaves exactly like `dict.get`, but the retrieved value can undergo
        template substitution (`string.Template`) if `template_vars` is given.
        Note that substitution will *not* be done for the `default` fallback.

        Parameters
        ----------
        key : str
            They key to look up.
        default : Any, optional
            Value to return if `key` was not found. Will *not* undergo
            substitution.
        template_vars : Mapping
            A `dict`-like mapping of template identifiers and values as used
            with `string.Template.substitute`.

        Notes
        -----
        Internally, `string.Template.safe_substitute` is used to avoid
        exceptions and allow further substitution by other sources.
        """
        value = super().get(key, default)
        if isinstance(value, str) and template_vars:
            value = Template(value).safe_substitute(template_vars)
        return value


# pylint: disable=too-many-ancestors
class Config(ConfigDict):
    """A wrapper around a parsed TOML configuration file.

    Provides typical `dict`-like access with per-section fallbacks and default
    values.

    Parameters
    ----------
    path : str or Path object
        Path to a TOML configuration file.
    *args, **kwargs
        Any extra arguments are passed to the `ConfigDict` constructor.

    Attributes
    ----------
    path : Path
        The file associated with this config, i.e. where it will be loaded from
        and saved to.
    """

    def __init__(self, path: Union[str, Path], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = path
        self._last_state = {}

    def load(self):
        """Load (or reload) the associated TOML config file.

        Reloading will updating any existing keys and add any keys that were
        not present originally.

        Raises
        ------
        FileNotFoundError
            If the given config file path does not exist.
        TomlDecodeError
            If there were any errors while parsing the config file.

        Warnings
        --------
        Any fallbacks created via `set_fallback` and any references to config
        keys and sections will *not* be updated.
        """
        self.update(toml.load(self.path))
        self._last_state = self.data

    # TODO: testing
    def save(self, new_path: Union[str, Path] = None):
        """Write the current config to disk.

        Parameters
        ----------
        new_path : str or Path object, optional
            Where the new config file should be written. If omitted, will
            overwrite where it was originally loaded from, i.e. `self.path`.
        """
        toml.dump(self.data, new_path or self.path)
        self._last_state = self.data

    def reset(self, key: str = None):
        """Reset this config to its last loaded/saved state.

        Parameters
        ----------
        key : str, optional
            If specified, resets a single key instead of the whole config. The
            value is interpreted as a dot-separated identifier for a key under
            an arbitrarily deep hierarchy, e.g. ``Core.Database.Filename``.
        """
        if key is not None:
            nodes = key.split('.')
            last = reduce(operator.getitem, nodes, self._last_state)
            key = nodes.pop()
            current = reduce(operator.getitem, nodes, self.data)
            current[key] = last
        else:
            self.data = self._last_state
