"""Рубильники владельца: «+бесконечность» из чата и с сайта.

Три места, ради которых эти проверки и написаны.

ПРОПУЩЕННЫЙ AWAIT — ЭТО БЕСКОНЕЧНОСТЬ ДЛЯ ВСЕХ. Проверка стала асинхронной, а
вызовов у неё восемь. Забудь `await` в одном — и выражение вернёт объект
корутины, который ИСТИНЕН всегда: списание монет начнёт проходить у каждого.
Питон предупредит про «coroutine was never awaited», но это предупреждение
утонет среди полутора тысяч других. Поэтому проверка структурная.

ПАМЯТЬ ПРОЦЕССА НЕ ГОДИТСЯ. Список жил множеством в памяти бота и читался из
базы один раз при запуске. Со вторым входом — кнопкой на сайте — это молча
разъезжается: панель пишет в базу, бот смотрит в своё множество, кнопка
выглядит сработавшей, а деньги списываются как раньше.

ЧТЕНИЕ ПЕРЕД ЗАПИСЬЮ. Значение общее на всех владельцев. Тот, кто пишет из
своего снимка, затирает чужие включения.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib
import re

import pytest

import owner_flags


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка bot_data: одна строка по ключу."""

    def __init__(self, значение=None):
        self.данные = {} if значение is None else {owner_flags.INFINITE_MONEY_KEY: значение}
        self.записей = 0
        self.падать = False

    async def get_data(self, key):
        if self.падать:
            raise RuntimeError("база недоступна")
        значение = self.данные.get(key)
        return {"data_key": key, "data_value": значение} if значение is not None else None

    async def set_data(self, key, value, updated_by=None):
        self.записей += 1
        self.данные[key] = value


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(owner_flags, "db", w)
    return w


# --- чтение -----------------------------------------------------------------

@_sync
async def test_пустой_список_это_никому(мир):
    assert await owner_flags.infinite_money_users() == set()
    assert await owner_flags.has_infinite_money(1) is False


@_sync
async def test_список_читается_из_базы(мир):
    мир.данные[owner_flags.INFINITE_MONEY_KEY] = "1,2,-3"
    assert await owner_flags.infinite_money_users() == {1, 2, -3}
    assert await owner_flags.has_infinite_money(2) is True
    assert await owner_flags.has_infinite_money(9) is False


@_sync
async def test_битая_запись_не_лишает_всех(мир):
    """В базе лежит текст. Одна испорченная запись не должна выключать
    рубильник у остальных."""
    мир.данные[owner_flags.INFINITE_MONEY_KEY] = "1, ,мусор,,2"
    assert await owner_flags.infinite_money_users() == {1, 2}


@_sync
async def test_недоступная_база_не_раздаёт_бесконечность(мир):
    """Безопасный исход тот, где бесконечных денег нет ни у кого."""
    мир.падать = True
    assert await owner_flags.has_infinite_money(1) is False


@_sync
async def test_пустой_идентификатор_это_нет(мир):
    """У аккаунта панели телеграма может не быть вовсе."""
    assert await owner_flags.has_infinite_money(None) is False
    assert await owner_flags.has_infinite_money(0) is False


# --- запись -----------------------------------------------------------------

@_sync
async def test_включение_и_выключение(мир):
    await owner_flags.set_infinite_money(5, True)
    assert await owner_flags.has_infinite_money(5) is True
    await owner_flags.set_infinite_money(5, False)
    assert await owner_flags.has_infinite_money(5) is False


@_sync
async def test_один_владелец_не_затирает_другого(мир):
    """Список общий. Тот, кто пишет из своего снимка, молча убирает чужих —
    и чужой рубильник просто перестаёт работать."""
    await owner_flags.set_infinite_money(1, True)
    await owner_flags.set_infinite_money(2, True)
    assert await owner_flags.infinite_money_users() == {1, 2}

    await owner_flags.set_infinite_money(2, False)
    assert await owner_flags.infinite_money_users() == {1}, "выключив себя, убрал чужого"


@_sync
async def test_выключение_отсутствующего_не_ломается(мир):
    await owner_flags.set_infinite_money(7, False)
    assert await owner_flags.infinite_money_users() == set()


# --- структура: то, что не увидишь поведением --------------------------------

