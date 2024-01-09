"""feature/quote/classes.py

Classes/Models used by the Quote feature.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, unique
from sqlite3 import Row

from ZeroBot.database import Connection, DBModel, Participant


@unique
class QuoteStyle(IntEnum):
    Standard = 1
    Epigraph = 2
    Unstyled = 3


class QuoteLine(DBModel):
    """A single—possibly the only—line of a quote.

    `QuoteLine` objects make up the body of a given quote. Each line may have
    its own author and may or may not be an action.

    Parameters
    - ---------
    quote_id: int
        The ID of the `Quote` that this line belongs to.
    body: str
        The quoted text.
    author: Participant
        The entity being quoted for this line.
    line_num: int, optional
        The position of this line in the `Quote`. For single-line quotes this
        is always `1`, and is also the default.
    author_num: int, optional
        The * Nth * unique author to be part of the associated `Quote`. For
        single-line quotes this is always `1`, and is also the default.
    action: bool, optional
        Whether or not the body should be interpreted as an "action" rather
        than something written or spoken. Defaults to `False`.
    """

    table_name = "quote_lines"

    def __init__(
        self,
        conn: Connection,
        quote_id: int,
        body: str,
        author: Participant,
        *,
        quote: Quote = None,
        line_num: int = 1,
        author_num: int = 1,
        action: bool = False,
    ):
        super().__init__(conn)
        self.quote_id = quote_id
        self.body = body
        self.author = author
        self.line_num = line_num
        self.author_num = author_num
        self.action = action
        if quote is not None and quote.id != self.quote_id:
            raise ValueError(f"The given quote.id does not match quote_id: {quote.id=} {self.quote_id}")
        self.quote = quote

    def __repr__(self):
        attrs = ["quote_id", "line_num", "body", "author", "author_num", "action"]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    def __str__(self):
        if self.action:
            return f"* {self.author} {self.body}"
        return f"<{self.author}> {self.body}"

    @classmethod
    async def from_row(cls, conn: Connection, row: Row) -> QuoteLine:
        """Construct a `QuoteLine` from a database row.

        Parameters
        -----------
        conn : Connection
            The database connection to use.
        row: sqlite3.Row
            A row returned from the database.
        """
        attrs = {name: row[name] for name in ("quote_id", "line_num", "author_num", "action")}
        author = await Participant.from_id(conn, row["participant_id"])
        return cls(conn, body=row["line"], author=author, **attrs)


class Quote(DBModel):
    """A ZeroBot quote.

    Parameters
    ----------
    quote_id : int or None
        The ID of the quote.
    submitter : Participant
        The person that submitted this quote.
    date : datetime, optional
        The date and time that the quoted content occurred. Defaults to the
        current date/time.
    style : QuoteStyle, optional
        How the quote should be formatted when displayed. Defaults to
        `QuoteStyle.Standard`.

    Attributes
    ----------
    id
    """

    table_name = "quotes"

    def __init__(
        self,
        conn: Connection,
        quote_id: int | None,
        submitter: Participant,
        *,
        date: datetime = datetime.utcnow(),
        style: QuoteStyle = QuoteStyle.Standard,
    ):
        super().__init__(conn)
        self.id = quote_id
        self.submitter = submitter
        self.date = date
        self.style = style
        self.lines = []
        self.authors = []

    def __repr__(self):
        attrs = ["id", "submitter", "date", "style", "lines"]
        repr_str = " ".join(f"{a}={getattr(self, a)!r}" for a in attrs)
        return f"<{self.__class__.__name__} {repr_str}>"

    def __str__(self):
        if self.style is QuoteStyle.Standard:
            return "\n".join(str(line) for line in self.lines)
        if self.style is QuoteStyle.Epigraph:
            formatted = "\n".join(line.body for line in self.lines)
            return f'"{formatted}" —{self.lines[0].author.name}'
        if self.style is QuoteStyle.Unstyled:
            return "\n".join(line.body for line in self.lines)
        raise ValueError(f"Invalid QuoteStyle: {self.style}")

    @classmethod
    async def from_row(cls, conn: Connection, row: Row) -> Quote:
        """Construct a `Quote` from a database row.

        Also fetches the associated `QuoteLine`s.

        Parameters
        ----------
        conn : Connection
            The database connection to use.
        row : sqlite3.Row
            A row returned from the database.
        """
        submitter = await Participant.from_id(conn, row["submitter"])
        quote = cls(
            conn,
            quote_id=row["quote_id"],
            submitter=submitter,
            date=row["submission_date"],
            style=QuoteStyle(row["style"]),
        )
        await quote.fetch_lines()
        return quote

    async def fetch_lines(self) -> list[QuoteLine]:
        """Fetch the `QuoteLine`s that make up the quote body.

        Sets `self.lines` to the fetched lines and returns them.
        """
        async with self._connection.cursor() as cur:
            await cur.execute(
                f"""
                SELECT * FROM {QuoteLine.table_name} WHERE quote_id = ?
                ORDER BY line_num
            """,
                (self.id,),
            )
            self.lines = [await QuoteLine.from_row(self._connection, row) for row in await cur.fetchall()]
        return self.lines

    async def fetch_authors(self) -> list[Participant]:
        """Fetch the authors that are part of this quote.

        Authors in the list are ordered by their `author_num` value. Sets
        `self.authors` to the fetched authors and returns them.
        """
        async with self._connection.cursor() as cur:
            await cur.execute(
                f"""
                SELECT DISTINCT participant_id FROM {QuoteLine.table_name}
                WHERE quote_id = ?
                ORDER BY author_num
            """,
                (self.id),
            )
            self.authors = [await Participant.from_id(self._connection, pid) for pid in await cur.fetchall()]
        return self.authors

    def get_author_num(self, author: Participant) -> int:
        """Get the ordinal of the given author for this quote.

        In other words, return `QuoteLine.author_num` for this author. If the
        given author isn't among the quote lines, returns the next available
        ordinal value. If there are no lines yet, returns ``1``.

        Parameters
        ----------
        author : Participant
            The author to return an ordinal for.
        """
        if not self.lines:
            return 1
        seen = set()
        for line in self.lines:
            if line.author == author:
                return line.author_num
            seen.add(line.author_num)
        return max(seen) + 1

    async def add_line(self, body: str, author: Participant, action: bool = False):
        """Add a line to this quote.

        Parameters
        ----------
        body : str
            The contents of the line.
        author : Participant
            The author of the line.
        action : bool, optional
            Whether or not this line is an action. Defaults to `False`.
        """
        line_num = len(self.lines) + 1
        author_num = self.get_author_num(author)
        self.lines.append(
            QuoteLine(
                self._connection,
                self.id,
                body,
                author,
                quote=self,
                line_num=line_num,
                author_num=author_num,
                action=action,
            )
        )

    async def save(self):
        """Save this `Quote` to the database."""
        async with self._connection.cursor() as cur:
            await cur.execute("BEGIN TRANSACTION")
            await cur.execute(
                f"""
                INSERT INTO {self.table_name}
                (quote_id, submitter, submission_date, style)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (quote_id) DO UPDATE SET
                    submitter = excluded.submitter,
                    submission_date = excluded.submission_date,
                    style = excluded.style
            """,
                (self.id, self.submitter.id, self.date, self.style.value),
            )

            self.id = cur.lastrowid
            for line in self.lines:
                line.quote_id = self.id

            await cur.execute(f"DELETE FROM {QuoteLine.table_name} WHERE quote_id = ?", (self.id,))
            params = [(self.id, ql.line_num, ql.body, ql.author.id, ql.author_num, ql.action) for ql in self.lines]
            await cur.executemany(f"INSERT INTO {QuoteLine.table_name} VALUES(?, ?, ?, ?, ?, ?)", params)

            await cur.execute("COMMIT TRANSACTION")

    async def delete(self):
        """Remove this `Quote` from the database."""
        async with self._connection.cursor() as cur:
            await cur.execute(f"DELETE FROM {Quote.table_name} WHERE quote_id = ?", (self.id,))
        await self._connection.commit()
