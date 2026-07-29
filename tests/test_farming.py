"""Огород: культуры, погода, вредители, грядки.

Правила живут в farming.py без БД и телеграма, поэтому большая часть проверок
здесь — чистая арифметика. Команды проверяем через тот же приём, что и в
соседних файлах: подменяем bot_module.db заглушкой-миром.
"""

from __future__ import annotations

import asyncio
import functools
import os
from datetime import date, datetime, timedelta

import pytest

import farming

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run прямо в теле теста. Здесь обработчиков много, поэтому один
    декоратор вместо asyncio.run в каждом. functools.wraps обязателен — по
    нему pytest видит настоящую сигнатуру и подставляет фикстуры."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


SUN = farming.WEATHER_BY_KEY["sun"]
RAIN = farming.WEATHER_BY_KEY["rain"]
CLOUD = farming.WEATHER_BY_KEY["cloud"]
HAIL = farming.WEATHER_BY_KEY["hail"]
WIND = farming.WEATHER_BY_KEY["wind"]
DROUGHT = farming.WEATHER_BY_KEY["drought"]


# --- каталог ----------------------------------------------------------------

def test_ключи_культур_не_повторяются():
    keys = [c.key for c in farming.CROPS]
    assert len(keys) == len(set(keys))


def test_пшеница_даёт_тот_же_корм_что_едят_питомцы():
    """farming не импортирует pets намеренно (модуль должен оставаться ни от
    чего не зависящим), поэтому ключ корма продублирован строкой. Разъедься
    они — пшеница молча начала бы давать несъедобный предмет с тем же видом."""
    import pets
    assert farming.FOOD_ITEM_KEY == pets.FOOD_ITEM_KEY
    assert farming.BY_KEY["pshenica"].item_key == pets.FOOD_ITEM_KEY


def test_у_каждой_культуры_есть_товар_в_магазине():
    """Без строки в каталоге урожай показывался бы в инвентаре голым ключом."""
    keys = {row[0] for row in farming.SHOP_ITEMS}
    assert keys == {c.item_key for c in farming.CROPS}


def test_синонимы_понимают_оба_написания():
    assert farming.resolve("картоха").key == "kartoshka"
    assert farming.resolve("  ЯГОДЫ ").key == "klubnika"
    assert farming.resolve("klubnika").key == "klubnika"
    assert farming.resolve("морковь") is None
    assert farming.resolve("") is None
    assert farming.resolve(None) is None


def test_портится_только_клубника():
    """Ровно одна культура заставляет вернуться вовремя. Станет их больше —
    про это стоит подумать отдельно, а не обнаружить случайно."""
    assert [c.key for c in farming.CROPS if c.perishable] == ["klubnika"]


# --- грядки -----------------------------------------------------------------

@pytest.mark.parametrize("stars,plots", [(0, 2), (1, 2), (2, 3), (9, 6), (10, 7), (99, 7)])
def test_грядки_растут_со_звёздностью(stars, plots):
    assert farming.plots_for(stars) == plots


def test_звёздность_после_потолка_грядок_ничего_не_меняет():
    assert farming.plots_next_star(10) is None
    assert farming.plots_next_star(0) == 2
    assert farming.plots_next_star(1) == 1


# --- погода -----------------------------------------------------------------

def test_погода_одинакова_весь_день_и_у_всех():
    day = date(2026, 7, 28)
    первый = farming.weather_for(-100, day)
    assert farming.weather_for(-100, day).key == первый.key
    assert farming.weather_for(-100, day).key == первый.key


def test_погода_разная_в_разные_дни():
    """Не «обязана отличаться каждый день» (так не бывает), а «за две недели
    она хоть раз сменилась» — иначе выведение из даты просто не работает."""
    ключи = {farming.weather_for(-100, date(2026, 7, d)).key for d in range(1, 15)}
    assert len(ключи) > 1


def test_погода_разная_в_разных_чатах():
    ключи = {farming.weather_for(chat, date(2026, 7, 28)).key for chat in range(-50, 0)}
    assert len(ключи) > 1


