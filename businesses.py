"""Бизнесы: каталог, уровни, налог на снятие дохода.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и без Telegram — чтобы баланс можно было
править и проверять тестами, не поднимая бота (как chat_events.py рядом).

Как устроен доход. Бизнес копит деньги сам по себе, без фоновых задач: в базе
лежит «сколько уже накоплено» и «с какого момента копим», а текущая сумма
считается на лету по прошедшему времени и упирается в потолок уровня. Потолок
существует, чтобы бизнес нужно было навещать: копилка переполняется примерно
за 4 часа, дальше деньги просто не идут.

Снять накопленное можно только с налогом — он тем больше, чем крупнее сумма
(см. tax_for). Налог считается ПО ЧАСТЯМ, как подоходный: каждая ступень
облагает только свой кусок суммы. Это не придирка к точности, а защита от
дыры: при «одна ставка на всю сумму» забрать 2001 было бы выгоднее не целиком,
а по частям, и игроки бы этим и занимались вместо игры.
"""

from __future__ import annotations

from typing import Optional

from dataclasses import dataclass

MAX_LEVEL = 3

# Во сколько обходится следующий уровень — доля от ЦЕНЫ бизнеса.
# Ключ — уровень, НА который поднимаемся.
UPGRADE_COST_SHARE = {2: 0.20, 3: 0.50}

# Сколько возвращает бот, если сдать бизнес ему, — доля от цены покупки.
# Улучшения при этом сгорают: бот платит за сам бизнес, а не за вложения.
BUYBACK_SHARE = 0.70

# Ступени налога: (верхняя граница куска, процент). None — «всё, что выше».
# Каждая ступень облагает только свою часть суммы.
TAX_BRACKETS: tuple[tuple[int | None, int], ...] = (
    (2_000, 5),
    (5_000, 10),
    (10_000, 15),
    (None, 20),
)


@dataclass(frozen=True)
class Business:
    key: str
    name: str
    price: int
    # По одному кортежу (доход в час, потолок накопления) на каждый уровень.
    levels: tuple[tuple[int, int], ...]

    def income(self, level: int) -> int:
        return self.levels[self._index(level)][0]

    def cap(self, level: int) -> int:
        return self.levels[self._index(level)][1]

    def upgrade_cost(self, to_level: int) -> int:
        """Цена подъёма НА уровень to_level. 0 — подниматься некуда."""
        share = UPGRADE_COST_SHARE.get(to_level)
        return int(self.price * share) if share else 0

    def buyback(self) -> int:
        """Сколько вернёт бот за этот бизнес."""
        return int(self.price * BUYBACK_SHARE)

    @staticmethod
    def _index(level: int) -> int:
        return max(1, min(int(level), MAX_LEVEL)) - 1


# Цифры целиком из спецификации. Единственное, что стоит знать при правке:
# у 14 из 15 клеток потолок ровно вчетверо больше часового дохода, и только
# у Ювелирной на 2 уровне он выше (6500 вместо 6000) — это не опечатка,
# так задумано, и тест это фиксирует отдельной строкой.
BUSINESSES: tuple[Business, ...] = (
    Business("shaurma",  "🌯 Ларёк с шаурмой",      12_500,
             ((250, 1_000), (300, 1_200), (500, 2_000))),
    Business("magazin",  "🛒 Продуктовый магазин",  25_000,
             ((500, 2_000), (750, 3_000), (1_000, 4_000))),
    Business("juvelirka", "💍 Ювелирная",           50_000,
             ((1_250, 5_000), (1_500, 6_500), (2_000, 8_000))),
    Business("avtosalon", "🚗 Автосалон",           75_000,
             ((2_000, 8_000), (2_500, 10_000), (3_000, 12_000))),
    Business("aeroport", "✈️ Аэропорт",            100_000,
             ((3_250, 13_000), (3_750, 15_000), (4_250, 17_000))),
)

BY_KEY: dict[str, Business] = {b.key: b for b in BUSINESSES}

# Человеческие названия для ввода: «бизнес купить шаурма» должно работать так
# же, как «бизнес купить shaurma». Ключи здесь — уже приведённые к нижнему
# регистру слова, которые люди реально напишут.
ALIASES: dict[str, str] = {
    "шаурма": "shaurma", "ларёк": "shaurma", "ларек": "shaurma", "шаурмичная": "shaurma",
    "магазин": "magazin", "продуктовый": "magazin", "продукты": "magazin",
    "ювелирка": "juvelirka", "ювелирная": "juvelirka", "ювелирный": "juvelirka",
    "автосалон": "avtosalon", "авто": "avtosalon", "салон": "avtosalon",
    "аэропорт": "aeroport", "аэро": "aeroport",
}


