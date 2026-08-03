"""Списки и топы показывают только тех, кто сейчас в чате.

Жалоба, с которой всё началось: «во всех списках присутствуют ушедшие люди» —
«Участники сообщения», «вне нормы», топы. Причина: эти выборки читали таблицы
истории (known_users, message_stats, message_daily, кошельки, статистику игр),
а оттуда никто не удаляется никогда — и не должен, иначе вернувшийся терял бы
стаж и накопления. Состав чата живёт в отдельной таблице current_users, и
запросы её просто не спрашивали.

Тут две проверки разного рода:

1. Поведение — SQL из db.py исполняется на настоящем SQLite, где среди данных
   есть вышедший. Проверяется и то, что его нет в строках, и то, что его нет в
   СЧЁТЧИКЕ: отфильтровать только строки — значит получить неверное «— N
   участников» в заголовке и пустые страницы в конце листания.
2. Состав — фильтр есть у каждой выборки из списка. Это заслон на будущее:
   новый топ легко написать по старому образцу, и он снова начнёт показывать
   вышедших.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, datetime, timedelta

import pytest

import db as db_module

CHAT_ID = -1001234567890
ALIVE = 111       # в чате
GHOST = 222       # вышел: в истории есть, в current_users нет
WEEK_AGO = (date.today() - timedelta(days=7)).isoformat()
LONG_AGO_DAY = (date.today() - timedelta(days=60)).isoformat()
LONG_AGO = (datetime.utcnow() - timedelta(days=90)).isoformat(" ")


def _spy_on(monkeypatch) -> list[tuple[str, tuple]]:
    """Подменяет доступ к БД (как в test_black_market_db) и возвращает общий
    журнал запросов. Именно журнал, а не последний запрос: у топов их два —
    строки и счётчик, и вся суть в том, что фильтр нужен в обоих."""
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


# ---------------------------------------------------------------------------
# 1. Поведение на настоящем SQL
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE known_users (chat_id INT, user_id INT, full_name TEXT, username TEXT,
                          last_seen_at TEXT, first_seen_at TEXT, invited_by INT);
CREATE TABLE current_users (chat_id INT, user_id INT, full_name TEXT, username TEXT,
                            last_seen_at TEXT, joined_at TEXT);
CREATE TABLE message_stats (chat_id INT, user_id INT, message_count INT,
                            first_seen_at TEXT, last_message_at TEXT);
CREATE TABLE message_daily (chat_id INT, user_id INT, day TEXT, message_count INT);
CREATE TABLE rest_requests (chat_id INT, user_id INT, status TEXT, expires_at TEXT);
CREATE TABLE call_unregs (chat_id INT, user_id INT, message TEXT, created_at TEXT);
CREATE TABLE call_signs (chat_id INT, user_id INT, emoji TEXT);
CREATE TABLE subscriptions (chat_id INT, subscriber_id INT, target_id INT, created_at TEXT);
"""


