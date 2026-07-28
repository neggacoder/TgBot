"""Огород: культуры, погода, вредители — числа и правила.

Без БД и телеграма: здесь только «сколько растёт, сколько даёт, что портит
урожай». Хранение грядок — db.ensure_farm_plots_table, команды — bot.py.

ЗАЧЕМ ОГОРОД, если ферма уже есть. Старая «ферма» — единственная команда в
боте, где нечего решать: раз в четыре часа жмёшь и получаешь случайное число.
И она кончается: звёздность упирается в потолок примерно за неделю, после чего
не меняется уже ничего. Огород даёт то, чего в боте не было совсем, — вещи,
которые ВЫРАЩИВАЮТ. Корм питомцам и ингредиент крафтов до сих пор доставались
только за монеты, то есть за ту же ферму; теперь их можно вырастить.

Старую «ферму» огород не заменяет и не трогает: это по-прежнему быстрый способ
получить монеты, не заходя в чат каждые два часа.

ТРИ РЕШЕНИЯ, которые здесь стоит объяснить.

1. Погода общая на чат и выводится из даты, а не хранится. Одинаковый день —
   одинаковая погода у всех, спорить не о чем и подкрутить нельзя. Своей
   таблицы не нужно, фоновой задачи тоже (тот же приём, что у «погоды в чате»
   и гороскопа: см. bot._daily_pick).

2. Скорость роста фиксирует погода ДНЯ ПОСАДКИ, а урожай — погода ДНЯ СБОРА.
   Не «средняя за всё время»: среднее невозможно объяснить человеку, а так
   появляется понятная игра — посадить в дождь, собрать в солнце.

3. Вредители решаются в момент посадки, а не в момент сбора. Иначе саранча
   возникала бы ровно тогда, когда прогнать её уже поздно, и «ферма помочь»
   была бы декорацией: соседу нужно окно, в которое он успеет прийти.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import ru_text

# ----------------------------------------------------------------------------
# ГРЯДКИ
#
# Число грядок растёт со звёздностью — это и есть ответ на «звёздность упёрлась
# в потолок и больше ничего не даёт». Прибавка к урожаю в 5% незаметна, а вот
# новая грядка видна сразу.
# ----------------------------------------------------------------------------
PLOTS_BASE = 2            # столько у любого, даже без единого фарма
PLOTS_PER_STARS = 2       # каждые столько звёзд — ещё одна грядка
PLOTS_MAX = 7


def plots_for(stars: int) -> int:
    """Сколько грядок у человека с такой звёздностью."""
    return min(PLOTS_MAX, PLOTS_BASE + max(0, int(stars)) // PLOTS_PER_STARS)


def plots_next_star(stars: int) -> Optional[int]:
    """Через сколько звёзд появится следующая грядка (None — уже максимум)."""
    if plots_for(stars) >= PLOTS_MAX:
        return None
    return PLOTS_PER_STARS - max(0, int(stars)) % PLOTS_PER_STARS


# ----------------------------------------------------------------------------
# КУЛЬТУРЫ
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Crop:
    key: str                 # ключ культуры в командах
    name: str
    emoji: str
    grow_hours: int
    seed_price: int          # сколько стоит посадить
    item_key: str            # что кладём в инвентарь при сборе
    item_name: str
    item_price: int          # цена этого предмета в магазине чата
    yield_min: int
    yield_max: int
    hint: str
    # Через сколько часов после созревания урожай пропадает. 0 — не портится:
    # у большинства культур забрать можно когда угодно, и только клубника
    # заставляет вернуться вовремя.
    perish_hours: int = 0
    # Культура только на время ивента: сажать вне его нельзя.
    event_only: bool = False

    @property
    def perishable(self) -> bool:
        return self.perish_hours > 0


# Пшеница отдаёт не «пшеницу», а сразу корм: смысл культуры в том, чтобы
# питомцев можно было кормить, ничего не покупая. Ключ дословный, а не импорт
# pets — модуль остаётся ни от чего не зависящим; что ключи совпадают,
# проверяет тест (tests/test_farming.py).
FOOD_ITEM_KEY = "korm"

CROPS: tuple[Crop, ...] = (
    Crop("kartoshka", "Картошка", "🥔", 2, 200,
         "urozhay_kartoshka", "Картошка с грядки", 260, 2, 4,
         "Быстрая и безотказная. Для тех, кто заходит часто."),
    Crop("pshenica", "Пшеница", "🌾", 4, 250,
         FOOD_ITEM_KEY, "Корм", 120, 3, 6,
         "Даёт корм питомцам — кормить, ничего не покупая."),
    Crop("podsolnuh", "Подсолнух", "🌻", 8, 600,
         "urozhay_podsolnuh", "Подсолнух", 900, 1, 3,
         "Ингредиент крафтов. Другого способа получить его нет."),
    Crop("klubnika", "Клубника", "🍓", 12, 900,
         "urozhay_klubnika", "Клубника", 1_500, 3, 5,
         "Самая дорогая — и единственная, которая сгниёт, если опоздать.",
         perish_hours=3),
    Crop("tykva", "Тыква", "🎃", 6, 500,
         "urozhay_tykva", "Тыква", 1_200, 1, 3,
         "Растёт только когда в чате идёт ивент.",
         event_only=True),
)

BY_KEY: dict[str, Crop] = {c.key: c for c in CROPS}

ALIASES: dict[str, str] = {
    "картошка": "kartoshka", "картофель": "kartoshka", "картоха": "kartoshka",
    "пшеница": "pshenica", "зерно": "pshenica", "рожь": "pshenica",
    "подсолнух": "podsolnuh", "подсолнечник": "podsolnuh", "семечки": "podsolnuh",
    "клубника": "klubnika", "ягода": "klubnika", "ягоды": "klubnika",
    "тыква": "tykva", "тыковка": "tykva",
}
_ALIASES_NORM: dict[str, str] = {ru_text.yo(k): v for k, v in ALIASES.items()}


def resolve(raw: Optional[str]) -> Optional[Crop]:
    """Культура по тому, что написал человек (ключ, название или синоним).

    Нормализуем и вход, и словарь: иначе «клубника» находилась бы, а написание
    через ё у соседней культуры — нет (см. ru_text).
    """
    if not raw:
        return None
    key = " ".join(ru_text.yo(raw.strip().casefold()).split())
    return BY_KEY.get(_ALIASES_NORM.get(key) or key)


# Товары для магазина чата: (ключ, название, цена, описание, эмодзи).
# Формат — как у pets.SHOP_ITEMS. Урожай попадает в общий инвентарь, поэтому
# без строки в каталоге он показывался бы голым ключом без названия.
#
# Заводится НЕАКТИВНЫМ (db.add_shop_item(is_active=False)): цена нужна, чтобы
# урожай можно было продать, но купить его нельзя. Иначе подсолнух, ради
# которого огород и затевался, брался бы за деньги — и выращивать стало бы
# незачем. По той же причине урожай не попадает в лутбоксы: их набор берётся
# из активных товаров магазина.
SHOP_ITEMS: list[tuple[str, str, int, str, str]] = [
    (c.item_key, c.item_name, c.item_price,
     f"{c.hint} Растёт на грядке за {c.grow_hours} ч.", c.emoji)
    for c in CROPS
]


# ----------------------------------------------------------------------------
# ПОГОДА
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Weather:
    key: str
    name: str
    emoji: str
    yield_percent: int    # прибавка к урожаю при сборе
    grow_percent: int     # прибавка к скорости роста при посадке
    pest_percent: int     # прибавка к шансу вредителей при посадке
    text: str
    weight: int


WEATHERS: tuple[Weather, ...] = (
    Weather("sun", "Солнечно", "☀️", 20, 0, 0,
            "Урожай наливается: собранное сегодня даёт на 20% больше.", 30),
    Weather("rain", "Дождь", "🌧", 0, 25, 0,
            "Посаженное сегодня растёт на четверть быстрее.", 25),
    Weather("cloud", "Пасмурно", "☁️", 0, 0, 0,
            "Обычный день. Ничего не мешает и ничего не помогает.", 22),
    Weather("wind", "Ветрено", "🍃", 0, 0, -15,
            "Ветер сдувает вредителей: саранча сегодня почти не садится.", 10),
    Weather("drought", "Засуха", "🌵", -30, -20, 0,
            "Земля трескается: и растёт медленнее, и урожай беднее.", 8),
    Weather("hail", "Град", "🌩", -50, 0, 25,
            "Побило половину. И вредители лезут как ошалелые.", 5),
)

WEATHER_BY_KEY: dict[str, Weather] = {w.key: w for w in WEATHERS}


def weather_for(chat_id: int, day: date) -> Weather:
    """Погода этого чата на эти сутки.

    Выводится из (чат, дата), а не хранится: одинаковый день — одинаковая
    погода у всех и при каждом показе. Ни таблицы, ни фоновой задачи, и
    подкрутить её нельзя даже случайно.
    """
    rng = random.Random(f"farm-weather:{chat_id}:{day.isoformat()}")
    total = sum(w.weight for w in WEATHERS)
    roll = rng.randrange(total)
    for weather in WEATHERS:
        roll -= weather.weight
        if roll < 0:
            return weather
    return WEATHERS[-1]        # недостижимо, но пусть функция всегда что-то даёт


# ----------------------------------------------------------------------------
# ВРЕДИТЕЛИ
#
# Саранча решается при посадке и садится в известный момент — иначе прогнать
# её было бы невозможно в принципе (см. решение 3 в шапке модуля). Урон
# копится по часам, а не бьёт разом: у соседа есть окно, в которое его помощь
# ещё что-то значит.
# ----------------------------------------------------------------------------
PEST_CHANCE_PERCENT = 20      # базовый шанс, что на грядку сядет саранча
PEST_LOSS_PER_HOUR = 12       # столько процентов урожая съедает за час
PEST_MAX_LOSS = 60            # больше этого не съест: голым поле не оставит
PEST_EARLIEST = 0.3           # раньше этой доли срока роста не появится
PEST_LATEST = 0.9

HELP_REWARD_COINS = 500       # сколько получает сосед за прогнанных вредителей
HELP_COOLDOWN = timedelta(hours=6)


def pest_chance(weather: Weather, protected: bool = False) -> int:
    """Шанс вредителей на этой грядке в процентах. Пугало снимает его совсем."""
    if protected:
        return 0
    return max(0, min(100, PEST_CHANCE_PERCENT + weather.pest_percent))


def pest_moment(planted_at: datetime, ready_at: datetime,
                roll: float) -> datetime:
    """Когда именно сядет саранча — где-то в середине срока роста.

    roll — доля от 0 до 1 (в боте это random.random()). Отдельным аргументом,
    чтобы момент можно было проверить тестом, а не гадать по случайности.
    """
    span = (ready_at - planted_at).total_seconds()
    share = PEST_EARLIEST + (PEST_LATEST - PEST_EARLIEST) * max(0.0, min(1.0, roll))
    return planted_at + timedelta(seconds=span * share)


def pest_loss_percent(pest_at: Optional[datetime], now: datetime) -> int:
    """Сколько процентов урожая уже съедено."""
    if pest_at is None or now <= pest_at:
        return 0
    hours = (now - pest_at).total_seconds() / 3600
    return int(min(PEST_MAX_LOSS, hours * PEST_LOSS_PER_HOUR))


def pests_visible(pest_at: Optional[datetime], now: datetime) -> bool:
    """Видно ли саранчу на грядке прямо сейчас (и можно ли её прогнать)."""
    return pest_at is not None and now >= pest_at


# ----------------------------------------------------------------------------
# РОСТ И СБОР
# ----------------------------------------------------------------------------
def grow_seconds(crop: Crop, weather: Weather, speed_percent: int = 0) -> int:
    """Сколько секунд растёт эта культура, посаженная в такую погоду.

    Проценты складываются и делят срок, а не умножают: «на 25% быстрее» должно
    означать «за то же время успею на четверть больше», иначе +100% давало бы
    нулевой срок.
    """
    percent = max(-90, weather.grow_percent + max(0, int(speed_percent)))
    base = crop.grow_hours * 3600
    return max(60, round(base * 100 / (100 + percent)))


def ready_at(crop: Crop, planted_at: datetime, weather: Weather,
             speed_percent: int = 0) -> datetime:
    return planted_at + timedelta(seconds=grow_seconds(crop, weather, speed_percent))


def is_ready(now: datetime, ready: datetime) -> bool:
    return now >= ready


def perish_at(crop: Crop, ready: datetime) -> Optional[datetime]:
    """Когда урожай пропадёт, если его не забрать (None — не пропадёт)."""
    if not crop.perishable:
        return None
    return ready + timedelta(hours=crop.perish_hours)


def is_perished(crop: Crop, ready: datetime, now: datetime) -> bool:
    gone = perish_at(crop, ready)
    return gone is not None and now >= gone


def harvest_units(crop: Crop, base_units: int, weather: Weather,
                  bonus_percent: int = 0, pest_loss: int = 0) -> int:
    """Сколько штук получится с грядки.

    base_units — бросок от yield_min до yield_max (кидает bot, чтобы здесь не
    было случайности и всё считалось тестом). Ноль возможен: град с саранчой
    способны съесть грядку целиком, и это честный исход, а не ошибка.
    """
    percent = 100 + weather.yield_percent + max(0, int(bonus_percent)) - max(0, int(pest_loss))
    return max(0, round(max(0, int(base_units)) * percent / 100))


# Свинка ищет на грядке трюфель — вторая жизнь способности «Кладоискатель».
# Процент способности идёт в шанс, а не в деньги: на грядке она должна
# работать иначе, чем на кладах, иначе это то же самое другими словами.
TRUFFLE_COINS = 2_500


def truffle_found(chance_percent: int, roll: int) -> bool:
    """roll — бросок 1..100 (кидает bot)."""
    return 0 < roll <= max(0, int(chance_percent))
