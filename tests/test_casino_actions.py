"""Правила казино вне телеграма: ставка, выплата, кошелёк, текст для чата.

Деньги — то место, где вторая правда обходится дороже всего, поэтому проверки
тут не про интерфейс, а про арифметику: сколько списали, сколько вернули и что
именно уходит в чат кнопкой «показать всем».
"""

from __future__ import annotations

import asyncio
import functools
import random
from datetime import date

import pytest

import casino_actions


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает казино."""

    def __init__(self, casino=10_000, coins=50_000):
        self.casino = casino
        self.coins = coins
        self.games = 0
        self.bonus_date = None
        self.achievements: set[str] = set()

    async def get_casino_wallet(self, chat_id, user_id):
        return {"balance": self.casino, "last_bonus_date": self.bonus_date}

    async def add_casino_balance(self, chat_id, user_id, amount):
        self.casino = max(0, self.casino + amount)
        return self.casino

    async def try_spend_casino_balance(self, chat_id, user_id, amount):
        if self.casino < amount:
            return False
        self.casino -= amount
        return True

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins, "total_farms": 0}

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def increment_casino_games(self, chat_id, user_id):
        self.games += 1
        return self.games

    async def get_casino_games(self, chat_id, user_id):
        return self.games

    async def claim_daily_bonus(self, chat_id, user_id, amount, today=None):
        if self.bonus_date == today:
            return False, self.casino
        self.bonus_date = today
        self.casino += amount
        return True, self.casino

    async def get_profile_card(self, chat_id, user_id):
        return {}

    async def list_pets(self, chat_id, user_id):
        return []

    async def get_data(self, key):
        return None


CHAT, USER = -100, 7


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(casino_actions, "db", world)
    # Событий и питомцев в этих проверках нет: они множат выигрыш, и с ними
    # арифметику пришлось бы сверять с двумя надбавками сразу.
    monkeypatch.setattr(casino_actions, "event_multiplier", _единица)
    monkeypatch.setattr(casino_actions, "pet_lucky", _без_надбавки)
    return world


async def _единица(chat_id):
    return 1.0


async def _без_надбавки(chat_id, user_id, amount):
    return amount


# --- чистая арифметика ------------------------------------------------------

def test_цвет_числа_как_на_колесе():
    assert casino_actions.roulette_number_color(0) == "green"
    assert casino_actions.roulette_number_color(1) == "red"
    assert casino_actions.roulette_number_color(2) == "black"
    цвета = {casino_actions.roulette_number_color(n) for n in range(37)}
    assert цвета == {"red", "black", "green"}
    красных = sum(1 for n in range(37)
                  if casino_actions.roulette_number_color(n) == "red")
    assert красных == 18


def test_комбинации_покера_оцениваются():
    оценить = casino_actions.evaluate_poker_hand
    assert оценить([(14, "♠"), (13, "♠"), (12, "♠"), (11, "♠"), (10, "♠")])[0] == 10
    assert оценить([(9, "♠"), (9, "♥"), (9, "♦"), (9, "♣"), (2, "♠")])[0] == 10
    assert оценить([(9, "♠"), (9, "♥"), (9, "♦"), (2, "♣"), (2, "♠")])[0] == 8
    assert оценить([(9, "♠"), (7, "♠"), (5, "♠"), (3, "♠"), (2, "♠")])[0] == 6
    assert оценить([(14, "♠"), (5, "♥"), (4, "♦"), (3, "♣"), (2, "♠")])[0] == 5
    assert оценить([(9, "♠"), (9, "♥"), (9, "♦"), (5, "♣"), (2, "♠")])[0] == 3
    assert оценить([(9, "♠"), (9, "♥"), (5, "♦"), (5, "♣"), (2, "♠")])[0] == 2
    assert оценить([(9, "♠"), (9, "♥"), (7, "♦"), (5, "♣"), (2, "♠")])[0] == 0


def test_в_колоде_нет_повторов():
    рука = casino_actions.draw_poker_hand()
    assert len(рука) == 5 and len(set(рука)) == 5


# --- рулетка ----------------------------------------------------------------

@_sync
async def test_выигрыш_в_рулетке_платит_вдвое(мир):
    было = мир.casino
    итог = await casino_actions.roulette(CHAT, USER, 100, "красное", lucky=True)
    assert итог.ok and итог.won and итог.multiplier == 2
    assert итог.delta == 100                     # чистыми ставка сверху
    assert мир.casino == было + 100
    assert итог.detail["color"] == "red"


@_sync
async def test_зелёное_платит_четырнадцать(мир):
    итог = await casino_actions.roulette(CHAT, USER, 100, "зелёное", lucky=True)
    assert итог.multiplier == 14 and итог.delta == 1300


@_sync
async def test_проигрыш_забирает_ставку_и_только_её(мир, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 2)   # чёрное
    было = мир.casino
    итог = await casino_actions.roulette(CHAT, USER, 100, "красное")
    assert итог.ok and not итог.won and итог.delta == -100
    assert мир.casino == было - 100


@_sync
async def test_ставка_больше_баланса_не_играется(мир):
    итог = await casino_actions.roulette(CHAT, USER, мир.casino + 1, "красное")
    assert not итог.ok and "Недостаточно" in итог.error
    assert мир.casino == 10_000


@_sync
async def test_ставка_все_это_весь_баланс_казино(мир):
    итог = await casino_actions.roulette(CHAT, USER, "все", "красное", lucky=True)
    assert итог.bet == 10_000 and итог.won


@_sync
async def test_непонятный_цвет_это_отказ(мир):
    итог = await casino_actions.roulette(CHAT, USER, 100, "синее")
    assert not итог.ok and мир.casino == 10_000


# --- кости, монета, покер ---------------------------------------------------

@_sync
async def test_кости_платят_вшестеро(мир, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    итог = await casino_actions.dice(CHAT, USER, 100, 4)
    assert итог.won and итог.multiplier == 6 and итог.delta == 500


@_sync
async def test_кости_вне_диапазона_отказ(мир):
    for число in (0, 7, "семь"):
        итог = await casino_actions.dice(CHAT, USER, 100, число)
        assert not итог.ok
    assert мир.casino == 10_000


@_sync
async def test_монета_платит_вдвое(мир, monkeypatch):
    monkeypatch.setattr(random, "choice", lambda seq: "орёл")
    итог = await casino_actions.coin(CHAT, USER, 100, "орел")
    assert итог.won and итог.delta == 100
    assert итог.detail["side"] == "орёл"


@_sync
async def test_покер_считает_по_руке(мир, monkeypatch):
    рука = [(14, "♠"), (14, "♥"), (14, "♦"), (14, "♣"), (2, "♠")]
    monkeypatch.setattr(casino_actions, "draw_poker_hand", lambda: рука)
    итог = await casino_actions.poker(CHAT, USER, 100)
    assert итог.won and итог.multiplier == 10 and итог.delta == 900
    assert итог.detail["combo"] == "каре"


# --- ачивки и счётчик -------------------------------------------------------

@_sync
async def test_сотая_игра_даёт_ачивку(мир):
    мир.games = 99
    итог = await casino_actions.dice(CHAT, USER, 100, 1)
    assert "casino_100_games" in итог.achievements


@_sync
async def test_рулетка_не_считается_в_сотню_как_и_в_чате(мир):
    """Не наша прихоть, а как есть у бота. Считай сайт иначе — сотня набралась
    бы в разных местах по-разному, и ачивка приходила бы за разное."""
    мир.games = 99
    итог = await casino_actions.roulette(CHAT, USER, 100, "красное", lucky=True)
    assert итог.achievements == [] and мир.games == 99


@_sync
async def test_крупный_выигрыш_это_джекпот(мир):
    мир.casino = 100_000
    итог = await casino_actions.dice(CHAT, USER, 2_000, 1)
    if итог.won:
        assert "casino_jackpot" in итог.achievements


# --- кошелёк ----------------------------------------------------------------

@_sync
async def test_пополнение_переносит_из_кошелька(мир):
    итог = await casino_actions.topup(CHAT, USER, 5_000)
    assert итог.ok and мир.coins == 45_000 and мир.casino == 15_000


@_sync
async def test_пополнить_больше_чем_есть_нельзя(мир):
    итог = await casino_actions.topup(CHAT, USER, 999_999)
    assert not итог.ok and мир.coins == 50_000 and мир.casino == 10_000


@_sync
async def test_вывод_возвращает_в_кошелёк(мир):
    итог = await casino_actions.withdraw(CHAT, USER, "все")
    assert итог.ok and мир.casino == 0 and мир.coins == 60_000


@_sync
async def test_бонус_даётся_раз_в_сутки(мир):
    сегодня = date(2026, 8, 2)
    первый = await casino_actions.daily_bonus(CHAT, USER, today=сегодня)
    assert первый.ok and первый.delta == casino_actions.DAILY_BONUS
    второй = await casino_actions.daily_bonus(CHAT, USER, today=сегодня)
    assert not второй.ok
    завтра = await casino_actions.daily_bonus(CHAT, USER, today=date(2026, 8, 3))
    assert завтра.ok


# --- состояние и текст для чата ---------------------------------------------

@_sync
async def test_состояние_описывает_стол(мир):
    итог = await casino_actions.state(CHAT, USER, today=date(2026, 8, 2))
    assert итог["balance"] == 10_000 and итог["coins"] == 50_000
    assert итог["bonus_ready"] is True
    assert {g["key"] for g in итог["games"]} == set(casino_actions.GAMES)
    assert [c["payout"] for c in итог["colors"]] == [2, 2, 14]


@_sync
async def test_показ_в_чате_называет_игрока_и_исход(мир):
    """Текст строит модуль, а не браузер: «покажи всем» обязано показывать то,
    что случилось, а не то, что прислали с сайта."""
    итог = await casino_actions.roulette(CHAT, USER, 100, "зелёное", lucky=True)
    текст = casino_actions.render_share(итог, "Лина")
    assert "Лина" in текст
    assert "Выигрыш" in текст and "x14" in текст
    assert str(итог.detail["number"]) in текст
    assert "🟢" in текст


@_sync
async def test_показ_проигрыша_не_врёт(мир, monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 2)
    итог = await casino_actions.roulette(CHAT, USER, 100, "красное")
    текст = casino_actions.render_share(итог, "Лина")
    assert "Проигрыш" in текст and "-100" in текст


@_sync
async def test_показ_покера_называет_руку(мир, monkeypatch):
    рука = [(9, "♠"), (9, "♥"), (5, "♦"), (5, "♣"), (2, "♠")]
    monkeypatch.setattr(casino_actions, "draw_poker_hand", lambda: рука)
    итог = await casino_actions.poker(CHAT, USER, 100)
    текст = casino_actions.render_share(итог, "Лина")
    assert "9♠" in текст and "две пары" in текст


@_sync
async def test_состояние_отдаёт_красные_числа(мир):
    """Лента на экране красится этим списком. Заведи браузер свой — цвет на
    картинке разошёлся бы с тем, что решает выплату."""
    итог = await casino_actions.state(CHAT, USER, today=date(2026, 8, 2))
    assert set(итог["reds"]) == set(casino_actions.RED_NUMBERS)
    assert all(casino_actions.roulette_number_color(n) == "red" for n in итог["reds"])
