"""Правила биржи вне телеграма: купить, продать, дивиденды, курс.

Три места, ради которых эти проверки и написаны.

ВЫКЛЮЧАТЕЛЬ. Биржу в чате можно выключить, и выключенная она заморожена
целиком. В боте эта проверка стоит в каждой из четырёх команд; стоит забыть её
в одном месте панели — и сайт станет обходом админского рубильника, причём
молча: кнопка нажимается, деньги уходят, никто не ругается.

ПОРЯДОК ДЕНЕГ. При покупке монеты списываются ДО учёта долей, при продаже
начисляются ПОСЛЕ. Наоборот — и неудачная половина операции оставляет либо
акции без оплаты, либо оплату без акций.

«ВСЁ». Считается по долям и курсу, а не в браузере: посчитанная снаружи сумма
после округления стабильно оказывается на копейку больше стоимости долей, и
продажа отказывает ровно тогда, когда человек хочет выйти целиком.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib

import pytest

import stock_actions

CHAT, USER = -100, 7


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает биржа.

    Имена полей взяты из настоящих функций db (get_stock_holding,
    sell_stock), а не выдуманы: выдуманное имя дало бы проверку, которая
    подтверждает несуществующее поведение."""

    def __init__(self, coins=100_000, price=10.0, enabled=True):
        self.coins = coins
        self.price = price
        self.enabled = enabled
        self.shares = 0.0
        self.invested = 0
        self.pending = 0.0
        self.total_profit = 0
        self.порядок: list[str] = []      # чем и когда трогали деньги

    async def is_stock_enabled(self, chat_id):
        return self.enabled

    async def get_stock_price(self, chat_id):
        return self.price

    async def get_stock_settings(self, chat_id):
        return {"dividend_percent": 1.5, "enabled": self.enabled}

    async def get_stock_holding(self, chat_id, user_id):
        return {"shares": self.shares, "invested": self.invested,
                "pending_dividends": self.pending, "total_profit": self.total_profit,
                "last_accrual_date": None, "last_dividend_at": None}

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

    async def buy_stock(self, chat_id, user_id, amount, price):
        self.порядок.append("учли доли")
        self.shares += amount / price
        self.invested += amount
        return await self.get_stock_holding(chat_id, user_id)

    async def sell_stock(self, chat_id, user_id, sell_value, price):
        self.порядок.append("списали доли")
        стоимость = self.shares * price
        if sell_value <= 0 or стоимость <= 0 or sell_value > стоимость + 0.01:
            return None
        доля = sell_value / стоимость
        продано = self.shares * доля
        вложено = self.invested * доля
        # GREATEST(...,0), как в настоящем SQL: при продаже «всё» доля выходит
        # чуть больше единицы, и без обрезки доли ушли бы в минус.
        self.shares = max(self.shares - продано, 0.0)
        self.invested = max(int(self.invested - вложено), 0)
        прибыль = sell_value - вложено
        if прибыль > 0:
            self.total_profit += int(прибыль)
        return {"sold_value": sell_value, "profit": прибыль}

    async def claim_dividends(self, chat_id, user_id):
        было, self.pending = self.pending, 0.0
        if было > 0:
            self.total_profit += int(round(было))
        return было

    async def list_stock_price_history(self, chat_id, since, limit=2000):
        return []


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(stock_actions, "db", w)
    return w


# --- выключатель ------------------------------------------------------------

@pytest.mark.parametrize("действие", ["buy", "sell", "dividends"])
@_sync
async def test_выключенная_биржа_не_торгует(monkeypatch, действие):
    """Все три действия, а не одно: пропущенная проверка в любом из них
    открывает обход рубильника целиком."""
    w = _World(enabled=False)
    w.shares, w.invested, w.pending = 100.0, 500, 50.0
    monkeypatch.setattr(stock_actions, "db", w)

    вызвать = getattr(stock_actions, действие)
    итог = await (вызвать(CHAT, USER, 100) if действие != "dividends"
                  else вызвать(CHAT, USER))
    assert not итог.ok
    assert "выключена" in итог.error
    assert w.coins == 100_000, "деньги тронули при выключенной бирже"
    assert w.порядок == [], "выключенная биржа всё равно полезла в кошелёк"


@_sync
async def test_на_выключенную_биржу_можно_смотреть(monkeypatch):
    """Выключение ничего не отнимает: акции на руках, дивиденды накоплены.
    Спрятать экран значило бы соврать, что их нет."""
    w = _World(enabled=False)
    w.shares, w.invested, w.pending = 10.0, 90, 7.0
    monkeypatch.setattr(stock_actions, "db", w)

    s = await stock_actions.state(CHAT, USER)
    assert s["enabled"] is False
    assert s["shares"] == 10.0 and s["invested"] == 90
    assert s["pending_dividends"] == 7.0
    assert s["disabled_text"], "нечем объяснить, почему кнопки не работают"


