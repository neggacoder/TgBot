"""Кабинет участника: бизнесы.

Правила — в business_actions, общем с ботом. Здесь только доступ и перевод
результата в JSON.

Передача и продажа ДРУГОМУ игроку идут через подтверждение: сайт только
предлагает, а соглашается вторая сторона кнопкой в чате. Односторонняя сделка
отдала бы человеку чужой бизнес без спроса — вместе с налогом на копилку и
обязанностью его чинить. Само предложение живёт в базе, потому что нажимают
кнопку в другом процессе (см. business_actions.offer).
"""

from __future__ import annotations

import html
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import business_actions
import casino_actions
import chats
import collection_actions
import db
import farm_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

get_bot = None
require_member_in_chat = None

FROZEN = "🧊 Ваш счёт заморожен администрацией."

# Дубликат двух строк из bot.ACHIEVEMENTS (словарь живёт в bot.py и панели
# недоступен). Тексты сверяет тест — разъедься они, за одно достижение
# приходили бы два разных поздравления.
ACHIEVEMENT_TEXTS = {
    "coins_10000": "💵 Достижение: <b>Богач</b> — накопить 10 000 i¢ в кошельке",
    "coins_100000": "🏦 Достижение: <b>Магнат</b> — накопить 100 000 i¢ в кошельке",
}

_LIST_COMMAND = "business_mine"
_ACTION_COMMANDS = {
    "buy": "business_buy",
    "collect": "business_collect",
    "upgrade": "business_upgrade",
    "repair": "business_repair",
    "equip": "business_equip",
    "sell": "business_sell",
    # Предложить сделку человеку. Права те же, что в чате: продажа — своё,
    # дарение — своё; какое именно, решает цена.
    "offer": "business_sell",
    "give": "business_transfer",
}


class BizBody(BaseModel):
    key: Optional[str] = None      # какой бизнес
    gear: Optional[str] = None     # какое оснащение
    # Сделка с человеком: кому и за сколько (0 — в дар).
    target_id: Optional[int] = None
    target: Optional[str] = None   # можно @ником — ищем в реестре бота
    price: Optional[int] = None


async def _announce(chat_id: int, result: business_actions.BizResult) -> None:
    """Ачивки — единственное, что уходит в чат само."""
    for code in result.achievements:
        text = ACHIEVEMENT_TEXTS.get(code)
        if not text:
            continue
        if not await db.grant_achievement(chat_id, result.user_id, code):
            continue
        try:
            await get_bot().send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Бизнесы кабинета: объявление в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


