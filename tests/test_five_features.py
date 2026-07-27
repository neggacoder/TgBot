"""Пять правок разом: рабочее «право», звёздность, восстановление, рынок в личке.

Закреп ×5 проверяется в test_shop_effects.py — там уже есть каркас применения
предметов.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import professions as P

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


def _message(text: str, chat_type: str = "private"):
    from aiogram.types import Chat, Message, User
    m = Message(message_id=1, date=datetime.now(),
                chat=Chat(id=CHAT_ID, type=chat_type),
                from_user=User(id=ME, is_bot=False, first_name="Тестер"), text=text)
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    object.__setattr__(m, "answer", reply)
    return m, replies


# --- п.2: «право» начинает работать ----------------------------------------

class _FakeHandler:
    def __init__(self):
        self.called = False

    async def __call__(self, event, data):
        self.called = True
        return "прошло"


def _run_gate(text: str, chat_type: str = "supergroup"):
    msg, replies = _message(text, chat_type)
    handler = _FakeHandler()
    mw = bot_module.CommandPermissionMiddleware()
    asyncio.run(mw(handler, msg, {}))
    return handler.called, replies


def test_без_настроек_заслон_не_вмешивается(monkeypatch):
    """Уровни по умолчанию не трогаем: их проверяют сами обработчики, иногда
    шире, чем «уровень не ниже N»."""
    monkeypatch.setattr(bot_module, "command_level_overrides", {}, raising=False)
    called, replies = _run_gate("о себе")
    assert called and not replies


def test_выставленный_уровень_режет_доступ(monkeypatch):
    monkeypatch.setattr(bot_module, "command_level_overrides", {"about": 2}, raising=False)
    monkeypatch.setattr(bot_module, "get_level", lambda uid: 0, raising=False)
    called, replies = _run_gate("о себе")
    assert not called, "команда не должна дойти до обработчика"
    assert not replies, "постороннему молчим"


def test_тому_у_кого_уровень_есть_объясняем(monkeypatch):
    monkeypatch.setattr(bot_module, "command_level_overrides", {"about": 3}, raising=False)
    monkeypatch.setattr(bot_module, "get_level", lambda uid: 1, raising=False)
    called, replies = _run_gate("о себе")
    assert not called
    assert replies and "уровнем" in replies[0]


def test_с_достаточным_уровнем_проходит(monkeypatch):
    monkeypatch.setattr(bot_module, "command_level_overrides", {"about": 2}, raising=False)
    monkeypatch.setattr(bot_module, "get_level", lambda uid: 3, raising=False)
    called, _ = _run_gate("о себе")
    assert called


def test_чужой_текст_заслон_не_трогает(monkeypatch):
    monkeypatch.setattr(bot_module, "command_level_overrides", {"about": 3}, raising=False)
    monkeypatch.setattr(bot_module, "get_level", lambda uid: 0, raising=False)
    called, _ = _run_gate("привет всем как дела")
    assert called


def test_команды_раздачи_прав_не_переопределяются():
    """У них уровень зашит в логику: разрешить понижать планку у команды,
    которая раздаёт права, — приглашение к захвату чата."""
    for key in ("set_permission", "grant_level", "revoke_admin", "promote_demote"):
        assert bot_module.COMMAND_REGISTRY[key].get("overridable") is False, key


# --- п.4: звёздность --------------------------------------------------------

def test_звезда_даётся_за_пять_фармов():
    assert bot_module.FARM_FARMS_PER_STAR == 5
    assert bot_module.farm_star_progress(0)[0] == 0
    assert bot_module.farm_star_progress(4)[0] == 0
    assert bot_module.farm_star_progress(5)[0] == 1
    assert bot_module.farm_star_progress(12)[0] == 2


def test_прогресс_показывает_остаток_до_следующей():
    stars, gained, needed = bot_module.farm_star_progress(12)
    assert (stars, gained, needed) == (2, 2, 5)
    assert "2/5" in bot_module.farm_star_line(12)


def test_на_максимуме_прогресс_не_делится_на_ноль():
    cap = bot_module.FARM_STAR_CAP * bot_module.FARM_FARMS_PER_STAR
    stars, gained, needed = bot_module.farm_star_progress(cap + 100)
    assert stars == bot_module.FARM_STAR_CAP
    assert gained == needed, "полоса просто полная"
    assert "максимум" in bot_module.farm_star_line(cap)


def test_звёздность_не_превышает_потолок():
    assert bot_module.farm_star_progress(10_000)[0] == bot_module.FARM_STAR_CAP


# --- п.5: восстановление ----------------------------------------------------

def test_скорость_растёт_с_уровнем():
    assert P.regen_per_hour(0) == P.REGEN_BASE_PER_HOUR
    assert P.regen_per_hour(5) > P.regen_per_hour(1)
    assert P.regen_per_hour(10) == P.REGEN_BASE_PER_HOUR + 10 * P.REGEN_PER_LEVEL


def test_восстановление_считается_по_часам():
    assert P.restored(50, 0, 5) == 50
    assert P.restored(50, 4, 5) == 70


def test_выше_потолка_не_растёт():
    assert P.restored(90, 100, 5) == P.MAX_STAT
    assert P.restored(100, 10, 5) == P.MAX_STAT


def test_отрицательное_время_ничего_не_даёт():
    """Часы бота и базы могут разъехаться — «восстановление назад» из этого
    получаться не должно."""
    assert P.restored(50, -10, 5) == 50


def test_время_до_полного_считается():
    assert P.hours_to_full(100, 5) == 0
    assert P.hours_to_full(50, 5) == 10
    assert P.hours_to_full(0, 0) == 0, "нулевая скорость не делит на ноль"


def test_без_профессии_восстановление_всё_равно_идёт():
    """Иначе новичок, ушедший в ноль, остался бы там навсегда и не смог бы
    даже устроиться на работу."""
    assert P.regen_per_hour(0) > 0


# --- п.3: рынок в личке -----------------------------------------------------

@pytest.fixture
def market_world(monkeypatch):
    state = {"goods": [{"id": 7, "chat_id": CHAT_ID, "seller_id": ME,
                        "item_key": "ogurcy", "name": "Огурцы", "emoji": "🥒",
                        "description": None, "price": 500, "status": "approved"}],
             "prices": [], "descriptions": []}

    async def list_market_goods_of_user(seller_id):
        return [dict(g) for g in state["goods"] if g["seller_id"] == seller_id]

    async def get_market_good_of_user(good_id, seller_id):
        for g in state["goods"]:
            if g["id"] == good_id and g["seller_id"] == seller_id:
                return dict(g)
        return None

    async def set_market_good_price(good_id, seller_id, price):
        state["prices"].append((good_id, price))
        return True

    async def set_market_good_description(good_id, seller_id, description):
        state["descriptions"].append((good_id, description))
        return True

    for name, fn in [("list_market_goods_of_user", list_market_goods_of_user),
                     ("get_market_good_of_user", get_market_good_of_user),
                     ("set_market_good_price", set_market_good_price),
                     ("set_market_good_description", set_market_good_description),
                     ("get_market_settings", _returns({"mode": "auto_accept",
                                                       "commission_percent": 5,
                                                       "max_price": 10_000,
                                                       "max_goods": 5})),
                     ("add_log", _noop)]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)
    return state


def test_цена_своего_товара_меняется(market_world):
    msg, replies = _message("рынок цена ogurcy 700")
    asyncio.run(bot_module.cmd_market_own_price(msg))
    assert market_world["prices"] == [(7, 700)]
    assert "700" in replies[0]


def test_цена_выше_потолка_не_проходит(market_world):
    msg, replies = _message("рынок цена ogurcy 99999")
    asyncio.run(bot_module.cmd_market_own_price(msg))
    assert not market_world["prices"]
    assert "отолок" in replies[0]


def test_описание_сохраняется(market_world):
    msg, replies = _message("рынок описание ogurcy Свежие с грядки")
    asyncio.run(bot_module.cmd_market_own_desc(msg))
    assert market_world["descriptions"] == [(7, "Свежие с грядки")]


def test_слишком_длинное_описание_отклоняется(market_world):
    import market as M
    msg, replies = _message("рынок описание ogurcy " + "я" * (M.DESC_MAX + 1))
    asyncio.run(bot_module.cmd_market_own_desc(msg))
    assert not market_world["descriptions"]
    assert str(M.DESC_MAX) in replies[0]


def test_описание_убирается_минусом(market_world):
    msg, replies = _message("рынок описание ogurcy -")
    asyncio.run(bot_module.cmd_market_own_desc(msg))
    assert market_world["descriptions"] == [(7, None)]


def test_чужой_товар_не_тронуть(market_world):
    market_world["goods"][0]["seller_id"] = 999
    msg, replies = _message("рынок цена ogurcy 700")
    asyncio.run(bot_module.cmd_market_own_price(msg))
    assert not market_world["prices"]
    assert "нет товара" in replies[0]


def test_названия_среди_команд_нет():
    """Требование заказчика: под этим названием товар одобрили, и в инвентарях
    покупателей он значится именно так."""
    assert not hasattr(bot_module.db, "set_market_good_name")
    assert not any("рынок название" in e["phrase"]
                   for e in bot_module.COMMAND_REGISTRY.values())


def test_кнопка_рынка_совпадает_с_текстовым_триггером():
    """В этом боте reply-кнопка отправляет свой текст и обязана попадать в тот
    же обработчик, что и набранное вручную (см. private_menu_kb)."""
    assert bot_module.BTN_MY_MARKET.casefold() in bot_module.MARKET_OWN_TRIGGERS


def test_одинаковый_ключ_в_двух_чатах_просит_уточнить(market_world):
    second = dict(market_world["goods"][0])
    second.update(id=8, chat_id=-100999)
    market_world["goods"].append(second)
    msg, replies = _message("рынок цена ogurcy 700")
    asyncio.run(bot_module.cmd_market_own_price(msg))
    assert not market_world["prices"]
    assert "нескольких чатах" in replies[0]


def test_звёздность_считается_от_фармов_а_не_от_столбца():
    """star_level пересчитывается только при фарме. После смены
    FARM_FARMS_PER_STAR столбец отстаёт, и кошелёк обещал бы бонус, которого
    игра не даёт, — ровно та же болезнь, что была у панды."""
    stale = {"total_farms": 40, "star_level": 2}   # столбец из старой формулы
    assert bot_module.wallet_stars(stale) == 8


def test_пустой_кошелёк_без_звёзд():
    assert bot_module.wallet_stars({}) == 0