# --- покупка ----------------------------------------------------------------

@_sync
async def test_покупка_списывает_и_даёт_доли(мир):
    итог = await stock_actions.buy(CHAT, USER, 1000)
    assert итог.ok
    assert мир.coins == 99_000
    assert итог.shares == 100.0          # 1000 монет по курсу 10
    assert мир.invested == 1000


@_sync
async def test_сначала_деньги_потом_доли(мир):
    """Наоборот — и сбой на списании оставит акции неоплаченными."""
    await stock_actions.buy(CHAT, USER, 1000)
    assert мир.порядок == ["списали 1000", "учли доли"]


@_sync
async def test_без_денег_доли_не_появляются(мир):
    мир.coins = 10
    итог = await stock_actions.buy(CHAT, USER, 1000)
    assert not итог.ok and "Недостаточно" in итог.error
    assert мир.shares == 0 and мир.invested == 0
    assert "учли доли" not in мир.порядок


@_sync
async def test_потолок_вложений_держится(мир):
    мир.invested = stock_actions.MAX_INVEST - 100
    итог = await stock_actions.buy(CHAT, USER, 500)
    assert not итог.ok
    assert "100" in итог.error, "не сказано, сколько ещё можно"
    assert мир.coins == 100_000, "деньги списали при отказе"


def test_потолок_и_порог_общие_с_ботом():
    """Два числа разошлись бы молча: в чате «максимум 10 млн», а в кабинете
    уже другой предел на того же человека. И то же с достижением —
    в чате давалось бы на одной прибыли, на сайте на другой."""
    import os

    aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
    if not hasattr(aiogram, "Dispatcher"):
        pytest.skip("установлена заглушка aiogram — запускайте из .venv")
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module

    assert bot_module.STOCK_MAX_INVEST == stock_actions.MAX_INVEST
    assert bot_module.STOCK_CHART_DAYS == stock_actions.CHART_DAYS

    # Сравнения ЗНАЧЕНИЙ мало: скопированное число равно самому себе, и
    # проверка молчит ровно до того дня, когда одно из двух поменяют. Смотрим
    # в исходник — число должно быть написано ОДИН раз.
    исходник = pathlib.Path(__file__).resolve().parent.parent / "bot.py"
    текст = исходник.read_text(encoding="utf-8")
    for имя, откуда in (("STOCK_MAX_INVEST", "stock_actions.MAX_INVEST"),
                        ("STOCK_CHART_DAYS", "stock_actions.CHART_DAYS")):
        строка = next(с for с in текст.split("\n") if с.startswith(f"{имя} ="))
        assert откуда in строка, f"{имя} у бота снова своё: {строка.strip()}"
    assert "stock_actions.INVESTOR_PROFIT" in текст, (
        "у бота снова собственный порог достижения «Инвестор»")
    assert 'total_profit"]) >= 1000' not in текст, "старое число осталось в боте"


# --- продажа ----------------------------------------------------------------

@_sync
async def test_продажа_начисляет_после_списания_долей(мир):
    """Наоборот — и сбой на списании долей оставит оплату без акций."""
    await stock_actions.buy(CHAT, USER, 1000)
    мир.порядок.clear()
    итог = await stock_actions.sell(CHAT, USER, 500)
    assert итог.ok
    assert мир.порядок == ["списали доли", "начислили 500"]


@_sync
async def test_нельзя_продать_больше_чем_есть(мир):
    await stock_actions.buy(CHAT, USER, 1000)
    денег = мир.coins
    итог = await stock_actions.sell(CHAT, USER, 5000)
    assert not итог.ok
    assert мир.coins == денег, "начислили за непроданное"


@_sync
async def test_всё_разворачивается_по_долям_и_курсу(мир):
    """Считать «всё» в браузере нельзя: после округления через JSON сумма
    стабильно оказывается на копейку больше стоимости долей, и выход из
    позиции целиком отказывает ровно тогда, когда он нужен."""
    await stock_actions.buy(CHAT, USER, 1000)
    мир.price = 10.03                       # курс успел сдвинуться
    итог = await stock_actions.sell(CHAT, USER, "всё")
    assert итог.ok, итог.error
    # Сто долей по 10.03 — это 1003, но в float ровно 1002.9999999999999.
    # Простое отбрасывание дробной части отдало бы 1002, то есть «продать
    # всё» каждый раз оставляло бы монету на руках.
    assert итог.amount == 1003
    assert мир.shares < 0.001, "после «всё» остались доли"


