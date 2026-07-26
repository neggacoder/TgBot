"""Ключи предметов — в <code>, чтобы их можно было скопировать нажатием.

Ключ («fishka», «korona») нужен человеку, чтобы написать «магазин купить
fishka», «использовать korona», «подарить cat». Пока он выводился обычным
текстом, его перенабирали руками, а промах в одной букве выглядел как
«такого товара нет». В Telegram текст в <code> копируется одним нажатием.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _message(text: str):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    return m, replies


# --- витрина магазина ------------------------------------------------------

def test_ключ_товара_в_code():
    line = bot_module.shop_item_line({
        "emoji": "🪙", "name": "Фишка", "item_key": "fishka",
        "price": 50, "stock": None, "description": "Красивая штука",
    })
    assert "<code>fishka</code>" in line


def test_ключ_не_теряется_у_товара_без_описания():
    line = bot_module.shop_item_line({
        "emoji": "👑", "name": "Корона", "item_key": "korona",
        "price": 500, "stock": 3, "description": None,
    })
    assert "<code>korona</code>" in line
    assert "осталось: 3" in line


def test_каждый_товар_по_умолчанию_показывает_свой_ключ():
    """Витрина — основное место, откуда ключ и копируют."""
    # Список живёт в db.py: в bot.py лежала его мёртвая копия, которую никто
    # не читал, — её удалили, чтобы товары не добавляли не в тот список.
    for item_key, name, price, description, emoji in bot_module.db.DEFAULT_SHOP_ITEMS:
        line = bot_module.shop_item_line({
            "emoji": emoji, "name": name, "item_key": item_key,
            "price": price, "stock": None, "description": description,
        })
        assert f"<code>{item_key}</code>" in line, item_key


def test_разметка_в_названии_товара_не_ломает_страницу():
    """Названия задают админы, и «<b>» в названии не должно превращаться
    в разметку — иначе Telegram отвергнет всё сообщение целиком."""
    line = bot_module.shop_item_line({
        "emoji": "🎁", "name": "<b>Хитрый</b>", "item_key": "a<b>c",
        "price": 10, "stock": None, "description": "<i>текст</i>",
    })
    assert "&lt;b&gt;Хитрый&lt;/b&gt;" in line
    assert "<code>a&lt;b&gt;c</code>" in line


# --- инвентарь -------------------------------------------------------------

@pytest.fixture
def inventory(monkeypatch):
    items = [
        {"item_key": "fishka", "name": "Фишка", "emoji": "🪙", "quantity": 2},
        {"item_key": "korona", "name": "Корона", "emoji": "👑", "quantity": 1},
    ]
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(items), raising=False)
    monkeypatch.setattr(bot_module.db, "get_item_usage_count", _returns(0), raising=False)
    monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"), raising=False)
    return items


def test_инвентарь_показывает_ключи(inventory):
    """Раньше инвентарь называл только предмет, и ключ приходилось искать
    в магазине — при том что переписывают его именно отсюда, в «использовать»,
    «подарить» и «магазин продать»."""
    msg, replies = _message("инвентарь")
    asyncio.run(bot_module.cmd_inventory(msg))
    assert "<code>fishka</code>" in replies[0]
    assert "<code>korona</code>" in replies[0]


def test_инвентарь_подсказывает_что_ключ_копируется(inventory):
    msg, replies = _message("инвентарь")
    asyncio.run(bot_module.cmd_inventory(msg))
    assert "скопируется" in replies[0]


def test_пустой_инвентарь_не_ломается(monkeypatch):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns([]), raising=False)
    monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"), raising=False)
    msg, replies = _message("инвентарь")
    asyncio.run(bot_module.cmd_inventory(msg))
    assert "пусто" in replies[0]
