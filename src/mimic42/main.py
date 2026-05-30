from __future__ import annotations

import logging
import sys

from mimic42.api.app import create_app
from mimic42.config import Settings

# Настройка базового логгера для всего приложения
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

settings = Settings()
app = create_app(settings=settings)
