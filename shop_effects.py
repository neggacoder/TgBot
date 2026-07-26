"""Полезные предметы магазина и наградные трофеи.

Здесь только КАТАЛОГ И ПРАВИЛА, без БД и Telegram — как businesses.py рядом.

Две разные вещи в одном файле, потому что живут они по одним и тем же
правилам витрины, а различает их один флаг:

  * ПОЛЕЗНЫЕ (EFFECT_ITEMS) — покупаются за монеты и что-то делают: чинят
    бизнес, сбрасывают кулдаун, удваивают следующий заработок, гасят одну
    поломку. Тратятся: применил — предмет ушёл.

  * ТРОФЕИ (REWARD_ITEMS) — выдаются автоматически вместе с наградой
    («наградить {степень}»). Их нельзя купить, подарить, продать и
    «использовать»: это знак отличия, а не расходник. Соответственно и
    пропасть они не могут.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# --- что умеет предмет ------------------------------------------------------
# Срабатывает сразу, в момент применения:
EFFECT_REPAIR = "repair"        # починить сломанный бизнес бесплатно
EFFECT_REFRESH = "refresh"      # сбросить кулдауны ферма/рыбалка/клад
EFFECT_WORK_REFRESH = "work_refresh"   # сбросить кулдаун смены
EFFECT_HEAL = "heal"            # восстановить энергию/настроение/здоровье
# Единственный эффект, которому нужна цель И аргумент, поэтому у него своя
# команда, а не общее «использовать» (см. bot.py).
EFFECT_STEAL_ITEM = "steal_item"
# Откладывается и ждёт своего случая (хранится в user_item_effects):
EFFECT_LUCKY = "lucky"          # следующий заработок — вдвое больше
EFFECT_SHIELD = "shield"        # следующая поломка бизнеса не случится
EFFECT_FREE_UPGRADE = "free_upgrade"   # следующий апгрейд бизнеса бесплатно

# Отложенные эффекты — те, что не срабатывают на месте, а ждут события.
PENDING_EFFECTS = frozenset({EFFECT_LUCKY, EFFECT_SHIELD, EFFECT_FREE_UPGRADE})

LUCKY_MULTIPLIER = 2


@dataclass(frozen=True)
class ShopEffectItem:
    key: str
    name: str
    emoji: str
    price: int
    effect: str
    description: str

    def as_shop_row(self) -> tuple[str, str, int, str, str]:
        """Кортеж в том виде, в каком его ждёт засев магазина."""
        return (self.key, self.name, self.price, self.description, self.emoji)


EFFECT_ITEMS: tuple[ShopEffectItem, ...] = (
    ShopEffectItem(
        "energetik", "Энергетик", "⚡", 3_000, EFFECT_REFRESH,
        "Сбрасывает кулдаун фермы, рыбалки и клада — можно собирать прямо сейчас",
    ),
    ShopEffectItem(
        "talisman", "Талисман удачи", "🍀", 5_000, EFFECT_LUCKY,
        "Следующая ферма, рыбалка или клад принесут вдвое больше",
    ),
    ShopEffectItem(
        "remkomplekt", "Ремкомплект", "🧰", 6_000, EFFECT_REPAIR,
        "Чинит сломанный бизнес бесплатно, без оплаты ремонта",
    ),
    ShopEffectItem(
        "strahovka", "Страховка бизнеса", "🛡", 12_000, EFFECT_SHIELD,
        "Ближайшая поломка бизнеса пройдёт мимо",
    ),
    ShopEffectItem(
        "kofe", "Кофе бригадира", "☕", 2_500, EFFECT_WORK_REFRESH,
        "Сбрасывает кулдаун смены — на работу можно выйти прямо сейчас",
    ),
    ShopEffectItem(
        "aptechka", "Аптечка", "⛑", 4_000, EFFECT_HEAL,
        "Восстанавливает энергию, настроение и здоровье до 100",
    ),
    ShopEffectItem(
        "biznesplan", "Бизнес-план", "📈", 9_000, EFFECT_FREE_UPGRADE,
        "Следующий апгрейд бизнеса — бесплатно, без оплаты уровня",
    ),
    ShopEffectItem(
        "medvezhatnik", "Медвежатник", "🗝", 75_000, EFFECT_STEAL_ITEM,
        "Крадёт ОДИН выбранный предмет у выбранного человека. "
        "Использовать: «медвежатник @кому {ключ предмета}»",
    ),
)

BY_KEY: dict[str, ShopEffectItem] = {i.key: i for i in EFFECT_ITEMS}


# --- трофеи за награды ------------------------------------------------------
@dataclass(frozen=True)
class RewardItem:
    key: str
    name: str
    emoji: str
    min_degree: int
    description: str

    def as_shop_row(self) -> tuple[str, str, int, str, str]:
        # Цена нужна схеме магазина, но купить трофей нельзя (см. is_reward).
        # Ставим её заведомо неоплатной, чтобы даже случайная дыра в проверке
        # не превратила знак отличия в товар.
        return (self.key, self.name, 999_999_999, self.description, self.emoji)


# Степень награды — от 1 до 8 (см. «наградить»). Трофей выдаётся по верхней
# планке, которую степень перекрывает: чем выше степень, тем весомее знак.
REWARD_ITEMS: tuple[RewardItem, ...] = (
    RewardItem("medal_bronze", "Бронзовая медаль", "🥉", 1,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("medal_silver", "Серебряная медаль", "🥈", 3,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("medal_gold", "Золотая медаль", "🥇", 5,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("order_star", "Орден Звезды", "🌟", 7,
               "Высшая награда чата. Не продаётся и не дарится"),
)

REWARD_BY_KEY: dict[str, RewardItem] = {i.key: i for i in REWARD_ITEMS}


# ----------------------------------------------------------------------------
# Предметы за АЧИВКИ. Выдаются сами, вместе с достижением (как монеты и титулы
# за него же), и работают двумя разными способами:
#
#   * ПАССИВНО — просто лежат в инвентаре и повышают доход от своего занятия.
#     Ничего нажимать не надо, тратить нечего.
#   * РАЗ В СУТКИ — их «используют», и они платят разово.
#
# Обмену не подлежат, как и медали: предмет за достижение — свидетельство
# того, что ты это сделал, и продать его значило бы продать достижение.
# ----------------------------------------------------------------------------
ACTIVITY_WORK = "work"
ACTIVITY_FARM = "farm"
ACTIVITY_FISHING = "fishing"
ACTIVITY_TREASURE = "treasure"
ACTIVITY_SIDE_JOB = "side_job"
ACTIVITY_DAILY_BONUS = "daily_bonus"

EFFECT_PASSIVE_BOOST = "passive_boost"
EFFECT_DAILY_CASH = "daily_cash"


@dataclass(frozen=True)
class AchievementItem:
    key: str
    name: str
    emoji: str
    achievement: str            # код ачивки, за которую выдаётся
    effect: str
    description: str
    activity: Optional[str] = None   # для пассивной прибавки — к чему она
    percent: int = 0                 # на сколько процентов поднимает
    shifts: int = 0                  # для разовой выплаты — во сколько смен

    def as_shop_row(self) -> tuple[str, str, int, str, str]:
        # Как и медали: в магазине предмет виден, но неоплатен — получить его
        # можно только за достижение.
        return (self.key, self.name, 999_999_999, self.description, self.emoji)


ACHIEVEMENT_ITEMS: tuple[AchievementItem, ...] = (
    AchievementItem(
        "robot_worker", "Робот работяги", "🤖", "work_20",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — смены приносят на 20% больше. Ачивка «Работяга»",
        activity=ACTIVITY_WORK, percent=20,
    ),
    AchievementItem(
        "traktor", "Трактор", "🚜", "farm_100",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — ферма приносит на 20% больше. Ачивка «Фермер»",
        activity=ACTIVITY_FARM, percent=20,
    ),
    AchievementItem(
        "snasti", "Счастливые снасти", "🎣", "fish_100",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — рыбалка приносит на 20% больше. Ачивка «Рыбак»",
        activity=ACTIVITY_FISHING, percent=20,
    ),
    AchievementItem(
        "karta", "Старая карта", "🗺", "treasure_10",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — найденный клад на 20% больше. Ачивка «Кладоискатель»",
        activity=ACTIVITY_TREASURE, percent=20,
    ),
    AchievementItem(
        "yashchik", "Ящик инструментов", "🧰", "sidejob_50",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — подработка приносит на 20% больше. Ачивка «Мастер на все руки»",
        activity=ACTIVITY_SIDE_JOB, percent=20,
    ),
    AchievementItem(
        "ogon", "Вечный огонь", "🔥", "streak_30",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — ежедневный бонус на 20% больше. Ачивка «Месяц подряд»",
        activity=ACTIVITY_DAILY_BONUS, percent=20,
    ),
    AchievementItem(
        "portfel", "Портфель карьериста", "💼", "prof_level10",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 4 смены. Ачивка «Карьерист»",
        shifts=4,
    ),
    AchievementItem(
        "slitok", "Золотой слиток", "💎", "coins_100000",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 8 смен. Ачивка «Магнат»",
        shifts=8,
    ),
    AchievementItem(
        "otmychka", "Мастер-отмычка", "🗝", "lootbox_master",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 3 смены. Ачивка «Азартный»",
        shifts=3,
    ),
)

ACHIEVEMENT_BY_KEY: dict[str, AchievementItem] = {i.key: i for i in ACHIEVEMENT_ITEMS}
# Ачивка → предмет. Одна ачивка выдаёт максимум один предмет.
ITEM_BY_ACHIEVEMENT: dict[str, AchievementItem] = {
    i.achievement: i for i in ACHIEVEMENT_ITEMS
}

# Всё, что нельзя ни купить, ни продать, ни подарить.
#
# Предметы за ачивки — потому что это свидетельство заслуги.
#
# Медали здесь ОСТАЛИСЬ, хотя за «наградить» их больше не выдают, и это не
# забытый код: у тех, кому они успели достаться, они лежат в инвентаре, а
# цена у них стоит заведомо неоплатная (999 999 999) — просто чтобы медаль
# нельзя было купить. Продажа же отдаёт 80% цены магазина, то есть снятие
# запрета превратило бы одну старую медаль в ~800 миллионов монет.
REWARD_KEYS: frozenset[str] = frozenset(REWARD_BY_KEY) | frozenset(ACHIEVEMENT_BY_KEY)


def passive_percent(item_keys, activity: str) -> int:
    """Суммарная прибавка к занятию от предметов, лежащих в инвентаре.

    Складывается, а не берётся максимум: предметы за разные ачивки — разные
    заслуги, и логично, что они дополняют друг друга. Сейчас на одно занятие
    приходится по одному предмету, так что сумма из одного слагаемого.
    """
    total = 0
    for key in item_keys:
        item = ACHIEVEMENT_BY_KEY.get(key)
        if item and item.effect == EFFECT_PASSIVE_BOOST and item.activity == activity:
            total += item.percent
    return total


def trophy_for_degree(degree: int) -> Optional[RewardItem]:
    """Какой трофей полагается за награду такой степени. None — степень ниже
    самой мелкой (в норме такого нет: степени начинаются с 1)."""
    best: Optional[RewardItem] = None
    for item in REWARD_ITEMS:
        if degree >= item.min_degree:
            best = item
    return best


def shop_rows() -> list[tuple[str, str, int, str, str]]:
    """Всё, что нужно досеять в магазин: полезное и предметы за ачивки.

    Предметы за ачивки тоже заводятся в магазине, хотя купить их нельзя: без
    записи в shop_items у предмета не было бы ни названия, ни эмодзи — в
    инвентаре он показался бы голым ключом.

    Медалей (REWARD_ITEMS) здесь НЕТ: их перестали выдавать за «наградить»,
    и заводить в магазине витрину предметов, которые никому не достанутся,
    незачем.
    """
    return ([i.as_shop_row() for i in EFFECT_ITEMS]
            + [i.as_shop_row() for i in ACHIEVEMENT_ITEMS])


def is_reward(item_key: str) -> bool:
    return item_key in REWARD_KEYS


def effect_of(item_key: str) -> Optional[str]:
    item = BY_KEY.get(item_key)
    return item.effect if item else None
