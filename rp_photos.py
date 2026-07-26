"""Хранилище картинок-реакций к РП-жестам — общее для бота и веб-панели.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Раньше каждая из трёх сторон знала о картинках своё,
и все три расходились:

  * панель загружала файлы в <репозиторий>/rp_media — папки, которой на диске
    вообще нет;
  * бот брал ссылки из словаря PHOTOS в relationships_v2 (pinimg и т.п.), то
    есть загрузка через панель ни на что не влияла;
  * а сами 106 картинок всё это время лежали в webpanel/static/rp_media.

Теперь путь один и объявлен здесь. Бот и панель импортируют этот модуль, так
что разойтись им больше нечем.

КАК КАРТИНКА ПОПАДАЕТ В ЧАТ. Telegram сам ходит за превью по ссылке, поэтому
файлы отдаёт публичный эндпоинт панели (GET /rp/{жест}/{пара}/{файл}) — без
входа: авторизоваться серверам Telegram нечем. Наружу смотрит только чтение
конкретного файла картинки, никаких списков каталога.
"""

from __future__ import annotations

import os
import random
from typing import Optional
from urllib.parse import quote

# Единственный корень хранилища: рядом со статикой панели, потому что именно
# там уже лежат картинки и оттуда же их отдаёт эндпоинт.
MEDIA_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "webpanel", "static", "rp_media"
)

# Пары по полу: mf — парень+девушка, mm — оба парня, ff — обе девушки.
PAIRINGS = ("mf", "mm", "ff")

# Общая корзина жеста: файлы, лежащие прямо в папке жеста, без подпапки пары.
# Нужна по двум причинам. Во-первых, такие файлы уже лежали на диске (папка
# smacks) и не показывались никому: подбор смотрел только в подпапки пар.
# Во-вторых, после отказа от внешних ссылок жесту, у которого картинка одна на
# всех, некуда её положить — заводить три одинаковые подпапки глупо.
COMMON_PAIRING = "all"

# Всё, что вообще может быть каталогом с картинками жеста. Именно этот набор
# — белый список для проверки путей; PAIRINGS остаётся «парами по полу».
STORAGE_PAIRINGS = PAIRINGS + (COMMON_PAIRING,)

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Публичный путь эндпоинта (см. webpanel/app.py). Держим здесь, чтобы бот
# собирал ссылку ровно на тот адрес, который панель обслуживает.
URL_PREFIX = "/rp"

# Адрес, по которому панель доступна ИЗ ИНТЕРНЕТА: по нему Telegram пойдёт за
# превью. Дефолт — тот же адрес, что бот показывает в команде «сайт».
DEFAULT_PUBLIC_URL = "https://nurasyl-aspire-a315-59.tail0a2432.ts.net/"


def public_base_url() -> str:
    """База для ссылок на картинки, без завершающего слэша."""
    return (os.getenv("PANEL_PUBLIC_URL") or DEFAULT_PUBLIC_URL).rstrip("/")


def is_photo(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in PHOTO_EXTS


def pairing_dir(folder: str, pairing: str) -> Optional[str]:
    """Абсолютный путь к папке пары или None, если он выводит за MEDIA_ROOT.

    Проверяем даже то, что сами же и собрали: folder приходит из БД, а имя
    вида «../..» превратило бы выдачу картинок в чтение произвольного файла
    с диска.

    Сам корень хранилища тоже не годится: у общей корзины (COMMON_PAIRING)
    в пути на один сегмент меньше, и folder вида «.» или «hugs/..» схлопнул бы
    её ровно в MEDIA_ROOT — то есть отдал бы наружу его содержимое через
    публичную (без входа) ручку /rp/…. Папка жеста всегда лежит ГЛУБЖЕ корня.
    """
    if not folder or pairing not in STORAGE_PAIRINGS:
        return None
    root = os.path.realpath(MEDIA_ROOT)
    # COMMON_PAIRING — это сама папка жеста, а не подпапка в ней.
    parts = (folder,) if pairing == COMMON_PAIRING else (folder, pairing)
    path = os.path.realpath(os.path.join(root, *parts))
    if not path.startswith(root + os.sep):
        return None
    return path


def list_photos(folder: str, pairing: str) -> list[str]:
    """Имена файлов-картинок в папке пары (отсортированные)."""
    directory = pairing_dir(folder, pairing)
    if not directory:
        return []
    try:
        return sorted(f for f in os.listdir(directory) if is_photo(f))
    except OSError:
        return []  # папки ещё нет — жест просто уйдёт без картинки


def photo_path(folder: str, pairing: str, filename: str) -> Optional[str]:
    """Путь к конкретному файлу — или None, если это не картинка/не наш файл."""
    directory = pairing_dir(folder, pairing)
    if not directory:
        return None
    safe = os.path.basename(filename)  # только имя, без каких-либо путей
    if not safe or not is_photo(safe):
        return None
    path = os.path.join(directory, safe)
    return path if os.path.isfile(path) else None


def photo_url(folder: str, pairing: str, filename: str, base_url: Optional[str] = None) -> str:
    base = (base_url or public_base_url()).rstrip("/")
    return f"{base}{URL_PREFIX}/{quote(folder)}/{quote(pairing)}/{quote(filename)}"


def pick_photo_url(
    folder: Optional[str], pairing: str, base_url: Optional[str] = None
) -> Optional[str]:
    """Случайная картинка для жеста и пары — уже готовой ссылкой.

    Сначала пробуем точную пару по полу, затем остальные пары, и последней —
    общую корзину жеста: у редких сочетаний картинок может не быть, и лучше
    показать чужую, чем ничего.
    """
    if not folder:
        return None
    order, seen = [], set()
    for candidate in (pairing, *STORAGE_PAIRINGS):
        if candidate not in seen and candidate in STORAGE_PAIRINGS:
            seen.add(candidate)
            order.append(candidate)
    for candidate in order:
        files = list_photos(folder, candidate)
        if files:
            return photo_url(folder, candidate, random.choice(files), base_url)
    return None


def count_photos(folder: str) -> dict[str, int]:
    """Сколько картинок у жеста по каждой корзине — для панели."""
    return {pairing: len(list_photos(folder, pairing)) for pairing in STORAGE_PAIRINGS}


def has_photos(folder: Optional[str]) -> bool:
    """Есть ли у жеста хоть одна картинка. Панели нужно, чтобы честно
    показывать «фото не залито», а не молча отправлять жест текстом."""
    if not folder:
        return False
    return any(list_photos(folder, pairing) for pairing in STORAGE_PAIRINGS)
