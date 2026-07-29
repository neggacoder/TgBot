"""Бизнесы: команды и денежные потоки.

Проверяется не текст ответов, а деньги: что налог уходит в казну, что копилка
обнуляется ровно один раз, что при сорвавшейся сделке покупателю возвращают
всё до коина и что смена владельца не даёт снять доход мимо налога.
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
import businesses as B  # noqa: E402

CHAT_ID = -1001234567890
OWNER_ID = 555
OTHER_ID = 777


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


# --- единый префикс раздела ------------------------------------------------

def test_все_команды_бизнеса_начинаются_со_слова_бизнес():
    """Общий префикс — не косметика. По ведущим словам фразы бот отличает
    команду в CommandCleanupMiddleware ещё ДО выбора обработчика: на этом
    держатся и свой срок автоочистки, и раздача прав по дереву команд.
    Форма вроде «мой бизнес» выпадает из связки и может утащить настройку
    не туда, поэтому её здесь быть не должно.
    """
    triggers = set(bot_module.BUSINESS_LIST_TRIGGERS) | set(bot_module.BUSINESS_MINE_TRIGGERS)
    for trigger in triggers:
        assert trigger.startswith("бизнес"), trigger

    # Формы с аргументами задаются регулярками — они тоже обязаны быть
    # привязаны к началу строки и к тому же слову.
    # Проверяем ПОВЕДЕНИЕ, а не текст шаблона: шаблоны собираются через
    # ru_text.rx и содержат классы [еЕёЁ] вместо голых букв, так что сравнивать
    # их со строкой значило бы проверять способ записи, а не саму привязку.
    samples = [
        (bot_module.BUSINESS_BUY_RE, "купить shaurma"),
        (bot_module.BUSINESS_UPGRADE_RE, "улучшить shaurma"),
        (bot_module.BUSINESS_COLLECT_RE, "собрать"),
        (bot_module.BUSINESS_SELL_BOT_RE, "продать shaurma"),
        (bot_module.BUSINESS_SELL_USER_RE, "продать shaurma 100 @kto"),
        (bot_module.BUSINESS_GIVE_RE, "передать shaurma @kto"),
        (bot_module.BUSINESS_REPAIR_RE, "починить shaurma"),
    ]
    for pattern, tail in samples:
        assert pattern.match(f"бизнес {tail}"), (
            f"{pattern.pattern} не ловит «бизнес {tail}»")
        assert not pattern.match(f"мой бизнес {tail}"), (
            f"{pattern.pattern} срабатывает не с начала строки")


def test_фразы_в_реестре_совпадают_с_реальными_командами():
    """Реестр — источник правды для панели и автоочистки. Если фраза там
    разойдётся с настоящим триггером, панель будет настраивать несуществующую
    команду, и это не заметят.
    """
    for key in ("business_catalog", "business_mine", "business_buy",
                "business_collect", "business_upgrade", "business_sell",
                "business_transfer", "business_repair"):
        phrase = bot_module.COMMAND_REGISTRY[key]["phrase"]
        assert phrase.startswith("бизнес"), (key, phrase)


def test_закрепление_тоже_начинается_со_слова_бизнес():
    assert bot_module.BUSINESS_PIN_RE.match("бизнес закрепить shaurma")
    assert not bot_module.BUSINESS_PIN_RE.match("мой бизнес закрепить shaurma")
    for trigger in bot_module.BUSINESS_UNPIN_TRIGGERS:
        assert trigger.startswith("бизнес"), trigger


def test_каждая_команда_бизнеса_настраивается_отдельно():
    """Панель должна уметь задать свой срок очистки каждой из них — а значит,
    бот обязан отличать их по тексту."""
    for key in ("business_catalog", "business_mine", "business_buy",
                "business_collect", "business_upgrade", "business_sell",
                "business_transfer", "business_repair", "business_pin"):
        assert bot_module.is_cleanup_targetable(key), key


# --- закрепление бизнеса в профиле -----------------------------------------

@pytest.fixture
def pinned(world, monkeypatch):
    """Ловим, что именно записали в закреп профиля."""
    state = {"value": "unset"}

    async def set_pinned_business(chat_id, user_id, key):
        state["value"] = key

    monkeypatch.setattr(bot_module.db, "set_pinned_business",
                        set_pinned_business, raising=False)
    return state


def test_свой_бизнес_закрепляется(world, pinned):
    _own(world, "aeroport")
    msg, replies = _message("бизнес закрепить аэропорт")
    asyncio.run(bot_module.cmd_business_pin(msg))
    assert pinned["value"] == "aeroport"
    assert "закреплён" in replies[0]


def test_чужой_бизнес_не_закрепить(world, pinned):
    """Иначе карточка профиля показывала бы бизнес, которого у человека нет."""
    _own(world, "aeroport", user_id=OTHER_ID)
    msg, replies = _message("бизнес закрепить аэропорт")
    asyncio.run(bot_module.cmd_business_pin(msg))
    assert pinned["value"] == "unset", "в закреп ничего писать не должны"
    assert "не принадлежит" in replies[0]


def test_несуществующий_бизнес_не_закрепить(world, pinned):
    msg, replies = _message("бизнес закрепить чепуха")
    asyncio.run(bot_module.cmd_business_pin(msg))
    assert pinned["value"] == "unset"
    assert "Такого бизнеса нет" in replies[0]


def test_открепление_очищает_закреп(world, pinned):
    msg, replies = _message("бизнес открепить")
    asyncio.run(bot_module.cmd_business_unpin(msg))
    assert pinned["value"] is None
    assert "больше не показывается" in replies[0]


async def _noop(*args, **kwargs):
    return None


def _message(text: str, user_id: int = OWNER_ID):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=user_id, is_bot=False, first_name="Тестер"), text=text,
    )
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    async def answer(t, **k):
        replies.append(t)
        return Message(
            message_id=99, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=1, is_bot=True, first_name="Бот"), text=t,
        )

    object.__setattr__(m, "reply", reply)
    object.__setattr__(m, "answer", answer)
    return m, replies


@pytest.fixture
def world(monkeypatch):
    """Мир в памяти: кошельки, казна и таблица бизнесов."""
    state = {
        "coins": {OWNER_ID: 0, OTHER_ID: 0},
        "treasury": 0,
        "rows": {},          # (user_id, key) -> строка бизнеса
        "logs": [],
    }

    async def add_coins(chat_id, user_id, amount):
        state["coins"][user_id] = state["coins"].get(user_id, 0) + amount
        return state["coins"][user_id]

    async def try_spend(chat_id, user_id, amount):
        if state["coins"].get(user_id, 0) < amount:
            return False
        state["coins"][user_id] -= amount
        return True

    async def add_chat_coins(chat_id, amount):
        state["treasury"] += amount
        return state["treasury"]

    async def list_user_businesses(chat_id, user_id):
        return [dict(v) for (u, _k), v in state["rows"].items() if u == user_id]

    async def get_user_business(chat_id, user_id, key):
        row = state["rows"].get((user_id, key))
        return dict(row) if row else None

    async def add_business(chat_id, user_id, key, now):
        if (user_id, key) in state["rows"]:
            return False
        state["rows"][(user_id, key)] = {
            "business_key": key, "level": 1, "accrued": 0,
            "last_tick_at": now, "bought_at": now,
        }
        return True

    async def set_business_accrual(chat_id, user_id, key, accrued, now):
        row = state["rows"].get((user_id, key))
        if row:
            row["accrued"] = accrued
            row["last_tick_at"] = now

    async def set_business_level(chat_id, user_id, key, level, accrued, now):
        row = state["rows"].get((user_id, key))
        if row:
            row.update(level=level, accrued=accrued, last_tick_at=now)

    async def delete_business(chat_id, user_id, key):
        return state["rows"].pop((user_id, key), None) is not None

    async def move_business(chat_id, from_id, to_id, key, now):
        if (to_id, key) in state["rows"] or (from_id, key) not in state["rows"]:
            return False
        row = state["rows"].pop((from_id, key))
        row.update(accrued=0, last_tick_at=now)
        state["rows"][(to_id, key)] = row
        return True

    async def add_log(kind, **kw):
        state["logs"].append(kind)

    async def get_wallet(chat_id, user_id):
        return {"coins": state["coins"].get(user_id, 0)}

    for name, fn in [
        ("add_coins", add_coins), ("try_spend_coins", try_spend),
        ("add_chat_coins", add_chat_coins), ("get_wallet", get_wallet),
        ("list_user_businesses", list_user_businesses),
        ("get_user_business", get_user_business), ("add_business", add_business),
        ("set_business_accrual", set_business_accrual),
        ("set_business_level", set_business_level),
        ("delete_business", delete_business), ("move_business", move_business),
        ("add_log", add_log),
    ]:
        monkeypatch.setattr(bot_module.db, name, fn, raising=False)

    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "has_infinite_money", lambda uid: False, raising=False)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop, raising=False)
    # Страховка (предмет магазина) проверяется перед каждой поломкой. По
    # умолчанию её нет — поломки происходят как обычно.
    monkeypatch.setattr(bot_module.db, "consume_item_effect", _returns(False), raising=False)
    # Оснащение бизнеса (охрана, реклама, сейф…) — по умолчанию его нет, все
    # числа считаются базовыми. Тесты про оснащение подменяют это сами.
    monkeypatch.setattr(bot_module.db, "list_business_upgrades",
                        _returns(set()), raising=False)
    monkeypatch.setattr(bot_module.db, "clear_business_upgrades", _noop, raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Кто-то"), raising=False)
    monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"), raising=False)
    return state


def _own(state, key, level=1, accrued=0, hours_ago=0.0, user_id=OWNER_ID):
    now = datetime.utcnow() - timedelta(hours=hours_ago)
    state["rows"][(user_id, key)] = {
        "business_key": key, "level": level, "accrued": accrued,
        "last_tick_at": now, "bought_at": now,
    }


# --- покупка ---------------------------------------------------------------

def test_покупка_списывает_цену_и_заводит_бизнес(world):
    world["coins"][OWNER_ID] = 20_000
    msg, _ = _message("бизнес купить шаурма")
    asyncio.run(bot_module.cmd_business_buy(msg))
    assert world["coins"][OWNER_ID] == 20_000 - 12_500
    assert (OWNER_ID, "shaurma") in world["rows"]


def test_без_денег_бизнес_не_покупается(world):
    world["coins"][OWNER_ID] = 100
    msg, replies = _message("бизнес купить шаурма")
    asyncio.run(bot_module.cmd_business_buy(msg))
    assert not world["rows"]
    assert world["coins"][OWNER_ID] == 100
    assert "едостаточно" in replies[0]


def test_второй_такой_же_бизнес_не_продаётся(world):
    world["coins"][OWNER_ID] = 100_000
    _own(world, "shaurma")
    msg, replies = _message("бизнес купить шаурма")
    asyncio.run(bot_module.cmd_business_buy(msg))
    assert world["coins"][OWNER_ID] == 100_000, "деньги не должны списаться"
    assert "уже есть" in replies[0]


def test_деньги_возвращаются_если_бизнес_не_завёлся(world, monkeypatch):
    """Гонка: между проверкой и вставкой такой же бизнес успели завести.
    Списание уже прошло — человек не должен остаться без денег и без бизнеса."""
    world["coins"][OWNER_ID] = 20_000
    monkeypatch.setattr(bot_module.db, "add_business", _returns(False), raising=False)
    msg, replies = _message("бизнес купить шаурма")
    asyncio.run(bot_module.cmd_business_buy(msg))
    assert world["coins"][OWNER_ID] == 20_000, "цена обязана вернуться"
    assert "ещё раз" in replies[0]


# --- сбор дохода -----------------------------------------------------------

def test_сбор_платит_за_вычетом_налога_а_налог_в_казну(world):
    _own(world, "shaurma", hours_ago=4)          # копилка полна: 1000
    msg, _ = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg))
    tax = B.tax_for(1_000)
    assert world["coins"][OWNER_ID] == 1_000 - tax
    assert world["treasury"] == tax
    assert world["rows"][(OWNER_ID, "shaurma")]["accrued"] == 0


def test_повторный_сбор_ничего_не_даёт(world):
    _own(world, "shaurma", hours_ago=4)
    msg, _ = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg))
    earned = world["coins"][OWNER_ID]
    msg2, replies = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg2))
    assert world["coins"][OWNER_ID] == earned, "копилка уже пуста"
    assert "пуст" in replies[0]


def test_налог_считается_с_общей_суммы_а_не_с_каждого(world):
    """Иначе владелец пяти мелких копилок платил бы по нижней ставке пять раз
    и в сумме меньше, чем владелец одной крупной."""
    _own(world, "shaurma", hours_ago=4)      # 1000
    _own(world, "magazin", hours_ago=4)      # 2000
    msg, _ = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg))
    total_tax = B.tax_for(3_000)
    per_business = B.tax_for(1_000) + B.tax_for(2_000)
    assert world["treasury"] == total_tax
    assert total_tax > per_business, "общая сумма обязана облагаться строже"
    assert world["coins"][OWNER_ID] == 3_000 - total_tax


def test_сбор_одного_бизнеса_не_трогает_остальные(world):
    _own(world, "shaurma", hours_ago=4)
    _own(world, "magazin", hours_ago=4)
    msg, _ = _message("бизнес собрать шаурма")
    asyncio.run(bot_module.cmd_business_collect(msg))
    assert world["rows"][(OWNER_ID, "shaurma")]["accrued"] == 0
    assert bot_module._business_pending(world["rows"][(OWNER_ID, "magazin")]) == 2_000


def test_замороженному_счёту_доход_не_идёт(world, monkeypatch):
    _own(world, "shaurma", hours_ago=4)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    msg, replies = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg))
    assert world["coins"][OWNER_ID] == 0
    assert "аморожен" in replies[0]


# --- апгрейд ---------------------------------------------------------------

def test_апгрейд_поднимает_уровень_и_сохраняет_копилку(world):
    world["coins"][OWNER_ID] = 5_000
    _own(world, "shaurma", hours_ago=2)          # накопилось 500
    msg, _ = _message("бизнес улучшить шаурма")
    asyncio.run(bot_module.cmd_business_upgrade(msg))
    row = world["rows"][(OWNER_ID, "shaurma")]
    assert row["level"] == 2
    assert world["coins"][OWNER_ID] == 5_000 - 2_500
    assert row["accrued"] == 500, "накопленное не должно сгореть при апгрейде"


def test_выше_третьего_уровня_не_поднять(world):
    world["coins"][OWNER_ID] = 100_000
    _own(world, "shaurma", level=3)
    msg, replies = _message("бизнес улучшить шаурма")
    asyncio.run(bot_module.cmd_business_upgrade(msg))
    assert world["coins"][OWNER_ID] == 100_000
    assert "максимум" in replies[0]


def test_чужой_бизнес_не_улучшить(world):
    world["coins"][OWNER_ID] = 100_000
    _own(world, "shaurma", user_id=OTHER_ID)
    msg, replies = _message("бизнес улучшить шаурма")
    asyncio.run(bot_module.cmd_business_upgrade(msg))
    assert "не принадлежит" in replies[0]


# --- продажа боту ----------------------------------------------------------

def _ask_bot_sale(text="бизнес продать шаурма", user_id=OWNER_ID):
    """Первый шаг продажи боту: команда только СПРАШИВАЕТ, ничего не меняя."""
    msg, replies = _message(text, user_id)
    asyncio.run(bot_module.cmd_business_sell_to_bot(msg))
    return replies


def test_команда_продажи_боту_только_спрашивает(world):
    """Продажа боту необратима и даёт лишь 70%, а «бизнес продать шаурма» —
    ровно то, что напишет забывший указать цену. Без подтверждения это был бы
    способ потерять бизнес опечаткой."""
    _own(world, "shaurma", hours_ago=4)
    replies = _ask_bot_sale()
    assert (OWNER_ID, "shaurma") in world["rows"], "бизнес обязан остаться до подтверждения"
    assert world["coins"][OWNER_ID] == 0, "и деньги не двигаются"
    assert "Продать боту?" in replies[0]
    assert (CHAT_ID, 99) in bot_module._business_bot_sales
    bot_module._business_bot_sales.pop((CHAT_ID, 99), None)


def test_продажа_боту_даёт_70_процентов_и_инкассирует_копилку(world):
    _own(world, "shaurma", hours_ago=4)          # копилка 1000
    _ask_bot_sale()
    cb = _FakeCallback(OWNER_ID)
    cb.data = "business_sell_bot"
    asyncio.run(bot_module.cb_business_sell_bot(cb))

    tax = B.tax_for(1_000)
    assert (OWNER_ID, "shaurma") not in world["rows"]
    assert world["coins"][OWNER_ID] == 8_750 + (1_000 - tax)
    assert world["treasury"] == tax, "копилка при продаже облагается налогом"


def test_чужой_не_может_продать_ваш_бизнес_боту(world):
    _own(world, "shaurma")
    _ask_bot_sale()
    cb = _FakeCallback(OTHER_ID)
    asyncio.run(bot_module.cb_business_sell_bot(cb))
    assert (OWNER_ID, "shaurma") in world["rows"]
    assert "не ваш" in cb.answers[0]
    bot_module._business_bot_sales.pop((CHAT_ID, 99), None)


def test_протухшее_подтверждение_не_продаёт(world):
    _own(world, "shaurma")
    _ask_bot_sale()
    bot_module._business_bot_sales[(CHAT_ID, 99)]["expires_at"] = (
        datetime.utcnow() - timedelta(seconds=1)
    )
    cb = _FakeCallback(OWNER_ID)
    asyncio.run(bot_module.cb_business_sell_bot(cb))
    assert (OWNER_ID, "shaurma") in world["rows"]
    assert "устарел" in cb.answers[0]


def test_бот_не_доплачивает_за_апгрейды(world):
    """Осознанное правило: бот платит 70% от БАЗОВОЙ цены, вложения сгорают."""
    _own(world, "shaurma", level=3)
    _ask_bot_sale()
    cb = _FakeCallback(OWNER_ID)
    asyncio.run(bot_module.cb_business_sell_bot(cb))
    assert world["coins"][OWNER_ID] == 8_750


# --- передача --------------------------------------------------------------

def test_передача_отдаёт_бизнес_а_копилку_оставляет_прежнему(world, monkeypatch):
    """Ключевая защита от дыры: иначе можно было бы накопить до потолка,
    «передать» второму аккаунту и забрать доход уже без налога."""
    _own(world, "shaurma", hours_ago=4)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((type("T", (), {"id": OTHER_ID, "is_bot": False})(), "")),
                        raising=False)
    msg, _ = _message("бизнес передать шаурма @kto")
    asyncio.run(bot_module.cmd_business_give(msg))

    tax = B.tax_for(1_000)
    assert (OTHER_ID, "shaurma") in world["rows"]
    assert (OWNER_ID, "shaurma") not in world["rows"]
    assert world["coins"][OWNER_ID] == 1_000 - tax, "копилка ушла прежнему владельцу"
    assert world["treasury"] == tax
    assert world["rows"][(OTHER_ID, "shaurma")]["accrued"] == 0, "бизнес переходит пустым"
    assert world["coins"][OTHER_ID] == 0


def test_передача_себе_не_проходит(world, monkeypatch):
    _own(world, "shaurma", hours_ago=4)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((type("T", (), {"id": OWNER_ID, "is_bot": False})(), "")),
                        raising=False)
    msg, replies = _message("бизнес передать шаурма @self")
    asyncio.run(bot_module.cmd_business_give(msg))
    assert (OWNER_ID, "shaurma") in world["rows"]
    assert world["coins"][OWNER_ID] == 0, "копилку тоже не должно было забрать"


def test_передача_не_проходит_если_у_получателя_такой_уже_есть(world, monkeypatch):
    _own(world, "shaurma")
    _own(world, "shaurma", user_id=OTHER_ID)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((type("T", (), {"id": OTHER_ID, "is_bot": False})(), "")),
                        raising=False)
    msg, replies = _message("бизнес передать шаурма @kto")
    asyncio.run(bot_module.cmd_business_give(msg))
    assert (OWNER_ID, "shaurma") in world["rows"], "бизнес остаётся у владельца"
    assert "уже есть" in replies[-1]


# --- сделка с игроком ------------------------------------------------------

class _FakeMessage:
    """Минимальное сообщение под кнопкой: обработчику нужны только чат,
    номер сообщения и возможность переписать текст."""

    def __init__(self, message_id, edited: list):
        self.chat = type("Chat", (), {"id": CHAT_ID})()
        self.message_id = message_id
        self._edited = edited

    async def edit_text(self, text, reply_markup=None):
        self._edited.append(text)


class _FakeCallback:
    def __init__(self, user_id, message_id=99):
        self.answers: list = []
        self.edited: list = []
        self.from_user = type("User", (), {"id": user_id})()
        self.data = "business_buy_offer"
        self.message = _FakeMessage(message_id, self.edited)

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


@pytest.fixture
def offer(world):
    """Открытое предложение: продавец отдаёт полную шаурму за 9000."""
    _own(world, "shaurma", hours_ago=4)
    bot_module._business_offers[(CHAT_ID, 99)] = {
        "seller_id": OWNER_ID, "buyer_id": OTHER_ID, "key": "shaurma", "price": 9_000,
        "expires_at": datetime.utcnow() + bot_module.BUSINESS_OFFER_TTL,
    }
    yield world
    bot_module._business_offers.pop((CHAT_ID, 99), None)


def test_сделка_переносит_бизнес_и_деньги(offer):
    offer["coins"][OTHER_ID] = 10_000
    cb = _FakeCallback(OTHER_ID)
    asyncio.run(bot_module.cb_business_buy_offer(cb))

    tax = B.tax_for(1_000)
    assert (OTHER_ID, "shaurma") in offer["rows"]
    assert offer["coins"][OTHER_ID] == 10_000 - 9_000
    # продавцу: цена + копилка за вычетом налога
    assert offer["coins"][OWNER_ID] == 9_000 + (1_000 - tax)
    assert offer["treasury"] == tax
    assert offer["rows"][(OTHER_ID, "shaurma")]["accrued"] == 0


def test_чужой_не_может_принять_предложение(offer):
    offer["coins"][123] = 100_000
    cb = _FakeCallback(123)
    asyncio.run(bot_module.cb_business_buy_offer(cb))
    assert (OWNER_ID, "shaurma") in offer["rows"]
    assert "не вам" in cb.answers[0]


def test_без_денег_сделка_не_проходит(offer):
    offer["coins"][OTHER_ID] = 100
    cb = _FakeCallback(OTHER_ID)
    asyncio.run(bot_module.cb_business_buy_offer(cb))
    assert (OWNER_ID, "shaurma") in offer["rows"], "бизнес остаётся у продавца"
    assert offer["coins"][OTHER_ID] == 100
    assert offer["coins"][OWNER_ID] == 0, "копилку тоже не трогали"


def test_протухшее_предложение_не_срабатывает(offer):
    offer["coins"][OTHER_ID] = 100_000
    bot_module._business_offers[(CHAT_ID, 99)]["expires_at"] = (
        datetime.utcnow() - timedelta(seconds=1)
    )
    cb = _FakeCallback(OTHER_ID)
    asyncio.run(bot_module.cb_business_buy_offer(cb))
    assert (OWNER_ID, "shaurma") in offer["rows"]
    assert "устарел" in cb.answers[0]


def test_деньги_возвращаются_если_перенос_сорвался(offer, monkeypatch):
    """Покупатель успел завести такой же бизнес между нажатием и переносом."""
    offer["coins"][OTHER_ID] = 10_000
    monkeypatch.setattr(bot_module.db, "move_business", _returns(False), raising=False)
    cb = _FakeCallback(OTHER_ID)
    asyncio.run(bot_module.cb_business_buy_offer(cb))
    assert offer["coins"][OTHER_ID] == 10_000, "цена обязана вернуться покупателю"
    assert "вернулись" in cb.answers[0]


def test_несуществующее_предложение_не_падает():
    cb = _FakeCallback(OTHER_ID, message_id=12345)
    asyncio.run(bot_module.cb_business_buy_offer(cb))
    assert cb.answers and "устарел" in cb.answers[0]


# --- поломки ---------------------------------------------------------------

@pytest.fixture
def broken(world, monkeypatch):
    """Сломанная шаурмичная с 400 i¢ в копилке на момент поломки."""
    async def set_broken(chat_id, user_id, key, kind, accrued, now):
        row = world["rows"].get((user_id, key))
        if not row or row.get("broken_kind"):
            return False
        row.update(broken_kind=kind, broken_at=now, accrued=accrued, last_tick_at=now)
        return True

    async def repair(chat_id, user_id, key, now):
        row = world["rows"].get((user_id, key))
        if not row or not row.get("broken_kind"):
            return False
        row.update(broken_kind=None, broken_at=None, last_tick_at=now)
        return True

    monkeypatch.setattr(bot_module.db, "set_business_broken", set_broken, raising=False)
    monkeypatch.setattr(bot_module.db, "repair_business", repair, raising=False)
    _own(world, "shaurma", accrued=400, hours_ago=0)
    world["rows"][(OWNER_ID, "shaurma")]["broken_kind"] = "сломался гриль"
    return world


def test_сломанный_бизнес_не_копит(broken):
    """Ради этого поломка и заводится: доход обязан остановиться."""
    row = broken["rows"][(OWNER_ID, "shaurma")]
    row["last_tick_at"] = datetime.utcnow() - timedelta(hours=10)
    assert bot_module._business_pending(row) == 400, "копилка замерла на моменте поломки"


def test_накопленное_до_поломки_можно_забрать(broken):
    """Деньги, заработанные ДО аварии, не должны сгорать — иначе поломка
    воспринимается как воровство, а не как расход."""
    msg, _ = _message("бизнес собрать")
    asyncio.run(bot_module.cmd_business_collect(msg))
    tax = B.tax_for(400)
    assert broken["coins"][OWNER_ID] == 400 - tax


def test_ремонт_чинит_и_списывает_стоимость_копилки(broken):
    broken["coins"][OWNER_ID] = 5_000
    ok, text = asyncio.run(bot_module._do_repair(CHAT_ID, OWNER_ID, "shaurma"))
    assert ok
    cost = B.repair_cost(B.BY_KEY["shaurma"], 1)      # полная копилка = 1000
    assert broken["coins"][OWNER_ID] == 5_000 - cost
    assert broken["rows"][(OWNER_ID, "shaurma")]["broken_kind"] is None


def test_после_ремонта_доход_идёт_заново(broken):
    broken["coins"][OWNER_ID] = 5_000
    asyncio.run(bot_module._do_repair(CHAT_ID, OWNER_ID, "shaurma"))
    row = broken["rows"][(OWNER_ID, "shaurma")]
    row["last_tick_at"] = datetime.utcnow() - timedelta(hours=1)
    assert bot_module._business_pending(row) == 400 + 250


def test_без_денег_бизнес_не_чинится(broken):
    broken["coins"][OWNER_ID] = 10
    ok, text = asyncio.run(bot_module._do_repair(CHAT_ID, OWNER_ID, "shaurma"))
    assert not ok
    assert broken["coins"][OWNER_ID] == 10
    assert broken["rows"][(OWNER_ID, "shaurma")]["broken_kind"] == "сломался гриль"


def test_целый_бизнес_чинить_нечего(world):
    world["coins"][OWNER_ID] = 5_000
    _own(world, "shaurma")
    ok, text = asyncio.run(bot_module._do_repair(CHAT_ID, OWNER_ID, "shaurma"))
    assert not ok
    assert world["coins"][OWNER_ID] == 5_000, "деньги не должны списаться"
    assert "чинить нечего" in text


def test_дважды_сломать_нельзя(broken):
    """Два тика цикла подряд не должны обнулять уже идущий простой."""
    row = broken["rows"][(OWNER_ID, "shaurma")]
    asyncio.run(bot_module._break_business(CHAT_ID, {**row, "user_id": OWNER_ID}))
    assert row["broken_kind"] == "сломался гриль", "поломка не должна перезаписаться"


def test_поломка_работает_даже_если_лс_закрыты(world, monkeypatch, broken):
    """Уведомление в личку — удобство, а не канал доставки: у половины чата
    лс закрыты, и бизнес обязан сломаться в любом случае."""
    from aiogram.exceptions import TelegramForbiddenError

    async def forbidden(*a, **k):
        raise TelegramForbiddenError(method=None, message="bot can't initiate conversation")

    monkeypatch.setattr(bot_module.bot, "send_message", forbidden, raising=False)
    _own(world, "aeroport")
    row = dict(world["rows"][(OWNER_ID, "aeroport")], user_id=OWNER_ID)
    asyncio.run(bot_module._break_business(CHAT_ID, row))
    assert world["rows"][(OWNER_ID, "aeroport")]["broken_kind"], "поломка обязана состояться"


def test_сломанный_бизнес_виден_в_моих_бизнесах(broken):
    """Раз лс могут не дойти, состояние обязано быть видно в чате."""
    text = asyncio.run(bot_module._my_businesses_text(CHAT_ID, OWNER_ID))
    assert "СЛОМАН" in text
    assert "сломался гриль" in text
    assert "бизнес починить" in text
