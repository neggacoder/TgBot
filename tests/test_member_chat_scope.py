"""Кабинет работает только в рабочем чате.

Проверка «бот видел вас в этом чате» пускала любой чат из истории — включая
тот, где бот давно не работает. Через игровые экраны туда уходили деньги и
данные под чужим chat_id, и заметить это можно было только по расхождению
цифр в чате и на сайте.
"""

from __future__ import annotations

import asyncio
import functools
import os
import pathlib
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)
pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

from fastapi import HTTPException  # noqa: E402

# Именно importlib: пакет webpanel в своём __init__ делает «from .app import
# app», и обычное «from webpanel import app» отдаёт объект FastAPI, а не
# модуль (соседние тесты берут его так же).
import importlib  # noqa: E402

panel = importlib.import_module("webpanel.app")
from webpanel.auth import PanelUser  # noqa: E402


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


РАБОЧИЙ, ЧУЖОЙ = -100111, -100999


def _участник(tg_user_id=7):
    return PanelUser(id=1, username="кто-то", role="member", tg_user_id=tg_user_id)


@pytest.fixture
def свой_чат(monkeypatch):
    async def work_chat_id():
        return РАБОЧИЙ

    async def видел(chat_id, user_id):
        return {"user_id": user_id}

    # Модуль подключён под именем chats_mod: в app.py уже была переменная
    # chats со списком чатов, и одноимённый импорт её перекрывал.
    monkeypatch.setattr(panel.chats_mod, "work_chat_id", work_chat_id)
    monkeypatch.setattr(panel.db, "get_known_user", видел)


@_sync
async def test_рабочий_чат_пускают(свой_чат):
    await panel._require_member_in_chat(_участник(), РАБОЧИЙ)


@_sync
async def test_чужой_чат_не_пускают_даже_если_бот_там_видел(свой_чат):
    """Именно «даже если видел»: старая проверка ровно на этом и держалась."""
    with pytest.raises(HTTPException) as ошибка:
        await panel._require_member_in_chat(_участник(), ЧУЖОЙ)
    assert ошибка.value.status_code == 403


@_sync
async def test_непривязанный_рабочий_чат_это_отказ(monkeypatch):
    """Свежая установка: пока «жалобы сюда» не сказали, кабинету не с чем
    работать — и молча пускать первый попавшийся чат нельзя."""
    async def нет_чата():
        return None

    monkeypatch.setattr(panel.chats_mod, "work_chat_id", нет_чата)
    with pytest.raises(HTTPException) as ошибка:
        await panel._require_member_in_chat(_участник(), РАБОЧИЙ)
    assert ошибка.value.status_code == 400


@_sync
async def test_незнакомого_человека_не_пускают(monkeypatch):
    """Рабочий чат правильный, но бот этого человека там не видел."""
    async def work_chat_id():
        return РАБОЧИЙ

    async def не_видел(chat_id, user_id):
        return None

    # Модуль подключён под именем chats_mod: в app.py уже была переменная
    # chats со списком чатов, и одноимённый импорт её перекрывал.
    monkeypatch.setattr(panel.chats_mod, "work_chat_id", work_chat_id)
    monkeypatch.setattr(panel.db, "get_known_user", не_видел)
    with pytest.raises(HTTPException) as ошибка:
        await panel._require_member_in_chat(_участник(), РАБОЧИЙ)
    assert ошибка.value.status_code == 403


def test_ни_один_эндпоинт_не_принимает_чат_снаружи():
    """Чат приходил в теле запроса — то есть его выбирал браузер. Даже с
    проверкой это лишний параметр, которым можно ошибиться: чат один, и знать
    его должен сервер, а не страница."""
    корень = pathlib.Path(panel.__file__).parent
    плохие = []
    for файл in sorted(корень.glob("member_*_api.py")):
        for номер, строка in enumerate(файл.read_text(encoding="utf-8").split("\n"), 1):
            # Поле в теле запроса (pydantic).
            if re.match(r"\s+chat_id: int", строка):
                плохие.append(f"{файл.name}:{номер} {строка.strip()}")
            # Параметр обработчика (query).
            if re.match(r"async def api_\w+\(.*chat_id", строка):
                плохие.append(f"{файл.name}:{номер} {строка.strip()}")
    assert not плохие, "чат приходит снаружи:\n" + "\n".join(плохие)
