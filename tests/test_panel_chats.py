"""GET /api/chats: список чатов для выпадающего списка в панели.

Счётчик участников должен браться из current_users (актуальный состав), а
не known_users (кого бот видел когда-либо) — иначе после разделения
known_users/current_users он бы только рос и расходился с реальностью.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_A = -1001111111111
CHAT_B = -1002222222222


@pytest.fixture
def panel_client(monkeypatch):
    async def list_current_chats():
        return [
            {"chat_id": CHAT_A, "members": 42, "last_seen": "2026-07-24 10:00:00"},
            {"chat_id": CHAT_B, "members": 7, "last_seen": "2026-07-23 09:00:00"},
        ]

    monkeypatch.setattr(db, "list_current_chats", list_current_chats)

    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="tester", role="owner"
    )
    yield TestClient(panel.app)
    panel.app.dependency_overrides.clear()


def test_api_chats_reads_current_users_not_known_users(panel_client):
    """Данные приходят из db.list_current_chats (current_users), не
    db.list_known_chats (known_users), и форма ответа соответствует контракту
    панели. Бот не инициализирован в тесте, поэтому get_bot() падает и
    заголовок чата естественно уходит в резервную ветку "(недоступен)"."""
    res = panel_client.get("/api/chats")
    assert res.status_code == 200, res.text
    chats = res.json()["chats"]

    assert [c["chat_id"] for c in chats] == [CHAT_A, CHAT_B]
    assert [c["members"] for c in chats] == [42, 7]
    assert [c["last_seen"] for c in chats] == ["2026-07-24 10:00:00", "2026-07-23 09:00:00"]
    assert all(c["title"] == f"{c['chat_id']} (недоступен)" for c in chats)


def test_api_chats_does_not_use_list_known_chats(panel_client, monkeypatch):
    """Явная защита от регрессии: если api_chats снова начнёт звать
    known_users вместо current_users, этот тест упадёт."""

    async def boom():
        raise AssertionError("api_chats не должен звать db.list_known_chats")

    monkeypatch.setattr(db, "list_known_chats", boom)

    res = panel_client.get("/api/chats")
    assert res.status_code == 200, res.text
