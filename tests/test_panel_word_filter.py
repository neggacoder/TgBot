"""Фильтр слов в панели (список / добавить / удалить).

Слово хранится в нижнем регистре (фильтр регистронезависимый), а после каждой
правки панель поднимает флаг перечитки — иначе бот, держащий список в памяти,
не узнает об изменении до перезапуска.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def panel_client(monkeypatch):
    state = {"words": ["спам", "реклама"], "reload": None, "logs": []}

    async def list_filter_words():
        return list(state["words"])

    async def add_filter_word(word):
        if word in state["words"]:
            return False
        state["words"].append(word)
        return True

    async def delete_filter_word(word):
        if word not in state["words"]:
            return False
        state["words"].remove(word)
        return True

    async def set_data(key, value, updated_by=None):
        if key == "panel_action_reload":
            state["reload"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("list_filter_words", list_filter_words), ("add_filter_word", add_filter_word),
        ("delete_filter_word", delete_filter_word), ("set_data", set_data), ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="owner", role="owner")
    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def test_список_слов(panel_client):
    res = panel_client.get("/api/word-filter")
    assert res.status_code == 200
    assert res.json()["words"] == ["спам", "реклама"]


def test_слово_добавляется(panel_client):
    res = panel_client.post("/api/word-filter", json={"word": "казино"})
    assert res.status_code == 200, res.text
    assert "казино" in panel_client.state["words"]


def test_слово_приводится_к_нижнему_регистру(panel_client):
    """«Спам» и «спам» — одно правило, не два."""
    panel_client.post("/api/word-filter", json={"word": "КАЗИНО"})
    assert panel_client.state["words"][-1] == "казино"


def test_повтор_отвергается(panel_client):
    assert panel_client.post("/api/word-filter", json={"word": "спам"}).status_code == 409


@pytest.mark.parametrize("bad", ["", "   "])
def test_пустое_слово(panel_client, bad):
    assert panel_client.post("/api/word-filter", json={"word": bad}).status_code == 400


def test_слишком_длинное(panel_client):
    assert panel_client.post("/api/word-filter", json={"word": "я" * 129}).status_code == 400


def test_слово_удаляется(panel_client):
    assert panel_client.request("DELETE", "/api/word-filter/спам").status_code == 200
    assert "спам" not in panel_client.state["words"]


def test_удаление_регистронезависимо(panel_client):
    """Удаляем «СПАМ» — уходит хранимое «спам»."""
    assert panel_client.request("DELETE", "/api/word-filter/СПАМ").status_code == 200
    assert "спам" not in panel_client.state["words"]


def test_удаление_несуществующего(panel_client):
    assert panel_client.request("DELETE", "/api/word-filter/нетакого").status_code == 404


def test_добавление_поднимает_флаг_перечитки(panel_client):
    assert panel_client.state["reload"] is None
    panel_client.post("/api/word-filter", json={"word": "новое"})
    assert panel_client.state["reload"] is not None


def test_удаление_поднимает_флаг(panel_client):
    panel_client.request("DELETE", "/api/word-filter/спам")
    assert panel_client.state["reload"] is not None


def test_чтение_флаг_не_трогает(panel_client):
    panel_client.get("/api/word-filter")
    assert panel_client.state["reload"] is None


def test_правки_пишутся_в_журнал(panel_client):
    panel_client.post("/api/word-filter", json={"word": "лог"})
    assert "word_filter_added" in panel_client.state["logs"]
