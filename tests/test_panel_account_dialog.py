"""Диалог «аккаунт» в личке боту — участник задаёт логин/пароль для входа на
сайт (вместо одноразового кода). Пароль хранится только как хэш (argon2) —
бот физически не может «напомнить» старый, только задать новый тем же
диалогом заново."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

PRIV_CHAT = 555


async def _async_noop(*args, **kwargs):
    return None


def _async_returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _make(text, user_id=555):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=PRIV_CHAT, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"), text=text,
    )
    sent = []
    deleted = []

    async def fake_answer(t, **kwargs):
        sent.append(t)

    async def fake_reply(t, **kwargs):
        sent.append(t)

    async def fake_delete():
        deleted.append(m.message_id)

    object.__setattr__(m, "answer", fake_answer)
    object.__setattr__(m, "reply", fake_reply)
    object.__setattr__(m, "delete", fake_delete)
    return m, sent, deleted


async def _fresh_state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=PRIV_CHAT, user_id=PRIV_CHAT)
    return FSMContext(storage=storage, key=key)


def test_уже_привязанный_персонал_получает_отказ(monkeypatch):
    async def get_panel_user_by_tg(tg_user_id):
        return {"id": 9, "role": "admin", "username": "boss", "tg_user_id": tg_user_id}

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", get_panel_user_by_tg)

    m, sent, _ = _make("аккаунт")
    state = asyncio.run(_fresh_state())
    asyncio.run(bot_module.cmd_panel_account_start(m, state))

    assert sent and "персонал" in sent[0].casefold()


def test_новый_участник_проходит_оба_шага(monkeypatch):
    async def get_panel_user_by_tg(tg_user_id):
        return None

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", get_panel_user_by_tg)
    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(False))

    calls = []

    async def upsert_panel_member_account(tg_user_id, username, password_hash, tg_full_name):
        calls.append((tg_user_id, username, password_hash, tg_full_name))
        return 42

    monkeypatch.setattr(bot_module.db, "upsert_panel_member_account", upsert_panel_member_account)

    state = asyncio.run(_fresh_state())

    m1, sent1, _ = _make("аккаунт")
    asyncio.run(bot_module.cmd_panel_account_start(m1, state))
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_username.state

    m2, sent2, _ = _make("новый_логин")
    asyncio.run(bot_module.panel_account_username_step(m2, state))
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_password.state
    data = asyncio.run(state.get_data())
    assert data["panel_account_username"] == "новый_логин"

    m3, sent3, deleted3 = _make("суперсекретныйпароль123")
    asyncio.run(bot_module.panel_account_password_step(m3, state))

    assert deleted3 == [m3.message_id]
    assert len(calls) == 1
    tg_user_id, username, password_hash, tg_full_name = calls[0]
    assert tg_user_id == 555 and username == "новый_логин"
    assert bot_module._panel_password_hasher.verify(password_hash, "суперсекретныйпароль123") is True
    assert asyncio.run(state.get_state()) is None
    assert sent3 and "готово" in sent3[-1].casefold()


def test_короткий_пароль_отклоняется_без_сохранения(monkeypatch):
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(False))

    saved = []

    async def upsert_panel_member_account(*a, **k):
        saved.append(a)
        return 1

    monkeypatch.setattr(bot_module.db, "upsert_panel_member_account", upsert_panel_member_account)

    state = asyncio.run(_fresh_state())
    asyncio.run(state.set_state(bot_module.PanelAccountStates.waiting_password))
    asyncio.run(state.update_data(panel_account_username="логин1"))

    m, sent, deleted = _make("123")
    asyncio.run(bot_module.panel_account_password_step(m, state))

    assert not saved
    assert deleted == [m.message_id]
    assert sent and "короче" in sent[-1].casefold()
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_password.state


def test_занятый_логин_просит_другой(monkeypatch):
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(True))

    state = asyncio.run(_fresh_state())
    asyncio.run(state.set_state(bot_module.PanelAccountStates.waiting_username))

    m, sent, _ = _make("занятый_логин")
    asyncio.run(bot_module.panel_account_username_step(m, state))

    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_username.state
    assert sent and "занят" in sent[-1].casefold()


def test_смена_логина_передаёт_exclude_user_id_текущего_аккаунта(monkeypatch):
    """Regression: без exclude_user_id участник, повторно вводящий СВОЙ ЖЕ
    текущий логин (например, чтобы просто сменить пароль), получал бы ложный
    отказ «логин уже занят» — is_username_taken_by_other обязан получить id
    его собственного аккаунта, чтобы тот исключался из проверки."""

    calls = []

    async def recording_is_username_taken_by_other(username, exclude_user_id=None):
        calls.append((username, exclude_user_id))
        return False

    monkeypatch.setattr(
        bot_module.db, "is_username_taken_by_other", recording_is_username_taken_by_other
    )

    # Сценарий 1: у участника уже есть аккаунт (id=77, логин «старый_логин»),
    # и он вводит тот же самый логин заново.
    async def get_panel_user_by_tg_existing(tg_user_id):
        return {"id": 77, "role": "member", "username": "старый_логин", "tg_user_id": tg_user_id}

    async def get_panel_member_by_tg_existing(tg_user_id):
        return {"id": 77, "username": "старый_логин", "tg_user_id": tg_user_id}

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", get_panel_user_by_tg_existing)
    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", get_panel_member_by_tg_existing)

    state = asyncio.run(_fresh_state())
    m1, sent1, _ = _make("аккаунт")
    asyncio.run(bot_module.cmd_panel_account_start(m1, state))
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_username.state

    m2, sent2, _ = _make("старый_логин")
    asyncio.run(bot_module.panel_account_username_step(m2, state))

    assert calls == [("старый_логин", 77)]
    # свой же логин не должен быть отклонён как «занят» — диалог продвинулся дальше
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_password.state

    # Сценарий 2: совершенно новый участник — аккаунта ещё нет вовсе.
    calls.clear()

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", _async_returns(None))

    state2 = asyncio.run(_fresh_state())
    m3, sent3, _ = _make("аккаунт")
    asyncio.run(bot_module.cmd_panel_account_start(m3, state2))

    m4, sent4, _ = _make("новый_логин_2")
    asyncio.run(bot_module.panel_account_username_step(m4, state2))

    assert calls == [("новый_логин_2", None)]


def test_мой_логин_напоминает_существующий(monkeypatch):
    async def get_panel_member_by_tg(tg_user_id):
        return {"id": 7, "username": "мой_логин_тут", "tg_user_id": tg_user_id}

    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", get_panel_member_by_tg)

    m, sent, _ = _make("мой логин")
    asyncio.run(bot_module.cmd_my_panel_login(m))

    assert sent and "мой_логин_тут" in sent[0]


def test_мой_логин_без_аккаунта(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", _async_returns(None))

    m, sent, _ = _make("мой логин")
    asyncio.run(bot_module.cmd_my_panel_login(m))

    assert sent and "аккаунт" in sent[0].casefold()
