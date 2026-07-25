"""Управление действиями «Предложить» через сайт.

GET  /api/propose-actions            — владелец и админ панели видят список
POST/PUT/DELETE .../phrases          — правка фраз (по уровню propose_manage)
POST .../synonyms, DELETE .../synonyms/{synonym}
POST .../{key}/active, .../{key}/settings
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel import roles
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "actions": {
            "romashka": {"cooldown_seconds": 300, "timeout_seconds": 120, "is_active": 1},
        },
        "phrases": [
            {"id": 1, "action_key": "romashka", "kind": "propose", "phrase": "{actor} зовёт {target} 🌼", "sort_order": 0, "is_active": 1},
            {"id": 2, "action_key": "romashka", "kind": "agree", "phrase": "ок 🌼", "sort_order": 0, "is_active": 1},
        ],
        "synonyms": {"ромашка": "romashka"},
        "admins": [],
        "command_levels": {},
        "reload_value": None, "logs": [],
    }
    next_id = {"v": 100}

    async def list_propose_actions_rows():
        return [{"action_key": k, **v} for k, v in state["actions"].items()]

    async def list_propose_phrases_rows():
        return [dict(p) for p in state["phrases"]]

    async def list_propose_action_synonyms():
        return dict(state["synonyms"])

    async def add_propose_phrase(action_key, kind, phrase, sort_order=None):
        next_id["v"] += 1
        state["actions"].setdefault(action_key, {"cooldown_seconds": 300, "timeout_seconds": 120, "is_active": 1})
        state["phrases"].append({"id": next_id["v"], "action_key": action_key, "kind": kind,
                                 "phrase": phrase, "sort_order": 0, "is_active": 1})
        return next_id["v"]

    async def update_propose_phrase(phrase_id, phrase):
        for p in state["phrases"]:
            if p["id"] == phrase_id:
                p["phrase"] = phrase
                return True
        return False

    async def delete_propose_phrase(phrase_id):
        before = len(state["phrases"])
        state["phrases"] = [p for p in state["phrases"] if p["id"] != phrase_id]
        return len(state["phrases"]) < before

    async def add_propose_action_synonym(synonym, action_key):
        state["synonyms"][synonym] = action_key

    async def delete_propose_action_synonym(synonym):
        return state["synonyms"].pop(synonym, None) is not None

    async def set_propose_action_active(action_key, is_active):
        if action_key not in state["actions"]:
            return 0
        state["actions"][action_key]["is_active"] = 1 if is_active else 0
        return 1

    async def set_propose_action_settings(action_key, cooldown_seconds, timeout_seconds):
        if action_key not in state["actions"]:
            return False
        state["actions"][action_key]["cooldown_seconds"] = cooldown_seconds
        state["actions"][action_key]["timeout_seconds"] = timeout_seconds
        return True

    async def list_admins():
        return state["admins"]

    async def fetch_settings():
        return {}

    async def list_command_levels():
        return dict(state["command_levels"])

    async def set_data(key, value, updated_by=None):
        if key == "panel_action_reload":
            state["reload_value"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("list_propose_actions_rows", list_propose_actions_rows),
        ("list_propose_phrases_rows", list_propose_phrases_rows),
        ("list_propose_action_synonyms", list_propose_action_synonyms),
        ("add_propose_phrase", add_propose_phrase),
        ("update_propose_phrase", update_propose_phrase),
        ("delete_propose_phrase", delete_propose_phrase),
        ("add_propose_action_synonym", add_propose_action_synonym),
        ("delete_propose_action_synonym", delete_propose_action_synonym),
        ("set_propose_action_active", set_propose_action_active),
        ("set_propose_action_settings", set_propose_action_settings),
        ("list_admins", list_admins), ("fetch_settings", fetch_settings),
        ("list_command_levels", list_command_levels),
        ("set_data", set_data), ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    roles.invalidate()  # кэш ролей живёт 30с — между тестами он бы протух не вовремя

    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def _as_owner(client):
    owner = PanelUser(id=1, username="owner", role="owner", tg_user_id=1)
    client.state["admins"] = []
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    return owner


def _as_senior_admin(client):
    admin = PanelUser(id=2, username="senior", role="admin", tg_user_id=42)
    client.state["admins"] = [{"user_id": 42, "level": roles.LEVEL_SENIOR}]
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def _as_junior_admin(client):
    admin = PanelUser(id=3, username="moder", role="admin", tg_user_id=43)
    client.state["admins"] = [{"user_id": 43, "level": roles.LEVEL_MODERATOR}]
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def overview(client):
    res = client.get("/api/propose-actions")
    assert res.status_code == 200, res.text
    return res.json()


def test_действия_видны_с_фразами_по_видам(panel_client):
    _as_owner(panel_client)
    data = overview(panel_client)
    romashka = next(a for a in data["actions"] if a["key"] == "romashka")
    assert [p["phrase"] for p in romashka["phrases"]["propose"]] == ["{actor} зовёт {target} 🌼"]
    assert [p["phrase"] for p in romashka["phrases"]["agree"]] == ["ок 🌼"]
    assert romashka["phrases"]["decline"] == []
    assert romashka["cooldown_seconds"] == 300
    assert romashka["synonyms"] == ["ромашка"]


def test_владелец_может_редактировать(panel_client):
    _as_owner(panel_client)
    assert overview(panel_client)["can_edit"] is True


def test_старший_админ_может_редактировать_по_умолчанию(panel_client):
    """propose_manage по умолчанию требует LEVEL_SENIOR — без оверрайда старший
    администратор проходит."""
    _as_senior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is True


def test_младший_админ_не_может_редактировать_по_умолчанию(panel_client):
    _as_junior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is False


def test_оверрайд_дерева_команд_поднимает_порог(panel_client):
    """Владелец поднял propose_manage до уровня владельца через Дерево команд —
    даже старший администратор больше не может редактировать."""
    panel_client.state["command_levels"] = {"propose_manage": roles.OWNER_LEVEL}
    _as_senior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is False


def test_фраза_добавляется_и_создаёт_новое_действие(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "turnir", "kind": "propose", "phrase": "{actor} зовёт {target} на турнир"})
    assert res.status_code == 200, res.text
    keys = {a["key"] for a in overview(panel_client)["actions"]}
    assert "turnir" in keys


def test_младший_админ_не_может_добавить_фразу(panel_client):
    _as_junior_admin(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "romashka", "kind": "propose", "phrase": "x {actor} {target}"})
    assert res.status_code == 403


def test_неизвестный_вид_фразы_отвергается(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "romashka", "kind": "wrong", "phrase": "x {actor} {target}"})
    assert res.status_code == 400


def test_действие_включается_выключается(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/romashka/active", json={"active": False})
    assert res.status_code == 200, res.text
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert romashka["active"] is False


def test_кулдаун_и_таймаут_сохраняются(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/romashka/settings",
                            json={"cooldown_seconds": 600, "timeout_seconds": 60})
    assert res.status_code == 200, res.text
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert romashka["cooldown_seconds"] == 600
    assert romashka["timeout_seconds"] == 60


def test_синоним_добавляется_и_удаляется(panel_client):
    _as_owner(panel_client)
    assert panel_client.post("/api/propose-actions/synonyms",
                             json={"synonym": "маргаритка", "action_key": "romashka"}).status_code == 200
    assert overview(panel_client)["actions"][0]["synonyms"] or True  # см. следующий ассерт
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert "маргаритка" in romashka["synonyms"]
    assert panel_client.request("DELETE", "/api/propose-actions/synonyms/маргаритка").status_code == 200
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert "маргаритка" not in romashka["synonyms"]


def test_правка_поднимает_флаг_перечитки(panel_client):
    _as_owner(panel_client)
    assert panel_client.state["reload_value"] is None
    panel_client.post("/api/propose-actions/romashka/active", json={"active": False})
    assert panel_client.state["reload_value"] is not None
