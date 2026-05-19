from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from pydantic import SecretStr

from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeConfig, LangChainAgentLike


class LangChainGraphAgent:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def ainvoke(self, input_data: dict[str, object]) -> object:
        return await self._graph.ainvoke(input_data)


def build_langchain_agent(config: AgentRuntimeConfig) -> LangChainAgentLike:
    model: str | ChatOpenRouter
    if config.llm_model.startswith("openrouter/"):
        settings = Settings()
        model = ChatOpenRouter(
            model=config.llm_model,
            api_key=SecretStr(settings.openrouter_api_key)
            if settings.openrouter_api_key is not None
            else None,
        )
    else:
        model = config.llm_model

    return LangChainGraphAgent(
        create_agent(
            model=model,
            tools=[],
            system_prompt=config.combined_prompt,
        )
    )
