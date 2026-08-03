"""Сверка по времени: где бот обязан считать в UTC, а где — по часовому поясу.

Правило в самом боте (см. блок «Границы суток» в bot.py) простое:

  * читаешь message_daily — считай сутки по UTC, потому что пишутся её строки
    по UTC и там уже лежит история;
  * своя колонка-отметка (бонусы, лимиты, ротации) — по настроенной зоне, там
    чужой истории нет, а человек ждёт своей полуночи.

Половина мест правилу не следовала: в чате на МСК «ежедневный» бонус
обновлялся в три ночи, а казиношный — в полночь. Плюс два места брали зону
ОПЕРАЦИОННОЙ СИСТЕМЫ (date.today()/datetime.now()), то есть ни то ни другое,
и молчали, пока сервер стоял на UTC.

Отдельно — сессия MySQL: NOW() и CURRENT_TIMESTAMP считаются в её зоне, а
питон пишет utcnow(). Пока зона сессии не задана, всё сходится только на
UTC-сервере.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
from datetime import date, datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import activity_chart  # noqa: E402
import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402


@pytest.fixture
def пояс(monkeypatch):
    def поставить(name):
        monkeypatch.setitem(bot_module.settings, "timezone", name)
    return поставить


# ---------------------------------------------------------------------------
# Сессия базы
# ---------------------------------------------------------------------------
def test_сессия_mysql_пришпилена_к_utc():
    """NOW(), CURRENT_TIMESTAMP и ON UPDATE CURRENT_TIMESTAMP считаются в зоне
    СЕССИИ. Питон пишет utcnow(). Не задать зону — значит поставить всякий
    срок и кулдаун в зависимость от настроек сервера БД, причём молча: на
    UTC-сервере сходится, при переезде разъезжается на смещение."""
    src = inspect.getsource(db_module.init_pool)
    assert "init_command" in src
    assert re.search(r"time_zone\s*=\s*'\+00:00'", src)


def test_решение_по_заявке_пишется_в_utc():
    """datetime.now() берёт зону ОС — отметка уезжала относительно соседних."""
    src = inspect.getsource(db_module.mark_request_decided)
    assert "datetime.utcnow()" in src
    assert "datetime.now()" not in src.replace("datetime.utcnow()", "")


# ---------------------------------------------------------------------------
# График активности
# ---------------------------------------------------------------------------
def test_график_строит_ряд_от_utc_суток():
    """Данные графика — из message_daily (UTC-сутки). Раньше последний день
    ряда брался date.today(), то есть по зоне ОС: восточнее UTC последний
    столбец оказывался завтрашним, а сегодняшние сообщения не попадали в ряд
    вовсе."""
    сегодня_utc = datetime.utcnow().date()
    rows = [{"day": сегодня_utc, "message_count": 42}]

    дни, значения = activity_chart._daily_series(rows, days=3)

    assert дни[-1] == сегодня_utc
    assert значения[-1] == 42


def test_график_принимает_день_снаружи():
    """Чтобы вызывающий мог передать ровно тот день, по которому размечена
    его выборка, а не полагаться на часы машины."""
    день = date(2026, 7, 31)
    дни, _ = activity_chart._daily_series([], days=2, today=день)

    assert дни == [день - timedelta(days=1), день]


# ---------------------------------------------------------------------------
# Своя полночь
# ---------------------------------------------------------------------------
def test_ближайшая_местная_полночь_переводится_в_utc(пояс):
    """Таймер «до обновления» вычитается из utcnow(), значит и полночь должна
    быть выражена в UTC. Для МСК местная полночь — это 21:00 UTC."""
    пояс("Europe/Moscow")

    полночь = bot_module.next_local_midnight_utc()

    assert полночь.hour == 21
    assert полночь.tzinfo is None, "для вычитания из utcnow() нужно наивное UTC"
    assert timedelta(0) < полночь - datetime.utcnow() <= timedelta(days=1)


def test_в_utc_местная_полночь_остаётся_полуночью(пояс):
    пояс("UTC")

    полночь = bot_module.next_local_midnight_utc()

    assert (полночь.hour, полночь.minute) == (0, 0)
    assert полночь.date() == datetime.utcnow().date() + timedelta(days=1)


# ---------------------------------------------------------------------------
# Кто по каким суткам живёт
# ---------------------------------------------------------------------------
ПО_МЕСТНЫМ_СУТКАМ = [
    "_daily_bonus_execute",      # ежедневный бонус — своя колонка last_day
    "_side_job_left_today",      # лимит подработок за сутки
    "_get_or_make_order",        # заказ чата на день
    "_daily_pick",               # гороскоп и прочее «на сутки»
]

ПО_UTC_СУТКАМ = [
    "_render_chat_chart",        # выборка из message_daily
    "compute_streak",            # стрик считается по message_daily
]


@pytest.mark.parametrize("имя", ПО_МЕСТНЫМ_СУТКАМ)
def test_суточные_отметки_живут_по_местному_времени(имя):
    """У этих своя колонка-отметка и никакой чужой истории: человек ждёт
    обновления в свою полночь, а не в полночь по Гринвичу."""
    src = inspect.getsource(getattr(bot_module, имя))
    assert "local_today()" in src, f"{имя} считает сутки не по местному времени"
    assert "utc_today()" not in src


@pytest.mark.parametrize("имя", ПО_UTC_СУТКАМ)
def test_читатели_message_daily_остаются_на_utc(имя):
    """Обратная половина правила. Начни читать историю по местным суткам — и
    в одной таблице навсегда смешаются две разметки дня."""
    src = inspect.getsource(getattr(bot_module, имя))
    assert "utc_today()" in src, f"{имя} читает message_daily не по UTC"


def test_зона_ос_нигде_не_используется():
    """date.today() и datetime.now() берут зону ОПЕРАЦИОННОЙ СИСТЕМЫ — это ни
    UTC, ни настроенный пояс. На UTC-сервере такое совпадает случайно и молчит
    до первого переезда."""
    подозрительные = []
    # Разбором кода, а не поиском по тексту: и bot.py, и db.py рассказывают
    # про date.today() в комментариях — как раз чтобы это не вернулось.
    ЗАПРЕЩЕНО = {("date", "today"), ("datetime", "now")}
    for имя in ("bot.py", "db.py", "activity_chart.py", "seasons.py", "farming.py"):
        путь = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), имя)
        дерево = ast.parse(open(путь, encoding="utf-8").read())
        for узел in ast.walk(дерево):
            if not isinstance(узел, ast.Call) or not isinstance(узел.func, ast.Attribute):
                continue
            владелец = getattr(узел.func.value, "id", "")
            # datetime.now(зона) — законно (см. local_now); запрещено без зоны.
            if (владелец, узел.func.attr) in ЗАПРЕЩЕНО and not узел.args:
                подозрительные.append(f"{имя}:{узел.lineno}")
    assert not подозрительные, "зона ОС вместо UTC/настроенной:\n" + "\n".join(подозрительные)
