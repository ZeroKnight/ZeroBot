"""database.py

Interface to ZeroBot's SQLite 3 database backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, AnyStr

import aiosqlite

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ZeroBot.module import Module

logger = logging.getLogger("ZeroBot.Database")

sqlite3.register_converter("BOOLEAN", lambda x: bool(int(x)))
sqlite3.converters["DATETIME"] = sqlite3.converters["TIMESTAMP"]  # alias

# HACK: "Extend" the default datetime adapter to trim microseconds
_orig_adapter = sqlite3.adapters[(datetime, sqlite3.PrepareProtocol)]
sqlite3.adapters[(datetime, sqlite3.PrepareProtocol)] = lambda val: _orig_adapter(val).partition(".")[0]


# Why does Python not include this?
def regexp(pattern: AnyStr, string: AnyStr) -> bool:
    """SQLite REGEXP implementation."""
    if pattern is None or string is None:
        return False
    try:
        return re.search(pattern, string) is not None
    except re.error:
        return False


def collate_casefold(a: str, b: str) -> bool:
    """SQLite casefold collation."""
    a, b = a.casefold(), b.casefold()
    if a == b:
        return 0
    return 1 if a < b else -1


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
        logger.debug(f"Closing connection to database at '{self._dbpath}' opened by module {self._module!r}")
        super().close()


class DBModel:
    """Base class for classes modelled after database entities.

    Parameters
    ----------
    connection : Connection
        A connection to the database containing this entity.

    Attributes
    ----------
    table_name : str, optional
        Class attribute that sets the name of the database table that this
        model is based on. If not specified, will default to the lowercased
        name of the class.
    """

    table_name = None

    def __new__(cls, *args, **kwargs):
        if cls.table_name is None:
            cls.table_name = cls.__name__.lower()
        return super().__new__(cls)

    def __init__(self, connection: Connection):
        self._connection = connection

    @property
    def connection(self) -> Connection:
        """The connection to the database for this model."""
        return self._connection


class DBUserInfo(DBModel):
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
    creation_metadata : dict, optional
        Arbitrary data associated with this user/alias.
    comment : str, optional
        An arbitrary note about this user/alias.

    Attributes
    ----------
    id : int
    """

    table_name = None

    def __init__(
        self,
        conn: Connection,
        user_id: int,
        name: str,
        *,
        created_at: datetime | None = None,
        creation_flags: int = 0,
        creation_metadata: dict | None = None,
        comment: str | None = None,
        **kwargs,
    ):
        super().__init__(conn)
        self._id = user_id
        self.name = name
        if created_at is None:
            created_at = datetime.now(tz=timezone.utc)
        self.created_at = created_at
        self.creation_flags = creation_flags
        self.creation_metadata = creation_metadata or {}
        self.comment = comment

    def __repr__(self):
        attrs = [
            "id",
            "name",
            "created_at",
            "creation_flags",
            "creation_metadata",
            "comment",
        ]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

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

    table_name = "users"

    @classmethod
    def from_row(cls, conn: Connection, row: sqlite3.Row) -> DBUser:
        """Construct a `DBUser` from a database row.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        """
        attrs = {name: row[name] for name in ("user_id", "name", "created_at", "creation_flags", "comment")}
        metadata = json.loads(row["creation_metadata"]) if row["creation_metadata"] is not None else None
        return cls(conn, creation_metadata=metadata, **attrs)

    @classmethod
    async def from_id(cls, conn: Connection, user_id: int) -> DBUser | None:
        """Construct a specific `DBUser` from the database.

        Returns `None` if the given ID was not found.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        user_id : int
            The ID of the user to fetch.
        """
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT * FROM {cls.table_name} WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
        if row is not None:
            return cls.from_row(conn, row)
        return None

    async def get_aliases(self) -> Iterator[DBUserAlias]:
        """Generator that fetches a list of this user's aliases, if any."""
        async with self._connection.cursor() as cur:
            await cur.execute(f"SELECT * FROM {DBUserAlias.table_name} WHERE user_id = ?", (self.id,))
            while row := await cur.fetchone():
                yield DBUserAlias.from_row(self._connection, row, self)


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

    table_name = "aliases"

    def __init__(self, *args, user: DBUser = None, case_sensitive: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_sensitive = case_sensitive
        if user is not None and user.id != self.id:
            raise ValueError(f"The given user.id does not match user_id: {user.id=} {self.id=}")
        self.user = user

    def __repr__(self):
        attrs = [
            "id",
            "user",
            "name",
            "case_sensitive",
            "created_at",
            "creation_flags",
            "creation_metadata",
            "comment",
        ]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    @classmethod
    def from_row(cls, conn: Connection, row: sqlite3.Row, user: DBUser = None) -> DBUserAlias:
        """Construct a `DBUserAlias` from a database row.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        user : DBUser, optional
            The `DBUser` associated with this alias.
        """
        attrs = {
            name: row[name]
            for name in (
                "user_id",
                "name",
                "created_at",
                "creation_flags",
                "comment",
                "case_sensitive",
            )
        }
        metadata = json.loads(row["creation_metadata"]) if row["creation_metadata"] is not None else None
        return cls(connection=conn, user=user, creation_metadata=metadata, **attrs)

    async def fetch_user(self) -> DBUser | None:
        """Fetch the `DBUser` associated with this alias.

        Sets `self.user` to the fetched `DBUser` and returns it.
        """
        self.user = await DBUser.from_id(self._connection, self.id)
        return self.user


class Participant(DBModel):
    """A distinct, named entity used by the database.

    Participants may or may not be linked to a `DBUser`. If they aren't, they
    can be considered a "soft" user of sorts.

    Parameters
    ----------
    participant_id : int
        The participant's ID.
    name : str
        The name of the participant.
    user_id : int, optional
        The participant's user ID, if it has one.
    user : DBUser, optional
        The user linked to this participant.

    Attributes
    ----------
    id
    """

    table_name = "participants"

    def __init__(
        self,
        conn: Connection,
        participant_id: int,
        name: str,
        *,
        user_id: int | None = None,
        user: DBUser = None,
    ):
        super().__init__(conn)
        self.id = participant_id
        self.name = name
        self.user_id = user_id
        if user is not None and user.id != self.user_id:
            raise ValueError(f"The given user.id does not match user_id: {user.id=} {self.user_id=}")
        self.user = user

    def __repr__(self):
        attrs = ["id", "name", "user"]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.id == other.id

    @classmethod
    def from_row(cls, conn: Connection, row: sqlite3.Row, user: DBUser = None) -> Participant:
        """Construct a `Participant` from a database row.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        user : DBUser, optional
            The `DBUser` associated with this alias.
        """
        attrs = {name: row[name] for name in ("participant_id", "name", "user_id")}
        return cls(conn, user=user, **attrs)

    @classmethod
    async def from_id(cls, conn: Connection, participant_id: int) -> Participant | None:
        """Construct a `Participant` by ID from the database.

        Returns `None` if there was no `Participant` with the given ID.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        participant_id : int
            The ID of the participant to fetch.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT * FROM {cls.table_name} WHERE participant_id = ?",
                (participant_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        user = await DBUser.from_id(conn, row["user_id"])
        return cls.from_row(conn, row, user)

    @classmethod
    async def from_name(cls, conn: Connection, name: str) -> Participant | None:
        """Construct a `Participant` by name from the database.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        name : str
            The name of the participant to fetch.
        """
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT * FROM {cls.table_name} WHERE name = ?", (name,))
            row = await cur.fetchone()
        if row is None:
            return None
        user = await DBUser.from_id(conn, row["user_id"])
        return cls.from_row(conn, row, user)

    @classmethod
    async def from_user(cls, conn: Connection, user: DBUser | int) -> Participant | None:
        """Construct a `Participant` linked to the given user.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        user : DBUser or int
            The linked user to search for. May be a `DBUser` object or an `int`
            referring to a user ID.
        """
        try:
            user_id = user.id
        except AttributeError:
            user_id = int(user)
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT * FROM {cls.table_name} WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        if not isinstance(user, DBUser):
            user = await DBUser.from_id(conn, row["user_id"])
        return cls.from_row(conn, row, user)

    async def fetch_user(self) -> DBUser:
        """Fetch the database user linked to this participant.

        Sets `self.user` to the fetched `DBUser` and returns it.
        """
        if self.user_id is None:
            raise ValueError("Participant has no linked user.")
        self.user = await DBUser.from_id(self._connection, self.user_id)
        return self.user

    async def save(self):
        """Save this `Participant` to the database."""
        async with self._connection.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO {self.table_name} VALUES (?, ?, ?)
                ON CONFLICT (participant_id) DO UPDATE SET
                    name = excluded.name,
                    user_id = excluded.user_id
            """,
                (self.id, self.name, self.user_id),
            )
            self.id = cur.lastrowid
            await self._connection.commit()


