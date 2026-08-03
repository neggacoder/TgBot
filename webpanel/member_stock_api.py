"""Кабинет участника: биржа.

Правила — в stock_actions, общем с ботом. Здесь только доступ.

Выключатель биржи проверяется НЕ здесь, а в самих правилах: пропусти его в
одном из четырёх мест — и сайт станет обходом админского рубильника, причём
молча. Тот же приём, что с рабочим чатом: решение принимается в одном месте,
а не повторяется в каждом обработчике.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import db
import farm_actions
import stock_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

# Ключ прав один на все четыре действия — ровно как в чате, где «биржа»,
# «биржа купить», «биржа продать» и «биржа дивиденды» гейтятся одним
# stock_market. Четыре разных ключа означали бы, что запрет в чате и запрет на
# сайте — разные запреты.
_COMMAND = "stock_market"

_ACTIONS = {"buy", "sell", "dividends"}


class StockBody(BaseModel):
    # Строкой приходит «всё»: во сколько монет оно разворачивается, знают
    # только доли и курс, а посчитанное в браузере после округления через JSON
    # стабильно промахивается мимо предела продажи.
    amount: Optional[Union[int, str]] = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


@router.get("/api/member/game/stock")
async def api_member_stock(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    return await stock_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/stock/{action}")
async def api_member_stock_action(
    action: str, body: StockBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    if action not in _ACTIONS:
        raise HTTPException(400, "Такого действия нет")
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "buy":
        result = await stock_actions.buy(chat_id, user_id, body.amount)
    elif action == "sell":
        result = await stock_actions.sell(chat_id, user_id, body.amount)
    else:
        result = await stock_actions.dividends(chat_id, user_id)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    for code in result.achievements:
        try:
            if not await db.grant_achievement(chat_id, result.user_id, code):
                continue
        except Exception as exc:  # достижение не должно ронять саму сделку
            logger.warning("не выдал достижение %s: %s", code, exc)

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"stock/{action} {result.amount}")
    return {
        "ok": True, "action": result.action, "amount": result.amount,
        "shares": result.shares, "price": result.price, "profit": result.profit,
        "state": await stock_actions.state(chat_id, user_id),
    }
