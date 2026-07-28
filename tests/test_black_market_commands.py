"""Лавка в боте: ротация раз в сутки и переживание простоя.

Главное, что здесь проверяется, — идемпотентность: ротацию дёргают из двух
мест (чтение лавки и суточный цикл), и второй вызов в тот же день обязан
ничего не менять. Иначе ассортимент переставлялся бы под человеком прямо
между «лавка» и «лавка купить».
"""

from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import black_market as BM  # noqa: E402
import bot as bot_module  # noqa: E402
import robbery  # noqa: E402

CHAT_ID = -1001234567890
TODAY = date(2026, 7, 28)


def _fake_db(monkeypatch, *, day=None):
    """Минимальная подмена БД: запоминает выставленный ассортимент."""
    state = {"day": day, "stock": {}, "cleared": 0, "seeded": 0}

    async def get_rotation_day(chat_id, keys):
        return state["day"]

    async def clear_rotation_stock(chat_id, keys):
        state["cleared"] += 1
        state["stock"] = {}

    async def set_shop_item_rotation(chat_id, item_key, stock, rotation_day):
        state["stock"][item_key] = stock
        state["day"] = rotation_day
        return True

    async def seed_extra_shop_items(chat_id, items, is_active=True):
        state["seeded"] += 1
        return 0

    monkeypatch.setattr(bot_module.db, "get_rotation_day", get_rotation_day)
    monkeypatch.setattr(bot_module.db, "clear_rotation_stock", clear_rotation_stock)
    monkeypatch.setattr(bot_module.db, "set_shop_item_rotation", set_shop_item_rotation)
    monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", seed_extra_shop_items)
    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)
    return state


def test_rotation_fills_assortment_when_never_rotated(monkeypatch):
    state = _fake_db(monkeypatch, day=None)

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is True
    assert 3 <= len(state["stock"]) <= 4
    assert set(state["stock"]) <= BM.POOL_KEYS
    assert state["day"] == TODAY


def test_rotation_is_idempotent_within_a_day(monkeypatch):
    state = _fake_db(monkeypatch, day=TODAY)

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is False
    assert state["cleared"] == 0
    assert state["stock"] == {}


def test_rotation_catches_up_after_downtime(monkeypatch):
    """Бот лежал сутки — ассортимент обновляется при первом же обращении."""
    state = _fake_db(monkeypatch, day=date(2026, 7, 26))

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is True
    assert state["cleared"] == 1
    assert state["day"] == TODAY


def test_rotation_seeds_rows_before_choosing(monkeypatch):
    """В чате, где магазин не открывали, выбирать было бы не из чего."""
    state = _fake_db(monkeypatch, day=None)

    asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert state["seeded"] >= 1


def test_two_simultaneous_rotations_do_not_reroll(monkeypatch):
    """Две «лавки» разом не должны разыграть ассортимент дважды.

    Без замка обе увидели бы «сегодня ещё не крутили» и обе перевыставили
    бы запас — второй прогон затёр бы то, что первый уже начал продавать.
    """
    state = _fake_db(monkeypatch, day=None)

    async def both():
        return await asyncio.gather(
            bot_module.ensure_black_market_rotation(CHAT_ID),
            bot_module.ensure_black_market_rotation(CHAT_ID),
        )

    results = asyncio.run(both())

    assert sorted(results) == [False, True]
    assert state["cleared"] == 1


# --- гейт покупки ---------------------------------------------------------
#
# SHOP_BUY_RE ловит и голое «купить {ключ}», без слова «магазин». Спрячь
# товары лавки только из витрины — и любой, кто знает ключ, купит их в обход
# ротации, в любой день. Поэтому гейт стоит внутри самой покупки.

class _Reply:
    """Сообщение-заглушка: копит ответы бота, ничего не отправляя."""

    def __init__(self, text, user_id=777):
        self.text = text
        self.replies = []
        self.chat = type("Chat", (), {"id": CHAT_ID, "type": "supergroup"})()
        self.from_user = type("User", (), {"id": user_id, "is_bot": False,
                                           "full_name": "Тест", "username": "test"})()
        self.reply_to_message = None

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return self

    async def answer(self, text, **kwargs):
        self.replies.append(text)
        return self


