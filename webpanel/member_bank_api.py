"""Кабинет участника: банк.

Правила — в bank_actions, общем с ботом. Здесь только доступ и одна вещь,
которой в правилах быть не может: показать заявку на кредит админам.

Кредит не выдаётся сам — его одобряет админ кнопкой в телеграме. Заявка с
сайта уходит теми же кнопками и с теми же данными, что заявка из чата, и
обрабатывают её те же обработчики бота. Отсюда два требования, оба неочевидные
и оба под заслоном: формат данных кнопки берётся из общего модуля, а не
пишется здесь заново; и если сообщение админам не ушло, заявка удаляется —
иначе она навсегда закрыла бы человеку кредиты, потому что следующая попытка
упирается в «у вас уже есть заявка», о которой никто не знает.

Ключи прав — те же пять, что в чате: одно действие в чате и то же действие на
сайте не могут быть разными запретами.
"""

from __future__ import annotations

import html
import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import bank_actions
import chats
import db
import farm_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

_LIST_COMMAND = "bank_status"
_ACTION_COMMANDS = {
    "deposit": "bank_deposit",
    "withdraw": "bank_withdraw",
    "credit": "bank_credit",
    "repay": "bank_repay",
}


class BankBody(BaseModel):
    amount: Optional[Union[int, str]] = None
    days: Optional[int] = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


@router.get("/api/member/game/bank")
async def api_member_bank(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    состояние = await bank_actions.state(chat_id, user.tg_user_id)
    # Есть ли кому показать заявку. Экран говорит это заранее: отказ по факту
    # нажатия читается как поломка, а не как правило.
    состояние["gate_ready"] = await chats.gate_chat_id() is not None
    return состояние


async def _показать_заявку(chat_id: int, user_id: int, имя: str,
                           итог: bank_actions.BankResult) -> bool:
    """Отправить заявку админам. False — не ушло."""
    gate = await chats.gate_chat_id()
    if gate is None:
        return False
    # Кнопки те же, что у заявки из чата: их обработчики живут в боте и ищут
    # заявку по общему ключу.
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить",
                             callback_data=bank_actions.callback_data(True, chat_id, user_id)),
        InlineKeyboardButton(text="❌ Отклонить",
                             callback_data=bank_actions.callback_data(False, chat_id, user_id)),
    ]])
    текст = (
        "🏦 <b>Заявка на кредит</b> <i>(из кабинета)</i>\n\n"
        f"👤 <a href=\"tg://user?id={user_id}\">{html.escape(имя or str(user_id))}</a>\n"
        f"💰 Сумма: {итог.amount} i¢\n"
        f"📈 К возврату: {итог.debt} i¢ (комиссия {итог.rate:g}%)\n"
        f"⏳ Срок: {итог.term_days} дн."
    )
    try:
        await get_bot().send_message(chat_id=gate, text=текст, reply_markup=kb)
        return True
    except Exception as exc:
        logger.warning("Банк кабинета: заявка на кредит не ушла в чат %s: %s: %s",
                       gate, type(exc).__name__, exc)
        return False


@router.post("/api/member/game/bank/{action}")
async def api_member_bank_action(
    action: str, body: BankBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    if action not in _ACTION_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _ACTION_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "deposit":
        result = await bank_actions.deposit(chat_id, user_id, body.amount, body.days)
    elif action == "withdraw":
        result = await bank_actions.withdraw(chat_id, user_id)
    elif action == "repay":
        result = await bank_actions.repay(chat_id, user_id, body.amount)
    else:
        result = await bank_actions.request_credit(
            chat_id, user_id, body.amount, await chats.gate_chat_id())
        имя = user.tg_full_name or user.username
        if result.ok and not await _показать_заявку(chat_id, user_id, имя, result):
            # Заявка, о которой админы не знают, навсегда закрыла бы человеку
            # кредиты: следующая попытка упрётся в «у вас уже есть заявка».
            await bank_actions.cancel_request(chat_id, user_id)
            raise HTTPException(400, "Не удалось передать заявку администраторам. "
                                     "Попробуйте позже.")

    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log(f"bank_{action}", chat_id=chat_id, actor_id=user_id,
                     details=str(result.amount))
    состояние = await bank_actions.state(chat_id, user_id)
    состояние["gate_ready"] = await chats.gate_chat_id() is not None
    return {
        "ok": True, "action": result.action, "amount": result.amount,
        "payout": result.payout, "days": result.days, "rate": result.rate,
        "debt": result.debt, "term_days": result.term_days, "closed": result.closed,
        "state": состояние,
    }