ИСХОДНИК = pathlib.Path(__file__).resolve().parent.parent


def test_каждая_проверка_с_await():
    """Пропущенный await делает выражение объектом корутины, а он ИСТИНЕН
    всегда: `if has_infinite_money(x)` начнёт срабатывать у каждого, и
    списание монет перестанет работать во всём боте.

    Предупреждение питона про «coroutine was never awaited» тут не спасает:
    в прогоне их полторы тысячи, и одно новое незаметно."""
    текст = (ИСХОДНИК / "bot.py").read_text(encoding="utf-8")
    голые = []
    for номер, строка in enumerate(текст.split("\n"), 1):
        if "has_infinite_money(" not in строка:
            continue
        # Объявление-алиас: у него скобок вызова нет.
        if строка.startswith("has_infinite_money = "):
            continue
        if "await has_infinite_money(" not in строка:
            голые.append(f"bot.py:{номер} {строка.strip()[:70]}")
    assert not голые, "вызов без await — бесконечные деньги у всех:\n" + "\n".join(голые)


def test_множества_в_памяти_больше_нет():
    """Множество наполнялось один раз при запуске. Рубильник, нажатый на
    сайте, для бота не существовал бы до перезапуска — и понять это можно было
    бы только по балансу."""
    текст = (ИСХОДНИК / "bot.py").read_text(encoding="utf-8")
    assert "INFINITE_MONEY_USERS" not in текст, "множество в памяти вернулось"
    assert "owner_flags.has_infinite_money" in текст, "проверка снова своя"


def test_оба_входа_пишут_через_один_переключатель():
    """И команда в чате, и кнопка на сайте обязаны идти через
    set_infinite_money: он перечитывает список перед записью."""
    бот = (ИСХОДНИК / "bot.py").read_text(encoding="utf-8")
    панель = (ИСХОДНИК / "webpanel" / "app.py").read_text(encoding="utf-8")
    for имя, текст in (("бот", бот), ("панель", панель)):
        assert "owner_flags.set_infinite_money(" in текст, f"{имя} пишет список сам"
        assert 'db.set_data("infinite_money_users"' not in текст, (
            f"{имя} пишет ключ напрямую, мимо перечитывания")
        assert 'set_data(owner_flags.INFINITE_MONEY_KEY' not in текст, (
            f"{имя} пишет ключ напрямую, мимо перечитывания")


def test_рубильник_на_сайте_только_для_владельца():
    """Класс owner-only прячет карточку, но не охраняет её: гейт обязан
    стоять на сервере. Спрятанная кнопка — удобство, а не защита."""
    панель = (ИСХОДНИК / "webpanel" / "app.py").read_text(encoding="utf-8")
    кусок = панель[панель.index('@app.get("/api/owner/infinite-money")'):]
    кусок = кусок[:кусок.index('@app.get("/api/users")')]
    assert кусок.count("auth.require_owner") == 2, (
        "не оба эндпоинта рубильника закрыты владельческим гейтом")
    assert "auth.verify_csrf(request)" in кусок, "запись без проверки csrf"
    assert "user.tg_user_id is None" in кусок, (
        "не привязанному телеграму рубильник молча ничего не запишет")


def test_на_экране_сказано_почему_нельзя():
    """Отказ по факту нажатия читается как поломка, а не как правило."""
    js = (ИСХОДНИК / "webpanel" / "static" / "app.js").read_text(encoding="utf-8")
    # Срез строго по показывающей функции: в соседней (сохраняющей) слово
    # disabled тоже есть — она гасит флажок на время запроса, — и проверка
    # «просто есть disabled» засчитала бы её вместо нужной.
    кусок = js[js.index("async function loadInfiniteMoney"):
               js.index("async function saveInfiniteMoney")]
    assert "привяжите телеграм" in кусок.lower(), "не сказано, что делать без привязки"
    assert re.search(r"disabled\s*=\s*!\w+\.linked", кусок), (
        "переключатель нажимается и без привязки телеграма")
    html = (ИСХОДНИК / "webpanel" / "static" / "index.html").read_text(encoding="utf-8")
    карточка = re.search(r'<div class="card owner-only hidden" id="infinite-card">', html)
    assert карточка, "карточка рубильника видна не только владельцу"
