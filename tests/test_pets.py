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
    # answer — объявление в чат без цитаты (раздача корма). Стаб такой же:
    # тестам важен текст, а не то, ответом он ушёл или отдельным сообщением.
    object.__setattr__(m, "answer", reply)
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
    # food — корм в инвентаре: кормление тратит его, и без запаса ни один тест
    # про кормёжку не проехал бы дальше первой строки. rerolls — память о
    # платных сменах способности, переживающая продажу.
    state = {"coins": 100_000, "pets": {}, "stats": [], "pinned": "unset",
             "food": 50, "elixirs": 0, "rerolls": {}, "logs": []}

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

    async def add_pet(chat_id, user_id, key, ts, rerolls=0):
        if key in state["pets"]:
            return False
        state["pets"][key] = {"pet_key": key, "pet_name": None, "hunger": 100,
                              "mood": 100, "last_tick_at": ts, "last_fed_at": None,
                              "last_care_at": None, "last_walk_at": None,
                              "bought_at": ts,
                              "ability": None, "ability2": None, "evolved": False,
                              "ability_rerolls": int(rerolls),
                              "xp": 0, "xp_tick_at": ts}
        return True

    async def delete_pet(chat_id, user_id, key):
        return state["pets"].pop(key, None) is not None

    async def remember_pet_rerolls(chat_id, user_id, key, rerolls):
        state["rerolls"][key] = max(state["rerolls"].get(key, 0), int(rerolls))

    async def recall_pet_rerolls(chat_id, user_id, key):
        return state["rerolls"].get(key, 0)

    # Инвентарь тестов держит два ключа: корм и эликсир эволюции. Оба
    # хранятся отдельными числами, потому что тесты читают и правят их прямо
    # (world["food"], world["elixirs"]).
    _SLOTS = {P.FOOD_ITEM_KEY: "food", "elixir": "elixirs"}

    async def get_inventory_quantity(chat_id, user_id, item_key):
        slot = _SLOTS.get(item_key)
        return state[slot] if slot else 0

    async def remove_inventory_item(chat_id, user_id, item_key, amount=1):
        slot = _SLOTS.get(item_key)
        if slot is None or state[slot] < amount:
            return False
        state[slot] -= amount
        return True

    async def add_inventory_item(chat_id, user_id, item_key, amount=1):
        slot = _SLOTS.get(item_key)
        if slot:
            state[slot] += amount

    async def evolve_pet(chat_id, user_id, key, second_ability, now):
        row = state["pets"].get(key)
        if row is None or row.get("evolved"):
            return False
        row["evolved"] = True
        row["ability2"] = second_ability
        row["xp"] = 0
        row["xp_tick_at"] = now
        return True

    async def get_profile_card(chat_id, user_id):
        return {"pinned_pet": state["pinned"] if state["pinned"] != "unset" else None}

    async def add_log(kind, **kwargs):
        state["logs"].append((kind, kwargs))

    async def set_pet_ability(chat_id, user_id, key, ability, rerolls):
        row = state["pets"].get(key)
        if row is None:
            return False
        row["ability"] = ability
        row["ability_rerolls"] = rerolls
        return True

    async def set_pet_stats(chat_id, user_id, key, hunger, mood, xp, ts,
                            fed_at=None, care_at=None, walk_at=None):
        state["stats"].append({"key": key, "hunger": hunger, "mood": mood, "xp": xp})
        row = state["pets"][key]
        row.update(hunger=hunger, mood=mood, last_tick_at=ts, xp=xp, xp_tick_at=ts)
        if fed_at:
            row["last_fed_at"] = fed_at
        if care_at:
            row["last_care_at"] = care_at
        if walk_at:
            row["last_walk_at"] = walk_at

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

    async def get_shop_item(chat_id, key):
        return {"item_key": key, "name": key, "emoji": "🎁"}

    for name, fn in [("get_wallet", get_wallet), ("try_spend_coins", try_spend_coins),
                     ("get_shop_item", get_shop_item),
                     ("seed_default_shop_items", _returns(0)),
                     ("add_coins", add_coins), ("list_pets", list_pets),
                     ("get_pet", get_pet), ("add_pet", add_pet),
                     ("delete_pet", delete_pet),
                     ("remember_pet_rerolls", remember_pet_rerolls),
                     ("recall_pet_rerolls", recall_pet_rerolls),
                     ("get_inventory_quantity", get_inventory_quantity),
                     ("evolve_pet", evolve_pet),
                     ("remove_inventory_item", remove_inventory_item),
                     ("add_inventory_item", add_inventory_item),
                     ("get_profile_card", get_profile_card),
                     ("seed_extra_shop_items", _returns(0)),
                     ("set_pet_stats", set_pet_stats), ("set_pinned_pet", set_pinned_pet),
                     ("rename_pet", _noop), ("add_log", add_log),
                     ("set_pet_ability", set_pet_ability),
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


def test_цена_смены_способности_не_ниже_пола():
    assert P.ability_reroll_price(0, 0) == P.ABILITY_REROLL_FLOOR
    assert P.ability_reroll_price(100, 0) == P.ABILITY_REROLL_FLOOR


def test_цена_смены_способности_растёт_от_цены_вида():
    cheap = P.ability_reroll_price(10_000, 0)
    expensive = P.ability_reroll_price(90_000, 0)
    assert expensive > cheap


def test_цена_смены_способности_растёт_с_каждой_сменой():
    prices = [P.ability_reroll_price(30_000, n) for n in range(4)]
    assert prices == sorted(prices) and len(set(prices)) == len(prices)



# --- уровень питомца ---------------------------------------------------------

def test_порогов_ровно_по_числу_уровней():
    assert len(P.LEVEL_XP_THRESHOLDS) == P.MAX_PET_LEVEL
    assert P.LEVEL_XP_THRESHOLDS[0] == 0
    assert list(P.LEVEL_XP_THRESHOLDS) == sorted(P.LEVEL_XP_THRESHOLDS)


def test_уровень_по_опыту_растёт_монотонно():
    assert P.level_for_xp(0) == 1
    assert P.level_for_xp(-5) == 1, "отрицательного опыта не бывает, но не должно падать"
    for threshold, level in zip(P.LEVEL_XP_THRESHOLDS, range(1, P.MAX_PET_LEVEL + 1)):
        assert P.level_for_xp(threshold) == level
        if threshold:
            assert P.level_for_xp(threshold - 1) == level - 1


def test_опыт_не_растёт_выше_порога_макс_уровня():
    assert P.xp_now(0, 1_000_000) == P.LEVEL_XP_THRESHOLDS[-1]
    assert P.level_for_xp(P.xp_now(0, 1_000_000)) == P.MAX_PET_LEVEL


def test_разовая_прибавка_тоже_капается_потолком():
    """Иначе цифра в базе росла бы бесконечно и после макс. уровня — молча,
    без влияния на уровень, но нарушая заявленный инвариант."""
    assert P.xp_add(P.LEVEL_XP_THRESHOLDS[-1], P.XP_BONUS_FEED) == P.LEVEL_XP_THRESHOLDS[-1]
    assert P.xp_add(0, -5) == 0, "отрицательной прибавки не бывает"


def test_опыт_без_времени_не_меняется():
    assert P.xp_now(123, 0) == 123
    assert P.xp_now(123, -5) == 123, "часы бота и базы могут разъехаться"


def test_прогресс_уровня_считает_от_начала_уровня():
    threshold = P.LEVEL_XP_THRESHOLDS[2]   # начало уровня 3
    level, gained, needed = P.level_progress(threshold + 10)
    assert level == 3
    assert gained == 10
    assert needed == P.LEVEL_XP_THRESHOLDS[3] - threshold


def test_прогресс_на_макс_уровне_не_делит_на_ноль():
    level, gained, needed = P.level_progress(P.LEVEL_XP_THRESHOLDS[-1] + 500)
    assert level == P.MAX_PET_LEVEL
    assert needed == gained   # бар просто полон, а не N/0


def test_бонус_способности_растёт_с_уровнем_и_на_первом_нулевой():
    assert P.level_ability_bonus(1) == 0
    assert P.level_ability_bonus(0) == 0, "уровня ниже первого не бывает"
    assert P.level_ability_bonus(P.MAX_PET_LEVEL) > P.level_ability_bonus(5) > 0


def test_текст_способности_на_уровне_учитывает_бонус():
    base = P.ability_text("farm")
    boosted = P.ability_text_at_level("farm", P.MAX_PET_LEVEL)
    assert base != boosted
    assert str(P.ABILITY_BY_KEY["farm"].percent + P.level_ability_bonus(P.MAX_PET_LEVEL)) in boosted


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
    import game_actions
    # Смотрим оба модуля: правила питомцев уехали в game_actions (панель не
    # может импортировать bot.py — подняла бы второго бота), и способность,
    # подключённая там, подключена по-настоящему. Ограничься сторож одним
    # bot.py — он объявил бы «безделушкой» работающего «Компаньона».
    src = inspect.getsource(bot_module) + inspect.getsource(game_actions)
    activities = {v for k, v in vars(SE).items() if k.startswith("ACTIVITY_")}
    # Третий способ — именованная константа (ABILITY_PET_MOOD = "pet_mood"):
    # ключ участвует в логике, просто не литералом в месте вызова. Само по себе
    # объявление подключением НЕ считается — иначе сторож пропустил бы ровно ту
    # «пустую безделушку», ради которой он и написан: требуем, чтобы имя
    # константы где-то ещё и использовалось.
    import re as _re
    named = _re.search(rf'^([A-Z_]+) = "{ability}"$', src, _re.MULTILINE)
    via_constant = bool(named) and len(_re.findall(rf'\b{named.group(1)}\b', src)) > 1
    called = f'_pet_bonus(chat_id, user_id, "{ability}")' in src \
        or f'_pet_lucky(chat_id, user_id, {ability!r}' in src.replace("'", '"') \
        or f'"{ability}")' in src \
        or via_constant
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


# --- смена способности своего питомца ---------------------------------------

def _ability_num(key):
    return next(i for i, a in enumerate(P.ABILITIES, start=1) if a.key == key)


def test_способность_без_номера_только_показывает_цену(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    before = world["coins"]
    msg, replies = _message("пет способность хомяк")
    asyncio.run(bot_module.cmd_pet_ability_reroll(msg))
    assert world["coins"] == before, "без номера деньги не должны списываться"
    assert world["pets"]["homyak"]["ability"] is None, "без номера способность не меняется"
    assert "стоит" in replies[0]


def test_смена_способности_списывает_и_меняет_бонус(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))  # farm
    before = world["coins"]
    num = _ability_num("discount_shop")
    msg, replies = _message(f"пет способность хомяк {num}")
    asyncio.run(bot_module.cmd_pet_ability_reroll(msg))
    assert world["pets"]["homyak"]["ability"] == "discount_shop"
    price = P.ability_reroll_price(P.BY_KEY["homyak"].price, 0)
    assert world["coins"] == before - price
    assert asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm")) == 0, \
        "старая способность вида больше не должна давать бонус"
    assert asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "discount_shop")) == \
        P.ABILITY_BY_KEY["discount_shop"].percent


