"""Приписка «рест» в теге участника и её снятие.

Баг, ради которого файл заведён: у НАСТОЯЩЕГО администратора (владельца,
например) приписка «рест» оставалась в теге навсегда. Причина — не в самой
подписи, а в том, кого перебирал цикл снятия: он ходил только по ключам
roletag:, а их бот пишет лишь тогда, когда сам выдал человеку админку ради
тега. Настоящему админу бот админку не выдаёт — только меняет подпись, —
и в переборе такой человек не появлялся ни разу.
"""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


# --- сама подпись ----------------------------------------------------------

def test_приписка_добавляется_и_убирается():
    assert bot_module._build_role_title("Модератор", is_resting=True).endswith(" рест")
    assert bot_module._build_role_title("Модератор", is_resting=False) == "Модератор"


def test_подпись_влезает_в_лимит_телеграма():
    """custom_title у Telegram — максимум 16 символов. Длинная роль вместе
    с припиской обязана обрезаться, иначе API отвергнет запрос целиком."""
    title = bot_module._build_role_title("ОченьДлинноеНазваниеРоли", is_resting=True)
    assert len(title) <= 16
    assert title.endswith(" рест")


# --- отметка о том, что приписка стоит -------------------------------------

@pytest.fixture
def store(monkeypatch):
    """Ключ-значение в памяти + подменённый Telegram."""
    state = {"data": {}, "titles": [], "promoted": []}

    async def set_data(key, value, updated_by=None):
        state["data"][key] = value

    async def get_data(key):
        return {"data_value": state["data"][key]} if key in state["data"] else None

    async def delete_data(key):
        state["data"].pop(key, None)

    async def list_data_by_prefix(prefix):
        return [{"data_key": k, "data_value": v}
                for k, v in state["data"].items() if k.startswith(prefix)]

    async def set_title(chat_id, user_id, title):
        state["titles"].append(title)

    async def promote(chat_id, user_id, **kw):
        state["promoted"].append(user_id)

    monkeypatch.setattr(bot_module.db, "set_data", set_data, raising=False)
    monkeypatch.setattr(bot_module.db, "get_data", get_data, raising=False)
    monkeypatch.setattr(bot_module.db, "delete_data", delete_data, raising=False)
    monkeypatch.setattr(bot_module.db, "list_data_by_prefix", list_data_by_prefix, raising=False)
    monkeypatch.setattr(bot_module.bot, "set_chat_administrator_custom_title",
                        set_title, raising=False)
    monkeypatch.setattr(bot_module.bot, "promote_chat_member", promote, raising=False)
    monkeypatch.setattr(bot_module.db, "get_user_role",
                        _returns({"name": "Модератор"}), raising=False)
    return state


def _member(status):
    return type("M", (), {"status": status})()


def test_настоящему_админу_ставится_отметка_о_приписке(store, monkeypatch):
    """Сердце бага: без этой отметки цикл снятия человека не найдёт."""
    monkeypatch.setattr(bot_module.bot, "get_chat_member",
                        _returns(_member("administrator")), raising=False)
    monkeypatch.setattr(bot_module.db, "get_active_rest",
                        _returns({"id": 1}), raising=False)

    asyncio.run(bot_module.sync_role_title(CHAT_ID, USER_ID))
    assert store["titles"][-1].endswith(" рест")
    assert bot_module._rest_tag_flag_key(CHAT_ID, USER_ID) in store["data"]


def test_после_реста_приписка_снимается_у_настоящего_админа(store, monkeypatch):
    monkeypatch.setattr(bot_module.bot, "get_chat_member",
                        _returns(_member("administrator")), raising=False)
    monkeypatch.setattr(bot_module.db, "get_active_rest", _returns(None), raising=False)
    store["data"][bot_module._rest_tag_flag_key(CHAT_ID, USER_ID)] = "1"

    asyncio.run(bot_module.sync_role_title(CHAT_ID, USER_ID))
    assert store["titles"][-1] == "Модератор", "приписка обязана уйти"
    assert bot_module._rest_tag_flag_key(CHAT_ID, USER_ID) not in store["data"]


def test_настоящего_админа_не_разжалуют(store, monkeypatch):
    """Отметка о приписке НЕ должна превращаться в право снять человеку
    админку: roletag ставится только когда админку выдал сам бот."""
    monkeypatch.setattr(bot_module.bot, "get_chat_member",
                        _returns(_member("administrator")), raising=False)
    monkeypatch.setattr(bot_module.db, "get_active_rest", _returns(None), raising=False)
    asyncio.run(bot_module.sync_role_title(CHAT_ID, USER_ID))
    assert store["promoted"] == [], "настоящему админу права трогать нельзя"
    assert bot_module._role_tag_flag_key(CHAT_ID, USER_ID) not in store["data"]


def test_цикл_видит_тех_кому_бот_админку_не_выдавал(store, monkeypatch):
    """Проверка ровно того, что было сломано: человек есть только в resttag —
    и цикл обязан до него дойти."""
    store["data"][bot_module._rest_tag_flag_key(CHAT_ID, USER_ID)] = "1"
    monkeypatch.setattr(bot_module.db, "get_active_rest", _returns(None), raising=False)

    visited: list = []

    async def fake_sync(chat_id, user_id):
        visited.append((chat_id, user_id))

    monkeypatch.setattr(bot_module, "sync_role_title", fake_sync, raising=False)

    async def run_once():
        # одна итерация цикла: сам цикл бесконечный, поэтому дёргаем его тело
        rows = (await bot_module.db.list_data_by_prefix("roletag:")) + \
               (await bot_module.db.list_data_by_prefix("resttag:"))
        seen = set()
        for row in rows:
            _, c, u = row["data_key"].split(":")
            key = (int(c), int(u))
            if key in seen:
                continue
            seen.add(key)
            if not await bot_module.db.get_active_rest(*key):
                await bot_module.sync_role_title(*key)

    asyncio.run(run_once())
    assert visited == [(CHAT_ID, USER_ID)]


def test_человек_в_обоих_наборах_обрабатывается_один_раз(store, monkeypatch):
    """roletag и resttag могут указывать на одного человека — лишний поход
    в Telegram за тем же тегом не нужен."""
    store["data"][bot_module._role_tag_flag_key(CHAT_ID, USER_ID)] = "1"
    store["data"][bot_module._rest_tag_flag_key(CHAT_ID, USER_ID)] = "1"
    monkeypatch.setattr(bot_module.db, "get_active_rest", _returns(None), raising=False)

    visited: list = []

    async def fake_sync(chat_id, user_id):
        visited.append((chat_id, user_id))

    monkeypatch.setattr(bot_module, "sync_role_title", fake_sync, raising=False)

    async def run_once():
        rows = (await bot_module.db.list_data_by_prefix("roletag:")) + \
               (await bot_module.db.list_data_by_prefix("resttag:"))
        seen = set()
        for row in rows:
            _, c, u = row["data_key"].split(":")
            key = (int(c), int(u))
            if key in seen:
                continue
            seen.add(key)
            if not await bot_module.db.get_active_rest(*key):
                await bot_module.sync_role_title(*key)

    asyncio.run(run_once())
    assert visited == [(CHAT_ID, USER_ID)], "обработать нужно один раз"
