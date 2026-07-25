"""Управление действиями «Предложить» текстовыми командами в личке боту —
по образцу rp_admin_command (bot.py)."""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from datetime import datetime

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

PRIV_CHAT = 555


def _make(text, user_id=555):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=PRIV_CHAT, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Админ"), text=text,
    )
    sent = []

    async def fake_answer(t, **kwargs):
        sent.append(t)

    async def fake_reply(t, **kwargs):
        sent.append(t)

    object.__setattr__(m, "answer", fake_answer)
    object.__setattr__(m, "reply", fake_reply)
    return m, sent


def _grant_senior(monkeypatch, user_id=555):
    monkeypatch.setattr(bot_module, "admin_levels", {user_id: bot_module.LEVEL_SENIOR})


def test_без_прав_молчит_если_не_админ(monkeypatch):
    monkeypatch.setattr(bot_module, "admin_levels", {})
    m, sent = _make("предложения список", user_id=999)
    asyncio.run(bot_module.propose_admin_command(m))
    assert not sent


def test_без_прав_объясняет_если_админ_но_ниже_уровня(monkeypatch):
    monkeypatch.setattr(bot_module, "admin_levels", {555: bot_module.LEVEL_MODERATOR})
    m, sent = _make("предложения список")
    asyncio.run(bot_module.propose_admin_command(m))
    assert sent and "Старший администратор" in sent[0]


def test_добавить_создаёт_действие_и_первую_фразу(monkeypatch):
    _grant_senior(monkeypatch)
    created = {}

    async def add_propose_phrase(action_key, kind, phrase):
        created.update(action_key=action_key, kind=kind, phrase=phrase)
        return 1

    monkeypatch.setattr(bot_module.db, "add_propose_phrase", add_propose_phrase)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения добавить турнир | {actor} вызывает {target} на турнир!")
    asyncio.run(bot_module.propose_admin_command(m))

    assert created == {"action_key": "турнир", "kind": "propose",
                        "phrase": "{actor} вызывает {target} на турнир!"}
    assert sent and "Фраза добавлена" in sent[0]


def test_фраза_добавляет_вид_согласие(monkeypatch):
    _grant_senior(monkeypatch)
    created = {}

    async def add_propose_phrase(action_key, kind, phrase):
        created.update(action_key=action_key, kind=kind, phrase=phrase)
        return 2

    monkeypatch.setattr(bot_module.db, "add_propose_phrase", add_propose_phrase)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения фраза турнир согласие | Есть контакт!")
    asyncio.run(bot_module.propose_admin_command(m))

    assert created == {"action_key": "турнир", "kind": "agree", "phrase": "Есть контакт!"}


def test_вкл_выкл(monkeypatch):
    _grant_senior(monkeypatch)
    calls = []

    async def set_propose_action_active(action_key, is_active):
        calls.append((action_key, is_active))
        return 1

    monkeypatch.setattr(bot_module.db, "set_propose_action_active", set_propose_action_active)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, _ = _make("предложения выкл романшка")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls == [("романшка", False)]


def test_кулдаун_и_таймаут(monkeypatch):
    """Команда меняет только одно из двух полей за раз (db.set_propose_action_settings
    делает частичный UPDATE) — обработчик не должен читать «текущее» значение
    второго поля из кэша, поэтому оба вызова проверяются независимо."""
    _grant_senior(monkeypatch)
    calls = []

    async def set_propose_action_settings(action_key, cooldown_seconds=None, timeout_seconds=None):
        calls.append((action_key, cooldown_seconds, timeout_seconds))
        return True

    monkeypatch.setattr(bot_module.db, "set_propose_action_settings", set_propose_action_settings)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения кулдаун romashka 600")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls[-1] == ("romashka", 600, None)

    m, sent = _make("предложения таймаут romashka 60")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls[-1] == ("romashka", None, 60)