def test_повторная_смена_дороже(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    num1 = _ability_num("discount_shop")
    asyncio.run(bot_module.cmd_pet_ability_reroll(_message(f"пет способность хомяк {num1}")[0]))
    before = world["coins"]
    num2 = _ability_num("lootbox")
    asyncio.run(bot_module.cmd_pet_ability_reroll(_message(f"пет способность хомяк {num2}")[0]))
    price_first = P.ability_reroll_price(P.BY_KEY["homyak"].price, 0)
    price_second = P.ability_reroll_price(P.BY_KEY["homyak"].price, 1)
    assert world["coins"] == before - price_second
    assert price_second > price_first, "вторая смена ЭТОГО питомца должна быть дороже первой"


def test_нельзя_задублировать_способность_у_другого_питомца(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))  # farm
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))    # daily_bonus
    num = _ability_num("farm")
    msg, replies = _message(f"пет способность кот {num}")
    asyncio.run(bot_module.cmd_pet_ability_reroll(msg))
    assert world["pets"]["kot"]["ability"] is None, "бонус одного вида не должен удваиваться"
    assert "складываются" in replies[0]


def test_смена_способности_не_трогает_вид_в_каталоге(world):
    """Другие хозяева того же вида и сам вид в каталоге не должны меняться."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    num = _ability_num("lootbox")
    asyncio.run(bot_module.cmd_pet_ability_reroll(_message(f"пет способность хомяк {num}")[0]))
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    assert specs["homyak"].ability == "farm"


# --- уровень: команды -------------------------------------------------------

def test_кормление_даёт_опыт(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    assert world["pets"]["homyak"]["xp"] == 0
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить хомяк")[0]))
    assert world["pets"]["homyak"]["xp"] == P.XP_BONUS_FEED


def test_ласка_тоже_даёт_опыт(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    asyncio.run(bot_module.cmd_pet_care(_message("пет гладить хомяк")[0]))
    assert world["pets"]["homyak"]["xp"] == P.XP_BONUS_CARE


def test_повторное_кормление_в_откате_опыт_не_копит(world):
    """Заблокированное действие не должно быть дырой для бесконечного опыта."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить хомяк")[0]))
    xp_after_first = world["pets"]["homyak"]["xp"]
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить хомяк")[0]))
    assert world["pets"]["homyak"]["xp"] == xp_after_first


