"""Лента последних сообщений: /api/messages и SSE-поток /api/messages/stream.

Ленту наполняет бот (см. _remember_recent_message в bot.py), панель только
читает. Здесь проверяется именно чтение: порядок, точка продолжения потока и
то, что поток не задваивает и не теряет сообщения на переподключении.
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
MODER_ID = 4
PLAIN_ID = 5


def row(row_id, message_id, user_id=PLAIN_ID, text="привет", kind=None, name="Паша"):
    return {
        "id": row_id,
        "message_id": message_id,
        "user_id": user_id,
        "full_name": name,
        "username": "pasha",
        "text": text,
        "kind": kind,
        "created_at": "2026-07-20 10:00:00",
    }


@pytest.fixture
def panel_client(monkeypatch):
    """Панель с лентой из подменённой БД. state['rows'] — что «лежит» в таблице."""
    state = {"rows": []}

    async def list_recent_messages(chat_id, limit=10):
        rows = [dict(r) for r in state["rows"] if chat_id == CHAT_ID]
        return rows[-limit:]

    async def list_recent_messages_after(chat_id, after_id, limit=50):
        rows = [dict(r) for r in state["rows"] if r["id"] > after_id]
        return rows[:limit]

    async def list_admins():
        return [{"user_id": MODER_ID, "level": 1, "added_by": None}]

    async def fetch_settings():
        return {}

    monkeypatch.setenv("OWNER_IDS", "")
    monkeypatch.setattr(db, "list_recent_messages", list_recent_messages)
    monkeypatch.setattr(db, "list_recent_messages_after", list_recent_messages_after)
    monkeypatch.setattr(db, "list_admins", list_admins)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    # Поток опрашивает БД раз в 2 с — в тесте это 2 секунды простоя на запрос.
    monkeypatch.setattr(panel, "STREAM_POLL_SECONDS", 0.01)
    monkeypatch.setattr(panel, "STREAM_HEARTBEAT_SECONDS", 0.02)
    # Поток бесконечный, а TestClient при закрытии ответа дожидается, пока
    # генератор завершится сам (http.disconnect он не шлёт). Без короткого
    # предела жизни тест просто повис бы.
    monkeypatch.setattr(panel, "STREAM_MAX_SECONDS", 1.0)

    roles.invalidate()
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="tester", role="owner"
    )
    yield TestClient(panel.app), state
    panel.app.dependency_overrides.clear()
    roles.invalidate()


def read_events(client, url, want, headers=None):
    """Читает поток, пока не наберётся want сообщений (комментарии-heartbeat
    пропускаем). Соединение бесконечное, поэтому выходим сами."""
    events = []
    with client.stream("GET", url, headers=headers or {}) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if len(events) >= want:
                    break
    return events


# --- первичная загрузка -----------------------------------------------------

def test_messages_are_oldest_first(panel_client):
    """В плашке порядок как в Telegram: сверху старые, снизу новые."""
    client, state = panel_client
    state["rows"] = [row(1, 101, text="раз"), row(2, 102, text="два"), row(3, 103, text="три")]

    data = client.get("/api/messages", params={"chat_id": CHAT_ID}).json()

    assert [m["text"] for m in data["messages"]] == ["раз", "два", "три"]


def test_last_id_points_at_newest(panel_client):
    """С last_id продолжится поток — если он врёт, панель либо потеряет
    сообщения, либо покажет уже показанные."""
    client, state = panel_client
    state["rows"] = [row(7, 101), row(9, 102)]

    data = client.get("/api/messages", params={"chat_id": CHAT_ID}).json()

    assert data["last_id"] == 9


def test_empty_feed_gives_zero_last_id(panel_client):
    client, state = panel_client
    state["rows"] = []

    data = client.get("/api/messages", params={"chat_id": CHAT_ID}).json()

    assert data["messages"] == []
    assert data["last_id"] == 0


def test_messages_carry_role_labels(panel_client):
    """Приписка роли — та же, что в списке участников."""
    client, state = panel_client
    state["rows"] = [row(1, 101, user_id=MODER_ID, name="Марк"), row(2, 102, user_id=PLAIN_ID)]

    messages = client.get("/api/messages", params={"chat_id": CHAT_ID}).json()["messages"]

    assert messages[0]["role_key"] == "moder"
    assert messages[1]["role_key"] == "member"


def test_limit_is_capped(panel_client):
    """limit из адреса не должен позволять выкачать ленту целиком."""
    client, state = panel_client
    state["rows"] = [row(i, 100 + i) for i in range(1, 120)]

    messages = client.get(
        "/api/messages", params={"chat_id": CHAT_ID, "limit": 10_000}
    ).json()["messages"]

    assert len(messages) == panel.MESSAGES_MAX_LIMIT


def test_attachment_without_text_keeps_kind(panel_client):
    """У фото и голосовых текста нет — плашке нужен тип, иначе строка пустая."""
    client, state = panel_client
    state["rows"] = [row(1, 101, text=None, kind="🖼 Фото")]

    message = client.get("/api/messages", params={"chat_id": CHAT_ID}).json()["messages"][0]

    assert message["text"] is None
    assert message["kind"] == "🖼 Фото"


# --- поток ------------------------------------------------------------------

def test_stream_sends_only_new_messages(panel_client):
    """after_id отсекает уже показанное: иначе при открытии плашки все
    сообщения приехали бы по второму разу."""
    client, state = panel_client
    state["rows"] = [row(1, 101, text="старое"), row(2, 102, text="новое")]

    events = read_events(client, f"/api/messages/stream?chat_id={CHAT_ID}&after_id=1", want=1)

    assert [e["text"] for e in events] == ["новое"]


def test_stream_resumes_from_last_event_id(panel_client):
    """Браузер переподключает SSE сам и присылает Last-Event-ID. Без учёта
    этого заголовка после каждого обрыва поток слал бы всё заново."""
    client, state = panel_client
    state["rows"] = [row(1, 101, text="раз"), row(2, 102, text="два"), row(3, 103, text="три")]

    events = read_events(
        client,
        f"/api/messages/stream?chat_id={CHAT_ID}&after_id=0",
        want=1,
        headers={"Last-Event-ID": "2"},
    )

    assert [e["text"] for e in events] == ["три"]


def test_stream_event_id_matches_row_id(panel_client):
    """id события — это позиция в ленте; по нему и продолжают после обрыва."""
    client, state = panel_client
    state["rows"] = [row(5, 101)]

    with client.stream("GET", f"/api/messages/stream?chat_id={CHAT_ID}&after_id=0") as res:
        ids = []
        for line in res.iter_lines():
            if line.startswith("id:"):
                ids.append(line[3:].strip())
                break

    assert ids == ["5"]


def test_stream_sends_heartbeat_when_quiet(panel_client):
    """В молчащем чате поток обязан подавать признаки жизни, иначе прокси
    (Funnel) закроет соединение по таймауту."""
    client, state = panel_client
    state["rows"] = []

    with client.stream("GET", f"/api/messages/stream?chat_id={CHAT_ID}&after_id=0") as res:
        for line in res.iter_lines():
            if line.startswith(":"):
                assert "ping" in line
                break
        else:
            pytest.fail("heartbeat не пришёл")
