from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from uuid import UUID

import asyncpg

from mimic42.core.onboarding import (
    OnboardingNotFoundError,
    OnboardingSession,
    TelegramLoginStatus,
)


class DatabaseConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None: ...

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]: ...


class DatabasePool(Protocol):
    def acquire(self) -> AbstractAsyncContextManager[DatabaseConnection]: ...


class DatabaseOnboardingRepository:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    async def save(self, session: OnboardingSession) -> None:
        async with _acquire(self._pool) as connection:
            await connection.execute(
                """
                insert into public.agent_onboarding_sessions (
                    id,
                    owner_id,
                    api_id,
                    api_hash_ciphertext,
                    phone_number,
                    phone_code_hash_ciphertext,
                    session_ciphertext,
                    authorization_status,
                    agent_name,
                    system_prompt,
                    soul_prompt
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                on conflict (id) do update set
                    api_hash_ciphertext = excluded.api_hash_ciphertext,
                    phone_number = excluded.phone_number,
                    phone_code_hash_ciphertext = excluded.phone_code_hash_ciphertext,
                    session_ciphertext = excluded.session_ciphertext,
                    authorization_status = excluded.authorization_status,
                    agent_name = excluded.agent_name,
                    system_prompt = excluded.system_prompt,
                    soul_prompt = excluded.soul_prompt
                """,
                session.onboarding_id,
                session.owner_id,
                session.api_id,
                session.api_hash_secret,
                session.phone_number,
                session.phone_code_hash_secret,
                session.session_secret,
                session.authorization_status.value,
                session.name,
                session.system_prompt,
                session.soul_prompt,
            )

    async def get(self, onboarding_id: UUID) -> OnboardingSession:
        async with _acquire(self._pool) as connection:
            row = await connection.fetchrow(
                """
                select
                    id,
                    owner_id,
                    api_id,
                    api_hash_ciphertext,
                    phone_number,
                    phone_code_hash_ciphertext,
                    session_ciphertext,
                    authorization_status,
                    agent_name,
                    system_prompt,
                    soul_prompt
                from public.agent_onboarding_sessions
                where id = $1
                limit 1
                """,
                onboarding_id,
            )
        if row is None:
            raise OnboardingNotFoundError(onboarding_id)
        return _row_to_session(dict(row))


async def create_database_pool(database_connection_string: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=database_connection_string)


@asynccontextmanager
async def _acquire(pool: DatabasePool) -> AsyncIterator[DatabaseConnection]:
    acquire_context = pool.acquire()
    async with acquire_context as connection:
        yield connection


def _row_to_session(row: dict[str, object]) -> OnboardingSession:
    return OnboardingSession(
        onboarding_id=_uuid(row["id"]),
        owner_id=_uuid(row["owner_id"]),
        api_id=_int(row["api_id"]),
        api_hash_secret=_str(row["api_hash_ciphertext"]),
        phone_number=_str(row["phone_number"]),
        authorization_status=TelegramLoginStatus(row["authorization_status"]),
        phone_code_hash_secret=_optional_str(row.get("phone_code_hash_ciphertext")),
        session_secret=_optional_str(row.get("session_ciphertext")),
        name=_optional_str(row.get("agent_name")),
        system_prompt=_optional_str(row.get("system_prompt")),
        soul_prompt=_optional_str(row.get("soul_prompt")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _str(value: object) -> str:
    if not isinstance(value, str):
        return str(value)
    return value


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value))


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
