"""Общий переключатель кабинета участника.

Настройка хранится на чат: один бот может обслуживать несколько сообществ, и
выключение сайта в одном из них не должно закрывать кабинет другого.
"""

from __future__ import annotations

import db

_DISABLED_PREFIX = "member_site_disabled:"


def key(chat_id: int) -> str:
    return f"{_DISABLED_PREFIX}{chat_id}"


async def is_enabled(chat_id: int) -> bool:
    row = await db.get_data(key(chat_id))
    return not row or row.get("data_value") != "1"


async def set_enabled(chat_id: int, enabled: bool, *, actor_id: int) -> None:
    if enabled:
        await db.delete_data(key(chat_id))
    else:
        await db.set_data(key(chat_id), "1", updated_by=actor_id)
