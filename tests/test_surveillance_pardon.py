"""Откуп по времени: надзор снимается сам через две недели.

Раньше выход из-под надзора был один — сто тысяч монет. Их у только что
пойманного грабителя чаще всего нет (он же секунду назад потерял 40% кошелька),
и наказание превращалось в вылет из механики навсегда.

Проверяем не «функция что-то вернула», а три места, где эта фича ломается
по-настоящему: граница срока, счётчик страйков и бэкфилл при миграции.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import db as db_module
import robbery


CHAT, USER = -100500, 777


class _Fake:
    """Подменяет db._fetchone/_execute: отдаёт заготовленную строку и
    запоминает все ушедшие запросы."""

    def __init__(self, row=None):
        self.row = row
        self.calls: list[tuple[str, tuple]] = []

    async def fetchone(self, query, params=()):
        self.calls.append((" ".join(query.split()), params))
        return self.row

    async def execute(self, query, params=()):
        self.calls.append((" ".join(query.split()), params))

    def queries(self) -> str:
        return "\n".join(q for q, _ in self.calls)


def _install(monkeypatch, row):
    fake = _Fake(row)
    monkeypatch.setattr(db_module, "_fetchone", fake.fetchone)
    monkeypatch.setattr(db_module, "_execute", fake.execute)
    return fake


# --- граница срока ----------------------------------------------------------

def test_надзор_держится_пока_срок_не_вышел(monkeypatch):
    """Тринадцать дней из четырнадцати — всё ещё под надзором."""
    since = datetime.utcnow() - (robbery.SURVEILLANCE_AUTO_PARDON - timedelta(days=1))
    fake = _install(monkeypatch, {"under_surveillance": 1, "surveillance_since": since})

    assert asyncio.run(db_module.is_under_surveillance(CHAT, USER)) is True
    assert "UPDATE" not in fake.queries(), "досрочного снятия быть не должно"


def test_надзор_снимается_когда_срок_вышел(monkeypatch):
    """Ровно на сроке — уже свободен, и это записано в базу, а не только
    возвращено наружу: иначе следующая же команда спросила бы заново."""
    since = datetime.utcnow() - robbery.SURVEILLANCE_AUTO_PARDON
    fake = _install(monkeypatch, {"under_surveillance": 1, "surveillance_since": since})

    assert asyncio.run(db_module.is_under_surveillance(CHAT, USER)) is False
    assert "under_surveillance = 0" in fake.queries()


def test_снятие_по_сроку_обнуляет_страйки(monkeypatch):
    """Главная ловушка всей фичи.

    add_robbery_strike сажает под надзор по условию «страйков не меньше лимита,
    и человек ещё не под надзором». Сними мы один только флаг — счётчик остался
    бы на трёх, и ПЕРВАЯ ЖЕ следующая поимка вернула бы надзор мгновенно. Две
    недели ожидания оказались бы выброшены, а причину этого в чате не увидел бы
    никто.
    """
    since = datetime.utcnow() - robbery.SURVEILLANCE_AUTO_PARDON
    fake = _install(monkeypatch, {"under_surveillance": 1, "surveillance_since": since})

    asyncio.run(db_module.is_under_surveillance(CHAT, USER))

    assert "surveillance_strikes = 0" in fake.queries()
    assert "surveillance_since = NULL" in fake.queries()


def test_не_под_надзором_никуда_не_ходит(monkeypatch):
    fake = _install(monkeypatch, {"under_surveillance": 0, "surveillance_since": None})

    assert asyncio.run(db_module.is_under_surveillance(CHAT, USER)) is False
    assert "UPDATE" not in fake.queries()


def test_строка_без_даты_получает_дату_а_не_амнистию(monkeypatch):
    """NULL у сидящего под надзором нельзя трактовать как «давно»: так весь чат
    амнистировался бы в первую же секунду."""
    fake = _install(monkeypatch, {"under_surveillance": 1, "surveillance_since": None})

    assert asyncio.run(db_module.is_under_surveillance(CHAT, USER)) is True
    assert "surveillance_since = %s" in fake.queries()
    assert "under_surveillance = 0" not in fake.queries()


# --- когда сажают -----------------------------------------------------------

def test_посадка_под_надзор_проставляет_дату(monkeypatch):
    """Флаг без даты — это надзор, из которого нет выхода по сроку, поэтому
    ставиться они обязаны одним запросом."""
    fake = _install(monkeypatch, {"surveillance_strikes": 3, "under_surveillance": 0})

    strikes, newly = asyncio.run(db_module.add_robbery_strike(CHAT, USER, 3))

    assert (strikes, newly) == (3, True)
    посадка = [q for q, _ in fake.calls if "under_surveillance = 1" in q]
    assert посадка, "надзор не поставлен"
    assert "surveillance_since = %s" in посадка[0], "дата ставится тем же запросом"


def test_амнистия_всем_гасит_и_дату(monkeypatch):
    """Оставшись в строке, дата стала бы стартом СЛЕДУЮЩЕГО надзора — и
    помилованный сегодня вышел бы из завтрашнего надзора задним числом."""
    fake = _install(monkeypatch, {"n": 2})

    assert asyncio.run(db_module.clear_all_surveillance(CHAT)) == 2
    assert "surveillance_since = NULL" in fake.queries()


# --- миграция ---------------------------------------------------------------

def test_миграция_бэкфиллит_уже_сидящих(monkeypatch):
    """Без бэкфилла NULL означал бы «никогда» — вечный надзор ровно у тех, ради
    кого срок и вводится."""
    executed: list[str] = []

    async def execute(query, params=()):
        executed.append(" ".join(query.split()))

    async def add_column(*args, **kwargs):
        pass

    monkeypatch.setattr(db_module, "_execute", execute)
    monkeypatch.setattr(db_module, "_add_column_if_missing", add_column)

    asyncio.run(db_module.ensure_robbery_tables())

    бэкфилл = [q for q in executed if "surveillance_since = UTC_TIMESTAMP()" in q]
    assert бэкфилл, "уже сидящие остались без даты начала"
    assert "under_surveillance = 1 AND surveillance_since IS NULL" in бэкфилл[0], (
        "бэкфилл обязан трогать только сидящих и только один раз"
    )


# --- сколько ждать ----------------------------------------------------------

def test_дата_снятия_считается_от_посадки(monkeypatch):
    since = datetime(2026, 1, 1, 12, 0, 0)
    _install(monkeypatch, {"under_surveillance": 1, "surveillance_since": since})

    assert asyncio.run(db_module.surveillance_pardon_at(CHAT, USER)) == (
        since + robbery.SURVEILLANCE_AUTO_PARDON
    )


def test_дата_снятия_у_свободного_пустая(monkeypatch):
    _install(monkeypatch, {"under_surveillance": 0, "surveillance_since": None})

    assert asyncio.run(db_module.surveillance_pardon_at(CHAT, USER)) is None


def test_срок_две_недели():
    """Число из спеки. Поменяют — тест упадёт и заставит поправить справку и
    фразу реестра, где «14 дней» написано словами."""
    assert robbery.SURVEILLANCE_AUTO_PARDON == timedelta(days=14)
