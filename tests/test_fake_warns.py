"""Обманные варны (fake_warns.py).

Проверяем две вещи: розыгрыш нигде не пересекается с настоящими варнами
(отдельное хранилище, свой счёт у каждого чата и человека) и ведёт себя как
настоящий там, где его видно, — прежде всего истекает по сроку.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import fake_warns

CHAT = -100500
OTHER_CHAT = -100600
USER = 42
OTHER_USER = 43
MODER = 7

NOW = datetime(2026, 7, 20, 12, 0)


@pytest.fixture(autouse=True)
def _clean():
    fake_warns.reset_all()
    yield
    fake_warns.reset_all()


def give(chat=CHAT, user=USER, reason="флуд", days=7, at=NOW):
    fake_warns.add(
        chat, user,
        reason=reason, warned_by=MODER, created_at=at,
        expires_at=at + timedelta(days=days) if days else None,
    )


# ---------------------------------------------------------------------------
# Счёт
# ---------------------------------------------------------------------------

def test_счёт_растёт():
    give(); give(); give()
    assert fake_warns.count(CHAT, USER, NOW) == 3


def test_у_не_разыгранного_ноль():
    assert fake_warns.count(CHAT, USER, NOW) == 0


def test_счета_разных_людей_не_смешиваются():
    give(); give()
    give(user=OTHER_USER)
    assert fake_warns.count(CHAT, USER, NOW) == 2
    assert fake_warns.count(CHAT, OTHER_USER, NOW) == 1


def test_счета_разных_чатов_не_смешиваются():
    """Один человек может состоять в двух чатах — розыгрыш в одном не должен
    доезжать до другого."""
    give()
    assert fake_warns.count(OTHER_CHAT, USER, NOW) == 0


# ---------------------------------------------------------------------------
# Срок
# ---------------------------------------------------------------------------

def test_истёкший_не_считается():
    """Настоящий варн через неделю перестаёт действовать — обманный обязан
    вести себя так же, иначе он переживёт все настоящие и станет заметен."""
    give(days=7)
    assert fake_warns.count(CHAT, USER, NOW + timedelta(days=8)) == 0


def test_действующий_считается_до_последнего_момента():
    give(days=7)
    assert fake_warns.count(CHAT, USER, NOW + timedelta(days=7) - timedelta(minutes=1)) == 1


def test_бессрочный_не_истекает():
    give(days=None)
    assert fake_warns.count(CHAT, USER, NOW + timedelta(days=3650)) == 1


def test_истекают_поштучно():
    give(days=1)
    give(days=30)
    assert fake_warns.count(CHAT, USER, NOW + timedelta(days=2)) == 1


# ---------------------------------------------------------------------------
# Содержимое записи — из него строится строка в списке «варны»
# ---------------------------------------------------------------------------

def test_запись_хранит_поля_настоящего_варна():
    give(reason="оффтоп")
    row = fake_warns.active(CHAT, USER, NOW)[0]
    assert row["reason"] == "оффтоп"
    assert row["warned_by"] == MODER
    assert row["created_at"] == NOW
    assert row["expires_at"] == NOW + timedelta(days=7)


def test_причина_может_отсутствовать():
    give(reason=None)
    assert fake_warns.active(CHAT, USER, NOW)[0]["reason"] is None


def test_порядок_выдачи_сохраняется():
    give(reason="первый")
    give(reason="второй")
    assert [r["reason"] for r in fake_warns.active(CHAT, USER, NOW)] == ["первый", "второй"]


# ---------------------------------------------------------------------------
# Снятие
# ---------------------------------------------------------------------------

def test_снятие_по_одному():
    give(); give()
    assert fake_warns.drop(CHAT, USER, NOW) == 1
    assert fake_warns.drop(CHAT, USER, NOW) == 0
    assert fake_warns.count(CHAT, USER, NOW) == 0


def test_снимается_последний_выданный():
    give(reason="первый")
    give(reason="второй")
    fake_warns.drop(CHAT, USER, NOW)
    assert [r["reason"] for r in fake_warns.active(CHAT, USER, NOW)] == ["первый"]


def test_снятие_у_не_разыгранного_не_ошибка():
    assert fake_warns.drop(CHAT, USER, NOW) == 0


def test_полная_очистка_возвращает_сколько_было():
    give(); give()
    assert fake_warns.clear(CHAT, USER) == 2
    assert fake_warns.count(CHAT, USER, NOW) == 0


def test_очистка_чистого_это_ноль():
    assert fake_warns.clear(CHAT, USER) == 0
