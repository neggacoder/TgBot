"""Сезоны: месячный зачёт и награды, которые больше никогда не выдадут.

Зачем это вообще. В боте всё бесконечно повторяемо: любую вещь, титул и
ачивку можно получить в любой момент, опоздать невозможно. Поэтому ничто в
нём по-настоящему не редкое. Сезон — единственное место, где ценность даёт
не сумма денег, а то, что человек был здесь в конкретный месяц и был первым.

Награда — только титул и ачивка. Оба не предметы: их нельзя подарить,
продать и нельзя потерять (user_titles ни в одном месте кода не удаляется).
Питомцев и вещи сюда намеренно не берём — их можно украсть медвежатником
или продать, а сезонная награда обязана быть неотчуждаемой.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как businesses.py рядом.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

# Сколько человек получают награды.
PLACES = 3

# Из чего складывается счёт. Смысл именно в СМЕСИ: за один источник его
# накрутили бы (проще всего — спамом сообщений), а так придётся и писать,
# и играть, и бить боссов.
POINTS_PER_MESSAGE = 1
POINTS_PER_BOSS_DAMAGE = 0.01     # 100 урона = 1 очко
POINTS_PER_1000_COINS = 5         # за собранный доход бизнеса

# Сколько сообщений подряд максимум идёт в зачёт за раз — грубая защита от
# простыни из односимвольных сообщений. Точную антинакрутку здесь не строим:
# у бота уже есть медленный режим и словофильтр.
MESSAGE_POINTS_CAP_PER_DAY = 300

PLACE_TITLES = {
    1: ("🥇", "Чемпион сезона"),
    2: ("🥈", "Призёр сезона"),
    3: ("🥉", "Бронза сезона"),
}


@dataclass(frozen=True)
class SeasonAward:
    place: int
    title_key: str
    title_name: str
    achievement_code: str


def season_key(day: date) -> str:
    """Ключ сезона по дате — календарный месяц. «2026-07»."""
    return f"{day.year:04d}-{day.month:02d}"


def previous_season_key(day: date) -> str:
    """Сезон, предшествующий тому, в котором лежит день."""
    year, month = day.year, day.month
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def previous_of(key: str) -> str:
    """Предыдущий сезон по КЛЮЧУ, а не по дате. Нужно, чтобы отмотать цепочку
    месяцев назад, не выдумывая для этого фиктивных дат."""
    try:
        year, month = (int(part) for part in key.split("-"))
    except ValueError:
        return key
    if month <= 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def season_label(key: str) -> str:
    """Человеческое название сезона: «июль 2026»."""
    months = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
    try:
        year, month = key.split("-")
        return f"{months[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return key


def award_for(season: str, place: int) -> Optional[SeasonAward]:
    """Что полагается за место. None — место вне призов.

    Ключ титула включает сезон, поэтому каждый месяц выдаётся НОВЫЙ титул:
    «Чемпион сезона июль 2026» и «Чемпион сезона август 2026» — разные вещи,
    и обладателя первого второй раз получить уже невозможно.
    """
    meta = PLACE_TITLES.get(place)
    if meta is None:
        return None
    emoji, name = meta
    return SeasonAward(
        place=place,
        title_key=f"season_{season}_{place}",
        title_name=f"{emoji} {name} {season_label(season)}"[:64],
        achievement_code=f"season_{place}",
    )


def points_for_messages(count: int) -> int:
    return max(0, min(int(count), MESSAGE_POINTS_CAP_PER_DAY)) * POINTS_PER_MESSAGE


def points_for_boss_damage(damage: int) -> int:
    return max(0, int(max(0, damage) * POINTS_PER_BOSS_DAMAGE))


def points_for_coins(coins: int) -> int:
    return max(0, int(max(0, coins) / 1000 * POINTS_PER_1000_COINS))


def rank(scores: dict[int, int]) -> list[tuple[int, int]]:
    """Места по очкам, убыванием. При равенстве — по user_id, чтобы итог не
    зависел от порядка обхода словаря."""
    return sorted(
        ((user, points) for user, points in scores.items() if points > 0),
        key=lambda pair: (-pair[1], pair[0]),
    )


def winners(scores: dict[int, int], places: int = PLACES) -> list[tuple[int, int]]:
    return rank(scores)[:max(0, places)]
