"""Профиль и топы вне телеграма.

Главное, что здесь проверяется, — неделя. Профиль и топ за неделю однажды уже
разошлись (профиль считал с понедельника, топ с субботы), и человек видел «25»
в одном месте и «125» в другом. Граница обязана быть одна на оба.
"""

from __future__ import annotations

import asyncio
import functools
import re
from datetime import datetime, timedelta

import pytest

import db
import fishing
import professions
import profile_actions


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


ЩУКА = next(s for s in fishing.SPECIES if not s.is_junk)


class _World:
    def __init__(self):
        self.люди = {
            7: {"user_id": 7, "full_name": "Лина", "username": "lina"},
            8: {"user_id": 8, "full_name": None, "username": "dolka"},
            9: {"user_id": 9},
        }

    async def get_known_user(self, chat_id, user_id):
        return self.люди.get(user_id)

    async def get_message_stats(self, chat_id, user_id):
        return {"message_count": 1234, "first_seen_at": datetime(2026, 1, 1),
                "last_message_at": datetime(2026, 8, 1)}

    async def get_message_rank(self, chat_id, user_id):
        return 3

    async def get_activity_breakdown(self, chat_id, user_id):
        # Имена — РОВНО те, что у настоящей функции. Заглушка со своими
        # именами один раз уже «подтвердила» баг: профиль читал day/week/month
        # и показывал нули, а тест этого не видел.
        return {"last_24h_count": 18, "today_count": 12, "week_count": 25,
                "month_count": 400}

    async def get_wallet(self, chat_id, user_id):
        return {"coins": 54321, "total_farms": 27}

    async def get_profile_card(self, chat_id, user_id):
        return {"active_title": "👑 Король чата"}

    async def get_achievements(self, chat_id, user_id):
        return [{"code": "fish_100"}, {"code": "work_20"}]

    async def get_user_clan(self, chat_id, user_id):
        return {"name": "Волки", "role": "leader"}

    async def get_fishing_stats(self, chat_id, user_id):
        return {"total_catches": 40, "best_weight": 4200,
                "best_weight_species": ЩУКА.key}

    async def get_profession_stats(self, chat_id, user_id):
        return {"profession_key": "уборщик", "prof_level": 4,
                "total_shifts": 61, "work_streak": 7}

    async def list_user_businesses(self, chat_id, user_id):
        return [{"business_key": "a"}, {"business_key": "b"}]

    async def list_pets(self, chat_id, user_id):
        return [{"pet_key": "cat"}]

    # --- топы ---
    async def list_top_messages(self, chat_id, limit=10, offset=0):
        return [{"user_id": 7, "message_count": 1234},
                {"user_id": 8, "message_count": 900}], 2

    async def list_top_messages_period(self, chat_id, since_day, limit=10, offset=0):
        self.неделя_с = since_day
        return [{"user_id": 8, "message_count": 25}], 1

    async def list_coins_top(self, chat_id, limit=10, offset=0):
        return [{"user_id": 7, "coins": 54321}], 1

    async def list_fishing_weight_top(self, chat_id, limit=10):
        return [{"user_id": 7, "best_weight": 4200,
                 "best_weight_species": ЩУКА.key, "total_catches": 40}]

    async def list_profession_top(self, chat_id, limit=10):
        # РОВНО те столбцы, что отдаёт настоящий запрос. Заглушка со своими
        # именами один раз уже «подтвердила» баг: экран показывал смены,
        # которых в выборке нет, и у всех выходил ноль.
        return [{"user_id": 9, "profession_key": "уборщик", "prof_level": 4,
                 "prof_xp": 350, "total_earned": 12000}]

    async def get_achievements_top(self, chat_id, limit=10):
        return [{"user_id": 7, "total": 12}]

    # Границу недели заглушка НЕ подменяет: она общая для всего бота, и весь
    # смысл проверки в том, что модуль зовёт именно её.
    period_start_day = staticmethod(db.period_start_day)


CHAT, USER = -100, 7


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(profile_actions, "db", world)
    return world


# --- профиль ----------------------------------------------------------------

@_sync
async def test_профиль_собирает_карточку(мир):
    карточка = await profile_actions.profile(CHAT, USER)
    assert карточка["name"] == "Лина" and карточка["username"] == "lina"
    assert карточка["messages"] == 1234 and карточка["rank"] == 3
    assert карточка["coins"] == 54321
    assert карточка["title"] == "👑 Король чата"
    assert карточка["clan"] == "Волки"
    assert карточка["achievements"] == 2
    assert карточка["businesses"] == 2 and карточка["pets"] == 1


@_sync
async def test_профиль_показывает_занятия(мир):
    карточка = await profile_actions.profile(CHAT, USER)
    assert карточка["work"]["name"] == professions.PROFESSIONS["уборщик"]["name"]
    assert карточка["work"]["level"] == 4 and карточка["work"]["shifts"] == 61
    assert карточка["fishing"]["best_species"] == ЩУКА.name
    assert карточка["fishing"]["best_weight_text"]


@_sync
async def test_звёздность_считается_общей_функцией(мир):
    """Звёзды в профиле и грядки на ферме обязаны считаться одинаково."""
    import farm_actions
    карточка = await profile_actions.profile(CHAT, USER)
    ожидаемо, _есть, _надо = farm_actions.farm_star_progress(27)
    assert карточка["stars"] == ожидаемо


