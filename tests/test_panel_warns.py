"""Варны в панели: список, выдача, снятие.

Главное требование — совпадать с ботом. Варн ведёт к автобану при достижении
лимита, и если панель выдаст варн «мимо» этой логики, человек наберёт три
предупреждения и останется в чате, а модератор будет думать, что бан случился.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
USER_ID = 777


class FakeBot:
    def __init__(self):
        self.banned, self.sent = [], []

    async def ban_chat_member(self, chat_id, user_id, **kwargs):
        self.banned.append((chat_id, user_id))

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture
def panel_client(monkeypatch):
    state = {"warns": [], "count": 0, "cleared": 0, "bans": [], "logs": [], "unmuted": 0,
             "settings": {"warn_limit": 3}}
    bot = FakeBot()

    async def add_warn(chat_id, user_id, warned_by, reason, expires_at=None):
        state["warns"].append({
            "id": len(state["warns"]) + 1, "warned_by": warned_by, "reason": reason,
            "created_at": datetime(2026, 7, 20, 12, 0), "expires_at": expires_at,
        })
        state["count"] += 1
        return state["count"]

    async def count_warns(chat_id, user_id):
        return state["count"]

    async def list_warns(chat_id, user_id):
        return [dict(w) for w in state["warns"]]

    async def remove_last_warn(chat_id, user_id):
        if not state["warns"]:
            return False
        state["warns"].pop()
        state["count"] -= 1
        return True

    async def clear_warns(chat_id, user_id):
        state["cleared"] += 1
        state["warns"].clear()
        state["count"] = 0
        return 1

    async def add_ban(chat_id, user_id, banned_by, reason):
        state["bans"].append({"user_id": user_id, "reason": reason})

    async def remove_mute(chat_id, user_id):
        state["unmuted"] += 1

    async def fetch_settings():
        return dict(state["settings"])

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("add_warn", add_warn), ("count_warns", count_warns), ("list_warns", list_warns),
        ("remove_last_warn", remove_last_warn), ("clear_warns", clear_warns),
        ("add_ban", add_ban), ("remove_mute", remove_mute),
        ("fetch_settings", fetch_settings), ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn)

    monkeypatch.setattr(panel, "get_bot", lambda: bot)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.state = state
    client.bot = bot
    yield client
    panel.app.dependency_overrides.clear()


def give(client, days=7, reason="спам"):
    return client.post("/api/warns", json={
        "chat_id": CHAT_ID, "user_id": USER_ID, "days": days, "reason": reason,
    })


def unwarn(client):
    return client.post("/api/warns/remove", json={"chat_id": CHAT_ID, "user_id": USER_ID})


def listing(client):
    return client.get("/api/warns", params={"chat_id": CHAT_ID, "user_id": USER_ID})


# ---------------------------------------------------------------------------
# Выдача
# ---------------------------------------------------------------------------

def test_варн_выдаётся(panel_client):
    res = give(panel_client)
    assert res.status_code == 200, res.text
    assert res.json()["count"] == 1
    assert panel_client.state["warns"][0]["reason"] == "спам"


def test_срок_считается_от_сейчас(panel_client):
    give(panel_client, days=3)
    expires = panel_client.state["warns"][0]["expires_at"]
    assert expires is not None
    assert timedelta(days=2, hours=23) < (expires - datetime.utcnow()) < timedelta(days=3, hours=1)


def test_срок_по_умолчанию_семь_дней(panel_client):
    give(panel_client, days=None)
    expires = panel_client.state["warns"][0]["expires_at"]
    assert timedelta(days=6, hours=23) < (expires - datetime.utcnow()) < timedelta(days=7, hours=1)


def test_автор_варна_не_подделывает_telegram_id(panel_client):
    """warned_by — Telegram-ID. У панельной учётки его нет, и чужой ID туда
    писать нельзя: он указал бы на постороннего человека."""
    give(panel_client)
    assert panel_client.state["warns"][0]["warned_by"] == 0


def test_выдача_пишется_в_журнал(panel_client):
    give(panel_client)
    assert "warn" in panel_client.state["logs"]


# ---------------------------------------------------------------------------
# Лимит и автобан — то же, что делает бот
# ---------------------------------------------------------------------------

def test_на_лимите_человек_банится(panel_client):
    give(panel_client); give(panel_client)
    assert panel_client.bot.banned == []
    res = give(panel_client)
    assert res.json()["banned"] is True
    assert panel_client.bot.banned == [(CHAT_ID, USER_ID)]


def test_после_автобана_варны_сбрасываются(panel_client):
    give(panel_client); give(panel_client); give(panel_client)
    assert panel_client.state["cleared"] == 1
    assert panel_client.state["count"] == 0


def test_бан_записывается_и_мут_снимается(panel_client):
    """Бот при автобане снимает мут и заводит запись о бане — иначе человек
    остаётся и в мутах, и в банах одновременно."""
    give(panel_client); give(panel_client); give(panel_client)
    assert panel_client.state["bans"][0]["user_id"] == USER_ID
    assert panel_client.state["unmuted"] == 1


def test_лимит_берётся_из_настроек(panel_client):
    panel_client.state["settings"]["warn_limit"] = 2
    give(panel_client)
    assert give(panel_client).json()["banned"] is True


def test_неудачный_бан_не_прячется(panel_client, monkeypatch):
    """Если у бота нет прав на бан, модератор должен об этом узнать: варн
    выдан, а наказание — нет."""
    async def boom(chat_id, user_id, **kwargs):
        raise RuntimeError("not enough rights")
    monkeypatch.setattr(panel_client.bot, "ban_chat_member", boom)
    panel_client.state["settings"]["warn_limit"] = 1
    res = give(panel_client)
    assert res.status_code == 200
    assert res.json()["banned"] is False
    assert "ban_error" in res.json()


# ---------------------------------------------------------------------------
# Список и снятие
# ---------------------------------------------------------------------------

def test_список_варнов(panel_client):
    give(panel_client, reason="флуд")
    data = listing(panel_client).json()
    assert data["count"] == 1 and data["limit"] == 3
    assert data["warns"][0]["reason"] == "флуд"


def test_снятие_последнего(panel_client):
    give(panel_client); give(panel_client)
    assert unwarn(panel_client).status_code == 200
    assert panel_client.state["count"] == 1


def test_снимать_нечего(panel_client):
    assert unwarn(panel_client).status_code == 409
