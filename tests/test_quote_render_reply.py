"""Плашка «в ответ на» в «.стикер».

Рендер плашки (bubble._render_reply) был написан и работал всегда — не
работала ПЕРЕДАЧА данных, поэтому в чате плашку никто ни разу не увидел.

Причина ровно одна и стоит того, чтобы её здесь зафиксировать: Telegram
обрезает вложенность реплаев на одном уровне. В апдейте «.стикер» поле
message.reply_to_message — это процитированное сообщение, но у НЕГО поля
reply_to_message уже нет («will not contain further reply_to_message fields
even if it itself is a reply», Bot API). Старый _attach_reply_plate читал
именно его, всегда получал None и молча выходил.

Отсюда и тесты: снимок реплая должен сниматься в момент приёма сообщения
(_remember_recent_message), а «.стикер» — доставать его из буфера.
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
from quote_render import QuoteMessage  # noqa: E402

CHAT_ID = -1001234567890
AUTHOR_ID = 555
QUOTED_ID = 777


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


def _message(message_id: int, user_id: int, text: str, reply_to=None):
    from aiogram.types import Chat, Message, User
    return Message(
        message_id=message_id, date=datetime.now(),
        chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=user_id, is_bot=False, first_name=f"U{user_id}"),
        text=text, reply_to_message=reply_to,
    )


@pytest.fixture(autouse=True)
def _clean_buffer(monkeypatch):
    monkeypatch.setattr(bot_module, "recent_chat_messages", {})
    monkeypatch.setattr(bot_module.db, "get_nickname", _returns(None))
    monkeypatch.setattr(bot_module.db, "add_recent_message", _returns(None))
    yield


# --- снимок снимается при приёме -------------------------------------------

def test_буфер_запоминает_реплай_в_момент_приёма():
    quoted = _message(10, QUOTED_ID, "Может встретимся в четверг?")
    reply = _message(11, AUTHOR_ID, "Давай", reply_to=quoted)

    asyncio.run(bot_module._remember_recent_message(reply))

    entry = bot_module.recent_chat_messages[CHAT_ID][-1]
    assert entry["reply_to_message_id"] == 10
    assert entry["reply_user_id"] == QUOTED_ID
    assert entry["reply_text"] == "Может встретимся в четверг?"


def test_сообщение_без_реплая_снимка_не_получает():
    asyncio.run(bot_module._remember_recent_message(_message(11, AUTHOR_ID, "просто текст")))
    entry = bot_module.recent_chat_messages[CHAT_ID][-1]
    assert "reply_text" not in entry


def test_реплай_на_голосовое_описывается_словами():
    """В плашке должно быть «🎤 Голосовое сообщение», а не пусто: иначе
    ответ на голосовое терял плашку целиком."""
    from aiogram.types import Chat, Message, User, Voice
    voice = Message(
        message_id=10, date=datetime.now(),
        chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=QUOTED_ID, is_bot=False, first_name="U"),
        voice=Voice(file_id="a", file_unique_id="b", duration=3),
    )
    asyncio.run(bot_module._remember_recent_message(
        _message(11, AUTHOR_ID, "ок", reply_to=voice)
    ))
    entry = bot_module.recent_chat_messages[CHAT_ID][-1]
    assert entry["reply_text"] == "🎤 Голосовое сообщение"


# --- «.стикер» достаёт снимок ----------------------------------------------

def test_плашка_берётся_из_буфера_когда_телеграм_вложенность_обрезал():
    """Главный тест: ровно тот случай, что был сломан.

    src пришёл БЕЗ reply_to_message — так Telegram и отдаёт процитированное
    сообщение. Данные должны найтись в буфере.
    """
    quoted = _message(10, QUOTED_ID, "Может встретимся в четверг?")
    asyncio.run(bot_module._remember_recent_message(
        _message(11, AUTHOR_ID, "Давай", reply_to=quoted)
    ))

    src = _message(11, AUTHOR_ID, "Давай")          # без reply_to_message!
    assert src.reply_to_message is None

    quote = QuoteMessage(user_id=AUTHOR_ID, name="U555", text="Давай")
    asyncio.run(bot_module._attach_reply_plate(quote, CHAT_ID, src))

    assert quote.reply_text == "Может встретимся в четверг?"
    assert quote.reply_chat_id == QUOTED_ID
    assert quote.reply_name == "U777"


def test_живой_апдейт_имеет_приоритет_над_буфером():
    quoted = _message(10, QUOTED_ID, "из апдейта")
    asyncio.run(bot_module._remember_recent_message(
        _message(11, AUTHOR_ID, "Давай", reply_to=_message(10, QUOTED_ID, "из буфера"))
    ))
    src = _message(11, AUTHOR_ID, "Давай", reply_to=quoted)

    quote = QuoteMessage(user_id=AUTHOR_ID, name="U555", text="Давай")
    asyncio.run(bot_module._attach_reply_plate(quote, CHAT_ID, src))

    assert quote.reply_text == "из апдейта"


def test_ник_чата_подставляется_в_плашку():
    """Плашка должна быть подписана тем же именем, что и сам бабл."""
    quoted = _message(10, QUOTED_ID, "текст")
    src = _message(11, AUTHOR_ID, "Давай", reply_to=quoted)

    quote = QuoteMessage(user_id=AUTHOR_ID, name="U555", text="Давай")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bot_module.db, "get_nickname", _returns("Ержан"))
        asyncio.run(bot_module._attach_reply_plate(quote, CHAT_ID, src))

    assert quote.reply_name == "Ержан"


def test_без_реплая_плашки_нет():
    src = _message(11, AUTHOR_ID, "Давай")
    quote = QuoteMessage(user_id=AUTHOR_ID, name="U555", text="Давай")
    asyncio.run(bot_module._attach_reply_plate(quote, CHAT_ID, src))
    assert quote.reply_text is None
    assert quote.reply_name is None


def test_чужой_message_id_плашку_не_подхватывает():
    """Снимок ищется строго по message_id — иначе плашка уехала бы к
    соседнему сообщению в склейке «.стикер N»."""
    quoted = _message(10, QUOTED_ID, "текст")
    asyncio.run(bot_module._remember_recent_message(
        _message(11, AUTHOR_ID, "Давай", reply_to=quoted)
    ))
    src = _message(99, AUTHOR_ID, "другое сообщение")

    quote = QuoteMessage(user_id=AUTHOR_ID, name="U555", text="другое")
    asyncio.run(bot_module._attach_reply_plate(quote, CHAT_ID, src))
    assert quote.reply_text is None


# --- рендер действительно рисует плашку ------------------------------------

def test_плашка_меняет_картинку():
    """Сквозная проверка: заполненные поля доезжают до рендера.

    Без неё тесты выше проверяли бы только передачу данных, а поломка могла
    переехать в bubble.py и остаться незамеченной.
    """
    pytest.importorskip("PIL", reason="нужен Pillow")
    from quote_render import render_quote

    plain = render_quote([QuoteMessage(user_id=AUTHOR_ID, name="U555", text="Давай")])
    with_reply = render_quote([QuoteMessage(
        user_id=AUTHOR_ID, name="U555", text="Давай",
        reply_name="U777", reply_text="Может встретимся в четверг?",
        reply_chat_id=QUOTED_ID,
    )])

    assert with_reply.height > plain.height, "плашка должна добавлять высоту баблу"
