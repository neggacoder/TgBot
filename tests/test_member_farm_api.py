"""Ферма в кабинете участника: то, что бот и сайт обязаны понимать одинаково.

Экран фермы на сайте — вторая дверь в ту же игру. Опасность у второй двери
одна: она незаметно начинает жить по своим правилам. Здесь проверяется не
вёрстка, а стыки — права, тексты и разбор количества.
"""

from __future__ import annotations

import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)
pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import farm_actions  # noqa: E402
from webpanel import member_farm_api as api  # noqa: E402


def test_у_каждого_действия_есть_право():
    """Действие без ключа права — дыра: в чате команда закрыта уровнем, а с
    сайта делается кем угодно."""
    действия = {"plant", "harvest", "expand", "barn_buy", "barn_sell", "barn_collect"}
    assert set(api._ACTION_COMMANDS) == действия
    assert all(api._ACTION_COMMANDS[a] for a in действия)


def test_права_фермы_известны_боту():
    """Ключ, которого нет в реестре команд бота, — это право, которое админ
    никогда не сможет настроить: «право farm_plant 2» ответит «не знаю такой»."""
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = set(api._ACTION_COMMANDS.values()) | {api._LIST_COMMAND}
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_поздравления_совпадают_с_ботом():
    """Тексты ачивок продублированы в панели (ACHIEVEMENTS живёт в bot.py, а
    панель его импортировать не может). Разъедься они — за одно достижение
    приходили бы два разных поздравления, смотря где нажал."""
    for код, текст in api.ACHIEVEMENT_TEXTS.items():
        meta = bot_module.ACHIEVEMENTS.get(код)
        assert meta, f"{код} пропал из ACHIEVEMENTS бота"
        assert meta["title"] in текст, f"{код}: название разъехалось"
        assert meta["desc"] in текст, f"{код}: описание разъехалось"
        assert meta["emoji"] in текст


def test_ачивки_фермы_объявляются_все():
    """Модуль правил умеет выдать ровно эти коды. Появится третий — про него
    забудут, и человек получит достижение молча."""
    коды = set()
    исходник = (bot_module.__file__.rsplit("/", 1)[0] + "/farm_actions.py")
    with open(исходник, encoding="utf-8") as f:
        текст = f.read()
    for код in api.ACHIEVEMENT_TEXTS:
        assert код in текст
        коды.add(код)
    for строка in текст.split("\n"):
        if "achievements.append(" in строка:
            код = строка.split('"')[1]
            assert код in коды, f"{код} выдаётся, но не объявляется на сайте"


@pytest.mark.parametrize("сырое,ожидание", [
    (None, 1), (3, 3), ("3", 3), (" 5 ", 5),
    ("все", "все"), ("всё", "все"), ("ВСЕ", "все"), ("all", "все"),
])
def test_количество_разбирается_как_в_чате(сырое, ожидание):
    assert api._count(сырое) == ожидание


def test_непонятное_количество_это_отказ_а_не_единица():
    """Молча посадить одну грядку вместо «десять» — хуже, чем отказать: человек
    увидит списание не за то, что просил."""
    with pytest.raises(Exception):
        api._count("много")


def test_состояние_не_течёт_в_чужой_чат():
    """Оба обработчика обязаны спросить require_member_in_chat ДО работы:
    без этого код доступа к своему чату открывал бы чужие фермы."""
    import inspect
    for fn in (api.api_member_farm, api.api_member_farm_action):
        исходник = inspect.getsource(fn)
        assert "require_member_in_chat" in исходник
        assert "permissions.ensure" in исходник


def test_заморозка_закрывает_ферму_и_на_сайте():
    import inspect
    исходник = inspect.getsource(api.api_member_farm_action)
    assert "is_account_frozen" in исходник
    assert api.FROZEN == "🧊 Ваш счёт заморожен администрацией."


def test_модуль_правил_общий_с_ботом():
    """Стык, ради которого всё затевалось: сайт зовёт те же функции."""
    assert api.farm_actions is farm_actions
    assert bot_module._farm_aura is farm_actions.aura
