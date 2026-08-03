"""Достижения и коллекции: витрина, только чтение.

Три вещи, ради которых эти проверки и написаны.

ВИТРИНА НИЧЕГО НЕ МЕНЯЕТ. Закрепление достижения, выдача титула за собранную
коллекцию и проверка «а не собралась ли она» живут там, где происходят сами
события. Позови их отсюда — и простое открытие экрана начало бы что-то
выдавать, причём каждый раз.

НЕПОЛУЧЕННОЕ ПОКАЗЫВАЕТСЯ ТОЖЕ. Список одного собранного отвечает на вопрос
«что у меня есть» и молчит о том, ради чего сюда и заходят.

ПРОГРЕСС СЧИТАЕТСЯ ОДИНАКОВО. Разъедься расчёт между чатом и сайтом — одна и
та же коллекция оказалась бы собранной в чате и несобранной в кабинете.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib

import pytest

import achievements_meta
import collections_meta
import gallery_actions as g

ЧАТ, ЧЕЛОВЕК = -100, 7


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    JUNK_ITEM_KEYS = ("junk_a", "junk_b", "junk_c")

    def __init__(self):
        self.достижения: list[str] = []
        self.бизнесы: list[dict] = []
        self.питомцы: list[str] = []
        self.инвентарь: list[str] = []
        self.титулы: list[str] = []
        self.трогали: list[str] = []      # что витрина попыталась изменить

    async def get_achievements(self, chat_id, user_id):
        return [{"code": c} for c in self.достижения]

    async def list_user_businesses(self, chat_id, user_id):
        return [dict(b) for b in self.бизнесы]

    async def list_pets(self, chat_id, user_id):
        return [{"pet_key": k} for k in self.питомцы]

    async def list_inventory(self, chat_id, user_id):
        return [{"item_key": k} for k in self.инвентарь]

    async def list_user_titles(self, chat_id, user_id):
        return [{"title_key": k} for k in self.титулы]

    # Всё, чего витрина касаться не должна: любое обращение записывается.
    async def grant_title(self, *a, **k):
        self.трогали.append("grant_title")

    async def grant_achievement(self, *a, **k):
        self.трогали.append("grant_achievement")

    async def add_coins(self, *a, **k):
        self.трогали.append("add_coins")

    async def set_active_title(self, *a, **k):
        self.трогали.append("set_active_title")


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(g, "db", w)
    return w


# --- достижения --------------------------------------------------------------

@_sync
async def test_показываются_все_и_помечены_полученные(мир):
    код = next(iter(achievements_meta.ACHIEVEMENTS))
    мир.достижения = [код]
    итог = await g.achievements(ЧАТ, ЧЕЛОВЕК)
    assert итог["total"] == len(achievements_meta.ACHIEVEMENTS)
    assert итог["earned"] == 1
    assert len(итог["items"]) == итог["total"], "неполученные не показаны"
    свои = [x for x in итог["items"] if x["earned"]]
    assert [x["code"] for x in свои] == [код]


@_sync
async def test_порядок_как_в_реестре(мир):
    """Реестр сгруппирован по смыслу — награды, сообщения, стрик, игры.
    Сортировка по дате получения рассыпала бы группы, ради которых список и
    читают."""
    итог = await g.achievements(ЧАТ, ЧЕЛОВЕК)
    assert [x["code"] for x in итог["items"]] == list(achievements_meta.ACHIEVEMENTS)


@_sync
async def test_у_каждого_есть_значок_название_и_описание(мир):
    итог = await g.achievements(ЧАТ, ЧЕЛОВЕК)
    for x in итог["items"]:
        assert x["emoji"] and x["title"] and x["desc"], f"пустое поле у {x['code']}"


@_sync
async def test_чужой_код_в_счёт_не_идёт(мир):
    """В базе может лежать код от достижения, которое давно убрали."""
    мир.достижения = ["его_больше_нет"]
    итог = await g.achievements(ЧАТ, ЧЕЛОВЕК)
    assert итог["earned"] == 0


# --- коллекции ---------------------------------------------------------------

@_sync
async def test_прогресс_считает_по_каталогу_чата(мир):
    """Питомцы считаются по каталогу ЧАТА: админ мог завести своих, и без них
    коллекция была бы уже неполной."""
    мир.питомцы = ["cat", "dog"]
    каталог = {"cat": {}, "dog": {}, "fox": {}, "own": {}}
    прогресс = await g.collection_progress(ЧАТ, ЧЕЛОВЕК, pet_specs=каталог)
    assert прогресс["zoo"] == (2, 4)


@_sync
async def test_хлам_считается_по_инвентарю(мир):
    мир.инвентарь = ["junk_a", "junk_c", "не_хлам"]
    прогресс = await g.collection_progress(ЧАТ, ЧЕЛОВЕК)
    assert прогресс["junk"] == (2, 3)


@_sync
async def test_империя_считает_только_прокачанные(мир):
    import businesses as каталог
    мир.бизнесы = [{"level": 1}, {"level": каталог.MAX_LEVEL}]
    прогресс = await g.collection_progress(ЧАТ, ЧЕЛОВЕК)
    assert прогресс["tycoon"][0] == 2
    assert прогресс["empire"][0] == 1


@_sync
async def test_витрина_отмечает_полученный_титул(мир):
    """Титул за полный сбор уже на руках — коллекция закрыта, даже если
    каталог с тех пор вырос."""
    c = collections_meta.COLLECTIONS[0]
    мир.титулы = [c.title_key]
    итог = await g.collections(ЧАТ, ЧЕЛОВЕК)
    строка = next(x for x in итог["items"] if x["key"] == c.key)
    assert строка["rewarded"] is True
    остальные = [x for x in итог["items"] if x["key"] != c.key]
    assert all(not x["rewarded"] for x in остальные)


@_sync
async def test_показываются_все_коллекции(мир):
    итог = await g.collections(ЧАТ, ЧЕЛОВЕК)
    assert [x["key"] for x in итог["items"]] == [c.key for c in collections_meta.COLLECTIONS]
    for x in итог["items"]:
        assert x["name"] and x["description"] and x["total"] >= 0


# --- витрина ничего не меняет ------------------------------------------------

@_sync
async def test_просмотр_ничего_не_выдаёт(мир):
    """Позови витрина проверку коллекций или выдачу титула — и открытие
    экрана начало бы что-то выдавать, причём каждый раз."""
    мир.питомцы = ["cat"]
    мир.инвентарь = list(_World.JUNK_ITEM_KEYS)      # хлам собран полностью
    await g.collections(ЧАТ, ЧЕЛОВЕК, pet_specs={"cat": {}})
    await g.achievements(ЧАТ, ЧЕЛОВЕК)
    assert мир.трогали == [], f"витрина полезла менять: {мир.трогали}"


КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


def test_в_модуле_витрины_нет_выдачи():
    """Структурно, а не только поведением: соблазн дописать «раз уж мы всё
    посчитали, заодно и выдадим» здесь особенно велик."""
    текст = (КОРЕНЬ / "gallery_actions.py").read_text(encoding="utf-8")
    for запрет in ("grant_title", "grant_achievement", "add_coins",
                   "set_active_title", "add_inventory_item"):
        assert запрет not in текст, f"витрина умеет менять: {запрет}"


def test_реестр_и_прогресс_общие_с_ботом():
    бот = (КОРЕНЬ / "bot.py").read_text(encoding="utf-8")
    assert "ACHIEVEMENTS = achievements_meta.ACHIEVEMENTS" in бот, (
        "у бота снова свой реестр достижений")
    assert 'ACHIEVEMENTS: dict = {' not in бот
    assert "gallery_actions.collection_progress(" in бот, (
        "бот считает прогресс коллекций сам — он разойдётся с кабинетом")


def test_панель_только_читает():
    файл = (КОРЕНЬ / "webpanel" / "member_gallery_api.py").read_text(encoding="utf-8")
    assert "@router.post" not in файл, "у витрины появился обработчик записи"
    assert "gallery_actions.achievements" in файл and "gallery_actions.collections" in файл
