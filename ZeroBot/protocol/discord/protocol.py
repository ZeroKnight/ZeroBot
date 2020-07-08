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

    async def on_disconnect(self):
        """Disconnected from Discord.

        Could be any reason, including a normal disconnect, dropped connection,
        or Discord itself terminating the connection for some reason.
        """
        logger.info('Disconnected from Discord')

    async def on_message(self, message: discord.Message):
        """Handle messages."""
        if message.channel.type == ChannelType.private:
            log_msg = '[{0.author}] {0.content}'.format(message)
        else:
            guild = message.guild
            source = '[{0}{1}]'.format(f'{guild}, ' if guild else '',
                                       message.channel)
            log_msg = '{0} <{1.author}> {1.content}'.format(source, message)
        logger.info(log_msg)
        if message.content.startswith(CORE.cmdprefix):
            await CORE.module_commanded(DiscordMessage(message), self)
        else:
            await CORE.module_send_event('message', self,
                                         DiscordMessage(message))

    # ZeroBot Interface

    async def module_message(self, destination: DiscordServer,
                             message: DiscordMessage):
        await destination.send(message)

    async def module_join(self, where, password=None):
        """Not applicable to Discord bots."""
        CORE.logger.error("'module_join' is not applicable to Discord bots.")

    async def module_leave(self, where: DiscordChannel, reason=None):
        """Not applicable to Discord bots.

        Bots cannot have friends, so they cannot participate in group DMs. So
        sad :(
        """
        CORE.logger.error("'module_leave' is not applicable to Discord bots.")

    async def reply_command_result(self, command, result):
        mention_str = command.invoker.mention
        await command.source.send(f"{mention_str}\n{result}")

    # TODO: Help output class with attrs for cmd/module, options, no such
    # command/module, etc to avoid all the string manipulation here
    async def core_command_help(self, help_cmd, help_str, request_cmd=None):
        embed = discord.Embed(title='Help', color=discord.Color.teal())
        if request_cmd:
            usage, desc, *opts = help_str.split('\n\n')
            usage = usage.partition(' ')[2]
            desc = desc.rstrip()
            opts = '\n'.join(opts)
            embed.title += f' — {request_cmd.name}'
            embed.description = f'**Usage**: `{usage}`\n\n{desc}'
            if opts:
                embed.description += f'\n\n**Arguments**:\n```\n{opts}```'
        elif help_cmd.args['module']:
            mod_desc, _, cmds = help_str.partition('\n\n')
            module, desc = mod_desc.split('\n')
            embed.title += f" — {help_cmd.args['module']}"
            embed.description = (f'**{module}**\n\n{desc}\n\n'
                                 f'**Commands**:\n```\n{cmds}```')
        else:
            body = help_str.partition('\n')[2]
            for section in body.split('\n\n'):
                module, cmds = section.split('\n')
                embed.add_field(name=module, value=cmds)
            embed.description = '**Available Commands**'
        await help_cmd.source.send(embed=embed)

    async def core_command_version(self, cmd, version, date):
        embed = discord.Embed(title='Version Info', color=discord.Color.gold())
        embed.description = f'**ZeroBot v{version}**'
        embed.add_field(name='Release Date', value=date)
        # TODO: Set thumbnail to whatever avatar we come up with for ZeroBot
        await cmd.source.send(embed=embed)
