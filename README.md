# Mimic42

Async base for a Telegram userbot agent platform:

- FastAPI API for dashboard-to-agent interaction.
- `MimicAgentRuntime` combines one Telethon user session and one LangChain agent.
- `AgentManager` keeps multiple async runtimes in one event loop.
- Onboarding API requests a Telegram login code, verifies it, stores a session string, and
  finalizes the agent profile.
- Runtime listens for incoming Telegram messages and replies through the LangChain agent.
- The first Telegram tool is `set_reaction`, implemented through Telethon reactions.
- Supabase migration defines users, agents, Telegram sessions, message history, and realtime agent events.
- Short-term conversation context is loaded from Postgres for the last 3 hours and trimmed to
  65,536 estimated tokens before model calls.
- Long-term memory is stored in Mem0 through `MemoryClient`.

## Agent Onboarding Flow

1. `POST /api/v1/onboarding/telegram` with `owner_id`, `api_id`, `api_hash`, `phone_number`.
2. `POST /api/v1/onboarding/{id}/telegram/code` with Telegram `code` and optional `password`.
3. `POST /api/v1/onboarding/{id}/agent` with `name`, `soul_prompt`, optional `system_prompt`.
4. Dashboard controls runtime through `/api/v1/agents/{id}/start`, `/stop`, and
   `/messages/trigger`.

`api_hash`, `phone_code_hash`, and Telethon `StringSession` are backend secrets and must not be
sent back to the browser after the request that provides them.

## Development

```bash
uv sync --all-groups
uv run uvicorn mimic42.main:app --reload
uv run pytest
uv run ruff check .
uv run ty check
```

The API starts at `http://127.0.0.1:8000` by default.

The current `.env` names used by the backend are:

- `DATABASE_CONNECTION_STRING` for the Supabase Postgres connection.
- `OPENROUTER_API_KEY` for model access.
- `MEM0_API_KEY` for long-term memory integration.
- `SECRET_KEY` for encrypting Telegram session strings before database storage.

Generate `SECRET_KEY` with:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The current backend model is global, not per-agent: `openrouter/free`.
