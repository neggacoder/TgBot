"""Созыв закрепляет себя сам.

Закрепляется ПЕРВОЕ сообщение созыва — то, в котором сам текст; остальные
это продолжение списка упоминаний. Прошлый закреп при этом снимается: созывы
идут регулярно, и без уборки шапка чата за неделю обрастает десятком
одинаковых закрепов.

Отдельно проверяется, что созыв переживает отсутствие прав на закрепление:
ради закрепа терять сам созыв нельзя.
"""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЧАТ = -1003673552861


@pytest.fixture
def стенд(monkeypatch):
    состояние = {
        "отправлено": [], "закреплено": [], "откреплено": [],
        "хранилище": {}, "пин_падает": False, "следующий_id": 100,
    }

    class _Отправленное:
        def __init__(self, message_id):
            self.message_id = message_id

    async def send_message(chat_id, text, **kwargs):
        состояние["отправлено"].append(text)
        состояние["следующий_id"] += 1
        return _Отправленное(состояние["следующий_id"])

    async def pin_chat_message(chat_id, message_id, **kwargs):
        if состояние["пин_падает"]:
            raise RuntimeError("нет прав на закрепление")
        состояние["закреплено"].append((message_id, kwargs.get("disable_notification")))

    async def unpin_chat_message(chat_id, message_id, **kwargs):
        состояние["откреплено"].append(message_id)

    async def get_data(key):
        значение = состояние["хранилище"].get(key)
        return {"data_value": значение} if значение is not None else None

    async def set_data(key, value, updated_by=None):
        состояние["хранилище"][key] = value

    async def no_sleep(_):
        return None

    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    monkeypatch.setattr(bot_module.bot, "pin_chat_message", pin_chat_message, raising=False)
    monkeypatch.setattr(bot_module.bot, "unpin_chat_message", unpin_chat_message, raising=False)
    monkeypatch.setattr(bot_module.db, "get_data", get_data, raising=False)
    monkeypatch.setattr(bot_module.db, "set_data", set_data, raising=False)
    monkeypatch.setattr(bot_module.asyncio, "sleep", no_sleep)
    return состояние


def _цели(сколько):
    return [{"user_id": 1000 + i, "emoji": "🐸"} for i in range(сколько)]


def _созыв(цели, текст="Все на сходку"):
    asyncio.run(bot_module._run_call(ЧАТ, цели, текст))


def test_созыв_закрепляется_сам(стенд):
    _созыв(_цели(3))

    assert len(стенд["закреплено"]) == 1, "закрепить нужно ровно одно сообщение"
    (message_id, тихо) = стенд["закреплено"][0]
    assert message_id == 101, "закрепляется первое сообщение созыва"
    assert тихо is True, "созыв и так всех протегал — второе уведомление лишнее"


def test_закрепляется_только_первое_из_нескольких_пачек(стенд):
    """Большой созыв уходит пачками. Закрепить каждую — завалить шапку чата
    списком упоминаний без текста."""
    _созыв(_цели(bot_module.CALL_BATCH_SIZE * 3))

    assert len(стенд["отправлено"]) >= 4      # три пачки + «Созыв окончен»
    assert len(стенд["закреплено"]) == 1


def test_прошлый_созыв_открепляется(стенд):
    стенд["хранилище"][f"callpin:{ЧАТ}"] = "42"

    _созыв(_цели(2))

    assert стенд["откреплено"] == [42]
    assert стенд["хранилище"][f"callpin:{ЧАТ}"] == "101", "запомнили новый закреп"


def test_без_прошлого_закрепа_ничего_не_открепляем(стенд):
    _созыв(_цели(2))

    assert стенд["откреплено"] == []


def test_без_прав_на_закреп_созыв_всё_равно_идёт(стенд):
    """Ронять созыв из-за закрепа нельзя: людей звали, а не закрепляли."""
    стенд["пин_падает"] = True

    _созыв(_цели(2))

    assert стенд["закреплено"] == []
    assert "📣 Созыв окончен." in стенд["отправлено"]
    assert f"callpin:{ЧАТ}" not in стенд["хранилище"], (
        "неудачный закреп не должен считаться закрепом — иначе следующий созыв "
        "попробует открепить то, чего нет"
    )


def test_созыв_без_текста_тоже_закрепляется(стенд):
    """Голое «созыв» без темы — сообщение всё равно есть, и оно первое."""
    asyncio.run(bot_module._run_call(ЧАТ, _цели(2), None))

    assert len(стенд["закреплено"]) == 1