async def get_participant(conn: Connection, name: str, *, auto_create: bool = True) -> Participant | None:
    """Get a `Participant` from the database.

    This is a convenient and generalized function for Zerobot modules that
    enables the most common actions related to database participants: lookup of
    existing participants and the creation of new ones. The lookup name may
    match any alias associated with the participant.

    **NOTE**: Non-existing participants are auto-created by default.

    Parameters
    ----------
    conn : Connection
        The database connection to use.
    name : str
        The name to look up; usually from a message source or command argument.
    auto_create : bool, optional
        Automatically create a new participant with `name` if not found.
        ``True`` by default.

    Returns
    -------
    Participant or None
        A `Participant` object matching `name` if found in the database.
        Otherwise, a new participant will be created and returned if
        `auto_create` is true, or ``None`` if it is false.

    Notes
    -----
    ZeroBot's Core defines triggers that, along with foreign key constraints,
    prevents Users and Participants from becoming inconsistent. As long as
    these measures are not circumvented, you shouldn't need to worry about any
    user/participant discrepancies, getting a `Participant` without its
    associated `DBUser`, having a user with no associated participant, etc.
    """
    if not (name := name.strip()):
        raise ValueError("Name is empty or whitespace")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT participant_id, name, user_id
            FROM participants_all_names AS "pan"
            WHERE pan.name = ? COLLATE FOLD
        """,
            (name,),
        )
        row = await cur.fetchone()
    if not row:
        if auto_create:
            participant = Participant(conn, None, name)
            await participant.save()
        else:
            participant = None
    else:
        participant = Participant.from_row(conn, row)
        with contextlib.suppress(ValueError):
            await participant.fetch_user()
    return participant


async def find_participant(conn: Connection, pattern: str) -> Participant | None:
    """Return the first Participant that matches `pattern`.

    Parameters
    ----------
    conn : Connection
        The database connection to use.
    pattern : str
        A regular expression to match participants.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT participant_id FROM participants_all_names
            WHERE name REGEXP ?
        """,
            (f"(?i:{pattern})",),
        )
        row = await cur.fetchone()
    return await Participant.from_id(conn, row[0]) if row else None


async def get_user(conn: Connection, name: str, *, ignore_case: bool = False) -> DBUser | None:
    """Get an existing user by their name or an alias.

    This is a convenient and generalized function for ZeroBot modules that
    facilitates simple user lookup. The given `name` will match against both
    canonical user names and any aliases associated with a user, taking alias
    case sensitivity into account.

    Parameters
    ----------
    conn : Connection
        The database connection to use.
    name : str
        The name to look up; usually from a message source or command argument.
    ignore_case : bool, optional
        Ignore case even for aliases marked as case-sensitive. ``False`` by
        default.

    Returns
    -------
    Optional[DBUser]
        The matched user or ``None`` if there were no matches for `name`.
    """
    if (name := name.strip()) == "":
        raise ValueError("Name is empty or whitespace")
    placeholder = "? COLLATE FOLD" if ignore_case else "?"
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT user_id FROM users_all_names
            WHERE name = {placeholder}
        """,
            (name,),
        )
        row = await cur.fetchone()
    return await DBUser.from_id(conn, row[0]) if row else None


