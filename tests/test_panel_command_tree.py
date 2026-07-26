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
    {"command_key": "top", "category": "Статистика", "phrase": "топ", "default_level": 0, "overridable": 1, "sort_order": 1, "cleanup_targetable": 1},
    {"command_key": "warn", "category": "Модерация", "phrase": "варн", "default_level": 1, "overridable": 1, "sort_order": 2, "cleanup_targetable": 1},
    {"command_key": "set_permission", "category": "ДК", "phrase": "право", "default_level": 3, "overridable": 0, "sort_order": 3, "cleanup_targetable": 1},
    # Команду с такой же фразой, как у соседней, бот в чате не отличает —
    # свой срок очистки ей задать нельзя.
    {"command_key": "top_admin", "category": "Статистика", "phrase": "топ", "default_level": 2, "overridable": 1, "sort_order": 4, "cleanup_targetable": 0},
]


def _mock_registry(monkeypatch, overrides=None, cleanup=None, cleanup_default=None):
    async def list_reg():
        return [dict(r) for r in REG]

    async def list_levels():
        return dict(overrides or {})

    async def list_cleanup():
        return dict(cleanup or {})

    async def fetch_settings():
        return {"command_cleanup_minutes": cleanup_default}

    monkeypatch.setattr(db, "list_command_cleanup", list_cleanup)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)

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


# --- свой срок автоочистки у отдельной команды -----------------------------

def test_дерево_отдаёт_сроки_очистки(client, monkeypatch):
    _as_staff()
    _mock_registry(monkeypatch, cleanup={"warn": 60}, cleanup_default=5)
    d = client.get("/api/command-tree").json()
    cats = {c["category"]: c for c in d["categories"]}
    warn = next(c for c in cats["Модерация"]["commands"] if c["key"] == "warn")
    top = next(c for c in cats["Статистика"]["commands"] if c["key"] == "top")
    assert warn["cleanup_minutes"] == 60      # свой срок
    assert top["cleanup_minutes"] is None     # живёт по общему
    assert d["cleanup_default"] == 5
    assert d["cleanup_max"] == panel.CMD_CLEANUP_MAX_MINUTES


def test_общий_срок_без_настройки_равен_умолчанию(client, monkeypatch):
    _as_staff()
    _mock_registry(monkeypatch, cleanup_default=None)
    assert client.get("/api/command-tree").json()["cleanup_default"] == 15


def test_владелец_задаёт_срок_команде(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    saved = {}

    async def set_cleanup(key, minutes, updated_by=None):
        saved.update(key=key, minutes=minutes)

    monkeypatch.setattr(db, "set_command_cleanup", set_cleanup)
    res = client.post("/api/command-tree/cleanup", json={"command_key": "top", "minutes": 90})
    assert res.status_code == 200, res.text
    assert saved == {"key": "top", "minutes": 90}
    assert res.json()["cleanup_minutes"] == 90


def test_ноль_означает_не_удалять(client, monkeypatch):
    """0 — валидное значение, а не «сбросить»: команду не убирают совсем."""
    _as_owner()
    _mock_registry(monkeypatch)
    saved = {}

    async def set_cleanup(key, minutes, updated_by=None):
        saved.update(key=key, minutes=minutes)

    monkeypatch.setattr(db, "set_command_cleanup", set_cleanup)
    res = client.post("/api/command-tree/cleanup", json={"command_key": "top", "minutes": 0})
    assert res.status_code == 200 and saved["minutes"] == 0
    assert res.json()["cleanup_minutes"] == 0


def test_сброс_срока_возвращает_на_общий(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    reset = {}

    async def do_reset(key):
        reset["key"] = key

    monkeypatch.setattr(db, "reset_command_cleanup", do_reset)
    res = client.post("/api/command-tree/cleanup", json={"command_key": "top", "minutes": None})
    assert res.status_code == 200 and reset["key"] == "top"
    assert res.json()["cleanup_minutes"] is None


@pytest.mark.parametrize("minutes", [-1, 48 * 60 + 1])
def test_срок_вне_потолка_отвергается(client, monkeypatch, minutes):
    """Потолок тот же, что у общей настройки: Telegram не даёт ботам удалять
    сообщения старше 48 часов, и всё сверх этого тихо не работало бы."""
    _as_owner()
    _mock_registry(monkeypatch)
    touched = []
    monkeypatch.setattr(db, "set_command_cleanup",
                        lambda *a, **k: touched.append(a))
    res = client.post("/api/command-tree/cleanup", json={"command_key": "top", "minutes": minutes})
    assert res.status_code == 400 and not touched


def test_срок_несуществующей_команде_не_задать(client, monkeypatch):
    _as_owner()
    _mock_registry(monkeypatch)
    res = client.post("/api/command-tree/cleanup", json={"command_key": "нетуTakoy", "minutes": 10})
    assert res.status_code == 404


def test_неотличимой_команде_срок_не_задать(client, monkeypatch):
    """Сохранить такую настройку — значит показать человеку, что она работает,
    хотя бот эту команду в чате от соседней не отличает."""
    _as_owner()
    _mock_registry(monkeypatch)
    touched = []
    monkeypatch.setattr(db, "set_command_cleanup", lambda *a, **k: touched.append(a))
    res = client.post("/api/command-tree/cleanup", json={"command_key": "top_admin", "minutes": 10})
    assert res.status_code == 409 and not touched


def test_дерево_помечает_неотличимые_команды(client, monkeypatch):
    _as_staff()
    _mock_registry(monkeypatch)
    cmds = {c["key"]: c for cat in client.get("/api/command-tree").json()["categories"]
            for c in cat["commands"]}
    assert cmds["top"]["cleanup_targetable"] is True
    assert cmds["top_admin"]["cleanup_targetable"] is False


# --- случайные события чата ------------------------------------------------

def test_события_читаются_по_чату(client, monkeypatch):
    _as_staff()

    async def get_data(key):
        return {"data_value": "1"} if key == "chat_events_off:-100" else None

    monkeypatch.setattr(db, "get_data", get_data)
    assert client.get("/api/chat-events?chat_id=-100").json()["enabled"] is False
    assert client.get("/api/chat-events?chat_id=-200").json()["enabled"] is True


def test_выключение_событий_пишет_тот_же_ключ_что_и_бот(client, monkeypatch):
    """Ключ обязан совпадать с bot._events_off_key: это одна настройка с двумя
    входами — панель и «−события» в чате."""
    _as_staff()
    written = {}

    async def set_data(key, value, updated_by=None):
        written.update(key=key, value=value)

    async def delete_data(key):
        written["deleted"] = key
        return True

    monkeypatch.setattr(db, "set_data", set_data)
    monkeypatch.setattr(db, "delete_data", delete_data)

    res = client.post("/api/chat-events", json={"chat_id": -100, "enabled": False})
    assert res.status_code == 200 and res.json()["enabled"] is False
    assert written["key"] == "chat_events_off:-100" and written["value"] == "1"

    res = client.post("/api/chat-events", json={"chat_id": -100, "enabled": True})
    assert res.status_code == 200 and res.json()["enabled"] is True
    assert written["deleted"] == "chat_events_off:-100"
