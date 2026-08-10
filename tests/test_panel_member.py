"""Постоянный аккаунт участника: общий вход по логину/паролю, отдельный
интерфейс и — самое важное — запрет административных эндпоинтов.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import db
from webpanel import auth
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

# Чат, который тесты панели используют как рабочий. Раньше он был просто
# числом в каждом запросе; теперь кабинет сверяет его с настройками, и число
# должно быть одно на весь файл.
ЧАТ = -100


@pytest.fixture
def client(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    async def _zero(*args, **kwargs):
        return 0

    monkeypatch.setattr(db, "add_log", _noop, raising=False)
    monkeypatch.setattr(db, "touch_panel_login", _noop, raising=False)
    monkeypatch.setattr(db, "add_panel_login_attempt", _noop, raising=False)
    monkeypatch.setattr(db, "count_failed_logins", _zero, raising=False)

    # Кабинет теперь работает только в РАБОЧЕМ чате, а какой он — читается из
    # настроек (см. chats.py). Заглушка обязана их отдать: иначе каждый тест
    # получает «рабочий чат ещё не привязан» вместо проверяемого поведения.
    async def _настройки():
        return {"complaint_chat_id": ЧАТ, "notify_chat_id": -100222}

    monkeypatch.setattr(db, "fetch_settings", _настройки, raising=False)
    c = TestClient(panel.app)
    yield c
    panel.app.dependency_overrides.clear()


# --- общий вход по логину и паролю ----------------------------------------

def test_участник_входит_через_обычную_форму(client, monkeypatch):
    password_hash = auth.hash_password("надёжный-пароль-участника")

    async def get_user(username):
        assert username == "tester"
        return {"id": 42, "username": username, "password_hash": password_hash,
                "role": "member", "tg_user_id": 555, "tg_full_name": "Тестер",
                "disabled": False}

    monkeypatch.setattr(db, "get_panel_user", get_user)
    request = Request({"type": "http", "method": "POST", "path": "/api/login",
                       "headers": [], "client": ("127.0.0.1", 12345)})
    res = asyncio.run(panel.api_login(panel.LoginBody(
        username="tester", password="надёжный-пароль-участника"), request))

    assert res.status_code == 200
    assert json.loads(res.body)["role"] == "member"
    assert auth.SESSION_COOKIE in res.headers.get("set-cookie", "")


def test_неверный_пароль_участника_отклонён(client, monkeypatch):
    password_hash = auth.hash_password("правильный-пароль-участника")
    async def get_user(_username):
        return {"id": 42, "username": "tester", "password_hash": password_hash,
                "role": "member", "disabled": False}

    monkeypatch.setattr(db, "get_panel_user", get_user)
    request = Request({"type": "http", "method": "POST", "path": "/api/login",
                       "headers": [], "client": ("127.0.0.1", 12345)})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(panel.api_login(
            panel.LoginBody(username="tester", password="неверный"), request))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Неверный логин или пароль"


def test_старого_входа_участника_по_коду_больше_нет():
    assert "/api/member/login" not in {
        route.path for route in panel.app.routes if hasattr(route, "path")
    }


def test_на_странице_одна_форма_логина_для_всех():
    static = Path(panel.STATIC_DIR)
    html = (static / "index.html").read_text(encoding="utf-8")
    js = (static / "app.js").read_text(encoding="utf-8")

    assert 'id="auth-form"' in html
    assert 'id="member-form"' not in html
    assert "/api/member/login" not in js
    assert "командой <code>аккаунт</code>" in html


# --- безопасность: участник не персонал -----------------------------------

def test_участник_не_может_в_админ_эндпоинт(monkeypatch):
    """С member-сессией require_user обязан давать 403 — иначе участник получил
    бы доступ ко всем админ-эндпоинтам, висящим на require_user."""
    password_hash = auth.hash_password("пароль-участника-123")

    async def get_user_by_id(uid):
        return {
            "id": uid, "username": "tg555", "role": "member",
            "tg_user_id": 555, "tg_full_name": "Тестер", "disabled": False,
            "password_hash": password_hash,
        }

    monkeypatch.setattr(db, "get_panel_user_by_id", get_user_by_id)
    token = auth.issue_session(7, password_hash)
    request = Request({
        "type": "http", "method": "GET", "path": "/api/settings",
        "headers": [(b"cookie", f"{auth.SESSION_COOKIE}={token}".encode())],
        "client": ("127.0.0.1", 12345),
    })
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.require_user(request))
    assert exc.value.status_code == 403


# --- read-only обзор возможностей ------------------------------------------

def test_capabilities_только_активные_и_без_id(client, monkeypatch):
    member = PanelUser(id=7, username="tg555", role="member", tg_user_id=555, tg_full_name="Тестер")
    panel.app.dependency_overrides[panel.auth.require_member] = lambda: member

    async def list_rp_rows():
        return [
            {"id": 1, "action_key": "обнять", "phrase": "{actor} обнимает {target}", "is_active": 1},
            {"id": 2, "action_key": "ударить", "phrase": "бьёт", "is_active": 0},
        ]

    async def list_rp_syn():
        return {"обнимашки": "обнять"}

    async def list_self_rows():
        return [{"id": 5, "action_key": "спит", "phrase": "{actor} спит", "is_active": 1}]

    monkeypatch.setattr(db, "list_rp_actions_rows", list_rp_rows)
    monkeypatch.setattr(db, "list_rp_action_synonyms", list_rp_syn)
    monkeypatch.setattr(db, "list_self_actions_rows", list_self_rows)

    res = client.get("/api/member/capabilities")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "Тестер"
    rp_keys = [a["key"] for a in data["rp"]["actions"]]
    assert "обнять" in rp_keys and "ударить" not in rp_keys  # неактивное скрыто
    assert data["rp"]["synonyms"] == {"обнимашки": "обнять"}
    # фразы — только текст, без id (read-only)
    assert data["rp"]["actions"][0]["phrases"] == ["{actor} обнимает {target}"]
    assert data["self"]["actions"][0]["key"] == "спит"


def test_capabilities_без_сессии_401(client):
    assert client.get("/api/member/capabilities").status_code == 401


# --- брак/отношения участника ----------------------------------------------

def _as_member(monkeypatch):
    member = PanelUser(id=7, username="tg555", role="member", tg_user_id=555, tg_full_name="Аня")
    panel.app.dependency_overrides[panel.auth.require_member] = lambda: member
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    async def known(chat_id, uid):
        return {"user_id": uid, "full_name": f"U{uid}", "username": None}

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(db, "get_known_user", known)
    # Снимок/отмена по умолчанию — «ничего нет»; конкретные тесты переопределяют.
    monkeypatch.setattr(db, "snapshot_dissolution", _none)
    monkeypatch.setattr(db, "get_rel2_pair_row", _none)
    monkeypatch.setattr(db, "get_recent_dissolution", _none)
    return member


def test_просмотр_брака_и_отношений(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_marriage(chat_id, uid):
        return {"partner_id": 999, "married_at": None} if uid == 555 else None

    async def get_pair(chat_id, uid):
        return {"partner_id": 888, "sparks": 1200, "level_index": 3, "contraception": True} if uid == 555 else None

    async def level_name(idx):
        return "Близкие"

    async def get_card(chat_id, uid):
        return {"gender": "ж"}

    monkeypatch.setattr(db, "get_marriage", get_marriage)
    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "get_rel2_level_name", level_name)
    monkeypatch.setattr(db, "get_profile_card", get_card)

    res = client.get("/api/member/relationship?chat_id=-100")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["marriage"]["partner_id"] == 999
    assert data["relationship"]["partner_name"] == "U888"
    assert data["relationship"]["level_name"] == "Близкие"
    assert data["relationship"]["contraception"] is True
    assert data["gender"] == "ж"


def test_презик_переключается(client, monkeypatch):
    _as_member(monkeypatch)
    state = {}

    async def get_pair(chat_id, uid):
        return {"id": 3, "partner_id": 999, "contraception": True}

    async def set_contra(pair_id, enabled):
        state["pair"] = pair_id
        state["on"] = enabled

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "set_rel2_contraception", set_contra)
    res = client.post("/api/member/rel-contraception", json={"chat_id": -100, "on": False})
    assert res.status_code == 200, res.text
    assert state == {"pair": 3, "on": False}


def test_презик_без_отношений_404(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_pair(chat_id, uid):
        return None

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    assert client.post("/api/member/rel-contraception", json={"chat_id": -100, "on": True}).status_code == 404


def test_пол_ставится_за_себя(client, monkeypatch):
    _as_member(monkeypatch)
    saved = {}

    async def set_gender(chat_id, uid, g):
        saved["uid"] = uid
        saved["g"] = g

    monkeypatch.setattr(db, "set_gender", set_gender)
    res = client.post("/api/member/gender", json={"chat_id": -100, "gender": "Ж"})
    assert res.status_code == 200, res.text
    assert saved == {"uid": 555, "g": "ж"}  # casefold, за сессионного пользователя


def test_пол_невалидный_400(client, monkeypatch):
    _as_member(monkeypatch)
    assert client.post("/api/member/gender", json={"chat_id": -100, "gender": "xyz"}).status_code == 400


def test_своя_инфа_участника(client, monkeypatch):
    _as_member(monkeypatch)  # мокает get_known_user

    async def stats(chat_id, uid):
        return {"message_count": 42, "first_seen_at": "2026-01-01T00:00:00", "last_message_at": "2026-07-01T12:00:00"}

    async def breakdown(chat_id, uid):
        return {"today_count": 1, "week_count": 5, "month_count": 20}

    async def rank(chat_id, uid):
        return 3

    async def role(chat_id, uid):
        return None

    async def _num(chat_id, uid):
        return 2

    async def rep(chat_id, uid):
        return 7

    monkeypatch.setattr(db, "get_message_stats", stats)
    monkeypatch.setattr(db, "get_activity_breakdown", breakdown)
    monkeypatch.setattr(db, "get_message_rank", rank)
    monkeypatch.setattr(db, "get_user_role", role)
    async def nick(chat_id, uid):
        return "Котик"

    monkeypatch.setattr(db, "count_rewards", _num)
    monkeypatch.setattr(db, "count_warns", _num)
    monkeypatch.setattr(db, "get_reputation", rep)
    monkeypatch.setattr(db, "get_nickname", nick)

    res = client.get("/api/member/info?chat_id=-100")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["messages"] == 42 and d["rank"] == 3 and d["week"] == 5
    assert d["rewards"] == 2 and d["reputation"] == 7 and d["nickname"] == "Котик"


def test_ник_ставится_и_снимается(client, monkeypatch):
    _as_member(monkeypatch)
    state = {}

    async def set_nick(chat_id, uid, nick):
        state["set"] = (uid, nick)

    async def del_nick(chat_id, uid):
        state["del"] = uid

    monkeypatch.setattr(db, "set_nickname", set_nick)
    monkeypatch.setattr(db, "delete_nickname", del_nick)
    assert client.post("/api/member/nickname", json={"chat_id": -100, "nickname": "Котик"}).status_code == 200
    assert state["set"] == (555, "Котик")
    assert client.post("/api/member/nickname", json={"chat_id": -100, "nickname": "  "}).status_code == 200
    assert state["del"] == 555  # пусто → снять ник


def test_ник_слишком_длинный_400(client, monkeypatch):
    _as_member(monkeypatch)
    assert client.post("/api/member/nickname", json={"chat_id": -100, "nickname": "я" * 40}).status_code == 400


def test_топ_с_моим_местом(client, monkeypatch):
    _as_member(monkeypatch)

    async def top(chat_id, limit=20):
        return ([{"user_id": 555, "message_count": 100}, {"user_id": 999, "message_count": 50}], 2)

    async def rank(chat_id, uid):
        return 1

    monkeypatch.setattr(db, "list_top_messages", top)
    monkeypatch.setattr(db, "get_message_rank", rank)
    res = client.get("/api/member/top?chat_id=-100")
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["top"][0]["me"] is True and d["top"][0]["rank"] == 1 and d["my_rank"] == 1


def test_свои_варны(client, monkeypatch):
    _as_member(monkeypatch)

    async def warns(chat_id, uid):
        return [{"reason": "спам", "created_at": "2026-01-01", "expires_at": None}]

    monkeypatch.setattr(db, "list_warns", warns)
    res = client.get("/api/member/warns?chat_id=-100")
    assert res.status_code == 200 and res.json()["warns"][0]["reason"] == "спам"


def test_свои_награды(client, monkeypatch):
    _as_member(monkeypatch)

    async def rewards(chat_id, uid):
        return [{"degree": 5, "reason": "помощь", "created_at": "2026-02-02"}]

    monkeypatch.setattr(db, "list_rewards", rewards)
    res = client.get("/api/member/rewards?chat_id=-100")
    assert res.status_code == 200 and res.json()["rewards"][0]["degree"] == 5


def test_жест_отправляется_в_чат(client, monkeypatch):
    _as_member(monkeypatch)
    sent = {}

    async def get_pair(chat_id, uid):
        return {"id": 3, "partner_id": 999}

    async def gestures(active_only=False):
        return [{
            "gesture_key": "hug", "name": "Обнять", "reply_template": None,
            "media_folder": "hugs", "phrases": [{"id": 1, "phrase": "{actor} обнимает {target}"}], "aliases": [],
        }]

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "list_rel2_gestures", gestures)
    monkeypatch.setattr(db, "get_rel2_cooldown", _none)
    monkeypatch.setattr(db, "set_rel2_cooldown", _none)
    monkeypatch.setattr(db, "increment_rel2_action_count", _none)
    monkeypatch.setattr(db, "get_profile_card", _none)
    monkeypatch.setattr(db, "get_nickname", _none)
    monkeypatch.setattr(panel, "RP_MEDIA_ROOT", "/no_such_dir_xyz")  # фото нет → текстовый путь

    class FakeBot:
        async def send_message(self, chat_id, text, **k):
            sent["chat"] = chat_id
            sent["text"] = text

        async def send_photo(self, chat_id, photo, caption=None):
            sent["photo"] = chat_id

    monkeypatch.setattr(panel, "get_bot", lambda: FakeBot())
    res = client.post("/api/member/gesture", json={"chat_id": -100, "key": "hug"})
    assert res.status_code == 200, res.text
    assert sent["chat"] == -100 and "обнимает" in sent["text"]


def test_восстановление_брака_в_72ч(client, monkeypatch):
    _as_member(monkeypatch)
    created = {}

    async def undo(kind, chat_id, uid, within_hours=72):
        return {"id": 9, "user_a": 555, "user_b": 999, "payload": "{}"} if kind == "marriage" else None

    async def get_marriage(chat_id, uid):
        return None  # оба свободны

    async def create_marriage(chat_id, a, b):
        created["pair"] = (a, b)
        return True

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(db, "get_recent_dissolution", undo)
    monkeypatch.setattr(db, "get_marriage", get_marriage)
    monkeypatch.setattr(db, "create_marriage", create_marriage)
    monkeypatch.setattr(db, "consume_dissolution", _none)

    res = client.post("/api/member/restore", json={"chat_id": -100, "kind": "marriage"})
    assert res.status_code == 200, res.text
    assert created["pair"] == (555, 999)


def test_восстановление_нечего_404(client, monkeypatch):
    _as_member(monkeypatch)  # get_recent_dissolution → None по умолчанию
    assert client.post("/api/member/restore", json={"chat_id": -100, "kind": "marriage"}).status_code == 404


def test_фарм_бонус_искр(client, monkeypatch):
    _as_member(monkeypatch)
    adj = {}

    async def get_pair(chat_id, uid):
        return {"id": 3, "partner_id": 999, "level_index": 2, "premium": True, "last_bonus_at": None}

    async def adjust(pair_id, delta, reason, floor_at_zero=True):
        adj["delta"] = delta
        return 1000

    async def levels():
        return [(1, "A", 0), (2, "B", 500), (3, "C", 2000)]

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "adjust_rel2_sparks", adjust)
    monkeypatch.setattr(db, "set_rel2_last_bonus_at", _none)
    monkeypatch.setattr(db, "set_rel2_level", _none)
    monkeypatch.setattr(db, "list_rel2_levels", levels)

    res = client.post("/api/member/farm-bonus", json={"chat_id": -100})
    assert res.status_code == 200, res.text
    # уровень 2, премиум: (100 + 2*20) * 1.2 = 168
    assert res.json()["amount"] == 168 and adj["delta"] == 168


# --- фарм-действия отношений (отн сделать <…> на сайте) ---------------------

def test_каталог_фарм_действий_уровень_и_блокировка(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_pair(chat_id, uid):
        return {"id": 5, "partner_id": 999, "level_index": 3, "premium": False}

    async def _no_cd(scope, ref_id, key):
        return None

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "get_rel2_cooldown", _no_cd)

    d = client.get("/api/member/rp-actions?chat_id=-100").json()
    by_key = {a["key"]: a for a in d["actions"]}
    assert len(d["actions"]) == 30
    assert by_key["compliment"]["available"] and by_key["compliment"]["reward"] == 15
    assert by_key["eternal_love"]["locked"] and not by_key["eternal_love"]["available"]


def test_фарм_действие_начисляет_искры(client, monkeypatch):
    _as_member(monkeypatch)
    calls = {}

    async def get_pair(chat_id, uid):
        return {"id": 5, "partner_id": 999, "level_index": 3, "premium": False}

    async def _no_cd(scope, ref_id, key):
        return None

    async def adjust(pair_id, delta, reason, floor_at_zero=True):
        calls["delta"] = delta
        return 2500

    async def set_cd(scope, ref_id, key):
        calls["cd_key"] = key

    async def levels():
        return [(1, "A", 0), (2, "B", 500), (3, "C", 2000)]

    async def level_name(idx):
        return "C"

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "get_rel2_cooldown", _no_cd)
    monkeypatch.setattr(db, "adjust_rel2_sparks", adjust)
    monkeypatch.setattr(db, "set_rel2_cooldown", set_cd)
    monkeypatch.setattr(db, "list_rel2_levels", levels)
    monkeypatch.setattr(db, "set_rel2_level", _none)
    monkeypatch.setattr(db, "get_rel2_level_name", level_name)

    res = client.post("/api/member/rp-action", json={"chat_id": -100, "key": "compliment"})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["amount"] == 15 and calls["delta"] == 15 and calls["cd_key"] == "compliment"


def test_фарм_действие_заблокировано_по_уровню(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_pair(chat_id, uid):
        return {"id": 5, "partner_id": 999, "level_index": 3, "premium": False}

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    res = client.post("/api/member/rp-action", json={"chat_id": -100, "key": "eternal_love"})
    assert res.status_code == 403  # открывается на уровне 30, у пары 3


def test_фарм_действие_на_кулдауне_429(client, monkeypatch):
    from datetime import datetime, timedelta

    _as_member(monkeypatch)

    async def get_pair(chat_id, uid):
        return {"id": 5, "partner_id": 999, "level_index": 3, "premium": False}

    async def recent_cd(scope, ref_id, key):
        return datetime.utcnow() - timedelta(minutes=1)  # у «комплимента» кулдаун 5 мин

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "get_rel2_cooldown", recent_cd)
    res = client.post("/api/member/rp-action", json={"chat_id": -100, "key": "compliment"})
    assert res.status_code == 429


def test_фарм_действие_пишет_в_чат(client, monkeypatch):
    """Действие через сайт отражается в чате, будто участник написал его сам."""
    _as_member(monkeypatch)
    sent = {}

    async def get_pair(chat_id, uid):
        return {"id": 5, "partner_id": 999, "level_index": 3, "premium": False}

    async def _none(*a, **k):
        return None

    async def adjust(pair_id, delta, reason, floor_at_zero=True):
        return 2500

    async def levels():
        return [(1, "A", 0), (2, "B", 500), (3, "C", 2000)]

    async def level_name(idx):
        return "C"

    monkeypatch.setattr(db, "get_rel2_pair", get_pair)
    monkeypatch.setattr(db, "get_rel2_cooldown", _none)
    monkeypatch.setattr(db, "adjust_rel2_sparks", adjust)
    monkeypatch.setattr(db, "set_rel2_cooldown", _none)
    monkeypatch.setattr(db, "list_rel2_levels", levels)
    monkeypatch.setattr(db, "set_rel2_level", _none)
    monkeypatch.setattr(db, "get_rel2_level_name", level_name)
    monkeypatch.setattr(db, "get_nickname", _none)

    class FakeBot:
        async def send_message(self, chat_id, text, **k):
            sent["chat"] = chat_id
            sent["text"] = text

    monkeypatch.setattr(panel, "get_bot", lambda: FakeBot())
    res = client.post("/api/member/rp-action", json={"chat_id": -100, "key": "flowers"})
    assert res.status_code == 200, res.text
    # В объявлении — ГЛАГОЛ из каталога («подарил(а) цветы»), а не название
    # действия в инфинитиве. Раньше тут проверялось второе, и это была не
    # придирка к формулировке: рядом с рабочим каталогом лежал его урезанный
    # дубль без «verb» и «phrases», он молча затирал полный — и панель писала
    # в чат «подарить цветы».
    assert sent["chat"] == -100
    assert "подарил(а) цветы" in sent["text"], sent["text"]


# --- кланы участника -------------------------------------------------------

def test_кланы_обзор_не_в_клане(client, monkeypatch):
    _as_member(monkeypatch)

    async def no_clan(chat_id, uid):
        return None

    async def clans(chat_id, limit, offset):
        return ([{"id": 1, "name": "Волки", "members_count": 3, "coins": 100,
                  "war_points": 5, "title": None, "leader_id": 999}], 1)

    monkeypatch.setattr(db, "get_user_clan", no_clan)
    monkeypatch.setattr(db, "list_clans", clans)
    d = client.get("/api/member/clans?chat_id=-100").json()
    assert d["my"] is None
    assert d["clans"][0]["name"] == "Волки" and d["clans"][0]["leader_name"]


def test_создать_клан(client, monkeypatch):
    _as_member(monkeypatch)
    made = {}

    async def no_clan(chat_id, uid):
        return None

    async def create(chat_id, leader_id, name, description):
        made.update(name=name, leader=leader_id)
        return 7

    monkeypatch.setattr(db, "get_user_clan", no_clan)
    monkeypatch.setattr(db, "create_clan", create)
    res = client.post("/api/member/clan/create", json={"chat_id": -100, "name": "Волки", "description": "лучшие"})
    assert res.status_code == 200 and res.json()["clan_id"] == 7
    assert made["name"] == "Волки" and made["leader"] == 555


def test_создать_клан_уже_в_клане_409(client, monkeypatch):
    _as_member(monkeypatch)

    async def in_clan(chat_id, uid):
        return {"id": 1, "role": "member"}

    monkeypatch.setattr(db, "get_user_clan", in_clan)
    assert client.post("/api/member/clan/create", json={"chat_id": -100, "name": "X"}).status_code == 409


def test_лидер_не_может_выйти_409(client, monkeypatch):
    _as_member(monkeypatch)

    async def leader(chat_id, uid):
        return {"id": 1, "role": "leader"}

    monkeypatch.setattr(db, "get_user_clan", leader)
    assert client.post("/api/member/clan/leave", json={"chat_id": -100}).status_code == 409


def test_зам_не_может_кикнуть_зама_403(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_uc(chat_id, uid):
        return {"id": 1, "role": "deputy"}  # и вызывающий, и цель — замы

    monkeypatch.setattr(db, "get_user_clan", get_uc)
    res = client.post("/api/member/clan/kick", json={"chat_id": -100, "user_id": 888})
    assert res.status_code == 403


def test_передать_лидерство_только_лидер_403(client, monkeypatch):
    _as_member(monkeypatch)

    async def deputy(chat_id, uid):
        return {"id": 1, "role": "deputy"}

    monkeypatch.setattr(db, "get_user_clan", deputy)
    assert client.post("/api/member/clan/transfer", json={"chat_id": -100, "user_id": 888}).status_code == 403


def test_удалить_клан_лидером(client, monkeypatch):
    _as_member(monkeypatch)
    deleted = {}

    async def leader(chat_id, uid):
        return {"id": 3, "role": "leader"}

    async def delete(chat_id, clan_id):
        deleted["id"] = clan_id
        return True

    monkeypatch.setattr(db, "get_user_clan", leader)
    monkeypatch.setattr(db, "delete_clan", delete)
    res = client.post("/api/member/clan/delete", json={"chat_id": -100})
    assert res.status_code == 200 and deleted["id"] == 3


# --- семья участника (дом / питомцы / дети) ---------------------------------

def _pair5(monkeypatch):
    async def get_pair(chat_id, uid):
        return {"id": 5, "sparks": 1234, "partner_id": 999, "level_index": 3, "premium": False}
    monkeypatch.setattr(db, "get_rel2_pair", get_pair)


def test_семья_обзор(client, monkeypatch):
    _as_member(monkeypatch)
    _pair5(monkeypatch)

    async def no_house(pair_id):
        return None

    async def pets(pair_id):
        return [{"id": 1, "name": "Рекс", "species": "Дракон", "rarity": "редкий",
                 "level_index": 2, "hp": 80, "mood": 90, "is_active": 1, "pair_id": 5}]

    async def kids(pair_id):
        return [{"id": 7, "name": "Ваня", "level_index": 1, "mood": 50, "health": 60,
                 "intellect": 40, "charisma": 30, "section_key": None, "pair_id": 5}]

    monkeypatch.setattr(db, "get_rel2_house", no_house)
    monkeypatch.setattr(db, "list_rel2_pets", pets)
    monkeypatch.setattr(db, "list_rel2_children", kids)
    d = client.get("/api/member/family?chat_id=-100").json()
    assert d["pair"] is True and d["sparks"] == 1234
    assert d["pets"][0]["name"] == "Рекс" and d["pets"][0]["active"] is True
    assert d["children"][0]["name"] == "Ваня"


def test_питомец_активный(client, monkeypatch):
    _as_member(monkeypatch)
    _pair5(monkeypatch)
    saved = {}

    async def get_pet(pet_id):
        return {"id": 1, "pair_id": 5, "name": "Рекс"}

    async def set_active(pair_id, pet_id):
        saved.update(pair=pair_id, pet=pet_id)

    monkeypatch.setattr(db, "get_rel2_pet", get_pet)
    monkeypatch.setattr(db, "set_rel2_active_pet", set_active)
    res = client.post("/api/member/pet/active", json={"chat_id": -100, "pet_id": 1})
    assert res.status_code == 200 and saved == {"pair": 5, "pet": 1}


def test_чужого_питомца_нельзя_404(client, monkeypatch):
    _as_member(monkeypatch)
    _pair5(monkeypatch)

    async def get_pet(pet_id):
        return {"id": 1, "pair_id": 999}  # питомец другой пары

    monkeypatch.setattr(db, "get_rel2_pet", get_pet)
    res = client.post("/api/member/pet/rename", json={"chat_id": -100, "pet_id": 1, "name": "Хакер"})
    assert res.status_code == 404


def test_переименовать_ребёнка(client, monkeypatch):
    _as_member(monkeypatch)
    _pair5(monkeypatch)
    saved = {}

    async def get_child(child_id):
        return {"id": 7, "pair_id": 5}

    async def rename(child_id, name):
        saved.update(child=child_id, name=name)

    monkeypatch.setattr(db, "get_rel2_child", get_child)
    monkeypatch.setattr(db, "rename_rel2_child", rename)
    res = client.post("/api/member/child/rename", json={"chat_id": -100, "child_id": 7, "name": "Петя"})
    assert res.status_code == 200 and saved == {"child": 7, "name": "Петя"}


def test_сортировка_участников_по_сообщениям(monkeypatch):
    staff = PanelUser(id=1, username="a", role="admin")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: staff

    class FakeRoleMap:
        def annotate(self, rows):
            for r in rows:
                r["role"] = None
                r["role_key"] = None
                r["level"] = 0

        def matches(self, uid, needle):
            return False

    async def load():
        return FakeRoleMap()

    async def lst(chat_id, limit=500):
        return [
            {"user_id": 1, "full_name": "A", "username": None, "message_count": 5},
            {"user_id": 2, "full_name": "B", "username": None, "message_count": 50},
        ]

    monkeypatch.setattr(panel.roles, "load", load)
    monkeypatch.setattr(db, "list_current_users_with_counts", lst)
    client = TestClient(panel.app)
    try:
        res = client.get("/api/members?chat_id=-100&sort=messages_desc")
        assert res.status_code == 200, res.text
        assert [m["user_id"] for m in res.json()["members"]] == [2, 1]
        res2 = client.get("/api/members?chat_id=-100&sort=messages_asc")
        assert [m["user_id"] for m in res2.json()["members"]] == [1, 2]
    finally:
        panel.app.dependency_overrides.clear()


def test_развод_только_за_себя(client, monkeypatch):
    _as_member(monkeypatch)
    deleted = {}

    async def get_marriage(chat_id, uid):
        return {"partner_id": 999, "married_at": None}

    async def delete_marriage(chat_id, uid):
        deleted["uid"] = uid

    monkeypatch.setattr(db, "get_marriage", get_marriage)
    monkeypatch.setattr(db, "delete_marriage", delete_marriage)

    res = client.post("/api/member/divorce", json={"chat_id": -100})
    assert res.status_code == 200, res.text
    # развёлся ИМЕННО сессионный пользователь (555), не какой-то из тела запроса
    assert deleted["uid"] == 555


def test_развод_без_брака_404(client, monkeypatch):
    _as_member(monkeypatch)

    async def get_marriage(chat_id, uid):
        return None

    monkeypatch.setattr(db, "get_marriage", get_marriage)
    assert client.post("/api/member/divorce", json={"chat_id": -100}).status_code == 404


def test_предложение_самому_себе_400(client, monkeypatch):
    _as_member(monkeypatch)
    res = client.post("/api/member/propose-marriage", json={"chat_id": -100, "target_id": 555})
    assert res.status_code == 400


def test_предложение_уходит_в_чат_с_нужными_кнопками(client, monkeypatch):
    _as_member(monkeypatch)
    sent = {}

    async def get_marriage(chat_id, uid):
        return None

    monkeypatch.setattr(db, "get_marriage", get_marriage)

    class FakeBot:
        async def send_message(self, chat_id, text, reply_markup=None):
            sent.update(chat_id=chat_id, text=text, kb=reply_markup)

    monkeypatch.setattr(panel, "get_bot", lambda: FakeBot())

    res = client.post("/api/member/propose-marriage", json={"chat_id": -100, "target_id": 999})
    assert res.status_code == 200, res.text
    assert sent["chat_id"] == -100
    # кнопка ведёт в тот же колбэк бота: proposer=сессия(555), target=999
    assert sent["kb"].inline_keyboard[0][0].callback_data == "marriage_accept:555:999"


def test_relationship_требует_членства_в_чате(client, monkeypatch):
    member = PanelUser(id=7, username="tg555", role="member", tg_user_id=555, tg_full_name="Аня")
    panel.app.dependency_overrides[panel.auth.require_member] = lambda: member

    async def known(chat_id, uid):
        return None  # бот не видел участника в этом чате

    monkeypatch.setattr(db, "get_known_user", known)
    assert client.get("/api/member/relationship?chat_id=-100").status_code == 403
