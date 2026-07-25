"""Модерация из веб-панели: /api/moderation/*.

Регрессия, ради которой тест и написан: панель снимала мут, но не закрывала
холд администратора, и права админу не возвращались — при муте «навсегда»
не возвращались вообще. Бот при этом всё делал правильно, поэтому баг был
виден только тем, кто снимает мут через сайт.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

# Именно import_module, а не `from webpanel import app`: пакет реэкспортирует
# сам объект FastAPI под именем app, и обычный импорт дал бы приложение вместо
# модуля — а нам нужен модуль, чтобы подменить в нём _bot.
panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
USER_ID = 42


class FakeBot:
    def __init__(self):
        self.restrict_calls = []
        self.promote_calls = []
        self.unban_calls = []
        self.messages = []

    async def restrict_chat_member(self, chat_id, user_id, **kwargs):
        self.restrict_calls.append((chat_id, user_id, kwargs))

    async def promote_chat_member(self, **kwargs):
        self.promote_calls.append(kwargs)

    async def unban_chat_member(self, *args, **kwargs):
        self.unban_calls.append((args, kwargs))

    async def ban_chat_member(self, *args, **kwargs):
        pass

    async def set_chat_administrator_custom_title(self, **kwargs):
        pass

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


@pytest.fixture
def panel_client(monkeypatch):
    """Панель с подменёнными БД, входом и Telegram-клиентом.

    state['hold'] — строка admin_action_holds; выставляем её в тесте, чтобы
    изобразить «этого админа мутили, права сняты и запомнены».
    """
    state = {"hold": None, "deleted": [], "logs": [], "mutes_removed": [], "bans_removed": []}

    async def get_admin_hold(chat_id, user_id):
        return state["hold"]

    async def delete_admin_hold(chat_id, user_id):
        state["deleted"].append((chat_id, user_id))
        state["hold"] = None
        return True

    async def remove_mute(chat_id, user_id):
        state["mutes_removed"].append((chat_id, user_id))

    async def remove_ban(chat_id, user_id):
        state["bans_removed"].append((chat_id, user_id))

    async def add_log(event_type, **kwargs):
        state["logs"].append(event_type)

    async def get_known_user(chat_id, user_id):
        return {"user_id": user_id, "full_name": "Пётр", "username": "petr"}

    monkeypatch.setattr(db, "get_admin_hold", get_admin_hold)
    monkeypatch.setattr(db, "delete_admin_hold", delete_admin_hold)
    monkeypatch.setattr(db, "remove_mute", remove_mute)
    monkeypatch.setattr(db, "remove_ban", remove_ban)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(db, "get_known_user", get_known_user)

    bot = FakeBot()
    monkeypatch.setattr(panel, "_bot", bot)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: PanelUser(
        id=1, username="tester", role="owner"
    )

    yield TestClient(panel.app), bot, state

    panel.app.dependency_overrides.clear()


def make_hold(action_type="mute"):
    return {
        "chat_id": CHAT_ID,
        "user_id": USER_ID,
        "action_type": action_type,
        "rights_json": '{"can_delete_messages": true, "can_restrict_members": true}',
        "custom_title": None,
        "until": None,
    }


def post(client, action, **body):
    return client.post(
        f"/api/moderation/{action}",
        json={"chat_id": CHAT_ID, "user_id": USER_ID, **body},
    )


def test_unmute_returns_admin_rights(panel_client):
    """Ядро регрессии: сняли мут через панель — права вернулись."""
    client, bot, state = panel_client
    state["hold"] = make_hold("mute")

    res = post(client, "unmute")

    assert res.status_code == 200
    assert res.json()["admin_rights_restored"] is True
    assert len(bot.promote_calls) == 1
    assert bot.promote_calls[0]["can_delete_messages"] is True
    assert bot.promote_calls[0]["can_restrict_members"] is True
    assert state["deleted"] == [(CHAT_ID, USER_ID)]
    # ограничение при этом всё равно снято
    assert bot.restrict_calls


def test_unban_returns_admin_rights(panel_client):
    client, bot, state = panel_client
    state["hold"] = make_hold("ban")

    res = post(client, "unban")

    assert res.status_code == 200
    assert res.json()["admin_rights_restored"] is True
    assert len(bot.promote_calls) == 1


def test_unmute_of_ordinary_member_touches_no_rights(panel_client):
    """Обычного участника мутили без снятия прав — panel не должна ничего
    промоутить, иначе снятие мута выдавало бы людям админку."""
    client, bot, state = panel_client
    state["hold"] = None

    res = post(client, "unmute")

    assert res.status_code == 200
    assert res.json()["admin_rights_restored"] is False
    assert bot.promote_calls == []


def test_mute_does_not_release_hold(panel_client):
    """Мут — не повод возвращать права."""
    client, bot, state = panel_client
    state["hold"] = make_hold("mute")

    res = post(client, "mute", minutes=60)

    assert res.status_code == 200
    assert bot.promote_calls == []
    assert state["hold"] is not None
