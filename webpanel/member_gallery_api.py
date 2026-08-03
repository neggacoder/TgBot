"""Кабинет участника: достижения и коллекции. Только просмотр.

Правила — в gallery_actions, общем с ботом. Здесь только доступ.

Экран ничего не меняет, и это не совпадение: закрепление достижения, выдача
титула за собранную коллекцию и проверка «а не собралась ли она» живут там,
где происходят сами события. Позови их отсюда — и открытие экрана начало бы
что-то выдавать.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

import casino_actions
import chats
import game_actions
import gallery_actions
import seasons

from . import auth, permissions
from .auth import PanelUser

logger = logging.getLogger(__name__)

router = APIRouter()

require_member_in_chat = None


async def _чат() -> int:
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    return chat_id


@router.get("/api/member/game/gallery")
async def api_member_gallery(user: PanelUser = Depends(auth.require_member)):
    chat_id = await _чат()
    await require_member_in_chat(user, chat_id)
    # Достижения и коллекции показываются вместе, но гейтятся своими ключами:
    # запрет в чате и запрет на сайте не могут быть разными запретами.
    await permissions.ensure(user, "achievements")
    user_id = user.tg_user_id

    # Каталог питомцев и сезон зависят от чата: первый чат может расширить
    # своими питомцами, второй считается по местному времени.
    коллекции = await gallery_actions.collections(
        chat_id, user_id,
        pet_specs=await game_actions._pet_specs(chat_id),
        # Сезон — по местному времени чата, как и в боте: посчитанный по
        # серверному, он в последние часы месяца назывался бы другим.
        season_key=seasons.season_key(await casino_actions.local_today()),
    )
    return {
        "achievements": await gallery_actions.achievements(chat_id, user_id),
        "collections": коллекции,
    }
