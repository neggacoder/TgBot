"""Рыбалка с настоящей рыбой: вид, вес, сетка, свежесть, продажа.

Прежняя рыбалка была фермой с другим текстом: бросил — получил монеты, улов
исчез. Теперь улов — предмет со своей судьбой, и вся ценность механики в
одном решении: сдать сейчас или придержать до события «Клёв пошёл», когда
рыба продаётся вдвое дороже.

Отсюда и главное, что здесь проверяется: множитель события применяется в
момент ПРОДАЖИ, а не поимки. Сломайся это — и придерживать улов станет
бессмысленно, причём молча: команды продолжат работать, деньги продолжат
капать, исчезнет только смысл.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

import fishing

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


def _message(text: str, sink: list):
    from aiogram.types import Chat, Message, User
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тестер"), text=text,
    )

    async def collect(t, **k):
        sink.append(t)

    object.__setattr__(m, "reply", collect)
    object.__setattr__(m, "answer", collect)
    return m


def _fish(fish_id: int, key: str, grams: int, age_hours: float = 0.0):
    return {
        "id": fish_id, "species_key": key, "grams": grams,
        "caught_at": datetime.utcnow() - timedelta(hours=age_hours),
    }


# --- каталог ----------------------------------------------------------------

def test_вес_всегда_в_пределах_вида():
    for species in fishing.SPECIES:
        for _ in range(50):
            grams = fishing.roll_grams(species)
            assert species.min_grams <= grams <= species.max_grams


def test_цена_растёт_с_весом():
    species = fishing.BY_KEY["shchuka"]
    assert fishing.base_price(species, 5_000) > fishing.base_price(species, 1_000)


def test_цена_никогда_не_ноль():
    """Иначе самая мелкая рыба продавалась бы за 0 и выглядела как ошибка."""
    for species in fishing.SPECIES:
        assert fishing.base_price(species, species.min_grams) >= 1


def test_ключи_видов_уникальны():
    assert len({s.key for s in fishing.SPECIES}) == len(fishing.SPECIES)


def test_у_каждого_вида_есть_подпись_редкости():
    for species in fishing.SPECIES:
        assert species.rarity in fishing.RARITY_LABEL


# Прежняя таблица уловов (вес, мин. i¢, макс. i¢) — та, что была до сетки.
# Держим её здесь как эталон: рыбалка должна была стать интереснее, а не
# богаче, и сравнивать новый доход больше не с чем.
OLD_CATCH_TABLE = [
    (18, 10, 80), (14, 30, 120), (20, 200, 450), (16, 450, 800),
    (12, 700, 1_200), (8, 1_100, 1_800), (5, 1_700, 2_800),
    (4, 2_500, 4_000), (2, 4_000, 7_000), (1, 9_000, 15_000),
    (1, 12_000, 20_000),
]


def _mean_grams(species) -> float:
    """Среднее ТРЕУГОЛЬНОГО распределения с модой в минимуме (см. roll_grams).

    Не (min+max)/2: у треугольного с модой в min среднее равно (2*min+max)/3,
    и для сома это 16.7 кг против 22.5 — ошибка завышает вообще всё.
    """
    return (2 * species.min_grams + species.max_grams) / 3


def _ev_per_cast() -> tuple[float, float, float]:
    """(старая таблица, продать сразу, копить и сливать в «Клёв»)."""
    old_total = sum(w for w, _, _ in OLD_CATCH_TABLE)
    ev_old = sum(w / old_total * (lo + hi) / 2 for w, lo, hi in OLD_CATCH_TABLE)

    total = sum(s.chance for s in fishing.SPECIES)
    ev_junk = sum(s.chance / total * fishing.base_price(s, _mean_grams(s))
                  for s in fishing.SPECIES if s.is_junk)
    ev_real = sum(s.chance / total * fishing.base_price(s, _mean_grams(s))
                  for s in fishing.SPECIES if not s.is_junk)
    # Хлам платится сразу и в сетку не попадает, поэтому ×2 на него не идёт.
    # 0.98 — лёгкая потеря свежести за время ожидания клёва.
    return ev_old, ev_junk + ev_real, ev_junk + ev_real * 2 * 0.98


def test_ленивая_игра_осталась_примерно_как_была():
    """Кто просто ловит и сразу сдаёт — не должен пострадать от новой механики."""
    ev_old, ev_now, _ev_opt = _ev_per_cast()
    ratio = ev_now / ev_old
    assert 0.6 < ratio < 1.1, f"доход «продать сразу» уехал в {ratio:.2f}x"


def test_оптимальная_игра_не_печатает_деньги():
    """Главная защита от инфляции.

    Событие «Клёв» теперь применяется при ПРОДАЖЕ, поэтому хороший игрок
    сливает в него всю сетку. С исходными ценами это давало 2.27x к прежнему
    доходу — при том, что сама механика выглядела безобидно. Держим потолок
    в полтора раза: это награда за внимание, а не новый станок.
    """
    ev_old, _ev_now, ev_opt = _ev_per_cast()
    ratio = ev_opt / ev_old
    assert ratio < 1.6, (
        f"копить и сливать в «Клёв» даёт {ratio:.2f}x прежнего дохода — "
        f"это инфляция, а не награда за игру"
    )


def test_придерживать_улов_всё_таки_выгодно():
    """Обратная сторона: если оптимум не лучше ленивой игры, вся сетка
    бессмысленна и её можно было не делать."""
    _ev_old, ev_now, ev_opt = _ev_per_cast()
    assert ev_opt > ev_now * 1.3


# --- свежесть ---------------------------------------------------------------

def test_свежая_рыба_стоит_полную_цену():
    assert fishing.freshness(0) == 1.0
    assert fishing.freshness(fishing.FRESH_HOURS) == 1.0


def test_рыба_дешевеет_со_временем():
    assert fishing.freshness(fishing.FRESH_HOURS + 12) < 1.0


def test_порча_не_ниже_пола():
    """Совсем в ноль рыба не уходит — иначе забытая сетка просто исчезает."""
    assert fishing.freshness(10_000) == fishing.ROT_FLOOR


def test_свежесть_монотонна():
    prev = 1.1
    for hours in range(0, 200, 5):
        value = fishing.freshness(hours)
        assert value <= prev
        prev = value


# --- заброс -----------------------------------------------------------------

def _catch_setup(monkeypatch, species_key: str, net=None, grams=None):
    species = fishing.BY_KEY[species_key]
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False))
    monkeypatch.setattr(bot_module.db, "get_fishing_stats", _returns({
        "last_fish_at": None, "total_catches": 0, "best_catch": 0,
        "best_catch_name": None, "best_weight": 0, "best_weight_species": None,
    }))
    monkeypatch.setattr(fishing, "roll_species", lambda no_junk=False: species)
    if grams is not None:
        monkeypatch.setattr(fishing, "roll_grams", lambda s: grams)
    monkeypatch.setattr(bot_module.db, "record_catch_weight", _returns(
        {"total_catches": 1, "best_weight": grams or 0, "best_weight_species": species_key}))
    monkeypatch.setattr(bot_module.db, "list_net", _returns(net if net is not None else []))
    monkeypatch.setattr(bot_module.db, "get_profile_card", _returns(None))
    monkeypatch.setattr(bot_module.db, "add_log", _noop)
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(1.0))
    monkeypatch.setattr(bot_module, "_with_passive",
                        lambda c, u, a, amount: _returns((amount, 0))())
    monkeypatch.setattr(bot_module, "_apply_lucky",
                        lambda c, u, amount: _returns((amount, False))())
    return species


def test_хлам_идёт_сразу_в_монеты_а_не_в_сетку(monkeypatch):
    """Иначе сетка забивалась бы ботинками, и её лимит терял бы смысл."""
    _catch_setup(monkeypatch, "botinok", grams=1_000)
    paid, netted = {}, {}
    monkeypatch.setattr(bot_module.db, "add_coins",
                        lambda c, u, amount, *a, **k: _returns(paid.update(v=amount))())
    monkeypatch.setattr(bot_module.db, "add_to_net",
                        lambda *a, **k: _returns(netted.update(hit=True))())

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert paid.get("v"), "хлам должен превращаться в монеты"
    assert not netted, "хлам не должен занимать место в сетке"
    assert "приёмку" in text


def test_настоящая_рыба_идёт_в_сетку_без_монет(monkeypatch):
    _catch_setup(monkeypatch, "okun", grams=800)
    paid, netted = {}, {}
    monkeypatch.setattr(bot_module.db, "add_coins",
                        lambda c, u, amount, *a, **k: _returns(paid.update(v=amount))())
    monkeypatch.setattr(bot_module.db, "add_to_net",
                        lambda *a, **k: _returns(netted.update(hit=True))())
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert netted.get("hit"), "рыба должна попасть в сетку"
    assert not paid, "за поимку монет быть не должно — только за продажу"
    assert "окунь" in text


def test_полная_сетка_выбрасывает_самую_дешёвую(monkeypatch):
    """Заброс не блокируется: вылетает мелочь, а не возможность играть."""
    net = [_fish(i, "rybeshka", 60) for i in range(1, bot_module.NET_CAPACITY)]
    net.append(_fish(99, "rybeshka", 50))          # самая дешёвая
    _catch_setup(monkeypatch, "som", net=net, grams=30_000)
    removed = {}

    async def remove(chat_id, user_id, fish_id):
        removed["id"] = fish_id
        return True

    monkeypatch.setattr(bot_module.db, "remove_from_net", remove)
    monkeypatch.setattr(bot_module.db, "add_to_net", _returns(1))
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert removed.get("id") == 99, "выбросить должно самую дешёвую"
    assert "выбросили" in text


def test_мелкую_рыбу_не_меняют_на_ещё_более_мелкую(monkeypatch):
    """Если новая рыба самая скромная — отпускают её, а не чужую добычу."""
    net = [_fish(i, "lobster", 2_000) for i in range(1, bot_module.NET_CAPACITY + 1)]
    _catch_setup(monkeypatch, "rybeshka", net=net, grams=50)
    monkeypatch.setattr(bot_module.db, "remove_from_net", _returns(True))
    added = {}
    monkeypatch.setattr(bot_module.db, "add_to_net",
                        lambda *a, **k: _returns(added.update(hit=True))())

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert not added, "самую мелкую рыбу в полную сетку класть не надо"
    assert "отпустили" in text


def test_закреплённый_трофей_не_вытесняется(monkeypatch):
    """Иначе смысл закрепления пропадает: трофей вылетит сам собой."""
    net = [_fish(1, "rybeshka", 50)]                       # самая дешёвая, но 📌
    net += [_fish(i, "lobster", 2_000) for i in range(2, bot_module.NET_CAPACITY + 1)]
    _catch_setup(monkeypatch, "som", net=net, grams=30_000)
    monkeypatch.setattr(bot_module.db, "get_profile_card", _returns({"pinned_fish": 1}))
    removed = {}

    async def remove(chat_id, user_id, fish_id):
        removed["id"] = fish_id
        return True

    monkeypatch.setattr(bot_module.db, "remove_from_net", remove)
    monkeypatch.setattr(bot_module.db, "add_to_net", _returns(1))
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))

    asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert removed.get("id") != 1, "закреплённый трофей выбрасывать нельзя"


def test_талисман_удваивает_вес(monkeypatch):
    """Монет при забросе нет, поэтому «вдвое больше» — это вдвое тяжелее."""
    _catch_setup(monkeypatch, "okun", grams=500)
    monkeypatch.setattr(bot_module, "_apply_lucky",
                        lambda c, u, amount: _returns((amount * 2, True))())
    stored = {}
    monkeypatch.setattr(bot_module.db, "add_to_net",
                        lambda c, u, key, grams, now: _returns(stored.update(g=grams))())
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))

    text = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert stored.get("g") == 1_000
    assert "вдвое крупнее" in text


def test_талисман_не_делает_рыбу_больше_видового_максимума(monkeypatch):
    """Иначе «топ рыбаков» становится рейтингом тех, кто не пожалел талисман:
    щука на 12 кг при заявленных в каталоге 6 обгоняет честного сома."""
    species = _catch_setup(monkeypatch, "shchuka", grams=5_000)
    monkeypatch.setattr(bot_module, "_apply_lucky",
                        lambda c, u, amount: _returns((amount * 2, True))())
    stored = {}
    monkeypatch.setattr(bot_module.db, "add_to_net",
                        lambda c, u, key, grams, now: _returns(stored.update(g=grams))())
    monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))

    asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
    assert stored.get("g") == species.max_grams == 6_000


def test_вес_в_сетке_всегда_в_пределах_каталога(monkeypatch):
    """Сквозная проверка: что бы ни накрутили по дороге, в сетку не должна
    попасть рыба тяжелее, чем бывает у этого вида."""
    for key in ("rybeshka", "shchuka", "som", "konyok"):
        species = _catch_setup(monkeypatch, key, grams=species_max(key))
        monkeypatch.setattr(bot_module, "_apply_lucky",
                            lambda c, u, amount: _returns((amount * 2, True))())
        stored = {}
        monkeypatch.setattr(bot_module.db, "add_to_net",
                            lambda c, u, k, grams, now: _returns(stored.update(g=grams))())
        monkeypatch.setattr(bot_module, "grant_achievement", _returns(False))
        asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))
        assert stored["g"] <= species.max_grams


def species_max(key: str) -> int:
    return fishing.BY_KEY[key].max_grams


# --- продажа ----------------------------------------------------------------

def _sell_setup(monkeypatch, net, multiplier=1.0, pinned=None):
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module.db, "list_net", _returns(net))
    monkeypatch.setattr(bot_module.db, "get_profile_card",
                        _returns({"pinned_fish": pinned} if pinned else None))
    monkeypatch.setattr(bot_module, "event_multiplier", _returns(multiplier))
    monkeypatch.setattr(bot_module, "_with_passive",
                        lambda c, u, a, amount: _returns((amount, 0))())
    monkeypatch.setattr(bot_module.db, "remove_from_net", _returns(True))
    monkeypatch.setattr(bot_module.db, "record_catch_price", _noop)
    monkeypatch.setattr(bot_module.db, "add_log", _noop)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
    paid = {}
    monkeypatch.setattr(bot_module.db, "add_coins",
                        lambda c, u, amount, *a, **k: _returns(paid.update(v=amount))())
    return paid


def test_ивент_удваивает_цену_ПРИ_ПРОДАЖЕ(monkeypatch):
    """Смысл всей сетки: рыба, пойманная вчера, продаётся по сегодняшнему клёву."""
    net = [_fish(1, "lobster", 2_000)]
    said = []

    plain = _sell_setup(monkeypatch, net, multiplier=1.0)
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))
    without = plain["v"]

    boosted = _sell_setup(monkeypatch, net, multiplier=2.0)
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))
    with_event = boosted["v"]

    assert with_event == without * 2, (without, with_event)
    assert any("Клёв" in s for s in said)


def test_несвежая_рыба_дешевле(monkeypatch):
    said = []
    fresh = _sell_setup(monkeypatch, [_fish(1, "lobster", 2_000, age_hours=0)])
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))

    stale = _sell_setup(monkeypatch, [_fish(1, "lobster", 2_000, age_hours=200)])
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))

    assert stale["v"] < fresh["v"]


def test_закреплённую_рыбу_не_продают_оптом(monkeypatch):
    """«сетка продать» без номера не должна сдавать трофей вместе со всеми."""
    net = [_fish(1, "lobster", 2_000), _fish(2, "okun", 900)]
    said = []
    _sell_setup(monkeypatch, net, pinned=1)
    removed = []

    async def remove(chat_id, user_id, fish_id):
        removed.append(fish_id)
        return True

    monkeypatch.setattr(bot_module.db, "remove_from_net", remove)
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))
    assert removed == [2]


def test_закреплённую_рыбу_не_продают_поштучно(monkeypatch):
    net = [_fish(1, "lobster", 2_000)]
    said = []
    _sell_setup(monkeypatch, net, pinned=1)
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать 1", said)))
    assert any("закреплена" in s for s in said)


def test_продажа_по_номеру_берёт_одну(monkeypatch):
    net = [_fish(1, "lobster", 2_000), _fish(2, "okun", 900)]
    said = []
    _sell_setup(monkeypatch, net)
    removed = []

    async def remove(chat_id, user_id, fish_id):
        removed.append(fish_id)
        return True

    monkeypatch.setattr(bot_module.db, "remove_from_net", remove)
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать 2", said)))
    assert removed == [2]


def test_номер_вне_диапазона_ничего_не_продаёт(monkeypatch):
    net = [_fish(1, "lobster", 2_000)]
    said = []
    _sell_setup(monkeypatch, net)
    removed = []
    monkeypatch.setattr(bot_module.db, "remove_from_net",
                        lambda c, u, i: _returns(removed.append(i))())
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать 9", said)))
    assert not removed


def test_пустая_сетка_продаже_не_поддаётся(monkeypatch):
    said = []
    _sell_setup(monkeypatch, [])
    asyncio.run(bot_module.cmd_net_sell(_message("сетка продать", said)))
    assert any("пуста" in s for s in said)


# --- лёд --------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_pinned_item(monkeypatch):
    """Применение предмета спрашивает, не закреплён ли он: закреплённый
    усиливается впятеро (shop_effects.PIN_MULTIPLIER). Тесты этого файла
    проверяют обычное поведение, поэтому закрепа нет."""
    monkeypatch.setattr(bot_module.db, "get_profile_card",
                        _returns({"pinned_item": None}), raising=False)


def test_лёд_обновляет_свежесть(monkeypatch):
    said = []
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(
        [{"item_key": "lyod", "quantity": 1, "name": "Лёд", "emoji": "🧊"}]))
    monkeypatch.setattr(bot_module.db, "list_net",
                        _returns([_fish(1, "lobster", 2_000, age_hours=40)]))
    refreshed = {}
    monkeypatch.setattr(bot_module.db, "refresh_net",
                        lambda c, u, now: _returns(refreshed.update(hit=True))())
    monkeypatch.setattr(bot_module.db, "remove_inventory_item", _returns(True))
    monkeypatch.setattr(bot_module.db, "add_log", _noop)

    asyncio.run(bot_module._use_effect_item(_message("использовать lyod", said), "lyod"))
    assert refreshed.get("hit")


def test_лёд_не_тратится_на_пустую_сетку(monkeypatch):
    said = []
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(
        [{"item_key": "lyod", "quantity": 1, "name": "Лёд", "emoji": "🧊"}]))
    monkeypatch.setattr(bot_module.db, "list_net", _returns([]))
    removed = []
    monkeypatch.setattr(bot_module.db, "remove_inventory_item",
                        lambda *a, **k: _returns(removed.append(1))())

    asyncio.run(bot_module._use_effect_item(_message("использовать lyod", said), "lyod"))
    assert not removed
    assert any("пуста" in s for s in said)


def test_лёд_не_тратится_на_свежую_рыбу(monkeypatch):
    said = []
    monkeypatch.setattr(bot_module.db, "list_inventory", _returns(
        [{"item_key": "lyod", "quantity": 1, "name": "Лёд", "emoji": "🧊"}]))
    monkeypatch.setattr(bot_module.db, "list_net",
                        _returns([_fish(1, "lobster", 2_000, age_hours=0)]))
    removed = []
    monkeypatch.setattr(bot_module.db, "remove_inventory_item",
                        lambda *a, **k: _returns(removed.append(1))())

    asyncio.run(bot_module._use_effect_item(_message("использовать lyod", said), "lyod"))
    assert not removed
    assert any("свежая" in s for s in said)
