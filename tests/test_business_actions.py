"""Правила бизнесов вне телеграма: копилка, налог, апгрейд, ремонт, продажа.

Самое дорогое место здесь — налог: он считается от ВСЕЙ снимаемой суммы разом.
Посчитай его с каждого бизнеса отдельно, и владелец пяти платил бы по нижней
ставке пять раз — то есть меньше владельца одного крупного.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta

import pytest

import business_actions
import businesses as catalog


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогают бизнесы."""

    def __init__(self, coins=10_000_000):
        self.coins = coins
        self.chat_coins = 0
        self.rows: list[dict] = []
        self.upgrades: dict[str, set] = {}
        self.season: dict[str, int] = {}
        self.effects: set[str] = set()
        self.data: dict[str, str] = {}

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def add_chat_coins(self, chat_id, amount):
        self.chat_coins += amount
        return self.chat_coins

    async def list_user_businesses(self, chat_id, user_id):
        return [dict(r) for r in self.rows]

    async def get_user_business(self, chat_id, user_id, key):
        for r in self.rows:
            if r["business_key"] == key:
                return dict(r)
        return None

    async def add_business(self, chat_id, user_id, key, now):
        if any(r["business_key"] == key for r in self.rows):
            return False
        self.rows.append({"business_key": key, "level": 1, "accrued": 0,
                          "last_tick_at": now, "broken_kind": None,
                          "boost_until": None})
        return True

    async def delete_business(self, chat_id, user_id, key):
        было = len(self.rows)
        self.rows = [r for r in self.rows if r["business_key"] != key]
        return len(self.rows) != было

    async def set_business_accrual(self, chat_id, user_id, key, accrued, now):
        for r in self.rows:
            if r["business_key"] == key:
                r["accrued"] = accrued
                r["last_tick_at"] = now

    async def set_business_level(self, chat_id, user_id, key, level, accrued, now):
        for r in self.rows:
            if r["business_key"] == key:
                r["level"] = level
                r["accrued"] = accrued
                r["last_tick_at"] = now

    async def repair_business(self, chat_id, user_id, key, now):
        for r in self.rows:
            if r["business_key"] == key and r["broken_kind"]:
                r["broken_kind"] = None
                r["last_tick_at"] = now
                return True
        return False

    async def list_business_upgrades(self, chat_id, user_id, key):
        return set(self.upgrades.get(key, set()))

    async def add_business_upgrade(self, chat_id, user_id, key, upgrade, now):
        поставлено = self.upgrades.setdefault(key, set())
        if upgrade in поставлено:
            return False
        поставлено.add(upgrade)
        return True

    async def clear_business_upgrades(self, chat_id, user_id, key):
        self.upgrades.pop(key, None)

    async def add_season_points(self, chat_id, season, user_id, points):
        self.season[season] = self.season.get(season, 0) + points

    async def consume_item_effect(self, chat_id, user_id, effect):
        if effect in self.effects:
            self.effects.discard(effect)
            return True
        return False

    async def list_pets(self, chat_id, user_id):
        return []

    async def get_profile_card(self, chat_id, user_id):
        return {}

    # Предложения сделок живут в общем key-value: они переживают перезапуск и
    # видны другому процессу (кнопку нажимают в телеграме, а не на сайте).
    async def get_data(self, key):
        return {"data_value": self.data[key]} if key in self.data else None

    async def set_data(self, key, value, updated_by=None):
        self.data[key] = str(value)

    async def delete_data(self, key):
        self.data.pop(key, None)


CHAT, USER = -100, 7
ПЕРВЫЙ = catalog.BUSINESSES[0]
ВТОРОЙ = catalog.BUSINESSES[1]


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(business_actions, "db", world)
    return world


def _накопить(мир, key, часов):
    """Отматывает время назад — копилка считается лениво, от last_tick_at."""
    for r in мир.rows:
        if r["business_key"] == key:
            r["last_tick_at"] = datetime.utcnow() - timedelta(hours=часов)


# --- покупка ----------------------------------------------------------------

@_sync
async def test_покупка_списывает_и_заводит(мир):
    было = мир.coins
    итог = await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.ok and итог.level == 1
    assert мир.coins == было - ПЕРВЫЙ.price
    assert len(мир.rows) == 1