def _shop_item(key, stock=3, rotation_day=None):
    return {
        "item_key": key, "name": key, "description": "", "emoji": "🎁",
        "price": 100, "is_active": True, "stock": stock,
        "rotation_day": rotation_day,
    }


def _only_catalog(monkeypatch, item):
    """Покупка не должна дойти до денег и инвентаря — только до гейта."""
    async def get_shop_item(chat_id, key):
        return item

    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)
    monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item)


def test_pool_item_cannot_be_bought_through_the_shop(monkeypatch):
    """Голое «купить binokl» не должно обходить лавку."""
    _only_catalog(monkeypatch, _shop_item("binokl", rotation_day=TODAY))
    message = _Reply("купить binokl")

    bought = asyncio.run(bot_module._shop_buy(message, "binokl", 1))

    assert bought is False
    assert any("лавка" in r for r in message.replies), message.replies


def test_shop_item_cannot_be_bought_through_the_black_market(monkeypatch):
    _only_catalog(monkeypatch, _shop_item("pechenka"))
    message = _Reply("лавка купить pechenka")

    bought = asyncio.run(
        bot_module._shop_buy(message, "pechenka", 1, from_black_market=True)
    )

    assert bought is False
    assert any("магазин" in r for r in message.replies), message.replies


def test_pool_item_out_of_rotation_is_not_for_sale(monkeypatch):
    """Позиция вне сегодняшнего ассортимента не продаётся даже в лавке."""
    _only_catalog(monkeypatch, _shop_item("binokl", stock=0,
                                          rotation_day=date(2026, 7, 26)))
    message = _Reply("лавка купить binokl")

    bought = asyncio.run(
        bot_module._shop_buy(message, "binokl", 1, from_black_market=True)
    )

    assert bought is False
    assert any("не завозили" in r for r in message.replies), message.replies


def test_shop_window_hides_pool_items(monkeypatch):
    """Витрина «магазин» не должна перечислять то, что продаётся в лавке."""
    async def seed(chat_id, items, is_active=True):
        return 0

    async def list_shop_items(chat_id, active_only=True):
        return [_shop_item("binokl"), _shop_item("pechenka")]

    monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", seed)
    monkeypatch.setattr(bot_module.db, "list_shop_items", list_shop_items)

    text, _ = asyncio.run(bot_module.shop_list_page(CHAT_ID, 0))

    assert "pechenka" in text
    assert "binokl" not in text


def test_quantity_cap_covers_the_whole_pool(monkeypatch):
    """Потолок в 3 шт. обязан накрывать и медвежатника тоже.

    Раньше он проверялся только для robbery.ROBBERY_ITEMS, а медвежатника и
    новинок лавки там нет — без правки они копились бы за много дней, и
    дефицит кончился бы на второй неделе.
    """
    assert "medvezhatnik" not in robbery.ROBBERY_ITEMS      # иначе тест пустой

    async def list_inventory(chat_id, user_id):
        return [{"item_key": "medvezhatnik",
                 "quantity": robbery.ROBBERY_ITEM_MAX_QUANTITY}]

    _only_catalog(monkeypatch, _shop_item("medvezhatnik", rotation_day=TODAY))
    monkeypatch.setattr(bot_module.db, "list_inventory", list_inventory)
    message = _Reply("лавка купить medvezhatnik")

    bought = asyncio.run(
        bot_module._shop_buy(message, "medvezhatnik", 1, from_black_market=True)
    )

    assert bought is False
    assert any("не больше" in r for r in message.replies), message.replies


def test_black_market_commands_are_registered():
    registry = bot_module.COMMAND_REGISTRY
    assert "лавка" in registry["black_market"]["phrase"]
    assert "лавка купить" in registry["black_market_buy"]["phrase"]


