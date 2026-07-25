"""Персонал самостоятельно привязывает свой аккаунт к Telegram — тем же
кодом, что уже выдаёт команда «сайт». После привязки require_member должен
пускать персонал на member-эндпоинты."""

from __future__ import annotations

import asyncio
import importlib

import aiomysql
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client(monkeypatch):
    state = {"codes": {}, "users": {}, "logs": []}

    async def consume_panel_link_code(code):
        row = state["codes"].pop(code, None)
        return dict(row) if row else None

    async def get_panel_user_by_tg(tg_user_id):
        for u in state["users"].values():
            if u.get("tg_user_id") == tg_user_id:
                return dict(u)
        return None

    async def set_panel_user_tg_link(user_id, tg_user_id, tg_full_name):
        if user_id not in state["users"]:
            return False
        state["users"][user_id]["tg_user_id"] = tg_user_id
        state["users"][user_id]["tg_full_name"] = tg_full_name
        return True

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "consume_panel_link_code", consume_panel_link_code)
    monkeypatch.setattr(db, "get_panel_user_by_tg", get_panel_user_by_tg)
    monkeypatch.setattr(db, "set_panel_user_tg_link", set_panel_user_tg_link)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    c = TestClient(panel.app)
    c.state = state
    yield c
    panel.app.dependency_overrides.clear()


def _login_as(client, user_id=1, role="admin", tg_user_id=None):
    user = PanelUser(id=user_id, username="staffuser", role=role, tg_user_id=tg_user_id)
    client.state["users"][user_id] = {
        "id": user_id, "username": "staffuser", "role": role, "tg_user_id": tg_user_id,
    }
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: user
    return user


def test_успешная_привязка(client):
    _login_as(client, user_id=1, tg_user_id=None)
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": "someone", "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 200, res.text
    assert client.state["users"][1]["tg_user_id"] == 999
    assert "panel_tg_linked" in client.state["logs"][0] or client.state["logs"]


def test_невалидный_код(client):
    _login_as(client, user_id=1, tg_user_id=None)
    res = client.post("/api/link-telegram", json={"code": "NOPE0000"})
    assert res.status_code == 400


def test_уже_привязан_нельзя_перепривязать(client):
    _login_as(client, user_id=1, tg_user_id=555)
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": None, "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 409


def test_tg_уже_занят_другим_аккаунтом(client):
    _login_as(client, user_id=1, tg_user_id=None)
    client.state["users"][2] = {"id": 2, "username": "other", "role": "admin", "tg_user_id": 999}
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": None, "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 409


def test_гонка_дубликат_tg_user_id_даёт_чистый_409(client, monkeypatch):
    """Два staff-аккаунта одновременно потребляют один код: оба проходят
    проверку на шаге 3 (existing is None), но на записи второй натыкается на
    UNIQUE INDEX uniq_panel_users_tg — должен быть чистый 409, а не сырая 500."""
    _login_as(client, user_id=1, tg_user_id=None)
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": None, "tg_full_name": "Кто-то",
    }

    async def set_panel_user_tg_link_raises(user_id, tg_user_id, tg_full_name):
        raise aiomysql.IntegrityError(1062, "Duplicate entry '999' for key 'uniq_panel_users_tg'")

    monkeypatch.setattr(db, "set_panel_user_tg_link", set_panel_user_tg_link_raises)

    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 409
    assert res.json()["detail"] == "Этот Telegram уже привязан к другому аккаунту."


class _FakeRequest:
    cookies: dict = {}


def test_require_member_пускает_привязанный_персонал(monkeypatch):
    user = PanelUser(id=1, username="staffuser", role="admin", tg_user_id=777)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel.auth, "current_user", fake_current_user)
    result = asyncio.run(panel.auth.require_member(_FakeRequest()))
    assert result.id == 1


def test_require_member_не_пускает_непривязанный_персонал(monkeypatch):
    user = PanelUser(id=1, username="staffuser", role="admin", tg_user_id=None)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel.auth, "current_user", fake_current_user)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(panel.auth.require_member(_FakeRequest()))
    assert exc_info.value.status_code == 403


def test_require_member_как_и_раньше_пускает_обычного_участника(monkeypatch):
    user = PanelUser(id=2, username="tg12345", role="member", tg_user_id=12345)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel.auth, "current_user", fake_current_user)
    result = asyncio.run(panel.auth.require_member(_FakeRequest()))
    assert result.id == 2
