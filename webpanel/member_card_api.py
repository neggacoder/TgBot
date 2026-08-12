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
import achievements_meta
import businesses as business_catalog
import fishing

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
    "gender": "gender", "citizen": "citizenship", "visible": "anketa_visibility",
}
_PIN_COMMANDS = {
    "item": "shop_list", "achievement": "achievement_pin", "business": "business_pin",
    "pet": "pet_care", "fish": "fishing_net", "doll": "craft",
}


class FieldBody(BaseModel):
    field: str
    value: Optional[str] = None
    on: Optional[bool] = None


class TitleBody(BaseModel):
    key: Optional[str] = None


class PinBody(BaseModel):
    field: str
    value: Optional[str] = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


async def _витрина(chat_id: int, user_id: int) -> dict:
    """Кандидаты для витрины профиля, собранные только из вещей владельца."""
    card = await db.get_profile_card(chat_id, user_id) or {}
    items = await db.list_inventory(chat_id, user_id)
    earned = {row["code"] for row in await db.get_achievements(chat_id, user_id)}
    businesses = await db.list_user_businesses(chat_id, user_id)
    pets = await db.list_pets(chat_id, user_id)
    net = await db.list_net(chat_id, user_id)
    dolls = await db.list_voodoo_dolls(chat_id, user_id)

    def option(value, label):
        return {"value": str(value), "label": label}

    return {
        "selected": {
            "item": card.get("pinned_item"),
            "achievement": card.get("pinned_achievement"),
            "business": card.get("pinned_business"),
            "pet": card.get("pinned_pet"),
            "fish": str(card["pinned_fish"]) if card.get("pinned_fish") is not None else None,
            "doll": str(card["pinned_doll"]) if card.get("pinned_doll") is not None else None,
        },
        "options": {
            "item": [option(r["item_key"], f"{r.get('emoji') or '🎁'} {r.get('name') or r['item_key']} · {int(r.get('quantity') or 0)} шт.") for r in items],
            "achievement": [option(code, f"{achievements_meta.ACHIEVEMENTS[code]['emoji']} {achievements_meta.ACHIEVEMENTS[code]['title']}") for code in sorted(earned & set(achievements_meta.ACHIEVEMENTS))],
            "business": [option(r["business_key"], (business_catalog.BY_KEY.get(r["business_key"]).name if r["business_key"] in business_catalog.BY_KEY else r["business_key"]) + f" · {int(r.get('level') or 1)} ур.") for r in businesses],
            "pet": [option(r["pet_key"], r.get("pet_name") or r["pet_key"]) for r in pets],
            "fish": [option(r["id"], f"{(fishing.BY_KEY.get(r['species_key']).emoji if r['species_key'] in fishing.BY_KEY else '🎣')} {(fishing.BY_KEY.get(r['species_key']).name if r['species_key'] in fishing.BY_KEY else r['species_key'])} · {fishing.format_weight(int(r['grams']))}") for r in net],
            "doll": [option(r["target_id"], f"🧵 {r.get('target_name') or r['target_id']}") for r in dolls],
        },
    }


@router.get("/api/member/game/card")
async def api_member_card(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, "anketa")
    return {
        "card": await card_actions.state(chat_id, user.tg_user_id),
        "titles": await title_actions.state(chat_id, user.tg_user_id),
        "pins": await _витрина(chat_id, user.tg_user_id),
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

    if body.field == "gender":
        result = await card_actions.set_gender(chat_id, user_id, body.value)
    elif body.field == "citizen":
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


@router.post("/api/member/game/card/pin")
async def api_member_card_pin(
    body: PinBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    """Закрепить одну принадлежащую пользователю вещь либо снять закреп."""
    auth.verify_csrf(request)
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, "anketa")
    user_id = user.tg_user_id
    field = body.field
    value = (body.value or "").strip()
    command = _PIN_COMMANDS.get(field)
    if command is None:
        raise HTTPException(400, "Такого места в витрине нет")
    await permissions.ensure(user, command)
    choices = await _витрина(chat_id, user_id)
    allowed = {str(x["value"]) for x in choices["options"][field]}
    if value and value not in allowed:
        raise HTTPException(400, "Можно закрепить только свою вещь.")

    setters = {
        "item": db.set_pinned_item,
        "achievement": db.set_pinned_achievement,
        "business": db.set_pinned_business,
        "pet": db.set_pinned_pet,
        "fish": db.set_pinned_fish,
        "doll": db.set_pinned_doll,
    }
    stored = int(value) if field in ("fish", "doll") and value else (value or None)
    await setters[field](chat_id, user_id, stored)
    await db.add_log("member_profile_pin", chat_id=chat_id, actor_id=user_id,
                     details=f"{field}:{stored or '-'}")
    return {"ok": True, "pins": await _витрина(chat_id, user_id)}


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
