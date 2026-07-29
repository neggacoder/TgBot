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


def test_чужая_гендерная_папка_не_берётся(media):
    """Раньше при пустой папке брали любую соседнюю. С появлением направления
    соседняя папка — это и есть неверное направление: картинка показывала бы
    не то, что написано в тексте жеста."""
    assert rp_photos.pick_photo_url("hugs", "mm") is None
    assert rp_photos.pick_photo_url("hugs", "fm") is None


def test_общая_корзина_под_запрет_не_попадает(media, tmp_path):
    """Она по своей природе не гендерная — одна картинка на всех, и
    направления в ней нет."""
    (tmp_path / "hugs" / "common.jpg").write_bytes(b"\xff\xd8\xff")
    url = rp_photos.pick_photo_url("hugs", "fm")
    assert url and url.endswith("/rp/hugs/all/common.jpg"), url


def test_направление_без_папки_идёт_в_корзину(media, tmp_path):
    (tmp_path / "hugs" / "common.jpg").write_bytes(b"\xff\xd8\xff")
    url = rp_photos.pick_photo_url("hugs", None)
    assert url and url.endswith("/rp/hugs/all/common.jpg"), url


def test_каждая_папка_проходит_проверку_путей():
    """pairing_dir — белый список; новая папка, не попавшая в него, отдавала
    бы None молча, и картинок в ней никто бы не увидел."""
    for pairing in rp_photos.STORAGE_PAIRINGS:
        assert rp_photos.pairing_dir("hugs", pairing) is not None, pairing


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


# ---------------------------------------------------------------------------
# Правило подбора — одно на бота и панель
# ---------------------------------------------------------------------------

def test_бот_и_панель_выбирают_одинаково():
    """Копий правила было две: своя в relationships_v2 и своя в webpanel. Обе
    теряли направление, и разойтись им было нечем — панель показывала админу
    превью, а бот присылал в чат другое.

    Проверяем не «совпали значения», а что обе стороны зовут ОДНУ функцию:
    совпадение двух копий держится ровно до первой правки.
    """
    import relationships_v2 as rel

    пары = [("м", "ж"), ("ж", "м"), ("м", "м"), ("ж", "ж"), (None, "ж"), ("др", "др")]
    for actor, target in пары:
        assert rel._rp_pairing(actor, target) == rp_photos.pairing_for(actor, target)


def test_в_панели_не_осталось_своей_копии_правила():
    """Сторож против возврата: строка вида «{g1, g2} == {"м"}» и была тем
    местом, где терялось направление."""
    import io, os
    корень = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    исходник = io.open(os.path.join(корень, "webpanel", "app.py"), encoding="utf-8").read()
    assert '{g1, g2}' not in исходник, "в панели снова своя копия правила пар"


def test_направления_попарно_различимы():
    """mf и fm обязаны быть разными строками: совпади они — вся задача
    свелась бы к переименованию папки."""
    направления = {rp_photos.pairing_for(a, b)
                   for a, b in (("м", "ж"), ("ж", "м"), ("м", "м"), ("ж", "ж"))}
    assert направления == {"mf", "fm", "mm", "ff"}
    assert set(rp_photos.PAIRINGS) == направления


# ---------------------------------------------------------------------------
# Регресс: у большинства фотки при «отн» исчезли
#
# Направление считается только по заполненной анкете, а заполняют её единицы.
# Отправив всех остальных в пустую корзину, мы лишили картинок почти весь чат:
# в mf лежит 60+ фото, в all — ноль. Честность, которой никто не видит, потому
# что смотреть не на что, честностью не является.
# ---------------------------------------------------------------------------

def test_без_анкеты_человек_считается_женщиной(media):
    """Решение пользователя: пол, не указанный в анкете, считается женским.

    Благодаря этому направление известно ВСЕГДА — «неизвестного» просто не
    бывает, и запасные папки поверх правила не нужны.
    """
    assert rp_photos.DEFAULT_GENDER == "ж"
    assert rp_photos.pairing_for("м", None) == "mf"
    assert rp_photos.pairing_for(None, "м") == "fm"
    assert rp_photos.pairing_for(None, None) == "ff"


def test_мужчина_и_человек_без_анкеты_идут_в_mf(media):
    """Тот самый пример: я мужчина, второй неизвестен — значит он ж."""
    url = rp_photos.pick_photo_url("hugs", rp_photos.pairing_for("м", None))
    assert url and url.endswith("/rp/hugs/mf/one.jpg"), url


def test_другой_пол_считается_женским():
    assert rp_photos.pairing_for("др", "м") == "fm"
    assert rp_photos.pairing_for("м", "др") == "mf"


def test_пустая_папка_уходит_в_корзину(media, tmp_path):
    """У жеста со своей общей картинкой она показывается, когда точной папки
    направления нет."""
    (tmp_path / "hugs" / "common.jpg").write_bytes(b"\xff\xd8\xff")
    url = rp_photos.pick_photo_url("hugs", "fm")
    assert url and url.endswith("/rp/hugs/all/common.jpg"), url


def test_известное_направление_нейтральную_папку_НЕ_берёт(media):
    """Главное свойство задачи и оно не должно было пострадать: если мы знаем,
    что било наоборот, картинка «М бьёт Ж» не показывается, даже когда она
    единственная в наличии."""
    assert rp_photos.pick_photo_url("hugs", "fm") is None
    assert rp_photos.pick_photo_url("hugs", "mm") is None
