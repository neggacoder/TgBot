"""Один источник правды о чатах.

Настройки чатов читались россыпью settings.get(...) по всему боту — сто семь
мест в одном bot.py. Пока их много, «рабочий чат» и «чат заявок» легко
перепутать: так уже было с ролями и чисткой, которые взяли notify_chat_id
вместо complaint_chat_id и молча работали не в том чате.
"""

from __future__ import annotations

import asyncio
import functools

import pytest

import chats


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


class _Settings:
    """Заглушка db: одна строка настроек, как в настоящей базе."""

    def __init__(self, работа=None, заявки=None):
        self.значения = {"complaint_chat_id": работа, "notify_chat_id": заявки}

    async def fetch_settings(self):
        return dict(self.значения)


@pytest.fixture
def настройки(monkeypatch):
    s = _Settings(работа=-100111, заявки=-100222)
    monkeypatch.setattr(chats, "db", s)
    return s


@_sync
async def test_рабочий_и_заявочный_чаты_различаются(настройки):
    assert await chats.work_chat_id() == -100111
    assert await chats.gate_chat_id() == -100222


@_sync
async def test_свой_чат_узнаётся(настройки):
    assert await chats.is_work_chat(-100111) is True
    assert await chats.is_work_chat(-100222) is False
    assert await chats.is_known_chat(-100222) is True
    assert await chats.is_known_chat(-100999) is False


@_sync
async def test_ненастроенный_бот_не_считает_чужие_чаты_своими(monkeypatch):
    """Свежая установка: чаты ещё не привязаны. is_work_chat обязан отвечать
    «нет» — иначе первый попавшийся чат стал бы рабочим."""
    monkeypatch.setattr(chats, "db", _Settings())
    assert await chats.work_chat_id() is None
    assert await chats.is_work_chat(-100999) is False
    assert await chats.is_known_chat(-100999) is False


@_sync
async def test_недоступная_база_не_роняет_бота(monkeypatch):
    """Бот обязан подниматься и с упавшей базой: без настроек он просто не
    считает своим ни один чат, а не падает при первом же сообщении."""
    class _Мёртвая:
        async def fetch_settings(self):
            raise RuntimeError("нет связи")

    monkeypatch.setattr(chats, "db", _Мёртвая())
    assert await chats.work_chat_id() is None
    assert await chats.is_work_chat(-100111) is False


@_sync
async def test_настройка_читается_каждый_раз(настройки):
    """Кэша быть не должно: чат меняют командой «жалобы сюда» на ходу, и
    запомненное значение пережило бы перепривязку."""
    assert await chats.work_chat_id() == -100111
    настройки.значения["complaint_chat_id"] = -100777
    assert await chats.work_chat_id() == -100777
