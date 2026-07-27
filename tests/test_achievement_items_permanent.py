"""Предмет, который выдаётся один раз, нельзя потерять НИКАК.

Правило: всё из shop_effects.REWARD_KEYS (предметы за ачивки + медали) не
продаётся, не дарится, не крадётся и не расходуется применениями. Вернуть
такой предмет нельзя — ачивка выдаётся однократно, — поэтому любая дыра
здесь необратима для того, кто в неё попал.

Тесты написаны ПЕРЕЧИСЛЕНИЕМ путей, а не по одному случаю на баг, и это
主 суть файла. Запрет держится не на одной проверке, а на повторённом в
шести местах `if is_reward(...)`, и ровно так его дважды и забыли:

  * кнопка «💰 Продать» в инвентаре (sell_item_cb) продавала предмет за
    ачивку по витринной цене 999 999 999 i¢ — то есть за 799 999 999 i¢;
  * десятое применение «использовать {ключ} @кому» сносило предмет
    из инвентаря насовсем.

Добавляете седьмой путь, где предмет уходит из инвентаря, — добавляйте
и случай в LOSS_PATHS, иначе он повторит ту же историю.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555
OTHER_ID = 777

# Все неотчуждаемые ключи: и предметы за ачивки, и старые медали.
PERMANENT_KEYS = sorted(SE.REWARD_KEYS)
# Обычный расходник для контрольных проверок — он теряться ДОЛЖЕН.
SPENDABLE_KEY = "energetik"


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


def _spec_of(key: str):
    return SE.ACHIEVEMENT_BY_KEY.get(key) or SE.REWARD_BY_KEY.get(key) or SE.BY_KEY[key]


def _shop_row(key: str) -> dict:
    spec = _spec_of(key)
    price = getattr(spec, "price", 999_999_999)
    return {
        "item_key": key, "name": spec.name, "emoji": spec.emoji, "price": price,
        "description": spec.description, "is_active": True, "stock": None,
    }


def _inventory_of(key: str) -> list[dict]:
    spec = _spec_of(key)
    return [{
        "item_key": key, "quantity": 1, "name": spec.name, "emoji": spec.emoji,
        "description": spec.description, "acquired_at": datetime.now(),
    }]


class _Ledger:
    """Записывает всё, что могло бы отнять предмет или начислить монеты."""

    def __init__(self) -> None:
        self.removed: list[str] = []
        self.coins: list[int] = []
        self.replies: list[str] = []

    def install(self, monkeypatch, key: str) -> None:
        async def remove_item(chat_id, user_id, item_key, amount=1):
            self.removed.append(item_key)
            return True

        async def remove_completely(chat_id, user_id, item_key):
            self.removed.append(item_key)
            return True

        async def add_coins(chat_id, user_id, amount, *a, **k):
            self.coins.append(amount)

        db = bot_module.db
        monkeypatch.setattr(db, "remove_inventory_item", remove_item)
        monkeypatch.setattr(db, "remove_inventory_item_completely", remove_completely)
        monkeypatch.setattr(db, "add_coins", add_coins)
        monkeypatch.setattr(db, "add_inventory_item", _noop)
        monkeypatch.setattr(db, "list_inventory", _returns(_inventory_of(key)))
        monkeypatch.setattr(db, "get_shop_item", _returns(_shop_row(key)))
        monkeypatch.setattr(db, "get_item_usage_count", _returns(0))
        monkeypatch.setattr(db, "increment_item_usage", _returns(1))
        monkeypatch.setattr(db, "reset_item_usage", _noop)
        monkeypatch.setattr(db, "get_profile_card", _returns(None))
        monkeypatch.setattr(db, "set_pinned_item", _noop)
        monkeypatch.setattr(db, "add_log", _noop)
        monkeypatch.setattr(db, "get_nickname", _returns(None))


def _message(text: str, ledger: _Ledger):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )

    async def collect(t, **k):
        ledger.replies.append(t)

    object.__setattr__(m, "reply", collect)
    object.__setattr__(m, "answer", collect)
    return m


# ---------------------------------------------------------------------------
# Пути, по которым предмет может уйти из инвентаря.
# ---------------------------------------------------------------------------

async def _path_sell_text(key: str, ledger: _Ledger) -> None:
    """«магазин продать {ключ}»"""
    await bot_module.cmd_sell_item(_message(f"магазин продать {key}", ledger))


async def _path_sell_button(key: str, ledger: _Ledger) -> None:
    """Кнопка «💰 Продать» в инвентаре."""
    from aiogram.types import CallbackQuery, Chat, Message, User
    msg = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text="инвентарь",
    )
    object.__setattr__(msg, "edit_text", _noop)
    cb = CallbackQuery(
        id="1", from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"),
        chat_instance="x", message=msg,
        data=f"sellitem:{key}:{USER_ID}:{USER_ID}",
    )

    async def answer(text=None, **k):
        ledger.replies.append(text or "")

    object.__setattr__(cb, "answer", answer)
    await bot_module.sell_item_cb(cb)


async def _path_use_limit(key: str, ledger: _Ledger) -> None:
    """«использовать {ключ} @кому» ITEM_USE_LIMIT раз подряд."""
    counter = {"n": 0}

    async def increment(chat_id, user_id, item_key):
        counter["n"] += 1
        return counter["n"]

    bot_module.db.increment_item_usage = increment

    async def resolve(*a, **k):
        from aiogram.types import User
        return User(id=OTHER_ID, is_bot=False, first_name="Цель"), ""

    original_resolve = bot_module.resolve_command_target
    original_display = bot_module.display_name
    original_display_id = bot_module.display_name_by_id
    bot_module.resolve_command_target = resolve
    bot_module.display_name = _returns("кто-то")
    bot_module.display_name_by_id = _returns("кто-то")
    try:
        for _ in range(bot_module.db.ITEM_USE_LIMIT + 2):
            await bot_module.cmd_item_use(
                _message(f"использовать {key} @target", ledger)
            )
    finally:
        bot_module.resolve_command_target = original_resolve
        bot_module.display_name = original_display
        bot_module.display_name_by_id = original_display_id


LOSS_PATHS = {
    "магазин продать": _path_sell_text,
    "кнопка Продать": _path_sell_button,
    "лимит применений": _path_use_limit,
}


@pytest.mark.parametrize("key", PERMANENT_KEYS)
@pytest.mark.parametrize("path_name", sorted(LOSS_PATHS))
def test_неотчуждаемый_предмет_не_теряется(key, path_name, monkeypatch):
    ledger = _Ledger()
    ledger.install(monkeypatch, key)
    asyncio.run(LOSS_PATHS[path_name](key, ledger))

    assert key not in ledger.removed, (
        f"путь «{path_name}» отнял «{key}» — предмет за достижение выдают "
        f"один раз, вернуть его нельзя"
    )
    assert not ledger.coins, (
        f"путь «{path_name}» начислил {ledger.coins} i¢ за «{key}» — "
        f"витринная цена такого предмета 999 999 999"
    )


@pytest.mark.parametrize("key", PERMANENT_KEYS)
def test_кнопка_продать_не_рисуется(key, monkeypatch):
    """Предлагать действие, которое запрещено, — тоже баг."""
    ledger = _Ledger()
    ledger.install(monkeypatch, key)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Тестер"))

    _text, keyboard = asyncio.run(
        bot_module._inventory_view(CHAT_ID, USER_ID, USER_ID, USER_ID)
    )
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert not [b for b in buttons if (b.callback_data or "").startswith("sellitem:")], (
        f"у «{key}» нарисована кнопка продажи"
    )


@pytest.mark.parametrize("key", PERMANENT_KEYS)
def test_инвентарь_не_обещает_лимит_применений(key, monkeypatch):
    ledger = _Ledger()
    ledger.install(monkeypatch, key)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Тестер"))

    text, _kb = asyncio.run(
        bot_module._inventory_view(CHAT_ID, USER_ID, USER_ID, USER_ID)
    )
    assert "осталось использований" not in text, (
        f"«{key}» не расходуется — счётчик применений вводит в заблуждение"
    )
    assert "навсегда" in text


# --- контроль: обычный расходник теряться ДОЛЖЕН --------------------------

def test_обычный_предмет_по_прежнему_продаётся(monkeypatch):
    """Иначе «починка» могла бы просто запретить продажу вообще всему."""
    ledger = _Ledger()
    ledger.install(monkeypatch, SPENDABLE_KEY)
    asyncio.run(_path_sell_text(SPENDABLE_KEY, ledger))

    assert SPENDABLE_KEY in ledger.removed
    assert ledger.coins == [int(SE.BY_KEY[SPENDABLE_KEY].price * 0.8)]


def test_список_неотчуждаемых_не_пуст():
    """Страховка от опечатки, которая обнулила бы весь файл разом."""
    assert len(PERMANENT_KEYS) >= len(SE.ACHIEVEMENT_ITEMS)
    assert "traktor" in PERMANENT_KEYS
    assert SPENDABLE_KEY not in PERMANENT_KEYS
