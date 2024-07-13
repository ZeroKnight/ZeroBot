"""protocol/discord/protocol.py

Discord protocol implementation.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import discord
from discord import ChannelType

from zerobot import util
from zerobot.command import ConfigCmdStatus, ModuleCmdStatus
from zerobot.context import Context, MentionPattern, ProtocolSupport

if TYPE_CHECKING:
    from zerobot.context import EntityID

from .classes import DiscordChannel, DiscordMessage, DiscordServer, DiscordUser

MODULE_NAME = "Discord"
MODULE_AUTHOR = "ZeroKnight"
MODULE_VERSION = "0.2"
MODULE_LICENSE = "MIT"
MODULE_DESC = "Discord protocol implementation"

CORE = None
CFG = None

logger = logging.getLogger("ZeroBot.Discord")


async def module_register(core, cfg):
    """Initialize module."""
    global CORE, CFG
    CORE = core
    CFG = cfg

    settings = CFG.get("Settings", {})
    ctx = DiscordContext(
        loop=core.eventloop,
        intents=discord.Intents.all(),
        max_messages=settings.get("MaxMessages", None),
    )
    coro = ctx.start(CFG["BotToken"])
    return {(ctx, coro)}


async def module_unregister(contexts, reason: str | None = None):
    """Prepare for shutdown."""
    for ctx in contexts:
        await ctx.close()


class DiscordContext(Context, discord.Client):
    """Discord implementation of a ZeroBot `Context`."""

    USER_MENTION = MentionPattern(re.compile(r"<@!?(\d+)>"), re.compile(r"@\S+"))
    CHANNEL_MENTION = MentionPattern(re.compile(r"<#(\d+)>"), re.compile(r"#\S+"))
    ROLE_MENTION = MentionPattern(re.compile(r"<@&(\d+)>"), USER_MENTION.plain)

    # Discord Handlers

    async def on_connect(self):
        """Established connection to Discord, but not yet ready."""
        logger.info("Connected to Discord")

    async def on_ready(self):
        """Connected and ready to listen for events."""
        logger.info(f"Logged in as {self.user}")

        # Find and set owner
        owner_str = CFG["Owner"]
        if re.match(r"^\d+$", owner_str):
            self._owner = self.get_user(owner_str)
            warnmsg = f"Could not set owner: no user found with ID '{owner_str}'"
        else:
            self._owner = DiscordUser(self, util.first(guild.get_member_named(owner_str) for guild in self.guilds))
            warnmsg = f"Could not set owner: user '{owner_str}' not found in any connected server."
        if self._owner:
            logger.info(f"Found owner: {self._owner}")
        else:
            logger.warning(warnmsg)
        await CORE.module_send_event("context_ready", self)

    async def on_disconnect(self):
        """Disconnected from Discord.

        Could be any reason, including a normal disconnect, dropped connection,
        or Discord itself terminating the connection for some reason.
        """
        logger.info("Disconnected from Discord")

    async def on_guild_join(self, guild):
        """We joined a guild."""
        CORE.module_send_event("join", self, DiscordServer(self, guild), self.user)

    async def on_message(self, message: discord.Message):
        """Handle messages."""
        if message.channel.type is ChannelType.private:
            # HACK: Discord intents shenanigans. Message.recipient is always
            # None due to a gateway change and discord.py bug(?).
            # Have to call create_dm the first time, but get_channel will
            # cache/populate recipient on subsequent calls.
            if (channel := super(Context, self).get_channel(message.channel.id)) is None:
                logger.debug(f"Fetching DMChannel for {message.author}")
                message.channel = await message.author.create_dm()
            else:
                message.channel = channel
            log_msg = f"[{message.author}] {message.content}"
        else:
            guild = message.guild
            source = "[{}{}]".format(f"{guild}, " if guild else "", message.channel)
            log_msg = f"{source} <{message.author}> {message.content}"
        logger.info(log_msg)

        msg = DiscordMessage(self, message)
        if message.content.startswith(CORE.cmdprefix) and message.author != self.user:
            await CORE.module_commanded(msg, self)
        else:
            await CORE.module_send_event("message", self, msg)

    # ZeroBot Interface

    @property
    def protocol(self) -> str:
        return "discord"

    @property
    def owner(self) -> DiscordUser:
        return self._owner

    @owner.setter
    def owner(self, user: DiscordUser):
        if isinstance(user, DiscordUser):
            self._owner = user
        else:
            raise TypeError(f"expected a DiscordUser object, not {type(user)}")

    @property
    def user(self) -> DiscordUser:
        return DiscordUser(self, super(Context, self).user)

    @property
    def support() -> ProtocolSupport:
        return (
            ProtocolSupport.MessageMultiLine
            | ProtocolSupport.MessageEdit
            | ProtocolSupport.StatusMessage
            | ProtocolSupport.Visibility
            | ProtocolSupport.Roles
            | ProtocolSupport.VoiceChat
            | ProtocolSupport.VideoChat
            | ProtocolSupport.ScreenShare
            | ProtocolSupport.Attachments
            | ProtocolSupport.Embeds
        )

    async def get_user(
        self, *, id: EntityID | None = None, name: str | None = None, username: str | None = None
    ) -> DiscordUser | None:
        for user in self.get_all_members():
            _name = (name or username or "").lstrip("@")
            if user.id == id or _name in (user.name, user.display_name):
                return DiscordUser(self, user)
        return None

    async def get_channel(self, *, id: EntityID | None = None, name: str | None = None) -> DiscordChannel | None:
        for channel in self.get_all_channels():
            if channel.id == id or channel.name == name.lstrip("#"):
                return DiscordChannel(self, channel)
        return None

    async def module_message(
        self,
        content: str,
        destination: DiscordChannel | DiscordUser,
        *,
        action: bool = False,
        mention_user: DiscordUser | None = None,
        **kwargs,
    ):
        if action:
            content = DiscordMessage.as_action_str(content)
        if mention_user:
            content = f"{mention_user.mention} {content}"
        await destination.send(content, embed=kwargs.get("embed"))

    async def module_reply(self, content: str, referent: DiscordMessage, *, action: bool = False, **kwargs):
        if action:
            content = DiscordMessage.as_action_str(content)
        await referent.channel.send(content, reference=referent, embed=kwargs.get("embed"))

    async def module_join(self, where, password=None):
        """Not applicable to Discord bots."""
        CORE.logger.error("'module_join' is not applicable to Discord bots.")

    async def module_leave(self, where: DiscordChannel, reason=None):
        """Not applicable to Discord bots.

        Bots cannot have friends, so they cannot participate in group DMs. So
        sad :(
        """
        CORE.logger.error("'module_leave' is not applicable to Discord bots.")

    # TODO: Result-based styling
    async def reply_command_result(self, message, command, result):
        if isinstance(message, list):
            message = "\n".join(message)
        await command.source.send(f"{command.invoker.mention}\n{message}")

    async def core_command_help(self, command, result):
        embed = discord.Embed(title="Help", color=discord.Color.teal())
        handler = globals()[f"_format_help_{result.type.name}"]
        handler(embed, command, result)
        await command.source.send(embed=embed)

    async def core_command_module(self, command, results):
        subcmd = command.subcmd
        embed = discord.Embed(title=f"Module {subcmd}")
        if subcmd.endswith("load"):
            await _handle_module_load(embed, command, results)
        else:
            await _handle_module_query(embed, command, results)

    async def core_command_config(self, command, results):
        subcmd = command.subcmd
        embed = discord.Embed(title=f"Config {subcmd}")
        if subcmd.endswith("set"):
            _handle_config_set_reset(embed, command, results[0])
        else:
            _handle_config_save_reload(embed, command, results)
        await command.source.send(embed=embed)

    async def core_command_version(self, command, info):
        embed = discord.Embed(title="Version Info", color=discord.Color.gold(), url=info.home)
        embed.description = f"**ZeroBot v{info.version}**"
        embed.set_thumbnail(url=self.user.avatar.url)
        embed.add_field(name="Release Date", value=info.release_date)
        embed.set_footer(text=f"Hacked together over the years by {info.author} with love.")
        await command.source.send(embed=embed)

    async def core_command_cancel(self, command, cancelled, wait_id, waiting):
        embed = discord.Embed(title="Cancel")
        if command.args["list"]:
            embed.color = discord.Color.gold()
            embed.description = "**Waiting Commands**:\n\nID | Command | Delay | Invoker | Remaining"
            for wait in waiting:
                remaining = wait.delay - (time.time() - wait.started)
                embed.description += (
                    f"\n**{wait.id}** | `{wait.cmd}` | {wait.delay:.2f}s | {wait.invoker} | {remaining:.2f}s"
                )
        elif cancelled:
            embed.color = discord.Color.green()
            embed.description = f"Cancelled waiting command **{wait_id}**:\n```\n{waiting.cmd}```"
        else:
            embed.description = f"No waiting command with ID **{wait_id}**"
        await command.source.send(embed=embed)

    async def core_command_backup(self, command, file):
        embed = discord.Embed(
            title="Database Backup",
            color=discord.Color.green(),
            description="Backup successful",
        )
        embed.add_field(name="Filename", value=file.name)
        await command.source.send(embed=embed)


def _format_help_CMD(embed, help_cmd, result):
    embed.title += f" — {result.name}"
    embed.description = f"**Usage**: `{result.usage}`\n\n{result.description}"
    if result.args:
        embed.description += "\n\n**Arguments**:"
        for arg, (help_str, is_sub) in result.args.items():
            embed.description += f"\n> **{arg}**"
            if help_str:
                embed.description += f"\n> {help_str}\n> "
            elif is_sub:
                embed.description += " - *Subcommand*"
                for name, sub_help in result.subcmds.items():
                    desc = sub_help.description
                    embed.description += f"\n> .. **{name}**"
                    if sub_help.aliases:
                        aliases = ", ".join(sub_help.aliases)
                        embed.description += f" ({aliases})"
                    if desc:
                        embed.description += f"\n> {desc}\n> "
            else:
                embed.description += "\n> "
        embed.description = embed.description.rstrip(" \n>")
    if result.opts:
        embed.description += "\n\n**Options**:"
        for names, info in result.opts.items():
            opts = ", ".join(f"**{name}**" for name in names)
            val_name, opt_desc = info
            if val_name is not None:
                opts = f"{opts} `{val_name}`"
            embed.description += f"\n> {opts}\n> "
            if opt_desc:
                embed.description += f"{opt_desc}\n> "
        embed.description = embed.description.rstrip(" \n>")


def _format_help_MOD(embed, help_cmd, result):
    embed.title += f" — {result.name}"
    embed.description = f"**Module**\n{result.description}"
    if result.cmds:
        embed.description += "\n\n**Commands**:"
        for cmd, help_str in result.cmds[result.name].items():
            embed.description += f"\n> **{cmd}**\n> "
            if help_str:
                embed.description += f"{help_str}\n> "
    else:
        embed.description += "\n\n*No commands available*"
    embed.description = embed.description.rstrip(" \n>")


def _format_help_ALL(embed, help_cmd, result):
    prefix = CORE.cmdprefix
    embed.description = f"💡 *Tip*: Type `{prefix}help help` to learn how to use the {prefix}help command."
    embed.description += "\n\n**Available Commands**:"
    for mod_id, cmds in result.cmds.items():
        section = f"\n\nModule [**{mod_id}**]"
        if help_cmd.args["full"]:
            for cmd, desc in cmds.items():
                section += f"\n> **{cmd}**" + f" - {desc}" if desc else ""
        else:
            section += "\n> " + ", ".join(cmd for cmd in cmds)
        embed.description += section


def _format_help_NO_SUCH_CMD(embed, help_cmd, result):
    embed.color = discord.Color.red()
    embed.description = f"No such command: **{result.name}**"


def _format_help_NO_SUCH_MOD(embed, help_cmd, result):
    embed.color = discord.Color.red()
    embed.description = f"No such module: **{result.name}**"


def _format_help_NO_SUCH_SUBCMD(embed, help_cmd, result):
    embed.color = discord.Color.red()
    subcmds = result.parent.subcmds
    subcmd_list = [f"**{sub}** ({', '.join(subcmds[sub].aliases)})" for sub in subcmds]
    if subcmds:
        embed.description = (
            f"`{result.parent.name}` has no subcommand `{result.name}`. Valid subcommands:\n> {', '.join(subcmd_list)}"
        )
    else:
        embed.description = f"**{result.parent.name}** has no subcommands."


async def _handle_module_load(embed, command, results):
    mcs = ModuleCmdStatus
    subcmd = command.subcmd
    lines = []
    had_ok, had_fail = False, False
    for res in results:
        mod_id = res.module
        mtype = res.mtype
        if mcs.is_ok(res.status):
            had_ok = True
            lines.append(f"\u2705 Successfully {subcmd}ed {mtype} module **{mod_id}**.")
        else:
            had_fail = True
            if res.status in {mcs.LOAD_FAIL, mcs.RELOAD_FAIL}:
                lines.append(f"Failed to {subcmd} {mtype} module **{mod_id}**.")
            elif res.status is mcs.NO_SUCH_MOD:
                lines.append(f"No such {mtype} module: **{mod_id}**")
            elif res.status is mcs.ALREADY_LOADED:
                lines.append(
                    f"{mtype.capitalize()} module **{mod_id}** is already "
                    "loaded. Use `module reload` if you wish to reload it."
                )
            elif res.status is mcs.NOT_YET_LOADED:
                lines.append(
                    f"{mtype.capitalize()} module **{mod_id}** is not yet "
                    "loaded. Use `module load` if you wish to load it."
                )
            lines[-1] = "\u274c " + lines[-1]
    if had_ok and had_fail:
        embed.color = discord.Color.gold()
    elif had_ok:
        embed.color = discord.Color.green()
    elif had_fail:
        embed.color = discord.Color.red()
    embed.description = "\n".join(lines)
    await command.source.send(embed=embed)


async def _handle_module_query(embed, command, results):
    subcmd = command.subcmd
    embed.color = discord.Color.teal()
    if subcmd == "list":
        categories = command.args["category"]
        if command.args["loaded"]:
            embed.description = "Currently loaded modules:\n\n"
        else:
            embed.description = "Available modules:\n\n"
        for category in categories:
            mod_list = ", ".join(res.module for res in results if res.mtype == category)
            if not mod_list:
                mod_list = "*None loaded*"
            embed.add_field(name=f"{category.capitalize()} Modules", value=mod_list)
        await command.source.send(embed=embed)
    elif subcmd == "info":
        for res in results:
            mtype = res.mtype
            info = res.info
            embed = discord.Embed(title=f"{mtype.capitalize()} Module")
            embed.color = discord.Color.red()
            if res.status is ModuleCmdStatus.NO_SUCH_MOD:
                embed.description = f"No such {mtype} module: **{res.module}**"
            elif res.status is ModuleCmdStatus.NOT_YET_LOADED:
                embed.description = f"{mtype.capitalize()} module **{res.module}** is not loaded."
            else:
                embed.color = discord.Color.teal()
                name, desc = info["name"], info["description"]
                embed.description = f"**{name}**\n{desc}"
                embed.add_field(name="Author", value=info["author"])
                embed.add_field(name="Version", value=info["version"])
                embed.add_field(name="License", value=info["license"])
            await command.source.send(embed=embed)


def _handle_config_save_reload(embed, command, results):
    ccs = ConfigCmdStatus
    subcmd = command.subcmd
    lines = []
    had_ok, had_fail = False, False
    for res in results:
        outcome = None
        if ccs.is_ok(res.status):
            had_ok = True
            verb = "saved" if subcmd.startswith("save") else "reloaded"
            outcome = f"\u2705 Successfully {verb}"
        elif res.status is ccs.NO_SUCH_CONFIG:
            had_fail = True
            lines.append(f"\u274c No loaded config with name **{res.config}**")
        else:
            had_fail = True
            verb = "save" if subcmd.startswith("save") else "reload"
            outcome = f"\u274c Failed to {verb}"
        if outcome:
            lines.append(f"{outcome} config **{res.config.path.name}**")
        if res.new_path:
            lines[-1] += f" to new path at `{res.new_path}`"
    if had_ok and had_fail:
        embed.color = discord.Color.gold()
    elif had_ok:
        embed.color = discord.Color.green()
    elif had_fail:
        embed.color = discord.Color.red()
    embed.description = "\n".join(lines)


def _handle_config_set_reset(embed, command, result):
    ccs = ConfigCmdStatus
    subcmd = command.subcmd
    ok = ccs.is_ok(result.status)
    embed.color = discord.Color.green() if ok else discord.Color.red()
    if subcmd.endswith("set"):
        if result.status is ccs.GET_OK:
            embed.description = f"Value of `{result.key}` is `{result.value}`"
        elif result.status is ccs.SET_OK:
            embed.description = f"Setting `{result.key}` to `{result.value}`"
        elif result.status is ccs.RESET_OK:
            what = f"value of `{result.key}`" if result.key else f"config **{result.config.path.name}**"
            state = "default" if command.args["default"] else "previously loaded"
            embed.description = f"Resetting {what} to its previously {state} state"
        elif result.status is ccs.NO_SUCH_KEY:
            verb = "get" if command.args["value"] is None else "set"
            embed.description = f"Cannot {verb} `{result.key}`: no such key"
        embed.add_field(name="Config file", value=result.config.path.stem)
