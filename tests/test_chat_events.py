"""Случайные события чата: каталог (chat_events.py) и их применение в боте.

Главное, что здесь ловится, — «сломанный тип» события: имя победителя уходило
в чат видимым куском HTML («<a href="…">имя</a>» прямо текстом) вместо
кликабельной ссылки. Причина не в шаблоне события, а в лишнем html.escape()
поверх display_name_by_id(), которая и так отдаёт готовую ссылку.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import chat_events

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
LINK = '<a href="https://telegram.me/muerzek">мурзик мелеонер</a>'


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def _winner_chat(monkeypatch):
    """Чат, где ровно один держатель кошелька и он же — победитель."""
    monkeypatch.setattr(bot_module.db, "list_wallet_holders",
                        _returns([{"user_id": 42, "coins": 100_000}]), raising=False)
    monkeypatch.setattr(bot_module.db, "add_coins", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "take_coins_up_to", _returns(1234), raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns(LINK), raising=False)


@pytest.mark.parametrize("key", ["meteor", "lottery", "inheritance", "bank_error"])
def test_событие_с_победителем_не_экранирует_ссылку(_winner_chat, key):
    event = chat_events.EVENTS_BY_KEY[key]
    text = asyncio.run(bot_module._apply_moment_event(CHAT_ID, event))
    assert LINK in text, "имя должно уйти готовой ссылкой"
    assert "&lt;a" not in text, "двойное экранирование — ссылка станет видимым текстом"


def test_карманник_не_экранирует_ссылку(_winner_chat):
    event = chat_events.EVENTS_BY_KEY["pickpocket"]
    text = asyncio.run(bot_module._apply_moment_event(CHAT_ID, event))
    assert LINK in text
    assert "&lt;a" not in text


def test_каждое_мгновенное_событие_имеет_обработчик(_winner_chat, monkeypatch):
    """Событие без ветки в _apply_moment_event тихо не состоялось бы: цикл
    получил бы None и промолчал. Проверяем, что таких в каталоге нет."""
    monkeypatch.setattr(bot_module.db, "get_stock_price", _returns(10.0), raising=False)
    monkeypatch.setattr(bot_module.db, "set_stock_price", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_stock_price_point", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "get_chat_coins", _returns(10_000_000), raising=False)
    monkeypatch.setattr(bot_module.db, "add_chat_coins", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "list_recent_active_users",
                        _returns([{"user_id": 42}]), raising=False)
    monkeypatch.setattr(bot_module.db, "add_coins_to_users", _returns(1), raising=False)
    monkeypatch.setattr(bot_module.db, "tax_all_wallets", _returns(500), raising=False)
    monkeypatch.setattr(bot_module.db, "clear_all_surveillance", _returns(2), raising=False)
    monkeypatch.setattr(bot_module.db, "restock_shop_items", _returns(3), raising=False)
    monkeypatch.setattr(bot_module.db, "list_poor_wallets",
                        _returns([{"user_id": 7, "coins": 0}]), raising=False)

    warned = []
    monkeypatch.setattr(bot_module.logger, "warning",
                        lambda *a, **k: warned.append(a), raising=False)

    for event in chat_events.EVENTS:
        if event.kind != chat_events.MOMENT:
            continue
        asyncio.run(bot_module._apply_moment_event(CHAT_ID, event))
    assert not warned, f"события без обработчика: {warned}"


def test_описание_события_не_падает_без_подстановок():
    for event in chat_events.EVENTS:
        text = chat_events.describe(event)
        assert text and "{" not in text.replace("{}", "")
