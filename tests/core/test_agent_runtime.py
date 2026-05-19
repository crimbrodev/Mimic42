from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeState,
    AgentTrigger,
    MimicAgentRuntime,
    TelegramAuthorizationRequired,
)
from mimic42.core.manager import AgentManager

type FakeHandlerEntry = tuple[Callable[[object], Awaitable[None]], object | None]


class FakeTelegramClient:
    def __init__(self, *, authorized: bool = True) -> None:
        self.authorized = authorized
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.sent_messages: list[tuple[str, str]] = []
        self.handlers: list[FakeHandlerEntry] = []

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def send_message(self, entity: str, message: str) -> object:
        self.sent_messages.append((entity, message))
        return {"id": len(self.sent_messages), "entity": entity, "message": message}

    def add_event_handler(
        self,
        callback: Callable[[object], Awaitable[None]],
        event: object | None = None,
    ) -> None:
        self.handlers.append((callback, event))

    async def emit_message(self, event: object) -> None:
        callback, _ = self.handlers[0]
        await callback(event)


class FakeLangChainAgent:
    def __init__(self, response: str = "agent response") -> None:
        self.response = response
        self.inputs: list[dict[str, object]] = []

    async def ainvoke(self, input_data: dict[str, object]) -> dict[str, object]:
        self.inputs.append(input_data)
        return {
            "messages": [
                {"role": "user", "content": "ignored"},
                {"role": "assistant", "content": self.response},
            ]
        }


class FakeIncomingEvent:
    def __init__(self, *, chat_id: int = 10, message_id: int = 42, text: str = "hello") -> None:
        self.chat_id = chat_id
        self.id = message_id
        self.raw_text = text
        self.is_private = True

    async def get_chat(self) -> str:
        return f"chat:{self.chat_id}"


def make_config(agent_id: UUID | None = None, owner_id: UUID | None = None) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=agent_id or uuid4(),
        owner_id=owner_id or uuid4(),
        telegram_session_name="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openai:gpt-4.1-mini",
        system_prompt="Base system prompt",
        soul_prompt="Quiet direct style",
    )


@pytest.mark.asyncio
async def test_runtime_start_and_stop_are_idempotent() -> None:
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(),
    )

    await runtime.start()
    await runtime.start()

    assert runtime.state is AgentRuntimeState.RUNNING
    assert telegram.connected is True
    assert telegram.connect_calls == 1

    await runtime.stop()
    await runtime.stop()

    assert runtime.state is AgentRuntimeState.STOPPED
    assert telegram.connected is False
    assert telegram.disconnect_calls == 1


@pytest.mark.asyncio
async def test_runtime_refuses_unauthorized_userbot_session() -> None:
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=FakeTelegramClient(authorized=False),
        langchain_agent=FakeLangChainAgent(),
    )

    with pytest.raises(TelegramAuthorizationRequired):
        await runtime.start()

    assert runtime.state is AgentRuntimeState.ERROR


@pytest.mark.asyncio
async def test_trigger_invokes_agent_and_sends_response_through_telegram() -> None:
    telegram = FakeTelegramClient()
    agent = FakeLangChainAgent(response="reply from llm")
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=agent,
    )

    await runtime.start()
    result = await runtime.trigger_message(
        AgentTrigger(peer="me", text="Ping from dashboard")
    )

    assert result.agent_id == runtime.config.agent_id
    assert result.peer == "me"
    assert result.response_text == "reply from llm"
    assert telegram.sent_messages == [("me", "reply from llm")]
    assert agent.inputs == [
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Ping from dashboard",
                }
            ]
        }
    ]


@pytest.mark.asyncio
async def test_runtime_registers_incoming_message_handler_and_replies() -> None:
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="reply to incoming"),
    )

    await runtime.start()
    await telegram.emit_message(FakeIncomingEvent(chat_id=99, message_id=777, text="incoming"))

    assert len(telegram.handlers) == 1
    assert telegram.sent_messages == [("chat:99", "reply to incoming")]


@pytest.mark.asyncio
async def test_manager_keeps_multiple_agents_per_owner_and_shuts_them_down() -> None:
    owner_id = uuid4()
    first_config = make_config(owner_id=owner_id)
    second_config = make_config(owner_id=owner_id)

    def build_runtime(config: AgentRuntimeConfig) -> MimicAgentRuntime:
        return MimicAgentRuntime(
            config=config,
            telegram_client=FakeTelegramClient(),
            langchain_agent=FakeLangChainAgent(response=f"reply:{config.agent_id}"),
        )

    manager = AgentManager(runtime_factory=build_runtime)

    first = await manager.create_agent(first_config)
    second = await manager.create_agent(second_config)
    await manager.start_agent(first.config.agent_id)
    await manager.start_agent(second.config.agent_id)

    owner_agents = await manager.list_agents(owner_id=owner_id)
    assert [item.agent_id for item in owner_agents] == [
        first.config.agent_id,
        second.config.agent_id,
    ]

    await manager.shutdown()

    assert first.state is AgentRuntimeState.STOPPED
    assert second.state is AgentRuntimeState.STOPPED
