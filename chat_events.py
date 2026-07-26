"""Случайные события чата — общие для всех сразу.

Вся остальная экономика бота одиночная и асинхронная: человек пришёл, собрал
ферму, ушёл. События — единственная механика, которая происходит со всем чатом
в один момент и заставляет прибежать прямо сейчас.

Модуль намеренно чистый: ни базы, ни aiogram. Здесь только каталог событий и
правила выбора — всё, что можно проверить тестом, не поднимая бота. Побочные
эффекты (списать монеты, объявить в чат) делает bot.py.

Два вида событий, и разница между ними принципиальная:

* MOMENT — срабатывает один раз в момент объявления (обвал курса, налог,
  метеорит). Целиком отрабатывает в цикле bot.py и НИЧЕГО не требует от
  остальных команд бота.
* BUFF — висит заданное время и меняет уже существующие механики
  (ферма ×3, казино ×1.5). Требует, чтобы соответствующая команда спросила
  multiplier()/flag() перед начислением.

Из-за этого MOMENT-события дешёвые и безопасные, а BUFF-события стоят по
одной правке в чужом обработчике каждое. Поэтому их меньше и они выбраны
там, где эффект заметнее всего.

Баланс правится числами ниже, трогать логику для этого не нужно.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------
# Общие настройки
# ----------------------------------------------------------------------------
EVENT_CHANCE_PERCENT = 12       # шанс, что за очередной тик в чате что-то случится
MIN_MINUTES_BETWEEN = 90        # не чаще одного события в полтора часа на чат
NO_REPEAT_LAST = 4              # последние N событий чата не повторяем

MOMENT = "moment"
BUFF = "buff"

# Теги множителей. Обработчик, который начисляет награду, спрашивает
# multiplier(state, TAG) и умножает на результат.
T_FARM = "farm"
T_FISHING = "fishing"
T_TREASURE = "treasure"
T_CASINO = "casino"
T_WORK = "work"
T_ROBBERY = "robbery"
T_DIVIDENDS = "dividends"
T_SHOP = "shop"          # множитель ЦЕНЫ: <1 — скидка
T_LOOTBOX = "lootbox"    # множитель ЦЕНЫ
T_REPUTATION = "reputation"

# Флаги — включают/выключают поведение, а не множат числа.
F_NO_SURVEILLANCE = "no_surveillance"   # ограбления не ведут к надзору
F_NO_ROBBERY = "no_robbery"             # грабить нельзя вообще
F_NO_ENERGY = "no_energy"               # смена на работе не тратит энергию
F_NO_BANK_PENALTY = "no_bank_penalty"   # пеня по кредиту не капает


@dataclass(frozen=True)
class Event:
    key: str
    kind: str
    title: str
    text: str                                   # что бот пишет в чат
    weight: int = 10                            # вес при случайном выборе
    minutes: int = 0                            # для BUFF — сколько висит
    effects: dict[str, float] = field(default_factory=dict)
    flags: frozenset[str] = frozenset()
    # Для MOMENT: параметр эффекта, смысл зависит от события (см. bot.py).
    amount: float = 0.0
    ends_text: Optional[str] = None             # чем объявить окончание BUFF


# ----------------------------------------------------------------------------
# Каталог. Веса: чем больше, тем чаще. Мягкие и приятные события — чаще,
# болезненные — реже, иначе чат начнёт воспринимать бота как наказание.
# ----------------------------------------------------------------------------
EVENTS: tuple[Event, ...] = (
    # --- Длящиеся: разгон существующих механик --------------------------
    Event(
        key="gold_rush", kind=BUFF, weight=14, minutes=20,
        title="Золотая лихорадка",
        text="⛏ <b>Золотая лихорадка!</b>\nЖила вскрылась прямо под чатом — "
             "ферма даёт <b>втрое больше</b> ближайшие {minutes} мин.",
        ends_text="⛏ Жила выработана. Ферма снова обычная.",
        effects={T_FARM: 3.0},
    ),
    Event(
        key="big_catch", kind=BUFF, weight=12, minutes=20,
        title="Клёв пошёл",
        text="🎣 <b>Клёв пошёл!</b>\nРыба сама лезет на крючок — улов "
             "<b>вдвое дороже</b> ближайшие {minutes} мин.",
        ends_text="🎣 Клёв кончился, рыба ушла на глубину.",
        effects={T_FISHING: 2.0},
    ),
    Event(
        key="treasure_fever", kind=BUFF, weight=10, minutes=25,
        title="Карта сокровищ",
        text="🗺 <b>Кто-то обронил карту сокровищ!</b>\nНаходки при раскопках "
             "<b>втрое щедрее</b> ближайшие {minutes} мин.",
        ends_text="🗺 Карта размокла под дождём. Клады снова обычные.",
        effects={T_TREASURE: 3.0},
    ),
    Event(
        key="lucky_hour", kind=BUFF, weight=11, minutes=15,
        title="Фартовый час",
        text="🍀 <b>Фартовый час!</b>\nВыигрыши в казино и на гонках "
             "<b>в полтора раза больше</b> ближайшие {minutes} мин.",
        ends_text="🍀 Фарт кончился. Казино снова считает по-своему.",
        effects={T_CASINO: 1.5},
    ),
    Event(
        key="cold_deck", kind=BUFF, weight=6, minutes=15,
        title="Крупье не в духе",
        text="🃏 <b>Крупье не в духе.</b>\nВыигрыши в казино <b>урезаны вдвое</b> "
             "ближайшие {minutes} мин. Не лучшее время для ставок.",
        ends_text="🃏 Крупье подобрел. Казино снова обычное.",
        effects={T_CASINO: 0.5},
    ),
    Event(
        key="overtime", kind=BUFF, weight=12, minutes=25,
        title="Переработка",
        text="🏭 <b>Аврал на производстве!</b>\nСмены по профессии приносят "
             "<b>вдвое больше</b> ближайшие {minutes} мин.",
        ends_text="🏭 Аврал кончился, все по домам.",
        effects={T_WORK: 2.0},
    ),
    Event(
        key="union_day", kind=BUFF, weight=8, minutes=30,
        title="День профсоюза",
        text="✊ <b>День профсоюза!</b>\nСмены по профессии <b>не тратят энергию</b> "
             "ближайшие {minutes} мин. Работайте сколько влезет.",
        ends_text="✊ Профсоюз разошёлся. Энергия снова тратится.",
        flags=frozenset({F_NO_ENERGY}),
    ),
    Event(
        key="bank_heist", kind=BUFF, weight=9, minutes=15,
        title="Налёт на банк",
        text="🚨 <b>Налёт на банк!</b>\nПолиция занята — ограбления "
             "<b>не ведут к надзору</b> и приносят <b>вдвое больше</b> "
             "ближайшие {minutes} мин.",
        ends_text="🚨 Полиция вернулась на посты. Грабить снова опасно.",
        effects={T_ROBBERY: 2.0}, flags=frozenset({F_NO_SURVEILLANCE}),
    ),
    Event(
        key="curfew", kind=BUFF, weight=7, minutes=20,
        title="Комендантский час",
        text="🚓 <b>Комендантский час.</b>\nНа улицах патрули — <b>грабить нельзя</b> "
             "ближайшие {minutes} мин.",
        ends_text="🚓 Патрули сняли. Можно снова шалить.",
        flags=frozenset({F_NO_ROBBERY}),
    ),
    Event(
        key="sale", kind=BUFF, weight=11, minutes=30,
        title="Распродажа",
        text="🏷 <b>Распродажа в магазине!</b>\nВсё <b>вдвое дешевле</b> "
             "ближайшие {minutes} мин.",
        ends_text="🏷 Распродажа кончилась, ценники вернули обратно.",
        effects={T_SHOP: 0.5},
    ),
    Event(
        key="black_friday", kind=BUFF, weight=8, minutes=25,
        title="Чёрная пятница",
        text="📦 <b>Чёрная пятница!</b>\nЛутбоксы <b>на 40% дешевле</b> "
             "ближайшие {minutes} мин.",
        ends_text="📦 Чёрная пятница кончилась.",
        effects={T_LOOTBOX: 0.6},
    ),
    Event(
        key="respect_hour", kind=BUFF, weight=9, minutes=20,
        title="Час признания",
        text="💗 <b>Час признания!</b>\nРепутация начисляется <b>вдвое</b> "
             "ближайшие {minutes} мин. Скажите людям спасибо.",
        ends_text="💗 Час признания закончился.",
        effects={T_REPUTATION: 2.0},
    ),
    Event(
        key="credit_holiday", kind=BUFF, weight=7, minutes=60,
        title="Кредитные каникулы",
        text="🏦 <b>Кредитные каникулы!</b>\nПеня по просроченным кредитам "
             "<b>не начисляется</b> ближайший час. Успейте погасить.",
        ends_text="🏦 Каникулы кончились, пеня снова капает.",
        flags=frozenset({F_NO_BANK_PENALTY}),
    ),
    Event(
        key="fat_dividends", kind=BUFF, weight=8, minutes=90,
        title="Отчётность за квартал",
        text="📊 <b>Компании отчитались за квартал!</b>\nБлижайшие полтора часа "
             "дивиденды по акциям <b>втрое больше</b>.",
        ends_text="📊 Квартальная эйфория прошла.",
        effects={T_DIVIDENDS: 3.0},
    ),

    # --- Мгновенные: отрабатывают в момент объявления --------------------
    Event(
        key="stock_crash", kind=MOMENT, weight=10, amount=-40,
        title="Биржевой обвал",
        text="📉 <b>Биржевой обвал!</b>\nПаника на торгах — курс акций рухнул "
             "на <b>{amount}%</b> и теперь {price} i¢ за акцию.",
    ),
    Event(
        key="stock_rally", kind=MOMENT, weight=10, amount=35,
        title="Биржевое ралли",
        text="📈 <b>Биржевое ралли!</b>\nИнвесторы скупают всё подряд — курс "
             "взлетел на <b>{amount}%</b>, до {price} i¢ за акцию.",
    ),
    Event(
        key="meteor", kind=MOMENT, weight=12, amount=5000,
        title="Метеоритный дождь",
        text="☄️ <b>Метеоритный дождь!</b>\nОбломок упал точно во двор к "
             "{name} — <b>+{amount} i¢</b>. Кому-то сегодня везёт.",
    ),
    Event(
        key="handout", kind=MOMENT, weight=11, amount=1000,
        title="Раздача из казны",
        text="🎁 <b>Казна чата раскошелилась!</b>\nКаждому, кто писал за "
             "последние сутки, — по <b>{amount} i¢</b>. Получили: {count} чел.",
    ),
    Event(
        key="tax", kind=MOMENT, weight=7, amount=3,
        title="Налоговая проверка",
        text="🧾 <b>Налоговая проверка!</b>\nСо всех кошельков списано по "
             "<b>{amount}%</b> — всего {total} i¢ ушло в казну чата. "
             "Спасибо за вклад в общее дело.",
    ),
    Event(
        key="bank_error", kind=MOMENT, weight=9, amount=2500,
        title="Ошибка в банке",
        text="🏧 <b>Сбой в банкомате!</b>\nВклад {name} по ошибке начислили "
             "дважды — <b>+{amount} i¢</b>. Банк сделал вид, что не заметил.",
    ),
    Event(
        key="pickpocket", kind=MOMENT, weight=8, amount=15,
        title="Карманник",
        text="🕵️ <b>В чате завёлся карманник!</b>\nУ {name} увели "
             "<b>{amount} i¢</b>. Вор скрылся в толпе.",
    ),
    Event(
        key="lottery", kind=MOMENT, weight=10, amount=10000,
        title="Лотерея",
        text="🎰 <b>Розыгрыш лотереи!</b>\nБилет {name} оказался счастливым — "
             "<b>+{amount} i¢</b>.",
    ),
    Event(
        key="amnesty", kind=MOMENT, weight=6,
        title="Амнистия",
        text="🕊 <b>Амнистия!</b>\nНадзор снят со всех, кто был под ним "
             "({count} чел.). Живите честно. Или нет.",
    ),
    Event(
        key="inheritance", kind=MOMENT, weight=8, amount=7000,
        title="Наследство",
        text="📜 <b>Нашлось наследство!</b>\nДальний родственник оставил "
             "{name} <b>{amount} i¢</b>. Родственника никто не помнит.",
    ),
    Event(
        key="chat_bonus", kind=MOMENT, weight=9, amount=2000,
        title="Вклад в казну",
        text="🏛 <b>Анонимный меценат!</b>\nВ казну чата поступило "
             "<b>{amount} i¢</b>. Имя жертвователя не разглашается.",
    ),
    Event(
        key="shop_restock", kind=MOMENT, weight=8,
        title="Завоз товара",
        text="🚚 <b>Завоз в магазин!</b>\nПрилавки пополнены — "
             "товаров в наличии стало больше ({count} поз.).",
    ),
    # Единственное событие, которое платит адресно бедным, а не всем подряд.
    # amount — верхняя граница кошелька, ниже которой человека считают
    # нуждающимся; сколько именно выдать, решает bot.py по остатку казны.
    Event(
        key="charity", kind=MOMENT, weight=9, amount=1000,
        title="Гуманитарная помощь",
        text="🤝 <b>Гуманитарная помощь!</b>\nКазна чата скинулась тем, у кого "
             "в кармане меньше {amount} i¢ — по <b>{per_head} i¢</b> на человека "
             "({count} чел.). Не благодарите.",
    ),
)

EVENTS_BY_KEY: dict[str, Event] = {e.key: e for e in EVENTS}


def _normalize(raw: str) -> str:
    """Слово для поиска: без регистра, лишних пробелов и знаков вокруг."""
    return " ".join(raw.strip().casefold().replace("ё", "е").split())


# Название → ключ. Заголовок события («Золотая лихорадка») человек напишет
# охотнее, чем ключ (gold_rush), поэтому ищем и по нему, и по первому слову
# заголовка — «золотая» должно хватить. Собирается один раз при импорте:
# держать второй, руками выписанный список синонимов значило бы рано или
# поздно разойтись с каталогом.
_BY_NAME: dict[str, str] = {}
for _event in EVENTS:
    _BY_NAME.setdefault(_normalize(_event.key), _event.key)
    _title = _normalize(_event.title)
    _BY_NAME.setdefault(_title, _event.key)
    _first = _title.split(" ")[0] if _title else ""
    # Первое слово — только если оно ничьё: у «Биржевого обвала» и «Биржевого
    # ралли» оно общее, и угадывать за человека, какое из двух он имел в виду,
    # нельзя.
    if _first and _first not in _BY_NAME:
        _BY_NAME[_first] = _event.key
    elif _first and _BY_NAME.get(_first) != _event.key:
        _BY_NAME[_first] = ""          # неоднозначно — не принимаем


def resolve(raw: Optional[str]) -> Optional[Event]:
    """Событие по ключу или названию. None — не нашли или название неоднозначное."""
    if not raw:
        return None
    key = _BY_NAME.get(_normalize(raw))
    return EVENTS_BY_KEY.get(key) if key else None


# ----------------------------------------------------------------------------
# Выбор события
# ----------------------------------------------------------------------------
def pick(recent_keys: list[str], rng: Optional[random.Random] = None) -> Optional[Event]:
    """Случайное событие с учётом весов, исключая последние recent_keys.

    Возвращает None, только если исключено вообще всё (столько же событий,
    сколько в каталоге) — в норме такого не бывает.
    """
    r = rng or random
    skip = set(recent_keys[-NO_REPEAT_LAST:])
    pool = [e for e in EVENTS if e.key not in skip]
    if not pool:
        pool = list(EVENTS)
    if not pool:
        return None
    return r.choices(pool, weights=[e.weight for e in pool], k=1)[0]


def should_fire(rng: Optional[random.Random] = None) -> bool:
    r = rng or random
    return r.randint(1, 100) <= EVENT_CHANCE_PERCENT


# ----------------------------------------------------------------------------
# Активный эффект. state — то, что bot.py хранит в bot_data (JSON-словарь):
#   {"key": "gold_rush", "until": "2026-07-26T15:40:00"}
# Проверку срока делает bot.py (там есть часы), здесь — только разбор.
# ----------------------------------------------------------------------------
def multiplier(state: Optional[dict], tag: str) -> float:
    """Во сколько раз событие меняет величину с этим тегом. 1.0 — не меняет."""
    event = _event_of(state)
    if event is None:
        return 1.0
    return float(event.effects.get(tag, 1.0))


def flag(state: Optional[dict], name: str) -> bool:
    event = _event_of(state)
    return bool(event and name in event.flags)


def _event_of(state: Optional[dict]) -> Optional[Event]:
    if not state:
        return None
    return EVENTS_BY_KEY.get(state.get("key") or "")


def describe(event: Event, **params) -> str:
    """Текст объявления. Недостающие подстановки не роняют бота: {name} без
    имени превращается в «кто-то», числа — в пустое место."""
    safe = {
        "minutes": event.minutes,
        "amount": abs(event.amount) if event.amount else "",
        "name": "кто-то",
        "count": "?",
        "total": "?",
        "price": "?",
        "per_head": "?",
    }
    safe.update({k: v for k, v in params.items() if v is not None})
    try:
        return event.text.format(**safe)
    except (KeyError, IndexError):
        return event.text
