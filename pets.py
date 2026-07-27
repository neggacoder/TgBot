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
HUG_GAIN = 20
KISS_GAIN = 15

# Как часто можно повторять действие.
FEED_COOLDOWN_MINUTES = 60
CARE_COOLDOWN_MINUTES = 30


# ----------------------------------------------------------------------------
# КОРМ. Кормление тратит предмет из инвентаря, а не происходит само собой:
# иначе сытость — не ограничение, а кнопка «нажми раз в час бесплатно».
#
# Товар живёт в обычном магазине чата и досеивается тем же
# db.seed_extra_shop_items, что и товары ограбления, — иначе он не доехал бы
# в чаты, где каталог магазина уже создан.
#
# Откат кормления при этом остаётся: корм ограничивает СКОЛЬКО кормлений вы
# можете себе позволить, откат — как часто. Убери одно, и второе перестаёт
# что-либо значить.
# ----------------------------------------------------------------------------
FOOD_ITEM_KEY = "korm"
FOOD_ITEM_NAME = "Корм"
FOOD_ITEM_EMOJI = "🥫"
FOOD_ITEM_PRICE = 120
FOOD_ITEM_DESCRIPTION = "Порция корма для питомца — тратится за одно кормление"

# Формат — как у robbery.ROBBERY_SHOP_ITEMS: (ключ, название, цена, описание, эмодзи).
SHOP_ITEMS: list[tuple[str, str, int, str, str]] = [
    (FOOD_ITEM_KEY, FOOD_ITEM_NAME, FOOD_ITEM_PRICE, FOOD_ITEM_DESCRIPTION, FOOD_ITEM_EMOJI),
]

# ----------------------------------------------------------------------------
# ПРОГУЛКА. Питомец умеет только отдавать проценты, которых не видно, а с
# появлением корма стал ещё и статьёй расходов. Прогулка возвращает ему
# осязаемую пользу: раз в WALK_COOLDOWN_HOURS он уходит и приносит находку.
#
# Гулять может только сытый и довольный — по тому же правилу, что и
# способности (is_active): заброшенный питомец никуда не пойдёт. Прогулка
# нагуливает аппетит и тратит немного сытости, поэтому она не бесплатный
# источник монет, а ещё одна причина держать корм под рукой.
# ----------------------------------------------------------------------------
WALK_COOLDOWN_HOURS = 6
WALK_HUNGER_COST = 10
WALK_MOOD_GAIN = 10          # гулять питомцу нравится
WALK_XP_BONUS = 5

# Монеты за прогулку: база плюс за уровень. Числа заметно ниже подработки —
# прогулка не должна конкурировать с занятиями, она приятная мелочь.
WALK_COINS_MIN = 150
WALK_COINS_MAX = 400
WALK_COINS_PER_LEVEL = 60

# Шанс, что вместо монет питомец притащит предмет (в процентах).
WALK_ITEM_CHANCE = 35


@dataclass(frozen=True)
class WalkFind:
    """Что питомец может принести. item_key=None — значит монеты."""
    text: str
    item_key: Optional[str] = None


# Находки по видам: что тащит именно этот зверь. Ключи предметов — из
# встроенного каталога магазина (db.DEFAULT_SHOP_ITEMS), чтобы находка
# гарантированно имела название и эмодзи в инвентаре.
WALK_FINDS: dict[str, tuple[WalkFind, ...]] = {
    "homyak":  (WalkFind("притащил за щекой зерно и высыпал вам под ноги", "pechenka"),
                WalkFind("нашёл потерянную кем-то пробку", "probka")),
    "popugay": (WalkFind("подобрал что-то блестящее", "fishka"),
                WalkFind("выменял у вороны погнутую скрепку", "skrepka")),
    "kot":     (WalkFind("принёс носок. Один", "nosok"),
                WalkFind("притащил камень и очень собой доволен", "kamen")),
    "pes":     (WalkFind("нашёл в кустах чей-то шарик", "sharik"),
                WalkFind("выкопал старую монетку", "fishka")),
    "lisa":    (WalkFind("стащил(а) у кого-то печенье. Не спрашивайте", "pechenka"),
                WalkFind("принёс(ла) цветок. Тоже чей-то", "cvetok")),
    "panda":   (WalkFind("приволок(ла) охапку бамбука и уснул(а)", "pechenka"),
                WalkFind("нашёл(ла) в траве цветок", "cvetok")),
    "drakon":  (WalkFind("притащил(а) что-то блестящее из своей заначки", "zvezda"),
                WalkFind("нашёл(ла) настоящий алмаз. Маленький", "diamond")),
}