def resolve(raw: str) -> Business | None:
    """Бизнес по ключу или человеческому названию. None — не нашли."""
    if not raw:
        return None
    key = raw.strip().casefold()
    return BY_KEY.get(ALIASES.get(key, key))


def tax_for(amount: int) -> int:
    """Налог с суммы, по ступеням TAX_BRACKETS.

    Округление вниз — в пользу игрока: копейка спора не стоит, а лишний
    коин налога с каждого снятия выглядит как обман.
    """
    if amount <= 0:
        return 0
    tax = 0.0
    lower = 0
    for upper, percent in TAX_BRACKETS:
        top = amount if upper is None else min(amount, upper)
        if top > lower:
            tax += (top - lower) * percent / 100
            lower = top
        if upper is not None and amount <= upper:
            break
    return int(tax)


# ----------------------------------------------------------------------------
# Оснащение бизнеса: разовые покупки, которые остаются с бизнесом навсегда.
#
# Отличие от УРОВНЯ: уровень поднимает всё сразу и стоит дорого, оснащение —
# точечное и покупается в любом порядке. Отличие от предметов магазина: те
# тратятся, эти стоят на месте.
#
# Оснащение НЕ переносится при продаже вместе с бизнесом (см. bot.py): иначе
# перепродажа прокачанного бизнеса стала бы выгоднее, чем его содержание.
# ----------------------------------------------------------------------------
UPGRADE_GUARD = "ohrana"
UPGRADE_GEAR = "apparatura"
UPGRADE_ADS = "reklama"
UPGRADE_SAFE = "seif"


@dataclass(frozen=True)
class Upgrade:
    key: str
    name: str
    emoji: str
    price_share: float     # доля от цены бизнеса
    description: str

    def price(self, business: "Business") -> int:
        return max(1, int(business.price * self.price_share))


# Насколько сильно каждое оснащение меняет свою величину.
GUARD_RAID_PENALTY = 25     # на столько процентных пунктов падает шанс налёта
GEAR_BREAK_FACTOR = 0.5     # во столько раз реже ломается
ADS_INCOME_PERCENT = 15     # +% к доходу в час
SAFE_CAP_PERCENT = 50       # +% к потолку копилки

UPGRADES: tuple[Upgrade, ...] = (
    Upgrade(UPGRADE_GUARD, "Охрана", "🛡", 0.30,
            f"Налёт на этот бизнес удаётся на {GUARD_RAID_PENALTY}% реже"),
    Upgrade(UPGRADE_GEAR, "Хорошая аппаратура", "🔧", 0.30,
            "Бизнес ломается вдвое реже"),
    Upgrade(UPGRADE_ADS, "Реклама", "📢", 0.35,
            f"Доход в час выше на {ADS_INCOME_PERCENT}%"),
    Upgrade(UPGRADE_SAFE, "Сейф", "🏦", 0.25,
            f"Копилка вмещает на {SAFE_CAP_PERCENT}% больше"),
)

UPGRADE_BY_KEY: dict[str, Upgrade] = {u.key: u for u in UPGRADES}

UPGRADE_ALIASES: dict[str, str] = {
    "охрана": UPGRADE_GUARD, "охранник": UPGRADE_GUARD, "сторож": UPGRADE_GUARD,
    "аппаратура": UPGRADE_GEAR, "оборудование": UPGRADE_GEAR, "техника": UPGRADE_GEAR,
    "реклама": UPGRADE_ADS, "маркетинг": UPGRADE_ADS,
    "сейф": UPGRADE_SAFE, "склад": UPGRADE_SAFE,
}


def resolve_upgrade(raw: str) -> Optional[Upgrade]:
    if not raw:
        return None
    key = raw.strip().casefold()
    return UPGRADE_BY_KEY.get(UPGRADE_ALIASES.get(key, key))


def effective_income(business: Business, level: int, upgrades) -> int:
    """Доход в час с учётом оснащения."""
    income = business.income(level)
    if UPGRADE_ADS in upgrades:
        income = int(income * (100 + ADS_INCOME_PERCENT) / 100)
    return max(1, income)


def effective_cap(business: Business, level: int, upgrades) -> int:
    """Потолок копилки с учётом оснащения."""
    cap = business.cap(level)
    if UPGRADE_SAFE in upgrades:
        cap = int(cap * (100 + SAFE_CAP_PERCENT) / 100)
    return max(1, cap)


