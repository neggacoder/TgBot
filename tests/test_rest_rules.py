"""Правила реста и памятка о нём (rest_rules.py).

Модуль чистый — ни базы, ни Telegram, поэтому тесты вызывают функции напрямую.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import rest_rules
from rest_rules import RestLimits, check_rest_rules, render_rest_template

NOW = datetime(2026, 7, 20, 12, 0)
DEFAULT_LIMITS = RestLimits()


def _check(**kwargs):
    params = {
        "now": NOW,
        "duration": timedelta(days=3),
        "first_seen_at": NOW - timedelta(days=365),
        "last_rest_end": None,
        "limits": DEFAULT_LIMITS,
    }
    params.update(kwargs)
    return check_rest_rules(**params)


# ---------------------------------------------------------------------------
# Максимальная длительность
# ---------------------------------------------------------------------------

def test_обычная_заявка_проходит():
    assert _check() is None


def test_ровно_две_недели_проходят():
    assert _check(duration=timedelta(days=14)) is None


def test_дольше_двух_недель_отклоняется():
    refusal = _check(duration=timedelta(days=15))
    assert refusal is not None
    assert "14 дней" in refusal


def test_нулевой_лимит_выключает_проверку_срока():
    limits = RestLimits(max_days=0)
    assert _check(duration=timedelta(days=200), limits=limits) is None


# ---------------------------------------------------------------------------
# Новички
# ---------------------------------------------------------------------------

def test_новичок_получает_отказ():
    refusal = _check(first_seen_at=NOW - timedelta(days=4))
    assert refusal is not None
    assert "новичк" in refusal.lower()
    # Дата, с которой рест станет доступен: 4 дня в чате + 10 дней ожидания.
    assert "30.07.2026" in refusal


def test_ровно_две_недели_в_чате_уже_не_новичок():
    assert _check(first_seen_at=NOW - timedelta(days=14)) is None


def test_день_до_срока_ещё_новичок():
    assert _check(first_seen_at=NOW - timedelta(days=13, hours=23)) is not None


def test_неизвестный_стаж_не_блокирует():
    assert _check(first_seen_at=None) is None


# ---------------------------------------------------------------------------
# Пауза между рестами
# ---------------------------------------------------------------------------

def test_повторный_рест_слишком_рано():
    refusal = _check(last_rest_end=NOW - timedelta(days=5))
    assert refusal is not None
    assert "Повторный рест" in refusal
    assert "29.07.2026" in refusal  # окончание прошлого (15.07) + 14 дней


def test_повторный_рест_ровно_через_две_недели():
    assert _check(last_rest_end=NOW - timedelta(days=14)) is None


def test_первый_рест_паузой_не_ограничен():
    assert _check(last_rest_end=None) is None


# ---------------------------------------------------------------------------
# Окно перед чисткой
# ---------------------------------------------------------------------------

def test_за_три_дня_до_чистки_рест_закрыт():
    limits = RestLimits(cleanup_date=date(2026, 7, 23))
    refusal = _check(limits=limits)
    assert refusal is not None
    assert "чистк" in refusal.lower()


def test_первый_день_окна_перед_чисткой_уже_закрыт():
    # now = 20.07, чистка 23.07, блокировка за 3 дня → окно 20.07…23.07.
    assert _check(limits=RestLimits(cleanup_date=date(2026, 7, 23))) is not None


def test_за_день_до_окна_рест_ещё_доступен():
    assert _check(limits=RestLimits(cleanup_date=date(2026, 7, 24))) is None


def test_в_день_чистки_рест_закрыт():
    assert _check(limits=RestLimits(cleanup_date=date(2026, 7, 20))) is not None


def test_после_чистки_рест_снова_доступен():
    assert _check(limits=RestLimits(cleanup_date=date(2026, 7, 19))) is None


def test_дата_чистки_не_задана_проверки_нет():
    assert _check(limits=RestLimits(cleanup_date=None)) is None


# ---------------------------------------------------------------------------
# Порядок проверок: сначала срок, потом всё остальное
# ---------------------------------------------------------------------------

def test_нарушены_сразу_несколько_правил_сообщается_про_срок():
    refusal = _check(
        duration=timedelta(days=30),
        first_seen_at=NOW - timedelta(days=1),
        last_rest_end=NOW - timedelta(days=1),
    )
    assert refusal is not None
    assert "Максимальная продолжительность" in refusal


# ---------------------------------------------------------------------------
# Разбор даты из настроек
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("23.07.2026", date(2026, 7, 23)),
        ("  23.07.2026  ", date(2026, 7, 23)),
        ("", None),
        (None, None),
        ("2026-07-23", None),
        ("завтра", None),
        ("32.07.2026", None),
    ],
)
def test_разбор_даты_чистки(raw, expected):
    assert rest_rules.parse_settings_date(raw) == expected


# ---------------------------------------------------------------------------
# Шаблон-памятка
# ---------------------------------------------------------------------------

def _render(template=None, reason="отпуск"):
    return render_rest_template(
        template,
        start=NOW,
        end=NOW + timedelta(days=3),
        reason=reason,
        member="<a href='tg://user?id=1'>Аня</a>",
        duration_text="3 дня",
    )


def test_подставляются_все_поля():
    text = _render("{участник} · {срок} · {дата_начала} → {дата_окончания} · {причина}")
    assert text == (
        "<a href='tg://user?id=1'>Аня</a> · 3 дня · "
        "20.07.2026 12:00 UTC → 23.07.2026 12:00 UTC · отпуск"
    )


def test_пустой_шаблон_заменяется_дефолтным():
    text = _render("   ")
    assert "максимальная продолжительность реста" in text
    assert "{дата_начала}" not in text


def test_причина_не_указана():
    assert "причина реста: не указана" in _render(reason=None)


def test_причина_экранируется():
    text = _render(reason="<b>болезнь</b>")
    assert "&lt;b&gt;болезнь&lt;/b&gt;" in text


def test_упоминание_остаётся_ссылкой():
    assert "<a href='tg://user?id=1'>Аня</a>" in _render("{участник}")


def test_неизвестный_плейсхолдер_и_скобки_не_ломают_рендер():
    text = _render("Привет {кто}! 100% {— и одинокая скобка: {")
    assert text == "Привет {кто}! 100% {— и одинокая скобка: {"


# ---------------------------------------------------------------------------
# Разбор числовых настроек
# ---------------------------------------------------------------------------
# Лимиты вводит человек — из панели и из лички бота. Оба входа проверяют ввод
# одной функцией, чтобы «14 дней» не проходило в панели и не отвергалось в
# боте (или наоборот).

@pytest.mark.parametrize("raw,expected", [("14", 14), ("0", 0), (" 7 ", 7), ("3650", 3650)])
def test_число_дней_разбирается(raw, expected):
    assert rest_rules.parse_days_setting(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["14 дней", "-1", "3651", "", "  ", None, "две недели", "7.5", "١٤"],
)
def test_мусор_в_числе_дней_отвергается(raw):
    assert rest_rules.parse_days_setting(raw) is None
