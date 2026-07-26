"""Боссы чата: каталог, расчёт урона и дележ награды.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как businesses.py рядом.

Смысл механики: это первое в боте занятие, где чат играет ВМЕСТЕ. Урон
человека считается из того, что он уже построил (профессия, бизнесы,
звёздность), поэтому прокачанный игрок реально полезен команде, а не просто
богаче остальных.

Награду босс приносит СВОЮ, а не из казны чата: казна может быть пуста, и
тогда победа осталась бы без выплаты. Так же устроены денежные события чата
(см. chat_events: метеорит тоже приносит монеты «извне»). Зато проигрыш —
наоборот, забирает часть казны, и это единственный способ потерять на боссе.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Сколько живёт бой и как часто можно бить.
FIGHT_MINUTES = 15
HIT_COOLDOWN_SECONDS = 45

# Базовый урон и прибавки за нажитое.
#
# Шкала подобрана так, чтобы босса нельзя было увести в одиночку. За бой
# один человек успевает 20 ударов (см. FIGHT_MINUTES/HIT_COOLDOWN_SECONDS);
# при этих числах предельно прокачанный игрок бьёт на 1350 и выдаёт за бой
# 27 000 — этого не хватает даже на самого мелкого босса. Новичок бьёт на
# 300 и приносит 6 000, то есть виден, но не решает.
#
# Разрыв между новичком и качком — 4.5 раза. Больше делать нельзя: смысл
# механики в том, что чат бьёт ВМЕСТЕ, а при разрыве в десятки раз слабые
# участники перестают что-либо значить и перестают приходить.
DAMAGE_BASE = 300
DAMAGE_PER_PROF_LEVEL = 40       # уровень профессии, 1..10  → до +400
DAMAGE_PER_BUSINESS_LEVEL = 30   # сумма уровней бизнесов, 0..15 → до +450
DAMAGE_PER_STAR = 20             # звёздность фермы, 0..10   → до +200
# Разброс удара, чтобы бой не был арифметикой.
DAMAGE_SPREAD_MIN = 0.8
DAMAGE_SPREAD_MAX = 1.2

# Сколько казны забирает победивший босс — доля.
DEFEAT_TREASURY_SHARE = 0.2

# Сколько человек получают предмет за верхние места.
TOP_REWARD_PLACES = 3


@dataclass(frozen=True)
class Boss:
    key: str
    name: str
    emoji: str
    hp: int
    pool: int          # сколько монет раздаётся при победе
    taunt: str         # чем босс грозит при появлении
    defeat_line: str   # чем всё кончится, если не добить

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


BOSSES: tuple[Boss, ...] = (
    Boss("taxman", "Налоговая проверка", "🧾", 30_000, 25_000,
         "Пришли с проверкой и требуют документы за три года.",
         "Проверка ушла довольной — и с деньгами чата."),
    Boss("raiders", "Рейдеры", "🥷", 60_000, 50_000,
         "Хотят отжать бизнесы чата. Всех сразу.",
         "Рейдеры своё забрали. В следующий раз собирайтесь быстрее."),
    Boss("karp", "Гигантский карп", "🐋", 100_000, 90_000,
         "Всплыл в чате и смотрит презрительно. Рыбалка отменяется.",
         "Карп ушёл на глубину, прихватив общий улов."),
    Boss("dragon", "Дракон", "🐉", 200_000, 200_000,
         "Сел на казну чата и заявил, что теперь она его.",
         "Дракон улетел с казной. Красиво, но дорого."),
)

BY_KEY: dict[str, Boss] = {b.key: b for b in BOSSES}


def _normalize(raw: str) -> str:
    return " ".join(raw.strip().casefold().replace("ё", "е").split())


# Название → ключ. Собирается из каталога, чтобы второй, руками выписанный
# список синонимов не разошёлся с ним (та же схема, что у событий чата).
_BY_NAME: dict[str, str] = {}
for _boss in BOSSES:
    _BY_NAME.setdefault(_normalize(_boss.key), _boss.key)
    _name = _normalize(_boss.name)
    _BY_NAME.setdefault(_name, _boss.key)
    _first = _name.split(" ")[0] if _name else ""
    if _first and _first not in _BY_NAME:
        _BY_NAME[_first] = _boss.key
    elif _first and _BY_NAME.get(_first) != _boss.key:
        _BY_NAME[_first] = ""      # неоднозначно — пусть уточнят


def resolve(raw: Optional[str]) -> Optional[Boss]:
    """Босс по ключу или названию. None — не нашли или название спорное."""
    if not raw:
        return None
    key = _BY_NAME.get(_normalize(raw))
    return BY_KEY.get(key) if key else None


def damage_for(prof_level: int, business_levels: int, star_level: int,
               roll: float = 1.0) -> int:
    """Урон одного удара.

    roll — множитель разброса (см. DAMAGE_SPREAD_*), передаётся снаружи,
    чтобы функция осталась чистой и её можно было проверить таблицей.
    """
    flat = (DAMAGE_BASE
            + max(0, int(prof_level)) * DAMAGE_PER_PROF_LEVEL
            + max(0, int(business_levels)) * DAMAGE_PER_BUSINESS_LEVEL
            + max(0, int(star_level)) * DAMAGE_PER_STAR)
    return max(1, int(flat * roll))


def split_reward(pool: int, damage_by_user: dict[int, int]) -> dict[int, int]:
    """Делит награду пропорционально нанесённому урону.

    Доля каждого округляется ВНИЗ, остаток от деления просто пропадает: так
    сумма выплат гарантированно не превысит пул. Обратный порядок (округлять
    вверх) при большом числе участников выдавал бы больше, чем босс принёс, —
    то есть печатал бы монеты из ниоткуда на каждом бою.
    """
    total = sum(v for v in damage_by_user.values() if v > 0)
    if pool <= 0 or total <= 0:
        return {}
    shares: dict[int, int] = {}
    for user_id, dealt in damage_by_user.items():
        if dealt <= 0:
            continue
        share = pool * dealt // total
        if share > 0:
            shares[user_id] = share
    return shares


def top_fighters(damage_by_user: dict[int, int], places: int = TOP_REWARD_PLACES):
    """Верхние места по урону — им полагается предмет.

    При равном уроне порядок стабильный (по user_id), чтобы результат боя не
    зависел от того, в каком порядке словарь обошёл ключи.
    """
    ranked = sorted(
        ((u, d) for u, d in damage_by_user.items() if d > 0),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return ranked[:max(0, places)]


def hp_bar(current: int, maximum: int, width: int = 12) -> str:
    """Полоса здоровья. Пока босс жив — хотя бы одно деление закрашено,
    иначе выглядит как «уже мёртв», а бой ещё идёт."""
    if maximum <= 0:
        return "▱" * width
    left = max(0, min(current, maximum))
    filled = int(width * left / maximum)
    if left > 0:
        filled = max(1, filled)
    return "▰" * filled + "▱" * (width - filled)
