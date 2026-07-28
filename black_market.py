"""Чёрный рынок: каталог лавки, размер ротации и запас.

Здесь только КАТАЛОГ И ПРАВИЛА, без БД и Telegram — как robbery.py и
market.py рядом.

Зачем механика. Всё воровское снаряжение до сих пор лежало в общем
«магазин» вперемешку с тортиками, доступное всегда и в любом количестве.
Лавка даёт ему своё место и ДЕФИЦИТ: ассортимент меняется раз в сутки,
запас общий на чат — кто успел, тот и купил.

Риска «спалиться» здесь намеренно НЕТ. Лавка держится на дефиците, а не на
шансе потерять деньги: шанс уже есть у самого ограбления, и вторая рулетка
поверх покупки сделала бы её просто налогом.

Состав лавки задан ЗДЕСЬ, а не колонкой в базе, и это единственное место
правды. Строки товаров при этом остаются в shop_items — без них инвентарь
показывал бы голый ключ вместо названия (list_inventory берёт название через
LEFT JOIN по ключу), и сломались бы продажа с подарками.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Сколько позиций показывает лавка за одну ротацию. Три-четыре из
# одиннадцати — чтобы «сегодня выпало именно это» было заметно.
SLOTS_MIN = 3
SLOTS_MAX = 4

# На сколько слепок ключа сокращает кулдаун медвежатника (10 ч → 7,5 ч).
STEAL_COOLDOWN_CUT = 0.25

SIGNAL_KEY = "signalizaciya"
SLEPOK_KEY = "slepok"


@dataclass(frozen=True)
class Slot:
    key: str
    max_stock: int


# Запас тем меньше, чем сильнее предмет: медвежатник за 75 000 не должен
# попадать в чат пачкой, а дешёвая мелочь пачкой никому не вредит.
POOL: tuple[Slot, ...] = (
    Slot("binokl", 3),
    Slot("rabbit_paw", 3),
    Slot("bronik", 3),
    Slot("dymovushka", 3),
    Slot("getaway_car", 3),
    Slot("lucky_coin", 2),
    Slot("gold_pig", 2),
    Slot(SLEPOK_KEY, 2),
    Slot("survilence_pass", 1),
    Slot("medvezhatnik", 1),
    Slot(SIGNAL_KEY, 1),
)

POOL_KEYS: frozenset[str] = frozenset(slot.key for slot in POOL)

# Новинки лавки: нигде, кроме неё, не продаются. Формат строки тот же, что у
# robbery.ROBBERY_SHOP_ITEMS, — их обоих принимает db.seed_extra_shop_items.
NEW_ITEMS: list[tuple[str, str, int, str, str]] = [
    (SIGNAL_KEY, "Сигнализация", 20_000,
     "Блокирует одну попытку медвежатника против вас. Срабатывает сама.",
     "🚨"),
    (SLEPOK_KEY, "Слепок ключа", 6_000,
     "Следующая кража медвежатником ставит кулдаун на четверть короче. "
     "Срабатывает сам.",
     "🔑"),
]


def pick_rotation(rng: random.Random | None = None) -> dict[str, int]:
    """Ассортимент на сутки: ключ → запас на весь чат.

    Запас именно УСТАНАВЛИВАЕТСЯ этим числом, а не прибавляется к
    вчерашнему: накопление нераскупленного убило бы дефицит за неделю.
    """
    r = rng or random
    chosen = r.sample(POOL, r.randint(SLOTS_MIN, SLOTS_MAX))
    return {slot.key: r.randint(1, slot.max_stock) for slot in chosen}
