"""Мини-приложение Telegram: вход по подписи вместо пароля.

Здесь проверяется единственное, что стоит между чатом и чужим аккаунтом, —
проверка initData. Telegram передаёт приложению, кто его открыл, и подписывает
это секретом бота; если проверку ослабить, доступ к разделу участника получит
кто угодно, просто подставив свой user id.

Отдельно закреплено, что послабления, нужные мини-приложению (нет CSRF,
разрешено встраивание в iframe), НЕ распространились на панель.
"""

from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

import db
import webapp_auth
from webpanel import auth

panel = importlib.import_module("webpanel.app")

TOKEN = "123456:ABCdefGHIjklMNOpqrsTUVwxyz"
TG_ID = 555


def signed(user: dict | None = None, auth_date: int | None = None, token: str = TOKEN) -> str:
    return webapp_auth.build_init_data(
        user or {"id": TG_ID, "first_name": "Аня", "username": "anya"}, token, auth_date
    )


# --- проверка подписи ------------------------------------------------------

def test_валидная_подпись_даёт_пользователя():
    user = webapp_auth.parse_init_data(signed(), TOKEN)
    assert user is not None
    assert user.id == TG_ID and user.username == "anya"
    assert user.full_name == "Аня"


def test_подпись_чужим_токеном_не_принимается():
    """Главное свойство: не зная токена бота, подпись не подделать."""
    assert webapp_auth.parse_init_data(signed(token="999:OTHERTOKEN"), TOKEN) is None


def test_подмена_данных_ломает_подпись():
    data = signed({"id": TG_ID, "first_name": "Аня"})
    tampered = data.replace(str(TG_ID), "999")
    assert tampered != data
    assert webapp_auth.parse_init_data(tampered, TOKEN) is None


def test_старая_подпись_протухает():
    """initData попадает в адрес webview и может утечь. Без срока годности
    утечка означала бы вечный доступ к аккаунту."""
    old = int(time.time()) - webapp_auth.MAX_AUTH_AGE_SECONDS - 60
    assert webapp_auth.parse_init_data(signed(auth_date=old), TOKEN) is None
    fresh = int(time.time()) - 60
    assert webapp_auth.parse_init_data(signed(auth_date=fresh), TOKEN) is not None


@pytest.mark.parametrize("raw", [
    "", None, "это не query-string", "user=%7B%7D&auth_date=1", "hash=deadbeef",
])
def test_мусор_не_проходит(raw):
    assert webapp_auth.parse_init_data(raw, TOKEN) is None


def test_бот_не_считается_пользователем():
    data = signed({"id": 42, "first_name": "Bot", "is_bot": True})
    assert webapp_auth.parse_init_data(data, TOKEN) is None


def test_без_токена_бота_ничего_не_проходит(monkeypatch):
    """Панель без BOT_TOKEN не должна «на всякий случай» пускать всех."""
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert webapp_auth.parse_init_data(signed()) is None


# --- вход в панель по подписи ----------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)

    async def _noop(*args, **kwargs):
        return None

    async def get_member(tg_user_id):
        return {"id": 7, "username": f"tg{tg_user_id}", "role": "member",
                "tg_user_id": tg_user_id, "tg_full_name": "Аня", "disabled": False}

    monkeypatch.setattr(db, "add_log", _noop, raising=False)
    monkeypatch.setattr(db, "get_panel_user_by_tg", get_member)
    monkeypatch.setattr(db, "update_panel_member_name", _noop, raising=False)
    c = TestClient(panel.app)
    yield c
    panel.app.dependency_overrides.clear()


def _member_chats(monkeypatch, chat_ids=(-100,)):
    async def list_user_chats(tg_user_id):
        return list(chat_ids)

    async def get_chat(chat_id):
        raise RuntimeError("в тестах в Telegram не ходим")

    monkeypatch.setattr(db, "list_user_chats", list_user_chats)
    monkeypatch.setattr(panel, "get_bot", lambda: type("B", (), {"get_chat": get_chat})())


