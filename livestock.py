"""Скот на ферме: кто живёт в хлеву, что даёт и как быстро.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как farming.py и pets.py
рядом. Хранение — db.ensure_farm_animals_table, команды — bot.py.

ЗАЧЕМ СКОТ, если огород уже есть. Грядки дают растения, и всё, что из них
выходит, — корм питомцам да ингредиент старых крафтов. Скот добавляет второй
источник материалов, и главное — материалов ДРУГОГО РОДА: шерсть и перо не
растут, а из молока с яйцами получается то, чего в боте не было совсем.

ТРИ РЕШЕНИЯ, которые стоит объяснить.

1. Кормить не надо. Питомцы в боте уже требуют ухода, и второй механики «не
   покормил — всё пропало» чат не выдержит: скот покупают, чтобы он работал
   в фоне, а не чтобы завести себе ещё одну обязанность.

2. Продукт копится ЛЕНИВО и упирается в потолок, как копилка бизнеса. Без
   потолка животное превращалось бы в накопительный счёт: ушёл на неделю —
   вернулся к горе шерсти, и заходить каждый день стало бы незачем. Потолок
   — примерно двое суток производства.

3. Животных одного вида теперь можно держать несколько — до MAX_PER_KIND.
   Раньше было строго по одному, и рассуждение звучало так: «пять коров — это
   просто ×5 к молоку, то есть никакого решения, а вот на что копить дальше —
   решение». Владелец решил иначе: хлев должен масштабироваться. Потолок на
   вид всё же остаётся — он держит цену продукта осмысленной и не даёт
   превратить хлев в бесконечный станок.

   Всё, что зависит от количества, считается через total_cap()/produced():
   и потолок накопления, и скорость — иначе три коровы давали бы столько же
   молока, сколько одна, и покупка выглядела бы обманом.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class Animal:
    key: str
    name: str
    emoji: str
    price: int
    # Продукт: он же строка в каталоге магазина (неактивная — см. SHOP_ITEMS).
    item_key: str
    item_name: str
    item_emoji: str
    item_price: int          # за сколько его примет «магазин продать»
    per_cycle: int           # штук за цикл
    cycle_hours: float       # длина цикла
    cap: int                 # больше столько не накопится

    @property
    def per_day(self) -> float:
        return self.per_cycle * 24 / self.cycle_hours


# Порядок — от дешёвого к дорогому: так же читается «ферма скот», и так же по
# нему поднимаются. Цены соотнесены с продуктом так, чтобы животное окупалось
# продажей примерно за полторы недели, — но настоящая его ценность в крафтах,
# где шерсть и молоко стоят дороже своей цены в магазине.
ANIMALS: tuple[Animal, ...] = (
    Animal("kurica", "Курица", "🐔", 800,
           "yayca", "Яйца", "🥚", 60,
           per_cycle=2, cycle_hours=4, cap=12),
    Animal("utka", "Утка", "🦆", 1_500,
           "pero", "Перо", "🪶", 100,
           per_cycle=1, cycle_hours=5, cap=10),
    Animal("svinya", "Свинья", "🐖", 2_500,
           "myaso", "Мясо", "🥓", 260,
           per_cycle=1, cycle_hours=8, cap=6),
    Animal("ovca", "Овца", "🐑", 4_000,
           "sherst", "Шерсть", "🧶", 420,
           per_cycle=1, cycle_hours=12, cap=4),
    Animal("korova", "Корова", "🐄", 6_000,
           "moloko", "Молоко", "🥛", 180,
           per_cycle=1, cycle_hours=6, cap=8),
)

BY_KEY: dict[str, Animal] = {a.key: a for a in ANIMALS}
BY_ITEM: dict[str, Animal] = {a.item_key: a for a in ANIMALS}

# Сколько возвращают за проданное животное, %. Половина — чтобы «купил-продал»
# не было бесплатным, но и не наказывало за смену планов.
SELL_BACK_PERCENT = 50

# Сколько животных одного вида можно держать. Не «сколько угодно»: продукт
# идёт в крафты и в продажу, и бесконечный хлев обесценил бы и то, и другое.
MAX_PER_KIND = 10

# Названия для команды: «ферма купить корова». Русское слово, а не ключ, —
# ключи человек видит только в инвентаре.
BY_WORD: dict[str, Animal] = {}
for _a in ANIMALS:
    BY_WORD[_a.name.casefold()] = _a
    BY_WORD[_a.key] = _a
# Пара очевидных форм, которые люди пишут вместо словарного названия.
BY_WORD["куру"] = BY_WORD["курицу"] = BY_KEY["kurica"]
BY_WORD["корову"] = BY_KEY["korova"]
BY_WORD["овцу"] = BY_KEY["ovca"]
BY_WORD["свинью"] = BY_KEY["svinya"]
BY_WORD["утку"] = BY_KEY["utka"]


# Формат — как у farming.SHOP_ITEMS. Продукт попадает в общий инвентарь,
# поэтому без строки в каталоге он показывался бы голым ключом без названия.
#
# Заводится НЕАКТИВНЫМ (db.add_shop_item(is_active=False)): цена нужна, чтобы
# продукт можно было продать, но купить его нельзя. Иначе шерсть, ради которой
# овцу и покупают, бралась бы за монеты — и держать овцу стало бы незачем.
SHOP_ITEMS: list[tuple[str, str, int, str, str]] = [
    (a.item_key, a.item_name, a.item_price,
     f"С фермы: даёт {a.name.lower()}. Идёт в крафты, продаётся в магазин.",
     a.item_emoji)
    for a in ANIMALS
]


def total_cap(animal: Animal, quantity: int = 1) -> int:
    """Потолок накопления на всё поголовье этого вида."""
    return animal.cap * max(1, int(quantity))


def produced(animal: Animal, last_collect_at: Optional[datetime],
             now: datetime, quantity: int = 1) -> int:
    """Сколько продукта накопилось к этому моменту. Никогда больше потолка.

    quantity — сколько таких животных в хлеву: и выработка, и потолок растут
    вместе с поголовьем. Считаем «сколько дало бы одно» и умножаем на число
    голов — так потолок остаётся ровно двумя сутками производства независимо
    от размера стада.

    Ленивый счёт, без фоновой задачи: в базе лежит только «когда забирали в
    прошлый раз». Бот может простоять сутки — при первом обращении досчитает,
    и ровно так же это переживает перезапуск.
    """
    if last_collect_at is None:
        return 0
    hours = (now - last_collect_at).total_seconds() / 3600
    if hours <= 0:
        return 0
    за_голову = min(animal.cap, int(hours / animal.cycle_hours) * animal.per_cycle)
    return за_голову * max(1, int(quantity))


def next_unit_in(animal: Animal, last_collect_at: Optional[datetime],
                 now: datetime, quantity: int = 1) -> Optional[timedelta]:
    """Через сколько появится следующая порция. None — потолок уже достигнут.

    Потолок и здесь на всё поголовье (см. total_cap): иначе у стада из трёх
    коров бот писал бы «полный хлев» втрое раньше, чем он на самом деле
    полон."""
    if last_collect_at is None:
        return timedelta(hours=animal.cycle_hours)
    if produced(animal, last_collect_at, now, quantity) >= total_cap(animal, quantity):
        return None
    hours = max(0.0, (now - last_collect_at).total_seconds() / 3600)
    циклов = int(hours / animal.cycle_hours) + 1
    return timedelta(hours=циклов * animal.cycle_hours) - (now - last_collect_at)


def sell_back(animal: Animal) -> int:
    return max(1, animal.price * SELL_BACK_PERCENT // 100)
