# Реальные аккаунты участников + привязка админов к тг Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** участник задаёт себе логин/пароль через диалог с ботом (вместо одноразового кода на 10 минут) и входит на сайт как обычный пользователь; персонал (admin/owner) может самостоятельно привязать свой аккаунт к тг тем же кодом, что уже выдаёт бот, и получает доступ ко всем ~25 member-фичам сайта под своим tg-аккаунтом, дополнительно к своей админ-панели.

**Architecture:** переиспользуем существующую инфраструктуру по максимуму: `panel_link_codes`/«сайт»-команда остаются как есть, просто получают новый потребитель (привязка вместо создания нового аккаунта). `POST /api/login` не меняется вообще — участник с паролем входит через него же, что и персонал. Единственная логика, которая меняется, — `require_member` (пускает ещё и персонал с привязанным tg) и фронтенд-переключатель вида (доп. вкладка вместо жёсткой замены экрана).

**Tech Stack:** Python 3.13, aiogram (бот, FSM через `StatesGroup`), FastAPI + aiomysql (панель), argon2 (хеширование паролей, `webpanel/auth.py`), ванильный JS (панель).

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-24-real-member-accounts-and-tg-linking-design.md` — при расхождении плана со спекой источник истины спека.
- Пароли — **только хэш** (`auth.hash_password`/`auth.verify_password`, argon2id, уже используется для персонала) — бот НИКОГДА не хранит и не может показать пароль в открытом виде. «Забыл пароль» = задать новый (тот же диалог заново), не восстановление старого.
- Сообщение участника с открытым текстом пароля удаляется ботом сразу после обработки (`await message.delete()`).
- Привязка tg к аккаунту персонала — **без функции отвязки** (самостоятельно бессрочно; поправить может только владелец вручную в БД).
- Один и тот же `tg_user_id` не может быть привязан к двум разным строкам `panel_users` одновременно (ни двум member, ни двум staff, ни member+staff) — гарантируется и на уровне приложения, и `UNIQUE INDEX` в БД.
- `POST /api/login`, `PanelUser`, `require_user`, `require_owner` — не меняются вообще.
- `db.py`-функции в проекте не тестируются напрямую (нет прецедента) — поведение проверяется через монкейпатч в тестах bot.py-хендлеров/webpanel-эндпоинтов.
- `tests/test_migrations_wired.py` автоматически проверяет вызов новых `ensure_*`/`_add_column_if_missing`-подобных миграций, если такие добавляются как отдельные `ensure_*`-функции (в этой задаче миграция — это правка существующей `ensure_panel_tables()`, а не новая `ensure_*`-функция, так что этот тест её не заметит — не полагаемся на него для этой конкретной миграции).
- Коммит — как и в предыдущих подпроектах: каждая задача заканчивается локальным `git commit` в репозитории `tg-bot/` (локальный, никогда не пушится).

---

### Task 1: БД — привязка tg к персоналу, апдейт member-аккаунта

**Files:**
- Modify: `db.py` (`ensure_panel_tables()` — добавить уникальный индекс; новые функции рядом с существующими `panel_users`/`panel_link_codes`-функциями, `db.py:6434-6582`)

**Interfaces:**
- Produces (используется Task 2/3):
  - `db.get_panel_user_by_tg(tg_user_id: int) -> Optional[dict]` — любая роль (в отличие от существующей `get_panel_member_by_tg`, которая фильтрует `role='member'`) — нужна, чтобы проверить «этот tg уже к кому-то привязан» перед и member-, и staff-привязкой.
  - `db.upsert_panel_member_account(tg_user_id: int, username: str, password_hash: str, tg_full_name: Optional[str]) -> int` — создаёt member-аккаунт, если для этого `tg_user_id` с ролью `member` его ещё нет, иначе обновляет `username`/`password_hash`/`tg_full_name` существующего. Возвращает `id` строки.
  - `db.set_panel_user_tg_link(user_id: int, tg_user_id: int, tg_full_name: Optional[str]) -> bool` — для привязки персонала: проставляет `tg_user_id`/`tg_full_name` существующей строке персонала по её `id`.

- [ ] **Step 1: Добавить уникальный индекс на `tg_user_id`**

В `db.py`, в `ensure_panel_tables()` (`db.py:6434-6484`), сразу после строки:
```python
    await _add_column_if_missing("panel_users", "tg_full_name", "VARCHAR(128) NULL")
```
добавить:
```python
    # Один tg-аккаунт — не больше одной строки panel_users (ни двум member,
    # ни двум staff, ни member+staff разом). MySQL считает каждый NULL
    # отдельным значением, так что это не мешает множеству ещё не
    # привязанных строк персонала с tg_user_id IS NULL.
    await _add_unique_index_if_missing("panel_users", "uniq_panel_users_tg", "tg_user_id")
