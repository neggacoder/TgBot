"""Навигация панели переживает перезагрузку через настоящие URL-страницы."""

import asyncio
import importlib
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

panel = importlib.import_module("webpanel.app")


def _guest_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})

APP_JS = (Path(__file__).parents[1] / "webpanel" / "static" / "app.js").read_text(
    encoding="utf-8"
)


def test_url_хранит_тип_панели_и_вкладку_в_пути():
    assert "const MEMBER_TAB_TO_ROUTE" in APP_JS
    assert 'if (parts[0] === "member")' in APP_JS
    assert 'if (parts[0] === "admin")' in APP_JS
    assert 'url.pathname = `/${panel}/${route || (panel === "member" ? "profile" : "send")}`' in APP_JS
    assert 'history[push ? "pushState" : "replaceState"]' in APP_JS


def test_участник_восстанавливает_вкладку_из_url():
    assert 'nav.panel === "member" ? nav.tab : null' in APP_JS
    assert 'switchMemberTab(exists ? requested : "prof", false)' in APP_JS


def test_админ_восстанавливает_раздел_из_url():
    assert 'nav.panel === "admin" ? nav.tab : null' in APP_JS
    assert 'switchAdminView(button ? requested : "send", false)' in APP_JS


def test_назад_и_вперёд_браузера_обрабатываются():
    assert 'window.addEventListener("popstate"' in APP_JS


def test_вход_возвращает_на_исходную_страницу():
    assert "function postLoginUrl()" in APP_JS
    assert "location.assign(postLoginUrl())" in APP_JS
    assert "`${location.pathname}${location.search}${location.hash}`" in APP_JS


def test_запуск_происходит_после_состояния_профиля():
    """Иначе быстрый /api/me открывал профайл до инициализации _prof."""
    assert APP_JS.rfind("boot().catch(") > APP_JS.index("const _prof =")


def test_маршрут_участника_не_превращается_в_админку_по_роли():
    assert 'if (nav.panel === "member") showMember();' in APP_JS
    assert 'if (me.role === "member") location.replace("/member/profile");' in APP_JS


def test_страница_участника_не_вешает_админский_обработчик_без_элемента():
    assert 'on(sel, "input", refreshStockForecast);' in APP_JS
    assert '$(sel).addEventListener("input", refreshStockForecast);' not in APP_JS


def test_сервер_отдаёт_оболочку_для_страниц_кабинета_и_админки():
    member = asyncio.run(panel.member_page("fishing", _guest_request()))
    admin = asyncio.run(panel.admin_page("complaints", _guest_request()))
    assert member.status_code == admin.status_code == 200
    member_html = member.body.decode()
    admin_html = admin.body.decode()
    assert "app.js?v=" in member_html
    assert "app.js?v=" in admin_html
    assert '<div id="member"' in member_html
    assert '<div id="app"' not in member_html
    assert '<div id="auth" class="auth">' in member_html
    assert '<div id="app"' in admin_html
    assert '<div id="member"' not in admin_html


def test_неизвестная_страница_остаётся_404():
    try:
        asyncio.run(panel.member_page("does-not-exist", _guest_request()))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("опечатка в маршруте не должна открывать главную")
