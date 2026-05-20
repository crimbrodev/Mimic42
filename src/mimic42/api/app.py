from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from mimic42.api.auth import AuthVerifier, CurrentUser, SupabaseJWTVerifier, require_user
from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    TelegramAuthorizationRequired,
)
from mimic42.core.agent_store import AgentActivity, AgentMessageRecord, AgentRecord, AgentStore
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
from mimic42.integrations.database_agent_store import DatabaseAgentStore
from mimic42.integrations.database_memory import DatabaseShortTermMemory
from mimic42.integrations.database_onboarding import (
    DatabaseOnboardingRepository,
)
from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.integrations.mem0_memory import build_mem0_memory
from mimic42.integrations.telegram_auth import TelethonAuthClientFactory

CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]


class AgentManagerLike(Protocol):
    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> object: ...

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus: ...

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]: ...

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
    telegram_session_name: str = Field(min_length=1)
    telegram_api_id: int = Field(gt=0)
    telegram_api_hash: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    soul_prompt: str = Field(default="", max_length=20_000)
    auto_start: bool = False

    def to_runtime_config(self, *, owner_id: UUID) -> AgentRuntimeConfig:
        return AgentRuntimeConfig(
            agent_id=self.agent_id,
            owner_id=owner_id,
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


class TelegramLoginRequest(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=1)
    phone_number: str = Field(min_length=5)


def create_app(
    *,
    manager: AgentManagerLike | None = None,
    onboarding_service: AgentOnboardingService | None = None,
    agent_store: AgentStore | None = None,
    auth_verifier: AuthVerifier | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    app_manager = manager or AgentManager()
    app_onboarding_service = onboarding_service or AgentOnboardingService(
        telegram_factory=TelethonAuthClientFactory(),
        agent_store=agent_store,
        llm_model=app_settings.llm_model,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database_engine = None
        should_build_database = (
            app_settings.database_connection_string
            and (onboarding_service is None or agent_store is None)
        )
        if should_build_database:
            database_engine = create_engine(app_settings.database_connection_string)
            session_factory = create_session_factory(database_engine)
            database_agent_store = agent_store or DatabaseAgentStore(
                session_factory,
                llm_model=app_settings.llm_model,
            )
            cipher = (
                FernetSecretCipher(app_settings.secret_key)
                if app_settings.secret_key is not None
                else None
            )
            app.state.agent_store = database_agent_store
            if onboarding_service is None:
                app.state.onboarding_service = AgentOnboardingService(
                    repository=DatabaseOnboardingRepository(session_factory),
                    telegram_factory=TelethonAuthClientFactory(),
                    cipher=cipher,
                    agent_store=database_agent_store,
                    llm_model=app_settings.llm_model,
                )
            if manager is None:
                long_term_memory = build_mem0_memory(app_settings.mem0_api_key)
                app.state.agent_manager = AgentManager(
                    memory_service_factory=lambda _config: RuntimeMemoryService(
                        short_term=DatabaseShortTermMemory(session_factory),
                        long_term=long_term_memory,
                    ),
                    config_loader=database_agent_store.get_runtime_config,
                    status_sink=database_agent_store.update_status,
                )
        try:
            yield
        finally:
            await _get_agent_manager(app).shutdown()
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(title="Mimic42 API", version="0.1.0", lifespan=lifespan)
    app.state.agent_manager = app_manager
    app.state.onboarding_service = app_onboarding_service
    app.state.agent_store = agent_store
    app.state.auth_verifier = auth_verifier or (
        SupabaseJWTVerifier(supabase_url=app_settings.supabase_url)
        if app_settings.supabase_url is not None
        else None
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "mimic42-api"}

    @app.get("/api/v1/agents", response_model=list[AgentRecord])
    async def list_agents(current_user: CurrentUserDep) -> list[AgentRecord]:
        store = _get_agent_store(app)
        if store is not None:
            return await store.list_agents(owner_id=current_user.user_id)
        statuses = await _get_agent_manager(app).list_agents(owner_id=current_user.user_id)
        return [
            AgentRecord(
                agent_id=status.agent_id,
                owner_id=status.owner_id,
                name="Runtime agent",
                state=status.state,
            )
            for status in statuses
        ]

    @app.post(
        "/api/v1/onboarding/telegram",
        response_model=OnboardingPublicStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def request_telegram_code(
        payload: TelegramLoginRequest,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        credentials = TelegramCredentials(
            owner_id=current_user.user_id,
            api_id=payload.api_id,
            api_hash=payload.api_hash,
            phone_number=payload.phone_number,
        )
        return await _get_onboarding_service(app).request_telegram_code(credentials)

    @app.post(
        "/api/v1/onboarding/{onboarding_id}/telegram/code",
        response_model=OnboardingPublicStatus,
    )
    async def verify_telegram_code(
        onboarding_id: UUID,
        payload: TelegramCodeVerification,
        current_user: CurrentUserDep,
    ) -> OnboardingPublicStatus:
        try:
            status_result = await _get_onboarding_service(app).get_status(onboarding_id)
            _ensure_owner(status_result.owner_id, current_user.user_id)
            result = await _get_onboarding_service(app).verify_telegram_code(onboarding_id, payload)
            return result
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
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        try:
            status_result = await _get_onboarding_service(app).get_status(onboarding_id)
            _ensure_owner(status_result.owner_id, current_user.user_id)
            result = await _get_onboarding_service(app).finalize_agent(onboarding_id, payload)
            return result
        except OnboardingNotFoundError as exc:
            raise _onboarding_not_found(exc.onboarding_id) from exc
        except TelegramAuthorizationIncompleteError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/agents/{agent_id}/messages", response_model=list[AgentMessageRecord])
    async def list_agent_messages(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: int = 50,
    ) -> list[AgentMessageRecord]:
        store = _get_agent_store(app)
        if store is None:
            return []
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.list_messages(agent_id=agent_id, limit=limit)

    @app.get("/api/v1/agents/{agent_id}/actions", response_model=list[AgentActivity])
    async def list_agent_actions(
        agent_id: UUID,
        current_user: CurrentUserDep,
        limit: int = 50,
    ) -> list[AgentActivity]:
        store = _get_agent_store(app)
        if store is None:
            return []
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=current_user.user_id)
        return await store.list_activities(agent_id=agent_id, limit=limit)

    @app.post(
        "/api/v1/agents",
        response_model=AgentStatus,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_agent(
        payload: CreateAgentRequest,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        try:
            manager_for_request = _get_agent_manager(app)
            await manager_for_request.create_agent(
                payload.to_runtime_config(owner_id=current_user.user_id),
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
    async def get_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> AgentStatus:
        try:
            status_result = await _get_agent_manager(app).get_agent_status(agent_id)
            _ensure_owner(status_result.owner_id, current_user.user_id)
            return status_result
        except AgentNotFoundError as exc:
            raise _not_found(exc.agent_id) from exc

    @app.post(
        "/api/v1/agents/{agent_id}/start",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def start_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
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
    async def stop_agent(
        agent_id: UUID,
        current_user: CurrentUserDep,
    ) -> Response:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
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
        current_user: CurrentUserDep,
    ) -> AgentTriggerResult:
        try:
            await _ensure_runtime_owner(app, agent_id=agent_id, user_id=current_user.user_id)
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


def _get_agent_store(app: FastAPI) -> AgentStore | None:
    return app.state.agent_store


def _ensure_owner(owner_id: UUID, user_id: UUID) -> None:
    if owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent does not belong to the authenticated user",
        )


async def _ensure_agent_owner(store: AgentStore, *, agent_id: UUID, user_id: UUID) -> None:
    owned_agents = await store.list_agents(owner_id=user_id)
    if not any(agent.agent_id == agent_id for agent in owned_agents):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} does not exist",
        )


async def _ensure_runtime_owner(app: FastAPI, *, agent_id: UUID, user_id: UUID) -> None:
    store = _get_agent_store(app)
    if store is not None:
        await _ensure_agent_owner(store, agent_id=agent_id, user_id=user_id)
        return
    runtime_status = await _get_agent_manager(app).get_agent_status(agent_id)
    _ensure_owner(runtime_status.owner_id, user_id)
