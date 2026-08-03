"""Ответ админа заявителю: переписка должна работать в обе стороны.

Жалоба: «человек, что подал заявку, писать может, админ — нет». Маршрутизация
была ни при чём (сообщение доходит до handle_admin_reply), ломалось внутри
обработчика, и оба пути были МОЛЧАЛИВЫМИ:

1. Адресат искался только в request_messages по id сообщения, на которое
   ответили. Ответил админ на служебное «сообщение закреплено», на карточку с
   отредактированным текстом или на любое другое сообщение бота про этого
   человека — и обработчик просто выходил. Ни ответа, ни следа.
2. Отвечать разрешалось только админам БОТА (таблица admins). Администратор
   чата заявок, которого забыли добавить в «админку», получал реакцию 🤷 — а
   если у бота нет прав на реакции, то и её не получал.

Заодно: react() без fallback_text молчит при любой ошибке, поэтому успешная
пересылка выглядела так же, как несработавшая.
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

from aiogram.dispatcher.event.bases import SkipHandler  # noqa: E402
from aiogram.types import Chat, Message, MessageEntity, User  # noqa: E402

import bot as bot_module  # noqa: E402

ЗАЯВКИ = -1003811995090
ЖАЛОБЫ = -1003673552861
ЗАЯВИТЕЛЬ = 424242
АДМИН_ЧАТА = 777        # администратор в Telegram, но не заведён в «админке»
ПОСТОРОННИЙ = 999


@pytest.fixture
def стенд(monkeypatch):
    состояние = {"заявителю": [], "в_чат": [], "реакции_работают": False, "треды": {}}

    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЖАЛОБЫ)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", ЗАЯВКИ)

    async def get_user_by_message(message_id):
        return состояние["треды"].get(message_id)

    async def get_known_user_by_username(username):
        return {"user_id": ЗАЯВИТЕЛЬ} if username.casefold() == "vasya" else None

    async def add_request_message(message_id, user_id, is_anchor):
        состояние["треды"][message_id] = user_id

    async def send_message(chat_id, text, **kwargs):
        (состояние["заявителю"] if chat_id > 0 else состояние["в_чат"]).append(text)

    async def set_message_reaction(**kwargs):
        if not состояние["реакции_работают"]:
            raise RuntimeError("у бота нет прав на реакции")

    async def get_chat_member(chat_id, user_id):
        статус = "administrator" if user_id == АДМИН_ЧАТА else "member"
        return type("M", (), {"status": статус})()

    for имя, fn in [("get_user_by_message", get_user_by_message),
                    ("get_known_user_by_username", get_known_user_by_username),
                    ("add_request_message", add_request_message)]:
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    monkeypatch.setattr(bot_module.bot, "set_message_reaction", set_message_reaction, raising=False)
    monkeypatch.setattr(bot_module.bot, "get_chat_member", get_chat_member, raising=False)
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)  # админов бота нет
    return состояние


def карточка(text="📩 Новая заявка на вступление", ссылка=None, message_id=10):
    """Сообщение бота в чате заявок — с упоминанием заявителя или без."""
    entities = None
    if ссылка:
        entities = [MessageEntity(type="text_link", offset=0, length=2, url=ссылка)]
    return Message(
        message_id=message_id, date=datetime.now(),
        chat=Chat(id=ЗАЯВКИ, type="supergroup"),
        from_user=User(id=123456, is_bot=True, first_name="Бот"),
        text=text, entities=entities,
    )


def ответ_админа(на_что, кто=АДМИН_ЧАТА, text="Здравствуйте, вы приняты", chat_id=ЗАЯВКИ):
    msg = Message(
        message_id=11, date=datetime.now(),
        chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=кто, is_bot=False, first_name="Админ"),
        text=text, reply_to_message=на_что,
    )
    ответы: list[str] = []

    async def reply(t, **kwargs):
        ответы.append(t)

    object.__setattr__(msg, "reply", reply)
    return msg, ответы


def _прогнать(msg):
    try:
        asyncio.run(bot_module.handle_admin_reply(msg))
        return False
    except SkipHandler:
        return True


# ---------------------------------------------------------------------------
# Адресат находится
# ---------------------------------------------------------------------------
def test_ответ_на_заявку_из_базы_доходит(стенд):
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка())

    _прогнать(msg)

    assert стенд["заявителю"] == ["💬 Администратор:\nЗдравствуйте, вы приняты"]


def test_адресат_восстанавливается_по_ссылке_на_профиль(стенд):
    """Записи в базе нет — но в карточке есть tg://user?id=…, и этого хватит."""
    msg, _ = ответ_админа(карточка(ссылка=f"tg://user?id={ЗАЯВИТЕЛЬ}"))

    _прогнать(msg)

    assert стенд["заявителю"], "ответ не ушёл, хотя заявитель указан в карточке"


