"""Веб-панель управления ботом (FastAPI). Запуск: python -m webpanel

Панель лежит в подпакете, а модули бота (db.py и остальные) — на уровень
выше. Python кладёт в пути поиска каталог запуска, а он зависит от того, чем
именно панель подняли — `python -m webpanel`, `uvicorn webpanel.app:app` или
systemd из другого каталога. Поэтому папку бота добавляем в пути явно: иначе
`import db` падает с ModuleNotFoundError при части способов запуска.
"""

import os
import sys

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

from .app import app  # noqa: E402  (импорт только после правки sys.path)

__all__ = ["app"]