def test_любая_погода_достижима():
    """Погода с нулевым весом была бы мёртвым кодом: описали и не показали."""
    ключи = set()
    for chat in range(-300, 0):
        for d in range(1, 29):
            ключи.add(farming.weather_for(chat, date(2026, 7, d)).key)
    assert ключи == set(farming.WEATHER_BY_KEY)


# --- рост -------------------------------------------------------------------

def test_дождь_ускоряет_рост():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.grow_seconds(crop, RAIN) < farming.grow_seconds(crop, CLOUD)


def test_засуха_замедляет_рост():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.grow_seconds(crop, DROUGHT) > farming.grow_seconds(crop, CLOUD)


def test_питомец_ускоряет_рост():
    crop = farming.BY_KEY["klubnika"]
    assert farming.grow_seconds(crop, CLOUD, 50) < farming.grow_seconds(crop, CLOUD)


def test_ускорение_не_обнуляет_срок():
    """Проценты ДЕЛЯТ срок, а не вычитаются из него: иначе +100% давало бы
    мгновенный урожай, а +150% — отрицательный."""
    crop = farming.BY_KEY["klubnika"]
    assert farming.grow_seconds(crop, CLOUD, 1000) >= 60


def test_срок_созревания_считается_от_посадки():
    crop = farming.BY_KEY["kartoshka"]
    now = datetime(2026, 7, 28, 12, 0)
    assert farming.ready_at(crop, now, CLOUD) == now + timedelta(hours=2)


# --- порча ------------------------------------------------------------------

def test_клубника_пропадает_если_опоздать():
    crop = farming.BY_KEY["klubnika"]
    ready = datetime(2026, 7, 28, 12, 0)
    assert not farming.is_perished(crop, ready, ready)
    assert not farming.is_perished(crop, ready, ready + timedelta(hours=2))
    assert farming.is_perished(crop, ready, ready + timedelta(hours=3))


def test_непортящаяся_культура_ждёт_сколько_угодно():
    crop = farming.BY_KEY["kartoshka"]
    ready = datetime(2026, 7, 28, 12, 0)
    assert farming.perish_at(crop, ready) is None
    assert not farming.is_perished(crop, ready, ready + timedelta(days=30))


# --- вредители --------------------------------------------------------------

def test_пугало_снимает_вредителей_совсем():
    assert farming.pest_chance(HAIL, protected=True) == 0
    assert farming.pest_chance(HAIL) > 0


def test_град_добавляет_вредителей_а_ветер_убирает():
    assert farming.pest_chance(HAIL) > farming.pest_chance(CLOUD) > farming.pest_chance(WIND)


def test_саранча_садится_в_середине_срока_а_не_в_конце():
    """Сядь она к моменту сбора — прогнать её было бы физически некогда, и
    «ферма помочь» осталась бы декорацией."""
    posadka = datetime(2026, 7, 28, 0, 0)
    gotovo = posadka + timedelta(hours=10)
    for roll in (0.0, 0.5, 1.0):
        moment = farming.pest_moment(posadka, gotovo, roll)
        assert posadka < moment < gotovo


def test_урон_саранчи_копится_по_часам_и_упирается_в_потолок():
    pest = datetime(2026, 7, 28, 0, 0)
    assert farming.pest_loss_percent(pest, pest) == 0
    assert farming.pest_loss_percent(pest, pest + timedelta(hours=1)) == 12
    assert farming.pest_loss_percent(pest, pest + timedelta(days=5)) == farming.PEST_MAX_LOSS
    assert farming.pest_loss_percent(None, pest + timedelta(days=5)) == 0


def test_будущая_саранча_ещё_не_видна():
    pest = datetime(2026, 7, 28, 12, 0)
    assert not farming.pests_visible(pest, pest - timedelta(minutes=1))
    assert farming.pests_visible(pest, pest)
    assert not farming.pests_visible(None, pest)


# --- сбор -------------------------------------------------------------------

def test_солнце_прибавляет_к_урожаю():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.harvest_units(crop, 10, SUN) == 12
    assert farming.harvest_units(crop, 10, CLOUD) == 10
    assert farming.harvest_units(crop, 10, HAIL) == 5


