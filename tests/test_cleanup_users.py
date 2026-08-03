"""Чистка «/clearUsers»: защита новичков и её настройка в панели.

Просьба: «если человек зашёл на этой неделе, он защищён от нормы». Половина
этого была и раньше — выборка брала только вступивших до начала недели, — но
опиралась на known_users.first_seen_at, а он помнит САМОЕ ПЕРВОЕ появление и
при возвращении не обновляется (это память о стаже, так и задумано). Значит,
ушедший год назад и вернувшийся вчера считался старожилом, не набравшим норму,
и попадал под перманентный бан.

Теперь момент входа берётся из current_users.joined_at — «когда вошёл в этот
раз», — и защит стало две: вступил до начала недели И пробыл в чате дольше
настраиваемого срока.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import date, datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402

ЧАТ = -1003673552861
СТАРОЖИЛ = 111        # в чате давно, норму не набрал → под чистку
ВЕРНУВШИЙСЯ = 222     # известен боту год, но вошёл заново вчера → защищён
НОВИЧОК = 333         # вступил сегодня → защищён
ДАВНО = (datetime.utcnow() - timedelta(days=365)).isoformat(" ")
ВЧЕРА = (datetime.utcnow() - timedelta(days=1)).isoformat(" ")
СЕГОДНЯ = datetime.utcnow().isoformat(" ")

SCHEMA = """
CREATE TABLE known_users (chat_id INT, user_id INT, full_name TEXT, username TEXT,
                          last_seen_at TEXT, first_seen_at TEXT, invited_by INT);
CREATE TABLE current_users (chat_id INT, user_id INT, full_name TEXT, username TEXT,
                            last_seen_at TEXT, joined_at TEXT);
CREATE TABLE message_stats (chat_id INT, user_id INT, message_count INT,
                            first_seen_at TEXT, last_message_at TEXT);
CREATE TABLE message_daily (chat_id INT, user_id INT, day TEXT, message_count INT);
CREATE TABLE rest_requests (chat_id INT, user_id INT, status TEXT, expires_at TEXT);
"""


@pytest.fixture
def база():
    """Трое ниже нормы, различаются только моментом входа в чат."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.create_function("UTC_TIMESTAMP", 0, lambda: datetime.utcnow().isoformat(" "))
    conn.create_function("LEAST", 2, lambda a, b: min(x for x in (a, b) if x is not None))

    for user_id, вошёл in ((СТАРОЖИЛ, ДАВНО), (ВЕРНУВШИЙСЯ, ВЧЕРА), (НОВИЧОК, СЕГОДНЯ)):
        # known_users у всех троих старая — именно на неё и полагались раньше.
        conn.execute("INSERT INTO known_users VALUES (?,?,?,NULL,?,?,NULL)",
                     (ЧАТ, user_id, f"Участник {user_id}", ДАВНО, ДАВНО))
        conn.execute("INSERT INTO current_users VALUES (?,?,?,NULL,?,?)",
                     (ЧАТ, user_id, f"Участник {user_id}", ДАВНО, вошёл))
        conn.execute("INSERT INTO message_stats VALUES (?,?,?,?,?)",
                     (ЧАТ, user_id, 5, ДАВНО, ДАВНО))
    conn.commit()
    return conn


def _spy(monkeypatch) -> list[tuple[str, tuple]]:
    journal: list[tuple[str, tuple]] = []

    class _Spy:
        def __init__(self, result):
            self.result = result

        async def __call__(self, query, params=()):
            journal.append((" ".join(query.split()), params))
            return self.result

    monkeypatch.setattr(db_module, "_fetchall", _Spy([]))
    monkeypatch.setattr(db_module, "_fetchone", _Spy(None))
    return journal


def _run(conn, call):
    query, params = call
    return [dict(r) for r in conn.execute(query.replace("%s", "?"), params).fetchall()]


@pytest.fixture
def настройки(monkeypatch):
    """settings — глобальный dict модуля; оставленное значение поехало бы
    в соседние тесты."""
    было = dict(bot_module.settings)
    yield bot_module.settings
    bot_module.settings.clear()
    bot_module.settings.update(было)


# ---------------------------------------------------------------------------
# Защита
# ---------------------------------------------------------------------------
def test_вернувшийся_и_новичок_под_чистку_не_идут(monkeypatch, база, настройки):
    настройки["cleanup_newcomer_days"] = 7
    journal = _spy(monkeypatch)
    asyncio.run(db_module.list_below_norm_joined_before(
        ЧАТ, db_module.week_start_day(), norm=50,
        joined_before=bot_module._cleanup_join_cutoff(),
    ))

    попали = [r["user_id"] for r in _run(база, journal[0])]
    assert попали == [СТАРОЖИЛ], "защита новичков не сработала"


