"""Кабинет участника: рынок между участниками.

Правила — в market_actions и market, общих с ботом. Здесь доступ и две вещи,
которых в правилах быть не может: объявление покупки в чат и заявка админам.

ПОКУПКА ОБЪЯВЛЯЕТСЯ. В чате сделку видят все, а продавцу приходит личка.
Промолчи сайт — и рынок с него стал бы тихим: продавец узнавал бы о продаже
только по изменившемуся балансу.

ЗАЯВКА УХОДИТ АДМИНАМ теми же кнопками, что и заявка из чата: их обработчики
живут в боте и ищут её по номеру товара.
"""

from __future__ import annotations

import html
import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import db
import farm_actions
import market_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

_COMMAND = "market"
_ACTIONS = {"buy", "apply", "withdraw"}


class MarketBody(BaseModel):
    key: str
    quantity: Optional[Union[int, str]] = 1
    name: Optional[str] = None
    price: Optional[Union[int, str]] = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


async def _имя(chat_id: int, user_id: int) -> str:
    try:
        row = await db.get_known_user(chat_id, user_id)
    except Exception as exc:
        logger.warning("Рынок: имя не прочиталось: %s", exc)
        row = None
    имя = (row or {}).get("full_name") or (row or {}).get("username") or str(user_id)
    return f'<a href="tg://user?id={user_id}">{html.escape(str(имя))}</a>'


@router.get("/api/member/game/market")
async def api_member_market(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    return await market_actions.state(chat_id, user.tg_user_id)


async def _объявить_покупку(chat_id: int, user_id: int,
                            итог: market_actions.MarketResult) -> None:
    """В чат — всем, продавцу — в личку. Ровно как из чата.

    Ошибку глотаем: деньги уже перешли, и падать задним числом означало бы
    сказать покупателю «не вышло» после состоявшейся сделки.
    """
    покупатель = await _имя(chat_id, user_id)
    продавец = await _имя(chat_id, итог.seller_id)
    комиссия = f"\nКомиссия чата: {итог.fee} i¢." if итог.fee else ""
    бот = get_bot()
    try:
        await бот.send_message(chat_id, (
            f"🧺 {покупатель} покупает у {продавец}: "
            f"<b>{html.escape(итог.name)}</b> × {итог.quantity} "
            f"за <b>{итог.total}</b> i¢.{комиссия}"))
    except Exception as exc:
        logger.warning("Рынок: объявление покупки не ушло: %s", exc)
    try:
        await бот.send_message(итог.seller_id, (
            f"🧺 У вас купили «{html.escape(итог.name)}» × {итог.quantity}. "
            f"Вам зачислено {итог.to_seller} i¢."))
    except Exception as exc:
        logger.info("Рынок: продавцу не написать: %s", exc)


async def _объявить_заявку(chat_id: int, user_id: int,
                           итог: market_actions.MarketResult) -> None:
    """Заявка админам. Не ушла — не беда: она уже записана и видна по команде
    «рынок заявки», а человеку мы про это скажем."""
    gate = await chats.gate_chat_id()
    if gate is None:
        return
    кто = await _имя(chat_id, user_id)
    try:
        await get_bot().send_message(gate, (
            f"📝 <b>Заявка на рынок</b> <i>(из кабинета)</i>\n\n"
            f"👤 {кто}\n"
            f"🧺 {html.escape(итог.name)} (<code>{html.escape(итог.key)}</code>)\n"
            f"№{итог.good_id}\n\n"
            f"Разобрать: <code>рынок принять {итог.good_id}</code> · "
            f"<code>рынок отклонить {итог.good_id}</code>"))
    except Exception as exc:
        logger.warning("Рынок: заявка админам не ушла: %s", exc)


@router.post("/api/member/game/market/{action}")
async def api_member_market_action(
    action: str, body: MarketBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    if action not in _ACTIONS:
        raise HTTPException(400, "Такого действия нет")
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    user_id = user.tg_user_id
    if action != "withdraw" and await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "buy":
        result = await market_actions.buy(chat_id, user_id, body.key, body.quantity)
    elif action == "apply":
        result = await market_actions.apply(chat_id, user_id, body.key,
                                            body.name or "", body.price)
    else:
        result = await market_actions.withdraw(chat_id, user_id, body.key)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    if result.action == "buy":
        await _объявить_покупку(chat_id, user_id, result)
    elif result.pending and result.good_id:
        await _объявить_заявку(chat_id, user_id, result)

    await db.add_log(f"market_{result.action}", chat_id=chat_id, actor_id=user_id,
                     target_id=result.seller_id or None, details=result.key)
    return {
        "ok": True, "action": result.action, "key": result.key, "name": result.name,
        "quantity": result.quantity, "total": result.total, "fee": result.fee,
        "pending": result.pending,
        "state": await market_actions.state(chat_id, user_id),
    }