def test_саранча_вычитается_из_урожая():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.harvest_units(crop, 10, CLOUD, pest_loss=60) == 4


def test_урожай_не_бывает_отрицательным():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.harvest_units(crop, 1, HAIL, pest_loss=60) == 0


def test_питомец_прибавляет_к_урожаю():
    crop = farming.BY_KEY["kartoshka"]
    assert farming.harvest_units(crop, 10, CLOUD, bonus_percent=30) == 13


def test_трюфель_по_шансу():
    assert farming.truffle_found(30, 1)
    assert farming.truffle_found(30, 30)
    assert not farming.truffle_found(30, 31)
    assert not farming.truffle_found(0, 1)


# --- команды ----------------------------------------------------------------

class _World:
    """Минимальная заглушка db: только то, что трогает огород."""

    def __init__(self, coins=1_000_000, stars_farms=50):
        self.coins = coins
        self.plots: list[dict] = []
        self.inventory: dict[str, int] = {}
        self.help_at = None
        self.total_farms = stars_farms
        self.messages: list[str] = []
        self.animals: list[dict] = []

    # хлев: «ферма собрать» забирает и грядки, и продукт скота (см. livestock).
    # Здесь он пуст — сам хлев проверяется своими тестами.
    async def list_farm_animals(self, chat_id, user_id):
        return self.animals

    async def touch_farm_animals(self, chat_id, user_id, keys, now):
        return None

    # кошелёк
    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins, "total_farms": self.total_farms}

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount
        return self.coins

    async def take_coins_up_to(self, chat_id, user_id, amount):
        taken = min(self.coins, amount)
        self.coins -= taken
        return taken

    # грядки
    async def list_farm_plots(self, chat_id, user_id):
        return [dict(p) for p in sorted(self.plots, key=lambda p: p["slot"])]

    async def plant_farm_crop(self, chat_id, user_id, slot, crop_key,
                              planted_at, ready_at, pest_at):
        if any(p["slot"] == slot for p in self.plots):
            return False
        self.plots.append({"slot": slot, "crop_key": crop_key,
                           "planted_at": planted_at, "ready_at": ready_at,
                           "pest_at": pest_at})
        return True

    async def clear_farm_plot(self, chat_id, user_id, slot):
        before = len(self.plots)
        self.plots = [p for p in self.plots if p["slot"] != slot]
        return len(self.plots) != before

    async def clear_farm_pests(self, chat_id, user_id, now):
        hit = [p for p in self.plots
               if p["pest_at"] is not None and p["pest_at"] <= now]
        for p in hit:
            p["pest_at"] = None
        return len(hit)

    async def get_farm_help_at(self, chat_id, helper_id):
        return self.help_at

    async def record_farm_help(self, chat_id, helper_id, helped_at):
        self.help_at = helped_at

    # инвентарь и магазин
    async def add_inventory_item(self, chat_id, user_id, item_key, amount=1):
        self.inventory[item_key] = self.inventory.get(item_key, 0) + amount

    async def list_inventory(self, chat_id, user_id):
        return [{"item_key": k, "quantity": v} for k, v in self.inventory.items()]

    async def seed_extra_shop_items(self, chat_id, items, is_active=True):
        self.seeded_active = is_active
        return 0

    # питомцев в этих тестах нет
    async def list_pets(self, chat_id, user_id):
        return []

    async def get_profile_card(self, chat_id, user_id):
        return {}

    async def is_account_frozen(self, chat_id, user_id):
        return False


class _Message:
    def __init__(self, text, world, chat_id=-100, user_id=7):
        self.text = text
        self.world = world
        self.chat = type("C", (), {"id": chat_id, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": user_id, "is_bot": False,
                                        "first_name": "Тест", "username": "test"})()
        self.reply_to_message = None

    async def answer(self, text, **kwargs):
        self.world.messages.append(text)

    async def reply(self, text, **kwargs):
        self.world.messages.append(text)


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(bot_module, "db", world)
    monkeypatch.setattr(bot_module, "is_account_frozen",
                        lambda *a, **k: _false())
    monkeypatch.setattr(bot_module, "spend_coins", _spend_for(world))
    monkeypatch.setattr(bot_module, "get_active_event", lambda chat_id: _none())
    monkeypatch.setattr(bot_module, "_check_misc_access", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "_item_perk", lambda *a, **k: _zero())
    monkeypatch.setattr(bot_module, "display_name", lambda *a, **k: _name())
    return world


