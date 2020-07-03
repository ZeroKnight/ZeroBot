"""protocol/discord/classes.py

Discord Implementation of ZeroBot.common.abc classes.
"""

from typing import Union

import discord
from discord.abc import GuildChannel, PrivateChannel

import ZeroBot.common.abc as zabc
from ZeroBot.util import gen_repr


class DiscordUser(zabc.User):
    """Represents a Discord User."""

    def __init__(self, user: discord.abc.User):
        self._original = user
        self.name = user.display_name
        self.username = user.name + user.discriminator
        self.bot = user.bot

    def __repr__(self):
        attrs = ['name', 'username', 'bot']
        extras = {'id': self._original.id}
        return gen_repr(self, attrs, **extras)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original

    def mention(self) -> str:
        return self._original.mention()

    def mentioned(self, message: 'DiscordMessage') -> bool:
        return self._original.mentioned_in(message)


class DiscordServer(zabc.Server):
    """Represents a Discord Server (or Guild)."""

    def __init__(self, server: discord.Guild):
        self._original = server
        self.name = server.name
        self.port = None  # Not applicable to Discord servers
        self.ipv6 = None  # Not applicable to Discord servers

    def __repr__(self):
        attrs = ['name']
        extras = {'id': self._original.id, 'region': self._original.region}
        return gen_repr(self, attrs, **extras)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original

    @property
    def hostname(self) -> str:
        """Alias for `self.name`.

        Discord servers don't have hostnames in the traditional sense.
        """
        return self.name

    @property
    def connected(self) -> bool:
        return not self._original.unavailable


class DiscordChannel(zabc.Channel):
    """Represents a Discord channel of any type, private or otherwise."""

    def __init__(self, channel: Union[GuildChannel, PrivateChannel]):
        self._original = channel
        self.password = None  # Not applicable to Discord channels
        if channel.type == discord.ChannelType.private:
            self.name = channel.recipient.display_name
        else:
            self.name = channel.name
        self.type = channel.type

    def __repr__(self):
        attrs = ['name']
        extras = {
            'id': self._original.id,
            'guild': self._original.guild,
            'category': self._original.category
        }
        return gen_repr(self, attrs, **extras)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original


class DiscordMessage(zabc.Message):
    """Represents a Discord message of any type."""

    def __init__(self, message: discord.Message):
        self.source = message.author
        self.destination = message.channel
        self.content = message.content
        self.time = message.created_at
        self._original = message

    def __repr__(self):
        attrs = ['source', 'destination', 'content', 'time']
        extras = {
            'id': self._original.id,
            'type': self._original.type,
            'flags': self._original.flags,
            'guild': self._original.guild,
        }
        return gen_repr(self, attrs, **extras)

    def __str__(self):
        return self.content

    def __eq__(self, other):
        return self._original == other._original

    @property
    def original(self):
        return self._original
