"""Администраторы Telegram из панели: /api/tg_admins/*.

Здесь настоящий статус администратора чата, а не уровень бота. Цена ошибки
высокая в обе стороны: лишнее право — это чужие руки в чате, потерянное —
неработающая модерация. Поэтому проверяем и запреты тоже.
"""

from __future__ import annotations

import importlib
import types

import pytest
from fastapi.testclient import TestClient

import admin_holds
import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
ADMIN_ID = 42
CREATOR_ID = 1
BOT_ID = 777


def user(user_id, name="Пётр", username="petr", is_bot=False):
    return types.SimpleNamespace(
        id=user_id, full_name=name, username=username, is_bot=is_bot
    )


def member(user_id, status="administrator", rights=None, custom_title=None, **kw):
    fields = {f: False for f, _ in admin_holds.TG_RIGHTS_FIELDS}
    fields.update(rights or {})
    return types.SimpleNamespace(
        user=user(user_id, **kw), status=status, custom_title=custom_title, **fields
    )


class FakeBot:
    def __init__(self, members=None, admins=None, promote_error=None):
        self._members = members or {}
        self._admins = admins or []
        self._promote_error = promote_error
        self.promote_calls = []
        self.title_calls = []

    async def get_chat_administrators(self, chat_id):
        return self._admins

    async def get_chat_member(self, chat_id, user_id):
        if user_id not in self._members:
            raise RuntimeError("user not found")
        return self._members[user_id]

    async def promote_chat_member(self, **kwargs):
        self.promote_calls.append(kwargs)
        if self._promote_error:
            raise self._promote_error

    async def set_chat_administrator_custom_title(self, **kwargs):
        self.title_calls.append(kwargs)


@pytest.fixture
def make_client(monkeypatch):
    """Отдаёт фабрику: сначала настраиваем бота и холд, потом создаём клиент."""
    state = {"hold": None, "logs": []}

    async def get_admin_hold(chat_id, user_id):
        return state["hold"]

    async def add_log(event_type, **kwargs):
        state["logs"].append(event_type)

    monkeypatch.setattr(db, "get_admin_hold", get_admin_hold)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    panel.app.dependency_overrides[panel.auth.require_owner] = lambda: PanelUser(
        id=1, username="tester", role="owner"
    )

    def build(bot):
        monkeypatch.setattr(panel, "_bot", bot)
        return TestClient(panel.app)

    yield build, state
    panel.app.dependency_overrides.clear()


ALL_RIGHTS_OFF = {f: False for f, _ in admin_holds.TG_RIGHTS_FIELDS}
SOME_RIGHTS = dict(ALL_RIGHTS_OFF, can_delete_messages=True, can_restrict_members=True)


# --- список ------------------------------------------------------------------

def test_creator_is_listed_but_not_editable(make_client):
    """Создателя чата Telegram менять не даёт никому — кнопки прятать заранее."""
    build, _ = make_client
    client = build(FakeBot(admins=[
        member(CREATOR_ID, status="creator", name="Оля"),
        member(ADMIN_ID, rights=SOME_RIGHTS),
    ]))

    admins = client.get("/api/tg_admins", params={"chat_id": CHAT_ID}).json()["admins"]

    by_id = {a["user_id"]: a for a in admins}
    assert by_id[CREATOR_ID]["is_creator"] is True
    assert by_id[CREATOR_ID]["editable"] is False
    assert by_id[ADMIN_ID]["editable"] is True
    assert by_id[ADMIN_ID]["rights"]["can_delete_messages"] is True


# --- назначение --------------------------------------------------------------

def test_promote_sends_full_rights_set(make_client):
    """Telegram сбрасывает всё, что не передали, поэтому набор всегда полный."""
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")})
    client = build(bot)

    res = client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID,
        "rights": {"can_delete_messages": True},
    })

    assert res.status_code == 200
    call = bot.promote_calls[0]
    for field, _ in admin_holds.TG_RIGHTS_FIELDS:
        assert field in call, f"{field} не передано — Telegram сбросил бы его в False"
    assert call["can_delete_messages"] is True
    assert call["can_promote_members"] is False


def test_promote_with_custom_title(make_client):
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")})
    client = build(bot)

    client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID,
        "rights": SOME_RIGHTS, "custom_title": "Смотритель",
    })

    assert bot.title_calls[0]["custom_title"] == "Смотритель"