def test_без_joined_at_решает_старая_логика(monkeypatch, база, настройки):
    """Строки, созданные до появления колонки: когда человек вошёл — уже не
    узнать, и он считается старожилом. Иначе после обновления бота чистка
    разом «простила» бы весь чат."""
    настройки["cleanup_newcomer_days"] = 7
    база.execute("UPDATE current_users SET joined_at = NULL")
    база.commit()

    journal = _spy(monkeypatch)
    asyncio.run(db_module.list_below_norm_joined_before(
        ЧАТ, db_module.week_start_day(), norm=50,
        joined_before=bot_module._cleanup_join_cutoff(),
    ))

    assert len(_run(база, journal[0])) == 3


def test_защита_действует_даже_при_нуле_дней(настройки):
    """0 — это «отсчёта в днях нет», но вступившие на текущей неделе под
    чистку не идут в любом случае: неделю, начавшуюся для них в среду,
    набрать нельзя."""
    настройки["cleanup_newcomer_days"] = 0
    граница = bot_module._cleanup_join_cutoff()

    assert граница.date() == db_module.week_start_day()


def test_граница_берёт_более_раннюю_из_двух(настройки):
    """Под чистку идёт тот, кто вошёл раньше ОБЕИХ защит, — значит граница
    это более ранняя дата, а не более поздняя."""
    настройки["cleanup_newcomer_days"] = 30
    граница = bot_module._cleanup_join_cutoff()

    assert граница <= datetime.utcnow() - timedelta(days=29)
    assert граница.date() <= db_module.week_start_day()


def test_настройка_читается_и_подрезается(настройки):
    настройки.pop("cleanup_newcomer_days", None)
    assert bot_module.cleanup_newcomer_days() == bot_module.CLEANUP_NEWCOMER_DAYS_DEFAULT

    настройки["cleanup_newcomer_days"] = 3
    assert bot_module.cleanup_newcomer_days() == 3

    настройки["cleanup_newcomer_days"] = 100000
    assert bot_module.cleanup_newcomer_days() == bot_module.CLEANUP_NEWCOMER_DAYS_MAX

    настройки["cleanup_newcomer_days"] = "мусор"
    assert bot_module.cleanup_newcomer_days() == bot_module.CLEANUP_NEWCOMER_DAYS_DEFAULT


def test_считаем_сколько_новичков_спасли(monkeypatch, настройки):
    """Число идёт в подтверждение перед необратимым баном: «новички не в
    счёт» — обещание, и админ должен видеть, что оно сработало."""
    async def list_below_norm(chat_id, since_day, norm, limit=200):
        return [{"user_id": СТАРОЖИЛ}, {"user_id": ВЕРНУВШИЙСЯ}, {"user_id": НОВИЧОК}]

    monkeypatch.setattr(bot_module.db, "list_below_norm", list_below_norm, raising=False)
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)

    spared = asyncio.run(bot_module._cleanup_protected_newcomers(
        ЧАТ, 50, [{"user_id": СТАРОЖИЛ}]))

    assert spared == 2


def test_админы_не_считаются_спасёнными_новичками(monkeypatch, настройки):
    """Их и так не банят — приписывать их защите новичков значит врать
    в цифре, на которую админ смотрит перед баном."""
    async def list_below_norm(chat_id, since_day, norm, limit=200):
        return [{"user_id": СТАРОЖИЛ}, {"user_id": ВЕРНУВШИЙСЯ}]

    monkeypatch.setattr(bot_module.db, "list_below_norm", list_below_norm, raising=False)
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: uid == ВЕРНУВШИЙСЯ)

    spared = asyncio.run(bot_module._cleanup_protected_newcomers(
        ЧАТ, 50, [{"user_id": СТАРОЖИЛ}]))

    assert spared == 0


# ---------------------------------------------------------------------------
# Раздел панели «Чистка /clearUsers»
# ---------------------------------------------------------------------------
class ФейкСостояние:
    def __init__(self):
        self._data: dict = {}
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, state):
        self.state = state


class ФейкСообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("Chat", (), {"id": 555, "type": "private"})()
        self.from_user = type("User", (), {"id": 555, "is_bot": False, "first_name": "Админ"})()
        self.ответы: list[str] = []

    async def answer(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def панель(monkeypatch, настройки):
    """Панель без базы: норма и настройки — словарями в памяти."""
    хранилище = {"norm": None, "saved": {}, "logs": []}
    настройки["complaint_chat_id"] = ЧАТ
    настройки["cleanup_newcomer_days"] = 7

    async def get_data(key):
        if key == f"norm:{ЧАТ}" and хранилище["norm"] is not None:
            return {"data_value": str(хранилище["norm"])}
        return None

    async def set_data(key, value, updated_by=None):
        if key == f"norm:{ЧАТ}":
            хранилище["norm"] = int(value)

    async def delete_data(key):
        хранилище["norm"] = None
        return 1

    async def save_setting(field, value):
        хранилище["saved"][field] = value

    async def add_log(event, **kwargs):
        хранилище["logs"].append(event)

    async def fetch_settings():
        db_module._remember_week_start(хранилище["saved"])
        return dict(хранилище["saved"])

    async def list_below_norm_joined_before(chat_id, since_day, norm, limit=1000, joined_before=None):
        хранилище["joined_before"] = joined_before
        return [{"user_id": СТАРОЖИЛ, "full_name": "Старожил", "username": None,
                 "message_count": 3}]

    async def list_below_norm(chat_id, since_day, norm, limit=200):
        return [{"user_id": СТАРОЖИЛ}, {"user_id": НОВИЧОК}]

    for имя, fn in [
        ("get_data", get_data), ("set_data", set_data), ("delete_data", delete_data),
        ("save_setting", save_setting), ("add_log", add_log),
        ("fetch_settings", fetch_settings),
        ("list_below_norm_joined_before", list_below_norm_joined_before),
        ("list_below_norm", list_below_norm),
    ]:
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: True)
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)
    return хранилище


