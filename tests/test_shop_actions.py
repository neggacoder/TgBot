"""Магазин и инвентарь вне телеграма.

Самое дорогое здесь — цена: она складывается из четырёх слоёв (распродажа чата,
питомец, снаряжение, и только потом «сколько влезет на все деньги»), и порядок
у них значащий.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import date

import pytest

import shop_actions


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


КЛЮЧ = "zelie"
СЕГОДНЯ = date(2026, 8, 2)


class _World:
    def __init__(self, coins=10_000):
        self.coins = coins
        self.товары = {KEY: {"item_key": KEY, "name": "Зелье", "emoji": "🧪",
                             "price": 500, "is_active": 1, "stock": 10,
                             "description": "проверочное"}
                       for KEY in (КЛЮЧ,)}
        self.инвентарь: dict[str, int] = {}
        self.pinned = None

    async def get_shop_item(self, chat_id, key):
        товар = self.товары.get(key)
        return dict(товар) if товар else None

    async def list_shop_items(self, chat_id, active_only=True):
        return [dict(t) for t in self.товары.values()]

    async def list_rotation_items(self, chat_id, keys, day):
        return []

    async def try_take_shop_stock(self, chat_id, key, qty):
        товар = self.товары.get(key)
        if товар is None or товар["stock"] is None:
            return True
        if товар["stock"] < qty:
            return False
        товар["stock"] -= qty
        return True

    async def return_shop_stock(self, chat_id, key, qty):
        товар = self.товары.get(key)
        if товар and товар["stock"] is not None:
            товар["stock"] += qty

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def add_inventory_item(self, chat_id, user_id, key, amount=1):
        self.инвентарь[key] = self.инвентарь.get(key, 0) + amount

    async def remove_inventory_item(self, chat_id, user_id, key, amount=1):
        if self.инвентарь.get(key, 0) < amount:
            return False
        self.инвентарь[key] -= amount
        if self.инвентарь[key] <= 0:
            del self.инвентарь[key]
        return True

    async def list_inventory(self, chat_id, user_id):
        return [{"item_key": k, "quantity": v} for k, v in self.инвентарь.items()]

    async def get_profile_card(self, chat_id, user_id):
        return {"pinned_item": self.pinned}

    async def set_pinned_item(self, chat_id, user_id, key):
        self.pinned = key

    async def list_pets(self, chat_id, user_id):
        return []

    async def get_data(self, key):
        return None


CHAT, USER = -100, 7


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(shop_actions, "db", world)
    monkeypatch.setattr(shop_actions.farm_actions, "db", world)
    return world


# --- покупка ----------------------------------------------------------------

@_sync
async def test_покупка_списывает_и_кладёт_в_инвентарь(мир):
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, 2, today=СЕГОДНЯ)
    assert итог.ok and итог.qty == 2 and итог.total == 1000
    assert мир.coins == 9000 and мир.инвентарь[КЛЮЧ] == 2
    assert мир.товары[КЛЮЧ]["stock"] == 8


@_sync
async def test_без_денег_остаток_возвращается_на_полку(мир):
    """Остаток снимается ДО списания. Не вернуть его — и товар исчезал бы из
    магазина от каждой неудачной попытки купить."""
    мир.coins = 100
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    assert not итог.ok
    assert мир.товары[КЛЮЧ]["stock"] == 10 and not мир.инвентарь


@_sync
async def test_все_упирается_в_деньги_и_остаток(мир):
    мир.coins = 1600            # хватает на 3
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, "все", today=СЕГОДНЯ)
    assert итог.qty == 3 and мир.coins == 100

    мир.coins = 100_000
    мир.товары[КЛЮЧ]["stock"] = 2
    ещё = await shop_actions.buy(CHAT, USER, КЛЮЧ, "все", today=СЕГОДНЯ)
    assert ещё.qty == 2, "«все» обязано упереться в остаток на полке"


@_sync
async def test_на_одну_не_хватает_это_слова_а_не_ноль(мир):
    """«Куплено 0 шт.» человек прочитал бы как поломку."""
    мир.coins = 10
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, "все", today=СЕГОДНЯ)
    assert not итог.ok and "не хватает" in итог.error


@_sync
async def test_распроданный_не_купить(мир):
    мир.товары[КЛЮЧ]["stock"] = 0
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    assert not итог.ok and "раскуплен" in итог.error


@_sync
async def test_больше_ста_за_раз_нельзя(мир):
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, shop_actions.BUY_MAX_QTY + 1,
                                  today=СЕГОДНЯ)
    assert not итог.ok


@_sync
async def test_распродажа_снижает_цену_а_ценник_нет(мир, monkeypatch):
    async def половина(chat_id):
        return 0.5
    monkeypatch.setattr(shop_actions, "event_multiplier", половина)
    итог = await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    assert итог.ok and итог.price == 250 and итог.sale
    assert итог.base_price == 500, "ценник в магазине не переписывается"


@_sync
async def test_скидки_складываются_после_события(мир, monkeypatch):
    """Порядок слоёв: событие множит базу, личные скидки режут результат."""
    async def половина(chat_id):
        return 0.5
    async def торгаш(chat_id, user_id, ability):
        return 20
    monkeypatch.setattr(shop_actions, "event_multiplier", половина)
    monkeypatch.setattr(shop_actions.game_actions, "_pet_bonus", торгаш)
    цена, скидка, распродажа = await shop_actions.price_for(CHAT, USER, 500)
    assert цена == 200 and скидка == 20 and распродажа   # 500→250→200


# --- продажа ----------------------------------------------------------------

@_sync
async def test_продажа_возвращает_восемьдесят_процентов(мир):
    await shop_actions.buy(CHAT, USER, КЛЮЧ, 2, today=СЕГОДНЯ)
    было = мир.coins
    итог = await shop_actions.sell(CHAT, USER, КЛЮЧ, 2)
    assert итог.ok and итог.total == int(500 * 2 * 0.8)
    assert мир.coins == было + итог.total and not мир.инвентарь


@_sync
async def test_продать_больше_чем_есть_нельзя(мир):
    await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    итог = await shop_actions.sell(CHAT, USER, КЛЮЧ, 5)
    assert not итог.ok and мир.инвентарь[КЛЮЧ] == 1


@_sync
async def test_продажа_всё_забирает_весь_запас(мир):
    await shop_actions.buy(CHAT, USER, КЛЮЧ, 3, today=СЕГОДНЯ)
    итог = await shop_actions.sell(CHAT, USER, КЛЮЧ, "все")
    assert итог.ok and итог.qty == 3 and not мир.инвентарь


@_sync
async def test_проданный_предмет_снимается_с_закрепа(мир):
    """Закреплённый в профиле предмет, которого больше нет, — пустая рамка."""
    await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    мир.pinned = КЛЮЧ
    await shop_actions.sell(CHAT, USER, КЛЮЧ, 1)
    assert мир.pinned is None


# --- витрина ----------------------------------------------------------------

@_sync
async def test_состояние_описывает_витрину_и_инвентарь(мир):
    await shop_actions.buy(CHAT, USER, КЛЮЧ, 1, today=СЕГОДНЯ)
    итог = await shop_actions.state(CHAT, USER, today=СЕГОДНЯ)
    товар = итог["items"][0]
    assert товар["key"] == КЛЮЧ and товар["price"] == 500
    assert товар["affordable"] is True and товар["stock"] == 9
    свой = итог["inventory"][0]
    assert свой["quantity"] == 1 and свой["sell_price"] == 400 and свой["sellable"]
    assert итог["sell_percent"] == shop_actions.SELL_PERCENT
