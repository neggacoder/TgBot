"""Заявки на рест в панели: список и решение.

Решение обязано доезжать до чата — бот отправлял карточку с кнопками, и её
надо закрыть. Иначе второй администратор нажмёт «Одобрить» по уже
обработанной заявке.
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
NOTIFY_CHAT = -1009999999999
REQ_ID = 5
USER_ID = 777
MESSAGE_ID = 321
REQUESTED_AT = datetime(2026, 7, 20, 9, 0)
EXPIRES_AT = datetime(2026, 7, 27, 9, 0)


class FakeBot:
    def __init__(self):
        self.edited, self.sent = [], []

    async def edit_message_text(self, **kwargs):
        self.edited.append(kwargs)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "row": {
            "id": REQ_ID, "chat_id": CHAT_ID, "user_id": USER_ID,
            "duration_seconds": 7 * 24 * 3600, "reason": "сессия",
            "status": "pending", "requested_at": REQUESTED_AT, "expires_at": None,
            "notice_chat_id": NOTIFY_CHAT, "notice_message_id": MESSAGE_ID,
            "full_name": "Паша", "username": "pasha",
        },
        "logs": [],
    }
    bot = FakeBot()

    async def list_pending_rest_requests(chat_id, limit=50):
        return [dict(state["row"])] if state["row"]["status"] == "pending" else []

    async def get_rest_request(request_id):
        return dict(state["row"]) if request_id == REQ_ID else None

    async def approve_rest_request(request_id, admin_id):
        if state["row"]["status"] != "pending":
            return None
        state["row"].update(status="approved", expires_at=EXPIRES_AT, decided_by=admin_id)
        return dict(state["row"])

    async def reject_rest_request(request_id, admin_id):
        if state["row"]["status"] != "pending":
            return None
        state["row"].update(status="rejected", decided_by=admin_id)
        return dict(state["row"])

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "list_pending_rest_requests", list_pending_rest_requests, raising=False)
    monkeypatch.setattr(db, "get_rest_request", get_rest_request)
    monkeypatch.setattr(db, "approve_rest_request", approve_rest_request)
    monkeypatch.setattr(db, "reject_rest_request", reject_rest_request)
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


def decide(client, approve=True, request_id=REQ_ID):
    return client.post(f"/api/rest-requests/{request_id}/decision", json={"approve": approve})


# ---------------------------------------------------------------------------
# Список
# ---------------------------------------------------------------------------

def test_список_заявок(panel_client):
    res = panel_client.get("/api/rest-requests", params={"chat_id": CHAT_ID})
    assert res.status_code == 200, res.text
    item = res.json()["requests"][0]
    assert item["full_name"] == "Паша"
    assert item["reason"] == "сессия"
    assert item["duration_seconds"] == 7 * 24 * 3600


def test_обработанные_заявки_в_списке_не_висят(panel_client):
    decide(panel_client)
    res = panel_client.get("/api/rest-requests", params={"chat_id": CHAT_ID})
    assert res.json()["requests"] == []


# ---------------------------------------------------------------------------
# Решение
# ---------------------------------------------------------------------------

def test_заявка_одобряется(panel_client):
    assert decide(panel_client).status_code == 200
    assert panel_client.state["row"]["status"] == "approved"


def test_карточка_в_чате_закрывается(panel_client):
    decide(panel_client)
    edit = panel_client.bot.edited[0]
    assert edit["chat_id"] == NOTIFY_CHAT and edit["message_id"] == MESSAGE_ID
    assert "Одобрено" in edit["text"]
    assert edit["reply_markup"] is None


def test_в_решении_видна_дата_окончания(panel_client):
    """Админ должен видеть, до какого числа человек в ресте, — иначе решение
    выглядит бессрочным."""
    decide(panel_client)
    assert "27.07.2026" in panel_client.bot.edited[0]["text"]


def test_заявитель_получает_уведомление(panel_client):
    decide(panel_client)
    assert any(m["chat_id"] == USER_ID and "одобрена" in m["text"] for m in panel_client.bot.sent)


def test_отклонение(panel_client):
    assert decide(panel_client, approve=False).status_code == 200
    assert panel_client.state["row"]["status"] == "rejected"
    assert "Отклонено" in panel_client.bot.edited[0]["text"]
    assert any("отклонена" in m["text"] for m in panel_client.bot.sent)


def test_повторное_решение_отвергается(panel_client):
    assert decide(panel_client).status_code == 200
    assert decide(panel_client).status_code == 409


def test_несуществующая_заявка(panel_client):
    assert decide(panel_client, request_id=999).status_code == 404


def test_недоступная_карточка_не_отменяет_решение(panel_client, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("message to edit not found")
    monkeypatch.setattr(panel_client.bot, "edit_message_text", boom)
    assert decide(panel_client).status_code == 200
    assert panel_client.state["row"]["status"] == "approved"


def test_решение_пишется_в_журнал(panel_client):
    decide(panel_client)
    assert "rest_approved" in panel_client.state["logs"]
