from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mimic42.core.onboarding import OnboardingNotFoundError, OnboardingSession, TelegramLoginStatus
from mimic42.integrations.database_models import Base
from mimic42.integrations.database_onboarding import DatabaseOnboardingRepository


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_onboarding_repository_maps_session_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = DatabaseOnboardingRepository(session_factory)
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


@pytest.mark.asyncio
async def test_database_onboarding_repository_raises_when_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = DatabaseOnboardingRepository(session_factory)

    with pytest.raises(OnboardingNotFoundError):
        await repository.get(uuid4())
