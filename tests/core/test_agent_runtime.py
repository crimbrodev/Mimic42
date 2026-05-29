from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
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


class FakeRuntimeMemoryService:
    def __init__(self) -> None:
        self.saved_messages: list[tuple[UUID, str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    async def build_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
    ) -> list[dict[str, Any]]:
        return [{"role": "user", "content": user_text}]

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        input_messages: list[dict[str, Any]],
        output_messages: list[dict[str, Any]],
    ) -> None:
        self.saved_messages.append((agent_id, peer, input_messages, output_messages))


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
        llm_model="openrouter/free",
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
async def test_trigger_persists_turn_to_memory() -> None:
    memory = FakeRuntimeMemoryService()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=FakeTelegramClient(),
        langchain_agent=FakeLangChainAgent(response="memory reply"),
        memory_service=memory,
    )

    await runtime.trigger_message(AgentTrigger(peer="chat", text="remember this"))

    assert len(memory.saved_messages) == 1
    saved = memory.saved_messages[0]
    assert saved[0] == runtime.config.agent_id
    assert saved[1] == "chat"
    # input_messages has the user message, output_messages has the assistant response
    assert any(m["role"] == "user" and m["content"] == "remember this" for m in saved[2])
    assert any(m["role"] == "assistant" and m["content"] == "memory reply" for m in saved[3])


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
    assert telegram.sent_messages == [("99", "reply to incoming")]


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


class MockDocAttribute:
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name


class MockDocument:
    def __init__(self, filename: str) -> None:
        self.id = 12345
        self.access_hash = 67890
        self.file_reference = b"ref"
        self.dc_id = 1
        self.attributes = [MockDocAttribute(filename)]


class MockMedia:
    def __init__(self, filename: str) -> None:
        self.document = MockDocument(filename)


class MockMessage:
    def __init__(self, filename: str) -> None:
        self.media = MockMedia(filename)
        self.date = datetime(2026, 5, 27, 12, 0, 0)


class MockSender:
    def __init__(self) -> None:
        self.first_name = "Alice"
        self.last_name = "Smith"
        self.username = "alice_smith"
        self.id = 98765


class MockChat:
    def __init__(self) -> None:
        self.title = "Test Group Chat"
        self.username = "test_group"


class MockEventWithMedia:
    def __init__(self, filename: str, client: object) -> None:
        self.message = MockMessage(filename)
        self.client = client
        self.is_private = False
        self.is_group = True
        self.is_channel = False
        self.sender_id = 98765
        self.chat_id = 12345
        self.date = datetime(2026, 5, 27, 12, 0, 0)

    async def get_chat(self) -> MockChat:
        return MockChat()

    async def get_sender(self) -> MockSender:
        return MockSender()


@pytest.mark.asyncio
async def test_rich_message_trigger_and_txt_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram = FakeTelegramClient()

    async def mock_download_media(message: object, file: Any) -> bytes:
        file.write(b"Line 1 content\nLine 2 content")
        return b"Line 1 content\nLine 2 content"

    telegram.download_media = mock_download_media  # type: ignore

    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="agent-ack"),
    )
    await runtime.start()

    monkeypatch.setattr(
        "mimic42.integrations.telegram_tools.format_media_object",
        lambda msg: "doc:12345:67890:726566:1:report.txt",
    )

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 777)

    event = MockEventWithMedia("report.txt", telegram)
    await telegram.emit_message(event)

    await runtime.stop()

    assert len(runtime._langchain_agent.inputs) == 1  # type: ignore
    prompt_text = runtime._langchain_agent.inputs[0]["messages"][-1]["content"]  # type: ignore

    assert "[Входящее сообщение]" in prompt_text
    assert "Время: 2026-05-27 12:00:00" in prompt_text
    assert 'Чат: Группа "Test Group Chat"' in prompt_text
    assert "Отправитель: Alice Smith (@alice_smith, ID: 98765)" in prompt_text
    assert "report.txt" in prompt_text
    assert "Line 1 content" in prompt_text
    assert "Line 2 content" in prompt_text


@pytest.mark.asyncio
async def test_unsupported_document_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="ack"),
    )
    await runtime.start()

    monkeypatch.setattr(
        "mimic42.integrations.telegram_tools.format_media_object",
        lambda msg: "doc:12345:67890:726566:1:document.pdf",
    )

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 777)

    event = MockEventWithMedia("document.pdf", telegram)
    await telegram.emit_message(event)

    await runtime.stop()

    prompt_text = runtime._langchain_agent.inputs[0]["messages"][-1]["content"]  # type: ignore
    assert "[Файл name=document.pdf (этот тип документа нельзя открыть)]" in prompt_text


