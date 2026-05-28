import asyncio
from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeConfig
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import build_telegram_langchain_tools
from unittest.mock import MagicMock
from telethon import types

async def test_agent_reasoning():
    settings = Settings()
    if not settings.openrouter_api_key:
        print("No OpenRouter API key found!")
        return

    print("Building a mock Telethon client...")
    client = MagicMock()
    # Mock get_input_entity to return a dummy peer
    async def mock_get_input_entity(peer):
        return types.InputPeerUser(user_id=123, access_hash=456)
    client.get_input_entity = mock_get_input_entity
    
    # Build actual LangChain tools
    print("Building Telegram LangChain tools...")
    tools = build_telegram_langchain_tools(client)
    
    import uuid
    # Build agent config
    config = AgentRuntimeConfig(
        agent_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        telegram_session_name="dummy",
        telegram_api_id=12345,
        telegram_api_hash="dummy_hash",
        system_prompt=(
            "Ты — умный ИИ-агент, который общается в Telegram. "
            "Твоя задача — поддерживать живой диалог. "
            "У тебя есть доступ к инструментам Telegram. Если пользователь просит тебя выполнить "
            "какое-то действие (например, замьютить чат, выключить звук, найти координаты), "
            "ты ДОЛЖЕН использовать соответствующий инструмент из списка и запустить его."
        ),
        soul_prompt="Ты дерзкий пацан, общайся неформально.",
        llm_model=settings.llm_model, # e.g. mistralai/mistral-small-2603
    )
    
    print(f"Building LangChain agent with model: {config.llm_model}...")
    agent = build_langchain_agent(config, tools=tools)
    
    # Run a test prompt
    user_text = (
        "[Входящее сообщение]\n"
        "Время: 2026-05-27 19:15:00\n"
        "Чат: ЛС\n"
        "Отправитель: Miqqil⁴² (@miqqil, ID: 6121153070)\n"
        "Содержимое: Замьют этот чат miqqil на 2 часа"
    )
    
    print(f"\nSending prompt to LLM agent:\n{user_text}\n")
    print("Awaiting agent response...")
    
    try:
        response = await agent.ainvoke({
            "messages": [{"role": "user", "content": user_text}]
        })
        print("\n=== Agent final response ===")
        print(response)
    except Exception as e:
        print("Error running agent:", e)

if __name__ == "__main__":
    asyncio.run(test_agent_reasoning())
