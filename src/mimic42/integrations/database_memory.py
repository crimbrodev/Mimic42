from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as db_session:
            result = await db_session.scalars(
                select(AgentMessageModel)
                .where(
                    AgentMessageModel.agent_id == agent_id,
                    AgentMessageModel.payload["peer"].as_string() == peer,
                    AgentMessageModel.created_at >= since,
                )
                .order_by(AgentMessageModel.created_at.asc())
            )
            messages: list[dict[str, Any]] = []
            for model in result:
                # Normalize stored role to OpenAI/LangChain format
                role = model.role
                msg: dict[str, Any] = {"role": role, "content": model.content}
                if role == "tool":
                    tool_call_id = model.payload.get("tool_call_id")
                    if tool_call_id:
                        msg["tool_call_id"] = tool_call_id
                elif role == "assistant":
                    tool_calls = model.payload.get("tool_calls")
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                messages.append(msg)
            return messages

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Save a list of LangChain message dicts to the database."""
        async with self._session_factory() as db_session:
            for msg in messages:
                payload: dict[str, Any] = {"peer": peer}
                role = msg.get("role", msg.get("type", ""))
                content = msg.get("content", "")

                # Preserve LangChain-specific fields in payload
                if "tool_calls" in msg:
                    payload["tool_calls"] = msg["tool_calls"]
                if "tool_call_id" in msg:
                    payload["tool_call_id"] = msg["tool_call_id"]
                if "id" in msg:
                    payload["id"] = msg["id"]

                # Map to database direction enum
                direction = self._resolve_direction(role, msg)

                db_session.add(
                    AgentMessageModel(
                        agent_id=agent_id,
                        direction=direction,
                        role=role,
                        content=content,
                        payload=payload,
                    )
                )
            await db_session.commit()

    @staticmethod
    def _resolve_direction(role: str, msg: dict[str, Any]) -> str:
        if role in ("user", "human"):
            return "incoming"
        if role == "tool":
            return "tool_result"
        if role in ("assistant", "ai"):
            return "tool_call" if msg.get("tool_calls") else "agent_response"
        if role == "system":
            return "dashboard_trigger"
        return "agent_response"
