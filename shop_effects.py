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
# Эффекты со своей командой вместо общего «использовать» (см. bot.py): им
# нужна цель или реплай, а «использовать {ключ} @кому» занято одним аргументом.
EFFECT_STEAL_ITEM = "steal_item"
EFFECT_SABOTAGE = "sabotage"      # сломать бизнес выбранного человека
EFFECT_KOMPROMAT = "kompromat"    # поднять старую фразу человека из ленты чата
EFFECT_DOSSIER = "dossier"        # досье: чем человек занимался в последнее время
EFFECT_MEGAPHONE = "megaphone"    # закрепить своё сообщение в чате

# Своя команда есть у всех перечисленных: общий «использовать» их не берёт.
OWN_COMMAND_EFFECTS = frozenset({
    EFFECT_STEAL_ITEM, EFFECT_SABOTAGE, EFFECT_KOMPROMAT,
    EFFECT_DOSSIER, EFFECT_MEGAPHONE,
})
EFFECT_ICE = "ice"              # обновить свежесть всей рыбы в сетке
EFFECT_EVENT_TICKET = "event_ticket"   # запустить событие чата прямо сейчас
EFFECT_VABANK = "vabank"        # удвоить кошелёк или потерять треть
EFFECT_GENEROSITY = "generosity"  # раздать монеты всем, кто сегодня писал
# Откладывается и ждёт своего случая (хранится в user_item_effects):
EFFECT_LUCKY = "lucky"          # следующий заработок — вдвое больше
EFFECT_SHIELD = "shield"        # следующая поломка бизнеса не случится
EFFECT_FREE_UPGRADE = "free_upgrade"   # следующий апгрейд бизнеса бесплатно
EFFECT_MIRROR = "mirror"        # следующее ограбление отражается на грабителя

# Отложенные эффекты — те, что не срабатывают на месте, а ждут события.
PENDING_EFFECTS = frozenset({
    EFFECT_LUCKY, EFFECT_SHIELD, EFFECT_FREE_UPGRADE, EFFECT_MIRROR,
})

LUCKY_MULTIPLIER = 2

# ----------------------------------------------------------------------------
# ЗАКРЕП УСИЛИВАЕТ ПРЕДМЕТ. Раньше закреплённый предмет был чистым украшением
# профиля — теперь он впятеро усиливает то, что предмет и так умеет. Закреп
# один на человека, поэтому это осмысленный выбор, а не бесплатная прибавка.
#
# Что именно множится, зависит от типа эффекта — единого числа у предметов
# нет, и притворяться, что есть, было бы враньём:
#
#   * отложенные (PENDING_EFFECTS) — PIN_MULTIPLIER зарядов вместо одного:
#     пять поломок мимо, пять отражённых ограблений, пять удвоенных заработков;
#   * щедрость — раздаёт и списывает в PIN_MULTIPLIER раз больше;
#   * остальные — предмет расходуется раз в PIN_MULTIPLIER применений, то есть
#     одной штуки хватает впятеро дольше. Починку или сброс кулдауна усилить
#     нечем: бизнес либо цел, либо нет.
#
# ВА-БАНК из умножения суммы исключён намеренно (см. PIN_AMOUNT_EFFECTS):
# «удвоить или потерять треть» в пятикратном размере — это либо ×10 к кошельку,
# либо минус полтора кошелька, то есть уход в отрицательный баланс. Он идёт по
# общему правилу расхода, как прочие бинарные.
# ----------------------------------------------------------------------------
PIN_MULTIPLIER = 5