def test_buy_trigger_does_not_swallow_the_listing_command():
    """«лавка» и «лавка купить …» — разные команды, а не одна с хвостом."""
    assert bot_module.BLACK_MARKET_BUY_RE.match("лавка купить binokl")
    assert not bot_module.BLACK_MARKET_BUY_RE.match("лавка")
    assert "лавка" in bot_module.BLACK_MARKET_TRIGGERS


def test_shop_buy_regex_still_ignores_the_black_market_phrase():
    """«лавка купить X» не должно попасть заодно и в обычную покупку."""
    assert not bot_module.SHOP_BUY_RE.match("лавка купить binokl")


# --- сигнализация и слепок ключа ------------------------------------------

VICTIM_ID = 888


class _Кража:
    """Обвязка для настоящего вызова cmd_steal_item.

    Подменяем ровно то, что команда трогает снаружи: инвентари, списания,
    журнал и отправку. Проверять сигнализацию на заглушках нельзя — тест
    сошёлся бы сам с собой, ничего не сказав о самой команде.
    """

    def __init__(self, monkeypatch, *, у_жертвы, у_вора=("medvezhatnik",)):
        self.снято: list[tuple[int, str]] = []
        self.выдано: list[tuple[int, str]] = []
        self.отметки: list[float] = []
        self.журнал: list[str] = []
        self.в_чат: list[str] = []
        self.в_личку: list[str] = []
        self.инвентари = {
            777: [{"item_key": k, "quantity": 1} for k in у_вора],
            VICTIM_ID: [{"item_key": k, "quantity": 1} for k in у_жертвы],
        }

        async def list_inventory(chat_id, user_id):
            return self.инвентари.get(user_id, [])

        async def remove_inventory_item(chat_id, user_id, key, qty=1):
            self.снято.append((user_id, key))
            self.инвентари[user_id] = [
                i for i in self.инвентари.get(user_id, []) if i["item_key"] != key
            ]
            return True

        async def add_inventory_item(chat_id, user_id, key, qty=1):
            self.выдано.append((user_id, key))

        async def add_log(*args, **kwargs):
            self.журнал.append(args[0] if args else "")

        async def get_shop_item(chat_id, key):
            return _shop_item(key)

        async def mark_used(chat_id, user_id, cut=0.0):
            self.отметки.append(cut)

        async def cooldown_left(chat_id, user_id):
            return None

        async def event_flag(chat_id, flag):
            return False

        async def display_name(chat_id, user):
            return "Кто-то"

        async def dm(user_id, text, **kwargs):
            self.в_личку.append(text)

        async def resolve_command_target(message, trigger_words=1):
            цель = type("User", (), {"id": VICTIM_ID, "is_bot": False,
                                     "full_name": "Жертва", "username": "victim"})()
            return цель, message.text

        monkeypatch.setattr(bot_module.db, "list_inventory", list_inventory)
        monkeypatch.setattr(bot_module.db, "remove_inventory_item", remove_inventory_item)
        monkeypatch.setattr(bot_module.db, "add_inventory_item", add_inventory_item)
        monkeypatch.setattr(bot_module.db, "add_log", add_log)
        monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item)
        monkeypatch.setattr(bot_module, "_steal_mark_used", mark_used)
        monkeypatch.setattr(bot_module, "_steal_cooldown_left", cooldown_left)
        monkeypatch.setattr(bot_module, "event_flag", event_flag)
        monkeypatch.setattr(bot_module, "display_name", display_name)
        monkeypatch.setattr(bot_module, "_dm_or_none", dm)
        monkeypatch.setattr(bot_module, "resolve_command_target", resolve_command_target)
        monkeypatch.setattr(bot_module, "_check_misc_access", lambda uid, key: True)


