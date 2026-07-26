"""Коллекции: награда за полный сбор.

Смысл механики — дать причину добрать последнее. Поэтому главное, что здесь
проверяется: коллекция не засчитывается частично, титул выдаётся ровно один
раз, а состав считается по КАТАЛОГУ ЧАТА (админ мог завести своих питомцев,
и без них зоопарк был бы неполным, хотя игрок собрал всё доступное).
"""

from __future__ import annotations

import asyncio
import os

import pytest

import businesses as B
import collections_meta as C
import pets as P
import seasons as S

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ME = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


# --- каталог ---------------------------------------------------------------

def test_коллекции_заполнены():
    for c in C.COLLECTIONS:
        assert c.name and c.emoji and c.description and c.title_name
        assert c.title_key.startswith("collection_")


def test_ключи_и_титулы_не_повторяются():
    assert len({c.key for c in C.COLLECTIONS}) == len(C.COLLECTIONS)
    assert len({c.title_key for c in C.COLLECTIONS}) == len(C.COLLECTIONS)


def test_ачивки_коллекций_существуют():
    """Ачивка без записи в каталоге не выдалась бы никогда."""
    for c in C.COLLECTIONS:
        assert c.achievement_code in bot_module.ACHIEVEMENTS, c.key


def test_полнота_считается_строго():
    assert not C.is_complete(4, 5)
    assert C.is_complete(5, 5)
    assert C.is_complete(6, 5), "перебор тоже полный сбор"
    assert not C.is_complete(0, 0), "пустая коллекция не считается собранной"


def test_полоса_прогресса_не_вылезает():
    for done in (-3, 0, 2, 5, 99):
        assert len(C.progress_text(done, 5)) == 10


def test_цепочка_сезонов_не_включает_текущий():
    """Текущий сезон ещё идёт, призы за него не выданы — требовать его
    значило бы требовать невозможного."""
    keys = C.season_streak_keys("2026-07", S.previous_of)
    assert "2026-07" not in keys
    assert keys == ["2026-06", "2026-05", "2026-04"]


def test_цепочка_переходит_через_январь():
    keys = C.season_streak_keys("2026-02", S.previous_of)
    assert keys == ["2026-01", "2025-12", "2025-11"]


# --- подсчёт прогресса -----------------------------------------------------

@pytest.fixture
def world(monkeypatch):
    state = {"businesses": [], "pets": [], "titles": [], "granted": [],
             "achievements": [], "announced": []}

    async def list_user_businesses(chat_id, user_id):
        return list(state["businesses"])

    async def list_pets(chat_id, user_id):
        return [{"pet_key": k} for k in state["pets"]]

    async def list_user_titles(chat_id, user_id):
        return [{"title_key": k} for k in state["titles"]]

    async def grant_title(chat_id, user_id, key):
        if key in state["granted"]:
            return False
        state["granted"].append(key)
        return True

    async def grant_achievement(chat_id, user_id, code, announce=True, **kw):
        state["achievements"].append(code)
        return True

    async def send_message(chat_id, text, **kw):
        state["announced"].append(text)

    monkeypatch.setattr(bot_module.db, "list_user_businesses", list_user_businesses, raising=False)
    monkeypatch.setattr(bot_module.db, "list_pets", list_pets, raising=False)
    monkeypatch.setattr(bot_module.db, "list_user_titles", list_user_titles, raising=False)
    monkeypatch.setattr(bot_module.db, "grant_title", grant_title, raising=False)
    monkeypatch.setattr(bot_module.db, "add_title_if_missing", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "ensure_pet_catalog", _returns(0), raising=False)
    monkeypatch.setattr(bot_module.db, "list_pet_catalog", _returns(
        [{"pet_key": p.key, "name": p.name, "emoji": p.emoji, "price": p.price,
          "sound": p.sound, "ability": p.ability, "is_active": True,
          "max_count": None} for p in P.PETS]), raising=False)
    monkeypatch.setattr(bot_module, "grant_achievement", grant_achievement, raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Игрок"), raising=False)
    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    return state


def _progress(world):
    return asyncio.run(bot_module._collection_progress(CHAT_ID, ME))


def _check(world):
    asyncio.run(bot_module._check_collections(CHAT_ID, ME))


def test_пустой_прогресс(world):
    p = _progress(world)
    assert p["tycoon"][0] == 0
    assert p["zoo"][0] == 0
    assert p["dynasty"][0] == 0


def test_бизнесы_считаются(world):
    world["businesses"] = [{"business_key": b.key, "level": 1} for b in B.BUSINESSES]
    p = _progress(world)
    assert p["tycoon"] == (len(B.BUSINESSES), len(B.BUSINESSES))
    assert p["empire"][0] == 0, "первый уровень — не империя"


def test_империя_требует_третьего_уровня(world):
    world["businesses"] = [{"business_key": b.key, "level": 3} for b in B.BUSINESSES]
    p = _progress(world)
    assert p["empire"] == (len(B.BUSINESSES), len(B.BUSINESSES))


def test_зоопарк_считается_по_каталогу_чата(world):
    """Не по встроенному списку: админ мог завести своих, и без них зоопарк
    был бы неполным, хотя игрок собрал всё доступное."""
    world["pets"] = [p.key for p in P.PETS]
    p = _progress(world)
    assert p["zoo"] == (len(P.PETS), len(P.PETS))


def test_династия_считает_призовые_сезоны(world):
    keys = C.season_streak_keys(bot_module._current_season(), S.previous_of)
    world["titles"] = [f"season_{keys[0]}_1", f"season_{keys[1]}_3"]
    p = _progress(world)
    assert p["dynasty"][0] == 2, "два сезона из трёх"


def test_любое_призовое_место_годится(world):
    keys = C.season_streak_keys(bot_module._current_season(), S.previous_of)
    world["titles"] = [f"season_{k}_{place}" for k, place in zip(keys, (1, 2, 3))]
    p = _progress(world)
    assert p["dynasty"][0] == C.SEASON_STREAK


# --- выдача награды --------------------------------------------------------

def test_неполная_коллекция_ничего_не_даёт(world):
    world["businesses"] = [{"business_key": b.key, "level": 1}
                           for b in B.BUSINESSES[:-1]]
    _check(world)
    assert not world["granted"]
    assert not world["announced"]


def test_полная_коллекция_выдаёт_титул_и_ачивку(world):
    world["businesses"] = [{"business_key": b.key, "level": 1} for b in B.BUSINESSES]
    _check(world)
    assert "collection_tycoon" in world["granted"]
    assert "collection_tycoon" in world["achievements"]
    assert any("Промышленник" in t for t in world["announced"])


def test_повторная_проверка_не_объявляет_дважды(world):
    """Проверка зовётся после каждой покупки и апгрейда — без этого чат
    заваливало бы одним и тем же поздравлением."""
    world["businesses"] = [{"business_key": b.key, "level": 1} for b in B.BUSINESSES]
    _check(world)
    announced_once = len(world["announced"])
    _check(world)
    assert len(world["announced"]) == announced_once


def test_несколько_коллекций_сразу(world):
    """Все бизнесы на 3 уровне — это и «Промышленник», и «Империя»."""
    world["businesses"] = [{"business_key": b.key, "level": 3} for b in B.BUSINESSES]
    _check(world)
    assert "collection_tycoon" in world["granted"]
    assert "collection_empire" in world["granted"]


def test_коллекционный_титул_нельзя_купить():
    """Заводится без цены, а «титул купить» отвергает всё без цены."""
    import inspect
    src = inspect.getsource(bot_module._check_collections)
    assert "add_title_if_missing(collection.title_key, collection.title_name)" in src
