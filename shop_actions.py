"""Магазин и инвентарь: купить, продать, показать. Ничего не отправляет.

Седьмой модуль того же устройства.

Самое дорогое место здесь — ЦЕНА. Она складывается из четырёх слоёв, и порядок
у них значащий: распродажа чата множит базовую цену, «Торгаш» (питомец) сбивает
получившееся, снаряжение («клубная карта») сбивает ещё раз, и только потом
считается «сколько влезет на все деньги». Посчитай слои в другом порядке — и
одна и та же скидка начнёт значить разные деньги в зависимости от того, идёт ли
сегодня распродажа.

Отдельно про «все»: разворачивается оно ЗДЕСЬ, а не у вызывающего, потому что
ограничителей четыре — деньги, потолок за раз, остаток на полке и лимит на
предметы ограбления, — и все четыре известны только тут.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import black_market
import chat_events
import db
import farm_actions
import farming
import game_actions
import pets as pets_catalog
import robbery
import shop_effects

logger = logging.getLogger(__name__)

BUY_MAX_QTY = 100          # столько же, сколько в чате
SELL_PERCENT = 80          # за сколько магазин принимает предмет обратно


async def ensure_catalog(chat_id: int) -> None:
    """Досеять встроенный каталог перед показом витрины.

    Бот и сайт работают с одной таблицей, но раньше только команда «магазин»
    запускала дозасев. Из-за этого сайт видел пустой или устаревший набор, пока
    кто-то не откроет магазин в Telegram. Правило живёт здесь, рядом с общим
    состоянием магазина, чтобы оба интерфейса не расходились снова.
    """
    await db.seed_default_shop_items(chat_id)
    await db.seed_extra_shop_items(chat_id, robbery.ROBBERY_SHOP_ITEMS)
    await db.seed_extra_shop_items(chat_id, black_market.NEW_ITEMS)
    await db.seed_extra_shop_items(chat_id, shop_effects.shop_rows())
    await db.seed_extra_shop_items(chat_id, pets_catalog.SHOP_ITEMS)
    # Урожай в каталоге нужен для названий и продажи, но покупаться не должен.
    await db.seed_extra_shop_items(chat_id, farming.SHOP_ITEMS, is_active=False)


@dataclass
class ShopResult:
    ok: bool
    error: str = ""
    key: str = ""
    name: str = ""
    emoji: str = ""
    qty: int = 0
    price: int = 0            # цена за штуку со всеми скидками
    total: int = 0
    base_price: int = 0       # ценник до скидок — чтобы показать «было/стало»
    sale: bool = False        # цену снизила распродажа чата
    discount: int = 0         # процент личных скидок
    left: Optional[int] = None
    coins: int = 0
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0


async def event_multiplier(chat_id: int) -> float:
    """Распродажа чата. Меняет цену ТОЛЬКО в момент покупки — ценники в
    магазине не переписываются."""
    return chat_events.multiplier(await farm_actions.active_event(chat_id),
                                  chat_events.T_SHOP)


async def price_for(chat_id: int, user_id: int, base: int) -> tuple[int, int, bool]:
    """(цена, процент личных скидок, была ли распродажа). Порядок слоёв — см.
    докстринг модуля."""
    событие = max(1, round(int(base) * await event_multiplier(chat_id)))
    цена = событие
    торгаш = await game_actions._pet_bonus(chat_id, user_id, "discount_shop")
    if торгаш:
        цена = max(1, цена - цена * торгаш // 100)
    снаряжение = await farm_actions.item_perk(chat_id, user_id,
                                              shop_effects.PERK_SHOP_DISCOUNT)
    if снаряжение:
        цена = max(1, цена - цена * снаряжение // 100)
    return цена, торгаш + снаряжение, событие < int(base)


def _fits(qty, price: int, coins: int, limit: int,
          stock: Optional[int]) -> int:
    """Сколько штук получится взять. «все» упирается в наименьшее из четырёх:
    деньги, потолок за раз, остаток на полке, лимит на такие предметы."""
    если_денег = coins // price if price > 0 else limit
    сколько = min(limit, если_денег)
    if stock is not None:
        сколько = min(сколько, int(stock))
    return max(0, int(сколько))


async def buy(chat_id: int, user_id: int, item_key: str, qty=1, *,
              from_black_market: bool = False,
              today: Optional[date] = None) -> ShopResult:
    """Купить товар. qty — число или слово «все»."""
    today = today or datetime.utcnow().date()
    item_key = (item_key or "").strip().casefold()
    всё = isinstance(qty, str) and qty.strip().casefold() in ("все", "всё", "all")
    if not всё:
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            return ShopResult(False, "Количество — число или слово «все».")
        if qty <= 0:
            return ShopResult(False, "Количество должно быть больше нуля.")
        if qty > BUY_MAX_QTY:
            return ShopResult(False, f"За раз можно купить не больше {BUY_MAX_QTY} шт.")

    item = await db.get_shop_item(chat_id, item_key)
    if item is None or not item["is_active"]:
        return ShopResult(False, "Такого товара в магазине нет.")

    # Гейт лавки: спрячь товар только из витрины — и любой, кто знает ключ,
    # купил бы его в обход ротации.
    в_лавке = item_key in black_market.POOL_KEYS
    if в_лавке and not from_black_market:
        return ShopResult(False, f"«{item['name']}» продаётся только в лавке.")
    if from_black_market and not в_лавке:
        return ShopResult(False, f"«{item['name']}» — товар обычного магазина.")
    if в_лавке and item.get("rotation_day") != today:
        return ShopResult(False, f"«{item['name']}» сегодня не завозили.")
    if shop_effects.is_reward(item_key):
        return ShopResult(False, f"«{item['name']}» не продаётся — это награда чата.")
    if item.get("stock") is not None and int(item["stock"]) <= 0:
        return ShopResult(False, f"«{item['name']}» раскуплен.")

    # Потолок на предметы ограбления и товары лавки: иначе дефицит кончился бы
    # на второй неделе.
    место: Optional[int] = None
    if item_key in robbery.ROBBERY_ITEMS or в_лавке:
        своих = next((int(i["quantity"]) for i in await db.list_inventory(chat_id, user_id)
                      if i["item_key"] == item_key), 0)
        осталось = robbery.ROBBERY_ITEM_MAX_QUANTITY - своих
        if всё:
            место = max(0, осталось)
        elif своих + qty > robbery.ROBBERY_ITEM_MAX_QUANTITY:
            return ShopResult(
                False, f"Таких предметов держат не больше "
                       f"{robbery.ROBBERY_ITEM_MAX_QUANTITY} — у вас уже {своих}.")

    цена, скидка, распродажа = await price_for(chat_id, user_id, int(item["price"]))
    wallet = await db.get_wallet(chat_id, user_id) or {}
    монеты = int(wallet.get("coins") or 0)

    if всё:
        предел = BUY_MAX_QTY if место is None else min(BUY_MAX_QTY, место)
        qty = _fits("все", цена, монеты, предел, item.get("stock"))
        if qty <= 0:
            # Ноль — это «не хватает даже на одну», и сказать это надо словами:
            # «куплено 0 шт.» человек прочитал бы как поломку.
            хвост = " И лимит на такие предметы уже выбран." if место == 0 else ""
            return ShopResult(False, f"На «{item['name']}» не хватает даже на одну: "
                                     f"цена {цена} i¢, у вас {монеты} i¢.{хвост}")

    if not await db.try_take_shop_stock(chat_id, item_key, qty):
        return ShopResult(False, f"Столько «{item['name']}» нет на полке.")
    итого = цена * qty
    if not await db.try_spend_coins(chat_id, user_id, итого):
        # Остаток уже снят с полки — возвращаем, иначе товар исчезал бы из
        # магазина от каждой неудачной попытки купить.
        await db.return_shop_stock(chat_id, item_key, qty)
        return ShopResult(False, f"Недостаточно монет: нужно {итого} i¢, "
                                 f"а у вас {монеты} i¢.")
    await db.add_inventory_item(chat_id, user_id, item_key, qty)
    обновлённый = await db.get_shop_item(chat_id, item_key)
    return ShopResult(True, key=item_key, name=item["name"],
                      emoji=item.get("emoji") or "🎁", qty=qty, price=цена,
                      total=итого, base_price=int(item["price"]),
                      sale=распродажа, discount=скидка,
                      left=(обновлённый or {}).get("stock"),
                      coins=монеты - итого, user_id=user_id)


async def sell(chat_id: int, user_id: int, item_key: str, qty=1) -> ShopResult:
    """Продать предмет из инвентаря за 80% цены. Использованный продаётся тоже
    — запрет снят решением владельца."""
    item_key = (item_key or "").strip().casefold()
    if shop_effects.is_reward(item_key):
        return ShopResult(False, "Награды не продаются — это знак отличия, а не товар.")

    всё = isinstance(qty, str) and qty.strip().casefold() in ("все", "всё", "all")
    if not всё:
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            return ShopResult(False, "Количество — число или слово «все».")
        if qty <= 0:
            return ShopResult(False, "Количество должно быть больше нуля.")

    свои = await db.list_inventory(chat_id, user_id)
    есть = next((i for i in свои if i["item_key"] == item_key), None)
    if есть is None:
        return ShopResult(False, "Такого предмета у вас нет.")
    if всё:
        qty = int(есть["quantity"])
        if qty <= 0:
            return ShopResult(False, "Такого предмета у вас нет.")
    if int(есть["quantity"]) < qty:
        return ShopResult(False, f"У вас только {есть['quantity']} шт.")

    товар = await db.get_shop_item(chat_id, item_key)
    if товар is None or товар.get("price") is None:
        return ShopResult(False, "Этот предмет нельзя продать — его нет в магазине.")

    цена = int(товар["price"])
    выручка = max(int(цена * qty * SELL_PERCENT / 100), 0)
    if not await db.remove_inventory_item(chat_id, user_id, item_key, qty):
        return ShopResult(False, "Не удалось продать — попробуйте ещё раз.")
    await db.add_coins(chat_id, user_id, выручка)

    # Закреплённый в профиле предмет, которого больше нет, — это пустая рамка
    # в карточке.
    card = await db.get_profile_card(chat_id, user_id)
    if card and card.get("pinned_item") == item_key:
        остаток = await db.list_inventory(chat_id, user_id)
        if not any(i["item_key"] == item_key for i in остаток):
            await db.set_pinned_item(chat_id, user_id, None)

    wallet = await db.get_wallet(chat_id, user_id) or {}
    return ShopResult(True, key=item_key, name=товар["name"],
                      emoji=товар.get("emoji") or "🎁", qty=qty,
                      price=цена, total=выручка, base_price=цена,
                      coins=int(wallet.get("coins") or 0), user_id=user_id)


async def state(chat_id: int, user_id: int, *,
                today: Optional[date] = None) -> dict:
    """Витрина, лавка и инвентарь — всё, что рисует экран."""
    today = today or datetime.utcnow().date()
    await ensure_catalog(chat_id)
    wallet = await db.get_wallet(chat_id, user_id) or {}
    монеты = int(wallet.get("coins") or 0)

    товары = await db.list_shop_items(chat_id, active_only=True)
    в_лавке = set(black_market.POOL_KEYS)

    async def карточка(item: dict, из_лавки: bool) -> dict:
        цена, скидка, распродажа = await price_for(chat_id, user_id, int(item["price"]))
        return {
            "key": item["item_key"], "name": item["name"],
            "emoji": item.get("emoji") or "🎁",
            "description": item.get("description") or "",
            "base_price": int(item["price"]), "price": цена,
            "sale": распродажа, "discount": скидка,
            "stock": item.get("stock"),
            "affordable": монеты >= цена,
            "reward": shop_effects.is_reward(item["item_key"]),
            "black_market": из_лавки,
        }

    витрина = [await карточка(i, False) for i in товары
               if i["item_key"] not in в_лавке
               and not shop_effects.is_reward(i["item_key"])]

    лавка = []
    try:
        for item in await db.list_rotation_items(chat_id, sorted(в_лавке), today):
            лавка.append(await карточка(item, True))
    except Exception as exc:
        logger.warning("state: лавка не прочиталась: %s", exc)

    # Инвентарь: цена продажи считается от ценника магазина, а не от того, за
    # сколько купили, — как и в чате.
    каталог = {i["item_key"]: i for i in await db.list_shop_items(chat_id, active_only=False)}
    инвентарь = []
    for row in await db.list_inventory(chat_id, user_id):
        товар = каталог.get(row["item_key"], {})
        цена = int(товар.get("price") or 0)
        инвентарь.append({
            "key": row["item_key"],
            "name": товар.get("name") or row["item_key"],
            "emoji": товар.get("emoji") or "🎁",
            "quantity": int(row["quantity"]),
            "sell_price": max(int(цена * SELL_PERCENT / 100), 0),
            "sellable": bool(цена) and not shop_effects.is_reward(row["item_key"]),
            "reward": shop_effects.is_reward(row["item_key"]),
        })

    return {
        "now": datetime.utcnow().isoformat(),
        "coins": монеты,
        "items": витрина,
        "black_market": лавка,
        "inventory": инвентарь,
        "sell_percent": SELL_PERCENT,
        "max_qty": BUY_MAX_QTY,
    }
