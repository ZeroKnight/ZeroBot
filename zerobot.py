#!/usr/bin/env python3

"""zerobot.py

A modular, mutli-protocol bot that exists primarily for amusement and arbitrary
utility, but otherwise serves no major or specific purpose. Pet-project and
personal bot of Alex "ZeroKnight" George.
"""

import asyncio
import logging
import sys

from ZeroBot import Core


def main():
    bot = Core()
    bot.run()


if __name__ == '__main__':
    sys.exit(main())