@_sync
async def test_второй_такой_же_не_положен(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    было = мир.coins
    итог = await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    assert not итог.ok and мир.coins == было


@_sync
async def test_без_денег_не_купить(мир):
    мир.coins = 1
    итог = await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    assert not итог.ok and not мир.rows and мир.coins == 1


# --- копилка и налог --------------------------------------------------------

@_sync
async def test_копилка_растёт_по_часам_и_упирается_в_потолок(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 2)
    строка = (await business_actions.load_all(CHAT, USER))[0]
    assert business_actions.pending(строка) == ПЕРВЫЙ.income(1) * 2

    _накопить(мир, ПЕРВЫЙ.key, 1000)
    строка = (await business_actions.load_all(CHAT, USER))[0]
    assert business_actions.pending(строка) == ПЕРВЫЙ.cap(1)


@_sync
async def test_сломанный_не_копит(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 5)
    мир.rows[0]["broken_kind"] = "поломка"
    мир.rows[0]["accrued"] = 10
    строка = (await business_actions.load_all(CHAT, USER))[0]
    assert business_actions.pending(строка) == 10


@_sync
async def test_налог_считается_от_всей_суммы_разом(мир):
    """Иначе владелец пяти бизнесов платил бы по нижней ставке пять раз."""
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    await business_actions.buy(CHAT, USER, ВТОРОЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 100)
    _накопить(мир, ВТОРОЙ.key, 100)
    итог = await business_actions.collect(CHAT, USER)
    assert итог.ok and итог.count == 2
    assert итог.tax == catalog.tax_for(итог.gross)
    отдельно = catalog.tax_for(ПЕРВЫЙ.cap(1)) + catalog.tax_for(ВТОРОЙ.cap(1))
    assert итог.tax >= отдельно


@_sync
async def test_сбор_платит_на_руки_и_в_казну(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 10)
    было = мир.coins
    итог = await business_actions.collect(CHAT, USER)
    assert мир.coins == было + итог.net
    assert мир.chat_coins == итог.tax
    assert итог.gross == итог.net + итог.tax


@_sync
async def test_после_сбора_копилка_пуста(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 10)
    await business_actions.collect(CHAT, USER)
    ещё = await business_actions.collect(CHAT, USER)
    assert not ещё.ok


@_sync
async def test_сбор_одного_не_трогает_остальные(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    await business_actions.buy(CHAT, USER, ВТОРОЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 10)
    _накопить(мир, ВТОРОЙ.key, 10)
    итог = await business_actions.collect(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.count == 1
    остаток = [r for r in мир.rows if r["business_key"] == ВТОРОЙ.key][0]
    assert business_actions.pending(остаток) > 0


@_sync
async def test_доход_даёт_очки_сезона(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 50)
    await business_actions.collect(CHAT, USER)
    assert sum(мир.season.values()) > 0


# --- апгрейд ----------------------------------------------------------------

@_sync
async def test_апгрейд_поднимает_уровень_и_доход(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    итог = await business_actions.upgrade(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.ok and итог.level == 2
    assert ПЕРВЫЙ.income(2) > ПЕРВЫЙ.income(1)


@_sync
async def test_выше_максимума_не_поднять(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    for _ in range(catalog.MAX_LEVEL - 1):
        await business_actions.upgrade(CHAT, USER, ПЕРВЫЙ.key)
    итог = await business_actions.upgrade(CHAT, USER, ПЕРВЫЙ.key)
    assert not итог.ok and "максимум" in итог.error


@_sync
async def test_апгрейд_фиксирует_копилку(мир):
    """У нового уровня свой потолок: без фиксации накопленное пересчиталось бы
    задним числом по новым правилам."""
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 3)
    до = business_actions.pending((await business_actions.load_all(CHAT, USER))[0])
    await business_actions.upgrade(CHAT, USER, ПЕРВЫЙ.key)
    assert мир.rows[0]["accrued"] == до


@_sync
async def test_бизнес_план_платит_вместо_монет(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    мир.effects.add("free_upgrade")
    было = мир.coins
    итог = await business_actions.upgrade(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.ok and итог.free and итог.spent == 0
    assert мир.coins == было


# --- ремонт и оснащение -----------------------------------------------------

@_sync
async def test_ремонт_возвращает_в_строй(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    мир.rows[0]["broken_kind"] = "поломка"
    итог = await business_actions.repair(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.ok and мир.rows[0]["broken_kind"] is None


@_sync
async def test_целый_чинить_нечего(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    было = мир.coins
    итог = await business_actions.repair(CHAT, USER, ПЕРВЫЙ.key)
    assert not итог.ok and мир.coins == было


@_sync
async def test_оснащение_ставится_один_раз_и_меняет_числа(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    итог = await business_actions.equip(CHAT, USER, ПЕРВЫЙ.key, "реклама")
    assert итог.ok
    строка = (await business_actions.load_all(CHAT, USER))[0]
    assert catalog.effective_income(ПЕРВЫЙ, 1, строка["upgrades"]) > ПЕРВЫЙ.income(1)
    ещё = await business_actions.equip(CHAT, USER, ПЕРВЫЙ.key, "реклама")
    assert not ещё.ok


@_sync
async def test_цена_оснащения_зависит_от_бизнеса(мир):
    """Сейф в дорогой бизнес и в дешёвый стоит по-разному — иначе оснащение
    крупного окупалось бы мгновенно."""
    дорогой = max(catalog.BUSINESSES, key=lambda b: b.price)
    дешёвый = min(catalog.BUSINESSES, key=lambda b: b.price)
    сейф = catalog.UPGRADE_BY_KEY[catalog.UPGRADE_SAFE]
    assert сейф.price(дорогой) > сейф.price(дешёвый)


# --- продажа ----------------------------------------------------------------

@_sync
async def test_продажа_возвращает_долю_и_копилку(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 5)
    накоплено = business_actions.pending((await business_actions.load_all(CHAT, USER))[0])
    было = мир.coins
    итог = await business_actions.sell_to_bot(CHAT, USER, ПЕРВЫЙ.key)
    assert итог.ok
    assert мир.coins == было + ПЕРВЫЙ.buyback() + накоплено
    assert not мир.rows


@_sync
async def test_продажа_снимает_оснащение(мир):
    """Оснащение не переезжает к новому хозяину — иначе перепродажа копила бы
    его бесплатно."""
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    await business_actions.equip(CHAT, USER, ПЕРВЫЙ.key, "охрана")
    await business_actions.sell_to_bot(CHAT, USER, ПЕРВЫЙ.key)
    assert not await мир.list_business_upgrades(CHAT, USER, ПЕРВЫЙ.key)


# --- состояние для экрана ---------------------------------------------------

@_sync
async def test_состояние_описывает_свои_и_каталог(мир):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 2)
    итог = await business_actions.state(CHAT, USER)
    свой = итог["mine"][0]
    assert свой["key"] == ПЕРВЫЙ.key and свой["level"] == 1
    assert свой["accrued"] > 0 and свой["cap"] == ПЕРВЫЙ.cap(1)
    assert 0 < свой["full_percent"] <= 100
    assert свой["gear_prices"]
    assert итог["pending_total"] == свой["accrued"]
    assert итог["tax_now"] == catalog.tax_for(итог["pending_total"])
    каталог = {c["key"]: c for c in итог["catalog"]}
    assert каталог[ПЕРВЫЙ.key]["owned"] is True
    assert каталог[ВТОРОЙ.key]["owned"] is False


@_sync
async def test_налог_виден_до_сбора(мир):
    """Узнавать про налог постфактум — худший способ: человек снимал бы по
    частям, чтобы не попасть в верхнюю ставку."""
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    _накопить(мир, ПЕРВЫЙ.key, 100)
    состояние = await business_actions.state(CHAT, USER)
    итог = await business_actions.collect(CHAT, USER)
    assert состояние["tax_now"] == итог.tax


# --- сделка между людьми ----------------------------------------------------

ПОКУПАТЕЛЬ = 9


class _МирСДвумя(_World):
    """У каждого свои бизнесы: сделка их и переносит."""

    def __init__(self):
        super().__init__()
        self.по_людям: dict[int, list[dict]] = {}

    async def list_user_businesses(self, chat_id, user_id):
        return [dict(r) for r in self.по_людям.get(user_id, [])]

    async def get_user_business(self, chat_id, user_id, key):
        for r in self.по_людям.get(user_id, []):
            if r["business_key"] == key:
                return dict(r)
        return None

    async def add_business(self, chat_id, user_id, key, now):
        свои = self.по_людям.setdefault(user_id, [])
        if any(r["business_key"] == key for r in свои):
            return False
        свои.append({"business_key": key, "level": 1, "accrued": 0,
                     "last_tick_at": now, "broken_kind": None, "boost_until": None})
        return True

    async def set_business_accrual(self, chat_id, user_id, key, accrued, now):
        for r in self.по_людям.get(user_id, []):
            if r["business_key"] == key:
                r["accrued"] = accrued
                r["last_tick_at"] = now

    async def move_business(self, chat_id, from_id, to_id, key, now):
        отдающий = self.по_людям.get(from_id, [])
        строка = next((r for r in отдающий if r["business_key"] == key), None)
        if строка is None:
            return False
        if any(r["business_key"] == key for r in self.по_людям.get(to_id, [])):
            return False
        отдающий.remove(строка)
        строка["accrued"] = 0
        строка["last_tick_at"] = now
        self.по_людям.setdefault(to_id, []).append(строка)
        return True


@pytest.fixture
def двое(monkeypatch):
    world = _МирСДвумя()
    monkeypatch.setattr(business_actions, "db", world)
    return world


@_sync
async def test_предложение_ничего_не_двигает(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    было = двое.coins
    итог = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 5_000)
    assert итог.ok and итог.deal_id
    assert двое.coins == было                       # деньги на месте
    assert await двое.get_user_business(CHAT, USER, ПЕРВЫЙ.key)   # владелец тот же
    assert not await двое.get_user_business(CHAT, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key)


@_sync
async def test_согласие_переносит_бизнес_и_деньги(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    предложение = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 5_000)
    было = двое.coins
    итог = await business_actions.accept_deal(CHAT, предложение.deal_id, ПОКУПАТЕЛЬ)
    assert итог.ok and итог.spent == 5_000
    # Кошелёк в заглушке общий, поэтому проверяем сам перенос владения.
    assert await двое.get_user_business(CHAT, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key)
    assert not await двое.get_user_business(CHAT, USER, ПЕРВЫЙ.key)
    assert двое.coins == было                       # заплатил одному, получил другой


@_sync
async def test_подтвердить_может_только_получатель(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    чужой = await business_actions.accept_deal(CHAT, п.deal_id, 12345)
    assert not чужой.ok and "не вам" in чужой.error
    assert await двое.get_user_business(CHAT, USER, ПЕРВЫЙ.key)


@_sync
async def test_дважды_одну_сделку_не_принять(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    assert (await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)).ok
    ещё = await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)
    assert not ещё.ok


@_sync
async def test_отказ_снимает_предложение(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    assert (await business_actions.decline_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)).ok
    assert await business_actions.load_deal(CHAT, п.deal_id) is None
    поздно = await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)
    assert not поздно.ok


@_sync
async def test_передумавший_владелец_тоже_может_отказаться(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    assert (await business_actions.decline_deal(CHAT, п.deal_id, USER)).ok


@_sync
async def test_дарение_переносит_без_денег(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 0)
    было = двое.coins
    итог = await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)
    assert итог.ok and итог.spent == 0 and двое.coins == было
    assert await двое.get_user_business(CHAT, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key)


@_sync
async def test_копилка_остаётся_продавцу(двое):
    """Бизнес переходит пустым. Иначе покупатель платил бы за бизнес, а получал
    бизнес плюс чужие накопления — и цена перестала бы что-то значить."""
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    двое.по_людям[USER][0]["last_tick_at"] = datetime.utcnow() - timedelta(hours=3)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    assert п.gross > 0
    итог = await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)
    assert итог.net > 0 and итог.tax >= 0         # инкассировано продавцу
    новый = await двое.get_user_business(CHAT, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key)
    assert новый["accrued"] == 0


@_sync
async def test_себе_бизнес_не_продать(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    итог = await business_actions.offer(CHAT, USER, USER, ПЕРВЫЙ.key, 100)
    assert not итог.ok


@_sync
async def test_нельзя_предложить_тому_у_кого_такой_есть(двое):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    await business_actions.buy(CHAT, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key)
    итог = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    assert not итог.ok and "уже есть" in итог.error


@_sync
async def test_просроченное_предложение_не_принять(двое, monkeypatch):
    await business_actions.buy(CHAT, USER, ПЕРВЫЙ.key)
    п = await business_actions.offer(CHAT, USER, ПОКУПАТЕЛЬ, ПЕРВЫЙ.key, 100)
    # Настоящую функцию берём ДО подмены: business_actions.time — это тот же
    # модуль time, и обращение к нему изнутри заглушки ушло бы в неё саму.
    настоящее = business_actions.time.time
    monkeypatch.setattr(business_actions.time, "time",
                        lambda: настоящее() + business_actions.OFFER_TTL_SECONDS + 1)
    итог = await business_actions.accept_deal(CHAT, п.deal_id, ПОКУПАТЕЛЬ)
    assert not итог.ok and "устарел" in итог.error
