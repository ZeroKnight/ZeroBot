"""protocol/discord/classes.py

Discord Implementation of ZeroBot.context classes
"""

from __future__ import annotations

import datetime
import re
from collections.abc import AsyncIterator

import discord

import ZeroBot.context as zctx
from ZeroBot.util import gen_repr

ACTION_PATTERN = re.compile(r"^\*(?:[^*]|(?<=\\)\*)*\*$")


class DiscordUser(zctx.User, discord.User):
    """Represents a Discord User."""

    def __init__(self, user: discord.User):
        self._original = user

    def __getattr__(self, name):
        return getattr(self._original, name)

    def __repr__(self):
        attrs = ["name", "username", "bot"]
        extras = {"id": self._original.id}
        return gen_repr(self, attrs, **extras)

    @property
    def original(self):
        return self._original

    @property
    def name(self) -> str:
        return self._original.display_name

    @property
    def username(self) -> str:
        return self._original.name

    @property
    def bot(self) -> bool:
        return self._original.bot

    def mention(self) -> str:
        return self._original.mention

    def mentioned(self, message: DiscordMessage) -> bool:
        return self._original.mentioned_in(message) or re.search(self.name, message.content, re.I)

    def mention_pattern(self) -> str:
        # The mention string differs by a '!' if it mentions a nickname or not.
        return f"({self.name}|<@!?{self.id}>)"


class DiscordServer(zctx.Server, discord.Guild):
    """Represents a Discord Server (Guild)."""

    def __init__(self, server: discord.Guild):
        self._original = server

    def __getattr__(self, name):
        return getattr(self._original, name)

    def __repr__(self):
        attrs = ["name"]
        extras = {"id": self._original.id, "region": self._original.region}
        return gen_repr(self, attrs, **extras)

    @property
    def original(self):
        return self._original

    @property
    def name(self) -> str:
        return self._original.name

    @property
    def connected(self) -> bool:
        return not self._original.unavailable


class DiscordChannel(zctx.Channel, discord.TextChannel):
    """Represents a Discord channel of any type, private or otherwise."""

    def __init__(self, channel: discord.TextChannel):
        self._original = channel

    def __getattr__(self, name):
        return getattr(self._original, name)

    def __repr__(self):
        attrs = ["name"]
        extras = {
            "id": self._original.id,
            "guild": self._original.guild,
            "category": self._original.category,
        }
        return gen_repr(self, attrs, **extras)

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original

    @property
    def name(self) -> str:
        if self._original.type == discord.ChannelType.private:
            return self._original.recipient.display_name
        return self._original.name

    @property
    def server(self) -> DiscordServer:
        return DiscordServer(self._original.guild)

    async def history(self, limit, before, after, authors) -> AsyncIterator[DiscordMessage]:
        for i, author in enumerate(authors):
            if isinstance(author, str):
                authors[i] = self._original.guild.get_member_named(author)

        async for msg in super().history(limit=limit, before=before, after=after):
            if authors and msg.author not in authors:
                continue
            yield DiscordMessage(msg)

    async def users(self) -> list[DiscordUser]:
        return [DiscordUser(x) for x in self._original.members]


class DiscordMessage(discord.Message, zctx.Message):
    """Represents a Discord message of any type."""

    def __init__(self, message: discord.Message):
        self._original = message

    def __getattr__(self, name):
        return getattr(self._original, name)

    def __repr__(self):
        attrs = ["source", "destination", "content", "time"]
        extras = {
            "id": self._original.id,
            "type": self._original.type,
            "flags": self._original.flags,
            "guild": self._original.guild,
        }
        return gen_repr(self, attrs, **extras)

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original

    @property
    def content(self) -> str:
        return self._original.content

    @property
    def source(self) -> DiscordUser:
        return DiscordUser(self.context, self._original.author)

    @property
    def destination(self) -> DiscordChannel:
        return DiscordChannel(self.context, self._original.channel)

    @property
    def time(self) -> datetime.datetime:
        return self._original.created_at

    @property
    def server(self) -> DiscordServer:
        return self._original.guild

    @staticmethod
    def is_action_str(string: str) -> bool:
        """Check if the given string is an action."""
        return bool(ACTION_PATTERN.match(string.strip()))

    @staticmethod
    def as_action_str(string: str) -> str:
        """Returns the given string as an action."""
        return f"*{string}*"

    @staticmethod
    def strip_action_str(string: str) -> str:
        """Strip the action formatting from the given string."""
        return string[1:-1]
