"""Настройки бота через панель: что можно менять и что панель обязана отсеять.

Лимиты реста — числа, по которым бот отказывает участникам в заявке. Опечатка
вроде «14 дней» вместо «14» не должна доезжать до базы: бот прочитает мусор,
молча подставит дефолт, и владелец будет уверен, что настроил одно, а работает
другое. Поэтому панель проверяет значение до сохранения и объясняет отказ.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def panel_client(monkeypatch):
    saved: dict[str, str | None] = {}

    async def save_setting(key, value):
        saved[key] = value

    async def fetch_settings():
        return {}

    async def add_log(*args, **kwargs):
        return None

    async def list_command_levels():
        return []

    async def set_data(*args, **kwargs):
        # После сохранения настройки панель поднимает флаг перечитки, чтобы бот
        # (отдельный процесс) увидел правку без перезапуска — см.
        # _signal_action_reload в webpanel/app.py.
        return None

    monkeypatch.setattr(db, "set_data", set_data)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels)
    monkeypatch.setattr(db, "save_setting", save_setting)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_owner] = lambda: owner
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    client = TestClient(panel.app)
    client.saved = saved
    yield client
    panel.app.dependency_overrides.clear()


def put(client, key, value):
    return client.post("/api/settings", json={"key": key, "value": value})


REST_NUMERIC_KEYS = (
    "rest_max_days",
    "rest_cooldown_days",
    "rest_min_member_days",
    "rest_cleanup_block_days",
)


def test_rest_settings_are_editable_from_panel(panel_client):
    """Все ключи реста панель отдаёт на редактирование — иначе владельцу
    пришлось бы лезть в личку бота ради одного числа."""
    res = panel_client.get("/api/settings")
    assert res.status_code == 200, res.text
    keys = res.json()["settings"].keys()
    for key in REST_NUMERIC_KEYS + ("rest_rules_template", "rest_cleanup_date"):
        assert key in keys


@pytest.mark.parametrize("key", REST_NUMERIC_KEYS)
def test_numeric_limit_accepts_number(panel_client, key):
    assert put(panel_client, key, "14").status_code == 200
    assert panel_client.saved[key] == "14"


@pytest.mark.parametrize("key", REST_NUMERIC_KEYS)
@pytest.mark.parametrize("bad", ["14 дней", "-1", "3651", "", "две недели"])
def test_numeric_limit_rejects_garbage(panel_client, key, bad):
    res = put(panel_client, key, bad)
    assert res.status_code == 400, f"{key}={bad!r} прошло в базу"
    assert key not in panel_client.saved


def test_zero_disables_the_rule(panel_client):
    """0 — это «правило выключено» (см. rest_rules.py), а не ошибка ввода."""
    assert put(panel_client, "rest_max_days", "0").status_code == 200


def test_cleanup_date_accepts_russian_format(panel_client):
    assert put(panel_client, "rest_cleanup_date", "01.08.2026").status_code == 200
    assert panel_client.saved["rest_cleanup_date"] == "01.08.2026"


@pytest.mark.parametrize("bad", ["2026-08-01", "32.08.2026", "1 августа", "01.08.26"])
def test_cleanup_date_rejects_other_formats(panel_client, bad):
    """Формат ровно ДД.ММ.ГГГГ: бот разбирает дату этим шаблоном и на всё
    остальное отвечает «чистка не задана» — молча, без следов."""
    assert put(panel_client, "rest_cleanup_date", bad).status_code == 400
    assert "rest_cleanup_date" not in panel_client.saved


def test_cleanup_date_can_be_cleared(panel_client):
    """Пустая дата — валидное состояние: чистка не запланирована."""
    assert put(panel_client, "rest_cleanup_date", "").status_code == 200
    assert panel_client.saved["rest_cleanup_date"] == ""


def test_text_settings_are_not_validated(panel_client):
    """Тексты остаются свободными — в памятке про рест живут и цифры, и скобки."""
    assert put(panel_client, "rest_rules_template", "рест до {дата_окончания}").status_code == 200


def test_unknown_key_is_rejected(panel_client):
    assert put(panel_client, "bot_token", "123").status_code == 400


@pytest.mark.parametrize("value", ["0", "1"])
def test_переключатель_принимает_ноль_и_единицу(panel_client, value):
    assert put(panel_client, "fake_warns_in_list", value).status_code == 200
    assert panel_client.saved["fake_warns_in_list"] == value


@pytest.mark.parametrize("bad", ["да", "true", "вкл", "2", "", "on"])
def test_переключатель_отвергает_остальное(panel_client, bad):
    """Бот считает выключенным всё, кроме понятных ему значений: «да» в базе
    молча выключило бы настройку, которую владелец только что включил."""
    assert put(panel_client, "fake_warns_in_list", bad).status_code == 400
    assert "fake_warns_in_list" not in panel_client.saved
