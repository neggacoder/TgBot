"""Боссы чата: арифметика боя и защита от двойной выплаты.

Главная проверка здесь — та, что глазами не читается: два добивающих удара,
пришедшие одновременно, не должны раздать награду дважды. Состояние боя
живёт в памяти, опереться на условие в SQL (как с поломкой бизнеса) нельзя,
поэтому флаг «бой закрыт» ставится синхронно, без await между проверкой
и записью. Тест бьёт по боссу двадцатью одновременными кликами.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import bosses as B

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


# --- каталог ---------------------------------------------------------------

def test_каталог_боссов_заполнен():
    assert len(B.BOSSES) >= 3
    for boss in B.BOSSES:
        assert boss.hp > 0 and boss.pool > 0
        assert boss.taunt and boss.defeat_line and boss.emoji


def test_боссы_идут_по_возрастанию_сложности():
    hps = [b.hp for b in B.BOSSES]
    assert hps == sorted(hps)


def test_боссы_находятся_по_ключу_и_названию():
    for boss in B.BOSSES:
        assert B.resolve(boss.key) is boss
        assert B.resolve(boss.name) is boss
        assert B.resolve(boss.name.upper()) is boss


@pytest.mark.parametrize("raw", ["", "  ", "чепуха", None])
def test_чужое_слово_не_считается_боссом(raw):
    assert B.resolve(raw) is None


# --- урон ------------------------------------------------------------------

def test_урон_растёт_от_нажитого():
    weak = B.damage_for(0, 0, 0)
    mid = B.damage_for(5, 6, 5)
    strong = B.damage_for(10, 15, 10)
    assert weak < mid < strong


def test_новичок_всё_равно_бьёт():
    """Смысл механики — совместная игра. Если новичок бьёт нулём, ему нет
    причин приходить."""
    assert B.damage_for(0, 0, 0) >= B.DAMAGE_BASE


def test_разрыв_между_новичком_и_качком_умеренный():
    """При разрыве в десятки раз слабые участники перестают что-либо
    значить — и механика «бьём вместе» перестаёт работать."""
    ratio = B.damage_for(10, 15, 10) / B.damage_for(0, 0, 0)
    assert 2 <= ratio <= 6, ratio


def test_одиночка_не_валит_даже_мелкого_босса():
    """Ради этого и подбирался баланс: босс обязан требовать компании."""
    hits = B.FIGHT_MINUTES * 60 // B.HIT_COOLDOWN_SECONDS
    solo = B.damage_for(10, 15, 10) * hits
    assert solo < min(b.hp for b in B.BOSSES)


def test_мусор_в_характеристиках_не_ломает_урон():
    assert B.damage_for(-5, -5, -5) >= 1
    assert B.damage_for(0, 0, 0, roll=0) >= 1


# --- дележ награды ---------------------------------------------------------

def test_награда_делится_по_вкладу():
    shares = B.split_reward(1_000, {1: 700, 2: 300})
    assert shares == {1: 700, 2: 300}


def test_выплата_никогда_не_превышает_пул():
    """Округление вниз — единственный безопасный вариант: округляй вверх, и
    каждый бой печатал бы монеты из ниоткуда."""
    for damage in ({1: 1}, {1: 1, 2: 1, 3: 1}, {i: 7 for i in range(1, 101)},
                   {1: 999_999, 2: 1}):
        assert sum(B.split_reward(10_000, damage).values()) <= 10_000


def test_не_бивший_ничего_не_получает():
    shares = B.split_reward(1_000, {1: 100, 2: 0})
    assert 2 not in shares


def test_пустой_бой_ничего_не_платит():
    assert B.split_reward(1_000, {}) == {}
    assert B.split_reward(0, {1: 100}) == {}


def test_топ_стабилен_при_равном_уроне():
    """Иначе результат боя зависел бы от порядка обхода словаря."""
    assert B.top_fighters({3: 100, 1: 100, 2: 100}) == [(1, 100), (2, 100), (3, 100)]


def test_в_топ_не_попадают_нулевые():
    assert B.top_fighters({1: 50, 2: 0}) == [(1, 50)]


# --- полоса здоровья -------------------------------------------------------

def test_живой_босс_всегда_показывает_хоть_одно_деление():
    """Иначе на последних процентах полоса выглядит как «уже мёртв»."""
    assert "▰" in B.hp_bar(1, 100_000)
    assert "▰" not in B.hp_bar(0, 100)


# --- бой -------------------------------------------------------------------

class _FakeCallback:
    def __init__(self, user_id, message_id=99):
        self.answers: list = []
        self.from_user = type("U", (), {"id": user_id})()
        self.data = "boss_hit"
        self.message = type("M", (), {
            "chat": type("C", (), {"id": CHAT_ID})(),
            "message_id": message_id,
        })()

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


@pytest.fixture
def fight(monkeypatch):
    """Бой с почти мёртвым боссом + учёт всех выплат."""
    paid = {"coins": [], "items": [], "edits": []}

    async def add_coins(chat_id, user_id, amount):
        paid["coins"].append((user_id, amount))

    async def add_inventory_item(chat_id, user_id, key):
        paid["items"].append((user_id, key))

    async def edit_message_text(**kwargs):
        paid["edits"].append(kwargs.get("text", ""))

    monkeypatch.setattr(bot_module.db, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(bot_module.db, "add_inventory_item", add_inventory_item, raising=False)
    monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "get_chat_coins", _returns(10_000), raising=False)
    monkeypatch.setattr(bot_module.db, "add_chat_coins", _noop, raising=False)
    monkeypatch.setattr(bot_module.bot, "edit_message_text", edit_message_text, raising=False)
    # Сила удара: без похода в базу.
    monkeypatch.setattr(bot_module, "_boss_power", _returns((0, 0, 0)), raising=False)

    boss = B.BY_KEY["taxman"]
    key = (CHAT_ID, 99)
    bot_module._boss_fights[key] = {
        "boss": boss, "hp": 1, "damage": {}, "last_hit": {}, "power": {},
        "expires_at": datetime.utcnow() + timedelta(minutes=5),
        "dirty": False, "closed": False,
    }
    paid["key"] = key
    paid["boss"] = boss
    yield paid
    bot_module._boss_fights.pop(key, None)


def test_добивающий_удар_закрывает_бой_и_платит(fight):
    asyncio.run(bot_module.cb_boss_hit(_FakeCallback(777)))
    assert fight["key"] not in bot_module._boss_fights
    assert sum(a for _u, a in fight["coins"]) <= fight["boss"].pool
    assert fight["coins"], "победитель обязан получить награду"


def test_двадцать_одновременных_ударов_платят_ровно_один_раз(fight):
    """Двадцать добивающих ударов в один момент — награда раздаётся один раз.

    Свойство держат ДВЕ независимые защиты, и хватает любой: синхронный флаг
    «бой закрыт» в обработчике и снятие боя из реестра до выплаты. Тест
    проверяет само свойство, а не конкретную из них: убери обе — падает,
    убери одну — держится. Так и задумано, дублирование здесь намеренное.
    """
    async def storm():
        await asyncio.gather(*(bot_module.cb_boss_hit(_FakeCallback(1000 + i))
                               for i in range(20)))

    asyncio.run(storm())
    total = sum(a for _u, a in fight["coins"])
    assert total <= fight["boss"].pool, f"выплачено {total} при пуле {fight['boss'].pool}"
    # Итоговое сообщение о победе — ровно одно.
    wins = [t for t in fight["edits"] if "повержен" in t]
    assert len(wins) == 1, f"сообщений о победе: {len(wins)}"


def test_повторный_удар_упирается_в_кулдаун(monkeypatch, fight):
    fight_state = bot_module._boss_fights[fight["key"]]
    fight_state["hp"] = 10_000_000        # чтобы бой не закончился
    cb = _FakeCallback(555)
    asyncio.run(bot_module.cb_boss_hit(cb))
    dealt_once = fight_state["damage"][555]
    asyncio.run(bot_module.cb_boss_hit(cb))
    assert fight_state["damage"][555] == dealt_once, "второй удар не должен пройти"
    assert any("Отдышитесь" in (a or "") for a in cb.answers)


def test_удар_по_закрытому_бою_ничего_не_делает(fight):
    bot_module._boss_fights[fight["key"]]["closed"] = True
    cb = _FakeCallback(777)
    asyncio.run(bot_module.cb_boss_hit(cb))
    assert not fight["coins"]
    assert "закончен" in cb.answers[0]


def test_удара_по_несуществующему_бою_не_бывает():
    cb = _FakeCallback(777, message_id=12345)
    asyncio.run(bot_module.cb_boss_hit(cb))
    assert cb.answers and "закончен" in cb.answers[0]


def test_проигрыш_забирает_часть_казны(monkeypatch, fight):
    taken: list = []

    async def add_chat_coins(chat_id, amount):
        taken.append(amount)

    monkeypatch.setattr(bot_module.db, "add_chat_coins", add_chat_coins, raising=False)
    asyncio.run(bot_module._finish_boss_fight(fight["key"], won=False))
    assert taken and taken[0] < 0, "казна должна уменьшиться"
    assert abs(taken[0]) == int(10_000 * B.DEFEAT_TREASURY_SHARE)
    assert not fight["coins"], "при поражении никто ничего не получает"


def test_пустая_казна_не_уходит_в_минус(monkeypatch, fight):
    monkeypatch.setattr(bot_module.db, "get_chat_coins", _returns(0), raising=False)
    taken: list = []

    async def add_chat_coins(chat_id, amount):
        taken.append(amount)

    monkeypatch.setattr(bot_module.db, "add_chat_coins", add_chat_coins, raising=False)
    asyncio.run(bot_module._finish_boss_fight(fight["key"], won=False))
    assert not taken, "забирать нечего — трогать казну незачем"


# --- включение и ручной призыв ---------------------------------------------

def test_все_команды_босса_начинаются_со_слова_босс():
    for trigger in set(bot_module.BOSS_STATUS_TRIGGERS) | set(bot_module.BOSS_TOGGLE_TRIGGERS):
        assert trigger.lstrip("+-!").startswith("босс"), trigger
    assert bot_module.BOSS_SUMMON_RE.pattern.startswith(r"(?i)^!?босс\s")


def test_формы_опознаются_как_свои_команды():
    """По этому опознаванию работают автоочистка и права."""
    assert bot_module.resolve_command_key("босс") == "boss_status"
    assert bot_module.resolve_command_key("боссы") == "boss_status"
    assert bot_module.resolve_command_key("+босс") == "boss_toggle"
    assert bot_module.resolve_command_key("-босс") == "boss_toggle"
    assert bot_module.resolve_command_key("босс призвать дракон") == "boss_toggle"


def test_обе_команды_настраиваются_в_панели_отдельно():
    assert bot_module.is_cleanup_targetable("boss_status")
    assert bot_module.is_cleanup_targetable("boss_toggle")


def test_вероятность_спавна_выведена_из_срока():
    """Числа не подобраны на глаз: поменяешь тик — частота не поедет."""
    assert bot_module.BOSS_SPAWN_CHANCE == pytest.approx(
        bot_module.BOSS_SPAWN_TICK / bot_module.BOSS_SPAWN_EVERY)
    assert 0 < bot_module.BOSS_SPAWN_CHANCE < 0.05
