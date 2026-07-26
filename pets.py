"""Личные питомцы: каталог, сытость и настроение.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как businesses.py рядом.

Это НЕ питомцы пары из «Отношений 2.0»: те принадлежат двоим и живут на
искрах. Эти закреплены за человеком, покупаются за i¢ и не зависят ни от
каких отношений.

Как устроены сытость и настроение. Обе величины падают сами по времени и
считаются ЛЕНИВО: в базе лежит значение и момент последнего пересчёта, а
текущее выводится из прошедших часов. Фонового цикла нет — бот может
простоять сутки и ничего не потеряет, при первом обращении досчитает.
Ровно так же устроены копилки бизнесов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MAX_STAT = 100

# За сколько единиц в час падают сытость и настроение.
HUNGER_PER_HOUR = 4
MOOD_PER_HOUR = 3

# Сколько возвращает одно действие.
FEED_GAIN = 35
PET_GAIN = 20
KISS_GAIN = 15

# Как часто можно повторять действие.
FEED_COOLDOWN_MINUTES = 60
CARE_COOLDOWN_MINUTES = 30

# Ниже этого питомец считается голодным/грустным — о нём напомнят в профиле.
LOW_STAT = 30


# ----------------------------------------------------------------------------
# СПОСОБНОСТИ. Питомец не украшение: сытый и довольный он приносит пользу.
#
# Ключевое правило — способность работает ТОЛЬКО пока питомец в порядке
# (см. is_active). Иначе кормёжка была бы обязанностью без награды: покормил,
# и ничего не изменилось. Здесь наоборот: перестал ухаживать — потерял выгоду.
#
# Каждая способность — это «сколько процентов» к одной понятной величине.
# Список готовый: при создании своего питомца админ выбирает из него, а не
# придумывает эффект, — иначе пришлось бы уметь исполнять произвольные фразы.
# ----------------------------------------------------------------------------
ABILITY_NONE = "none"


@dataclass(frozen=True)
class Ability:
    key: str
    name: str
    description: str
    percent: int


ABILITIES: tuple[Ability, ...] = (
    # --- доход от занятий ---
    Ability("farm",           "Фермер",        "+{p}% к доходу с фермы", 15),
    Ability("fishing",        "Рыболов",       "+{p}% к улову", 15),
    Ability("treasure",       "Кладоискатель", "+{p}% к найденному кладу", 15),
    Ability("side_job",       "Подмастерье",   "+{p}% к подработке", 15),
    Ability("daily_bonus",    "Талисман дня",  "+{p}% к ежедневному бонусу", 20),
    Ability("work",           "Напарник",      "+{p}% к доходу со смены", 15),
    Ability("hat",            "Зазывала",      "+{p}% к собранному шапкой", 20),
    # --- защита ---
    Ability("guard_raid",     "Сторож",        "налёт на ваш бизнес удаётся на {p}% реже", 20),
    Ability("guard_robbery",  "Телохранитель", "вас грабят успешно на {p}% реже", 20),
    Ability("guard_break",    "Механик",       "бизнес ломается на {p}% реже", 25),
    # --- нападение ---
    Ability("attack_raid",    "Наводчик",      "ваш налёт удаётся на {p}% чаще", 15),
    Ability("attack_robbery", "Подельник",     "ваше ограбление удаётся на {p}% чаще", 15),
    Ability("raid_loot",      "Скупщик",       "+{p}% к добыче с налёта", 20),
    Ability("robbery_loot",   "Барыга",        "+{p}% к добыче с ограбления", 20),
    # --- экономия ---
    Ability("discount_shop",  "Торгаш",        "скидка {p}% в магазине", 10),
    Ability("discount_repair", "Ремонтник",    "ремонт бизнеса дешевле на {p}%", 25),
    Ability("discount_upgrade", "Прораб",      "апгрейд бизнеса дешевле на {p}%", 15),
    # --- прочее ---
    Ability("boss_damage",    "Боевой",        "+{p}% к урону по боссу", 20),
    Ability("casino_win",     "Везунчик",      "+{p}% к выигрышу в казино", 15),
    Ability("lootbox",        "Нюхач",         "+{p}% к шансу редкого приза из лутбокса", 20),
    Ability("reputation",     "Обаяшка",       "+{p}% к получаемой репутации", 25),
    Ability("pet_mood",       "Компаньон",     "настроение всех ваших питомцев падает на {p}% медленнее", 30),
)

ABILITY_BY_KEY: dict[str, Ability] = {a.key: a for a in ABILITIES}


def ability_text(key: str) -> str:
    """Человеческое описание способности. Пустая строка — способности нет."""
    ability = ABILITY_BY_KEY.get(key or "")
    if ability is None:
        return ""
    return ability.description.format(p=ability.percent)


def is_active(hunger: int, mood: int) -> bool:
    """Работает ли способность прямо сейчас.

    Голодный или загрустивший питомец пользы не приносит — в этом и смысл
    ухода. Порог тот же, по которому в профиле пишется «проголодался».
    """
    return hunger >= LOW_STAT and mood >= LOW_STAT


@dataclass(frozen=True)
class Pet:
    key: str
    name: str
    emoji: str
    price: int
    sound: str      # чем отвечает на ласку
    ability: str = ABILITY_NONE

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


# Способность у каждого своя и по характеру: пёс сторожит, лиса наводит,
# панда успокаивает остальных. Так её не нужно запоминать отдельно.
PETS: tuple[Pet, ...] = (
    Pet("homyak",  "Хомяк",    "🐹",  8_000, "пыхтит",             "farm"),
    Pet("popugay", "Попугай",  "🦜", 12_000, "повторяет за вами",  "discount_shop"),
    Pet("kot",     "Кот",      "🐈", 15_000, "мурчит",             "daily_bonus"),
    Pet("pes",     "Пёс",      "🐕", 15_000, "виляет хвостом",     "guard_raid"),
    Pet("lisa",    "Лиса",     "🦊", 30_000, "хитро щурится",      "attack_raid"),
    Pet("panda",   "Панда",    "🐼", 45_000, "жуёт бамбук",        "pet_mood"),
    Pet("drakon",  "Дракончик", "🐉", 90_000, "дымит ноздрями",     "boss_damage"),
)

BY_KEY: dict[str, Pet] = {p.key: p for p in PETS}

ALIASES: dict[str, str] = {
    "кот": "kot", "котик": "kot", "кошка": "kot",
    "пёс": "pes", "пес": "pes", "собака": "pes", "щенок": "pes",
    "хомяк": "homyak", "хома": "homyak",
    "попугай": "popugay", "птица": "popugay",
    "лиса": "lisa", "лисичка": "lisa",
    "панда": "panda",
    "дракон": "drakon", "дракончик": "drakon",
}


def resolve(raw: Optional[str]) -> Optional[Pet]:
    """Питомец по ключу или по-русски. None — не нашли."""
    if not raw:
        return None
    key = " ".join(raw.strip().casefold().replace("ё", "е").split())
    # В ALIASES ключи записаны как есть, поэтому «ё» ищем и в исходном виде.
    return BY_KEY.get(ALIASES.get(key)
                      or ALIASES.get(raw.strip().casefold())
                      or key)


def decayed(value: int, hours: float, per_hour: int) -> int:
    """Во что превратилось значение через hours часов. Ниже нуля не падает.

    Округление ИМЕННО к ближайшему, а не отбрасыванием дроби. При int() любое
    сколь угодно малое прошедшее время съедало целое очко: посмотрел на
    питомца через секунду после кормления — и сытость уже на единицу меньше,
    хотя пройти успела тысячная часа.
    """
    if hours <= 0:
        return max(0, min(int(value), MAX_STAT))
    return max(0, min(int(round(value - per_hour * hours)), MAX_STAT))


def hunger_now(stored: int, hours: float) -> int:
    return decayed(stored, hours, HUNGER_PER_HOUR)


def mood_now(stored: int, hours: float) -> int:
    return decayed(stored, hours, MOOD_PER_HOUR)


def gain(value: int, amount: int) -> int:
    """Прибавка с потолком: перекормить нельзя."""
    return max(0, min(int(value) + int(amount), MAX_STAT))


def bar(value: int, width: int = 10) -> str:
    filled = max(0, min(int(round(width * value / MAX_STAT)), width))
    return "▰" * filled + "▱" * (width - filled)


def state_text(hunger: int, mood: int) -> str:
    """Одна строка о самочувствии — то, что видно в профиле."""
    if hunger <= 0:
        return "🥺 голодает"
    if hunger < LOW_STAT:
        return "🍽 проголодался"
    if mood < LOW_STAT:
        return "😔 скучает"
    return "😊 всё хорошо"
