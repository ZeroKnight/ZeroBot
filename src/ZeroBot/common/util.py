"""common/util.py

Assorted and miscellaneous utilities for writing ZeroBot modules.
"""

from __future__ import annotations

import random
import sys

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
