"""Личные питомцы: сытость, настроение и команды.

Главное, что проверяется, — ленивый расчёт: сытость и настроение падают сами
по времени, и если посчитать их неверно, питомец либо голодает мгновенно,
либо не голодает никогда. Плюс то, что каталог живёт в БД: админ может
создать своего питомца, и команды обязаны его видеть.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import pets as P

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ME = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


def _message(text: str):
    from aiogram.types import Chat, Message, User
    m = Message(message_id=1, date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="supergroup"),
                from_user=User(id=ME, is_bot=False, first_name="Тестер"), text=text)
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    return m, replies


# --- каталог ---------------------------------------------------------------

def test_каталог_заполнен():
    for spec in P.PETS:
        assert spec.name and spec.emoji and spec.sound
        assert spec.price > 0


def test_ключи_не_повторяются():
    keys = [p.key for p in P.PETS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("raw, key", [
    ("kot", "kot"), ("кот", "kot"), ("КОТИК", "kot"),
    ("пёс", "pes"), ("пес", "pes"), ("собака", "pes"),
    ("дракончик", "drakon"), ("панда", "panda"),
])
def test_питомец_находится_по_ключу_и_по_русски(raw, key):
    found = P.resolve(raw)
    assert found is not None and found.key == key


@pytest.mark.parametrize("raw", ["", "  ", "чепуха", None])
def test_чужое_слово_не_питомец(raw):
    assert P.resolve(raw) is None


# --- сытость и настроение --------------------------------------------------

def test_сытость_падает_со_временем():
    assert P.hunger_now(100, 0) == 100
    assert P.hunger_now(100, 10) == 100 - P.HUNGER_PER_HOUR * 10


def test_ниже_нуля_не_падает():
    """Иначе «минус двести сытости» пришлось бы откармливать вечность."""
    assert P.hunger_now(10, 1000) == 0
    assert P.mood_now(10, 1000) == 0


def test_отрицательное_время_не_кормит_питомца():
    """Часы бота и базы могут разъехаться — сытость от этого расти не должна."""
    assert P.hunger_now(50, -5) == 50


def test_перекормить_нельзя():
    assert P.gain(90, 50) == P.MAX_STAT
    assert P.gain(0, 10) == 10


def test_настроение_падает_медленнее_сытости():
    """Осознанно: есть питомец хочет чаще, чем скучать."""
    assert P.MOOD_PER_HOUR < P.HUNGER_PER_HOUR


def test_состояние_описывается_словами():
    assert "голодает" in P.state_text(0, 100)
    assert "роголодался" in P.state_text(P.LOW_STAT - 1, 100)
    assert "скучает" in P.state_text(100, P.LOW_STAT - 1)
    assert "хорошо" in P.state_text(100, 100)


def test_полоса_не_вылезает_за_края():
    for value in (-50, 0, 37, 100, 500):
        bar = P.bar(value, width=10)
        assert len(bar) == 10


# --- команды ---------------------------------------------------------------

@pytest.fixture
def world(monkeypatch):
    now = datetime.utcnow()
    state = {"coins": 100_000, "pets": {}, "stats": [], "pinned": "unset"}

    async def get_wallet(chat_id, user_id):
        return {"coins": state["coins"]}

    async def try_spend_coins(chat_id, user_id, amount):
        if state["coins"] < amount:
            return False
        state["coins"] -= amount
        return True

    async def add_coins(chat_id, user_id, amount):
        state["coins"] += amount

    async def list_pets(chat_id, user_id):
        return [dict(v) for v in state["pets"].values()]

    async def get_pet(chat_id, user_id, key):
        row = state["pets"].get(key)
        return dict(row) if row else None

    async def add_pet(chat_id, user_id, key, ts):
        if key in state["pets"]:
            return False
        state["pets"][key] = {"pet_key": key, "pet_name": None, "hunger": 100,
                              "mood": 100, "last_tick_at": ts, "last_fed_at": None,
                              "last_care_at": None, "bought_at": ts}
        return True

    async def set_pet_stats(chat_id, user_id, key, hunger, mood, ts,
                            fed_at=None, care_at=None):
        state["stats"].append({"key": key, "hunger": hunger, "mood": mood})
        row = state["pets"][key]
        row.update(hunger=hunger, mood=mood, last_tick_at=ts)
        if fed_at:
            row["last_fed_at"] = fed_at
        if care_at:
            row["last_care_at"] = care_at

    async def set_pinned_pet(chat_id, user_id, key):
        state["pinned"] = key

    # Каталог: встроенные плюс один «созданный админом». Выключатель и лимит
    # приходят ИЗ БАЗЫ, поэтому тесты правят их здесь (state["catalog"]), а не
    # патчат словарь настроек: тот перечитывается при каждом обращении.
    state["catalog"] = {}

    async def list_pet_catalog(chat_id):
        rows = [{"pet_key": p.key, "name": p.name, "emoji": p.emoji,
                 "price": p.price, "sound": p.sound, "ability": p.ability}
                for p in P.PETS]
        rows.append({"pet_key": "ezhik", "name": "Ёжик", "emoji": "🦔",
                     "price": 5_000, "sound": "фыркает", "ability": "fishing"})
        for row in rows:
            row.setdefault("is_active", True)
            row.setdefault("max_count", None)
            row.update(state["catalog"].get(row["pet_key"], {}))
        return rows

    for name, fn in [("get_wallet", get_wallet), ("try_spend_coins", try_spend_coins),
                     ("add_coins", add_coins), ("list_pets", list_pets),
                     ("get_pet", get_pet), ("add_pet", add_pet),
                     ("set_pet_stats", set_pet_stats), ("set_pinned_pet", set_pinned_pet),
                     ("rename_pet", _noop), ("add_log", _noop),
                     ("ensure_pet_catalog", _returns(0)),
                     ("list_pet_catalog", list_pet_catalog)]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "has_infinite_money", lambda uid: False, raising=False)
    state["now"] = now
    return state


def test_питомец_покупается_и_списывает_цену(world):
    msg, replies = _message("пет купить кот")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "kot" in world["pets"]
    assert world["coins"] == 100_000 - P.BY_KEY["kot"].price


def test_созданный_админом_питомец_покупается_так_же(world):
    """Каталог живёт в БД — команды обязаны видеть заведённых в панели."""
    msg, replies = _message("пет купить ezhik")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "ezhik" in world["pets"]
    assert world["coins"] == 100_000 - 5_000


def test_второго_такого_же_не_завести(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    before = world["coins"]
    msg, replies = _message("пет купить кот")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert world["coins"] == before, "деньги не должны списаться"
    assert "уже есть" in replies[0]


def test_без_денег_питомца_нет(world):
    world["coins"] = 10
    msg, replies = _message("пет купить дракончик")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert not world["pets"]
    assert "едостаточно" in replies[0]


def test_кормление_поднимает_сытость(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["pets"]["kot"]["hunger"] = 20
    msg, replies = _message("пет кормить кот")
    asyncio.run(bot_module.cmd_pet_feed(msg))
    assert world["stats"][-1]["hunger"] == P.gain(20, P.FEED_GAIN)


def test_повторное_кормление_упирается_в_откат(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить кот")[0]))
    before = len(world["stats"])
    msg, replies = _message("пет кормить кот")
    asyncio.run(bot_module.cmd_pet_feed(msg))
    assert len(world["stats"]) == before, "второе кормление не должно пройти"
    assert "сыт" in replies[0]


def test_ласка_поднимает_настроение_а_не_сытость(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["pets"]["kot"].update(hunger=40, mood=10)
    asyncio.run(bot_module.cmd_pet_care(_message("пет гладить кот")[0]))
    last = world["stats"][-1]
    assert last["mood"] == P.gain(10, P.PET_GAIN)
    assert last["hunger"] == 40, "гладить — не кормить"


def test_поцелуй_и_поглаживание_делят_откат(world):
    """Это одно действие разными словами, а не две механики."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_care(_message("пет гладить кот")[0]))
    before = len(world["stats"])
    msg, replies = _message("пет поцеловать кот")
    asyncio.run(bot_module.cmd_pet_care(msg))
    assert len(world["stats"]) == before
    assert "доволен" in replies[0]


