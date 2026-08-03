"""Пополнение из панели в личке: то, что админ ввёл, должно появиться в чате.

Товары лавки живут в той же таблице, что и магазин, но показываются только с
сегодняшним rotation_day (см. db.list_rotation_items). Панель ставила один
лишь остаток — и «лавка» в чате не менялась вообще: позиции с вчерашним днём
там нет, сколько ей ни клади. Со стороны это выглядело как «пополняю из лички,
и ничего не происходит».
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import black_market as BM  # noqa: E402
import bot as bot_module  # noqa: E402

ЖАЛОБЫ = -1003673552861
СЕГОДНЯ = date(2026, 7, 31)
ТОВАР_ЛАВКИ = "binokl"
ТОВАР_МАГАЗИНА = "cake"


class ФейкСостояние:
    """FSMContext ровно в том объёме, в каком его трогает обработчик."""

    def __init__(self, data):
        self._data = dict(data)
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, state):
        self.state = state


class ФейкСообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("Chat", (), {"id": 555, "type": "private"})()
        self.from_user = type("User", (), {"id": 555, "is_bot": False, "first_name": "Админ"})()
        self.ответы: list[str] = []

    async def answer(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def стенд(monkeypatch):
    состояние = {"stock": {}, "rotation": {}}

    async def set_shop_item_stock(chat_id, item_key, stock):
        состояние["stock"][item_key] = stock
        return True

    async def set_shop_item_rotation(chat_id, item_key, stock, rotation_day):
        состояние["rotation"][item_key] = (stock, rotation_day)
        состояние["stock"][item_key] = stock
        return True

    async def get_shop_item(chat_id, item_key):
        return {"item_key": item_key, "name": "Товар", "emoji": "🎁",
                "price": 100, "is_active": True,
                "stock": состояние["stock"].get(item_key), "restock_max": 5}

    for имя, функция in (
        ("set_shop_item_stock", set_shop_item_stock),
        ("set_shop_item_rotation", set_shop_item_rotation),
        ("get_shop_item", get_shop_item),
    ):
        monkeypatch.setattr(bot_module.db, имя, функция, raising=False)

    monkeypatch.setattr(bot_module, "local_today", lambda: СЕГОДНЯ)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЖАЛОБЫ)
    return состояние


def _ввести_остаток(item_key, текст="7"):
    msg = ФейкСообщение(текст)
    state = ФейкСостояние({"shop_item_key": item_key})
    asyncio.run(bot_module.shop_item_stock_set(msg, state))
    return msg


def test_остаток_товара_лавки_попадает_в_сегодняшний_ассортимент(стенд):
    """Главная поломка: без rotation_day позиция не показывается в «лавке»,
    и пополнение из лички не меняло в чате ровно ничего."""
    _ввести_остаток(ТОВАР_ЛАВКИ)
    assert ТОВАР_ЛАВКИ in стенд["rotation"], "товар лавки не выставлен в ассортимент дня"
    запас, день = стенд["rotation"][ТОВАР_ЛАВКИ]
    assert (запас, день) == (7, СЕГОДНЯ)


def test_обычному_товару_ротация_не_нужна(стенд):
    """Магазин показывает товар без всякого rotation_day — трогать его значило
    бы затащить обычный товар в лавку."""
    _ввести_остаток(ТОВАР_МАГАЗИНА)
    assert стенд["rotation"] == {}
    assert стенд["stock"][ТОВАР_МАГАЗИНА] == 7


def test_админу_сказано_что_запас_лавки_живёт_до_конца_суток(стенд):
    """Ротация обнулит его ночью — это устройство лавки, а не поломка. Не
    сказать об этом значит получить тот же вопрос завтра."""
    msg = _ввести_остаток(ТОВАР_ЛАВКИ)
    assert any("конца суток" in ответ.lower() for ответ in msg.ответы), msg.ответы


def test_карточка_товара_лавки_не_обещает_ежедневный_завоз(стенд, monkeypatch):
    """list_shop_items_for_restock исключает товары лавки намеренно, поэтому
    «до N шт./день» на их карточке — неправда."""
    подпись = bot_module.shop_item_restock_line(
        {"item_key": ТОВАР_ЛАВКИ, "restock_max": 5}
    )
    assert "день" not in подпись.lower(), подпись
    assert "лавк" in подпись.lower(), подпись


def test_карточка_обычного_товара_называет_настоящий_час_завоза(стенд):
    """Раньше стояло «15:00 UTC», а цикл считает час по зоне чата
    (local_now). Человек ждал завоза не тогда, когда он приходит."""
    подпись = bot_module.shop_item_restock_line(
        {"item_key": ТОВАР_МАГАЗИНА, "restock_max": 5}
    )
    assert str(bot_module.SHOP_RESTOCK_HOUR_LOCAL) in подпись
    assert "utc" not in подпись.lower(), подпись


# ---------------------------------------------------------------------------
# Пути, где панель по-прежнему говорила «готово», не меняя ничего
# ---------------------------------------------------------------------------

def test_безлимит_товару_лавки_не_даётся(стенд):
    """«Без лимита» — это stock = NULL: ни ротации, ни дефицита. Раньше панель
    молча принимала его и товар оставался невидимым в лавке — ровно та же
    жалоба «пополняю с лички, ничего не меняется»."""
    msg = _ввести_остаток(ТОВАР_ЛАВКИ, bot_module.BTN_SHOP_UNLIMITED)
    assert стенд["rotation"] == {}
    assert ТОВАР_ЛАВКИ not in стенд["stock"], "безлимит не должен записываться"
    assert any("лавк" in о.lower() for о in msg.ответы), msg.ответы


def test_обычному_товару_безлимит_по_прежнему_можно(стенд):
    msg = _ввести_остаток(ТОВАР_МАГАЗИНА, bot_module.BTN_SHOP_UNLIMITED)
    assert ТОВАР_МАГАЗИНА in стенд["stock"]
    assert стенд["stock"][ТОВАР_МАГАЗИНА] is None
    assert any("остаток обновлён" in о.lower() for о in msg.ответы), msg.ответы


def _открыть_пополнение(item_key):
    msg = ФейкСообщение("🔁 Пополнение")
    state = ФейкСостояние({"shop_item_key": item_key})
    asyncio.run(bot_module.shop_item_restock_start(msg, state))
    return msg, state


def test_ежедневный_завоз_товару_лавки_не_настраивается(стенд):
    """list_shop_items_for_restock исключает товары лавки намеренно. Панель
    же принимала число и отвечала «✅ до N шт./день» — про то, чего не будет."""
    msg, state = _открыть_пополнение(ТОВАР_ЛАВКИ)
    assert state.state is None, "в ввод числа заходить не за чем"
    assert any("лавк" in о.lower() for о in msg.ответы), msg.ответы


def test_ежедневный_завоз_обычному_товару_настраивается(стенд):
    msg, state = _открыть_пополнение(ТОВАР_МАГАЗИНА)
    assert state.state is not None, "обычный товар настраивается как раньше"


def test_приглашение_к_вводу_называет_настоящий_час(стенд):
    """Соседняя строка с карточкой годами обещала «15:00 (UTC)», хотя цикл
    считает час по зоне чата."""
    msg, _ = _открыть_пополнение(ТОВАР_МАГАЗИНА)
    текст = " ".join(msg.ответы)
    assert "utc" not in текст.lower(), текст
    assert str(bot_module.SHOP_RESTOCK_HOUR_LOCAL) in текст, текст
