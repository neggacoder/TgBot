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


# --- доставка карточки: настоящий и обманный неотличимы ---------------------

class _Deliverable:
    """Сообщение-команда: умеет удаляться и знает, ответ это или нет."""

    def __init__(self, reply_to_id=None, can_delete=True):
        self.chat = type("C", (), {"id": -100500})()
        self.from_user = type("U", (), {"id": 555})()
        self.message_id = 10
        self.deleted = False
        self._can_delete = can_delete
        self.reply_to_message = (
            type("R", (), {"message_id": reply_to_id})() if reply_to_id else None
        )

    async def delete(self):
        if not self._can_delete:
            from aiogram.exceptions import TelegramBadRequest
            raise TelegramBadRequest(method=None, message="not enough rights")
        self.deleted = True


@pytest.fixture
def outbox(monkeypatch):
    sent: list = []

    async def send_message(chat_id, text, reply_to_message_id=None, **kwargs):
        sent.append({"chat_id": chat_id, "text": text,
                     "reply_to": reply_to_message_id})
        return type("M", (), {"message_id": 777, "chat": type("C", (), {"id": chat_id})()})()

    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    return sent


def test_команда_удаляется_а_карточка_остаётся(outbox):
    """То, ради чего всё затевалось: в чате не остаётся ни «варн», ни «&варн»."""
    msg = _Deliverable(reply_to_id=42)
    asyncio.run(bot_module._deliver_warn_card(msg, "карточка"))
    assert msg.deleted, "сообщение с командой обязано исчезнуть"
    assert outbox and outbox[0]["text"] == "карточка"


def test_карточка_отвечает_на_сообщение_нарушителя(outbox):
    msg = _Deliverable(reply_to_id=42)
    asyncio.run(bot_module._deliver_warn_card(msg, "карточка"))
    assert outbox[0]["reply_to"] == 42, "не на команду, а на само нарушение"


def test_без_ответа_карточка_уходит_обычным_сообщением(outbox):
    """Варн выдан по @username — отвечать не на что."""
    msg = _Deliverable(reply_to_id=None)
    asyncio.run(bot_module._deliver_warn_card(msg, "карточка"))
    assert outbox[0]["reply_to"] is None


def test_без_прав_на_удаление_карточка_всё_равно_уходит(outbox):
    """Иначе бот на слабых правах вообще перестал бы выдавать варны."""
    msg = _Deliverable(reply_to_id=42, can_delete=False)
    asyncio.run(bot_module._deliver_warn_card(msg, "карточка"))
    assert outbox, "карточка важнее, чем удаление команды"
    assert not msg.deleted


def test_карточка_уходит_до_удаления_команды(monkeypatch):
    """Порядок обязателен: удали команду первой — и Telegram не даст на неё
    сослаться, а при выдаче ответом ссылка нужна."""
    order: list = []

    async def send_message(chat_id, text, reply_to_message_id=None, **kwargs):
        order.append("send")
        return type("M", (), {"message_id": 777, "chat": type("C", (), {"id": chat_id})()})()

    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    msg = _Deliverable(reply_to_id=42)
    original_delete = msg.delete

    async def delete():
        order.append("delete")
        await original_delete()

    msg.delete = delete
    asyncio.run(bot_module._deliver_warn_card(msg, "карточка"))
    assert order == ["send", "delete"], order


def test_настоящий_и_обманный_варн_доставляются_одним_кодом():
    """Разойдись доставка хоть в мелочи — подделка видна без амперсанда.
    Поэтому обе команды обязаны звать один и тот же помощник."""
    import inspect
    real = inspect.getsource(bot_module.cmd_warn)
    fake = inspect.getsource(bot_module.cmd_fake_warn)
    assert "_deliver_warn_card" in real
    assert "_deliver_warn_card" in fake
    assert "message.reply(" not in fake, "своя отправка рано или поздно разойдётся"


def test_в_письме_видно_сколько_всего_варнов(dm):
    """Модератору важно не только «какой», но и «сколько» — иначе он добьёт
    человека настоящим третьим варном по ложному следу."""
    asyncio.run(bot_module._tell_moderator_warn_kind(
        _FakeMessage(), "Жертва", fake=True, count=2))
    assert "2" in dm[0][1]
