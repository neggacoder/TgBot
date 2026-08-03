"""Кабинет участника: анкета и титулы.

Одним модулем на два: и то и другое — это карточка человека, живут они в одной
таблице (profile_cards) и на экране стоят рядом. Разводить по двум файлам
значило бы дважды править любую правку доступа.

Правила — в card_actions и title_actions, общих с ботом. Здесь только доступ.

Ключи прав — те же, что в чате: одно действие в чате и то же действие на сайте
не могут быть разными запретами.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import card_actions
import chats
import db
import farm_actions
import title_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

# Анкету правят команды «+звание», «+девиз», «!мой город», «о себе»,
# «+гражданство», «+анкета» — у них разные ключи прав, и мы берём тот, что
# отвечает за само поле.
_FIELD_COMMANDS = {
    "title": "title", "motto": "motto", "city": "city", "about": "about",
    "citizen": "citizenship", "visible": "anketa_visibility",
}


class FieldBody(BaseModel):
    field: str
    value: Optional[str] = None
    on: Optional[bool] = None


class TitleBody(BaseModel):
    key: Optional[str] = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


@router.get("/api/member/game/card")
async def api_member_card(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, "anketa")
    return {
        "card": await card_actions.state(chat_id, user.tg_user_id),
        "titles": await title_actions.state(chat_id, user.tg_user_id),
    }


@router.post("/api/member/game/card/field")
async def api_member_card_field(
    body: FieldBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    команда = _FIELD_COMMANDS.get(body.field)
    if команда is None:
        raise HTTPException(400, "Такого поля в анкете нет")
    await permissions.ensure(user, команда)
    user_id = user.tg_user_id

    if body.field == "citizen":
        result = await card_actions.set_citizen(chat_id, user_id, bool(body.on))
    elif body.field == "visible":
        result = await card_actions.set_visible(chat_id, user_id, bool(body.on))
    else:
        result = await card_actions.set_field(chat_id, user_id, body.field, body.value)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log("member_card", chat_id=chat_id, actor_id=user_id,
                     details=f"{result.field}{'/clear' if result.cleared else ''}")
    return {"ok": True, "field": result.field, "cleared": result.cleared,
            "card": await card_actions.state(chat_id, user_id)}


@router.post("/api/member/game/card/title/{action}")
async def api_member_title(
    action: str, body: TitleBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    if action not in ("buy", "equip"):
        raise HTTPException(400, "Такого действия нет")
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, "title_buy" if action == "buy" else "title_equip")
    user_id = user.tg_user_id
    # Заморозка гасит траты целиком; надеть уже купленное она не мешает.
    if action == "buy" and await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "buy":
        result = await title_actions.buy(chat_id, user_id, body.key or "")
    else:
        result = await title_actions.equip(chat_id, user_id, body.key)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log(f"title_{result.action}", chat_id=chat_id, actor_id=user_id,
                     details=result.key)
    return {"ok": True, "action": result.action, "key": result.key,
            "name": result.name, "price": result.price,
            "titles": await title_actions.state(chat_id, user_id)}