async def _check_collections(chat_id: int, user_id: int) -> None:
    """Покупка или прокачка бизнеса в кабинете закрывает те же коллекции."""
    try:
        awards = await collection_actions.check_collections(
            chat_id, user_id, today=await casino_actions.local_today())
    except Exception as exc:
        logger.warning("Бизнесы кабинета: не проверились коллекции: %s: %s",
                       type(exc).__name__, exc)
        return
    for collection in awards:
        try:
            await get_bot().send_message(
                chat_id,
                await collection_actions.site_announcement(chat_id, user_id, collection),
            )
        except Exception as exc:
            logger.warning("Бизнесы кабинета: объявление о коллекции в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


@router.get("/api/member/game/business")
async def api_member_business(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    return await business_actions.state(chat_id, user.tg_user_id)


@router.post("/api/member/game/business/{action}")
async def api_member_business_action(
    action: str, body: BizBody, request: Request,
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

    if action in ("offer", "give"):
        return await _offer(chat_id, user_id, body, дарение=(action == "give"))

    if action == "collect":
        # Без ключа — забрать со всех разом: налог считается от общей суммы, и
        # собирать по одному было бы просто дороже (см. business_actions).
        result = await business_actions.collect(chat_id, user_id, body.key)
    elif action in ("buy", "upgrade", "repair", "sell"):
        if not body.key:
            raise HTTPException(400, "Не выбран бизнес.")
        действие = {"buy": business_actions.buy,
                    "upgrade": business_actions.upgrade,
                    "repair": business_actions.repair,
                    "sell": business_actions.sell_to_bot}[action]
        result = await действие(chat_id, user_id, body.key)
    else:
        if not body.key or not body.gear:
            raise HTTPException(400, "Не выбраны бизнес и оснащение.")
        result = await business_actions.equip(chat_id, user_id, body.key, body.gear)

    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"business/{action} {result.key or ''}")
    if action in ("buy", "upgrade", "equip"):
        await _check_collections(chat_id, user_id)
    await _announce(chat_id, result)
    return {
        "ok": True, "key": result.key, "level": result.level,
        "gross": result.gross, "tax": result.tax, "net": result.net,
        "spent": result.spent, "count": result.count, "free": result.free,
        "state": await business_actions.state(chat_id, user_id),
    }


async def _offer(chat_id: int, user_id: int, body: BizBody, *, дарение: bool) -> dict:
    """Предложить сделку и отправить её в чат кнопкой.

    В чат, а не в личку: подтверждать должен именно тот человек, а найти его
    личку у бота может не быть права — зато в чате он точно есть, раз бот его
    там видел. Заодно сделка видна всем, как и любая другая в этом чате.
    """
    if not body.key:
        raise HTTPException(400, "Не выбран бизнес.")
    кому = body.target_id
    if not кому and body.target:
        # @ник ищем в РЕЕСТРЕ бота, а не у телеграма: Bot API не умеет
        # превращать чужой @username в user_id (см. resolve_rel2_target).
        найден = await db.get_known_user_by_username_in_chat(
            chat_id, body.target.lstrip("@").strip())
        кому = найден and найден.get("user_id")
    if not кому:
        raise HTTPException(400, "Не выбран человек — укажите @ник того, "
                                 "кого бот уже видел в этом чате.")
    цена = 0 if дарение else max(0, int(body.price or 0))
    if not дарение and цена <= 0:
        raise HTTPException(400, "Цена должна быть больше нуля.")

    получатель = await db.get_known_user(chat_id, кому)
    if not получатель:
        raise HTTPException(400, "Бот ещё не видел этого человека в этом чате.")

    result = await business_actions.offer(chat_id, user_id, кому, body.key, цена)
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    item = business_actions.catalog.BY_KEY.get(result.key)
    имя_кому = html.escape(str(получатель.get("full_name")
                               or получатель.get("username") or "Игрок"))
    продавец = await db.get_known_user(chat_id, user_id)
    имя_кто = html.escape(str((продавец or {}).get("full_name")
                              or (продавец or {}).get("username") or "Игрок"))
    строки = [
        "🤝 <b>Сделка</b>",
        f"{имя_кто} {'дарит' if дарение else 'продаёт'} {имя_кому}",
        f"{item.name if item else result.key} · {result.level} ур.",
    ]
    if not дарение:
        строки.append(f"Цена: <b>{цена}</b> i¢")
    if result.gross:
        строки.append(f"Копилку ({result.gross} i¢) владелец заберёт себе "
                      "с налогом — бизнес перейдёт пустым.")
    строки.append(f"Согласиться может только {имя_кому}. "
                  f"Предложение живёт {business_actions.OFFER_TTL_SECONDS // 60} мин.")

    try:
        await get_bot().send_message(
            chat_id, "\n".join(строки),
            reply_markup=_deal_keyboard(result.deal_id, цена))
    except Exception as exc:
        # Сделка ещё ничего не двигала — просто снимаем предложение, чтобы оно
        # не висело без кнопки.
        await db.delete_data(business_actions.deal_key(chat_id, result.deal_id))
        logger.warning("Бизнесы кабинета: сделка в чат %s не ушла: %s: %s",
                       chat_id, type(exc).__name__, exc)
        raise HTTPException(400, "Не удалось отправить предложение в чат.")

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     target_id=кому,
                     details=f"business/offer {result.key}:{цена}")
    return {"ok": True, "deal_id": result.deal_id, "sent": True,
            "state": await business_actions.state(chat_id, user_id)}


def _deal_keyboard(deal_id: int, price: int) -> dict:
    """Кнопки под предложением. Разметку собираем словарём: у панели нет
    aiogram-типов, а Bot API принимает обычный JSON.

    Обрабатывает нажатие БОТ (cb_business_site_deal в bot.py) — префикс и
    формат обязаны совпадать с ним дословно.
    """
    беру = "✅ Принять" if not price else f"✅ Купить за {price} i¢"
    return {"inline_keyboard": [[
        {"text": беру, "callback_data": f"bizdeal:{deal_id}:ok"},
        {"text": "✖️ Отказаться", "callback_data": f"bizdeal:{deal_id}:no"},
    ]]}
