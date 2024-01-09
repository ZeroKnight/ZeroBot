#!/usr/bin/env python3

"""A modular, multi-protocol bot for amusement and utility.

Personal bot of Alex "ZeroKnight" George.
Repository: https://github.com/ZeroKnight/ZeroBot
"""

from __future__ import annotations

import code
import sys

from ZeroBot import Core
from ZeroBot.database import create_interactive_connection


def main() -> int:
    bot = Core()
    return bot.run()


def edit_db() -> None:
    try:
        db = sys.argv[1]
    except IndexError:
        print("Expected path to database")
        sys.exit(1)
    with create_interactive_connection(db) as conn:
        print('sqlite connection object is ready and named "conn"')
        code.interact(local=locals())


if __name__ == "__main__":
    sys.exit(main())
