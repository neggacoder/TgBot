"""Поиск по ролям чата в панели (GET /api/chat-roles).

Роли чата — игровые роли участников (таблица chat_roles), которые занимают,
бронируют и освобождают из бота. Это НЕ уровни прав (webpanel/roles.py и
/api/roles) — сущности разные, слово общее, поэтому тесты заодно стерегут
границу между ними.

Слой БД подменён: проверяем ровно то, за что отвечает панель, — разбор
параметров, отказ на мусор и форму ответа.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
RESERVED_AT = datetime(2026, 7, 20, 10, 0)

# Тестовый чат: занятая роль, свободная, забронированная и заявка на модерации —
# по одной каждого состояния, которое панель обязана показать по-разному.
ROLES = [
    {
        "id": 1, "name": "Аска Лэнгли", "category": "Пилоты", "status": "taken",
        "holder_user_id": 100, "holder_full_name": "Оля", "holder_username": "olya",
        "reserved_user_id": None, "reserved_full_name": None, "reserved_username": None,
        "reserved_at": None, "approved": 1,
    },
    {
        "id": 2, "name": "Синдзи Икари", "category": "Пилоты", "status": "free",
        "holder_user_id": None, "holder_full_name": None, "holder_username": None,
        "reserved_user_id": None, "reserved_full_name": None, "reserved_username": None,
        "reserved_at": None, "approved": 1,
    },
    {
        "id": 3, "name": "Мисато Кацураги", "category": "NERV", "status": "reserved",
        "holder_user_id": None, "holder_full_name": None, "holder_username": None,
        "reserved_user_id": 200, "reserved_full_name": "Паша", "reserved_username": "pasha",
        "reserved_at": RESERVED_AT, "approved": 1,
    },
    {
        "id": 4, "name": "Каору Нагиса", "category": None, "status": "free",
        "holder_user_id": None, "holder_full_name": None, "holder_username": None,
        "reserved_user_id": None, "reserved_full_name": None, "reserved_username": None,
        "reserved_at": None, "approved": 0,
    },
]


@pytest.fixture
def panel_client(monkeypatch):
    calls = {}

    async def search_chat_roles(chat_id, *, q=None, status=None, category=None, limit=100, offset=0):
        calls["params"] = {
            "chat_id": chat_id, "q": q, "status": status,
            "category": category, "limit": limit, "offset": offset,
        }
        rows = [dict(r) for r in ROLES]
        # Заглушка повторяет договор функции БД: без фильтра статуса заявки на
        # модерации не показываются (как в list_roles с approved_only).
        if status == "pending":
            rows = [r for r in rows if not r["approved"]]
        else:
            rows = [r for r in rows if r["approved"]]
            if status:
                rows = [r for r in rows if r["status"] == status]
        if category:
            rows = [r for r in rows if r["category"] == category]
        if q:
            needle = q.casefold()
            rows = [
                r for r in rows
                if needle in (r["name"] or "").casefold()
                or needle in (r["category"] or "").casefold()
                or needle in (r["holder_full_name"] or "").casefold()
                or needle in (r["holder_username"] or "").casefold()
                or needle in (r["reserved_full_name"] or "").casefold()
                or needle in (r["reserved_username"] or "").casefold()
            ]
        return rows[offset:offset + limit], len(rows)

    async def count_chat_roles_by_status(chat_id):
        return {"free": 1, "taken": 1, "reserved": 1, "pending": 1}

    async def list_role_categories(chat_id):
        return ["NERV", "Пилоты"]

    async def fetch_settings():
        return {"role_reserve_timeout_hours": 48}

    monkeypatch.setattr(db, "search_chat_roles", search_chat_roles, raising=False)
    monkeypatch.setattr(db, "count_chat_roles_by_status", count_chat_roles_by_status, raising=False)
    monkeypatch.setattr(db, "list_role_categories", list_role_categories, raising=False)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)

    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="tester", role="admin"
    )
    client = TestClient(panel.app)
    client.calls = calls
    yield client
    panel.app.dependency_overrides.clear()


def roles(client, **params):
    res = client.get("/api/chat-roles", params={"chat_id": CHAT_ID, **params})
    assert res.status_code == 200, res.text
    return res.json()


def names(payload):
    return [r["name"] for r in payload["roles"]]


# ---------------------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected", [
    ("аска", ["Аска Лэнгли"]),           # по названию, регистр не важен
    ("пилоты", ["Аска Лэнгли", "Синдзи Икари"]),  # по категории
    ("Оля", ["Аска Лэнгли"]),            # по имени держателя
    ("pasha", ["Мисато Кацураги"]),      # по username забронировавшего
])
def test_поиск_находит(panel_client, query, expected):
    """Одно поле ищет и роль, и человека: в панели «кто такая Аска» и «что у
    Оли» — один и тот же вопрос, заданный с разных сторон."""
    assert names(roles(panel_client, q=query)) == expected


def test_пустой_поиск_отдаёт_все_одобренные(panel_client):
    assert names(roles(panel_client)) == ["Аска Лэнгли", "Синдзи Икари", "Мисато Кацураги"]


def test_ничего_не_нашлось_не_ошибка(panel_client):
    payload = roles(panel_client, q="Годзилла")
    assert payload["roles"] == [] and payload["total"] == 0


# ---------------------------------------------------------------------------
# Фильтры по статусу
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    ("free", ["Синдзи Икари"]),
    ("taken", ["Аска Лэнгли"]),
    ("reserved", ["Мисато Кацураги"]),
    ("pending", ["Каору Нагиса"]),
])
def test_фильтр_по_статусу(panel_client, status, expected):
    assert names(roles(panel_client, status=status)) == expected


def test_заявки_на_модерации_не_видны_без_фильтра(panel_client):
    """Неодобренная роль — ещё не роль чата, в общем списке ей не место."""
    assert "Каору Нагиса" not in names(roles(panel_client))


@pytest.mark.parametrize("bad", ["taken; DROP TABLE", "занята", "approved"])
def test_неизвестный_статус_отвергается(panel_client, bad):
    res = panel_client.get("/api/chat-roles", params={"chat_id": CHAT_ID, "status": bad})
    assert res.status_code == 400


def test_пустой_статус_это_отсутствие_фильтра(panel_client):
    """Фронтенд шлёт status= при сбросе чипа — это «показать все», не ошибка."""
    res = panel_client.get("/api/chat-roles", params={"chat_id": CHAT_ID, "status": ""})
    assert res.status_code == 200


def test_фильтр_по_категории(panel_client):
    assert names(roles(panel_client, category="NERV")) == ["Мисато Кацураги"]


# ---------------------------------------------------------------------------
# Форма ответа
# ---------------------------------------------------------------------------

def test_держатель_отдаётся_объектом(panel_client):
    taken = roles(panel_client, status="taken")["roles"][0]
    assert taken["holder"] == {"user_id": 100, "full_name": "Оля", "username": "olya"}
    assert taken["reserved_by"] is None


def test_свободная_роль_без_держателя_не_ломает_ответ(panel_client):
    free = roles(panel_client, status="free")["roles"][0]
    assert free["holder"] is None and free["reserved_by"] is None
    assert free["reserve_expires_at"] is None


def test_срок_брони_считается_по_настройке(panel_client):
    """48 часов из settings, а не зашитые 72: бот живёт по этой же настройке, и
    панель, показывая свой срок, врала бы про чужое правило."""
    reserved = roles(panel_client, status="reserved")["roles"][0]
    assert reserved["reserved_by"]["full_name"] == "Паша"
    assert reserved["reserve_expires_at"] == (RESERVED_AT + timedelta(hours=48)).isoformat()


def test_счётчики_и_категории(panel_client):
    payload = roles(panel_client)
    assert payload["counts"] == {"free": 1, "taken": 1, "reserved": 1, "pending": 1}
    assert payload["categories"] == ["NERV", "Пилоты"]


def test_лимит_ограничен_сверху(panel_client):
    """Иначе один запрос с limit=10**9 выкачивает всю таблицу."""
    roles(panel_client, limit=100000)
    assert panel_client.calls["params"]["limit"] <= 200