class Source(DBModel):
    """A specific combination of protocol, server, and channel.

    A source is a particular combination of a protocol, server, and channel
    where something (typically a message) originated. ZeroBot modules should
    create and reference sources when possible as they can be used by all
    feature modules in a centralized manner, as opposed to each module creating
    its own unique channel and/or server references.

    Parameters
    ----------
    source_id : int
        The source's ID.
    protocol : str
        A protocol identifier, e.g. ``discord``.
    server : str, optional
        The name of a server on the given `protocol`.
    channel : str, optional
        The name of a channel on the given `server`.

    Attributes
    ----------
    id
    """

    table_name = "sources"

    def __init__(
        self,
        conn: Connection,
        source_id: int,
        protocol: str,
        server: str | None = None,
        channel: str | None = None,
    ):
        super().__init__(conn)
        self.id = source_id
        if protocol is not None:
            self.protocol = protocol
        else:
            raise TypeError("protocol cannot be None")
        self.server = server
        self.channel = channel

    def __repr__(self):
        attrs = ["id", "protocol", "server", "channel"]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    def __str__(self):
        return ", ".join(attr for attr in (self.server, self.channel) if attr is not None)

    def __eq__(self, other):
        return self.id == other.id

    @classmethod
    def from_row(cls, conn: Connection, row: sqlite3.Row) -> Source:
        """Construct a `Source` from a database row.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        """
        return cls(conn, *row)

    @classmethod
    async def from_id(cls, conn: Connection, source_id: int) -> Source | None:
        """Construct a `Source` by ID from the database.

        Returns `None` if there was no `Source` with the given ID.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        source_id : int
            The ID of the source to fetch.
        """
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT * FROM {cls.table_name} WHERE source_id = ?", (source_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        return cls.from_row(conn, row)

    async def save(self):
        """Save this `Source` to the database."""
        async with self._connection.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO {self.table_name} VALUES (?, ?, ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET
                    protocol = excluded.protocol,
                    server = excluded.server,
                    channel = excluded.channel
            """,
                (self.id, self.protocol, self.server, self.channel),
            )
            self.id = cur.lastrowid
            await self._connection.commit()


async def get_source(conn: Connection, protocol: str, server: str | None = None, channel: str | None = None) -> int:
    """Get an existing source or create a new one.

    This is a convenient and generalized function for Zerobot modules that
    enables the most common actions related to database sources: lookup of
    existing sources and the creation of new ones.

    Parameters
    ----------
    conn : Connection
        The database connection to use.
    protocol : str
        A protocol identifier, e.g. ``discord``.
    server : str, optional
        The name of a server on the given `protocol`.
    channel : str, optional
        The name of a channel on the given `server`.

    Returns
    -------
    int
        The ``source_id`` of either an existing or newly created source.
    """
    for attr in ("protocol", "server", "channel"):
        if locals()[attr].strip() == "":
            raise ValueError(f"{attr} is empty or whitespace")
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT source_id, protocol, server, channel
            FROM {Source.table_name}
            WHERE protocol = ? AND server = ? AND channel = ?
        """,
            (protocol, server, channel),
        )
        row = await cur.fetchone()
    if row is None:
        # Create new Source
        source = Source(conn, None, protocol, server, channel)
        await source.save()
    else:
        source = Source.from_row(conn, row)
    return source


