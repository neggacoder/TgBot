"""Хлев: скот, его продукт и крафты из него.

Ломается такая механика в двух местах: в подсчёте накопленного (ленивый счёт
легко сделать бесконечным или, наоборот, теряющим порции) и на стыке с уже
существующим «ферма собрать», который обещает забрать ВСЁ поспевшее.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import crafting
import livestock
import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555
КОРОВА = livestock.BY_KEY["korova"]


# --- накопление -------------------------------------------------------------

def test_свежекупленное_животное_ещё_ничего_не_дало():
    сейчас = datetime(2026, 7, 29, 12, 0)
    assert livestock.produced(КОРОВА, сейчас, сейчас) == 0


def test_порция_появляется_по_окончании_цикла():
    куплено = datetime(2026, 7, 29, 12, 0)
    почти = куплено + timedelta(hours=КОРОВА.cycle_hours) - timedelta(minutes=1)
    ровно = куплено + timedelta(hours=КОРОВА.cycle_hours)

    assert livestock.produced(КОРОВА, куплено, почти) == 0
    assert livestock.produced(КОРОВА, куплено, ровно) == КОРОВА.per_cycle


def test_накопленное_упирается_в_потолок():
    """Без потолка животное превращалось бы в накопительный счёт: ушёл на
    неделю — вернулся к горе шерсти, и заходить каждый день стало бы незачем."""
    куплено = datetime(2026, 7, 29, 12, 0)
    через_месяц = куплено + timedelta(days=30)

    assert livestock.produced(КОРОВА, куплено, через_месяц) == КОРОВА.cap


def test_время_назад_не_даёт_продукта():
    """Часы на сервере могут прыгнуть; отрицательный интервал не должен
    превращаться в порцию продукта."""
    куплено = datetime(2026, 7, 29, 12, 0)
    assert livestock.produced(КОРОВА, куплено, куплено - timedelta(hours=5)) == 0


def test_срок_следующей_порции_убывает():
    куплено = datetime(2026, 7, 29, 12, 0)
    сразу = livestock.next_unit_in(КОРОВА, куплено, куплено)
    позже = livestock.next_unit_in(КОРОВА, куплено, куплено + timedelta(hours=1))

    assert позже < сразу
    assert сразу == timedelta(hours=КОРОВА.cycle_hours)


def test_полный_хлев_не_обещает_следующую_порцию():
    """None означает «больше не накопится» — иначе бот показывал бы срок,
    после которого ничего не изменится."""
    куплено = datetime(2026, 7, 29, 12, 0)
    assert livestock.next_unit_in(КОРОВА, куплено, куплено + timedelta(days=30)) is None


# --- каталог ----------------------------------------------------------------

def test_у_каждого_животного_свой_продукт():
    """Два животных с одним продуктом означали бы, что второе покупать незачем."""
    продукты = [a.item_key for a in livestock.ANIMALS]
    assert len(set(продукты)) == len(продукты)


def test_продукт_заводится_в_каталоге_но_не_в_продаже():
    """Цена нужна, чтобы продукт можно было ПРОДАТЬ. Купить его нельзя —
    иначе шерсть, ради которой овцу и покупают, бралась бы за монеты."""
    ключи = {row[0] for row in livestock.SHOP_ITEMS}
    assert ключи == {a.item_key for a in livestock.ANIMALS}
    assert all(row[2] > 0 for row in livestock.SHOP_ITEMS), "без цены не продать"


def test_названия_животных_узнаются_в_командах():
    """«ферма купить корову» люди пишут не реже, чем «корова»."""
    for слово in ("корова", "корову", "korova"):
        assert livestock.BY_WORD[слово] is КОРОВА
    assert livestock.BY_WORD.get("дракон") is None


def test_продажа_возвращает_половину_и_никогда_не_ноль():
    for animal in livestock.ANIMALS:
        назад = livestock.sell_back(animal)
        assert 0 < назад < animal.price, animal.key


def test_команды_хлева_опознаются():
    for текст in ("ферма скот", "скот", "хлев", "ферма купить корова",
                  "ферма продать овца"):
        assert bot_module.is_command_like(текст), текст


# --- крафты из продукта -----------------------------------------------------

_ФЕРМЕРСКИЕ = ("syr", "pirog", "sharf", "tulup")


def test_новые_крафты_есть_в_каталоге_предметов():
    """Рецепт, выдающий несуществующий ключ, положил бы в инвентарь голый
    ключ без названия."""
    for ключ in _ФЕРМЕРСКИЕ:
        assert ключ in SE.CRAFT_BY_KEY, ключ


def test_каждый_фермерский_рецепт_требует_продукт_хлева():
    """Иначе ветка фермы существовала бы только на словах: рецепт был бы, а
    держать скот ради него — незачем."""
    продукты = {a.item_key for a in livestock.ANIMALS}
    for recipe in crafting.RECIPES:
        if recipe.result not in _ФЕРМЕРСКИЕ:
            continue
        нужное = {r.key for r in recipe.reqs if r.kind == crafting.REQ_ITEM}
        assert нужное & продукты, recipe.key


def test_фермерские_крафты_дают_разные_бонусы():
    """Четыре предмета с одинаковым эффектом — это один предмет и три
    декорации."""
    цели = [SE.CRAFT_BY_KEY[k].activity for k in _ФЕРМЕРСКИЕ]
    assert len(set(цели)) == len(цели), цели


# --- сбор -------------------------------------------------------------------

class _Хлев:
    def __init__(self, monkeypatch, животные):
        self.выдано: list[tuple[str, int]] = []
        self.отмечено: list[str] = []
        self.строки = животные

        async def list_farm_animals(chat_id, user_id):
            return self.строки

        async def add_inventory_item(chat_id, user_id, key, qty=1):
            self.выдано.append((key, qty))

        async def touch(chat_id, user_id, keys, now):
            self.отмечено = list(keys)

        async def seed(*a, **k):
            return 0

        monkeypatch.setattr(bot_module.db, "list_farm_animals", list_farm_animals, raising=False)
        monkeypatch.setattr(bot_module.db, "add_inventory_item", add_inventory_item, raising=False)
        monkeypatch.setattr(bot_module.db, "touch_farm_animals", touch, raising=False)
        monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", seed, raising=False)


def test_сбор_выдаёт_накопленное_и_отмечает_забранное(monkeypatch):
    давно = datetime.utcnow() - timedelta(days=3)
    хлев = _Хлев(monkeypatch, [{"animal_key": "korova", "last_collect_at": давно}])

    строки = asyncio.run(bot_module._collect_barn(CHAT_ID, USER_ID, datetime.utcnow()))

    assert хлев.выдано == [("moloko", КОРОВА.cap)]
    assert хлев.отмечено == ["korova"]
    assert строки and "Молоко" in строки[0]


def test_сбор_не_трогает_тех_кто_ещё_не_накопил(monkeypatch):
    """Отметить сбор у пустого животного значило бы обнулить ему накопление."""
    только_что = datetime.utcnow()
    хлев = _Хлев(monkeypatch, [{"animal_key": "korova", "last_collect_at": только_что}])

    строки = asyncio.run(bot_module._collect_barn(CHAT_ID, USER_ID, только_что))

    assert хлев.выдано == []
    assert хлев.отмечено == []
    assert строки == []


def test_пустой_хлев_ничего_не_возвращает(monkeypatch):
    _Хлев(monkeypatch, [])
    assert asyncio.run(bot_module._collect_barn(CHAT_ID, USER_ID, datetime.utcnow())) == []


def test_неизвестный_вид_пропускается_а_не_роняет_сбор(monkeypatch):
    """Вид, убранный из каталога, не должен ломать сбор остальным."""
    давно = datetime.utcnow() - timedelta(days=3)
    хлев = _Хлев(monkeypatch, [
        {"animal_key": "динозавр", "last_collect_at": давно},
        {"animal_key": "korova", "last_collect_at": давно},
    ])

    asyncio.run(bot_module._collect_barn(CHAT_ID, USER_ID, datetime.utcnow()))

    assert хлев.выдано == [("moloko", КОРОВА.cap)]
    assert хлев.отмечено == ["korova"]


# --- новые товары и награды -------------------------------------------------

def test_ключи_товаров_магазина_уникальны():
    """Дубль ключа означал бы, что второй товар молча не заведётся:
    add_shop_item существующий ключ не трогает."""
    import db as db_module
    ключи = [i[0] for i in db_module.DEFAULT_SHOP_ITEMS]
    assert len(ключи) == len(set(ключи))


def test_весь_хлам_перечислен_в_ключах_хлама():
    """JUNK_ITEM_KEYS — источник правды для крафтов и коллекции
    «Барахольщик». Забытая строка означала бы предмет, который выглядит хламом,
    но никуда не годится."""
    import db as db_module
    цены = {i[0]: i[2] for i in db_module.DEFAULT_SHOP_ITEMS}
    for ключ in db_module.JUNK_ITEM_KEYS:
        assert ключ in цены, ключ
        assert цены[ключ] <= 25, f"{ключ}: хлам живёт в своём ценовом этаже"


def test_у_каждой_степени_награды_свой_трофей():
    """Трофей выдаётся по верхней перекрытой планке. Две награды на одну
    степень означали бы, что одна из них не достанется никому никогда."""
    планки = [r.min_degree for r in SE.REWARD_ITEMS]
    assert планки == sorted(планки), "порядок задаёт выдачу — он обязан быть по возрастанию"
    assert len(планки) == len(set(планки)), "две награды на одну степень"
    assert планки == list(range(1, 9)), "степени 1–8 покрыты не полностью"


# ---------------------------------------------------------------------------
# Регрессия: покупка животного отвечала «уже куплено» с первого раза
#
# Ответ брался из сравнения записанной bought_at с переданной датой. Но
# bought_at — это DATETIME, MySQL режет микросекунды, а datetime.utcnow() их
# приносит: равенство не выполнялось НИКОГДА. Первая же покупка отвечала
# «животное уже куплено» и возвращала деньги за корову, которая при этом
# преспокойно стояла в хлеву.
#
# Теперь голов может быть несколько, и ответ — это РАЗНИЦА поголовья до и
# после: целые числа, которые база не округляет. Дата в ответе не участвует
# вовсе, и вернуться баг уже не может.
# ---------------------------------------------------------------------------

def _стенд_поголовья(monkeypatch, до: int, после: int) -> list[str]:
    import db as db_module

    запросы: list[str] = []
    состояние = {"вызовов": 0}

    async def execute(query, params=()):
        запросы.append(" ".join(query.split()))
        return 1

    async def fetchone(query, params=()):
        состояние["вызовов"] += 1
        return {"quantity": до if состояние["вызовов"] == 1 else после}

    monkeypatch.setattr(db_module, "_execute", execute)
    monkeypatch.setattr(db_module, "_fetchone", fetchone)
    return запросы


def test_покупка_отвечает_разницей_поголовья(monkeypatch):
    import db as db_module

    запросы = _стенд_поголовья(monkeypatch, до=0, после=3)

    добавлено = asyncio.run(db_module.add_farm_animals(
        CHAT_ID, USER_ID, "korova", datetime.utcnow(), quantity=3, max_per_kind=10))

    assert добавлено == 3
    assert any("INSERT INTO farm_animals" in q for q in запросы)


def test_упор_в_потолок_виден_по_ответу(monkeypatch):
    """Потолок держит сама база (LEAST), а вызывающий по этому же числу
    возвращает деньги за неполученных."""
    import db as db_module

    _стенд_поголовья(monkeypatch, до=9, после=10)

    добавлено = asyncio.run(db_module.add_farm_animals(
        CHAT_ID, USER_ID, "korova", datetime.utcnow(), quantity=5, max_per_kind=10))

    assert добавлено == 1


def test_микросекунды_даты_на_ответ_не_влияют(monkeypatch):
    """Смысл давней правки: какой бы ни была дата, ответ решает поголовье."""
    import db as db_module

    for дата in (datetime(2026, 7, 29, 12, 0, 0, 123456), datetime(2026, 7, 29, 12, 0, 0)):
        _стенд_поголовья(monkeypatch, до=0, после=1)
        assert asyncio.run(db_module.add_farm_animals(
            CHAT_ID, USER_ID, "korova", дата, quantity=1, max_per_kind=10)) == 1


def test_продать_больше_чем_есть_нельзя(monkeypatch):
    """База считает сама: между проверкой в коде и удалением помещается вторая
    команда, и продать одну корову дважды было бы можно."""
    import db as db_module

    _стенд_поголовья(monkeypatch, до=2, после=0)

    продано = asyncio.run(db_module.remove_farm_animals(
        CHAT_ID, USER_ID, "korova", quantity=99))

    assert продано == 2
