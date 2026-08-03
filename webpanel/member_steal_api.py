"""Кабинет участника: медвежатник.

Правила — в steal_actions, общем с ботом. Здесь доступ и то, чего в правилах
быть не может: объявление в чат и весть жертве.

И то и другое ОБЯЗАТЕЛЬНО. В чате кража громкая: сообщение видят все, а
обворованному приходит личка. Промолчи сайт — и он стал бы тихим способом
красть, то есть другой игрой, а не тем же действием через другое окно.

Чужой инвентарь наружу не отдаётся: ключ предмета человек вводит сам, как и в
чате. Показать список чужих вещей значило бы выдать даром то, за чем
существует отдельный платный предмет «Досье», и превратить медвежатник из
риска в выбор из меню.
"""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import black_market
import chats
import db
import farm_actions
import steal_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

_COMMAND = "item_steal"


class StealBody(BaseModel):
    target_id: int
    item_key: str


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


async def _имя(chat_id: int, user_id: int) -> str:
    try:
        row = await db.get_known_user(chat_id, user_id)
    except Exception as exc:
        logger.warning("Медвежатник: имя не прочиталось: %s", exc)
        row = None
    имя = (row or {}).get("full_name") or (row or {}).get("username") or str(user_id)
    return f'<a href="tg://user?id={user_id}">{html.escape(str(имя))}</a>'


@router.get("/api/member/game/steal")
async def api_member_steal(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    return await steal_actions.state(chat_id, user.tg_user_id)


@router.get("/api/member/game/steal/loot")
async def api_member_steal_loot(
    target_id: int, user: PanelUser = Depends(auth.require_member),
):
    """Что лежит у выбранной цели. Открыто только владельцу инструмента —
    решает это сам steal_actions.loot, а не этот обработчик: иначе список
    стал бы бесплатной слежкой за чужими карманами для всего чата."""
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    if not await db.get_known_user(chat_id, target_id):
        raise HTTPException(400, "Этого человека нет в чате.")
    return {"items": await steal_actions.loot(chat_id, user.tg_user_id, target_id)}


async def _рассказать(chat_id: int, user_id: int,
                      итог: steal_actions.StealResult) -> None:
    """В чат — всем, жертве — в личку. Ровно как из чата.

    Ошибку отправки глотаем: дело уже сделано, предметы списаны, и падать
    задним числом означало бы сказать вору «не вышло» после удавшейся кражи.
    """
    вор = await _имя(chat_id, user_id)
    жертва = await _имя(chat_id, итог.target_id)
    название = html.escape(итог.item_name or итог.item_key)

    if итог.outcome == "blocked":
        в_чат = (f"🚨 {вор} вскрыл(а) закрома {жертва}, но взвыла сигнализация — "
                 f"уходить пришлось с пустыми руками.")
        в_личку = (f"🚨 Вашу сигнализацию сорвали — кражу предотвратили, предмет "
                   f"«{название}» остался у вас. Сигнализация израсходована.")
    else:
        в_чат = (f"🗝 {вор} вскрыл(а) закрома и унёс(ла) у {жертва} "
                 f"предмет «{название}».")
        if итог.signal_missed:
            защита = (f"\n🚨 Сигнализация не сработала — она глушит кражу с шансом "
                      f"{black_market.SIGNAL_BLOCK_CHANCE}%. Потрачена не была, "
                      f"остаётся у вас на следующий раз.")
        else:
            защита = (f"\n🚨 От медвежатника есть защита — «Сигнализация» на чёрном "
                      f"рынке: глушит кражу с шансом {black_market.SIGNAL_BLOCK_CHANCE}%.")
        в_личку = (f"🗝 У вас украли предмет «{название}». "
                   f"Работал медвежатник.{защита}")

    бот = get_bot()
    try:
        await бот.send_message(chat_id, в_чат)
    except Exception as exc:
        logger.warning("Медвежатник: объявление в чат не ушло: %s", exc)
    try:
        await бот.send_message(итог.target_id, в_личку)
    except Exception as exc:
        # Закрытые личные сообщения — обычное дело, а не сбой.
        logger.info("Медвежатник: жертве не написать: %s", exc)


@router.post("/api/member/game/steal")
async def api_member_steal_do(
    body: StealBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _COMMAND)
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    # Цель обязана быть человеком из этого же чата: иначе с сайта можно было
    # бы обчистить того, кого бот здесь не видит.
    if not await db.get_known_user(chat_id, body.target_id):
        raise HTTPException(400, "Этого человека нет в чате.")

    итог = await steal_actions.steal(chat_id, user_id, body.target_id, body.item_key)
    if not итог.ok:
        raise HTTPException(400, итог.error)

    if итог.outcome in ("stolen", "blocked"):
        await _рассказать(chat_id, user_id, итог)
    await db.add_log(
        "item_stolen" if итог.outcome == "stolen" else f"item_steal_{итог.outcome}",
        chat_id=chat_id, actor_id=user_id, target_id=итог.target_id,
        details=итог.item_key)

    return {
        "ok": True, "outcome": итог.outcome, "item_key": итог.item_key,
        "item_name": итог.item_name, "signal_missed": итог.signal_missed,
        "slepok_used": итог.slepok_used,
        "state": await steal_actions.state(chat_id, user_id),
    }
