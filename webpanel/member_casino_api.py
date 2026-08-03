"""Кабинет участника: казино.

Правила — в casino_actions, общем с ботом. Здесь только доступ, деньги и
кнопка «показать в чате».

Про кнопку. Текст сообщения НИКОГДА не приходит из браузера: сыграв, человек
получает результат, а сервер запоминает у себя готовую строку и по нажатию
отправляет именно её. Иначе «покажи всем» превращается в право написать в чат
от имени бота что угодно — например, чужой выигрыш, которого не было.

Отметка одноразовая: показать один заход можно один раз. Плюс пауза между
показами — казино на сайте играется быстро, и без неё чат превращается в
ленту чужих ставок.
"""

from __future__ import annotations

import html
import json
import logging
import time
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import casino_actions
import chats
import db
import farm_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

# Проставляются из app.py при подключении (см. member_game_api).
get_bot = None
require_member_in_chat = None

# Сколько ждать между показами в чат. Не про безопасность, а про соседей:
# заход в казино занимает секунду, и без паузы один игрок залил бы чат.
SHARE_COOLDOWN_SECONDS = 45

# Сколько живёт право показать заход. Отметка лежит в базе и переживает
# закрытие вкладки: без срока человек, вернувшийся назавтра, отправил бы в чат
# вчерашний выигрыш как свежий — а соседи прочитали бы его как только что
# случившийся.
SHARE_TTL_SECONDS = 10 * 60

FROZEN = "🧊 Ваш счёт заморожен администрацией."

# Ачивки казино: код → как объявить. Дубликат двух строк из bot.ACHIEVEMENTS
# (сам словарь живёт в bot.py и панели недоступен); тексты сверяет тест.
ACHIEVEMENT_TEXTS = {
    "casino_100_games": "🃏 Достижение: <b>Завсегдатай казино</b> — сыграть в казино 100 раз",
    "casino_jackpot": "🎰 Достижение: <b>Джекпот</b> — выиграть в казино 5 000 i¢ и более за раз",
}

_LIST_COMMAND = "casino_balance"
_GAME_COMMANDS = {
    "roulette": "casino_roulette",
    "dice": "casino_dice",
    "coin": "casino_coin",
    "poker": "casino_poker",
}
_MONEY_COMMANDS = {
    "topup": "casino_topup",
    "withdraw": "casino_withdraw",
    "bonus": "casino_balance",
    # Показ в чате — не отдельная команда бота: право берём от баланса, то
    # есть от самого доступа в казино.
    "share": "casino_balance",
}


class CasinoBody(BaseModel):
    # Ставка: число или слово «все» — как в чате.
    bet: Optional[Union[int, str]] = None
    color: Optional[str] = None      # рулетка
    guess: Optional[int] = None      # кости
    side: Optional[str] = None       # орёл/решка
    amount: Optional[Union[int, str]] = None   # пополнить/вывести


def _share_key(chat_id: int, user_id: int) -> str:
    return f"casino_share:{chat_id}:{user_id}"


def _share_at_key(chat_id: int, user_id: int) -> str:
    """Когда показывали в прошлый раз. Отдельным ключом, потому что сам показ
    свою отметку СТИРАЕТ (заход одноразовый), и хранить время в ней значило бы
    забывать про паузу ровно тогда, когда она нужна."""
    return f"casino_share_at:{chat_id}:{user_id}"


async def _remember_share(chat_id: int, user_id: int, text: str) -> None:
    """Запоминает, что можно показать. Перезаписывает прошлый заход: показать
    можно только СВЕЖИЙ результат, а не выбрать лучший из истории."""
    await db.set_data(_share_key(chat_id, user_id),
                      json.dumps({"text": text, "at": int(time.time())},
                                 ensure_ascii=False),
                      updated_by=user_id)


async def _fresh_share(chat_id: int, user_id: int) -> Optional[str]:
    """Текст последнего захода, если он ещё не протух. None — показывать
    нечего: либо не играли, либо результат старше SHARE_TTL_SECONDS."""
    row = await db.get_data(_share_key(chat_id, user_id))
    if not row:
        return None
    try:
        данные = json.loads(row["data_value"])
        текст = str(данные["text"])
        когда = int(данные.get("at") or 0)
    except (ValueError, TypeError, KeyError):
        await db.delete_data(_share_key(chat_id, user_id))
        return None
    if int(time.time()) - когда > SHARE_TTL_SECONDS:
        await db.delete_data(_share_key(chat_id, user_id))
        return None
    return текст


async def _player_name(chat_id: int, user_id: int) -> str:
    """Как назвать игрока в чате. В чате бот отвечает на его сообщение, и имя
    не нужно; с сайта результат приходит сам по себе — без имени чат увидит
    выигрыш ничей."""
    try:
        row = await db.get_known_user(chat_id, user_id)
    except Exception as exc:
        logger.warning("Казино кабинета: имя не прочиталось: %s", exc)
        row = None
    имя = (row or {}).get("full_name") or (row or {}).get("username") or "Игрок"
    return html.escape(str(имя))


