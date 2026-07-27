"""Профессии: энергия, выгорание, профсоюз, стажировка, заказы, аналитика.

Всё это выросло из одной дыры. «!работа перерыв» не имел ни кулдауна, ни
цены, ни лимита: его можно было жать подряд и держать энергию на сотне.
Из-за этого НИЧЕГО не значили ни энергия сама по себе, ни ⛑ Аптечка за
4 000 i¢, ни «!работа буст» за 50, ни улучшение «инструменты» (−50% расхода),
ни привилегия Робота работяги. Экономить было нечего.

Плюс три улучшения из пяти — «офис», «стиль», «аналитика» на 2 800 i¢ вместе —
списывали деньги и не делали ровным счётом ничего: в коде их никто не читал.

Поэтому здесь проверяется в первую очередь, что у отдыха есть цена, а у
купленного — эффект.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555
OTHER_ID = 777


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


def _stats(**kw):
    base = {
        "chat_id": CHAT_ID, "user_id": USER_ID, "profession_key": "уборщик",
        "prof_level": 1, "prof_xp": 0, "energy": 100, "mood": 100, "health": 100,
        "work_streak": 0, "last_work_at": None, "last_shift_day": None,
        "total_earned": 0, "total_shifts": 0, "last_break_at": None,
        "shifts_since_break": 0, "last_office_day": None, "mentor_id": None,
    }
    base.update(kw)
    return base


class _Spy:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.coins: list[tuple[int, int]] = []

    def message(self, text: str, user_id: int = USER_ID):
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


def _work_setup(monkeypatch, stats, colleagues=1, upgrades=(), income=1000):
    db = bot_module.db
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    monkeypatch.setattr(db, "get_profession_stats", _returns(stats))
    monkeypatch.setattr(db, "count_profession_colleagues", _returns(colleagues))
    monkeypatch.setattr(db, "has_profession_upgrade",
                        lambda c, u, key: _returns(key in upgrades)())
    monkeypatch.setattr(db, "use_profession_office", _returns(True))
    monkeypatch.setattr(bot_module, "event_flag", _returns(False))
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0))
    monkeypatch.setattr(bot_module, "_item_perk", _returns(0))
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Наставник"))
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))
    monkeypatch.setattr(random_stub := bot_module.random, "randint",
                        lambda a, b: income if b > 100 else 100)
    monkeypatch.setattr(random_stub, "random", lambda: 1.0)   # без случайного события
    monkeypatch.setattr(random_stub, "uniform", lambda a, b: 1.0)

    paid = []
    monkeypatch.setattr(db, "add_coins",
                        lambda c, u, amount, *a, **k: _returns(paid.append((u, amount)))())
    monkeypatch.setattr(db, "update_profession_after_shift", _returns(_stats(
        prof_xp=10, prof_level=1, total_shifts=1,
        shifts_since_break=int(stats.get("shifts_since_break") or 0) + 1)))
    monkeypatch.setattr(db, "set_profession_mentor", _noop)
    return paid


# --- перерыв: у отдыха появилась цена ---------------------------------------

def test_перерыв_нельзя_жать_подряд(monkeypatch):
    """Та самая дыра: без кулдауна энергия всегда на сотне."""
    spy = _Spy()
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns(
        _stats(last_break_at=datetime.utcnow() - timedelta(minutes=5), energy=40)))
    took = []
    monkeypatch.setattr(bot_module.db, "take_profession_break",
                        lambda *a, **k: _returns(took.append(1))())

    asyncio.run(bot_module.cmd_prof_break(spy.message("!работа перерыв")))
    assert not took, "перерыв сработал, хотя кулдаун не вышел"
    assert any("Следующий перерыв через" in s for s in spy.said)


def test_перерыв_работает_когда_кулдаун_вышел(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns(
        _stats(last_break_at=datetime.utcnow() - timedelta(hours=2), energy=40)))
    monkeypatch.setattr(bot_module.db, "take_profession_break", _returns(60))

    asyncio.run(bot_module.cmd_prof_break(spy.message("!работа перерыв")))
    assert any("отдохнули" in s for s in spy.said)


def test_перерыв_без_профессии_бессмыслен(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(bot_module.db, "get_profession_stats",
                        _returns(_stats(profession_key=None)))
    took = []
    monkeypatch.setattr(bot_module.db, "take_profession_break",
                        lambda *a, **k: _returns(took.append(1))())
    asyncio.run(bot_module.cmd_prof_break(spy.message("!работа перерыв")))
    assert not took


def test_платный_буст_не_запирает_бесплатный_перерыв(monkeypatch):
    """Иначе трата 50 i¢ наказывала бы: следом нельзя отдохнуть даром."""
    spy = _Spy()
    monkeypatch.setattr(bot_module, "spend_coins", _returns(True))
    captured = {}

    async def take(chat_id, user_id, energy, now, touch_cooldown=True):
        captured["touch"] = touch_cooldown
        return 70

    monkeypatch.setattr(bot_module.db, "take_profession_break", take)
    asyncio.run(bot_module.cmd_prof_boost(spy.message("!работа буст")))
    assert captured["touch"] is False


def test_кулдаун_перерыва_короче_кулдауна_смены():
    """Иначе между сменами нельзя было бы отдохнуть ни разу и энергия
    утекала бы в ноль без вариантов."""
    assert bot_module.PROFESSION_BREAK_COOLDOWN < bot_module.PROFESSION_WORK_COOLDOWN


# --- выгорание --------------------------------------------------------------

def test_выгорание_режет_доход(monkeypatch):
    spy = _Spy()
    clean = _work_setup(monkeypatch, _stats(shifts_since_break=0))
    text_clean = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    earned_clean = clean[0][1]

    burnt = _work_setup(monkeypatch, _stats(
        shifts_since_break=bot_module.BURNOUT_AFTER))
    text_burnt = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    earned_burnt = burnt[0][1]

    assert earned_burnt < earned_clean
    assert "Выгорание" in text_burnt
    assert "Выгорание" not in text_clean


def test_предупреждение_перед_выгоранием(monkeypatch):
    _work_setup(monkeypatch, _stats(shifts_since_break=bot_module.BURNOUT_WARN_AT))
    text = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Устали" in text


# --- профсоюз ---------------------------------------------------------------

def test_профсоюз_снижает_расход_энергии(monkeypatch):
    """Уборщик тратит 20 энергии, с профсоюзом — 16. При 17 на счету это и
    есть разница между «работать нельзя» и «смена прошла»."""
    _work_setup(monkeypatch, _stats(energy=17), colleagues=1)
    alone = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Не хватает энергии" in alone

    _work_setup(monkeypatch, _stats(energy=17),
                colleagues=bot_module.UNION_MIN_MEMBERS)
    with_union = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Не хватает энергии" not in with_union
    assert "Профсоюз" in with_union


def test_профсоюз_не_срабатывает_вчетвером(monkeypatch):
    _work_setup(monkeypatch, _stats(), colleagues=bot_module.UNION_MIN_MEMBERS - 1)
    text = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Профсоюз" not in text


# --- офис -------------------------------------------------------------------

def test_офис_даёт_смену_вне_очереди(monkeypatch):
    """Улучшение за 1 500 i¢, которое до сих пор не делало ничего."""
    just_worked = _stats(last_work_at=datetime.utcnow() - timedelta(minutes=5))
    _work_setup(monkeypatch, just_worked, upgrades=("офис",))
    text = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" not in text
    assert "офис" in text


def test_без_офиса_кулдаун_держит(monkeypatch):
    just_worked = _stats(last_work_at=datetime.utcnow() - timedelta(minutes=5))
    _work_setup(monkeypatch, just_worked)
    text = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" in text


def test_офис_только_раз_в_сутки(monkeypatch):
    just_worked = _stats(last_work_at=datetime.utcnow() - timedelta(minutes=5))
    _work_setup(monkeypatch, just_worked, upgrades=("офис",))
    monkeypatch.setattr(bot_module.db, "use_profession_office", _returns(False))
    text = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" in text


# --- стажировка -------------------------------------------------------------

def test_наставник_получает_долю_сверх_дохода_ученика(monkeypatch):
    """Именно сверх: вычитай долю из ученика — и наставник стал бы налогом."""
    paid = _work_setup(monkeypatch, _stats(mentor_id=OTHER_ID))
    asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))

    student = [a for u, a in paid if u == USER_ID]
    mentor = [a for u, a in paid if u == OTHER_ID]
    assert student and mentor
    assert mentor[0] == max(1, round(student[0] * bot_module.MENTOR_SHARE / 100))


def test_без_наставника_доли_нет(monkeypatch):
    paid = _work_setup(monkeypatch, _stats(mentor_id=None))
    asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert {u for u, _ in paid} == {USER_ID}


def test_в_наставники_берут_только_опытных(monkeypatch):
    spy = _Spy()
    from aiogram.types import User
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "resolve_command_target",
                        _returns((User(id=OTHER_ID, is_bot=False, first_name="Ю"), "")))
    monkeypatch.setattr(bot_module.db, "get_profession_stats", lambda c, u: _returns(
        _stats(prof_level=1) if u == USER_ID else _stats(prof_level=2))())
    saved = []
    monkeypatch.setattr(bot_module.db, "set_profession_mentor",
                        lambda *a, **k: _returns(saved.append(1))())

    asyncio.run(bot_module.cmd_prof_mentor(spy.message("!работа наставник @кто")))
    assert not saved
    assert any("уровня" in s for s in spy.said)


def test_опытному_ученику_стажировка_не_нужна(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module.db, "get_profession_stats",
                        _returns(_stats(prof_level=bot_module.STUDENT_MAX_LEVEL)))
    saved = []
    monkeypatch.setattr(bot_module.db, "set_profession_mentor",
                        lambda *a, **k: _returns(saved.append(1))())
    asyncio.run(bot_module.cmd_prof_mentor(spy.message("!работа наставник @кто")))
    assert not saved


# --- заказы -----------------------------------------------------------------

def _order_setup(monkeypatch, spy, order=None, stats=None):
    db = bot_module.db
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))
    monkeypatch.setattr(bot_module, "display_name", _returns("Тестер"))
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Другой"))
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
    monkeypatch.setattr(db, "add_log", _noop)
    monkeypatch.setattr(db, "update_profession_after_shift", _returns(_stats()))
    monkeypatch.setattr(db, "has_profession_upgrade", _returns(False))
    monkeypatch.setattr(db, "get_profession_stats", _returns(stats or _stats()))
    stored = {}

    async def get_data(key):
        return {"data_value": json.dumps(order)} if order else None

    async def set_data(key, value, **k):
        stored["value"] = json.loads(value)

    monkeypatch.setattr(db, "get_data", get_data)
    monkeypatch.setattr(db, "set_data", set_data)
    paid = []
    monkeypatch.setattr(db, "add_coins",
                        lambda c, u, amount, *a, **k: _returns(paid.append((u, amount)))())
    return stored, paid


def test_заказ_платит_кратно(monkeypatch):
    spy = _Spy()
    order = {"day": "2026-07-27", "profession": "уборщик", "taken_by": None}
    stored, paid = _order_setup(monkeypatch, spy, order=order)
    monkeypatch.setattr(bot_module.random, "randint", lambda a, b: 100 if b > 90 else 1)

    asyncio.run(bot_module.cmd_prof_order_take(spy.message("!работа заказ взять")))
    assert paid, "за выполненный заказ не заплатили"
    assert paid[0][1] >= 100 * bot_module.ORDER_REWARD_MULT
    assert stored["value"]["taken_by"] == USER_ID


def test_заказ_забирают_один_раз(monkeypatch):
    spy = _Spy()
    order = {"day": "2026-07-27", "profession": "уборщик", "taken_by": OTHER_ID}
    _stored, paid = _order_setup(monkeypatch, spy, order=order)
    asyncio.run(bot_module.cmd_prof_order_take(spy.message("!работа заказ взять")))
    assert not paid
    assert any("уже забрал" in s for s in spy.said)


def test_заказ_не_для_чужой_профессии(monkeypatch):
    spy = _Spy()
    order = {"day": "2026-07-27", "profession": "космонавт", "taken_by": None}
    _stored, paid = _order_setup(monkeypatch, spy, order=order)
    asyncio.run(bot_module.cmd_prof_order_take(spy.message("!работа заказ взять")))
    assert not paid


def test_заказ_требует_готовой_смены(monkeypatch):
    """Иначе заказ обходил бы кулдаун и был бы просто бесплатными деньгами."""
    spy = _Spy()
    order = {"day": "2026-07-27", "profession": "уборщик", "taken_by": None}
    _stored, paid = _order_setup(
        monkeypatch, spy, order=order,
        stats=_stats(last_work_at=datetime.utcnow() - timedelta(minutes=5)))
    asyncio.run(bot_module.cmd_prof_order_take(spy.message("!работа заказ взять")))
    assert not paid


def test_vip_заказ_выгоднее_обычного():
    assert bot_module.ORDER_VIP_MULT > bot_module.ORDER_REWARD_MULT


# --- аналитика --------------------------------------------------------------

def test_аналитика_требует_улучшения(monkeypatch):
    """Улучшение за 1 000 i¢ до сих пор не делало ничего вообще."""
    spy = _Spy()
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module.db, "has_profession_upgrade", _returns(False))
    asyncio.run(bot_module.cmd_prof_analytics(spy.message("!работа аналитика")))
    assert any("улучшить аналитика" in s for s in spy.said)


def test_аналитика_показывает_рейтинг(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module.db, "has_profession_upgrade", _returns(True))
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns(_stats()))
    asyncio.run(bot_module.cmd_prof_analytics(spy.message("!работа аналитика")))
    text = " ".join(spy.said)
    assert "Аналитика рынка труда" in text
    assert "на единицу энергии" in text


def test_все_улучшения_теперь_что_то_делают():
    """Раньше «офис», «стиль» и «аналитика» списывали 2 800 i¢ суммарно и не
    читались нигде в коде. Список нужен, чтобы это не повторилось."""
    import io
    src = io.open(bot_module.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    for key in bot_module.PROFESSION_UPGRADES:
        assert src.count(f'"{key}"') >= 2, (
            f"улучшение «{key}» нигде не используется — оно продаётся впустую"
        )
