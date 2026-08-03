"""Правила фермы вне телеграма: посадить, собрать, докупить, завести скот.

Эти функции зовёт сайт, и у него нет ни команд, ни сообщений — только результат
и состояние. Поэтому здесь всё гоняется напрямую, с заглушкой базы вместо
настоящей: проверяется, что действие меняет мир так, как обещает, и что отказ
остаётся отказом, а не наполовину случившимся действием.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta

import pytest

import farm_actions
import farming
import livestock


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает ферма."""

    def __init__(self, coins=1_000_000, total_farms=50):
        self.coins = coins
        self.total_farms = total_farms
        self.plots: list[dict] = []
        self.animals: list[dict] = []
        self.inventory: dict[str, int] = {}
        self.data: dict[str, str] = {}
        self.achievements: set[str] = set()

    # key-value
    async def get_data(self, key):
        return {"data_value": self.data[key]} if key in self.data else None

    async def set_data(self, key, value, updated_by=None):
        self.data[key] = str(value)

    async def delete_data(self, key):
        self.data.pop(key, None)

    # кошелёк
    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins, "total_farms": self.total_farms}

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    # грядки
    async def list_farm_plots(self, chat_id, user_id):
        return [dict(p) for p in sorted(self.plots, key=lambda p: p["slot"])]

    async def plant_farm_crop(self, chat_id, user_id, slot, crop_key,
                              planted_at, ready_at, pest_at):
        if any(p["slot"] == slot for p in self.plots):
            return False
        self.plots.append({"slot": slot, "crop_key": crop_key,
                           "planted_at": planted_at, "ready_at": ready_at,
                           "pest_at": pest_at})
        return True

    async def clear_farm_plot(self, chat_id, user_id, slot):
        было = len(self.plots)
        self.plots = [p for p in self.plots if p["slot"] != slot]
        return len(self.plots) != было

    # хлев
    async def list_farm_animals(self, chat_id, user_id):
        return [dict(a) for a in self.animals]

    async def get_farm_animal_quantity(self, chat_id, user_id, key):
        for a in self.animals:
            if a["animal_key"] == key:
                return int(a["quantity"])
        return 0

    async def add_farm_animals(self, chat_id, user_id, key, now, quantity=1,
                               max_per_kind=10):
        for a in self.animals:
            if a["animal_key"] == key:
                можно = max(0, max_per_kind - int(a["quantity"]))
                добавлено = min(quantity, можно)
                a["quantity"] += добавлено
                return добавлено
        добавлено = min(quantity, max_per_kind)
        self.animals.append({"animal_key": key, "quantity": добавлено,
                             "last_collect_at": now})
        return добавлено

    async def remove_farm_animals(self, chat_id, user_id, key, quantity):
        for a in self.animals:
            if a["animal_key"] == key:
                убрано = min(quantity, int(a["quantity"]))
                a["quantity"] -= убрано
                if a["quantity"] <= 0:
                    self.animals.remove(a)
                return убрано
        return 0

    async def touch_farm_animals(self, chat_id, user_id, keys, now):
        for a in self.animals:
            if a["animal_key"] in keys:
                a["last_collect_at"] = now

    # инвентарь и прочее
    async def add_inventory_item(self, chat_id, user_id, item_key, amount=1):
        self.inventory[item_key] = self.inventory.get(item_key, 0) + amount

    async def list_inventory(self, chat_id, user_id):
        return [{"item_key": k, "quantity": v} for k, v in self.inventory.items()]

    async def seed_extra_shop_items(self, chat_id, items, is_active=True):
        return 0

    async def list_pets(self, chat_id, user_id):
        return []

    async def grant_achievement(self, chat_id, user_id, code):
        новое = code not in self.achievements
        self.achievements.add(code)
        return новое


CHAT, USER = -100, 7


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(farm_actions, "db", world)
    return world


# --- посадка ----------------------------------------------------------------

@_sync
async def test_посадка_занимает_грядку_и_списывает_монеты(мир):
    было = мир.coins
    итог = await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50)
    assert итог.ok and итог.planted == 1
    assert len(мир.plots) == 1
    assert мир.coins == было - farming.BY_KEY["kartoshka"].seed_price
    assert итог.ready_at > datetime.utcnow()


@_sync
async def test_посадка_всё_поле_занимает_все_свободные(мир):
    """Кнопка «Всё поле» шлёт слово, а не число, — ровно как команда в чате."""
    итог = await farm_actions.plant(CHAT, USER, "картошка", "все",
                                    stars=50, coins=мир.coins)
    всего = await farm_actions.plot_count(CHAT, USER, 50)
    assert итог.planted == всего
    assert len(мир.plots) == всего


