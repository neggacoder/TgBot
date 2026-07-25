"""Статистика чата в панели (GET /api/stats).

Эндпоинт уже отдавал топы и счётчики; здесь проверяется добавленная аналитика:
ряд активности по дням (с заполнением пустых дней нулями) и по часам за
последние сутки (ровно 24 корзины), плюс сводные числа для плиток-метрик.

Заполнение пропусков — на сервере: график не должен «схлопывать» дни без
сообщений, иначе ось времени врёт (три дня подряд с нулём выглядели бы как
один день).
"""

from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import db
from webpanel import roles
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
TODAY = date(2026, 7, 21)


@pytest.fixture
def panel_client(monkeypatch):
    # Активность за 4 дня: в один из дней сообщений не было вовсе (пропуск).
    daily = [
        {"day": date(2026, 7, 18), "message_count": 10},
        {"day": date(2026, 7, 19), "message_count": 40},
        # 20-е пропущено — 0 сообщений
        {"day": date(2026, 7, 21), "message_count": 25},
    ]
    hourly = [
        {"day": date(2026, 7, 21), "hour": 9, "message_count": 5},
        {"day": date(2026, 7, 21), "hour": 14, "message_count": 30},
    ]

    async def count_messages_since(chat_id, days):
        return sum(d["message_count"] for d in daily)

    async def get_top_active_since(chat_id, days, limit=5):
        return [{"user_id": 100, "full_name": "Оля", "username": "olya", "total": 40}]

    async def get_reputation_top(chat_id, limit=10):
        return []

    async def get_achievements_top(chat_id, limit=10):
        return []

    async def get_new_members_since(chat_id, days, limit=20):
        return [{"user_id": 200, "full_name": "Новичок", "username": None}]

    async def list_daily_counts_for_chat(chat_id, since_day):
        return [dict(d) for d in daily if d["day"] >= since_day]

    async def list_hourly_last_24h_for_chat(chat_id):
        return [dict(h) for h in hourly]

    for name, fn in [
        ("count_messages_since", count_messages_since),
        ("get_top_active_since", get_top_active_since),
        ("get_reputation_top", get_reputation_top),
        ("get_achievements_top", get_achievements_top),
        ("get_new_members_since", get_new_members_since),
        ("list_daily_counts_for_chat", list_daily_counts_for_chat),
        ("list_hourly_last_24h_for_chat", list_hourly_last_24h_for_chat),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    # roles.load() дергается для аннотации топов — подменяем на пустую карту.
    class FakeRoleMap:
        def annotate(self, rows):
            return rows

    async def fake_load():
        return FakeRoleMap()

    monkeypatch.setattr(roles, "load", fake_load)
    # фиксируем «сегодня», чтобы ряд дней был детерминированным
    monkeypatch.setattr(panel, "_stats_today", lambda: TODAY, raising=False)

    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="owner", role="owner")
    client = TestClient(panel.app)
    yield client
    panel.app.dependency_overrides.clear()


def stats(client, days=4):
    res = client.get("/api/stats", params={"chat_id": CHAT_ID, "days": days})
    assert res.status_code == 200, res.text
    return res.json()


def test_старые_поля_на_месте(panel_client):
    """Обогащение не должно ломать то, что вкладка уже показывала."""
    data = stats(panel_client)
    assert data["messages"] == 75
    assert data["top_active"][0]["full_name"] == "Оля"
    assert len(data["newcomers"]) == 1


def test_ряд_по_дням_непрерывный(panel_client):
    """4 дня — 4 точки, включая пустой день с нулём: пропуски заполнены."""
    daily = stats(panel_client, days=4)["daily"]
    assert [d["count"] for d in daily] == [10, 40, 0, 25]
    assert [d["day"] for d in daily] == ["2026-07-18", "2026-07-19", "2026-07-20", "2026-07-21"]


def test_число_точек_равно_числу_дней(panel_client):
    assert len(stats(panel_client, days=7)["daily"]) == 7


def test_ряд_по_часам_ровно_24_корзины(panel_client):
    hourly = stats(panel_client)["hourly"]
    assert len(hourly) == 24
    counts = {h["hour"]: h["count"] for h in hourly}
    assert counts[9] == 5 and counts[14] == 30
    # час без сообщений присутствует нулём, а не пропущен
    assert counts[3] == 0


def test_сводка_для_плиток(panel_client):
    data = stats(panel_client)
    summary = data["summary"]
    assert summary["total"] == 75
    assert summary["active_users"] == 1
    assert summary["newcomers"] == 1
    # пик дня — 19-е с 40 сообщениями
    assert summary["peak_day"]["count"] == 40
    assert summary["peak_day"]["day"] == "2026-07-19"
    # пик часа — 14:00 с 30
    assert summary["peak_hour"]["hour"] == 14
    assert summary["peak_hour"]["count"] == 30


def test_пустой_чат_не_ломается(panel_client, monkeypatch):
    async def empty_daily(chat_id, since_day):
        return []

    async def empty_hourly(chat_id):
        return []

    async def zero_messages(chat_id, days):
        return 0

    monkeypatch.setattr(db, "list_daily_counts_for_chat", empty_daily)
    monkeypatch.setattr(db, "list_hourly_last_24h_for_chat", empty_hourly)
    monkeypatch.setattr(db, "count_messages_since", zero_messages)

    data = stats(panel_client)
    assert all(d["count"] == 0 for d in data["daily"])
    assert len(data["hourly"]) == 24
    # пик пустого чата — не падение, а нули
    assert data["summary"]["peak_day"]["count"] == 0
    assert data["summary"]["peak_hour"]["count"] == 0
