from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.onboarding import OnboardingNotFoundError, OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository


class FakeConnection:
    def __init__(self) -> None:
        self.rows: dict[object, dict[str, object]] = {}

    async def execute(self, query: str, *args: object) -> None:
        assert "agent_onboarding_sessions" in query
        self.rows[args[0]] = {
            "id": args[0],
            "owner_id": args[1],
            "api_id": args[2],
            "api_hash_ciphertext": args[3],
            "phone_number": args[4],
            "phone_code_hash_ciphertext": args[5],
            "session_ciphertext": args[6],
            "authorization_status": args[7],
            "agent_name": args[8],
            "system_prompt": args[9],
            "soul_prompt": args[10],
        }

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        assert "agent_onboarding_sessions" in query
        return self.rows.get(args[0])

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return []


class FakeAcquireContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class FakePool:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def acquire(self) -> FakeAcquireContext:
        return FakeAcquireContext(self.connection)


@pytest.mark.asyncio
async def test_database_onboarding_repository_maps_session_rows() -> None:
    pool = FakePool()
    repository = DatabaseOnboardingRepository(pool)
    session = OnboardingSession(
        onboarding_id=uuid4(),
        owner_id=uuid4(),
        api_id=12345,
        api_hash_secret="encrypted-hash",
        phone_number="+79990000000",
        authorization_status=TelegramLoginStatus.CODE_REQUESTED,
        phone_code_hash_secret="encrypted-code-hash",
        session_secret="encrypted-session",
    )

    await repository.save(session)
    loaded = await repository.get(session.onboarding_id)

    assert loaded == session
    saved_row = pool.connection.rows[session.onboarding_id]
    assert saved_row["api_hash_ciphertext"] == "encrypted-hash"
    assert "api_hash_secret" not in saved_row


@pytest.mark.asyncio
async def test_database_onboarding_repository_raises_when_missing() -> None:
    repository = DatabaseOnboardingRepository(FakePool())

    with pytest.raises(OnboardingNotFoundError):
        await repository.get(uuid4())