def test_чужого_питомца_не_покормить(world):
    msg, replies = _message("пет кормить панда")
    asyncio.run(bot_module.cmd_pet_feed(msg))
    assert not world["stats"]
    assert "нет" in replies[0]


def test_закрепление_только_своего(world):
    msg, replies = _message("пет закрепить кот")
    asyncio.run(bot_module.cmd_pet_pin(msg))
    assert world["pinned"] == "unset", "чужого закреплять нельзя"

    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_pin(_message("пет закрепить кот")[0]))
    assert world["pinned"] == "kot"


# --- способности -----------------------------------------------------------

def test_способностей_больше_двадцати():
    """Их выбирают из готового списка при создании питомца в панели."""
    assert len(P.ABILITIES) >= 20


def test_ключи_способностей_уникальны():
    keys = [a.key for a in P.ABILITIES]
    assert len(keys) == len(set(keys))


def test_у_каждой_способности_есть_описание_и_процент():
    for ability in P.ABILITIES:
        assert ability.name and ability.description
        assert 0 < ability.percent <= 50, ability.key
        # описание обязано подставлять процент, иначе в панели будет «{p}»
        assert "{p}" in ability.description, ability.key
        assert "{p}" not in P.ability_text(ability.key)


def test_у_каждого_встроенного_питомца_есть_способность():
    for spec in P.PETS:
        assert spec.ability != P.ABILITY_NONE, spec.key
        assert spec.ability in P.ABILITY_BY_KEY, spec.key


