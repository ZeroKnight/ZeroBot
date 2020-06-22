"""util.py

Various utilities for ZeroBot
"""

from typing import Any, Iterable


def gen_repr(obj: Any, attrs: Iterable) -> str:
    """Generates a __repr__ string.

    Used to create consistent `__repr__` methods throughout ZeroBot's codebase
    and modules.

    Parameters
    ----------
    obj : Any object
        A reference to an object whose class this repr is for.
    attrs: Any iterable
        An iterable containing attribute names that should be included in the
        `__repr__` string.

    Returns
    -------
    str
        A string suitable to return from the class's `__repr__` method.
    """
    name = obj.__class__.__name__
    body = ' '.join(f'{attr}={getattr(obj, attr)!r}' for attr in attrs)
    return f'<{name} {body}>'
