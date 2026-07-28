"""Права панели — по уровню человека в БОТЕ, а не по панельной роли.

Дыра, которую это чинит. Роли панели (owner/admin/member) живут отдельно от
уровней бота. Панельный admin дёргал все админские эндпоинты независимо от
того, какой у него уровень в боте, — хоть нулевой. Человек-модератор с
панельным аккаунтом admin получал на сайте больше, чем в чате.

Уровни в боте ГЛОБАЛЬНЫЕ: в таблице admins нет chat_id, и «модератор в этом
чате» как понятие не существует. Здесь мы это не чиним, а честно повторяем —
две разные правды о правах были бы хуже одной неудобной.

Владелец (OWNER_IDS или панельная роль owner) проходит всегда: иначе владелец
может запереть себя снаружи и остаться без доступа к собственной панели.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException, status

import db

from . import roles

LEVEL_MEMBER = roles.LEVEL_MEMBER
LEVEL_MODERATOR = roles.LEVEL_MODERATOR
LEVEL_ADMIN = roles.LEVEL_ADMIN
LEVEL_SENIOR = roles.LEVEL_SENIOR
OWNER_LEVEL = roles.OWNER_LEVEL

# Реестр команд и оверрайды уровней меняются редко, а спрашиваются на каждое
# поле формы. Кэш на минуту: правка через «право» доедет почти сразу, а сотня
# полей не превратится в сотню запросов.
_CACHE_TTL_SECONDS = 60
_cache: Optional[tuple[float, dict[str, int]]] = None


def forget_cache() -> None:
    """Сбросить кэш — нужен тестам и после правки уровня из панели."""
    global _cache
    _cache = None


async def _levels() -> dict[str, int]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    registry = {r["command_key"]: int(r["default_level"])
                for r in await db.list_command_registry()}
    registry.update(await db.list_command_levels())
    _cache = (now, registry)
    return registry


async def bot_level(user) -> int:
    """Уровень этого человека в боте."""
    if getattr(user, "is_owner", False):
        return OWNER_LEVEL
    tg_id = getattr(user, "tg_user_id", None)
    if tg_id is None:
        # Аккаунт не привязан к Telegram — бот про такого человека не знает.
        return LEVEL_MEMBER
    if tg_id in roles.owner_ids():
        return OWNER_LEVEL
    return int(await db.get_admin_level(tg_id))


async def required_level(command_key: str) -> int:
    """Уровень, нужный для этой команды: оверрайд, иначе умолчание реестра.

    Неизвестный ключ требует максимума, а не минимума: опечатка не должна
    ОТКРЫВАТЬ доступ.
    """
    return (await _levels()).get(command_key, LEVEL_SENIOR)


async def level_name(level: int) -> str:
    """Название уровня — то же, что панель показывает везде остальное, и то
    же, что человек видит в чате.

    Раньше здесь брались названия по умолчанию, а эмодзи срезался хардкодом.
    В чате, где владелец переименовал «Администратор», текст ошибки называл
    уровень, которого человек у себя не найдёт, — доступ это не ломало, но
    объяснить, какого права не хватает, становилось нечем."""
    return (await roles.load()).name_of(level)


async def ensure(user, command_key: str) -> None:
    """403 с названием нужного уровня, если человек не дотягивает."""
    need = await required_level(command_key)
    have = await bot_level(user)
    if have >= need:
        return
    if getattr(user, "tg_user_id", None) is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Аккаунт не привязан к Telegram — бот не знает вашего уровня. "
            "Привязать можно в панели, раздел «Аккаунты».",
        )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Нужен уровень «{await level_name(need)}» и выше.",
    )
