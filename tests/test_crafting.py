"""Крафты и эволюция питомцев.

Главное, что проверяется: каждый вид требования разбирается отдельно и
расходуемое не списывается, пока не выполнены ВСЕ требования. Списать хлам и
только потом обнаружить, что не хватает монет, — самый обидный из возможных
исходов.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

import crafting as C
import pets as P

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import shop_effects as SE  # noqa: E402

# Проверка «+бесконечность» стала асинхронной: список читается из базы на
# каждый вопрос, иначе рубильник с сайта для бота не существует до
# перезапуска (см. owner_flags). Синхронная заглушка отдавала bool, а его
# нельзя await'ить.
async def _не_бесконечность(user_id):
    return False


async def _бесконечность(user_id):
    return True


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
    object.__setattr__(m, "answer", reply)
    return m, replies


# --- каталог ----------------------------------------------------------------

def test_у_каждого_рецепта_есть_предмет():
    """Кроме рецептов с целью: у куклы результат — не предмет инвентаря, а
    строка в своей таблице (потому её и нельзя отобрать)."""
    for recipe in C.RECIPES:
        if recipe.target:
            assert recipe.result == "", recipe.key
            continue
        assert recipe.result in SE.CRAFT_BY_KEY, recipe.key


def test_рецепт_с_целью_ровно_один():
    """Если появится второй, обработчик крафта кукол придётся обобщать —
    сейчас он знает про «кукла» по имени."""
    assert [r.key for r in C.RECIPES if r.target] == ["кукла"]


def test_рецепты_требуют_только_существующие_предметы():
    """Рецепт с опечаткой в ключе собрать нельзя НИКОГДА, и понять это по
    сообщению бота невозможно: он честно скажет «не хватает материалов».

    Источников четыре: хлам из магазина, урожай с грядки (farming), продукт
    хлева (livestock) и материалы мастерской (shop_effects.MATERIAL_ITEMS).
    Все четыре — настоящие каталоги; всё, чего нет ни в одном из них, —
    опечатка.
    """
    import db
    import farming
    import livestock
    known = (set(db.JUNK_ITEM_KEYS)
             | {c.item_key for c in farming.CROPS}
             | {a.item_key for a in livestock.ANIMALS}
             | set(SE.MATERIAL_KEYS))
    for recipe in C.RECIPES:
        for req in recipe.reqs:
            if req.kind == C.REQ_ITEM:
                assert req.key in known, f"{recipe.key}: {req.key}"


def test_ключи_рецептов_не_повторяются():
    keys = [r.key for r in C.RECIPES]
    assert len(keys) == len(set(keys))


def test_крафтовое_нельзя_купить_продать_подарить():
    """Скрафченное зарабатывают, а не выменивают."""
    for item in SE.CRAFT_ITEMS:
        assert SE.is_reward(item.key), item.key


def test_корона_даёт_ко_всем_занятиям():
    for activity in (SE.ACTIVITY_FARM, SE.ACTIVITY_FISHING, SE.ACTIVITY_WORK,
                     SE.ACTIVITY_TREASURE, SE.ACTIVITY_SIDE_JOB):
        assert SE.passive_percent(["korona_mastera"], activity) == 25


def test_обычный_предмет_ко_всем_занятиям_не_даёт():
    assert SE.passive_percent(["traktor"], SE.ACTIVITY_FISHING) == 0


def test_требования_описываются_словами():
    assert "i¢" in C.req_text(C.Req(C.REQ_COINS, amount=5_000))
    assert "уровня" in C.req_text(C.Req(C.REQ_PET_LEVEL, amount=10))
    assert "эволюц" in C.req_text(C.Req(C.REQ_PET_EVOLVED))
    assert "титул" in C.req_text(C.Req(C.REQ_TITLE))


def test_расходуется_только_вещественное():
    """Титул или ачивку нельзя «потратить», и отбирать их за крафт было бы дико."""
    for recipe in C.RECIPES:
        for req in recipe.consumed:
            assert req.kind in (C.REQ_ITEM, C.REQ_COINS)


# --- крафт ------------------------------------------------------------------

@pytest.fixture
def world(monkeypatch):
    state = {"coins": 1_000_000, "inv": {}, "titles": ["legend"], "achievements": set(),
             "pets": [], "prof": {"profession_key": None, "prof_level": 1},
             "logs": []}

    async def get_wallet(chat_id, user_id):
        return {"coins": state["coins"], "total_farms": 0}

    async def try_spend_coins(chat_id, user_id, amount):
        if state["coins"] < amount:
            return False
        state["coins"] -= amount
        return True

    async def add_coins(chat_id, user_id, amount):
        state["coins"] += amount

    async def get_inventory_quantity(chat_id, user_id, key):
        return state["inv"].get(key, 0)

    async def remove_inventory_item(chat_id, user_id, key, amount=1):
        if state["inv"].get(key, 0) < amount:
            return False
        state["inv"][key] -= amount
        return True

    async def add_inventory_item(chat_id, user_id, key, amount=1):
        state["inv"][key] = state["inv"].get(key, 0) + amount

    async def get_shop_item(chat_id, key):
        return {"item_key": key, "name": key, "emoji": "🎁"}

    async def list_user_titles(chat_id, user_id):
        return [{"title_key": t} for t in state["titles"]]

    async def has_title(chat_id, user_id, key):
        return key in state["titles"]

    async def get_achievement_codes(chat_id, user_id):
        return set(state["achievements"])

    async def list_pets(chat_id, user_id):
        return [dict(p) for p in state["pets"]]

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("get_wallet", get_wallet), ("try_spend_coins", try_spend_coins),
        ("add_coins", add_coins),
        ("get_inventory_quantity", get_inventory_quantity),
        ("remove_inventory_item", remove_inventory_item),
        ("add_inventory_item", add_inventory_item),
        ("get_shop_item", get_shop_item),
        ("list_user_titles", list_user_titles), ("has_title", has_title),
        ("get_achievement_codes", get_achievement_codes),
        ("list_pets", list_pets),
        ("get_profession_stats", _returns(state["prof"])),
        ("seed_extra_shop_items", _returns(0)),
        ("add_log", add_log),
    ]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "has_infinite_money", _не_бесконечность, raising=False)
    return state


def _stock(world, recipe_key):
    """Кладёт всё, что нужно рецепту из вещей."""
    recipe = C.BY_KEY[recipe_key]
    for req in recipe.reqs:
        if req.kind == C.REQ_ITEM:
            world["inv"][req.key] = world["inv"].get(req.key, 0) + req.amount


def test_крафт_собирает_предмет(world):
    _stock(world, "otmychka")
    before = world["coins"]
    asyncio.run(bot_module.cmd_craft(_message("крафт otmychka да")[0]))
    assert world["inv"].get("otmychka") == 1
    assert world["coins"] == before - 5_000
    assert world["inv"].get("skrepka", 0) == 0, "материалы израсходованы"


def test_без_материалов_ничего_не_тратится(world):
    before = world["coins"]
    msg, replies = _message("крафт otmychka да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "otmychka" not in world["inv"]
    assert world["coins"] == before, "монеты не тронуты"
    assert "❌" in replies[0], "показано, чего не хватает"


def test_без_монет_материалы_возвращаются(world):
    """Списать хлам и только потом обнаружить нехватку монет — худший исход."""
    _stock(world, "otmychka")
    world["coins"] = 10
    msg, replies = _message("крафт otmychka да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "otmychka" not in world["inv"]
    assert world["inv"]["skrepka"] == 1, "материалы вернулись"
    assert world["inv"]["nitka"] == 1
    assert world["inv"]["gvozd"] == 1


def test_без_подтверждения_только_показывает(world):
    _stock(world, "otmychka")
    before = world["coins"]
    msg, replies = _message("крафт otmychka")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "otmychka" not in world["inv"]
    assert world["coins"] == before
    assert "Нужно" in replies[0]


def test_требование_ачивки_проверяется(world):
    _stock(world, "amulet")
    msg, replies = _message("крафт amulet да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "amulet_serii" not in world["inv"], "без ачивки нельзя"
    world["achievements"].add("streak_7")
    asyncio.run(bot_module.cmd_craft(_message("крафт amulet да")[0]))
    assert world["inv"].get("amulet_serii") == 1


def test_требование_уровня_питомца_проверяется(world):
    _stock(world, "elixir")
    msg, replies = _message("крафт elixir да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "elixir" not in world["inv"], "без питомца 10 уровня нельзя"
    world["pets"].append({"pet_key": "kot", "xp": P.LEVEL_XP_THRESHOLDS[-1],
                          "xp_tick_at": datetime.utcnow(), "evolved": False,
                          "ability": None, "ability2": None})
    asyncio.run(bot_module.cmd_craft(_message("крафт elixir да")[0]))
    assert world["inv"].get("elixir") == 1


def test_требование_эволюционировавшего_питомца_проверяется(world):
    world["achievements"].add("collection_tycoon")
    msg, replies = _message("крафт korona да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "korona_mastera" not in world["inv"]
    world["pets"].append({"pet_key": "kot", "xp": 0, "xp_tick_at": datetime.utcnow(),
                          "evolved": True, "ability": None, "ability2": None})
    asyncio.run(bot_module.cmd_craft(_message("крафт korona да")[0]))
    assert world["inv"].get("korona_mastera") == 1


def test_неизвестный_рецепт_подсказывает_список(world):
    msg, replies = _message("крафт чепуха да")
    asyncio.run(bot_module.cmd_craft(msg))
    assert "крафты" in replies[0]


def test_список_крафтов_показывает_все_рецепты(world):
    msg, replies = _message("крафты")
    asyncio.run(bot_module.cmd_craft_list(msg))
    for recipe in C.RECIPES:
        assert recipe.key in replies[0], recipe.key


def test_реролл_не_выдаёт_питомцу_его_же_вторую_способность():
    """_pet_bonus проверяет вхождение способности, а не считает штуки, — за
    одинаковую пару человек платил бы подорожавшую смену ни за что."""
    import inspect
    src = inspect.getsource(bot_module.cmd_pet_ability_reroll)
    assert 'row.get("ability2")' in src


def test_эликсир_подсказывает_свою_команду():
    """Общий ответ «награду не используют» для расходника сбивал бы с толку."""
    import inspect
    src = inspect.getsource(bot_module.cmd_item_use)
    assert "EFFECT_EVOLUTION" in src
    assert "пет эволюция" in src


def test_экран_способности_знает_про_удвоение():
    import inspect
    src = inspect.getsource(bot_module.cmd_pet_ability_reroll)
    assert "ability_text_evolved" in src


# --- кукла вуду -------------------------------------------------------------
#
# Сувенир, а не оружие: ничего не делает. Главное свойство — её нельзя
# потерять, продать и ограбить, и обеспечено это НЕ списком запретов, а тем,
# что кукла вообще не лежит в user_inventory.

@pytest.fixture
def dolls(world, monkeypatch):
    state = world
    state["dolls"] = []

    async def add_voodoo_doll(chat_id, owner_id, target_id, target_name, now):
        if any(d["target_id"] == target_id and d["owner_id"] == owner_id
               for d in state["dolls"]):
            return False
        state["dolls"].append({"chat_id": chat_id, "owner_id": owner_id,
                               "target_id": target_id, "target_name": target_name,
                               "created_at": now})
        return True

    async def list_voodoo_dolls(chat_id, owner_id):
        return [dict(d) for d in state["dolls"] if d["owner_id"] == owner_id]

    async def count_voodoo_dolls_of(chat_id, target_id):
        return sum(1 for d in state["dolls"] if d["target_id"] == target_id)

    for name, fn in [("add_voodoo_doll", add_voodoo_doll),
                     ("list_voodoo_dolls", list_voodoo_dolls),
                     ("count_voodoo_dolls_of", count_voodoo_dolls_of)]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)
    monkeypatch.setattr(bot_module, "display_name", _returns("Вася"), raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Петя"), raising=False)

    class _Target:
        id = 777
        is_bot = False

    monkeypatch.setattr(bot_module, "_target_for_item", _returns(_Target()), raising=False)
    return state


def test_кукла_крафтится_и_попадает_в_свою_коллекцию(dolls):
    _stock(dolls, "кукла")
    before = dolls["coins"]
    asyncio.run(bot_module.cmd_craft_doll(_message("крафт кукла @petya")[0]))
    assert len(dolls["dolls"]) == 1
    assert dolls["dolls"][0]["target_id"] == 777
    assert dolls["coins"] == before - 2_000
    assert "kukla" not in dolls["inv"], "в инвентарь кукла не кладётся"


def test_вторая_кукла_того_же_человека_не_делается(dolls):
    _stock(dolls, "кукла")
    asyncio.run(bot_module.cmd_craft_doll(_message("крафт кукла @petya")[0]))
    _stock(dolls, "кукла")
    msg, replies = _message("крафт кукла @petya")
    asyncio.run(bot_module.cmd_craft_doll(msg))
    assert len(dolls["dolls"]) == 1
    assert "уже есть" in replies[0]


def test_без_материалов_кукла_не_делается(dolls):
    before = dolls["coins"]
    msg, replies = _message("крафт кукла @petya")
    asyncio.run(bot_module.cmd_craft_doll(msg))
    assert not dolls["dolls"]
    assert dolls["coins"] == before
    assert "❌" in replies[0]


def test_без_монет_материалы_возвращаются(dolls):
    _stock(dolls, "кукла")
    dolls["coins"] = 10
    msg, replies = _message("крафт кукла @petya")
    asyncio.run(bot_module.cmd_craft_doll(msg))
    assert not dolls["dolls"]
    assert dolls["inv"]["nitka"] == 1 and dolls["inv"]["nosok"] == 1


def test_кукла_ничего_не_делает():
    """Сувенир. Если однажды захочется эффекта — он появится осознанно, а не
    потому, что кто-то решил, будто вуду обязано вредить."""
    import inspect
    src = inspect.getsource(bot_module.cmd_craft_doll)
    for damage in ("set_profession_state", "add_coins(chat_id, target",
                   "restore_profession", "energy"):
        assert damage not in src, damage


def test_кукла_не_ходит_по_инвентарю():
    """Продажа, подарок, Медвежатник и лимит применений работают по
    user_inventory — того, чего там нет, они физически не достанут."""
    import inspect
    src = inspect.getsource(bot_module.cmd_craft_doll)
    assert "add_inventory_item(chat_id, user_id, recipe.result" not in src
    assert "add_voodoo_doll" in src


def test_список_кукол_пустой_подсказывает_команду(dolls):
    msg, replies = _message("куклы")
    asyncio.run(bot_module.cmd_doll_list(msg))
    assert "крафт кукла" in replies[0]


def test_список_кукол_показывает_имена(dolls):
    _stock(dolls, "кукла")
    asyncio.run(bot_module.cmd_craft_doll(_message("крафт кукла @petya")[0]))
    msg, replies = _message("куклы")
    asyncio.run(bot_module.cmd_doll_list(msg))
    assert "Петя" in replies[0]


def test_имя_в_кукле_хранится_без_разметки(dolls, monkeypatch):
    """display_name_by_id возвращает HTML-ссылку. Сохранённая как есть, она
    при показе экранируется и вылезает тегами: «<a href=...>ебанина</a>»."""
    monkeypatch.setattr(
        bot_module, "display_name_by_id",
        _returns('<a href="https://telegram.me/kto">Вася</a>'), raising=False)
    _stock(dolls, "кукла")
    asyncio.run(bot_module.cmd_craft_doll(_message("крафт кукла @kto")[0]))
    assert dolls["dolls"], "кукла не сделалась"
    assert "<" not in dolls["dolls"][0]["target_name"], (
        f"в базу ушла разметка: {dolls['dolls'][0]['target_name']!r}")


def test_имя_в_списке_кликабельно(dolls, monkeypatch):
    """Ссылка строится ЖИВЬЁМ по target_id и уже готова — экранировать её
    нельзя, иначе теги вылезут текстом (так список и ломался)."""
    monkeypatch.setattr(
        bot_module, "display_name_by_id",
        _returns('<a href="https://telegram.me/kto">Вася</a>'), raising=False)
    dolls["dolls"].append({
        "chat_id": CHAT_ID, "owner_id": ME, "target_id": 42,
        "target_name": "Вася", "created_at": datetime.now()})
    msg, replies = _message("куклы")
    asyncio.run(bot_module.cmd_doll_list(msg))
    assert '<a href="https://telegram.me/kto">Вася</a>' in replies[0], replies[0]
    assert "&lt;a" not in replies[0], "разметку экранировали — ссылка не сработает"


def test_ссылка_берётся_по_id_а_не_из_хранимого_имени(dolls, monkeypatch):
    """Человек мог сменить ник — сохранённое имя устаревает, id нет."""
    monkeypatch.setattr(
        bot_module, "display_name_by_id",
        _returns('<a href="tg://user?id=42">Новый ник</a>'), raising=False)
    dolls["dolls"].append({
        "chat_id": CHAT_ID, "owner_id": ME, "target_id": 42,
        "target_name": "Старый ник", "created_at": datetime.now()})
    msg, replies = _message("куклы")
    asyncio.run(bot_module.cmd_doll_list(msg))
    assert "Новый ник" in replies[0]
    assert "Старый ник" not in replies[0]


def test_если_человек_неизвестен_показываем_хранимое_имя(dolls, monkeypatch):
    """Бот мог человека уже не видеть — тогда сувенир не должен превращаться
    в голый id."""
    async def boom(*a, **k):
        raise RuntimeError("нет такого участника")

    monkeypatch.setattr(bot_module, "display_name_by_id", boom, raising=False)
    dolls["dolls"].append({
        "chat_id": CHAT_ID, "owner_id": ME, "target_id": 42,
        "target_name": "Вася", "created_at": datetime.now()})
    msg, replies = _message("куклы")
    asyncio.run(bot_module.cmd_doll_list(msg))
    assert "Вася" in replies[0]


def test_закрепить_куклу_не_перехватывается_предметами():
    """«закрепить {ключ}» ловит любые слова. Порядок обработчиков куклу и рыбу
    разводит, но опираться только на него нельзя — запрет должен быть явным."""
    assert bot_module.PIN_ITEM_RE.match("закрепить fishka")
    assert not bot_module.PIN_ITEM_RE.match("закрепить куклу")
    assert not bot_module.PIN_ITEM_RE.match("закрепить куклы")
    assert not bot_module.PIN_ITEM_RE.match("закрепить рыбу")
    assert bot_module.DOLL_PIN_RE.match("закрепить куклу @kto")


def test_закреп_куклы_ничего_не_усиливает():
    """Закреп усиливает то, что предмет умеет. Кукла не умеет ничего, и
    придумывать ей силу ради единообразия значило бы сделать из сувенира
    снаряжение."""
    import inspect
    src = inspect.getsource(bot_module.cmd_doll_pin)
    assert "PIN_MULTIPLIER" not in src
    assert "set_pinned_doll" in src
