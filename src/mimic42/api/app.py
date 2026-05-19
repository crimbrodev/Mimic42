from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    TelegramAuthorizationRequired,
)
from mimic42.core.crypto import FernetSecretCipher
from mimic42.core.manager import AgentManager, AgentNotFoundError
from mimic42.core.memory import RuntimeMemoryService
from mimic42.core.onboarding import (
    AgentOnboardingService,
    AgentProfileInput,
    OnboardingNotFoundError,
    OnboardingPublicStatus,
    TelegramAuthorizationIncompleteError,
    TelegramCodeVerification,
    TelegramCredentials,
    TelegramPasswordRequiredError,
)
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_onboarding import (
    DatabaseOnboardingRepository,
    create_database_pool,
)
from mimic42.integrations.mem0_memory import build_mem0_memory
from mimic42.integrations.telegram_auth import TelethonAuthClientFactory


class AgentManagerLike(Protocol):
    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> object: ...

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus: ...

    async def start_agent(self, agent_id: UUID) -> None: ...

    async def stop_agent(self, agent_id: UUID) -> None: ...

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult: ...

    async def shutdown(self) -> None: ...


class CreateAgentRequest(BaseModel):
    agent_id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    telegram_session_name: str = Field(min_length=1)
    telegram_api_id: int = Field(gt=0)
    telegram_api_hash: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    soul_prompt: str = Field(default="", max_length=20_000)
    auto_start: bool = False

    def to_runtime_config(self) -> AgentRuntimeConfig:
        return AgentRuntimeConfig(
            agent_id=self.agent_id,
            owner_id=self.owner_id,
            telegram_session_name=self.telegram_session_name,
            telegram_api_id=self.telegram_api_id,
            telegram_api_hash=self.telegram_api_hash,
            system_prompt=self.system_prompt,
            soul_prompt=self.soul_prompt,
        )


class TriggerMessageRequest(BaseModel):
    peer: str = Field(min_length=1)
    text: str = Field(min_length=1)

    def to_trigger(self) -> AgentTrigger:
        return AgentTrigger(peer=self.peer, text=self.text)


def create_app(
    *,
    manager: AgentManagerLike | None = None,
    onboarding_service: AgentOnboardingService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    app_manager = manager or AgentManager()
    app_onboarding_service = onboarding_service or AgentOnboardingService(
        telegram_factory=TelethonAuthClientFactory(),
        llm_model=app_settings.llm_model,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database_pool = None
        if onboarding_service is None and app_settings.database_connection_string:
            database_pool = await create_database_pool(app_settings.database_connection_string)
            cipher = (
                FernetSecretCipher(app_settings.secret_key)
                if app_settings.secret_key is not None
                else None
            )
            app.state.onboarding_service = AgentOnboardingService(
                repository=DatabaseOnboardingRepository(database_pool),
                telegram_factory=TelethonAuthClientFactory(),
                cipher=cipher,
                llm_model=app_settings.llm_model,
            )
            if manager is None:
                long_term_memory = build_mem0_memory(app_settings.mem0_api_key)
                app.state.agent_manager = AgentManager(
                    memory_service_factory=lambda _config: RuntimeMemoryService(
                        short_term=DatabaseShortTermMemory(database_pool),
                        long_term=long_term_memory,
                    )
                )
        try:
            yield
        finally:
            await _get_agent_manager(app).shutdown()
            if database_pool is not None:
                await database_pool.close()

    app = FastAPI(title="Mimic42 API", version="0.1.0", lifespan=lifespan)
    app.state.agent_manager = app_manager
    app.state.onboarding_service = app_onboarding_service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "mimic42-api"}

    @app.post(
        "/api/v1/onboarding/telegram",
        response_model=OnboardingPublicStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def request_telegram_code(payload: TelegramCredentials) -> OnboardingPublicStatus:
        return await _get_onboarding_service(app).request_telegram_code(payload)

    @app.post(
        "/api/v1/onboarding/{onboarding_id}/telegram/code",
        response_model=OnboardingPublicStatus,
    )
    async def verify_telegram_code(
        onboarding_id: UUID,
        payload: TelegramCodeVerification,
    ) -> OnboardingPublicStatus:
        try:
            return await _get_onboarding_service(app).verify_telegram_code(onboarding_id, payload)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(exc.onboarding_id) from exc
        except TelegramPasswordRequiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="Telegram account requires a 2FA password.",
            ) from exc

    @app.post(
        "/api/v1/onboarding/{onboarding_id}/agent",
        response_model=AgentStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def finalize_agent(
        onboarding_id: UUID,
        payload: AgentProfileInput,
    ) -> AgentStatus:
        try:
            return await _get_onboarding_service(app).finalize_agent(onboarding_id, payload)
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(exc.onboarding_id) from exc
        except TelegramAuthorizationIncompleteError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/v1/agents",
        response_model=AgentStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_agent(payload: CreateAgentRequest) -> AgentStatus:
        try:
            manager_for_request = _get_agent_manager(app)
            await manager_for_request.create_agent(
                payload.to_runtime_config(),
                start=payload.auto_start,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc
        return await _get_agent_manager(app).get_agent_status(payload.agent_id)

    @app.get("/api/v1/agents/{agent_id}", response_model=AgentStatus)
    async def get_agent(agent_id: UUID) -> AgentStatus:
        try:
            return await _get_agent_manager(app).get_agent_status(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc

    @app.post(
        "/api/v1/agents/{agent_id}/start",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def start_agent(agent_id: UUID) -> Response:
        try:
            await _get_agent_manager(app).start_agent(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/v1/agents/{agent_id}/stop",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def stop_agent(agent_id: UUID) -> Response:
        try:
            await _get_agent_manager(app).stop_agent(agent_id)
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/v1/agents/{agent_id}/messages/trigger",
        response_model=AgentTriggerResult,
    )
    async def trigger_message(
        agent_id: UUID,
        payload: TriggerMessageRequest,
    ) -> AgentTriggerResult:
        try:
            return await _get_agent_manager(app).trigger_message(agent_id, payload.to_trigger())
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc
        except TelegramAuthorizationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=str(exc),
            ) from exc

    return app


def _not_found(agent_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Agent {agent_id} does not exist",
    )


def _onboarding_not_found(onboarding_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Onboarding session {onboarding_id} does not exist",
    )


def _get_onboarding_service(app: FastAPI) -> AgentOnboardingService:
    return app.state.onboarding_service


def _get_agent_manager(app: FastAPI) -> AgentManagerLike:
    return app.state.agent_manager