async def _announce(chat_id: int, result: casino_actions.RoundResult) -> None:
    """Ачивки — единственное, что казино кабинета шлёт в чат само.

    Сам результат в чат не идёт: его отправляет человек кнопкой, если хочет.
    Неудача отправки не отменяет игру — ставка уже сыграна.
    """
    for code in result.achievements:
        text = ACHIEVEMENT_TEXTS.get(code)
        if not text:
            continue
        if not await db.grant_achievement(chat_id, result.user_id, code):
            continue
        try:
            await get_bot().send_message(chat_id, text)
        except Exception as exc:
            logger.warning("Казино кабинета: объявление в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


@router.get("/api/member/game/casino")
async def api_member_casino(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    состояние = await casino_actions.state(
        chat_id, user.tg_user_id, today=await casino_actions.local_today())
    # Есть ли что показать в чате — экран рисует кнопку только тогда, и только
    # пока заход свежий.
    состояние["can_share"] = await _fresh_share(chat_id, user.tg_user_id) is not None
    return состояние


@router.post("/api/member/game/casino/play/{game}")
async def api_member_casino_play(
    game: str, body: CasinoBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if game not in _GAME_COMMANDS:
        raise HTTPException(400, "Такой игры нет")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _GAME_COMMANDS[game])
    user_id = user.tg_user_id
    # Заморозка закрывает казино и на сайте — так же, как в чате
    # (см. try_spend_casino в bot.py).
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    ставка = body.bet if body.bet is not None else 0
    if game == "roulette":
        result = await casino_actions.roulette(chat_id, user_id, ставка, body.color or "")
    elif game == "dice":
        result = await casino_actions.dice(chat_id, user_id, ставка, body.guess or 0)
    elif game == "coin":
        result = await casino_actions.coin(chat_id, user_id, ставка, body.side or "")
    else:
        result = await casino_actions.poker(chat_id, user_id, ставка)

    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")

    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"casino/{game} bet={result.bet} delta={result.delta}")
    await _announce(chat_id, result)
    # Готовый текст кладём сразу: кнопка «показать в чате» ничего не сочиняет,
    # она лишь разрешает отправить уже случившееся.
    await _remember_share(chat_id, user_id,
                          casino_actions.render_share(
                              result, await _player_name(chat_id, user_id)))
    return {
        "ok": True, "game": result.game, "bet": result.bet, "won": result.won,
        "delta": result.delta, "multiplier": result.multiplier,
        "balance": result.balance, "detail": result.detail,
        "can_share": True,
    }


@router.post("/api/member/game/casino/{action}")
async def api_member_casino_money(
    action: str, body: CasinoBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")

    if action not in _MONEY_COMMANDS:
        raise HTTPException(400, "Такого действия нет")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _MONEY_COMMANDS[action])
    user_id = user.tg_user_id
    if await farm_actions.is_account_frozen(chat_id, user_id):
        raise HTTPException(400, FROZEN)

    if action == "share":
        return await _share(chat_id, user_id)

    сумма = body.amount if body.amount is not None else 0
    if action == "topup":
        result = await casino_actions.topup(chat_id, user_id, сумма)
    elif action == "withdraw":
        result = await casino_actions.withdraw(chat_id, user_id, сумма)
    else:
        result = await casino_actions.daily_bonus(
            chat_id, user_id, today=await casino_actions.local_today())
    if not result.ok:
        raise HTTPException(400, result.error or "Не вышло.")
    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details=f"casino/{action} {result.delta}")
    return {"ok": True, "delta": result.delta, "balance": result.balance,
            "state": await casino_actions.state(
                chat_id, user_id, today=await casino_actions.local_today())}


async def _share(chat_id: int, user_id: int) -> dict:
    """Показать в чате последний свой заход. Один раз и не чаще, чем раз в
    SHARE_COOLDOWN_SECONDS."""
    текст = await _fresh_share(chat_id, user_id)
    if текст is None:
        raise HTTPException(400, "Показывать нечего — сыграйте заход ещё раз.")

    прошлый = await db.get_data(_share_at_key(chat_id, user_id))
    try:
        было = int((прошлый or {}).get("data_value") or 0)
    except (TypeError, ValueError):
        было = 0
    ждать = было + SHARE_COOLDOWN_SECONDS - int(time.time())
    if ждать > 0:
        raise HTTPException(400, f"Слишком часто — подождите {ждать} с.")

    if get_bot is None:
        raise HTTPException(500, "Бот недоступен")
    try:
        await get_bot().send_message(chat_id, текст)
    except Exception as exc:
        logger.warning("Казино кабинета: показ в чат %s не ушёл: %s: %s",
                       chat_id, type(exc).__name__, exc)
        raise HTTPException(400, "Не удалось отправить в чат — попробуйте позже.")

    # Отметку снимаем ПОСЛЕ удачной отправки: сними раньше — и не дошедшее
    # сообщение оставило бы человека без возможности повторить.
    await db.delete_data(_share_key(chat_id, user_id))
    await db.set_data(_share_at_key(chat_id, user_id), str(int(time.time())),
                      updated_by=user_id)
    await db.add_log("member_game", chat_id=chat_id, actor_id=user_id,
                     details="casino/share")
    return {"ok": True, "shared": True}
