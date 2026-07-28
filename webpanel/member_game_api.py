"""Кабинет участника: игра через сайт.

Отдельным модулем, а не дописыванием в app.py: тот уже 4400+ строк.

Тишина держится на одном: отчёт возвращается в HTTP-ответе и никуда больше,
а в чат уходят только объявления — ачивки, уровни, звёзды. Их шлёт ровно одно
место (_announce), и тест это стережёт: второй такой вызов в этом файле — уже
спам.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import db
import game_actions

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

# Проставляются из app.py при подключении: модуль не импортирует app,
# иначе получился бы цикл.
get_bot = None
require_member_in_chat = None


class PetActionBody(BaseModel):
    chat_id: int
    key: Optional[str] = None
    name: Optional[str] = None
    confirm: bool = False
    # Только для care_all: каким из трёх слов приласкать всех разом. Для
    # одиночных pet/hug/kiss слово уже зашито в ключ действия и это поле не
    # читается.
    verb: Optional[str] = None


async def _announce(chat_id: int, result: game_actions.ActionResult) -> None:
    """Единственное место, откуда кабинет пишет в чат.

    Отчёт о нажатии сюда не попадает никогда — только награды, которые
    положено показать людям, даже если кнопку нажали на сайте.

    Неудача отправки НЕ отменяет действие и не превращается в ошибку сайта.
    Питомец к этому моменту уже накормлен, а уровень записан: бота могли
    выгнать из чата, разметка могла не разобраться — это про чат, а не про
    действие. Отдать в ответ 500 значило бы соврать человеку, что ничего не
    вышло, и позвать его покормить второй раз впустую. Так же поступает и
    сам бот: объявление о собранной коллекции у него завёрнуто в try (см.
    _check_collections в bot.py).
    """
    for item in result.announcements:
        try:
            await get_bot().send_message(chat_id, item.text)
        except Exception as exc:
            logger.warning("Кабинет: объявление в чат %s не ушло: %s: %s",
                           chat_id, type(exc).__name__, exc)


# Ключ команды, которым это же действие закрывается в чате (см.
# _check_misc_access в обработчиках bot.py). Админ поднимает порог командой
# «право», и порог обязан быть один: «право pet_care 2» не должно закрывать
# кормление в чате, оставляя его открытым на сайте — это две разные правды об
# одном праве, и вторая обнаруживается только по жалобе.
#
# Умолчание у этих команд — нулевой уровень, так что обычный участник ничего
# не теряет: проверка начинает работать ровно тогда, когда порог подняли.
_LIST_COMMAND = "pet_list"
_ACTION_COMMANDS = {
    "feed": "pet_care",
    "feed_all": "pet_care",
    "pet": "pet_care",
    "hug": "pet_care",
    "kiss": "pet_care",
    "care_all": "pet_care",
    "walk": "pet_care",
    "walk_all": "pet_care",
    # Покупки и продажи здесь нет намеренно — их у кабинета нет вообще
    # (см. _DISABLED). Вернутся — вернутся с ключом pet_buy: в чате его
    # спрашивают оба обработчика, и cmd_pet_buy, и cmd_pet_sell.
    "rename": "pet_care",
    "pin": "pet_care",
    "unpin": "pet_care",
    "food": "pet_care",
}


@router.get("/api/member/game/pets")
async def api_member_pets(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    # own=True: это экран «мои питомцы», а не просмотр чужого профиля — тех же
    # двух исходов (свой/чужой), что и у cmd_pets_mine в bot.py, кабинет не
    # различает: посмотреть чужих питомцев с сайта негде.
    result = await game_actions.my_pets_text(chat_id, user.tg_user_id, own=True)
    # Текст остаётся как есть — его человек и читает. Рядом отдаём тех же
    # питомцев списком: вкладке нужен ключ на каждую кнопку, а без ключа
    # действие уходит «кому-нибудь» и у любого, у кого питомцев больше
    # одного, отбивается советом набрать команду в чате.
    return {"ok": result.ok, "text": result.text,
            "pets": await game_actions.my_pets_list(chat_id, user.tg_user_id)}


# Слово ласки для care_pet/care_all — то же самое, что разбирает регулярка
# бота (см. bot.PET_CARE_VERBS), только с сайта оно приходит не текстом
# сообщения, а именем кнопки.
_CARE_VERBS = {"pet": "погладить", "hug": "обнять", "kiss": "поцеловать"}

_ACTIONS = {
    "feed": lambda body, chat_id, uid: game_actions.feed_pet(chat_id, uid, body.key),
    "feed_all": lambda body, chat_id, uid: game_actions.feed_all(chat_id, uid),
    "pet": lambda body, chat_id, uid: game_actions.care_pet(
        chat_id, uid, _CARE_VERBS["pet"], body.key),
    "hug": lambda body, chat_id, uid: game_actions.care_pet(
        chat_id, uid, _CARE_VERBS["hug"], body.key),
    "kiss": lambda body, chat_id, uid: game_actions.care_pet(
        chat_id, uid, _CARE_VERBS["kiss"], body.key),
    # body.verb проверен обработчиком (api_member_pet_action, отдельной
    # веткой на care_all) ДО того, как лямбда его прочитает, — там же
    # написано, почему непонятное слово это отказ, а не подстановка
    # «погладить». Поэтому прямое индексирование здесь безопасно.
    "care_all": lambda body, chat_id, uid: game_actions.care_all(
        chat_id, uid, _CARE_VERBS[body.verb]),
    "walk": lambda body, chat_id, uid: game_actions.walk_pet(chat_id, uid, body.key),
    "walk_all": lambda body, chat_id, uid: game_actions.walk_all(chat_id, uid),
    "rename": lambda body, chat_id, uid: game_actions.rename_pet(
        chat_id, uid, body.key, body.name),
    "pin": lambda body, chat_id, uid: game_actions.pin_pet(chat_id, uid, body.key),
    "unpin": lambda body, chat_id, uid: game_actions.unpin_pet(chat_id, uid),
    # raw_qty всегда None: с числом buy_food честно отказывает («купите
    # словом боту в чате» — см. её докстринг) — общего магазина (скидки,
    # распродажи, остаток на полке) у кабинета нет и до переноса подпроекта 2
    # не будет. Кабинету доступна только эта ветка — показать цену и остаток.
    "food": lambda body, chat_id, uid: game_actions.buy_food(chat_id, uid, None),
}

# Действия, которых у кабинета НЕТ, — с объяснением вместо «такого действия
# нет»: адрес существует, отказ осознанный.
#
# Покупка. Бот зовёт buy_pet с on_bought=_check_collections, кабинет не может:
# функция живёт в bot.py, а импортировать его панели нельзя — это поднимет
# второго бота. Худший случай не выдуманный: человек покупает с сайта
# последнего недостающего питомца «Зоопарка» и не получает ни титула, ни
# ачивки, ни Единорога, и пересчёта не будет, пока он не сделает что-нибудь в
# чате. Бот ещё передаёт spend=spend_coins, знающий про «+бесконечность», —
# владелец, купивший с сайта, заплатил бы как все.
#
# Продажа закрыта заодно, и причина у неё своя: пересчёта коллекций после
# продажи не делает и сам бот, зато без покупки продажа — дорога в одну
# сторону. Продать питомца с сайта (уровень и опыт сгорают безвозвратно), а
# завести обратно уйти в чат — не то, что стоит выставлять наружу.
#
# Что нужно, чтобы вернуть обе: в общий модуль должен переехать пересчёт
# коллекций — bot._check_collections вместе с тем, на чём он держится
# (_collection_progress, grant_achievement, выдача титула). Тогда buy_pet
# получит его тем же аргументом on_bought, что и у бота, и разницы между
# чатом и сайтом не останется.
_DISABLED = {
    "buy": "Питомцев пока покупают только в чате: с сайта не пересчитались бы "
           "коллекции — за собранный «Зоопарк» не пришли бы ни титул, ни "
           "ачивка. Команда: «пет купить {ключ}».",
    "sell": "Питомцев пока продают только в чате — там же, где их покупают: "
            "уровень и опыт при продаже сгорают безвозвратно. "
            "Команда: «пет продать {ключ}».",
}

# Поля, без которых действие падает НЕ на правиле игры, а на самом обращении
# к ним: rename зовёт raw_name.strip() ДО первого обращения к базе — значит
# 500 у панели ловится не в бою, а на пустой форме. Остальные действия здесь
# не перечислены не по забывчивости: они идут через pick_pet/_pet_spec,
# которые сами возвращают опрятный отказ на None (см. game_actions.pick_pet
# — «без ключа берём единственного»). Словарь, а не россыпь if: новое
# действие, читающее свой ключ так же небрежно, обязано попасть сюда явно, а
# не остаться безымянной дырой. Покупка тоже читает ключ небрежно
# (raw_key.casefold()) — вернётся из _DISABLED, вернётся и сюда.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "rename": ("key", "name"),
}
_FIELD_LABELS = {"key": "питомец", "name": "имя"}


def _missing_fields(action: str, body: "PetActionBody") -> list[str]:
    return [_FIELD_LABELS[f] for f in _REQUIRED_FIELDS.get(action, ())
            if not getattr(body, f)]


@router.post("/api/member/game/pets/{action}")
async def api_member_pet_action(
    action: str, body: PetActionBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    # Отключённые проверяем ДО «такого действия нет»: адрес существует, и
    # отвечать на него «не знаю такого» значило бы врать тому, кто помнит
    # это действие по чату.
    if action in _DISABLED:
        raise HTTPException(400, _DISABLED[action])
    if action not in _ACTIONS:
        raise HTTPException(400, "Такого действия нет")
    missing = _missing_fields(action, body)
    if missing:
        raise HTTPException(400, f"Не заполнено обязательное поле: {', '.join(missing)}.")
    if action == "care_all" and body.verb not in _CARE_VERBS:
        # Кулдаун у ласки один на все три слова (см. care_pet): молча
        # подставить «погладить» на непонятный verb значило бы дать «обнять»
        # исчезнуть в отказе без права тут же попробовать снова тем же
        # действием. Явный 400 честнее.
        raise HTTPException(
            400, f"Укажите verb — один из: {', '.join(_CARE_VERBS)}.")
    await require_member_in_chat(user, body.chat_id)
    # Сначала «а вы вообще в этом чате», потом «а хватает ли уровня»: иначе
    # постороннему сообщали бы, какого права ему не хватает в чужом чате.
    # Ключ берём прямым индексированием: действие без ключа команды — дыра, и
    # тест не даёт такому появиться (см. test_у_каждого_действия_есть_право).
    await permissions.ensure(user, _ACTION_COMMANDS[action])
    result = await _ACTIONS[action](body, body.chat_id, user.tg_user_id)
    # Защита на будущее: контракт «результат действия — всегда ActionResult»
    # сегодня выполняют все действия таблицы, но держится он в game_actions.py,
    # а не здесь — забытый там None молча уронил бы _announce на
    # result.announcements. Проверка ничего не стоит и не тестируется прямым
    # путём (нечем воспроизвести None сегодня), но остаётся на случай, если
    # однажды появится.
    if result is None:
        raise HTTPException(400, "Это действие с сайта пока недоступно")
    # Журнал ПЕРЕД объявлениями: действие уже случилось, и след о нём не
    # должен зависеть от того, дошло ли поздравление до чата. Сейчас неудачу
    # отправки ловит _announce, но порядок держит запись даже без ловушки.
    await db.add_log("member_game", chat_id=body.chat_id,
                     actor_id=user.tg_user_id, details=f"pets/{action}")
    await _announce(body.chat_id, result)
    return {"ok": result.ok, "text": result.text}
