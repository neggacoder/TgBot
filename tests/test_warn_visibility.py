"""Что видно в чате после варна — и что приходит модератору в личку.

Две вещи, которые ломаются молча:

* Наказания (варн, мут, бан и их снятие) не должны попадать под автоочистку:
  через час после неё нечем подтвердить, за что человека наказали.
* Обманный варн обязан вести себя в чате ТАК ЖЕ, как настоящий. Оставь
  чистку только настоящим — и розыгрыш начнёт исчезать через 15 минут, а
  настоящие варны оставаться. Это выдаёт шутку вернее любого амперсанда.
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


# --- наказания переживают автоочистку --------------------------------------

@pytest.mark.parametrize("text", [
    "варн @kto спам", "ВАРН @KTO", "!варн @kto", "-варн @kto", "варн- @kto",
    "мут 3ч @kto", "-мут @kto", "размут @kto",
    "бан @kto навсегда", "-бан @kto", "разбан @kto",
])
def test_наказания_не_чистятся(text):
    """След наказания обязан остаться в чате: иначе спор «за что меня
    наказали» восстановить будет нечем."""
    assert bot_module.is_cleanup_exempt(text), text


@pytest.mark.parametrize("text", ["&варн @kto", "&-варн @kto", "&варн- @kto"])
def test_обманный_варн_не_чистится_наравне_с_настоящим(text):
    """Сердце маскировки: если розыгрыш исчезает, а настоящий варн остаётся,
    подделка видна по одному тому, что сообщение пропало."""
    assert bot_module.is_cleanup_exempt(text), text


@pytest.mark.parametrize("text", [
    "банк", "банк чс", "баны", "банлист", "варны", "&варны",
    "мутный какой-то тип", "варнинг чата", "ферма", "помощь",
])
def test_соседние_команды_и_обычная_речь_чистятся_как_прежде(text):
    """Исключение должно быть узким: «банк» и «баны» — не наказания."""
    assert not bot_module.is_cleanup_exempt(text), text


def test_перевод_остался_в_исключениях():
    """Он был там до наказаний — расширение списка не должно его потерять."""
    assert bot_module.is_cleanup_exempt("перевод 500 @kto")
    assert bot_module.is_cleanup_exempt("перевести 500 @kto")


# --- письмо модератору в личку ---------------------------------------------

class _FakeMessage:
    def __init__(self, actor_id=555):
        self.from_user = type("U", (), {"id": actor_id})()


@pytest.fixture
def dm(monkeypatch):
    """Ловим, что ушло в личку и кому."""
    sent: list = []

    async def send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    return sent


def test_про_обманный_варн_пишут_что_он_обманный(dm):
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(), "Жертва", fake=True, count=2))
    assert dm and dm[0][0] == 555, "письмо уходит выдавшему, а не жертве"
    assert "ОБМАННЫЙ" in dm[0][1]
    assert "Жертва" in dm[0][1]


def test_про_настоящий_варн_пишут_что_он_настоящий(dm):
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(), "Жертва", fake=False, count=1))
    assert "НАСТОЯЩИЙ" in dm[0][1]
    assert "ОБМАННЫЙ" not in dm[0][1]


def test_письмо_уходит_именно_выдавшему(dm):
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(actor_id=999), "Жертва", fake=True, count=1))
    assert dm[0][0] == 999


def test_закрытая_личка_не_ломает_выдачу(monkeypatch):
    """И, что важнее, не заставляет бота писать в чат: это выдало бы шутку."""
    from aiogram.exceptions import TelegramForbiddenError

    async def forbidden(*a, **k):
        raise TelegramForbiddenError(method=None, message="blocked")

    monkeypatch.setattr(bot_module.bot, "send_message", forbidden, raising=False)
    # Не должно бросить исключение наружу.
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(), "Жертва", fake=True, count=1))


def test_в_письме_видно_сколько_всего_варнов(dm):
    """Модератору важно не только «какой», но и «сколько» — иначе он добьёт
    человека настоящим третьим варном по ложному следу."""
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(), "Жертва", fake=True, count=2))
    assert "2" in dm[0][1]
