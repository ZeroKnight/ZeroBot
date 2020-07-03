"""protocol/discord/protocol.py

Discord protocol implementation.
"""

import asyncio
import logging

import discord
from discord import ChannelType

import ZeroBot.common.abc as abc
from ZeroBot.protocol.context import Context

from .classes import DiscordChannel, DiscordMessage, DiscordServer, DiscordUser

MODULE_NAME = 'Discord'
MODULE_AUTHOR = 'ZeroKnight'
MODULE_VERSION = '0.1'
MODULE_LICENSE = 'MIT'
MODULE_DESC = 'Discord protocol implementation'

CORE = None
CFG = None

logger = logging.getLogger('ZeroBot.Discord')


async def module_register(core, cfg):
    """Initialize module."""
    global CORE, CFG
    CORE = core
    CFG = cfg

    settings = CFG.get('Settings', {})

    ctx = DiscordContext(loop=core.eventloop,
                         max_messages=settings.get('MaxMessages', None))
    coro = ctx.start(CFG['BotToken'])
    return set([(ctx, coro)])


async def module_unregister(contexts):
    """Prepare for shutdown."""
    for ctx in contexts:
        await ctx.close()


class DiscordContext(Context, discord.Client):
    """Discord implementation of a ZeroBot `Context`."""

    # Discord Handlers

    async def on_connect(self):
        """Established connection to Discord, but not yet ready."""
        logger.info('Connected to Discord')

    async def on_ready(self):
        """Connected and ready to listen for events."""
        logger.info(f'Logged in as {self.user}')

    async def on_message(self, message: DiscordMessage):
        """Handle messages."""
        print('Message from {0.author}: {0.content}'.format(message))
        msg = DiscordMessage(message)
        await CORE.module_send_event('message', self, msg)

    # ZeroBot Interface

    async def module_message(self, destination: DiscordServer,
                             message: DiscordMessage):
        await destination.send(message)

    async def module_join(self, where, password=None):
        """Not applicable to Discord bots."""
        CORE.logger.error("'module_join' is not applicable to Discord bots.")

    async def module_leave(self, where: DiscordChannel, reason=None):
        if where.type in any(ChannelType.private, ChannelType.group):
            # TODO: raise exception?
            logger.error(
                f'Can only leave DM or Group channels, not {where.type}')
