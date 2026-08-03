"""Заслоны против «несостыковок»: одно имя — одно определение, кнопка влезает
в лимит, длинный список не превращается в молчание.

Каждая проверка здесь появилась не из головы, а по найденному:

  * `_is_raid_command` в bot.py был объявлен ДВАЖДЫ. Второе определение молча
    затирало первое, и рубильник «Заработок» проверял команду одним правилом,
    а обработчик ловил другим.
  * `RP_ACTIONS` в панели — то же самое: рядом с полным каталогом лежал
    урезанный дубль без «verb» и «phrases», и панель писала в чат «подарить
    цветы» вместо «подарил(а) цветы».
  * `callback_data` у Telegram — 64 БАЙТА на всё. Ключ товара разрешался до 64
    символов, и «мой инвентарь» у владельца такого предмета не открывался
    вовсе: сервер отвергает клавиатуру целиком.
  * Сообщение длиннее 4096 Telegram тоже отвергает целиком — команда просто не
    отвечает. «Участники сообщения» это учитывали, «не в норме» — нет.
"""

from __future__ import annotations

import ast
import asyncio
import os
from collections import Counter

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

КОРЕНЬ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
МОДУЛИ = ["bot.py", "db.py", "relationships_v2.py", "game_actions.py", "shop_effects.py",
          "webpanel/app.py", "chat_events.py", "seasons.py", "farming.py", "pets.py"]


def _дерево(файл):
    return ast.parse(open(os.path.join(КОРЕНЬ, файл), encoding="utf-8").read())


# ---------------------------------------------------------------------------
# Одно имя — одно определение
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("файл", МОДУЛИ)
def test_нет_двух_определений_одной_функции(файл):
    """Второе определение молча затирает первое — и половина файла работает с
    одним поведением, половина с другим. Так жил `_is_raid_command`."""
    счёт, строки = Counter(), {}
    for node in _дерево(файл).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            счёт[node.name] += 1
            строки.setdefault(node.name, []).append(node.lineno)
    дубли = [f"{имя} (строки {строки[имя]})" for имя, n in счёт.items() if n > 1]
    assert not дубли, f"{файл}: определены дважды — " + "; ".join(дубли)


@pytest.mark.parametrize("файл", МОДУЛИ)
def test_каталоги_не_переопределяются(файл):
    """Про присвоения на верхнем уровне. Считаем только ПОЛНУЮ замену
    (`X = ...`): дописывание (`X = X + (...)`) — обычный приём в этом коде,
    им собираются каталоги предметов по веткам."""
    присвоения = {}
    for node in _дерево(файл).body:
        цель, значение = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            цель, значение = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            цель, значение = node.target.id, node.value
        if цель is None or not цель.isupper():
            continue
        # дописывание к себе же — не замена
        if any(isinstance(n, ast.Name) and n.id == цель for n in ast.walk(значение)):
            continue
        присвоения.setdefault(цель, []).append(node.lineno)
    дубли = [f"{имя} (строки {где})" for имя, где in присвоения.items() if len(где) > 1]
    assert not дубли, f"{файл}: каталог переопределён целиком — " + "; ".join(дубли)


# ---------------------------------------------------------------------------
# callback_data
# ---------------------------------------------------------------------------
def test_ключ_товара_влезает_в_кнопку():
    """Самый длинный разрешённый ключ + два id по 13 цифр обязаны влезть в 64
    байта, иначе карточка инвентаря не отправится целиком."""
    assert bot_module.SHOP_ITEM_KEY_MAX <= 24
    assert bot_module.shop_item_key_fits("a" * bot_module.SHOP_ITEM_KEY_MAX)
    assert not bot_module.shop_item_key_fits("a" * (bot_module.SHOP_ITEM_KEY_MAX + 1))


def test_кириллический_ключ_меряется_байтами():
    """Иначе админ заводит ключ, который проверку прошёл, а в кнопку не лезет —
    и карточка инвентаря у владельца предмета не открывается вовсе."""
    assert not bot_module.shop_item_key_fits("я" * bot_module.SHOP_ITEM_KEY_MAX)
    assert bot_module.shop_item_key_fits("я" * 10)


def test_карточка_инвентаря_переживает_длинный_ключ(monkeypatch):
    """Ключ длиннее лимита остался у старых чатов. Карточка обязана открыться —
    просто без кнопок у такого предмета."""
    длинный = "очень_длинный_ключ_предмета_из_старого_чата"

    async def list_inventory(chat_id, user_id):
        return [{"item_key": длинный, "quantity": 1, "used_count": 0}]

    async def get_shop_item(chat_id, item_key):
        return {"item_key": item_key, "name": "Штука", "emoji": "🎁", "price": 100}

    async def _ноль(*a, **k):
        return 0

    async def _имя(*a, **k):
        return "Тестер"

    monkeypatch.setattr(bot_module.db, "list_inventory", list_inventory, raising=False)
    monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item, raising=False)
    monkeypatch.setattr(bot_module.db, "get_item_usage_count", _ноль, raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _имя)

    текст, клавиатура = asyncio.run(bot_module._inventory_view(-100, 555, 555, 555))

    подписи = [b.text for ряд in клавиатура.inline_keyboard for b in ряд]
    assert not any("Закрепить" in c or "Продать" in c for c in подписи), подписи
    assert any("Назад" in c for c in подписи), "карточка должна остаться рабочей"


def test_callback_fits_считает_байты_а_не_символы():
    assert bot_module.callback_fits("a" * 64)
    assert not bot_module.callback_fits("a" * 65)
    assert not bot_module.callback_fits("я" * 33), "кириллица — по два байта"


# ---------------------------------------------------------------------------
# Длинные сообщения
# ---------------------------------------------------------------------------
def test_длинный_текст_режется_под_лимит():
    текст = "\n".join(f"строка {i}" for i in range(2000))
    итог = bot_module.clip_html_message(текст)

    assert len(итог) <= bot_module.TELEGRAM_TEXT_LIMIT
    assert "обрезано" in итог


def test_обрезка_закрывает_теги():
    """Оборванный <blockquote> или <b> — это второй отказ, теперь за разметку,
    то есть снова тишина в чате."""
    текст = "<blockquote expandable>" + "\n".join(
        f"<b>строка {i}</b> — текст" for i in range(500)) + "</blockquote>"

    итог = bot_module.clip_html_message(текст)

    assert len(итог) <= bot_module.TELEGRAM_TEXT_LIMIT
    открытые = bot_module._unclosed_tags(итог)
    assert открытые == [], f"остались незакрытыми: {открытые}"


def test_короткий_текст_не_трогаем():
    assert bot_module.clip_html_message("привет") == "привет"


def test_список_участников_режется_с_честным_остатком():
    строки = ["Заголовок", bot_module.DIVIDER] + [
        f"{i}. Участник с довольно длинным именем — {i}/100" for i in range(1, 301)]

    итог = bot_module.clip_member_list(строки, total=300)

    assert len(итог) <= bot_module.TELEGRAM_TEXT_LIMIT
    assert "Заголовок" in итог.split("\n")[0]
    assert f"…и ещё {300 - bot_module.LONG_LIST_HEAD}" in итог


def test_короткий_список_остаётся_целым():
    строки = ["Заголовок", bot_module.DIVIDER, "1. Кто-то — 5/100"]
    assert bot_module.clip_member_list(строки, total=1) == "\n".join(строки)
