"""Шрифты и картинки эмодзи для рендера цитат-стикеров.

Ассеты не лежат в репозитории — модуль скачивает их при первом обращении в
папку ``bot/assets`` и дальше берёт с диска. Если сети нет, шрифты падают на
системный DejaVu (как было раньше), а эмодзи — на обычную отрисовку символа
шрифтом. Стикер в этом случае выглядит хуже, но бот не ломается.
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.request
from io import BytesIO
from typing import Optional

from PIL import Image, ImageFont

logger = logging.getLogger(__name__)

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
)
FONTS_DIR = os.path.join(_ASSETS_DIR, "fonts")
EMOJI_DIR = os.path.join(_ASSETS_DIR, "emoji")

_HTTP_TIMEOUT = 20
_USER_AGENT = "Mozilla/5.0 (compatible; quote-render/1.0)"

# Noto Sans — то самое семейство, которым рисует настоящий quotly (в его
# Dockerfile ставятся системные fonts-noto, а шрифты регистрируются под
# именами NotoSans / NotoSansMono). Кириллица полная, включая казахскую.
_NOTO_BASE = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"
_FONT_SOURCES = {
    "NotoSans-Regular.ttf": f"{_NOTO_BASE}/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf": f"{_NOTO_BASE}/NotoSans/hinted/ttf/NotoSans-Bold.ttf",
    "NotoSans-Italic.ttf": f"{_NOTO_BASE}/NotoSans/hinted/ttf/NotoSans-Italic.ttf",
    "NotoSans-BoldItalic.ttf": f"{_NOTO_BASE}/NotoSans/hinted/ttf/NotoSans-BoldItalic.ttf",
    "NotoSansMono-Regular.ttf": (
        f"{_NOTO_BASE}/NotoSansMono/hinted/ttf/NotoSansMono-Regular.ttf"
    ),
}

# Запасные системные шрифты — если скачать Noto не удалось.
_FALLBACK_FONTS = {
    "NotoSans-Regular.ttf": "DejaVuSans.ttf",
    "NotoSans-Bold.ttf": "DejaVuSans-Bold.ttf",
    "NotoSans-Italic.ttf": "DejaVuSans-Oblique.ttf",
    "NotoSans-BoldItalic.ttf": "DejaVuSans-BoldOblique.ttf",
    "NotoSansMono-Regular.ttf": "DejaVuSansMono.ttf",
}
_FALLBACK_DIRS = [
    "/usr/share/fonts/truetype/dejavu/",
    "/usr/share/fonts/truetype/liberation/",
    "C:/Windows/Fonts/",
    "",
]

# Apple-эмодзи (тот же набор, что рисует quotly) — по одному PNG на эмодзи.
_EMOJI_CDN = "https://cdn.jsdelivr.net/gh/iamcal/emoji-data@master/img-apple-160"

_download_lock = threading.Lock()
_font_cache: dict = {}
_emoji_cache: dict = {}
_failed_downloads: set = set()

# Маркер «такого эмодзи нет» — чтобы отличать промах кэша от закэшированного
# отрицательного ответа и не ходить в сеть повторно.
_NO_EMOJI = Image.new("RGBA", (1, 1))


def _download(url: str, dest: str) -> bool:
    """Качает url в dest (атомарно, через временный файл). True — получилось."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read()
        if not data:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = f"{dest}.part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
        return True
    except urllib.error.HTTPError as exc:
        # 404 — рабочая ситуация: имена файлов эмодзи перебираются в
        # нескольких вариантах, промах по первому не повод шуметь в логах.
        if exc.code == 404:
            logger.debug("Ассет не найден: %s", url)
        else:
            logger.warning("Не удалось скачать ассет %s: HTTP %s", url, exc.code)
        return False
    except Exception:
        logger.warning("Не удалось скачать ассет %s", url, exc_info=True)
        return False


def _ensure_file(filename: str, url: str, directory: str) -> Optional[str]:
    """Путь к файлу ассета, скачивая его при необходимости. None — не вышло.

    Один и тот же неудавшийся адрес больше не дёргаем: иначе каждый стикер
    ждал бы таймаут на каждом отсутствующем эмодзи.
    """
    path = os.path.join(directory, filename)
    if os.path.exists(path):
        return path
    with _download_lock:
        if os.path.exists(path):
            return path
        if url in _failed_downloads:
            return None
        if _download(url, path):
            return path
        _failed_downloads.add(url)
        return None


