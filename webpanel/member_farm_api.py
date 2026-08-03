"""Кабинет участника: ферма.

Отдельным модулем по той же причине, что и member_game_api: app.py и без того
на четыре тысячи строк. Правила здесь не живут — они в farm_actions, общем с
ботом. Этот файл только пускает или не пускает и переводит результат в JSON.

Тишина держится на том же правиле: отчёт уходит в HTTP-ответ и никуда больше,
в чат идут только ачивки — их положено показать людям, даже если кнопку нажали
на сайте.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chats
import db
import farm_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

# Проставляются из app.py при подключении: модуль не импортирует app, иначе
# получился бы цикл.
get_bot = None
require_member_in_chat = None

# Ачивки фермы: код → как объявить. Дубликат двух строк из bot.ACHIEVEMENTS —
# сам словарь описывает ВСЕ ачивки бота и живёт в bot.py, а панель его
# импортировать не может. Чтобы дубликат не разъехался, тексты сверяет тест
# (tests/test_member_farm_api.py): разойдись они, человек получил бы за одно и
# то же достижение два разных поздравления в зависимости от того, где нажал.
ACHIEVEMENT_TEXTS = {
    "farm_plant_100": "🌱 Достижение: <b>Сто посадок</b> — посадить 100 грядок",
    "farm_harvest_100": "🧺 Достижение: <b>Сто сборов</b> — собрать урожай с грядок 100 раз",
}

# Ключ команды, которым это же действие закрывается в чате (см.
# _check_misc_access в bot.py). Порог обязан быть один: «право farm_plant 2»
# не должно закрывать посадку в чате, оставляя её открытой на сайте.
_LIST_COMMAND = "farm_garden"
_ACTION_COMMANDS = {
    "plant": "farm_plant",
    "harvest": "farm_harvest",
    "expand": "farm_expand",
    "barn_buy": "farm_barn",
    "barn_sell": "farm_barn",
    "barn_collect": "farm_harvest",
}

FROZEN = "🧊 Ваш счёт заморожен администрацией."


class FarmBody(BaseModel):
    crop: Optional[str] = None
    animal: Optional[str] = None
    # Куда сажать. Экран присылает грядку, по которой нажали; в чате её нет.
    slot: Optional[int] = None
    # Число или слово «все» — ровно как в командах чата. Строку разбираем
    # здесь, чтобы farm_actions не гадал, что ему пришло.
    count: Optional[Union[int, str]] = None


def _count(raw: Optional[Union[int, str]], default: int = 1):
    """«все» остаётся словом (farm_actions понимает его сам), число — числом."""
    if raw is None:
        return default
    if isinstance(raw, str):
        if raw.strip().casefold() in ("все", "всё", "all"):
            return "все"
        try:
            return int(raw.strip())
        except ValueError:
            raise HTTPException(400, "Количество — число или слово «все».")
    return int(raw)


# Списываем через db напрямую, а не через bot.spend_coins: та знает про
# «+бесконечность», но это множество в ПАМЯТИ процесса бота, и панели оно не
# видно ни при каком раскладе. Разница ровно одна и касается только владельца
# с включённым режимом: в чате семена ему бесплатны, на сайте — за деньги.
async def _wallet(chat_id: int, user_id: int) -> tuple[int, int]:
    """(звёзды, монеты) — обе цифры из одного кошелька, а не двух запросов."""
    wallet = await db.get_wallet(chat_id, user_id) or {}
    return farm_actions.wallet_stars(wallet), int(wallet.get("coins") or 0)


async def _announce(chat_id: int, result: farm_actions.FarmResult) -> None:
    """Единственное место, откуда ферма кабинета пишет в чат.

    Неудача отправки НЕ отменяет действие: урожай к этому моменту уже в
    инвентаре, и отдать 500 значило бы соврать человеку, что ничего не вышло.
    Так же поступает и кабинет питомцев (см. member_game_api._announce).
    """
    for code in result.achievements:
        text = ACHIEVEMENT_TEXTS.get(code)
        if not text:
            continue
        # Идемпотентно: второй раз тот же код вернёт False и объявления не
        # будет — иначе сотая посадка поздравляла бы и на сто первой.
        if not await db.grant_achievement(chat_id, result.user_id, code):
            continue
        try:
            await get_bot().send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Ферма кабинета: объявление в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


@router.get("/api/member/game/farm")
async def api_member_farm(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    stars, coins = await _wallet(chat_id, user.tg_user_id)
    return await farm_actions.state(
        chat_id, user.tg_user_id, stars=stars, coins=coins,
        event_active=await farm_actions.active_event(chat_id) is not None,
    )


@router.post("/api/member/game/farm/{action}")
async def api_member_farm_action(
    action: str, body: FarmBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if action not in _ACTION_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    # Сначала «а вы вообще в этом чате», потом «а хватает ли уровня»: иначе
    # постороннему сообщали бы, какого права ему не хватает в чужом чате.
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _ACTION_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    stars, coins = await _wallet(chat_id, user_id)
    if action == "plant":
        if not body.crop:
            raise HTTPException(400, "Не выбрана культура.")
        result = await farm_actions.plant(
            chat_id, user_id, body.crop, _count(body.count),
            stars=stars, coins=coins, slot=body.slot,
            event_active=await farm_actions.active_event(chat_id) is not None)
    elif action == "harvest":
        result = await farm_actions.harvest(chat_id, user_id)
    elif action == "expand":
        result = await farm_actions.buy_plots(
            chat_id, user_id, _count(body.count), stars=stars, coins=coins)
    elif action == "barn_collect":
        result = await farm_actions.collect_barn(chat_id, user_id)
    elif action == "barn_buy":
        if not body.animal:
            raise HTTPException(400, "Не выбрано животное.")
        result = await farm_actions.barn_buy(
            chat_id, user_id, body.animal, _count(body.count), coins=coins)
    else:
        if not body.animal:
            raise HTTPException(400, "Не выбрано животное.")
        result = await farm_actions.barn_sell(
            chat_id, user_id, body.animal, _count(body.count))

    result.user_id = user_id
    if not result.ok:
        # Отказ по правилу игры — это 400 с человеческим текстом, а не пустой
        # успех: сайт показывает его тем же местом, где показал бы бот.
        raise HTTPException(400, result.error or "Не вышло.")

    # Журнал ПЕРЕД объявлениями: действие уже случилось, и след о нём не должен
    # зависеть от того, дошло ли поздравление до чата.
    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"farm/{action}")
    await _announce(chat_id, result)

    # Состояние возвращаем сразу: экран перерисовывается ответом на действие, а
    # не вторым запросом — иначе между «посадил» и «увидел» успевает моргнуть
    # старая картинка.
    stars, coins = await _wallet(chat_id, user_id)
    return {
        "ok": True,
        "planted": result.planted, "harvested": result.harvested,
        "items": result.items, "coins_spent": result.coins_spent,
        "coins_gained": result.coins_gained, "truffles": result.truffles,
        "perished": result.perished, "pest_loss": result.pest_loss,
        "state": await farm_actions.state(
            chat_id, user_id, stars=stars, coins=coins,
            event_active=await farm_actions.active_event(chat_id) is not None),
    }
