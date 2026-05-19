from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentRecord,
    InMemoryAgentStore,
)


@pytest.mark.asyncio
async def test_dashboard_can_list_agents_messages_and_actions() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    now = datetime(2026, 5, 19, 23, 30, tzinfo=UTC)
    store = InMemoryAgentStore(
        agents=[
            AgentRecord(
                agent_id=agent_id,
                owner_id=owner_id,
                name="Mimic",
                state=AgentRuntimeState.STOPPED,
            )
        ],
        messages=[
            AgentMessageRecord(
                agent_id=agent_id,
                peer="chat",
                role="assistant",
                content="hello",
                created_at=now,
            )
        ],
        activities=[
            AgentActivity(
                agent_id=agent_id,
                event_type="telegram.message.received",
                status="succeeded",
                created_at=now,
            )
        ],
    )
    app = create_app(agent_store=store)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        agents = await client.get(f"/api/v1/agents?owner_id={owner_id}")
        messages = await client.get(f"/api/v1/agents/{agent_id}/messages")
        actions = await client.get(f"/api/v1/agents/{agent_id}/actions")

    assert agents.status_code == 200
    assert agents.json() == [
        {
            "agent_id": str(agent_id),
            "owner_id": str(owner_id),
            "name": "Mimic",
            "state": "stopped",
        }
    ]
    assert messages.status_code == 200
    assert messages.json()[0]["content"] == "hello"
    assert actions.status_code == 200
    assert actions.json()[0]["event_type"] == "telegram.message.received"
