"""Холды администраторов — общий код для бота и веб-панели.

Telegram не позволяет ограничивать (мутить/банить) действующего администратора
чата. Поэтому перед мутом/баном админа бот сначала снимает с него права,
сохраняет их снимок в таблице admin_action_holds (см. db.add_admin_hold), а
позже возвращает — автоматически по истечении срока мута либо вручную вместе
со снятием мута/бана.

Модуль вынесен из bot.py, потому что возвращать права должны ОБА процесса:
и сам бот (текстовые команды «размут»/«разбан»), и веб-панель (кнопки «Снять
мут»/«Разбан»). Пока логика жила только внутри bot.py, снятие мута через
панель оставляло администратора без прав: ограничение снималось, строка
холда — нет, и права не возвращались вообще (при муте «навсегда») либо
только когда истекал исходный срок мута.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import db

logger = logging.getLogger(__name__)

# Права администратора Telegram, которые снимаем и возвращаем. Порядок важен:
# в таком же виде список показывается человеку в меню прав.
TG_RIGHTS_FIELDS = [
    ("can_delete_messages",    "🗑 Удаление сообщений"),
    ("can_restrict_members",   "🔇 Мут / бан участников"),
    ("can_pin_messages",       "📌 Закреп сообщений"),
    ("can_invite_users",       "➕ Приглашение по ссылке"),
    ("can_manage_video_chats", "🎥 Видеочаты"),
    ("can_change_info",        "✏️ Изменение инфы чата"),
    ("can_manage_chat",        "🛠 Управление чатом"),
    ("can_promote_members",    "👑 Назначение других админов"),
    ("can_manage_tags",        "🏷 Изменение тегов участников"),
    ("is_anonymous",           "🕶 Анонимность"),
]
TG_RIGHTS_FIELD_SET = {field for field, _ in TG_RIGHTS_FIELDS}

# Набор «обычного администратора» — им бот назначает по команде «+тг админ», он
# же предлагается по умолчанию в панели. Права назначать других админов и менять
# инфу чата намеренно выключены: выданный так админ не должен расширять себе
# полномочия сам.
DEFAULT_ADMIN_RIGHTS = {
    "is_anonymous": False,
    "can_manage_chat": True,
    "can_delete_messages": True,
    "can_manage_video_chats": True,
    "can_restrict_members": True,
    "can_promote_members": False,
    "can_change_info": False,
    "can_invite_users": True,
    "can_pin_messages": True,
    "can_manage_tags": True,
}

# Максимальная длина должности (custom title) в Telegram.
CUSTOM_TITLE_MAX = 16


def snapshot_admin_rights(member) -> dict:
    """Текущий набор прав администратора (полей из TG_RIGHTS_FIELDS)."""
    return {field: bool(getattr(member, field, False)) for field, _ in TG_RIGHTS_FIELDS}


def normalize_rights(rights: dict) -> dict:
    """Приводит произвольный словарь к полному набору полей TG_RIGHTS_FIELDS.

    Полный набор обязателен: Telegram сбрасывает в False любое булево право,
    которое не передали в promoteChatMember. Отправить «только то, что
    поменялось» нельзя — снимет всё остальное."""
    return {field: bool(rights.get(field, False)) for field, _ in TG_RIGHTS_FIELDS}


async def promote_with_rights(bot: Bot, chat_id: int, user_id: int, rights: dict) -> None:
    """Выставляет администратору ровно этот набор прав.

    can_post_messages/can_edit_messages — права каналов, в группах смысла не
    имеют, но передать их надо: иначе Telegram посчитает их сброшенными и в
    ответе окажется не то, что ожидали.

    Исключения (TelegramForbiddenError / TelegramBadRequest) наружу не ловим —
    вызывающая сторона показывает их человеку по-своему."""
    await bot.promote_chat_member(
        chat_id=chat_id, user_id=user_id,
        can_post_messages=False, can_edit_messages=False,
        **normalize_rights(rights),
    )


async def demote_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Полностью снимает права администратора Telegram. True, если получилось
    (не получится, если этого администратора назначал не бот)."""
    try:
        await bot.promote_chat_member(
            chat_id=chat_id, user_id=user_id,
            is_anonymous=False, can_manage_chat=False, can_delete_messages=False,
            can_manage_video_chats=False, can_restrict_members=False, can_promote_members=False,
            can_change_info=False, can_invite_users=False, can_pin_messages=False,
            can_post_messages=False, can_edit_messages=False,
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        return False
    return True


async def restore_admin_rights(
    bot: Bot, chat_id: int, user_id: int, rights: dict, custom_title: Optional[str]
) -> tuple[bool, bool]:
    """Возвращает ранее снятые права администратора (+ должность, если была).

    Возвращает (promoted, title_restored):
      promoted       — удалось ли вернуть сам статус администратора;
      title_restored — удалось ли восстановить кастомную должность (True,
                        если её и не было).

    ВАЖНО: promoteChatMember со ВСЕМИ флагами False — это ровно тот же вызов,
    которым мы демоутим админа (см. demote_admin). Если у восстанавливаемого
    администратора не было ни одного отдельного права (например, админ «для
    вида» — только галочка/анонимность/должность, без прав), передача такого
    набора обратно в promoteChatMember ничего не восстановит: Telegram
    воспримет это как demote, и снаружи будет выглядеть так, будто права
    выдали и тут же снова забрали. Поэтому в этом случае принудительно
    выставляем одно безобидное право, чтобы Telegram реально сохранил статус
    администратора.
    """
    safe_rights = normalize_rights(rights)
    forced_min_right = False
    if not any(safe_rights.values()):
        safe_rights["can_invite_users"] = True
        forced_min_right = True

    try:
        await promote_with_rights(bot, chat_id, user_id, safe_rights)
    except (TelegramForbiddenError, TelegramBadRequest):
        return False, True

    if forced_min_right:
        logger.warning(
            "admin_hold: у пользователя %s в чате %s не было ни одного отдельного права администратора — "
            "принудительно выставлено минимальное право (can_invite_users), иначе Telegram не сохранил бы статус админа",
            user_id, chat_id,
        )

    title_restored = True
    if custom_title:
        try:
            await bot.set_chat_administrator_custom_title(
                chat_id=chat_id, user_id=user_id, custom_title=custom_title
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            title_restored = False

    return True, title_restored


async def _fallback_name(chat_id: int, user_id: int) -> str:
    """Имя для сообщения в чат, когда вызывающая сторона его не передала
    (панель не умеет строить имена так же, как бот)."""
    try:
        row = await db.get_known_user(chat_id, user_id)
    except Exception:
        row = None
    if row and row.get("full_name"):
        return str(row["full_name"])
    return f"ID {user_id}"


async def finish_admin_hold(
    bot: Bot, chat_id: int, user_id: int, hold: dict, manual: bool,
    name: Optional[str] = None,
) -> bool:
    """Возврат прав администратора по холду: и для авто-восстановления по
    истечении срока мута, и для ручного досрочного снятия мута/бана — из бота
    или из панели. Возвращает True, если статус админа удалось вернуть."""
    try:
        rights = json.loads(hold["rights_json"])
    except (TypeError, ValueError, KeyError):
        rights = {}
    custom_title = hold.get("custom_title")
    action_type = hold.get("action_type")

    if action_type == "ban":
        try:
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        except Exception:
            pass
        # Снятие мута/бана должно закрыть и саму запись действия, иначе
        # списки «муты»/«баны» продолжают показывать уже размученного/
        # разбаненного администратора (холд удаляется ниже, а mutes/bans — нет).
        try:
            await db.remove_ban(chat_id, user_id)
        except Exception:
            logger.exception("admin_hold: не удалось снять запись бана для %s в чате %s", user_id, chat_id)
    elif action_type == "mute":
        try:
            await db.remove_mute(chat_id, user_id)
        except Exception:
            logger.exception("admin_hold: не удалось снять запись мута для %s в чате %s", user_id, chat_id)

    promoted, title_restored = await restore_admin_rights(bot, chat_id, user_id, rights, custom_title)
    await db.delete_admin_hold(chat_id, user_id)

    if name is None:
        name = await _fallback_name(chat_id, user_id)

    if promoted:
        note = "вручную" if manual else "автоматически (истёк срок)"
        title_note = "" if title_restored else "\n⚠️ Не удалось восстановить должность (custom title) — задайте её вручную."
        try:
            await bot.send_message(chat_id, f"👑 {name} — права администратора возвращены ({note}).{title_note}")
        except Exception:
            pass
        try:
            await bot.send_message(user_id, "👑 В группе вам возвращены права администратора.")
        except Exception:
            pass
    else:
        try:
            await bot.send_message(
                chat_id, f"⚠️ Не удалось автоматически вернуть права администратора {name} — сделайте это вручную."
            )
        except Exception:
            pass
    await db.add_log("admin_rights_restored", chat_id=chat_id, target_id=user_id)
    return promoted


async def release_hold_for(
    bot: Bot, chat_id: int, user_id: int, action_type: str, name: Optional[str] = None
) -> bool:
    """«Сняли наказание — верни права, если снимали». Ищет холд нужного типа
    (mute/ban) и завершает его. True, если холд был и права вернулись.

    Именно этого вызова не хватало веб-панели: она снимала мут/бан, но холд
    оставался, и администратор так и сидел без прав."""
    hold = await db.get_admin_hold(chat_id, user_id)
    if not hold or hold.get("action_type") != action_type:
        return False
    return await finish_admin_hold(bot, chat_id, user_id, hold, manual=True, name=name)
