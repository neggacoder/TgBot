"""Игровые действия без Telegram.

Модуль game_actions делает действие и возвращает результат. Отправить он
ничего не может — у него нет бота, и это не забывчивость, а конструкция:
тишина на сайте получается сама, а не заглушкой, которую можно забыть.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta

import pytest

import collections_meta
import game_actions
import pets as pets_catalog


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. tests/test_farming.py)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает кормление.

    Имена методов и поля строк — как в настоящем db.py, иначе заглушка
    проверяла бы выдуманный интерфейс: кормление ходит в set_pet_stats и
    читает last_fed_at/last_tick_at, а не что-то похожее по смыслу.
    """

    def __init__(self):
        now = datetime.utcnow()
        self.pets = [{
            "pet_key": "kot", "pet_name": None, "hunger": 10, "mood": 80,
            "xp": 0, "xp_tick_at": now, "last_fed_at": None,
            "last_care_at": None, "last_tick_at": now, "last_walk_at": None,
            "evolved": False, "ability": None, "ability2": None,
        }]
        self.inventory = {pets_catalog.FOOD_ITEM_KEY: 3}
        self.card = {}
        self.saved = []

    async def list_pets(self, chat_id, user_id):
        return [dict(p) for p in self.pets]

    async def get_pet(self, chat_id, user_id, key):
        return next((dict(p) for p in self.pets if p["pet_key"] == key), None)

    async def ensure_pet_catalog(self, chat_id, defaults):
        return 0

    async def list_pet_catalog(self, chat_id):
        return [{"pet_key": p.key, "name": p.name, "emoji": p.emoji,
                 "price": p.price, "sound": p.sound, "ability": p.ability,
                 "is_active": True, "max_count": None}
                for p in pets_catalog.PETS]

    async def get_profile_card(self, chat_id, user_id):
        return dict(self.card)

    async def get_inventory_quantity(self, chat_id, user_id, item_key):
        return self.inventory.get(item_key, 0)

    async def seed_extra_shop_items(self, chat_id, items, is_active=True):
        return 0

    async def remove_inventory_item(self, chat_id, user_id, item_key, amount=1):
        have = self.inventory.get(item_key, 0)
        if have < amount:
            return False
        self.inventory[item_key] = have - amount
        return True

    async def add_inventory_item(self, chat_id, user_id, item_key, amount=1):
        self.inventory[item_key] = self.inventory.get(item_key, 0) + amount

    async def set_pet_stats(self, chat_id, user_id, key, hunger, mood, xp, ts,
                            fed_at=None, care_at=None, walk_at=None):
        fields = {"hunger": hunger, "mood": mood, "xp": xp,
                  "last_tick_at": ts, "xp_tick_at": ts}
        # Условия ровно как в db.set_pet_stats («is not None», а не «if x»):
        # заглушка, повторяющая интерфейс, обязана повторять и его края.
        if fed_at is not None:
            fields["last_fed_at"] = fed_at
        if care_at is not None:
            fields["last_care_at"] = care_at
        if walk_at is not None:
            fields["last_walk_at"] = walk_at
        for p in self.pets:
            if p["pet_key"] == key:
                p.update(fields)
        self.saved.append((key, fields))
        return True

    async def rename_pet(self, chat_id, user_id, key, name):
        for p in self.pets:
            if p["pet_key"] == key:
                p["pet_name"] = name
        return None


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(game_actions, "db", world)
    return world


@_sync
async def test_кормление_поднимает_сытость_и_тратит_корм(мир):
    было = мир.inventory[pets_catalog.FOOD_ITEM_KEY]
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert res.ok, res.text
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == было - 1
    assert мир.pets[0]["hunger"] > 10


@_sync
async def test_без_корма_кормление_не_проходит(мир):
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 0
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert not res.ok
    assert "корм" in res.text.lower()
    assert мир.pets[0]["hunger"] == 10, "неудача не должна ничего менять"


@_sync
async def test_сытого_кормить_нельзя(мир):
    мир.pets[0]["hunger"] = 100
    мир.pets[0]["last_fed_at"] = datetime.utcnow()
    было = мир.inventory[pets_catalog.FOOD_ITEM_KEY]
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert not res.ok
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == было, "корм не тратится впустую"


@_sync
async def test_неизвестный_питомец(мир):
    res = await game_actions.feed_pet(-100, 7, "дракон")
    assert not res.ok


