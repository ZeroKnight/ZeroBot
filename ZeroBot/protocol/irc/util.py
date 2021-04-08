"""protocol/irc/util.py

IRC protocol implementation utilities and helpers.
"""

from __future__ import annotations

import datetime
from typing import Optional

UserTuple = tuple[Optional[str], Optional[str], Optional[str]]


def irc_time_format(time: datetime.datetime) -> str:
    """Return a ``server-time`` compliant time string based on `time`.

    Parameters
    ----------
    time : datetime.datetime
        The time to convert.

    Returns
    -------
    str
        A time string in ISO 8601 format that adheres to the requirements of
        the IRCv3 ``server-time`` extension. Specifically:
        ``YYYY-MM-DDThh:mm:ss.sssZ``.
    """
    if not time.tzname() or time.tzname() != 'UTC':
        time = time.replace(tzinfo=datetime.timezone.utc)
    return time.isoformat('T', 'milliseconds').replace('+00:00', 'Z')
