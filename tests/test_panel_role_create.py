"""Создание и удаление ролей чата из панели.

POST   /api/chat-roles      — добавить роль (сразу в список, без модерации)
DELETE /api/chat-roles/{id} — удалить роль

Правила те же, что у команд «роль добавить» / «роль удалить» в чате: название
до 64 символов, повторов быть не должно, удалять можно только свободную роль —
иначе человек лишится роли, не узнав об этом.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
ROLE_ID = 12


@pytest.fixture
def panel_client(monkeypatch):
    state = {"created": [], "deleted": [], "logs": [], "taken_name": "Аска Лэнгли",
             "role": {"id": ROLE_ID, "name": "Пен-Пен", "status": "free", "approved": 1}}

    async def propose_role(chat_id, name, category, proposed_by, auto_approved=False):
        if name.strip() == state["taken_name"]:
            return None  # роль с таким названием уже есть
        state["created"].append({
            "name": name, "category": category,
            "proposed_by": proposed_by, "auto_approved": auto_approved,
        })
        return 99

    async def get_role(chat_id, role_id):
        role = state["role"]
        return dict(role) if role and role["id"] == role_id else None

    async def delete_role(chat_id, role_id):
        state["deleted"].append(role_id)
        return True

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "propose_role", propose_role)
    monkeypatch.setattr(db, "get_role", get_role)
    monkeypatch.setattr(db, "delete_role", delete_role)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def create(client, name="Кадзи Рёдзи", category=None):
    return client.post("/api/chat-roles", json={"chat_id": CHAT_ID, "name": name, "category": category})


def remove(client, role_id=ROLE_ID):
    return client.request("DELETE", f"/api/chat-roles/{role_id}", json={"chat_id": CHAT_ID})


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------

def test_роль_создаётся(panel_client):
    res = create(panel_client)
    assert res.status_code == 200, res.text
    assert panel_client.state["created"][0]["name"] == "Кадзи Рёдзи"


def test_роль_из_панели_не_идёт_на_модерацию(panel_client):
    """Её добавил администратор — одобрять нечего и некому."""
    create(panel_client)
    assert panel_client.state["created"][0]["auto_approved"] is True


def test_автором_не_записывается_пользователь_панели(panel_client):
    """proposed_by — это Telegram-ID: по нему бот пишет автору заявки. ID
    учётки панели там означал бы сообщение случайному человеку в Telegram."""
    create(panel_client)
    assert panel_client.state["created"][0]["proposed_by"] is None


def test_категория_сохраняется(panel_client):
    create(panel_client, category="NERV")
    assert panel_client.state["created"][0]["category"] == "NERV"


def test_пустая_категория_это_её_отсутствие(panel_client):
    create(panel_client, category="   ")
    assert panel_client.state["created"][0]["category"] is None


def test_пробелы_по_краям_срезаются(panel_client):
    create(panel_client, name="  Рей Аянами  ")
    assert panel_client.state["created"][0]["name"] == "Рей Аянами"


@pytest.mark.parametrize("bad", ["", "   ", "\n"])
def test_роль_без_названия_отвергается(panel_client, bad):
    assert create(panel_client, name=bad).status_code == 400


def test_слишком_длинное_название(panel_client):
    """В базе колонка на 64 символа: молча обрезанное название потом не
    совпадёт с тем, что человек вводил."""
    assert create(panel_client, name="я" * 65).status_code == 400


def test_слишком_длинная_категория(panel_client):
    assert create(panel_client, name="Норм", category="к" * 65).status_code == 400


def test_повтор_названия_отвергается(panel_client):
    assert create(panel_client, name="Аска Лэнгли").status_code == 409


def test_создание_пишется_в_журнал(panel_client):
    create(panel_client)
    assert "role_add" in panel_client.state["logs"]


# ---------------------------------------------------------------------------
# Удаление
# ---------------------------------------------------------------------------

def test_свободная_роль_удаляется(panel_client):
    res = remove(panel_client)
    assert res.status_code == 200, res.text
    assert panel_client.state["deleted"] == [ROLE_ID]


@pytest.mark.parametrize("status", ["taken", "reserved"])
def test_занятую_роль_удалять_нельзя(panel_client, status):
    """Как и в чате: сначала освободить. Иначе человек лишится роли молча."""
    panel_client.state["role"]["status"] = status
    assert remove(panel_client).status_code == 409
    assert panel_client.state["deleted"] == []


def test_удаление_несуществующей(panel_client):
    assert remove(panel_client, role_id=777).status_code == 404


def test_удаление_пишется_в_журнал(panel_client):
    remove(panel_client)
    assert "role_delete" in panel_client.state["logs"]


# ---------------------------------------------------------------------------
# Переименование
# ---------------------------------------------------------------------------

def rename(client, name="Мисато", category=None, role_id=ROLE_ID):
    return client.patch(f"/api/chat-roles/{role_id}",
                        json={"chat_id": CHAT_ID, "name": name, "category": category})


def test_роль_переименовывается(panel_client, monkeypatch):
    seen = {}

    async def rename_role(chat_id, role_id, name, category):
        seen.update(role_id=role_id, name=name, category=category)
        return True

    monkeypatch.setattr(db, "rename_role", rename_role)
    assert rename(panel_client, name="Мисато Кацураги", category="NERV").status_code == 200
    assert seen == {"role_id": ROLE_ID, "name": "Мисато Кацураги", "category": "NERV"}


def test_переименование_в_занятое_имя_отклоняется(panel_client, monkeypatch):
    async def rename_role(chat_id, role_id, name, category):
        return False  # такое название уже есть

    monkeypatch.setattr(db, "rename_role", rename_role)
    assert rename(panel_client, name="Аска Лэнгли").status_code == 409


@pytest.mark.parametrize("bad", ["", "   "])
def test_переименование_без_названия(panel_client, bad):
    assert rename(panel_client, name=bad).status_code == 400


def test_переименование_несуществующей(panel_client, monkeypatch):
    monkeypatch.setattr(db, "rename_role", lambda *a, **k: None)
    assert rename(panel_client, role_id=777).status_code == 404


def test_переименование_пишется_в_журнал(panel_client, monkeypatch):
    async def rename_role(chat_id, role_id, name, category):
        return True
    monkeypatch.setattr(db, "rename_role", rename_role)
    rename(panel_client)
    assert "role_rename" in panel_client.state["logs"]
