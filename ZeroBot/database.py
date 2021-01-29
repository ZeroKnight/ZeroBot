"""database.py

Interface to ZeroBot's SQLite 3 database backend.
"""

import asyncio
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import AnyStr, Dict, Iterator, Optional, Tuple, Union

import aiosqlite

from ZeroBot.module import Module, ProtocolModule

logger = logging.getLogger('ZeroBot.Database')

sqlite3.register_converter('BOOLEAN', lambda x: bool(int(x)))
sqlite3.converters['DATETIME'] = sqlite3.converters['TIMESTAMP']  # alias


# Why does Python not include this?
def regexp(pattern: AnyStr, string: AnyStr) -> bool:
    """SQLite REGEXP implementation."""
    if pattern is None or string is None:
        return False
    return re.search(pattern, string) is not None


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
        """Close the database connection."""
        logger.debug(f"Closing connection to database at '{self._dbpath}' "
                     f'opened by module {self._module!r}')
        super().close()


class DBUserInfo:
    """Base mixin for database users/aliases.

    Parameters
    ----------
    user_id : int
        The user's ID.
    name : str
        The name of the user/alias.
    created_at : datetime, optional
        Date and time that the user/alias was created. If omitted, the
        current date and time is used.
    creation_flags : TODO
        TBD
    creation_metadata : Dict, optional
        Arbitrary data associated with this user/alias.
    comment : str, optional
        An arbitrary note about this user/alias.

    Attributes
    ----------
    id : int
    """

    def __init__(self, user_id: int, name: str, *,
                 created_at: datetime = None, creation_flags: int = 0,
                 creation_metadata: Dict = None, comment: str = None):
        self._id = user_id
        self.name = name
        if created_at is None:
            created_at = datetime.utcnow()
        self.created_at = created_at
        self.creation_flags = creation_flags
        self.creation_metadata = creation_metadata or {}
        self.comment = comment

    def __repr__(self):
        attrs = ['id', 'name', 'created_at', 'creation_flags',
                 'creation_metadata', 'comment']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    def __str__(self):
        return self.name

    @property
    def id(self) -> int:
        """The user's ID."""
        return self._id


class DBUser(DBUserInfo):
    """A Database User.

    Represents a "user" from the perspective of ZeroBot's database rather
    than a `Context`. Feature modules may create such users for a variety
    of reasons, such as authorization, associating information, or
    whatever else a given module sees fit.
    """

    @classmethod
    def from_row(cls, row: Tuple) -> 'DBUser':
        """Construct a `DBUser` from a database row.

        Parameters
        ----------
        row : Tuple
            A row returned from the database.
        """
        metadata = json.loads(row[4]) if row[4] is not None else None
        return cls(
            user_id=row[0], name=row[1], created_at=row[2],
            creation_flags=row[3], creation_metadata=metadata, comment=row[5]
        )

    @classmethod
    async def from_id(cls, user_id: int,
                      conn: Connection) -> Optional['DBUser']:
        """Construct a specific `DBUser` from the database.

        Returns `None` if the given ID was not found.

        Parameters
        ----------
        user_id : int
            The ID of the user to fetch.
        conn : Connection
            The database connection to use.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = await cur.fetchone()
        if row is not None:
            return cls.from_row(row)
        return None

    async def get_aliases(self, conn: Connection) -> Iterator['DBUserAlias']:
        """Generator that fetches a list of this user's aliases, if any.

        Parameters
        ----------
        conn : ZeroBot.database.Connection
            The database connection to use to fetch the aliases.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT * FROM aliases WHERE user_id = ?', (self.id))
            while row := await cur.fetchone():
                yield DBUserAlias.from_row(row, self)


class DBUserAlias(DBUserInfo):
    """An alias for a Database User.

    Parameters
    ----------
    user : DBUser, optional
        The user associated with this alias.
    case_sensitive : bool, optional
        Whether or not this alias is case sensitive. Defaults to `False`.
    *args, **kwargs
        Extra arguments are passed to the `DBUserInfo` constructor.
    """

    def __init__(self, *args, user: DBUser = None,
                 case_sensitive: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_sensitive = case_sensitive
        if user is not None and user.id != self.id:
            raise ValueError(
                'The given user.id does not match user_id: '
                f'{user.id=} {self.id=}')
        self.user = user

    def __repr__(self):
        attrs = ['id', 'user', 'name', 'case_sensitive', 'created_at',
                 'creation_flags', 'creation_metadata', 'comment']
        repr_str = ' '.join(f'{a}={getattr(self, a)!r}' for a in attrs)
        return f'<{self.__class__.__name__} {repr_str}>'

    @classmethod
    def from_row(cls, row: Tuple, user: DBUser = None) -> 'DBUserAlias':
        """Construct a `DBUserAlias` from a database row.

        Parameters
        ----------
        row : Tuple
            A row returned from the database.
        """
        metadata = json.loads(row[5]) if row[5] is not None else None
        return cls(
            user_id=row[0], name=row[1], user=user, case_sensitive=row[2],
            created_at=row[3], creation_flags=row[4],
            creation_metadata=metadata, comment=row[6]
        )

    async def fetch_user(self, conn: Connection) -> DBUser:
        """Fetch the `DBUser` associated with this alias.

        Sets `self.user` to the fetched `DBUser` and returns it.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        """
        self.user = await DBUser.from_id(self.id, conn)
        return self.user


async def create_connection(database: Union[str, Path], module: Module,
                            loop: asyncio.AbstractEventLoop = None,
                            readonly: bool = False, **kwargs) -> Connection:
    """Establish a new connection to a ZeroBot database.

    Modules *should not* use this method or the `connect` method from either
    `sqlite3` or `aiosqlite` directly. Use `Core.database_connect`
    instead.

    Parameters
    ----------
    database : str or Path
        The path to the SQLite 3 database.
    module : Module
        The ZeroBot module that this connection is associated with, i.e. the
        module that "owns" this connection.
    loop : asyncio.AbstractEventLoop, optional
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
    if loop is None:
        loop = asyncio.get_event_loop()

    logger.debug(f"Creating {'read-only ' if readonly else ''}connection to "
                 f"database at '{database}' for module {module!r}")
    # NOTE: aiosqlite passes kwargs to sqlite3.connect
    conn = await aiosqlite.connect(
        f"{database.as_uri()}?mode={'ro' if readonly else 'rwc'}",
        loop=loop, uri=True, factory=Connection,
        detect_types=sqlite3.PARSE_DECLTYPES, **kwargs)
    conn.setName(module.identifier)
    await conn.create_function('REGEXP', 2, regexp)
    conn._connection._module = module  # pylint: disable=protected-access
    conn._connection._dbpath = database  # pylint: disable=protected-access
    return conn


async def create_backup(database: Connection, target: Union[str, Path],
                        loop: asyncio.AbstractEventLoop = None):
    """Create a full backup of a ZeroBot database.

    Modules *should not* use this method or the `backup` method from either
    `sqlite3` or `aiosqlite` directly. Use `Core.database_create_backup`
    instead.

    Parameters
    ----------
    database : ZeroBot.database.Connection
        A connection to a ZeroBot database.
    target : str or Path
        Where to write the backup.
    loop : asyncio.AbstractEventLoop, optional
        The `asyncio` event loop to use. This is typically `Core.eventloop`.
    """
    if loop is None:
        loop = asyncio.get_event_loop()
    logger.debug(f"Creating connection to new backup database at '{target}'")
    async with aiosqlite.connect(target, loop=loop) as backup_conn:
        logger.info(f"Creating database backup at '{target}'")
        await database.backup(backup_conn)
