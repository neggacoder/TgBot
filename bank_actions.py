"""Банк: вклад, снятие, заявка на кредит, погашение. Ничего не отправляет.

Девятый модуль того же устройства. Правила живут здесь, бот и веб-панель зовут
их и по-своему показывают ответ.

Четыре места, где ошибиться легко и дорого.

ВЫПЛАТА ПО ВКЛАДУ. Простые проценты, ставка фиксируется в момент открытия:
сумма + сумма × ставка/100 × дни. Считается ОДНОЙ функцией, потому что число
это показывают трижды — когда открывают вклад, пока он зреет и когда снимают.
Три места с одной формулой рано или поздно дают три разных числа, а человек
видит расхождение как обман.

ДОСРОЧНОГО СНЯТИЯ НЕТ. Вклад заморожен до срока, и это правило, а не
ограничение интерфейса: спрятать кнопку мало, потому что кнопка — не
единственный вход.

КРЕДИТ НЕ ВЫДАЁТСЯ САМ. Заявку одобряет админ кнопкой в телеграме. Здесь
только проверки и запись заявки; кому и как её показать — дело вызывающего,
у бота и у панели это разные пути. Зато проверок семь, и они одни на оба
входа: чёрный список, отрицательный баланс после взыскания, автоотказ,
непогашенный кредит, уже поданная заявка, ненастроенный чат заявок и сумма.

ПОГАШЕНИЕ НЕ БОЛЬШЕ ДОЛГА. Платёж обрезается по остатку ДО списания — иначе
человек, заплативший «с запасом», подарил бы банку разницу.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

import db

logger = logging.getLogger(__name__)

DEPOSIT_TERMS = (1, 3, 7)               # сроки вклада в днях
RATE_COLUMN = {1: "rate_1d", 3: "rate_3d", 7: "rate_7d"}

# Ключи общих с ботом записей. Формат обязан совпадать до символа: заявку с
# сайта одобряют теми же кнопками в телеграме, что и заявку из чата, а
# обработчик кнопки ищет её по этому самому ключу.
def pending_key(chat_id: int, user_id: int) -> str:
    return f"bank_credit_pending:{chat_id}:{user_id}"


def auto_reject_key(chat_id: int) -> str:
    return f"bank_autoreject:{chat_id}"


def callback_data(approve: bool, chat_id: int, user_id: int) -> str:
    return f"bankcredit_{'yes' if approve else 'no'}:{chat_id}:{user_id}"


@dataclass
class BankResult:
    ok: bool
    error: str = ""
    action: str = ""
    amount: int = 0            # сколько монет ушло или пришло
    payout: int = 0            # выплата по вкладу
    days: int = 0
    rate: float = 0.0
    debt: int = 0              # остаток долга после погашения
    term_days: int = 0
    closed: bool = False       # кредит закрыт полностью
    user_id: int = 0


def payout(amount: int, rate: float, days: int) -> int:
    """Выплата по вкладу: простые проценты за весь срок.

    Одна функция на все три места, где это число показывают. Совпадать они
    обязаны до монеты — расхождение человек читает как обман, а не как
    округление.
    """
    return int(amount + amount * float(rate) / 100 * int(days))


def _amount(raw: Union[int, str, None]) -> Optional[int]:
    if raw is None:
        return None
    try:
        значение = int(float(raw))
    except (TypeError, ValueError):
        return None
    return значение if значение > 0 else None


async def auto_reject(chat_id: int) -> bool:
    """Выключены ли кредиты в чате. Ключ общий с ботом — иначе рубильник
    работал бы в чате и не работал на сайте."""
    row = await db.get_data(auto_reject_key(chat_id))
    return row is not None and row.get("data_value") == "1"


async def state(chat_id: int, user_id: int, now: Optional[datetime] = None) -> dict:
    """Всё, что нужно экрану: вклад, долг, ставки и что мешает взять кредит."""
    now = now or datetime.utcnow()
    account = await db.get_bank_account(chat_id, user_id)
    s = await db.get_bank_settings(chat_id) or {}
    wallet = await db.get_wallet(chat_id, user_id)
    заявка = await db.get_data(pending_key(chat_id, user_id))

    вклад = None
    if account["deposit_amount"]:
        созреет = account["deposit_matures_at"]
        дни = int(account["deposit_days"])
        ставка = float(account["deposit_rate"])
        вклад = {
            "amount": int(account["deposit_amount"]),
            "days": дни,
            "rate": ставка,
            "payout": payout(int(account["deposit_amount"]), ставка, дни),
            "matures_at": созреет.isoformat() if созреет else None,
            "ready": bool(созреет and now >= созреет),
        }

    кредит = None
    if account["credit_debt"]:
        срок = account["credit_due_at"]
        кредит = {
            "debt": int(account["credit_debt"]),
            "amount": int(account["credit_amount"] or 0),
            "due_at": срок.isoformat() if срок else None,
            "overdue": bool(срок and now >= срок),
        }

    монеты = int(wallet["coins"])
    return {
        "now": now.isoformat(),
        "coins": монеты,
        "deposit": вклад,
        "credit": кредит,
        "pending": bool(заявка and заявка.get("data_value")),
        "terms": [
            {"days": д, "rate": float(s.get(RATE_COLUMN[д]) or 0)} for д in DEPOSIT_TERMS
        ],
        "min_deposit": int(s.get("min_deposit") or 0),
        "credit_fee_percent": float(s.get("credit_fee_percent") or 0),
        "credit_term_days": int(s.get("credit_term_days") or 0),
        "credit_penalty_percent": float(s.get("credit_penalty_percent") or 0),
        # Почему кредит недоступен — экран обязан сказать это заранее, а не
        # после нажатия: отказ по факту читается как поломка.
        "blacklisted": await db.is_bank_blacklisted(chat_id, user_id),
        "auto_reject": await auto_reject(chat_id),
        "in_the_red": монеты < 0,
    }


async def deposit(chat_id: int, user_id: int, raw: Union[int, str, None],
                  days: Union[int, str, None]) -> BankResult:
    amount = _amount(raw)
    if amount is None:
        return BankResult(False, "Сколько кладём на вклад?", user_id=user_id)
    try:
        срок = int(days)
    except (TypeError, ValueError):
        срок = 0
    if срок not in DEPOSIT_TERMS:
        return BankResult(False, "Срок вклада может быть только 1, 3 или 7 дней.",
                          user_id=user_id)

    s = await db.get_bank_settings(chat_id) or {}
    минимум = int(s.get("min_deposit") or 0)
    if amount < минимум:
        return BankResult(False, f"Минимальная сумма вклада — {минимум} i¢.", user_id=user_id)

    account = await db.get_bank_account(chat_id, user_id)
    if account["deposit_amount"]:
        return BankResult(False, "У вас уже есть открытый вклад — сначала снимите его.",
                          user_id=user_id)

    # Деньги ДО открытия вклада: наоборот — и сбой на списании оставил бы
    # вклад, за который не заплачено.
    if not await db.try_spend_coins(chat_id, user_id, amount):
        return BankResult(False, f"Недостаточно монет: нужно {amount} i¢.", user_id=user_id)

    ставка = float(s.get(RATE_COLUMN[срок]) or 0)
    await db.open_bank_deposit(chat_id, user_id, amount, срок, ставка)
    return BankResult(True, action="deposit", amount=amount, days=срок, rate=ставка,
                      payout=payout(amount, ставка, срок), user_id=user_id)


async def withdraw(chat_id: int, user_id: int,
                   now: Optional[datetime] = None) -> BankResult:
    now = now or datetime.utcnow()
    account = await db.get_bank_account(chat_id, user_id)
    if not account["deposit_amount"]:
        return BankResult(False, "У вас нет открытого вклада.", user_id=user_id)

    созреет = account["deposit_matures_at"]
    if созреет and now < созреет:
        # Досрочно снять нельзя — это правило банка, а не спрятанная кнопка.
        return BankResult(False, "Вклад ещё заморожен — досрочно снять нельзя.",
                          user_id=user_id)

    сумма = int(account["deposit_amount"])
    ставка = float(account["deposit_rate"])
    дни = int(account["deposit_days"])
    выплата = payout(сумма, ставка, дни)
    await db.add_coins(chat_id, user_id, выплата)
    await db.close_bank_deposit(chat_id, user_id)
    return BankResult(True, action="withdraw", amount=сумма, payout=выплата,
                      days=дни, rate=ставка, user_id=user_id)


async def repay(chat_id: int, user_id: int, raw: Union[int, str, None]) -> BankResult:
    account = await db.get_bank_account(chat_id, user_id)
    долг = int(account["credit_debt"])
    if not долг:
        return BankResult(False, "У вас нет активного кредита.", user_id=user_id)

    if isinstance(raw, str) and raw.strip().casefold() in ("все", "всё", "all", "max"):
        amount = долг
    else:
        amount = _amount(raw)
    if amount is None:
        return BankResult(False, "Сколько погашаем?", user_id=user_id)

    # Обрезаем ДО списания: иначе заплативший «с запасом» подарил бы банку
    # разницу, и понять это по своему балансу было бы нечем.
    платёж = min(amount, долг)
    if not await db.try_spend_coins(chat_id, user_id, платёж):
        wallet = await db.get_wallet(chat_id, user_id)
        return BankResult(
            False, f"Недостаточно монет: у вас {int(wallet['coins'])} i¢, нужно {платёж} i¢.",
            user_id=user_id)

    остаток = await db.reduce_bank_credit_debt(chat_id, user_id, платёж)
    return BankResult(True, action="repay", amount=платёж, debt=int(остаток or 0),
                      closed=not остаток, user_id=user_id)


async def request_credit(chat_id: int, user_id: int, raw: Union[int, str, None],
                         gate_chat_id: Optional[int]) -> BankResult:
    """Проверяет заявку и записывает её. НЕ отправляет ничего.

    Кому и как показать заявку — дело вызывающего: бот шлёт её сам, панель
    через своего бота. А вот проверки обязаны быть одни: разъедься они, и один
    из входов начал бы выдавать кредиты тем, кому в другом отказано.
    """
    amount = _amount(raw)
    if amount is None:
        return BankResult(False, "Сумма кредита должна быть больше нуля.", user_id=user_id)

    account = await db.get_bank_account(chat_id, user_id)
    if account["credit_debt"]:
        return BankResult(
            False, f"У вас уже есть непогашенный кредит: {int(account['credit_debt'])} i¢.",
            user_id=user_id)

    # Взыскание уже увело баланс в минус — новый кредит поверх него утроил бы
    # яму (старый минус плюс новый долг) без единого шанса выбраться.
    wallet = await db.get_wallet(chat_id, user_id)
    if int(wallet.get("coins") or 0) < 0:
        return BankResult(
            False, "За вами уже взыскан долг — баланс отрицательный. "
                   "Новый кредит дадут, когда выйдете в ноль.", user_id=user_id)

    if await db.is_bank_blacklisted(chat_id, user_id):
        return BankResult(False, "Вам закрыт доступ к кредитам банка — вы в чёрном списке.",
                          user_id=user_id)

    if await auto_reject(chat_id):
        return BankResult(False, "Кредиты в этом чате временно не выдаются.", user_id=user_id)

    if not gate_chat_id:
        return BankResult(False, "Кредиты пока некому одобрять — админы не настроили чат заявок.",
                          user_id=user_id)

    ключ = pending_key(chat_id, user_id)
    прежняя = await db.get_data(ключ)
    if прежняя and прежняя.get("data_value"):
        return BankResult(False, "У вас уже есть заявка на кредит, которая ждёт решения.",
                          user_id=user_id)

    s = await db.get_bank_settings(chat_id) or {}
    комиссия = float(s.get("credit_fee_percent") or 0)
    срок = int(s.get("credit_term_days") or 0)
    долг = int(round(amount * (1 + комиссия / 100)))
    await db.set_data(ключ, json.dumps({"amount": amount, "debt": долг, "term_days": срок}))
    return BankResult(True, action="credit", amount=amount, debt=долг,
                      term_days=срок, rate=комиссия, user_id=user_id)


async def cancel_request(chat_id: int, user_id: int) -> None:
    """Убрать заявку. Зовётся, когда показать её админам не удалось: заявка,
    о которой никто не знает, навсегда заблокировала бы человеку кредиты —
    следующая попытка упирается в «у вас уже есть заявка»."""
    await db.delete_data(pending_key(chat_id, user_id))
