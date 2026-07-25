"""РП-действия и себяшки в панели.

Оба набора устроены одинаково (action_key → список фраз, можно включать/
выключать действие целиком), поэтому эндпоинты общие и параметризованы видом
kind ∈ {rp, self}. У РП вдобавок есть синонимы.

Ключевое, что стережём: панель и бот — разные процессы. После любой правки
панель обязана поднять флаг перечитки в bot_data, иначе бот не увидит правку в
живых чатах до перезапуска.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

RELOAD_KEY = "panel_action_reload"


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "rp_rows": [
            {"id": 1, "action_key": "обнять", "phrase": "{actor} обнимает {target}", "sort_order": 0, "is_active": 1},
            {"id": 2, "action_key": "обнять", "phrase": "{actor} крепко обнимает {target}", "sort_order": 1, "is_active": 1},
            {"id": 3, "action_key": "ударить", "phrase": "{actor} бьёт {target}", "sort_order": 0, "is_active": 0},
        ],
        "self_rows": [
            {"id": 10, "action_key": "чихнуть", "phrase": "{user} чихнул(а)", "sort_order": 0, "is_active": 1},
        ],
        "synonyms": {"обнимашки": "обнять"},
        "reload_value": None, "logs": [],
    }
    next_id = {"v": 100}

    async def list_rp_actions_rows():
        return [dict(r) for r in state["rp_rows"]]

    async def list_self_actions_rows():
        return [dict(r) for r in state["self_rows"]]

    async def add_rp_action_phrase(action_key, phrase, sort_order=None):
        next_id["v"] += 1
        state["rp_rows"].append({"id": next_id["v"], "action_key": action_key,
                                 "phrase": phrase, "sort_order": 0, "is_active": 1})
        return next_id["v"]

    async def add_self_action_phrase(action_key, phrase, sort_order=None):
        next_id["v"] += 1
        state["self_rows"].append({"id": next_id["v"], "action_key": action_key,
                                   "phrase": phrase, "sort_order": 0, "is_active": 1})
        return next_id["v"]

    async def update_rp_action_phrase(phrase_id, phrase):
        for r in state["rp_rows"]:
            if r["id"] == phrase_id:
                r["phrase"] = phrase
                return True
        return False

    async def update_self_action_phrase(phrase_id, phrase):
        for r in state["self_rows"]:
            if r["id"] == phrase_id:
                r["phrase"] = phrase
                return True
        return False

    async def delete_rp_action_phrase(phrase_id):
        before = len(state["rp_rows"])
        state["rp_rows"] = [r for r in state["rp_rows"] if r["id"] != phrase_id]
        return len(state["rp_rows"]) < before

    async def delete_self_action_phrase(phrase_id):
        before = len(state["self_rows"])
        state["self_rows"] = [r for r in state["self_rows"] if r["id"] != phrase_id]
        return len(state["self_rows"]) < before

    async def set_rp_action_key_active(action_key, is_active):
        n = 0
        for r in state["rp_rows"]:
            if r["action_key"] == action_key:
                r["is_active"] = 1 if is_active else 0
                n += 1
        return n

    async def set_self_action_key_active(action_key, is_active):
        n = 0
        for r in state["self_rows"]:
            if r["action_key"] == action_key:
                r["is_active"] = 1 if is_active else 0
                n += 1
        return n

    async def list_rp_action_synonyms():
        return dict(state["synonyms"])

    async def add_rp_action_synonym(synonym, action_key):
        state["synonyms"][synonym] = action_key

    async def delete_rp_action_synonym(synonym):
        return state["synonyms"].pop(synonym, None) is not None

    async def set_data(key, value, updated_by=None):
        if key == RELOAD_KEY:
            state["reload_value"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("list_rp_actions_rows", list_rp_actions_rows), ("list_self_actions_rows", list_self_actions_rows),
        ("add_rp_action_phrase", add_rp_action_phrase), ("add_self_action_phrase", add_self_action_phrase),
        ("update_rp_action_phrase", update_rp_action_phrase), ("update_self_action_phrase", update_self_action_phrase),
        ("delete_rp_action_phrase", delete_rp_action_phrase), ("delete_self_action_phrase", delete_self_action_phrase),
        ("set_rp_action_key_active", set_rp_action_key_active), ("set_self_action_key_active", set_self_action_key_active),
        ("list_rp_action_synonyms", list_rp_action_synonyms), ("add_rp_action_synonym", add_rp_action_synonym),
        ("delete_rp_action_synonym", delete_rp_action_synonym),
        ("set_data", set_data), ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def overview(client, kind="rp"):
    res = client.get(f"/api/action-sets/{kind}")
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Список
# ---------------------------------------------------------------------------

def test_действия_сгруппированы_по_ключу(panel_client):
    data = overview(panel_client, "rp")
    keys = {a["key"]: a for a in data["actions"]}
    assert set(keys) == {"обнять", "ударить"}
    assert [p["phrase"] for p in keys["обнять"]["phrases"]] == [
        "{actor} обнимает {target}", "{actor} крепко обнимает {target}"]


def test_выключенное_действие_видно_с_пометкой(panel_client):
    """В списке для редактирования выключенные тоже показаны — иначе их нельзя
    включить обратно."""
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert keys["обнять"]["active"] is True
    assert keys["ударить"]["active"] is False


def test_синонимы_только_у_рп(panel_client):
    assert overview(panel_client, "rp")["synonyms"] == {"обнимашки": "обнять"}
    assert overview(panel_client, "self")["synonyms"] == {}


def test_себяшки_отдельный_набор(panel_client):
    keys = {a["key"] for a in overview(panel_client, "self")["actions"]}
    assert keys == {"чихнуть"}


def test_неизвестный_вид_отвергается(panel_client):
    assert panel_client.get("/api/action-sets/clans").status_code == 404


# ---------------------------------------------------------------------------
# Добавление фразы (и нового действия)
# ---------------------------------------------------------------------------

def test_фраза_добавляется_в_существующее_действие(panel_client):
    res = panel_client.post("/api/action-sets/rp/phrases",
                            json={"key": "обнять", "phrase": "{actor} тискает {target}"})
    assert res.status_code == 200, res.text
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert any(p["phrase"] == "{actor} тискает {target}" for p in keys["обнять"]["phrases"])


def test_новое_действие_создаётся_первой_фразой(panel_client):
    panel_client.post("/api/action-sets/rp/phrases",
                      json={"key": "пнуть", "phrase": "{actor} пинает {target}"})
    assert "пнуть" in {a["key"] for a in overview(panel_client, "rp")["actions"]}


@pytest.mark.parametrize("phrase", ["", "   "])
def test_пустая_фраза_отвергается(panel_client, phrase):
    assert panel_client.post("/api/action-sets/rp/phrases",
                             json={"key": "обнять", "phrase": phrase}).status_code == 400


def test_слишком_длинная_фраза(panel_client):
    """Колонка phrase — 512 символов; молча обрезанная фраза не совпадёт с
    задуманной."""
    assert panel_client.post("/api/action-sets/rp/phrases",
                             json={"key": "обнять", "phrase": "я" * 513}).status_code == 400


def test_слишком_длинный_ключ(panel_client):
    assert panel_client.post("/api/action-sets/rp/phrases",
                             json={"key": "к" * 65, "phrase": "ok {actor} {target}"}).status_code == 400


# ---------------------------------------------------------------------------
# Включение / выключение действия
# ---------------------------------------------------------------------------

def test_действие_выключается_целиком(panel_client):
    res = panel_client.post("/api/action-sets/rp/actions/обнять/active", json={"active": False})
    assert res.status_code == 200, res.text
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert keys["обнять"]["active"] is False


def test_действие_включается_обратно(panel_client):
    panel_client.post("/api/action-sets/rp/actions/ударить/active", json={"active": True})
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert keys["ударить"]["active"] is True


def test_включение_несуществующего_действия(panel_client):
    assert panel_client.post("/api/action-sets/rp/actions/неттакого/active",
                             json={"active": False}).status_code == 404


# ---------------------------------------------------------------------------
# Правка и удаление фраз
# ---------------------------------------------------------------------------

def test_фраза_редактируется(panel_client):
    res = panel_client.patch("/api/action-sets/rp/phrases/1",
                             json={"phrase": "{actor} обнимает {target} нежно"})
    assert res.status_code == 200, res.text
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert keys["обнять"]["phrases"][0]["phrase"] == "{actor} обнимает {target} нежно"


def test_правка_несуществующей_фразы(panel_client):
    assert panel_client.patch("/api/action-sets/rp/phrases/999",
                              json={"phrase": "ok {actor} {target}"}).status_code == 404


def test_фраза_удаляется(panel_client):
    assert panel_client.request("DELETE", "/api/action-sets/rp/phrases/2").status_code == 200
    keys = {a["key"]: a for a in overview(panel_client, "rp")["actions"]}
    assert [p["id"] for p in keys["обнять"]["phrases"]] == [1]


def test_удаление_несуществующей_фразы(panel_client):
    assert panel_client.request("DELETE", "/api/action-sets/rp/phrases/999").status_code == 404


# ---------------------------------------------------------------------------
# Синонимы (только РП)
# ---------------------------------------------------------------------------

def test_синоним_добавляется(panel_client):
    res = panel_client.post("/api/action-sets/rp/synonyms", json={"synonym": "обнимашка", "key": "обнять"})
    assert res.status_code == 200, res.text
    assert overview(panel_client, "rp")["synonyms"]["обнимашка"] == "обнять"


def test_синоним_удаляется(panel_client):
    assert panel_client.request("DELETE", "/api/action-sets/rp/synonyms/обнимашки").status_code == 200
    assert "обнимашки" not in overview(panel_client, "rp")["synonyms"]


def test_синонимы_у_себяшек_недоступны(panel_client):
    assert panel_client.post("/api/action-sets/self/synonyms",
                             json={"synonym": "x", "key": "чихнуть"}).status_code == 404


# ---------------------------------------------------------------------------
# Сигнал перечитки — ради него всё и затевалось
# ---------------------------------------------------------------------------

def test_добавление_поднимает_флаг_перечитки(panel_client):
    assert panel_client.state["reload_value"] is None
    panel_client.post("/api/action-sets/rp/phrases", json={"key": "обнять", "phrase": "{actor} жмёт {target}"})
    assert panel_client.state["reload_value"] is not None


def test_каждая_правка_меняет_флаг(panel_client):
    panel_client.post("/api/action-sets/rp/actions/обнять/active", json={"active": False})
    first = panel_client.state["reload_value"]
    panel_client.post("/api/action-sets/rp/actions/обнять/active", json={"active": True})
    assert panel_client.state["reload_value"] != first


def test_чтение_флаг_не_трогает(panel_client):
    overview(panel_client, "rp")
    assert panel_client.state["reload_value"] is None


def test_правки_пишутся_в_журнал(panel_client):
    panel_client.post("/api/action-sets/rp/phrases", json={"key": "обнять", "phrase": "{actor} {target} ok"})
    assert any("rp" in k for k in panel_client.state["logs"])
