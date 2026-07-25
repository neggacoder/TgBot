"""Роли участников в панели: приписки и поиск (webpanel/roles.py, /api/members).

Роль здесь — уровень прав внутри бота. Панель обязана показывать ту же
подпись, что человек видит в чате, включая переименованные уровни, иначе
модератор в панели и модератор в Telegram будут выглядеть как разные вещи.
"""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

import db
from webpanel import roles
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890

OWNER_ID = 1
SENIOR_ID = 2
ADMIN_ID = 3
MODER_ID = 4
PLAIN_ID = 5

MEMBERS = [
    {"user_id": OWNER_ID, "full_name": "Оля", "username": "olya"},
    {"user_id": SENIOR_ID, "full_name": "Семён", "username": "semen"},
    {"user_id": ADMIN_ID, "full_name": "Алла", "username": "alla"},
    {"user_id": MODER_ID, "full_name": "Марк", "username": "mark"},
    {"user_id": PLAIN_ID, "full_name": "Паша", "username": "pasha"},
]


@pytest.fixture
def panel_client(monkeypatch):
    monkeypatch.setenv("OWNER_IDS", str(OWNER_ID))

    async def list_admins():
        return [
            {"user_id": SENIOR_ID, "level": 3, "added_by": None},
            {"user_id": ADMIN_ID, "level": 2, "added_by": None},
            {"user_id": MODER_ID, "level": 1, "added_by": None},
        ]

    async def fetch_settings():
        return {}

    async def list_known_users(chat_id, limit=10, offset=0):
        # копии: annotate дописывает роль прямо в строки
        return [dict(m) for m in MEMBERS], len(MEMBERS)

    async def list_current_users_with_counts(chat_id, limit=500):
        # /api/members смотрит в current_users (не known_users) — не должен
        # захламляться участниками, которые уже вышли из чата.
        return [dict(m) for m in MEMBERS]

    monkeypatch.setattr(db, "list_admins", list_admins)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    monkeypatch.setattr(db, "list_known_users", list_known_users)
    monkeypatch.setattr(db, "list_current_users_with_counts", list_current_users_with_counts)

    roles.invalidate()  # кэш ролей живёт 30 с — между тестами он бы протух не вовремя
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="tester", role="owner"
    )
    yield TestClient(panel.app)
    panel.app.dependency_overrides.clear()
    roles.invalidate()


def members(client, **params):
    res = client.get("/api/members", params={"chat_id": CHAT_ID, **params})
    assert res.status_code == 200, res.text
    return res.json()["members"]


def test_every_member_gets_a_role_label(panel_client):
    """Приписка есть у каждого — у обычного участника тоже, иначе пустое место
    читается как «панель не смогла определить»."""
    by_id = {m["user_id"]: m for m in members(panel_client)}

    assert by_id[OWNER_ID]["role_key"] == "owner"
    assert by_id[SENIOR_ID]["role_key"] == "senior"
    assert by_id[ADMIN_ID]["role_key"] == "admin"
    assert by_id[MODER_ID]["role_key"] == "moder"
    assert by_id[PLAIN_ID]["role_key"] == "member"
    assert all(m.get("role") for m in by_id.values())


def test_owner_from_env_outranks_admins_table(panel_client):
    """Владелец из .env выше любого уровня из таблицы и в ней не хранится."""
    by_id = {m["user_id"]: m for m in members(panel_client)}
    assert by_id[OWNER_ID]["level"] == roles.OWNER_LEVEL


def test_filter_by_role_key(panel_client):
    found = members(panel_client, role="moder")
    assert [m["user_id"] for m in found] == [MODER_ID]


def test_unknown_role_is_rejected(panel_client):
    res = panel_client.get("/api/members", params={"chat_id": CHAT_ID, "role": "boss"})
    assert res.status_code == 400


def test_text_search_finds_by_role_word(panel_client):
    """«модер» в общем поиске находит модераторов — чтобы не заставлять лезть
    в отдельный список."""
    found = members(panel_client, q="модер")
    assert [m["user_id"] for m in found] == [MODER_ID]


def test_text_search_still_finds_by_name(panel_client):
    found = members(panel_client, q="паша")
    assert [m["user_id"] for m in found] == [PLAIN_ID]


def test_custom_level_names_are_used(panel_client, monkeypatch):
    """Уровни переименовали командой в чате — панель показывает новое название."""
    async def fetch_settings():
        return {"level_names": json.dumps({"1": "🐺 Смотрящий"}, ensure_ascii=False)}

    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    roles.invalidate()

    by_id = {m["user_id"]: m for m in members(panel_client)}
    assert by_id[MODER_ID]["role"] == "🐺 Смотрящий"
    # и поиск идёт по новому названию тоже
    assert [m["user_id"] for m in members(panel_client, q="смотрящий")] == [MODER_ID]


def test_roles_catalog_endpoint(panel_client):
    res = panel_client.get("/api/roles")
    assert res.status_code == 200
    keys = [r["key"] for r in res.json()["roles"]]
    assert keys == ["owner", "senior", "admin", "moder", "member"]
