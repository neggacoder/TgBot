"""Кабинет участника: магазин и инвентарь.

Правила — в shop_actions, общем с ботом. Здесь только доступ.

Лавка (чёрный рынок) показывается, но купить в ней с сайта можно ровно то, что
завезли сегодня: гейт стоит в самих правилах, а не в витрине — иначе тот, кто
знает ключ, брал бы товар в обход ротации.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import casino_actions
import collection_actions
import db
import farm_actions
import shop_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

_LIST_COMMAND = "shop_list"
_ACTION_COMMANDS = {"buy": "shop_buy", "sell": "item_sell"}


async def _check_collections(chat_id: int, user_id: int) -> None:
    """Последний кусок хлама, купленный в кабинете, завершает коллекцию."""
    try:
        awards = await collection_actions.check_collections(
            chat_id, user_id, today=await casino_actions.local_today())
    except Exception as exc:
        logger.warning("Магазин кабинета: не проверились коллекции: %s: %s",
                       type(exc).__name__, exc)
        return
    for collection in awards:
        try:
            await get_bot().send_message(
                chat_id,
                await collection_actions.site_announcement(chat_id, user_id, collection),
            )
        except Exception as exc:
            logger.warning("Магазин кабинета: объявление о коллекции в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


class ShopBody(BaseModel):
    key: Optional[str] = None
    qty: Optional[Union[int, str]] = None
    # Товар из лавки: тот же адрес, но правила пускают его только сегодняшним
    # ассортиментом.
    black_market: bool = False


@router.get("/api/member/game/shop")
async def api_member_shop(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    return await shop_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/shop/{action}")
async def api_member_shop_action(
    action: str, body: ShopBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if action not in _ACTION_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _ACTION_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)
    if not body.key:
        raise HTTPException(400, "Не выбран предмет.")

    сколько = body.qty if body.qty is not None else 1
    if action == "buy":
        result = await shop_actions.buy(chat_id, user_id, body.key, сколько,
                                        from_black_market=body.black_market)
    else:
        result = await shop_actions.sell(chat_id, user_id, body.key, сколько)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"shop/{action} {result.key}:{result.qty}")
    if action == "buy" and result.key in db.JUNK_ITEM_KEYS:
        await _check_collections(chat_id, user_id)
    return {
        "ok": True, "action": action, "key": result.key, "name": result.name,
        "emoji": result.emoji, "qty": result.qty, "price": result.price,
        "total": result.total, "sale": result.sale, "discount": result.discount,
        "left": result.left,
        "state": await shop_actions.state(chat_id, user_id),
    }