@_sync
async def test_результат_не_умеет_отправлять():
    """Ключевое свойство: у модуля нет ни бота, ни отправки. Тишина на сайте
    — следствие конструкции, а не забытой проверки."""
    import inspect
    src = inspect.getsource(game_actions)
    assert "aiogram" not in src
    assert "send_message" not in src
    assert "import bot" not in src


@_sync
async def test_новый_уровень_становится_объявлением(мир):
    """Ачивки и уровни объявляются в чат даже когда действие сделано с сайта:
    их ради этого и добывают. Модуль их не шлёт, а возвращает.

    Утверждение безусловное намеренно. Написанное как «if res.announcements:»
    оно проходило бы и при полностью выпиленной механике объявлений — то есть
    единственное новое в этой работе не проверялось бы ничем.
    """
    мир.pets[0]["xp"] = pets_catalog.LEVEL_XP_THRESHOLDS[1] - 1
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert res.ok
    assert res.announcements, "новый уровень обязан стать объявлением"
    assert all(a.text for a in res.announcements)
    assert all(a.kind == game_actions.ANNOUNCE_PET_LEVEL for a in res.announcements)


@_sync
async def test_питомец_на_откате_ждёт_столько_же_сколько_в_чате(мир):
    """Откат кормёжки — правило игры, а не текст обработчика: с сайта он
    обязан быть тот же самый, иначе кулдаун обходился бы сменой окна."""
    мир.pets[0]["last_fed_at"] = datetime.utcnow() - timedelta(minutes=1)
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert not res.ok
    assert "сыт" in res.text


@_sync
async def test_ласка_поднимает_настроение(мир):
    мир.pets[0]["mood"] = 40
    res = await game_actions.care_pet(-100, 7, "гладить", "kot")
    assert res.ok, res.text
    assert мир.pets[0]["mood"] > 40


@_sync
async def test_ласка_имеет_кулдаун(мир):
    await game_actions.care_pet(-100, 7, "гладить", "kot")
    было = мир.pets[0]["mood"]
    res = await game_actions.care_pet(-100, 7, "гладить", "kot")
    assert not res.ok
    assert мир.pets[0]["mood"] == было


@_sync
async def test_массовое_кормление_кормит_всех_кому_хватило(мир):
    мир.pets.append(dict(мир.pets[0], pet_key="panda", hunger=20))
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 1
    res = await game_actions.feed_all(-100, 7)
    assert res.ok
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == 0
    assert "1" in res.text


@_sync
async def test_массовое_кормление_без_корма(мир):
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 0
    res = await game_actions.feed_all(-100, 7)
    assert not res.ok