def test_способности_встроенных_не_повторяются():
    """Иначе два питомца делали бы одно и то же и выбор терял смысл."""
    abilities = [p.ability for p in P.PETS]
    assert len(abilities) == len(set(abilities))


def test_описание_неизвестной_способности_пустое():
    assert P.ability_text("чепуха") == ""
    assert P.ability_text(P.ABILITY_NONE) == ""


def test_способность_работает_только_у_сытого_и_довольного():
    """Смысл всей механики: перестал ухаживать — потерял выгоду."""
    assert P.is_active(100, 100)
    assert not P.is_active(P.LOW_STAT - 1, 100), "голодный не помогает"
    assert not P.is_active(100, P.LOW_STAT - 1), "грустный не помогает"


@pytest.mark.parametrize("ability", [a.key for a in P.ABILITIES])
def test_каждая_способность_реально_подключена(ability):
    """Способность без обработчика — та самая «пустая безделушка», от которой
    мы и уходили: в списке она есть, а делать ничего не делает.

    Засчитываем два способа подключения: явный вызов _pet_bonus/_pet_lucky
    с этим ключом и передачу ключа как названия занятия (ферма, рыбалка и
    прочие идут через общий _passive_bonus, куда ключ приходит константой
    shop_effects.ACTIVITY_*).
    """
    import inspect
    import shop_effects as SE
    src = inspect.getsource(bot_module)
    activities = {v for k, v in vars(SE).items() if k.startswith("ACTIVITY_")}
    called = f'_pet_bonus(chat_id, user_id, "{ability}")' in src \
        or f'_pet_lucky(chat_id, user_id, {ability!r}' in src.replace("'", '"') \
        or f'"{ability}")' in src
    assert called or ability in activities, f"способность {ability} никуда не подключена"


def test_питомец_с_подходящей_способностью_даёт_прибавку(world, monkeypatch):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))  # farm
    bonus = asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm"))
    assert bonus == P.ABILITY_BY_KEY["farm"].percent


def test_голодный_питомец_прибавки_не_даёт(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    world["pets"]["homyak"]["hunger"] = 0
    assert asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm")) == 0


def test_чужая_способность_не_считается(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    assert asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "boss_damage")) == 0


def test_без_питомцев_прибавки_нет(world):
    assert asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm")) == 0


def test_компаньон_замедляет_падение_настроения():
    row = {"hunger": 100, "mood": 100,
           "last_tick_at": datetime.utcnow() - timedelta(hours=10)}
    _h, plain = bot_module._pet_now(row)
    _h2, slowed = bot_module._pet_now(row, mood_slowdown=50)
    assert slowed > plain, "с компаньоном настроение должно падать медленнее"


# --- настройка вида питомца из панели --------------------------------------

def test_выключенного_питомца_не_купить(world, monkeypatch):
    """Выключатель гасит ПРОДАЖУ: у тех, кто уже завёл, питомец остаётся."""
    world["catalog"]["kot"] = {"is_active": False}
    msg, replies = _message("пет купить кот")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "kot" not in world["pets"]
    assert world["coins"] == 100_000, "деньги не должны списаться"
    assert "недоступен" in replies[0]


def test_лимит_численности_держит(world, monkeypatch):
    world["catalog"]["kot"] = {"max_count": 2}
    monkeypatch.setattr(bot_module.db, "count_pet_owners", _returns(2), raising=False)
    msg, replies = _message("пет купить кот")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "kot" not in world["pets"]
    assert "разобрали" in replies[0]


def test_под_лимитом_питомец_покупается(world, monkeypatch):
    world["catalog"]["kot"] = {"max_count": 5}
    monkeypatch.setattr(bot_module.db, "count_pet_owners", _returns(1), raising=False)
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    assert "kot" in world["pets"]


def test_без_настройки_ограничений_нет(world):
    """Вид, про который в панели ничего не трогали, продаётся как обычно."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    assert "kot" in world["pets"]


def test_правка_вида_бьёт_только_по_разрешённым_полям():
    """В update_pet_spec приходят данные из панели: подстановка произвольного
    имени колонки в SQL была бы дырой."""
    import inspect
    src = inspect.getsource(bot_module.db.update_pet_spec)
    assert "allowed" in src
    assert "if column not in allowed" in src


def test_все_команды_питомцев_начинаются_на_пет_или_питомец():
    for trigger in bot_module.PET_LIST_TRIGGERS | bot_module.PET_UNPIN_TRIGGERS:
        assert trigger.lstrip("!").startswith(("пет", "питом")), trigger
    for pattern in (bot_module.PET_BUY_RE, bot_module.PET_FEED_RE,
                    bot_module.PET_CARE_RE, bot_module.PET_NAME_RE,
                    bot_module.PET_PIN_RE, bot_module.PET_SHOP_RE):
        assert "пет|питомец" in pattern.pattern, pattern.pattern
