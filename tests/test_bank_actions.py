"""Правила банка вне телеграма: вклад, снятие, заявка на кредит, погашение.

Четыре места, ради которых эти проверки и написаны.

ВЫПЛАТА. Простые проценты, ставка фиксируется в момент открытия. Число
показывают трижды — при открытии, пока вклад зреет и при снятии; три места с
одной формулой рано или поздно дают три разных числа, а расхождение человек
читает как обман.

ДОСРОЧНОГО СНЯТИЯ НЕТ. Это правило, а не спрятанная кнопка: кнопка не
единственный вход.

КРЕДИТ НЕ ВЫДАЁТСЯ САМ. Семь проверок до заявки, и они одни на чат и на сайт.
Разъедься они — один из входов начал бы выдавать кредиты тем, кому в другом
отказано.

ПОГАШЕНИЕ НЕ БОЛЬШЕ ДОЛГА. Платёж обрезается ДО списания, иначе заплативший
«с запасом» дарит банку разницу и не может этого заметить.
"""

from __future__ import annotations

import asyncio
import functools
import json
import pathlib
from datetime import datetime, timedelta

import pytest

import bank_actions

CHAT, USER, GATE = -100, 7, -200


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает банк.

    Имена полей взяты из настоящих таблиц (bank_accounts, bank_settings), а не
    выдуманы: выдуманное имя дало бы проверку, подтверждающую несуществующее
    поведение."""

    def __init__(self, coins=100_000):
        self.coins = coins
        self.данные: dict[str, str] = {}
        self.чёрный = False
        self.счёт = {
            "deposit_amount": 0, "deposit_days": None, "deposit_rate": None,
            "deposit_matures_at": None, "credit_amount": 0, "credit_debt": 0,
            "credit_due_at": None,
        }
        self.настройки = {
            "rate_1d": 5.0, "rate_3d": 7.0, "rate_7d": 10.0,
            "credit_fee_percent": 20.0, "credit_term_days": 7,
            "credit_penalty_percent": 10.0, "min_deposit": 1000,
        }
        self.порядок: list[str] = []

    async def get_bank_account(self, chat_id, user_id):
        return dict(self.счёт)

    async def get_bank_settings(self, chat_id):
        return dict(self.настройки)

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def try_spend_coins(self, chat_id, user_id, amount):
        self.порядок.append(f"списали {amount}")
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def add_coins(self, chat_id, user_id, amount):
        self.порядок.append(f"начислили {amount}")
        self.coins += amount
        return self.coins

    async def open_bank_deposit(self, chat_id, user_id, amount, days, rate):
        self.порядок.append("открыли вклад")
        self.счёт.update(deposit_amount=amount, deposit_days=days, deposit_rate=rate,
                         deposit_matures_at=datetime.utcnow() + timedelta(days=days))

    async def close_bank_deposit(self, chat_id, user_id):
        self.порядок.append("закрыли вклад")
        self.счёт.update(deposit_amount=0, deposit_days=None, deposit_rate=None,
                         deposit_matures_at=None)

    async def reduce_bank_credit_debt(self, chat_id, user_id, amount):
        self.порядок.append(f"уменьшили долг на {amount}")
        остаток = max(0, int(self.счёт["credit_debt"]) - amount)
        self.счёт["credit_debt"] = остаток
        return остаток

    async def is_bank_blacklisted(self, chat_id, user_id):
        return self.чёрный

    async def get_data(self, key):
        значение = self.данные.get(key)
        return {"data_key": key, "data_value": значение} if значение is not None else None

    async def set_data(self, key, value, updated_by=None):
        self.данные[key] = value

    async def delete_data(self, key):
        return self.данные.pop(key, None) is not None


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(bank_actions, "db", w)
    return w


# --- выплата ----------------------------------------------------------------

@pytest.mark.parametrize("сумма,ставка,дни,ждём", [
    (1000, 5, 1, 1050),
    (1000, 7, 3, 1210),
    (5000, 10, 7, 8500),
    (1000, 0, 7, 1000),
])
def test_выплата_простыми_процентами(сумма, ставка, дни, ждём):
    """Простые, а не сложные: 7%/день на 3 дня — это +21%, а не +22.5%."""
    assert bank_actions.payout(сумма, ставка, дни) == ждём


def test_формула_выплаты_одна_на_бота_и_сайт():
    """Число показывают трижды — при открытии, пока зреет, при снятии. Три
    места с одной формулой рано или поздно дают три разных числа."""
    исходник = (pathlib.Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert исходник.count("bank_actions.payout(") == 3, (
        "не все три места считают выплату общей формулой")
    assert "amount * rate / 100 * days" not in исходник, "формула снова написана в боте руками"


# --- вклад ------------------------------------------------------------------

@_sync
async def test_вклад_открывается_и_списывает(мир):
    итог = await bank_actions.deposit(CHAT, USER, 2000, 3)
    assert итог.ok
    assert мир.coins == 98_000
    assert итог.payout == bank_actions.payout(2000, 7.0, 3)
    assert мир.порядок == ["списали 2000", "открыли вклад"], (
        "вклад открыт до списания — сбой оставил бы его неоплаченным")


@_sync
async def test_второй_вклад_не_открыть(мир):
    await bank_actions.deposit(CHAT, USER, 2000, 3)
    денег = мир.coins
    итог = await bank_actions.deposit(CHAT, USER, 1000, 1)
    assert not итог.ok and "уже есть" in итог.error
    assert мир.coins == денег, "списали за вклад, который не открыли"


@pytest.mark.parametrize("срок", [0, 2, 5, 30, None, "нет"])
@_sync
async def test_чужой_срок_вклада_не_принимается(мир, срок):
    итог = await bank_actions.deposit(CHAT, USER, 2000, срок)
    assert not итог.ok
    assert мир.coins == 100_000


@_sync
async def test_ниже_минимума_вклад_не_открыть(мир):
    итог = await bank_actions.deposit(CHAT, USER, 999, 1)
    assert not итог.ok and "инимальн" in итог.error
    assert мир.coins == 100_000


@_sync
async def test_без_денег_вклад_не_появляется(мир):
    мир.coins = 500
    итог = await bank_actions.deposit(CHAT, USER, 2000, 1)
    assert not итог.ok
    assert "открыли вклад" not in мир.порядок


@_sync
async def test_ставка_берётся_по_сроку(мир):
    итог = await bank_actions.deposit(CHAT, USER, 1000, 7)
    assert итог.rate == 10.0, "срок 7 дней взял ставку не своего срока"


# --- снятие -----------------------------------------------------------------

@_sync
async def test_досрочно_снять_нельзя(мир):
    await bank_actions.deposit(CHAT, USER, 1000, 3)
    денег = мир.coins
    итог = await bank_actions.withdraw(CHAT, USER)
    assert not итог.ok and "заморожен" in итог.error
    assert мир.coins == денег, "досрочное снятие всё-таки прошло"


@_sync
async def test_созревший_вклад_снимается_с_процентами(мир):
    await bank_actions.deposit(CHAT, USER, 1000, 3)
    было = мир.coins
    поздно = datetime.utcnow() + timedelta(days=4)
    итог = await bank_actions.withdraw(CHAT, USER, now=поздно)
    assert итог.ok
    assert итог.payout == bank_actions.payout(1000, 7.0, 3) == 1210
    assert мир.coins == было + 1210
    assert мир.счёт["deposit_amount"] == 0


@_sync
async def test_снимать_нечего(мир):
    итог = await bank_actions.withdraw(CHAT, USER)
    assert not итог.ok and "нет открытого" in итог.error


# --- погашение --------------------------------------------------------------

@_sync
async def test_погашение_уменьшает_долг(мир):
    мир.счёт["credit_debt"] = 1200
    итог = await bank_actions.repay(CHAT, USER, 500)
    assert итог.ok and итог.debt == 700 and not итог.closed
    assert мир.coins == 99_500


@_sync
async def test_платёж_обрезается_по_долгу(мир):
    """Заплативший «с запасом» подарил бы банку разницу, и заметить это по
    своему балансу было бы нечем."""
    мир.счёт["credit_debt"] = 300
    итог = await bank_actions.repay(CHAT, USER, 10_000)
    assert итог.ok and итог.amount == 300 and итог.closed
    assert мир.coins == 99_700, "списали больше долга"


@_sync
async def test_погасить_всё_словом(мир):
    мир.счёт["credit_debt"] = 750
    итог = await bank_actions.repay(CHAT, USER, "всё")
    assert итог.ok and итог.closed and итог.amount == 750


@_sync
async def test_без_кредита_гасить_нечего(мир):
    итог = await bank_actions.repay(CHAT, USER, 100)
    assert not итог.ok and "нет активного" in итог.error
    assert мир.coins == 100_000


@_sync
async def test_без_денег_долг_не_уменьшается(мир):
    мир.счёт["credit_debt"] = 5000
    мир.coins = 100
    итог = await bank_actions.repay(CHAT, USER, 5000)
    assert not итог.ok
    assert мир.счёт["credit_debt"] == 5000
    assert not any(с.startswith("уменьшили") for с in мир.порядок)


# --- заявка на кредит -------------------------------------------------------

@_sync
async def test_заявка_записывается_с_комиссией(мир):
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert итог.ok
    assert итог.debt == 1200 and итог.term_days == 7
    записано = json.loads(мир.данные[bank_actions.pending_key(CHAT, USER)])
    assert записано == {"amount": 1000, "debt": 1200, "term_days": 7}


@_sync
async def test_заявка_не_выдаёт_деньги_сама(мир):
    """Кредит одобряет админ кнопкой. Заявка не должна ничего начислять —
    иначе одобрение выдало бы деньги второй раз."""
    await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert мир.coins == 100_000
    assert мир.порядок == []


@_sync
async def test_вторая_заявка_не_подаётся(мир):
    await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    итог = await bank_actions.request_credit(CHAT, USER, 5000, GATE)
    assert not итог.ok and "уже есть заявка" in итог.error


@_sync
async def test_с_непогашенным_кредитом_заявку_не_подать(мир):
    мир.счёт["credit_debt"] = 500
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert not итог.ok and "непогашенный" in итог.error
    assert bank_actions.pending_key(CHAT, USER) not in мир.данные


@_sync
async def test_после_взыскания_кредит_не_дают(мир):
    """Взыскание уже увело баланс в минус — новый кредит поверх утроил бы яму
    без единого шанса выбраться."""
    мир.coins = -300
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert not итог.ok and "отрицательный" in итог.error


@_sync
async def test_чёрный_список_закрывает_кредиты(мир):
    мир.чёрный = True
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert not итог.ok and "чёрном списке" in итог.error


@_sync
async def test_автоотказ_закрывает_кредиты(мир):
    мир.данные[bank_actions.auto_reject_key(CHAT)] = "1"
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert not итог.ok and "не выдаются" in итог.error


@_sync
async def test_без_чата_заявок_заявку_не_подать(мир):
    итог = await bank_actions.request_credit(CHAT, USER, 1000, None)
    assert not итог.ok and "некому одобрять" in итог.error
    assert bank_actions.pending_key(CHAT, USER) not in мир.данные


@_sync
async def test_отменённая_заявка_не_блокирует_следующую(мир):
    """Заявка, о которой админы не узнали (сообщение не ушло), навсегда
    закрыла бы человеку кредиты: следующая попытка упрётся в «уже есть»."""
    await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    await bank_actions.cancel_request(CHAT, USER)
    итог = await bank_actions.request_credit(CHAT, USER, 1000, GATE)
    assert итог.ok


def test_ключи_и_кнопки_общие_с_ботом():
    """Заявку с сайта одобряют ТЕМИ ЖЕ кнопками в телеграме, и обработчик
    ищет её по этому самому ключу. Разъедься формат — заявка с сайта осталась
    бы без ответа навсегда, а человек ждал бы решения."""
    assert bank_actions.pending_key(-100, 7) == "bank_credit_pending:-100:7"
    assert bank_actions.auto_reject_key(-100) == "bank_autoreject:-100"
    assert bank_actions.callback_data(True, -100, 7) == "bankcredit_yes:-100:7"
    assert bank_actions.callback_data(False, -100, 7) == "bankcredit_no:-100:7"

    исходник = (pathlib.Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert 'f"bank_credit_pending:{chat_id}:{user_id}"' not in исходник, (
        "бот снова собирает ключ заявки сам")
    assert исходник.count("bank_actions.pending_key(") == 3
    assert "bank_actions.auto_reject_key" in исходник


# --- состояние экрана -------------------------------------------------------

@_sync
async def test_состояние_отдаёт_всё_что_рисует_экран(мир):
    s = await bank_actions.state(CHAT, USER)
    нужны = {"coins", "deposit", "credit", "pending", "terms", "min_deposit",
             "credit_fee_percent", "credit_term_days", "credit_penalty_percent",
             "blacklisted", "auto_reject", "in_the_red"}
    пропали = нужны - set(s)
    assert not пропали, f"экран не получит: {sorted(пропали)}"
    assert [t["days"] for t in s["terms"]] == [1, 3, 7]
    assert s["deposit"] is None and s["credit"] is None


@_sync
async def test_состояние_считает_зрелость_вклада(мир):
    await bank_actions.deposit(CHAT, USER, 1000, 1)
    сейчас = await bank_actions.state(CHAT, USER)
    assert сейчас["deposit"]["ready"] is False
    потом = await bank_actions.state(CHAT, USER, now=datetime.utcnow() + timedelta(days=2))
    assert потом["deposit"]["ready"] is True
    assert потом["deposit"]["payout"] == bank_actions.payout(1000, 5.0, 1)


@_sync
async def test_состояние_говорит_про_просрочку(мир):
    мир.счёт["credit_debt"] = 1200
    мир.счёт["credit_due_at"] = datetime.utcnow() - timedelta(days=1)
    s = await bank_actions.state(CHAT, USER)
    assert s["credit"]["overdue"] is True


def test_панель_ходит_в_банк_только_через_правила():
    """Позови панель db.open_bank_deposit напрямую — и проверки (минимум,
    второй вклад, досрочное снятие) перестанут что-либо значить на сайте."""
    файл = (pathlib.Path(__file__).resolve().parent.parent
            / "webpanel" / "member_bank_api.py")
    текст = файл.read_text(encoding="utf-8")
    мимо = [имя for имя in ("db.open_bank_deposit", "db.close_bank_deposit",
                            "db.open_bank_credit", "db.reduce_bank_credit_debt",
                            "db.get_bank_account", "db.add_coins", "db.try_spend_coins",
                            "db.set_data")
            if имя in текст]
    assert not мимо, f"панель ходит в базу мимо правил банка: {мимо}"
    for действие in ("bank_actions.deposit", "bank_actions.withdraw",
                     "bank_actions.repay", "bank_actions.request_credit",
                     "bank_actions.cancel_request", "bank_actions.callback_data"):
        assert действие in текст, f"{действие} не вызывается"


def test_неотправленная_заявка_отменяется():
    """Заявка есть в базе, а админы о ней не знают — человек заперт: следующая
    попытка упрётся в «у вас уже есть заявка»."""
    текст = ((pathlib.Path(__file__).resolve().parent.parent
              / "webpanel" / "member_bank_api.py").read_text(encoding="utf-8"))
    кусок = текст[текст.index("result = await bank_actions.request_credit"):]
    кусок = кусок[:кусок.index("if not result.ok")]
    assert "cancel_request" in кусок, "не отменяют заявку, которая не ушла админам"