@_sync
async def test_прогулка_даёт_монеты_и_ставит_кулдаун(мир, monkeypatch):
    начислено = []

    async def add_coins(chat_id, user_id, amount):
        начислено.append(amount)
        return amount

    async def add_inventory_item(chat_id, user_id, item_key, amount=1):
        мир.inventory[item_key] = мир.inventory.get(item_key, 0) + amount

    monkeypatch.setattr(мир, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(мир, "add_inventory_item", add_inventory_item, raising=False)
    monkeypatch.setattr(game_actions.random, "randint", lambda a, b: b)
    # Прогулка — первое перенесённое действие, которое требует бодрого
    # питомца (pets.LOW_STAT): заглушка держит сытость низкой ради кормёжки
    # (см. _World.__init__), а без этой строки тест проверял бы отказ, а не
    # саму прогулку.
    мир.pets[0]["hunger"] = 100
    res = await game_actions.walk_pet(-100, 7, "kot")
    assert res.ok, res.text
    assert мир.pets[0]["last_walk_at"] is not None
    assert начислено, "монеты обязаны начислиться"


@_sync
async def test_голодный_гулять_не_идёт(мир):
    мир.pets[0]["hunger"] = 0
    мир.pets[0]["mood"] = 0
    res = await game_actions.walk_pet(-100, 7, "kot")
    assert not res.ok


@_sync
async def test_наградного_питомца_не_купить(мир, monkeypatch):
    """Питомец за ачивку — знак отличия, а не товар. Правило одно на чат и
    сайт, иначе через кабинет его можно было бы купить за монеты."""
    награда = next(p for p in pets_catalog.PETS if p.by_achievement)
    res = await game_actions.buy_pet(-100, 7, награда.key)
    assert not res.ok


@_sync
async def test_наградного_питомца_не_продать(мир):
    награда = next(p for p in pets_catalog.PETS if p.by_achievement)
    мир.pets.append(dict(мир.pets[0], pet_key=награда.key))
    res = await game_actions.sell_pet(-100, 7, награда.key, confirm=True)
    assert not res.ok


@_sync
async def test_имя_обрезается_по_длине(мир):
    """Строка питомца в заглушке хранит имя под ключом pet_name — как и
    настоящая база (см. _World.rename_pet и db.rename_pet). Раньше тест
    читал несуществующий ключ "name" и проходил бы независимо от того,
    обрезает rename_pet имя или нет — см. task-5-report.md, находка 2."""
    res = await game_actions.rename_pet(-100, 7, "kot", "и" * 500)
    assert not res.ok or len(мир.pets[0].get("pet_name") or "") <= pets_catalog.NAME_MAX


@_sync
async def test_корм_без_числа_показывает_а_с_числом_честно_отказывает(мир):
    """buy_food — единственное публичное действие модуля, и его контракт
    обязан быть таким же однородным, как у всех остальных: ActionResult
    ВСЕГДА, никогда None (было иначе до ревью — обобщённый вызывающий вроде
    веб-панели падал на result.ok с AttributeError, получив None). Покупку с
    числом buy_food по-прежнему не считает сама — она идёт через общий
    магазинный путь (см. bot._shop_buy), а не вторую копию его правил здесь,
    — но честно возвращает отказ, а не молчаливый None."""
    res_qty = await game_actions.buy_food(-100, 7, "10")
    assert isinstance(res_qty, game_actions.ActionResult)
    assert not res_qty.ok
    res_info = await game_actions.buy_food(-100, 7, None)
    assert res_info.ok and str(pets_catalog.FOOD_ITEM_PRICE) in res_info.text


@_sync
async def test_ачивка_за_коллекцию_не_показывает_голый_код(мир):
    """Без переданного achievement_info buy_pet обязан подставить название
    сам, а не оставить в тексте внутренний код ачивки — тот, кто зовёт
    действие, не обязан знать о существовании ACHIEVEMENTS (панель, прямой
    вызов модуля). Полностью это работает для ачивок за коллекции: их
    название и описание есть в чистом collections_meta, без похода в bot.py
    (см. _default_achievement_info — для остальных ачивок дыра остаётся
    открытой, это отдельная находка)."""
    награда = next(p for p in pets_catalog.PETS if p.achievement.startswith("collection_"))
    res = await game_actions.buy_pet(-100, 7, награда.key)
    assert not res.ok
    assert награда.achievement not in res.text
    collection = collections_meta.BY_KEY[награда.achievement.removeprefix("collection_")]
    assert collection.name in res.text


def _злой_вид() -> dict:
    """Строка каталога, какой её может оставить админ: длину бот режет, а
    угловые скобки — нет (см. bot.py, `value = raw[:64]`)."""
    return {"pet_key": "<svg/onload=alert(1)>",
            "name": "<script>alert(1)</script>",
            "emoji": "<img src=x onerror=alert(1)>",
            "price": 100, "sound": "<b>шипит</b>",
            "ability": None, "is_active": True, "max_count": None}


def _подсунуть_злой_вид(мир, monkeypatch) -> dict:
    вид = _злой_вид()

    async def каталог(chat_id):
        return [вид]

    monkeypatch.setattr(мир, "list_pet_catalog", каталог, raising=False)
    мир.pets = [dict(мир.pets[0], pet_key=вид["pet_key"])]
    return вид


@_sync
async def test_вид_из_каталога_не_доезжает_до_текста_сырым(мир, monkeypatch):
    """Каталог видов заполняет админ, а кабинет вставляет ответ в страницу
    как HTML — на том же адресе, где живёт админ-панель со своей кукой.
    Раньше последствие было безобидным: такой текст просто отвергал Telegram.
    Порог для атаки — уровень модератора, то есть не «только владелец»."""
    вид = _подсунуть_злой_вид(мир, monkeypatch)
    res = await game_actions.my_pets_text(-100, 7, own=True)
    for сырое in (вид["name"], вид["emoji"], вид["pet_key"]):
        assert сырое not in res.text, f"в текст доехало сырым: {сырое}"
    assert "&lt;script&gt;" in res.text, "название вида должно быть экранировано"


@_sync
async def test_звук_вида_тоже_экранируется(мир, monkeypatch):
    """Звук («чем отвечает на ласку») правится тем же админским полем, что и
    название, и попадает в ответ на ласку — то есть в ту же страницу."""
    вид = _подсунуть_злой_вид(мир, monkeypatch)
    res = await game_actions.care_pet(-100, 7, "погладить", None)
    assert res.ok, res.text
    assert вид["sound"] not in res.text
    assert "&lt;b&gt;шипит&lt;/b&gt;" in res.text