```
Проверить, существует ли уже хелпер `_add_unique_index_if_missing` в `db.py` (рядом с `_add_column_if_missing`, которая уже используется в этом же файле). Если ЕСТЬ — использовать его. Если такого хелпера нет — добавить его сразу перед `ensure_panel_tables` (или туда же, где определён `_add_column_if_missing` — искать по этому имени), по образцу:
```python
async def _add_unique_index_if_missing(table: str, index_name: str, column: str) -> None:
    row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index_name),
    )
    if row and row["cnt"]:
        return
    await _execute(f"ALTER TABLE {table} ADD UNIQUE INDEX {index_name} ({column})")
```
(проверить точное имя параметра БД/схемы, используемое в остальных подобных проверках этого файла — если `_add_column_if_missing` использует другой способ проверки существования, например `information_schema.columns`, повторить тот же стиль для индекса через `information_schema.statistics`, как показано выше — это стандартный способ проверить существование индекса в MySQL).

- [ ] **Step 2: Добавить новые функции**

Сразу после `get_panel_member_by_tg` (`db.py:6515-6519`), добавить:

```python
async def get_panel_user_by_tg(tg_user_id: int) -> Optional[dict]:
    """Любая роль — в отличие от get_panel_member_by_tg (только role='member'),
    нужна проверить «этот tg уже к кому-то привязан», прежде чем создавать
    новую привязку (member или staff)."""
    return await _fetchone(
        "SELECT * FROM panel_users WHERE tg_user_id = %s", (tg_user_id,)
    )


async def upsert_panel_member_account(
    tg_user_id: int, username: str, password_hash: str, tg_full_name: Optional[str]
) -> int:
    """Заводит member-аккаунт с логином/паролем, если для этого tg_user_id с
    ролью member его ещё нет, иначе обновляет логин/пароль/имя существующего
    (тот же путь — и первичная настройка, и смена пароля/логина по команде
    «аккаунт» в личке боту)."""
    existing = await get_panel_member_by_tg(tg_user_id)
    if existing:
        await _execute(
            "UPDATE panel_users SET username = %s, password_hash = %s, tg_full_name = %s WHERE id = %s",
            (username, password_hash, tg_full_name, existing["id"]),
        )
        return existing["id"]
    return await _execute(
        "INSERT INTO panel_users (username, password_hash, role, tg_user_id, tg_full_name) "
        "VALUES (%s, %s, 'member', %s, %s)",
        (username, password_hash, tg_user_id, tg_full_name),
    )
```

Сразу после `set_panel_password` (`db.py:6568-6572`), добавить:

```python
async def set_panel_user_tg_link(user_id: int, tg_user_id: int, tg_full_name: Optional[str]) -> bool:
    return bool(await _execute(
        "UPDATE panel_users SET tg_user_id = %s, tg_full_name = %s WHERE id = %s",
        (tg_user_id, tg_full_name, user_id),
    ))
```

- [ ] **Step 2a: Проверить уникальность логина при апдейте участника**

`upsert_panel_member_account` не проверяет, не занят ли `username` кем-то ДРУГИМ (`panel_users.username` уже `UNIQUE` на уровне схемы, `db.py:6445`, так что INSERT/UPDATE с занятым чужим логином упадёт с ошибкой БД, а не тихо перезапишет чужую строку) — добавить обёртку, которая ловит это заранее и возвращает понятный сигнал вместо падения на уровне БД:

```python
async def is_username_taken_by_other(username: str, exclude_user_id: Optional[int] = None) -> bool:
    """Занят ли логин КЕМ-ТО ДРУГИМ (не самим обновляемым аккаунтом) —
    участник должен иметь возможность повторно ввести свой же логин при
    смене пароля, не получая отказ «занято»."""
    row = await _fetchone(
        "SELECT id FROM panel_users WHERE username = %s AND id != %s",
        (username, exclude_user_id or 0),
    )
    return row is not None