async def create_connection(
    database: str | Path,
    module: Module,
    loop: asyncio.AbstractEventLoop | None = None,
    readonly: bool = False,
    **kwargs,
) -> Connection:
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

    logger.debug(
        f"Creating {'read-only ' if readonly else ''}connection to database at '{database}' for module {module!r}"
    )
    # NOTE: aiosqlite passes kwargs to sqlite3.connect
    conn = await aiosqlite.connect(
        f"{database.as_uri()}?mode={'ro' if readonly else 'rwc'}",
        loop=loop,
        uri=True,
        factory=Connection,
        detect_types=sqlite3.PARSE_DECLTYPES,
        **kwargs,
    )
    conn.setName(module.identifier)
    conn.row_factory = sqlite3.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.create_function("REGEXP", 2, regexp)
    # HACK: As of aiosqlite v0.19, this method is not exposed by the library
    await conn._execute(conn._conn.create_collation, "FOLD", collate_casefold)
    conn._connection._module = module
    conn._connection._dbpath = database
    return conn


def create_interactive_connection(database: str, **kwargs) -> sqlite3.Connection:
    """Start a Python interpreter and create a database connection.

    Sets up a connection to a ZeroBot database and drops into an interactive
    Python interpreter to facilitate manual querying and editing. Performs all
    necessary connection setup needed to work with the database, e.g. custom
    functions, collations, etc.

    Parameters
    ----------
    databse : str or Path
        The path to the SQLite3 datbase.
    kwargs
        Remaining keyword arguments are passed to `sqlite3.connect`.

    Returns
    -------
    sqlite3.Connection
        A connection object for the requested database.
    """
    if not isinstance(database, Path):
        database = Path(database)
    database = database.absolute()

    logger.info(f"Creating interactive connection to database at '{database}'")
    conn = sqlite3.connect(
        database,
        detect_types=sqlite3.PARSE_DECLTYPES,
        **kwargs,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("REGEXP", 2, regexp)
    conn.create_collation("FOLD", collate_casefold)
    return conn


async def create_database(database: str | Path, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Create a new ZeroBot database.

    This method creates a fresh database at the given path and initializes the core tables, indices, views, etc.

    Parameters
    ----------
    database : str or Path
        Where to create the new database.

    loop : asyncio.AbstractEventLoop, optional
        The `asyncio` event loop to use. This is typically `Core.eventloop`.
    """
    if loop is None:
        loop = asyncio.get_event_loop()
    logger.info(f"Creating new database at '{database}'")
    async with aiosqlite.connect(database, loop=loop) as db:
        sql_file = resources.files("ZeroBot").joinpath("sql/schema/core.sql")
        logger.debug(f"Applying core schema from {sql_file}")
        await db.executescript(sql_file.read_text())


async def create_backup(
    database: Connection,
    target: str | Path,
    loop: asyncio.AbstractEventLoop | None = None,
):
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