def test_адресат_восстанавливается_по_юзернейму(стенд):
    """mention_id ставит ссылку на t.me/{username}, когда юзернейм известен, —
    то есть чаще, чем tg://user?id. Без этого разбора починка была бы
    половинчатой."""
    msg, _ = ответ_админа(карточка(ссылка="https://telegram.me/vasya"))

    _прогнать(msg)

    assert стенд["заявителю"]


def test_ответ_админа_запоминается_как_часть_треда(стенд):
    """Иначе следующий ответ — уже на СВОЁ сообщение — снова никуда не уйдёт."""
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка())

    _прогнать(msg)

    assert стенд["треды"][11] == ЗАЯВИТЕЛЬ


# ---------------------------------------------------------------------------
# Молчания больше нет
# ---------------------------------------------------------------------------
def test_непонятный_адресат_объясняется_а_не_молчит(стенд):
    """Служебное «сообщение закреплено» и прочие сообщения бота без заявителя.
    Раньше здесь был молчаливый выход — самый частый вид жалобы."""
    msg, ответы = ответ_админа(карточка(text="Сообщение закреплено"))

    пропущено = _прогнать(msg)

    assert пропущено, "сообщение должно уйти дальше по цепочке"
    assert ответы and "Не понял, кому переслать" in ответы[0]
    assert not стенд["заявителю"]


def test_на_реплай_человеку_бот_не_ругается(стенд):
    """Админы в чате заявок переговариваются между собой — на каждый их реплай
    отвечать «не понял» нельзя."""
    сообщение_человека = Message(
        message_id=12, date=datetime.now(), chat=Chat(id=ЗАЯВКИ, type="supergroup"),
        from_user=User(id=АДМИН_ЧАТА, is_bot=False, first_name="Админ"), text="а он вообще кто?",
    )
    msg, ответы = ответ_админа(сообщение_человека)

    пропущено = _прогнать(msg)

    assert пропущено
    assert ответы == []


def test_успешная_пересылка_видна_даже_без_реакций(стенд):
    """react() без fallback_text молчит при любой ошибке — и успех выглядел
    так же, как несработавшая отправка."""
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка())

    _прогнать(msg)

    assert стенд["в_чат"] == ["✅ Отправлено заявителю."]


def test_с_рабочими_реакциями_чат_не_засоряется(стенд):
    стенд["реакции_работают"] = True
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка())

    _прогнать(msg)

    assert стенд["в_чат"] == [], "при живых реакциях лишний текст не нужен"


# ---------------------------------------------------------------------------
# Кто имеет право отвечать
# ---------------------------------------------------------------------------
def test_админ_чата_может_отвечать_без_записи_в_админке(стенд):
    """Чат заявок служебный: кто в нём администратор Telegram — тот персонал.
    Требовать сверх этого записи в «админке» значит молча не работать для
    половины команды."""
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка(), кто=АДМИН_ЧАТА)

    _прогнать(msg)

    assert стенд["заявителю"]


def test_посторонний_получает_отказ_а_не_тишину(стенд):
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка(), кто=ПОСТОРОННИЙ)

    _прогнать(msg)

    assert not стенд["заявителю"]
    assert стенд["в_чат"] and "только администраторы" in стенд["в_чат"][0]


def test_админ_бота_не_обязан_быть_админом_чата(стенд, monkeypatch):
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: uid == ПОСТОРОННИЙ)
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, _ = ответ_админа(карточка(), кто=ПОСТОРОННИЙ)

    _прогнать(msg)

    assert стенд["заявителю"]


def test_в_другом_чате_обработчик_не_вмешивается(стенд):
    """Заслон по чату остаётся: в рабочем чате реплаи — это игры и разговор."""
    стенд["треды"][10] = ЗАЯВИТЕЛЬ
    msg, ответы = ответ_админа(карточка(), chat_id=ЖАЛОБЫ)

    пропущено = _прогнать(msg)

    assert пропущено
    assert ответы == [] and not стенд["заявителю"]
