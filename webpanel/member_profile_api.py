"""Кабинет участника: профиль и топы.

Только чтение — ни денег, ни действий. Поэтому и заморозка счёта здесь ничего
не закрывает: замороженному не дают играть, но смотреть свою карточку он
вправе.

Чужой профиль с сайта не открывается: в чате за него платят «досье», и
бесплатная дверь мимо платной команды обесценила бы её. Свой — пожалуйста.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

import profile_actions

import chats

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

require_member_in_chat = None

_PROFILE_COMMAND = "profile"
_TOPS_COMMAND = "top"
# Сколько строк в таблице. Десять — как в чате: экран показывает то же самое,
# и «на сайте топ длиннее» было бы отдельной правдой.
TOP_LIMIT = 10


@router.get("/api/member/game/profile")
async def api_member_profile(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _PROFILE_COMMAND)
    return await profile_actions.profile(chat_id, user.tg_user_id)


@router.get("/api/member/game/tops")
async def api_member_tops(kind: str = "",
                          user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _TOPS_COMMAND)
    if kind:
        if kind not in profile_actions.TOPS:
            raise HTTPException(400, "Такого топа нет")
        return await profile_actions.top(chat_id, kind, TOP_LIMIT)
    return await profile_actions.tops(chat_id, TOP_LIMIT)
