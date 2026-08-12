"""Настройка баланса: множители кранов, лимит подработок и отчёт «экономика».

Три куска одной задачи — крутить, придержать и измерить. Ломаются они
по-своему, поэтому и проверяются по-разному: множитель — на порядке
применения, лимит — на смене суток, отчёт — на том, что он ничего не теряет.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta

import pytest

import activities
import chat_settings
import db as db_module

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


# --- множитель дохода -------------------------------------------------------

@pytest.mark.parametrize("percent,было,стало", [
    (100, 1000, 1000),      # умолчание ничего не меняет
    (50, 1000, 500),
    (200, 1000, 2000),
    (0, 1000, 0),           # выключенный источник
    (40, 2, 1),             # пол в 1 i¢: 40% от двух — это один, а не ноль
    (100, 0, 0),
])
def test_множитель_считает_итог(monkeypatch, percent, было, стало):
    monkeypatch.setattr(bot_module.db, "get_income_percent",
                        _returns(float(percent)), raising=False)
    got = asyncio.run(bot_module.apply_income_percent(CHAT_ID, "side_job", было))
    assert got == стало


def test_ноль_выключает_а_округление_нет(monkeypatch):
    """Ноль как РЕЗУЛЬТАТ означает «источник выключен». Получись он от
    округления — источник выключался бы сам, на мелких суммах, и объяснить это
    в панели было бы нечем."""
    monkeypatch.setattr(bot_module.db, "get_income_percent", _returns(1.0), raising=False)
    assert asyncio.run(bot_module.apply_income_percent(CHAT_ID, "fishing", 3)) == 1

    monkeypatch.setattr(bot_module.db, "get_income_percent", _returns(0.0), raising=False)
    assert asyncio.run(bot_module.apply_income_percent(CHAT_ID, "fishing", 3)) == 0


def test_каждое_слово_команды_ведёт_к_настройке():
    """INCOME_BY_WORD — то, что человек пишет в «доход рыбалка 50». Слово без
    настройки означало бы команду, которая отвечает «готово» и не делает
    ничего."""
    for слово, ключ in chat_settings.INCOME_BY_WORD.items():
        assert chat_settings.income_setting_key(ключ) in chat_settings.BY_KEY, слово
        assert ключ in chat_settings.INCOME_TITLES, слово


def test_ферма_не_получила_вторую_ручку():
    """У неё своя, более старая настройка economy.farm_yield. Две настройки на
    одно число — гарантированный вопрос «а какая из них главная»."""
    assert "ферма" not in chat_settings.INCOME_BY_WORD
    assert "economy.farm_yield" in chat_settings.BY_KEY


# --- суточный лимит подработок ---------------------------------------------

class _Учёт:
    """Подменяет счётчик суток тем же поведением, что и SQL: смена дня
    обнуляет, а не накапливает."""

    def __init__(self):
        self.день = None
        self.раз = 0

    async def count(self, chat_id, user_id, key, day):
        return self.раз if self.день == day else 0

    async def bump(self, chat_id, user_id, key, day):
        if self.день != day:
            self.день, self.раз = day, 0
        self.раз += 1


def test_счётчик_обнуляется_при_смене_суток():
    учёт = _Учёт()
    сегодня, завтра = date(2026, 7, 29), date(2026, 7, 30)

    asyncio.run(учёт.bump(CHAT_ID, USER_ID, "side_job", сегодня))
    asyncio.run(учёт.bump(CHAT_ID, USER_ID, "side_job", сегодня))
    assert asyncio.run(учёт.count(CHAT_ID, USER_ID, "side_job", сегодня)) == 2

    assert asyncio.run(учёт.count(CHAT_ID, USER_ID, "side_job", завтра)) == 0


def test_запрос_счётчика_обнуляет_вчерашнее(monkeypatch):
    """Обнуление живёт в ТОМ ЖЕ запросе, что и увеличение: отдельная полуночная
    задача означала бы, что после простоя бота лимит у всех остался
    вчерашним."""
    отправлено = {}

    async def execute(query, params=()):
        отправлено["q"] = " ".join(query.split())

    monkeypatch.setattr(db_module, "_execute", execute)
    asyncio.run(db_module.bump_activity_today(CHAT_ID, USER_ID, "side_job", date(2026, 7, 29)))

    assert "day_times = IF(last_day <=> VALUES(last_day), day_times + 1, 1)" in отправлено["q"]


def test_учёт_суток_не_затирается_обычной_отметкой(monkeypatch):
    """touch_earning_activity зовут без day, и раньше это писало NULL поверх
    отметки суток — то есть лимит обнулялся бы каждой подработкой."""
    отправлено = {}

    async def execute(query, params=()):
        отправлено["q"] = " ".join(query.split())

    monkeypatch.setattr(db_module, "_execute", execute)
    asyncio.run(db_module.touch_earning_activity(
        CHAT_ID, USER_ID, "side_job", datetime.utcnow(), earned=10))

    assert "last_day = IF(VALUES(last_day) IS NULL, last_day, VALUES(last_day))" in отправлено["q"]


def test_начисление_пишется_в_личную_историю(monkeypatch):
    запросы = []

    async def execute(query, params=()):
        запросы.append((" ".join(query.split()), params))

    monkeypatch.setattr(db_module, "_execute", execute)
    now = datetime(2026, 8, 13, 10, 30)
    asyncio.run(db_module.touch_earning_activity(
        CHAT_ID, USER_ID, "fishing", now, earned=250,
    ))

    history = next((q for q, _ in запросы if "INSERT INTO earning_history" in q), "")
    assert history
    assert any(params[-2:] == (250, now) for query, params in запросы
               if "INSERT INTO earning_history" in query)


@pytest.fixture
def лимит(monkeypatch):
    def настроить(предел, сделано):
        monkeypatch.setattr(bot_module.db, "get_side_job_daily_limit",
                            _returns(предел), raising=False)
        monkeypatch.setattr(bot_module.db, "count_activity_today",
                            _returns(сделано), raising=False)
    return настроить


def test_остаток_подработок_считается(лимит):
    лимит(16, 3)
    assert asyncio.run(bot_module._side_job_left_today(CHAT_ID, USER_ID)) == 13


def test_ноль_означает_без_лимита_а_не_запрет(лимит):
    """Ноль в настройке — «лимита нет». Прочитай его как «нельзя» — и чат,
    где настройку не трогали, остался бы без подработок вовсе."""
    лимит(0, 100)
    assert asyncio.run(bot_module._side_job_left_today(CHAT_ID, USER_ID)) is None


def test_исчерпанный_лимит_даёт_ноль_а_не_отрицательное(лимит):
    лимит(5, 9)
    assert asyncio.run(bot_module._side_job_left_today(CHAT_ID, USER_ID)) == 0


def test_панель_показывает_исчерпанный_лимит_ожиданием(лимит, monkeypatch):
    """Иначе панель обещает подработку готовой там, где команда откажет, —
    ровно тот разрыв, который спека панели объявляет недопустимым."""
    for имя, fn in {
        "get_earning_activity": _returns(None),
        "get_fishing_stats": _returns({}), "get_digger": _returns({}),
        "get_wallet": _returns({}),
        "get_profession_stats": _returns({"profession_key": None}),
        "get_robbery_stats": _returns({}), "is_under_surveillance": _returns(False),
        "get_income_percent": _returns(100.0),
    }.items():
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "_item_perk", _returns(0), raising=False)
    monkeypatch.setattr(bot_module, "_load_businesses", _returns([]), raising=False)
    лимит(16, 16)

    states, _ = asyncio.run(bot_module.collect_activity_states(CHAT_ID, USER_ID))
    подработка = {s.activity.key: s for s in states}["side_job"]

    assert not подработка.ready, "лимит исчерпан, а панель зовёт работать"
    assert подработка.left is not None
    assert подработка.left <= timedelta(days=1), "ждать до полуночи, а не дольше"


# --- отчёт «экономика» ------------------------------------------------------

def test_половина_денег_считается_по_убыванию():
    assert activities.wallets_holding_half([100, 1, 1, 1]) == 1
    assert activities.wallets_holding_half([25, 25, 25, 25]) == 2
    assert activities.wallets_holding_half([]) == 0
    assert activities.wallets_holding_half([0, 0]) == 0


def test_отчёт_не_теряет_работу(monkeypatch):
    """Работа живёт в своей таблице и в earning_activity не попадает. Забудь
    её — и из отчёта пропал бы один из самых крупных источников."""
    monkeypatch.setattr(bot_module.db, "economy_overview", _returns({
        "net": 900, "positive": 1000, "debt": 100, "holders": 3,
        "wallets": [600, 300, 100],
        "sources": {"side_job": (500, 12), "farm": (200, 5)},
        "profession": (900, 30),
        "treasury": 77,
    }), raising=False)

    текст = asyncio.run(bot_module._economy_report_text(CHAT_ID))

    assert "работа" in текст and "900" in текст
    assert "подработка" in текст and "ферма" in текст
    assert "Долгов" in текст, "долги нельзя прятать в «на руках»"
    assert "77" in текст, "казна потерялась"
    assert "<blockquote expandable>" in текст


def test_отчёт_честно_подписывает_накопительный_итог(monkeypatch):
    """Разбивки по неделям в базе нет. Приписать «за неделю» к накопительной
    сумме значило бы соврать в главном числе отчёта."""
    monkeypatch.setattr(bot_module.db, "economy_overview", _returns({
        "net": 10, "positive": 10, "debt": 0, "holders": 1, "wallets": [10],
        "sources": {"side_job": (5, 1)}, "profession": (0, 0), "treasury": 0,
    }), raising=False)

    текст = asyncio.run(bot_module._economy_report_text(CHAT_ID))
    assert "не за неделю" in текст


def test_пустой_чат_не_рисует_пустую_таблицу(monkeypatch):
    monkeypatch.setattr(bot_module.db, "economy_overview", _returns({
        "net": 0, "positive": 0, "debt": 0, "holders": 0, "wallets": [],
        "sources": {}, "profession": (0, 0), "treasury": 0,
    }), raising=False)

    текст = asyncio.run(bot_module._economy_report_text(CHAT_ID))
    assert "пока пусто" in текст


def test_каждый_источник_отчёта_имеет_название():
    """Ключ без подписи вывалился бы в отчёт голым «business_raid»."""
    для_отчёта = {bot_module.EARN_DAILY_BONUS, bot_module.EARN_SIDE_JOB,
                  bot_module.EARN_HAT, bot_module.EARN_FARM,
                  bot_module.EARN_FISHING, bot_module.EARN_TREASURE,
                  bot_module.EARN_BUSINESS_RAID}
    assert для_отчёта <= set(bot_module.ECONOMY_SOURCE_TITLES)
