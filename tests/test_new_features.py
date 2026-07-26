"""Новое: 20-й модуль «Браки», рыбалка, клад и защита очистки команд.

Проверяется логика, а не БД: все обращения к db подменяются. Смысл — поймать
то, что маршрутизацией не ловится: расчёт цены продления, кулдауны, рост
клада, порядок «сначала кулдаун, потом монеты», и — главное — что очистка
команд не удаляет сообщения по протухшему сроку.
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

CHAT_ID = -1001234567890
USER_ID = 555
PARTNER_ID = 999


async def _noop(*args, **kwargs):
    return None


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


@pytest.fixture(autouse=True)
def _quiet_db(monkeypatch):
    """Общие заглушки, которые нужны почти каждому тесту ниже."""
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Партнёр"), raising=False)
    # Награды за рыбалку и клад с некоторых пор проходят через множитель
    # случайного события чата, а тот лезет в БД за активным событием. Здесь
    # проверяется расчёт награды, а не события, поэтому множитель нейтральный:
    # без этой заглушки тесты падают на «DB pool is not initialized».
    # Тесту про события (см. tests/test_chat_events.py) эта фикстура не мешает.
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0), raising=False)
    # Талисман удачи (предмет магазина) проверяется на каждом начислении.
    # Здесь его нет — значит, заряд не тратится и награда не удваивается.
    monkeypatch.setattr(bot_module.db, "consume_item_effect", _returns(False), raising=False)


# ---------------------------------------------------------------------------
# Браки: продление
# ---------------------------------------------------------------------------

def _extend_message(text: str):
    """Минимальный объект-сообщение: команде нужны только текст, чат и автор."""
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )
    replies = []

    async def reply(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    return m, replies


def test_продление_брака_списывает_цену_за_каждые_сутки(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_marriage_settings",
                        _returns({"renew_price": 500, "divorce_mode": "off", "rating_enabled": True}))
    monkeypatch.setattr(bot_module.db, "get_marriage",
                        _returns({"id": 1, "partner_id": PARTNER_ID,
                                  "married_at": datetime.utcnow(), "expires_at": None}))
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 10_000}))
    monkeypatch.setattr(bot_module, "has_infinite_money", lambda uid: False)

    charged = {}

    # Списание идёт через db.try_spend_coins: одним запросом «проверить и
    # вычесть», иначе две одновременные команды спишут одни и те же монеты.
    # Поэтому сумма приходит ПОЛОЖИТЕЛЬНОЙ (это «сколько снять»), а не
    # отрицательной прибавкой, как было при db.add_coins.
    async def try_spend_coins(chat_id, user_id, amount):
        charged["amount"] = amount
        return True

    new_expiry = datetime.utcnow() + timedelta(days=7)
    monkeypatch.setattr(bot_module.db, "try_spend_coins", try_spend_coins)
    monkeypatch.setattr(bot_module.db, "extend_marriage", _returns(new_expiry))

    msg, replies = _extend_message("брак продлить 7")
    asyncio.run(bot_module.cmd_marriage_extend(msg))

    assert charged["amount"] == 3500, "7 суток по 500 i¢ = 3500"
    assert replies and "7" in replies[0]


def test_продление_без_денег_ничего_не_списывает(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_marriage_settings",
                        _returns({"renew_price": 500, "divorce_mode": "off", "rating_enabled": True}))
    monkeypatch.setattr(bot_module.db, "get_marriage",
                        _returns({"id": 1, "partner_id": PARTNER_ID,
                                  "married_at": datetime.utcnow(), "expires_at": None}))
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 100}))
    monkeypatch.setattr(bot_module, "has_infinite_money", lambda uid: False)

    extended = []

    # Денег не хватает — try_spend_coins отказывает и НИЧЕГО не списывает.
    # Главное здесь: после отказа брак не должен продлиться.
    async def try_spend_coins(chat_id, user_id, amount):
        return False

    monkeypatch.setattr(bot_module.db, "try_spend_coins", try_spend_coins)
    monkeypatch.setattr(bot_module.db, "extend_marriage",
                        lambda *a, **k: extended.append(a) or _noop())

    msg, replies = _extend_message("брак продлить 7")
    asyncio.run(bot_module.cmd_marriage_extend(msg))

    assert not extended, "после отказа в списании брак продлевать нельзя"
    assert replies and "едостаточно" in replies[0]


def test_продление_без_брака_отказывает(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_marriage_settings",
                        _returns({"renew_price": 500, "divorce_mode": "off", "rating_enabled": True}))
    monkeypatch.setattr(bot_module.db, "get_marriage", _returns(None))

    msg, replies = _extend_message("брак продлить 3")
    asyncio.run(bot_module.cmd_marriage_extend(msg))
    assert replies and "не в браке" in replies[0]


def test_бесплатное_продление_не_трогает_кошелёк(monkeypatch):
    """Цена 0 — админ выключил плату; тогда кошелёк вообще не читается."""
    monkeypatch.setattr(bot_module.db, "get_marriage_settings",
                        _returns({"renew_price": 0, "divorce_mode": "off", "rating_enabled": True}))
    monkeypatch.setattr(bot_module.db, "get_marriage",
                        _returns({"id": 1, "partner_id": PARTNER_ID,
                                  "married_at": datetime.utcnow(), "expires_at": None}))

    async def boom(*a, **k):
        raise AssertionError("кошелёк не должен читаться при нулевой цене")

    monkeypatch.setattr(bot_module.db, "get_wallet", boom)
    monkeypatch.setattr(bot_module.db, "add_coins", boom)
    monkeypatch.setattr(bot_module.db, "extend_marriage",
                        _returns(datetime.utcnow() + timedelta(days=2)))

    msg, replies = _extend_message("брак продлить 2")
    asyncio.run(bot_module.cmd_marriage_extend(msg))
    assert replies and "продлён" in replies[0]


def test_срок_бессрочного_брака_подписан_как_бессрочный():
    assert "бессрочный" in bot_module._marriage_expiry_line(None)


def test_истёкший_срок_видно_по_тексту():
    past = datetime.utcnow() - timedelta(days=1)
    assert "истёк" in bot_module._marriage_expiry_line(past)


# ---------------------------------------------------------------------------
# Браки: ответ словами
# ---------------------------------------------------------------------------

def test_предложение_живёт_ограниченное_время(monkeypatch):
    bot_module._marriage_proposals.clear()
    bot_module._remember_proposal(CHAT_ID, USER_ID, PARTNER_ID)
    assert bot_module._take_proposal(CHAT_ID, USER_ID) == PARTNER_ID
    # забрали — второй раз уже нечего
    assert bot_module._take_proposal(CHAT_ID, USER_ID) is None


def test_протухшее_предложение_не_принимается():
    bot_module._marriage_proposals.clear()
    old = datetime.utcnow() - bot_module.MARRIAGE_PROPOSAL_TTL - timedelta(minutes=1)
    bot_module._marriage_proposals[(CHAT_ID, USER_ID)] = (PARTNER_ID, old)
    assert bot_module._take_proposal(CHAT_ID, USER_ID) is None


def test_подкоманды_не_считаются_предложением():
    """Иначе «Брак да» уходило бы в предложение руки и сердца."""
    assert bot_module._is_marriage_proposal("брак @user") is True
    assert bot_module._is_marriage_proposal("брак") is True
    for sub in ("брак да", "брак нет", "брак продлить 5",
                "брак цена продления 100", "брак режим развода авто"):
        assert bot_module._is_marriage_proposal(sub) is False, sub


# ---------------------------------------------------------------------------
# Рыбалка
# ---------------------------------------------------------------------------

def test_улов_всегда_чего_то_стоит():
    for _ in range(300):
        _emoji, name, amount = bot_module.roll_catch()
        assert amount >= 1 and name


def test_рыбалка_ставит_кулдаун_до_начисления(monkeypatch):
    """Порядок важен: упади запись улова — человек останется без монет, но не
    с возможностью забрасывать удочку в цикле."""
    order = []

    monkeypatch.setattr(bot_module.db, "get_fishing_stats",
                        _returns({"last_fish_at": None, "total_catches": 0,
                                  "best_catch": 0, "best_catch_name": None}))

    async def record_catch(chat_id, user_id, amount, name, now):
        order.append("cooldown")
        return {"total_catches": 1, "best_catch": amount, "best_catch_name": name}

    async def add_coins(chat_id, user_id, amount):
        order.append("coins")
        return amount

    monkeypatch.setattr(bot_module.db, "record_catch", record_catch)
    monkeypatch.setattr(bot_module.db, "add_coins", add_coins)

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert order == ["cooldown", "coins"], order
    assert "i¢" in text


def test_рыбалка_на_кулдауне_не_начисляет(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_fishing_stats",
                        _returns({"last_fish_at": datetime.utcnow(), "total_catches": 3,
                                  "best_catch": 100, "best_catch_name": "окунь"}))

    async def boom(*a, **k):
        raise AssertionError("на кулдауне ничего начислять нельзя")

    monkeypatch.setattr(bot_module.db, "record_catch", boom)
    monkeypatch.setattr(bot_module.db, "add_coins", boom)

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert "через" in text


def test_замороженный_счёт_не_рыбачит(monkeypatch):
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(True))
    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert "аморожен" in text


# ---------------------------------------------------------------------------
# Клад
# ---------------------------------------------------------------------------

def test_промах_растит_клад_и_не_платит(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_digger", _returns({"last_dig_at": None, "finds": 0}))
    monkeypatch.setattr(bot_module.db, "get_treasure",
                        _returns({"pot": 1000, "attempts": 0, "started_at": datetime.utcnow()}))
    monkeypatch.setattr(bot_module.random, "random", lambda: 1.0)  # гарантированный промах

    grown = {}

    async def grow(chat_id, amount):
        grown["amount"] = amount

    async def boom(*a, **k):
        raise AssertionError("промах не должен ничего начислять")

    monkeypatch.setattr(bot_module.db, "grow_treasure", grow)
    monkeypatch.setattr(bot_module.db, "record_dig", _noop)
    monkeypatch.setattr(bot_module.db, "add_coins", boom)
    monkeypatch.setattr(bot_module.db, "claim_treasure", boom)

    text = asyncio.run(bot_module._treasure_execute(CHAT_ID, USER_ID))
    assert bot_module.TREASURE_GROWTH_MIN <= grown["amount"] <= bot_module.TREASURE_GROWTH_MAX
    assert "подрос" in text


def test_находка_отдаёт_весь_банк(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_digger", _returns({"last_dig_at": None, "finds": 2}))
    monkeypatch.setattr(bot_module.db, "get_treasure",
                        _returns({"pot": 4321, "attempts": 9, "started_at": datetime.utcnow()}))
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)  # гарантированная находка

    paid = {}

    async def add_coins(chat_id, user_id, amount):
        paid["amount"] = amount
        return amount

    monkeypatch.setattr(bot_module.db, "claim_treasure", _returns(4321))
    monkeypatch.setattr(bot_module.db, "record_dig", _noop)
    monkeypatch.setattr(bot_module.db, "add_coins", add_coins)

    text = asyncio.run(bot_module._treasure_execute(CHAT_ID, USER_ID))
    assert paid["amount"] == 4321
    assert "КЛАД НАЙДЕН" in text


def test_клад_перехваченный_другим_не_платит_дважды(monkeypatch):
    """claim_treasure вернул None — банк уже забрали. Платить нечего."""
    monkeypatch.setattr(bot_module.db, "get_digger", _returns({"last_dig_at": None, "finds": 0}))
    monkeypatch.setattr(bot_module.db, "get_treasure",
                        _returns({"pot": 500, "attempts": 3, "started_at": datetime.utcnow()}))
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)

    async def boom(*a, **k):
        raise AssertionError("монеты за чужой клад начислять нельзя")

    monkeypatch.setattr(bot_module.db, "claim_treasure", _returns(None))
    monkeypatch.setattr(bot_module.db, "record_dig", _noop)
    monkeypatch.setattr(bot_module.db, "add_coins", boom)

    text = asyncio.run(bot_module._treasure_execute(CHAT_ID, USER_ID))
    assert "успели забрать" in text


def test_шанс_находки_растёт_но_не_превышает_потолок():
    base = bot_module.TREASURE_CHANCE_BASE
    step = bot_module.TREASURE_CHANCE_STEP
    cap = bot_module.TREASURE_CHANCE_MAX
    assert min(base + 0 * step, cap) == base
    assert min(base + 5 * step, cap) > base
    assert min(base + 1000 * step, cap) == cap


# ---------------------------------------------------------------------------
# Очистка команд: защита от протухшего контекста
# ---------------------------------------------------------------------------

def test_очистка_игнорирует_протухший_срок(monkeypatch):
    """Ключевая защита: задача, созданная внутри обработчика (таймер), уносит
    с собой копию контекста. Через несколько часов её сообщение приходило бы
    сюда со сроком удаления из ПРОШЛОГО и исчезало через минуту после
    появления."""
    queued = []
    monkeypatch.setattr(bot_module, "_queue_cleanup",
                        lambda chat_id, message_id, delete_at: queued.append(message_id))

    class FakeResult:
        message_id = 77

    class FakeMethod:
        chat_id = CHAT_ID

    async def make_request(bot_obj, method):
        return FakeResult()

    async def run(delete_at):
        token = bot_module._cleanup_context.set((CHAT_ID, delete_at))
        try:
            await bot_module.cleanup_tracking_middleware(make_request, None, FakeMethod())
        finally:
            bot_module._cleanup_context.reset(token)

    # срок в прошлом — контекст чужой, в очередь ничего не идёт
    asyncio.run(run(datetime.utcnow() - timedelta(hours=3)))
    assert queued == []

    # обычный свежий срок — сообщение бота ставится в очередь как раньше
    asyncio.run(run(datetime.utcnow() + timedelta(minutes=15)))
    assert queued == [77]


def test_потолок_очистки_не_даёт_задать_больше_48_часов():
    """Telegram не удаляет сообщения старше 48 часов — значение выше просто
    перестало бы работать, молча."""
    assert bot_module.CMD_CLEANUP_MAX_MINUTES == 48 * 60


def test_чтение_настройки_подрезает_старое_значение(monkeypatch):
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "999999")
    assert bot_module.cmd_cleanup_minutes() == bot_module.CMD_CLEANUP_MAX_MINUTES
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "мусор")
    assert bot_module.cmd_cleanup_minutes() == bot_module.DEFAULT_CMD_CLEANUP_MINUTES