@_sync
async def test_всё_поле_ограничено_деньгами_а_не_землёй(мир):
    мир.coins = farming.BY_KEY["kartoshka"].seed_price * 2
    итог = await farm_actions.plant(CHAT, USER, "картошка", "все",
                                    stars=50, coins=мир.coins)
    assert итог.planted == 2
    assert мир.coins == 0


@_sync
async def test_без_денег_не_сажают_и_не_списывают(мир):
    мир.coins = 10
    итог = await farm_actions.plant(CHAT, USER, "клубника", 1, stars=50)
    assert not итог.ok
    assert мир.coins == 10 and not мир.plots


@_sync
async def test_тыква_заперта_без_ивента(мир):
    """Сайт обязан запирать её ровно тогда же, когда чат."""
    итог = await farm_actions.plant(CHAT, USER, "тыква", 1, stars=50,
                                    event_active=False)
    assert not итог.ok and "ивент" in итог.error
    assert not мир.plots
    можно = await farm_actions.plant(CHAT, USER, "тыква", 1, stars=50,
                                     event_active=True)
    assert можно.ok


@_sync
async def test_больше_чем_грядок_не_посадить(мир):
    всего = await farm_actions.plot_count(CHAT, USER, 50)
    итог = await farm_actions.plant(CHAT, USER, "картошка", 99, stars=50)
    assert итог.planted == всего


@_sync
async def test_сотая_посадка_даёт_ачивку(мир):
    мир.data[farm_actions.counter_key(CHAT, USER, "plant")] = "99"
    итог = await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50)
    assert итог.achievements == ["farm_plant_100"]


# --- сбор -------------------------------------------------------------------

@_sync
async def test_сбор_кладёт_урожай_в_инвентарь_и_освобождает_грядку(мир):
    await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50)
    мир.plots[0]["ready_at"] = datetime.utcnow() - timedelta(minutes=1)
    итог = await farm_actions.harvest(CHAT, USER)
    assert итог.ok and итог.harvested > 0
    assert мир.inventory["urozhay_kartoshka"] == итог.harvested
    assert not мир.plots


@_sync
async def test_неспелое_не_трогают(мир):
    await farm_actions.plant(CHAT, USER, "клубника", 1, stars=50)
    итог = await farm_actions.harvest(CHAT, USER)
    assert not итог.ok
    assert len(мир.plots) == 1


@_sync
async def test_сгнившая_освобождает_грядку_но_ничего_не_даёт(мир):
    await farm_actions.plant(CHAT, USER, "клубника", 1, stars=50)
    crop = farming.BY_KEY["klubnika"]
    мир.plots[0]["ready_at"] = datetime.utcnow() - timedelta(hours=crop.perish_hours + 1)
    итог = await farm_actions.harvest(CHAT, USER)
    assert итог.ok and итог.harvested == 0 and итог.perished == 1
    assert not мир.plots and not мир.inventory


# --- грядки за монеты -------------------------------------------------------

@_sync
async def test_покупка_грядки_растит_участок(мир):
    было = await farm_actions.plot_count(CHAT, USER, 50)
    итог = await farm_actions.buy_plots(CHAT, USER, 1, stars=50, coins=мир.coins)
    assert итог.ok and итог.coins_spent > 0
    assert await farm_actions.plot_count(CHAT, USER, 50) == было + 1


@_sync
async def test_грядки_все_упираются_в_деньги(мир):
    мир.coins = farming.plot_price(0)
    итог = await farm_actions.buy_plots(CHAT, USER, "все", stars=50, coins=мир.coins)
    assert итог.ok
    assert await farm_actions.bought_plots(CHAT, USER) == 1


@_sync
async def test_без_денег_грядку_не_купить(мир):
    мир.coins = 1
    итог = await farm_actions.buy_plots(CHAT, USER, 1, stars=50, coins=1)
    assert not итог.ok and мир.coins == 1


# --- хлев -------------------------------------------------------------------

@_sync
async def test_покупка_скота_списывает_и_добавляет_голов(мир):
    было = мир.coins
    итог = await farm_actions.barn_buy(CHAT, USER, "корову", 3, coins=мир.coins)
    assert итог.ok and итог.planted == 3
    assert мир.coins == было - livestock.BY_KEY["korova"].price * 3
    assert await мир.get_farm_animal_quantity(CHAT, USER, "korova") == 3


@_sync
async def test_скот_не_держат_сверх_потолка(мир):
    await farm_actions.barn_buy(CHAT, USER, "корову", livestock.MAX_PER_KIND,
                                coins=мир.coins)
    итог = await farm_actions.barn_buy(CHAT, USER, "корову", 1, coins=мир.coins)
    assert not итог.ok


