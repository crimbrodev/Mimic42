from __future__ import annotations

from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import AgentRuntimeConfig


def build_telegram_client(config: AgentRuntimeConfig) -> TelegramClient:
    if config.telegram_session_string:
        return TelegramClient(
            StringSession(config.telegram_session_string),
            config.telegram_api_id,
            config.telegram_api_hash,
        )

    session_path = Path(config.telegram_session_name)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path),
        config.telegram_api_id,
        config.telegram_api_hash,
    )