def accrued_now(level: int, business: Business, stored: int, hours: float,
                upgrades=()) -> int:
    """Сколько накоплено сейчас: то, что лежало, плюс доход за прошедшее время,
    но не выше потолка уровня.

    hours — сколько часов прошло с последнего пересчёта (дробные допустимы:
    полчаса дают половину часового дохода). upgrades — оснащение бизнеса:
    реклама поднимает доход, сейф — потолок.
    """
    if hours < 0:
        hours = 0.0
    grown = stored + effective_income(business, level, upgrades) * hours
    return max(0, min(int(grown), effective_cap(business, level, upgrades)))


def hours_to_full(level: int, business: Business, current: int) -> float:
    """Через сколько часов копилка переполнится. 0 — уже полна."""
    left = business.cap(level) - current
    if left <= 0:
        return 0.0
    return left / business.income(level)


# ----------------------------------------------------------------------------
# Поломки: у каждого бизнеса свои. Сломанный НЕ КОПИТ вообще — уже накопленное
# при этом сохраняется, оно просто перестаёт расти. Ремонт стоит cap(уровень),
# то есть ровно одну полную копилку: чем дороже бизнес, тем дороже чинить.
#
# Ремонт считается от cap(), а не от «доход × 4», намеренно: у Ювелирной на
# 2 уровне потолок выше четырёх часов дохода, и cap() держит это исключение
# сам, без второго места, где его пришлось бы помнить.
# ----------------------------------------------------------------------------
BREAKDOWNS: dict[str, tuple[str, ...]] = {
    "shaurma":   ("сломался гриль", "потёк холодильник", "отключили вытяжку"),
    "magazin":   ("встала касса", "разморозилась витрина", "не приняли поставку"),
    "juvelirka": ("сработала и сгорела сигнализация", "заело сейф", "разбилась витрина"),
    "avtosalon": ("сломался подъёмник", "закоротило проводку в шоуруме", "угнали тестовую машину"),
    "aeroport":  ("отказала диспетчерская", "обледенела полоса", "забастовка грузчиков"),
}


def repair_cost(business: Business, level: int) -> int:
    """Во сколько обойдётся ремонт — одна полная копилка этого уровня."""
    return business.cap(level)


# ----------------------------------------------------------------------------
# Срочные предложения: обратная сторона поломки. Разовое вложение, которое на
# несколько часов поднимает доход. Живёт недолго — потому и «срочное».
# ----------------------------------------------------------------------------
OFFERS: dict[str, tuple[str, ...]] = {
    "shaurma":   ("поставить второй гриль", "нанять зазывалу"),
    "magazin":   ("взять паллету со скидкой", "поставить кассу самообслуживания"),
    "juvelirka": ("выкупить партию камней", "заказать витрину получше"),
    "avtosalon": ("взять партию на реализацию", "устроить тест-драйв выходного дня"),
    "aeroport":  ("открыть ночные рейсы", "продлить лицензию на грузовые"),
}

# Насколько предложение поднимает доход и на сколько часов.
OFFER_BONUS_PERCENT = 50
OFFER_HOURS = 6
# Цена — доля от полной копилки. Выгода при OFFER_BONUS_PERCENT=50 и
# OFFER_HOURS=6 равна 3 часам дохода (0.75 копилки), так что цена в половину
# копилки оставляет предложение выгодным, но не бесплатным.
OFFER_COST_SHARE = 0.5


def offer_cost(business: Business, level: int) -> int:
    return max(1, int(business.cap(level) * OFFER_COST_SHARE))


def offer_profit(business: Business, level: int) -> int:
    """Сколько лишних монет принесёт предложение, если копилку не переполнить."""
    return int(business.income(level) * OFFER_HOURS * OFFER_BONUS_PERCENT / 100)


def accrued_with_boost(
    level: int,
    business: Business,
    stored: int,
    normal_hours: float,
    boosted_hours: float,
    upgrades=(),
) -> int:
    """То же, что accrued_now, но часть времени доход шёл с надбавкой.

    Разделять интервал приходится потому, что надбавка кончается по часам, а
    копилка считается лениво: между двумя обращениями к бизнесу надбавка могла
    начаться и закончиться, и оба куска времени должны посчитаться по своим
    ставкам. Потолок при этом общий — надбавка ускоряет наполнение, но выше
    потолка всё равно не пускает.
    """
    normal_hours = max(0.0, normal_hours)
    boosted_hours = max(0.0, boosted_hours)
    rate = effective_income(business, level, upgrades)
    boosted_rate = rate * (100 + OFFER_BONUS_PERCENT) / 100
    grown = stored + rate * normal_hours + boosted_rate * boosted_hours
    return max(0, min(int(grown), effective_cap(business, level, upgrades)))