```

- [ ] **Step 3: Проверить, что бот импортируется, и прогнать миграционный тест**

Run: `python -c "import os; os.environ.setdefault('BOT_TOKEN','123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN'); os.environ.setdefault('OWNER_IDS','1'); import bot"`
Expected: без исключений.

Run: `pytest tests/test_migrations_wired.py -v`
Expected: PASS (эта задача не добавляет новых `ensure_*`-функций, только правит существующую `ensure_panel_tables`, так что список отслеживаемых миграций не меняется).

- [ ] **Step 4: Commit**

```bash
git add db.py
git commit -m "feat(accounts): БД — уникальный tg_user_id у panel_users, апдейт member-аккаунта, привязка персонала"
```

---

### Task 2: Бот — диалог «аккаунт» (логин+пароль участника), напоминание логина, правка текста «сайт»

**Files:**
- Modify: `bot.py` (новый `PanelAccountStates`, новые хендлеры рядом с `cmd_site_code`, `bot.py:2054-2093`)
- Create: `tests/test_panel_account_dialog.py`

**Interfaces:**
- Consumes: `db.upsert_panel_member_account`, `db.get_panel_user_by_tg`, `db.is_username_taken_by_other`, `db.get_panel_member_by_tg` (Task 1); `auth.hash_password`, `auth.validate_password`, `auth.validate_username` — эти функции живут в `webpanel/auth.py`, а `bot.py` их импортировать напрямую не может (`webpanel` — отдельный процесс/пакет с собственными зависимостями типа FastAPI, которых у бота нет, и наоборот — `bot.py` использует aiogram, которого нет смысла тянуть в панель). Продублировать в `bot.py` минимальную copy этих трёх функций (как уже задублированы уровни доступа между `bot.py` и `webpanel/roles.py` в предыдущих подпроектах) — см. Step 1.
- Produces: ничего для других задач — лист-узел на бот-стороне.

- [ ] **Step 1: Продублировать хеширование и валидацию пароля/логина в `bot.py`**

`bot.py` не может импортировать `webpanel/auth.py` (отдельный процесс, циклические зависимости на FastAPI/argon2-контекст, который бот не поднимает) — нужна собственная копия того же алгоритма хеширования (argon2), чтобы хэш, записанный ботом, проверялся тем же `verify_password` в панели. Добавить рядом с существующими импортами `bot.py` (в начало файла, где уже импортируются сторонние пакеты):

```python
from argon2 import PasswordHasher
```

и рядом с константами (например, рядом с `PANEL_LINK_CODE_TTL_MIN`, `bot.py:2061`):

```python
# Дублирует webpanel/auth.py: MIN_PASSWORD_LENGTH/_hasher/validate_password/
# validate_username/hash_password — панель отдельный процесс, импортировать
# нельзя (см. webpanel-README про дублирование констант уровней доступа).
# Править вместе с webpanel/auth.py, если меняете там.
PANEL_MIN_PASSWORD_LENGTH = 10
_panel_password_hasher = PasswordHasher()


def _panel_hash_password(password: str) -> str:
    return _panel_password_hasher.hash(password)


def _panel_validate_password(password: str) -> Optional[str]:
    if len(password) < PANEL_MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {PANEL_MIN_PASSWORD_LENGTH} символов."
    if password.isdigit():
        return "Пароль из одних цифр слишком легко подобрать."
    if password.lower() in {"password", "qwerty123456", "administrator"}:
        return "Это слишком очевидный пароль."
    return None


def _panel_validate_username(username: str) -> Optional[str]:
    if not (3 <= len(username) <= 64):
        return "Логин должен быть от 3 до 64 символов."
    if not all(ch.isalnum() or ch in "._-" for ch in username):
        return "В логине можно использовать буквы, цифры, точку, дефис и подчёркивание."
    return None
```

- [ ] **Step 2: Написать падающие тесты**

Создать `tests/test_panel_account_dialog.py`:

```python
"""Диалог «аккаунт» в личке боту — участник задаёт логин/пароль для входа на
сайт (вместо одноразового кода). Пароль хранится только как хэш (argon2) —
бот физически не может «напомнить» старый, только задать новый тем же
диалогом заново."""

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

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

PRIV_CHAT = 555


async def _async_noop(*args, **kwargs):
    return None


def _async_returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _make(text, user_id=555):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=PRIV_CHAT, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"), text=text,
    )
    sent = []
    deleted = []

    async def fake_answer(t, **kwargs):
        sent.append(t)

    async def fake_reply(t, **kwargs):
        sent.append(t)

    async def fake_delete():
        deleted.append(m.message_id)

    object.__setattr__(m, "answer", fake_answer)
    object.__setattr__(m, "reply", fake_reply)
    object.__setattr__(m, "delete", fake_delete)
    return m, sent, deleted


async def _fresh_state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=PRIV_CHAT, user_id=PRIV_CHAT)
    return FSMContext(storage=storage, key=key)


def test_уже_привязанный_персонал_получает_отказ(monkeypatch):
    async def get_panel_user_by_tg(tg_user_id):
        return {"id": 9, "role": "admin", "username": "boss", "tg_user_id": tg_user_id}

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", get_panel_user_by_tg)

    m, sent, _ = _make("аккаунт")
    state = asyncio.run(_fresh_state())
    asyncio.run(bot_module.cmd_panel_account_start(m, state))

    assert sent and "персонал" in sent[0].casefold()


