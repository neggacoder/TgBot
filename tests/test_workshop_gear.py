"""Мастерская: покупные материалы, снаряжение из них и его фишки.

До этого магазин кончался расходниками и хламом: всё, что лежит в инвентаре
постоянно, приходило только за ачивки и из двух крафтовых веток (хлам и
ферма). Мастерская добавляет третий путь — материалы покупаются за монеты, а
из них собирается снаряжение, которое режет кулдауны занятий и цену в самом
магазине.

Проверяется именно проводка: каталог, рецепты и то, что новые фишки доезжают
до расчётов. Фишка, которую никто не читает, — самый тихий вид мёртвого кода:
предмет собран, описание обещает, и ничего не происходит.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import crafting as C  # noqa: E402
import shop_effects as SE  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _инвентарь(*keys):
    return [{"item_key": k, "quantity": 1} for k in keys]


# --- каталог материалов -----------------------------------------------------

def test_материалы_доезжают_до_витрины():
    """shop_rows() — единственный досев, который добирается до чатов с уже
    наполненным магазином (db.seed_default_shop_items у непустого молчит),
    поэтому материал вне этого списка не появится ни у кого."""
    rows = {r[0] for r in SE.shop_rows()}
    missing = [i.key for i in SE.MATERIAL_ITEMS if i.key not in rows]
    assert not missing, missing


def test_материалы_можно_купить():
    """Смысл материала в том, чтобы его купили: попади он в REWARD_KEYS —
    магазин ответит «это награда чата», и ветка мастерской умрёт целиком."""
    for item in SE.MATERIAL_ITEMS:
        assert not SE.is_reward(item.key), item.key
        assert item.price > 0, item.key


def test_материалы_дороже_хлама():
    """У хлама свой ценовой этаж (1-15 i¢) — материалы не должны с ним
    смешиваться, иначе витрина превращается в кашу."""
    import db as db_module
    junk_max = max(r[2] for r in db_module.DEFAULT_SHOP_ITEMS
                   if r[0] in db_module.JUNK_ITEM_KEYS)
    assert min(i.price for i in SE.MATERIAL_ITEMS) > junk_max


# Уникальность ключей материалов среди всех каталогов проверяется там, где
# это правило уже живёт, — tests/test_item_catalog_keys.py.


# --- новые фишки ------------------------------------------------------------

_НОВЫЕ_ФИШКИ = {
    SE.PERK_FISH_COOLDOWN: "ledobur",
    SE.PERK_TREASURE_COOLDOWN: "metalloiskatel",
    SE.PERK_WORK_COOLDOWN: "kofemashina",
    SE.PERK_SHOP_DISCOUNT: "klubnaya_karta",
}


@pytest.mark.parametrize("perk,key", sorted(_НОВЫЕ_ФИШКИ.items()))
def test_у_новой_фишки_есть_носитель(perk, key):
    assert SE.perk_percent([key], perk) > 0, key
    assert SE.perks_of(key), f"«{key}»: фишка есть, а объяснить её нечем"


def test_две_скидки_складываются():
    """Клубная карта и торговый знак — разные вещи и разные рецепты; складывать
    их осознанно, иначе вторая покупка не даёт ничего."""
    одна = SE.perk_percent(["klubnaya_karta"], SE.PERK_SHOP_DISCOUNT)
    две = SE.perk_percent(["klubnaya_karta", "torgovyy_znak"], SE.PERK_SHOP_DISCOUNT)
    assert две > одна
    assert две < 100, "скидка не должна доходить до бесплатного"


def test_чужой_предмет_фишку_не_даёт():
    assert SE.perk_percent(["traktor"], SE.PERK_FISH_COOLDOWN) == 0
    assert SE.perk_percent(["energetik"], SE.PERK_SHOP_DISCOUNT) == 0


# --- рецепты ----------------------------------------------------------------

def test_снаряжение_мастерской_крафтится():
    """Предмет без рецепта получить нельзя вообще — он мёртвый груз каталога."""
    результаты = {r.result for r in C.RECIPES}
    for key in ("ledobur", "metalloiskatel", "kofemashina", "klubnaya_karta",
                "torgovyy_znak", "echolot", "almaznaya_kirka", "kombinezon",
                "vezdehod"):
        assert key in SE.CRAFT_BY_KEY, key
        assert key in результаты, f"«{key}» не собрать: нет рецепта"


def test_рецепты_требуют_только_существующие_ачивки():
    """Опечатка в коде ачивки делает рецепт невыполнимым навсегда, а бот
    честно скажет «не хватает» — понять причину по сообщению невозможно."""
    for recipe in C.RECIPES:
        for req in recipe.reqs:
            if req.kind == C.REQ_ACHIEVEMENT:
                assert req.key in bot_module.ACHIEVEMENTS, f"{recipe.key}: {req.key}"


def test_звёздность_и_профессия_наконец_требуются():
    """REQ_STARS и REQ_PROF_LEVEL были поддержаны проверяльщиком, но ни один
    рецепт их не просил — код без единого потребителя."""
    виды = {req.kind for r in C.RECIPES for req in r.reqs}
    assert C.REQ_STARS in виды
    assert C.REQ_PROF_LEVEL in виды


# --- проводка фишек в расчёты ----------------------------------------------

def test_perk_cooldown_режет_ожидание(monkeypatch):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь("ledobur")))
    срок = asyncio.run(bot_module._perk_cooldown(
        CHAT_ID, USER_ID, timedelta(hours=4), SE.PERK_FISH_COOLDOWN))
    assert срок < timedelta(hours=4)


def test_perk_cooldown_не_уходит_в_ноль(monkeypatch):
    """Сумма срезов однажды перевалит за 100% — третий предмет с той же фишкой
    добавить проще, чем заметить, что кулдаун стал отрицательным и занятие
    доступно всегда. Потолок держим здесь, а не в каждом занятии."""
    monkeypatch.setattr(bot_module, "_item_perk", _returns(250))
    срок = asyncio.run(bot_module._perk_cooldown(
        CHAT_ID, USER_ID, timedelta(hours=4), SE.PERK_FISH_COOLDOWN))
    assert срок > timedelta(0)


def test_perk_cooldown_без_предмета_ничего_не_меняет(monkeypatch):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь("kamen")))
    базовый = timedelta(hours=4)
    срок = asyncio.run(bot_module._perk_cooldown(
        CHAT_ID, USER_ID, базовый, SE.PERK_FISH_COOLDOWN))
    assert срок == базовый


def _минут(текст: str) -> int:
    """Сколько ждать по тексту отказа. Сравниваем числа, а не строки: в тексте
    два старших разряда, и секунды в нём меняются от запуска к запуску."""
    часы = re.search(r"(\d+)\s+час", текст)
    минуты = re.search(r"(\d+)\s+минут", текст)
    assert часы or минуты, f"в отказе нет срока: {текст}"
    return (int(часы.group(1)) * 60 if часы else 0) + (int(минуты.group(1)) if минуты else 0)


@pytest.fixture
def _тихо(monkeypatch):
    """Отказы занятий приклеивают подсказку «чем заняться» — она тянет
    пол-бота и к кулдаунам отношения не имеет."""
    monkeypatch.setattr(bot_module, "activity_hint", _returns(""))
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    return monkeypatch


def _отказ_рыбалки(monkeypatch, *предметы) -> str:
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь(*предметы)))
    monkeypatch.setattr(bot_module.db, "get_fishing_stats", _returns(
        {"last_fish_at": datetime.utcnow() - bot_module.FISHING_COOLDOWN / 4}))
    return asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))


def test_ледобур_укорачивает_ожидание_рыбалки(_тихо):
    """И в отказе, и в допуске: срок считается один раз, иначе текст обещает
    одно, а пускает бот по другому."""
    без = _минут(_отказ_рыбалки(_тихо, "kamen"))
    с_буром = _минут(_отказ_рыбалки(_тихо, "ledobur"))
    assert 0 < с_буром < без, (с_буром, без)


def _отказ_клада(monkeypatch, *предметы) -> str:
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь(*предметы)))
    monkeypatch.setattr(bot_module.db, "get_digger", _returns(
        {"last_dig_at": datetime.utcnow() - bot_module.TREASURE_COOLDOWN / 4}))
    return asyncio.run(bot_module._treasure_execute(CHAT_ID, USER_ID))


def test_металлоискатель_укорачивает_ожидание_клада(_тихо):
    без = _минут(_отказ_клада(_тихо, "kamen"))
    с_прибором = _минут(_отказ_клада(_тихо, "metalloiskatel"))
    assert 0 < с_прибором < без, (с_прибором, без)


def _отказ_смены(monkeypatch, *предметы) -> str:
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь(*предметы)))
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns({
        "profession_key": next(iter(bot_module.PROFESSIONS)),
        "last_work_at": datetime.utcnow() - bot_module.PROFESSION_WORK_COOLDOWN / 4,
        "prof_level": 1, "shifts_since_break": 0,
    }))
    monkeypatch.setattr(bot_module.db, "has_profession_upgrade", _returns(False))
    return asyncio.run(bot_module._profession_execute_work(
        CHAT_ID, USER_ID, with_hint=False))


def test_кофемашина_укорачивает_ожидание_смены(_тихо):
    без = _минут(_отказ_смены(_тихо, "kamen"))
    с_кофе = _минут(_отказ_смены(_тихо, "kofemashina"))
    assert 0 < с_кофе < без, (с_кофе, без)


# Сводка «чем заняться» обязана считать теми же сроками — это проверяется в
# tests/test_activity_board.py, где уже стоит её фикстура со всеми заглушками.


# --- скидка в магазине ------------------------------------------------------

def test_клубная_карта_снижает_цену_покупки(monkeypatch):
    """Скидка обязана считаться ДО «все» и до списания: иначе человек платит
    полную цену, а в ответе видит скидочную."""
    цены = []

    async def spend_coins(chat_id, user_id, amount, *a, **k):
        цены.append(amount)
        return True

    item = {"item_key": "doska", "name": "Доска", "emoji": "🪵", "price": 100,
            "stock": None, "is_active": True}
    monkeypatch.setattr(bot_module.db, "get_shop_item", _returns(item))
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0))
    monkeypatch.setattr(bot_module.game_actions, "_pet_bonus", _returns(0))
    monkeypatch.setattr(bot_module.db, "try_take_shop_stock", _returns(True))
    monkeypatch.setattr(bot_module, "spend_coins", spend_coins)
    monkeypatch.setattr(bot_module.db, "add_inventory_item", _returns(None))
    monkeypatch.setattr(bot_module.db, "add_log", _returns(None))
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": 100_000}))

    ответы = []

    class _Сообщение:
        chat = type("_C", (), {"id": CHAT_ID, "type": "supergroup"})()
        from_user = type("_U", (), {"id": USER_ID, "full_name": "Игрок",
                                    "username": None, "is_bot": False})()

        async def reply(self, text, **kwargs):
            ответы.append(text)

    for предметы, метка in ((("kamen",), "без карты"), (("klubnaya_karta",), "с картой")):
        monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_инвентарь(*предметы)))
        ok = asyncio.run(bot_module._shop_buy(_Сообщение(), "doska", 1))
        assert ok, (метка, ответы)

    без, со_скидкой = цены
    assert со_скидкой < без, (без, со_скидкой)
    assert str(со_скидкой) in ответы[-1], "в ответе должна стоять уплаченная цена"
    # «Распродажа» — это событие чата, а не своя скидка. Событие здесь
    # выключено (множитель 1.0), и объявлять распродажу бот не должен: иначе
    # владелец карты видит её при каждой покупке и слово теряет смысл.
    assert "распродажа" not in ответы[-1].lower(), ответы[-1]
