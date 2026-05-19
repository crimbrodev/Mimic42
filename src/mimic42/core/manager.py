from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast
from uuid import UUID

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentStatus,
    AgentTrigger,
    AgentTriggerResult,
    MimicAgentRuntime,
    TelegramClientLike,
)
from mimic42.core.memory import RuntimeMemoryService
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telethon_client import build_telegram_client


class AgentNotFoundError(KeyError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"Agent {agent_id} does not exist")
        self.agent_id = agent_id


RuntimeFactory = Callable[[AgentRuntimeConfig], MimicAgentRuntime]
MemoryServiceFactory = Callable[[AgentRuntimeConfig], RuntimeMemoryService]


class AgentManager:
    """In-process async registry for multiple users and their agent runtimes."""

    def __init__(
        self,
        runtime_factory: RuntimeFactory | None = None,
        memory_service_factory: MemoryServiceFactory | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory or _build_runtime
        self._memory_service_factory = memory_service_factory
        self._agents: dict[UUID, MimicAgentRuntime] = {}
        self._lock = asyncio.Lock()

    async def create_agent(
        self,
        config: AgentRuntimeConfig,
        *,
        start: bool = False,
    ) -> MimicAgentRuntime:
        async with self._lock:
            if config.agent_id in self._agents:
                raise ValueError(f"Agent {config.agent_id} already exists")
            runtime = (
                self._build_runtime_with_memory(config)
                if self._memory_service_factory is not None
                else self._runtime_factory(config)
            )
            self._agents[config.agent_id] = runtime

        if start:
            await runtime.start()
        return runtime

    async def get_agent(self, agent_id: UUID) -> MimicAgentRuntime:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError(agent_id) from exc

    async def get_agent_status(self, agent_id: UUID) -> AgentStatus:
        return (await self.get_agent(agent_id)).status

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        agents = list(self._agents.values())
        if owner_id is not None:
            agents = [agent for agent in agents if agent.config.owner_id == owner_id]
        return [agent.status for agent in agents]

    async def start_agent(self, agent_id: UUID) -> None:
        await (await self.get_agent(agent_id)).start()

    async def stop_agent(self, agent_id: UUID) -> None:
        await (await self.get_agent(agent_id)).stop()

    async def trigger_message(
        self,
        agent_id: UUID,
        trigger: AgentTrigger,
    ) -> AgentTriggerResult:
        return await (await self.get_agent(agent_id)).trigger_message(trigger)

    async def shutdown(self) -> None:
        agents = list(self._agents.values())
        await asyncio.gather(*(agent.stop() for agent in agents), return_exceptions=True)

    def _build_runtime_with_memory(self, config: AgentRuntimeConfig) -> MimicAgentRuntime:
        telegram_client = cast(TelegramClientLike, build_telegram_client(config))
        if self._memory_service_factory is None:
            memory_service = RuntimeMemoryService()
        else:
            memory_service = self._memory_service_factory(config)
        return MimicAgentRuntime(
            config=config,
            telegram_client=telegram_client,
            langchain_agent=build_langchain_agent(config),
            memory_service=memory_service,
        )


def _build_runtime(config: AgentRuntimeConfig) -> MimicAgentRuntime:
    telegram_client = cast(TelegramClientLike, build_telegram_client(config))
    return MimicAgentRuntime(
        config=config,
        telegram_client=telegram_client,
        langchain_agent=build_langchain_agent(config),
    )
