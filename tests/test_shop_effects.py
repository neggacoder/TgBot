"""Полезные предметы и наградные трофеи.

Главное, что здесь проверяется, — две вещи, которые ломаются молча:
предмет не должен тратиться, если эффект не сработал, и трофей не должен
никакими путями превратиться в товар (продажа, дарение, покупка).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


def _message(text: str):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    return m, replies


# --- каталог ---------------------------------------------------------------

def test_у_каждого_полезного_предмета_есть_эффект():
    for item in SE.EFFECT_ITEMS:
        assert item.effect, item.key
        assert SE.effect_of(item.key) == item.effect


def test_ключи_предметов_не_повторяются():
    """Один ключ на два предмета — и один из них молча недостижим."""
    keys = ([i.key for i in SE.EFFECT_ITEMS] + [i.key for i in SE.REWARD_ITEMS]
            + [i.key for i in SE.ACHIEVEMENT_ITEMS])
    assert len(keys) == len(set(keys))


def test_каждая_ачивка_выдаёт_не_больше_одного_предмета():
    codes = [i.achievement for i in SE.ACHIEVEMENT_ITEMS]
    assert len(codes) == len(set(codes))


def test_все_ачивки_предметов_существуют():
    """Предмет за несуществующую ачивку не выдался бы никогда."""
    for item in SE.ACHIEVEMENT_ITEMS:
        assert item.achievement in bot_module.ACHIEVEMENTS, item.achievement


def test_пассивные_и_суточные_предметы_заполнены_правильно():
    for item in SE.ACHIEVEMENT_ITEMS:
        if item.effect == SE.EFFECT_PASSIVE_BOOST:
            assert item.activity and item.percent > 0, item.key
        elif item.effect == SE.EFFECT_DAILY_CASH:
            assert item.shifts > 0, item.key
        else:
            pytest.fail(f"неизвестный эффект у {item.key}: {item.effect}")


def test_прибавка_считается_только_по_своему_занятию():
    keys = ["robot_worker", "traktor", "fishka"]
    assert SE.passive_percent(keys, SE.ACTIVITY_WORK) == 20
    assert SE.passive_percent(keys, SE.ACTIVITY_FARM) == 20
    assert SE.passive_percent(keys, SE.ACTIVITY_FISHING) == 0
    assert SE.passive_percent([], SE.ACTIVITY_WORK) == 0


def test_трофеи_и_полезные_предметы_не_пересекаются():
    """Иначе один и тот же ключ был бы и наградой, и товаром."""
    assert not (set(SE.BY_KEY) & set(SE.REWARD_BY_KEY))


def test_все_новые_вещи_попадают_в_засев():
    rows = SE.shop_rows()
    keys = {row[0] for row in rows}
    # Медалей за «наградить» тут нет: их перестали выдавать, и заводить
    # витрину предметов, которые никому не достанутся, незачем.
    assert keys == set(SE.BY_KEY) | set(SE.ACHIEVEMENT_BY_KEY)
    assert not (keys & set(SE.REWARD_BY_KEY))
    for _key, name, price, description, emoji in rows:
        assert name and description and emoji
        assert price > 0


def test_трофей_нельзя_купить_даже_случайно():
    """Цена трофея заведомо неоплатная — страховка на случай дыры в проверке
    is_reward: даже если она отвалится, знак отличия не станет товаром."""
    for item in SE.REWARD_ITEMS:
        _key, _name, price, _desc, _emoji = item.as_shop_row()
        assert price > 100_000_000


def test_медали_за_наградить_больше_не_выдаются():
    """Сама награда видна в профиле и в списке наград — предмет рядом с ней
    ничего не добавлял."""
    import inspect
    src = inspect.getsource(bot_module.cmd_reward)
    assert "trophy_for_degree" not in src
    assert "add_inventory_item" not in src


def test_медали_остались_неторгуемыми():
    """Не забытый код, а защита. У медалей стоит цена-заглушка 999 999 999 —
    просто чтобы их нельзя было купить. Продажа отдаёт 80% цены магазина,
    так что снятие запрета превратило бы одну старую медаль, если она у
    кого-то осталась, примерно в 800 миллионов монет.
    """
    for key in SE.REWARD_BY_KEY:
        assert SE.is_reward(key), key


@pytest.mark.parametrize("degree, key", [
    (1, "medal_bronze"), (2, "medal_bronze"),
    (3, "medal_silver"), (4, "medal_silver"),
    (5, "medal_gold"), (6, "medal_gold"),
    (7, "order_star"), (8, "order_star"),
])
def test_трофей_по_степени_награды(degree, key):
    trophy = SE.trophy_for_degree(degree)
    assert trophy is not None and trophy.key == key


def test_чем_выше_степень_тем_весомее_трофей():
    keys = [SE.trophy_for_degree(d).key for d in range(1, 9)]
    # порядок не убывает: значения меняются только вверх по списку REWARD_ITEMS
    order = [item.key for item in SE.REWARD_ITEMS]
    indexes = [order.index(k) for k in keys]
    assert indexes == sorted(indexes)


def test_витрина_не_показывает_неоплатную_цену_трофея():
    """Иначе в магазине висело бы «999999999 i¢» — цена-заглушка, которая
    нужна схеме, но человеку ничего не говорит."""
    line = bot_module.shop_item_line({
        "emoji": "🥇", "name": "Золотая медаль", "item_key": "medal_gold",
        "price": 999_999_999, "stock": None, "description": "Награда чата",
    })
    assert "999999999" not in line
    assert "не продаётся" in line
    assert "<code>medal_gold</code>" in line


def test_обычный_товар_цену_показывает():
    line = bot_module.shop_item_line({
        "emoji": "🍀", "name": "Талисман", "item_key": "talisman",
        "price": 5_000, "stock": None, "description": "Удача",
    })
    assert "5000 i¢" in line


def test_is_reward_отличает_награды_от_товаров():
    assert SE.is_reward("medal_gold")
    assert not SE.is_reward("talisman")
    assert not SE.is_reward("fishka")


# --- применение полезных предметов -----------------------------------------

@pytest.fixture
def world(monkeypatch):
    state = {"inventory": [], "removed": [], "effects": [], "cooldowns_reset": 0,
             "repaired": [], "businesses": []}

    async def list_inventory(chat_id, user_id):
        return list(state["inventory"])

    async def remove_inventory_item(chat_id, user_id, key):
        state["removed"].append(key)
        return True

    async def add_item_effect(chat_id, user_id, effect, charges=1):
        state["effects"].append(effect)

    async def reset_earning_cooldowns(chat_id, user_id):
        state["cooldowns_reset"] += 1

    async def list_user_businesses(chat_id, user_id):
        return list(state["businesses"])

    async def repair_business(chat_id, user_id, key, now):
        state["repaired"].append(key)
        return True

    monkeypatch.setattr(bot_module.db, "list_inventory", list_inventory, raising=False)
    monkeypatch.setattr(bot_module.db, "remove_inventory_item",
                        remove_inventory_item, raising=False)
    monkeypatch.setattr(bot_module.db, "add_item_effect", add_item_effect, raising=False)
    monkeypatch.setattr(bot_module.db, "reset_earning_cooldowns",
                        reset_earning_cooldowns, raising=False)
    monkeypatch.setattr(bot_module.db, "list_user_businesses",
                        list_user_businesses, raising=False)
    monkeypatch.setattr(bot_module.db, "repair_business", repair_business, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    return state


def _use(key):
    msg, replies = _message(f"использовать {key}")
    asyncio.run(bot_module._use_effect_item(msg, key))
    return replies


def test_энергетик_сбрасывает_кулдауны_и_тратится(world):
    world["inventory"] = [{"item_key": "energetik"}]
    replies = _use("energetik")
    assert world["cooldowns_reset"] == 1
    assert world["removed"] == ["energetik"]
    assert "Кулдауны сброшены" in replies[0]


def test_талисман_кладёт_заряд(world):
    world["inventory"] = [{"item_key": "talisman"}]
    _use("talisman")
    assert world["effects"] == [SE.EFFECT_LUCKY]
    assert world["removed"] == ["talisman"]


def test_страховка_кладёт_заряд(world):
    world["inventory"] = [{"item_key": "strahovka"}]
    _use("strahovka")
    assert world["effects"] == [SE.EFFECT_SHIELD]


def test_ремкомплект_чинит_сломанный_бизнес(world):
    world["inventory"] = [{"item_key": "remkomplekt"}]
    world["businesses"] = [{"business_key": "shaurma", "level": 1,
                            "broken_kind": "сломался гриль"}]
    replies = _use("remkomplekt")
    assert world["repaired"] == ["shaurma"]
    assert world["removed"] == ["remkomplekt"]
    assert "починен бесплатно" in replies[0]


def test_ремкомплект_не_тратится_если_чинить_нечего(world):
    """Главное правило применения: не сработало — предмет остаётся. Иначе
    покупка сгорала бы на опечатке или на исправном бизнесе."""
    world["inventory"] = [{"item_key": "remkomplekt"}]
    world["businesses"] = [{"business_key": "shaurma", "level": 1, "broken_kind": None}]
    replies = _use("remkomplekt")
    assert world["removed"] == [], "предмет обязан остаться"
    assert world["repaired"] == []
    assert "Ломаться нечему" in replies[0]


def test_каждый_отложенный_эффект_кладёт_свой_заряд(world):
    """Отложенные эффекты различаются только записью — перепутай их, и
    страховка чинила бы, а бизнес-план удваивал заработок."""
    expected = {"talisman": SE.EFFECT_LUCKY, "strahovka": SE.EFFECT_SHIELD,
                "biznesplan": SE.EFFECT_FREE_UPGRADE}
    for key, effect in expected.items():
        world["effects"].clear()
        world["inventory"] = [{"item_key": key}]
        _use(key)
        assert world["effects"] == [effect], key


def test_кофе_требует_профессии(world, monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_profession_stats",
                        _returns({"profession_key": None}), raising=False)
    world["inventory"] = [{"item_key": "kofe"}]
    replies = _use("kofe")
    assert world["removed"] == [], "без работы предмет тратить не за что"
    assert "устройтесь" in replies[0]


def test_аптечка_не_тратится_у_здорового(world, monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns(
        {"profession_key": "повар", "energy": 100, "mood": 100, "health": 100}),
        raising=False)
    world["inventory"] = [{"item_key": "aptechka"}]
    replies = _use("aptechka")
    assert world["removed"] == []
    assert "в полном порядке" in replies[0]


def test_аптечка_лечит_когда_есть_что_лечить(world, monkeypatch):
    healed = {"n": 0}

    async def restore(chat_id, user_id):
        healed["n"] += 1

    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns(
        {"profession_key": "повар", "energy": 40, "mood": 100, "health": 100}),
        raising=False)
    monkeypatch.setattr(bot_module.db, "restore_profession_state", restore, raising=False)
    world["inventory"] = [{"item_key": "aptechka"}]
    _use("aptechka")
    assert healed["n"] == 1
    assert world["removed"] == ["aptechka"]


def test_чужой_предмет_не_применить(world):
    world["inventory"] = []
    replies = _use("energetik")
    assert world["cooldowns_reset"] == 0
    assert world["removed"] == []
    assert "нет предмета" in replies[0]


# --- талисман в начислениях ------------------------------------------------

def test_талисман_удваивает_и_тратит_заряд(monkeypatch):
    used: list = []

    async def consume(chat_id, user_id, effect):
        used.append(effect)
        return True

    monkeypatch.setattr(bot_module.db, "consume_item_effect", consume, raising=False)
    amount, lucky = asyncio.run(bot_module._apply_lucky(CHAT_ID, USER_ID, 500))
    assert amount == 500 * SE.LUCKY_MULTIPLIER
    assert lucky is True
    assert used == [SE.EFFECT_LUCKY]


def test_без_талисмана_награда_не_меняется(monkeypatch):
    monkeypatch.setattr(bot_module.db, "consume_item_effect",
                        _returns(False), raising=False)
    amount, lucky = asyncio.run(bot_module._apply_lucky(CHAT_ID, USER_ID, 500))
    assert amount == 500 and lucky is False


# --- трофеи не превращаются в товар ----------------------------------------

@pytest.fixture
def trade(monkeypatch):
    """Все пути обмена замоканы так, что ЛЮБОЕ движение предмета заметно."""
    moved = {"touched": []}

    async def boom(*a, **k):
        moved["touched"].append("moved")
        return True

    for name in ("remove_inventory_item", "add_inventory_item",
                 "try_decrement_shop_item_stock"):
        monkeypatch.setattr(bot_module.db, name, boom, raising=False)
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(
        {"item_key": "medal_gold", "name": "Золотая медаль", "emoji": "🥇",
         "price": 999_999_999, "is_active": True, "stock": None}), raising=False)
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(
        [{"item_key": "medal_gold", "name": "Золотая медаль",
          "emoji": "🥇", "quantity": 1}]), raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    return moved


def test_трофей_нельзя_продать(trade):
    msg, replies = _message("магазин продать medal_gold")
    asyncio.run(bot_module.cmd_sell_item(msg))
    assert not trade["touched"], "предмет не должен никуда двинуться"
    assert "не продаются" in replies[0]


def test_трофей_нельзя_купить(trade):
    msg, replies = _message("магазин купить medal_gold")
    asyncio.run(bot_module.cmd_shop_buy(msg))
    assert not trade["touched"]
    assert "не продаётся" in replies[0]


def test_трофей_нельзя_использовать(trade):
    msg, replies = _message("использовать medal_gold")
    asyncio.run(bot_module.cmd_item_use(msg))
    assert not trade["touched"]
    assert "не «используют»" in replies[0]
