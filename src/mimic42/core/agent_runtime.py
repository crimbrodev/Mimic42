from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, Field

from mimic42.core.memory import MemoryServiceLike, RuntimeMemoryService


class TelegramAuthorizationRequired(RuntimeError):
    """Raised when a Telethon user session is connected but not authorized."""


class AgentRuntimeState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class AgentRuntimeConfig(BaseModel):
    agent_id: UUID
    owner_id: UUID
    telegram_session_name: str = Field(min_length=1)
    telegram_api_id: int = Field(gt=0)
    telegram_api_hash: str = Field(min_length=1)
    telegram_session_string: str | None = Field(default=None, min_length=1)
    llm_model: str = Field(default="openrouter/free", min_length=1)
    system_prompt: str = Field(min_length=1)
    soul_prompt: str = Field(default="", max_length=20_000)

    @property
    def combined_prompt(self) -> str:
        if not self.soul_prompt:
            return self.system_prompt
        return f"{self.system_prompt}\n\nSOUL.md:\n{self.soul_prompt}"


class AgentStatus(BaseModel):
    agent_id: UUID
    owner_id: UUID
    state: AgentRuntimeState


class AgentTrigger(BaseModel):
    peer: str = Field(min_length=1)
    text: str = Field(min_length=1)
    message_id: int | None = Field(default=None, gt=0)


class AgentTriggerResult(BaseModel):
    agent_id: UUID
    peer: str
    input_text: str
    response_text: str
    telegram_message_id: str | None = None


