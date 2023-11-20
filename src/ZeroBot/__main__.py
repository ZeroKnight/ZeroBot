#!/usr/bin/env python3

"""A modular, multi-protocol bot for amusement and utility.

Personal bot of Alex "ZeroKnight" George.
Repository: https://github.com/ZeroKnight/ZeroBot
"""

import sys

from ZeroBot import Core


def main() -> int:
    bot = Core()
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
