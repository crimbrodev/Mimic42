from __future__ import annotations

from uuid import uuid4

import pytest

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.agent_store import InMemoryAgentStore
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    InMemoryOnboardingRepository,
    OnboardingSession,
    TelegramAuthClient,
    TelegramLoginStatus,
)


class UnusedTelegramFactory:
    def build(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> TelegramAuthClient:
        raise AssertionError("Telegram factory should not be used while finalizing an agent")


@pytest.mark.asyncio
async def test_finalize_agent_persists_agent_and_telegram_session() -> None:
    owner_id = uuid4()
    onboarding_id = uuid4()
    onboarding_repository = InMemoryOnboardingRepository()
    agent_store = InMemoryAgentStore()
    await onboarding_repository.save(
        OnboardingSession(
            onboarding_id=onboarding_id,
            owner_id=owner_id,
            api_id=12345,
            api_hash_secret="encrypted-hash",
            phone_number="+79990000000",
            authorization_status=TelegramLoginStatus.AUTHORIZED,
            session_secret="encrypted-session",
        )
    )
    service = AgentOnboardingService(
        repository=onboarding_repository,
        telegram_factory=UnusedTelegramFactory(),
        agent_store=agent_store,
    )

    status = await service.finalize_agent(
        onboarding_id,
        AgentProfileInput(name="Mimic", soul_prompt="Short replies", system_prompt="System"),
    )

    assert status.agent_id == onboarding_id
    assert status.state is AgentRuntimeState.STOPPED
    persisted = await agent_store.get_runtime_config(onboarding_id)
    assert persisted.owner_id == owner_id
    assert persisted.telegram_api_hash == "encrypted-hash"
    assert persisted.telegram_session_string == "encrypted-session"
    assert persisted.system_prompt == "System"
    assert persisted.soul_prompt == "Short replies"
