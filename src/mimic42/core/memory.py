from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

DEFAULT_SHORT_TERM_TTL = timedelta(hours=3)
DEFAULT_MAX_CONTEXT_TOKENS = 65_536


class MemoryRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MemoryMessage(BaseModel):
    agent_id: UUID
    peer: str = Field(min_length=1)
    role: MemoryRole
    content: str
    created_at: datetime


class ShortTermMemoryStore(Protocol):
    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
    ) -> list[MemoryMessage]: ...

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        assistant_text: str,
    ) -> None: ...


class LongTermMemoryStore(Protocol):
    async def search(self, *, agent_id: UUID, query: str) -> list[str]: ...

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        user_text: str,
        assistant_text: str,
    ) -> None: ...


class MemoryServiceLike(Protocol):
    async def build_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
    ) -> list[dict[str, str]]: ...

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        assistant_text: str,
    ) -> None: ...


class RuntimeMemoryService:
    def __init__(
        self,
        *,
        short_term: ShortTermMemoryStore | None = None,
        long_term: LongTermMemoryStore | None = None,
        short_term_ttl: timedelta = DEFAULT_SHORT_TERM_TTL,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        token_counter: Callable[[str], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._short_term = short_term
        self._long_term = long_term
        self._short_term_ttl = short_term_ttl
        self._max_context_tokens = max_context_tokens
        self._token_counter = token_counter or _estimate_tokens
        self._now = now or (lambda: datetime.now(UTC))

    async def build_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        long_term_context = await self._load_long_term_context(agent_id=agent_id, query=user_text)
        if long_term_context:
            messages.append(
                {
                    "role": MemoryRole.SYSTEM.value,
                    "content": "Long-term memory:\n"
                    + "\n".join(f"- {memory}" for memory in long_term_context),
                }
            )

        short_term_messages = await self._load_short_term_context(agent_id=agent_id, peer=peer)
        messages.extend(
            {"role": message.role.value, "content": message.content}
            for message in short_term_messages
        )
        messages.append({"role": MemoryRole.USER.value, "content": user_text})
        return self._fit_token_budget(messages)

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if self._short_term is not None:
            await self._short_term.save_turn(
                agent_id=agent_id,
                peer=peer,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        if self._long_term is not None:
            await self._long_term.save_turn(
                agent_id=agent_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )

    async def _load_short_term_context(
        self,
        *,
        agent_id: UUID,
        peer: str,
    ) -> list[MemoryMessage]:
        if self._short_term is None:
            return []
        since = self._now() - self._short_term_ttl
        return await self._short_term.load_recent_messages(
            agent_id=agent_id,
            peer=peer,
            since=since,
        )

    async def _load_long_term_context(self, *, agent_id: UUID, query: str) -> list[str]:
        if self._long_term is None:
            return []
        return await self._long_term.search(agent_id=agent_id, query=query)

    def _fit_token_budget(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        selected_reversed: list[dict[str, str]] = []
        token_total = 0
        for message in reversed(messages):
            message_tokens = self._token_counter(message["content"])
            if selected_reversed and token_total + message_tokens > self._max_context_tokens:
                break
            selected_reversed.append(message)
            token_total += message_tokens
        return list(reversed(selected_reversed))


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