# Для видов, заведённых админом, своего списка нет — берём общий.
WALK_FINDS_DEFAULT: tuple[WalkFind, ...] = (
    WalkFind("нашёл(ла) что-то блестящее", "fishka"),
    WalkFind("принёс(ла) обычный камень", "kamen"),
)


def walk_finds(pet_key: str) -> tuple[WalkFind, ...]:
    return WALK_FINDS.get(pet_key, WALK_FINDS_DEFAULT)


def walk_coins(level: int, roll: int) -> int:
    """Монеты за прогулку. roll — уже разыгранное число от WALK_COINS_MIN до
    WALK_COINS_MAX; передаётся снаружи, чтобы модуль остался без случайностей
    и проверялся тестами (так же сделано в fishing.py)."""
    return max(1, int(roll) + WALK_COINS_PER_LEVEL * max(0, int(level) - 1))


# Раздача корма админом. Намеренно меньше недельной нормы: чтобы питомец не
# проседал ниже LOW_STAT, его кормят около трёх раз в сутки, то есть больше
# двадцати кормлений в неделю. Раздача — подпорка, а не замена покупке: иначе
# корм перестал бы что-либо ограничивать.
FOOD_GRANT_AMOUNT = 10
FOOD_GRANT_COOLDOWN_DAYS = 7


# ----------------------------------------------------------------------------
# ПРОДАЖА. Возврат заведомо меньше цены покупки — иначе питомец превращается
# в бесплатный склад монет. Уровень и опыт при продаже сгорают: они нажиты
# временем, а не деньгами, и выкупить их обратно нельзя.
# ----------------------------------------------------------------------------
SELL_SHARE = 0.50


def sell_price(catalog_price: int) -> int:
    """Сколько вернут за питомца. catalog_price — цена вида В ЭТОМ ЧАТЕ
    (её правит админ), а не константа из PETS: продавать по прайсу из кода
    там, где вид подешевел, значило бы печатать монеты."""
    return max(0, int(max(0, int(catalog_price)) * SELL_SHARE))

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


# ----------------------------------------------------------------------------
# Смена способности своего питомца — платный слив, а не бесплатная перепрошивка.
# Меняется способность ОДНОГО конкретного питомца конкретного хозяина: вид в
# каталоге и питомцы других владельцев не трогаются (см. user_pets.ability —
# override поверх способности вида).
# ----------------------------------------------------------------------------
ABILITY_REROLL_SHARE = 0.30       # доля от цены вида — первая смена
ABILITY_REROLL_FLOOR = 1_000      # даже у дешёвых видов смена не бесплатна
ABILITY_REROLL_MULTIPLIER = 1.5   # каждая следующая смена ЭТОГО питомца дороже


def ability_reroll_price(catalog_price: int, rerolls_done: int) -> int:
    """Цена смены способности. Растёт с каждой сменой у этого питомца —
    иначе можно было бы перебирать способности за бесценок, пока не выпадет
    самая выгодная, и деньги никуда бы не девались."""
    base = max(ABILITY_REROLL_FLOOR, int(catalog_price * ABILITY_REROLL_SHARE))
    return int(base * (ABILITY_REROLL_MULTIPLIER ** max(0, int(rerolls_done))))


