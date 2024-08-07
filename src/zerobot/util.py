"""util.py

Various helpers and utilities. Used by ZeroBot internally as well as by feature
and protocol modules.
"""

from __future__ import annotations

import operator
import random
import sys
from functools import reduce
from io import StringIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# fmt: off
if sys.version_info >= (3, 11):
    import datetime
    parse_iso_format = datetime.datetime.fromisoformat
else:
    import dateutil
    parse_iso_format = dateutil.parser.isoparse
# fmt: on


def rand_chance(percentage: float) -> bool:
    """Returns `True` at the given percent chance, otherwise `False`.

    Simulates the chance of something succeeding or happening at random. For
    example, if ZeroBot should ``foo()`` with a 30% chance::
        if rand_chance(0.3):
            foo()
    """
    return random.random() < percentage


def gen_repr(obj: Any, attrs: Iterable, **kwargs) -> str:
    """Generates a __repr__ string.

    Used to create consistent `__repr__` methods throughout ZeroBot's codebase
    and modules.

    Parameters
    ----------
    obj : Any object
        A reference to an object whose class this repr is for.
    attrs : Any iterable
        An iterable containing attribute names that should be included in the
        `__repr__` string.
    kwargs
        Any extra keyword arguments are included as extra attributes.

    Returns
    -------
    str
        A string suitable to return from the class's `__repr__` method.
    """
    name = obj.__class__.__name__
    body = " ".join(f"{attr}={getattr(obj, attr)!r}" for attr in attrs)
    if kwargs:
        extras = " ".join(f"{attr}={val!r}" for attr, val in kwargs.items())
        body += " " + extras
    return f"<{name} {body}>"


def map_reduce(key_path: str | Sequence[str], mapping: Mapping[str, Any]) -> Any:
    """Reduce a mapping, returning a value from an arbitrarily deep hierarcy.

    The result of calling this function is the same as successively
    subscripting each key in the `key_path`, starting from `mapping`.

    Parameters
    ----------
    key_path : str or Sequence[str]
        A collection of sequential child keys into `mapping`. May be given as
        either a sequence of strings or a single string with dots (``.``)
        delimiting keys.
    mapping : Mapping[str, Any]
        The mapping to subscript.

    Example
    -------
    The following lines are equivalent:

        map_reduce('foo.bar.baz', things)
        # Is the same as:
        map_reduce(['foo', 'bar', 'baz'], things)
        # Is the same as:
        things['foo']['bar']['baz']
    """
    if isinstance(key_path, str):
        key_path = key_path.split(".")
    return reduce(operator.getitem, key_path, mapping)


def flatten(iterable):
    """Simple generator that flattens nested lists and tuples."""
    for elem in iterable:
        if isinstance(elem, list | tuple):
            yield from elem
        else:
            yield elem


def first(iterable, func=None, default=None):
    """Return the first value from ``iterable`` from the filter ``func``.

    If no elements in the iterable match, ``default`` is returned instead,
    which is ``None`` if left unspecified.
    """
    return next(filter(func, iterable), default)


def shellish_split(string: str) -> list[str]:
    """Perform shell-like word splitting on the given string.

    A bit more arbitrary and simplistic compared to ``shlex``, as it does *too*
    much for ZeroBot's command needs. Only a limited set of escape sequences
    have an effect, the rest are ignored and left as-is. Only double-quotes
    group arguments, as apostrophes are very common in chat.
    """
    words = []
    escaped = False
    quoted = False
    with StringIO(string) as buffer, StringIO() as word:
        while char := buffer.read(1):
            if char == '"':
                if escaped:
                    word.write(char)
                    escaped = False
                else:
                    quoted = not quoted
            elif char == "\\":
                if escaped:
                    word.write(char)
                escaped = not escaped
            elif char == " ":
                if escaped or quoted:
                    word.write(char)
                    escaped = False
                else:
                    words.append(word.getvalue())
                    word.seek(0)
                    word.truncate()
            else:
                if escaped:
                    # Only interested in certain escapes, so the backslash
                    # stays in the string.
                    word.write("\\")
                    escaped = False
                word.write(char)
        if quoted:
            raise ValueError("Unclosed quote")
        if escaped:
            # Include trailing backslash
            word.write("\\")
        words.append(word.getvalue())
    return words
