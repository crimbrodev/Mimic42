from __future__ import annotations

import pytest
from telethon import functions, types

from mimic42.integrations.telegram_tools import TelegramToolbox, build_telegram_langchain_tools


class FakeTelethonCallableClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def __call__(self, request: object) -> bool:
        self.requests.append(request)
        return True


@pytest.mark.asyncio
async def test_set_reaction_sends_telethon_reaction_request() -> None:
    client = FakeTelethonCallableClient()
    toolbox = TelegramToolbox(client)

    result = await toolbox.set_reaction(peer="username", message_id=42, emoji="👍")

    assert result is True
    assert len(client.requests) == 1
    request = client.requests[0]
    assert isinstance(request, functions.messages.SendReactionRequest)
    assert request.peer == "username"
    assert request.msg_id == 42
    assert request.big is False
    assert request.add_to_recent is True
    assert request.reaction == [types.ReactionEmoji(emoticon="👍")]


@pytest.mark.asyncio
async def test_set_reaction_is_exposed_as_langchain_tool() -> None:
    client = FakeTelethonCallableClient()
    tools = build_telegram_langchain_tools(client)

    result = await tools[0].ainvoke(
        {
            "peer": "username",
            "message_id": 42,
            "emoji": "🔥",
        }
    )

    assert tools[0].name == "set_reaction"
    assert result is True
    assert len(client.requests) == 1