async def _false():
    return False


async def _none():
    return None


async def _zero():
    return 0


async def _name():
    return "Тест"


def _spend_for(world):
    async def spend(chat_id, user_id, amount):
        if world.coins < amount:
            return False
        world.coins -= amount
        return True
    return spend


@_sync
async def test_посадка_занимает_грядку_и_списывает_монеты(мир):
    было = мир.coins
    await bot_module.cmd_farm_plant(_Message("ферма посадить картошка", мир))
    assert len(мир.plots) == 1
    assert мир.coins == было - farming.BY_KEY["kartoshka"].seed_price
    assert "Посажено" in мир.messages[-1]


@_sync
async def test_посадка_нескольких_грядок_разом(мир):
    await bot_module.cmd_farm_plant(_Message("ферма посадить картошка 3", мир))
    assert len(мир.plots) == 3


@_sync
async def test_больше_грядок_чем_есть_не_посадить(мир):
    """Звёздность даёт 7 грядок — просьба о 20 не должна ни падать, ни брать
    деньги за несуществующие."""
    было = мир.coins
    await bot_module.cmd_farm_plant(_Message("ферма посадить картошка 20", мир))
    assert len(мир.plots) == farming.PLOTS_MAX
    assert было - мир.coins == farming.BY_KEY["kartoshka"].seed_price * farming.PLOTS_MAX


@_sync
async def test_на_занятые_грядки_не_сажают(мир):
    await bot_module.cmd_farm_plant(_Message("ферма посадить картошка 7", мир))
    было = мир.coins
    await bot_module.cmd_farm_plant(_Message("ферма посадить клубника", мир))
    assert len(мир.plots) == farming.PLOTS_MAX
    assert мир.coins == было, "за неудачную посадку деньги брать нельзя"
    assert "заняты" in мир.messages[-1]


@_sync
async def test_без_денег_не_посадить(мир):
    мир.coins = 10
    await bot_module.cmd_farm_plant(_Message("ферма посадить клубника", мир))
    assert not мир.plots
    assert "Не хватает монет" in мир.messages[-1]


@_sync
async def test_неизвестная_культура(мир):
    await bot_module.cmd_farm_plant(_Message("ферма посадить морковь", мир))
    assert not мир.plots
    assert "Не знаю такой культуры" in мир.messages[-1]


@_sync
async def test_тыква_только_в_ивент(мир):
    await bot_module.cmd_farm_plant(_Message("ферма посадить тыква", мир))
    assert not мир.plots
    assert "ивент" in мир.messages[-1]


@_sync
async def test_сбор_кладёт_урожай_в_инвентарь(мир):
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "kartoshka",
                      "planted_at": now - timedelta(hours=3),
                      "ready_at": now - timedelta(hours=1), "pest_at": None})
    await bot_module.cmd_farm_harvest(_Message("ферма собрать", мир))
    assert not мир.plots, "собранная грядка освобождается"
    assert мир.inventory.get("urozhay_kartoshka", 0) >= 1


@_sync
async def test_неготовую_грядку_сбор_не_трогает(мир):
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "kartoshka",
                      "planted_at": now,
                      "ready_at": now + timedelta(hours=2), "pest_at": None})
    await bot_module.cmd_farm_harvest(_Message("ферма собрать", мир))
    assert len(мир.plots) == 1
    assert not мир.inventory
    assert "поспеет через" in мир.messages[-1]


@_sync
async def test_сгнившая_клубника_освобождает_грядку_но_ничего_не_даёт(мир):
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "klubnika",
                      "planted_at": now - timedelta(hours=20),
                      "ready_at": now - timedelta(hours=8), "pest_at": None})
    await bot_module.cmd_farm_harvest(_Message("ферма собрать", мир))
    assert not мир.plots
    assert not мир.inventory
    assert "сгнила" in мир.messages[-1]