def test_новый_участник_проходит_оба_шага(monkeypatch):
    async def get_panel_user_by_tg(tg_user_id):
        return None

    monkeypatch.setattr(bot_module.db, "get_panel_user_by_tg", get_panel_user_by_tg)
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(False))

    calls = []

    async def upsert_panel_member_account(tg_user_id, username, password_hash, tg_full_name):
        calls.append((tg_user_id, username, password_hash, tg_full_name))
        return 42

    monkeypatch.setattr(bot_module.db, "upsert_panel_member_account", upsert_panel_member_account)

    state = asyncio.run(_fresh_state())

    m1, sent1, _ = _make("аккаунт")
    asyncio.run(bot_module.cmd_panel_account_start(m1, state))
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_username.state

    m2, sent2, _ = _make("новый_логин")
    asyncio.run(bot_module.panel_account_username_step(m2, state))
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_password.state
    data = asyncio.run(state.get_data())
    assert data["panel_account_username"] == "новый_логин"

    m3, sent3, deleted3 = _make("суперсекретныйпароль123")
    asyncio.run(bot_module.panel_account_password_step(m3, state))

    assert deleted3 == [m3.message_id]
    assert len(calls) == 1
    tg_user_id, username, password_hash, tg_full_name = calls[0]
    assert tg_user_id == 555 and username == "новый_логин"
    assert bot_module._panel_password_hasher.verify(password_hash, "суперсекретныйпароль123") is True
    assert asyncio.run(state.get_state()) is None
    assert sent3 and "готово" in sent3[-1].casefold()


def test_короткий_пароль_отклоняется_без_сохранения(monkeypatch):
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(False))

    saved = []

    async def upsert_panel_member_account(*a, **k):
        saved.append(a)
        return 1

    monkeypatch.setattr(bot_module.db, "upsert_panel_member_account", upsert_panel_member_account)

    state = asyncio.run(_fresh_state())
    asyncio.run(state.set_state(bot_module.PanelAccountStates.waiting_password))
    asyncio.run(state.update_data(panel_account_username="логин1"))

    m, sent, deleted = _make("123")
    asyncio.run(bot_module.panel_account_password_step(m, state))

    assert not saved
    assert deleted == [m.message_id]
    assert sent and "короче" in sent[-1].casefold()
    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_password.state


def test_занятый_логин_просит_другой(monkeypatch):
    monkeypatch.setattr(bot_module.db, "is_username_taken_by_other", _async_returns(True))

    state = asyncio.run(_fresh_state())
    asyncio.run(state.set_state(bot_module.PanelAccountStates.waiting_username))

    m, sent, _ = _make("занятый_логин")
    asyncio.run(bot_module.panel_account_username_step(m, state))

    assert asyncio.run(state.get_state()) == bot_module.PanelAccountStates.waiting_username.state
    assert sent and "занят" in sent[-1].casefold()


def test_мой_логин_напоминает_существующий(monkeypatch):
    async def get_panel_member_by_tg(tg_user_id):
        return {"id": 7, "username": "мой_логин_тут", "tg_user_id": tg_user_id}

    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", get_panel_member_by_tg)

    m, sent, _ = _make("мой логин")
    asyncio.run(bot_module.cmd_my_panel_login(m))

    assert sent and "мой_логин_тут" in sent[0]


def test_мой_логин_без_аккаунта(monkeypatch):
    monkeypatch.setattr(bot_module.db, "get_panel_member_by_tg", _async_returns(None))

    m, sent, _ = _make("мой логин")
    asyncio.run(bot_module.cmd_my_panel_login(m))

    assert sent and "аккаунт" in sent[0].casefold()
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `pytest tests/test_panel_account_dialog.py -v`
Expected: FAIL/ERROR — `PanelAccountStates`/`cmd_panel_account_start`/`panel_account_username_step`/`panel_account_password_step`/`cmd_my_panel_login` не существуют.

- [ ] **Step 4: Реализовать FSM-состояния и хендлеры**

Сразу после `class ComplaintStates(StatesGroup):` (`bot.py:1210` — найти блок с другими `StatesGroup`, добавить новый класс рядом), добавить:

```python
class PanelAccountStates(StatesGroup):
    waiting_username = State()
    waiting_password = State()
```

Сразу после `cmd_site_code` (`bot.py:2074-2093`), добавить:

