"""Ежедневный завоз в магазин: один чат, одно объявление, адресаты — в личке.

Три вещи, которые здесь ломались и ради которых написан этот файл:

  * завоз шёл по ВСЕМ чатам, где когда-либо открывали магазин (включая чужие
    группы и личку), а объявление каждый раз слал в один и тот же чат — люди
    видели «магазин обновился» столько раз, сколько чатов набралось в базе;
  * объявление приходило в общий чат, хотя нужно админам в личные сообщения;
  * выключить эти сообщения было нечем.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЖАЛОБЫ = -1003673552861          # settings.complaint_chat_id — рабочий чат
ЗАЯВКИ = -1003811995090          # settings.notify_chat_id — другой чат
ЧУЖОЙ = -1009999999999


@pytest.fixture
def стенд(monkeypatch):
    """Подменяет базу и отправку сообщений; возвращает журнал вызовов."""
    состояние = {
        "data": {},                 # bot_data: ключ -> значение
        "restocked": [],            # (chat_id, item_key, сколько)
        "личка": [],                # (user_id, текст)
        "в_чат": [],                # (chat_id, текст)
        "ротация": [],              # чаты, где крутили лавку
    }

    async def get_data(key):
        value = состояние["data"].get(key)
        return None if value is None else {"data_value": value}

    async def set_data(key, value, updated_by=None):
        состояние["data"][key] = value

    async def delete_data(key):
        состояние["data"].pop(key, None)

    async def list_shop_items_for_restock(chat_id, exclude_keys=()):
        return [{"item_key": "cake", "restock_max": 5}]

    async def restock_shop_item(chat_id, item_key, amount):
        состояние["restocked"].append((chat_id, item_key, amount))

    async def get_shop_item(chat_id, item_key):
        return {"item_key": item_key, "name": "Тортик", "emoji": "🍰"}

    async def list_shop_chat_ids():
        # Ровно та ситуация из жизни: в базе несколько чатов, включая личку.
        return [ЖАЛОБЫ, ЗАЯВКИ, ЧУЖОЙ, 555]

    for имя, функция in (
        ("get_data", get_data), ("set_data", set_data), ("delete_data", delete_data),
        ("list_shop_items_for_restock", list_shop_items_for_restock),
        ("restock_shop_item", restock_shop_item),
        ("get_shop_item", get_shop_item),
        ("list_shop_chat_ids", list_shop_chat_ids),
    ):
        monkeypatch.setattr(bot_module.db, имя, функция, raising=False)

    async def ensure_rotation(chat_id):
        состояние["ротация"].append(chat_id)
        return True

    monkeypatch.setattr(bot_module, "ensure_black_market_rotation", ensure_rotation)

    async def send_message(chat_id, text, **kwargs):
        if chat_id < 0:
            состояние["в_чат"].append((chat_id, text))
        else:
            состояние["личка"].append((chat_id, text))

    monkeypatch.setattr(bot_module.bot, "send_message", send_message)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЖАЛОБЫ)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", ЗАЯВКИ)
    monkeypatch.setattr(bot_module, "admin_levels", {111: 1, 222: 3})
    monkeypatch.setattr(bot_module, "OWNER_IDS", {999})
    # Случайность из завоза убираем: тест про адресатов, а не про кубик.
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: b)
    return состояние


def _завоз(now=None):
    return asyncio.run(bot_module.run_shop_restock(now or datetime(2026, 7, 31, 15, 5)))


def test_завоз_идёт_только_в_рабочий_чат(стенд):
    """Раньше цикл проходил по всем чатам из shop_items — по чужой группе и по
    личке в том числе, — а объявление слал в один и тот же чат."""
    _завоз()
    assert {c for c, _, _ in стенд["restocked"]} == {ЖАЛОБЫ}
    assert стенд["ротация"] == [ЖАЛОБЫ]


def test_объявление_приходит_один_раз_каждому_админу(стенд):
    _завоз()
    assert sorted(uid for uid, _ in стенд["личка"]) == [111, 222, 999]
    assert стенд["в_чат"] == [], "объявление больше не идёт в общий чат"


def test_повторный_запуск_в_тот_же_день_молчит(стенд):
    _завоз()
    стенд["личка"].clear()
    _завоз(datetime(2026, 7, 31, 15, 55))
    assert стенд["личка"] == []


def test_на_следующий_день_приходит_снова(стенд):
    _завоз()
    стенд["личка"].clear()
    _завоз(datetime(2026, 8, 1, 15, 5))
    assert len(стенд["личка"]) == 3


def test_выключенные_уведомления_молчат_но_завоз_идёт(стенд):
    """Выключатель гасит только сообщения: товар на полке появиться обязан,
    иначе «выключить уведомления» тихо выключило бы саму механику."""
    стенд["data"][bot_module._shop_restock_notify_key(ЖАЛОБЫ)] = "0"
    _завоз()
    assert стенд["личка"] == []
    assert стенд["restocked"], "завоз должен пройти и с выключенными уведомлениями"


def test_закрытая_личка_одного_админа_не_мешает_остальным(стенд, monkeypatch):
    async def send_message(chat_id, text, **kwargs):
        if chat_id == 111:
            raise RuntimeError("bot was blocked by the user")
        стенд["личка"].append((chat_id, text))

    monkeypatch.setattr(bot_module.bot, "send_message", send_message)
    _завоз()
    assert sorted(uid for uid, _ in стенд["личка"]) == [222, 999]


def test_без_привязанного_чата_ничего_не_делает(стенд, monkeypatch):
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", None)
    _завоз()
    assert стенд["restocked"] == []
    assert стенд["личка"] == []


def test_уведомления_включены_по_умолчанию(стенд):
    """Ключа в базе нет — значит включено. Обратный порядок («нет ключа =
    выключено») означал бы, что настройку надо включать руками, а человек
    просил ровно наоборот: пусть приходит, а выключить можно."""
    assert asyncio.run(bot_module.is_shop_restock_notify_enabled(ЖАЛОБЫ)) is True


# ---------------------------------------------------------------------------
# Выключатель «+завоз / -завоз»
# ---------------------------------------------------------------------------

class ФейкСообщение:
    def __init__(self, text, chat_id):
        self.text = text
        self.chat = type("Chat", (), {"id": chat_id, "type": "supergroup"})()
        self.from_user = type("User", (), {"id": 222, "is_bot": False, "first_name": "Админ"})()
        self.ответы: list[str] = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)


def _переключить(текст, chat_id, стенд, monkeypatch):
    async def add_log(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.db, "add_log", add_log, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: True)
    msg = ФейкСообщение(текст, chat_id)
    asyncio.run(bot_module.cmd_shop_restock_notify_toggle(msg))
    return msg


def test_выключатель_пишет_настройку_рабочего_чата(стенд, monkeypatch):
    """Ключ должен быть по рабочему чату, а не по тому, откуда написали:
    читает настройку завоз именно для рабочего чата."""
    _переключить("-завоз", ЗАЯВКИ, стенд, monkeypatch)
    assert стенд["data"].get(bot_module._shop_restock_notify_key(ЖАЛОБЫ)) == "0"

    _завоз()
    assert стенд["личка"] == [], "выключатель обязан подействовать на сводку"


def test_включение_возвращает_сводку(стенд, monkeypatch):
    _переключить("-завоз", ЖАЛОБЫ, стенд, monkeypatch)
    _переключить("+завоз", ЖАЛОБЫ, стенд, monkeypatch)
    _завоз()
    assert len(стенд["личка"]) == 3