# ----------------------------------------------------------------------------
# УРОВЕНЬ ПИТОМЦА. Растёт сам по себе от времени — забытый питомец всё равно
# прокачивается, просто медленно; кормёжка и ласка (в пределах их обычных
# откатов) дают разовую прибавку сверху и растят быстрее. Чем выше уровень,
# тем сильнее СПОСОБНОСТЬ (см. level_ability_bonus) — сам питомец не меняется.
#
# Опыт хранится числом и растёт лениво по прошедшим часам, как копилка
# бизнеса, только не падает и не имеет фонового цикла — так же, как сытость
# и настроение, только в другую сторону.
# ----------------------------------------------------------------------------
MAX_PET_LEVEL = 10
XP_PER_HOUR = 1          # пассивный прирост — просто оттого, что питомец есть
XP_BONUS_FEED = 6        # разовая прибавка за кормление (раз в FEED_COOLDOWN_MINUTES)
XP_BONUS_CARE = 4        # разовая прибавка за поглаживание/поцелуй (раз в CARE_COOLDOWN_MINUTES)
LEVEL_XP_BASE = 80       # опыта нужно на 2 уровень
LEVEL_XP_GROWTH = 1.35   # во сколько раз дороже каждый следующий уровень
LEVEL_ABILITY_STEP = 2   # +N процентных пунктов к базовому проценту способности за уровень выше первого


def _build_level_thresholds() -> tuple[int, ...]:
    """Порог опыта для каждого уровня (индекс 0 — уровень 1, порог 0)."""
    thresholds = [0]
    need = float(LEVEL_XP_BASE)
    total = 0.0
    for _ in range(2, MAX_PET_LEVEL + 1):
        total += need
        thresholds.append(int(total))
        need *= LEVEL_XP_GROWTH
    return tuple(thresholds)


# Посчитан один раз при импорте — как ABILITIES и PETS рядом, а не заново на
# каждый вызов level_for_xp.
LEVEL_XP_THRESHOLDS: tuple[int, ...] = _build_level_thresholds()


def level_for_xp(xp: int) -> int:
    level = 1
    for i, threshold in enumerate(LEVEL_XP_THRESHOLDS[1:], start=2):
        if xp < threshold:
            break
        level = i
    return level


def level_progress(xp: int) -> tuple[int, int, int]:
    """(уровень, опыт с начала уровня, опыт нужный на следующий уровень).

    На максимальном уровне «нужно» и «набрано» равны — прогресс-бар просто
    полон, а не делится на ноль.
    """
    level = level_for_xp(xp)
    floor = LEVEL_XP_THRESHOLDS[level - 1]
    if level >= MAX_PET_LEVEL:
        gained = xp - floor
        return level, gained, gained
    ceiling = LEVEL_XP_THRESHOLDS[level]
    return level, xp - floor, ceiling - floor


def xp_now(stored_xp: int, hours: float) -> int:
    """Опыт прямо сейчас — растёт сам по себе, без действий хозяина.

    Капается порогом максимального уровня: цифра в базе не обязана расти
    бесконечно, если хозяин месяцами не заходит."""
    gained = int(XP_PER_HOUR * hours) if hours > 0 else 0
    return xp_add(stored_xp, gained)


def xp_add(stored_xp: int, bonus: int) -> int:
    """Разовая прибавка опыта (кормёжка, ласка) с тем же потолком, что и у
    пассивного роста — иначе прокачанный питомец копил бы в базе бесконечно
    растущее число, просто не влияющее на уровень."""
    return min(max(0, int(stored_xp)) + max(0, int(bonus)), LEVEL_XP_THRESHOLDS[-1])


def level_ability_bonus(level: int) -> int:
    """Прибавка в процентных ПУНКТАХ к базовому проценту способности."""
    return LEVEL_ABILITY_STEP * max(0, int(level) - 1)


def ability_text(key: str) -> str:
    """Человеческое описание способности. Пустая строка — способности нет."""
    ability = ABILITY_BY_KEY.get(key or "")
    if ability is None:
        return ""
    return ability.description.format(p=ability.percent)