```python
@router.message(
    F.chat.type == "private",
    F.text.func(lambda t: bool(t) and t.strip().casefold() == "аккаунт"),
)
async def cmd_panel_account_start(message: Message, state: FSMContext):
    existing_staff = await db.get_panel_user_by_tg(message.from_user.id)
    if existing_staff and existing_staff["role"] in ("owner", "admin"):
        await message.reply(
            "Вы уже привязаны на сайте как персонал (логин "
            f"«{html.escape(existing_staff['username'])}»). Отдельный аккаунт участника "
            "заводить не нужно — вход по обычному логину/паролю."
        )
        return
    await state.set_state(PanelAccountStates.waiting_username)
    await message.answer(
        "🔑 <b>Аккаунт на сайте</b>\n\n"
        "Придумайте логин для входа (буквы, цифры, точка, дефис, подчёркивание, "
        "от 3 до 64 символов):"
    )


@router.message(F.chat.type == "private", StateFilter(PanelAccountStates.waiting_username))
async def panel_account_username_step(message: Message, state: FSMContext):
    username = (message.text or "").strip()
    error = _panel_validate_username(username)
    if error:
        await message.reply(error)
        return
    if await db.is_username_taken_by_other(username):
        await message.reply(f"Логин «{html.escape(username)}» уже занят, придумайте другой:")
        return
    await state.update_data(panel_account_username=username)
    await state.set_state(PanelAccountStates.waiting_password)
    await message.answer(
        f"Логин: <code>{html.escape(username)}</code>. Теперь придумайте пароль "
        f"(от {PANEL_MIN_PASSWORD_LENGTH} символов) — сообщение с паролем сразу "
        "удалится из чата."
    )


@router.message(F.chat.type == "private", StateFilter(PanelAccountStates.waiting_password))
async def panel_account_password_step(message: Message, state: FSMContext):
    password = message.text or ""
    try:
        await message.delete()
    except Exception:
        logger.exception("Не удалось удалить сообщение с паролем")

    error = _panel_validate_password(password)
    if error:
        await message.reply(f"{error} Придумайте пароль ещё раз:")
        return

    data = await state.get_data()
    username = data.get("panel_account_username")
    if not username:
        await state.clear()
        await message.answer("⚠️ Что-то пошло не так, начните заново командой «аккаунт».")
        return

    password_hash = _panel_hash_password(password)
    await db.upsert_panel_member_account(
        message.from_user.id, username, password_hash,
        message.from_user.full_name or str(message.from_user.id),
    )
    await state.clear()
    await message.answer(
        f"✅ Готово! Логин: <code>{html.escape(username)}</code>. "
        f"Заходите на сайт ({PANEL_SITE_URL}) по обычной форме входа."
    )


@router.message(
    F.chat.type == "private",
    F.text.func(lambda t: bool(t) and t.strip().casefold() == "мой логин"),
)
async def cmd_my_panel_login(message: Message):
    account = await db.get_panel_member_by_tg(message.from_user.id)
    if not account:
        await message.reply(
            "У вас пока нет аккаунта участника на сайте — заведите командой «аккаунт»."
        )
        return
    await message.answer(f"Ваш логин на сайте: <code>{html.escape(account['username'])}</code>")
```

Примечание: проверено напрямую в этом окружении — `PasswordHasher.verify(hash, password)` при совпадении возвращает `True` (не `None`), при несовпадении бросает `VerifyMismatchError`. Тест в Step 2 уже использует `assert ... is True` — оставить как есть, не менять на `try/except`.

- [ ] **Step 5: Обновить текст команды «сайт», чтобы упоминать оба сценария**

В `bot.py`, в `cmd_site_code` (`bot.py:2081-2092`), заменить текст сообщения (сохранить кнопку и остальную логику без изменений):

```python
    await message.answer(
        "🔑 <b>Код для сайта</b>\n\n"
        f"<code>{code}</code>\n\n"
        f"🌐 Сайт: {PANEL_SITE_URL}\n"
        f"Если у вас ЕЩЁ НЕТ аккаунта персонала — этот код для входа участника "
        "устарел, используйте команду «аккаунт», чтобы задать логин/пароль.\n"
        "Если вы уже вошли на сайте как персонал (admin/owner) — введите этот код "
        "в разделе привязки Telegram в панели, чтобы привязать свой аккаунт к тг. "
        f"Код одноразовый и действует {PANEL_LINK_CODE_TTL_MIN} минут.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🌐 Сайт", url=PANEL_SITE_URL)]]
        ),
    )
```

- [ ] **Step 6: Прогнать тесты — должны пройти**

Run: `pytest tests/test_panel_account_dialog.py -v`
Expected: PASS (7 тестов), либо `SKIPPED` целиком без настоящего aiogram.

- [ ] **Step 7: Прогнать весь набор тестов**

Run: `pytest tests/ -q`
Expected: PASS, за вычетом уже известного предсуществующего несвязанного флейки-теста в `tests/test_panel_member.py`.

- [ ] **Step 8: Commit**

```bash
git add bot.py tests/test_panel_account_dialog.py
git commit -m "feat(accounts): диалог «аккаунт» — логин/пароль участника через личку боту"
```

---