@_sync
async def test_урожай_заводится_в_каталоге_но_не_в_продаже(мир):
    """Строка в магазине нужна ради названия в инвентаре и цены для продажи.
    Стань она активной — подсолнух можно было бы купить, и выращивать его
    (единственный смысл огорода как источника вещей) стало бы незачем."""
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "kartoshka",
                      "planted_at": now - timedelta(hours=3),
                      "ready_at": now - timedelta(hours=1), "pest_at": None})
    await bot_module.cmd_farm_harvest(_Message("ферма собрать", мир))
    assert мир.seeded_active is False


@_sync
async def test_пшеница_даёт_корм_а_не_свой_предмет(мир):
    import pets
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "pshenica",
                      "planted_at": now - timedelta(hours=5),
                      "ready_at": now - timedelta(hours=1), "pest_at": None})
    await bot_module.cmd_farm_harvest(_Message("ферма собрать", мир))
    assert мир.inventory.get(pets.FOOD_ITEM_KEY, 0) >= 1


@_sync
async def test_помощь_соседу_прогоняет_саранчу_и_платит(мир, monkeypatch):
    now = datetime.utcnow()
    мир.plots.append({"slot": 0, "crop_key": "kartoshka",
                      "planted_at": now - timedelta(hours=2),
                      "ready_at": now + timedelta(hours=1),
                      "pest_at": now - timedelta(hours=1)})
    сосед = type("U", (), {"id": 999, "is_bot": False})()
    monkeypatch.setattr(bot_module, "_target_for_item", _target(сосед))
    было = мир.coins
    await bot_module.cmd_farm_help(_Message("ферма помочь @kto", мир))
    assert мир.plots[0]["pest_at"] is None
    assert мир.coins == было + farming.HELP_REWARD_COINS
    assert мир.help_at is not None


@_sync
async def test_помощь_себе_не_считается(мир, monkeypatch):
    сам = type("U", (), {"id": 7, "is_bot": False})()
    monkeypatch.setattr(bot_module, "_target_for_item", _target(сам))
    было = мир.coins
    await bot_module.cmd_farm_help(_Message("ферма помочь @сам", мир))
    assert мир.coins == было
    assert "сами" in мир.messages[-1]


@_sync
async def test_помощь_на_чистых_грядках_не_платит(мир, monkeypatch):
    сосед = type("U", (), {"id": 999, "is_bot": False})()
    monkeypatch.setattr(bot_module, "_target_for_item", _target(сосед))
    было = мир.coins
    await bot_module.cmd_farm_help(_Message("ферма помочь @kto", мир))
    assert мир.coins == было
    assert мир.help_at is None, "кулдаун за холостую помощь не тратится"


def _target(user):
    """Заглушка _target_for_item. Именно ФУНКЦИЯ, а не готовая корутина:
    корутину можно ждать только один раз, и второй вызов падал бы."""
    async def go(*a, **k):
        return user
    return go


@_sync
async def test_помощь_упирается_в_кулдаун(мир, monkeypatch):
    now = datetime.utcnow()
    мир.help_at = now - timedelta(minutes=5)
    мир.plots.append({"slot": 0, "crop_key": "kartoshka",
                      "planted_at": now - timedelta(hours=2),
                      "ready_at": now + timedelta(hours=1),
                      "pest_at": now - timedelta(hours=1)})
    сосед = type("U", (), {"id": 999, "is_bot": False})()
    monkeypatch.setattr(bot_module, "_target_for_item", _target(сосед))
    было = мир.coins
    await bot_module.cmd_farm_help(_Message("ферма помочь @kto", мир))
    assert мир.coins == было
    assert мир.plots[0]["pest_at"] is not None


@_sync
async def test_грядки_показываются_без_питомцев_и_без_посевов(мир):
    text = await bot_module._farm_garden_text(-100, 7)
    assert "Ваш огород" in text
    assert "Пусто" in text


@_sync
async def test_старая_ферма_не_тронута():
    """Огород добавили рядом, а не вместо: команда «ферма» осталась прежней."""
    assert "ферма" in bot_module.FARM_TRIGGERS
    assert bot_module.resolve_command_key("ферма") == "farm_run"
