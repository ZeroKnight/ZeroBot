"""common/util.py

Assorted and miscellaneous utilities for writing ZeroBot modules.
"""

from __future__ import annotations

import random


def rand_chance(percentage: float) -> bool:
    """Returns `True` at the given percent chance, otherwise `False`.

    Simulates the chance of something succeeding or happening at random. For
    example, if ZeroBot should ``foo()`` with a 30% chance::
        if rand_chance(0.3):
            foo()
    """
    return random.random() < percentage
