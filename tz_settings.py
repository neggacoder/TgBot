"""Часовой пояс показа времени — общий разбор для бота и веб-панели.

Внутри бот ХРАНИТ всё в UTC, и так остаётся. Настройка влияет на две вещи:

  * как человек видит время в сообщениях («14:30 UTC» → «17:30 МСК»);
  * где проходит граница суток у того, что считается «раз в день» и имеет
    собственную отметку, — ежедневный бонус казино, дивиденды, час завоза
    в магазин (см. local_today()/local_hour() в bot.py).

Чего настройка НЕ трогает — разметку message_daily: там сутки были и остаются
UTC-шными, потому что таблица уже набита историей. Всё, что её читает (стата
за период, стрики, нормы, графики), обязано считать сутки по UTC — иначе одна
и та же колонка молча смешает две разные разметки дня.

Модуль намеренно чистый: ни aiogram, ни базы. Панель — отдельный процесс, и
импортировать из неё bot.py нельзя (он поднимает Bot и тянет матплотлиб), а
разъехавшийся разбор означал бы, что значение, принятое в чате, панель
отвергает — или наоборот. Настройки-обёртки, знающие про таблицу settings,
живут в bot.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "UTC"

# Короткие подписи для популярных зон — иначе в тексте стояло бы «UTC+3»,
# что читается хуже, чем «МСК». Всё, чего здесь нет, подписывается смещением
# автоматически (см. timezone_label).
TIMEZONE_LABELS = {
    "UTC": "UTC",
    "Europe/Moscow": "МСК",
    "Europe/Kaliningrad": "Калининград",
    "Europe/Samara": "Самара",
    "Europe/Kyiv": "Киев",
    "Europe/Minsk": "Минск",
    "Asia/Almaty": "Алматы",
    "Asia/Tashkent": "Ташкент",
    "Asia/Yekaterinburg": "Екатеринбург",
    "Asia/Omsk": "Омск",
    "Asia/Krasnoyarsk": "Красноярск",
    "Asia/Irkutsk": "Иркутск",
    "Asia/Yakutsk": "Якутск",
    "Asia/Vladivostok": "Владивосток",
    "Asia/Tbilisi": "Тбилиси",
    "Asia/Yerevan": "Ереван",
    "Asia/Baku": "Баку",
}

# Понятные человеку названия → канонический ключ зоны: люди пишут «мск», а не
# «Europe/Moscow».
TIMEZONE_ALIASES = {
    "мск": "Europe/Moscow", "москва": "Europe/Moscow", "msk": "Europe/Moscow",
    "московское": "Europe/Moscow", "москве": "Europe/Moscow",
    "киев": "Europe/Kyiv", "минск": "Europe/Minsk",
    "калининград": "Europe/Kaliningrad", "самара": "Europe/Samara",
    "екатеринбург": "Asia/Yekaterinburg", "омск": "Asia/Omsk",
    "красноярск": "Asia/Krasnoyarsk", "иркутск": "Asia/Irkutsk",
    "якутск": "Asia/Yakutsk", "владивосток": "Asia/Vladivostok",
    "алматы": "Asia/Almaty", "астана": "Asia/Almaty", "ташкент": "Asia/Tashkent",
    "тбилиси": "Asia/Tbilisi", "ереван": "Asia/Yerevan", "баку": "Asia/Baku",
    "utc": "UTC", "гринвич": "UTC", "gmt": "UTC", "гмт": "UTC",
}

# Знак необязателен: «gmt3», «гмт 3» и просто «3» люди пишут не реже, чем
# «+3», и отвергать их было бы придиркой — без знака считаем восток (плюс),
# как принято в разговоре про GMT.
_FIXED_OFFSET_RE = re.compile(r"^(?:utc|gmt|гмт)?([+-]?)(\d{1,2})(?::?(\d{2}))?$")


def parse_timezone(raw: Optional[str]) -> Optional[str]:
    """Приводит введённое человеком к каноническому виду.

    Понимает «Europe/Moscow», «мск», «Москва», «+3», «UTC+03:00».
    Возвращает None, если такой зоны не существует: проверяем на ВВОДЕ, чтобы
    в базу не попало значение, на котором потом упадёт любой показ времени.
    """
    text = (raw or "").strip()
    if not text:
        return None
    low = text.casefold().replace("ё", "е")
    if low in TIMEZONE_ALIASES:
        return TIMEZONE_ALIASES[low]

    fixed = _FIXED_OFFSET_RE.match(low.replace(" ", ""))
    if fixed:
        sign = fixed.group(1) or "+"
        hours, minutes = int(fixed.group(2)), int(fixed.group(3) or 0)
        if hours > 14 or minutes > 59:
            return None
        if hours == 0 and minutes == 0:
            return "UTC"
        body = f"{hours}" if not minutes else f"{hours}:{minutes:02d}"
        return f"UTC{sign}{body}"

    try:
        ZoneInfo(text)
        return text
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def tzinfo_from_name(name: Optional[str]):
    """tzinfo по каноническому имени; UTC — если имя вдруг не читается."""
    name = name or DEFAULT_TIMEZONE
    fixed = _FIXED_OFFSET_RE.match(name.casefold().replace(" ", ""))
    if fixed:
        sign = fixed.group(1) or "+"
        hours, minutes = int(fixed.group(2)), int(fixed.group(3) or 0)
        delta = timedelta(hours=hours, minutes=minutes)
        return dt_timezone(-delta if sign == "-" else delta)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        # Например, образ без пакета tzdata. Падать на каждом показе времени
        # нельзя; о подмене предупредит вызывающий код.
        return dt_timezone.utc


def timezone_available(name: Optional[str]) -> bool:
    """Реально ли зона доступна в этой системе (есть ли tzdata)."""
    name = name or DEFAULT_TIMEZONE
    if _FIXED_OFFSET_RE.match(name.casefold().replace(" ", "")) or name == "UTC":
        return True
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


def timezone_label(name: Optional[str] = None) -> str:
    """Короткая подпись зоны для текста: «МСК», «UTC», «UTC+5»."""
    name = name or DEFAULT_TIMEZONE
    if name in TIMEZONE_LABELS:
        return TIMEZONE_LABELS[name]
    if name.upper().startswith("UTC"):
        return name.upper()
    # Незнакомая зона IANA — подписываем её текущим смещением.
    offset = datetime.now(tzinfo_from_name(name)).utcoffset() or timedelta()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours}" if not minutes else f"UTC{sign}{hours}:{minutes:02d}"


def to_zone(dt, name: Optional[str]):
    """Наивное UTC-время из БД → время в указанной зоне.

    Наивное считаем UTC: именно так его пишет весь бот (datetime.utcnow()).
    Уже «осведомлённое» просто переводим.

    Голая ДАТА (datetime.date, без времени суток) возвращается как есть:
    переводить нечего — у неё нет часа, который мог бы уехать в соседние
    сутки. Проверка обязательна: у date нет ни tzinfo, ни astimezone, и без
    неё функция падала AttributeError. Так в бот и приехали сломанные
    «не в норме», «чистка по норме» и «участники за неделю» — там границы
    периода считаются именно датами.
    """
    if not isinstance(dt, datetime):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(tzinfo_from_name(name))
