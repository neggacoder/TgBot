"""Права панели берутся из уровня человека в БОТЕ, а не из панельной роли.

Дыра, которую это чинит: панельная роль admin давала все админские
эндпоинты независимо от уровня в боте — хоть нулевого. Человек-модератор с
панельным аккаунтом admin получал на сайте больше, чем в чате.
"""

from __future__ import annotations

import asyncio
import functools
import importlib

import pytest
from fastapi import HTTPException

import db
from webpanel.auth import PanelUser

permissions = importlib.import_module("webpanel.permissions")


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@pytest.fixture
def мир(monkeypatch):
    уровни = {555: 1, 777: 2}

    async def get_admin_level(user_id):
        return уровни.get(user_id, 0)

    async def list_command_levels():
        return {"bank_manage": 3}

    async def list_command_registry():
        return [
            {"command_key": "bank_manage", "default_level": 2},
            {"command_key": "farm_yield_set", "default_level": 2},
        ]

    # Название уровня в тексте отказа берётся из карты ролей — той же, что
    # показывает панель везде остальное, — а она ходит в БД за админами и за
    # переименованиями уровней.
    async def list_admins():
        return [{"user_id": uid, "level": lvl} for uid, lvl in уровни.items()]

    async def fetch_settings():
        return {}

    monkeypatch.setattr(db, "get_admin_level", get_admin_level, raising=False)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels, raising=False)
    monkeypatch.setattr(db, "list_command_registry", list_command_registry, raising=False)
    monkeypatch.setattr(db, "list_admins", list_admins, raising=False)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings, raising=False)
    monkeypatch.setattr(permissions.roles, "owner_ids", lambda: {1})
    permissions.forget_cache()
    permissions.roles.invalidate()  # кэш карты ролей живёт 30 с и течёт между тестами
    return уровни


@_sync
async def test_аккаунт_без_привязки_имеет_нулевой_уровень(мир):
    """Панельный admin, не привязавший Telegram, — никто с точки зрения бота."""
    user = PanelUser(id=9, username="admin", role="admin", tg_user_id=None)
    assert await permissions.bot_level(user) == 0


@_sync
async def test_уровень_берётся_из_бота(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    assert await permissions.bot_level(user) == 1


@_sync
async def test_владелец_из_env_проходит_всегда(мир):
    """Иначе владелец может запереть себя снаружи."""
    user = PanelUser(id=9, username="own", role="member", tg_user_id=1)
    assert await permissions.bot_level(user) == permissions.OWNER_LEVEL


@_sync
async def test_панельный_владелец_тоже_проходит(мир):
    user = PanelUser(id=1, username="own", role="owner", tg_user_id=None)
    assert await permissions.bot_level(user) == permissions.OWNER_LEVEL


@_sync
async def test_требуемый_уровень_берёт_оверрайд(мир):
    """«право bank_manage 3» должно действовать и на сайте."""
    assert await permissions.required_level("bank_manage") == 3
    assert await permissions.required_level("farm_yield_set") == 2


@_sync
async def test_неизвестная_команда_требует_максимума(мир):
    """Опечатка в ключе не должна ОТКРЫВАТЬ доступ."""
    assert await permissions.required_level("такой нет") == permissions.LEVEL_SENIOR


@_sync
async def test_модератор_не_проходит_туда_где_нужен_админ(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    with pytest.raises(HTTPException) as err:
        await permissions.ensure(user, "farm_yield_set")
    assert err.value.status_code == 403


@_sync
async def test_админ_проходит(мир):
    user = PanelUser(id=9, username="adm", role="admin", tg_user_id=777)
    await permissions.ensure(user, "farm_yield_set")     # не бросает


@_sync
async def test_в_ошибке_названо_нужное_право(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    with pytest.raises(HTTPException) as err:
        await permissions.ensure(user, "farm_yield_set")
    assert "Администратор" in err.value.detail
