"""Коллекции: награда за то, что собрано ВСЁ, а не только выгодное.

Зачем. В боте почти везде выгоднее остановиться на середине: взять два
доходных бизнеса и не трогать остальные, купить одного полезного питомца и
забыть про других. Коллекция — единственная причина добрать последнее.

Ничего не хранится отдельно: состав коллекции проверяется по тому, что уже
лежит в базе (бизнесы, питомцы, титулы, ачивки). Своей таблицы у коллекций
нет и не нужно — иначе появилось бы второе место правды, которое рано или
поздно разойдётся с первым.

Здесь только КАТАЛОГ И ПРАВИЛА, без БД и Telegram — как businesses.py рядом.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Сколько сезонов подряд нужно продержаться в призах.
SEASON_STREAK = 3


@dataclass(frozen=True)
class Collection:
    key: str
    name: str
    emoji: str
    description: str
    title_name: str        # титул, который выдаётся за полный сбор
    achievement_code: str

    @property
    def title_key(self) -> str:
        return f"collection_{self.key}"


COLLECTIONS: tuple[Collection, ...] = (
    Collection(
        "tycoon", "Промышленник", "🏢",
        "Владеть всеми видами бизнеса одновременно",
        "🏢 Промышленник", "collection_tycoon",
    ),
    Collection(
        "empire", "Империя", "👑",
        "Все бизнесы прокачаны до 3 уровня",
        "👑 Империя", "collection_empire",
    ),
    Collection(
        "zoo", "Зоопарк", "🐾",
        "Завести всех питомцев",
        "🐾 Зоопарк", "collection_zoo",
    ),
    Collection(
        "dynasty", "Династия", "🏆",
        f"Попасть в призы {SEASON_STREAK} сезона подряд",
        "🏆 Династия", "collection_dynasty",
    ),
)

BY_KEY: dict[str, Collection] = {c.key: c for c in COLLECTIONS}


def progress_text(done: int, total: int) -> str:
    """Полоса прогресса коллекции."""
    if total <= 0:
        return ""
    width = 10
    filled = max(0, min(int(round(width * done / total)), width))
    return "▰" * filled + "▱" * (width - filled)


def is_complete(done: int, total: int) -> bool:
    return total > 0 and done >= total


def season_streak_keys(current: str, previous_of, length: int = SEASON_STREAK) -> list:
    """Ключи последних length ЗАВЕРШЁННЫХ сезонов, от свежего к старому.

    Текущий не считается: он ещё идёт, призы за него не выданы, и требовать
    его в цепочке значило бы требовать невозможного.

    previous_of передаётся снаружи (seasons.previous_of), чтобы этот модуль
    не знал про устройство ключа сезона — иначе правило «как выглядит месяц»
    жило бы в двух местах.
    """
    keys: list = []
    cursor = current
    for _ in range(max(0, length)):
        cursor = previous_of(cursor)
        keys.append(cursor)
    return keys
