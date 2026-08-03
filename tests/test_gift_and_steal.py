"""Подарок пачкой и кулдаун медвежатника.

Обе правки об одном: действие, которое раньше было ровно на одну штуку,
теперь считает количество — а у кражи количество ограничено временем, а не
кошельком.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402


# --- сколько дарим --------------------------------------------------------

@pytest.mark.parametrize("хвост,ожидаем", [
    ("", 1),                 # без числа — одна штука, как было всегда
    ("   ", 1),
    ("@vasya", 1),           # только цель
    ("4", 4),
    ("@vasya 4", 4),
    ("4 @vasya", 4),
    (str(bot_module.SHOP_GIFT_MAX_QTY), bot_module.SHOP_GIFT_MAX_QTY),
])
def test_количество_разбирается(хвост, ожидаем):
    qty, err = bot_module._gift_quantity(хвост)
    assert not err, err
    assert qty == ожидаем


@pytest.mark.parametrize("хвост", ["0", "-3 @vasya", str(bot_module.SHOP_GIFT_MAX_QTY + 1), "2 3"])
def test_негодное_количество_отбивается(хвост):
    """«-3» число не даёт (isdigit ложь) и уезжает в цель — но ноль, перебор
    и два числа обязаны получить внятный отказ, а не молча стать единицей."""
    qty, err = bot_module._gift_quantity(хвост)
    if хвост == "-3 @vasya":
        assert (qty, err) == (1, "")     # это не количество, а мусор рядом с целью
    else:
        assert err, f"{хвост!r} прошло молча"
        assert qty == 0


@pytest.mark.parametrize("хвост", ["²", "³ @vasya", "٣", "@vasya ²"])
def test_нецифровые_цифры_не_роняют_обработчик(хвост):
    """isdigit() истинен для «²» и для арабо-индийской «٣», а int("²")
    бросает ValueError — перехватывать его тут некому, и подарок падал от
    одного символа в сообщении. Такой хвост — это не количество, а мусор
    рядом с целью: дарим одну штуку, как без числа вовсе."""
    qty, err = bot_module._gift_quantity(хвост)
    assert (qty, err) == (1, "")


def test_потолок_подарка_не_больше_потолка_покупки():
    """Разойдись они — дарением можно было бы обойти ограничение покупки."""
    assert bot_module.SHOP_GIFT_MAX_QTY == bot_module.SHOP_BUY_MAX_QTY


def test_фраза_реестра_обещает_количество():
    """Формы, забытой во фразе, не существует для автоочистки и справки."""
    фраза = bot_module.COMMAND_REGISTRY["gift_item"]["phrase"]
    assert "сколько" in фраза
    assert "«все»" in фраза, "слово «все» тоже принимается — значит, обещано быть должно"


# --- кулдаун медвежатника -------------------------------------------------

def test_кулдаун_ровно_десять_часов():
    assert bot_module.STEAL_COOLDOWN == timedelta(hours=10)


def test_фраза_реестра_обещает_кулдаун():
    assert "10 час" in bot_module.COMMAND_REGISTRY["item_steal"]["phrase"]


class _Data:
    """Заглушка key-value хранилища бота."""

    def __init__(self):
        self.rows: dict[str, str] = {}

    async def get_data(self, key):
        value = self.rows.get(key)
        return {"data_key": key, "data_value": value} if value is not None else None

    async def set_data(self, key, value, updated_by=None):
        self.rows[key] = value


@pytest.fixture
def хранилище(monkeypatch):
    data = _Data()
    # Откат медвежатника считает steal_actions, общий с сайтом: у него своя
    # ссылка на db, и подмены только у бота ей не видно.
    import steal_actions
    monkeypatch.setattr(steal_actions, "db", data)
    monkeypatch.setattr(bot_module, "db", data)
    return data


def _run(coro):
    return asyncio.run(coro)


def test_первый_раз_идти_можно(хранилище):
    assert _run(bot_module._steal_cooldown_left(-100, 7)) is None


def test_сразу_после_дела_нельзя(хранилище):
    _run(bot_module._steal_mark_used(-100, 7))
    left = _run(bot_module._steal_cooldown_left(-100, 7))
    assert left is not None and left <= bot_module.STEAL_COOLDOWN


def test_через_десять_часов_снова_можно(хранилище):
    давно = datetime.utcnow() - bot_module.STEAL_COOLDOWN - timedelta(minutes=1)
    хранилище.rows[bot_module._steal_key(-100, 7)] = давно.isoformat()
    assert _run(bot_module._steal_cooldown_left(-100, 7)) is None


def test_кулдаун_у_каждого_свой(хранилище):
    """Ключ включает и чат, и человека: иначе один вор запирал бы всех."""
    _run(bot_module._steal_mark_used(-100, 7))
    assert _run(bot_module._steal_cooldown_left(-100, 8)) is None
    assert _run(bot_module._steal_cooldown_left(-200, 7)) is None


def test_мусор_в_хранилище_не_запирает_навсегда(хранилище):
    """Нечитаемая дата — не повод отобрать команду насовсем."""
    хранилище.rows[bot_module._steal_key(-100, 7)] = "не дата"
    assert _run(bot_module._steal_cooldown_left(-100, 7)) is None


# --- подарок пачкой не должен размножать предметы --------------------------
#
# Обработчик читает количество, сравнивает с нужным и списывает, а само
# списание раньше тоже читало-потом-писало. Между чтением и записью пролезала
# вторая команда того же человека: обе видели «хватает», обе списывали одну и
# ту же вещь, и получатели получали по предмету каждый. Пока дарили строго по
# одной штуке, гонка удваивала одну; с подарком пачкой она удваивает сотню.

CHAT_ID = -1001112223334
USER_ID = 42


class _Инвентарь:
    """Одна строка user_inventory с настоящей семантикой запросов.

    Каждый метод начинается с переключения задач (asyncio.sleep(0)): именно
    там, на await между запросами, вторая команда и пролезала. Без этой точки
    гонку не воспроизвести, и тест был бы зелёным при любой реализации.
    """

    def __init__(self, quantity: int):
        self.quantity = quantity
        self.строка_есть = True

    async def fetchone(self, query, args=()):
        await asyncio.sleep(0)
        return {"quantity": self.quantity} if self.строка_есть else None

    async def execute(self, query, args=()):
        await asyncio.sleep(0)
        q = " ".join(query.split())
        if q.startswith("DELETE FROM user_inventory"):
            if not self.строка_есть or ("quantity <= 0" in q and self.quantity > 0):
                return 0
            self.строка_есть, self.quantity = False, 0
            return 1
        if "SET quantity = quantity - %s" in q:      # условное списание
            amount = args[0]
            if not self.строка_есть or self.quantity < amount:
                return 0
            self.quantity -= amount
            return 1
        if "SET quantity = %s" in q:                 # запись готового числа
            self.quantity = args[0]
            return 1
        return 0


@pytest.fixture
def инвентарь(monkeypatch):
    def _завести(quantity: int) -> _Инвентарь:
        склад = _Инвентарь(quantity)
        monkeypatch.setattr(db_module, "_fetchone", склад.fetchone)
        monkeypatch.setattr(db_module, "_execute", склад.execute)
        return склад
    return _завести


def test_две_одновременные_отдачи_не_размножают_пачку(инвентарь):
    """Сто кормов на руках, две команды «подарить korm 100» разом — уйти
    должна одна пачка, а не две."""
    склад = инвентарь(100)

    async def сценарий():
        return await asyncio.gather(
            db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 100),
            db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 100),
        )

    исходы = _run(сценарий())
    assert sorted(исходы) == [False, True], f"списаний прошло: {исходы}"
    assert склад.quantity == 0, "предметы взялись из воздуха"


def test_две_одновременные_отдачи_по_штуке_тоже_не_размножают(инвентарь):
    """Тот же случай в исходном масштабе: одна вещь на руках, две команды."""
    склад = инвентарь(1)

    async def сценарий():
        return await asyncio.gather(
            db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 1),
            db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 1),
        )

    исходы = _run(сценарий())
    assert sorted(исходы) == [False, True], f"списаний прошло: {исходы}"
    assert склад.quantity == 0


def test_обычное_списание_работает_как_прежде(инвентарь):
    склад = инвентарь(5)
    assert _run(db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 2)) is True
    assert склад.quantity == 3
    assert склад.строка_есть, "строка с остатком не должна удаляться"


def test_нехватка_отбивается(инвентарь):
    склад = инвентарь(3)
    assert _run(db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 4)) is False
    assert склад.quantity == 3, "неудачное списание не должно трогать остаток"


def test_последняя_штука_убирает_строку(инвентарь):
    """Иначе предмет остался бы в инвентаре нулём и показывался «0 шт.»."""
    склад = инвентарь(2)
    assert _run(db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 2)) is True
    assert склад.quantity == 0 and not склад.строка_есть


def test_предмета_нет_вовсе(инвентарь):
    склад = инвентарь(0)
    склад.строка_есть = False
    assert _run(db_module.remove_inventory_item(CHAT_ID, USER_ID, "korm", 1)) is False


# ---------------------------------------------------------------------------
# «магазин подарить {ключ} все @кому»
#
# У подарка количеством считалось ТОЛЬКО голое число — и не по недосмотру: в
# хвосте команды идёт @username получателя, и принять его за число значило бы
# дарить втихую не то количество. Слово «все» этой путаницы не создаёт —
# юзернеймом оно быть не может, — поэтому разбирается наравне с числом.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("хвост,ожидание", [
    ("@vasya", 1),                       # без количества — одна штука
    ("3 @vasya", 3),
    ("@vasya 3", 3),
    ("все @vasya", bot_module.GIFT_ALL),
    ("@vasya все", bot_module.GIFT_ALL),
    ("@vasya всё", bot_module.GIFT_ALL),
    ("ВСЕ @vasya", bot_module.GIFT_ALL),
])
def test_разбор_количества_подарка(хвост, ожидание):
    сколько, ошибка = bot_module._gift_quantity(хвост)
    assert ошибка == ""
    assert сколько == ожидание


def test_юзернейм_не_считается_количеством():
    """Ради этого разбор и был строгим — «подарить korm @all» не должно стать
    подарком всего запаса."""
    сколько, ошибка = bot_module._gift_quantity("@allen")
    assert (сколько, ошибка) == (1, "")


@pytest.mark.parametrize("хвост,кусок_ошибки", [
    ("2 3 @vasya", "одним числом"),
    ("0 @vasya", "меньше одной"),
    (f"{bot_module.SHOP_GIFT_MAX_QTY + 1} @vasya", "не больше"),
])
def test_ошибки_количества_подарка_на_месте(хвост, кусок_ошибки):
    сколько, ошибка = bot_module._gift_quantity(хвост)
    assert сколько == 0 and кусок_ошибки in ошибка
