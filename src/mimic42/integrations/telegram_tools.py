from __future__ import annotations

from typing import Protocol, cast

from langchain_core.tools import BaseTool, StructuredTool
from telethon import functions, types
from telethon.tl.types import TypeInputPeer


class TelethonRequestClient(Protocol):
    async def __call__(self, request: object) -> object: ...


class TelegramToolbox:
    """Small, explicit Telethon tool surface exposed to the agent."""

    def __init__(self, client: TelethonRequestClient) -> None:
        self._client = client

    async def set_reaction(
        self,
        *,
        peer: object,
        message_id: int,
        emoji: str,
        big: bool = False,
    ) -> bool:
        result = await self._client(
            functions.messages.SendReactionRequest(
                peer=cast(TypeInputPeer, peer),
                msg_id=message_id,
                big=big,
                add_to_recent=True,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
            )
        )
        return bool(result)


def build_telegram_langchain_tools(client: TelethonRequestClient) -> list[BaseTool]:
    toolbox = TelegramToolbox(client)

    async def set_reaction(peer: str, message_id: int, emoji: str) -> bool:
        """Set an emoji reaction on a Telegram message."""
        return await toolbox.set_reaction(peer=peer, message_id=message_id, emoji=emoji)

    return [
        StructuredTool.from_function(
            coroutine=set_reaction,
            name="set_reaction",
            description=(
                "Set an emoji reaction on a Telegram message by peer, message id, and emoji."
            ),
        )
    ]
