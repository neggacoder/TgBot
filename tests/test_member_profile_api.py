"""Профиль и топы в кабинете: доступ и совпадение с чатом."""

from __future__ import annotations

import inspect
import os
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)
pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import profile_actions  # noqa: E402
from webpanel import member_profile_api as api  # noqa: E402


def test_права_известны_боту():
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = {api._PROFILE_COMMAND, api._TOPS_COMMAND}
    ключи |= {v["command"] for v in profile_actions.TOPS.values()}
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_чужой_профиль_с_сайта_не_открывается():
    """В чате за чужую карточку платят «досье». Бесплатная дверь мимо платной
    команды обесценила бы её."""
    исходник = inspect.getsource(api.api_member_profile)
    assert "user.tg_user_id" in исходник
    assert "target" not in исходник and "user_id:" not in исходник


def test_чужой_чат_не_открывается():
    for fn in (api.api_member_profile, api.api_member_tops):
        исходник = inspect.getsource(fn)
        assert "require_member_in_chat" in исходник and "permissions.ensure" in исходник


def test_топ_такой_же_длины_как_в_чате():
    """«На сайте топ длиннее» было бы отдельной правдой о том же топе."""
    assert api.TOP_LIMIT == 10


def test_неизвестный_топ_это_отказ_а_не_пустота():
    исходник = inspect.getsource(api.api_member_tops)
    assert "profile_actions.TOPS" in исходник and "HTTPException" in исходник


def test_профиль_ничего_не_меняет():
    """Витрина: ни одной записи в базу. Иначе открытие вкладки начислялось бы
    как действие — так уже было со счётчиком игр в казино."""
    исходник = inspect.getsource(profile_actions)
    for запрет in ("add_coins", "set_data", "grant_achievement", "increment_",
                   "add_log", "delete_data"):
        assert запрет not in исходник, f"профиль пишет в базу: {запрет}"


def test_границы_недели_общие_с_ботом():
    """Профиль и топ уже расходились ровно здесь: один считал неделю с
    понедельника, другой с субботы."""
    исходник = inspect.getsource(profile_actions.top)
    assert "period_start_day" in исходник
    assert not re.search(r"weekday\(\)|timedelta\(days=", исходник), (
        "своя арифметика недели — это второй источник правды")
