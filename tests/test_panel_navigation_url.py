"""Навигация панели переживает перезагрузку через параметры URL."""

from pathlib import Path


APP_JS = (Path(__file__).parents[1] / "webpanel" / "static" / "app.js").read_text(
    encoding="utf-8"
)


def test_url_хранит_тип_панели_и_вкладку():
    assert 'url.searchParams.set("panel", panel)' in APP_JS
    assert 'url.searchParams.set("tab", tab)' in APP_JS
    assert 'history[push ? "pushState" : "replaceState"]' in APP_JS


def test_участник_восстанавливает_вкладку_из_url():
    assert 'nav.panel === "member" ? nav.tab : null' in APP_JS
    assert 'switchMemberTab(exists ? requested : "prof", false)' in APP_JS


def test_админ_восстанавливает_раздел_из_url():
    assert 'nav.panel === "admin" ? nav.tab : null' in APP_JS
    assert 'switchAdminView(button ? requested : "send", false)' in APP_JS


def test_назад_и_вперёд_браузера_обрабатываются():
    assert 'window.addEventListener("popstate"' in APP_JS

