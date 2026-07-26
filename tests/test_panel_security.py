"""Защита веб-панели: то, что нельзя проверить глазами и легко сломать правкой.

Панель смотрит в интернет через Tailscale Funnel, поэтому здесь закреплены
именно те свойства, отсутствие которых уже было дырой:

  * сессия перестаёт годиться после смены пароля (иначе угнанная кука живёт
    свои 12 часов, что бы владелец ни делал);
  * X-Forwarded-For слушается только от доверенного прокси (иначе счётчик
    неудачных входов по адресу обнуляется одной строкой в заголовке);
  * аккаунт без пароля (участник) нельзя пройти обычной формой входа;
  * выход из панели требует CSRF-токен.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import db
from webpanel import auth

panel = importlib.import_module("webpanel.app")


def _request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "client": ((peer, 12345) if peer else None),
    })


# --- сессия и смена пароля -------------------------------------------------

def test_смена_пароля_обесценивает_старую_сессию():
    old_hash = auth.hash_password("прежний-пароль-12345")
    token = auth.issue_session(7, old_hash)

    uid, fingerprint = auth.read_session(token)
    assert uid == 7
    # с тем же хешем кука подходит
    assert fingerprint == auth.session_fingerprint(old_hash)
    # а с новым — уже нет
    new_hash = auth.hash_password("новый-пароль-1234567")
    assert fingerprint != auth.session_fingerprint(new_hash)


def test_участник_без_пароля_имеет_пустой_отпечаток():
    """У аккаунта-участника password_hash = NULL: отзывать нечего, но и падать
    на None нельзя — иначе вход по коду ломается целиком."""
    assert auth.session_fingerprint(None) == ""
    uid, fingerprint = auth.read_session(auth.issue_session(42))
    assert (uid, fingerprint) == (42, "")


def test_чужая_подпись_не_проходит():
    assert auth.read_session("сплошная.выдумка.подпись") is None


# --- пароль ----------------------------------------------------------------

def test_пустой_хеш_не_подходит_ни_к_какому_паролю():
    """Аккаунт-участник заводится с password_hash = NULL. Раньше argon2
    получал None и падал TypeError — 500 вместо 401 выдавал наружу, что такой
    аккаунт существует."""
    assert auth.verify_password(None, "любой") is False
    assert auth.verify_password("", "любой") is False


# --- доверие к заголовкам прокси -------------------------------------------

def test_forwarded_for_от_чужого_адреса_игнорируется(monkeypatch):
    monkeypatch.delenv("PANEL_TRUSTED_PROXIES", raising=False)
    ip = auth.client_ip(_request("203.0.113.9", "1.2.3.4"))
    assert ip == "203.0.113.9", "подделанный заголовок не должен подменять адрес"


def test_forwarded_for_от_локального_прокси_принимается(monkeypatch):
    monkeypatch.delenv("PANEL_TRUSTED_PROXIES", raising=False)
    assert auth.client_ip(_request("127.0.0.1", "198.51.100.7")) == "198.51.100.7"


def test_берётся_последний_элемент_списка(monkeypatch):
    """Всё, что левее, мог прислать сам клиент; правый элемент дописал наш
    собственный прокси."""
    monkeypatch.delenv("PANEL_TRUSTED_PROXIES", raising=False)
    ip = auth.client_ip(_request("127.0.0.1", "1.2.3.4, 198.51.100.7"))
    assert ip == "198.51.100.7"


def test_без_заголовка_берётся_адрес_соединения(monkeypatch):
    monkeypatch.delenv("PANEL_TRUSTED_PROXIES", raising=False)
    assert auth.client_ip(_request("198.51.100.1")) == "198.51.100.1"


# --- CSRF ------------------------------------------------------------------

@pytest.fixture
def client():
    c = TestClient(panel.app)
    yield c
    panel.app.dependency_overrides.clear()


def test_выход_без_csrf_токена_отклоняется(client):
    """Без этого сторонний сайт выкидывал бы вас из панели одним запросом."""
    assert client.post("/api/logout").status_code == 403


def test_выход_с_csrf_токеном_проходит(client):
    # токены только из ASCII: настоящий new_csrf_token() — url-safe base64,
    # а кириллица в заголовке HTTP просто не кодируется
    client.cookies.set(auth.CSRF_COOKIE, "logout-token-123")
    res = client.post("/api/logout", headers={auth.CSRF_HEADER: "logout-token-123"})
    assert res.status_code == 200


def test_несовпадающий_csrf_токен_отклоняется(client):
    client.cookies.set(auth.CSRF_COOKIE, "real-token-123")
    res = client.post("/api/logout", headers={auth.CSRF_HEADER: "guessed-token-9"})
    assert res.status_code == 403


# --- заголовки ответа ------------------------------------------------------

def test_ответ_несёт_заголовки_безопасности(client, monkeypatch):
    async def no_users():
        return 0

    monkeypatch.setattr(db, "count_panel_users", no_users)
    headers = client.get("/api/me").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "max-age=" in headers["Strict-Transport-Security"]
    csp = headers["Content-Security-Policy"]
    for directive in ("frame-ancestors 'none'", "base-uri 'none'", "object-src 'none'"):
        assert directive in csp, f"в CSP пропала директива {directive}"
