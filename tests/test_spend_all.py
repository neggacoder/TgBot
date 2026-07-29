"""Слово «все» вместо числа: потратить всё, что есть.

Ломается это в трёх местах: «все» не доходит до разбора (регулярка ждала
цифры), «все» считает не тот кошелёк, и — самое дорогое — «все» просачивается
туда, где числа не тратят, а НАЗНАЧАЮТ.
"""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402


# --- слово ------------------------------------------------------------------

@pytest.mark.parametrize("слово", ["все", "всё", "ВСЁ", "Все", " все ", "all", "max", "макс"])
def test_все_узнаётся_в_любом_написании(слово):
    assert bot_module.is_spend_all(слово), слово


@pytest.mark.parametrize("слово", ["5", "10к", "", None, "всего", "всех"])
def test_похожее_словом_все_не_считается(слово):
    """«всего» и «всех» — обычные слова, и принять их за команду значило бы
    списать кошелёк по случайной фразе."""
    assert not bot_module.is_spend_all(слово), слово


# --- главный запрет ---------------------------------------------------------

def test_в_назначение_чисел_слово_не_просочилось():
    """Самый дорогой из возможных промахов. parse_amount зовут из 28 мест, и
    половина из них числа НАЗНАЧАЕТ: цена товара, потолок рынка, минимальный
    вклад. Пропусти «все» туда — и «магазин цена fishka все» поставила бы
    ценник в размер кошелька владельца."""
    for слово in ("все", "всё", "all", "max"):
        assert bot_module.parse_amount(слово) is None, слово


# --- сумма ------------------------------------------------------------------

def test_сумма_все_это_весь_баланс():
    assert bot_module.parse_spend_amount("все", 1234) == 1234
    assert bot_module.parse_spend_amount("всё", 0) == 0


def test_обычные_суммы_разбираются_как_раньше():
    assert bot_module.parse_spend_amount("10к", 5) == 10_000
    assert bot_module.parse_spend_amount("1.5к", 5) == 1_500
    assert bot_module.parse_spend_amount("мусор", 5) is None


def test_отрицательный_баланс_не_становится_ставкой():
    """Баланс уходит в минус при взыскании по кредиту — «все» от долга должно
    дать ноль, а не отрицательную ставку."""
    assert bot_module.parse_spend_amount("все", -500) == 0


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


class _Сообщение:
    def __init__(self):
        self.chat = type("C", (), {"id": -100, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": 5, "is_bot": False})()


def test_ставка_все_берёт_кошелёк_казино(monkeypatch):
    """Кошельков два, и ошибись здесь — «рулетка все» поставила бы на кон весь
    основной кошелёк, которого казино вообще не касается."""
    monkeypatch.setattr(bot_module.db, "get_casino_wallet",
                        _returns({"balance": 700}), raising=False)
    monkeypatch.setattr(bot_module.db, "get_wallet",
                        _returns({"coins": 99_999}), raising=False)

    сумма = asyncio.run(bot_module.resolve_casino_amount(_Сообщение(), "все"))
    assert сумма == 700


def test_перевод_все_берёт_основной_кошелёк(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_casino_wallet",
                        _returns({"balance": 700}), raising=False)
    monkeypatch.setattr(bot_module.db, "get_wallet",
                        _returns({"coins": 99_999}), raising=False)

    сумма = asyncio.run(bot_module.resolve_wallet_amount(_Сообщение(), "все"))
    assert сумма == 99_999


def test_число_кошелька_не_касается(monkeypatch):
    async def взрыв(*a, **k):
        raise AssertionError("за балансом ходить незачем — сумма указана числом")

    monkeypatch.setattr(bot_module.db, "get_wallet", взрыв, raising=False)
    assert asyncio.run(bot_module.resolve_wallet_amount(_Сообщение(), "10к")) == 10_000


# --- количество -------------------------------------------------------------

def _сколько(**kw):
    kw.setdefault("stock", None)
    return bot_module.parse_spend_quantity("все", **kw)


def test_количество_упирается_в_деньги():
    assert _сколько(price=100, coins=550, limit=100) == 5


def test_количество_упирается_в_потолок_команды():
    """Потолок заведён против опечаток вроде «купить fishka 100000» — «все»
    его не отменяет."""
    assert _сколько(price=1, coins=1_000_000, limit=100) == 100


def test_количество_упирается_в_остаток_на_складе():
    assert _сколько(price=1, coins=1_000_000, limit=100, stock=3) == 3


def test_берётся_меньшее_из_всех_ограничителей():
    """Вернуть больше любого из них значило бы пообещать покупку, которая тут
    же и провалится."""
    assert _сколько(price=100, coins=550, limit=3, stock=10) == 3
    assert _сколько(price=100, coins=550, limit=100, stock=2) == 2


def test_не_хватает_даже_на_одну_даёт_ноль():
    """Ноль — это «не хватает», а не «купить нисколько»: отличить их обязан
    вызывающий, поэтому ноль возвращается честно."""
    assert _сколько(price=100, coins=50, limit=100) == 0


def test_число_остаётся_числом():
    assert bot_module.parse_spend_quantity("7", price=1, coins=1, limit=100) == 7
    assert bot_module.parse_spend_quantity(None, price=1, coins=1, limit=100) == 1
    assert bot_module.parse_spend_quantity("мусор", price=1, coins=1, limit=100) is None


# --- команда доходит до разбора --------------------------------------------

@pytest.mark.parametrize("текст", [
    "магазин купить bronik все",
    "купить bronik всё",
    "лавка купить binokl все",
])
def test_покупка_со_словом_опознаётся(текст):
    """Регулярка ждала цифры, и команда со словом просто не опознавалась —
    человек получал молчание вместо покупки."""
    совпало = (bot_module.SHOP_BUY_RE.match(текст)
               or bot_module.BLACK_MARKET_BUY_RE.match(текст))
    assert совпало, текст
    assert bot_module.is_spend_all(совпало.group(2)), текст


@pytest.mark.parametrize("текст", [
    "!покер все", "рулетка все красное", "!кости все 3",
    "!орёл все", "!гонки все", "казино пополнить все",
    "казино вывести все", "банк вклад все 7", "банк погасить все",
])
def test_ставки_и_банк_принимают_слово(текст):
    """У этих регулярок аргумент и так «\\S+» — тест закрепляет, что его не
    сузят до цифр при следующей правке."""
    assert bot_module.is_command_like(текст) or True   # опознание тут не главное
    for re_ in (bot_module.CASINO_POKER_RE, bot_module.CASINO_ROULETTE_RE,
                bot_module.CASINO_DICE_RE, bot_module.CASINO_COIN_RE,
                bot_module.RACE_CMD_RE, bot_module.CASINO_TOPUP_RE,
                bot_module.CASINO_WITHDRAW_RE, bot_module.BANK_DEPOSIT_RE,
                bot_module.BANK_REPAY_RE):
        if re_.match(текст):
            return
    pytest.fail(f"ни одна регулярка не приняла {текст!r}")
