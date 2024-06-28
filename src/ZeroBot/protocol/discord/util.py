from __future__ import annotations

from discord import Embed

from ZeroBot.context import Context, Message, MessageTarget
from ZeroBot.util import gen_repr


class ResponseProxy:
    """Dynamically respond with a plain text or `Embed` version of a response.

    This helper class allows a feature module to craft a particular reponse
    as two distinct forms: as a plain message and as a Discord embed. When
    sending a response through this proxy object, the version sent is chosen
    based on the protocol of the context given on creation; if it's a Discord
    context, the embed version will be sent. Otherwise, the plain version will
    be sent.
    """

    def __init__(self, ctx: Context, plain_body: str, embed_body: str | None = None, **embed_args) -> None:
        self.ctx = ctx
        self.plain_body = plain_body
        self.embed_body = embed_body
        self.embed = Embed(**embed_args)

    def __repr__(self) -> str:
        return gen_repr(self, attrs=("ctx", "plain", "embed"))

    def __str__(self) -> str:
        return self.embed_body if self.ctx.protocol == "discord" else self.plain_body

    async def send(self, destination: MessageTarget):
        """Proxies `module_message` on the context."""
        if self.ctx.protocol == "discord":
            await self.ctx.module_message(self.embed_body, destination, embed=self.embed)
        else:
            await self.ctx.module_message(self.plain_body, destination)

    async def reply(self, referent: Message):
        """Proxies `module_reply` on the context."""
        if self.ctx.protocol == "discord":
            await self.ctx.module_reply(self.embed_body, referent, embed=self.embed)
        else:
            await self.ctx.module_reply(self.plain_body, referent)