def test_повышение_уровня_объявляется_в_ответе(world, monkeypatch):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    world["pets"]["homyak"]["xp"] = P.LEVEL_XP_THRESHOLDS[1] - P.XP_BONUS_FEED
    msg, replies = _message("пет кормить хомяк")
    asyncio.run(bot_module.cmd_pet_feed(msg))
    assert bot_module._pet_level(world["pets"]["homyak"]) == 2
    assert "Новый уровень" in replies[0]


def test_прокачанный_питомец_даёт_бонус_больше_базового(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))  # farm
    world["pets"]["homyak"]["xp"] = P.LEVEL_XP_THRESHOLDS[-1]
    bonus = asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm"))
    assert bonus == P.ABILITY_BY_KEY["farm"].percent + P.level_ability_bonus(P.MAX_PET_LEVEL)


def test_опыт_растёт_пассивно_от_времени(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    world["pets"]["homyak"]["xp_tick_at"] = datetime.utcnow() - timedelta(hours=10)
    assert bot_module._pet_xp_now(world["pets"]["homyak"]) == P.XP_PER_HOUR * 10


def test_старый_питомец_не_прыгает_на_макс_уровень(world):
    """xp_tick_at — своя метка, отдельная от last_tick_at покупки: у мигрированных
    строк её выставляют на «сейчас» отдельно, а не считают с даты покупки."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить хомяк")[0]))
    world["pets"]["homyak"]["last_tick_at"] = datetime.utcnow() - timedelta(days=90)
    assert bot_module._pet_level(world["pets"]["homyak"]) == 1


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
    # Проверяем ПОВЕДЕНИЕ, а не текст шаблона: шаблоны собираются через
    # ru_text.rx и содержат классы [еЕёЁ] вместо голых букв — сравнение со
    # строкой проверяло бы способ записи, а не саму привязку к слову.
    for pattern, sample in ((bot_module.PET_BUY_RE, "купить кот"),
                            (bot_module.PET_FEED_RE, "кормить кот"),
                            (bot_module.PET_CARE_RE, "гладить кот"),
                            (bot_module.PET_NAME_RE, "назвать кот Барсик"),
                            (bot_module.PET_PIN_RE, "закрепить кот"),
                            (bot_module.PET_SHOP_RE, "каталог")):
        assert pattern.match(f"пет {sample}"), pattern.pattern
        assert pattern.match(f"питомец {sample}"), pattern.pattern
        assert not pattern.match(f"мой пет {sample}"), pattern.pattern


# --- массовые команды ------------------------------------------------------
#
# Регулярки проверяются ОТДЕЛЬНО от обработчиков: тесты зовут обработчики
# напрямую и роутер не задействуют, поэтому коллизия «пет покормить все»
# с одиночной командой прошла бы весь набор незамеченной и упала бы в чате.

@pytest.mark.parametrize("text", [
    "пет покормить все", "пет кормить всех", "пет покормить всем",
    "питомцы кормить все", "!пет покормить все",
])
def test_массовое_кормление_не_путается_с_одиночным(text):
    assert bot_module.PET_FEED_ALL_RE.match(text), text
    assert bot_module.PET_FEED_RE.match(text) is None, (
        "«все» уехало бы в ключ питомца и бот ответил бы «такого питомца нет»")


@pytest.mark.parametrize("text", [
    "пет гладить все", "пет обнять всех", "пет поцеловать всем",
    "пет обнимать все", "питомец погладить все",
])
def test_массовая_ласка_не_путается_с_одиночной(text):
    assert bot_module.PET_CARE_ALL_RE.match(text), text
    assert bot_module.PET_CARE_RE.match(text) is None, text


@pytest.mark.parametrize("text, key", [
    ("пет кормить кот", "кот"),
    ("пет кормить всеволод", "всеволод"),   # «все» только целиком, не куском
])
def test_одиночное_кормление_по_ключу_живо(text, key):
    match = bot_module.PET_FEED_RE.match(text)
    assert match and match.group(1) == key


def test_обнять_понимается_и_поштучно():
    match = bot_module.PET_CARE_RE.match("пет обнять кот")
    assert match and match.group(1) == "обнять" and match.group(2) == "кот"


def test_массовое_кормление_кормит_всех(world):
    for key in ("кот", "пес", "хомяк"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    for row in world["pets"].values():
        row["hunger"] = 10
    msg, replies = _message("пет покормить все")
    asyncio.run(bot_module.cmd_pet_feed_all(msg))
    assert len(world["stats"]) == 3
    assert all(r["hunger"] == P.gain(10, P.FEED_GAIN) for r in world["pets"].values())
    assert world["food"] == 50 - 3, "по одному корму за каждого"


def test_массовое_кормление_при_нехватке_корма_кормит_частично(world):
    for key in ("кот", "пес", "хомяк"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    world["food"] = 2
    msg, replies = _message("пет покормить все")
    asyncio.run(bot_module.cmd_pet_feed_all(msg))
    assert len(world["stats"]) == 2, "накормлены только те, на кого хватило"
    assert world["food"] == 0
    assert "2 из 3" in replies[0]
    assert "не хватило" in replies[0]


def test_массовое_кормление_без_корма_никого_не_трогает(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["food"] = 0
    msg, replies = _message("пет покормить все")
    asyncio.run(bot_module.cmd_pet_feed_all(msg))
    assert not world["stats"]
    assert "Корма нет" in replies[0]


def test_массовое_кормление_пропускает_тех_кто_на_откате(world):
    for key in ("кот", "пес"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить кот")[0]))
    before = len(world["stats"])
    msg, replies = _message("пет покормить все")
    asyncio.run(bot_module.cmd_pet_feed_all(msg))
    assert len(world["stats"]) == before + 1, "кот на откате — покормлен только пёс"
    assert "1 из 1" in replies[0]
    assert "Ждут отката" in replies[0]


def test_массовая_ласка_поднимает_настроение_всем(world):
    for key in ("кот", "пес"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    for row in world["pets"].values():
        row["mood"] = 10
    msg, replies = _message("пет обнять все")
    asyncio.run(bot_module.cmd_pet_care_all(msg))
    assert all(r["mood"] == P.gain(10, P.HUG_GAIN) for r in world["pets"].values())
    assert "обняли" in replies[0]
    assert world["food"] == 50, "ласка бесплатна"


def test_массовая_ласка_делит_откат_с_поштучной(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_care(_message("пет гладить кот")[0]))
    before = len(world["stats"])
    asyncio.run(bot_module.cmd_pet_care_all(_message("пет обнять все")[0]))
    assert len(world["stats"]) == before, "откат общий на все слова ласки"


def test_массовая_команда_без_питомцев_подсказывает_каталог(world):
    msg, replies = _message("пет покормить все")
    asyncio.run(bot_module.cmd_pet_feed_all(msg))
    assert "каталог" in replies[0]


# --- корм ------------------------------------------------------------------

def test_кормление_тратит_корм(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить кот")[0]))
    assert world["food"] == 49


def test_без_корма_питомец_не_кормится_и_откат_не_тратится(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["food"] = 0
    msg, replies = _message("пет кормить кот")
    asyncio.run(bot_module.cmd_pet_feed(msg))
    assert not world["stats"], "статы не тронуты"
    assert world["pets"]["kot"]["last_fed_at"] is None, "откат не должен сгорать впустую"
    assert "Корма нет" in replies[0]


def test_корм_есть_в_товарах_для_магазина():
    keys = [row[0] for row in P.SHOP_ITEMS]
    assert P.FOOD_ITEM_KEY in keys
    for _key, name, price, description, emoji in P.SHOP_ITEMS:
        assert name and description and emoji and price > 0


def test_пет_корм_без_числа_только_показывает(world):
    msg, replies = _message("пет корм")
    asyncio.run(bot_module.cmd_pet_food_buy(msg))
    assert str(P.FOOD_ITEM_PRICE) in replies[0]
    assert world["coins"] == 100_000, "показ цены денег не трогает"


# --- продажа ---------------------------------------------------------------

def test_цена_продажи_ниже_цены_покупки():
    for spec in P.PETS:
        assert 0 < P.sell_price(spec.price) < spec.price, spec.key


def test_продажа_без_подтверждения_только_показывает_цену(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    before = world["coins"]
    msg, replies = _message("пет продать кот")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "kot" in world["pets"], "без «да» питомец остаётся"
    assert world["coins"] == before
    assert str(P.sell_price(P.BY_KEY["kot"].price)) in replies[0]


def test_продажа_с_подтверждением_отдаёт_половину(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    before = world["coins"]
    asyncio.run(bot_module.cmd_pet_sell(_message("пет продать кот да")[0]))
    assert "kot" not in world["pets"]
    assert world["coins"] == before + P.sell_price(P.BY_KEY["kot"].price)


def test_продажа_снимает_закреп(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_pin(_message("пет закрепить кот")[0]))
    assert world["pinned"] == "kot"
    asyncio.run(bot_module.cmd_pet_sell(_message("пет продать кот да")[0]))
    assert world["pinned"] is None


def test_продажа_не_снимает_чужой_закреп(world):
    for key in ("кот", "пес"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    asyncio.run(bot_module.cmd_pet_pin(_message("пет закрепить пес")[0]))
    asyncio.run(bot_module.cmd_pet_sell(_message("пет продать кот да")[0]))
    assert world["pinned"] == "pes"


def test_счётчик_смен_способности_переживает_продажу(world):
    """Иначе продать и купить заново было бы дешевле очередной смены."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["pets"]["kot"]["ability_rerolls"] = 3
    asyncio.run(bot_module.cmd_pet_sell(_message("пет продать кот да")[0]))
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    assert world["pets"]["kot"]["ability_rerolls"] == 3
    price_now = P.ability_reroll_price(P.BY_KEY["kot"].price, 3)
    assert price_now > P.ability_reroll_price(P.BY_KEY["kot"].price, 0)


def test_нельзя_продать_чужого(world):
    msg, replies = _message("пет продать кот да")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "нет" in replies[0]
    assert world["coins"] == 100_000


def test_продажа_замороженного_счёта_не_проходит(world, monkeypatch):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    before = world["coins"]
    msg, replies = _message("пет продать кот да")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "kot" in world["pets"]
    assert world["coins"] == before


def test_цена_продажи_идёт_от_цены_каталога_чата(world):
    """Каталог правит админ: продавать по прайсу из кода там, где вид
    подешевел, значило бы печатать монеты."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["catalog"]["kot"] = {"price": 1_000}
    before = world["coins"]
    asyncio.run(bot_module.cmd_pet_sell(_message("пет продать кот да")[0]))
    assert world["coins"] == before + 500, "половина цены КАТАЛОГА, а не pets.PETS"


def test_продажа_предупреждает_о_купленной_способности(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["pets"]["kot"]["ability"] = "casino_win"
    world["pets"]["kot"]["ability_rerolls"] = 2
    msg, replies = _message("пет продать кот")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "способность" in replies[0]
    assert "счётчик смен (2)" in replies[0]


def test_продать_единственного_можно_без_ключа(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    msg, replies = _message("пет продать")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "kot" in world["pets"], "без «да» питомец остаётся"
    assert replies and "продажа" in replies[0].casefold()


def test_продать_без_ключа_при_нескольких_просит_уточнить(world):
    for key in ("кот", "пес"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    msg, replies = _message("пет продать")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert len(world["pets"]) == 2
    assert "укажите" in replies[0]


def test_купить_корм_не_отвечает_что_такого_питомца_нет(world):
    msg, replies = _message("пет купить корм")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "пет корм" in replies[0]
    assert world["coins"] == 100_000


# --- раздача корма админом -------------------------------------------------

@pytest.fixture
def grant_world(world, monkeypatch):
    """world плюс метка недельного отката и список владельцев питомцев."""
    state = world
    state["owners"] = [111, 222, 333]
    state["data"] = {}
    state["granted"] = []

    async def list_pet_owners(chat_id):
        return list(state["owners"])

    async def add_inventory_item_bulk(chat_id, user_ids, item_key, amount=1):
        state["granted"].append((list(user_ids), item_key, amount))
        return len(user_ids)

    async def get_data(key):
        value = state["data"].get(key)
        return {"data_key": key, "data_value": value} if value is not None else None

    async def set_data(key, value, updated_by=None):
        state["data"][key] = value

    for name, fn in [("list_pet_owners", list_pet_owners),
                     ("add_inventory_item_bulk", add_inventory_item_bulk),
                     ("get_data", get_data), ("set_data", set_data)]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)
    # Уровень админа: команда закрыта, и без этого не проехать дальше проверки.
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: True, raising=False)
    return state


def test_раздача_выдаёт_всем_владельцам_питомцев(grant_world):
    msg, replies = _message("пет раздать")
    asyncio.run(bot_module.cmd_pet_food_grant(msg))
    assert grant_world["granted"] == [([111, 222, 333], P.FOOD_ITEM_KEY,
                                       P.FOOD_GRANT_AMOUNT)]
    assert str(P.FOOD_GRANT_AMOUNT) in replies[0]


def test_повторная_раздача_в_ту_же_неделю_не_проходит(grant_world):
    asyncio.run(bot_module.cmd_pet_food_grant(_message("пет раздать")[0]))
    msg, replies = _message("пет раздать корм")
    asyncio.run(bot_module.cmd_pet_food_grant(msg))
    assert len(grant_world["granted"]) == 1, "второй раздачи быть не должно"
    assert "через" in replies[0]


def test_через_неделю_раздача_снова_проходит(grant_world):
    asyncio.run(bot_module.cmd_pet_food_grant(_message("пет раздать")[0]))
    key = next(iter(grant_world["data"]))
    old = datetime.utcnow() - timedelta(days=P.FOOD_GRANT_COOLDOWN_DAYS, minutes=1)
    grant_world["data"][key] = old.isoformat()
    asyncio.run(bot_module.cmd_pet_food_grant(_message("пет раздать")[0]))
    assert len(grant_world["granted"]) == 2


def test_пустой_чат_не_тратит_недельный_лимит(grant_world):
    grant_world["owners"] = []
    msg, replies = _message("пет раздать")
    asyncio.run(bot_module.cmd_pet_food_grant(msg))
    assert not grant_world["granted"]
    assert not grant_world["data"], "метку ставить не за что — раздавать было некому"
    assert "питомцев ни у кого нет" in replies[0]


def test_метка_ставится_до_раздачи(grant_world, monkeypatch):
    """Если выдача упадёт на середине, часть людей корм уже получит — повтор
    выдал бы им вторую порцию. Метка должна пережить падение."""
    async def boom(*args, **kwargs):
        raise RuntimeError("база отвалилась")

    monkeypatch.setattr(bot_module.db, "add_inventory_item_bulk", boom, raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(bot_module.cmd_pet_food_grant(_message("пет раздать")[0]))
    assert grant_world["data"], "метка должна стоять, иначе повтор задвоит корм"


def test_не_админ_ничего_не_раздаёт(grant_world, monkeypatch):
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: False, raising=False)
    monkeypatch.setattr(bot_module, "get_level", lambda uid: 0, raising=False)
    msg, replies = _message("пет раздать")
    asyncio.run(bot_module.cmd_pet_food_grant(msg))
    assert not grant_world["granted"]
    assert not replies, "постороннему команда просто не отвечает"


def test_битая_метка_не_блокирует_раздачу(grant_world):
    grant_world["data"][f"{bot_module.PET_FOOD_GRANT_KEY}:{CHAT_ID}"] = "не-дата"
    asyncio.run(bot_module.cmd_pet_food_grant(_message("пет раздать")[0]))
    assert len(grant_world["granted"]) == 1


def test_раздача_требует_уровня_админа():
    """Проверяется ЭФФЕКТИВНЫЙ уровень, а не только запись в реестре: доступ
    считает required_level, и её фолбэк — единственное, что отделяет недельную
    раздачу от «любой участник может нажать». У всех остальных команд питомцев
    уровень 0, так что этот путь тут задействован впервые."""
    assert bot_module.required_level("pet_food_grant") == bot_module.LEVEL_ADMIN
    assert bot_module.COMMAND_REGISTRY["pet_food_grant"]["level"] == bot_module.LEVEL_ADMIN


# --- «Компаньон» (панда) ----------------------------------------------------
#
# Способность обещает «настроение всех ваших питомцев падает на 30% медленнее».
# Раньше поблажка применялась ровно в одном месте — при отрисовке списка, —
# то есть меняла показанное число и больше ничего: способности не платили, а
# кормление и ласка записывали в базу настроение, посчитанное БЕЗ неё, стирая
# накопленное при каждом взаимодействии.

def _panda_world(world, hours: float):
    """Панда и кот у одного хозяина, оба не тронуты hours часов."""
    for key in ("панда", "кот"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    long_ago = datetime.utcnow() - timedelta(hours=hours)
    for row in world["pets"].values():
        row["last_tick_at"] = long_ago
        row["xp_tick_at"] = long_ago
    return world


def test_компаньон_замедляет_падение_настроения(world):
    _panda_world(world, hours=17)
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    rows = list(world["pets"].values())
    slowdown = bot_module._pet_mood_slowdown(rows, specs)
    assert slowdown > 0, "панда должна давать поблажку"
    without = bot_module._pet_now(world["pets"]["kot"])[1]
    with_panda = bot_module._pet_now(world["pets"]["kot"], slowdown)[1]
    assert with_panda > without


def test_кормление_не_стирает_поблажку_компаньона(world):
    """Настроение при кормлении БАНКУЕТСЯ: посчитанное без поблажки затирало
    бы её накопленный эффект при каждом кормлении."""
    _panda_world(world, hours=17)
    asyncio.run(bot_module.cmd_pet_feed(_message("пет кормить кот")[0]))
    banked = world["pets"]["kot"]["mood"]
    naive = bot_module.pets_catalog.mood_now(100, 17)
    assert banked > naive, "в базу ушло настроение с учётом поблажки"


def test_ласка_не_стирает_поблажку_компаньона(world):
    _panda_world(world, hours=17)
    asyncio.run(bot_module.cmd_pet_care(_message("пет гладить кот")[0]))
    banked = world["pets"]["kot"]["mood"]
    naive = bot_module.pets_catalog.gain(
        bot_module.pets_catalog.mood_now(100, 17), bot_module.pets_catalog.PET_GAIN)
    assert banked > naive


def test_массовая_ласка_тоже_учитывает_компаньона(world):
    _panda_world(world, hours=17)
    asyncio.run(bot_module.cmd_pet_care_all(_message("пет обнять все")[0]))
    naive = bot_module.pets_catalog.gain(
        bot_module.pets_catalog.mood_now(100, 17), bot_module.pets_catalog.HUG_GAIN)
    assert world["pets"]["kot"]["mood"] > naive


def test_массовое_кормление_тоже_учитывает_компаньона(world):
    """_feed_pet банкует и настроение тоже — значит поблажка нужна и здесь."""
    _panda_world(world, hours=17)
    asyncio.run(bot_module.cmd_pet_feed_all(_message("пет покормить все")[0]))
    naive = bot_module.pets_catalog.mood_now(100, 17)
    assert world["pets"]["kot"]["mood"] > naive


def test_компаньон_вытягивает_загрустившую_способность(world):
    """Ради этого панда и заводится: без поблажки кот загрустил и его
    способность спит, с поблажкой — ещё работает."""
    # Часами этого не добиться: сытость падает быстрее настроения и упирается
    # в порог первой, поэтому загрустившего, но сытого кота задаём прямо.
    _panda_world(world, hours=6)
    world["pets"]["kot"]["mood"] = 45
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    rows = list(world["pets"].values())
    kot = world["pets"]["kot"]
    assert not P.is_active(*bot_module._pet_now(kot)), "без поблажки — спит"
    slowdown = bot_module._pet_mood_slowdown(rows, specs)
    assert P.is_active(*bot_module._pet_now(kot, slowdown)), "с поблажкой — работает"
    bonus = asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "daily_bonus"))
    assert bonus > 0, "и способность обязана реально платить, а не только светиться"


def test_голодный_компаньон_поблажки_не_даёт(world):
    """Способность работает, только пока сам питомец сыт и доволен."""
    _panda_world(world, hours=1)
    world["pets"]["panda"]["hunger"] = 0
    world["pets"]["panda"]["mood"] = 0
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    assert bot_module._pet_mood_slowdown(list(world["pets"].values()), specs) == 0


def test_без_компаньона_поблажки_нет(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    assert bot_module._pet_mood_slowdown(list(world["pets"].values()), specs) == 0


# --- прогулка ---------------------------------------------------------------

def _force_walk_roll(monkeypatch, item: bool, coins: int = 200):
    """Прогулка разыгрывает две вещи одним random.randint: попадёт ли она в
    шанс предмета и сколько монет. Обе ветки надо проверять отдельно, иначе
    тест ловит их через раз и поломка любой выглядит как мигание."""
    calls = {"n": 0}

    def fake_randint(a, b):
        calls["n"] += 1
        if calls["n"] == 1:          # бросок на предмет: 1..100
            return 1 if item else 100
        return coins                  # бросок на монеты

    monkeypatch.setattr(bot_module.random, "randint", fake_randint)


def test_прогулка_приносит_предмет(world, monkeypatch):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    _force_walk_roll(monkeypatch, item=True)
    before = world["coins"]
    msg, replies = _message("пет гулять кот")
    asyncio.run(bot_module.cmd_pet_walk(msg))
    assert world["coins"] == before, "предмет вместо монет"
    assert "🎁" in replies[0], "находка названа в ответе"
    assert world["pets"]["kot"]["last_walk_at"] is not None


def test_прогулка_приносит_монеты(world, monkeypatch):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    _force_walk_roll(monkeypatch, item=False, coins=250)
    before = world["coins"]
    msg, replies = _message("пет гулять кот")
    asyncio.run(bot_module.cmd_pet_walk(msg))
    expected = P.walk_coins(1, 250)
    assert world["coins"] == before + expected
    assert str(expected) in replies[0]


def test_прогулка_упирается_в_откат(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_walk(_message("пет гулять кот")[0]))
    before = len(world["stats"])
    msg, replies = _message("пет гулять кот")
    asyncio.run(bot_module.cmd_pet_walk(msg))
    assert len(world["stats"]) == before
    assert "нагулялся" in replies[0]


def test_голодный_питомец_гулять_не_идёт(world):
    """То же правило, что и у способностей: заброшенный питомец бесполезен."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["pets"]["kot"]["hunger"] = 0
    msg, replies = _message("пет гулять кот")
    asyncio.run(bot_module.cmd_pet_walk(msg))
    assert world["pets"]["kot"]["last_walk_at"] is None
    assert "покормите" in replies[0]


def test_прогулка_тратит_сытость(world):
    """Иначе она была бы бесплатным источником монет, не связанным с кормом."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_walk(_message("пет гулять кот")[0]))
    assert world["pets"]["kot"]["hunger"] == 100 - P.WALK_HUNGER_COST
    assert world["pets"]["kot"]["mood"] == 100, "настроение и так на максимуме"


def test_прогулка_даёт_опыт(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    asyncio.run(bot_module.cmd_pet_walk(_message("пет гулять кот")[0]))
    assert world["pets"]["kot"]["xp"] >= P.WALK_XP_BONUS


def test_массовая_прогулка_выгуливает_всех(world):
    for key in ("кот", "пес", "хомяк"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    asyncio.run(bot_module.cmd_pet_walk_all(_message("пет гулять все")[0]))
    assert all(r["last_walk_at"] is not None for r in world["pets"].values())


def test_монеты_за_прогулку_растут_с_уровнем():
    assert P.walk_coins(1, 200) == 200
    assert P.walk_coins(5, 200) > P.walk_coins(1, 200)
    assert P.walk_coins(1, 0) >= 1, "меньше монетки не бывает"


def test_у_каждого_вида_есть_что_принести():
    for spec in P.PETS:
        finds = P.walk_finds(spec.key)
        assert finds, spec.key
        for find in finds:
            assert find.text and find.item_key


def test_неизвестному_виду_достаётся_общий_список():
    """Вида, заведённого админом, в списке находок нет — прогулка обязана
    работать и для него."""
    assert P.walk_finds("ezhik") == P.WALK_FINDS_DEFAULT


# --- эволюция ---------------------------------------------------------------

def _maxed(world, key="kot"):
    """Питомец максимального уровня — с него и начинается эволюция."""
    row = world["pets"][key]
    row["xp"] = P.LEVEL_XP_THRESHOLDS[-1]
    row["xp_tick_at"] = datetime.utcnow()
    return row


def test_эволюция_требует_максимального_уровня(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    world["elixirs"] = 1
    msg, replies = _message("пет эволюция кот да")
    asyncio.run(bot_module.cmd_pet_evolve(msg))
    assert not world["pets"]["kot"].get("evolved")
    assert "❌" in replies[0]


def test_эволюция_проходит_и_даёт_вторую_способность(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    _maxed(world)
    world["elixirs"] = 1
    msg, replies = _message("пет эволюция кот да")
    asyncio.run(bot_module.cmd_pet_evolve(msg))
    row = world["pets"]["kot"]
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    assert row["evolved"] is True
    assert row["ability2"], "вторая способность выдана"
    assert row["ability2"] != bot_module._effective_ability(row, specs["kot"]), (
        "вторая не должна повторять первую")
    assert world["elixirs"] == 0, "эликсир израсходован"


def test_вторая_способность_не_дублирует_чужие(world):
    """Правило то же, что у платной смены: одинаковые не складываются, и выдать
    дубль значило бы подарить пустое место."""
    for key in ("кот", "пес", "хомяк", "попугай"):
        asyncio.run(bot_module.cmd_pet_buy(_message(f"пет купить {key}")[0]))
    _maxed(world)
    world["elixirs"] = 1
    asyncio.run(bot_module.cmd_pet_evolve(_message("пет эволюция кот да")[0]))
    specs = asyncio.run(bot_module._pet_specs(CHAT_ID))
    kot = world["pets"]["kot"]
    занято = set()
    for key, row in world["pets"].items():
        if key == "kot":
            continue
        занято.update(bot_module._effective_abilities(row, specs.get(key)))
    assert kot["ability2"] not in занято


def test_когда_свободных_способностей_нет_эволюция_всё_равно_проходит(world, monkeypatch):
    """Остальные три выгоды эволюции от этого не зависят — отказывать было бы
    хуже, чем выдать питомца без второй способности."""
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    _maxed(world)
    world["elixirs"] = 1
    monkeypatch.setattr(bot_module, "_pet_second_ability",
                        lambda *a, **k: "", raising=False)
    msg, replies = _message("пет эволюция кот да")
    asyncio.run(bot_module.cmd_pet_evolve(msg))
    assert world["pets"]["kot"]["evolved"] is True
    assert "не осталось" in replies[0]


def test_второй_раз_тот_же_питомец_не_растёт(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    _maxed(world)
    world["elixirs"] = 2
    asyncio.run(bot_module.cmd_pet_evolve(_message("пет эволюция кот да")[0]))
    msg, replies = _message("пет эволюция кот да")
    asyncio.run(bot_module.cmd_pet_evolve(msg))
    assert world["elixirs"] == 1, "второй эликсир не тронут"
    assert "уже эволюционировал" in replies[0]


def test_эволюционировавший_считает_обе_способности(world):
    asyncio.run(bot_module.cmd_pet_buy(_message("пет купить кот")[0]))
    row = world["pets"]["kot"]
    row["evolved"] = True
    row["ability2"] = "farm"
    bonus = asyncio.run(bot_module._pet_bonus(CHAT_ID, ME, "farm"))
    assert bonus > 0, "вторая способность обязана платить"


def test_база_способности_удваивается_после_эволюции():
    base = P.ability_percent("farm", 1, evolved=False)
    grown = P.ability_percent("farm", 1, evolved=True)
    assert grown == base * P.EVOLVE_ABILITY_MULTIPLIER


def test_прибавка_за_уровень_не_удваивается():
    """Иначе эволюционировавший на максимуме давал бы вчетверо, а не вдвое
    с небольшим."""
    at_max = P.ability_percent("farm", P.MAX_PET_LEVEL, evolved=True)
    base = P.ABILITY_BY_KEY["farm"].percent
    assert at_max == base * P.EVOLVE_ABILITY_MULTIPLIER + P.level_ability_bonus(P.MAX_PET_LEVEL)


def test_эволюционировавший_голодает_медленнее():
    assert P.hunger_now_evolved(100, 10) > P.hunger_now(100, 10)


def test_у_каждого_встроенного_вида_есть_во_что_расти():
    for spec in P.PETS:
        assert P.evolution_of(spec.key) is not None, spec.key


def test_заведённый_админом_вид_не_эволюционирует():
    """Кем вырастет чужой зверь, придумать за администрацию мы не можем."""
    assert P.evolution_of("ezhik") is None


# --- полнота каталога -------------------------------------------------------

def test_у_каждой_способности_есть_свой_питомец():
    """Способность без питомца — строка в списке, которую никак не получить."""
    covered = {p.ability for p in P.PETS}
    осиротевшие = [a.key for a in P.ABILITIES if a.key not in covered]
    assert not осиротевшие, f"эти способности нельзя завести: {осиротевшие}"


def test_способности_не_повторяются_у_разных_видов():
    """Два вида на одну способность обесценивают дешёвого: смысла брать
    дорогого нет, а бонусы у одного хозяина ещё и складываются."""
    abilities = [p.ability for p in P.PETS]
    дубли = sorted({a for a in abilities if abilities.count(a) > 1})
    assert not дубли, f"способность закреплена за несколькими видами: {дубли}"


def test_синонимы_ведут_на_существующие_виды():
    for alias, key in P.ALIASES.items():
        assert key in P.BY_KEY, f"синоним «{alias}» ведёт в никуда: {key}"


def test_синонимы_понимают_оба_написания_ё():
    """Словарь синонимов сравнивается с нормализованным ключом — запись через
    ё без нормализации была бы недостижима обоими написаниями."""
    for alias in P.ALIASES:
        assert P.resolve(alias) is not None, alias
        assert P.resolve(alias.replace("ё", "е")) is not None, alias


def test_цены_и_звуки_заполнены_у_всех():
    for spec in P.PETS:
        assert spec.price > 0 and spec.sound and spec.emoji, spec.key


# --- питомцы за ачивки ------------------------------------------------------

def test_наградные_питомцы_помечены():
    награда = [p for p in P.PETS if p.by_achievement]
    assert награда, "нет ни одного питомца за ачивку"
    for spec in награда:
        assert spec.achievement, spec.key
        assert spec.ability != P.ABILITY_NONE, spec.key


def test_ачивка_выдаёт_не_больше_одного_питомца():
    codes = [p.achievement for p in P.PETS if p.by_achievement]
    assert len(codes) == len(set(codes))
    assert set(P.PET_BY_ACHIEVEMENT) == set(codes)


def test_наградные_ачивки_существуют():
    """Питомец за несуществующую ачивку недостижим навсегда."""
    for code in P.PET_BY_ACHIEVEMENT:
        assert code in bot_module.ACHIEVEMENTS, code


def test_наградного_питомца_не_купить(world):
    msg, replies = _message("пет купить единорог")
    asyncio.run(bot_module.cmd_pet_buy(msg))
    assert "edinorog" not in world["pets"]
    assert world["coins"] == 100_000
    assert "за ачивку" in replies[0]


def test_наградного_питомца_не_продать(world):
    asyncio.run(bot_module.db.add_pet(CHAT_ID, ME, "edinorog", datetime.utcnow()))
    before = world["coins"]
    msg, replies = _message("пет продать единорог да")
    asyncio.run(bot_module.cmd_pet_sell(msg))
    assert "edinorog" in world["pets"], "знак отличия не имущество"
    assert world["coins"] == before
    assert "не продаётся" in replies[0]


def test_каталог_показывает_что_питомец_за_ачивку(world):
    msg, replies = _message("пет каталог")
    asyncio.run(bot_module.cmd_pets_catalog(msg))
    assert "за ачивку" in replies[0]


def test_способности_ауры_действуют_на_всех():
    """Наставник, Хозяйственный и Следопыт — как Компаньон: работают на всех
    питомцев хозяина, а не на себя."""
    for key in ("pet_mood", "pet_hunger", "pet_xp", "pet_walk"):
        assert key in P.ABILITY_BY_KEY, key


def test_аура_считает_проценты():
    aura = bot_module.PetAura(xp=50, walk=50)
    assert aura.xp_gain(10) == 15
    assert aura.walk_coins(200) == 300
    assert bot_module.PetAura().xp_gain(10) == 10
