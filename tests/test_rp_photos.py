"""Хранилище картинок-реакций: один корень, публичная отдача, защита путей.

Эти тесты закрепляют то, что раньше разъезжалось у трёх сторон сразу: панель
загружала файлы в несуществующую папку, бот брал ссылки на сторонние сайты, а
106 реальных картинок лежали третьим местом и не использовались вообще.

Отдельно проверяется, что публичный эндпоинт /rp/… отдаёт ТОЛЬКО картинки из
хранилища: он единственный в панели работает без входа (иначе Telegram не
сможет забрать превью), и любая дыра в нём — это чтение файлов с сервера.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

import rp_photos

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client():
    return TestClient(panel.app)


@pytest.fixture
def media(tmp_path, monkeypatch):
    """Своё хранилище во временной папке — настоящие картинки не трогаем."""
    monkeypatch.setattr(rp_photos, "MEDIA_ROOT", str(tmp_path))
    d = tmp_path / "hugs" / "mf"
    d.mkdir(parents=True)
    (d / "one.jpg").write_bytes(b"\xff\xd8\xff")
    (d / "readme.txt").write_bytes(b"not a photo")
    return tmp_path


# --- один корень на всех ---------------------------------------------------

def test_панель_и_бот_смотрят_в_один_корень():
    """Расхождение этих двух путей и было причиной, по которой загрузка фото
    через панель ни на что не влияла."""
    assert panel.RP_MEDIA_ROOT == rp_photos.MEDIA_ROOT


def test_корень_хранилища_существует():
    assert os.path.isdir(rp_photos.MEDIA_ROOT), rp_photos.MEDIA_ROOT


# --- выбор файлов ----------------------------------------------------------

def test_видит_только_картинки(media):
    assert rp_photos.list_photos("hugs", "mf") == ["one.jpg"]


def test_пустая_папка_даёт_пустой_список(media):
    assert rp_photos.list_photos("hugs", "mm") == []
    assert rp_photos.list_photos("несуществующий", "mf") == []


def test_откат_на_другую_пару(media):
    """Для «оба парня» картинок нет, но есть у mf — берём оттуда, иначе жест
    остался бы без картинки навсегда."""
    url = rp_photos.pick_photo_url("hugs", "mm")
    assert url and url.endswith("/rp/hugs/mf/one.jpg"), url


def test_нет_картинок_вообще_даёт_none(media):
    assert rp_photos.pick_photo_url("kisses", "mf") is None
    assert rp_photos.pick_photo_url(None, "mf") is None


def test_ссылка_абсолютная_и_на_публичный_адрес(media, monkeypatch):
    monkeypatch.setenv("PANEL_PUBLIC_URL", "https://example.org/")
    url = rp_photos.pick_photo_url("hugs", "mf")
    assert url == "https://example.org/rp/hugs/mf/one.jpg", url


def test_путь_за_пределы_хранилища_отвергается(media):
    for pairing in ("mf", "all"):
        for folder in ("..", "../..", "hugs/../.."):
            assert rp_photos.pairing_dir(folder, pairing) is None, (folder, pairing)
    assert rp_photos.pairing_dir("hugs", "xx") is None  # пара не из белого списка


@pytest.mark.parametrize("folder", [".", "hugs/..", "./."])
def test_сам_корень_хранилища_не_отдаётся(media, folder):
    """У общей корзины в пути на один сегмент меньше, и folder вида «.»
    схлопывал бы её ровно в MEDIA_ROOT — то есть отдавал бы наружу его
    содержимое через публичную ручку /rp/…. Папка жеста всегда глубже корня."""
    assert rp_photos.pairing_dir(folder, "all") is None, folder
    assert rp_photos.photo_path(folder, "all", "one.jpg") is None, folder


# --- публичная отдача ------------------------------------------------------

def test_картинка_отдаётся_без_входа(client):
    """Единственная ручка панели без авторизации — и так задумано: превью
    забирают серверы Telegram, предъявить куку им нечем."""
    photos = rp_photos.list_photos("hugs", "mf")
    assert photos, "в репозитории должны лежать картинки для hugs/mf"
    res = client.get(f"/rp/hugs/mf/{photos[0]}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/")
    assert "immutable" in res.headers.get("cache-control", "")


@pytest.mark.parametrize("path", [
    "/rp/../../db.py",
    "/rp/hugs/mf/../../../../db.py",
    "/rp/hugs/mf/..%2f..%2fdb.py",
    "/rp/%2e%2e/%2e%2e/db.py",
    "/rp/hugs/mf/bot.py",
    "/rp/hugs/mf/nonexistent.jpg",
    "/rp/hugs/zz/whatever.jpg",
])
def test_чужой_файл_не_отдаётся(client, path):
    assert client.get(path).status_code != 200, path


def test_остальная_панель_по_прежнему_под_входом(client):
    """Публичной должна была стать ровно одна ручка, а не раздел целиком."""
    for endpoint in ("/api/rel-gestures", "/api/settings", "/api/chats"):
        assert client.get(endpoint).status_code == 401, endpoint