@pytest.mark.asyncio
async def test_set_wakeup_timer_tool_and_scheduler() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from mimic42.integrations.database_models import (
        AgentModel,
        AgentTimerModel,
        Base,
        ProfileModel,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    agent_id = uuid4()
    owner_id = uuid4()

    async with session_factory() as session:
        session.add(ProfileModel(id=owner_id))
        session.add(
            AgentModel(
                id=agent_id,
                owner_id=owner_id,
                name="Test Agent",
            )
        )
        await session.commit()

    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(agent_id=agent_id, owner_id=owner_id),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="timer triggered reply"),
        session_factory=session_factory,
    )

    from mimic42.integrations.telegram_tools import TelegramToolbox

    toolbox = TelegramToolbox(telegram, agent_id=agent_id, session_factory=session_factory)

    res = await toolbox.set_wakeup_timer(
        peer="12345", delay_seconds=0, description="Process analytics"
    )
    assert res["success"] is True

    async with session_factory() as session:
        from sqlalchemy import select

        stmt = select(AgentTimerModel).where(AgentTimerModel.agent_id == agent_id)
        db_timers = list(await session.scalars(stmt))
        assert len(db_timers) == 1
        assert db_timers[0].peer == "12345"
        assert db_timers[0].status == "pending"
        assert db_timers[0].description == "Process analytics"

    # Call scheduler trigger manually (without start() loop to avoid dual trigger race condition)
    await runtime._check_and_trigger_timers()

    async with session_factory() as session:
        db_timers = list(await session.scalars(stmt))
        assert db_timers[0].status == "succeeded"

    assert len(telegram.sent_messages) == 1
    assert telegram.sent_messages[0] == ("12345", "timer triggered reply")

    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_ignores_muted_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from telethon.tl import functions
    telegram = FakeTelegramClient()

    async def mock_get_input_entity(peer: Any) -> Any:
        return MagicMock()

    async def mock_call(self: Any, request: Any) -> Any:
        if isinstance(request, functions.account.GetNotifySettingsRequest):
            res = MagicMock()
            res.silent = True
            res.mute_until = None
            return res
        return True

    telegram.get_input_entity = mock_get_input_entity  # type: ignore
    monkeypatch.setattr(FakeTelegramClient, "__call__", mock_call, raising=False)

    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="should not reply"),
    )

    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 777)

    event = FakeIncomingEvent(chat_id=12345, message_id=777, text="incoming text")
    await telegram.emit_message(event)

    await runtime.stop()

    assert len(runtime._langchain_agent.inputs) == 0  # type: ignore
    assert len(telegram.sent_messages) == 0


@pytest.mark.asyncio
async def test_runtime_triggers_unmuted_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from telethon.tl import functions
    telegram = FakeTelegramClient()

    async def mock_get_input_entity(peer: Any) -> Any:
        return MagicMock()

    async def mock_call(self: Any, request: Any) -> Any:
        if isinstance(request, functions.account.GetNotifySettingsRequest):
            res = MagicMock()
            res.silent = False
            res.mute_until = None
            return res
        return True

    telegram.get_input_entity = mock_get_input_entity  # type: ignore
    monkeypatch.setattr(FakeTelegramClient, "__call__", mock_call, raising=False)

    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="should reply"),
    )

    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 777)

    event = FakeIncomingEvent(chat_id=12345, message_id=777, text="incoming text")
    await telegram.emit_message(event)

    await runtime.stop()

    assert len(runtime._langchain_agent.inputs) == 1  # type: ignore
    assert telegram.sent_messages == [("12345", "should reply")]


@pytest.mark.asyncio
async def test_trigger_handles_telegram_permission_errors_gracefully() -> None:
    class FailingTelegramClient(FakeTelegramClient):
        async def send_message(self, entity: str, message: str) -> object:
            from telethon.errors import ChatAdminRequiredError
            from telethon.tl.functions.messages import SendMessageRequest
            req = SendMessageRequest(peer=entity, message=message)
            raise ChatAdminRequiredError(request=req)

    telegram = FailingTelegramClient()
    memory = FakeRuntimeMemoryService()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="admin failure reply"),
        memory_service=memory,
    )

    await runtime.start()
    result = await runtime.trigger_message(
        AgentTrigger(peer="me", text="Try to ping read-only channel")
    )
    await runtime.stop()

    assert result.agent_id == runtime.config.agent_id
    assert result.peer == "me"
    assert result.response_text == "admin failure reply"
    assert result.telegram_message_id is None
    # Verify that it still persisted to memory
    assert len(memory.saved_messages) == 1
    saved = memory.saved_messages[0]
    assert saved[0] == runtime.config.agent_id
    assert saved[1] == "me"
    assert any(m["role"] == "user" for m in saved[2])
    assert any(m["role"] == "assistant" for m in saved[3])


@pytest.mark.asyncio
async def test_handle_incoming_message_handles_exceptions_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram = FakeTelegramClient()
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(response="reply"),
    )

    await runtime.start()

    async def mock_peer(ev: Any) -> str:
        return "12345"

    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_peer", mock_peer)
    monkeypatch.setattr("mimic42.core.agent_runtime._extract_incoming_message_id", lambda ev: 777)

    # Monkeypatch trigger_message to raise an error
    async def mock_trigger_message(self, trigger: Any) -> Any:
        raise ValueError("Trigger error")
    monkeypatch.setattr(MimicAgentRuntime, "trigger_message", mock_trigger_message)

    # This should not raise an exception, preventing crash
    event = FakeIncomingEvent(chat_id=12345, message_id=777, text="incoming text")
    await telegram.emit_message(event)

    await runtime.stop()
