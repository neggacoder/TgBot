"""Рынок между участниками вне телеграма.

Рынок — первое место в боте, где двое договорившихся могут гонять друг другу
произвольные суммы: цену назначает сам продавец. Держат это два ограничителя,
и оба обязаны работать одинаково из чата и с сайта: комиссия в казну и потолок
цены.

Три места, где ошибиться легко и дорого.

ДЕНЬГИ ОДНОЙ ТРАНЗАКЦИЕЙ. Покупка двигает четыре вещи разом. Читать баланс
заранее и списывать отдельно нельзя: две покупки подряд обе прошли бы проверку
и увели бы кошелёк в минус.

ЗАЯВКА — НЕ ТОВАР. До одобрения администрацией товара на витрине нет.
Исключение — режим автопринятия, и это настройка чата, а не решение экрана.

СВОЙ СНЯТЫЙ ТОВАР ВОЗВРАЩАЕТСЯ. Строка по нему остаётся ради названий в чужих
инвентарях, поэтому обычная проверка «ключ занят» отбивала бы владельца от его
собственного товара.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib

import pytest

import market
import market_actions as ma

ЧАТ, ПРОДАВЕЦ, ПОКУПАТЕЛЬ = -100, 7, 8


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    def __init__(self, coins=100_000, mode=market.MODE_MANUAL):
        self.coins = {ПОКУПАТЕЛЬ: coins, ПРОДАВЕЦ: 0}
        self.режим = mode
        self.товары: dict[str, dict] = {}
        self.следующий = 1
        self.сделки: list[tuple] = []
        self.снято: list[str] = []

    async def get_market_settings(self, chat_id):
        return {"mode": self.режим, "commission_percent": 10,
                "max_price": 50_000, "max_goods": 2}

    async def get_market_good(self, chat_id, key):
        т = self.товары.get(key)
        return dict(т) if т else None

    async def list_market_goods(self, chat_id, status="approved"):
        return [dict(т) for т in self.товары.values() if т["status"] == status]

    async def list_market_goods_of(self, chat_id, seller_id):
        return [dict(т) for т in self.товары.values() if т["seller_id"] == seller_id]

    async def count_market_goods_of(self, chat_id, seller_id):
        return sum(1 for т in self.товары.values() if т["seller_id"] == seller_id)

    async def add_market_good(self, chat_id, seller_id, key, name, price, status):
        if key in self.товары:
            return None
        good_id = self.следующий
        self.следующий += 1
        self.товары[key] = {"id": good_id, "item_key": key, "name": name,
                            "price": price, "seller_id": seller_id,
                            "status": status, "emoji": "🧺", "sold_count": 0}
        return good_id

    async def relist_market_good(self, chat_id, good_id, price, status):
        for т in self.товары.values():
            if т["id"] == good_id:
                т["price"], т["status"] = price, status

    async def remove_market_good(self, chat_id, key, seller_id):
        т = self.товары.get(key)
        if not т or т["seller_id"] != seller_id:
            return None
        self.снято.append(key)
        if т["sold_count"]:
            т["status"] = "withdrawn"
            return "withdrawn"
        del self.товары[key]
        return "deleted"

    async def market_purchase(self, chat_id, buyer, seller, good_id, key,
                              qty, total, to_seller, fee):
        # Одна операция: не хватило — не меняется вообще ничего.
        if self.coins.get(buyer, 0) < total:
            return False
        self.coins[buyer] -= total
        self.coins[seller] = self.coins.get(seller, 0) + to_seller
        self.сделки.append((key, qty, total, to_seller, fee))
        self.товары[key]["sold_count"] += qty
        return True

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins.get(user_id, 0)}


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(ma, "db", w)
    return w


async def _завести(мир, key="ogurcy", price=500, status="approved"):
    await мир.add_market_good(ЧАТ, ПРОДАВЕЦ, key, "Огурцы", price, status)


# --- деньги ------------------------------------------------------------------

@_sync
async def test_покупка_делит_деньги_с_комиссией(мир):
    """Комиссия округляется ВНИЗ, остаток продавцу: сумма сходится копейка в
    копейку и ниоткуда не берётся лишняя монета."""
    await _завести(мир, price=505)
    итог = await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "ogurcy", 3)
    assert итог.ok
    всего = 505 * 3
    assert итог.total == всего
    assert итог.fee + итог.to_seller == всего, "деньги не сошлись"
    assert итог.fee == int(всего * 10 / 100)
    assert мир.coins[ПОКУПАТЕЛЬ] == 100_000 - всего
    assert мир.coins[ПРОДАВЕЦ] == итог.to_seller


@_sync
async def test_не_хватило_денег_ничего_не_двинулось(мир):
    await _завести(мир, price=50_000)
    мир.coins[ПОКУПАТЕЛЬ] = 100
    итог = await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "ogurcy", 1)
    assert not итог.ok and "не хватает" in итог.error.lower()
    assert мир.coins[ПОКУПАТЕЛЬ] == 100 and мир.сделки == []


@_sync
async def test_свой_товар_не_купить(мир):
    """Деньги продавцу даём намеренно: без них покупка не прошла бы и так —
    по нехватке средств, — и проверка молчала бы о снятом правиле."""
    мир.coins[ПРОДАВЕЦ] = 100_000
    await _завести(мир)
    итог = await ma.buy(ЧАТ, ПРОДАВЕЦ, "ogurcy", 1)
    assert not итог.ok and "незачем" in итог.error
    assert мир.сделки == []


@_sync
async def test_неодобренный_товар_не_купить(мир):
    await _завести(мир, status="pending")
    итог = await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "ogurcy", 1)
    assert not итог.ok and мир.сделки == []


@pytest.mark.parametrize("сколько", [0, -1, market.BUY_MAX_QTY + 1, "много"])
@_sync
async def test_дурное_количество_не_проходит(мир, сколько):
    await _завести(мир)
    итог = await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "ogurcy", сколько)
    assert not итог.ok and мир.сделки == []


# --- заявка ------------------------------------------------------------------

@_sync
async def test_заявка_ждёт_одобрения(мир):
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд", 900)
    assert итог.ok and итог.pending
    assert мир.товары["med"]["status"] == "pending", "товар попал на витрину без одобрения"


@_sync
async def test_автопринятие_выводит_сразу(мир):
    мир.режим = market.MODE_AUTO_ACCEPT
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд", 900)
    assert итог.ok and not итог.pending
    assert мир.товары["med"]["status"] == "approved"


@_sync
async def test_закрытый_приём_не_принимает(мир):
    мир.режим = market.MODE_AUTO_REJECT
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд", 900)
    assert not итог.ok and мир.товары == {}


@_sync
async def test_потолок_цены_держится(мир):
    """Один из двух ограничителей, на которых стоит вся экономика рынка."""
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд", 500_000)
    assert not итог.ok and "отолок" in итог.error
    assert мир.товары == {}


@pytest.mark.parametrize("ключ", ["ab", "Огурцы", "og urcy", "o" * 40, ""])
@_sync
async def test_дурной_ключ_не_проходит(мир, ключ):
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, ключ, "Мёд", 900)
    assert not итог.ok and мир.товары == {}


@_sync
async def test_в_отказе_нет_разметки_чата(мир):
    """Тексты в market.py написаны для чата и несут теги. На сайте они
    показываются как есть — тег в лицо человеку."""
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "ab", "Мёд", 900)
    assert "<" not in итог.error and ">" not in итог.error


@_sync
async def test_чужой_ключ_занят(мир):
    await _завести(мир, key="med")
    итог = await ma.apply(ЧАТ, ПОКУПАТЕЛЬ, "med", "Свой мёд", 900)
    assert not итог.ok and "занят" in итог.error


@_sync
async def test_потолок_числа_товаров(мир):
    await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд", 900)
    await ma.apply(ЧАТ, ПРОДАВЕЦ, "syr", "Сыр", 900)
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "hleb", "Хлеб", 900)
    assert not итог.ok and "больше" in итог.error


@_sync
async def test_длинное_название_не_проходит(мир):
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "М" * (market.NAME_MAX + 1), 900)
    assert not итог.ok and мир.товары == {}


# --- снятие и возврат --------------------------------------------------------

@_sync
async def test_непроданный_товар_снимается_целиком(мир):
    await _завести(мир, key="med")
    итог = await ma.withdraw(ЧАТ, ПРОДАВЕЦ, "med")
    assert итог.ok and "med" not in мир.товары, "ключ не освободился"


@_sync
async def test_проданный_товар_остаётся_строкой(мир):
    """Строка нужна ради названий в инвентарях покупателей — удалить её
    значило бы оставить у людей безымянные ключи."""
    await _завести(мир, key="med")
    await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "med", 1)
    итог = await ma.withdraw(ЧАТ, ПРОДАВЕЦ, "med")
    assert итог.ok
    assert мир.товары["med"]["status"] == "withdrawn"


@_sync
async def test_свой_снятый_товар_возвращается(мир):
    """Обычная проверка занятости ключа отбивала бы владельца от его же
    собственного товара."""
    await _завести(мир, key="med")
    await ma.buy(ЧАТ, ПОКУПАТЕЛЬ, "med", 1)
    await ma.withdraw(ЧАТ, ПРОДАВЕЦ, "med")
    итог = await ma.apply(ЧАТ, ПРОДАВЕЦ, "med", "Мёд снова", 1200)
    assert итог.ok and итог.action == "relist"
    assert мир.товары["med"]["price"] == 1200


@_sync
async def test_чужой_товар_не_снять(мир):
    await _завести(мир, key="med")
    итог = await ma.withdraw(ЧАТ, ПОКУПАТЕЛЬ, "med")
    assert not итог.ok and "med" in мир.товары


# --- состояние экрана --------------------------------------------------------

@_sync
async def test_состояние_отдаёт_всё_что_рисует_экран(мир):
    await _завести(мир)
    s = await ma.state(ЧАТ, ПОКУПАТЕЛЬ)
    нужны = {"coins", "commission_percent", "max_price", "max_goods", "max_qty",
             "name_max", "mode", "mode_label", "accepts_requests", "auto_accept",
             "goods", "mine"}
    assert not (нужны - set(s))
    assert s["goods"][0]["mine"] is False


# --- одни правила на чат и сайт ----------------------------------------------

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


def test_панель_идёт_через_общие_правила():
    файл = (КОРЕНЬ / "webpanel" / "member_market_api.py").read_text(encoding="utf-8")
    for имя in ("market_actions.buy", "market_actions.apply",
                "market_actions.withdraw", "market_actions.state"):
        assert имя in файл
    for запрет in ("db.market_purchase", "db.add_market_good", "db.remove_market_good"):
        assert запрет not in файл, f"панель торгует мимо правил: {запрет}"


def test_покупка_с_сайта_такая_же_громкая():
    """В чате сделку видят все, продавцу приходит личка. Промолчи сайт — и
    рынок с него стал бы тихим: продавец узнавал бы о продаже только по
    изменившемуся балансу."""
    файл = (КОРЕНЬ / "webpanel" / "member_market_api.py").read_text(encoding="utf-8")
    кусок = файл[файл.index("async def _объявить_покупку"):файл.index("async def _объявить_заявку")]
    assert кусок.count("send_message") == 2, "сайт объявляет покупку не всем и не продавцу"
    вызов = файл[файл.index("async def api_member_market_action"):]
    assert "_объявить_покупку(" in вызов


def test_заявка_с_сайта_получает_инлайн_кнопки():
    """Именно кабинет раньше отправлял голый текст с командами решения."""
    файл = (КОРЕНЬ / "webpanel" / "member_market_api.py").read_text(encoding="utf-8")
    кусок = файл[файл.index("async def _объявить_заявку"):файл.index("async def api_member_market_action")]
    assert "InlineKeyboardMarkup" in кусок
    assert "market.decision_callback_data(True" in кусок
    assert "market.decision_callback_data(False" in кусок
    assert "reply_markup=keyboard" in кусок
    assert "рынок принять" not in кусок and "рынок отклонить" not in кусок


def test_магазин_берёт_количество_из_поля_на_карточке():
    файл = (КОРЕНЬ / "webpanel" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'class="good-qty" data-shop-qty' in файл
    assert 'querySelector("[data-shop-qty]")' in файл
    shop_click = файл[файл.index("async function onShopClick"):файл.index("// --- питомцы")]
    assert 'prompt("Сколько купить?' not in shop_click
