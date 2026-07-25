"""Общая обвязка тестов.

Тесты проверяют логику, а не сеть и не БД, поэтому два тяжёлых пакета
подменяем заглушками ещё до импорта тестируемых модулей:

  * aiogram  — нужен только как источник классов Bot/исключений; настоящий
               клиент Telegram в тестах не поднимаем;
  * aiomysql — db.py импортирует его на уровне модуля, хотя соединение
               открывает лениво (db.init_pool), которого мы не вызываем.

Так тесты запускаются на любой машине, где есть pytest, — без .env, без
MySQL и без токена бота.
"""

from __future__ import annotations

import os
import sys
import types

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)


def _module_importable(name: str) -> bool:
    """Есть ли настоящий модуль и грузится ли он.

    Проверяем импортом, а не find_spec: matplotlib, например, находится, но
    падает на загрузке DLL — для наших целей это то же самое, что «нет».
    """
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _install_fake_matplotlib() -> None:
    """activity_chart.py тянет matplotlib на уровне модуля, а через него — весь
    bot.py. Рисование графиков тестам не нужно, поэтому подменяем заглушкой,
    если настоящий пакет не работает (на этой машине ему не хватает системной
    DLL)."""
    if _module_importable("matplotlib"):
        return

    matplotlib = types.ModuleType("matplotlib")
    matplotlib.use = lambda *a, **k: None
    matplotlib.rcParams = {}

    pyplot = types.ModuleType("matplotlib.pyplot")
    for name in ("subplots", "figure", "close", "savefig", "tight_layout"):
        setattr(pyplot, name, lambda *a, **k: None)

    dates = types.ModuleType("matplotlib.dates")
    dates.DateFormatter = lambda *a, **k: None
    dates.HourLocator = lambda *a, **k: None
    dates.DayLocator = lambda *a, **k: None

    ticker = types.ModuleType("matplotlib.ticker")
    ticker.MaxNLocator = lambda *a, **k: None
    ticker.FuncFormatter = lambda *a, **k: None

    matplotlib.pyplot = pyplot
    matplotlib.dates = dates
    matplotlib.ticker = ticker
    sys.modules.update({
        "matplotlib": matplotlib,
        "matplotlib.pyplot": pyplot,
        "matplotlib.dates": dates,
        "matplotlib.ticker": ticker,
    })


def _install_fake_aiogram() -> None:
    # Настоящий aiogram (из .venv) всегда лучше заглушки: с ним проверяются
    # реальные фильтры и роутеры, а не наши представления о них.
    if "aiogram" in sys.modules or _module_importable("aiogram"):
        return

    aiogram = types.ModuleType("aiogram")

    class Bot:  # noqa: D401 — только для аннотаций и isinstance в тестах
        pass

    aiogram.Bot = Bot

    exceptions = types.ModuleType("aiogram.exceptions")

    class TelegramAPIError(Exception):
        # Сигнатура повторяет настоящий aiogram: (method, message). Иначе тесты,
        # написанные под заглушку, разваливаются на машине, где установлен
        # настоящий пакет, — и наоборот.
        def __init__(self, method=None, message: str = ""):
            super().__init__(message)
            self.method = method
            self.message = message

    class TelegramBadRequest(TelegramAPIError):
        pass

    class TelegramForbiddenError(TelegramAPIError):
        pass

    exceptions.TelegramAPIError = TelegramAPIError
    exceptions.TelegramBadRequest = TelegramBadRequest
    exceptions.TelegramForbiddenError = TelegramForbiddenError

    types_mod = types.ModuleType("aiogram.types")

    class ChatPermissions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class BufferedInputFile:
        def __init__(self, data, filename=None):
            self.data = data
            self.filename = filename

    class InlineKeyboardButton:
        def __init__(self, text=None, callback_data=None, **kwargs):
            self.text = text
            self.callback_data = callback_data
            self.__dict__.update(kwargs)

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None, **kwargs):
            self.inline_keyboard = inline_keyboard or []
            self.__dict__.update(kwargs)

    types_mod.ChatPermissions = ChatPermissions
    types_mod.BufferedInputFile = BufferedInputFile
    types_mod.InlineKeyboardButton = InlineKeyboardButton
    types_mod.InlineKeyboardMarkup = InlineKeyboardMarkup

    client = types.ModuleType("aiogram.client")
    client_default = types.ModuleType("aiogram.client.default")

    class DefaultBotProperties:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    client_default.DefaultBotProperties = DefaultBotProperties

    enums = types.ModuleType("aiogram.enums")

    class ParseMode:
        HTML = "HTML"

    enums.ParseMode = ParseMode

    aiogram.exceptions = exceptions
    aiogram.types = types_mod
    aiogram.client = client
    aiogram.enums = enums
    client.default = client_default

    sys.modules.update({
        "aiogram": aiogram,
        "aiogram.exceptions": exceptions,
        "aiogram.types": types_mod,
        "aiogram.client": client,
        "aiogram.client.default": client_default,
        "aiogram.enums": enums,
    })


def _install_fake_aiomysql() -> None:
    if "aiomysql" in sys.modules or _module_importable("aiomysql"):
        return
    aiomysql = types.ModuleType("aiomysql")

    class DictCursor:
        pass

    aiomysql.DictCursor = DictCursor
    aiomysql.create_pool = None  # тесты в БД не ходят
    sys.modules["aiomysql"] = aiomysql


_install_fake_matplotlib()
_install_fake_aiogram()
_install_fake_aiomysql()
