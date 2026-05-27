from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.config = config
        self._telegram_client = telegram_client
        self._langchain_agent = langchain_agent
        self._memory_service = memory_service or RuntimeMemoryService()
        self._session_factory = session_factory
        self._state = AgentRuntimeState.STOPPED
        self._lifecycle_lock = asyncio.Lock()
        self._trigger_lock = asyncio.Lock()
        self._message_handler_registered = False
        self._member_tag_cache: dict[tuple[int, int], tuple[str | None, float]] = {}
        self._chat_mute_cache: dict[str, tuple[bool, float]] = {}
        self._scheduler_task: asyncio.Task[None] | None = None

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
            if self._session_factory is not None:
                self._scheduler_task = asyncio.create_task(self._run_scheduler_loop())

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self._state is AgentRuntimeState.STOPPED:
                return

            self._state = AgentRuntimeState.STOPPING
            if self._scheduler_task is not None:
                self._scheduler_task.cancel()
                try:
                    await self._scheduler_task
                except asyncio.CancelledError:
                    pass
                self._scheduler_task = None

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
            
            # Convert stringified numeric peer ID to integer for Telethon compatibility
            peer_id: str | int = trigger.peer
            if peer_id.startswith("-") and peer_id[1:].isdigit():
                peer_id = int(peer_id)
            elif peer_id.isdigit():
                peer_id = int(peer_id)
                
            sent_message = await self._telegram_client.send_message(
                peer_id,
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
        # Check if chat is muted
        try:
            peer = await _extract_incoming_peer(event)
            import time
            now_ts = time.time()
            
            is_muted = False
            if peer in self._chat_mute_cache:
                cached_muted, expiry = self._chat_mute_cache[peer]
                if now_ts < expiry:
                    is_muted = cached_muted
                    if is_muted:
                        return
                else:
                    self._chat_mute_cache.pop(peer, None)
                    
            if peer not in self._chat_mute_cache:
                input_chat = getattr(event, "input_chat", None)
                if input_chat is None:
                    input_chat = await self._telegram_client.get_input_entity(peer)
                
                from telethon import functions, types
                notify_peer = types.InputNotifyPeer(peer=input_chat)
                res = await self._telegram_client(functions.account.GetNotifySettingsRequest(peer=notify_peer))
                
                is_muted = False
                if res.silent:
                    is_muted = True
                if res.mute_until:
                    from datetime import datetime
                    now = datetime.now(res.mute_until.tzinfo) if res.mute_until.tzinfo else datetime.now()
                    if res.mute_until > now:
                        is_muted = True
                
                self._chat_mute_cache[peer] = (is_muted, now_ts + 60.0)
                
                if is_muted:
                    return
        except Exception as e:
            import traceback
            traceback.print_exc()
            pass

        raw_text = getattr(event, "raw_text", None) or getattr(event, "text", None)
        if not isinstance(raw_text, str):
            raw_text = ""

        # Process attachments in memory and transcribers
        text = await _process_media_and_text(event, raw_text)
        if not text:
            return

        # Format sender name and metadata
        is_private = getattr(event, "is_private", False)
        is_group = getattr(event, "is_group", False)

        from datetime import datetime
        msg_date = getattr(event, "date", None)
        if not msg_date:
            message = getattr(event, "message", None)
            msg_date = getattr(message, "date", None)
        if not msg_date:
            msg_date = datetime.now()
        time_str = msg_date.strftime("%Y-%m-%d %H:%M:%S")

        # Chat name
        if is_private:
            chat_type_str = "ЛС"
        else:
            chat = await event.get_chat()
            chat_title = getattr(chat, "title", "")
            if not chat_title:
                chat_title = (
                    getattr(chat, "username", "")
                    or str(getattr(event, "chat_id", ""))
                )
            if is_group:
                chat_type_str = f'Группа "{chat_title}"'
            else:
                chat_type_str = f'Канал "{chat_title}"'

        # Sender details
        get_sender = getattr(event, "get_sender", None)
        sender = None
        if callable(get_sender):
            try:
                import inspect
                res = get_sender()
                if inspect.isawaitable(res):
                    sender = await res
                else:
                    sender = res
            except Exception:
                pass
        if sender:
            first_name = getattr(sender, "first_name", None) or ""
            last_name = getattr(sender, "last_name", None) or ""
            name_parts = []
            if first_name:
                name_parts.append(first_name)
            if last_name:
                name_parts.append(last_name)
            name_str = " ".join(name_parts)
            if not name_str:
                name_str = (
                    getattr(sender, "title", None)
                    or getattr(sender, "username", None)
                    or str(getattr(sender, "id", ""))
                )
            if not name_str:
                name_str = "Unknown"

            username = getattr(sender, "username", None)
            username_str = f"@{username}" if username else ""
            sender_id = getattr(sender, "id", None)
            id_str = f"ID: {sender_id}" if sender_id else ""

            details = ", ".join(filter(None, [username_str, id_str]))
            details_str = f" ({details})" if details else ""
            sender_str = f"{name_str}{details_str}"
        else:
            chat = await event.get_chat()
            chat_title = getattr(chat, "title", "Unknown")
            sender_str = chat_title

        # Check role/title
        title = None
        if getattr(event, "sender_id", None) and getattr(event, "chat_id", None):
            chat_id = event.chat_id
            sender_id = event.sender_id
            cache_key = (chat_id, sender_id)
            import time
            now_ts = time.time()
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
                    is_supergroup = getattr(event, "is_channel", False)
                    if is_supergroup:
                        input_chat = getattr(event, "input_chat", None) or chat_id
                        input_sender = (
                            getattr(event, "input_sender", None) or sender_id
                        )
                        res = await event.client(
                            functions.channels.GetParticipantRequest(
                                channel=input_chat,
                                participant=input_sender,
                            )
                        )
                        title = (
                            res.participant.title
                            if hasattr(res.participant, "title")
                            else None
                        )
                except Exception:
                    title = None
                self._member_tag_cache[cache_key] = (title, now_ts + 3600.0)

        # Fallback to channel post author signature
        post_author = getattr(getattr(event, "message", None), "post_author", None)
        if not title and post_author:
            title = post_author

        if title:
            sender_str += f" [Подпись/Роль: {title}]"

        # Format output message text
        text = (
            f"[Входящее сообщение]\n"
            f"Время: {time_str}\n"
            f"Чат: {chat_type_str}\n"
            f"Отправитель: {sender_str}\n"
            f"Содержимое: {text}"
        )

        peer = await _extract_incoming_peer(event)
        await self.trigger_message(
            AgentTrigger(
                peer=peer,
                text=text,
                message_id=_extract_incoming_message_id(event),
            )
        )

    async def _run_scheduler_loop(self) -> None:
        """Background loop to check and trigger pending agent timers."""
        while self._state is AgentRuntimeState.RUNNING:
            try:
                await self._check_and_trigger_timers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in scheduler loop: {e}")

            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break

    async def _check_and_trigger_timers(self) -> None:
        if not self._session_factory:
            return

        from datetime import UTC, datetime

        from sqlalchemy import select, update

        from mimic42.integrations.database_models import AgentTimerModel

        now_utc = datetime.now(UTC)

        async with self._session_factory() as db_session:
            stmt = (
                select(AgentTimerModel)
                .where(
                    AgentTimerModel.agent_id == self.config.agent_id,
                    AgentTimerModel.status == "pending",
                    AgentTimerModel.trigger_at <= now_utc,
                )
            )
            result = await db_session.scalars(stmt)
            due_timers = list(result)

            if not due_timers:
                return

            for timer in due_timers:
                timer.status = "running"
            await db_session.commit()

            for timer in due_timers:
                try:
                    trigger_text = f"[Отложенное событие] Сработал таймер: {timer.description}"
                    await self.trigger_message(
                        AgentTrigger(
                            peer=timer.peer,
                            text=trigger_text,
                        )
                    )
                    timer.status = "succeeded"
                except Exception as e:
                    print(f"Error triggering timer {timer.id}: {e}")
                    timer.status = "failed"

                # Update status
                async with self._session_factory() as update_session:
                    await update_session.execute(
                        update(AgentTimerModel)
                        .where(AgentTimerModel.id == timer.id)
                        .values(status=timer.status)
                    )
                    await update_session.commit()


async def _process_media_and_text(event: object, text: str) -> str:
    message = getattr(event, "message", None)
    if not message or not getattr(message, "media", None):
        return text

    try:
        from mimic42.integrations.telegram_tools import format_media_object
        media_id = format_media_object(message)
        if not media_id:
            return text

        if media_id.startswith("photo:"):
            return f"[Фото id={media_id}]" + (f" {text}" if text else "")

        elif media_id.startswith("sticker:"):
            parts = media_id.split(":")
            emoji = parts[5] if len(parts) > 5 else ""
            pack_name = parts[6] if len(parts) > 6 else ""
            pack_str = f" пак={pack_name}" if pack_name else ""
            return (
                f"[Стикер {emoji} id={media_id}{pack_str}]"
                + (f" {text}" if text else "")
            )

        elif media_id.startswith(("voice:", "round:")):
            import os
            from io import BytesIO

            import httpx

            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                err_msg = "[Голосовое сообщение (ошибка: OPENROUTER_API_KEY не установлен)]"
                return err_msg + (f" {text}" if text else "")

            buffer = BytesIO()
            await event.client.download_media(message, file=buffer)
            file_bytes = buffer.getvalue()
            if not file_bytes:
                err_msg = "[Голосовое сообщение (ошибка: файл пустой)]"
                return err_msg + (f" {text}" if text else "")

            filename = "voice.ogg" if media_id.startswith("voice:") else "video.mp4"

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    import base64
                    audio_b64 = base64.b64encode(file_bytes).decode("utf-8")
                    payload = {
                        "model": "openai/whisper-large-v3",
                        "input_audio": {
                            "data": audio_b64,
                            "format": filename.split(".")[-1],
                        },
                    }
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    response = await client.post(
                        "https://openrouter.ai/api/v1/audio/transcriptions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    res_json = response.json()
                    transcription = res_json.get("text", "")
                    mtype = (
                        "Голосовое сообщение"
                        if media_id.startswith("voice:")
                        else "Видеосообщение"
                    )
                    trans_text = f"[{mtype} (расшифровка: \"{transcription}\")]"
                    return trans_text + (f" {text}" if text else "")
            except Exception as e:
                mtype = (
                    "Голосовое сообщение"
                    if media_id.startswith("voice:")
                    else "Видеосообщение"
                )
                return f"[{mtype} (ошибка транскрипции: {e})]" + (f" {text}" if text else "")

        elif media_id.startswith("doc:"):
            parts = media_id.split(":")
            filename = parts[5] if len(parts) > 5 else "file"
            ext = filename.split(".")[-1].lower() if "." in filename else ""

            allowed_exts = (
                "docx",
                "xlsx",
                "txt",
                "md",
                "json",
                "csv",
                "xml",
                "py",
                "html",
                "css",
                "yaml",
                "yml",
            )
            if ext not in allowed_exts and ext != "":
                return (
                    f"[Файл name={filename} (этот тип документа нельзя открыть)]"
                    + (f" {text}" if text else "")
                )

            from io import BytesIO
            buffer = BytesIO()
            await event.client.download_media(message, file=buffer)
            file_bytes = buffer.getvalue()
            if not file_bytes:
                return f"[Файл name={filename} (пустой)]" + (f" {text}" if text else "")

            if ext == "docx":
                try:
                    import docx
                    doc = docx.Document(BytesIO(file_bytes))
                    paragraphs = [p.text for p in doc.paragraphs]
                    for table in doc.tables:
                        for row in table.rows:
                            row_text = [cell.text for cell in row.cells]
                            paragraphs.append(" | ".join(row_text))
                    doc_content = "\n".join(paragraphs)
                    doc_text = f"[Файл name={filename} (содержимое: \"{doc_content}\")]"
                    return doc_text + (f" {text}" if text else "")
                except Exception as e:
                    err_msg = f"[Файл name={filename} (ошибка чтения: {e})]"
                    return err_msg + (f" {text}" if text else "")

            elif ext == "xlsx":
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True)
                    sheet_texts = []
                    for sheet in wb.worksheets:
                        sheet_texts.append(f"Лист: {sheet.title}")
                        for row in sheet.iter_rows(values_only=True):
                            row_str = " | ".join(str(val) if val is not None else "" for val in row)
                            if row_str.strip(" |"):
                                sheet_texts.append(row_str)
                    xlsx_content = "\n".join(sheet_texts)
                    xlsx_text = f"[Файл name={filename} (содержимое: \"{xlsx_content}\")]"
                    return xlsx_text + (f" {text}" if text else "")
                except Exception as e:
                    err_msg = f"[Файл name={filename} (ошибка чтения: {e})]"
                    return err_msg + (f" {text}" if text else "")

            else:
                try:
                    txt_content = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        txt_content = file_bytes.decode("latin-1")
                    except Exception as e:
                        txt_content = f"<Ошибка декодирования: {e}>"

                txt_text = f"[Файл name={filename} (содержимое: \"{txt_content}\")]"
                return txt_text + (f" {text}" if text else "")

    except Exception:
        pass

    return text


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
    chat_id = getattr(event, "chat_id", None)
    if chat_id is not None:
        return str(chat_id)
    get_chat = getattr(event, "get_chat", None)
    if callable(get_chat):
        chat = await get_chat()
        if chat:
            cid = getattr(chat, "id", None)
            if cid is not None:
                return str(cid)
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
