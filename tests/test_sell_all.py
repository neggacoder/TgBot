"""«магазин продать {ключ} все» — как и «купить … все».

У покупки количество разбиралось как ЛЮБОЙ токен, и слово «все» доезжало до
кода, где известны все ограничители. У продажи в регулярке стояло `\\d+` —
цифры и только цифры, — поэтому «магазин продать bronik все» не совпадало с
командой вовсе: бот уходил в общую подсказку по магазину, будто такой команды
нет. Ни ошибки, ни продажи.

Здесь проверяется и разбор («все» = сколько лежит в инвентаре), и то, что
остальные отказы продажи никуда не делись: награда, не свой предмет, мусор
вместо числа. Запрет на продажу УЖЕ ИСПОЛЬЗОВАННОГО предмета снят отдельным
решением владельца — на это тоже есть проверка, чтобы он не вернулся молча.
"""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЧАТ = -1003673552861
ЧЕЛОВЕК = 555
КЛЮЧ = "bronik"
ЦЕНА = 100


class _Сообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": ЧАТ, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": ЧЕЛОВЕК, "is_bot": False, "full_name": "Тестер"})()
        self.ответы: list[str] = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def стенд(monkeypatch):
    состояние = {"quantity": 7, "used": 0, "продано": [], "начислено": [], "цена": ЦЕНА}

    async def list_inventory(chat_id, user_id):
        if состояние["quantity"] <= 0:
            return []
        return [{"item_key": КЛЮЧ, "quantity": состояние["quantity"], "name": "Бронежилет"}]

    async def get_item_usage_count(chat_id, user_id, item_key):
        return состояние["used"]

    async def get_shop_item(chat_id, item_key):
        if состояние["цена"] is None:
            return {"item_key": item_key, "name": "Бронежилет", "emoji": "🦺", "price": None}
        return {"item_key": item_key, "name": "Бронежилет", "emoji": "🦺",
                "price": состояние["цена"]}

    async def remove_inventory_item(chat_id, user_id, item_key, amount):
        состояние["продано"].append(amount)
        состояние["quantity"] -= amount
        return True

    async def add_coins(chat_id, user_id, amount, *a, **k):
        состояние["начислено"].append(amount)

    async def _none(*a, **k):
        return None

    for имя, fn in [("list_inventory", list_inventory),
                    ("get_item_usage_count", get_item_usage_count),
                    ("get_shop_item", get_shop_item),
                    ("remove_inventory_item", remove_inventory_item),
                    ("add_coins", add_coins),
                    ("get_profile_card", _none),
                    ("set_pinned_item", _none),
                    ("add_log", _none)]:
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    return состояние


def _продать(текст):
    msg = _Сообщение(текст)
    asyncio.run(bot_module.cmd_sell_item(msg))
    return msg.ответы


# ---------------------------------------------------------------------------
# Разбор команды
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("текст", [
    f"магазин продать {КЛЮЧ} все",
    f"магазин продать {КЛЮЧ} всё",
    f"магазин продать {КЛЮЧ} ВСЕ",
    f"!продать {КЛЮЧ} все",
])
def test_команда_с_словом_все_вообще_опознаётся(текст):
    """Пока в регулярке стояло `\\d+`, такая строка не была командой: бот
    отвечал общей подсказкой по магазину, будто её не существует."""
    assert bot_module.SELL_ITEM_RE.match(текст) is not None


def test_продать_все_продаёт_весь_запас(стенд):
    ответы = _продать(f"магазин продать {КЛЮЧ} все")

    assert стенд["продано"] == [7]
    assert стенд["начислено"] == [int(ЦЕНА * 7 * 0.8)]
    assert "× 7" in ответы[0]


def test_число_работает_как_раньше(стенд):
    _продать(f"магазин продать {КЛЮЧ} 3")

    assert стенд["продано"] == [3]
    assert стенд["начислено"] == [int(ЦЕНА * 3 * 0.8)]


def test_без_количества_продаётся_одна(стенд):
    _продать(f"магазин продать {КЛЮЧ}")

    assert стенд["продано"] == [1]


def test_мусор_вместо_числа_объясняется(стенд):
    """Раньше такая строка просто не была командой. Теперь она командой стала,
    и на неё нужен внятный ответ, а не молчание."""
    ответы = _продать(f"магазин продать {КЛЮЧ} побольше")

    assert стенд["продано"] == []
    assert "число или слово «все»" in ответы[0]


# ---------------------------------------------------------------------------
# Отказы продажи не должны были пострадать
# ---------------------------------------------------------------------------
def test_использованный_предмет_теперь_продаётся(стенд):
    """Запрет «этот предмет уже был в использовании» снят по решению
    владельца: продаётся всё, что лежит в инвентаре, по той же цене в 80%."""
    стенд["used"] = 3
    ответы = _продать(f"магазин продать {КЛЮЧ} все")

    assert стенд["продано"] == [7]
    assert стенд["начислено"] == [int(ЦЕНА * 7 * 0.8)]
    assert "использовани" not in " ".join(ответы)


def test_нет_предмета_нет_продажи(стенд):
    стенд["quantity"] = 0
    ответы = _продать(f"магазин продать {КЛЮЧ} все")

    assert стенд["продано"] == []
    assert "нет предмета" in ответы[0]


def test_непродаваемый_товар_остаётся_непродаваемым(стенд):
    стенд["цена"] = None
    ответы = _продать(f"магазин продать {КЛЮЧ} все")

    assert стенд["продано"] == []
    assert "нельзя продать" in ответы[0]


def test_награду_не_продать(стенд, monkeypatch):
    monkeypatch.setattr(bot_module.shop_effects, "is_reward", lambda key: True)
    ответы = _продать(f"магазин продать {КЛЮЧ} все")

    assert стенд["продано"] == []
    assert "Награды не продаются" in ответы[0]


def test_больше_чем_есть_не_продать(стенд):
    ответы = _продать(f"магазин продать {КЛЮЧ} 100")

    assert стенд["продано"] == []
    assert "только 7" in ответы[0]