def test_promote_rejects_too_long_title(make_client):
    build, _ = make_client
    client = build(FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")}))

    res = client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID,
        "rights": SOME_RIGHTS, "custom_title": "А" * 17,
    })

    assert res.status_code == 400


def test_promote_rejects_bots(make_client):
    build, _ = make_client
    client = build(FakeBot(members={BOT_ID: member(BOT_ID, status="member", is_bot=True)}))

    res = client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": BOT_ID, "rights": SOME_RIGHTS,
    })

    assert res.status_code == 400


def test_empty_rights_set_is_refused(make_client):
    """promoteChatMember со всеми False — это снятие админа. Молча «назначить
    никем» нельзя: в панели успех, в чате ничего не изменилось."""
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")})
    client = build(bot)

    res = client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID, "rights": ALL_RIGHTS_OFF,
    })

    assert res.status_code == 400
    assert bot.promote_calls == []


def test_unknown_right_is_refused(make_client):
    """Опечатка в имени права не должна тихо превращаться в «выключено»."""
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")})
    client = build(bot)

    res = client.post("/api/tg_admins/promote", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID,
        "rights": {"can_delete_messages": True, "can_rule_the_world": True},
    })

    assert res.status_code == 400
    assert bot.promote_calls == []


# --- изменение прав ----------------------------------------------------------

def test_rights_change_requires_existing_admin(make_client):
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, status="member")})
    client = build(bot)

    res = client.post("/api/tg_admins/rights", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID, "rights": SOME_RIGHTS,
    })

    assert res.status_code == 400
    assert bot.promote_calls == []


def test_creator_rights_cannot_be_changed(make_client):
    build, _ = make_client
    bot = FakeBot(members={CREATOR_ID: member(CREATOR_ID, status="creator")})
    client = build(bot)

    res = client.post("/api/tg_admins/rights", json={
        "chat_id": CHAT_ID, "user_id": CREATOR_ID, "rights": SOME_RIGHTS,
    })

    assert res.status_code == 400
    assert bot.promote_calls == []


def test_clearing_title_sends_empty_string(make_client):
    """Должность сбрасывается вместе с правами, поэтому её выставляют заново
    каждый раз — в том числе пустую, если её убрали."""
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, custom_title="Старая")})
    client = build(bot)

    client.post("/api/tg_admins/rights", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID, "rights": SOME_RIGHTS, "custom_title": "",
    })

    assert bot.title_calls[0]["custom_title"] == ""


# --- холды -------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", ["promote", "rights", "demote"])
def test_active_hold_blocks_changes(make_client, endpoint):
    """На человеке висит холд (замучен, права сняты и запомнены). Любая правка
    сейчас пропала бы: снятие мута вернуло бы старый снимок поверх неё."""
    build, state = make_client
    state["hold"] = {"action_type": "mute", "rights_json": "{}"}
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID)})
    client = build(bot)

    res = client.post(f"/api/tg_admins/{endpoint}", json={
        "chat_id": CHAT_ID, "user_id": ADMIN_ID, "rights": SOME_RIGHTS,
    })

    assert res.status_code == 409
    assert "мут" in res.json()["detail"].casefold()
    assert bot.promote_calls == []


# --- снятие ------------------------------------------------------------------

def test_demote_clears_every_right(make_client):
    build, _ = make_client
    bot = FakeBot(members={ADMIN_ID: member(ADMIN_ID, rights=SOME_RIGHTS)})
    client = build(bot)

    res = client.post("/api/tg_admins/demote", json={"chat_id": CHAT_ID, "user_id": ADMIN_ID})

    assert res.status_code == 200
    call = bot.promote_calls[0]
    assert not any(v for k, v in call.items() if k.startswith("can_") or k == "is_anonymous")


def test_demote_explains_foreign_admin(make_client):
    """Бот не может снять того, кого назначал не он. Голое «Telegram отказал»
    здесь бесполезно — человек должен понять, почему и что делать."""
    build, _ = make_client
    bot = FakeBot(
        members={ADMIN_ID: member(ADMIN_ID)},
        promote_error=admin_holds.TelegramBadRequest(method=None, message="not enough rights"),
    )
    client = build(bot)

    res = client.post("/api/tg_admins/demote", json={"chat_id": CHAT_ID, "user_id": ADMIN_ID})

    assert res.status_code == 400
    assert "назначал не бот" in res.json()["detail"]
