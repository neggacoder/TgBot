"""Рынок между участниками.

Механика простая на вид и опасная по сути: цену назначает сам продавец, а
покупатель платит другому ЧЕЛОВЕКУ. Это первое место в боте, где двое
договорившихся могут гонять друг другу любые суммы, поэтому здесь проверяются
не столько команды, сколько два ограничителя — комиссия и потолок цены — и
арифметика, которая не должна создавать монеты из воздуха.

Отдельно проверяется защита ключей. Магазин досеивается функцией, которая
молча пропускает существующие ключи (db.seed_extra_shop_items), так что товар
с ключом «talisman» навсегда лишил бы чат настоящего Талисмана удачи — без
единой ошибки в логах.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

import market
import robbery
import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
BUYER = 555
SELLER = 777


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


def _settings(**kw):
    base = {"mode": market.DEFAULT_MODE, "commission_percent": market.DEFAULT_COMMISSION,
            "max_price": market.DEFAULT_MAX_PRICE, "max_goods": market.DEFAULT_MAX_GOODS}
    base.update(kw)
    return base


def _good(**kw):
    base = {"id": 1, "chat_id": CHAT_ID, "seller_id": SELLER, "item_key": "ogurcy",
            "name": "Огурцы", "emoji": "🥒", "description": None, "price": 500,
            "sold": 0, "earned": 0, "status": "approved"}
    base.update(kw)
    return base


class _Spy:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.coins: list[tuple[int, int]] = []
        self.treasury: list[int] = []
        self.inventory: list[tuple[str, int]] = []

    def install(self, monkeypatch):
        db = bot_module.db
        monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
        monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: True)
        monkeypatch.setattr(bot_module, "display_name", _returns("Покупатель"))
        monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Продавец"))
        monkeypatch.setattr(bot_module, "_dm_or_none", _noop)
        monkeypatch.setattr(db, "add_log", _noop)
        monkeypatch.setattr(db, "record_market_sale", _noop)
        monkeypatch.setattr(db, "add_coins",
                            lambda c, u, amount, *a, **k: _returns(self.coins.append((u, amount)))())
        monkeypatch.setattr(db, "add_chat_coins",
                            lambda c, amount: _returns(self.treasury.append(amount))())
        monkeypatch.setattr(db, "add_inventory_item",
                            lambda c, u, key, amount=1: _returns(self.inventory.append((key, amount)))())

        # Покупка идёт одной транзакцией (db.market_purchase). Подменяем её
        # целиком и записываем ровно то, что она сделала бы с деньгами, —
        # так тест проверяет намерение бота, а не устройство SQL.
        self.balance = 100_000

        async def purchase(chat_id, buyer_id, seller_id, good_id, item_key,
                           quantity, total, to_seller, fee):
            if self.balance < total:
                return False
            self.balance -= total
            self.coins.append((buyer_id, -total))
            self.coins.append((seller_id, to_seller))
            if fee:
                self.treasury.append(fee)
            self.inventory.append((item_key, quantity))
            return True

        monkeypatch.setattr(db, "market_purchase", purchase)

    def message(self, text: str, user_id: int = BUYER):
        from aiogram.types import Chat, Message, User
        m = Message(
            message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=user_id, is_bot=False, first_name="Тестер"), text=text,
        )

        async def collect(t, **k):
            self.said.append(t)

        object.__setattr__(m, "reply", collect)
        object.__setattr__(m, "answer", collect)
        return m


# --- арифметика денег -------------------------------------------------------

def test_сумма_сходится_копейка_в_копейку():
    """Ничто не должно создаваться из воздуха и не должно пропадать."""
    for price in (1, 7, 99, 500, 12_345):
        for qty in (1, 3, 17):
            for fee_pct in (0, 5, 10, 33, 50):
                total, to_seller, fee = market.split_payment(price, qty, fee_pct)
                assert total == price * qty
                assert to_seller + fee == total, (price, qty, fee_pct)
                assert to_seller >= 0 and fee >= 0


def test_комиссия_округляется_вниз_в_пользу_продавца():
    total, to_seller, fee = market.split_payment(101, 1, 10)
    assert (total, to_seller, fee) == (101, 91, 10)


def test_нулевая_комиссия_отдаёт_всё_продавцу():
    assert market.split_payment(500, 2, 0) == (1000, 1000, 0)


# --- ключи ------------------------------------------------------------------

@pytest.mark.parametrize("key", ["ogurcy", "abc", "a_b_1", "x" * 32])
def test_годные_ключи(key):
    assert market.validate_key(key) == ""


@pytest.mark.parametrize("key", ["ab", "x" * 33, "Огурцы", "og urcy", "og-urcy", ""])
def test_негодные_ключи(key):
    assert market.validate_key(key) != ""


def test_потолок_цены_не_обойти():
    settings = market.Settings(max_price=1000)
    assert market.validate_price(1000, settings) == ""
    assert market.validate_price(1001, settings) != ""
    assert market.validate_price(0, settings) != ""
    assert market.validate_price(-5, settings) != ""


@pytest.mark.parametrize("key", ["talisman", "energetik", "strahovka", "medvezhatnik"])
def test_ключи_предметов_магазина_заняты(key, monkeypatch):
    """Самая опасная коллизия: досев магазина молча пропустил бы настоящий
    предмет, и чат остался бы без него навсегда."""
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(None))
    assert asyncio.run(bot_module._market_key_taken(CHAT_ID, key)) != ""


@pytest.mark.parametrize("key", ["traktor", "portfel", "slitok"])
def test_ключи_ачивочных_предметов_заняты(key, monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(None))
    assert asyncio.run(bot_module._market_key_taken(CHAT_ID, key)) != ""


def test_ключи_предметов_ограбления_заняты(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(None))
    for key in list(robbery.ROBBERY_ITEMS)[:3]:
        assert asyncio.run(bot_module._market_key_taken(CHAT_ID, key)) != ""


def test_свободный_ключ_проходит(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(None))
    assert asyncio.run(bot_module._market_key_taken(CHAT_ID, "ogurcy")) == ""


def test_занятый_в_чате_ключ_не_проходит(monkeypatch):
    """Монополия: товар в чате продаёт кто-то один."""
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(_good()))
    assert asyncio.run(bot_module._market_key_taken(CHAT_ID, "ogurcy")) != ""


def test_каталоги_ботa_не_пересекаются_между_собой():
    """Если ключ есть и в магазине, и у ограблений — какой-то из них молча
    не доедет до чата."""
    shop = set(SE.BY_KEY) | set(SE.ACHIEVEMENT_BY_KEY) | set(SE.REWARD_BY_KEY)
    assert not (shop & set(robbery.ROBBERY_ITEMS))


# --- покупка ----------------------------------------------------------------

def _buy_setup(monkeypatch, spy, good=None, coins=100_000, settings=None):
    db = bot_module.db
    spy.install(monkeypatch)
    spy.balance = coins
    monkeypatch.setattr(db, "get_market_good", _returns(good if good is not None else _good()))
    monkeypatch.setattr(db, "get_market_settings", _returns(settings or _settings()))
    monkeypatch.setattr(db, "get_wallet", _returns({"coins": coins}))


def test_покупка_двигает_деньги_и_кладёт_товар(monkeypatch):
    spy = _Spy()
    _buy_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить ogurcy 2")))

    assert (BUYER, -1000) in spy.coins, spy.coins
    assert (SELLER, 900) in spy.coins
    assert spy.treasury == [100]
    assert spy.inventory == [("ogurcy", 2)]


def test_покупка_ничего_не_создаёт_из_воздуха(monkeypatch):
    """Сколько ушло у покупателя — столько пришло продавцу и в казну."""
    spy = _Spy()
    _buy_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить ogurcy 3")))

    paid = -sum(a for u, a in spy.coins if u == BUYER)
    got = sum(a for u, a in spy.coins if u == SELLER)
    assert paid == got + sum(spy.treasury)


def test_свой_товар_не_купить(monkeypatch):
    spy = _Spy()
    _buy_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить ogurcy", user_id=SELLER)))
    assert not spy.coins
    assert any("свой" in s.lower() for s in spy.said)


def test_без_денег_покупки_нет(monkeypatch):
    spy = _Spy()
    _buy_setup(monkeypatch, spy, coins=10)
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить ogurcy")))
    assert not spy.coins
    assert not spy.inventory
    assert any("хватает" in s for s in spy.said)


def test_неодобренный_товар_не_купить(monkeypatch):
    spy = _Spy()
    _buy_setup(monkeypatch, spy, good=_good(status="pending"))
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить ogurcy")))
    assert not spy.coins


def test_несуществующий_товар_не_купить(monkeypatch):
    spy = _Spy()
    _buy_setup(monkeypatch, spy, good=None)
    monkeypatch.setattr(bot_module.db, "get_market_good", _returns(None))
    asyncio.run(bot_module.cmd_market_buy(spy.message("рынок купить nety")))
    assert not spy.coins


def test_количество_ограничено_сверху(monkeypatch):
    """Опечатка в количестве иначе выносит кошелёк целиком."""
    spy = _Spy()
    _buy_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_buy(
        spy.message(f"рынок купить ogurcy {market.BUY_MAX_QTY + 1}")))
    assert not spy.coins


# --- заявки -----------------------------------------------------------------

def _apply_setup(monkeypatch, spy, settings=None, mine=0):
    db = bot_module.db
    spy.install(monkeypatch)
    monkeypatch.setattr(db, "get_market_settings", _returns(settings or _settings()))
    monkeypatch.setattr(db, "get_shop_item", _returns(None))
    monkeypatch.setattr(db, "get_market_good", _returns(None))
    monkeypatch.setattr(db, "count_market_goods_of", _returns(mine))
    created = {}

    async def add_good(chat_id, seller_id, key, name, price, **kw):
        created.update(key=key, price=price, status=kw.get("status"))
        return 42

    monkeypatch.setattr(db, "add_market_good", add_good)
    return created


def test_заявка_ждёт_решения(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))
    assert created["status"] == "pending"
    assert any("Заявка №42" in s for s in spy.said)


def test_автопринятие_пускает_сразу(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy,
                           settings=_settings(mode=market.MODE_AUTO_ACCEPT))
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))
    assert created["status"] == "approved"


def test_автоотклонение_не_принимает_заявок(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy,
                           settings=_settings(mode=market.MODE_AUTO_REJECT))
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))
    assert not created
    assert any("закрыт" in s for s in spy.said)


def test_цена_выше_потолка_не_проходит(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy, settings=_settings(max_price=1000))
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 5000 Огурцы")))
    assert not created
    assert any("Потолок" in s for s in spy.said)


def test_лимит_товаров_на_человека(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy, mine=market.DEFAULT_MAX_GOODS)
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))
    assert not created


def test_занятый_ключ_не_заявить(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка talisman 500 Талисман")))
    assert not created


def test_кривой_ключ_не_заявить(monkeypatch):
    spy = _Spy()
    created = _apply_setup(monkeypatch, spy)
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка Огурцы 500 Огурцы")))
    assert not created


# --- снятие товара ----------------------------------------------------------

def test_снятие_непроданного_освобождает_ключ(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    monkeypatch.setattr(bot_module.db, "remove_market_good", _returns("deleted"))
    asyncio.run(bot_module.cmd_market_withdraw(spy.message("рынок снять ogurcy")))
    assert any("ключ снова свободен" in s for s in spy.said)


def test_снятие_проданного_оставляет_ключ_за_продавцом(monkeypatch):
    """Строку удалять нельзя: по ней в инвентаре покупателей резолвятся
    название и эмодзи. Удали — и у всех «огурцы» станут голым ключом, а сам
    ключ смог бы занять кто-то другой со своим товаром."""
    spy = _Spy()
    spy.install(monkeypatch)
    monkeypatch.setattr(bot_module.db, "remove_market_good", _returns("withdrawn"))
    asyncio.run(bot_module.cmd_market_withdraw(spy.message("рынок снять ogurcy")))
    said = " ".join(spy.said)
    assert "остаётся за вами" in said
    assert "ключ снова свободен" not in said


def test_чужой_товар_не_снять(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    monkeypatch.setattr(bot_module.db, "remove_market_good", _returns(None))
    asyncio.run(bot_module.cmd_market_withdraw(spy.message("рынок снять chuzhoe")))
    assert any("нет товара" in s for s in spy.said)


def test_свой_снятый_товар_возвращается_на_витрину(monkeypatch):
    """Обычная проверка занятости ключа отбила бы владельца от его же товара."""
    spy = _Spy()
    spy.install(monkeypatch)
    monkeypatch.setattr(bot_module.db, "get_market_settings", _returns(_settings()))
    monkeypatch.setattr(bot_module.db, "get_market_good",
                        _returns(_good(status="withdrawn", seller_id=BUYER)))
    relisted = {}
    monkeypatch.setattr(bot_module.db, "relist_market_good",
                        lambda c, gid, price, status: _returns(
                            relisted.update(id=gid, price=price, status=status))())

    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 700 Огурцы")))
    assert relisted == {"id": 1, "price": 700, "status": "pending"}


def test_чужой_снятый_товар_не_перехватить(monkeypatch):
    """Ключ остаётся за прежним продавцом — иначе инвентари покупателей
    начали бы врать про чужой товар."""
    spy = _Spy()
    spy.install(monkeypatch)
    monkeypatch.setattr(bot_module.db, "get_market_settings", _returns(_settings()))
    monkeypatch.setattr(bot_module.db, "get_market_good",
                        _returns(_good(status="withdrawn", seller_id=SELLER)))
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(None))
    created = {}
    monkeypatch.setattr(bot_module.db, "add_market_good",
                        lambda *a, **k: _returns(created.update(hit=True))())
    monkeypatch.setattr(bot_module.db, "relist_market_good", _noop)
    monkeypatch.setattr(bot_module.db, "count_market_goods_of", _returns(0))

    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 700 Мои огурцы")))
    assert not created
    assert any("занят" in s for s in spy.said)


# --- куда уходят заявки -----------------------------------------------------

NOTIFY_CHAT = -1009999999999


def test_заявка_уходит_в_чат_уведомлений(monkeypatch):
    """Не в чат жалоб и не в исходный чат: туда же, куда заявки на вступление."""
    spy = _Spy()
    _apply_setup(monkeypatch, spy)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", NOTIFY_CHAT)
    monkeypatch.setitem(bot_module.settings, "notify_topic_id", 7)
    sent = {}

    async def send(chat_id, text, message_thread_id=None, reply_markup=None, **k):
        sent.update(chat_id=chat_id, text=text, topic=message_thread_id,
                    kb=reply_markup)

    monkeypatch.setattr(bot_module.bot, "send_message", send)

    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))

    assert sent["chat_id"] == NOTIFY_CHAT
    assert sent["topic"] == 7
    assert "Заявка на рынок" in sent["text"]
    assert any("отправлена администрации" in s for s in spy.said)


def test_кнопки_заявки_несут_исходный_чат(monkeypatch):
    """Кнопку жмут в чате уведомлений, а решение нужно исходному чату."""
    spy = _Spy()
    _apply_setup(monkeypatch, spy)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", NOTIFY_CHAT)
    monkeypatch.setitem(bot_module.settings, "notify_topic_id", None)
    sent = {}

    async def send(chat_id, text, message_thread_id=None, reply_markup=None, **k):
        sent.update(kb=reply_markup)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))

    payloads = [b.callback_data for row in sent["kb"].inline_keyboard for b in row]
    assert payloads == [f"mktok:{CHAT_ID}:42", f"mktno:{CHAT_ID}:42"]
    for payload in payloads:
        assert len(payload.encode()) <= 64, "callback_data не влезет в лимит Telegram"


def test_без_настроенного_чата_заявка_ждёт_панель(monkeypatch):
    """Текстовых команд решения нет: резервный путь — админ-панель."""
    spy = _Spy()
    _apply_setup(monkeypatch, spy)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", None)

    asyncio.run(bot_module.cmd_market_apply(spy.message("рынок заявка ogurcy 500 Огурцы")))
    assert any("ждёт решения администрации в панели" in s.lower() for s in spy.said)
    assert not any("рынок принять" in s or "рынок отклонить" in s for s in spy.said)


def _decide_setup(monkeypatch, spy, good=None):
    db = bot_module.db
    spy.install(monkeypatch)
    monkeypatch.setattr(db, "get_market_good_by_id", _returns(
        good if good is not None else _good(status="pending")))
    monkeypatch.setattr(db, "decide_market_good", _returns(True))
    announced = {}

    async def send(chat_id, text, **k):
        announced.update(chat_id=chat_id, text=text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    return announced


def _callback(data: str):
    from aiogram.types import CallbackQuery, Chat, Message, User
    msg = Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=NOTIFY_CHAT, type="supergroup"),
        from_user=User(id=1, is_bot=True, first_name="Бот"), text="заявка",
    )
    object.__setattr__(msg, "edit_text", _noop)
    cb = CallbackQuery(
        id="1", from_user=User(id=9, is_bot=False, first_name="Админ"),
        chat_instance="x", message=msg, data=data,
    )
    answers = []

    async def answer(text=None, **k):
        answers.append(text or "")

    object.__setattr__(cb, "answer", answer)
    return cb, answers


def test_решение_кнопкой_объявляется_в_исходном_чате(monkeypatch):
    spy = _Spy()
    announced = _decide_setup(monkeypatch, spy)
    cb, _answers = _callback(f"mktok:{CHAT_ID}:1")

    asyncio.run(bot_module.market_decide_cb(cb))
    assert announced["chat_id"] == CHAT_ID, "объявили не в том чате"
    assert "одобрена" in announced["text"]


def test_отклонение_кнопкой_освобождает_ключ(monkeypatch):
    spy = _Spy()
    announced = _decide_setup(monkeypatch, spy)
    cb, _answers = _callback(f"mktno:{CHAT_ID}:1")

    asyncio.run(bot_module.market_decide_cb(cb))
    assert "отклонена" in announced["text"]
    assert "свободен" in announced["text"]


def test_кнопку_жмёт_только_администрация(monkeypatch):
    spy = _Spy()
    _decide_setup(monkeypatch, spy)
    monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: False)
    decided = []
    monkeypatch.setattr(bot_module.db, "decide_market_good",
                        lambda *a, **k: _returns(decided.append(1))())

    cb, answers = _callback(f"mktok:{CHAT_ID}:1")
    asyncio.run(bot_module.market_decide_cb(cb))
    assert not decided
    assert any("администрация" in a for a in answers)


def test_разобранную_заявку_повторно_не_провести(monkeypatch):
    spy = _Spy()
    _decide_setup(monkeypatch, spy, good=_good(status="approved"))
    cb, answers = _callback(f"mktok:{CHAT_ID}:1")
    asyncio.run(bot_module.market_decide_cb(cb))
    assert any("уже разобрали" in a for a in answers)


# --- режимы и настройки -----------------------------------------------------

def test_все_режимы_подписаны():
    for mode in market.MODES:
        assert market.MODE_LABEL[mode]


def test_комиссия_ограничена_сверху(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    saved = {}
    monkeypatch.setattr(bot_module.db, "set_market_settings",
                        lambda c, **kw: _returns(saved.update(kw))())
    asyncio.run(bot_module.cmd_market_config(spy.message("рынок комиссия 80")))
    assert not saved, "комиссия 80% — это уже не комиссия, а конфискация"

    asyncio.run(bot_module.cmd_market_config(spy.message("рынок комиссия 15")))
    assert saved == {"commission_percent": 15.0}
