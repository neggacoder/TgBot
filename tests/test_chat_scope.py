"""Бот работает только в своём чате.

Игры, экономика, репутация и весь остальной разговор бота отвечали в ЛЮБОЙ
группе, куда его добавили. Из-за этого же в shop_items копились чужие чаты, и
ежедневный завоз объявлялся столько раз, сколько их набралось.

Решение — заслон на входе, но не «глухая стена»: чат заявок и настроечные
команды обязаны продолжать работать, иначе бота нельзя ни перепривязать, ни
пользоваться заявками.

Проверяется здесь в первую очередь ПРЕДИКАТ, потому что handler.check() из
test_bot_routing.py middleware не исполняет и такого заслона не увидел бы
вовсе. Ниже — сама middleware и её место в очереди: верный предикат в
неподключённой (или подключённой после статистики) middleware не работает.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЖАЛОБЫ = -1003673552861      # рабочий чат
ЗАЯВКИ = -1003811995090      # чат заявок — другой
ЧУЖОЙ = -1009999999999


@pytest.fixture(autouse=True)
def чаты(monkeypatch):
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЖАЛОБЫ)
    monkeypatch.setitem(bot_module.settings, "notify_chat_id", ЗАЯВКИ)


def можно(chat_id, chat_type="supergroup", text=None, ответ_боту=False):
    return bot_module.chat_scope_allows(chat_id, chat_type, text, ответ_боту)


def test_в_рабочем_чате_можно_всё():
    assert можно(ЖАЛОБЫ, text="баланс")
    assert можно(ЖАЛОБЫ, text="привет")


def test_в_чужой_группе_нельзя_ничего():
    assert not можно(ЧУЖОЙ, text="баланс")
    assert not можно(ЧУЖОЙ, text="магазин")
    assert not можно(ЧУЖОЙ, text="привет", ответ_боту=True)


def test_личка_не_трогается():
    """В личке живут панель админа, анкеты, анонимки и заявки на рест."""
    assert можно(555, chat_type="private", text="админка")


@pytest.mark.parametrize("фраза", ["чат сюда", "топик сюда", "жалобы сюда",
                                   "Жалобы Сюда", "  жалобы сюда  "])
def test_настроечные_команды_проходят_откуда_угодно(фраза):
    """Иначе бота нельзя перепривязать: заслон закрыл бы ту самую команду,
    которой меняют рабочий чат, и выйти из этого было бы нечем."""
    assert можно(ЧУЖОЙ, text=фраза)


def test_в_чате_заявок_ответ_админа_на_заявку_проходит():
    """handle_admin_reply пересылает заявителю ответ админа. Заявка — это
    сообщение БОТА, и ответ на неё обязан дойти."""
    assert можно(ЗАЯВКИ, text="Здравствуйте, вы приняты", ответ_боту=True)


def test_в_чате_заявок_обычная_болтовня_и_игры_не_работают():
    assert not можно(ЗАЯВКИ, text="баланс")
    assert not можно(ЗАЯВКИ, text="магазин")


def test_в_чате_заявок_ответ_на_сообщение_человека_не_пропуск_для_игр():
    """Иначе экономика осталась бы работать в чате заявок целиком: ответил на
    сообщение соседа — и команда прошла."""
    assert not можно(ЗАЯВКИ, text="баланс", ответ_боту=False)


def test_без_привязанного_чата_бот_не_превращается_в_кирпич(monkeypatch):
    """На свежей установке complaint_chat_id пуст. Закройся заслон и здесь —
    бота нельзя было бы настроить вообще ничем."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", None)
    assert можно(ЧУЖОЙ, text="баланс")


def test_кнопки_работают_в_рабочем_чате_и_в_заявках():
    """У заявки есть кнопки «принять/отклонить», и живут они в чате заявок."""
    assert bot_module.callback_scope_allows(ЖАЛОБЫ, "supergroup")
    assert bot_module.callback_scope_allows(ЗАЯВКИ, "supergroup")
    assert bot_module.callback_scope_allows(555, "private")
    assert not bot_module.callback_scope_allows(ЧУЖОЙ, "supergroup")


def test_подпись_к_фото_тоже_считается_текстом():
    """Команды приходят подписью к фото (см. тест про «созыв»), и настроечная
    фраза не должна теряться из-за того, что она в caption."""
    assert можно(ЧУЖОЙ, text="жалобы сюда")
    assert not можно(ЧУЖОЙ, text=None)


# ---------------------------------------------------------------------------
# Сама middleware, а не только предикат: предикат может быть верным, а
# заслон — не подключённым или подключённым после статистики.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

from aiogram.types import Chat, Message, User  # noqa: E402


def _сообщение(chat_id, text="баланс", chat_type="supergroup", ответ_на=None):
    kw = {}
    if ответ_на is not None:
        kw["reply_to_message"] = Message(
            message_id=2, date=datetime.now(),
            chat=Chat(id=chat_id, type=chat_type),
            from_user=User(id=42, is_bot=ответ_на == "бот", first_name="Кто-то"),
            text="заявка" if ответ_на == "бот" else "реплика соседа",
        )
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=User(id=555, is_bot=False, first_name="Тестер"),
        text=text, **kw,
    )


def _прошло(msg):
    дошло = []

    async def handler(event, data):
        дошло.append(event)
        return "обработано"

    asyncio.run(bot_module.ChatScopeMiddleware()(handler, msg, {}))
    return bool(дошло)


def test_middleware_пропускает_рабочий_чат_и_режет_чужой():
    assert _прошло(_сообщение(ЖАЛОБЫ))
    assert not _прошло(_сообщение(ЧУЖОЙ))
    assert not _прошло(_сообщение(ЗАЯВКИ))
    assert _прошло(_сообщение(ЧУЖОЙ, text="жалобы сюда"))


def test_middleware_различает_кому_отвечают_в_чате_заявок():
    """Ответ на заявку (сообщение бота) проходит, ответ на соседа — нет."""
    assert _прошло(_сообщение(ЗАЯВКИ, text="вы приняты", ответ_на="бот"))
    assert not _прошло(_сообщение(ЗАЯВКИ, text="баланс", ответ_на="человек"))


def test_заслон_стоит_раньше_статистики_и_очистки():
    """В чужом чате не должно быть ни счётчиков сообщений, ни планов на
    удаление. Обе middleware висят на диспетчере, и порядок регистрации здесь
    и есть порядок исполнения."""
    имена = [type(m).__name__ for m in bot_module.dp.message.outer_middleware]
    assert "ChatScopeMiddleware" in имена, имена
    assert имена.index("ChatScopeMiddleware") < имена.index("MessageStatsMiddleware"), имена
    assert имена.index("ChatScopeMiddleware") < имена.index("CommandCleanupMiddleware"), имена
