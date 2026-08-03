"""Правила работы вне телеграма: смена, перерыв, состояние.

Порядок множителей в смене — значащий, и здесь он зафиксирован: настроение
множит базу, уровень и курсы идут следом, выгорание режет полученное, событие
чата множит после всего, надбавка предметов — предпоследней, настройка чата —
последней. Переставь два шага, и «+20% от курсов» начнёт значить разные
деньги в зависимости от того, идёт ли аврал.
"""

from __future__ import annotations

import asyncio
import functools
import random
from datetime import date, datetime, timedelta

import pytest

import professions
import work_actions


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    def __init__(self):
        self.coins = 0
        self.чужие: dict[int, int] = {}
        self.stats = {
            "profession_key": "уборщик", "prof_level": 1, "prof_xp": 0,
            "energy": 100, "mood": 100, "health": 100, "work_streak": 0,
            "total_shifts": 0, "shifts_since_break": 0,
            "last_work_at": None, "last_break_at": None,
            "last_shift_day": None, "mentor_id": None,
        }
        self.upgrades: set[str] = set()
        self.colleagues = 0
        self.office_used = False

    async def get_profession_stats(self, chat_id, user_id):
        return dict(self.stats)

    async def has_profession_upgrade(self, chat_id, user_id, key):
        return key in self.upgrades

    async def use_profession_office(self, chat_id, user_id, today):
        if self.office_used:
            return False
        self.office_used = True
        return True

    async def count_profession_colleagues(self, chat_id, key):
        return self.colleagues

    async def update_profession_after_shift(self, chat_id, user_id, xp, income,
                                            energy_delta, mood_delta,
                                            health_delta, streak, today):
        s = self.stats
        s["prof_xp"] += xp
        s["energy"] = max(0, min(100, s["energy"] + energy_delta))
        s["mood"] = max(0, min(100, s["mood"] + mood_delta))
        s["health"] = max(0, min(100, s["health"] + health_delta))
        s["work_streak"] = streak
        s["last_shift_day"] = today
        s["last_work_at"] = datetime.utcnow()
        s["total_shifts"] += 1
        s["shifts_since_break"] += 1
        return dict(s)

    async def set_profession_level(self, chat_id, user_id, level):
        self.stats["prof_level"] = level

    async def set_profession_mentor(self, chat_id, user_id, mentor):
        self.stats["mentor_id"] = mentor

    async def take_profession_break(self, chat_id, user_id, energy, now,
                                    touch_cooldown=True):
        self.stats["energy"] = max(0, min(100, self.stats["energy"] + energy))
        self.stats["shifts_since_break"] = 0
        if touch_cooldown:
            self.stats["last_break_at"] = now
        return self.stats["energy"]

    async def add_coins(self, chat_id, user_id, amount):
        if user_id == USER:
            self.coins += amount
        else:
            self.чужие[user_id] = self.чужие.get(user_id, 0) + amount
        return self.coins

    async def get_income_percent(self, chat_id, source):
        return 100

    async def list_inventory(self, chat_id, user_id):
        return []

    async def list_pets(self, chat_id, user_id):
        return []

    async def get_data(self, key):
        return None


CHAT, USER = -100, 7
УБОРЩИК = professions.PROFESSIONS["уборщик"]


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(work_actions, "db", world)
    monkeypatch.setattr(work_actions.farm_actions, "db", world)
    # Случайности убираем: проверяем арифметику, а не броски.
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    monkeypatch.setattr(random, "uniform", lambda a, b: a)
    monkeypatch.setattr(random, "random", lambda: 0.99)   # без случая на смене
    return world


@_sync
async def test_смена_платит_и_тратит_энергию(мир):
    итог = await work_actions.shift(CHAT, USER)
    assert итог.ok and итог.income > 0
    assert мир.coins == итог.income
    assert мир.stats["energy"] == 100 - УБОРЩИК["energy"]
    assert итог.next_at


@_sync
async def test_настроение_множит_доход(мир):
    """Настроение 100 даёт ×1, настроение 0 — ×0.5."""
    полный = await work_actions.shift(CHAT, USER)
    мир.stats.update(mood=0, energy=100, last_work_at=None)
    унылый = await work_actions.shift(CHAT, USER)
    assert унылый.income < полный.income


@_sync
async def test_курсы_дают_ровно_двадцать_процентов(мир):
    без = await work_actions.shift(CHAT, USER)
    мир.upgrades.add("курсы")
    мир.stats.update(energy=100, last_work_at=None, mood=100)
    с_курсами = await work_actions.shift(CHAT, USER)
    assert с_курсами.income == int(без.income * 1.2)


