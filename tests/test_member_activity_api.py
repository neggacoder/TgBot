"""Рыбалка и работа в кабинете: права и объявления."""

from __future__ import annotations

import inspect
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)
pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import fishing_actions  # noqa: E402
import work_actions  # noqa: E402
from webpanel import member_activity_api as api  # noqa: E402


def test_права_известны_боту():
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = (set(api._FISH_COMMANDS.values()) | set(api._WORK_COMMANDS.values())
             | {api._FISH_LIST, api._WORK_LIST})
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_сайт_умеет_открепить_трофей():
    assert api._FISH_COMMANDS["unpin"] == "fishing_net"
    source = inspect.getsource(api.api_member_fishing_action)
    assert 'fishing_actions.pin(chat_id, user_id, None)' in source


def test_заморозка_закрывает_занятия_и_на_сайте():
    for fn in (api.api_member_fishing_action, api.api_member_work_action):
        assert "is_account_frozen" in inspect.getsource(fn)


def test_чужой_чат_не_открывается():
    """Проверку делает общий _gate — она обязана стоять у каждого обработчика."""
    assert "require_member_in_chat" in inspect.getsource(api._gate)
    assert "permissions.ensure" in inspect.getsource(api._gate)
    for fn in (api.api_member_fishing, api.api_member_fishing_action,
               api.api_member_work, api.api_member_work_action):
        assert "_gate(" in inspect.getsource(fn)


def test_поздравления_совпадают_с_ботом():
    for код, текст in api.ACHIEVEMENT_TEXTS.items():
        meta = bot_module.ACHIEVEMENTS.get(код)
        assert meta, f"{код} пропал из ACHIEVEMENTS бота"
        assert meta["title"] in текст, f"{код}: название разъехалось"
        assert meta["desc"] in текст, f"{код}: описание разъехалось"


def test_все_ачивки_занятий_объявляются():
    коды = set()
    for модуль in (fishing_actions, work_actions):
        with open(модуль.__file__, encoding="utf-8") as f:
            for строка in f:
                if "achievements.append(" in строка:
                    коды.add(строка.split('"')[1])
    assert коды <= set(api.ACHIEVEMENT_TEXTS), (
        f"не объявляются: {sorted(коды - set(api.ACHIEVEMENT_TEXTS))}")


def test_улов_и_смена_в_чат_не_уходят():
    """Это личные занятия: в чат идут только достижения. Иначе каждый заброс
    засорял бы чат — а хвастаться есть кнопкой в казино."""
    исходник = inspect.getsource(api)
    отправки = исходник.count("send_message")
    assert отправки == 1, "отправка в чат должна быть ровно одна — в _announce"
    assert "send_message" in inspect.getsource(api._announce)


def test_правила_общие_с_ботом():
    assert bot_module.PROFESSIONS is work_actions.professions.PROFESSIONS
    assert bot_module.PROFESSION_WORK_COOLDOWN is work_actions.professions.WORK_COOLDOWN
    assert bot_module.NET_CAPACITY == fishing_actions.NET_CAPACITY
    assert bot_module.FISHING_COOLDOWN == fishing_actions.COOLDOWN
