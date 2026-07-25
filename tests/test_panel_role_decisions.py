"""Решения по заявкам на роль из панели (POST /api/chat-roles/{id}/decision).

Заявку можно принять или отклонить и в чате кнопками, и в панели. Главное
требование к панельному пути: решение должно доехать обратно в чат — карточку
с кнопками надо отредактировать. Иначе второй администратор нажмёт «Принять»
по заявке, которую только что закрыли из панели, и получит невнятную ошибку.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
NOTIFY_CHAT = -1009999999999
ROLE_ID = 7
PROPOSER = 555
MESSAGE_ID = 4242


class FakeBot:
    """Телеграм в тестах не поднимаем — записываем, что панель попыталась
    сделать, и этого достаточно: важно, что она правит нужное сообщение и
    пишет автору заявки."""

    def __init__(self):
        self.edited = []
        self.sent = []
        self.members = {}

    async def edit_message_text(self, **kwargs):
        self.edited.append(kwargs)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})

    async def get_chat_member(self, chat_id, user_id):
        status = self.members.get(user_id, "member")
        if status == "left":
            raise RuntimeError("user not found")
        return type("M", (), {"status": status})()


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "role": {
            "id": ROLE_ID, "chat_id": CHAT_ID, "name": "Аска Лэнгли", "category": "Пилоты",
            "status": "free", "approved": 0, "proposed_by": PROPOSER,
            "proposal_chat_id": NOTIFY_CHAT, "proposal_message_id": MESSAGE_ID,
        },
        "approved": [], "rejected": [], "reserved": [], "logs": [],
    }
    bot = FakeBot()

    async def get_role(chat_id, role_id):
        role = state["role"]
        return dict(role) if role and role["id"] == role_id else None

    async def approve_role_proposal(chat_id, role_id):
        if not state["role"] or state["role"]["approved"]:
            return None
        state["role"]["approved"] = 1
        state["approved"].append(role_id)
        return dict(state["role"])

    async def reject_role_proposal(chat_id, role_id):
        if not state["role"] or state["role"]["approved"]:
            return False
        state["role"] = None
        state["rejected"].append(role_id)
        return True

    async def reserve_role(chat_id, role_id, user_id):
        state["reserved"].append((role_id, user_id))
        return True

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "get_role", get_role)
    monkeypatch.setattr(db, "approve_role_proposal", approve_role_proposal)
    monkeypatch.setattr(db, "reject_role_proposal", reject_role_proposal)
    monkeypatch.setattr(db, "reserve_role", reserve_role)
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


def decide(client, approve=True, role_id=ROLE_ID):
    return client.post(
        f"/api/chat-roles/{role_id}/decision",
        json={"chat_id": CHAT_ID, "approve": approve},
    )


# ---------------------------------------------------------------------------
# Одобрение
# ---------------------------------------------------------------------------

def test_заявка_одобряется(panel_client):
    res = decide(panel_client)
    assert res.status_code == 200, res.text
    assert panel_client.state["approved"] == [ROLE_ID]


def test_карточка_в_чате_правится(panel_client):
    """То самое, ради чего всё затевалось: в чате сообщение с кнопками должно
    смениться отметкой о решении."""
    decide(panel_client)
    assert len(panel_client.bot.edited) == 1
    edit = panel_client.bot.edited[0]
    assert edit["chat_id"] == NOTIFY_CHAT
    assert edit["message_id"] == MESSAGE_ID
    assert "Принято" in edit["text"]
    assert edit["reply_markup"] is None  # кнопки убраны, повторно не нажать


def test_автор_заявки_получает_уведомление(panel_client):
    decide(panel_client)
    assert any(m["chat_id"] == PROPOSER and "одобрена" in m["text"] for m in panel_client.bot.sent)


def test_роль_бронируется_если_автора_нет_в_чате(panel_client):
    """Как и в боте: автор ещё не в группе — роль держим за ним, а не отдаём
    первому желающему."""
    panel_client.bot.members[PROPOSER] = "left"
    decide(panel_client)
    assert panel_client.state["reserved"] == [(ROLE_ID, PROPOSER)]


def test_роль_не_бронируется_если_автор_в_чате(panel_client):
    decide(panel_client)
    assert panel_client.state["reserved"] == []


# ---------------------------------------------------------------------------
# Отклонение
# ---------------------------------------------------------------------------

def test_заявка_отклоняется(panel_client):
    res = decide(panel_client, approve=False)
    assert res.status_code == 200, res.text
    assert panel_client.state["rejected"] == [ROLE_ID]


def test_при_отклонении_карточка_тоже_правится(panel_client):
    decide(panel_client, approve=False)
    edit = panel_client.bot.edited[0]
    assert "Отклонено" in edit["text"]
    assert edit["reply_markup"] is None


def test_автору_сообщают_об_отказе(panel_client):
    decide(panel_client, approve=False)
    assert any(m["chat_id"] == PROPOSER and "отклонена" in m["text"] for m in panel_client.bot.sent)


# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------

def test_повторное_решение_отвергается(panel_client):
    assert decide(panel_client).status_code == 200
    assert decide(panel_client).status_code == 409


def test_несуществующая_заявка(panel_client):
    assert decide(panel_client, role_id=999).status_code == 404


def test_недоступное_сообщение_не_ломает_решение(panel_client, monkeypatch):
    """Карточку могли удалить из чата руками. Заявка всё равно должна
    закрыться: решение важнее, чем отметка о нём."""
    async def boom(**kwargs):
        raise RuntimeError("message to edit not found")
    monkeypatch.setattr(panel_client.bot, "edit_message_text", boom)
    res = decide(panel_client)
    assert res.status_code == 200
    assert panel_client.state["approved"] == [ROLE_ID]


def test_решение_пишется_в_журнал(panel_client):
    decide(panel_client)
    assert "role_approve" in panel_client.state["logs"]
