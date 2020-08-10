"""database.py

Interface to ZeroBot's SQLite 3 database backend.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Union

import aiosqlite

from ZeroBot.module import Module, ProtocolModule

logger = logging.getLogger('ZeroBot.Database')


class Connection(sqlite3.Connection):
    """Extension of `sqlite3.Connection` tied to ZeroBot.

    Attributes
    ----------
    module : Module
    dbpath : Path
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._module = None
        self._dbpath = None

    @property
    def module(self) -> Module:
        """The ZeroBot module associated with this connection."""
        return self._module

    @property
    def dbpath(self) -> Path:
        """The path to the connected database."""
        return self._dbpath

    def close(self):
        logger.debug(f"Closing connection to database at '{self._dbpath}' "
                     f'opened by module {self._module!r}')
        super().close()


async def create_connection(database: Union[str, Path], module: Module,
                            loop: asyncio.AbstractEventLoop,
                            readonly: bool = False, **kwargs) -> Connection:
    """Establish a new connection to a ZeroBot database.

    Modules *should not* use this method or the `connect` method from either
    `sqlite3` or `aiosqlite` directly. Use `Core.new_database_connection`
    instead.

    Parameters
    ----------
    database : str or Path
        The path to the SQLite 3 database.
    module : Module
        The ZeroBot module that this connection is associated with, i.e. the
        module that "owns" this connection.
    loop : asyncio.AbstractEventLoop
        The `asyncio` event loop to use. This is typically `Core.eventloop`.
    readonly : bool, optional
        Whether the connection is read-only. Defaults to `False`.
    kwargs
        Remaining keyword arguments are passed to `aiosqlite.connect`.

    Returns
    -------
    Connection
        A connection object for the requested database.
    """
    if not isinstance(database, Path):
        database = Path(database)
    database = database.absolute()

    logger.debug(f"Creating {'read-only ' if readonly else ''}connection to "
                 f"database at '{database}' for module {module!r}")
    conn = await aiosqlite.connect(
        f"{database.as_uri()}?mode={'ro' if readonly else 'rwc'}",
        loop=loop, uri=True, factory=Connection, **kwargs)
    conn._connection._module = module  # pylint: disable=protected-access
    conn._connection._dbpath = database  # pylint: disable=protected-access
    return conn
