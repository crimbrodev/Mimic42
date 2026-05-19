from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from mimic42.core.agent_runtime import AgentRuntimeConfig, LangChainAgentLike


class LangChainGraphAgent:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def ainvoke(self, input_data: dict[str, object]) -> object:
        return await self._graph.ainvoke(input_data)


def build_langchain_agent(config: AgentRuntimeConfig) -> LangChainAgentLike:
    return LangChainGraphAgent(
        create_agent(
            model=config.llm_model,
            tools=[],
            system_prompt=config.combined_prompt,
        )
    )
