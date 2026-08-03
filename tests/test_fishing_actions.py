"""Правила рыбалки вне телеграма: заброс, сетка, продажа.

Главное, что обязано совпадать с чатом до копейки: монеты рождаются при
ПРОДАЖЕ, а не при поимке. Поэтому и множитель «Клёва», и надбавка снастей
стоят на продаже — придержать улов выгодно, и в этом весь смысл сетки.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta

import pytest

import fishing
import fishing_actions


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    def __init__(self):
        self.coins = 0
        self.net: list[dict] = []
        self.seq = 0
        self.stats: dict = {}
        self.pinned = None
        self.earned = 0
        self.records: list = []
        self.effects: set[str] = set()

    async def get_fishing_stats(self, chat_id, user_id):
        return dict(self.stats)

    async def record_catch_weight(self, chat_id, user_id, grams, key, now):
        self.stats["last_fish_at"] = now
        self.stats["total_catches"] = int(self.stats.get("total_catches") or 0) + 1
        if grams > int(self.stats.get("best_weight") or 0):
            self.stats["best_weight"] = grams
        return dict(self.stats)

    async def record_catch_price(self, chat_id, user_id, price, name):
        self.records.append((price, name))

    async def list_net(self, chat_id, user_id):
        return [dict(f) for f in self.net]

    async def add_to_net(self, chat_id, user_id, key, grams, now):
        self.seq += 1
        self.net.append({"id": self.seq, "species_key": key, "grams": grams,
                         "caught_at": now})
        return self.seq

    async def remove_from_net(self, chat_id, user_id, fish_id):
        было = len(self.net)
        self.net = [f for f in self.net if f["id"] != fish_id]
        return len(self.net) != было

    async def get_profile_card(self, chat_id, user_id):
        return {"pinned_fish": self.pinned}

    async def set_pinned_fish(self, chat_id, user_id, fish_id):
        self.pinned = fish_id

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def touch_earning_activity(self, chat_id, user_id, kind, now, earned=0):
        self.earned += earned

    async def get_income_percent(self, chat_id, source):
        return 100

    async def consume_item_effect(self, chat_id, user_id, effect):
        if effect in self.effects:
            self.effects.discard(effect)
            return True
        return False

    async def list_inventory(self, chat_id, user_id):
        return []

    async def list_pets(self, chat_id, user_id):
        return []

    async def get_data(self, key):
        return None


CHAT, USER = -100, 7
ЩУКА = next(s for s in fishing.SPECIES if not s.is_junk)
ХЛАМ = next(s for s in fishing.SPECIES if s.is_junk)


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(fishing_actions, "db", world)
    monkeypatch.setattr(fishing_actions.farm_actions, "db", world)
    return world


@_sync
async def test_заброс_кладёт_рыбу_в_сетку(мир, monkeypatch):
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: ЩУКА)
    monkeypatch.setattr(fishing, "roll_grams", lambda s: s.max_grams)
    итог = await fishing_actions.cast(CHAT, USER)
    assert итог.ok and not итог.junk
    assert len(мир.net) == 1 and мир.net[0]["species_key"] == ЩУКА.key
    assert итог.coins == 0, "монеты у рыбалки рождаются при продаже, а не тут"


@_sync
async def test_хлам_платят_сразу_и_в_сетку_не_кладут(мир, monkeypatch):
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: ХЛАМ)
    monkeypatch.setattr(fishing, "roll_grams", lambda s: s.max_grams)
    итог = await fishing_actions.cast(CHAT, USER)
    assert итог.ok and итог.junk and итог.coins > 0
    assert not мир.net


@_sync
async def test_второй_заброс_упирается_в_кулдаун(мир, monkeypatch):
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: ЩУКА)
    await fishing_actions.cast(CHAT, USER)
    ещё = await fishing_actions.cast(CHAT, USER)
    assert not ещё.ok and ещё.next_at


@_sync
async def test_талисман_удваивает_вес_но_не_выше_видового(мир, monkeypatch):
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: ЩУКА)
    monkeypatch.setattr(fishing, "roll_grams", lambda s: s.min_grams)
    мир.effects.add("lucky")
    итог = await fishing_actions.cast(CHAT, USER)
    assert итог.grams <= ЩУКА.max_grams
    assert итог.grams >= ЩУКА.min_grams


@_sync
async def test_полная_сетка_выбрасывает_самую_дешёвую(мир, monkeypatch):
    мелкая = min((s for s in fishing.SPECIES if not s.is_junk),
                 key=lambda s: fishing.base_price(s, s.min_grams))
    крупная = max((s for s in fishing.SPECIES if not s.is_junk),
                  key=lambda s: fishing.base_price(s, s.max_grams))
    now = datetime.utcnow()
    for i in range(fishing_actions.NET_CAPACITY):
        await мир.add_to_net(CHAT, USER, мелкая.key, мелкая.min_grams, now)
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: крупная)
    monkeypatch.setattr(fishing, "roll_grams", lambda s: s.max_grams)
    итог = await fishing_actions.cast(CHAT, USER)
    assert итог.ok and итог.evicted
    assert len(мир.net) == fishing_actions.NET_CAPACITY


@_sync
async def test_самый_скромный_улов_отпускают(мир, monkeypatch):
    крупная = max((s for s in fishing.SPECIES if not s.is_junk),
                  key=lambda s: fishing.base_price(s, s.max_grams))
    мелкая = min((s for s in fishing.SPECIES if not s.is_junk),
                 key=lambda s: fishing.base_price(s, s.min_grams))
    now = datetime.utcnow()
    for i in range(fishing_actions.NET_CAPACITY):
        await мир.add_to_net(CHAT, USER, крупная.key, крупная.max_grams, now)
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: мелкая)
    monkeypatch.setattr(fishing, "roll_grams", lambda s: s.min_grams)
    итог = await fishing_actions.cast(CHAT, USER)
    assert итог.released and len(мир.net) == fishing_actions.NET_CAPACITY


@_sync
async def test_продажа_платит_и_чистит_сетку(мир):
    now = datetime.utcnow()
    await мир.add_to_net(CHAT, USER, ЩУКА.key, ЩУКА.max_grams, now)
    итог = await fishing_actions.sell(CHAT, USER)
    assert итог.ok and итог.sold == 1 and итог.coins > 0
    assert мир.coins == итог.coins and not мир.net


@_sync
async def test_закреплённый_трофей_не_продаётся(мир):
    now = datetime.utcnow()
    номер = await мир.add_to_net(CHAT, USER, ЩУКА.key, ЩУКА.max_grams, now)
    await fishing_actions.pin(CHAT, USER, номер)
    итог = await fishing_actions.sell(CHAT, USER)
    assert not итог.ok and len(мир.net) == 1
    одну = await fishing_actions.sell(CHAT, USER, номер)
    assert not одну.ok


@_sync
async def test_свежесть_снижает_цену(мир):
    старая = datetime.utcnow() - timedelta(hours=fishing.ROT_HOURS + 10)
    свежая = datetime.utcnow()
    строка_с = {"id": 1, "species_key": ЩУКА.key, "grams": ЩУКА.max_grams, "caught_at": свежая}
    строка_ст = {"id": 2, "species_key": ЩУКА.key, "grams": ЩУКА.max_grams, "caught_at": старая}
    _, цена_свежей, _ = fishing_actions.view(строка_с, datetime.utcnow())
    _, цена_старой, _ = fishing_actions.view(строка_ст, datetime.utcnow())
    assert цена_старой < цена_свежей


@_sync
async def test_выпустить_освобождает_место(мир):
    now = datetime.utcnow()
    номер = await мир.add_to_net(CHAT, USER, ЩУКА.key, ЩУКА.max_grams, now)
    итог = await fishing_actions.release(CHAT, USER, номер)
    assert итог.ok and not мир.net
    assert мир.coins == 0, "выпустить — не продать"


@_sync
async def test_состояние_описывает_сетку_и_ожидание(мир, monkeypatch):
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: ЩУКА)
    await fishing_actions.cast(CHAT, USER)
    итог = await fishing_actions.state(CHAT, USER)
    assert итог["capacity"] == fishing_actions.NET_CAPACITY
    assert len(итог["net"]) == 1
    assert итог["net"][0]["weight"] and итог["net"][0]["freshness"]
    assert итог["next_at"], "после заброса обязан быть виден срок следующего"
    assert итог["net_value"] == итог["net"][0]["price"]
    assert {s["key"] for s in итог["species"]} == set(fishing.BY_KEY)
