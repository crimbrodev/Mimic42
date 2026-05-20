from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.integrations.mem0_memory import Mem0LongTermMemory


class FakeMem0Client:
    def __init__(self) -> None:
        self.added: list[tuple[object, dict[str, object]]] = []

    def search(self, query: str, **kwargs: object) -> dict[str, object]:
        return {
            "results": [
                {"memory": f"preference for {query}"},
                {"ignored": "missing memory key"},
            ]
        }

    def add(self, messages: object, **kwargs: object) -> dict[str, object]:
        self.added.append((messages, kwargs))
        return {"results": []}


@pytest.mark.asyncio
async def test_mem0_memory_searches_and_saves_by_agent_id() -> None:
    client = FakeMem0Client()
    memory = Mem0LongTermMemory(client)
    agent_id = uuid4()

    memories = await memory.search(agent_id=agent_id, query="tea")
    await memory.save_turn(agent_id=agent_id, user_text="hello", assistant_text="hi")

    assert memories == ["preference for tea"]
    assert client.added == [
        (
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            {"user_id": str(agent_id), "output_format": "v1.1"},
        )
    ]
