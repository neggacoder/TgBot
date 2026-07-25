"""Жалобы в панели.

Главное здесь — анонимность. Если человек пожаловался анонимно, панель не
просто прячет его имя в вёрстке, а вообще не отдаёт reporter_id с сервера:
иначе он виден в сетевых запросах браузера, и обещание анонимности оказывается
ложным.
"""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

TARGET_ID = 300
OPEN_REPORTER = 100
ANON_REPORTER = 200

COMPLAINTS = [
    {"id": 1, "target_id": TARGET_ID, "reporter_id": OPEN_REPORTER, "anonymous": 0,
     "reason": "оскорбления", "status": "pending",
     "created_at": datetime(2026, 7, 20, 10, 0), "decided_by": None, "decided_at": None},
    {"id": 2, "target_id": TARGET_ID, "reporter_id": ANON_REPORTER, "anonymous": 1,
     "reason": "спам в лс", "status": "pending",
     "created_at": datetime(2026, 7, 20, 11, 0), "decided_by": None, "decided_at": None},
]

NAMES = {
    TARGET_ID: {"user_id": TARGET_ID, "full_name": "Марина Ким", "username": None},
    OPEN_REPORTER: {"user_id": OPEN_REPORTER, "full_name": "Оля Ковалёва", "username": "olya"},
    ANON_REPORTER: {"user_id": ANON_REPORTER, "full_name": "Паша", "username": "pasha"},
}


@pytest.fixture
def panel_client(monkeypatch):
    state = {"rows": [dict(c) for c in COMPLAINTS], "statuses": [], "deleted": [], "logs": []}

    async def list_complaint_targets():
        return [{"target_id": TARGET_ID, "total": len(state["rows"]),
                 "pending": sum(1 for c in state["rows"] if c["status"] == "pending")}]

    async def list_complaints_for_target(target_id):
        return [dict(c) for c in state["rows"] if c["target_id"] == target_id]

    async def get_complaint(complaint_id):
        for c in state["rows"]:
            if c["id"] == complaint_id:
                return dict(c)
        return None

    async def set_complaint_status(complaint_id, status, decided_by):
        state["statuses"].append((complaint_id, status))
        for c in state["rows"]:
            if c["id"] == complaint_id:
                c["status"] = status

    async def delete_complaint(complaint_id):
        state["deleted"].append(complaint_id)
        state["rows"] = [c for c in state["rows"] if c["id"] != complaint_id]

    async def get_known_names(user_ids):
        return {uid: NAMES[uid] for uid in user_ids if uid in NAMES}

    async def count_pending_complaints():
        return sum(1 for c in state["rows"] if c["status"] == "pending")

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("list_complaint_targets", list_complaint_targets),
        ("list_complaints_for_target", list_complaints_for_target),
        ("get_complaint", get_complaint),
        ("set_complaint_status", set_complaint_status),
        ("delete_complaint", delete_complaint),
        ("get_known_names", get_known_names),
        ("count_pending_complaints", count_pending_complaints),
        ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def targets(client):
    res = client.get("/api/complaints")
    assert res.status_code == 200, res.text
    return res.json()


def for_target(client, target_id=TARGET_ID):
    res = client.get(f"/api/complaints/{target_id}")
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Анонимность — то, ради чего люди её выбирают
# ---------------------------------------------------------------------------

def test_анонимная_жалоба_не_раскрывает_автора(panel_client):
    """Ни id, ни имени: отданный сервером reporter_id виден в сетевых
    запросах браузера, и «скрытие» на фронте ничего не стоит."""
    anon = next(c for c in for_target(panel_client)["complaints"] if c["id"] == 2)
    assert anon["anonymous"] is True
    assert anon["reporter"] is None
    assert "reporter_id" not in anon
    assert "Паша" not in str(anon) and "pasha" not in str(anon)


def test_обычная_жалоба_показывает_автора(panel_client):
    """Не анонимная — значит человек согласен, что его видно."""
    open_one = next(c for c in for_target(panel_client)["complaints"] if c["id"] == 1)
    assert open_one["anonymous"] is False
    assert open_one["reporter"]["full_name"] == "Оля Ковалёва"


def test_в_целом_ответе_нет_следов_анонима(panel_client):
    """Проверяем весь ответ целиком: id анонима не должен просочиться ни в
    одном поле."""
    body = for_target(panel_client)
    assert str(ANON_REPORTER) not in str(body).replace(str(TARGET_ID), "")


# ---------------------------------------------------------------------------
# Списки
# ---------------------------------------------------------------------------

def test_список_целей_с_именами(panel_client):
    data = targets(panel_client)
    item = data["targets"][0]
    assert item["target_id"] == TARGET_ID
    assert item["full_name"] == "Марина Ким"
    assert item["pending"] == 2 and item["total"] == 2


def test_счётчик_нерассмотренных(panel_client):
    assert targets(panel_client)["pending_total"] == 2


def test_жалобы_на_человека_с_причиной_и_датой(panel_client):
    first = for_target(panel_client)["complaints"][0]
    assert first["reason"] == "оскорбления"
    assert first["created_at"].startswith("2026-07-20")
    assert for_target(panel_client)["target"]["full_name"] == "Марина Ким"


# ---------------------------------------------------------------------------
# Решения
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["accepted", "declined"])
def test_решение_по_жалобе(panel_client, status):
    res = panel_client.post("/api/complaints/1/status", json={"status": status})
    assert res.status_code == 200, res.text
    assert panel_client.state["statuses"] == [(1, status)]


def test_недопустимый_статус(panel_client):
    assert panel_client.post("/api/complaints/1/status", json={"status": "удалить"}).status_code == 400


def test_решение_по_несуществующей(panel_client):
    assert panel_client.post("/api/complaints/999/status", json={"status": "accepted"}).status_code == 404


def test_жалоба_удаляется(panel_client):
    assert panel_client.request("DELETE", "/api/complaints/1").status_code == 200
    assert panel_client.state["deleted"] == [1]


def test_удаление_несуществующей(panel_client):
    assert panel_client.request("DELETE", "/api/complaints/999").status_code == 404


def test_решения_пишутся_в_журнал(panel_client):
    panel_client.post("/api/complaints/1/status", json={"status": "accepted"})
    assert "complaint_accepted" in panel_client.state["logs"]