def test_signalizaciya_blocks_the_theft_but_burns_the_burglar_tool(monkeypatch):
    """Сигнализация гасит кражу, но медвежатник вор всё равно теряет.

    Иначе жать медвежатником по чужим закромам стало бы бесплатной проверкой
    «а есть ли у него сигнализация», и защита выдавала бы сама себя.
    """
    мир = _Кража(monkeypatch, у_жертвы=("diamond", BM.SIGNAL_KEY))
    message = _Reply("медвежатник diamond")

    asyncio.run(bot_module.cmd_steal_item(message))

    assert (777, "medvezhatnik") in мир.снято
    assert (VICTIM_ID, BM.SIGNAL_KEY) in мир.снято
    assert (VICTIM_ID, "diamond") not in мир.снято      # вещь осталась у жертвы
    assert мир.выдано == []                             # и вору не досталась
    assert мир.отметки == [0.0]                         # кулдаун — обычный


def test_theft_without_signalizaciya_still_works(monkeypatch):
    """Контроль: без сигнализации кража проходит как раньше."""
    мир = _Кража(monkeypatch, у_жертвы=("diamond",))
    message = _Reply("медвежатник diamond")

    asyncio.run(bot_module.cmd_steal_item(message))

    assert (VICTIM_ID, "diamond") in мир.снято
    assert (777, "diamond") in мир.выдано


def test_slepok_is_spent_only_after_a_successful_theft(monkeypatch):
    """Слепок сокращает откат и тратится — но лишь когда вещь реально взяли."""
    мир = _Кража(monkeypatch, у_жертвы=("diamond",),
                 у_вора=("medvezhatnik", BM.SLEPOK_KEY))
    message = _Reply("медвежатник diamond")

    asyncio.run(bot_module.cmd_steal_item(message))

    assert (777, BM.SLEPOK_KEY) in мир.снято
    assert мир.отметки == [0.0, BM.STEAL_COOLDOWN_CUT]


def test_slepok_survives_a_blocked_theft(monkeypatch):
    """Сигнализация сорвала кражу — слепок обязан остаться у вора.

    Отметка кулдауна ставится до того, как исход известен; сожги слепок
    вместе с ней — и он сгорал бы за кражу, которой не было.
    """
    мир = _Кража(monkeypatch, у_жертвы=("diamond", BM.SIGNAL_KEY),
                 у_вора=("medvezhatnik", BM.SLEPOK_KEY))
    message = _Reply("медвежатник diamond")

    asyncio.run(bot_module.cmd_steal_item(message))

    assert (777, BM.SLEPOK_KEY) not in мир.снято
    assert мир.отметки == [0.0]


def test_steal_mark_shifts_the_stamp_back_by_a_quarter(monkeypatch):
    """Слепок сдвигает отметку назад на четверть кулдауна: 10 ч → 7,5 ч."""
    from datetime import datetime, timedelta

    saved = {}

    async def set_data(key, value, updated_by=None):
        saved[key] = value

    monkeypatch.setattr(bot_module.db, "set_data", set_data)

    before = datetime.utcnow()
    asyncio.run(bot_module._steal_mark_used(CHAT_ID, 777, cut=BM.STEAL_COOLDOWN_CUT))
    stamp = datetime.fromisoformat(list(saved.values())[0])

    shift = before - stamp
    assert abs(shift - bot_module.STEAL_COOLDOWN * BM.STEAL_COOLDOWN_CUT) < timedelta(seconds=5)
    assert abs((bot_module.STEAL_COOLDOWN - shift) - timedelta(hours=7.5)) < timedelta(seconds=5)


def test_steal_mark_without_slepok_is_unchanged(monkeypatch):
    """Без слепка отметка пишется текущим временем — полные 10 часов."""
    from datetime import datetime, timedelta

    saved = {}

    async def set_data(key, value, updated_by=None):
        saved[key] = value

    monkeypatch.setattr(bot_module.db, "set_data", set_data)

    before = datetime.utcnow()
    asyncio.run(bot_module._steal_mark_used(CHAT_ID, 777))
    stamp = datetime.fromisoformat(list(saved.values())[0])

    assert abs(before - stamp) < timedelta(seconds=5)
