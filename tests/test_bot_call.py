"""Отклик на «Бот».

Одна и та же фраза на каждый зов читается как автоответчик: человек зовёт
бота десять раз в день и десять раз получает «На месте!». Набор фраз делает
из этого живую реакцию, а ответ НА сообщение — понятно, кого именно позвали,
когда в чате говорят трое.
"""

from __future__ import annotations

import asyncio
import functools
import os
import random

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


class _Сообщение:
    def __init__(self, text):
        self.text = text
        self.date = None
        self.chat = type("C", (), {"id": -100, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": 7, "is_bot": False,
                                        "full_name": "Тест", "username": "t"})()
        self.ответы = []
        self.просто = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)

    async def answer(self, text, **kwargs):
        self.просто.append(text)


@pytest.fixture(autouse=True)
def доступ(monkeypatch):
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)

    async def ник(chat_id, user_id):
        return "Лина-Ромашка"

    monkeypatch.setattr(bot_module.db, "get_nickname", ник, raising=False)


def test_фраз_на_зов_много_и_они_разные():
    """Одна фраза на все случаи — это автоответчик, а не бот."""
    assert len(bot_module.BOT_CALL_REPLIES) >= 5
    assert len(set(bot_module.BOT_CALL_REPLIES)) == len(bot_module.BOT_CALL_REPLIES)
    assert any("Тутачки" in ф for ф in bot_module.BOT_CALL_REPLIES)
    assert not any("Слушаю" in ф for ф in bot_module.BOT_CALL_REPLIES)


@_sync
async def test_на_зов_отвечает_одной_из_фраз(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    m = _Сообщение("Бот")
    await bot_module.cmd_misc_ping(m)
    assert m.ответы, "ответа нет вовсе"
    assert m.ответы[0].endswith(bot_module.BOT_CALL_REPLIES[0])


@_sync
async def test_зов_обращается_к_позвавшему_кликабельно(monkeypatch):
    """Обращение по имени и ссылкой: видно, кому бот отвечает, даже когда
    сообщение пролистали и цитата свернулась."""
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    m = _Сообщение("Бот")
    await bot_module.cmd_misc_ping(m)
    ответ = m.ответы[0]
    первая, вторая = ответ.split("\n", 1)
    assert первая.startswith("<a href=") and первая.endswith(",")
    # Ник этого чата, а не имя из телеграма: в РП-действиях человек
    # подписан ником, и в ответе на зов он должен быть тем же.
    assert "Лина-Ромашка" in первая and "Тест" not in первая
    assert вторая == bot_module.BOT_CALL_REPLIES[0]


@_sync
async def test_зов_цитирует_сообщение():
    """В чате, где говорят трое, ответ без цитаты не показывает, кого позвали."""
    m = _Сообщение("бот")
    await bot_module.cmd_misc_ping(m)
    assert m.ответы and not m.просто, "ответ должен быть цитатой, а не в пустоту"


@_sync
async def test_зов_не_считает_миллисекунды():
    """«Тутачки (240 мс)» — это уже не разговор, а телеметрия."""
    m = _Сообщение("Бот")
    await bot_module.cmd_misc_ping(m)
    assert "мс" not in m.ответы[0]


@_sync
async def test_пинг_остался_пингом():
    """Понг с задержкой — смысл самой команды, его не трогаем."""
    m = _Сообщение("пинг")
    await bot_module.cmd_misc_ping(m)
    получено = (m.ответы + m.просто)[0]
    assert "Понг" in получено


@_sync
async def test_прозвища_бота_отвечают_так_же(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    for зов in ("хуйло", "хуйлан"):
        m = _Сообщение(зов)
        await bot_module.cmd_misc_ping(m)
        assert m.ответы[0].endswith(bot_module.BOT_CALL_REPLIES[0]), зов


@_sync
async def test_без_ника_подставляется_имя_из_телеграма(monkeypatch):
    """Ник задан не у всех — тогда остаётся имя, а не пустая ссылка."""
    async def без_ника(chat_id, user_id):
        return None

    monkeypatch.setattr(bot_module.db, "get_nickname", без_ника, raising=False)
    m = _Сообщение("Бот")
    await bot_module.cmd_misc_ping(m)
    assert "Тест" in m.ответы[0].split("\n", 1)[0]
