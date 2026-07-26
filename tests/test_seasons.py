"""Сезоны: месячный зачёт и неотчуждаемые награды.

Две вещи, ради которых файл существует:

* Награда за место выдаётся РОВНО ОДИН РАЗ. Цикл закрытия ходит по всем
  чатам каждые полчаса и легко совпадает с ручным вызовом — без защиты
  титулы и ачивки раздались бы повторно.
* Награда неотчуждаема. Именно поэтому это титул и ачивка, а не предмет:
  предмет можно продать, подарить и украсть медвежатником, а титул нельзя
  ни отдать, ни потерять.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime

import pytest

import seasons as S

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


async def _noop(*args, **kwargs):
    return None


# --- ключи и границы месяцев -----------------------------------------------

def test_ключ_сезона_это_месяц():
    assert S.season_key(date(2026, 7, 26)) == "2026-07"
    assert S.season_key(date(2026, 12, 1)) == "2026-12"


def test_предыдущий_сезон_считается_через_январь():
    """Тут легко ошибиться на единицу и получить «2026-00»."""
    assert S.previous_season_key(date(2026, 1, 5)) == "2025-12"
    assert S.previous_season_key(date(2026, 8, 1)) == "2026-07"


def test_название_сезона_человеческое():
    assert S.season_label("2026-07") == "июль 2026"
    assert S.season_label("мусор") == "мусор"


# --- очки ------------------------------------------------------------------

def test_очки_идут_из_трёх_источников():
    """Смесь намеренная: за один источник зачёт накрутили бы спамом."""
    assert S.points_for_messages(10) > 0
    assert S.points_for_boss_damage(10_000) > 0
    assert S.points_for_coins(50_000) > 0


def test_у_сообщений_есть_потолок():
    """Иначе простыня из односимвольных сообщений решала бы сезон."""
    huge = S.points_for_messages(1_000_000)
    assert huge == S.MESSAGE_POINTS_CAP_PER_DAY * S.POINTS_PER_MESSAGE


def test_отрицательные_величины_не_дают_очков():
    assert S.points_for_messages(-5) == 0
    assert S.points_for_boss_damage(-100) == 0
    assert S.points_for_coins(-1000) == 0


def test_места_расставляются_стабильно():
    """При равных очках порядок не должен зависеть от обхода словаря."""
    assert S.rank({3: 10, 1: 10, 2: 10}) == [(1, 10), (2, 10), (3, 10)]


def test_нулевые_в_зачёт_не_идут():
    assert S.rank({1: 5, 2: 0}) == [(1, 5)]


def test_призовых_мест_ровно_столько_сколько_объявлено():
    scores = {i: 100 - i for i in range(1, 10)}
    assert len(S.winners(scores)) == S.PLACES


# --- награды ---------------------------------------------------------------

def test_титул_несёт_в_себе_сезон():
    """Ключ включает месяц — значит, титул за июль и за август это РАЗНЫЕ
    вещи, и первый второй раз получить уже невозможно."""
    july = S.award_for("2026-07", 1)
    august = S.award_for("2026-08", 1)
    assert july.title_key != august.title_key
    assert "2026-07" in july.title_key
    assert "июль" in july.title_name


def test_вне_призов_награды_нет():
    assert S.award_for("2026-07", 4) is None
    assert S.award_for("2026-07", 0) is None


def test_название_титула_влезает_в_колонку():
    """VARCHAR(64) — длинное имя сезона не должно обрезаться базой молча."""
    for place in range(1, S.PLACES + 1):
        assert len(S.award_for("2026-12", place).title_name) <= 64


# --- закрытие сезона -------------------------------------------------------

@pytest.fixture
def world(monkeypatch):
    state = {"closed": set(), "titles": [], "granted": [], "achievements": [],
             "scores": [{"user_id": 1, "points": 500},
                        {"user_id": 2, "points": 300},
                        {"user_id": 3, "points": 100}]}

    async def close_season(chat_id, season, now):
        if (chat_id, season) in state["closed"]:
            return False
        state["closed"].add((chat_id, season))
        return True

    async def list_season_scores(chat_id, season, limit=50):
        return state["scores"][:limit]

    async def add_title_if_missing(key, name, price=None):
        state["titles"].append(key)

    async def grant_title(chat_id, user_id, key):
        state["granted"].append((user_id, key))
        return True

    async def grant_achievement(chat_id, user_id, code, announce=True, **kw):
        state["achievements"].append((user_id, code))
        return True

    monkeypatch.setattr(bot_module.db, "close_season", close_season, raising=False)
    monkeypatch.setattr(bot_module.db, "list_season_scores", list_season_scores, raising=False)
    monkeypatch.setattr(bot_module.db, "add_title_if_missing", add_title_if_missing, raising=False)
    monkeypatch.setattr(bot_module.db, "grant_title", grant_title, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setattr(bot_module, "grant_achievement", grant_achievement, raising=False)
    monkeypatch.setattr(bot_module, "display_name_by_id", _returns("Игрок"), raising=False)
    return state


def test_закрытие_выдаёт_титулы_и_ачивки(world):
    text = asyncio.run(bot_module.close_season_for_chat(CHAT_ID, "2026-07"))
    assert text and "завершён" in text
    assert [u for u, _k in world["granted"]] == [1, 2, 3]
    assert [c for _u, c in world["achievements"]] == ["season_1", "season_2", "season_3"]


def test_повторное_закрытие_ничего_не_выдаёт(world):
    """Цикл ходит по чатам каждые полчаса и может совпасть с ручным вызовом —
    без защиты призы раздались бы дважды."""
    asyncio.run(bot_module.close_season_for_chat(CHAT_ID, "2026-07"))
    granted_once = len(world["granted"])
    again = asyncio.run(bot_module.close_season_for_chat(CHAT_ID, "2026-07"))
    assert again is None
    assert len(world["granted"]) == granted_once


def test_одновременное_закрытие_платит_один_раз(world):
    """Тот же сценарий, но параллельно."""
    async def storm():
        await asyncio.gather(*(bot_module.close_season_for_chat(CHAT_ID, "2026-07")
                               for _ in range(10)))
    asyncio.run(storm())
    assert len(world["granted"]) == 3, world["granted"]


def test_пустой_сезон_никого_не_награждает(world):
    world["scores"] = []
    assert asyncio.run(bot_module.close_season_for_chat(CHAT_ID, "2026-07")) is None
    assert not world["granted"]


def test_сезонный_титул_заводится_без_цены():
    """Титул без цены нельзя купить (см. cmd_title_buy) — это и делает его
    неотчуждаемым: не продаётся, не дарится, не покупается."""
    import inspect
    src = inspect.getsource(bot_module.close_season_for_chat)
    assert "add_title_if_missing(award.title_key, award.title_name)" in src, \
        "цену передавать нельзя — иначе сезонный титул попадёт в продажу"


def test_награда_не_предмет():
    """Предмет можно продать, подарить и украсть медвежатником. Поэтому
    сезонная награда — титул и ачивка, и ничего больше."""
    import inspect
    src = inspect.getsource(bot_module.close_season_for_chat)
    assert "add_inventory_item" not in src
    assert "grant_title" in src and "grant_achievement" in src
