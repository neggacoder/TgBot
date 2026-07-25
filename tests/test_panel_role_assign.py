"""Выдача и освобождение роли из панели.

POST /api/chat-roles/{id}/assign   — закрепить роль за участником
POST /api/chat-roles/{id}/release  — освободить роль

Панель повторяет поведение бота («роль отдать» / «роль снять»), с одним
уточнением: человека, которого сейчас нет в группе, назначать держателем
бессмысленно — за ним роль бронируют, как и при одобрении заявки.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
ROLE_ID = 3
USER_ID = 100


class FakeBot:
    def __init__(self):
        self.sent = []
        self.absent = set()

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})

    async def get_chat_member(self, chat_id, user_id):
        if user_id in self.absent:
            raise RuntimeError("user not found")
        return type("M", (), {"status": "member"})()


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "role": {
            "id": ROLE_ID, "chat_id": CHAT_ID, "name": "Мисато Кацураги",
            "category": "NERV", "status": "free", "approved": 1,
            "holder_user_id": None, "reserved_user_id": None,
        },
        "given": [], "reserved": [], "released": [], "logs": [],
    }
    bot = FakeBot()

    async def get_role(chat_id, role_id):
        role = state["role"]
        return dict(role) if role["id"] == role_id else None

    async def force_set_role(chat_id, role_id, user_id):
        state["given"].append((role_id, user_id))
        return True

    async def force_reserve_role(chat_id, role_id, user_id):
        state["reserved"].append((role_id, user_id))
        return True

    async def release_role(chat_id, role_id):
        state["released"].append(role_id)
        return True

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "get_role", get_role)
    monkeypatch.setattr(db, "force_set_role", force_set_role)
    monkeypatch.setattr(db, "force_reserve_role", force_reserve_role)
    monkeypatch.setattr(db, "release_role", release_role)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel, "get_bot", lambda: bot)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.state = state
    client.bot = bot
    yield client
    panel.app.dependency_overrides.clear()


def assign(client, user_id=USER_ID, role_id=ROLE_ID):
    return client.post(
        f"/api/chat-roles/{role_id}/assign",
        json={"chat_id": CHAT_ID, "user_id": user_id},
    )


def release(client, role_id=ROLE_ID):
    return client.post(f"/api/chat-roles/{role_id}/release", json={"chat_id": CHAT_ID})


# ---------------------------------------------------------------------------
# Выдача
# ---------------------------------------------------------------------------

def test_роль_закрепляется_за_участником(panel_client):
    res = assign(panel_client)
    assert res.status_code == 200, res.text
    assert panel_client.state["given"] == [(ROLE_ID, USER_ID)]
    assert res.json()["reserved"] is False


def test_отсутствующему_в_чате_роль_бронируется(panel_client):
    """Держателем можно быть только находясь в группе. Человека, которого там
    нет, ставим в бронь — как это делает бот и как уже сделано при одобрении
    заявки."""
    panel_client.bot.absent.add(USER_ID)
    res = assign(panel_client)
    assert res.status_code == 200
    assert panel_client.state["reserved"] == [(ROLE_ID, USER_ID)]
    assert panel_client.state["given"] == []
    assert res.json()["reserved"] is True


def test_получатель_узнаёт_о_роли(panel_client):
    assign(panel_client)
    assert any(m["chat_id"] == USER_ID and "Мисато" in m["text"] for m in panel_client.bot.sent)


def test_закрытая_личка_не_отменяет_выдачу(panel_client, monkeypatch):
    async def boom(chat_id, text, **kwargs):
        raise RuntimeError("bot was blocked by the user")
    monkeypatch.setattr(panel_client.bot, "send_message", boom)
    assert assign(panel_client).status_code == 200
    assert panel_client.state["given"] == [(ROLE_ID, USER_ID)]


def test_выдача_пишется_в_журнал(panel_client):
    assign(panel_client)
    assert "role_force_give" in panel_client.state["logs"]


def test_несуществующая_роль(panel_client):
    assert assign(panel_client, role_id=999).status_code == 404


def test_заявку_на_модерации_выдать_нельзя(panel_client):
    """Роль ещё не одобрена — её нет в списке чата, и держателя у неё быть не
    может."""
    panel_client.state["role"]["approved"] = 0
    assert assign(panel_client).status_code == 409


# ---------------------------------------------------------------------------
# Освобождение
# ---------------------------------------------------------------------------

def test_роль_освобождается(panel_client):
    panel_client.state["role"].update(status="taken", holder_user_id=USER_ID)
    res = release(panel_client)
    assert res.status_code == 200, res.text
    assert panel_client.state["released"] == [ROLE_ID]


def test_бывшему_держателю_сообщают(panel_client):
    panel_client.state["role"].update(status="taken", holder_user_id=USER_ID)
    release(panel_client)
    assert any(m["chat_id"] == USER_ID for m in panel_client.bot.sent)


def test_свободную_роль_освобождать_нечего(panel_client):
    assert release(panel_client).status_code == 409


def test_освобождение_пишется_в_журнал(panel_client):
    panel_client.state["role"].update(status="taken", holder_user_id=USER_ID)
    release(panel_client)
    assert "role_force_take" in panel_client.state["logs"]
