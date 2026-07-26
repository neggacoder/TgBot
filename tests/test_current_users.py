"""known_users/current_users — «нью» больше не путает вернувшегося участника
с новым.

known_users никогда не чистится при выходе (стаж/новизна). current_users —
новая таблица «кто сейчас в чате»: заполняется при активности, чистится при
выходе. Тесты проверяют именно места стыковки — что нужные функции
вызываются с нужными аргументами, а НЕ полное поведение хендлеров (оно уже
покрыто существовавшим до этой фичи кодом и не меняется).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from types import SimpleNamespace

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


async def _async_noop(*args, **kwargs):
    return None


def _async_returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _make(text, chat_type="supergroup"):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type=chat_type),
        from_user=User(id=555, is_bot=False, first_name="Тестер"), text=text,
    )
    sent = []

    async def fake_reply(t, **kwargs):
        sent.append(t)

    object.__setattr__(m, "reply", fake_reply)
    return m, sent


def test_вступление_заносит_в_current_users(monkeypatch):
    monkeypatch.setattr(bot_module, "_member_events_seen", {})
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "resolve_reservations_on_join", _async_returns([]))
    monkeypatch.setattr(bot_module, "group_join_text", lambda: None)
    monkeypatch.setattr(bot_module, "is_join_notify_enabled", _async_returns(False))
    monkeypatch.setattr(bot_module, "prompt_role_pick_after_join", _async_noop)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    user = User(id=555, is_bot=False, first_name="Тестер")
    asyncio.run(bot_module.handle_member_joined(CHAT_ID, user, inviter_id=None))

    assert calls == [(CHAT_ID, 555, "Тестер", None)]


def test_выход_чистит_current_users_а_не_known_users(monkeypatch):
    """Регрессионный тест на сам баг: known_users больше не должна трогаться
    при выходе — иначе first_seen_at снова будет теряться при возврате."""
    monkeypatch.setattr(bot_module, "_member_events_seen", {})
    monkeypatch.setattr(bot_module, "is_leave_notify_enabled", _async_returns(False))
    monkeypatch.setattr(bot_module.db, "delete_call_data", _async_noop)
    monkeypatch.setattr(bot_module.db, "delete_subscriptions_of_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "delete_reputation_of_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "release_role_by_holder", _async_returns(None))

    known_user_calls = []

    async def delete_known_user(chat_id, user_id):
        known_user_calls.append((chat_id, user_id))

    current_user_calls = []

    async def delete_current_user(chat_id, user_id):
        current_user_calls.append((chat_id, user_id))

    monkeypatch.setattr(bot_module.db, "delete_known_user", delete_known_user)
    monkeypatch.setattr(bot_module.db, "delete_current_user", delete_current_user)

    user = User(id=555, is_bot=False, first_name="Тестер")
    asyncio.run(bot_module.handle_member_left(CHAT_ID, user))

    assert current_user_calls == [(CHAT_ID, 555)]
    assert known_user_calls == []


def test_сообщение_заносит_в_current_users(monkeypatch):
    monkeypatch.setattr(bot_module.db, "increment_message_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "increment_daily_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "increment_hourly_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "clear_unreg", _async_noop)
    monkeypatch.setattr(bot_module, "check_message_achievements", _async_noop)
    monkeypatch.setattr(bot_module, "_remember_recent_message", _async_noop)
    monkeypatch.setattr(bot_module, "RSTICK_CHANCE", 0.0)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    message, _ = _make("привет")

    async def next_handler(event, data):
        return "ok"

    mw = bot_module.MessageCounterMiddleware()
    result = asyncio.run(mw(next_handler, message, {}))

    assert result == "ok"
    assert calls == [(CHAT_ID, 555, "Тестер", None)]


def test_синхронизация_админов_заносит_в_current_users(monkeypatch):
    admin_user = User(id=777, is_bot=False, first_name="Админ")

    class FakeMember:
        def __init__(self, user):
            self.user = user

    class FakeBot:
        async def get_chat_administrators(self, chat_id):
            return [FakeMember(admin_user)]

    monkeypatch.setattr(bot_module, "bot", FakeBot())
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    asyncio.run(bot_module.sync_known_admins(CHAT_ID))

    assert calls == [(CHAT_ID, 777, "Админ", None)]


def test_участники_без_ролей_читает_current_users(monkeypatch):
    monkeypatch.setattr(bot_module, "roles_context_chat_id", _async_returns(CHAT_ID))

    calls = []

    async def list_current_users_without_role(chat_id, limit=50, offset=0):
        calls.append((chat_id, limit))
        return [{"user_id": 42, "full_name": "Тест", "username": None}], 1

    monkeypatch.setattr(bot_module.db, "list_current_users_without_role", list_current_users_without_role)

    # Команда сверяет каждого через get_chat_member. Без подмены тест уходил бы
    # в настоящий api.telegram.org с тестовым токеном и падал Unauthorized.
    async def get_chat_member(chat_id, user_id):
        return SimpleNamespace(status="member")

    monkeypatch.setattr(bot_module.bot, "get_chat_member", get_chat_member)

    message, sent = _make("участники без ролей")
    asyncio.run(bot_module.cmd_members_without_role(message))

    assert calls == [(CHAT_ID, bot_module.ROSTER_LIST_LIMIT)]
    assert sent and "Тест" in sent[0]