class TelegramClientLike(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_user_authorized(self) -> bool: ...

    async def send_message(self, entity: str, message: str) -> object: ...

    def add_event_handler(
        self,
        callback: Callable[[object], Awaitable[None]],
        event: object | None = None,
    ) -> None: ...


class LangChainAgentLike(Protocol):
    async def ainvoke(self, input_data: dict[str, object]) -> object: ...


class MimicAgentRuntime:
    """Async runtime that owns one Telegram user session and one LangChain agent."""

    def __init__(
        self,
        *,
        config: AgentRuntimeConfig,
        telegram_client: TelegramClientLike,
        langchain_agent: LangChainAgentLike,
        memory_service: MemoryServiceLike | None = None,
    ) -> None:
        self.config = config
        self._telegram_client = telegram_client
        self._langchain_agent = langchain_agent
        self._memory_service = memory_service or RuntimeMemoryService()
        self._state = AgentRuntimeState.STOPPED
        self._lifecycle_lock = asyncio.Lock()
        self._trigger_lock = asyncio.Lock()
        self._message_handler_registered = False
        self._member_tag_cache: dict[tuple[int, int], tuple[str | None, float]] = {}

    @property
    def state(self) -> AgentRuntimeState:
        return self._state

    @property
    def status(self) -> AgentStatus:
        return AgentStatus(
            agent_id=self.config.agent_id,
            owner_id=self.config.owner_id,
            state=self.state,
        )

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._state is AgentRuntimeState.RUNNING:
                return

            self._state = AgentRuntimeState.STARTING
            try:
                await self._telegram_client.connect()
                if not await self._telegram_client.is_user_authorized():
                    raise TelegramAuthorizationRequired(
                        "Telegram user session is not authorized. Complete onboarding first."
                    )
                self._register_message_handler()
            except Exception:
                self._state = AgentRuntimeState.ERROR
                raise

            self._state = AgentRuntimeState.RUNNING

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self._state is AgentRuntimeState.STOPPED:
                return

            self._state = AgentRuntimeState.STOPPING
            await self._telegram_client.disconnect()
            self._state = AgentRuntimeState.STOPPED

    async def trigger_message(self, trigger: AgentTrigger) -> AgentTriggerResult:
        if self._state is not AgentRuntimeState.RUNNING:
            await self.start()

        async with self._trigger_lock:
            messages = await self._memory_service.build_messages(
                agent_id=self.config.agent_id,
                peer=trigger.peer,
                user_text=trigger.text,
            )
            response = await self._langchain_agent.ainvoke(
                {
                    "messages": messages,
                }
            )
            response_text = _extract_response_text(response)
            sent_message = await self._telegram_client.send_message(
                trigger.peer,
                response_text,
            )
            await self._memory_service.save_turn(
                agent_id=self.config.agent_id,
                peer=trigger.peer,
                user_text=trigger.text,
                assistant_text=response_text,
            )

        return AgentTriggerResult(
            agent_id=self.config.agent_id,
            peer=trigger.peer,
            input_text=trigger.text,
            response_text=response_text,
            telegram_message_id=_extract_message_id(sent_message),
        )

    def _register_message_handler(self) -> None:
        if self._message_handler_registered:
            return

        try:
            from telethon import events
        except ImportError:
            event_builder = None
        else:
            event_builder = events.NewMessage(incoming=True)

        self._telegram_client.add_event_handler(self._handle_incoming_message, event_builder)
        self._message_handler_registered = True

    async def _handle_incoming_message(self, event: object) -> None:
        text = _extract_incoming_text(event)
        if not text:
            return

        # Format sender name and member tag in groups/channels
        is_group = getattr(event, "is_group", False)
        is_channel = getattr(event, "is_channel", False)
        if is_group or is_channel:
            sender = await getattr(event, "get_sender", lambda: None)()
            sender_name = ""
            if sender:
                first_name = getattr(sender, "first_name", None)
                last_name = getattr(sender, "last_name", None)
                if first_name:
                    sender_name = first_name
                    if last_name:
                        sender_name += f" {last_name}"
                else:
                    sender_name = (
                        getattr(sender, "title", None)
                        or getattr(sender, "username", None)
                        or str(getattr(sender, "id", ""))
                    )
            
            if not sender_name:
                sender_name = "Unknown"

            # Fetch member tag/title
            title = None
            if getattr(event, "sender_id", None) and getattr(event, "chat_id", None):
                chat_id = event.chat_id
                sender_id = event.sender_id
                cache_key = (chat_id, sender_id)
                import time
                now_ts = time.time()
                
                # Check cache
                if cache_key in self._member_tag_cache:
                    cached_title, expiry = self._member_tag_cache[cache_key]
                    if now_ts < expiry:
                        title = cached_title
                
                is_expired = (
                    cache_key not in self._member_tag_cache
                    or now_ts >= self._member_tag_cache[cache_key][1]
                )
                if is_expired:
                    try:
                        from telethon.tl import functions
                        # Only supergroups/channels support GetParticipantRequest
                        is_supergroup = getattr(event, "is_channel", False)
                        if is_supergroup:
                            res = await event.client(functions.channels.GetParticipantRequest(
                                channel=chat_id,
                                participant=sender_id
                            ))
                            title = (
                                res.participant.title
                                if hasattr(res.participant, "title")
                                else None
                            )
                    except Exception:
                        title = None
                    self._member_tag_cache[cache_key] = (title, now_ts + 3600.0)

            if title:
                text = f"{sender_name} [{title}]: {text}"
            else:
                text = f"{sender_name}: {text}"

        peer = await _extract_incoming_peer(event)
        await self.trigger_message(
            AgentTrigger(
                peer=peer,
                text=text,
                message_id=_extract_incoming_message_id(event),
            )
        )


def _extract_response_text(response: object) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        response_map = cast("Mapping[str, Any]", response)
        messages = response_map.get("messages")
        if isinstance(messages, list) and messages:
            last_message = messages[-1]
            content = _get_content(last_message)
            if content:
                return content
        output = response_map.get("output") or response_map.get("content")
        if isinstance(output, str) and output:
            return output
    content = _get_content(response)
    if content:
        return content
    return str(response)


def _get_content(value: object) -> str | None:
    if isinstance(value, Mapping):
        value_map = cast("Mapping[str, Any]", value)
        content = value_map.get("content")
    else:
        content = getattr(value, "content", None)
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                item_map = cast("Mapping[str, Any]", item)
                text = item_map.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


def _extract_message_id(message: object) -> str | None:
    if isinstance(message, Mapping):
        message_map = cast("Mapping[str, Any]", message)
        value: Any = message_map.get("id")
    else:
        value = getattr(message, "id", None)
    if value is None:
        return None
    return str(value)


def _extract_incoming_text(event: object) -> str:
    text = getattr(event, "raw_text", None) or getattr(event, "text", None)
    if not isinstance(text, str):
        text = ""
        
    message = getattr(event, "message", None)
    if message and getattr(message, "media", None):
        try:
            from mimic42.integrations.telegram_tools import format_media_object
            media_id = format_media_object(message)
            if media_id:
                if media_id.startswith("photo:"):
                    text = f"[Фото id={media_id}]" + (f" {text}" if text else "")
                elif media_id.startswith("sticker:"):
                    parts = media_id.split(":")
                    emoji = parts[5] if len(parts) > 5 else ""
                    pack_name = parts[6] if len(parts) > 6 else ""
                    pack_str = f" пак={pack_name}" if pack_name else ""
                    text = (
                        f"[Стикер {emoji} id={media_id}{pack_str}]"
                        + (f" {text}" if text else "")
                    )
                elif media_id.startswith("voice:"):
                    text = (
                        f"[Голосовое сообщение id={media_id}]"
                        + (f" {text}" if text else "")
                    )
                elif media_id.startswith("round:"):
                    text = (
                        f"[Видеосообщение id={media_id}]"
                        + (f" {text}" if text else "")
                    )
                elif media_id.startswith("doc:"):
                    parts = media_id.split(":")
                    filename = parts[5] if len(parts) > 5 else "file"
                    text = (
                        f"[Файл name={filename} id={media_id}]"
                        + (f" {text}" if text else "")
                    )
        except Exception:
            pass
            
    return text


async def _extract_incoming_peer(event: object) -> str:
    get_chat = getattr(event, "get_chat", None)
    if callable(get_chat):
        chat = await get_chat()
        return str(chat)
    chat_id = getattr(event, "chat_id", None)
    if chat_id is not None:
        return str(chat_id)
    peer_id = getattr(event, "peer_id", None)
    if peer_id is not None:
        return str(peer_id)
    raise ValueError("Incoming Telegram event does not include a peer")


def _extract_incoming_message_id(event: object) -> int | None:
    value = getattr(event, "id", None)
    if isinstance(value, int):
        return value
    message = getattr(event, "message", None)
    message_id = getattr(message, "id", None)
    if isinstance(message_id, int):
        return message_id
    return None
