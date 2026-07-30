"""Роли при вступлении: список ролей и проверка «выбрал ли роль» должны
смотреть в ОДИН чат — тот же, что и обработчик кнопки rpick.

Баг из жизни: «чат сюда» (notify_chat_id) и «жалобы сюда» (complaint_chat_id)
привязаны к разным группам. Роли живут в чате из roles_context_chat_id()
(complaint_chat_id) — там их выбирают все обычные команды («сменить роль» и
т.п.). А флоу заявки на вход брал notify_chat_id: список ролей заявителю
собирался из чужого чата (кнопки rpick указывали на id ролей, которых в чате
ролей нет — «Эта роль больше не существует»), а «Дать ссылку» проверяла роль
тоже в notify_chat_id и потому не видела реально выбранную роль — админам
писало «Заявитель ещё не выбрал роль», хотя роль выбрана.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

# Как в реальной базе: заявки падают в один чат, роли живут в другом.
NOTIFY_CHAT = -1003811995090
ROLES_CHAT = -1003673552861
APPLICANT = 555

# Свободные роли в каждом чате — с РАЗНЫМИ id, чтобы по callback_data кнопки
# было видно, из какого чата собран список.
_ROLES = {
    ROLES_CHAT: [{"id": 501, "name": "Рей Аянами", "category": None, "status": "free"}],
    NOTIFY_CHAT: [{"id": 901, "name": "Рей Аянами", "category": None, "status": "free"}],
}


async def _async_noop(*args, **kwargs):
    return None


def _async_returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _setup_roles(monkeypatch):
    """Общая обвязка: два чата с ролями + запись того, какие chat_id спрашивали."""
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", NOTIFY_CHAT)
    monkeypatch.setitem(bot_module.settings, "notify_topic_id", None)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ROLES_CHAT)

    asked: list[int] = []

    async def list_roles(chat_id, approved_only=True):
        asked.append(chat_id)
        return list(_ROLES.get(chat_id, []))

    async def list_free_roles(chat_id):
        asked.append(chat_id)
        return [r for r in _ROLES.get(chat_id, []) if r["status"] == "free"]

    monkeypatch.setattr(bot_module.db, "list_roles", list_roles)
    monkeypatch.setattr(bot_module.db, "list_free_roles", list_free_roles)
    return asked


def _capture_send(monkeypatch):
    sent: list[dict] = []

    async def send_message(chat_id, text=None, **kwargs):
        sent.append({"chat_id": chat_id, "text": text, **kwargs})

    monkeypatch.setattr(bot_module.bot, "send_message", send_message)
    return sent


def _kb_callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_обязательный_выбор_роли_заявителю_берёт_роли_из_чата_ролей(monkeypatch):
    asked = _setup_roles(monkeypatch)
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(bot_module.db, "get_user_role", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "get_user_reservation", _async_returns(None))

    asyncio.run(bot_module.prompt_role_pick_for_applicant(APPLICANT))

    assert asked, "список ролей вообще не запрашивался"
    assert set(asked) == {ROLES_CHAT}, (
        f"роли спрашивали не только в чате ролей: {sorted(set(asked))}"
    )
    assert len(sent) == 1 and sent[0]["chat_id"] == APPLICANT
    # Кнопки должны вести на роли чата ролей, иначе rpick ответит
    # «Эта роль больше не существует».
    assert _kb_callbacks(sent[0]["reply_markup"]) == ["rpick:501"]


def test_мягкая_подсказка_после_входа_берёт_роли_из_чата_ролей(monkeypatch):
    """Человек вошёл в чат заявок (ссылка ведёт туда) — кнопки всё равно должны
    указывать на роли того чата, где их обрабатывает rpick."""
    asked = _setup_roles(monkeypatch)
    sent = _capture_send(monkeypatch)
    monkeypatch.setattr(bot_module.db, "get_user_role", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "get_user_reservation", _async_returns(None))

    asyncio.run(bot_module.prompt_role_pick_after_join(NOTIFY_CHAT, APPLICANT))

    assert set(asked) == {ROLES_CHAT}, (
        f"роли спрашивали не только в чате ролей: {sorted(set(asked))}"
    )
    assert len(sent) == 1
    assert _kb_callbacks(sent[0]["reply_markup"]) == ["rpick:501"]


def _give_link_callback():
    answers: list[dict] = []
    edits: list[str] = []

    async def answer(text=None, show_alert=False, **kwargs):
        answers.append({"text": text, "show_alert": show_alert})

    async def edit_text(text, **kwargs):
        edits.append(text)

    message = SimpleNamespace(
        message_id=10,
        chat=SimpleNamespace(id=NOTIFY_CHAT, type="supergroup"),
        text="Заявка",
        html_text="Заявка",
        edit_text=edit_text,
    )
    callback = SimpleNamespace(
        data=f"give_link:{APPLICANT}",
        from_user=SimpleNamespace(id=1, full_name="Админ", username="admin"),
        message=message,
        answer=answer,
    )
    return callback, answers, edits


def test_дать_ссылку_видит_бронь_выбранную_в_чате_ролей(monkeypatch):
    """Заявитель выбрал роль (пока не в группе — значит бронь) в чате ролей.
    «Дать ссылку» обязана это увидеть и выдать ссылку, а не писать
    «Заявитель ещё не выбрал роль»."""
    _setup_roles(monkeypatch)
    sent = _capture_send(monkeypatch)
    monkeypatch.setitem(bot_module.settings, "invite_link", "https://t.me/+test")
    monkeypatch.setattr(bot_module, "is_admin", lambda user_id: True)

    reservation = {"id": 501, "name": "Рей Аянами", "status": "reserved"}

    async def get_user_reservation(chat_id, user_id):
        return reservation if chat_id == ROLES_CHAT else None

    monkeypatch.setattr(bot_module.db, "get_user_role", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "get_user_reservation", get_user_reservation)
    monkeypatch.setattr(bot_module.db, "get_anchor_message_id", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "add_log", _async_noop)

    callback, answers, _edits = _give_link_callback()
    asyncio.run(bot_module.handle_give_link(callback))

    assert [s["chat_id"] for s in sent] == [APPLICANT], (
        "ссылка заявителю не отправлена — гейт ролей ошибочно сработал: "
        f"{answers}"
    )
    assert not any("не выбрал роль" in (a["text"] or "") for a in answers), answers


def test_дать_ссылку_блокируется_если_роль_не_выбрана_нигде(monkeypatch):
    """Обратная сторона: без роли и брони ссылку по-прежнему не выдаём."""
    _setup_roles(monkeypatch)
    sent = _capture_send(monkeypatch)
    monkeypatch.setitem(bot_module.settings, "invite_link", "https://t.me/+test")
    monkeypatch.setattr(bot_module, "is_admin", lambda user_id: True)
    monkeypatch.setattr(bot_module.db, "get_user_role", _async_returns(None))
    monkeypatch.setattr(bot_module.db, "get_user_reservation", _async_returns(None))

    callback, answers, _edits = _give_link_callback()
    asyncio.run(bot_module.handle_give_link(callback))

    assert any("не выбрал роль" in (a["text"] or "") for a in answers), answers
    # Ссылку не отправили; вместо неё заявителю повторно ушёл выбор роли.
    assert not any("t.me/+test" in (s["text"] or "") for s in sent), sent
