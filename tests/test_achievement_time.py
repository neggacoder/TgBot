"""Ачивки за время суток считаются по часовому поясу чата, а не по UTC.

«Сова» и «Жаворонок» выдавались по часу UTC-времени сообщения. В чате,
живущем по МСК (UTC+3), это значит, что «написать между 3 и 5 утра» падало
тем, кто писал в 6–8 утра по своим часам, а настоящие полуночники не получали
её никогда. Пояс в боте настраивается («часовой пояс Москва») — по нему и
надо считать.

Хранение при этом не меняется: сообщения как лежали в UTC, так и лежат.
Сдвигается только момент проверки. Стрик и стаж считаются по message_daily, у
которой сутки размечены UTC при записи, и их трогать нельзя — иначе в одной
таблице смешаются две разметки дня.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЧАТ = -1003673552861
ЧЕЛОВЕК = 555


@pytest.fixture
def стенд(monkeypatch):
    выдано: list[str] = []

    async def get_message_stats(chat_id, user_id):
        # 7 сообщений: не круглое число, чтобы не сработали пороговые ачивки
        # и проверка стажа — в этом тесте про них речи нет.
        return {"message_count": 7, "first_seen_at": datetime.utcnow()}

    async def grant_achievement(chat_id, user_id, code, **kwargs):
        выдано.append(code)

    async def list_active_days(chat_id, user_id):
        return []

    monkeypatch.setattr(bot_module.db, "get_message_stats", get_message_stats, raising=False)
    monkeypatch.setattr(bot_module.db, "list_active_days", list_active_days, raising=False)
    monkeypatch.setattr(bot_module, "grant_achievement", grant_achievement)
    return выдано


def _проверить(when):
    asyncio.run(bot_module.check_message_achievements(ЧАТ, ЧЕЛОВЕК, when))


@pytest.fixture
def пояс(monkeypatch):
    def поставить(name):
        monkeypatch.setitem(bot_module.settings, "timezone", name)
    return поставить


def test_сова_по_московскому_времени(стенд, пояс):
    """04:00 МСК — это 01:00 UTC. По UTC-часу ачивка не выдавалась вовсе."""
    пояс("Europe/Moscow")

    _проверить(datetime(2026, 7, 31, 1, 0))   # 04:00 МСК

    assert стенд == ["night_owl"]


def test_по_utc_часу_сова_больше_не_падает(стенд, пояс):
    """04:00 UTC — это 07:00 МСК, обычное утро. Раньше именно тут и падала."""
    пояс("Europe/Moscow")

    _проверить(datetime(2026, 7, 31, 4, 0))   # 07:00 МСК

    assert стенд == []


def test_жаворонок_по_московскому_времени(стенд, пояс):
    пояс("Europe/Moscow")

    _проверить(datetime(2026, 7, 31, 3, 0))   # 06:00 МСК

    assert стенд == ["early_bird"]


def test_без_настройки_пояса_остаётся_utc(стенд, пояс):
    """Пояс не задан — поведение прежнее, UTC. Иначе обновление молча сдвинуло
    бы правила в чатах, которые пояс не настраивали."""
    пояс("UTC")

    _проверить(datetime(2026, 7, 31, 4, 0))
    assert стенд == ["night_owl"]

    стенд.clear()
    _проверить(datetime(2026, 7, 31, 1, 0))
    assert стенд == []


@pytest.mark.parametrize("зона,utc_час,ожидание", [
    ("Europe/Moscow", 23, None),          # 02:00 МСК — до окна
    ("Europe/Moscow", 0, "night_owl"),    # 03:00 МСК — окно совы открылось
    ("Europe/Moscow", 2, "early_bird"),   # 05:00 МСК — сова кончилась, начался жаворонок
    ("Europe/Moscow", 4, None),           # 07:00 МСК — оба окна закрыты
    ("Asia/Almaty", 22, "night_owl"),     # 03:00 следующих суток в зоне +5
])
def test_границы_окон_в_разных_зонах(стенд, пояс, зона, utc_час, ожидание):
    пояс(зона)

    _проверить(datetime(2026, 7, 31, utc_час, 0))

    assert стенд == ([ожидание] if ожидание else [])


def test_описание_ачивки_говорит_про_время_чата():
    """Иначе «между 3 и 5 утра» читается как UTC — и жалоба вернётся."""
    for код in ("night_owl", "early_bird"):
        assert "по времени чата" in bot_module.ACHIEVEMENTS[код]["desc"]
