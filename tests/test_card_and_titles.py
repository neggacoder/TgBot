"""Анкета и титулы вне телеграма.

Два места, где ошибиться легко и незаметно.

ДЛИНЫ. В чате «+звание» отбивает текст длиннее тридцати символов, а колонка в
базе шире. Напиши сайт своё число — и одно и то же звание в чате не
принимается, а из кабинета проходит. Числа объявлены в одном месте, бот берёт
их оттуда, и это проверяется по исходнику: сравнение значений тут бесполезно —
скопированное число равно самому себе.

ДВА ВИДА ТИТУЛОВ. Одни продаются, другие даются только за достижение и цены не
имеют вовсе. Показать вторые в витрине значило бы предложить купить то, что
зарабатывают, и человек, нажав, получил бы отказ без объяснения.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib

import pytest

import card_actions
import title_actions

ЧАТ, ЧЕЛОВЕК = -100, 7


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    def __init__(self, coins=100_000):
        self.карточка = {}
        self.coins = coins
        self.титулы = [
            {"title_key": "hero", "name": "Герой", "price": 5000},
            {"title_key": "star", "name": "Звезда", "price": 12000},
            {"title_key": "legend", "name": "Живая легенда", "price": None},
        ]
        self.свои: set[str] = set()
        self.очищено: list[str] = []

    # --- анкета ---
    async def get_profile_card(self, chat_id, user_id):
        return dict(self.карточка)

    async def set_title(self, chat_id, user_id, value):
        self.карточка["title"] = value

    async def clear_title(self, chat_id, user_id):
        self.очищено.append("title")
        self.карточка.pop("title", None)

    async def set_motto(self, chat_id, user_id, value):
        self.карточка["motto"] = value

    async def clear_motto(self, chat_id, user_id):
        self.очищено.append("motto")
        self.карточка.pop("motto", None)

    async def set_city(self, chat_id, user_id, value):
        self.карточка["city"] = value

    async def clear_city(self, chat_id, user_id):
        self.очищено.append("city")
        self.карточка.pop("city", None)

    async def set_about(self, chat_id, user_id, value):
        self.карточка["about_text"] = value

    async def clear_about(self, chat_id, user_id):
        self.очищено.append("about")
        self.карточка.pop("about_text", None)

    async def set_citizenship(self, chat_id, user_id, on):
        self.карточка["is_citizen"] = bool(on)

    async def set_anketa_visibility(self, chat_id, user_id, on):
        self.карточка["anketa_visible"] = bool(on)

    # --- титулы ---
    async def list_titles(self):
        return [dict(t) for t in self.титулы]

    async def get_title(self, key):
        return next((dict(t) for t in self.титулы if t["title_key"] == key), None)

    async def list_user_titles(self, chat_id, user_id):
        return [{"title_key": k, "name": k} for k in sorted(self.свои)]

    async def has_title(self, chat_id, user_id, key):
        return key in self.свои

    async def grant_title(self, chat_id, user_id, key):
        было = key in self.свои
        self.свои.add(key)
        return not было

    async def set_active_title(self, chat_id, user_id, key):
        self.карточка["active_title"] = key

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(card_actions, "db", w)
    monkeypatch.setattr(title_actions, "db", w)
    return w


# --- анкета ------------------------------------------------------------------

@pytest.mark.parametrize("поле,предел", [
    ("title", card_actions.TITLE_MAX), ("motto", card_actions.MOTTO_MAX),
    ("city", card_actions.CITY_MAX), ("about", card_actions.ABOUT_MAX),
])
@_sync
async def test_длинное_не_принимается(мир, поле, предел):
    итог = await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, поле, "я" * (предел + 1))
    assert not итог.ok and str(предел) in итог.error
    assert мир.карточка == {}, "длинное всё-таки записали"


@pytest.mark.parametrize("поле", ["title", "motto", "city", "about"])
@_sync
async def test_ровно_по_пределу_проходит(мир, поле):
    предел = card_actions.ПОЛЯ[поле][0]
    итог = await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, поле, "я" * предел)
    assert итог.ok, итог.error


@pytest.mark.parametrize("пусто", ["", "   ", None])
@_sync
async def test_пустое_поле_это_снять(мир, пусто):
    """В чате для снятия есть отдельная команда, на сайте её роль играет
    пустое поле. Записать пустую строку значило бы оставить в анкете
    строку-призрак: места столько же, а прочесть нечего."""
    await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, "motto", "Живём")
    итог = await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, "motto", пусто)
    assert итог.ok and итог.cleared
    assert "motto" in мир.очищено
    assert "motto" not in мир.карточка


@_sync
async def test_пробелы_по_краям_срезаются(мир):
    await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, "city", "  Алматы  ")
    assert мир.карточка["city"] == "Алматы"


@_sync
async def test_чужое_поле_не_правится(мир):
    """Список закрытый: закреплённый питомец или рыба ставятся своими
    экранами, где рядом есть из чего выбирать."""
    итог = await card_actions.set_field(ЧАТ, ЧЕЛОВЕК, "pinned_pet", "кот")
    assert not итог.ok
    assert мир.карточка == {}


@_sync
async def test_видимость_по_умолчанию_включена(мир):
    """NULL в базе означает «видна». Считать её скрытой значило бы спрятать
    анкеты всем, кто никогда её не трогал."""
    s = await card_actions.state(ЧАТ, ЧЕЛОВЕК)
    assert s["visible"] is True
    await card_actions.set_visible(ЧАТ, ЧЕЛОВЕК, False)
    assert (await card_actions.state(ЧАТ, ЧЕЛОВЕК))["visible"] is False


@_sync
async def test_состояние_отдаёт_пределы(мир):
    """Экран рисует «до N символов» и обрезает ввод по тому же числу — брать
    его из своего кармана значило бы завести второе."""
    s = await card_actions.state(ЧАТ, ЧЕЛОВЕК)
    assert s["limits"]["title"] == card_actions.TITLE_MAX
    assert set(s["limits"]) == set(card_actions.ПОЛЯ)


def test_пределы_общие_с_ботом():
    """Сравнения значений мало: скопированное число равно самому себе и
    молчит до первой правки. Смотрим в исходник."""
    бот = (pathlib.Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    for имя in ("card_actions.TITLE_MAX", "card_actions.MOTTO_MAX",
                "card_actions.CITY_MAX", "card_actions.ABOUT_MAX"):
        assert имя in бот, f"бот не берёт предел из общего места: {имя}"
    assert "ABOUT_MAX_LEN = 1000" not in бот and "CITY_MAX_LEN = 64" not in бот
    assert "максимум 30 символов" not in бот and "максимум 100 символов" not in бот


# --- титулы ------------------------------------------------------------------

@_sync
async def test_витрина_делит_титулы_по_виду(мир):
    s = await title_actions.state(ЧАТ, ЧЕЛОВЕК)
    assert [t["key"] for t in s["for_sale"]] == ["hero", "star"]
    assert [t["key"] for t in s["earned_only"]] == ["legend"]
    assert all(t["price"] is None for t in s["earned_only"]), (
        "у титула за достижение появилась цена — его предложат купить")


@_sync
async def test_титул_за_достижение_не_купить(мир):
    итог = await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "legend")
    assert not итог.ok
    assert мир.coins == 100_000 and "legend" not in мир.свои


@_sync
async def test_покупка_списывает_и_выдаёт(мир):
    итог = await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "hero")
    assert итог.ok and итог.price == 5000
    assert мир.coins == 95_000 and "hero" in мир.свои


@_sync
async def test_второй_раз_тот_же_титул_не_купить(мир):
    await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "hero")
    денег = мир.coins
    итог = await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "hero")
    assert not итог.ok and "уже есть" in итог.error
    assert мир.coins == денег


@_sync
async def test_без_денег_титул_не_выдаётся(мир):
    мир.coins = 100
    итог = await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "hero")
    assert not итог.ok
    assert "hero" not in мир.свои


@_sync
async def test_надеть_можно_только_свой(мир):
    """Проверка по базе, а не по списку экрана: между отрисовкой и нажатием
    титул мог и не появиться."""
    итог = await title_actions.equip(ЧАТ, ЧЕЛОВЕК, "hero")
    assert not итог.ok and "нет такого" in итог.error
    assert мир.карточка.get("active_title") is None


@_sync
async def test_свой_надевается_и_снимается(мир):
    await title_actions.buy(ЧАТ, ЧЕЛОВЕК, "hero")
    надет = await title_actions.equip(ЧАТ, ЧЕЛОВЕК, "hero")
    assert надет.ok and надет.action == "equip"
    assert мир.карточка["active_title"] == "hero"

    снят = await title_actions.equip(ЧАТ, ЧЕЛОВЕК, "")
    assert снят.ok and снят.action == "unequip"
    assert мир.карточка["active_title"] is None


@_sync
async def test_титул_за_достижение_надевается_если_заслужен(мир):
    """Купить его нельзя, а надеть — можно: он такой же титул, просто
    достался иначе."""
    мир.свои.add("legend")
    итог = await title_actions.equip(ЧАТ, ЧЕЛОВЕК, "legend")
    assert итог.ok and мир.карточка["active_title"] == "legend"


# --- панель не ходит мимо правил ---------------------------------------------

def test_панель_идёт_через_общие_правила():
    файл = (pathlib.Path(__file__).resolve().parent.parent
            / "webpanel" / "member_card_api.py").read_text(encoding="utf-8")
    for имя in ("card_actions.set_field", "card_actions.state",
                "title_actions.buy", "title_actions.equip", "title_actions.state"):
        assert имя in файл, f"{имя} не вызывается"
    for запрет in ("db.set_title", "db.set_motto", "db.grant_title",
                   "db.set_active_title", "db.try_spend_coins"):
        assert запрет not in файл, f"панель правит карточку мимо правил: {запрет}"