### Task 3: Панель — привязка персонала к тг, доступ к member-фичам

**Files:**
- Modify: `webpanel/auth.py` (`require_member`, `webpanel/auth.py:195-203`)
- Modify: `webpanel/app.py` (новый эндпоинт `POST /api/link-telegram`, рядом с `/api/member/login`, `webpanel/app.py:531-561`)
- Create: `tests/test_panel_link_telegram.py`

**Interfaces:**
- Consumes: `db.consume_panel_link_code` (существует), `db.get_panel_user_by_tg`, `db.set_panel_user_tg_link` (Task 1).
- Produces: `POST /api/link-telegram` — используется Task 4 (фронтенд).

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_panel_link_telegram.py`:

```python
"""Персонал самостоятельно привязывает свой аккаунт к Telegram — тем же
кодом, что уже выдаёт команда «сайт». После привязки require_member должен
пускать персонал на member-эндпоинты."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client(monkeypatch):
    state = {"codes": {}, "users": {}, "logs": []}

    async def consume_panel_link_code(code):
        row = state["codes"].pop(code, None)
        return dict(row) if row else None

    async def get_panel_user_by_tg(tg_user_id):
        for u in state["users"].values():
            if u.get("tg_user_id") == tg_user_id:
                return dict(u)
        return None

    async def set_panel_user_tg_link(user_id, tg_user_id, tg_full_name):
        if user_id not in state["users"]:
            return False
        state["users"][user_id]["tg_user_id"] = tg_user_id
        state["users"][user_id]["tg_full_name"] = tg_full_name
        return True

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    monkeypatch.setattr(db, "consume_panel_link_code", consume_panel_link_code)
    monkeypatch.setattr(db, "get_panel_user_by_tg", get_panel_user_by_tg)
    monkeypatch.setattr(db, "set_panel_user_tg_link", set_panel_user_tg_link)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    c = TestClient(panel.app)
    c.state = state
    yield c
    panel.app.dependency_overrides.clear()


def _login_as(client, user_id=1, role="admin", tg_user_id=None):
    user = PanelUser(id=user_id, username="staffuser", role=role, tg_user_id=tg_user_id)
    client.state["users"][user_id] = {
        "id": user_id, "username": "staffuser", "role": role, "tg_user_id": tg_user_id,
    }
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: user
    return user


def test_успешная_привязка(client):
    _login_as(client, user_id=1, tg_user_id=None)
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": "someone", "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 200, res.text
    assert client.state["users"][1]["tg_user_id"] == 999
    assert "panel_tg_linked" in client.state["logs"][0] or client.state["logs"]


def test_невалидный_код(client):
    _login_as(client, user_id=1, tg_user_id=None)
    res = client.post("/api/link-telegram", json={"code": "NOPE0000"})
    assert res.status_code == 400


def test_уже_привязан_нельзя_перепривязать(client):
    _login_as(client, user_id=1, tg_user_id=555)
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": None, "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 409


def test_tg_уже_занят_другим_аккаунтом(client):
    _login_as(client, user_id=1, tg_user_id=None)
    client.state["users"][2] = {"id": 2, "username": "other", "role": "admin", "tg_user_id": 999}
    client.state["codes"]["ABC12345"] = {
        "code": "ABC12345", "tg_user_id": 999, "tg_username": None, "tg_full_name": "Кто-то",
    }
    res = client.post("/api/link-telegram", json={"code": "ABC12345"})
    assert res.status_code == 409
```

Плюс тест на саму функцию `require_member` (тестируем её напрямую, не через `TestClient`/эндпоинт — она вызывается как обычная async-функция с `Request`-like объектом, из которого читает только `request.cookies`; `current_user()` — единственная её внутренняя зависимость, monkeypatch'им через фикстуру `monkeypatch`, как и везде в проекте):

```python
import asyncio

from webpanel import auth as panel_auth


class _FakeRequest:
    cookies: dict = {}


def test_require_member_пускает_привязанный_персонал(monkeypatch):
    user = panel_auth.PanelUser(id=1, username="staffuser", role="admin", tg_user_id=777)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel_auth, "current_user", fake_current_user)
    result = asyncio.run(panel_auth.require_member(_FakeRequest()))
    assert result.id == 1


def test_require_member_не_пускает_непривязанный_персонал(monkeypatch):
    user = panel_auth.PanelUser(id=1, username="staffuser", role="admin", tg_user_id=None)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel_auth, "current_user", fake_current_user)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(panel_auth.require_member(_FakeRequest()))
    assert exc_info.value.status_code == 403


def test_require_member_как_и_раньше_пускает_обычного_участника(monkeypatch):
    user = panel_auth.PanelUser(id=2, username="tg12345", role="member", tg_user_id=12345)

    async def fake_current_user(request):
        return user

    monkeypatch.setattr(panel_auth, "current_user", fake_current_user)
    result = asyncio.run(panel_auth.require_member(_FakeRequest()))
    assert result.id == 2
```

`HTTPException` нужно импортировать в тестовом файле: `from fastapi import HTTPException`. `pytest.raises(HTTPException)`-подход даёт возможность проверить конкретно `status_code == 403`, а не любое исключение — важно отличать «нет доступа» (403) от «не вошёл» (401), которые обрабатываются разными ветками `require_member`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_panel_link_telegram.py -v`
Expected: FAIL — эндпоинта `/api/link-telegram` ещё нет (404), `require_member` ещё не пускает персонал.

- [ ] **Step 3: Изменить `require_member`**

В `webpanel/auth.py`, заменить (`webpanel/auth.py:195-203`):

```python
async def require_member(request: Request) -> PanelUser:
    """Доступ для аккаунта-участника (роль member). Персонал сюда не пускаем —
    у него свои разделы; участнику эндпоинты read-only."""
    user = await current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход")
    if not user.is_member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел для участников")
    return user
```

на:

```python
async def require_member(request: Request) -> PanelUser:
    """Доступ для аккаунта-участника (роль member) — а также для персонала
    (admin/owner), самостоятельно привязавшего свой аккаунт к Telegram
    (POST /api/link-telegram): тогда те же member-эндпоинты работают под их
    собственным tg_user_id, дополнительно к обычной админ-панели."""
    user = await current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход")
    if user.is_member:
        return user
    if user.role in STAFF_ROLES and user.tg_user_id is not None:
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел для участников")
```

- [ ] **Step 4: Добавить `POST /api/link-telegram`**

В `webpanel/app.py`, сразу после `api_member_login` (`webpanel/app.py:531-561`), добавить:

```python
class LinkTelegramBody(BaseModel):
    code: str


@app.post("/api/link-telegram")
async def api_link_telegram(
    body: LinkTelegramBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if user.tg_user_id is not None:
        raise HTTPException(409, "Ваш аккаунт уже привязан к Telegram.")

    row = await db.consume_panel_link_code(body.code.strip().upper())
    if not row:
        raise HTTPException(400, "Код неверный или устарел.")

    existing = await db.get_panel_user_by_tg(row["tg_user_id"])
    if existing and existing["id"] != user.id:
        raise HTTPException(409, "Этот Telegram уже привязан к другому аккаунту.")

    await db.set_panel_user_tg_link(user.id, row["tg_user_id"], row.get("tg_full_name"))
    await db.add_log("panel_tg_linked", actor_id=user.id, details=str(row["tg_user_id"]))
    return {"ok": True, "tg_full_name": row.get("tg_full_name")}
```

`BaseModel`, `Depends`, `HTTPException`, `Request`, `PanelUser` уже импортированы в этом файле.

- [ ] **Step 5: Прогнать тесты — должны пройти**

Run: `pytest tests/test_panel_link_telegram.py -v`
Expected: PASS.

- [ ] **Step 6: Прогнать весь набор тестов панели**

Run: `pytest tests/ -k panel -v`
Expected: PASS (ничего не сломано — особое внимание на все существующие тесты `require_member`/`/api/member/*`, которые проверяли отказ персоналу: они должны по-прежнему отказывать персоналу БЕЗ `tg_user_id`, что не меняется этой правкой).

- [ ] **Step 7: Commit**

```bash
git add webpanel/auth.py webpanel/app.py tests/test_panel_link_telegram.py
git commit -m "feat(accounts): персонал привязывает аккаунт к Telegram; require_member пускает привязанный персонал"
```

---

### Task 4: Фронтенд — привязка Telegram у персонала + доступ к экрану участника

**Files:**
- Modify: `webpanel/static/index.html` (блок привязки — где именно, implementer определяет по факту чтения файла: рядом с существующими настройками/профилем персонала, например там же, где смена своего пароля, `POST /api/password`)
- Modify: `webpanel/static/app.js` (`boot()`, `webpanel/static/app.js:156-175`, плюс новая логика привязки/переключения вида)

**Interfaces:**
- Consumes: `POST /api/link-telegram` (Task 3), существующий `GET /api/me` (не меняется — должен уже отдавать `tg_user_id`/`tg_full_name`, если они непустые — implementer должен проверить, отдаёт ли `/api/me` эти поля уже сейчас; если нет — добавить их в ответ этого эндпоинта, это не отдельная задача, а необходимая часть той же правки).

- [ ] **Step 1: Проверить/дополнить `GET /api/me`**

Найти существующий эндпоинт `GET /api/me` в `webpanel/app.py` (используется `boot()` на фронтенде). Убедиться, что его ответ включает `tg_user_id`/`tg_full_name` для персонала (сейчас, вероятно, отдаёт только `role`/`username`/`authenticated`, так как раньше это было не нужно). Если полей нет — добавить их в возвращаемый dict для персонала (`role in STAFF_ROLES`), беря значения из `user.tg_user_id`/`user.tg_full_name`.

- [ ] **Step 2: Добавить UI привязки и переключатель вида**

В `webpanel/static/app.js`, в `boot()` (`webpanel/static/app.js:156-175`), после строки `if (me.role === "member") showMember(); else showApp();` ничего не менять в этой ветке — вместо этого внутри `showApp()` (найти определение — общий вход для персонала) добавить рендер блока привязки/переключения:

- Если `me.tg_user_id` пусто — показать небольшую форму («код из бота» + кнопка «Привязать»), вызывающую `POST /api/link-telegram`; при успехе — обновить `me` (например, повторным вызовом `/api/me` или локально проставив поля) и перерисовать блок как «✅ Привязан к Telegram: {tg_full_name}».
- Если `me.tg_user_id` уже есть — показать кнопку/пункт меню «Мой профиль участника», по клику вызывающую `showMember()` (существующая функция, которая сейчас вызывается только при `role === 'member'`) — и добавить в экран участника (там, где сейчас, вероятно, нет кнопки «выйти в панель», раз туда раньше попадал только чистый participant) способ вернуться — по клику `showApp()` обратно, **только если `me.role` — персонал** (чистый участник такой кнопки не видит, ему некуда «возвращаться»).

Implementer сам определяет точную разметку/расположение (это в первую очередь про доступность функционала, а не про конкретные CSS-классы) — переиспользовать существующие стили карточек/кнопок панели, не изобретать новые.

- [ ] **Step 3: Проверить синтаксис**

Run: `node --check webpanel/static/app.js`
Expected: без ошибок.

- [ ] **Step 4: Проверить вручную в браузере**

Ручная проверка (нет JS-тестового рантайма в проекте):

1. Войти как admin/owner без привязки — видно поле «код из бота».
2. В боте выполнить «сайт», получить код, ввести его — видно «✅ Привязан к Telegram: ...».
3. Кликнуть «Мой профиль участника» — виден тот же экран, что видит обычный участник (браки/кланы/питомцы и т.д., под tg-аккаунтом этого же персонала).
4. Кликнуть «Назад в панель» — снова обычная админ-панель.
5. Обновить страницу (F5) — привязка сохраняется, кнопка «Мой профиль участника» на месте.
6. Войти как обычный участник (`role=member`) — кнопки «Назад в панель» НЕТ (ему некуда возвращаться).

- [ ] **Step 5: Commit**

```bash
git add webpanel/static/index.html webpanel/static/app.js webpanel/app.py
git commit -m "feat(panel): привязка Telegram у персонала + переключение на профиль участника"
```

---

### Task 5: Хелп-текст

**Files:**
- Modify: `help_texts.py` (подраздел про сайт/панель, если такой уже есть — найти по факту чтения файла; если отдельного подраздела про вход на сайт ещё нет, добавить его рядом с описанием команды «сайт», если она вообще упоминается в хелпе).

**Interfaces:**
- Нет — чисто документация.

- [ ] **Step 1: Найти существующее упоминание команды «сайт»/входа на сайт в хелпе**

Открыть `help_texts.py`, найти текст, упоминающий вход на сайт/команду «сайт» (implementer определяет по факту чтения — если такого текста нет вообще, эта задача просто добавляет новый короткий подраздел, а не правит существующий).

- [ ] **Step 2: Обновить/добавить текст**

Описать: команда «аккаунт» — завести логин/пароль для входа на сайт участнику; команда «мой логин» — напомнить логин; команда «сайт» — код для персонала, чтобы привязать существующий аккаунт к тг (раздел на сайте, где ввести код).

- [ ] **Step 3: Прогнать тест хелпа**

Run: `pytest tests/test_help_texts_accuracy.py -v`
Expected: PASS (эта задача не меняет ничего, что проверяют существующие тесты этого файла, если только implementer случайно не задел проверяемый текст — тогда свериться и поправить).

- [ ] **Step 4: Commit**

```bash
git add help_texts.py
git commit -m "docs(accounts): хелп про команды «аккаунт»/«мой логин»/привязку персонала к тг"
```

---

## Порядок выполнения

Task 1 → Task 2 → Task 3 → Task 4 → Task 5. Task 2 и Task 3 оба зависят только от Task 1 — можно поменять местами. Task 4 зависит от Task 3 (эндпоинт). Task 5 не зависит ни от чего технически, но логичнее делать последней, когда весь функционал уже описан кодом.
