"""Переписыватель вызовов: убрать первый параметр chat_id.

Правок четыре тысячи. Руками их не сделать, а скриптом на регулярках — опасно:
«chat_id» встречается и там, где он ОСТАЁТСЯ (отправка в телеграм, настройки,
заслон чатов), и правка по имени переписала бы и их.

Поэтому правится по разбору кода, а всё, в чём скрипт не уверен, он
отказывается трогать и печатает списком: скрипт, который додумывает в спорном
месте, ломает молча — а молчаливых поломок в четырёх тысячах правок и надо
бояться больше всего.
"""

from __future__ import annotations

from tools import rewrite_chat_id as r


def test_находит_функции_с_чатом_первым():
    код = (
        "async def get_wallet(chat_id: int, user_id: int) -> dict: ...\n"
        "async def fetch_settings() -> dict: ...\n"
        "async def add_log(kind: str, chat_id: int = 0) -> None: ...\n"
    )
    # add_log сюда не попадает: у неё чат не первый, и убирать его вслепую
    # значило бы сдвинуть остальные аргументы.
    assert r.функции_с_чатом(код) == {"get_wallet"}


def test_убирает_параметр_из_объявления():
    код = "async def get_wallet(chat_id: int, user_id: int) -> dict:\n    pass\n"
    новый = r.убрать_параметр(код, {"get_wallet"})
    assert "async def get_wallet(user_id: int) -> dict:" in новый


def test_объявление_в_несколько_строк():
    """В db.py длинные сигнатуры разбиты по строкам — самый частый случай."""
    код = (
        "async def add_business(\n"
        "    chat_id: int, user_id: int, key: str, now\n"
        ") -> bool:\n    pass\n"
    )
    новый = r.убрать_параметр(код, {"add_business"})
    assert "chat_id" not in новый
    assert "user_id: int, key: str, now" in новый


def test_убирает_первый_аргумент_из_вызова():
    код = "x = await db.get_wallet(chat_id, user_id)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert новый == "x = await db.get_wallet(user_id)\n"
    assert not отказы


def test_понимает_разные_виды_первого_аргумента():
    for первый in ("chat_id", "chat.id", "message.chat.id",
                   "callback.message.chat.id", "event.chat.id", "-100123"):
        код = f"await db.get_wallet({первый}, 7)\n"
        новый, отказы, _ = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
        assert новый.strip() == "await db.get_wallet(7)", первый
        assert not отказы, первый


def test_вызов_с_одним_аргументом():
    код = "n = await db.count_businesses(chat_id)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"count_businesses"}, {"db"})
    assert новый == "n = await db.count_businesses()\n"


def test_вызов_в_несколько_строк():
    код = (
        "await db.set_business_level(\n"
        "    chat_id, user_id, item.key, level + 1, pending,\n"
        "    datetime.utcnow())\n"
    )
    новый, отказы, _ = r.убрать_аргумент(код, {"set_business_level"}, {"db"})
    assert "chat_id" not in новый
    assert "user_id, item.key" in новый
    assert not отказы


def test_вложенные_скобки_не_путают_разбор():
    """Первый аргумент — чат, а внутри следующих есть запятые и скобки."""
    код = "await db.add_coins(chat_id, max(1, round(x / 2)), note)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"add_coins"}, {"db"})
    assert новый == "await db.add_coins(max(1, round(x / 2)), note)\n"
    assert not отказы


def test_чужие_вызовы_не_трогает():
    """bot.send_message(chat_id, …) обязан остаться: телеграму чат нужен."""
    код = "await bot.send_message(chat_id, text)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"send_message"}, {"db"})
    assert новый == код


def test_непонятный_первый_аргумент_это_отказ():
    """Скрипт, который додумывает в спорном месте, ломает молча."""
    код = "await db.get_wallet(выбрать_чат(x), 7)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert новый == код
    assert отказы and "get_wallet" in отказы[0]


def test_именованный_первый_аргумент_это_отказ():
    """chat_id=… переставляет смысл: убирать вслепую нельзя."""
    код = "await db.get_wallet(chat_id=x, user_id=7)\n"
    новый, отказы, _ = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert новый == код and отказы


def test_считает_переписанные_вызовы():
    """Отчёту нужно число правок. Разницей строк его не получить:
    многострочный вызов схлопывается и сдвигает всё ниже, и одна правка
    выглядит как тысяча."""
    код = ("await db.get_wallet(chat_id, 1)\n"
           "await db.get_wallet(chat_id, 2)\n"
           "await db.get_wallet(выбрать(x), 3)\n")
    _новый, отказы, правок = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert правок == 2 and len(отказы) == 1
