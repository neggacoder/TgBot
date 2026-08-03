"""Рулетка казино: слово-триггер и общий с казино кошелёк.

Раньше рулетка стояла особняком: вызывалась только «.рулетка» (единственная
команда казино с точкой) и играла прямо из кошелька i¢, а не с баланса
казино, как кости, орёл/решка и покер. Из-за этого выигрыш в казино нельзя
было проиграть в казино, а «казино вывести» её вовсе не касалось.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

# Проверка «+бесконечность» стала асинхронной: список читается из базы на
# каждый вопрос, иначе рубильник с сайта для бота не существует до
# перезапуска (см. owner_flags). Синхронная заглушка отдавала bool, а его
# нельзя await'ить.
async def _не_бесконечность(user_id):
    return False


async def _бесконечность(user_id):
    return True


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

    async def answer(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    object.__setattr__(m, "answer", answer)
    return m, replies


# --- триггеры --------------------------------------------------------------

def _handlers_for(text: str) -> list:
    msg, _ = _message(text)

    async def run():
        found = []
        for handler in bot_module.router.message.handlers:
            ok, _data = await handler.check(msg, bot=bot_module.bot)
            if ok:
                found.append(handler.callback.__name__)
        return found

    return asyncio.run(run())


@pytest.mark.parametrize("text", [
    "рулетка 100 красное",
    "РУЛЕТКА 100 Красное",
    ".рулетка 100 красное",      # старая форма — остаётся рабочей
    "!рулетка 100 зелёное",
])
def test_рулетка_ловится_с_точкой_и_без(text):
    assert "cmd_casino_roulette" in _handlers_for(text)


@pytest.mark.parametrize("text", ["рулетка", ".рулетка", "!рулетка"])
def test_голая_рулетка_отдаёт_подсказку_а_не_молчит(text):
    """Иначе узнавший о команде пишет «рулетка», получает тишину и решает,
    что команды нет."""
    assert "cmd_casino_roulette_help" in _handlers_for(text)


def test_обычная_фраза_со_словом_рулетка_не_триггерит():
    assert _handlers_for("рулетка красная в магазине") == []


@pytest.mark.parametrize("text", ["русскаяру", "русскаяру 3"])
def test_русская_рулетка_не_задета(text):
    """Шуточная игра с киком живёт на другом слове — её нельзя было зацепить,
    открывая казино-рулетку для голого «рулетка»."""
    taken = _handlers_for(text)
    assert "cmd_roulette" in taken
    assert "cmd_casino_roulette" not in taken


@pytest.mark.parametrize("text", ["+рулетка", "-рулетка"])
def test_переключатели_русской_рулетки_не_задеты(text):
    taken = _handlers_for(text)
    assert "cmd_roulette_toggle" in taken
    assert "cmd_casino_roulette" not in taken
    assert "cmd_casino_roulette_help" not in taken


# --- кошелёк ---------------------------------------------------------------

@pytest.fixture
def casino(monkeypatch):
    """Казино-баланс и кошелёк i¢ по отдельности — чтобы видеть, что тронуто."""
    state = {"casino": 1_000, "coins": 50_000, "log": [], "lucky": False}

    # Подкрученный фарт («фарт» у владельца бота). По умолчанию его нет —
    # обычная рулетка обязана оставаться честной; сам фарт проверяется ниже.
    async def take_lucky(user_id):
        было, state["lucky"] = state["lucky"], False
        return было

    monkeypatch.setattr(bot_module, "_take_lucky_roulette", take_lucky, raising=False)

    async def get_casino_wallet(chat_id, user_id):
        return {"balance": state["casino"], "last_bonus_date": None}

    async def try_spend_casino_balance(chat_id, user_id, amount):
        if state["casino"] < amount:
            return False
        state["casino"] -= amount
        return True

    async def add_casino_balance(chat_id, user_id, amount):
        state["casino"] = max(0, state["casino"] + amount)
        return state["casino"]

    async def add_coins(chat_id, user_id, amount):
        state["coins"] += amount
        return state["coins"]

    async def try_spend_coins(chat_id, user_id, amount):
        if state["coins"] < amount:
            return False
        state["coins"] -= amount
        return True

    monkeypatch.setattr(bot_module.db, "get_casino_wallet", get_casino_wallet, raising=False)
    monkeypatch.setattr(bot_module.db, "try_spend_casino_balance",
                        try_spend_casino_balance, raising=False)
    monkeypatch.setattr(bot_module.db, "add_casino_balance", add_casino_balance, raising=False)
    monkeypatch.setattr(bot_module.db, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(bot_module.db, "try_spend_coins", try_spend_coins, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "has_infinite_money", _не_бесконечность, raising=False)
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    return state


def _play(text="рулетка 100 красное"):
    msg, replies = _message(text)
    asyncio.run(bot_module.cmd_casino_roulette(msg))
    return replies


def test_проигрыш_снимает_с_казино_а_не_с_кошелька(casino, monkeypatch):
    """Главное в этой правке: рулетка играет тем же кошельком, что кости,
    орёл/решка и покер, — иначе выигранное в казино нельзя проиграть в казино."""
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 2)   # чёрное
    _play("рулетка 100 красное")
    assert casino["casino"] == 900
    assert casino["coins"] == 50_000, "основной кошелёк рулетка трогать не должна"


def test_выигрыш_ложится_на_казино_баланс(casino, monkeypatch):
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 1)   # красное
    _play("рулетка 100 красное")
    # ставка вернулась + столько же выигрыша (x2)
    assert casino["casino"] == 1_000 + 100
    assert casino["coins"] == 50_000


def test_зелёное_платит_x14(casino, monkeypatch):
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 0)   # зеро
    _play("рулетка 100 зелёное")
    assert casino["casino"] == 1_000 + 1_300


def test_без_денег_в_казино_ставка_не_проходит(casino, monkeypatch):
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 2)
    casino["casino"] = 50
    replies = _play("рулетка 100 красное")
    assert casino["casino"] == 50
    assert casino["coins"] == 50_000, "из кошелька добирать нельзя"
    assert "Недостаточно средств в казино" in replies[0]
    assert "казино пополнить" in replies[0]


def test_ставка_списывается_до_розыгрыша(casino, monkeypatch):
    """Порядок защищает от гонки: две рулетки подряд не должны обе пройти
    проверку с одними и теми же деньгами."""
    order: list = []

    async def try_spend(chat_id, user_id, amount):
        order.append("spend")
        casino["casino"] -= amount
        return True

    monkeypatch.setattr(bot_module.db, "try_spend_casino_balance", try_spend, raising=False)
    monkeypatch.setattr(bot_module.random, "randint",
                        lambda a, b: order.append("roll") or 2)
    _play("рулетка 100 красное")
    assert order[0] == "spend", order


def test_две_ставки_подряд_не_проходят_на_одних_деньгах(casino, monkeypatch):
    """Ровно тот сценарий, ради которого списание атомарное."""
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 2)
    casino["casino"] = 100
    _play("рулетка 100 красное")
    replies = _play("рулетка 100 красное")
    assert casino["casino"] == 0
    assert "Недостаточно средств" in replies[0]


def test_замороженному_счёту_играть_нельзя(casino, monkeypatch):
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 2)
    _play("рулетка 100 красное")
    assert casino["casino"] == 1_000


def test_ответ_показывает_баланс_казино(casino, monkeypatch):
    """Как у костей — иначе непонятно, чем именно ты играешь."""
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 2)
    replies = _play("рулетка 100 красное")
    assert "Баланс казино" in replies[0]


def test_неверный_цвет_объясняет_без_точки(casino):
    replies = _play("рулетка 100 синее")
    assert "рулетка {ставка} {цвет}" in replies[0]
    assert ".рулетка {ставка}" not in replies[0], "подсказка не должна учить старой форме"
    assert casino["casino"] == 1_000, "при непонятном цвете деньги не трогаем"


# --- подкрученный фарт ------------------------------------------------------
#
# Владелец бота выдаёт человеку один гарантированно выигрышный заход — просто
# чтобы обрадовать. Ломается это двумя способами: фарт не срабатывает вовсе
# или, наоборот, не сгорает и превращается в станок.

def test_фарт_делает_следующий_заход_выигрышным(casino, monkeypatch):
    casino["lucky"] = True
    # Кубик оставляем честным: подкрутка обязана работать сама, а не совпадать.
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 0)

    ответ = "\n".join(_play("рулетка 100 красное"))

    assert "Выигрыш" in ответ, ответ
    assert "Красное" in ответ


def test_фарт_сгорает_после_одного_захода(casino, monkeypatch):
    casino["lucky"] = True
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 0)  # честный ноль — зелёное

    первый = "\n".join(_play("рулетка 100 красное"))
    второй = "\n".join(_play("рулетка 100 красное"))

    assert "Выигрыш" in первый
    assert "Проигрыш" in второй, "заряд не сгорел — подарок стал станком"


def test_фарт_уважает_выбранный_цвет(casino, monkeypatch):
    """Гарантия — на ЦВЕТ ставки, а не на «красное всегда»."""
    casino["lucky"] = True
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 1)  # честная единица — красное

    ответ = "\n".join(_play("рулетка 100 черное"))

    assert "Выигрыш" in ответ and "Чёрное" in ответ, ответ


def test_без_фарта_рулетка_остаётся_честной(casino, monkeypatch):
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 0)   # зелёное
    assert "Проигрыш" in "\n".join(_play("рулетка 100 красное"))