@_sync
async def test_профиль_переживает_сбой_части(мир, monkeypatch):
    """Витрина: упавший запрос по питомцам не должен уносить с собой монеты."""
    async def падает(*a, **k):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(мир, "list_pets", падает)
    monkeypatch.setattr(мир, "get_user_clan", падает)
    карточка = await profile_actions.profile(CHAT, USER)
    assert карточка["coins"] == 54321
    assert карточка["pets"] == 0 and карточка["clan"] is None


@_sync
async def test_безымянного_показываем_ником_или_номером(мир):
    без_имени = await profile_actions.profile(CHAT, 8)
    assert без_имени["name"] == "dolka"
    совсем = await profile_actions.profile(CHAT, 9)
    assert совсем["name"].startswith("id ")


# --- топы -------------------------------------------------------------------

@_sync
async def test_у_каждого_топа_есть_строки_и_места(мир):
    все = await profile_actions.tops(CHAT)
    assert set(все["tables"]) == set(profile_actions.TOPS)
    for вид, таблица in все["tables"].items():
        assert таблица["title"] and "rows" in таблица
        места = [r["place"] for r in таблица["rows"]]
        assert места == list(range(1, len(места) + 1)), f"{вид}: места не по порядку"
        assert all(r["name"] for r in таблица["rows"]), f"{вид}: строка без имени"


@_sync
async def test_неделя_берётся_из_общей_границы(мир):
    """Своя граница здесь — это ровно тот баг, из-за которого профиль и топ
    показывали разные числа за одну и ту же неделю."""
    await profile_actions.top(CHAT, "week")
    assert мир.неделя_с == db.period_start_day("week")


@_sync
async def test_рыбный_топ_называет_вид_и_вес(мир):
    таблица = await profile_actions.top(CHAT, "fishing")
    строка = таблица["rows"][0]
    assert строка["text"] == fishing.format_weight(4200)
    assert ЩУКА.name in строка["note"]


@_sync
async def test_рабочий_топ_показывает_то_по_чему_отсортирован(мир):
    """Топ отсортирован по уровню (см. db.list_profession_top), значит уровень
    и надо показывать. Раньше показывались смены — столбца с ними в выборке
    нет вовсе, и у всех честно выходил ноль, а порядок строк не сходился с
    показанным числом."""
    таблица = await profile_actions.top(CHAT, "work")
    строка = таблица["rows"][0]
    assert строка["value"] == 4, "показываем уровень"
    assert таблица["unit"] == "ур."
    assert "Уборщик" in строка["note"]


def test_топы_читают_только_существующие_столбцы():
    """Тот самый класс ошибок: поле, которого запрос не отдаёт, молча даёт
    ноль. Заглушка тут не поможет — она может ошибаться вместе с кодом,
    поэтому столбцы берутся из ИСХОДНИКА запросов."""
    import inspect
    источники = [inspect.getsource(getattr(db, имя)) for имя in (
        "list_top_messages", "list_top_messages_period", "list_coins_top",
        "list_fishing_weight_top", "list_profession_top", "get_achievements_top")]
    столбцы = set()
    for источник in источники:
        столбцы |= set(re.findall(r"\bAS (\w+)", источник))
        # Запросы в db.py разрезаны на строки, и между списком столбцов и
        # словом FROM стоит кавычка, а не пробел: шаблон с пробелом не
        # находил ничего и «доказывал» отсутствие любых столбцов.
        for кусок in re.findall(r"SELECT\s+(.+?)\bFROM\b", источник, re.S):
            for часть in кусок.split(","):
                # Берём последнее слово части, выкинув кавычки и переносы:
                # запрос разрезан на строки, и у последнего столбца хвостом
                # висит кавычка — из-за неё он терялся.
                слова = re.findall(r"\w+", часть)
                if слова:
                    столбцы.add(слова[-1])
    читает = set(re.findall(r'r\.get\("(\w+)"\)|r\["(\w+)"\]',
                            inspect.getsource(profile_actions.top)))
    читает = {a or b for a, b in читает}
    лишние = читает - столбцы
    assert not лишние, f"эти столбцы запросы не отдают: {sorted(лишние)}"


@_sync
async def test_неизвестный_топ_не_роняет_экран(мир):
    таблица = await profile_actions.top(CHAT, "выдумка")
    assert таблица["rows"] == []


@_sync
async def test_активность_читается_настоящими_именами_столбцов(мир):
    """Профиль читает реальные имена полей, которые возвращает база."""
    карточка = await profile_actions.profile(CHAT, USER)
    assert карточка["activity"] == {"last_24h": 18, "day": 12, "week": 25,
                                    "month": 400}


def test_имена_столбцов_совпадают_с_базой():
    """Заглушка может ошибаться вместе с кодом — поэтому имена сверяются с
    ИСХОДНИКОМ db, а не с выдумкой теста."""
    import inspect
    исходник = inspect.getsource(db.get_activity_breakdown)
    столбцы = set(re.findall(r"AS (\w+_count)", исходник))
    assert столбцы == {"last_24h_count", "today_count", "week_count", "month_count"}
    читает = inspect.getsource(profile_actions.profile)
    for столбец in столбцы:
        assert f'"{столбец}"' in читает, f"профиль не читает {столбец}"
