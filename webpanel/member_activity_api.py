"""Кабинет участника: рыбалка и работа.

Одним модулем на два занятия: у них общий каркас — кулдаун, действие, отчёт, —
и разводить это по двум почти одинаковым файлам значило бы дважды править
любую правку доступа.

Правила живут в fishing_actions и work_actions, общих с ботом. Здесь только
доступ и перевод результата в JSON.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import db
import farm_actions
import fishing_actions
import work_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

# Дубликаты строк из bot.ACHIEVEMENTS (словарь живёт в bot.py и панели
# недоступен). Тексты сверяет тест.
ACHIEVEMENT_TEXTS = {
    "fish_100": "🎣 Достижение: <b>Рыбак</b> — поймать 100 уловов",
    "coins_10000": "💵 Достижение: <b>Богач</b> — накопить 10 000 i¢ в кошельке",
    "coins_100000": "🏦 Достижение: <b>Магнат</b> — накопить 100 000 i¢ в кошельке",
    "work_20": "🤖 Достижение: <b>Работяга</b> — отработать 20 смен",
}

_FISH_LIST = "fishing_net"
_FISH_COMMANDS = {"cast": "fishing_run", "sell": "fishing_net",
                  "release": "fishing_net", "pin": "fishing_net"}
_WORK_LIST = "prof_profile"
# Перерыв в чате идёт без отдельного права — берём то же, что у смены.
_WORK_COMMANDS = {"shift": "prof_run", "rest": "prof_run"}


class ActivityBody(BaseModel):
    fish_id: Optional[int] = None     # какую рыбу продать/выпустить/закрепить


async def _announce(chat_id: int, result) -> None:
    """Ачивки — единственное, что уходит в чат само. Улов и смена остаются в
    ответе: это личное занятие, а не объявление."""
    for code in getattr(result, "achievements", ()):
        text = ACHIEVEMENT_TEXTS.get(code)
        if not text:
            continue
        if not await db.grant_achievement(chat_id, result.user_id, code):
            continue
        try:
            await get_bot().send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Занятия кабинета: объявление в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


async def _gate(user: PanelUser, chat_id: int, command: str) -> None:
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, command)


# --- рыбалка ----------------------------------------------------------------
@router.get("/api/member/game/fishing")
async def api_member_fishing(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await _gate(user, chat_id, _FISH_LIST)
    return await fishing_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/fishing/{action}")
async def api_member_fishing_action(
    action: str, body: ActivityBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if action not in _FISH_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    await _gate(user, chat_id, _FISH_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "cast":
        result = await fishing_actions.cast(chat_id, user_id)
    elif action == "sell":
        result = await fishing_actions.sell(chat_id, user_id, body.fish_id)
    elif action == "release":
        if body.fish_id is None:
            raise HTTPException(400, "Не выбрана рыба.")
        result = await fishing_actions.release(chat_id, user_id, body.fish_id)
    else:
        result = await fishing_actions.pin(chat_id, user_id, body.fish_id)

    if not result.ok:
        # У заброса отказ бывает штатным («ещё не время»), и экран рисует по
        # нему таймер — поэтому срок следующего заброса едет вместе с отказом.
        raise HTTPException(400, result.error or "Не вышло.",
                            headers={"X-Next-At": result.next_at or ""})

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"fishing/{action}")
    await _announce(chat_id, result)
    return {
        "ok": True, "action": action,
        "species": result.species, "name": result.name, "emoji": result.emoji,
        "rarity": result.rarity, "grams": result.grams, "price": result.price,
        "junk": result.junk, "lucky": result.lucky, "record": result.record,
        "released": result.released, "evicted": result.evicted,
        "coins": result.coins, "sold": result.sold, "passive": result.passive,
        "multiplier": result.multiplier,
        "state": await fishing_actions.state(chat_id, user_id),
    }


# --- работа -----------------------------------------------------------------
@router.get("/api/member/game/work")
async def api_member_work(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await _gate(user, chat_id, _WORK_LIST)
    return await work_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/work/{action}")
async def api_member_work_action(
    action: str, body: ActivityBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if action not in _WORK_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    await _gate(user, chat_id, _WORK_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    result = (await work_actions.shift(chat_id, user_id) if action == "shift"
              else await work_actions.rest(chat_id, user_id))
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.",
                            headers={"X-Next-At": result.next_at or ""})

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"work/{action}")
    await _announce(chat_id, result)
    return {
        "ok": True, "action": action, "income": result.income, "xp": result.xp,
        "level": result.level, "level_up": result.level_up,
        "energy": result.energy, "mood": result.mood, "health": result.health,
        "streak": result.streak, "burnout": result.burnout, "union": result.union,
        "event": result.event, "office": result.office,
        "mentor_share": result.mentor_share, "graduated": result.graduated,
        "state": await work_actions.state(chat_id, user_id),
    }