# Эффекты, у которых закреп множит САМУ СУММУ, а не число применений.
PIN_AMOUNT_EFFECTS = frozenset({EFFECT_GENEROSITY})


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
    # --- предметы, которые создают событие на весь чат --------------------
    # В отличие от всего, что выше, эти видит не только владелец: смысл в
    # моменте, который происходит у всех на глазах, а не в тихой прибавке
    # к проценту.
    ShopEffectItem(
        "lyod", "Лёд", "🧊", 3_500, EFFECT_ICE,
        "Пересыпает сетку льдом: вся рыба в ней снова свежая, отсчёт порчи "
        "начинается заново. Можно спокойно ждать «Клёва»",
    ),
    ShopEffectItem(
        "zerkalo", "Зеркало", "🪞", 18_000, EFFECT_MIRROR,
        "Ближайшее ограбление против вас отражается: крадут не у вас, "
        "а у самого грабителя. Бот объявит это в чат",
    ),
    ShopEffectItem(
        "bilet", "Билет на ивент", "🎪", 30_000, EFFECT_EVENT_TICKET,
        "Запускает случайное событие чата прямо сейчас, не дожидаясь "
        "расписания. Действует на весь чат",
    ),
    ShopEffectItem(
        "vabank", "Ва-банк", "🃏", 5_000, EFFECT_VABANK,
        "Орёл или решка на весь кошелёк: удвоить или потерять треть. "
        "Результат бот объявляет в чат",
    ),
    ShopEffectItem(
        "shchedrost", "Щедрость", "🎁", 40_000, EFFECT_GENEROSITY,
        "Раздаёт по чуть-чуть всем, кто сегодня писал в чат, — от вашего "
        "имени и с объявлением поимённо",
    ),
    ShopEffectItem(
        "sabotazh", "Саботаж", "🧨", 22_000, EFFECT_SABOTAGE,
        "Ломает бизнес выбранного человека — если у него нет страховки. "
        "Использовать: «саботаж @кому»",
    ),
    ShopEffectItem(
        "kompromat", "Компромат", "💣", 15_000, EFFECT_KOMPROMAT,
        "Поднимает случайную старую фразу человека из ленты чата и публикует "
        "её картинкой-цитатой. Использовать: «компромат @кому»",
    ),
    ShopEffectItem(
        "dosye", "Досье", "🕵️", 12_000, EFFECT_DOSSIER,
        "Показывает, чем человек занимался в последнее время: заработки, "
        "ограбления, покупки. Использовать: «досье @кому»",
    ),
    ShopEffectItem(
        "megafon", "Мегафон", "📢", 25_000, EFFECT_MEGAPHONE,
        "Закрепляет ваше сообщение в чате на час. Использовать: «мегафон» "
        "ответом на своё сообщение",
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

# Трофей выдаётся по ВЕРХНЕЙ планке, которую степень перекрывает, поэтому
# порядок здесь важнее самих названий: новая строка между существующими
# меняет то, что получат уже награждённые следующей степенью. Новые вставлены
# так, чтобы ни одна старая планка не сдвинулась — 2, 4, 6 и 8 были пусты, и
# половина степеней выдавала тот же знак, что и соседняя.
REWARD_ITEMS = tuple(sorted(REWARD_ITEMS + (
    RewardItem("medal_iron", "Железная медаль", "🎖", 2,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("order_leaf", "Лавровый венок", "🏵", 4,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("order_shield", "Орден Щита", "🛡", 6,
               "Награда чата. Не продаётся и не дарится"),
    RewardItem("order_crown", "Корона чата", "👑", 8,
               "Высшая награда чата. Не продаётся и не дарится"),
), key=lambda i: i.min_degree))

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
# Особое значение: прибавка идёт к ЛЮБОМУ занятию. Нужно Короне мастера —
# перечислять шесть занятий шестью предметами было бы нелепо.
ACTIVITY_ANY = "any"

EFFECT_PASSIVE_BOOST = "passive_boost"
EFFECT_DAILY_CASH = "daily_cash"


# --- постоянные привилегии --------------------------------------------------
# Вторая, «неарифметическая» сила предмета за ачивку. Работает всё время,
# пока предмет лежит в инвентаре: нажимать ничего не надо, тратиться нечему
# (потерять предмет за ачивку вообще нельзя — см. REWARD_KEYS).
#
# Смысл в том, чтобы ачивку хотелось добыть не ради «+20% к ферме», которых
# никто не замечает, а ради заметной привилегии. Числа держим скромными:
# привилегия вечная и накапливается с остальными предметами.
PERK_ROBBERY_DEFENSE = "robbery_defense"   # −N% к шансу, что ограбят ВАС
PERK_ROBBERY_ATTACK = "robbery_attack"     # +N% к шансу вашего ограбления
PERK_FAIL_LOSS_CUT = "fail_loss_cut"       # −N% к потере при провале ограбления
PERK_ENERGY_SAVE = "energy_save"           # −N% к расходу энергии и настроения
PERK_FARM_COOLDOWN = "farm_cooldown"       # −N% к кулдауну фермы
PERK_NO_EMPTY_FISHING = "no_empty_fishing"  # улов не бывает пустым
PERK_NO_EMPTY_TREASURE = "no_empty_treasure"  # яма не бывает пустой
PERK_BREAK_RESIST = "break_resist"         # −N% к шансу поломки бизнеса
PERK_STREAK_SHIELD = "streak_shield"       # серия не сгорает за один пропуск
PERK_FARM_NO_PESTS = "farm_no_pests"       # на грядки не садятся вредители

# Привилегии-переключатели: у них нет процента, важен сам факт наличия.
FLAG_PERKS = frozenset({
    PERK_NO_EMPTY_FISHING, PERK_NO_EMPTY_TREASURE, PERK_STREAK_SHIELD,
    PERK_FARM_NO_PESTS,
})


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
    perk: Optional[str] = None       # постоянная привилегия (см. PERK_*)
    perk_percent: int = 0            # её сила; у FLAG_PERKS не используется
    perk_text: str = ""              # как привилегия объясняется человеку

    def as_shop_row(self) -> tuple[str, str, int, str, str]:
        # Как и медали: в магазине предмет виден, но неоплатен — получить его
        # можно только за достижение.
        return (self.key, self.name, 999_999_999, self.description, self.emoji)


ACHIEVEMENT_ITEMS: tuple[AchievementItem, ...] = (
    AchievementItem(
        "robot_worker", "Робот работяги", "🤖", "work_20",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — смены приносят на 20% больше, а энергии тратят "
        "на четверть меньше. Ачивка «Работяга»",
        activity=ACTIVITY_WORK, percent=20,
        perk=PERK_ENERGY_SAVE, perk_percent=25,
        perk_text="смена отнимает на 25% меньше энергии",
    ),
    AchievementItem(
        "traktor", "Трактор", "🚜", "farm_100",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — ферма приносит на 20% больше, а ждать её на 15% "
        "меньше. Ачивка «Фермер»",
        activity=ACTIVITY_FARM, percent=20,
        perk=PERK_FARM_COOLDOWN, perk_percent=15,
        perk_text="кулдаун фермы короче на 15%",
    ),
    AchievementItem(
        "snasti", "Счастливые снасти", "🎣", "fish_100",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — рыбалка приносит на 20% больше и никогда не "
        "остаётся пустой. Ачивка «Рыбак»",
        activity=ACTIVITY_FISHING, percent=20,
        perk=PERK_NO_EMPTY_FISHING,
        perk_text="улов никогда не бывает пустым",
    ),
    AchievementItem(
        "karta", "Старая карта", "🗺", "treasure_10",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — найденный клад на 20% больше, а неудачная копка "
        "всё равно что-то приносит. Ачивка «Кладоискатель»",
        activity=ACTIVITY_TREASURE, percent=20,
        perk=PERK_NO_EMPTY_TREASURE,
        perk_text="даже промах на раскопках приносит немного монет",
    ),
    AchievementItem(
        "yashchik", "Ящик инструментов", "🧰", "sidejob_50",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — подработка приносит на 20% больше, а бизнес "
        "ломается на 20% реже. Ачивка «Мастер на все руки»",
        activity=ACTIVITY_SIDE_JOB, percent=20,
        perk=PERK_BREAK_RESIST, perk_percent=20,
        perk_text="бизнес ломается на 20% реже",
    ),
    AchievementItem(
        "ogon", "Вечный огонь", "🔥", "streak_30",
        EFFECT_PASSIVE_BOOST,
        "Пока в инвентаре — ежедневный бонус на 20% больше, а серия переживает "
        "один пропущенный день. Ачивка «Месяц подряд»",
        activity=ACTIVITY_DAILY_BONUS, percent=20,
        perk=PERK_STREAK_SHIELD,
        perk_text="серия не сгорает за один пропущенный день",
    ),
    AchievementItem(
        "portfel", "Портфель карьериста", "💼", "prof_level10",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 4 смены. Пока в "
        "инвентаре — вас на 15% реже грабят. Ачивка «Карьерист»",
        shifts=4,
        perk=PERK_ROBBERY_DEFENSE, perk_percent=15,
        perk_text="шанс, что вас ограбят, ниже на 15%",
    ),
    AchievementItem(
        "slitok", "Золотой слиток", "💎", "coins_100000",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 8 смен. Пока в "
        "инвентаре — при провале ограбления теряете на четверть меньше. "
        "Ачивка «Магнат»",
        shifts=8,
        perk=PERK_FAIL_LOSS_CUT, perk_percent=25,
        perk_text="при провале ограбления теряете на 25% меньше",
    ),
    # Ключ — «master_otmychka», а не «otmychka»: последний занят КРАФТОВОЙ
    # «Отмычкой» (CRAFT_ITEMS ниже), и она же им названа в рецепте
    # crafting.RECIPES. Раньше оба предмета стояли под одним ключом, а
    # ACHIEVEMENT_BY_KEY собирается из ACHIEVEMENT_ITEMS + CRAFT_ITEMS —
    # крафтовая шла второй и молча затирала эту. Любой поиск по ключу отдавал
    # крафтовую версию, поэтому заслуживший ачивку «Азартный» терял суточную
    # выплату, а из двух строк засева магазина одну отбрасывал UNIQUE-ключ.
    # Переименована именно наградная: у крафтовой ключ завязан на рецепт.
    AchievementItem(
        "master_otmychka", "Мастер-отмычка", "🗝", "lootbox_master",
        EFFECT_DAILY_CASH,
        "Раз в сутки выдаёт столько, сколько приносят 3 смены. Пока в "
        "инвентаре — ваши ограбления удаются на 10% чаще. Ачивка «Азартный»",
        shifts=3,
        perk=PERK_ROBBERY_ATTACK, perk_percent=10,
        perk_text="ваши ограбления удаются на 10% чаще",
    ),
)

# ----------------------------------------------------------------------------
# КРАФТОВЫЕ ПРЕДМЕТЫ. Форма та же, что у предметов за ачивки, и это не
# совпадение: «лежит в инвентаре и постоянно что-то даёт» здесь уже умеет
# работать (passive_percent, perk_percent, has_perk), и крафту достаточно
# попасть в тот же ACHIEVEMENT_BY_KEY, чтобы плюшки заработали без единой
# правки в местах начисления.
#
# Заодно они автоматически попадают в REWARD_KEYS — значит их нельзя купить,
# продать и подарить. Крафтовое зарабатывают, а не выменивают.
#
# Поле achievement пустое: за ачивку они не выдаются, получить их можно только
# командой «крафт» (рецепты — в crafting.py).
# ----------------------------------------------------------------------------
EFFECT_EVOLUTION = "evolution"   # расходник эволюции питомца, сам ничего не делает

CRAFT_ITEMS: tuple[AchievementItem, ...] = (
    AchievementItem(
        "otmychka", "Отмычка", "🗝", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — ваши ограбления удаются на 15% чаще",
        perk=PERK_ROBBERY_ATTACK, perk_percent=15,
        perk_text="ограбление удаётся на 15% чаще",
    ),
    AchievementItem(
        "obereg", "Оберег", "🧿", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — вас грабят успешно на 20% реже",
        perk=PERK_ROBBERY_DEFENSE, perk_percent=20,
        perk_text="вас грабят успешно на 20% реже",
    ),
    AchievementItem(
        "kompas", "Компас кладоискателя", "🧭", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — яма с кладом никогда не бывает пустой",
        perk=PERK_NO_EMPTY_TREASURE,
        perk_text="даже промах на раскопках приносит немного монет",
    ),
    AchievementItem(
        "set_rybaka", "Сеть рыбака", "🕸", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — улов никогда не бывает пустым",
        perk=PERK_NO_EMPTY_FISHING,
        perk_text="улов никогда не бывает пустым",
    ),
    AchievementItem(
        "termos", "Термос", "☕", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — смена отнимает на 25% меньше энергии",
        perk=PERK_ENERGY_SAVE, perk_percent=25,
        perk_text="смена отнимает на 25% меньше энергии",
    ),
    AchievementItem(
        "amulet_serii", "Амулет серии", "🔥", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — серия активности не сгорает за один пропуск",
        perk=PERK_STREAK_SHIELD,
        perk_text="серия не сгорает за один пропущенный день",
    ),
    AchievementItem(
        "elixir", "Эликсир эволюции", "🧪", "",
        EFFECT_EVOLUTION,
        "Крафт. Тратится на эволюцию питомца десятого уровня: "
        "«пет эволюция {ключ}»",
    ),
    AchievementItem(
        "korona_mastera", "Корона мастера", "👑", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — ВСЕ занятия приносят на 25% больше",
        activity=ACTIVITY_ANY, percent=25,
    ),
    # Единственный крафт, который собирают из выращенного, а не из купленного:
    # огород замыкается сам на себя — вырастил подсолнух, сделал пугало,
    # растишь спокойнее.
    AchievementItem(
        "pugalo", "Пугало", "🎭", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт. Пока в инвентаре — на ваши грядки не садятся вредители",
        perk=PERK_FARM_NO_PESTS,
        perk_text="вредители обходят ваш огород стороной",
    ),
)

CRAFT_ITEMS = CRAFT_ITEMS + (
    # --- Ветка фермы: из молока, яиц, шерсти и пера ------------------------
    #
    # Все четыре — пассивные, и это не лень, а единственный проверенный путь:
    # расходники (аптечка, талисман) живут в EFFECT_ITEMS и продаются в
    # магазине за монеты, а вещь, которую можно купить, незачем выращивать.
    # Поэтому еда здесь — не «съел и восстановил», а припасы: пока лежат в
    # сумке, работается легче.
    AchievementItem(
        "syr", "Сыр", "🧀", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт из молока. Пока в инвентаре — смены приносят на 10% больше",
        activity=ACTIVITY_WORK, percent=10,
    ),
    AchievementItem(
        "pirog", "Пирог", "🥧", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт из яиц и молока. Пока в инвентаре — подработки приносят "
        "на 20% больше",
        activity=ACTIVITY_SIDE_JOB, percent=20,
    ),
    AchievementItem(
        "sharf", "Шарф", "🧣", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт из шерсти. Пока в инвентаре — рыбалка приносит на 15% больше",
        activity=ACTIVITY_FISHING, percent=15,
    ),
    AchievementItem(
        "tulup", "Тулуп", "🧥", "",
        EFFECT_PASSIVE_BOOST,
        "Крафт из шерсти и пера. Пока в инвентаре — ферма приносит на 20% "
        "больше, а на грядки не садятся вредители",
        activity=ACTIVITY_FARM, percent=20,
        perk=PERK_FARM_NO_PESTS,
        perk_text="на ваши грядки не садятся вредители",
    ),
)

CRAFT_BY_KEY: dict[str, AchievementItem] = {i.key: i for i in CRAFT_ITEMS}

# Крафтовые предметы лежат в том же справочнике, что и предметы за ачивки, —
# см. комментарий выше.
ACHIEVEMENT_BY_KEY: dict[str, AchievementItem] = {
    i.key: i for i in ACHIEVEMENT_ITEMS + CRAFT_ITEMS
}
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
        if item is None or item.effect != EFFECT_PASSIVE_BOOST:
            continue
        if item.activity == activity or item.activity == ACTIVITY_ANY:
            total += item.percent
    return total


def perk_percent(item_keys, perk: str) -> int:
    """Суммарная сила привилегии от предметов, лежащих в инвентаре.

    Складывается по той же причине, что и passive_percent: разные предметы —
    разные заслуги. Сейчас на каждую привилегию приходится ровно один
    предмет, так что сумма из одного слагаемого.
    """
    total = 0
    for key in item_keys:
        item = ACHIEVEMENT_BY_KEY.get(key)
        if item and item.perk == perk:
            total += item.perk_percent
    return total


def has_perk(item_keys, perk: str) -> bool:
    """Для привилегий-переключателей (FLAG_PERKS), где процента нет."""
    return any(
        (ACHIEVEMENT_BY_KEY.get(key) or _NO_ITEM).perk == perk for key in item_keys
    )


class _NoItem:
    perk = None


_NO_ITEM = _NoItem()


def perks_of(item_key: str) -> str:
    """Человеческое описание привилегии предмета — пустая строка, если её нет.

    Нужно, чтобы инвентарь показывал привилегию из КАТАЛОГА, а не из строки
    магазина: описания в shop_items засеваются один раз и при обновлении
    бота у старых чатов не переписываются (add_shop_item пропускает
    существующие ключи), то есть остались бы прежними навсегда.
    """
    item = ACHIEVEMENT_BY_KEY.get(item_key)
    return item.perk_text if item and item.perk_text else ""


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
            + [i.as_shop_row() for i in ACHIEVEMENT_ITEMS]
            + [i.as_shop_row() for i in CRAFT_ITEMS])


def is_reward(item_key: str) -> bool:
    return item_key in REWARD_KEYS


def effect_of(item_key: str) -> Optional[str]:
    item = BY_KEY.get(item_key)
    return item.effect if item else None
