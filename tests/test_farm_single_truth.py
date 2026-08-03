"""Общие части фермы — одно определение на бота и на сайт.

ЧТО общее на сегодня: помощники (аура питомцев, погода, разбивка грядок,
счётчики ачивок) и ключи хранения. Тела самих действий у бота пока свои —
farm_actions.plant/harvest/... зовёт только сайт. Пока это так, правку цены
или срока приходится делать в двух местах; свести их — отдельная работа.

Панель — отдельный процесс, bot.py она импортировать не может, поэтому правила
огорода переехали в farm_actions. Соблазн при следующей правке — дописать
недостающее прямо в bot.py «пока только для чата»: тогда сайт и бот начнут
считать грядки, ауру питомцев и ключи хранения по-разному, и заметит это не
тест, а человек, у которого купленная на сайте грядка не появилась в чате.

Поэтому здесь не поведение, а устройство: одно имя — одно определение.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest

import farm_actions

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


# Что бот обязан брать из общего модуля, а не заводить своё.
ОБЩЕЕ = {
    "FarmAura": "FarmAura",
    "_farm_aura": "aura",
    "_farm_bought_plots": "bought_plots",
    "_farm_plots_key": "plots_key",
    "_farm_counter_key": "counter_key",
    "_farm_bump_counter": "bump_counter",
}


@pytest.mark.parametrize("в_боте,в_модуле", sorted(ОБЩЕЕ.items()))
def test_бот_берёт_правила_фермы_из_общего_модуля(в_боте, в_модуле):
    assert getattr(bot_module, в_боте) is getattr(farm_actions, в_модуле), (
        f"bot.{в_боте} перестал быть farm_actions.{в_модуле} — "
        "значит, у чата и сайта разные правила"
    )


def test_в_боте_нет_своих_определений_этих_имён():
    """Проверяем ИСХОДНИК, а не объект: «is» выше пройдёт и в том случае, если
    рядом с присваиванием кто-то допишет собственное def с тем же именем —
    победит последнее, и какое именно, зависит от порядка строк."""
    дерево = ast.parse((КОРЕНЬ / "bot.py").read_text(encoding="utf-8"))
    определения = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            определения.add(узел.name)
    свои = определения & set(ОБЩЕЕ)
    assert not свои, f"bot.py снова определяет сам: {', '.join(sorted(свои))}"


def test_ключи_общие_даже_там_где_чтение_своё():
    """У заморозки и событий бот читает базу сам — через свой модульный db,
    который подменяют тесты. Но КЛЮЧ обязан быть общим: разъедься он, сайт
    смотрел бы не на ту отметку и пускал бы замороженного играть."""
    assert bot_module._frozen_key is farm_actions.frozen_key
    assert bot_module._events_state_key is farm_actions.events_state_key
    assert farm_actions.frozen_key(-100, 7) == "frozen:-100:7"
    assert farm_actions.events_state_key(-100) == "chat_event:-100"


def test_ключи_хранения_совпадают_с_прежними():
    """Формат менять нельзя: под этими ключами уже лежат чужие грядки и счётчики
    ачивок. Опечатка здесь не падает, а тихо обнуляет людям прогресс."""
    assert farm_actions.plots_key(-100, 7) == "farm_plots:-100:7"
    assert farm_actions.counter_key(-100, 7, "plant") == "farm_count_plant:-100:7"
    assert farm_actions.counter_key(-100, 7, "harvest") == "farm_count_harvest:-100:7"


def test_общий_модуль_не_тянет_за_собой_бота():
    """farm_actions обязан оставаться импортируемым из панели: импортируй он
    bot.py, панель подняла бы второго бота на том же токене."""
    дерево = ast.parse((КОРЕНЬ / "farm_actions.py").read_text(encoding="utf-8"))
    импорты = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Import):
            импорты.update(a.name.split(".")[0] for a in узел.names)
        elif isinstance(узел, ast.ImportFrom) and узел.module:
            импорты.add(узел.module.split(".")[0])
    assert "bot" not in импорты
    assert "aiogram" not in импорты
