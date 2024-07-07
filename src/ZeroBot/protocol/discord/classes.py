"""protocol/discord/classes.py

Discord Implementation of ZeroBot.context classes
"""

from __future__ import annotations

import datetime
import re
from collections.abc import AsyncIterator
from functools import cached_property

import discord

import ZeroBot.context as zctx
from ZeroBot.util import gen_repr

ACTION_PATTERN = re.compile(r"^\*(?:[^*]|(?<=\\)\*)*\*$")


class DiscordUser(zctx.User, discord.User):
    """Represents a Discord User."""

    def __repr__(self):
        attrs = ["name", "username", "bot"]
        extras = {"id": self._original.id}
        return gen_repr(self, attrs, **extras)

    @property
    def name(self) -> str:
        return self._original.display_name

    @property
    def username(self) -> str:
        return self._original.name

    @property
    def bot(self) -> bool:
        return self._original.bot

    @property
    def mention(self) -> str:
        return self._original.mention

    def mentioned(self, message: DiscordMessage) -> bool:
        return self._original.mentioned_in(message) or re.search(self.name, message.content, re.I)

    @cached_property
    def mention_pattern(self) -> re.Pattern:
        # The mention string differs by a '!' if it mentions a nickname or not.
        return re.compile(f"({self.name}|<@!?{self.id}>)")


class DiscordServer(zctx.Server, discord.Guild):
    """Represents a Discord Server (Guild)."""

    def __repr__(self):
        attrs = ["name"]
        extras = {"id": self._original.id, "region": self._original.region}
        return gen_repr(self, attrs, **extras)

    @property
    def name(self) -> str:
        return self._original.name

    @property
    def connected(self) -> bool:
        return not self._original.unavailable

    @property
    async def channels(self) -> list[DiscordChannel]:
        return [DiscordChannel(self.context, channel) for channel in self._original.text_channels]

    @property
    async def users(self) -> list[DiscordUser]:
        return [DiscordChannel(self.context, user) for user in self._original.members]

    async def get_user(
        self, *, id: zctx.EntityID | None = None, name: str | None = None, username: str | None = None
    ) -> DiscordUser | None:
        if name or username:
            user = self._original.get_member_named((name or username).lstrip("@"))
        elif id:
            user = self._original.get_member(id)
        else:
            raise ValueError("Must specify at least one keyword argument")
        return DiscordUser(self.context, user) if user else None

    async def get_channel(self, *, id: zctx.EntityID | None = None, name: str | None = None) -> DiscordChannel | None:
        if name:
            for channel in self.channels:
                if channel.name == name.lstrip("#"):
                    return channel
            return None
        if id:
            channel = self._original.get_channel(id)
            return DiscordChannel(self.context, channel) if channel else None
        raise ValueError("Must specify at least one keyword argument")


class DiscordChannel(zctx.Channel, discord.TextChannel):
    """Represents a Discord channel of any type, private or otherwise."""

    def __repr__(self):
        attrs = ["name"]
        extras = {
            "id": self._original.id,
            "guild": self._original.guild,
        }
        return gen_repr(self, attrs, **extras)

    def __eq__(self, other):
        return self._original == other._original

    @property
    def name(self) -> str:
        if self.is_dm:
            return self._original.recipient.display_name
        return self._original.name

    @property
    def server(self) -> DiscordServer | None:
        if self.is_dm:
            return None
        return DiscordServer(self.context, self._original.guild)

    @property
    def is_dm(self) -> bool:
        return self._original.type is discord.ChannelType.private

    async def history(self, *, limit, before, after, authors) -> AsyncIterator[DiscordMessage]:
        for i, author in enumerate(authors):
            if isinstance(author, str):
                authors[i] = self._original.guild.get_member_named(author)

        async for msg in super().history(limit=limit, before=before, after=after):
            if authors and msg.author not in authors:
                continue
            yield DiscordMessage(self.context, msg)

    async def users(self) -> list[DiscordUser]:
        return [DiscordUser(self.context, x) for x in self._original.members]

    async def get_message(self, id: int | str) -> DiscordMessage | None:
        try:
            return DiscordMessage(self.context, await self._original.fetch_message(id))
        except (discord.NotFound, discord.Forbidden):
            # TODO: Revist when we have a permissions interface
            return None

    @property
    def mention(self) -> str:
        if self.is_dm:
            raise NotImplementedError
        return self._original.mention

    def mentioned(self, message: DiscordMessage) -> bool:
        return self.mention in message.content

    @cached_property
    def mention_pattern(self) -> re.Pattern:
        return re.compile(f"(#{self.name}|<#{self.id}>)")


class DiscordMessage(zctx.Message, discord.Message):
    """Represents a Discord message of any type."""

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
    def server(self) -> DiscordServer | None:
        if (guild := self._original.guild) is not None:
            return DiscordServer(self.context, guild)
        return None

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

    # XXX: Appease ABC subclass check. Could not get __subclasshook__ to work
    # at all; it wasn't ever called for some reason.
    clean_content = discord.Message.clean_content
