"""Пороги наград по степеням — панель.

GET  /api/reward-levels        — список порогов 1-8 (владелец и админ панели видят)
POST /api/reward-levels/level  — изменить/сбросить порог (только владелец)
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client(monkeypatch):
    state = {"overrides": {}, "reload_value": None, "logs": []}

    async def list_reward_degree_levels():
        return dict(state["overrides"])

    async def set_reward_degree_level(degree, min_level, updated_by=None):
        state["overrides"][degree] = min_level

    async def reset_reward_degree_level(degree):
        state["overrides"].pop(degree, None)

    async def set_data(key, value, updated_by=None):
        if key == "panel_action_reload":
            state["reload_value"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    async def fetch_settings():
        return {}

    async def list_admins():
        return []

    monkeypatch.setattr(db, "list_reward_degree_levels", list_reward_degree_levels)
    monkeypatch.setattr(db, "set_reward_degree_level", set_reward_degree_level)
    monkeypatch.setattr(db, "reset_reward_degree_level", reset_reward_degree_level)
    monkeypatch.setattr(db, "set_data", set_data)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    monkeypatch.setattr(db, "list_admins", list_admins)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    c = TestClient(panel.app)
    c.state = state
    yield c
    panel.app.dependency_overrides.clear()


def _as_owner():
    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    panel.app.dependency_overrides[panel.auth.require_owner] = lambda: owner
    return owner


def _as_staff():
    admin = PanelUser(id=2, username="admin", role="admin")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def test_админ_видит_пороги_без_права_правки(client):
    _as_staff()
    d = client.get("/api/reward-levels").json()
    assert len(d["degrees"]) == 8
    deg1 = next(x for x in d["degrees"] if x["degree"] == 1)
    assert deg1["level"] == 0  # LEVEL_MEMBER по умолчанию — доступно всем
    deg6 = next(x for x in d["degrees"] if x["degree"] == 6)
    assert deg6["level"] == 99  # OWNER_LEVEL по умолчанию
    assert d["can_edit"] is False


def test_владелец_видит_право_правки(client):
    _as_owner()
    d = client.get("/api/reward-levels").json()
    assert d["can_edit"] is True


def test_владелец_меняет_порог(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 4, "level": 3})
    assert res.status_code == 200, res.text
    assert client.state["overrides"][4] == 3
    assert res.json() == {"ok": True, "level": 3, "overridden": True}
    assert client.state["reload_value"] is not None
    assert "reward_degree_level_set" in client.state["logs"]


def test_сброс_порога_к_умолчанию(client):
    _as_owner()
    client.state["overrides"][4] = 3
    res = client.post("/api/reward-levels/level", json={"degree": 4, "level": None})
    assert res.status_code == 200, res.text
    assert 4 not in client.state["overrides"]
    assert res.json() == {"ok": True, "level": 2, "overridden": False}  # LEVEL_ADMIN — дефолт для степени 4
    assert "reward_degree_level_reset" in client.state["logs"]


def test_недопустимая_степень(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 9, "level": 1})
    assert res.status_code == 400


def test_недопустимый_уровень(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 1, "level": 5})
    assert res.status_code == 400


def test_админ_не_может_менять_порог(client, monkeypatch):
    """require_owner сам вызывает require_user внутри (не через Depends), поэтому
    dependency_overrides для require_user тут не сработал бы — подменяем
    require_user напрямую в модуле, чтобы реальная проверка is_owner в
    require_owner отработала и вернула 403."""
    admin = PanelUser(id=2, username="admin", role="admin")

    async def fake_require_user(request):
        return admin

    monkeypatch.setattr(panel.auth, "require_user", fake_require_user)
    res = client.post("/api/reward-levels/level", json={"degree": 1, "level": 2})
    assert res.status_code == 403