def _system_fallback_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    name = _FALLBACK_FONTS.get(filename, "DejaVuSans.ttf")
    for directory in _FALLBACK_DIRS:
        try:
            return ImageFont.truetype(directory + name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def font(
    size: int,
    *,
    bold: bool = False,
    italic: bool = False,
    mono: bool = False,
) -> ImageFont.FreeTypeFont:
    """Шрифт нужного начертания и размера (с кэшем — Pillow грузит ttf с диска
    на каждый вызов truetype, а рендер дёргает шрифты сотни раз)."""
    if mono:
        filename = "NotoSansMono-Regular.ttf"
    elif bold and italic:
        filename = "NotoSans-BoldItalic.ttf"
    elif bold:
        filename = "NotoSans-Bold.ttf"
    elif italic:
        filename = "NotoSans-Italic.ttf"
    else:
        filename = "NotoSans-Regular.ttf"

    key = (filename, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached

    path = _ensure_file(filename, _FONT_SOURCES[filename], FONTS_DIR)
    if path:
        try:
            loaded = ImageFont.truetype(path, size)
        except Exception:
            logger.warning("Битый файл шрифта %s, беру системный", path)
            loaded = _system_fallback_font(filename, size)
    else:
        loaded = _system_fallback_font(filename, size)

    _font_cache[key] = loaded
    return loaded


_emoji_warned = False


def _warn_emoji_unavailable() -> None:
    """Один раз за жизнь процесса громко сообщает, что эмодзи не грузятся —
    иначе стикеры молча выходят без них, и причина неочевидна."""
    global _emoji_warned
    if _emoji_warned:
        return
    _emoji_warned = True
    logger.warning(
        "Не удалось получить картинки эмодзи — в стикерах-цитатах их не будет. "
        "Причину покажет: python -m quote_render --check (запускать из папки бота)"
    )


def _emoji_filenames(cluster: str) -> list:
    """Имена файлов-кандидатов для эмодзи в наборе iamcal/emoji-data.

    Там файл назван кодпоинтами через дефис, но VARIATION SELECTOR-16 (fe0f)
    в именах то есть, то нет — зависит от эмодзи. Поэтому пробуем оба
    варианта: как есть и без fe0f.
    """
    # Кодпоинт дополняется нулями до четырёх цифр: © лежит как 00a9.png, а
    # не a9.png. Более длинные коды (1f44b) формат не трогает.
    full = "-".join(f"{ord(ch):04x}" for ch in cluster)
    stripped = "-".join(f"{ord(ch):04x}" for ch in cluster if ord(ch) != 0xFE0F)
    names = [f"{full}.png"]
    if stripped and stripped != full:
        names.append(f"{stripped}.png")
    return names


def emoji_image(cluster: str, size: int) -> Optional[Image.Image]:
    """Картинка эмодзи размером size×size, либо None — если такого эмодзи в
    наборе нет или скачать не удалось (тогда зовущий рисует его шрифтом)."""
    key = (cluster, size)
    cached = _emoji_cache.get(key)
    if cached is not None:
        return cached.copy() if cached is not _NO_EMOJI else None

    path = None
    for filename in _emoji_filenames(cluster):
        path = _ensure_file(filename, f"{_EMOJI_CDN}/{filename}", EMOJI_DIR)
        if path:
            break

    if not path:
        _warn_emoji_unavailable()
        _emoji_cache[key] = _NO_EMOJI
        return None

    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
    except Exception:
        logger.warning("Не удалось открыть картинку эмодзи %s", path, exc_info=True)
        _emoji_cache[key] = _NO_EMOJI
        return None

    _emoji_cache[key] = img
    return img.copy()


_glyph_cache: dict = {}
# Кодпоинт из области для частного использования — глифа под него нет ни в
# одном нормальном шрифте, поэтому он даёт эталонный «квадратик-заглушку».
_NOTDEF_PROBE = "\U0010FFFD"


def glyph_missing(font: ImageFont.FreeTypeFont, char: str) -> bool:
    """Правда ли, что в шрифте нет глифа для символа.

    Нужно, чтобы не рисовать пустой квадрат вместо эмодзи: шрифт молча
    подставляет заглушку, и отличить её можно только сравнив растр символа с
    растром заведомо отсутствующего кодпоинта.
    """
    key = (getattr(font, "path", None), getattr(font, "size", None), char)
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached

    try:
        reference = font.getmask(_NOTDEF_PROBE)
        actual = font.getmask(char)
        missing = actual.size == reference.size and bytes(actual) == bytes(reference)
    except Exception:
        missing = False

    _glyph_cache[key] = missing
    return missing


def prefetch() -> None:
    """Прогревает шрифты (эмодзи качаются по мере встречи). Зовётся один раз
    при старте бота, чтобы первый стикер не ждал загрузки."""
    for size in (28, 30, 36, 48):
        font(size)
        font(size, bold=True)
    logger.info("Шрифты для цитат готовы (%s)", FONTS_DIR)
