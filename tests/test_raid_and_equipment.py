"""Налёт на бизнес, оснащение, кража предмета и покупка пачкой.

Всё это трогает чужое добро, поэтому проверяется прежде всего то, где ошибка
создаёт или теряет монеты и предметы: копилка не должна «отрастать» после
кражи, остаток товара не должен исчезать от неудачной покупки, оснащение не
должно переезжать к новому владельцу.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import bosses  # noqa: F401  (подтягивает зависимости бота)
import businesses as B
import robbery
import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ME, VICTIM = 555, 777


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


def _message(text: str, user_id: int = ME):
    from aiogram.types import Chat, Message, User
    m = Message(message_id=1, date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="supergroup"),
                from_user=User(id=user_id, is_bot=False, first_name="Тестер"), text=text)
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    async def answer(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    object.__setattr__(m, "answer", answer)
    return m, replies


# --- оснащение: чистая арифметика ------------------------------------------

def test_каталог_оснащения_заполнен():
    for up in B.UPGRADES:
        assert up.name and up.emoji and up.description
        assert 0 < up.price_share < 1


def test_цена_оснащения_растёт_с_ценой_бизнеса():
    guard = B.UPGRADE_BY_KEY[B.UPGRADE_GUARD]
    assert guard.price(B.BY_KEY["shaurma"]) < guard.price(B.BY_KEY["aeroport"])


def test_реклама_поднимает_доход_а_сейф_потолок():
    item = B.BY_KEY["shaurma"]
    assert B.effective_income(item, 1, {B.UPGRADE_ADS}) > item.income(1)
    assert B.effective_cap(item, 1, {B.UPGRADE_SAFE}) > item.cap(1)
    # и не влияют друг на друга
    assert B.effective_cap(item, 1, {B.UPGRADE_ADS}) == item.cap(1)
    assert B.effective_income(item, 1, {B.UPGRADE_SAFE}) == item.income(1)


def test_без_оснащения_числа_базовые():
    item = B.BY_KEY["aeroport"]
    for level in (1, 2, 3):
        assert B.effective_income(item, level, set()) == item.income(level)
        assert B.effective_cap(item, level, set()) == item.cap(level)


def test_копилка_с_рекламой_и_сейфом_растёт_выше():
    item = B.BY_KEY["shaurma"]
    plain = B.accrued_now(1, item, 0, 100)
    rich = B.accrued_now(1, item, 0, 100, {B.UPGRADE_ADS, B.UPGRADE_SAFE})
    assert rich > plain


@pytest.mark.parametrize("raw, key", [
    ("охрана", B.UPGRADE_GUARD), ("ОХРАНА", B.UPGRADE_GUARD),
    ("аппаратура", B.UPGRADE_GEAR), ("реклама", B.UPGRADE_ADS),
    ("сейф", B.UPGRADE_SAFE), ("seif", B.UPGRADE_SAFE),
])
def test_оснащение_находится_по_ключу_и_по_русски(raw, key):
    found = B.resolve_upgrade(raw)
    assert found is not None and found.key == key


@pytest.mark.parametrize("raw", ["", "чепуха", None])
def test_чужое_слово_не_оснащение(raw):
    assert B.resolve_upgrade(raw) is None


# --- налёт: арифметика -----------------------------------------------------

def test_налёт_не_уносит_больше_копилки():
    for pot in (1, 500, 17_000):
        assert robbery.compute_raid_amount(pot, False) <= pot


def test_у_налёта_есть_жёсткий_потолок():
    """Без него полная копилка Аэропорта отдавала бы за раз больше, чем
    приносит день честной игры."""
    assert robbery.compute_raid_amount(1_000_000, True) <= robbery.RAID_MAX_STEAL


def test_из_пустой_копилки_не_украсть():
    assert robbery.compute_raid_amount(0, False) == 0


def test_охрана_реально_сбивает_шанс():
    base = robbery.success_chance(False)
    assert base - B.GUARD_RAID_PENALTY < base


# --- налёт: деньги ---------------------------------------------------------

@pytest.fixture
def world(monkeypatch):
    state = {"coins": {ME: 10_000, VICTIM: 0}, "accrual": {}, "dm": [],
             "upgrades": set(), "shield": False, "inventory": {ME: {}, VICTIM: {}}}

    now = datetime.utcnow()
    biz = {"business_key": "aeroport", "level": 1, "accrued": 8_000,
           "last_tick_at": now, "bought_at": now, "broken_kind": None,
           "boost_until": None, "user_id": VICTIM}

    async def add_coins(chat_id, user_id, amount):
        state["coins"][user_id] = state["coins"].get(user_id, 0) + amount

    async def get_wallet(chat_id, user_id):
        return {"coins": state["coins"].get(user_id, 0)}

    async def list_user_businesses(chat_id, user_id):
        return [dict(biz)] if user_id == VICTIM else []

    async def list_business_upgrades(chat_id, user_id, key):
        return set(state["upgrades"])

    async def set_business_accrual(chat_id, user_id, key, accrued, ts):
        state["accrual"][key] = accrued

    async def consume_item_effect(chat_id, user_id, effect):
        if effect == SE.EFFECT_SHIELD and state["shield"]:
            state["shield"] = False
            return True
        return False

    async def list_inventory(chat_id, user_id):
        return [{"item_key": k, "quantity": v}
                for k, v in state["inventory"].get(user_id, {}).items()]

    async def dm(user_id, text, keyboard=None):
        state["dm"].append((user_id, text))
        return None

    for name, fn in [("add_coins", add_coins), ("get_wallet", get_wallet),
                     ("list_user_businesses", list_user_businesses),
                     ("list_business_upgrades", list_business_upgrades),
                     ("set_business_accrual", set_business_accrual),
                     ("consume_item_effect", consume_item_effect),
                     ("list_inventory", list_inventory),
                     ("add_log", _noop), ("touch_earning_activity", _noop),
                     ("get_earning_activity", _returns(None)),
                     ("is_under_surveillance", _returns(False)),
                     ("remove_inventory_item", _returns(True)),
                     ("add_robbery_strike", _returns((1, False)))]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)

    monkeypatch.setattr(bot_module, "_dm_or_none", dm, raising=False)
    monkeypatch.setattr(bot_module, "event_flag", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"), raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Жертва"), raising=False)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((type("T", (), {"id": VICTIM, "is_bot": False})(), "")),
                        raising=False)
    state["biz"] = biz
    return state


def _raid(monkeypatch, success=True):
    monkeypatch.setattr(bot_module.random, "randint",
                        lambda a, b: 1 if success else 100)
    msg, replies = _message("налёт @kto")
    asyncio.run(bot_module.cmd_business_raid(msg))
    return replies


def test_удачный_налёт_переносит_деньги_из_копилки(world, monkeypatch):
    replies = _raid(monkeypatch, success=True)
    stolen = world["coins"][ME] - 10_000
    assert stolen > 0, "грабитель должен что-то унести"
    # копилка уменьшилась ровно на украденное
    assert world["accrual"]["aeroport"] == 8_000 - stolen
    assert any("вынес" in r for r in replies)


def test_жертву_уведомляют_в_лс(world, monkeypatch):
    """Иначе пропажу из копилки нечем объяснить и она выглядит как сбой бота."""
    _raid(monkeypatch, success=True)
    assert world["dm"] and world["dm"][0][0] == VICTIM
    assert "налёт" in world["dm"][0][1]


def test_страховка_гасит_налёт_целиком(world, monkeypatch):
    world["shield"] = True
    replies = _raid(monkeypatch, success=True)
    assert world["coins"][ME] == 10_000, "ничего не украдено"
    assert not world["accrual"], "копилка не тронута"
    assert any("страховка" in r for r in replies)


def test_провал_наказывает_налётчика(world, monkeypatch):
    replies = _raid(monkeypatch, success=False)
    assert world["coins"][ME] < 10_000, "провалившийся теряет деньги"
    assert not world["accrual"], "копилка жертвы не тронута"
    assert any("попался" in r for r in replies)


def test_под_надзором_налетать_нельзя(world, monkeypatch):
    monkeypatch.setattr(bot_module.db, "is_under_surveillance",
                        _returns(True), raising=False)
    replies = _raid(monkeypatch, success=True)
    assert world["coins"][ME] == 10_000
    assert any("надзором" in r for r in replies)


def test_кулдаун_держит(world, monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_earning_activity",
                        _returns({"last_at": datetime.utcnow()}), raising=False)
    replies = _raid(monkeypatch, success=True)
    assert world["coins"][ME] == 10_000
    assert any("рано" in r for r in replies)


def test_комендантский_час_отменяет_налёт(world, monkeypatch):
    monkeypatch.setattr(bot_module, "event_flag", _returns(True), raising=False)
    replies = _raid(monkeypatch, success=True)
    assert world["coins"][ME] == 10_000
    assert any("омендантский" in r for r in replies)


# --- кража предмета --------------------------------------------------------

def test_медвежатник_самый_дорогой_в_магазине():
    prices = [i.price for i in SE.EFFECT_ITEMS]
    assert SE.BY_KEY["medvezhatnik"].price == max(prices)


def test_награды_и_ачивочные_предметы_не_крадутся():
    """Иначе медвежатник обнулял бы смысл достижений."""
    for key in list(SE.REWARD_BY_KEY) + list(SE.ACHIEVEMENT_BY_KEY):
        assert SE.is_reward(key), key


# --- покупка пачкой --------------------------------------------------------

@pytest.mark.parametrize("text, key, qty", [
    ("купить fishka", "fishka", None),
    ("купить fishka 5", "fishka", "5"),
    ("магазин купить korona 10", "korona", "10"),
])
def test_количество_разбирается(text, key, qty):
    m = bot_module.SHOP_BUY_RE.match(text)
    assert m and m.group(1) == key and m.group(2) == qty


def test_у_количества_есть_потолок():
    """Опечатка «купить fishka 100000» иначе выносит весь кошелёк."""
    assert 0 < bot_module.SHOP_BUY_MAX_QTY <= 1000
