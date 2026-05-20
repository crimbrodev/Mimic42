from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.memory import MemoryMessage, MemoryRole
from mimic42.integrations.database_models import AgentMessageModel


class DatabaseShortTermMemory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_recent_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        since: datetime,
    ) -> list[MemoryMessage]:
        async with self._session_factory() as db_session:
            result = await db_session.scalars(
                select(AgentMessageModel)
                .where(
                    AgentMessageModel.agent_id == agent_id,
                    AgentMessageModel.payload["peer"].as_string() == peer,
                    AgentMessageModel.created_at >= since,
                    AgentMessageModel.role.in_(
                        [MemoryRole.USER.value, MemoryRole.ASSISTANT.value, MemoryRole.SYSTEM.value]
                    ),
                )
                .order_by(AgentMessageModel.created_at.asc())
            )
            return [
                MemoryMessage(
                    agent_id=model.agent_id,
                    peer=str(model.payload.get("peer", "")),
                    role=MemoryRole(model.role),
                    content=model.content,
                    created_at=model.created_at,
                )
                for model in result
            ]

    async def save_turn(
        self,
        *,
        agent_id: UUID,
        peer: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        async with self._session_factory() as db_session:
            db_session.add_all(
                [
                    AgentMessageModel(
                        agent_id=agent_id,
                        direction="incoming",
                        role=MemoryRole.USER.value,
                        content=user_text,
                        payload={"peer": peer},
                    ),
                    AgentMessageModel(
                        agent_id=agent_id,
                        direction="agent_response",
                        role=MemoryRole.ASSISTANT.value,
                        content=assistant_text,
                        payload={"peer": peer},
                    ),
                ]
            )
            await db_session.commit()
