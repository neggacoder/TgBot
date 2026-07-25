"""Возврат прав администратора по холду (admin_holds.py).

Речь про механику из bot.py: Telegram не даёт мутить/банить администратора,
поэтому бот сначала снимает с него права, запоминает их снимок в
admin_action_holds и возвращает при снятии наказания. Ломается это тихо —
человек просто остаётся без прав и замечает не сразу, — поэтому проверяем
явно.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import admin_holds
import db


class FakeBot:
    """Запоминает вызовы Telegram API вместо того, чтобы их делать."""

    def __init__(self, *, promote_fails: bool = False):
        self.promote_calls = []
        self.title_calls = []
        self.unban_calls = []
        self.messages = []
        self._promote_fails = promote_fails

    async def promote_chat_member(self, **kwargs):
        self.promote_calls.append(kwargs)
        if self._promote_fails:
            raise admin_holds.TelegramBadRequest(method=None, message="not enough rights")

    async def set_chat_administrator_custom_title(self, **kwargs):
        self.title_calls.append(kwargs)

    async def unban_chat_member(self, **kwargs):
        self.unban_calls.append(kwargs)

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


def run(coro):
    """Тесты синхронные: pytest-asyncio в зависимостях проекта нет, а один
    asyncio.run на тест здесь ничем не хуже."""
    return asyncio.run(coro)


CHAT_ID = -1001234567890
USER_ID = 42


def make_hold(action_type="mute", rights=None, custom_title=None):
    if rights is None:
        rights = {"can_delete_messages": True, "can_restrict_members": True}
    return {
        "chat_id": CHAT_ID,
        "user_id": USER_ID,
        "action_type": action_type,
        "rights_json": json.dumps(rights),
        "custom_title": custom_title,
        "until": None,
    }


@pytest.fixture
def fake_db(monkeypatch):
    """Подменяет обращения к БД. state['hold'] — что лежит в admin_action_holds."""
    state = {"hold": None, "deleted": [], "logs": []}

    async def get_admin_hold(chat_id, user_id):
        return state["hold"]

    async def delete_admin_hold(chat_id, user_id):
        state["deleted"].append((chat_id, user_id))
        state["hold"] = None
        return True

    async def add_log(event_type, **kwargs):
        state["logs"].append(event_type)

    async def get_known_user(chat_id, user_id):
        return {"user_id": user_id, "full_name": "Пётр", "username": "petr"}

    monkeypatch.setattr(db, "get_admin_hold", get_admin_hold)
    monkeypatch.setattr(db, "delete_admin_hold", delete_admin_hold)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(db, "get_known_user", get_known_user)
    return state


# --- release_hold_for: то, ради чего модуль вынесли из bot.py ---------------

def test_release_hold_returns_saved_rights(fake_db):
    """Сняли мут — права из снимка вернулись, строка холда удалена."""
    fake_db["hold"] = make_hold(rights={"can_delete_messages": True, "can_pin_messages": True})
    bot = FakeBot()

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert restored is True
    assert len(bot.promote_calls) == 1
    call = bot.promote_calls[0]
    assert call["user_id"] == USER_ID
    assert call["can_delete_messages"] is True
    assert call["can_pin_messages"] is True
    assert call["can_restrict_members"] is False
    # холд закрыт — иначе повторное снятие мута попыталось бы вернуть права ещё раз
    assert fake_db["deleted"] == [(CHAT_ID, USER_ID)]


def test_release_hold_restores_custom_title(fake_db):
    fake_db["hold"] = make_hold(custom_title="Смотритель")
    bot = FakeBot()

    run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert bot.title_calls == [
        {"chat_id": CHAT_ID, "user_id": USER_ID, "custom_title": "Смотритель"}
    ]


def test_release_hold_without_hold_does_nothing(fake_db):
    """Мутили обычного участника — прав никто не снимал, возвращать нечего."""
    fake_db["hold"] = None
    bot = FakeBot()

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert restored is False
    assert bot.promote_calls == []
    assert fake_db["deleted"] == []


def test_release_hold_ignores_other_action_type(fake_db):
    """Снятие мута не должно закрывать холд от бана: человек всё ещё забанен,
    и права ему возвращать рано."""
    fake_db["hold"] = make_hold(action_type="ban")
    bot = FakeBot()

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert restored is False
    assert bot.promote_calls == []
    assert fake_db["hold"] is not None


def test_release_ban_hold_unbans_first(fake_db):
    fake_db["hold"] = make_hold(action_type="ban")
    bot = FakeBot()

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "ban"))

    assert restored is True
    assert bot.unban_calls and bot.unban_calls[0]["only_if_banned"] is True


def test_admin_without_any_right_still_gets_admin_status(fake_db):
    """Админ «для вида» (одна должность, ни одного права): promoteChatMember со
    всеми False — это demote, поэтому модуль обязан выставить хотя бы одно
    безобидное право, иначе статус админа не вернётся вообще."""
    fake_db["hold"] = make_hold(rights={field: False for field, _ in admin_holds.TG_RIGHTS_FIELDS})
    bot = FakeBot()

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert restored is True
    assert bot.promote_calls[0]["can_invite_users"] is True


def test_failed_promote_reports_and_clears_hold(fake_db):
    """Telegram отказал — сообщаем в чат и всё равно закрываем холд: иначе он
    висел бы вечно и блокировал следующий мут этого же человека."""
    fake_db["hold"] = make_hold()
    bot = FakeBot(promote_fails=True)

    restored = run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert restored is False
    assert fake_db["deleted"] == [(CHAT_ID, USER_ID)]
    assert any("вернуть права" in text for _, text in bot.messages)


def test_name_falls_back_to_known_users(fake_db):
    """Панель не умеет строить имена так, как бот, и имя не передаёт — модуль
    берёт его из known_users, чтобы в чат не ушло «👑 None»."""
    fake_db["hold"] = make_hold()
    bot = FakeBot()

    run(admin_holds.release_hold_for(bot, CHAT_ID, USER_ID, "mute"))

    assert any("Пётр" in text for _, text in bot.messages)
