"""Биржа: купить, продать, забрать дивиденды, показать курс. Ничего не отправляет.

Восьмой модуль того же устройства, что farm_actions и остальные: правила живут
здесь, а бот и веб-панель только зовут их и по-своему показывают ответ.

Три места, где ошибиться легко и дорого:

ВЫКЛЮЧАТЕЛЬ. Биржу в чате можно выключить, и выключенная она заморожена
целиком: курс замирает, команды не работают, но акции и дивиденды остаются на
руках. Проверка стоит ЗДЕСЬ, в каждом действии, а не у вызывающего — иначе
достаточно забыть её в одном месте панели, и сайт станет обходом админского
рубильника. В боте эта проверка написана четыре раза (_stock_off), и именно
поэтому её нельзя было повторять пятый.

ПОРЯДОК ДЕНЕГ. При покупке монеты списываются ДО учёта долей, при продаже
начисляются ПОСЛЕ. Наоборот — и неудачная половина операции оставляет либо
акции без оплаты, либо оплату без акций. Списание атомарное (try_spend_coins):
проверка и вычитание одним запросом, иначе две покупки подряд обе увидят
«денег хватает».

«ВСЁ». Разворачивается тоже здесь: сколько это в монетах, знают только доли и
курс, а сумма, посчитанная в браузере, после округления через JSON стабильно
промахивается мимо предела продажи на копейку.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Union

import db

logger = logging.getLogger(__name__)

MAX_INVEST = 10_000_000_000    # максимум вложений на человека
CHART_DAYS = 30                # какой хвост истории показываем
INVESTOR_PROFIT = 100000         # с какой прибыли даётся ачивка «Инвестор»

ВЫКЛЮЧЕНА = ("Биржа в этом чате выключена. Купленные акции и накопленные "
             "дивиденды никуда не делись — они ждут, пока администрация "
             "включит биржу обратно.")


@dataclass
class StockResult:
    ok: bool
    error: str = ""
    action: str = ""
    amount: int = 0            # сколько монет вложено или получено
    shares: float = 0.0        # сколько долей куплено или продано
    price: float = 0.0         # курс, по которому прошла сделка
    profit: float = 0.0        # прибыль сделки (только продажа)
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0


def _amount(raw: Union[int, str, None]) -> Optional[int]:
    """Сумма из тела запроса. «Всё» сюда не попадает — его разворачивают
    отдельно, там, где известны доли и курс."""
    if raw is None:
        return None
    try:
        значение = int(float(raw))
    except (TypeError, ValueError):
        return None
    return значение if значение > 0 else None


def is_all(raw: Union[int, str, None]) -> bool:
    return isinstance(raw, str) and raw.strip().casefold() in ("все", "всё", "all", "max")


async def _achievements(chat_id: int, user_id: int) -> list[str]:
    """«Инвестор» — за суммарную прибыль. Порог общий с ботом: там он тоже
    берётся отсюда, чтобы два числа не разошлись."""
    holding = await db.get_stock_holding(chat_id, user_id)
    if int(holding["total_profit"]) >= INVESTOR_PROFIT:
        return ["investor"]
    return []


async def state(chat_id: int, user_id: int) -> dict:
    """Всё, что нужно экрану: курс, свои акции, история и настройки.

    Отдаётся и когда биржа выключена — смотреть на замерший курс и на свои
    акции никто не запрещал, запрещено только торговать.
    """
    enabled = await db.is_stock_enabled(chat_id)
    price = float(await db.get_stock_price(chat_id))
    holding = await db.get_stock_holding(chat_id, user_id)
    settings = await db.get_stock_settings(chat_id) or {}
    история = await db.list_stock_price_history(
        chat_id, datetime.utcnow() - timedelta(days=CHART_DAYS))

    shares = float(holding["shares"])
    invested = int(holding["invested"])
    wallet = await db.get_wallet(chat_id, user_id)
    return {
        "now": datetime.utcnow().isoformat(),
        "enabled": bool(enabled),
        "disabled_text": ВЫКЛЮЧЕНА,
        "price": round(price, 2),
        "shares": round(shares, 4),
        "value": int(shares * price),
        "invested": invested,
        "max_invest": MAX_INVEST,
        "room": max(MAX_INVEST - invested, 0),
        "pending_dividends": round(float(holding["pending_dividends"]), 2),
        "total_profit": int(holding["total_profit"]),
        "coins": int(wallet["coins"]),
        "dividend_percent": float(settings.get("dividend_percent") or 0),
        "chart_days": CHART_DAYS,
        # Точки отдаём как есть — рисует их браузер, и подписи ему нужны свои.
        "history": [
            {"price": round(float(т["price"]), 2),
             "at": т["created_at"].isoformat() if т["created_at"] else None}
            for т in история
        ],
    }


async def buy(chat_id: int, user_id: int, raw: Union[int, str, None]) -> StockResult:
    if not await db.is_stock_enabled(chat_id):
        return StockResult(False, ВЫКЛЮЧЕНА, user_id=user_id)
    amount = _amount(raw)
    if amount is None:
        return StockResult(False, "Сколько вкладываем?", user_id=user_id)

    holding = await db.get_stock_holding(chat_id, user_id)
    вложено = int(holding["invested"])
    if вложено + amount > MAX_INVEST:
        осталось = max(MAX_INVEST - вложено, 0)
        return StockResult(
            False, f"Максимум вложений на человека — {MAX_INVEST} i¢. "
                   f"Сейчас можно вложить ещё {осталось} i¢.", user_id=user_id)

    # Сначала деньги, потом доли: наоборот — и сбой на списании оставил бы
    # акции неоплаченными.
    if not await db.try_spend_coins(chat_id, user_id, amount):
        return StockResult(False, f"Недостаточно монет: нужно {amount} i¢.", user_id=user_id)

    price = float(await db.get_stock_price(chat_id))
    await db.buy_stock(chat_id, user_id, amount, price)
    return StockResult(True, action="buy", amount=amount, price=round(price, 2),
                       shares=round(amount / price, 4), user_id=user_id)


async def sell(chat_id: int, user_id: int, raw: Union[int, str, None]) -> StockResult:
    if not await db.is_stock_enabled(chat_id):
        return StockResult(False, ВЫКЛЮЧЕНА, user_id=user_id)

    price = float(await db.get_stock_price(chat_id))
    holding = await db.get_stock_holding(chat_id, user_id)
    стоимость = float(holding["shares"]) * price

    if is_all(raw):
        # Округляем до копеек, а потом до целого. Просто int() отрезал бы
        # монету: сто долей по 10.03 дают в float 1002.9999999999999, и
        # «продать всё» стабильно оставляло бы на руках копейку. Лишние
        # полкопейки после округления берёт на себя допуск в db.sell_stock
        # (он принимает сумму на 0.01 больше стоимости долей).
        amount = int(round(стоимость, 2))
    else:
        amount = _amount(raw)
    if amount is None or amount <= 0:
        return StockResult(False, "Сколько продаём?", user_id=user_id)

    итог = await db.sell_stock(chat_id, user_id, amount, price)
    if итог is None:
        return StockResult(
            False, f"У вас акций максимум на {стоимость:.0f} i¢ — столько продать нельзя.",
            user_id=user_id)

    # Доли списаны — только теперь деньги на руки.
    await db.add_coins(chat_id, user_id, amount)
    return StockResult(True, action="sell", amount=amount, price=round(price, 2),
                       profit=round(float(итог["profit"]), 2),
                       achievements=await _achievements(chat_id, user_id),
                       user_id=user_id)


async def dividends(chat_id: int, user_id: int) -> StockResult:
    if not await db.is_stock_enabled(chat_id):
        return StockResult(False, ВЫКЛЮЧЕНА, user_id=user_id)
    pending = await db.claim_dividends(chat_id, user_id)
    if pending <= 0:
        return StockResult(
            False, "Дивидендов пока нет — они копятся раз в сутки от вложенной суммы.",
            user_id=user_id)
    сумма = int(round(pending))
    await db.add_coins(chat_id, user_id, сумма)
    return StockResult(True, action="dividends", amount=сумма,
                       achievements=await _achievements(chat_id, user_id),
                       user_id=user_id)