def test_подписанный_запрос_пускает_без_куки(client, monkeypatch):
    _member_chats(monkeypatch)
    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code == 200, res.text
    assert res.json()["chats"][0]["chat_id"] == -100


def test_без_подписи_и_без_куки_401(client):
    assert client.get("/api/member/chats").status_code == 401


def test_поддельная_подпись_401(client):
    bad = signed(token="999:NOTTHEBOTTOKEN")
    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: bad})
    assert res.status_code == 401


def test_отключённый_аккаунт_не_пускают(client, monkeypatch):
    async def disabled(tg_user_id):
        return {"id": 7, "username": "tg555", "role": "member",
                "tg_user_id": tg_user_id, "tg_full_name": "Аня", "disabled": True}

    monkeypatch.setattr(db, "get_panel_user_by_tg", disabled)
    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code == 401


def test_подпись_не_даёт_доступа_к_админским_ручкам(client, monkeypatch):
    """Мини-приложение — это раздел УЧАСТНИКА. Подпись Telegram не должна
    открывать настройки бота и прочую админку."""
    for endpoint in ("/api/settings", "/api/chats", "/api/users"):
        res = client.get(endpoint, headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
        assert res.status_code in (401, 403), f"{endpoint}: {res.status_code}"


def test_подписанный_post_не_требует_csrf(client, monkeypatch):
    """CSRF защищает от того, что браузер сам подставит куку к чужому запросу.
    Здесь куки нет вовсе, а заголовок с подписью чужая страница выставить не
    может — поэтому проверка тут лишняя и мешала бы."""
    async def in_chat(user, chat_id):
        return None

    async def no_pair(chat_id, uid):
        return None

    monkeypatch.setattr(panel, "_require_member_in_chat", in_chat)
    monkeypatch.setattr(db, "get_rel2_pair", no_pair)
    res = client.post(
        "/api/member/farm-bonus",
        json={"chat_id": -100},
        headers={auth.WEBAPP_INIT_DATA_HEADER: signed()},
    )
    # 404 «нет пары» — значит, до логики дошли: CSRF не отказал (было бы 403)
    assert res.status_code == 404, res.text


def test_обычный_post_по_куке_csrf_по_прежнему_требует(client):
    """Послабление касается только запросов с подписью Telegram."""
    assert client.post("/api/logout").status_code == 403


# --- страница приложения и заголовки ---------------------------------------

def test_страница_приложения_отдаётся(client):
    res = client.get("/app")
    assert res.status_code == 200
    assert "webapp.js" in res.text


def test_приложение_можно_встроить_только_телеграму(client):
    csp = client.get("/app").headers["Content-Security-Policy"]
    assert "frame-ancestors https://web.telegram.org https://telegram.org" in csp
    # X-Frame-Options умеет только DENY/SAMEORIGIN и здесь помешал бы
    assert "X-Frame-Options" not in client.get("/app").headers


def test_панель_встраивать_по_прежнему_нельзя(client, monkeypatch):
    async def no_users():
        return 0

    monkeypatch.setattr(db, "count_panel_users", no_users)
    for path in ("/", "/api/me"):
        headers = client.get(path).headers
        assert headers.get("X-Frame-Options") == "DENY", path
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"], path


def test_внешний_скрипт_разрешён_только_на_странице_приложения(client):
    app_csp = client.get("/app").headers["Content-Security-Policy"]
    panel_csp = client.get("/").headers["Content-Security-Policy"]
    assert "script-src 'self' https://telegram.org" in app_csp
    assert "script-src 'self';" in panel_csp + ";"
    assert "telegram.org" not in panel_csp


# --- первое открытие приложения --------------------------------------------

def test_первое_открытие_заводит_аккаунт(client, monkeypatch):
    """Путь, по которому проходит КАЖДЫЙ новый пользователь: строки в панели
    ещё нет, её надо создать по данным из подписи."""
    created = {}

    async def no_member(tg_user_id):
        return None

    async def create(tg_user_id, username, full_name):
        created.update(tg=tg_user_id, username=username, name=full_name)
        return 42

    monkeypatch.setattr(db, "get_panel_user_by_tg", no_member)
    monkeypatch.setattr(db, "create_panel_member", create)
    _member_chats(monkeypatch)

    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code == 200, res.text
    assert created == {"tg": TG_ID, "username": f"tg{TG_ID}", "name": "Аня"}


def test_гонка_при_первом_открытии_не_роняет_вход(client, monkeypatch):
    """Приложение дёргает несколько ручек сразу: оба запроса видят «строки
    нет», второй INSERT упирается в UNIQUE. Это не ошибка — нас опередили."""
    import aiomysql

    calls = {"n": 0}

    async def racing_member(tg_user_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # первый взгляд: строки нет
        return {"id": 7, "username": f"tg{tg_user_id}", "role": "member",
                "tg_user_id": tg_user_id, "tg_full_name": "Аня", "disabled": False}

    async def create_conflict(*args, **kwargs):
        raise aiomysql.IntegrityError(1062, "Duplicate entry")

    monkeypatch.setattr(db, "get_panel_user_by_tg", racing_member)
    monkeypatch.setattr(db, "create_panel_member", create_conflict)
    _member_chats(monkeypatch)

    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code == 200, res.text


# --- тела запросов, которые шлёт само приложение ---------------------------
# Каждая кнопка в webapp.js отправляет свой JSON. Если модель на сервере
# ждёт другое поле — кнопка молча вернёт 422, и заметит это только человек в
# чате. Ниже проверяется ровно то, что шлёт фронт: до логики дошло, разбор
# тела не отверг.

@pytest.mark.parametrize("path,body", [
    ("/api/member/farm-bonus", {"chat_id": -100}),
    ("/api/member/rp-action", {"chat_id": -100, "key": "compliment"}),
    ("/api/member/divorce", {"chat_id": -100}),
    ("/api/member/restore", {"chat_id": -100, "kind": "marriage"}),
    ("/api/member/clan/leave", {"chat_id": -100}),
    ("/api/member/clan/join", {"chat_id": -100, "clan_id": 1}),
])
def test_тела_запросов_приложения_принимаются(client, monkeypatch, path, body):
    async def in_chat(user, chat_id):
        return None

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(panel, "_require_member_in_chat", in_chat)
    for name in ("get_rel2_pair", "get_marriage", "get_recent_dissolution",
                 "get_user_clan", "get_clan"):
        monkeypatch.setattr(db, name, nothing, raising=False)

    res = client.post(path, json=body, headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code != 422, f"{path}: тело не подошло модели — {res.text}"
    assert res.status_code != 403, f"{path}: отказ CSRF, хотя вход по подписи"


# --- совместимость с новыми клиентами --------------------------------------

def _signed_with_signature(in_hash: bool) -> str:
    """Собирает initData так, как её присылают новые клиенты: с полем
    signature. Оно появилось позже, и включать ли его в строку для hash —
    вопрос, по которому документация менялась. Принимать надо оба варианта:
    цена ошибки — «не пускает вообще никого»."""
    import hashlib
    import hmac
    import json as _json
    import time as _time
    from urllib.parse import urlencode

    fields = {
        "user": _json.dumps({"id": TG_ID, "first_name": "Аня"},
                            separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(int(_time.time())),
        "chat_type": "private",
        "signature": "ed25519-подпись",
    }
    keys = sorted(fields) if in_hash else sorted(k for k in fields if k != "signature")
    dcs = "\n".join(f"{k}={fields[k]}" for k in keys)
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.mark.parametrize("signature_in_hash", [False, True])
def test_подпись_с_полем_signature_принимается(signature_in_hash):
    user, reason = webapp_auth.check_init_data(_signed_with_signature(signature_in_hash), TOKEN)
    assert user is not None, reason
    assert user.id == TG_ID


def test_лишнее_поле_не_ломает_проверку():
    """Telegram добавляет новые поля со временем; проверка обязана считать
    подпись по тому, что реально пришло, а не по заранее известному списку."""
    import hashlib
    import hmac
    import json as _json
    import time as _time
    from urllib.parse import urlencode

    fields = {
        "user": _json.dumps({"id": TG_ID, "first_name": "Аня"}, separators=(",", ":")),
        "auth_date": str(int(_time.time())),
        "поле_из_будущего": "значение",
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    user, reason = webapp_auth.check_init_data(urlencode(fields), TOKEN)
    assert user is not None, reason


# --- самодиагностика --------------------------------------------------------

def test_диагностика_объясняет_отказ(client):
    """Без неё «Нужен вход» одинаково означает и чужой токен, и съехавшее
    время, и вообще отсутствие данных."""
    bad = signed(token="999:NOTTHEBOTTOKEN")
    res = client.get("/api/webapp-check", headers={auth.WEBAPP_INIT_DATA_HEADER: bad})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "BOT_TOKEN" in body["reason"]
    assert body["got_init_data"] is True
    assert body["user_id"] is None


def test_диагностика_подтверждает_успех(client):
    res = client.get("/api/webapp-check", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    body = res.json()
    assert body["ok"] is True and body["user_id"] == TG_ID and body["reason"] == ""


def test_диагностика_без_данных(client):
    body = client.get("/api/webapp-check").json()
    assert body["ok"] is False and body["got_init_data"] is False


def test_диагностика_не_выдаёт_секретов(client):
    """Ручка публичная — в ответе не должно быть ни токена, ни подписи."""
    raw = client.get("/api/webapp-check",
                     headers={auth.WEBAPP_INIT_DATA_HEADER: signed()}).text
    assert TOKEN not in raw
    assert "hash" not in raw


# --- регрессия: владелец не мог войти в собственное приложение --------------

def test_привязанный_персонал_пускается(client, monkeypatch):
    """Тот самый баг с первого реального захода.

    Колонка panel_users.tg_user_id — UNIQUE, а персонал (owner/admin)
    привязывает к ней свой Telegram сам — это прямо советует команда «сайт».
    Поиск шёл с фильтром role='member', такую строку не находил, пытался
    завести вторую с тем же tg_user_id, упирался в UNIQUE — и отказывал.
    Владелец получал «Нужен вход» в приложении, которое сам же и поставил,
    а обычный участник заходил нормально.
    """
    async def staff_row(tg_user_id):
        return {"id": 1, "username": "owner", "role": "owner",
                "tg_user_id": tg_user_id, "tg_full_name": "Хозяин", "disabled": False}

    async def must_not_create(*args, **kwargs):
        raise AssertionError("аккаунт уже есть — создавать второй нельзя")

    monkeypatch.setattr(db, "get_panel_user_by_tg", staff_row)
    monkeypatch.setattr(db, "create_panel_member", must_not_create)
    _member_chats(monkeypatch)

    res = client.get("/api/member/chats", headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
    assert res.status_code == 200, res.text


def test_персоналу_подпись_всё_равно_не_открывает_админку(client, monkeypatch):
    """Роль сохраняется настоящая — значит, надо убедиться, что это не даёт
    админского доступа: его выдаёт только вход по паролю (кука)."""
    async def staff_row(tg_user_id):
        return {"id": 1, "username": "owner", "role": "owner",
                "tg_user_id": tg_user_id, "tg_full_name": "Хозяин", "disabled": False}

    monkeypatch.setattr(db, "get_panel_user_by_tg", staff_row)
    for endpoint in ("/api/settings", "/api/users", "/api/chats"):
        res = client.get(endpoint, headers={auth.WEBAPP_INIT_DATA_HEADER: signed()})
        assert res.status_code in (401, 403), f"{endpoint}: {res.status_code}"
