"""Счётчики сообщений считают ВСЕ сообщения группы, включая команды rel2.

Болезнь была тихая: relationships_v2.router подключён к диспетчеру раньше
основного, а счётчики висели на основном. Всё, что разбирал rel2 — «дом»,
«отн», «рб» и их формы, — до счётчиков не доходило. Человек, игравший в дом и
питомцев весь день, оставался в чате с нулём сообщений: ни в /топ, ни в
профиле, ни в очках сезона его активности не было.

Проверяем не «функцию вызвали», а три свойства разом: считается ли то, что
разбирает rel2; считается ли РОВНО ОДИН РАЗ; и по-прежнему ли не считается
спам, который сейчас удалит фильтр мата.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _сообщение(text: str, user_id: int = USER_ID) -> Message:
    return Message(
        message_id=7,
        date=datetime.now(),
        chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=user_id, is_bot=False, first_name="Тестер"),
        text=text,
    )


@pytest.fixture
def посчитано(monkeypatch):
    """Подменяет всё, во что упирается подсчёт, и возвращает список посчитанных."""
    считанные: list[int] = []

    async def increment_message_count(chat_id, user_id):
        считанные.append(user_id)

    async def noop(*args, **kwargs):
        return None

    for имя in ("increment_daily_count", "increment_hourly_count", "upsert_known_user",
                "upsert_current_user", "clear_unreg"):
        monkeypatch.setattr(bot_module.db, имя, noop, raising=False)
    monkeypatch.setattr(bot_module.db, "increment_message_count", increment_message_count)
    monkeypatch.setattr(bot_module, "_add_season_points", noop, raising=False)
    monkeypatch.setattr(bot_module, "check_message_achievements", noop, raising=False)
    monkeypatch.setattr(bot_module, "_remember_recent_message", noop, raising=False)
    monkeypatch.setattr(bot_module, "RSTICK_CHANCE", 0.0)
    return считанные


async def _дальше(event, data):
    return "ok"


def _прогнать(text: str, user_id: int = USER_ID):
    """Через ВСЕ middleware диспетчера — так же, как пойдёт живое сообщение."""
    async def run():
        цепочка = _дальше
        for mw in reversed(list(bot_module.dp.message.outer_middleware)):
            цепочка = (lambda сл, м: lambda e, d: м(сл, e, d))(цепочка, mw)
        return await цепочка(_сообщение(text, user_id), {})
    return asyncio.run(run())


@pytest.mark.parametrize("text", [
    "дом",
    "дом купить cottage",
    "отн пт карта 5",
    "просто болтовня",
    "!ограбить",
])
def test_считается_всё_включая_команды_rel2(посчитано, text):
    """Главное свойство: счётчик не зависит от того, какой роутер разберёт
    сообщение. «дом» — такое же сообщение в чате, как «привет»."""
    assert _прогнать(text) == "ok"
    assert посчитано == [USER_ID], f"{text!r} не посчитано"


def test_сообщение_считается_ровно_один_раз(посчитано):
    """Ловушка «повесить ту же middleware на второй роутер»: внешняя middleware
    срабатывает на входе события в роутер, до фильтров, — и сообщение, которое
    rel2 не взял, посчиталось бы дважды. Здесь это закреплено числом."""
    _прогнать("привет всем")
    assert посчитано == [USER_ID], "двойной подсчёт"


def test_спам_из_фильтра_не_считается(посчитано, monkeypatch):
    """Правило старое и сохранено намеренно: то, что через мгновение удалит
    фильтр мата, не должно попадать в статистику. Раньше это держалось
    порядком вызовов в одной middleware, теперь — общей проверкой."""
    monkeypatch.setattr(bot_module, "word_filter_hit", lambda event: "мат")

    assert _прогнать("плохое слово") == "ok", "обработчики должны отработать как обычно"
    assert посчитано == [], "спам посчитан в статистику"


def test_проверка_на_спам_ничего_не_удаляет(monkeypatch):
    """word_filter_hit обязана остаться чистой: удаление и запись в лог —
    дело _enforce_word_filter, который живёт на роутере и там же остался.

    Синхронность здесь и есть доказательство: ни удалить сообщение, ни
    сходить в базу без await нельзя.
    """
    assert not asyncio.iscoroutinefunction(bot_module.word_filter_hit)

    monkeypatch.setattr(bot_module, "WORD_FILTER", {"мат"})
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)
    assert bot_module.word_filter_hit(_сообщение("мат")) == "мат"
    assert bot_module.word_filter_hit(_сообщение("вежливо")) is None


def test_админа_фильтр_не_касается_и_считает_как_обычно(посчитано, monkeypatch):
    """Освобождение админов живёт в той же проверке — значит, его сообщение со
    словом из фильтра и не удаляется, и по-прежнему считается."""
    monkeypatch.setattr(bot_module, "WORD_FILTER", {"мат"})
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: True)

    _прогнать("мат")
    assert посчитано == [USER_ID]


def test_фильтр_и_медленный_режим_остались_на_роутере():
    """Их сознательно НЕ переносили: распространить модерацию на команды rel2 —
    это смена правил чата, а не починка статистики."""
    на_диспетчере = [type(m).__name__ for m in bot_module.dp.message.outer_middleware]
    на_роутере = [type(m).__name__ for m in bot_module.router.message.outer_middleware]

    assert "MessageStatsMiddleware" in на_диспетчере
    assert "MessageGuardMiddleware" in на_роутере
    assert "MessageGuardMiddleware" not in на_диспетчере


def test_статистика_идёт_раньше_очистки():
    """Порядок регистрации, а не вкус: внутри статистики есть create_task на
    случайный стикер, а задача уносит копию контекста. Встань она внутрь
    контекста очистки — стикер удалялся бы вместе с командой."""
    имена = [type(m).__name__ for m in bot_module.dp.message.outer_middleware]
    assert имена.index("MessageStatsMiddleware") < имена.index("CommandCleanupMiddleware")
