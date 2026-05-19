from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from mimic42.core.memory import MemoryMessage, MemoryRole
from mimic42.integrations.database_onboarding import DatabasePool, _acquire, _str, _uuid


class DatabaseShortTermMemory:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
    ) -> list[MemoryMessage]:
        async with _acquire(self._pool) as connection:
            rows = await connection.fetch(
                """
                select
                    agent_id,
                    coalesce(payload->>'peer', '') as peer,
                    role,
                    content,
                    created_at
                from public.agent_messages
                where agent_id = $1
                    and payload->>'peer' = $2
                    and created_at >= $3
                    and role in ('user', 'assistant', 'system')
                order by created_at asc
                """,
                agent_id,
                peer,
                since,
            )
        return [
            MemoryMessage(
                agent_id=_uuid(row["agent_id"]),
                peer=_str(row["peer"]),
                role=MemoryRole(_str(row["role"])),
                content=_str(row["content"]),
                created_at=_datetime(row["created_at"]),
            )
            for row in rows
        ]

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        async with _acquire(self._pool) as connection:
            await connection.execute(
                """
                insert into public.agent_messages (
                    agent_id,
                    direction,
                    role,
                    content,
                    payload
                )
                values
                    ($1, 'incoming', 'user', $2, jsonb_build_object('peer', $3)),
                    ($1, 'agent_response', 'assistant', $4, jsonb_build_object('peer', $3))
                """,
                agent_id,
                user_text,
                peer,
                assistant_text,
            )


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime.fromisoformat(str(value))
