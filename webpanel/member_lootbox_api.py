"""Кабинет участника: лутбоксы.

Правила — в lootbox_actions, общем с ботом. Здесь только доступ.

Надбавка питомца «Нюхач» передаётся правилам ФУНКЦИЕЙ, а не числом: считать её
здесь значило бы завести второе место, где решают, какой у коробки шанс
редкого, — и увидеть расхождение можно было бы только по сотням открытий.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import db
import farm_actions
import game_actions
import lootbox_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

_ACTION_COMMANDS = {"buy": "lootbox_buy", "open": "lootbox_open"}


class LootBody(BaseModel):
    rarity: str
    count: Optional[Union[int, str]] = 1


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


@router.get("/api/member/game/lootbox")
async def api_member_lootbox(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, "lootbox_info")
    return await lootbox_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/lootbox/{action}")
async def api_member_lootbox_action(
    action: str, body: LootBody, request: Request,
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

    if action == "buy":
        result = await lootbox_actions.buy(chat_id, user_id, body.rarity, body.count)
    else:
        result = await lootbox_actions.open_boxes(
            chat_id, user_id, body.rarity, body.count,
            # Надбавку питомца считает тот же код, что и в чате.
            pet_bonus=game_actions._pet_bonus)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    for code in result.achievements:
        try:
            await db.grant_achievement(chat_id, result.user_id, code)
        except Exception as exc:
            logger.warning("не выдал достижение %s: %s", code, exc)

    await db.add_log(f"lootbox_{action}", chat_id=chat_id, actor_id=user_id,
                     details=f"{result.rarity}x{result.count}")
    return {
        "ok": True, "action": result.action, "rarity": result.rarity,
        "count": result.count, "total_price": result.total_price,
        "rare_hits": result.rare_hits, "rewards": result.rewards,
        "state": await lootbox_actions.state(chat_id, user_id),
    }
