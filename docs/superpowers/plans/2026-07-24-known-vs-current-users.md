# «Нью» — known_users/current_users Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** исправить баг «бот считает вернувшегося участника новым» — разделить «историю/стаж» (`known_users`, никогда не чистится) и «кто сейчас в чате» (новая `current_users`, чистится при выходе).

**Architecture:** новая таблица `current_users` (копия структуры `known_users` без исторических полей) заполняется везде, где сейчас пишется `known_users` при активности человека (сообщение, вход, синхронизация админов), и чистится при выходе ВМЕСТО `known_users`. `known_users` перестаёт удаляться при выходе — только это и чинит баг. Три места, где бизнес-смысл именно «кто сейчас в чате» (не история), переключаются читать `current_users`: «участники без ролей», панельный `/api/members`. Выбор цели жалобы (авто-список и ручной ростер) сознательно остаётся на `known_users` — там разрешено вручную регистрировать не-участников чата.

**Tech Stack:** Python 3.13, aiogram (бот), FastAPI + aiomysql (панель), pytest (`tests/conftest.py` подменяет aiogram/aiomysql заглушками там, где настоящих пакетов нет).

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-24-known-vs-current-users-design.md` — при расхождении плана со спекой источник истины спека.
- `known_users` больше НИКОГДА не удаляется построчно при выходе участника из чата. Единственное оставшееся построчное удаление из `known_users` — ручное действие админа в ростере жалоб (`complaint_roster_delete_confirm`), не трогаем.
- Новая таблица `current_users` не хранит `first_seen_at`/`invited_by` — это исторические поля, ей не нужны.
- `current_users.last_seen_at` пишется через `UTC_TIMESTAMP()` в самом запросе (не полагаемся на `ON UPDATE CURRENT_TIMESTAMP` колонки — она в часовом поясе сессии MySQL) — тот же приём, что уже применяется в `upsert_known_user` (`db.py:1435-1452`, с объясняющим комментарием на месте).
- Выбор цели жалобы (`complaint_picker_page`, `complaint_roster_add_id/name`, `complaint_roster_delete_confirm`) НЕ трогаем — сознательно остаётся на `known_users` целиком.
- `db.py`-функции в проекте не тестируются напрямую (нет прецедента в `tests/`) — поведение проверяется через монкейпатч в тестах `bot.py`-хендлеров и `webpanel/app.py`-эндпоинтов.
- `tests/test_migrations_wired.py::test_каждая_миграция_вызывается` автоматически проверяет, что новая `ensure_current_users_table` где-то вызывается.
- Тесты запускаются из `tg-bot/`: `pytest tests/<file>.py -v`. Тесты, вызывающие `bot.py`-хендлеры напрямую, требуют настоящего `aiogram` (иначе `SKIPPED`, не `FAILED`).
- Коммит — как и в предыдущих двух подпроектах: каждая задача заканчивается локальным `git commit` в репозитории `tg-bot/` (локальный, никогда не пушится). Дизайн-спека и сам план коммитятся отдельно, только по прямому запросу пользователя в моменте.

---

### Task 1: БД — таблица `current_users`, CRUD, бэкафилл

**Files:**
- Modify: `db.py` (новые `ensure_current_users_table`/CRUD/`backfill_current_users_from_known_users`, сразу после блока `known_users`-функций — после `search_known_users`, `db.py:1489-1503`, перед `get_known_user_by_username_in_chat`, `db.py:1550`)
- Modify: `bot.py` (вызовы в `main()`)

**Interfaces:**
- Produces (используется Task 2/3):
  - `db.upsert_current_user(chat_id: int, user_id: int, full_name: str, username: Optional[str]) -> None`.
  - `db.delete_current_user(chat_id: int, user_id: int) -> None`.
  - `db.list_current_users_without_role(chat_id: int, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]` — те же поля/сортировка, что и `list_known_users_without_role`, но `FROM current_users`.
  - `db.list_current_users_with_counts(chat_id: int, limit: int = 500) -> list[dict]` — тот же JOIN с `message_stats`, что и `list_known_users_with_counts`, но `FROM current_users`.
  - `db.backfill_current_users_from_known_users() -> int` (число скопированных строк; вызывается один раз в `main()`).

- [ ] **Step 1: Добавить таблицу**

Сразу после `search_known_users` (`db.py:1489-1503`), перед `get_known_user_by_username_in_chat` (`db.py:1550`), вставить:

```python
# ----------------------------------------------------------------------------
# current_users — «кто прямо сейчас состоит в чате», в отличие от known_users
# («кого бот когда-либо видел» — там же first_seen_at для «Олды»/«Новички»/
# «нью»/стажа для реста). Раньше эти два смысла жили в одной таблице
# known_users, и её же чистили при выходе участника — из-за чего first_seen_at
# терялся при обычном выходе-входе, и бот считал вернувшегося новичком.
# Разделение: known_users теперь не чистится НИКОГДА при выходе (только
# вручную, из ростера жалоб — не связано с этим), а current_users чистится
# при выходе и не хранит историю (нет first_seen_at/invited_by).
# ----------------------------------------------------------------------------
async def ensure_current_users_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS current_users ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "full_name VARCHAR(255) NOT NULL, "
        "username VARCHAR(64) NULL, "
        "last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id), "
        "INDEX idx_current_users_seen (chat_id, last_seen_at DESC)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
