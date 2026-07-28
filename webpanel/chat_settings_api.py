"""Настройки чата в панели.

Отдельным файлом, а не дописыванием в app.py: тот уже 4377 строк, и класть
туда ещё один раздел значит закреплять привычку, из-за которой файл и вырос.

Требуемый уровень зависит от НАСТРОЙКИ, а не от маршрута, поэтому зависимостью
FastAPI это не проверить: она про ключ в теле запроса ничего не знает. Проверка
идёт внутри обработчика.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chat_settings
import db

from . import auth, permissions, roles
from .auth import PanelUser

router = APIRouter()


async def _known_chat(chat_id: int) -> bool:
    return any(row["chat_id"] == chat_id for row in await db.list_current_chats())


@router.get("/api/chat-settings")
async def api_chat_settings(chat_id: int, user: PanelUser = Depends(auth.require_user)):
    if not await _known_chat(chat_id):
        raise HTTPException(400, "Бот не знает такого чата")

    values = await db.get_chat_setting_values(chat_id, list(chat_settings.SETTINGS))
    have = await permissions.bot_level(user)
    # Карту ролей берём один раз на весь ответ, а не на каждое из 23 полей:
    # так все подписи заведомо из одного среза настроек, даже если кто-то
    # переименует уровень ровно между двумя полями.
    role_map = await roles.load()

    groups = []
    for group in chat_settings.GROUPS:
        fields = []
        for setting in chat_settings.SETTINGS:
            if setting.group != group:
                continue
            need = await permissions.required_level(setting.command_key)
            fields.append({
                "key": setting.key,
                "title": setting.title,
                "kind": setting.kind,
                "value": values.get(setting.key),
                "default": setting.default,
                "minimum": setting.minimum,
                "maximum": setting.maximum,
                "choices": [{"value": v, "label": l} for v, l in setting.choices],
                "hint": setting.hint,
                "required_level": need,
                "level_name": role_map.name_of(need),
                # Поле, до которого человек не дотягивает, ПОКАЗЫВАЕМ неактивным,
                # а не прячем: спрятанное читается как «такой настройки нет», и
                # человек идёт спрашивать, почему сайт беднее чата.
                "can_edit": have >= need,
                "global": setting.is_global,
            })
        if fields:
            groups.append({"group": group, "settings": fields})
    return {"groups": groups}


class ChatSettingBody(BaseModel):
    chat_id: int
    key: str
    value: Optional[str] = None


@router.post("/api/chat-settings")
async def api_set_chat_setting(
    body: ChatSettingBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    setting = chat_settings.BY_KEY.get(body.key)
    if setting is None:
        raise HTTPException(400, "Такой настройки нет")
    if not await _known_chat(body.chat_id):
        raise HTTPException(400, "Бот не знает такого чата")

    await permissions.ensure(user, setting.command_key)

    try:
        value = chat_settings.validate(setting, body.value)
    except ValueError as err:
        raise HTTPException(400, str(err)) from None

    await db.set_chat_setting_value(body.chat_id, setting, value)
    details = f"{setting.key}={value}"
    if user.tg_user_id is None:
        # Владелец (is_owner) проходит ensure() выше даже без привязки к
        # Telegram — так и задумано, иначе он может запереть себя снаружи.
        # Но actor_id тогда пуст, а именно у этого класса аккаунтов доступ
        # есть всегда — значит следу нужнее всего не потеряться. Раз в
        # actor_id (chat_id администратора бота) писать нечего, опознаём по
        # панельному аккаунту прямо в тексте записи.
        details = f"{details} (панель: {user.username or user.id})"
    await db.add_log(
        "chat_setting_set",
        chat_id=body.chat_id,
        actor_id=user.tg_user_id,
        details=details,
    )
    # Бот — другой процесс и держит настройки в памяти. Без этого флага сайт
    # писал бы в базу, отвечал «Сохранено», а чат жил бы по-старому до
    # перезапуска бота (или до случайной правки чего-то ещё через панель).
    await db.signal_panel_reload()
    return {"ok": True, "value": value}
