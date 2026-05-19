from __future__ import annotations

from mimic42.api.app import create_app
from mimic42.config import Settings

settings = Settings()
app = create_app()