@_sync
async def test_продажа_возвращает_половину(мир):
    await farm_actions.barn_buy(CHAT, USER, "курицу", 2, coins=мир.coins)
    было = мир.coins
    итог = await farm_actions.barn_sell(CHAT, USER, "курицу", 2)
    assert итог.ok and итог.harvested == 2
    assert мир.coins == было + livestock.sell_back(livestock.BY_KEY["kurica"]) * 2
    assert await мир.get_farm_animal_quantity(CHAT, USER, "kurica") == 0


@_sync
async def test_продать_больше_чем_есть_нельзя(мир):
    await farm_actions.barn_buy(CHAT, USER, "курицу", 1, coins=мир.coins)
    итог = await farm_actions.barn_sell(CHAT, USER, "курицу", 5)
    assert not итог.ok
    assert await мир.get_farm_animal_quantity(CHAT, USER, "kurica") == 1


@_sync
async def test_продукт_копится_и_забирается(мир):
    await farm_actions.barn_buy(CHAT, USER, "курицу", 1, coins=мир.coins)
    animal = livestock.BY_KEY["kurica"]
    мир.animals[0]["last_collect_at"] = datetime.utcnow() - timedelta(
        hours=animal.cycle_hours + 1)
    итог = await farm_actions.collect_barn(CHAT, USER)
    assert итог.ok and итог.items[animal.item_key] >= animal.per_cycle
    пусто = await farm_actions.collect_barn(CHAT, USER)
    assert not пусто.ok       # только что забрали — копится заново


# --- состояние для экрана ---------------------------------------------------

@_sync
async def test_состояние_описывает_каждую_грядку(мир):
    итог = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins)
    assert len(итог["plots"]) == итог["plot_total"]
    assert all(p["crop"] is None for p in итог["plots"])
    assert итог["plot_free"] == итог["plot_total"]
    assert {c["key"] for c in итог["crops"]} == set(farming.BY_KEY)
    assert {a["key"] for a in итог["barn"]} == set(livestock.BY_KEY)
    assert итог["weather"]["emoji"] and итог["weather"]["name"]


@_sync
async def test_состояние_показывает_рост_и_готовность(мир):
    await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50)
    итог = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins)
    грядка = next(p for p in итог["plots"] if p["crop"])
    assert грядка["ready"] is False and 0 <= грядка["progress"] < 100

    мир.plots[0]["ready_at"] = datetime.utcnow() - timedelta(minutes=1)
    итог = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins)
    грядка = next(p for p in итог["plots"] if p["crop"])
    assert грядка["ready"] is True


@_sync
async def test_сроки_отдаются_текстом_который_поймёт_браузер(мир):
    """Экран считает таймеры сам, и время обязано быть разбираемым: не
    «через 2 часа», а момент, от которого можно отнять «сейчас»."""
    await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50)
    итог = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins)
    грядка = next(p for p in итог["plots"] if p["crop"])
    assert datetime.fromisoformat(грядка["ready_at"]) > datetime.fromisoformat(итог["now"])
    assert datetime.fromisoformat(грядка["planted_at"]) <= datetime.fromisoformat(итог["now"])


@_sync
async def test_тыква_в_каталоге_помечена_запертой(мир):
    итог = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins,
                                    event_active=False)
    тыква = next(c for c in итог["crops"] if c["key"] == "tykva")
    assert тыква["locked"] is True
    открыто = await farm_actions.state(CHAT, USER, stars=50, coins=мир.coins,
                                       event_active=True)
    assert next(c for c in открыто["crops"] if c["key"] == "tykva")["locked"] is False


@_sync
async def test_сажают_в_ту_грядку_по_которой_нажали(мир):
    """На экране растение обязано взойти там, куда попал палец. Без этого
    нажатие на дальнюю грядку выращивало бы росток в первой свободной — и
    главный элемент экрана показывал бы не то, что человек сделал."""
    итог = await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50, slot=4)
    assert итог.ok
    assert [p["slot"] for p in мир.plots] == [4]


@_sync
async def test_занятая_грядка_не_ломает_посадку(мир):
    """Слот мог занять вторая вкладка, пока человек выбирал культуру."""
    await farm_actions.plant(CHAT, USER, "картошка", 1, stars=50, slot=2)
    итог = await farm_actions.plant(CHAT, USER, "пшеница", 1, stars=50, slot=2)
    assert итог.ok and итог.planted == 1
    занятые = sorted(p["slot"] for p in мир.plots)
    assert занятые == [0, 2]      # вторая ушла в младшую свободную


@_sync
async def test_в_чате_слота_нет_и_порядок_прежний(мир):
    итог = await farm_actions.plant(CHAT, USER, "картошка", 2, stars=50)
    assert итог.planted == 2
    assert sorted(p["slot"] for p in мир.plots) == [0, 1]
