"""Выдача наград за коллекции из любого интерфейса.

Коллекция достраивается действием, а не открытием витрины: купить последнего
питомца можно и в чате, и в кабинете, а результат обязан быть одинаковым.
Этот модуль не зависит от Telegram, поэтому его безопасно вызывают оба пути.
"""

from __future__ import annotations

from datetime import datetime
import html

import collections_meta
import db
import gallery_actions
import game_actions
import pets as pets_catalog
import seasons


async def source_user_link(chat_id: int, user_id: int) -> str:
    """Кликабельное имя автора действия, предпочтительно в виде @username."""
    known = await db.get_known_user(chat_id, user_id) or {}
    username = known.get("username")
    nickname = await db.get_nickname(chat_id, user_id)
    label = f"@{username}" if username else (nickname or known.get("full_name") or str(user_id))
    href = f"https://telegram.me/{username}" if username else f"tg://user?id={user_id}"
    return f'<a href="{href}">{html.escape(str(label))}</a>'


async def site_announcement(chat_id: int, user_id: int,
                            collection: collections_meta.Collection) -> str:
    """Текст объявления: сайт обязан назвать того, чьё действие его вызвало."""
    return (
        f"{collection.emoji} От {await source_user_link(chat_id, user_id)}:\n"
        f"Собрана коллекция «{collection.name}»!\n"
        f"<i>{collection.description}</i>\nТитул: {collection.title_name}"
    )


async def _grant_collection_achievement(chat_id: int, user_id: int, code: str) -> None:
    """Записывает ачивку и её неотъемлемую награду без отправки сообщения.

У «Зоопарка» это единорог. Обычный ``db.grant_achievement`` хранит только
саму ачивку; выдача питомца в боте раньше жила рядом с его уведомлением.
Здесь она нужна и кабинету, иначе сайт выдавал бы неполную награду.
"""
    if not await db.grant_achievement(chat_id, user_id, code):
        return
    await db.add_log("achievement", chat_id=chat_id, actor_id=user_id, details=code)

    pet_spec = pets_catalog.PET_BY_ACHIEVEMENT.get(code)
    if pet_spec is None:
        return
    await db.ensure_pet_catalog(chat_id, pets_catalog.PETS)
    if await db.get_pet(chat_id, user_id, pet_spec.key):
        return
    if await db.add_pet(chat_id, user_id, pet_spec.key, datetime.utcnow()):
        await db.add_log("pet_achievement", chat_id=chat_id, actor_id=user_id,
                         details=f"{pet_spec.key}:{code}")


async def check_collections(chat_id: int, user_id: int, *, today) -> list[collections_meta.Collection]:
    """Выдаёт новые награды за завершённые коллекции и возвращает их список.

    ``today`` передаётся вызывающим: у панели это та же дата в часовом поясе
    чата, что и у бота. Так «Династия» не меняет условия на границе месяца.
    """
    progress = await gallery_actions.collection_progress(
        chat_id,
        user_id,
        pet_specs=await game_actions._pet_specs(chat_id),
        season_key=seasons.season_key(today),
    )
    awarded: list[collections_meta.Collection] = []
    for collection in collections_meta.COLLECTIONS:
        done, total = progress.get(collection.key, (0, 0))
        if not collections_meta.is_complete(done, total):
            continue
        await db.add_title_if_missing(collection.title_key, collection.title_name)
        if not await db.grant_title(chat_id, user_id, collection.title_key):
            continue
        await _grant_collection_achievement(chat_id, user_id, collection.achievement_code)
        await db.add_log("collection_done", chat_id=chat_id, actor_id=user_id,
                         details=collection.key)
        awarded.append(collection)
    return awarded
