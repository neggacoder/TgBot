"""Ивенты: включение, просмотр и ручной запуск со своей длительностью.

«Ивент» и «событие» — одно и то же; в чате говорят и так, и эдак, поэтому
обе формы обязаны работать. Отдельно проверяется, что фразы в реестре
покрывают ВСЕ рабочие формы: по ним бот опознаёт команду для автоочистки и
прав, и форма, забытая в реестре, теряет эту привязку молча.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import chat_events

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _message(text: str):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )
    replies: list = []

    async def reply(t, **k):
        replies.append(t)

    async def answer(t, **k):
        replies.append(t)

    object.__setattr__(m, "reply", reply)
    object.__setattr__(m, "answer", answer)
    return m, replies


def _handlers_for(text: str) -> list:
    msg, _ = _message(text)

    async def run():
        found = []
        for handler in bot_module.router.message.handlers:
            ok, _data = await handler.check(msg, bot=bot_module.bot)
            if ok:
                found.append(handler.callback.__name__)
        return found

    return asyncio.run(run())


# --- маршрутизация ---------------------------------------------------------

@pytest.mark.parametrize("text", ["ивенты", "!ивенты", "события", "!события", "событие"])
def test_просмотр_ивентов_доходит(text):
    assert "cmd_chat_event_status" in _handlers_for(text)


@pytest.mark.parametrize("text", ["+ивент", "-ивент", "+события", "-события",
                                  "+ивенты", "-ивенты"])
def test_включение_и_выключение_доходят(text):
    assert "cmd_chat_events_toggle" in _handlers_for(text)


@pytest.mark.parametrize("text", [
    "ивент gold_rush",
    "ивент gold_rush 30м",
    "ивент золотая лихорадка 2ч",
    "событие запустить gold_rush",       # старая форма остаётся рабочей
])
def test_запуск_ивента_доходит(text):
    assert "cmd_chat_event_force" in _handlers_for(text)


@pytest.mark.parametrize("text", ["событие века", "ивентов много", "событие произошло вчера"])
def test_обычные_фразы_не_запускают_ивент(text):
    """«событие {что-то}» намеренно не ловится: иначе админ, написавший
    «событие века», получал бы в ответ простыню со списком событий."""
    assert "cmd_chat_event_force" not in _handlers_for(text)


def test_голое_слово_ивент_не_показывает_статус():
    """«ивент» занято запуском — иначе слово стало бы неоднозначным при
    опознавании команды по тексту. Смотреть — «ивенты»."""
    assert "cmd_chat_event_status" not in _handlers_for("ивент")


# --- поиск события по названию ---------------------------------------------

@pytest.mark.parametrize("raw, key", [
    ("gold_rush", "gold_rush"),
    ("золотая лихорадка", "gold_rush"),
    ("Золотая", "gold_rush"),
    ("ЗОЛОТАЯ ЛИХОРАДКА", "gold_rush"),
    ("метеоритный дождь", "meteor"),
])
def test_событие_находится_по_ключу_и_по_названию(raw, key):
    found = chat_events.resolve(raw)
    assert found is not None and found.key == key


@pytest.mark.parametrize("raw", ["", "   ", "чепуха", None])
def test_чужое_слово_не_считается_событием(raw):
    assert chat_events.resolve(raw) is None


def test_каждое_событие_находится_по_своему_ключу():
    """Ключ обязан работать всегда — это то, что бот сам печатает в списке."""
    for event in chat_events.EVENTS:
        assert chat_events.resolve(event.key) is event, event.key


def test_неоднозначное_первое_слово_не_угадывается():
    """Если первое слово заголовка общее у двух событий, выбирать за человека
    нельзя — пусть уточнит."""
    from collections import Counter
    firsts = Counter(chat_events._normalize(e.title).split(" ")[0] for e in chat_events.EVENTS)
    for word, count in firsts.items():
        if count > 1:
            assert chat_events.resolve(word) is None, word


# --- своя длительность -----------------------------------------------------

def _fire_with(monkeypatch, text, kind=chat_events.BUFF):
    """Запускает команду и возвращает (событие, минуты), с которыми позвали
    fire_chat_event."""
    captured: dict = {}

    async def fake_fire(chat_id, event, minutes=None):
        captured["event"] = event
        captured["minutes"] = minutes
        return True

    monkeypatch.setattr(bot_module, "fire_chat_event", fake_fire, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: True, raising=False)
    msg, replies = _message(text)
    asyncio.run(bot_module.cmd_chat_event_force(msg))
    return captured, replies


def test_длительность_разбирается_и_передаётся(monkeypatch):
    captured, _ = _fire_with(monkeypatch, "ивент gold_rush 30м")
    assert captured["event"].key == "gold_rush"
    assert captured["minutes"] == 30


def test_длительность_в_часах(monkeypatch):
    captured, _ = _fire_with(monkeypatch, "ивент gold_rush 2ч")
    assert captured["minutes"] == 120


def test_без_длительности_берётся_штатная(monkeypatch):
    captured, _ = _fire_with(monkeypatch, "ивент gold_rush")
    assert captured["minutes"] is None


def test_многословное_название_без_срока_не_ломается(monkeypatch):
    """Последнее слово похоже на часть названия, а не на время — резать его
    нельзя."""
    captured, _ = _fire_with(monkeypatch, "ивент золотая лихорадка")
    assert captured["event"].key == "gold_rush"
    assert captured["minutes"] is None


def test_многословное_название_со_сроком(monkeypatch):
    captured, _ = _fire_with(monkeypatch, "ивент золотая лихорадка 45м")
    assert captured["event"].key == "gold_rush"
    assert captured["minutes"] == 45


def test_мгновенному_событию_срок_не_задать(monkeypatch):
    """У метеорита нет длительности — просить её бессмысленно, но и отказывать
    целиком не за что: запускаем как есть, предупредив."""
    captured, replies = _fire_with(monkeypatch, "ивент meteor 30м")
    assert captured["event"].key == "meteor"
    assert captured["minutes"] is None
    assert any("мгновенно" in r for r in replies)


def test_слишком_долгий_ивент_отклоняется(monkeypatch):
    captured, replies = _fire_with(monkeypatch, "ивент gold_rush 100д")
    assert not captured, "событие не должно запуститься"
    assert any("Слишком долго" in r for r in replies)


def test_несуществующее_событие_показывает_список(monkeypatch):
    captured, replies = _fire_with(monkeypatch, "ивент чепуха 30м")
    assert not captured
    assert replies and "gold_rush" in replies[0]


# --- реестр покрывает все формы --------------------------------------------

@pytest.mark.parametrize("text, key", [
    ("ивенты", "chat_events"),
    ("события", "chat_events"),
    ("событие", "chat_events"),
    ("+ивент", "chat_events_toggle"),
    ("-ивент", "chat_events_toggle"),
    ("+события", "chat_events_toggle"),
    ("-события", "chat_events_toggle"),
    ("ивент gold_rush 30м", "chat_events_toggle"),
    ("событие запустить gold_rush", "chat_events_toggle"),
])
def test_каждая_форма_опознаётся_как_своя_команда(text, key):
    """По этому опознаванию работают свой срок автоочистки и права. Форма,
    забытая во фразе реестра, привяжется к соседней команде — и настройка
    молча уедет не туда."""
    assert bot_module.resolve_command_key(text) == key


def test_обе_команды_настраиваются_в_панели_отдельно():
    assert bot_module.is_cleanup_targetable("chat_events")
    assert bot_module.is_cleanup_targetable("chat_events_toggle")