@pytest.fixture
def sqlite_db():
    """Живой и вышедший — с одинаковой историей: сотня сообщений когда-то и
    ноль за последнюю неделю. Различие ровно одно — строка в current_users.
    Значит, всё, что поймает тест, и есть работа фильтра."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Функции MySQL, которых в SQLite нет, а в запросах они встречаются.
    conn.create_function("UTC_TIMESTAMP", 0, lambda: datetime.utcnow().isoformat(" "))
    conn.create_function("LEAST", 2, min)

    for user_id in (ALIVE, GHOST):
        conn.execute(
            "INSERT INTO known_users VALUES (?,?,?,NULL,?,?,NULL)",
            (CHAT_ID, user_id, f"Участник {user_id}", LONG_AGO, LONG_AGO),
        )
        conn.execute(
            "INSERT INTO message_stats VALUES (?,?,?,?,?)",
            (CHAT_ID, user_id, 100, LONG_AGO, LONG_AGO),
        )
        conn.execute(
            "INSERT INTO message_daily VALUES (?,?,?,?)",
            (CHAT_ID, user_id, LONG_AGO_DAY, 100),
        )
    conn.execute(
        "INSERT INTO current_users VALUES (?,?,?,NULL,?,?)",
        (CHAT_ID, ALIVE, f"Участник {ALIVE}", LONG_AGO, LONG_AGO),
    )
    conn.commit()
    return conn


def _run(conn, call):
    """Исполняет на SQLite запрос, собранный настоящей функцией db.py."""
    query, params = call
    return [dict(r) for r in conn.execute(query.replace("%s", "?"), params).fetchall()]


def test_топ_не_показывает_вышедшего(monkeypatch, sqlite_db):
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_top_messages(CHAT_ID, limit=10))

    count_sql, rows_sql = journal  # сперва счётчик, потом строки
    assert _run(sqlite_db, count_sql) == [{"total": 1}], "вышедший попал в счётчик топа"
    assert [r["user_id"] for r in _run(sqlite_db, rows_sql)] == [ALIVE]


def test_топ_за_период_не_показывает_вышедшего(monkeypatch, sqlite_db):
    journal = _spy_on(monkeypatch)
    since = (date.today() - timedelta(days=90)).isoformat()  # чтобы данные попали в период
    asyncio.run(db_module.list_top_messages_period(CHAT_ID, since, limit=10))

    count_sql, rows_sql = journal
    assert _run(sqlite_db, count_sql) == [{"total": 1}], "вышедший попал в счётчик топа"
    assert [r["user_id"] for r in _run(sqlite_db, rows_sql)] == [ALIVE]


def test_вне_нормы_не_показывает_вышедшего(monkeypatch, sqlite_db):
    """Он и раньше шёл первым: сообщений за неделю ноль — дальше всех от нормы."""
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_below_norm(CHAT_ID, WEEK_AGO, norm=50))

    assert [r["user_id"] for r in _run(sqlite_db, journal[0])] == [ALIVE]


def test_участники_сообщения_не_показывают_вышедшего(monkeypatch, sqlite_db):
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_by_message_count(CHAT_ID, WEEK_AGO, "<", 10))

    assert [r["user_id"] for r in _run(sqlite_db, journal[0])] == [ALIVE]


def test_чистка_clearusers_не_берёт_вышедших(monkeypatch, sqlite_db):
    """Выборка под /clearUsers — это массовый бан. Того, кто ушёл сам, банить
    незачем, а в списке он стоял первым."""
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_below_norm_joined_before(CHAT_ID, WEEK_AGO, norm=50))

    assert [r["user_id"] for r in _run(sqlite_db, journal[0])] == [ALIVE]


def test_место_в_топе_считается_без_вышедших(monkeypatch, sqlite_db):
    """Иначе профиль говорит «вы третий», а в самом топе человек второй."""
    sqlite_db.execute("UPDATE message_stats SET message_count = 500 WHERE user_id = ?", (GHOST,))
    sqlite_db.execute("INSERT INTO message_stats VALUES (?,?,?,NULL,NULL)", (CHAT_ID, 333, 300))
    sqlite_db.execute("INSERT INTO current_users VALUES (?,?,?,NULL,NULL,NULL)",
                      (CHAT_ID, 333, "Третий"))
    sqlite_db.commit()

    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.get_message_rank(CHAT_ID, ALIVE))

    # Впереди только живой с 300 сообщениями; вышедший с 500 не считается.
    assert _run(sqlite_db, journal[0]) == [{"user_rank": 2}]


# ---------------------------------------------------------------------------
# 2. Состав: фильтр есть у всех выборок, а не только у названных выше
# ---------------------------------------------------------------------------
def _call(name, *args):
    return lambda: getattr(db_module, name)(*args)


FILTERED = [
    ("list_top_messages", _call("list_top_messages", CHAT_ID)),
    ("list_top_messages_period", _call("list_top_messages_period", CHAT_ID, WEEK_AGO)),
    ("get_message_rank", _call("get_message_rank", CHAT_ID, ALIVE)),
    ("list_below_norm", _call("list_below_norm", CHAT_ID, WEEK_AGO, 10)),
    ("list_below_norm_joined_before",
     _call("list_below_norm_joined_before", CHAT_ID, WEEK_AGO, 10)),
    ("list_by_message_count", _call("list_by_message_count", CHAT_ID, WEEK_AGO, "<", 10)),
    ("list_oldtimers", _call("list_oldtimers", CHAT_ID)),
    ("list_newcomers", _call("list_newcomers", CHAT_ID)),
    ("list_new_members_since", _call("list_new_members_since", CHAT_ID, datetime.utcnow())),
    ("list_recent_active_users", _call("list_recent_active_users", CHAT_ID)),
    ("get_top_active_since", _call("get_top_active_since", CHAT_ID, 7)),
    ("list_coins_top", _call("list_coins_top", CHAT_ID)),
    ("list_reward_top", _call("list_reward_top", CHAT_ID)),
    ("get_reputation_top", _call("get_reputation_top", CHAT_ID)),
    ("get_achievements_top", _call("get_achievements_top", CHAT_ID)),
    ("get_top_subscribed", _call("get_top_subscribed", CHAT_ID)),
    ("list_lootbox_top", _call("list_lootbox_top", CHAT_ID)),
    ("list_robbery_top", _call("list_robbery_top", CHAT_ID)),
    ("list_profession_top", _call("list_profession_top", CHAT_ID)),
    ("list_fishing_top", _call("list_fishing_top", CHAT_ID)),
    ("list_fishing_weight_top", _call("list_fishing_weight_top", CHAT_ID)),
    ("list_chat_investment_top", _call("list_chat_investment_top", CHAT_ID)),
    # Созыв и подписки — не «списки» на вид, но источник тот же: known_users.
    ("list_callable_users", _call("list_callable_users", CHAT_ID)),
    ("get_subscribers", _call("get_subscribers", CHAT_ID, ALIVE)),
    ("count_subscribers", _call("count_subscribers", CHAT_ID, ALIVE)),
]


@pytest.mark.parametrize("name,call", FILTERED, ids=[n for n, _ in FILTERED])
def test_у_выборки_есть_фильтр_состава(monkeypatch, name, call):
    journal = _spy_on(monkeypatch)
    asyncio.run(call())

    assert journal, f"{name} не сделала ни одного запроса"
    for query, _params in journal:
        assert "current_users cu_f" in query, (
            f"{name}: запрос без фильтра «сейчас в чате» — вышедшие снова в списке\n{query}"
        )


def test_неактив_и_молчуны_фильтруются_через_join(monkeypatch):
    """Эти две сделаны раньше и иначе — через JOIN current_users. Проверяем,
    что фильтр в них никуда не делся: под общий признак cu_f они не подходят."""
    for name in ("list_inactive", "list_silent"):
        journal = _spy_on(monkeypatch)
        asyncio.run(getattr(db_module, name)(CHAT_ID, datetime.utcnow()))
        assert "JOIN current_users cu" in journal[0][0], name


def test_антирейдовый_список_новичков_вышедших_не_прячет(monkeypatch):
    """Единственное осознанное исключение: рейдера, успевшего выйти самому,
    админ всё равно должен видеть — бан работает и по отсутствующему."""
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_new_members_without_role_since(CHAT_ID, datetime.utcnow()))

    assert "current_users" not in journal[0][0]


def test_созыв_не_зовёт_вышедших(monkeypatch, sqlite_db):
    """«Созывается слишком много людей»: созыв тегал всех, кого бот когда-либо
    видел в чате, — включая давно ушедших."""
    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.list_callable_users(CHAT_ID))

    assert [r["user_id"] for r in _run(sqlite_db, journal[0])] == [ALIVE]


def test_созвать_своих_зовёт_только_оставшихся(monkeypatch, sqlite_db):
    """И профиль показывает то же число, что позовёт созыв."""
    for user_id in (ALIVE, GHOST):
        sqlite_db.execute("INSERT INTO subscriptions VALUES (?,?,?,?)",
                          (CHAT_ID, user_id, 999, LONG_AGO))
    sqlite_db.commit()

    journal = _spy_on(monkeypatch)
    asyncio.run(db_module.get_subscribers(CHAT_ID, 999))
    assert [r["user_id"] for r in _run(sqlite_db, journal[0])] == [ALIVE]

    journal.clear()
    asyncio.run(db_module.count_subscribers(CHAT_ID, 999))
    assert _run(sqlite_db, journal[0]) == [{"total": 1}]
