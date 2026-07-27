"""Награды чата: что они теперь дают и почему их нельзя штамповать.

До этого «наградить» не влияло вообще ни на что: медаль была строкой в
профиле и списке наград, и всё. Раздел справки поэтому и выглядел пустым —
рассказывать было не о чем.

Теперь награда приносит монеты и репутацию по степени, за неё дают ачивки и
есть «топ наград». Ровно поэтому у неё появился кулдаун на пару «кто → кому»:
выдаётся она руками, и без ограничения двое договорившихся награждали бы друг
друга по кругу, печатая монеты и репутацию.

Плюс здесь зафиксирована починка тихой подмены: «наградить 99» раньше молча
выдавало первую степень, и человек был уверен, что вручил высшую.
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
ACTOR = 555
TARGET = 999


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


class _Spy:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.coins: list[tuple[int, int]] = []
        self.rep: list[int] = []
        self.rewards: list[dict] = []
        self.achievements: list[str] = []

    def install(self, monkeypatch, last_reward=None, total_rewards=0):
        db = bot_module.db
        monkeypatch.setattr(bot_module, "get_level",
                            lambda uid: bot_module.LEVEL_SENIOR if uid == ACTOR else 0)
        monkeypatch.setattr(bot_module, "required_reward_level",
                            lambda d: bot_module.LEVEL_MODERATOR)
        monkeypatch.setattr(bot_module, "display_name", _returns("Цель"))
        monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
        monkeypatch.setattr(db, "add_log", _noop)
        monkeypatch.setattr(db, "last_reward_between", _returns(last_reward))
        monkeypatch.setattr(db, "count_rewards", _returns(total_rewards))

        async def add_reward(chat_id, uid, degree, reason, by):
            self.rewards.append({"uid": uid, "degree": degree, "reason": reason})
            return 7

        async def add_coins(chat_id, uid, amount, *a, **k):
            self.coins.append((uid, amount))

        async def change_reputation(chat_id, actor, target, amount):
            self.rep.append(amount)
            return amount

        async def grant(chat_id, uid, code, **k):
            self.achievements.append(code)
            return True

        monkeypatch.setattr(db, "add_reward", add_reward)
        monkeypatch.setattr(db, "add_coins", add_coins)
        monkeypatch.setattr(db, "change_reputation", change_reputation)
        monkeypatch.setattr(bot_module, "grant_achievement", grant)

    def message(self, text: str):
        from aiogram.types import Chat, Message, User
        target = User(id=TARGET, is_bot=False, first_name="Цель")
        replied = Message(
            message_id=2, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=target, text="за что-то",
        )
        m = Message(
            message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=ACTOR, is_bot=False, first_name="Админ"),
            text=text, reply_to_message=replied,
        )

        async def collect(t, **k):
            self.said.append(t)

        object.__setattr__(m, "reply", collect)
        object.__setattr__(m, "answer", collect)
        return m


# --- награда что-то даёт ----------------------------------------------------

def test_награда_приносит_монеты_и_репутацию(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 5")))

    assert spy.rewards[0]["degree"] == 5
    assert (TARGET, bot_module.REWARD_COINS_PER_DEGREE * 5) in spy.coins
    assert spy.rep == [5]


def test_чем_выше_степень_тем_больше(monkeypatch):
    spy_low = _Spy()
    spy_low.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy_low.message("наградить 1")))

    spy_high = _Spy()
    spy_high.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy_high.message("наградить 8")))

    assert spy_high.coins[0][1] > spy_low.coins[0][1]
    assert spy_high.rep[0] > spy_low.rep[0]


def test_ачивка_за_первую_награду(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, total_rewards=1)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 2")))
    assert "rewarded_first" in spy.achievements
    assert "rewarded_5" not in spy.achievements


def test_ачивка_за_пять_наград(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, total_rewards=5)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 2")))
    assert "rewarded_5" in spy.achievements


def test_ачивка_за_высокую_степень(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, total_rewards=1)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 7")))
    assert "rewarded_high" in spy.achievements


def test_низкая_степень_ордена_не_даёт(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, total_rewards=1)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 6")))
    assert "rewarded_high" not in spy.achievements


# --- защита от накрутки -----------------------------------------------------

def test_нельзя_награждать_одного_подряд(monkeypatch):
    """Награда теперь печатает монеты и репутацию — без кулдауна двое
    договорившихся гоняли бы их по кругу."""
    spy = _Spy()
    spy.install(monkeypatch, last_reward=datetime.utcnow() - timedelta(hours=1))
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 5")))

    assert not spy.rewards, "награда выдана, хотя кулдаун не вышел"
    assert not spy.coins
    assert any("через" in s for s in spy.said)


def test_через_сутки_снова_можно(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch, last_reward=datetime.utcnow() - timedelta(hours=25))
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 5")))
    assert spy.rewards


def test_кулдаун_не_короче_суток():
    assert bot_module.REWARD_SAME_TARGET_COOLDOWN >= timedelta(hours=24)


# --- разбор степени ---------------------------------------------------------

def test_кривая_степень_больше_не_подменяется_молча(monkeypatch):
    """«наградить 99» выдавало первую степень без единого слова, и человек
    был уверен, что вручил высшую."""
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 99")))

    assert not spy.rewards
    assert any("от 1 до 8" in s for s in spy.said)


def test_нечисловая_степень_отбивается(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить абв")))
    assert not spy.rewards


def test_без_степени_даётся_первая(monkeypatch):
    """Это как раз осмысленное умолчание: степень не назвали — вручили самую
    скромную."""
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить")))
    assert spy.rewards and spy.rewards[0]["degree"] == 1


def test_причина_попадает_в_награду(monkeypatch):
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(bot_module.cmd_reward(spy.message("наградить 3\nЗа помощь новичкам")))
    assert spy.rewards[0]["reason"] == "За помощь новичкам"
    assert any("За помощь новичкам" in s for s in spy.said)


# --- топ --------------------------------------------------------------------

def test_топ_считает_по_сумме_степеней(monkeypatch):
    """Иначе десять первых степеней обгоняли бы один орден высшей."""
    spy = _Spy()
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Кто-то"))
    monkeypatch.setattr(bot_module.db, "list_reward_top", _returns([
        {"user_id": 1, "weight": 16, "total": 2, "best": 8},
        {"user_id": 2, "weight": 10, "total": 10, "best": 1},
    ]))
    asyncio.run(bot_module.cmd_reward_top(spy.message("топ наград")))
    text = " ".join(spy.said)
    assert "Самые заслуженные" in text
    assert text.index("🥇") < text.index("🥈")


def test_пустой_топ_не_падает(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module.db, "list_reward_top", _returns([]))
    asyncio.run(bot_module.cmd_reward_top(spy.message("топ наград")))
    assert any("никого не награждали" in s for s in spy.said)
