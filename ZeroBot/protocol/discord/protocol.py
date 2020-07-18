"""protocol/discord/protocol.py

Discord protocol implementation.
"""

import asyncio
import logging

import discord
from discord import ChannelType

import ZeroBot.common.abc as abc
from ZeroBot.common import HelpType, ModuleCmdStatus
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


async def module_unregister(contexts, reason: str = None):
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

    async def core_command_help(self, help_cmd, result):
        embed = discord.Embed(title='Help', color=discord.Color.teal())
        handler = getattr(self, f'_format_help_{result.type.name}')
        handler(embed, help_cmd, result)
        await help_cmd.source.send(embed=embed)

    def _format_help_CMD(self, embed, help_cmd, result):
        embed.title += f' — {result.name}'
        embed.description = (f'**Usage**: `{result.usage}`\n\n'
                             f'{result.description}')
        if result.args or result.opts:
            embed.description += '\n\n**Arguments**:'
            for arg, (help_str, is_sub) in result.args.items():
                embed.description += f'\n> **{arg}**'
                if help_str:
                    embed.description += f'\n> ```\n> {help_str}```'
                else:
                    embed.description += '\n> '
                if is_sub:
                    embed.description += '\n> *Subcommand*\n> ```'
                    for name, sub_help in result.subcmds.items():
                        desc = sub_help.description
                        embed.description += f'\n> {name} - {desc}'
                    embed.description += '```'
            for names, info in result.opts.items():
                opts = ', '.join(f'**{name}**' for name in names)
                embed.description += (f'\n> {opts} {info[0]}'
                                      f'\n> ```\n> {info[1]}```')

    def _format_help_MOD(self, embed, help_cmd, result):
        embed.title += f" — {result.name}"
        embed.description = f'**Module**\n{result.description}'
        if result.cmds:
            embed.description += '\n\n**Commands**:'
            for cmd, help_str in result.cmds[result.name].items():
                embed.description += f'\n> **{cmd}**\n> '
                if help_str:
                    embed.description += f'```\n> {help_str}```'
        else:
            embed.description += '*\n\n*No commands available*'

    def _format_help_ALL(self, embed, help_cmd, result):
        embed.description = '**Available Commands**:'
        for mod_id, cmds in result.cmds.items():
            section = f'\n\nModule [**{mod_id}**]'
            if help_cmd.args['full']:
                for cmd, desc in cmds.items():
                    section += f'\n> **{cmd}**' + f' - {desc}' if desc else ''
            else:
                section += '\n> ' + ', '.join(cmd for cmd in cmds.keys())
            embed.description += section

    def _format_help_NO_SUCH_CMD(self, embed, help_cmd, result):
        embed.color = discord.Color.red()
        embed.description = f'No such command: **{result.name}**'

    def _format_help_NO_SUCH_MOD(self, embed, help_cmd, result):
        embed.color = discord.Color.red()
        embed.description = f'No such module: **{result.name}**'

    def _format_help_NO_SUCH_SUBCMD(self, embed, help_cmd, result):
        embed.color = discord.Color.red()
        subcmds = list(result.parent.subcmds.keys())
        if subcmds:
            embed.description = (f'**{result.parent.name}** has no subcommand '
                                 f'**{result.name}**. Valid subcommands:\n> '
                                 + ', '.join(subcmds))
        else:
            embed.description = f'**{result.parent.name}** has no subcommands.'

    async def core_command_module(self, command, status, modules=None,
                                  info=None):
        mcs = ModuleCmdStatus
        if command.args['subcmd'] != 'list':
            # TODO: handle multiple modules
            mod_id = command.args['module'][0]
        mtype = 'protocol' if command.args['protocol'] else 'feature'
        verb = '{0}load'.format('re' if mcs.is_reload(status) else '')
        embed = discord.Embed(title='Module')
        if status is mcs.QUERY:
            embed.color = discord.Color.teal()
            if modules:
                if command.args['loaded']:
                    embed.description = '**Currently loaded modules**:\n\n'
                else:
                    embed.description = '**Available modules**:\n\n'
                categories = ['protocol', 'feature']
                if command.args['protocol']:
                    categories.remove('feature')
                elif command.args['feature']:
                    categories.remove('protocol')
                for category in categories:
                    mod_list = ', '.join(modules[category]) or '*None loaded*'
                    embed.add_field(name=f'{category.capitalize()} Modules',
                                    value=mod_list)
            elif info:
                pass
        elif mcs.is_ok(status):
            embed.color = discord.Color.green()
            embed.description = (
                f'Successfully {verb}ed {mtype} module **{mod_id}**.')
        else:
            embed.color = discord.Color.red()
            if status in (mcs.LOAD_FAIL, mcs.RELOAD_FAIL):
                embed.description = (
                    f'Failed to {verb} {mtype} module **{mod_id}**.')
            elif status is mcs.NO_SUCH_MOD:
                embed.description = f'No such {mtype} module: **{mod_id}**'
            elif status is mcs.ALREADY_LOADED:
                embed.description = (
                    f'{mtype.capitalize()} module **{mod_id}** is already '
                    'loaded. Use `module reload` if you wish to reload it.')
            elif status is mcs.NOT_YET_LOADED:
                embed.description = (
                    f'{mtype.capitalize()} module **{mod_id}** is not yet '
                    'loaded. Use `module load` if you wish to load it.')
        await command.source.send(embed=embed)

    async def core_command_version(self, command, info):
        embed = discord.Embed(title='Version Info',
                              color=discord.Color.gold())
        embed.description = f'**ZeroBot v{info.version}**'
        embed.add_field(name='Release Date', value=info.release_date)
        embed.set_footer(text='Hacked together over the years by '
                         f'{info.author} with love.')
        # TODO: Set thumbnail to whatever avatar we come up with for ZeroBot
        await command.source.send(embed=embed)
