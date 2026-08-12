"""Рынок между участниками: правила заявок, ключей и денег.

Здесь только ПРАВИЛА, без БД и Telegram — как fishing.py и robbery.py рядом.

Суть механики: участник заводит СВОЙ товар («огурцы»), администрация его
подтверждает, и дальше этот товар в чате продаёт только он. Ключ товара
уникален на чат — это и есть монополия.

⚠️ Главная опасность рынка — не баги, а экономика. Это первое место в боте,
где двое договорившихся могут гонять друг другу произвольные суммы: цену
назначает сам продавец. Поэтому здесь два ограничителя, и убирать их нельзя:

  * КОМИССИЯ — процент с каждой сделки уходит в казну чата. Перекачка
    становится убыточной, а монеты частично изымаются из оборота.
  * ПОТОЛОК ЦЕНЫ — товар дороже него не заявить.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- значения по умолчанию (правит админ командой «рынок ...») --------------
DEFAULT_COMMISSION = 10.0      # % с продажи в казну чата
DEFAULT_MAX_PRICE = 50_000     # потолок цены товара
DEFAULT_MAX_GOODS = 3          # сколько товаров держит один человек
DEFAULT_MODE = "manual"

# Режимы разбора заявок. auto_reject нужен, чтобы закрыть рынок, не выключая
# уже одобренные товары: заявки отбиваются, торговля продолжается.
MODE_MANUAL = "manual"
MODE_AUTO_ACCEPT = "auto_accept"
MODE_AUTO_REJECT = "auto_reject"
MODES = (MODE_MANUAL, MODE_AUTO_ACCEPT, MODE_AUTO_REJECT)

MODE_LABEL = {
    MODE_MANUAL: "вручную — заявки ждут решения администрации",
    MODE_AUTO_ACCEPT: "автопринятие — заявки одобряются сразу",
    MODE_AUTO_REJECT: "автоотклонение — новые заявки не принимаются",
}

KEY_RE = re.compile(r"^[a-z0-9_]{3,32}$")
NAME_MAX = 48
DESC_MAX = 200
BUY_MAX_QTY = 100              # потолок на одну команду, как SHOP_BUY_MAX_QTY


def decision_callback_data(approve: bool, chat_id: int, good_id: int) -> str:
    """Короткий callback для решения заявки рынка.

    Его строят и бот, и кабинет участника: заявка может быть подана из
    любого из этих мест, но обработчик кнопки в боте один.
    """
    return f"{'mktok' if approve else 'mktno'}:{chat_id}:{good_id}"


@dataclass(frozen=True)
class Settings:
    mode: str = DEFAULT_MODE
    commission_percent: float = DEFAULT_COMMISSION
    max_price: int = DEFAULT_MAX_PRICE
    max_goods: int = DEFAULT_MAX_GOODS


def validate_key(key: str) -> str:
    """Пустая строка — ключ годится, иначе текст ошибки для человека.

    Латиница и цифры, потому что ключ набирают руками в «рынок купить {ключ}»,
    а раскладку в этот момент никто не переключает.
    """
    if not KEY_RE.match(key):
        return ("Ключ товара — латиница, цифры и подчёркивание, от 3 до 32 "
                "символов. Например: <code>ogurcy</code>")
    return ""


def validate_price(price: int, settings: Settings) -> str:
    if price <= 0:
        return "Цена должна быть больше нуля."
    if price > settings.max_price:
        return (f"Потолок цены в этом чате — {settings.max_price} i¢. "
                f"Поднять его может администрация: «рынок потолок {{число}}».")
    return ""


def split_payment(price: int, quantity: int, commission_percent: float) -> tuple[int, int, int]:
    """(всего с покупателя, продавцу, в казну чата).

    Комиссию округляем ВНИЗ, а остаток отдаём продавцу: так сумма всегда
    сходится копейка в копейку и ниоткуда не берётся лишняя монета.
    """
    total = price * quantity
    fee = int(total * commission_percent / 100)
    return total, total - fee, fee