@pytest.mark.parametrize("слово", ["все", "всё", "ALL", " max "])
@_sync
async def test_слово_всё_узнаётся_в_разных_видах(мир, слово):
    await stock_actions.buy(CHAT, USER, 1000)
    итог = await stock_actions.sell(CHAT, USER, слово)
    assert итог.ok, f"«{слово}» не узналось"


@_sync
async def test_прибыль_считается_от_вложенного(мир):
    await stock_actions.buy(CHAT, USER, 1000)     # 100 долей по 10
    мир.price = 15.0
    итог = await stock_actions.sell(CHAT, USER, "всё")
    assert итог.ok
    # Вложено 1000, продано на 1500 — прибыль ровно 500.
    assert round(итог.profit) == 500


# --- дивиденды --------------------------------------------------------------

@_sync
async def test_дивиденды_забираются_и_обнуляются(мир):
    мир.pending = 250.0
    итог = await stock_actions.dividends(CHAT, USER)
    assert итог.ok and итог.amount == 250
    assert мир.coins == 100_250
    assert мир.pending == 0


@_sync
async def test_пустые_дивиденды_не_начисляют_ничего(мир):
    итог = await stock_actions.dividends(CHAT, USER)
    assert not итог.ok
    assert мир.coins == 100_000
    assert "не" in итог.error.lower()


@_sync
async def test_ачивка_инвестора_с_общего_порога(мир):
    """Порог тот же, что у бота: два числа разошлись бы, и в чате достижение
    давалось бы на одной сумме, а на сайте на другой."""
    мир.pending = stock_actions.INVESTOR_PROFIT + 1
    итог = await stock_actions.dividends(CHAT, USER)
    assert итог.ok and "investor" in итог.achievements


@_sync
async def test_мелкая_прибыль_ачивку_не_даёт(мир):
    мир.pending = 10.0
    итог = await stock_actions.dividends(CHAT, USER)
    assert итог.ok and итог.achievements == []


# --- гейт нельзя обойти в обход правил ---------------------------------------

def test_панель_ходит_на_биржу_только_через_правила():
    """Выключатель биржи живёт в stock_actions. Позови панель db.buy_stock
    напрямую — и рубильник перестанет что-либо значить на сайте, молча: кнопка
    нажимается, деньги уходят, никто не ругается.

    Поэтому запрет структурный: обработчику вообще нечего звать в db, кроме
    журнала и достижений."""
    файл = (pathlib.Path(__file__).resolve().parent.parent
            / "webpanel" / "member_stock_api.py")
    текст = файл.read_text(encoding="utf-8")
    мимо = [имя for имя in ("db.buy_stock", "db.sell_stock", "db.claim_dividends",
                            "db.get_stock_price", "db.get_stock_holding",
                            "db.is_stock_enabled", "db.add_coins", "db.try_spend_coins")
            if имя in текст]
    assert not мимо, f"панель ходит в базу мимо правил биржи: {мимо}"
    for действие in ("stock_actions.buy", "stock_actions.sell",
                     "stock_actions.dividends", "stock_actions.state"):
        assert действие in текст, f"{действие} не вызывается — экран неполон"


def test_выключатель_стоит_в_каждом_действии():
    """Три действия — три проверки. Забыть её в одном месте достаточно, чтобы
    открыть обход целиком, а поведенческие проверки выше поймают это, только
    если кто-то не удалит заодно и их."""
    файл = pathlib.Path(stock_actions.__file__)
    текст = файл.read_text(encoding="utf-8")
    for действие in ("async def buy(", "async def sell(", "async def dividends("):
        начало = текст.index(действие)
        конец = текст.find("\nasync def ", начало + 1)
        тело = текст[начало:конец if конец > 0 else len(текст)]
        assert "is_stock_enabled" in тело, f"{действие.strip()} не спрашивает выключатель"


# --- состояние экрана -------------------------------------------------------

@_sync
async def test_состояние_отдаёт_всё_что_рисует_экран(мир):
    await stock_actions.buy(CHAT, USER, 1000)
    s = await stock_actions.state(CHAT, USER)
    нужны = {"enabled", "price", "shares", "value", "invested", "max_invest",
             "room", "pending_dividends", "total_profit", "coins",
             "dividend_percent", "chart_days", "history"}
    пропали = нужны - set(s)
    assert not пропали, f"экран не получит: {sorted(пропали)}"
    assert s["value"] == 1000 and s["room"] == stock_actions.MAX_INVEST - 1000
