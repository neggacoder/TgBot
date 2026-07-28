"""Чтение и запись настроек чата по описанию из реестра.

MySQL тесты не поднимают, поэтому подменяем два нижних уровня db (_fetchone,
_fetchall, _execute) и проверяем, ЧТО именно слой запрашивает и пишет.
"""

from __future__ import annotations

import asyncio
import functools

import pytest

import chat_settings
import db


@pytest.fixture
def запросы(monkeypatch):
    """Собирает выполненные запросы и отдаёт заранее заготовленные ответы."""
    written: list[tuple[str, tuple]] = []
    rows: dict[str, dict] = {}
    seen: list[str] = []

    async def fake_execute(query, args=()):
        written.append((" ".join(query.split()), args))
        return 1

    async def fake_fetchone(query, args=()):
        seen.append(query)
        for table, row in rows.items():
            if f"FROM {table}" in query:
                return row
        return None

    monkeypatch.setattr(db, "_execute", fake_execute)
    monkeypatch.setattr(db, "_fetchone", fake_fetchone)
    return type("Q", (), {"written": written, "rows": rows, "seen": seen})


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. tests/test_farming.py). Один декоратор вместо
    asyncio.run в каждом тесте."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@_sync
async def test_читает_колонку_початовой_таблицы(запросы):
    запросы.rows["bank_settings"] = {"rate_1d": 7.5, "min_deposit": 2000}
    s = [chat_settings.BY_KEY["bank.rate_1d"], chat_settings.BY_KEY["bank.min_deposit"]]
    out = await db.get_chat_setting_values(-100, s)
    assert out["bank.rate_1d"] == 7.5
    assert out["bank.min_deposit"] == 2000


@_sync
async def test_нет_строки_чата_значит_умолчание(запросы):
    s = [chat_settings.BY_KEY["bank.rate_1d"]]
    out = await db.get_chat_setting_values(-100, s)
    assert out["bank.rate_1d"] == chat_settings.BY_KEY["bank.rate_1d"].default


@_sync
async def test_одна_таблица_читается_одним_запросом(запросы):
    """Семь настроек банка — не семь походов в базу. Счётчик ведёт фикстура,
    подменять db прямо в тесте нельзя: подмена пережила бы тест."""
    запросы.rows["bank_settings"] = {"rate_1d": 1, "rate_3d": 2, "rate_7d": 3}
    s = [chat_settings.BY_KEY[k] for k in ("bank.rate_1d", "bank.rate_3d", "bank.rate_7d")]
    await db.get_chat_setting_values(-100, s)
    assert len(запросы.seen) == 1


@_sync
async def test_пишет_колонку_с_апсертом(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.rate_1d"], 8.0)
    query, args = запросы.written[-1]
    assert "bank_settings" in query and "rate_1d" in query
    assert -100 in args and 8.0 in args


@_sync
async def test_переключатель_в_data_пишется_единицей(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.auto_reject"], True)
    query, args = запросы.written[-1]
    assert "bot_data" in query
    assert "bank_autoreject:-100" in args and "1" in args


@_sync
async def test_выключение_в_data_удаляет_ключ(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.auto_reject"], False)
    query, _args = запросы.written[-1]
    assert "DELETE FROM bot_data" in query


@_sync
async def test_перевёрнутый_переключатель_наоборот(запросы):
    """Боссы: ключ boss_off есть — боссы ВЫКЛЮЧЕНЫ. Включение стирает ключ."""
    boss = chat_settings.BY_KEY["boss.enabled"]
    await db.set_chat_setting_value(-100, boss, True)
    assert "DELETE FROM bot_data" in запросы.written[-1][0]
    await db.set_chat_setting_value(-100, boss, False)
    query, args = запросы.written[-1]
    assert "INSERT INTO bot_data" in query and "boss_off:-100" in args


@_sync
async def test_перевёрнутый_читается_наоборот(запросы):
    boss = chat_settings.BY_KEY["boss.enabled"]
    out = await db.get_chat_setting_values(-100, [boss])
    assert out["boss.enabled"] is True          # ключа нет — боссы включены
    запросы.rows["bot_data"] = {"data_key": "boss_off:-100", "data_value": "1"}
    out = await db.get_chat_setting_values(-100, [boss])
    assert out["boss.enabled"] is False


@_sync
async def test_глобальная_настройка_читается_из_settings(запросы):
    запросы.rows["settings"] = {"duel_outcome": "ban_day"}
    out = await db.get_chat_setting_values(-100, [chat_settings.BY_KEY["duel.outcome"]])
    assert out["duel.outcome"] == "ban_day"
