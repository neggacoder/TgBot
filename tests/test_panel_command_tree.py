"""Дерево команд в панели: чтение реестра (staff) и правка уровня (владелец).

Реестр команд — зеркало COMMAND_REGISTRY бота в таблице command_registry; панель
читает его + оверрайды уровней (command_permissions) и группирует по категориям.
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
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(db, "add_log", _noop, raising=False)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    c = TestClient(panel.app)
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


REG = [
    {"command_key": "top", "category": "Статистика", "phrase": "топ", "default_level": 0, "overridable": 1, "sort_order": 1},
    {"command_key": "warn", "category": "Модерация", "phrase": "варн", "default_level": 1, "overridable": 1, "sort_order": 2},
    {"command_key": "set_permission", "category": "ДК", "phrase": "право", "default_level": 3, "overridable": 0, "sort_order": 3},
]


def _mock_registry(monkeypatch, overrides=None):
    async def list_reg():
        return [dict(r) for r in REG]

    async def list_levels():
        return dict(overrides or {})

    async def get_data(key):
        if key == "command_level_names":
            return {"data_value": '{"0":"Все","1":"Модератор","2":"Админ","3":"Старший"}'}
        if key == "command_category_order":
            return {"data_value": '["Статистика","Модерация","ДК"]'}
        return None

    async def set_data(key, value, updated_by=None):
        return None

    monkeypatch.setattr(db, "list_command_registry", list_reg)
    monkeypatch.setattr(db, "list_command_levels", list_levels)
    monkeypatch.setattr(db, "get_data", get_data)
    monkeypatch.setattr(db, "set_data", set_data)


def test_дерево_читается_и_группируется(client, monkeypatch):
    _as_staff()
    _mock_registry(monkeypatch, overrides={"warn": 2})
    d = client.get("/api/command-tree").json()
    cats = {c["category"]: c for c in d["categories"]}
    # порядок категорий — из command_category_order
    assert list(cats) == ["Статистика", "Модерация", "ДК"]
    warn = next(c for c in cats["Модерация"]["commands"] if c["key"] == "warn")
    assert warn["level"] == 2 and warn["overridden"] is True  # оверрайд применён
    assert d["can_edit"] is False  # админ — не владелец, правка недоступна


def test_владелец_меняет_уровень(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    saved = {}

    async def set_level(key, level, updated_by=None):
        saved.update(key=key, level=level)

    monkeypatch.setattr(db, "set_command_level", set_level)
    res = client.post("/api/command-tree/level", json={"command_key": "top", "level": 2})
    assert res.status_code == 200, res.text
    assert saved["key"] == "top" and saved["level"] == 2
    assert res.json()["level"] == 2 and res.json()["overridden"] is True


def test_сброс_уровня_к_умолчанию(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    reset = {}

    async def do_reset(key):
        reset["key"] = key

    monkeypatch.setattr(db, "reset_command_level", do_reset)
    res = client.post("/api/command-tree/level", json={"command_key": "top", "level": None})
    assert res.status_code == 200 and reset["key"] == "top"
    assert res.json()["level"] == 0 and res.json()["overridden"] is False


def test_неоверрайдабл_команду_менять_нельзя(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    res = client.post("/api/command-tree/level", json={"command_key": "set_permission", "level": 1})
    assert res.status_code == 403
