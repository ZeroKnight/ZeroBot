"""util.py

Various internal utilities for ZeroBot. If you're working on a feature module,
you *probably* want `ZeroBot.common` instead.
"""

from typing import Any, Iterable


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
    body = ' '.join(f'{attr}={getattr(obj, attr)!r}' for attr in attrs)
    if kwargs:
        extras = ' '.join(f'{attr}={val!r}' for attr, val in kwargs.items())
        body += ' ' + extras
    return f'<{name} {body}>'
