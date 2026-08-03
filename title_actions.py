"""Титулы: купить, надеть, снять. Ничего не отправляет.

Двенадцатый модуль того же устройства.

Титулы двух видов, и различать их обязательно. Одни ПРОДАЮТСЯ за монеты;
другие даются только за достижение и цены не имеют вовсе (в базе у них
price = NULL). Показать вторые в витрине с ценой «0» значило бы предложить
купить то, что зарабатывают, — и человек, нажав, получил бы отказ без
объяснения. Поэтому витрина делит их сама, а покупка второй вид не принимает.

Второе: надеть можно только СВОЙ титул. Проверка стоит здесь, а не в
интерфейсе, потому что список у экрана свой, а правда — в базе: между
отрисовкой и нажатием титул мог достаться, а мог и нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import db

logger = logging.getLogger(__name__)


@dataclass
class TitleResult:
    ok: bool
    error: str = ""
    action: str = ""
    key: str = ""
    name: str = ""
    price: int = 0


async def state(chat_id: int, user_id: int) -> dict:
    """Витрина и свои титулы. Надетый — отдельным полем, а не пометкой в
    списке: экран рисует его в шапке, и искать его перебором незачем."""
    все = await db.list_titles()
    свои = {t["title_key"] for t in await db.list_user_titles(chat_id, user_id)}
    card = await db.get_profile_card(chat_id, user_id) or {}
    wallet = await db.get_wallet(chat_id, user_id)

    продаются, за_дела = [], []
    for t in все:
        цена = t.get("price")
        запись = {
            "key": t["title_key"],
            "name": t["name"],
            "price": int(цена) if цена is not None else None,
            "owned": t["title_key"] in свои,
        }
        (продаются if цена is not None else за_дела).append(запись)

    return {
        "coins": int(wallet["coins"]),
        "active": card.get("active_title") or "",
        "for_sale": продаются,
        # Титулы за достижения: показываем, но без цены и без кнопки покупки —
        # их зарабатывают. Скрыть их совсем значило бы не сказать, что они
        # вообще существуют.
        "earned_only": за_дела,
        "owned": sorted(свои),
    }


async def buy(chat_id: int, user_id: int, key: str) -> TitleResult:
    ключ = (key or "").strip().casefold()
    титул = await db.get_title(ключ)
    if титул is None or титул.get("price") is None:
        # И «нет такого», и «этот не продаётся» — один ответ: второй вид
        # титулов покупкой не берётся вовсе.
        return TitleResult(False, "Такого титула нет в продаже.")
    if await db.has_title(chat_id, user_id, ключ):
        return TitleResult(False, "У вас уже есть этот титул.")

    цена = int(титул["price"])
    if not await db.try_spend_coins(chat_id, user_id, цена):
        return TitleResult(False, f"Недостаточно монет: нужно {цена} i¢.")
    await db.grant_title(chat_id, user_id, ключ)
    return TitleResult(True, action="buy", key=ключ, name=титул["name"], price=цена)


async def equip(chat_id: int, user_id: int, key: Optional[str]) -> TitleResult:
    """Надеть свой титул или снять надетый (пустой ключ — снять)."""
    ключ = (key or "").strip().casefold()
    if not ключ:
        await db.set_active_title(chat_id, user_id, None)
        return TitleResult(True, action="unequip")

    # Проверяем по базе, а не по списку экрана: между отрисовкой и нажатием
    # титул мог и не появиться.
    if not await db.has_title(chat_id, user_id, ключ):
        return TitleResult(False, "У вас нет такого титула.")
    титул = await db.get_title(ключ)
    await db.set_active_title(chat_id, user_id, ключ)
    return TitleResult(True, action="equip", key=ключ,
                       name=(титул or {}).get("name") or ключ)
