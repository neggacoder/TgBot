"""«Предложить действие» — матчинг триггера и отправка предложения.

Похоже на РП-действия (bot.py:handle_rp_action), но с обязательным префиксом
«предложить» и таблицей ожидания ответа (propose_requests) вместо мгновенного
выполнения.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from types import SimpleNamespace

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


def _set_propose_synonyms(monkeypatch, synonyms: dict[str, str]) -> None:
    """Как и RP_ACTION_SYNONYMS/_RP_ACTION_ALL_KEYS в test_bot_routing.py:
    _match_propose_action_prefix ходит не в PROPOSE_ACTION_SYNONYMS напрямую,
    а в производный отсортированный кэш _PROPOSE_ACTION_ALL_KEYS (заполняется
    в load_caches()/refresh_propose_caches(), которые тесты не вызывают) —
    поэтому его нужно подменять вместе с самим словарём синонимов."""
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", synonyms)
    monkeypatch.setattr(
        bot_module, "_PROPOSE_ACTION_ALL_KEYS",
        sorted(synonyms.keys(), key=lambda k: len(k.split()), reverse=True),
    )


def _make(text, reply_from_id=None):
    replied = None
    if reply_from_id is not None:
        replied = Message(
            message_id=2, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=reply_from_id, is_bot=False, first_name="Партнёр"), text="привет",
        )
    m = Message(
        message_id=3, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=555, is_bot=False, first_name="Инициатор"), text=text,
        reply_to_message=replied,
    )
    sent = []

    async def fake_answer(t, **kwargs):
        sent.append((t, kwargs))
        return SimpleNamespace(message_id=999)  # id отправленного сообщения

    async def fake_reply(t, **kwargs):
        # Настоящий Message.reply() строит SendMessage независимо от .answer()
        # и требует привязанный Bot (падает в тестах без него) — поэтому
        # патчим и его тем же фиктивным приёмником (см. test_bot_routing.py,
        # где .reply патчится отдельно от .answer тем же способом).
        sent.append((t, kwargs))
        return SimpleNamespace(message_id=999)

    object.__setattr__(m, "answer", fake_answer)
    object.__setattr__(m, "reply", fake_reply)
    return m, sent


@pytest.mark.parametrize(
    "text,expected_key,expected_n",
    [
        ("предложить ромашка", "romashka", 2),
        ("предложить погадать на ромашке", "romashka", 4),
        ("предложить дуэль на щелбанчики", "schelbany", 4),
        ("предложить искать клад", "klad", 3),
        ("предложить полить цветы", None, None),  # не из дефолтного списка — не матчится
    ],
)
def test_матчинг_многословных_синонимов(monkeypatch, text, expected_key, expected_n):
    _set_propose_synonyms(monkeypatch, {
        "ромашка": "romashka", "погадать на ромашке": "romashka",
        "дуэль на щелбанчики": "schelbany", "искать клад": "klad",
    })
    result = bot_module._match_propose_action_prefix(text)
    if expected_key is None:
        assert result is None
    else:
        assert result == (expected_key, expected_n)


def test_регистр_и_лишние_пробелы_не_мешают(monkeypatch):
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})
    assert bot_module._match_propose_action_prefix("ПРЕДЛОЖИТЬ   Ромашка") == ("romashka", 2)


def test_без_префикса_предложить_не_матчится(monkeypatch):
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})
    assert bot_module._match_propose_action_prefix("ромашка") is None


def test_отправка_предложения_по_reply(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["{actor} зовёт {target} гадать на ромашке 🌼"],
                     "agree": ["ok"], "decline": ["no"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})

    async def display_name_link(chat_id, u):
        return getattr(u, "full_name", None) or getattr(u, "first_name", "N")

    async def check_and_touch_propose_cooldown(*a, **k):
        return None

    created = {}
    message_id_updates = {}

    async def create_or_replace_propose_request(chat_id, message_id, action_key, from_user_id, to_user_id):
        created.update(chat_id=chat_id, message_id=message_id, action_key=action_key,
                       from_user_id=from_user_id, to_user_id=to_user_id)
        return 42

    async def set_propose_request_message_id(request_id, message_id):
        message_id_updates.update(request_id=request_id, message_id=message_id)

    monkeypatch.setattr(bot_module, "display_name_link", display_name_link)
    monkeypatch.setattr(bot_module.db, "check_and_touch_propose_cooldown", check_and_touch_propose_cooldown)
    monkeypatch.setattr(bot_module.db, "create_or_replace_propose_request", create_or_replace_propose_request)
    monkeypatch.setattr(bot_module.db, "set_propose_request_message_id", set_propose_request_message_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложить ромашка", reply_from_id=777)
    asyncio.run(bot_module.handle_propose_action(m))

    assert sent, "бот должен был отправить сообщение с предложением"
    text, kwargs = sent[0]
    assert "гадать на ромашке" in text
    kb = kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data == "propose_yes:42"
    assert kb.inline_keyboard[0][1].callback_data == "propose_no:42"
    assert created == {
        "chat_id": CHAT_ID, "message_id": 0, "action_key": "romashka",
        "from_user_id": 555, "to_user_id": 777,
    }
    assert message_id_updates == {"request_id": 42, "message_id": 999}


def test_самому_себе_нельзя(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x {actor} {target}"], "agree": ["a"], "decline": ["d"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})
    m, sent = _make("предложить ромашка", reply_from_id=555)  # reply на самого себя
    asyncio.run(bot_module.handle_propose_action(m))
    assert sent and "сам" in sent[0][0].casefold()


def test_кулдаун_блокирует_повторное_предложение(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x {actor} {target}"], "agree": ["a"], "decline": ["d"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})

    async def check_and_touch_propose_cooldown(*a, **k):
        return 42  # 42 секунды ещё ждать

    monkeypatch.setattr(bot_module.db, "check_and_touch_propose_cooldown", check_and_touch_propose_cooldown)
    m, sent = _make("предложить ромашка", reply_from_id=777)
    asyncio.run(bot_module.handle_propose_action(m))
    assert sent and "42" in sent[0][0]


def test_неизвестное_действие_пропускается(monkeypatch):
    """action_key реально матчится (синоним есть), но его нет в PROPOSE_ACTIONS —
    должна сработать именно ветка `if action_key not in PROPOSE_ACTIONS: raise
    SkipHandler` в handle_propose_action, а не защитный `if matched is None`
    (для последнего — отдельный test_нераспознанный_текст_не_обрабатывается)."""
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {})
    _set_propose_synonyms(monkeypatch, {"ромашка": "romashka"})
    m, sent = _make("предложить ромашка", reply_from_id=777)
    with pytest.raises(SkipHandler):
        asyncio.run(bot_module.handle_propose_action(m))
    assert not sent


def test_нераспознанный_текст_не_обрабатывается(monkeypatch):
    """Прямой вызов хендлера без роутерного фильтра (см. комментарий в
    handle_propose_action) с текстом, для которого _match_propose_action_prefix
    вообще не находит совпадения (синонимов нет) — должен сработать `if matched
    is None: raise SkipHandler`. PROPOSE_ACTIONS намеренно непустой и содержит
    "romashka", чтобы показать: это другая ветка, чем в
    test_неизвестное_действие_пропускается — там как раз matched не None,
    а action_key просто отсутствует в PROPOSE_ACTIONS."""
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x {actor} {target}"], "agree": ["a"], "decline": ["d"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    _set_propose_synonyms(monkeypatch, {})  # ни одного синонима — матчиться нечему
    m, sent = _make("предложить ромашка", reply_from_id=777)
    with pytest.raises(SkipHandler):
        asyncio.run(bot_module.handle_propose_action(m))
    assert not sent


from aiogram.types import CallbackQuery  # noqa: E402


def _make_callback(data, from_user_id, chat_id=CHAT_ID, message_id=3):
    msg = Message(
        message_id=message_id, date=datetime.now(), chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=1, is_bot=True, first_name="Бот"), text="{actor} зовёт {target}...",
    )
    edits = []

    async def fake_edit_text(text, **kwargs):
        edits.append(text)

    object.__setattr__(msg, "edit_text", fake_edit_text)

    cb = CallbackQuery(
        id="1", from_user=User(id=from_user_id, is_bot=False, first_name="U"),
        chat_instance="ci", data=data, message=msg,
    )
    answers = []

    async def fake_answer(text=None, **kwargs):
        answers.append((text, kwargs.get("show_alert", False)))

    object.__setattr__(cb, "answer", fake_answer)
    return cb, edits, answers


def _propose_request_row(**overrides):
    row = {
        "id": 42, "chat_id": CHAT_ID, "message_id": 3, "action_key": "romashka",
        "from_user_id": 555, "to_user_id": 777, "created_at": datetime.utcnow(),
    }
    row.update(overrides)
    return row


def test_согласие_редактирует_сообщение_и_чистит_запись(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x"], "agree": ["Есть контакт! {target} и {actor} гадают 🌼"],
                     "decline": ["no"], "cooldown_seconds": 300, "timeout_seconds": 120},
    })

    async def get_propose_request(request_id):
        assert request_id == 42
        return _propose_request_row()

    deleted = {}

    async def delete_propose_request(request_id):
        deleted["id"] = request_id
        return True

    async def display_name_by_id(chat_id, user_id):
        return "N"

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", delete_propose_request)
    monkeypatch.setattr(bot_module, "display_name_by_id", display_name_by_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    cb, edits, answers = _make_callback("propose_yes:42", from_user_id=777)
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert edits and "Есть контакт" in edits[0]
    assert deleted == {"id": 42}
    assert answers


def test_отказ_редактирует_сообщение(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x"], "agree": ["ok"], "decline": ["{target} отказывает {actor} 🥀"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })

    async def get_propose_request(request_id):
        return _propose_request_row()

    async def display_name_by_id(chat_id, user_id):
        return "N"

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", lambda request_id: asyncio.sleep(0, result=True))
    monkeypatch.setattr(bot_module, "display_name_by_id", display_name_by_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    cb, edits, answers = _make_callback("propose_no:42", from_user_id=777)
    asyncio.run(bot_module.propose_no_callback(cb))

    assert edits and "отказывает" in edits[0]


def test_чужой_клик_не_меняет_состояние(monkeypatch):
    async def get_propose_request(request_id):
        return _propose_request_row()  # to_user_id=777

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)

    cb, edits, answers = _make_callback("propose_yes:42", from_user_id=999)  # не 777
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert not edits
    assert answers and answers[0][1] is True  # show_alert=True
    assert "не вам" in answers[0][0]


def test_несуществующая_или_протухшая_заявка(monkeypatch):
    async def get_propose_request(request_id):
        return None

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)

    cb, edits, answers = _make_callback("propose_yes:999", from_user_id=777)
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert not edits
    assert answers and "не активно" in answers[0][0].casefold()


def test_просроченный_запрос_обрабатывается_фоновым_лупом(monkeypatch):
    from datetime import timedelta

    processed = []

    async def list_expired_propose_requests(now):
        return [{
            "id": 42, "chat_id": CHAT_ID, "message_id": 3, "action_key": "romashka",
            "from_user_id": 555, "to_user_id": 777,
            "created_at": now - timedelta(seconds=999),
        }]

    async def delete_propose_request(request_id):
        processed.append(request_id)
        return True

    class FakeBot:
        def __init__(self):
            self.edits = []

        async def edit_message_text(self, chat_id, message_id, text, **kwargs):
            self.edits.append((chat_id, message_id, text))

    fake_bot = FakeBot()
    monkeypatch.setattr(bot_module, "bot", fake_bot)
    monkeypatch.setattr(bot_module.db, "list_expired_propose_requests", list_expired_propose_requests)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", delete_propose_request)

    n = asyncio.run(bot_module._process_expired_propose_requests())

    assert n == 1
    assert processed == [42]
    assert fake_bot.edits and "устарело" in fake_bot.edits[0][2].casefold()
