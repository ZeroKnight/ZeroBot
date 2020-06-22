"""config.py

Interface for ZeroBot's configuration and config files.
"""

from collections import ChainMap, UserDict
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

import toml


# pylint: disable=too-many-ancestors
class Config(UserDict):
    """A wrapper around a parsed TOML configuration file.

    Provides typical `dict`-like access with per-section fallbacks and default
    values.

    Parameters
    ----------
    path : str or Path object
        Path to a TOML configuration file.
    initial_data : Mapping or Iterable, optional
        Initial data to populate the config with. Values may be overwritten by
        the loaded file.

    Attributes
    ----------
    path : Path
        The file associated with this config, i.e. where it will be loaded from
        and saved to.
    """

    def __init__(self, path: Union[str, Path],
                 initial_data: Optional[Union[Mapping, Iterable]] = None):
        super().__init__(initial_data)
        self.path = path

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

    @staticmethod
    def make_fallback(section: dict, fallback: dict) -> ChainMap:
        """Create a fallback-aware copy of a section.

        Attempting to retrieve a value for a key in `section` that doesn't
        exist will look for the same key in `fallback`. This modifies key
        lookup for this object as a whole; see *Notes* for details.

        Parameters
        ----------
        section : dict
            The section to set a fallback for.
        fallback : dict
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
        if not isinstance(section, dict):
            raise TypeError(
                f"section type expects 'dict', not '{type(section)}")
        if not isinstance(fallback, dict):
            raise TypeError(
                f"fallback type expects 'dict', not '{type(fallback)}")
        return ChainMap(section, fallback)