@_sync
async def test_инструменты_вдвое_экономят_энергию(мир):
    мир.upgrades.add("инструменты")
    await work_actions.shift(CHAT, USER)
    assert мир.stats["energy"] == 100 - УБОРЩИК["energy"] // 2


@_sync
async def test_профсоюз_снижает_расход(мир):
    мир.colleagues = professions.UNION_MIN_MEMBERS
    итог = await work_actions.shift(CHAT, USER)
    assert итог.union == professions.UNION_MIN_MEMBERS
    ожидаемо = max(1, round(УБОРЩИК["energy"] * (100 - professions.UNION_ENERGY_CUT) / 100))
    assert мир.stats["energy"] == 100 - ожидаемо


@_sync
async def test_выгорание_режет_доход(мир):
    обычный = await work_actions.shift(CHAT, USER)
    мир.stats.update(energy=100, last_work_at=None,
                     shifts_since_break=professions.BURNOUT_AFTER)
    выгоревший = await work_actions.shift(CHAT, USER)
    assert выгоревший.burnout
    assert выгоревший.income == max(1, round(
        обычный.income * (100 - professions.BURNOUT_PENALTY) / 100))


@_sync
async def test_без_энергии_смены_нет(мир):
    мир.stats["energy"] = 0
    итог = await work_actions.shift(CHAT, USER)
    assert not итог.ok and "энергии" in итог.error
    assert мир.coins == 0


@_sync
async def test_второй_подход_упирается_в_кулдаун(мир):
    await work_actions.shift(CHAT, USER)
    ещё = await work_actions.shift(CHAT, USER)
    assert not ещё.ok and ещё.next_at


@_sync
async def test_офис_даёт_смену_вне_очереди_один_раз(мир):
    мир.upgrades.add("офис")
    await work_actions.shift(CHAT, USER)
    вне_очереди = await work_actions.shift(CHAT, USER)
    assert вне_очереди.ok and вне_очереди.office
    третья = await work_actions.shift(CHAT, USER)
    assert not третья.ok


@_sync
async def test_наставнику_идёт_доля_сверх_дохода_ученика(мир):
    """Сверх, а не из: иначе наставничество было бы для ученика налогом."""
    мир.stats["mentor_id"] = 555
    итог = await work_actions.shift(CHAT, USER)
    assert итог.mentor_share > 0
    assert мир.coins == итог.income           # у ученика полный доход
    assert мир.чужие[555] == итог.mentor_share


@_sync
async def test_ученик_выпускается_на_пятом_уровне(мир):
    мир.stats.update(mentor_id=555, prof_xp=professions.LEVEL_XP[professions.STUDENT_MAX_LEVEL])
    итог = await work_actions.shift(CHAT, USER)
    assert итог.level >= professions.STUDENT_MAX_LEVEL and итог.graduated
    assert мир.stats["mentor_id"] is None


@_sync
async def test_серия_считается_по_дням(мир):
    вчера = datetime.utcnow().date() - timedelta(days=1)
    мир.stats.update(last_shift_day=вчера, work_streak=4)
    итог = await work_actions.shift(CHAT, USER)
    assert итог.streak == 5


@_sync
async def test_двадцатая_смена_даёт_ачивку(мир):
    мир.stats["total_shifts"] = 19
    итог = await work_actions.shift(CHAT, USER)
    assert "work_20" in итог.achievements


@_sync
async def test_перерыв_снимает_выгорание(мир):
    мир.stats["shifts_since_break"] = professions.BURNOUT_AFTER
    мир.stats["energy"] = 10
    итог = await work_actions.rest(CHAT, USER)
    assert итог.ok and итог.burnout
    assert мир.stats["shifts_since_break"] == 0
    assert мир.stats["energy"] == 10 + professions.BREAK_ENERGY


@_sync
async def test_перерыв_подряд_не_жмут(мир):
    await work_actions.rest(CHAT, USER)
    ещё = await work_actions.rest(CHAT, USER)
    assert not ещё.ok and ещё.next_at


@_sync
async def test_без_профессии_ни_смены_ни_перерыва(мир):
    мир.stats["profession_key"] = None
    assert not (await work_actions.shift(CHAT, USER)).ok
    assert not (await work_actions.rest(CHAT, USER)).ok


@_sync
async def test_состояние_описывает_силы_и_каталог(мир):
    итог = await work_actions.state(CHAT, USER)
    assert итог["profession"] == "уборщик" and итог["level"] == 1
    assert итог["energy"] == 100 and итог["xp_next"] == professions.LEVEL_XP[2]
    assert итог["burnout_after"] == professions.BURNOUT_AFTER
    assert {c["key"] for c in итог["catalog"]} == set(professions.PROFESSIONS)
    assert {u["key"] for u in итог["upgrade_catalog"]} == set(professions.UPGRADES)
    assert итог["next_at"] is None
