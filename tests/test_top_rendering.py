"""Топ активности: домик у граждан и итог по сообщениям — во ВСЕХ формах.

У топа три разных вывода, и они уже расходились: домик и итог добавили в
постраничный и в общий, а форма с явно указанным числом («топ 20 неделя»)
идёт своим путём и осталась без них. Поэтому здесь проверяется не отдельная
функция, а свойство всех трёх сразу.
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ROWS = [
    {"user_id": 1, "message_count": 620},
    {"user_id": 2, "message_count": 410},
    {"user_id": 3, "message_count": 95},
]
CITIZENS = {1, 3}
PERIOD_TOTAL = 14_203
ALLTIME_TOTAL = 98_750


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


@pytest.fixture(autouse=True)
def stats(monkeypatch):
    async def top(chat_id, limit=10, offset=0):
        return ROWS[offset:offset + limit], len(ROWS)

    async def top_period(chat_id, since, limit=10, offset=0):
        return ROWS[offset:offset + limit], len(ROWS)

    async def summ(chat_id, since):
        # None — «за всё время»: реальная sum_messages_period в этом случае
        # уходит в get_chat_total_messages, повторяем это поведение.
        return ALLTIME_TOTAL if since is None else PERIOD_TOTAL

    async def name(chat_id, user_id):
        return f"user{user_id}"

    monkeypatch.setattr(bot_module.db, "list_top_messages", top, raising=False)
    monkeypatch.setattr(bot_module.db, "list_top_messages_period", top_period, raising=False)
    monkeypatch.setattr(bot_module.db, "list_citizens", _returns(CITIZENS), raising=False)
    monkeypatch.setattr(bot_module.db, "sum_messages_period", summ, raising=False)
    monkeypatch.setattr(bot_module.db, "get_chat_total_messages",
                        _returns(ALLTIME_TOTAL), raising=False)
    monkeypatch.setattr(bot_module, "display_name_link_by_id", name, raising=False)


def _all_variants() -> dict:
    """Все три вывода топа под одними и теми же данными."""
    async def build():
        paged, _kb = await bot_module.stat_period_page(CHAT_ID, "week", 0)
        top, _kb2 = await bot_module.top_page(CHAT_ID, 0)
        exact = await bot_module.stat_period_text(CHAT_ID, "week", 20)
        return {"явное число": exact, "постраничный": paged, "общий топ": top}
    return asyncio.run(build())


@pytest.mark.parametrize("variant", ["явное число", "постраничный", "общий топ"])
def test_домик_есть_у_граждан_во_всех_формах(variant):
    text = _all_variants()[variant]
    assert "🏠 user1" in text, variant
    assert "🏠 user3" in text, variant


@pytest.mark.parametrize("variant", ["явное число", "постраничный", "общий топ"])
def test_у_неграждан_домика_нет(variant):
    text = _all_variants()[variant]
    assert "🏠 user2" not in text, variant


@pytest.mark.parametrize("variant", ["явное число", "постраничный", "общий топ"])
def test_итог_по_сообщениям_есть_во_всех_формах(variant):
    text = _all_variants()[variant]
    assert "Всего сообщений" in text, variant


def test_итог_считается_за_период_списка():
    """Показывать всю историю под недельным топом значило бы сравнивать
    разные вещи."""
    variants = _all_variants()
    assert str(PERIOD_TOTAL) in variants["явное число"]
    assert str(PERIOD_TOTAL) in variants["постраничный"]
    assert str(ALLTIME_TOTAL) in variants["общий топ"]


def test_все_формы_строят_строки_одним_кодом():
    """Расхождение уже случалось: пока рендер размазан по трём функциям,
    следующая правка снова обойдёт одну из них."""
    import inspect
    for fn in (bot_module.stat_period_text, bot_module.stat_period_page,
               bot_module.top_page):
        src = inspect.getsource(fn)
        assert "_stat_rank_lines" in src, fn.__name__
        assert "_stat_total_line" in src, fn.__name__


def test_нумерация_и_медали_сохранились():
    text = _all_variants()["явное число"]
    assert "🥇" in text and "🥈" in text and "🥉" in text


def test_сквозная_нумерация_на_второй_странице():
    async def build():
        lines = await bot_module._stat_rank_lines(CHAT_ID, ROWS[:2], start=10)
        return lines
    lines = asyncio.run(build())
    assert lines[0].startswith("11.") and lines[1].startswith("12.")


def test_пустой_период_не_ломается():
    async def build():
        return await bot_module.stat_period_text(CHAT_ID, "week", 0)
    # limit=0 — строк нет; функция обязана вернуть текст, а не упасть
    text = asyncio.run(build())
    assert isinstance(text, str) and text
