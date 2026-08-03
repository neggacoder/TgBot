"""Хлев: скот покупается и продаётся пачками — «ферма купить корова 3».

Раньше вид держали строго по одному, и это было осознанным решением («пять
коров — просто ×5 к молоку»). Владелец решил иначе, поэтому здесь проверяется
не только разбор количества, но и то, что стадо реально работает как стадо:
три коровы дают втрое больше молока и упираются во втрое больший потолок.
Иначе покупка второй головы была бы обманом.

Отдельная забота — деньги: списываем за всё поголовье сразу, а если между
проверкой и покупкой кто-то занял место, разницу возвращаем.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import livestock  # noqa: E402

ЧАТ = -1003673552861
ЧЕЛОВЕК = 555
КОРОВА = livestock.BY_KEY["korova"]


class _Сообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": ЧАТ, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": ЧЕЛОВЕК, "is_bot": False, "full_name": "Тестер"})()
        self.ответы: list[str] = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)

    async def answer(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def хлев(monkeypatch):
    состояние = {
        "монеты": 100_000,
        "поголовье": {},                 # ключ → сколько
        "last_collect": {},              # ключ → когда забирали
        "инвентарь": [],                 # (item_key, сколько)
        "потолок": livestock.MAX_PER_KIND,
    }

    async def get_wallet(chat_id, user_id):
        return {"coins": состояние["монеты"]}

    async def spend_coins(chat_id, user_id, amount, *a, **k):
        if состояние["монеты"] < amount:
            return False
        состояние["монеты"] -= amount
        return True

    async def add_coins(chat_id, user_id, amount, *a, **k):
        состояние["монеты"] += amount

    async def get_farm_animal_quantity(chat_id, user_id, key):
        return состояние["поголовье"].get(key, 0)

    async def add_farm_animals(chat_id, user_id, key, now, quantity=1, max_per_kind=1):
        было = состояние["поголовье"].get(key, 0)
        стало = min(было + quantity, max_per_kind)
        состояние["поголовье"][key] = стало
        состояние["last_collect"][key] = now
        return стало - было

    async def remove_farm_animals(chat_id, user_id, key, quantity=1):
        было = состояние["поголовье"].get(key, 0)
        убрано = min(было, quantity)
        состояние["поголовье"][key] = было - убрано
        if not состояние["поголовье"][key]:
            состояние["поголовье"].pop(key, None)
        return убрано

    async def list_farm_animals(chat_id, user_id):
        return [
            {"animal_key": k, "quantity": n,
             "bought_at": состояние["last_collect"].get(k),
             "last_collect_at": состояние["last_collect"].get(k)}
            for k, n in состояние["поголовье"].items()
        ]

    async def add_inventory_item(chat_id, user_id, item_key, amount):
        состояние["инвентарь"].append((item_key, amount))

    async def _none(*a, **k):
        return None

    async def _false(*a, **k):
        return False

    for имя, fn in [("get_wallet", get_wallet), ("add_coins", add_coins),
                    ("get_farm_animal_quantity", get_farm_animal_quantity),
                    ("add_farm_animals", add_farm_animals),
                    ("remove_farm_animals", remove_farm_animals),
                    ("list_farm_animals", list_farm_animals),
                    ("add_inventory_item", add_inventory_item),
                    ("seed_extra_shop_items", _none), ("touch_farm_animals", _none),
                    ("add_log", _none)]:
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    monkeypatch.setattr(bot_module, "spend_coins", spend_coins)
    monkeypatch.setattr(bot_module, "is_account_frozen", _false)
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    async def подсказка(*a, **k):
        return ""            # настоящая activity_hint возвращает строку

    monkeypatch.setattr(bot_module, "activity_hint", подсказка)
    return состояние


def _купить(текст):
    msg = _Сообщение(текст)
    asyncio.run(bot_module.cmd_barn_buy(msg))
    return msg.ответы


def _продать(текст):
    msg = _Сообщение(текст)
    asyncio.run(bot_module.cmd_barn_sell(msg))
    return msg.ответы


# ---------------------------------------------------------------------------
# Покупка
# ---------------------------------------------------------------------------
def test_можно_купить_сразу_три(хлев):
    ответы = _купить("ферма купить корова 3")

    assert хлев["поголовье"]["korova"] == 3
    assert хлев["монеты"] == 100_000 - КОРОВА.price * 3
    assert "× 3" in ответы[0]


def test_без_числа_покупается_одна(хлев):
    _купить("ферма купить корова")
    assert хлев["поголовье"]["korova"] == 1


def test_докупить_к_имеющимся_можно(хлев):
    _купить("ферма купить корова 2")
    _купить("ферма купить корова 2")

    assert хлев["поголовье"]["korova"] == 4


def test_все_берёт_сколько_хватает_монет(хлев):
    хлев["монеты"] = КОРОВА.price * 2 + 10

    _купить("ферма купить корова все")

    assert хлев["поголовье"]["korova"] == 2
    assert хлев["монеты"] == 10


def test_все_не_превышает_потолок(хлев):
    _купить("ферма купить корова все")

    assert хлев["поголовье"]["korova"] == livestock.MAX_PER_KIND


def test_выше_потолка_не_продают(хлев):
    хлев["поголовье"]["korova"] = livestock.MAX_PER_KIND

    ответы = _купить("ферма купить корова 1")

    assert хлев["поголовье"]["korova"] == livestock.MAX_PER_KIND
    assert str(livestock.MAX_PER_KIND) in ответы[0]


def test_просьба_больше_остатка_объясняется(хлев):
    хлев["поголовье"]["korova"] = livestock.MAX_PER_KIND - 1

    ответы = _купить("ферма купить корова 5")

    assert хлев["поголовье"]["korova"] == livestock.MAX_PER_KIND - 1
    assert "ещё 1" in ответы[0]
    assert хлев["монеты"] == 100_000, "деньги не должны были уйти"


def test_не_хватает_монет_на_пачку(хлев):
    хлев["монеты"] = КОРОВА.price * 2

    ответы = _купить("ферма купить корова 3")

    assert "korova" not in хлев["поголовье"]
    assert хлев["монеты"] == КОРОВА.price * 2
    assert "Недостаточно" in ответы[0]


def test_мусор_вместо_числа_объясняется(хлев):
    ответы = _купить("ферма купить корова три")

    assert "korova" not in хлев["поголовье"]
    assert "число или слово «все»" in ответы[0]


def test_деньги_возвращаются_за_неполученных(хлев, monkeypatch):
    """Между проверкой места и покупкой могла пройти вторая команда. База
    отдаёт ровно столько голов, сколько влезло, — за остальных возвращаем."""
    async def жадный_add(chat_id, user_id, key, now, quantity=1, max_per_kind=1):
        хлев["поголовье"][key] = хлев["поголовье"].get(key, 0) + 1
        return 1                      # влезла только одна

    monkeypatch.setattr(bot_module.db, "add_farm_animals", жадный_add, raising=False)

    _купить("ферма купить корова 3")

    assert хлев["монеты"] == 100_000 - КОРОВА.price, "вернули за двух неполученных"


# ---------------------------------------------------------------------------
# Стадо работает как стадо
# ---------------------------------------------------------------------------
def test_три_коровы_дают_втрое_больше(хлев):
    прошло = datetime.utcnow() - timedelta(hours=КОРОВА.cycle_hours)

    одна = livestock.produced(КОРОВА, прошло, datetime.utcnow(), 1)
    три = livestock.produced(КОРОВА, прошло, datetime.utcnow(), 3)

    assert одна == КОРОВА.per_cycle
    assert три == КОРОВА.per_cycle * 3


def test_потолок_растёт_вместе_со_стадом():
    assert livestock.total_cap(КОРОВА, 3) == КОРОВА.cap * 3
    давно = datetime.utcnow() - timedelta(days=30)
    assert livestock.produced(КОРОВА, давно, datetime.utcnow(), 3) == КОРОВА.cap * 3


def test_сбор_учитывает_поголовье(хлев):
    хлев["поголовье"]["korova"] = 3
    хлев["last_collect"]["korova"] = datetime.utcnow() - timedelta(hours=КОРОВА.cycle_hours)

    asyncio.run(bot_module._collect_barn(ЧАТ, ЧЕЛОВЕК, datetime.utcnow()))

    assert хлев["инвентарь"] == [(КОРОВА.item_key, КОРОВА.per_cycle * 3)]


def test_покупка_сначала_забирает_накопленное(хлев):
    """last_collect_at у вида один на всех: не забери мы продукт до покупки,
    новые головы надоили бы за время, когда их ещё не было."""
    хлев["поголовье"]["korova"] = 1
    хлев["last_collect"]["korova"] = datetime.utcnow() - timedelta(hours=КОРОВА.cycle_hours)

    _купить("ферма купить корова 2")

    assert хлев["инвентарь"] == [(КОРОВА.item_key, КОРОВА.per_cycle)], (
        "забрать надо было ровно за одну голову, что была до покупки"
    )


# ---------------------------------------------------------------------------
# Продажа
# ---------------------------------------------------------------------------
def test_продать_несколько_голов(хлев):
    хлев["поголовье"]["korova"] = 4
    хлев["last_collect"]["korova"] = datetime.utcnow()
    было = хлев["монеты"]

    ответы = _продать("ферма продать корова 3")

    assert хлев["поголовье"]["korova"] == 1
    assert хлев["монеты"] == было + livestock.sell_back(КОРОВА) * 3
    assert "Осталось голов: 1" in ответы[0]


def test_продать_все(хлев):
    хлев["поголовье"]["korova"] = 3
    хлев["last_collect"]["korova"] = datetime.utcnow()

    _продать("ферма продать корова все")

    assert "korova" not in хлев["поголовье"]


def test_без_числа_продаётся_одна(хлев):
    хлев["поголовье"]["korova"] = 3
    хлев["last_collect"]["korova"] = datetime.utcnow()

    _продать("ферма продать корова")

    assert хлев["поголовье"]["korova"] == 2


def test_продать_больше_чем_есть_нельзя(хлев):
    хлев["поголовье"]["korova"] = 2
    хлев["last_collect"]["korova"] = datetime.utcnow()
    было = хлев["монеты"]

    ответы = _продать("ферма продать корова 5")

    assert хлев["поголовье"]["korova"] == 2
    assert хлев["монеты"] == было
    assert "У вас 2" in ответы[0]


def test_продать_то_чего_нет(хлев):
    ответы = _продать("ферма продать корова все")

    assert "и нет" in ответы[0]
