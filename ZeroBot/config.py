"""config.py

Interface for ZeroBot's configuration and config files.
"""

from collections import ChainMap, UserDict
from copy import deepcopy
from pathlib import Path
from string import Template
from typing import Any, Iterable, Mapping, Optional, Union

import toml

import ZeroBot
from ZeroBot.common.exceptions import (ConfigDecodeError, ConfigEncodeError,
                                       ConfigReadError, ConfigWriteError)
from ZeroBot.util import map_reduce

_configvars = {
    'botversion': ZeroBot.__version__
}


class ConfigDict(UserDict):  # pylint: disable=too-many-ancestors
    """Wrapper around a `dict` useful for deserialized config files.

    Do not use this class directly, use `Config` instead.
    """

    def __getitem__(self, key):
        key, *subkeys = key.split('.', 1)
        value = super().__getitem__(key)
        if subkeys:
            value = value.__getitem__(subkeys[0])
        elif isinstance(value, str):
            value = Template(value).safe_substitute(_configvars)
        elif isinstance(value, list):
            for elem in value:
                elem = Template(elem).safe_substitute(_configvars)
        return value

    def __setitem__(self, key, value):
        tail, *subkeys = key.rsplit('.', 1)[::-1]
        if subkeys:
            target = self.__getitem__(subkeys[0])
        else:
            target = self.data
        if isinstance(value, dict):
            value = ConfigDict(value)
        target[tail] = value

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
        """Extends `dict.get` with substitution and dotted-subkey access.

        The retrieved value can undergo template substitution, i.e.
        (`string.Template`) if `template_vars` is given. Note that substitution
        will *not* be done for the `default` fallback. See `Config` for details
        on dotted-subkey access.

        Parameters
        ----------
        key : str
            They key to look up; may be a dotted-subkey.
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
        if template_vars:
            if isinstance(value, str):
                value = Template(value).safe_substitute(template_vars)
            elif isinstance(value, list):
                for elem in value:
                    elem = Template(elem).safe_substitute(_configvars)
        return value


# pylint: disable=too-many-ancestors
class Config(ConfigDict):
    """A wrapper around a parsed TOML configuration file.

    Provides typical `dict`-like access with per-section fallbacks and default
    values. Since these config files very often contain nested sections,
    methods that take a dictionary key as an argument have been expanded to
    allow dot-delimited keys that specify sequential access into nested
    sections. Such keys are of the form ``'foo.bar.baz'`` and would be
    equivalent to performing successive lookups of each key on a starting
    dictionary. For example::

        self.get('foo.bar.baz')
        # Is the same as:
        self.get('foo').get('bar').get('baz')

        my_config['foo.bar.baz']
        # Is the same as:
        my_config['foo']['bar']['baz']

    In addition, key values are automatically subject to template expansion for
    some global variables, as well as on demand with the inclusion of
    a `template_vars` parameter. This feature leverages `string.Template`, and
    thus works identically.

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
        self._last_state = None

    def reset(self, key: str = None):
        """Reset this config or a single key to its last loaded/saved state.

        See `Config` for details on dotted-subkey access.

        Parameters
        ----------
        key : str, optional
            If specified, resets a single key instead of the whole config. The
            key may be a dotted-subkey.
        """
        if key is not None:
            self[key] = self._last_state[key]
        else:
            self.data = self._last_state

    def unset(self, key: str = None):
        """Unset a single key, or the entire config.

        Effectively reverts keys to their default values.

        Parameters
        ----------
        key : str , optional
            If specified, unsets a single key instead of the whole config. The
            key may be a dotted-subkey.
        """
        if key is not None:
            del self[key]
        else:
            self.data = ConfigDict()

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
        try:
            self.update(toml.load(self.path))
        except toml.TomlDecodeError as ex:
            raise ConfigDecodeError(
                f"Failed to parse config file at '{self.path}'",
                config_name=self.path.stem) from ex
        except OSError as ex:
            raise ConfigReadErrror(
                f"Could not read config file at '{self.path}'",
                config_name=self.path.stem) from ex
        self._last_state = ConfigDict(deepcopy(self.data))

    # TODO: testing
    def save(self, new_path: Union[str, Path] = None):
        """Write the current config to disk.

        Parameters
        ----------
        new_path : str or Path object, optional
            Where the new config file should be written. If omitted, will
            overwrite where it was originally loaded from, i.e. `self.path`.
        """
        path = new_path or self.path
        try:
            with open(path, 'w') as file:
                toml.dump(self.data, file)
        except ValueError as ex:
            cls_name = self.__class__.__name__
            raise ConfigEncodeError(
                f'Failed to encode {cls_name} object {self}',
                config_name=self.path.stem) from ex
        except OSError as ex:
            raise ConfigWriteError(
                f"Could not write config file to '{path}'",
                config_name=self.path.stem) from ex
        self._last_state = ConfigDict(deepcopy(self.data))
