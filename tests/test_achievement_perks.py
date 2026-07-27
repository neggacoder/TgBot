"""Постоянные привилегии предметов за ачивки (shop_effects.PERK_*).

Предмет за ачивку раньше был чистой арифметикой: +20% к одному занятию,
которых никто не замечал. Привилегия — вторая, заметная способность, которая
работает всё время, пока предмет лежит в инвентаре.

Проверяем и каталог, и проводку: каталог легко поправить, не подключив
привилегию никуда, — и тогда описание в инвентаре обещает то, чего нет.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta

import pytest

import shop_effects as SE

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*a, **k):
        return value
    return _fn


async def _noop(*a, **k):
    return None


def _inventory(*keys):
    return [{"item_key": k, "quantity": 1, "name": k, "emoji": "🎁"} for k in keys]


# --- каталог ---------------------------------------------------------------

def test_у_каждой_привилегии_есть_объяснение():
    """Привилегия без текста невидима: человек не узнает, что она у него есть."""
    for item in SE.ACHIEVEMENT_ITEMS:
        if item.perk:
            assert item.perk_text, f"у «{item.key}» есть привилегия, но нечего показать"


def test_процентные_привилегии_имеют_силу():
    for item in SE.ACHIEVEMENT_ITEMS:
        if item.perk and item.perk not in SE.FLAG_PERKS:
            assert item.perk_percent > 0, f"«{item.key}»: привилегия без величины"


def test_привилегии_не_дублируются():
    """Две вещи с одной привилегией складывались бы — это надо решать осознанно."""
    perks = [i.perk for i in SE.ACHIEVEMENT_ITEMS if i.perk]
    assert len(perks) == len(set(perks))


def test_perk_percent_считает_только_свою_привилегию():
    keys = ["portfel", "slitok", "traktor"]
    assert SE.perk_percent(keys, SE.PERK_ROBBERY_DEFENSE) == 15
    assert SE.perk_percent(keys, SE.PERK_FAIL_LOSS_CUT) == 25
    assert SE.perk_percent(keys, SE.PERK_ROBBERY_ATTACK) == 0


def test_has_perk_для_переключателей():
    assert SE.has_perk(["snasti"], SE.PERK_NO_EMPTY_FISHING)
    assert not SE.has_perk(["traktor"], SE.PERK_NO_EMPTY_FISHING)
    assert not SE.has_perk([], SE.PERK_NO_EMPTY_FISHING)


def test_обычный_предмет_привилегий_не_даёт():
    assert SE.perk_percent(["energetik", "talisman"], SE.PERK_ROBBERY_DEFENSE) == 0
    assert SE.perks_of("energetik") == ""


# --- проводка: _item_perk --------------------------------------------------

def test_item_perk_читает_инвентарь(monkeypatch):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory("portfel")))
    got = asyncio.run(bot_module._item_perk(CHAT_ID, USER_ID, SE.PERK_ROBBERY_DEFENSE))
    assert got == 15


def test_item_perk_переключатель_отдаёт_единицу(monkeypatch):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory("snasti")))
    assert asyncio.run(bot_module._item_perk(CHAT_ID, USER_ID, SE.PERK_NO_EMPTY_FISHING)) == 1
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory("traktor")))
    assert asyncio.run(bot_module._item_perk(CHAT_ID, USER_ID, SE.PERK_NO_EMPTY_FISHING)) == 0


def test_упавший_инвентарь_не_роняет_механику(monkeypatch):
    """Привилегия — надстройка: ферма и ограбление должны пережить сбой БД."""
    async def boom(*a, **k):
        raise RuntimeError("БД прилегла")

    monkeypatch.setattr(bot_module.db, "list_inventory", boom)
    assert asyncio.run(bot_module._item_perk(CHAT_ID, USER_ID, SE.PERK_ROBBERY_DEFENSE)) == 0


# --- рыбалка: мусорный улов ------------------------------------------------

def test_снасти_убирают_мусорный_улов():
    """Со «Счастливыми снастями» ботинок, банка и водоросли не выпадают."""
    import fishing

    keys = {fishing.roll_species(no_junk=True) for _ in range(400)}
    assert keys, "перевзвешенная таблица не должна оказаться пустой"
    assert not [s for s in keys if s.is_junk]


def test_без_снастей_мусор_по_прежнему_ловится():
    import fishing

    keys = {fishing.roll_species() for _ in range(400)}
    assert [s for s in keys if s.is_junk], "обычная рыбалка не должна измениться"


def test_в_каталоге_есть_и_мусор_и_рыба():
    """Каталог без хлама молча отключил бы привилегию, каталог без рыбы —
    сломал бы перевзвешенный выбор."""
    import fishing

    assert [s for s in fishing.SPECIES if s.is_junk]
    assert [s for s in fishing.SPECIES if not s.is_junk]


# --- ферма: укороченный кулдаун --------------------------------------------

def _farm_setup(monkeypatch, keys, last_farm_ago: timedelta):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory(*keys)))
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    monkeypatch.setattr(bot_module.db, "get_wallet", _returns({
        "coins": 1000, "last_farm_at": datetime.utcnow() - last_farm_ago, "star_level": 0,
    }))


def test_трактор_укорачивает_кулдаун_фермы(monkeypatch):
    """3.5 часа: обычному игроку рано, владельцу трактора (−15%) уже пора."""
    ago = timedelta(hours=3, minutes=30)

    _farm_setup(monkeypatch, [], ago)
    without = asyncio.run(bot_module._farm_execute(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" in without

    _farm_setup(monkeypatch, ["traktor"], ago)
    monkeypatch.setattr(bot_module.db, "get_farm_yield", _returns(100))
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0))
    monkeypatch.setattr(bot_module, "_with_passive", _returns((100, 0)))
    monkeypatch.setattr(bot_module, "_apply_lucky", _returns((100, False)))
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
    monkeypatch.setattr(bot_module.db, "record_farm",
                        _returns({"total_farms": 1, "star_level": 0}))
    with_traktor = asyncio.run(bot_module._farm_execute(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" not in with_traktor
    assert "ЗАЧЁТ" in with_traktor


def test_текст_отказа_называет_укороченный_срок(monkeypatch):
    """Иначе бот пишет «раз в 4 часа», а пускает через 3:24 — и наоборот."""
    _farm_setup(monkeypatch, ["traktor"], timedelta(minutes=10))
    text = asyncio.run(bot_module._farm_execute(CHAT_ID, USER_ID))
    assert "НЕЗАЧЁТ" in text
    # Проверяем положительно: в тексте должен стоять именно укороченный срок
    # (4 ч − 15% = 3 ч 24 мин), а не просто «не 4 часа».
    expected = bot_module.format_duration_ru(
        timedelta(seconds=bot_module.FARM_COOLDOWN.total_seconds() * 0.85)
    )
    assert f"раз в {expected}" in text, text


# --- ежедневный бонус: серия переживает пропуск ----------------------------

def _bonus_setup(monkeypatch, keys, last_day):
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory(*keys)))
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    monkeypatch.setattr(bot_module.db, "get_earning_activity",
                        _returns({"last_day": last_day, "streak": 9}))
    monkeypatch.setattr(bot_module.db, "touch_earning_activity", _noop)
    monkeypatch.setattr(bot_module.db, "add_coins", _noop)
    monkeypatch.setattr(bot_module.db, "add_log", _noop)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
    monkeypatch.setattr(bot_module, "utc_today", lambda: date(2026, 7, 27))


def test_вечный_огонь_прощает_один_пропуск(monkeypatch):
    _bonus_setup(monkeypatch, ["ogon"], date(2026, 7, 25))     # позавчера
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert "Дней подряд: <b>10</b>" in text
    assert "Вечный огонь" in text


def test_без_огня_пропуск_обнуляет_серию(monkeypatch):
    _bonus_setup(monkeypatch, [], date(2026, 7, 25))
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert "Серия начата" in text


def test_два_пропуска_обнуляют_серию_даже_с_огнём(monkeypatch):
    """Иначе предмет означал бы «серия не кончается никогда»."""
    _bonus_setup(monkeypatch, ["ogon"], date(2026, 7, 24))     # три дня назад
    text = asyncio.run(bot_module._daily_bonus_execute(CHAT_ID, USER_ID))
    assert "Серия начата" in text


# --- смена: экономия энергии ------------------------------------------------

def test_робот_снижает_расход_энергии(monkeypatch):
    """20 энергии у уборщика: с роботом (−25%) хватает 15, без него — нет."""
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    monkeypatch.setattr(bot_module.db, "has_profession_upgrade", _returns(False))
    monkeypatch.setattr(bot_module.db, "get_profession_stats", _returns({
        "profession_key": "уборщик", "energy": 16, "mood": 100, "health": 100,
        "prof_level": 1, "work_streak": 0, "last_work_at": None, "last_shift_day": None,
    }))

    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory()))
    without = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Не хватает энергии" in without

    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(_inventory("robot_worker")))
    monkeypatch.setattr(bot_module, "event_flag", _returns(False))
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0))
    monkeypatch.setattr(bot_module, "_with_passive", _returns((500, 0)))
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))
    monkeypatch.setattr(bot_module.db, "add_coins", _noop)
    monkeypatch.setattr(bot_module.db, "update_profession_after_shift", _returns({
        "total_shifts": 1, "prof_xp": 10, "prof_level": 1,
        "energy": 1, "mood": 90, "health": 100,
    }))
    with_robot = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    assert "Не хватает энергии" not in with_robot
