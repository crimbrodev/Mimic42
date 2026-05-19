from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mimic42 API"
    environment: str = Field(default="development")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, le=65535)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MIMIC42_",
        extra="ignore",
    )

