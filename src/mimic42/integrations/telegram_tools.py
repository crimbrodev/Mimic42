from __future__ import annotations

from typing import Protocol, cast

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
