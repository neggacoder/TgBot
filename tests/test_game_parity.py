"""Одно действие — один результат, из чата и с сайта.

Главный риск этой работы: кто-нибудь однажды посчитает прямо в обработчике
бота, и правила раздвоятся. Разойдутся они молча — в чате одно, на сайте
другое, — и узнаем мы об этом от людей.
"""

from __future__ import annotations

import ast
import inspect
import os
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import game_actions  # noqa: E402

# Обработчики питомцев, которых в кабинете участника НЕТ — переносить их в
# game_actions незачем, а не забыли. Каждый — со своей причиной, а не общим
# «эти пока не трогали»: то же самое пришлось бы объяснять ревьюеру устно.
НЕ_В_КАБИНЕТЕ = {
    # Меняет облик питомца и тратит эликсир — такого действия на сайте нет.
    "cmd_pet_evolve",
    # Платная смена способности питомца — тоже вне кабинета.
    "cmd_pet_ability_reroll",
    # Статичная справка по номерам способностей, а не действие с питомцем.
    "cmd_pet_abilities_list",
    # Админская еженедельная раздача корма всем в чате — не действие участника
    # со своим питомцем.
    "cmd_pet_food_grant",
    # Админское удаление ВИДА из каталога чата — не про питомца участника.
    "cmd_pet_delete",
}


def _pet_handlers() -> dict[str, object]:
    """Все обработчики питомцев бота — cmd_pet_* и cmd_pets_* — находятся
    автоматически, а не рукописным списком: тот приходилось пополнять руками
    при каждом переносе, и забытая строка тихо переставала проверяться (см.
    progress.md). Теперь новый обработчик обязан либо звать game_actions,
    либо попасть в НЕ_В_КАБИНЕТЕ с причиной — иначе один из тестов ниже
    упадёт сам, без правки этого файла.
    """
    return {
        name: obj for name, obj in vars(bot_module).items()
        if re.match(r"^cmd_pets?_", name) and inspect.iscoroutinefunction(obj)
    }


_ОБНАРУЖЕННЫЕ = _pet_handlers()
ПЕРЕВЕДЁННЫЕ = sorted(set(_ОБНАРУЖЕННЫЕ) - НЕ_В_КАБИНЕТЕ)


def test_обработчиков_питомцев_нашлось_хоть_сколько_то():
    """Если regex вдруг перестанет находить обработчики (переименование
    команды, опечатка в префиксе), список опустеет, и все параметризованные
    проверки ниже станут пустыми — то есть будут молча всегда «зелёными».
    Явный порог не даёт сторожу тихо обнулиться."""
    assert len(_ОБНАРУЖЕННЫЕ) >= 10


def test_список_исключений_не_протух():
    """Каждое имя из НЕ_В_КАБИНЕТЕ обязано быть реальным обработчиком
    питомцев прямо сейчас — иначе исключение мертво и молчит о том, что
    обработчик переименовали, удалили, или что в список затесалось что-то
    постороннее."""
    пропавшие = НЕ_В_КАБИНЕТЕ - set(_ОБНАРУЖЕННЫЕ)
    assert not пропавшие, f"нет такого обработчика питомцев: {пропавшие}"


@pytest.mark.parametrize("handler", ПЕРЕВЕДЁННЫЕ)
def test_обработчик_зовёт_общий_модуль(handler):
    src = inspect.getsource(getattr(bot_module, handler))
    assert "game_actions." in src, (
        f"{handler} обязан звать game_actions, а не считать сам — или "
        f"объяснить в НЕ_В_КАБИНЕТЕ (tests/test_game_parity.py), почему нет")


@pytest.mark.parametrize("handler", ПЕРЕВЕДЁННЫЕ)
def test_переведённый_обработчик_не_считает_сам(handler):
    """У обёртки нет своей арифметики: разбор аргументов, вызов, ответ.
    Появились расчёты — значит правила раздвоились."""
    tree = ast.parse(inspect.getsource(getattr(bot_module, handler)))
    запретные = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "db"]
    assert not запретные, (
        f"{handler} ходит в базу напрямую — это работа game_actions")


def test_общий_модуль_не_знает_про_telegram():
    src = inspect.getsource(game_actions)
    for запрет in ("aiogram", "send_message", "import bot", "message."):
        assert запрет not in src, f"в game_actions просочилось «{запрет}»"


def test_разделитель_сводок_не_разъехался():
    """game_actions._DIVIDER — рукописная копия bot.DIVIDER (импортировать
    константу из bot.py нельзя по той же причине, по которой модуль вообще
    заводился). Копия строки может разойтись молча: ни один текстовый тест
    её не проверяет построчно, только по кускам вроде «2 из 3»."""
    assert bot_module.DIVIDER == game_actions._DIVIDER


def _game_actions_kwargs(handler) -> dict[str, str]:
    """Имена keyword-аргументов, переданных в вызовах game_actions.* внутри
    обработчика — по AST, а не по подстроке исходника: перенос вызова на
    несколько строк или лишний пробел вокруг «=» не должны ронять сторожа,
    который проверяет ровно то же самое по смыслу."""
    tree = ast.parse(inspect.getsource(handler))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "game_actions"):
            for kw in node.keywords:
                if kw.arg and isinstance(kw.value, ast.Name):
                    out[kw.arg] = kw.value.id
    return out


def test_покупка_и_продажа_питомца_передают_свою_заморозку():
    """buy_pet/sell_pet принимают заморозку и списание АРГУМЕНТОМ (см. их
    докстринги) — так у бота остаётся свой is_account_frozen/spend_coins со
    кэшем «+бесконечность», а не вторая копия проверки внутри game_actions.

    Без этого теста забытый аргумент не был бы замечен ничем: is_frozen молча
    подменился бы дефолтом game_actions (тоже честно ходит в базу — сетка
    тестов бота это не поймает, у неё «заморожен» проверяется подменой
    bot_module.is_account_frozen, а не строкой в БД), а без spend= владелец с
    «+бесконечность» стал бы платить за питомцев как все — тоже молча."""
    buy_kwargs = _game_actions_kwargs(bot_module.cmd_pet_buy)
    assert buy_kwargs.get("is_frozen") == "is_account_frozen"
    assert buy_kwargs.get("spend") == "spend_coins"
    sell_kwargs = _game_actions_kwargs(bot_module.cmd_pet_sell)
    assert sell_kwargs.get("is_frozen") == "is_account_frozen"
