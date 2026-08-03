"""Неделя у всего бота начинается в один и тот же день — и день этот настраивается.

Жалоба: в профиле «за неделю 25», а в топе за ту же неделю у того же
человека — 125. Причина: правило «когда начинается неделя» было записано
дважды. bot._current_week_start отсчитывал от субботы (как просил владелец),
а db.get_activity_breakdown — от понедельника, своим отдельным
`today - today.weekday()`. У профиля неделя начиналась на два дня позже, и
суббота с воскресеньем в неё не попадали.

Заодно «стата/топ {период}» считали скользящее окно (последние 7 и 30 суток)
вместо календарных недели и месяца. Совпадало с нормой ровно по пятницам,
когда сегодня-минус-6 случайно попадает на субботу.

Тест сравнивает МОДУЛИ ДРУГ С ДРУГОМ, а не каждый сам с собой: проверка
«неделя начинается в субботу» отдельно в bot.py уже была (test_bot_routing) и
этого бага не поймала — вторая половина правила жила в другом файле.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402

# Неделя, где есть все дни: суббота 25.07.2026 — пятница 31.07.2026 и
# следующая суббота, на которой отсчёт обязан перескочить.
СУББОТА = date(2026, 7, 25)
НЕДЕЛЯ = [СУББОТА + timedelta(days=i) for i in range(8)]
ДНИ = [d.strftime("%a %d.%m") for d in НЕДЕЛЯ]


@pytest.fixture
def настройка_недели():
    """Кэш настройки живёт в модуле db — оставленное значение поехало бы в
    соседние тесты (у них неделя начиналась бы не там, где они ждут)."""
    было = (db_module._week_start_weekday, db_module._week_start_loaded)
    yield db_module._remember_week_start
    db_module._week_start_weekday, db_module._week_start_loaded = было


def test_по_умолчанию_неделя_с_субботы(настройка_недели):
    """Так просил считать владелец; настройка не трогана — значит суббота."""
    настройка_недели({})
    assert db_module.WEEK_START_DEFAULT == 5
    assert db_module.week_start_weekday() == 5
    assert db_module.week_start_day(date(2026, 7, 31)) == СУББОТА


@pytest.mark.parametrize("день_недели", range(7))
def test_настройка_двигает_границу(настройка_недели, день_недели):
    """Ради этого день и вынесен в настройку: правкой исходников его менять
    неправильно."""
    настройка_недели({"week_start_weekday": день_недели})

    начало = db_module.week_start_day(date(2026, 7, 31))
    assert начало.weekday() == день_недели
    assert начало <= date(2026, 7, 31)
    assert date(2026, 7, 31) - начало < timedelta(days=7)


def test_пустая_и_битая_настройка_дают_дефолт(настройка_недели):
    """NULL в колонке — «админ не трогал». Мусор — тоже не повод считать
    неделю от понедельника молча."""
    for значение in ({}, {"week_start_weekday": None}, {"week_start_weekday": "суббота"}):
        настройка_недели(значение)
        assert db_module.week_start_weekday() == db_module.WEEK_START_DEFAULT


@pytest.mark.parametrize("день", НЕДЕЛЯ, ids=ДНИ)
def test_неделя_не_длиннее_семи_дней(настройка_недели, день):
    настройка_недели({})
    начало = db_module.week_start_day(день)
    assert начало.weekday() == 5
    assert начало <= день
    assert день - начало < timedelta(days=7)


def test_в_день_начала_неделя_отсчитывается_заново(настройка_недели):
    """Границу проверяем явно: ошибка на день здесь незаметна шесть дней из
    семи, а на седьмой неделя молча растягивается вдвое."""
    настройка_недели({})
    assert db_module.week_start_day(date(2026, 7, 31)) == СУББОТА       # пятница
    assert db_module.week_start_day(date(2026, 8, 1)) == СУББОТА + timedelta(days=7)


@pytest.mark.parametrize("день_недели", range(7))
def test_профиль_норма_и_топ_считают_одну_и_ту_же_неделю(настройка_недели, день_недели):
    """Ровно то, что разъехалось. Проверяем при ЛЮБОЙ настройке: правило одно,
    и все спрашивают его у db, а не считают сами."""
    настройка_недели({"week_start_weekday": день_недели})
    эталон = db_module.week_start_day()

    assert db_module.period_start_day("week") == эталон
    assert bot_module._current_week_start() == эталон
    assert bot_module._period_cutoff_day("week") == эталон
    assert bot_module._participants_period_start("week") == эталон


def test_месяц_считается_с_первого_числа_везде():
    """Тот же дефект, что и у недели: в профиле месяц был календарным, а в
    «стата месяц» — последними 30 сутками."""
    assert db_module.period_start_day("month", date(2026, 7, 31)) == date(2026, 7, 1)
    assert bot_module._period_cutoff_day("month") == db_module.period_start_day("month")
    assert bot_module._participants_period_start("month") == db_module.period_start_day("month")


def test_за_всё_время_отсечки_нет():
    """None здесь — рабочее значение: по нему вызывающий переключается с
    посуточной message_daily на общий счётчик message_stats. Верни отсюда
    дату — и «топ за всё время» станет топом за сегодня."""
    assert db_module.period_start_day("all") is None
    assert bot_module._period_cutoff_day("all") is None


def test_настройка_подхватывается_из_строки_настроек(monkeypatch, настройка_недели):
    """fetch_settings — единственная дорога к строке настроек, и её проходят
    оба процесса. Панель не зовёт отдельный загрузчик и не должна."""
    настройка_недели({})

    async def fetchone(query, params=()):
        return {"id": 1, "week_start_weekday": 0}

    monkeypatch.setattr(db_module, "_fetchone", fetchone)
    asyncio.run(db_module.fetch_settings())

    assert db_module.week_start_weekday() == 0
    assert bot_module._current_week_start().weekday() == 0


def test_окна_профиля_и_топа_совпадают_по_дате(monkeypatch, настройка_недели):
    """Одного совпадения правил мало: у профиля и у топа это РАЗНЫЕ запросы, и
    расхождение в границе (`>` вместо `>=`, вчерашняя дата) выглядело бы ровно
    как тот же баг. Сверяем то, что реально уходит в SQL."""
    настройка_недели({"week_start_weekday": 5})
    запросы: list[tuple] = []

    async def fetchone(query, params=()):
        запросы.append((" ".join(query.split()), params))
        return None

    async def fetchall(query, params=()):
        запросы.append((" ".join(query.split()), params))
        return []

    monkeypatch.setattr(db_module, "_fetchone", fetchone)
    monkeypatch.setattr(db_module, "_fetchall", fetchall)

    asyncio.run(db_module.get_activity_breakdown(-100, 555))
    профиль_sql, профиль_params = запросы[0]
    # (today, week_start, month_start, chat_id, user_id) — см. сам запрос
    assert профиль_params[1] == db_module.week_start_day()

    запросы.clear()
    cutoff = bot_module._period_cutoff_day("week")
    asyncio.run(db_module.list_top_messages_period(-100, cutoff, limit=10))
    for _sql, params in запросы:
        assert params[1] == db_module.week_start_day(), "топ считает от другой даты"

    # Обе выборки включают сам день начала — иначе разница была бы ровно в
    # день, с которого неделя начинается.
    assert "day >= %s" in профиль_sql
    assert all("day >= %s" in sql for sql, _ in запросы)


def test_подпись_периода_показывает_дату_начала():
    """В день начала недели «за неделю» законно показывает почти ноль — без
    даты это читается как поломка бота, а не как начало новой недели."""
    подпись = bot_module._stat_period_title("week", СУББОТА)
    assert "неделю" in подпись and "25.07" in подпись
    # У суток дата — это сегодня, а у «всего времени» её нет вовсе.
    assert bot_module._stat_period_title("day", date.today()) == "сутки"
    assert bot_module._stat_period_title("all", None) == "всё время"


# ---------------------------------------------------------------------------
# Команда «начало недели»
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("слово,ожидание", [
    ("понедельник", 0), ("пн", 0), ("понедельника", 0),
    ("вторник", 1), ("среду", 2), ("четверг", 3), ("пятницы", 4),
    ("суббота", 5), ("сб", 5), ("субботу", 5),
    ("воскресенье", 6), ("вс", 6),
    ("Суббота", 5), ("  сб  ", 5),
])
def test_день_недели_понимается_словом(слово, ожидание):
    assert bot_module.parse_weekday(слово) == ожидание


@pytest.mark.parametrize("слово", ["завтра", "выходные", "7", ""])
def test_непонятный_день_не_угадывается(слово):
    assert bot_module.parse_weekday(слово) is None


class _Сообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": -100, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": 1, "full_name": "Админ", "username": None})()
        self.ответы: list[str] = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def _настройки(monkeypatch, настройка_недели):
    """Подменяет сохранение настройки — как её видит бот, без базы."""
    сохранено: dict = {}

    async def save_setting(field, value):
        сохранено[field] = value

    async def fetch_settings():
        db_module._remember_week_start(сохранено)
        return dict(сохранено)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.db, "save_setting", save_setting, raising=False)
    monkeypatch.setattr(bot_module.db, "fetch_settings", fetch_settings, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", noop, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: True)
    настройка_недели({})
    return сохранено


def test_команда_показывает_текущее_начало_недели(_настройки):
    msg = _Сообщение("начало недели")
    asyncio.run(bot_module.cmd_week_start(msg))

    assert "субботы" in msg.ответы[0]
    assert _настройки == {}, "показ не должен ничего сохранять"


def test_команда_меняет_начало_недели(_настройки):
    msg = _Сообщение("начало недели понедельник")
    asyncio.run(bot_module.cmd_week_start(msg))

    assert _настройки["week_start_weekday"] == 0
    assert db_module.week_start_weekday() == 0, "новая граница должна работать сразу"
    assert bot_module._current_week_start().weekday() == 0


def test_команда_не_принимает_ерунду(_настройки):
    msg = _Сообщение("начало недели завтра")
    asyncio.run(bot_module.cmd_week_start(msg))

    assert _настройки == {}
    assert "Не понял день" in msg.ответы[0]


def test_права_на_смену_проверяются(monkeypatch, _настройки):
    monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: False)
    monkeypatch.setattr(bot_module, "get_level", lambda *a, **k: 1)

    msg = _Сообщение("начало недели понедельник")
    asyncio.run(bot_module.cmd_week_start(msg))

    assert _настройки == {}
    assert "⛔" in msg.ответы[0]


# ---------------------------------------------------------------------------
# «Итоги недели» — та же неделя, что у нормы и топов
# ---------------------------------------------------------------------------
@pytest.fixture
def дайджест(monkeypatch, настройка_недели):
    """Перехватывает выборки сводки и отправку в чат."""
    настройка_недели({})
    вызовы: dict = {}
    отправлено: list[tuple] = []
    хранилище: dict = {}

    async def запомнить(имя, chat_id, *args, **kwargs):
        вызовы[имя] = (args, kwargs)
        return []

    async def count_messages_since(chat_id, since_day, until_day=None):
        вызовы["count"] = (since_day, until_day)
        return 10

    async def get_top_active_since(chat_id, since_day, limit=5, until_day=None):
        вызовы["top"] = (since_day, until_day)
        return []

    async def get_data(key):
        return {"data_value": хранилище[key]} if key in хранилище else None

    async def set_data(key, value, updated_by=None):
        хранилище[key] = value

    async def list_data_by_prefix(prefix):
        return [{"data_key": "digest:-100", "data_value": "1"}]

    async def send_message(chat_id, text, **kwargs):
        отправлено.append((chat_id, text))

    monkeypatch.setattr(bot_module.db, "count_messages_since", count_messages_since, raising=False)
    monkeypatch.setattr(bot_module.db, "get_top_active_since", get_top_active_since, raising=False)
    for имя in ("get_new_members_since", "get_marriages_since",
                "get_achievements_since", "get_reputation_gainers_since"):
        monkeypatch.setattr(
            bot_module.db, имя,
            (lambda имя: lambda chat_id, *a, **k: запомнить(имя, chat_id, *a, **k))(имя),
            raising=False,
        )
    monkeypatch.setattr(bot_module.db, "get_data", get_data, raising=False)
    monkeypatch.setattr(bot_module.db, "set_data", set_data, raising=False)
    monkeypatch.setattr(bot_module.db, "list_data_by_prefix", list_data_by_prefix, raising=False)
    monkeypatch.setattr(bot_module.bot, "send_message", send_message, raising=False)
    return {"вызовы": вызовы, "отправлено": отправлено, "хранилище": хранилище}


def test_ручные_итоги_считают_текущую_неделю(дайджест):
    """Раньше это было скользящее окно в 7 суток, и «неделя» в сводке
    начиналась где придётся — не там, где у нормы и топов."""
    текст = asyncio.run(bot_module.build_weekly_digest(-100))

    начало, конец = дайджест["вызовы"]["count"]
    assert начало == db_module.week_start_day()
    assert конец is None, "у текущей недели верхней границы нет"
    assert f"с {bot_module.fmt_date(начало)}" in текст


def test_автопост_подводит_итог_завершившейся_недели(дайджест):
    """Постим на границе: сводка новой недели, которой сутки от роду, никому
    не нужна. Верхняя граница обязательна — иначе в итог прошлой недели
    попали бы сообщения новой."""
    asyncio.run(bot_module.post_due_weekly_digests())

    начало, конец = дайджест["вызовы"]["count"]
    assert конец == db_module.week_start_day()
    assert начало == конец - timedelta(days=7)
    assert дайджест["отправлено"], "сводка не ушла в чат"


def test_за_одну_неделю_автопост_срабатывает_один_раз(дайджест):
    asyncio.run(bot_module.post_due_weekly_digests())
    было = len(дайджест["отправлено"])

    asyncio.run(bot_module.post_due_weekly_digests())

    assert len(дайджест["отправлено"]) == было, "сводка ушла второй раз за ту же неделю"
    assert дайджест["хранилище"]["digestlast:-100"] == db_module.week_start_day().isoformat()


def test_новая_неделя_снова_разрешает_автопост(дайджест):
    asyncio.run(bot_module.post_due_weekly_digests())
    # Метка прошлой недели — как будто наступила следующая.
    дайджест["хранилище"]["digestlast:-100"] = (
        db_module.week_start_day() - timedelta(days=7)).isoformat()

    asyncio.run(bot_module.post_due_weekly_digests())

    assert len(дайджест["отправлено"]) == 2
