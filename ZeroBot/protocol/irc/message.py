"""protocol/irc/message.py

Implementation of Message ABC for the IRC protocol.
"""

from typing import Dict, Optional, Union

import ZeroBot.common

class Message(common.Message):
    """Represents a message on an IRC network.

    Attributes
    ----------
    source: Union[User, Channel, Server]
        Where the message came from.
    destination: Union[User, Channel, Server]
        Where the message is being sent.
    content: str
        The contents of the message.
    time: datetime
        The time that the message was sent, in UTC.
    tags: Dict[str, Optional[str]]
        A dictionary containing any IRCv3 tags present in the message, mapped to
        their optional values. A tag with no value is assigned ``None``.
    """

    def __init__(self, source: Union[User, Channel, Server],
                 destination: Union[User, Channel, Server], content: str,
                 time: datetime, tags: Dict[str, Optional[str]]):
        self.source = source
        self.destination = destination
        self.content = content
        self.time = time
        self.tags = tags

    def __repr__(self):
        attrs = ['source', 'destination', 'content', 'time']
        return f"{self.__class__.__name__}({' '.join(f'{a}={getattr(self, a)}' for a in attrs)})"

    def __str__(self):
        return self.content

    def __eq__(self, other):
        return self.content == other.content
