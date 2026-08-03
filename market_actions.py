"""Рынок между участниками: витрина, покупка, свои товары, заявка.

Четырнадцатый модуль того же устройства. Правила разбора (ключ, цена, дележ
денег) уже лежат отдельно — в market.py; здесь то, что ходит в базу.

Три места, где ошибиться легко и дорого.

ДЕНЬГИ ОДНОЙ ТРАНЗАКЦИЕЙ. Покупка двигает четыре вещи разом: списывает у
покупателя, начисляет продавцу, кладёт комиссию в казну и выдаёт товар. Всё
это делает один db.market_purchase с проверкой баланса внутри самого UPDATE.
Читать баланс заранее и списывать отдельно нельзя: две покупки подряд обе
прошли бы проверку и увели бы кошелёк в минус.

ЗАЯВКА — НЕ ТОВАР. Заявку одобряет администрация, и до одобрения товар на
витрине не появляется. Исключение — режим автопринятия, и это настройка чата,
а не решение экрана.

СВОЙ СНЯТЫЙ ТОВАР ВОЗВРАЩАЕТСЯ ТЕМ ЖЕ ПУТЁМ. Строка по нему остаётся в базе
ради названий в чужих инвентарях, поэтому обычная проверка «ключ занят»
отбивала бы владельца от его собственного товара.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Union

import db
import market

logger = logging.getLogger(__name__)


@dataclass
class MarketResult:
    ok: bool
    error: str = ""
    action: str = ""
    key: str = ""
    name: str = ""
    quantity: int = 0
    total: int = 0
    to_seller: int = 0
    fee: int = 0
    seller_id: int = 0
    good_id: int = 0
    pending: bool = False       # заявка ждёт решения администрации
    user_id: int = 0


def settings_of(row: Optional[dict]) -> market.Settings:
    """Настройки рынка чата с подстановкой значений по умолчанию."""
    row = row or {}
    return market.Settings(
        mode=row.get("mode") or market.DEFAULT_MODE,
        commission_percent=float(row.get("commission_percent")
                                 if row.get("commission_percent") is not None
                                 else market.DEFAULT_COMMISSION),
        max_price=int(row.get("max_price") or market.DEFAULT_MAX_PRICE),
        max_goods=int(row.get("max_goods") or market.DEFAULT_MAX_GOODS),
    )


def _qty(raw: Union[int, str, None]) -> Optional[int]:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= market.BUY_MAX_QTY else None


async def state(chat_id: int, user_id: int) -> dict:
    s = settings_of(await db.get_market_settings(chat_id))
    витрина = await db.list_market_goods(chat_id)
    свои = await db.list_market_goods_of(chat_id, user_id)
    wallet = await db.get_wallet(chat_id, user_id)
    return {
        "coins": int(wallet["coins"]),
        "commission_percent": s.commission_percent,
        "max_price": s.max_price,
        "max_goods": s.max_goods,
        "max_qty": market.BUY_MAX_QTY,
        "name_max": market.NAME_MAX,
        "mode": s.mode,
        "mode_label": market.MODE_LABEL.get(s.mode, s.mode),
        # Заявки принимаются или нет — экран обязан сказать это до нажатия.
        "accepts_requests": s.mode != market.MODE_AUTO_REJECT,
        "auto_accept": s.mode == market.MODE_AUTO_ACCEPT,
        "goods": [
            {"key": g["item_key"], "name": g["name"], "price": int(g["price"]),
             "emoji": g.get("emoji") or "🧺", "seller_id": int(g["seller_id"]),
             "mine": int(g["seller_id"]) == user_id,
             "sold": int(g.get("sold_count") or 0)}
            for g in витрина
        ],
        "mine": [
            {"key": g["item_key"], "name": g["name"], "price": int(g["price"]),
             "status": g["status"], "sold": int(g.get("sold_count") or 0)}
            for g in свои
        ],
    }


async def buy(chat_id: int, user_id: int, key: str,
              quantity: Union[int, str, None]) -> MarketResult:
    ключ = (key or "").strip().casefold()
    n = _qty(quantity if quantity is not None else 1)
    if n is None:
        return MarketResult(False, f"Количество — от 1 до {market.BUY_MAX_QTY} за раз.",
                            user_id=user_id)

    товар = await db.get_market_good(chat_id, ключ)
    if товар is None or товар["status"] != "approved":
        return MarketResult(False, "На рынке нет такого товара.", user_id=user_id)
    продавец = int(товар["seller_id"])
    if продавец == user_id:
        return MarketResult(False, "Свой собственный товар покупать незачем.", user_id=user_id)

    s = settings_of(await db.get_market_settings(chat_id))
    всего, продавцу, комиссия = market.split_payment(
        int(товар["price"]), n, s.commission_percent)

    # Деньги, казна, инвентарь и счётчик продаж — ОДНОЙ транзакцией, с
    # проверкой баланса внутри самого UPDATE. Раздельно нельзя: две покупки
    # подряд обе прошли бы проверку и увели кошелёк в минус.
    if not await db.market_purchase(chat_id, user_id, продавец, int(товар["id"]),
                                    ключ, n, всего, продавцу, комиссия):
        wallet = await db.get_wallet(chat_id, user_id)
        return MarketResult(False, f"Не хватает монет: нужно {всего} i¢, "
                                   f"у вас {int(wallet.get('coins') or 0)}.", user_id=user_id)

    return MarketResult(True, action="buy", key=ключ, name=товар["name"], quantity=n,
                        total=всего, to_seller=продавцу, fee=комиссия,
                        seller_id=продавец, user_id=user_id)


async def apply(chat_id: int, user_id: int, key: str, name: str,
                price: Union[int, str, None]) -> MarketResult:
    """Заявка на свой товар. Одобряет её администрация — кроме режима
    автопринятия, и это настройка чата, а не решение экрана."""
    s = settings_of(await db.get_market_settings(chat_id))
    if s.mode == market.MODE_AUTO_REJECT:
        return MarketResult(False, "Приём заявок в этом чате сейчас закрыт.", user_id=user_id)

    ключ = (key or "").strip().casefold()
    ошибка = market.validate_key(ключ)
    if ошибка:
        return MarketResult(False, _без_разметки(ошибка), user_id=user_id)

    название = (name or "").strip()
    if not название:
        return MarketResult(False, "Не сказано, как называется товар.", user_id=user_id)
    if len(название) > market.NAME_MAX:
        return MarketResult(False, f"Название длиннее {market.NAME_MAX} символов.",
                            user_id=user_id)

    try:
        цена = int(price)
    except (TypeError, ValueError):
        return MarketResult(False, "Не понял цену.", user_id=user_id)
    ошибка = market.validate_price(цена, s)
    if ошибка:
        return MarketResult(False, _без_разметки(ошибка), user_id=user_id)

    # Свой снятый товар возвращается той же дорогой: строка по нему осталась
    # ради названий в чужих инвентарях, и обычная проверка занятости ключа
    # отбила бы владельца от его собственного товара.
    прежний = await db.get_market_good(chat_id, ключ)
    возврат = (прежний is not None and int(прежний["seller_id"]) == user_id
               and прежний["status"] == "withdrawn")
    if прежний is not None and not возврат:
        return MarketResult(False, "Этот ключ в чате уже занят.", user_id=user_id)

    авто = s.mode == market.MODE_AUTO_ACCEPT
    if возврат:
        await db.relist_market_good(chat_id, int(прежний["id"]), цена,
                                    "approved" if авто else "pending")
        return MarketResult(True, action="relist", key=ключ, name=название,
                            good_id=int(прежний["id"]), pending=not авто,
                            user_id=user_id)

    мои = await db.count_market_goods_of(chat_id, user_id)
    if мои >= s.max_goods:
        return MarketResult(False, f"У вас уже {мои} товаров — больше {s.max_goods} "
                                   f"в этом чате нельзя.", user_id=user_id)

    good_id = await db.add_market_good(chat_id, user_id, ключ, название, цена,
                                       status="approved" if авто else "pending")
    if good_id is None:
        return MarketResult(False, "Этот товар в чате уже кто-то продаёт — ключ занят.",
                            user_id=user_id)
    return MarketResult(True, action="apply", key=ключ, name=название,
                        good_id=int(good_id), pending=not авто, user_id=user_id)


async def withdraw(chat_id: int, user_id: int, key: str) -> MarketResult:
    """Снять свой товар с витрины.

    Исходов два, и различать их надо: непроданный товар удаляется целиком и
    освобождает ключ, а проданный уходит с витрины, но строка остаётся — по
    ней в инвентарях покупателей резолвятся название и эмодзи. Решает это
    db.remove_market_good, здесь только передаём разницу наверх.
    """
    ключ = (key or "").strip().casefold()
    товар = await db.get_market_good(chat_id, ключ)
    имя = (товар or {}).get("name") or ключ
    исход = await db.remove_market_good(chat_id, ключ, user_id)
    if исход is None:
        return MarketResult(False, "У вас нет такого товара на рынке.", user_id=user_id)
    return MarketResult(True, action="withdraw", key=ключ, name=имя,
                        # ключ освободился только если строку удалили целиком
                        pending=(исход != "deleted"), user_id=user_id)


def _без_разметки(текст: str) -> str:
    """Тексты в market.py написаны для чата и несут теги <code>. На сайте они
    показываются как есть, поэтому теги убираем здесь, а не правим общий
    модуль: чату они нужны."""
    import re
    return re.sub(r"<[^>]+>", "", текст)
