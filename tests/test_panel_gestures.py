"""Управление РП-жестами «отн» через панель: список, добавление (валидация),
загрузка фото в rp_media. БД-функции мокаем; файловую систему — через tmp_path.
"""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(db, "add_log", _noop, raising=False)
    monkeypatch.setattr(db, "set_data", _noop, raising=False)  # _signal_action_reload
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    staff = PanelUser(id=1, username="admin", role="admin")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: staff
    c = TestClient(panel.app)
    yield c
    panel.app.dependency_overrides.clear()


def test_список_жестов_с_фото(client, monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "RP_MEDIA_ROOT", str(tmp_path))

    async def list_g(active_only=False):
        return [{
            "gesture_key": "hug", "name": "Обнять", "reply_template": "…",
            "media_folder": "hugs", "is_active": True, "sort_order": 0,
            "phrases": [{"id": 1, "phrase": "p"}], "aliases": ["обнять"],
        }]

    monkeypatch.setattr(db, "list_rel2_gestures", list_g)
    res = client.get("/api/rel-gestures")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["gestures"][0]["gesture_key"] == "hug"
    assert data["gestures"][0]["photos"] == {"mf": [], "mm": [], "ff": []}
    assert data["pairings"] == ["mf", "mm", "ff"]


def test_добавление_жеста_плохой_ключ(client):
    res = client.post("/api/rel-gestures", json={"key": "Обнять!", "name": "Обнять"})
    assert res.status_code == 400


def test_добавление_жеста_ок_и_дубль(client, monkeypatch):
    calls = {"n": 0}

    async def add(key, name, reply, folder):
        calls["n"] += 1
        return calls["n"] == 1  # первый — успех, второй — уже занят

    monkeypatch.setattr(db, "add_rel2_gesture", add)
    assert client.post("/api/rel-gestures", json={"key": "wink", "name": "Подмигнуть"}).status_code == 200
    assert client.post("/api/rel-gestures", json={"key": "wink", "name": "Подмигнуть"}).status_code == 409


def test_загрузка_фото_кладёт_файл(client, monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "RP_MEDIA_ROOT", str(tmp_path))

    async def get_g(key):
        return {"gesture_key": key, "media_folder": "hugs", "name": "Обнять",
                "reply_template": None, "is_active": True}

    monkeypatch.setattr(db, "get_rel2_gesture", get_g)
    files = {"file": ("pic.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}
    res = client.post("/api/rel-gestures/hug/photos", data={"pairing": "mf"}, files=files)
    assert res.status_code == 200, res.text
    saved_dir = tmp_path / "hugs" / "mf"
    assert saved_dir.is_dir()
    assert any(p.suffix == ".png" for p in saved_dir.iterdir())


def test_загрузка_фото_плохое_расширение(client, monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "RP_MEDIA_ROOT", str(tmp_path))

    async def get_g(key):
        return {"gesture_key": key, "media_folder": "hugs"}

    monkeypatch.setattr(db, "get_rel2_gesture", get_g)
    files = {"file": ("bad.txt", io.BytesIO(b"hi"), "text/plain")}
    res = client.post("/api/rel-gestures/hug/photos", data={"pairing": "mf"}, files=files)
    assert res.status_code == 400


def test_загрузка_фото_неверная_пара(client, monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "RP_MEDIA_ROOT", str(tmp_path))

    async def get_g(key):
        return {"gesture_key": key, "media_folder": "hugs"}

    monkeypatch.setattr(db, "get_rel2_gesture", get_g)
    files = {"file": ("pic.png", io.BytesIO(b"x"), "image/png")}
    res = client.post("/api/rel-gestures/hug/photos", data={"pairing": "xx"}, files=files)
    assert res.status_code == 400
