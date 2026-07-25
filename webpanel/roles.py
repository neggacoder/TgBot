"""Роли участников для панели.

«Роль» здесь — это уровень прав внутри бота: тот же, что показывает бот в
чате и что даёт команда «+админ». Источники ровно те же, что у бота, чтобы
панель и чат не расходились:

  * таблица admins        — уровни 1-3 (см. db.list_admins);
  * OWNER_IDS из .env     — владельцы, уровень 99, в БД не хранятся;
  * settings.level_names  — кастомные названия уровней, если их переименовали
                            командой в чате.

Панель — отдельный процесс и bot.py импортировать не может (это подняло бы
второй экземпляр бота), поэтому константы продублированы здесь. Правите
LEVEL_NAMES в bot.py — поправьте и тут.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import db

LEVEL_MEMBER = 0
LEVEL_MODERATOR = 1
LEVEL_ADMIN = 2
LEVEL_SENIOR = 3
OWNER_LEVEL = 99

# Названия по умолчанию. Уровень 0 бот отдельно не именует (он просто «не
# админ»), но в списке участников подпись нужна каждому — иначе непонятно,
# то ли у человека нет роли, то ли панель её не смогла определить.
DEFAULT_LEVEL_NAMES = {
    LEVEL_MEMBER:    "Участник",
    LEVEL_MODERATOR: "🛡 Модератор",
    LEVEL_ADMIN:     "⭐ Администратор",
    LEVEL_SENIOR:    "👑 Старший администратор",
    OWNER_LEVEL:     "🔱 Владелец",
}

# Ключ уровня — для CSS-класса бейджа и для фильтра в адресе запроса.
LEVEL_KEYS = {
    LEVEL_MEMBER: "member",
    LEVEL_MODERATOR: "moder",
    LEVEL_ADMIN: "admin",
    LEVEL_SENIOR: "senior",
    OWNER_LEVEL: "owner",
}
KEY_LEVELS = {key: level for level, key in LEVEL_KEYS.items()}

# Слова, по которым роль находится обычным поиском в строке — чтобы «модер»
# в поле поиска работало так же, как выбор роли в выпадающем списке.
LEVEL_ALIASES = {
    LEVEL_MEMBER: ("участник", "member", "без роли", "нет роли"),
    LEVEL_MODERATOR: ("модератор", "модер", "мод", "moder"),
    LEVEL_ADMIN: ("администратор", "админ", "admin"),
    LEVEL_SENIOR: ("старший администратор", "старший", "сеньор", "senior"),
    OWNER_LEVEL: ("владелец", "овнер", "owner", "создатель"),
}


# Награды (медали): 8 степеней, порог доступа к каждой хранится в БД
# (reward_degree_levels) с фолбэком на формулу по умолчанию — дублирует
# _default_reward_degree_level из bot.py, править вместе с ней.
REWARD_DEGREE_EMOJI = {
    1: "🎗", 2: "🥉", 3: "🥈", 4: "🥇", 5: "🎖", 6: "🏅", 7: "🏆", 8: "🏵",
}


def default_reward_degree_level(degree: int) -> int:
    if degree == 1:
        return LEVEL_MEMBER
    if degree <= 3:
        return LEVEL_MODERATOR
    if degree == 4:
        return LEVEL_ADMIN
    if degree == 5:
        return LEVEL_SENIOR
    return OWNER_LEVEL


def owner_ids() -> set[int]:
    raw = os.getenv("OWNER_IDS", os.getenv("ADMIN_IDS", ""))
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}


class RoleMap:
    """Готовая таблица «кто какого уровня» + названия уровней."""

    def __init__(self, levels: dict[int, int], names: dict[int, str]):
        self._levels = levels
        self._names = names

    def level_of(self, user_id: int) -> int:
        return self._levels.get(int(user_id), LEVEL_MEMBER)

    def name_of(self, level: int) -> str:
        return self._names.get(level) or DEFAULT_LEVEL_NAMES.get(level) or f"Уровень {level}"

    def describe(self, user_id: int) -> dict:
        """Поля роли, которые панель дописывает к любому участнику."""
        level = self.level_of(user_id)
        return {
            "level": level,
            "role": self.name_of(level),
            "role_key": LEVEL_KEYS.get(level, "member"),
        }

    def annotate(self, rows: list[dict], id_key: str = "user_id") -> list[dict]:
        """Дописывает роль каждому участнику списка. Строки из БД приходят как
        обычные dict — правим их на месте, копия тут ни к чему."""
        for row in rows:
            if row.get(id_key) is not None:
                row.update(self.describe(row[id_key]))
        return rows

    def matches(self, user_id: int, needle: str) -> bool:
        """Совпадает ли роль участника с поисковым запросом («модер», «владелец»…)."""
        level = self.level_of(user_id)
        if needle in self.name_of(level).casefold():
            return True
        return any(needle in alias for alias in LEVEL_ALIASES.get(level, ()))

    def catalog(self) -> list[dict]:
        """Список ролей для выпадающего фильтра — от старших к младшим."""
        return [
            {"key": LEVEL_KEYS[level], "level": level, "name": self.name_of(level)}
            for level in (OWNER_LEVEL, LEVEL_SENIOR, LEVEL_ADMIN, LEVEL_MODERATOR, LEVEL_MEMBER)
        ]


# Роли меняются редко, а нужны почти в каждом ответе (участники, подсказки,
# статистика). Держим короткий кэш, чтобы не ходить в БД по два запроса на
# каждый чих; 30 секунд — незаметно для человека, который только что выдал
# кому-то права и обновляет страницу.
_CACHE_TTL = 30.0
_cache: Optional[RoleMap] = None
_cache_at = 0.0


async def load(force: bool = False) -> RoleMap:
    global _cache, _cache_at
    if not force and _cache is not None and (time.monotonic() - _cache_at) < _CACHE_TTL:
        return _cache

    levels = {int(row["user_id"]): int(row["level"]) for row in await db.list_admins()}
    # Владелец из .env стоит выше любого уровня из таблицы — перетираем.
    for owner_id in owner_ids():
        levels[owner_id] = OWNER_LEVEL

    names = dict(DEFAULT_LEVEL_NAMES)
    settings = await db.fetch_settings() or {}
    raw = settings.get("level_names")
    if raw:
        try:
            names.update({int(k): v for k, v in json.loads(raw).items() if v})
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    _cache = RoleMap(levels, names)
    _cache_at = time.monotonic()
    return _cache


def invalidate() -> None:
    """Сбросить кэш — после действий, которые могли поменять уровни.

    Обнуляем именно сам кэш, а не только отметку времени: time.monotonic() на
    свежезагруженной машине может быть меньше _CACHE_TTL, и сброс «на ноль»
    тогда ничего бы не сбросил."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0