def test_меню_чистки_показывает_все_три_настройки(панель):
    панель["norm"] = 100
    msg, st = ФейкСообщение(f"🧹 {bot_module.LBL_CLEANUP}"), ФейкСостояние()

    asyncio.run(bot_module.cfg_cleanup(msg, st))

    текст = msg.ответы[0]
    assert "100" in текст and "Защита новичков" in текст
    assert bot_module.weekday_name(db_module.week_start_weekday()) in текст
    assert st.state == bot_module.AdminStates.menu_cleanup


def test_меню_говорит_что_норма_не_задана(панель):
    msg, st = ФейкСообщение(f"🧹 {bot_module.LBL_CLEANUP}"), ФейкСостояние()

    asyncio.run(bot_module.cfg_cleanup(msg, st))

    assert "не задана" in msg.ответы[0]


def test_норма_задаётся_из_панели(панель):
    st = ФейкСостояние()
    asyncio.run(bot_module.process_cleanup_norm(ФейкСообщение("150"), st))

    assert панель["norm"] == 150
    assert st.state == bot_module.AdminStates.menu_cleanup


def test_норма_снимается_прочерком(панель):
    панель["norm"] = 100
    asyncio.run(bot_module.process_cleanup_norm(ФейкСообщение("-"), ФейкСостояние()))

    assert панель["norm"] is None


def test_норма_не_принимает_ерунду(панель):
    msg = ФейкСообщение("сто")
    asyncio.run(bot_module.process_cleanup_norm(msg, ФейкСостояние()))

    assert панель["norm"] is None
    assert "число" in msg.ответы[0]


def test_защита_новичков_задаётся_из_панели(панель, настройки):
    asyncio.run(bot_module.process_cleanup_newcomer(ФейкСообщение("14"), ФейкСостояние()))

    assert панель["saved"]["cleanup_newcomer_days"] == 14
    assert bot_module.cleanup_newcomer_days() == 14, "настройка должна работать сразу"


def test_защита_новичков_не_принимает_ерунду(панель, настройки):
    msg = ФейкСообщение("две недели")
    asyncio.run(bot_module.process_cleanup_newcomer(msg, ФейкСостояние()))

    assert "cleanup_newcomer_days" not in панель["saved"]
    assert "дней" in msg.ответы[0]


def test_начало_недели_задаётся_из_панели(панель, настройки):
    было = db_module.week_start_weekday()
    try:
        asyncio.run(bot_module.process_cleanup_week_start(
            ФейкСообщение("понедельник"), ФейкСостояние()))
        assert панель["saved"]["week_start_weekday"] == 0
        assert db_module.week_start_weekday() == 0
    finally:
        db_module._remember_week_start({"week_start_weekday": было})


def test_предпросмотр_показывает_кандидатов_и_спасённых(панель):
    панель["norm"] = 100
    msg = ФейкСообщение(bot_module.BTN_CLEANUP_PREVIEW)

    asyncio.run(bot_module.cfg_cleanup_preview(msg, ФейкСостояние()))

    текст = msg.ответы[0]
    assert "Старожил" in текст
    assert "Новичков защищено: 1" in текст
    assert "/clearUsers" in текст, "из панели не банят — надо сказать, где банить"


def test_предпросмотр_считает_от_настроенной_границы(панель):
    """Предпросмотр обязан спрашивать ровно то же, что спросит сам бан."""
    панель["norm"] = 100
    asyncio.run(bot_module.cfg_cleanup_preview(ФейкСообщение(""), ФейкСостояние()))

    # Секунды между двумя вызовами utcnow() — не расхождение логики.
    assert abs((панель["joined_before"] - bot_module._cleanup_join_cutoff())
               .total_seconds()) < 5


def test_без_нормы_предпросмотр_не_врёт(панель):
    msg = ФейкСообщение(bot_module.BTN_CLEANUP_PREVIEW)
    asyncio.run(bot_module.cfg_cleanup_preview(msg, ФейкСостояние()))

    assert "не задана" in msg.ответы[0]