def ability_text_at_level(key: str, level: int) -> str:
    """То же самое, но с процентом, прокачанным до этого уровня — для
    описания уже ЗАВЕДЁННОГО питомца, а не вида в каталоге."""
    ability = ABILITY_BY_KEY.get(key or "")
    if ability is None:
        return ""
    return ability.description.format(p=ability.percent + level_ability_bonus(level))


# ----------------------------------------------------------------------------
# ЭВОЛЮЦИЯ. Десятый уровень был тупиком: опыт упирается в потолок
# (LEVEL_XP_THRESHOLDS[-1]), прибавка способности застывает на +18 п.п., и
# дальше не происходит ничего. Эволюция — то, ради чего туда доходят.
#
# Даёт четыре вещи сразу: новый облик, удвоенный базовый процент способности,
# ВТОРУЮ способность и замедленный голод. Уровень при этом обнуляется и растёт
# заново до десятого, то есть прибавка за уровень копится поверх удвоенной базы.
#
# Одноразовая: второй раз тот же питомец не растёт. Иначе это бесконечная
# лестница без потолка, а весь смысл — в редкой и заметной вершине.
# ----------------------------------------------------------------------------
EVOLVE_LEVEL = MAX_PET_LEVEL       # эволюционируют только с максимального
EVOLVE_PRICE_SHARE = 1.0           # плюс цена вида в монетах
EVOLVE_ABILITY_MULTIPLIER = 2      # базовый процент способности после эволюции
EVOLVE_HUNGER_SLOWDOWN = 25        # на сколько процентов медленнее падает сытость


@dataclass(frozen=True)
class Evolution:
    name: str
    emoji: str


# Во что вырастает каждый вид. Заведённым админом видам эволюция недоступна:
# придумывать за него, кем станет его зверь, мы не можем.
EVOLUTIONS: dict[str, Evolution] = {
    "homyak":  Evolution("Капибара", "🦫"),
    "popugay": Evolution("Павлин", "🦚"),
    "kot":     Evolution("Рысь", "🐆"),
    "pes":     Evolution("Волк", "🐺"),
    "lisa":    Evolution("Кицунэ", "✨"),
    "panda":   Evolution("Великая панда", "👑"),
    "drakon":  Evolution("Дракон", "🐲"),
}


def evolution_of(pet_key: str) -> Optional[Evolution]:
    return EVOLUTIONS.get(pet_key)


def evolve_price(catalog_price: int) -> int:
    """Сколько монет стоит эволюция сверх эликсира."""
    return max(0, int(max(0, int(catalog_price)) * EVOLVE_PRICE_SHARE))


def ability_percent(key: str, level: int, evolved: bool = False) -> int:
    """Итоговый процент способности: база (у эволюционировавшего — удвоенная)
    плюс прибавка за уровень.

    Прибавка за уровень НЕ удваивается: удваивается только база. Иначе
    эволюционировавший питомец десятого уровня давал бы вчетверо больше
    обычного, а не вдвое с небольшим.
    """
    ability = ABILITY_BY_KEY.get(key or "")
    if ability is None:
        return 0
    base = ability.percent * (EVOLVE_ABILITY_MULTIPLIER if evolved else 1)
    return base + level_ability_bonus(level)


def ability_text_evolved(key: str, level: int) -> str:
    """Описание способности эволюционировавшего питомца — с удвоенной базой."""
    ability = ABILITY_BY_KEY.get(key or "")
    if ability is None:
        return ""
    return ability.description.format(p=ability_percent(key, level, evolved=True))


def hunger_now_evolved(stored: int, hours: float) -> int:
    """Сытость эволюционировавшего: падает медленнее на EVOLVE_HUNGER_SLOWDOWN
    процентов. Настроение не трогаем — им занимается «Компаньон»."""
    return hunger_now(stored, hours * (100 - EVOLVE_HUNGER_SLOWDOWN) / 100)


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
