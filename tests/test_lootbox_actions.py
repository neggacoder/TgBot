"""Лутбоксы вне телеграма.

Три места, ради которых эти проверки и написаны.

ШАНС РЕДКОГО складывается из трёх слагаемых: база коробки, питомец «Нюхач» и
закреп темы «Коллекции». Посчитай их где-то ещё по-своему — и одна и та же
коробка станет давать редкое с разной вероятностью в зависимости от того,
откуда её открыли. Увидеть такое можно только по сотням открытий, то есть
практически никогда.

ПУЛ собирается заново из текущего магазина и титулов С ЦЕНОЙ. Титулы за
достижения в розыгрыш не идут: их нельзя купить, и выдавать их коробкой
значило бы обесценить то, что зарабатывают.

КОРОБКИ списываются ПОСЛЕ сборки пула: если открывать не на что, они обязаны
остаться на руках.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib

import pytest

import lootbox_actions as loot

ЧАТ, ЧЕЛОВЕК = -100, 7


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    def __init__(self, coins=100_000):
        self.coins = coins
        self.коробки: dict[str, int] = {}
        self.инвентарь: list[str] = []
        self.титулы_свои: set[str] = set()
        self.порядок: list[str] = []
        self.товары = [
            {"item_key": "cheap", "name": "Дешёвка", "emoji": "🎁", "price": 100},
            {"item_key": "mid", "name": "Средняя", "emoji": "🎁", "price": 1000},
            {"item_key": "dear", "name": "Дорогая", "emoji": "🎁", "price": 50000},
        ]
        self.каталог_титулов = [
            {"title_key": "sold", "name": "Продажный", "price": 7000},
            {"title_key": "earned", "name": "Заслуженный", "price": None},
        ]
        self.открыто = 0

    async def seed_default_shop_items(self, chat_id): pass
    async def seed_extra_shop_items(self, chat_id, rows): pass

    async def list_shop_items(self, chat_id, active_only=False):
        return [dict(t) for t in self.товары]

    async def list_titles(self):
        return [dict(t) for t in self.каталог_титулов]

    async def get_profile_card(self, chat_id, user_id):
        return {}

    async def list_user_lootboxes(self, chat_id, user_id):
        return [{"rarity": k, "quantity": v} for k, v in self.коробки.items() if v]

    async def get_lootbox_count(self, chat_id, user_id, rarity):
        return self.коробки.get(rarity, 0)

    async def add_lootbox(self, chat_id, user_id, rarity, count):
        self.порядок.append(f"выдали {count} коробок")
        self.коробки[rarity] = self.коробки.get(rarity, 0) + count

    async def remove_lootbox(self, chat_id, user_id, rarity, count):
        self.порядок.append(f"списали {count} коробок")
        self.коробки[rarity] = max(0, self.коробки.get(rarity, 0) - count)

    async def add_inventory_item(self, chat_id, user_id, key, qty=1):
        self.инвентарь.append(key)

    async def has_title(self, chat_id, user_id, key):
        return key in self.титулы_свои

    async def grant_title(self, chat_id, user_id, key):
        было = key in self.титулы_свои
        self.титулы_свои.add(key)
        return not было

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def try_spend_coins(self, chat_id, user_id, amount):
        self.порядок.append(f"списали {amount} монет")
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def increment_lootbox_stats(self, chat_id, user_id, count, rare):
        self.открыто += count
        return {"opened_count": self.открыто, "rare_count": rare}


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(loot, "db", w)
    return w


РЕДКОЕ = lambda: 1        # noqa: E731  — бросок ниже шанса: выпало редкое
ОБЫЧНОЕ = lambda: 100     # noqa: E731  — бросок выше любого шанса
ПЕРВЫЙ = lambda пул, weights, k: [пул[0]]      # noqa: E731  — самое дорогое в пуле
ПОСЛЕДНИЙ = lambda пул, weights, k: [пул[-1]]  # noqa: E731  — самое дешёвое


# --- редкость ----------------------------------------------------------------

@pytest.mark.parametrize("слово,ждём", [
    ("редкий", "rare"), ("РЕДКИЕ", "rare"), ("5", "legendary"),
    ("legendary", "legendary"), ("  обычный ", "common"),
])
def test_редкость_узнаётся_как_в_чате(слово, ждём):
    assert loot.resolve_rarity(слово) == ждём


def test_чужое_слово_не_редкость():
    assert loot.resolve_rarity("золотой") is None
    assert loot.resolve_rarity("") is None


# --- пул ---------------------------------------------------------------------

@_sync
async def test_дорогое_уходит_в_редкий_пул(мир):
    обычный, редкий = await loot.build_pools(ЧАТ)
    assert [п["key"] for п in редкий] == ["dear"], "в редкий пул попало не самое дорогое"
    assert {п["key"] for п in обычный} == {"sold", "mid", "cheap"}


@_sync
async def test_титул_за_достижение_в_розыгрыш_не_идёт(мир):
    """Его нельзя купить, и выдавать коробкой значило бы обесценить то, что
    зарабатывают."""
    обычный, редкий = await loot.build_pools(ЧАТ)
    ключи = {п["key"] for п in обычный + редкий}
    assert "earned" not in ключи and "sold" in ключи


@_sync
async def test_пустой_чат_даёт_пустой_пул(мир):
    мир.товары = []
    мир.каталог_титулов = []
    assert await loot.build_pools(ЧАТ) == ([], [])


def test_дорогое_выпадает_реже():
    """Вес обратен цене: иначе самая дорогая вещь выпадала бы наравне с
    грошовой, и коробки перестали бы что-либо значить."""
    пул = [{"key": "a", "price": 100}, {"key": "b", "price": 10000}]
    веса = []
    loot.weighted_pick(пул, pick=lambda p, weights, k: (веса.extend(weights), [p[0]])[1])
    assert веса[0] > веса[1], "дешёвая вещь весит не больше дорогой"


# --- покупка -----------------------------------------------------------------

@_sync
async def test_покупка_списывает_по_цене(мир):
    итог = await loot.buy(ЧАТ, ЧЕЛОВЕК, "редкий", 3)
    assert итог.ok and итог.count == 3
    assert итог.total_price == loot.TYPES["rare"]["price"] * 3
    assert мир.coins == 100_000 - итог.total_price
    assert мир.коробки["rare"] == 3


@_sync
async def test_сотню_за_раз_не_купить(мир):
    """Предохранитель тот же, что в чате: иначе одной опечаткой можно
    остаться без всего кошелька."""
    итог = await loot.buy(ЧАТ, ЧЕЛОВЕК, "обычный", 1000)
    assert итог.count == loot.MAX_PER_COMMAND


@_sync
async def test_без_денег_коробок_не_будет(мир):
    мир.coins = 10
    итог = await loot.buy(ЧАТ, ЧЕЛОВЕК, "легендарный", 1)
    assert not итог.ok
    assert мир.коробки == {}


# --- открытие ----------------------------------------------------------------

@_sync
async def test_нельзя_открыть_больше_чем_есть(мир):
    мир.коробки["rare"] = 1
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "редкий", 5, roll=ОБЫЧНОЕ, pick=ПЕРВЫЙ)
    assert not итог.ok and "не хватает" in итог.error
    assert мир.коробки["rare"] == 1


@_sync
async def test_нечего_разыгрывать_коробки_целы(мир):
    """Пул собирается ДО списания: если в чате нет ни товаров, ни титулов,
    коробки должны остаться на руках, а не сгореть впустую."""
    мир.коробки["rare"] = 2
    мир.товары = []
    мир.каталог_титулов = []
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "редкий", 2, roll=РЕДКОЕ, pick=ПЕРВЫЙ)
    assert not итог.ok
    assert мир.коробки["rare"] == 2, "коробки сгорели, хотя открывать было не на что"
    assert not any(с.startswith("списали 2 коробок") for с in мир.порядок)


@_sync
async def test_редкий_бросок_берёт_из_редкого_пула(мир):
    мир.коробки["legendary"] = 1
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "легендарный", 1, roll=РЕДКОЕ, pick=ПЕРВЫЙ)
    assert итог.ok and итог.rare_hits == 1
    assert итог.rewards[0]["key"] == "dear" and итог.rewards[0]["rare"] is True


@_sync
async def test_обычный_бросок_берёт_из_обычного_пула(мир):
    мир.коробки["common"] = 1
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "обычный", 1, roll=ОБЫЧНОЕ, pick=ПЕРВЫЙ)
    assert итог.ok and итог.rare_hits == 0
    assert итог.rewards[0]["rare"] is False and итог.rewards[0]["key"] != "dear"


@_sync
async def test_предмет_падает_в_инвентарь(мир):
    """Пул отсортирован по убыванию цены, и первым в обычном стоит ТИТУЛ
    (7000) — предмет достаётся последним. Проверять «что-нибудь выдали» тут
    мало: у титула и предмета разные пути выдачи."""
    мир.коробки["common"] = 1
    await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "обычный", 1, roll=ОБЫЧНОЕ, pick=ПОСЛЕДНИЙ)
    assert мир.инвентарь == ["cheap"], "предмет не попал в инвентарь"
    assert not мир.титулы_свои


@_sync
async def test_титул_из_коробки_выдаётся_титулом(мир):
    мир.коробки["common"] = 1
    await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "обычный", 1, roll=ОБЫЧНОЕ, pick=ПЕРВЫЙ)
    assert мир.титулы_свои == {"sold"}, "титул не выдан"
    assert not мир.инвентарь


@_sync
async def test_повтор_титула_меняется_на_компенсацию(мир):
    """Второй такой же титул ничего не значит — вместо него половина цены
    монетами, иначе редкий приз превращается в пустое место."""
    мир.титулы_свои.add("sold")
    приз = {"kind": "title", "key": "sold", "name": "Продажный", "price": 7000}
    было = мир.coins
    пометка = await loot.grant(ЧАТ, ЧЕЛОВЕК, приз)
    assert мир.coins == было + 3500 and "компенсация" in пометка


@_sync
async def test_достижение_на_сотом_открытии(мир):
    мир.коробки["common"] = 1
    мир.открыто = loot.MASTER_OPENED - 1
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "обычный", 1, roll=ОБЫЧНОЕ, pick=ПЕРВЫЙ)
    assert "lootbox_master" in итог.achievements


@_sync
async def test_до_сотни_достижения_нет(мир):
    мир.коробки["common"] = 1
    итог = await loot.open_boxes(ЧАТ, ЧЕЛОВЕК, "обычный", 1, roll=ОБЫЧНОЕ, pick=ПЕРВЫЙ)
    assert итог.achievements == []


# --- шанс редкого ------------------------------------------------------------

@_sync
async def test_без_надбавок_шанс_базовый(мир):
    assert await loot.rare_chance(ЧАТ, ЧЕЛОВЕК, "rare") == loot.TYPES["rare"]["rare_chance"]


@_sync
async def test_питомец_поднимает_шанс(мир):
    async def нюхач(chat_id, user_id, ability):
        return 50
    шанс = await loot.rare_chance(ЧАТ, ЧЕЛОВЕК, "rare", pet_bonus=нюхач)
    база = loot.TYPES["rare"]["rare_chance"]
    assert шанс == база + база * 50 // 100


@_sync
async def test_шанс_не_переваливает_за_сто(мир):
    async def сказочный(chat_id, user_id, ability):
        return 500
    assert await loot.rare_chance(ЧАТ, ЧЕЛОВЕК, "legendary", pet_bonus=сказочный) == 100


# --- одни правила на чат и сайт ----------------------------------------------

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


def test_бот_берёт_таблицы_отсюда():
    """Разъедься цены и шансы — одна и та же коробка стоила бы разного и
    давала бы редкое с разной вероятностью в зависимости от входа."""
    бот = (КОРЕНЬ / "bot.py").read_text(encoding="utf-8")
    for имя in ("LOOTBOX_TYPES = lootbox_actions.TYPES",
                "LOOTBOX_ORDER = lootbox_actions.ORDER",
                "LOOTBOX_ALIASES = lootbox_actions.ALIASES",
                "LOOTBOX_MAX_PER_COMMAND = lootbox_actions.MAX_PER_COMMAND",
                "LOOTBOX_RARE_POOL_SHARE = lootbox_actions.RARE_POOL_SHARE"):
        assert имя in бот, f"бот держит своё: {имя}"
    assert '"common":    {"name": "Обычный"' not in бот, "таблица коробок вернулась в бота"


def test_панель_идёт_через_общие_правила():
    файл = (КОРЕНЬ / "webpanel" / "member_lootbox_api.py").read_text(encoding="utf-8")
    for имя in ("lootbox_actions.buy", "lootbox_actions.open_boxes", "lootbox_actions.state"):
        assert имя in файл
    for запрет in ("db.add_lootbox", "db.remove_lootbox", "db.add_inventory_item",
                   "db.grant_title", "db.try_spend_coins"):
        assert запрет not in файл, f"панель раздаёт призы мимо правил: {запрет}"
    # Надбавка питомца передаётся функцией, а не считается на месте: иначе
    # получилось бы второе место, где решают шанс редкого.
    assert "pet_bonus=game_actions._pet_bonus" in файл
