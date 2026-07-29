"""Новые способы заработка: ежедневный бонус, подработка, шапка по кругу.

Три механики с разными правилами доступа (сутки / откат / откат + чужие
кошельки), поэтому и проверяется в каждой своё: что нельзя забрать дважды,
что деньги не появляются из воздуха и что откат ставится ДО начисления.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

@pytest.fixture(autouse=True)
def _обычный_множитель_дохода(monkeypatch):
    """Заработок с некоторых пор домножается на настройку чата
    («доход подработка 50»). Здесь она не проверяется — у неё свой тест, — но
    без заглушки эти тесты полезли бы в базу за ней."""
    async def сто(chat_id, source):
        return 100.0

    async def _учёт(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.db, "get_income_percent", сто, raising=False)
    # Ферма, рыбалка и клад теперь пишут строку учёта в earning_activity —
    # ради отчёта «экономика». Кулдауны у них по-прежнему свои, поэтому здесь
    # это просто лишний поход в базу.
    monkeypatch.setattr(bot_module.db, "touch_earning_activity", _учёт, raising=False)
    monkeypatch.setattr(bot_module.db, "bump_activity_today", _учёт, raising=False)

    # Суточный лимит подработок: 0 — «без лимита», то есть поведение до его
    # появления. Сам лимит проверяется своим тестом.
    async def _без_лимита(chat_id):
        return 0

    monkeypatch.setattr(bot_module.db, "get_side_job_daily_limit",
                        _без_лимита, raising=False)



CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def earn(monkeypatch):
    """Общая обвязка: замороженных нет, ачивки молчат, монеты и отметки пишутся
    в словарь, чтобы можно было проверить и суммы, и порядок записей."""
    state = {"coins": 0, "touched": [], "row": None}

    async def add_coins(chat_id, user_id, amount):
        state["coins"] += amount
        return state["coins"]

    async def touch(chat_id, user_id, key, now, streak=None, day=None, earned=0):
        state["touched"].append({"key": key, "streak": streak, "day": day, "earned": earned})

    async def get_activity(chat_id, user_id, key):
        return state["row"]

    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(bot_module.db, "touch_earning_activity", touch, raising=False)
    monkeypatch.setattr(bot_module.db, "get_earning_activity", get_activity, raising=False)
    return state


# --- ежедневный бонус ------------------------------------------------------

def test_бонус_растёт_с_серией():
    assert bot_module.daily_bonus_amount(1) == bot_module.DAILY_BONUS_BASE
    assert bot_module.daily_bonus_amount(2) == bot_module.DAILY_BONUS_BASE + bot_module.DAILY_BONUS_STEP
    assert bot_module.daily_bonus_amount(3) > bot_module.daily_bonus_amount(2)


def test_каждый_седьмой_день_двойной():
    day6, day7 = bot_module.daily_bonus_amount(6), bot_module.daily_bonus_amount(7)
    assert day7 == (bot_module.DAILY_BONUS_BASE + bot_module.DAILY_BONUS_STEP * 6) * 2
    assert day7 > day6 * 1.5


def test_бонус_перестаёт_расти_на_потолке():
    """Иначе через полгода ежедневный бонус обгонит все остальные механики."""
    cap = bot_module.DAILY_BONUS_MAX_DAYS
    at_cap = bot_module.DAILY_BONUS_BASE + bot_module.DAILY_BONUS_STEP * (cap - 1)
    # Берём дни, не кратные семи: у кратных сверху включается удвоение.
    for streak in (cap, cap + 1, cap + 100):
        if streak % 7 == 0:
            continue
        assert bot_module.daily_bonus_amount(streak) == at_cap, streak


def test_первый_бонус_начинает_серию(earn):
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == bot_module.DAILY_BONUS_BASE
    assert earn["touched"][0]["streak"] == 1
    assert "Серия начата" in text


def test_второй_день_подряд_продолжает_серию(earn):
    earn["row"] = {"last_day": bot_module.utc_today() - timedelta(days=1), "streak": 4,
                   "last_at": datetime.utcnow() - timedelta(days=1)}
    asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert earn["touched"][0]["streak"] == 5
    assert earn["coins"] == bot_module.daily_bonus_amount(5)


def test_пропуск_дня_обнуляет_серию(earn):
    earn["row"] = {"last_day": bot_module.utc_today() - timedelta(days=3), "streak": 10,
                   "last_at": datetime.utcnow() - timedelta(days=3)}
    asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert earn["touched"][0]["streak"] == 1
    assert earn["coins"] == bot_module.DAILY_BONUS_BASE


def test_дважды_за_день_не_забрать(earn):
    earn["row"] = {"last_day": bot_module.utc_today(), "streak": 3,
                   "last_at": datetime.utcnow()}
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 0 and not earn["touched"]
    assert "уже забрали" in text


def test_замороженному_счёту_бонус_не_идёт(earn, monkeypatch):
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 0 and not earn["touched"]
    assert "заморожен" in text


# --- подработка ------------------------------------------------------------

def test_подработка_платит_и_ставит_откат(earn, monkeypatch):
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.5)   # без чаевых и без кидалова
    text = asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))
    assert earn["coins"] > 0
    assert earn["touched"][0]["key"] == bot_module.EARN_SIDE_JOB
    assert "i¢" in text


def test_подработка_под_откатом_не_платит(earn, monkeypatch):
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    earn["row"] = {"last_at": datetime.utcnow() - timedelta(minutes=1),
                   "streak": 0, "last_day": None}
    text = asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 0 and not earn["touched"]
    assert "Следующая" in text


def test_кидалово_оставляет_без_денег_но_с_откатом(earn, monkeypatch):
    """Откат обязан встать и при нулевой оплате — иначе неудачную подработку
    можно было бы просто перезапускать до победного."""
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)
    text = asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 0
    assert earn["touched"] and earn["touched"][0]["key"] == bot_module.EARN_SIDE_JOB
    assert "пропал" in text


def test_чаевые_поднимают_оплату(earn, monkeypatch):
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    monkeypatch.setattr(bot_module.random, "choice", lambda seq: ("📦", "тест", 100, 100))
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 100)
    monkeypatch.setattr(bot_module.random, "random",
                        lambda: bot_module.SIDE_JOB_SCAM_CHANCE + 0.001)
    text = asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 150
    assert "чаевые" in text


def test_аврал_поднимает_подработку(earn, monkeypatch):
    """Подработка — тоже работа за деньги, событие «Аврал» её не обходит."""
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(2.0), raising=False)
    monkeypatch.setattr(bot_module.random, "choice", lambda seq: ("📦", "тест", 100, 100))
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 100)
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.5)
    asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))
    assert earn["coins"] == 200


def test_все_подработки_платят_положительно():
    for emoji, what, low, high in bot_module.SIDE_JOBS:
        assert emoji and what
        assert 0 < low <= high, what


# --- шапка по кругу --------------------------------------------------------

class _FakeMessage:
    def __init__(self, chat_id, message_id, edited: list):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.message_id = message_id
        self._edited = edited

    async def edit_text(self, text, reply_markup=None):
        self._edited.append(text)


class _FakeCallback:
    """Минимальный CallbackQuery: обработчику шапки нужны только чат, номер
    сообщения, автор нажатия и возможность ответить."""

    def __init__(self, chat_id, message_id, user_id):
        self.answers: list = []
        self.edited: list = []
        self.from_user = type("User", (), {"id": user_id})()
        self.message = _FakeMessage(chat_id, message_id, self.edited)
        self.data = "hat_drop"

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


@pytest.fixture
def hat(monkeypatch):
    """Открытый сбор в памяти + подменённые кошельки."""
    state = {"spent": [], "received": 0, "enough": True}

    async def spend(chat_id, user_id, amount):
        if not state["enough"]:
            return False
        state["spent"].append((user_id, amount))
        return True

    async def add_coins(chat_id, user_id, amount):
        state["received"] += amount
        return state["received"]

    monkeypatch.setattr(bot_module, "spend_coins", spend, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module.db, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)

    key = (CHAT_ID, 1)
    bot_module._hat_rounds[key] = {
        "owner_id": USER_ID, "owner_name": "Хозяин", "donors": set(), "total": 0,
        "expires_at": datetime.utcnow() + bot_module.HAT_OPEN_FOR,
    }
    state["round"] = bot_module._hat_rounds[key]
    yield state
    bot_module._hat_rounds.pop(key, None)


def test_чужой_кидает_и_деньги_переходят(hat):
    cb = _FakeCallback(CHAT_ID, 1, 777)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert hat["spent"] == [(777, bot_module.HAT_DONATION)]
    assert hat["received"] == bot_module.HAT_DONATION
    assert hat["round"]["total"] == bot_module.HAT_DONATION


def test_второй_раз_тот_же_человек_не_кидает(hat):
    asyncio.run(bot_module.cb_hat_drop(_FakeCallback(CHAT_ID, 1, 777)))
    cb = _FakeCallback(CHAT_ID, 1, 777)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert len(hat["spent"]) == 1
    assert "уже скинулись" in cb.answers[0]


def test_себе_в_шапку_нельзя(hat):
    cb = _FakeCallback(CHAT_ID, 1, USER_ID)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert not hat["spent"] and hat["received"] == 0


def test_без_денег_попытка_не_засчитывается(hat):
    """Отказ по деньгам не должен «сжигать» право скинуться позже."""
    hat["enough"] = False
    cb = _FakeCallback(CHAT_ID, 1, 777)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert hat["received"] == 0
    assert 777 not in hat["round"]["donors"]

    hat["enough"] = True
    asyncio.run(bot_module.cb_hat_drop(_FakeCallback(CHAT_ID, 1, 777)))
    assert hat["received"] == bot_module.HAT_DONATION


def test_закрытый_сбор_не_принимает(hat):
    hat["round"]["expires_at"] = datetime.utcnow() - timedelta(seconds=1)
    cb = _FakeCallback(CHAT_ID, 1, 777)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert hat["received"] == 0 and "закрыт" in cb.answers[0]


def test_несуществующий_сбор_не_падает():
    cb = _FakeCallback(CHAT_ID, 12345, 777)
    asyncio.run(bot_module.cb_hat_drop(cb))
    assert cb.answers and "закрыт" in cb.answers[0]
