"""Предметы, которые создают событие на весь чат.

Отличаются от прежних восьми тем, что их видит не только владелец: ва-банк
и щедрость объявляются в чат, зеркало разворачивает чужое ограбление,
саботаж ломает чужой бизнес, компромат публикует старую фразу.

Главное, что здесь проверяется, — правило из shop_effects: предмет уходит
ТОЛЬКО если эффект реально сработал. Ломается оно молча и обиднее всего:
человек жмёт предмет за 30 000 i¢, ничего не происходит, предмета нет.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime

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

NEW_KEYS = ["zerkalo", "bilet", "vabank", "shchedrost",
            "sabotazh", "kompromat", "dosye", "megafon"]


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


class _Spy:
    """Следит за тем, что предмет ушёл (или остался) и что сказано в чат."""

    def __init__(self) -> None:
        self.removed: list[str] = []
        self.said: list[str] = []
        self.coins: list[tuple[int, int]] = []

    def install(self, monkeypatch, inventory_keys):
        async def remove_item(chat_id, user_id, item_key, amount=1):
            self.removed.append(item_key)
            return True

        async def add_coins(chat_id, user_id, amount, *a, **k):
            self.coins.append((user_id, amount))

        db = bot_module.db
        monkeypatch.setattr(db, "remove_inventory_item", remove_item)
        monkeypatch.setattr(db, "add_coins", add_coins)
        monkeypatch.setattr(db, "add_log", _noop)
        monkeypatch.setattr(db, "list_inventory", _returns(
            [{"item_key": k, "quantity": 1, "name": k, "emoji": "🎁"} for k in inventory_keys]
        ))
        monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"))
        monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Сосед"))

    def message(self, text: str):
        from aiogram.types import Chat, Message, User
        m = Message(
            message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
        )

        async def collect(t, **k):
            self.said.append(t)

        object.__setattr__(m, "reply", collect)
        object.__setattr__(m, "answer", collect)
        return m


# --- каталог ----------------------------------------------------------------

@pytest.mark.parametrize("key", NEW_KEYS)
def test_новый_предмет_есть_в_каталоге(key):
    assert key in SE.BY_KEY, f"«{key}» не доедет до магазина"


@pytest.mark.parametrize("key", NEW_KEYS)
def test_новый_предмет_продаётся_а_не_награда(key):
    """Иначе он попал бы под запрет отчуждения и его нельзя было бы купить."""
    assert not SE.is_reward(key)
    assert SE.BY_KEY[key].price > 0


def test_предметы_со_своей_командой_помечены():
    """По этому множеству «использовать» отличает их от обычных."""
    for key in ("sabotazh", "kompromat", "dosye", "megafon"):
        assert SE.BY_KEY[key].effect in SE.OWN_COMMAND_EFFECTS


def test_зеркало_отложенный_эффект():
    assert SE.EFFECT_MIRROR in SE.PENDING_EFFECTS


# --- зеркало ----------------------------------------------------------------
# Срабатывание зеркала живёт внутри cmd_robbery, а на этот обработчик в
# проекте тестового каркаса нет (слишком много состояния: кулдауны, надзор,
# события чата, питомцы). Поэтому здесь проверяется активация заряда —
# половина, которую можно проверить, не выдумывая половину бота.

def test_зеркало_вешает_заряд(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["zerkalo"])
    charged = {}

    async def add_effect(chat_id, user_id, effect, charges=1):
        charged["effect"] = effect

    monkeypatch.setattr(bot_module.db, "add_item_effect", add_effect)

    asyncio.run(bot_module._use_effect_item(spy.message("использовать zerkalo"), "zerkalo"))
    assert spy.removed == ["zerkalo"]
    assert charged.get("effect") == SE.EFFECT_MIRROR
    assert "Зеркало" in " ".join(spy.said)


# --- ва-банк ----------------------------------------------------------------

def test_вабанк_с_пустым_кошельком_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["vabank"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 10}))

    asyncio.run(bot_module._use_effect_item(spy.message("использовать vabank"), "vabank"))
    assert not spy.removed, "предмет сгорел, хотя ставку сделать было нельзя"
    assert "нужно хотя бы" in " ".join(spy.said)


def test_вабанк_выигрыш_удваивает(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["vabank"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 5_000}))
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.0)   # орёл

    asyncio.run(bot_module._use_effect_item(spy.message("использовать vabank"), "vabank"))
    assert spy.removed == ["vabank"]
    assert (USER_ID, 5_000) in spy.coins
    assert "ОРЁЛ" in " ".join(spy.said)


def test_вабанк_проигрыш_забирает_треть(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["vabank"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 6_000}))
    monkeypatch.setattr(bot_module.random, "random", lambda: 0.99)  # решка

    asyncio.run(bot_module._use_effect_item(spy.message("использовать vabank"), "vabank"))
    assert spy.removed == ["vabank"]
    assert (USER_ID, -2_000) in spy.coins
    assert "РЕШКА" in " ".join(spy.said)


def test_вабанк_не_печатает_деньги():
    """Проверять надо ожидание, а не «шанс меньше половины».

    Выигрыш даёт +100% кошелька, проигрыш забирает только треть — поэтому
    «45% < 50%» выглядело безопасно, а на деле давало +26.7% за применение,
    и тем больше в абсолюте, чем толще кошелёк. Ровно так экономику этого
    бота уже раздувала биржа (см. комментарий у stock_settings в db.py).
    """
    ev = (bot_module.VABANK_WIN_CHANCE * 1.0
          - (1 - bot_module.VABANK_WIN_CHANCE) * bot_module.VABANK_LOSS_SHARE)
    assert ev < 0, f"ва-банк выгоден в среднем: EV = {ev:+.1%} кошелька за применение"


# --- щедрость ---------------------------------------------------------------

def test_щедрость_без_получателей_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["shchedrost"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 100_000}))
    monkeypatch.setattr(bot_module.db, "list_today_active_users", _returns([]))
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))

    asyncio.run(bot_module._use_effect_item(
        spy.message("использовать shchedrost"), "shchedrost"))
    assert not spy.removed
    assert "дарить некому" in " ".join(spy.said)


def test_щедрость_делит_сумму_на_всех(monkeypatch):
    """Сумма фиксированная и делится — иначе большой чат печатал бы монеты."""
    spy = _Spy()
    spy.install(monkeypatch, ["shchedrost"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 100_000}))
    monkeypatch.setattr(bot_module.db, "list_today_active_users", _returns(
        [{"user_id": uid, "message_count": 5} for uid in (101, 102, 103)]
    ))
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))

    asyncio.run(bot_module._use_effect_item(
        spy.message("использовать shchedrost"), "shchedrost"))

    assert spy.removed == ["shchedrost"]
    paid_out = [c for c in spy.coins if c[1] > 0]
    assert len(paid_out) == 3
    assert sum(c[1] for c in paid_out) <= bot_module.GENEROSITY_COST
    assert (USER_ID, -bot_module.GENEROSITY_COST) in spy.coins


def test_щедрость_себе_не_платит(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["shchedrost"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 100_000}))
    monkeypatch.setattr(bot_module.db, "list_today_active_users", _returns(
        [{"user_id": USER_ID, "message_count": 9}, {"user_id": 101, "message_count": 5}]
    ))
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))

    asyncio.run(bot_module._use_effect_item(
        spy.message("использовать shchedrost"), "shchedrost"))
    assert [c for c in spy.coins if c[1] > 0] == [(101, bot_module.GENEROSITY_COST)]


def test_щедрость_без_денег_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["shchedrost"])
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 5}))

    asyncio.run(bot_module._use_effect_item(
        spy.message("использовать shchedrost"), "shchedrost"))
    assert not spy.removed


# --- билет на ивент ---------------------------------------------------------

def test_билет_не_тратится_когда_событие_уже_идёт(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["bilet"])
    monkeypatch.setattr(bot_module, "events_enabled", _returns(True))
    monkeypatch.setattr(bot_module, "get_active_event", _returns({"key": "gold_rush"}))

    asyncio.run(bot_module._use_effect_item(spy.message("использовать bilet"), "bilet"))
    assert not spy.removed
    assert "уже идёт событие" in " ".join(spy.said)


def test_билет_не_тратится_при_выключенных_событиях(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["bilet"])
    monkeypatch.setattr(bot_module, "events_enabled", _returns(False))

    asyncio.run(bot_module._use_effect_item(spy.message("использовать bilet"), "bilet"))
    assert not spy.removed


def test_билет_запускает_событие(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["bilet"])
    monkeypatch.setattr(bot_module, "events_enabled", _returns(True))
    monkeypatch.setattr(bot_module, "get_active_event", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_data", _returns(None))
    fired = {}

    async def fire(chat_id, event, minutes=None):
        fired["key"] = event.key
        return True

    monkeypatch.setattr(bot_module, "fire_chat_event", fire)

    asyncio.run(bot_module._use_effect_item(spy.message("использовать bilet"), "bilet"))
    assert spy.removed == ["bilet"]
    assert fired.get("key")


def test_билет_не_тратится_если_событие_не_завелось(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["bilet"])
    monkeypatch.setattr(bot_module, "events_enabled", _returns(True))
    monkeypatch.setattr(bot_module, "get_active_event", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_data", _returns(None))
    monkeypatch.setattr(bot_module, "fire_chat_event", _returns(False))

    asyncio.run(bot_module._use_effect_item(spy.message("использовать bilet"), "bilet"))
    assert not spy.removed


# --- саботаж ----------------------------------------------------------------

def _target_user():
    from aiogram.types import User
    return User(id=OTHER_ID, is_bot=False, first_name="Сосед")


def test_саботаж_без_целей_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["sabotazh"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((_target_user(), "")))
    monkeypatch.setattr(bot_module.db, "list_user_businesses", _returns([]))

    asyncio.run(bot_module.cmd_sabotage(spy.message("саботаж @kto")))
    assert not spy.removed
    assert "нечего ломать" in " ".join(spy.said)


def test_саботаж_гасится_страховкой(monkeypatch):
    """Предмет против предмета: страховка тратится, бизнес цел."""
    spy = _Spy()
    spy.install(monkeypatch, ["sabotazh"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((_target_user(), "")))
    monkeypatch.setattr(bot_module.db, "list_user_businesses",
                        _returns([{"business_key": "shaurma", "broken_kind": None}]))
    monkeypatch.setattr(bot_module.db, "consume_item_effect", _returns(True))
    broke = {}

    async def brk(chat_id, row):
        broke["hit"] = True

    monkeypatch.setattr(bot_module, "_break_business", brk)

    asyncio.run(bot_module.cmd_sabotage(spy.message("саботаж @kto")))
    assert spy.removed == ["sabotazh"], "саботаж должен тратиться и при провале"
    assert not broke, "страховка обязана спасти бизнес"
    assert "страховка" in " ".join(spy.said)


def test_саботаж_ломает_бизнес(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["sabotazh"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((_target_user(), "")))
    monkeypatch.setattr(bot_module.db, "list_user_businesses",
                        _returns([{"business_key": "shaurma", "broken_kind": None}]))
    monkeypatch.setattr(bot_module.db, "consume_item_effect", _returns(False))
    monkeypatch.setattr(bot_module, "_dm_or_none", _noop)
    broke = {}

    async def brk(chat_id, row):
        broke["key"] = row["business_key"]

    monkeypatch.setattr(bot_module, "_break_business", brk)

    asyncio.run(bot_module.cmd_sabotage(spy.message("саботаж @kto")))
    assert spy.removed == ["sabotazh"]
    assert broke.get("key") == "shaurma"


def test_саботаж_по_себе_запрещён(monkeypatch):
    from aiogram.types import User
    spy = _Spy()
    spy.install(monkeypatch, ["sabotazh"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target", _returns(
        (User(id=USER_ID, is_bot=False, first_name="Тестер"), "")))

    asyncio.run(bot_module.cmd_sabotage(spy.message("саботаж @self")))
    assert not spy.removed


# --- компромат --------------------------------------------------------------

def test_компромат_без_архива_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["kompromat"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((_target_user(), "")))
    monkeypatch.setattr(bot_module.db, "list_recent_messages_by_user", _returns([]))

    asyncio.run(bot_module.cmd_kompromat(spy.message("компромат @kto")))
    assert not spy.removed
    assert "компромата не нашлось" in " ".join(spy.said)


# --- мегафон ----------------------------------------------------------------

def test_мегафон_без_реплая_не_тратится(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, ["megafon"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)

    asyncio.run(bot_module.cmd_megaphone(spy.message("мегафон")))
    assert not spy.removed


def test_мегафон_не_тратится_если_пин_не_удался(monkeypatch):
    """Прав на закрепление у бота может не быть — покупка сгорать не должна."""
    from aiogram.types import Chat, Message, User
    spy = _Spy()
    spy.install(monkeypatch, ["megafon"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)

    own = Message(
        message_id=7, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text="я тут",
    )
    msg = spy.message("мегафон")
    object.__setattr__(msg, "reply_to_message", own)

    async def boom(*a, **k):
        raise RuntimeError("not enough rights")

    monkeypatch.setattr(bot_module.bot, "pin_chat_message", boom)

    asyncio.run(bot_module.cmd_megaphone(msg))
    assert not spy.removed
    assert "не хватает прав" in " ".join(spy.said)


def test_мегафон_чужое_сообщение_не_закрепляет(monkeypatch):
    from aiogram.types import Chat, Message, User
    spy = _Spy()
    spy.install(monkeypatch, ["megafon"])
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)

    alien = Message(
        message_id=7, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=OTHER_ID, is_bot=False, first_name="Сосед"), text="чужое",
    )
    msg = spy.message("мегафон")
    object.__setattr__(msg, "reply_to_message", alien)

    asyncio.run(bot_module.cmd_megaphone(msg))
    assert not spy.removed
    assert "только ваши" in " ".join(spy.said)


# --- «использовать» подсказывает правильную команду -------------------------

@pytest.mark.parametrize("key", ["sabotazh", "kompromat", "dosye", "megafon", "medvezhatnik"])
def test_использовать_подсказывает_свою_команду(key, monkeypatch):
    """Раньше такой предмет отвечал «пока ничего не умеет» — и это неправда."""
    spy = _Spy()
    spy.install(monkeypatch, [key])

    asyncio.run(bot_module._use_effect_item(spy.message(f"использовать {key}"), key))
    said = " ".join(spy.said)
    assert not spy.removed
    assert "своей командой" in said, said