```

- [ ] **Step 2: Добавить CRUD**

Сразу после Step 1:

```python
async def upsert_current_user(chat_id: int, user_id: int, full_name: str, username: Optional[str]) -> None:
    # last_seen_at — явно UTC_TIMESTAMP() в самом запросе, не полагаемся на
    # ON UPDATE CURRENT_TIMESTAMP колонки (тот в часовом поясе сессии MySQL,
    # а весь остальной код сравнивает время в UTC) — тот же приём, что и в
    # upsert_known_user (db.py:1435-1452).
    await _execute(
        "INSERT INTO current_users (chat_id, user_id, full_name, username) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE full_name = VALUES(full_name), username = VALUES(username), "
        "last_seen_at = UTC_TIMESTAMP()",
        (chat_id, user_id, full_name[:255], username),
    )


async def delete_current_user(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM current_users WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def list_current_users_without_role(chat_id: int, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """Как list_known_users_without_role (db.py:1522-1547), но по current_users —
    не имеет смысла предлагать назначить роль тому, кто уже вышел из чата."""
    holders_subquery = (
        "SELECT holder_user_id AS user_id FROM chat_roles "
        "WHERE chat_id = %s AND status = 'taken' AND holder_user_id IS NOT NULL "
        "UNION "
        "SELECT reserved_user_id AS user_id FROM chat_roles "
        "WHERE chat_id = %s AND status = 'reserved' AND reserved_user_id IS NOT NULL"
    )
    count_row = await _fetchone(
        f"SELECT COUNT(*) AS total FROM current_users cu "
        f"WHERE cu.chat_id = %s AND cu.user_id NOT IN ({holders_subquery})",
        (chat_id, chat_id, chat_id),
    )
    rows = await _fetchall(
        f"SELECT cu.user_id, cu.full_name, cu.username FROM current_users cu "
        f"WHERE cu.chat_id = %s AND cu.user_id NOT IN ({holders_subquery}) "
        f"ORDER BY cu.last_seen_at DESC LIMIT %s OFFSET %s",
        (chat_id, chat_id, chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def list_current_users_with_counts(chat_id: int, limit: int = 500) -> list[dict]:
    """Как list_known_users_with_counts (db.py:1474-1486), но по current_users —
    для панели («Чаты и люди»): не нужно захламлять список ушедшими."""
    return await _fetchall(
        "SELECT cu.user_id, cu.full_name, cu.username, "
        "COALESCE(ms.message_count, 0) AS message_count, "
        "ms.first_seen_at, ms.last_message_at, cu.last_seen_at "
        "FROM current_users cu "
        "LEFT JOIN message_stats ms ON ms.chat_id = cu.chat_id AND ms.user_id = cu.user_id "
        "WHERE cu.chat_id = %s ORDER BY cu.last_seen_at DESC LIMIT %s",
        (chat_id, limit),
    )


async def backfill_current_users_from_known_users() -> int:
    """Одноразовая миграция при деплое: бот не может запросить у Telegram
    полный список участников обычной группы, поэтому единственный доступный
    сигнал «кто сейчас в чате» на момент включения этой фичи — «все, кого
    known_users считает известными прямо сейчас, предположительно ещё в
    чате». Неточность (кто-то мог выйти до деплоя) со временем самоисправится
    через реальные события выхода. Выполняется только если current_users
    пуста (тот же идиом, что и seed_*_if_empty в этом файле)."""
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM current_users")
    if row and row["cnt"]:
        return 0
    await _execute(
        "INSERT IGNORE INTO current_users (chat_id, user_id, full_name, username, last_seen_at) "
        "SELECT chat_id, user_id, full_name, username, last_seen_at FROM known_users"
    )
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM current_users")
    return int(row["cnt"] if row else 0)
```

- [ ] **Step 3: Вызвать в `main()`**

В `bot.py` `main()`, рядом с остальными `ensure_*`-вызовами (например, после блока, добавленного для `propose_actions` в предыдущем подпроекте — найти любой соседний `await db.ensure_*_table()` и вставить после него):

```python
    await db.ensure_current_users_table()
```

Сразу после (после всех остальных `ensure_*`/`seed_*`-вызовов, перед строками `asyncio.create_task(...)`, например перед `asyncio.create_task(panel_action_reload_loop())`):

```python
    await db.backfill_current_users_from_known_users()
```

- [ ] **Step 4: Проверить, что бот импортируется и миграция «привязана»**

Run: `python -c "import os; os.environ.setdefault('BOT_TOKEN','123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN'); os.environ.setdefault('OWNER_IDS','1'); import bot"`
Expected: без исключений.

Run: `pytest tests/test_migrations_wired.py -v`
Expected: PASS — `ensure_current_users_table` найдена и вызывается.

- [ ] **Step 5: Commit**

```bash
git add db.py bot.py
git commit -m "feat(current-users): БД-слой — таблица current_users, CRUD, бэкафилл из known_users"
```

---

### Task 2: Бот — заполнение/чистка current_users, переключение потребителей

**Files:**
- Modify: `bot.py` (`MessageCounterMiddleware`, `handle_member_joined`, `handle_member_left`, `sync_known_admins`, `cmd_members_without_role`)
- Create: `tests/test_current_users.py`

**Interfaces:**
- Consumes: `db.upsert_current_user`, `db.delete_current_user`, `db.list_current_users_without_role` (Task 1).
- Produces: ничего нового для других задач — лист-узел на бот-стороне.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_current_users.py`:

```python
"""known_users/current_users — «нью» больше не путает вернувшегося участника
с новым.

known_users никогда не чистится при выходе (стаж/новизна). current_users —
новая таблица «кто сейчас в чате»: заполняется при активности, чистится при
выходе. Тесты проверяют именно места стыковки — что нужные функции
вызываются с нужными аргументами, а НЕ полное поведение хендлеров (оно уже
покрыто существовавшим до этой фичи кодом и не меняется).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


async def _async_noop(*args, **kwargs):
    return None


def _async_returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _make(text, chat_type="supergroup"):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=CHAT_ID, type=chat_type),
        from_user=User(id=555, is_bot=False, first_name="Тестер"), text=text,
    )
    sent = []

    async def fake_reply(t, **kwargs):
        sent.append(t)

    object.__setattr__(m, "reply", fake_reply)
    return m, sent


def test_вступление_заносит_в_current_users(monkeypatch):
    monkeypatch.setattr(bot_module, "_member_events_seen", {})
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "resolve_reservations_on_join", _async_returns([]))
    monkeypatch.setattr(bot_module, "group_join_text", lambda: None)
    monkeypatch.setattr(bot_module, "is_join_notify_enabled", _async_returns(False))
    monkeypatch.setattr(bot_module, "prompt_role_pick_after_join", _async_noop)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    user = User(id=555, is_bot=False, first_name="Тестер")
    asyncio.run(bot_module.handle_member_joined(CHAT_ID, user, inviter_id=None))

    assert calls == [(CHAT_ID, 555, "Тестер", None)]


def test_выход_чистит_current_users_а_не_known_users(monkeypatch):
    """Регрессионный тест на сам баг: known_users больше не должна трогаться
    при выходе — иначе first_seen_at снова будет теряться при возврате."""
    monkeypatch.setattr(bot_module, "_member_events_seen", {})
    monkeypatch.setattr(bot_module, "is_leave_notify_enabled", _async_returns(False))
    monkeypatch.setattr(bot_module.db, "delete_call_data", _async_noop)
    monkeypatch.setattr(bot_module.db, "delete_subscriptions_of_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "delete_reputation_of_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "release_role_by_holder", _async_returns(None))

    known_user_calls = []

    async def delete_known_user(chat_id, user_id):
        known_user_calls.append((chat_id, user_id))

    current_user_calls = []

    async def delete_current_user(chat_id, user_id):
        current_user_calls.append((chat_id, user_id))

    monkeypatch.setattr(bot_module.db, "delete_known_user", delete_known_user)
    monkeypatch.setattr(bot_module.db, "delete_current_user", delete_current_user)

    user = User(id=555, is_bot=False, first_name="Тестер")
    asyncio.run(bot_module.handle_member_left(CHAT_ID, user))

    assert current_user_calls == [(CHAT_ID, 555)]
    assert known_user_calls == []


def test_сообщение_заносит_в_current_users(monkeypatch):
    monkeypatch.setattr(bot_module.db, "increment_message_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "increment_daily_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "increment_hourly_count", _async_noop)
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)
    monkeypatch.setattr(bot_module.db, "clear_unreg", _async_noop)
    monkeypatch.setattr(bot_module, "check_message_achievements", _async_noop)
    monkeypatch.setattr(bot_module, "_remember_recent_message", _async_noop)
    monkeypatch.setattr(bot_module, "RSTICK_CHANCE", 0.0)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    message, _ = _make("привет")

    async def next_handler(event, data):
        return "ok"

    mw = bot_module.MessageCounterMiddleware()
    result = asyncio.run(mw(next_handler, message, {}))

    assert result == "ok"
    assert calls == [(CHAT_ID, 555, "Тестер", None)]


def test_синхронизация_админов_заносит_в_current_users(monkeypatch):
    admin_user = User(id=777, is_bot=False, first_name="Админ")

    class FakeMember:
        def __init__(self, user):
            self.user = user

    class FakeBot:
        async def get_chat_administrators(self, chat_id):
            return [FakeMember(admin_user)]

    monkeypatch.setattr(bot_module, "bot", FakeBot())
    monkeypatch.setattr(bot_module.db, "upsert_known_user", _async_noop)

    calls = []

    async def upsert_current_user(chat_id, user_id, full_name, username):
        calls.append((chat_id, user_id, full_name, username))

    monkeypatch.setattr(bot_module.db, "upsert_current_user", upsert_current_user)

    asyncio.run(bot_module.sync_known_admins(CHAT_ID))

    assert calls == [(CHAT_ID, 777, "Админ", None)]


def test_участники_без_ролей_читает_current_users(monkeypatch):
    monkeypatch.setattr(bot_module, "roles_context_chat_id", _async_returns(CHAT_ID))

    calls = []

    async def list_current_users_without_role(chat_id, limit=50, offset=0):
        calls.append((chat_id, limit))
        return [{"user_id": 42, "full_name": "Тест", "username": None}], 1

    monkeypatch.setattr(bot_module.db, "list_current_users_without_role", list_current_users_without_role)

    message, sent = _make("участники без ролей")
    asyncio.run(bot_module.cmd_members_without_role(message))

    assert calls == [(CHAT_ID, bot_module.ROSTER_LIST_LIMIT)]
    assert sent and "Тест" in sent[0]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_current_users.py -v`
Expected: FAIL/ERROR — `db.upsert_current_user`/`db.delete_current_user`/`db.list_current_users_without_role` не существуют (Task 1 уже сделан, так что они есть в `db.py`, но `bot.py` их ещё не вызывает — тесты упадут на `assert calls == [...]`, где `calls` пуст, либо на `AttributeError`, если тест ссылается на ещё не добавленный `bot_module.RSTICK_CHANCE`/т.п., — в норме именно на пустых/неверных `calls`).

- [ ] **Step 3: Добавить вызов в `handle_member_joined`**

В `bot.py`, внутри `handle_member_joined` (`bot.py:290-356`), сразу после существующего вызова `await db.upsert_known_user(...)` (строки 297-303), добавить:

```python
        await db.upsert_current_user(
            chat_id, user.id, user.full_name or str(user.id), user.username,
        )
```

- [ ] **Step 4: Заменить удаление в `handle_member_left`**

В `bot.py`, внутри `handle_member_left` (`bot.py:359-397`), заменить строку 382:

```python
        await db.delete_known_user(chat_id, user.id)
```

на:

```python
        await db.delete_current_user(chat_id, user.id)
```

- [ ] **Step 5: Добавить вызов в `MessageCounterMiddleware`**

В `bot.py`, внутри `MessageCounterMiddleware.__call__` (`bot.py:201-247`), сразу после существующего вызова `await db.upsert_known_user(...)` (строки 223-228), добавить:

```python
                    await db.upsert_current_user(
                        event.chat.id, event.from_user.id,
                        event.from_user.full_name or str(event.from_user.id), event.from_user.username,
                    )
```

- [ ] **Step 6: Добавить вызов в `sync_known_admins`**

В `bot.py`, внутри `sync_known_admins` (`bot.py:3826-3845`), сразу после существующего вызова `await db.upsert_known_user(...)` (строка 3839), добавить:

```python
            await db.upsert_current_user(chat_id, user.id, user.full_name or str(user.id), user.username)
```

- [ ] **Step 7: Переключить «участники без ролей»**

В `bot.py`, в `cmd_members_without_role` (`bot.py:5329-5346`), заменить строку 5335:

```python
    rows, total = await db.list_known_users_without_role(chat_id, limit=ROSTER_LIST_LIMIT)
```

на:

```python
    rows, total = await db.list_current_users_without_role(chat_id, limit=ROSTER_LIST_LIMIT)
```

- [ ] **Step 8: Прогнать тесты — должны пройти**

Run: `pytest tests/test_current_users.py -v`
Expected: PASS (5 тестов), либо `SKIPPED` целиком без настоящего aiogram.

- [ ] **Step 9: Прогнать весь набор, чтобы убедиться, что ничего не сломано**

Run: `pytest tests/ -q`
Expected: PASS, за вычетом уже известного предсуществующего несвязанного флейки-теста в `tests/test_panel_member.py` (time-dependent кулдаун, не связан с этой фичей — подтверждён pre-existing в двух предыдущих подпроектах).

- [ ] **Step 10: Commit**

```bash
git add bot.py tests/test_current_users.py
git commit -m "fix(current-users): known_users больше не чистится при выходе; current_users для «кто сейчас в чате»"
```

---

### Task 3: Панель — «Чаты и люди» смотрит в current_users

**Files:**
- Modify: `webpanel/app.py` (`api_members`, `webpanel/app.py:658-697`)
- Modify: `tests/test_panel_roles.py` (существующий фикстур `panel_client`)

**Interfaces:**
- Consumes: `db.list_current_users_with_counts` (Task 1).
- Produces: ничего для других задач — лист-узел.

- [ ] **Step 1: Обновить существующую фикстуру теста**

В `tests/test_panel_roles.py`, в фикстуре `panel_client` (`tests/test_panel_roles.py:39-72`), заменить:

```python
    async def list_known_users_with_counts(chat_id, limit=500):
        # /api/members теперь берёт участников со счётчиком сообщений (список, не кортеж)
        return [dict(m) for m in MEMBERS]
```

на:

```python
    async def list_current_users_with_counts(chat_id, limit=500):
        # /api/members смотрит в current_users (не known_users) — не должен
        # захламляться участниками, которые уже вышли из чата.
        return [dict(m) for m in MEMBERS]
```

и заменить строку монкейпатча:

```python
    monkeypatch.setattr(db, "list_known_users_with_counts", list_known_users_with_counts)
```

на:

```python
    monkeypatch.setattr(db, "list_current_users_with_counts", list_current_users_with_counts)
```

(строка `monkeypatch.setattr(db, "list_known_users", list_known_users)` и сама функция `list_known_users` — не трогать, используются другим, не связанным с этой задачей эндпоинтом).

- [ ] **Step 2: Убедиться, что существующие тесты падают**

Run: `pytest tests/test_panel_roles.py -v`
Expected: FAIL — `api_members` всё ещё вызывает `db.list_known_users_with_counts` (реальную, немокнутую функцию — упадёт на отсутствии живой БД/пустом результате), а не замоканную `list_current_users_with_counts`.

- [ ] **Step 3: Переключить `api_members`**

В `webpanel/app.py`, в `api_members` (`webpanel/app.py:658-697`), заменить строку 664:

```python
    rows = await db.list_known_users_with_counts(chat_id, limit=500)
```

на:

```python
    rows = await db.list_current_users_with_counts(chat_id, limit=500)
```

- [ ] **Step 4: Прогнать тесты — должны пройти**

Run: `pytest tests/test_panel_roles.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Прогнать весь набор тестов панели**

Run: `pytest tests/ -k panel -v`
Expected: PASS (ничего не сломано).

- [ ] **Step 6: Commit**

```bash
git add webpanel/app.py tests/test_panel_roles.py
git commit -m "fix(panel): /api/members смотрит в current_users вместо known_users"
```

---

## Порядок выполнения

Task 1 → Task 2 → Task 3. Task 2 и Task 3 оба зависят только от Task 1 (CRUD) — код не пересекается, можно поменять местами при необходимости, но проще по порядку.
