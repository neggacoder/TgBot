"""Лутбоксы: купить, открыть, посмотреть. Ничего не отправляет.

Тринадцатый модуль того же устройства.

Самое дорогое здесь — ШАНС РЕДКОГО. Он складывается из трёх слагаемых: базовый
шанс коробки, надбавка питомца «Нюхач» и надбавка закрепа темы «Коллекции».
Посчитай их в другом месте по-своему — и одна и та же коробка станет давать
редкое с разной вероятностью в зависимости от того, откуда её открыли. Заметить
такое можно только по многим сотням открытий, то есть практически никогда.

Второе: ПУЛ СОБИРАЕТСЯ ЗАНОВО из текущего магазина чата и титулов с ценой.
Ничего не захардкожено — добавил админ товар, он в тот же час участвует в
розыгрыше. Титулы без цены (за достижения) в пул не попадают: их нельзя
купить, и выдавать их коробкой значило бы обесценить то, что зарабатывают.

Третье: КОРОБКИ СПИСЫВАЮТСЯ ПОСЛЕ сборки пула. Если в чате нет ни товаров, ни
титулов, открывать не на что — и коробки должны остаться на руках, а не
сгореть впустую.

Броски принимаются снаружи (`roll`, `pick`) — иначе ни один исход не
проверить, а проверять здесь надо именно исходы.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

import db
import pets as pets_catalog
import pins
import robbery
import shop_effects

logger = logging.getLogger(__name__)

TYPES: dict[str, dict] = {
    "common":    {"name": "Обычный",     "emoji": "🟢", "price": 500,   "rare_chance": 5},
    "uncommon":  {"name": "Необычный",   "emoji": "🔵", "price": 2000,  "rare_chance": 15},
    "rare":      {"name": "Редкий",      "emoji": "🟣", "price": 5000,  "rare_chance": 35},
    "epic":      {"name": "Эпический",   "emoji": "🟠", "price": 10000, "rare_chance": 60},
    "legendary": {"name": "Легендарный", "emoji": "🔴", "price": 25000, "rare_chance": 85},
}
ORDER = ["common", "uncommon", "rare", "epic", "legendary"]
ALIASES: dict[str, str] = {
    "обычный": "common", "обычные": "common", "обычная": "common", "common": "common", "1": "common",
    "необычный": "uncommon", "необычные": "uncommon", "uncommon": "uncommon", "2": "uncommon",
    "редкий": "rare", "редкие": "rare", "rare": "rare", "3": "rare",
    "эпический": "epic", "эпические": "epic", "epic": "epic", "4": "epic",
    "легендарный": "legendary", "легендарные": "legendary", "legendary": "legendary", "5": "legendary",
}
MAX_PER_COMMAND = 100      # предохранитель: не купить и не открыть сотню за раз
RARE_POOL_SHARE = 0.25    # доля самых дорогих позиций каталога — «редкий» пул
MASTER_OPENED = 100       # с какого числа открытых даётся достижение


@dataclass
class LootResult:
    ok: bool
    error: str = ""
    action: str = ""
    rarity: str = ""
    count: int = 0
    total_price: int = 0
    rare_hits: int = 0
    rewards: list[dict] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0


def resolve_rarity(token: str) -> Optional[str]:
    return ALIASES.get((token or "").strip().casefold())


def _count(raw, предел: int = MAX_PER_COMMAND) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, min(n, предел))


async def build_pools(chat_id: int) -> tuple[list[dict], list[dict]]:
    """Пул наград из ТЕКУЩЕГО ассортимента: активные товары магазина чата и
    титулы с ценой. Возвращает (обычный, редкий) — самые дорогие позиции
    уходят в редкий.

    Титулы без цены сюда не попадают: их не купить, и выдавать их коробкой
    значило бы обесценить то, что зарабатывают достижением.
    """
    await db.seed_default_shop_items(chat_id)
    # Дозасев: новые товары доезжают и в чаты, где магазин давно наполнен, —
    # иначе они не появились бы там никогда.
    await db.seed_extra_shop_items(chat_id, robbery.ROBBERY_SHOP_ITEMS)
    await db.seed_extra_shop_items(chat_id, shop_effects.shop_rows())
    await db.seed_extra_shop_items(chat_id, pets_catalog.SHOP_ITEMS)

    пул: list[dict] = []
    for item in await db.list_shop_items(chat_id, active_only=True):
        пул.append({"kind": "item", "key": item["item_key"], "name": item["name"],
                    "emoji": item.get("emoji") or "🎁", "price": int(item["price"])})
    for title in await db.list_titles():
        if title.get("price") is not None:
            пул.append({"kind": "title", "key": title["title_key"], "name": title["name"],
                        "emoji": "🎖", "price": int(title["price"])})
    if not пул:
        return [], []

    пул.sort(key=lambda x: x["price"], reverse=True)
    редких = max(1, round(len(пул) * RARE_POOL_SHARE))
    редкий = пул[:редких]
    обычный = пул[редких:] or редкий
    return обычный, редкий


def weighted_pick(пул: list[dict], *, pick: Optional[Callable] = None) -> dict:
    """Чем дороже вещь, тем реже выпадает: вес обратен цене."""
    веса = [1 / max(п["price"], 1) for п in пул]
    выбрать = pick or random.choices
    return выбрать(пул, weights=веса, k=1)[0]


async def rare_chance(chat_id: int, user_id: int, rarity: str,
                      pet_bonus: Optional[Callable] = None) -> int:
    """Итоговый шанс редкого: база коробки плюс надбавки.

    Считается ОДНОЙ функцией, потому что слагаемых три и живут они в разных
    местах. Разойдись расчёт между чатом и сайтом — одна и та же коробка
    давала бы редкое с разной вероятностью, и увидеть это можно было бы
    только по сотням открытий.
    """
    база = TYPES[rarity]["rare_chance"]
    надбавка = 0
    if pet_bonus is not None:
        надбавка += await pet_bonus(chat_id, user_id, "lootbox")
    надбавка += await pin_bonus(chat_id, user_id, "lootbox")
    if not надбавка:
        return база
    return min(100, база + база * надбавка // 100)


async def pin_bonus(chat_id: int, user_id: int, effect_key: str) -> int:
    """Прибавка от закрепа профиля. Ошибку глотаем: надбавка — надстройка, и
    непрочитавшаяся карточка не должна ронять открытие коробки."""
    try:
        card = await db.get_profile_card(chat_id, user_id)
    except Exception as exc:
        logger.warning("закреп профиля не прочитался: %s", exc)
        return 0
    if not card:
        return 0
    итог = pins.achievement_bonus(card.get("pinned_achievement"), effect_key)
    if card.get("pinned_fish") and effect_key == shop_effects.ACTIVITY_FISHING:
        итог += pins.FISH_CATCH_PERCENT
    return итог


async def grant(chat_id: int, user_id: int, reward: dict) -> str:
    """Выдаёт награду. Возвращает пометку, если титул уже был: повтор титула
    ничего не значит, поэтому вместо него идёт половина цены монетами."""
    if reward["kind"] == "item":
        await db.add_inventory_item(chat_id, user_id, reward["key"], 1)
        return ""
    if await db.has_title(chat_id, user_id, reward["key"]):
        компенсация = max(reward["price"] // 2, 1)
        await db.add_coins(chat_id, user_id, компенсация)
        return f"титул уже был — компенсация {компенсация} i¢"
    await db.grant_title(chat_id, user_id, reward["key"])
    return ""


async def state(chat_id: int, user_id: int) -> dict:
    свои = {r["rarity"]: int(r["quantity"])
            for r in await db.list_user_lootboxes(chat_id, user_id)}
    wallet = await db.get_wallet(chat_id, user_id)
    return {
        "coins": int(wallet["coins"]),
        "max_per_command": MAX_PER_COMMAND,
        "kinds": [
            {"key": k, "name": TYPES[k]["name"], "emoji": TYPES[k]["emoji"],
             "price": TYPES[k]["price"], "rare_chance": TYPES[k]["rare_chance"],
             "owned": свои.get(k, 0)}
            for k in ORDER
        ],
    }


async def buy(chat_id: int, user_id: int, rarity: str, count) -> LootResult:
    вид = resolve_rarity(rarity)
    if вид is None:
        return LootResult(False, "Не понял редкость.", user_id=user_id)
    n = _count(count)
    цена = TYPES[вид]["price"] * n
    if not await db.try_spend_coins(chat_id, user_id, цена):
        return LootResult(False, f"Недостаточно монет: нужно {цена} i¢.", user_id=user_id)
    await db.add_lootbox(chat_id, user_id, вид, n)
    return LootResult(True, action="buy", rarity=вид, count=n,
                      total_price=цена, user_id=user_id)


async def open_boxes(chat_id: int, user_id: int, rarity, count, *,
                     roll: Optional[Callable[[], int]] = None,
                     pick: Optional[Callable] = None,
                     pet_bonus: Optional[Callable] = None) -> LootResult:
    вид = resolve_rarity(rarity)
    if вид is None:
        return LootResult(False, "Не понял редкость.", user_id=user_id)
    n = _count(count)

    есть = await db.get_lootbox_count(chat_id, user_id, вид)
    if есть < n:
        info = TYPES[вид]
        return LootResult(False, f"У вас только {есть}× {info['name']} — не хватает, "
                                 f"чтобы открыть {n}.", user_id=user_id)

    # Пул собираем ДО списания коробок: если в чате нет ни товаров, ни титулов,
    # открывать не на что — и коробки должны остаться на руках.
    обычный, редкий = await build_pools(chat_id)
    if not обычный and not редкий:
        return LootResult(False, "В этом чате пока нет ни товаров в магазине, ни титулов "
                                 "с ценой — открывать лутбокс не на что.", user_id=user_id)

    await db.remove_lootbox(chat_id, user_id, вид, n)
    шанс = await rare_chance(chat_id, user_id, вид, pet_bonus=pet_bonus)
    бросить = roll or (lambda: random.randint(1, 100))

    награды, редких = [], 0
    for _ in range(n):
        редкая = бросить() <= шанс
        пул = редкий if (редкая and редкий) else (обычный or редкий)
        приз = weighted_pick(пул, pick=pick)
        пометка = await grant(chat_id, user_id, приз)
        из_редкого = пул is редкий
        редких += 1 if из_редкого else 0
        награды.append({**приз, "rare": из_редкого, "note": пометка})

    stats = await db.increment_lootbox_stats(chat_id, user_id, n, редких)
    ачивки = ["lootbox_master"] if int(stats["opened_count"]) >= MASTER_OPENED else []
    return LootResult(True, action="open", rarity=вид, count=n, rare_hits=редких,
                      rewards=награды, achievements=ачивки, user_id=user_id)
