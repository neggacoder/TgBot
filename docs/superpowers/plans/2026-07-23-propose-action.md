# «Предложить действие» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** участник чата предлагает другому «предложить <действие>» (полить цветы, дуэль на щелбанчики и т.п.), бот показывает Да/Нет, согласие/отказ редактирует то же сообщение; список действий (7 по умолчанию), их синонимы и все тексты редактируются владельцем/админами через бота и через сайт.

**Architecture:** новый набор таблиц в БД (`propose_actions`/`propose_action_synonyms`/`propose_phrases` — глобальная конфигурация без `chat_id`, как `rp_actions`; `propose_requests`/`propose_cooldowns` — рантайм-состояние с `chat_id`, как `rel2_requests`). Матчинг триггера и хендлер сообщения — по образцу `handle_rp_action`/`_match_rp_action_prefix`. Callback Да/Нет — по образцу `_role_proposal_decision`/`rprop_approve`. Управление — текстовые команды в личке (по образцу `rp_admin_command`) + сайт (новые эндпоинты `/api/propose-actions/*`, права через существующий `COMMAND_REGISTRY`/«Дерево команд», не через отдельный owner-only гейт). Live-reload между ботом и панелью — существующий `_signal_action_reload()`/`panel_action_reload_loop`.

**Tech Stack:** Python 3.13, aiogram (бот), FastAPI + aiomysql (панель, `webpanel/app.py`), ванильный JS (`webpanel/static/app.js`), pytest (`tests/conftest.py` подменяет aiogram/aiomysql заглушками там, где настоящих пакетов нет).

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-23-propose-action-design.md` — при расхождении плана со спекой источник истины спека.
- Адресат — reply ИЛИ @username/text_mention/голый ID (`resolve_command_target`, приоритет — то, что нашлось в тексте; reply — фолбэк).
- Действие работает только в группах/супергруппах, не в личке.
- На действие — 4 настраиваемых элемента: синонимы триггера, фразы «предложение» (5 вариантов), «согласие» (5 вариантов), «отказ» (5 вариантов). Бот берёт случайный вариант при показе.
- Список действий — глобальный для всего бота (без `chat_id`), как РП-действия.
- Кулдаун и таймаут — свои у каждого действия, в секундах, правятся на сайте (и текстовой командой в личке).
- Доступ к управлению (бот и сайт) — через `COMMAND_REGISTRY["propose_manage"]` (дефолт `LEVEL_SENIOR`, как `rp_manage`), точный уровень владелец меняет во вкладке «Дерево команд» — отдельного owner-only флага в панели не заводим.
- `db.py`-функции в проекте не тестируются напрямую (нет ни одного прецедента в `tests/`) — их поведение проверяется через монкейпатч в тестах `bot.py`-хендлеров и `webpanel/app.py`-эндпоинтов, как для `rp_actions`/`rel2_requests`. Не изобретаем для этой фичи отдельный слой unit-тестов на `db.py`.
- `tests/test_migrations_wired.py::test_каждая_миграция_вызывается` уже автоматически проверяет, что каждая новая `ensure_*` функция где-то вызывается — отдельного теста на это не пишем, но проверяем, что он проходит.
- Тесты запускаются из `tg-bot/`: `pytest tests/<file>.py -v`. Тесты, вызывающие `bot.py`-хендлеры напрямую, требуют настоящего `aiogram` (`pytest.importorskip`, см. `tests/test_bot_routing.py:24-30`) — без него они помечаются `SKIPPED`, а не падают.
- Коммит — как и в предыдущем подпроекте «Награды — пороги по ролям»: каждая задача заканчивается локальным `git commit` в репозитории `tg-bot/` (локальный, никогда не пушится) — это часть согласованного SDD-воркфлоу ревью между задачами. Дизайн-спека и сам этот план коммитятся отдельно, только по прямому запросу пользователя в моменте (см. память `never-commit-without-explicit-ask` — коммит не по запросу это ошибка, не повторять).

---

### Task 1: БД — схема, CRUD, сидирование дефолтов

**Files:**
- Modify: `db.py` (новые `ensure_*_table`/CRUD/`seed_*_if_empty`, после блока `self_actions` CRUD, `db.py:3278-3324`, перед комментарием `# REL_ONLY_PARTNER_ACTIONS...` на `db.py:3330`)
- Modify: `bot.py` (дефолтные данные для сидирования + вызовы в `main()`, `bot.py:21084-21086` и `bot.py:21127-21129`)
- Test: `tests/test_migrations_wired.py` (уже существует, не меняется — проверяем, что проходит)

**Interfaces:**
- Produces (используется Task 2-6):
  - `db.list_propose_actions(active_only: bool = True) -> dict[str, dict]` — `{action_key: {"propose": [str,...], "agree": [str,...], "decline": [str,...], "cooldown_seconds": int, "timeout_seconds": int}}`.
  - `db.list_propose_actions_rows() -> list[dict]` — `{action_key, cooldown_seconds, timeout_seconds, is_active}` на строку, все действия (для панели).
  - `db.list_propose_phrases_rows() -> list[dict]` — `{id, action_key, kind, phrase, sort_order, is_active}` на строку, все фразы всех действий.
  - `db.add_propose_phrase(action_key: str, kind: str, phrase: str) -> int`, `db.update_propose_phrase(phrase_id: int, phrase: str) -> bool`, `db.delete_propose_phrase(phrase_id: int) -> bool`.
  - `db.set_propose_action_active(action_key: str, is_active: bool) -> int` (число задетых строк `propose_actions`, 0 или 1).
  - `db.set_propose_action_settings(action_key: str, cooldown_seconds: Optional[int] = None, timeout_seconds: Optional[int] = None) -> bool` — оба параметра опциональны и обновляют только переданное поле (частичный `UPDATE`), чтобы вызывающему не нужно было знать текущее значение второго поля (см. Task 4 — текстовая команда меняет только один из двух за раз).
  - `db.list_propose_action_synonyms() -> dict[str, str]`, `db.add_propose_action_synonym(synonym: str, action_key: str) -> None`, `db.delete_propose_action_synonym(synonym: str) -> bool`.
  - `db.create_or_replace_propose_request(chat_id: int, message_id: int, action_key: str, from_user_id: int, to_user_id: int) -> int` (id новой строки; вызывается с `message_id=0`-заглушкой ДО отправки сообщения — см. Task 2).
  - `db.set_propose_request_message_id(request_id: int, message_id: int) -> None` — проставляет настоящий `message_id` СРАЗУ ПОСЛЕ отправки (Telegram отдаёт `message_id` только после того, как сообщение уже отправлено, а `request_id` для `callback_data` нужен ДО отправки — отсюда двухшаговая запись, без правки уже отправленной клавиатуры).
  - `db.get_propose_request(request_id: int) -> Optional[dict]` — `{id, chat_id, message_id, action_key, from_user_id, to_user_id, created_at}`.
  - `db.delete_propose_request(request_id: int) -> bool`.
  - `db.list_expired_propose_requests(now: datetime) -> list[dict]` — те же поля + `timeout_seconds` действия.
  - `db.check_and_touch_propose_cooldown(chat_id: int, action_key: str, from_user_id: int, to_user_id: int, cooldown_seconds: int) -> Optional[int]` — `None`, если кулдаун прошёл (и он тут же обновлён на «сейчас»); иначе — сколько секунд ещё ждать (строка не тронута).

- [ ] **Step 1: Добавить таблицы в `db.py`**

Найти конец блока `self_actions` CRUD (после `delete_self_action_phrase`/`set_self_action_key_active`, `db.py:3278-3324`) и комментарий `# REL_ONLY_PARTNER_ACTIONS` (`db.py:3330`). Вставить между ними:

```python
# ----------------------------------------------------------------------------
# «Предложить действие» — один участник предлагает другому что-то сделать,
# бот показывает Да/Нет. propose_actions/propose_action_synonyms/propose_phrases
# — глобальная конфигурация (без chat_id, как rp_actions/rp_action_synonyms).
# propose_requests/propose_cooldowns — рантайм-состояние конкретного чата/пары
# (с chat_id, как rel2_requests).
# ----------------------------------------------------------------------------

async def ensure_propose_actions_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS propose_actions ("
        "action_key VARCHAR(64) NOT NULL PRIMARY KEY, "
        "cooldown_seconds INT NOT NULL DEFAULT 300, "
        "timeout_seconds INT NOT NULL DEFAULT 120, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_propose_action_synonyms_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS propose_action_synonyms ("
        "synonym VARCHAR(64) NOT NULL PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "INDEX idx_propose_action_synonyms_key (action_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_propose_phrases_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS propose_phrases ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "kind ENUM('propose','agree','decline') NOT NULL, "
        "phrase VARCHAR(512) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_propose_phrases_key (action_key, kind, sort_order)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_propose_requests_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS propose_requests ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "message_id BIGINT NOT NULL, "
        "action_key VARCHAR(64) NOT NULL, "
        "from_user_id BIGINT NOT NULL, "
        "to_user_id BIGINT NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_propose_requests_pair (chat_id, action_key, from_user_id, to_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_propose_cooldowns_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS propose_cooldowns ("
        "chat_id BIGINT NOT NULL, "
        "action_key VARCHAR(64) NOT NULL, "
        "from_user_id BIGINT NOT NULL, "
        "to_user_id BIGINT NOT NULL, "
        "last_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, action_key, from_user_id, to_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
```

- [ ] **Step 2: Добавить сидирование дефолтов**

Сразу после таблиц из Step 1:

```python
async def seed_propose_actions_if_empty(action_keys: list[str]) -> int:
    """Заполняет propose_actions ключами действий (cooldown/timeout — из
    DEFAULT колонок) — только если таблица пуста."""
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM propose_actions")
    if row and row["cnt"]:
        return 0
    n = 0
    for key in action_keys:
        await _execute("INSERT INTO propose_actions (action_key) VALUES (%s)", (key,))
        n += 1
    return n


async def seed_propose_action_synonyms_if_empty(defaults: dict[str, str]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM propose_action_synonyms")
    if row and row["cnt"]:
        return 0
    n = 0
    for synonym, action_key in defaults.items():
        await _execute(
            "INSERT IGNORE INTO propose_action_synonyms (synonym, action_key) VALUES (%s, %s)",
            (synonym, action_key),
        )
        n += 1
    return n


async def seed_propose_phrases_if_empty(defaults: dict[str, dict[str, list[str]]]) -> int:
    """defaults: {action_key: {"propose": [...], "agree": [...], "decline": [...]}}."""
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM propose_phrases")
    if row and row["cnt"]:
        return 0
    n = 0
    for action_key, kinds in defaults.items():
        for kind, phrases in kinds.items():
            for i, phrase in enumerate(phrases):
                await _execute(
                    "INSERT INTO propose_phrases (action_key, kind, phrase, sort_order) VALUES (%s, %s, %s, %s)",
                    (action_key, kind, phrase, i),
                )
                n += 1
    return n
```

- [ ] **Step 3: Добавить CRUD-функции**

Сразу после Step 2:

```python
async def list_propose_actions(active_only: bool = True) -> dict[str, dict]:
    """Живой формат для кэша бота: {action_key: {"propose": [...], "agree": [...],
    "decline": [...], "cooldown_seconds": int, "timeout_seconds": int}}. Выключенные
    действия (is_active=0) не отдаются — их и не должно быть видно в чате."""
    actions = await _fetchall(
        "SELECT action_key, cooldown_seconds, timeout_seconds FROM propose_actions"
        + (" WHERE is_active = TRUE" if active_only else "")
    )
    result: dict[str, dict] = {
        a["action_key"]: {
            "propose": [], "agree": [], "decline": [],
            "cooldown_seconds": a["cooldown_seconds"], "timeout_seconds": a["timeout_seconds"],
        }
        for a in actions
    }
    phrases = await _fetchall(
        "SELECT action_key, kind, phrase FROM propose_phrases WHERE is_active = TRUE ORDER BY action_key, kind, sort_order"
    )
    for p in phrases:
        entry = result.get(p["action_key"])
        if entry is not None:
            entry[p["kind"]].append(p["phrase"])
    return result


async def list_propose_actions_rows() -> list[dict]:
    """Все действия, включая выключенные (для панели/меню — иначе их нельзя
    было бы включить обратно)."""
    return await _fetchall(
        "SELECT action_key, cooldown_seconds, timeout_seconds, is_active FROM propose_actions "
        "ORDER BY action_key"
    )


async def list_propose_phrases_rows() -> list[dict]:
    return await _fetchall(
        "SELECT id, action_key, kind, phrase, sort_order, is_active FROM propose_phrases "
        "ORDER BY action_key, kind, sort_order"
    )


async def add_propose_phrase(action_key: str, kind: str, phrase: str, sort_order: Optional[int] = None) -> int:
    await _execute(
        "INSERT INTO propose_actions (action_key) VALUES (%s) ON DUPLICATE KEY UPDATE action_key = action_key",
        (action_key,),
    )
    if sort_order is None:
        row = await _fetchone(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM propose_phrases "
            "WHERE action_key = %s AND kind = %s",
            (action_key, kind),
        )
        sort_order = row["next_order"] if row else 0
    return await _execute(
        "INSERT INTO propose_phrases (action_key, kind, phrase, sort_order) VALUES (%s, %s, %s, %s)",
        (action_key, kind, phrase, sort_order),
    )


async def update_propose_phrase(phrase_id: int, phrase: str) -> bool:
    rowcount = await _execute("UPDATE propose_phrases SET phrase = %s WHERE id = %s", (phrase, phrase_id))
    return bool(rowcount)


async def delete_propose_phrase(phrase_id: int) -> bool:
    rowcount = await _execute("DELETE FROM propose_phrases WHERE id = %s", (phrase_id,))
    return bool(rowcount)


async def set_propose_action_active(action_key: str, is_active: bool) -> int:
    return await _execute(
        "UPDATE propose_actions SET is_active = %s WHERE action_key = %s", (is_active, action_key)
    )


async def set_propose_action_settings(
    action_key: str, cooldown_seconds: Optional[int] = None, timeout_seconds: Optional[int] = None
) -> bool:
    """Оба параметра опциональны — обновляется только переданное поле
    (частичный UPDATE), чтобы вызывающему не нужно было знать/перечитывать
    текущее значение другого поля (текстовая команда бота меняет за раз
    только одно из двух; панель обычно передаёт оба сразу)."""
    sets, params = [], []
    if cooldown_seconds is not None:
        sets.append("cooldown_seconds = %s")
        params.append(cooldown_seconds)
    if timeout_seconds is not None:
        sets.append("timeout_seconds = %s")
        params.append(timeout_seconds)
    if not sets:
        return False
    params.append(action_key)
    rowcount = await _execute(
        f"UPDATE propose_actions SET {', '.join(sets)} WHERE action_key = %s", tuple(params)
    )
    return bool(rowcount)


async def list_propose_action_synonyms() -> dict[str, str]:
    rows = await _fetchall("SELECT synonym, action_key FROM propose_action_synonyms")
    return {r["synonym"]: r["action_key"] for r in rows}


async def add_propose_action_synonym(synonym: str, action_key: str) -> None:
    await _execute(
        "INSERT INTO propose_action_synonyms (synonym, action_key) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE action_key = VALUES(action_key)",
        (synonym, action_key),
    )


async def delete_propose_action_synonym(synonym: str) -> bool:
    rowcount = await _execute("DELETE FROM propose_action_synonyms WHERE synonym = %s", (synonym,))
    return bool(rowcount)


async def create_or_replace_propose_request(
    chat_id: int, message_id: int, action_key: str, from_user_id: int, to_user_id: int
) -> int:
    """Новое предложение той же паре по тому же действию перезаписывает старое
    (как create_rel2_request) — старая клавиатура станет недействительной, если
    по ней всё же нажмут (get_propose_request вернёт None)."""
    await _execute(
        "DELETE FROM propose_requests WHERE chat_id = %s AND action_key = %s "
        "AND from_user_id = %s AND to_user_id = %s",
        (chat_id, action_key, from_user_id, to_user_id),
    )
    return await _execute(
        "INSERT INTO propose_requests (chat_id, message_id, action_key, from_user_id, to_user_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, message_id, action_key, from_user_id, to_user_id),
    )


async def set_propose_request_message_id(request_id: int, message_id: int) -> None:
    await _execute("UPDATE propose_requests SET message_id = %s WHERE id = %s", (message_id, request_id))


async def get_propose_request(request_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, chat_id, message_id, action_key, from_user_id, to_user_id, created_at "
        "FROM propose_requests WHERE id = %s",
        (request_id,),
    )


async def delete_propose_request(request_id: int) -> bool:
    rowcount = await _execute("DELETE FROM propose_requests WHERE id = %s", (request_id,))
    return bool(rowcount)


async def list_expired_propose_requests(now: datetime) -> list[dict]:
    return await _fetchall(
        "SELECT r.id, r.chat_id, r.message_id, r.action_key, r.from_user_id, r.to_user_id, r.created_at "
        "FROM propose_requests r JOIN propose_actions a ON a.action_key = r.action_key "
        "WHERE TIMESTAMPDIFF(SECOND, r.created_at, %s) > a.timeout_seconds",
        (now,),
    )


async def check_and_touch_propose_cooldown(
    chat_id: int, action_key: str, from_user_id: int, to_user_id: int, cooldown_seconds: int
) -> Optional[int]:
    row = await _fetchone(
        "SELECT last_at FROM propose_cooldowns WHERE chat_id = %s AND action_key = %s "
        "AND from_user_id = %s AND to_user_id = %s",
        (chat_id, action_key, from_user_id, to_user_id),
    )
    if row:
        elapsed = (datetime.utcnow() - row["last_at"]).total_seconds()
        if elapsed < cooldown_seconds:
            return int(cooldown_seconds - elapsed)
    await _execute(
        "INSERT INTO propose_cooldowns (chat_id, action_key, from_user_id, to_user_id, last_at) "
        "VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE last_at = VALUES(last_at)",
        (chat_id, action_key, from_user_id, to_user_id, datetime.utcnow()),
    )
    return None
```

`datetime` уже импортирован в `db.py` на уровне модуля (используется другими функциями, например `set_admin`/дуэли) — дополнительного импорта не требуется.

- [ ] **Step 4: Дефолтный контент + вызовы в `bot.py`**

В `bot.py`, рядом с `_RP_ACTIONS_DEFAULT`/`_RP_ACTION_SYNONYMS_DEFAULT` (`bot.py:6714+`), добавить:

```python
_PROPOSE_ACTION_KEYS_DEFAULT = [
    "romashka", "schelbany", "morozhenoe", "karaoke", "klad", "podushki", "zhelanie",
]

_PROPOSE_ACTION_SYNONYMS_DEFAULT = {
    "погадать на ромашке": "romashka", "ромашка": "romashka", "погадать на любовь": "romashka",
    "дуэль на щелбанчики": "schelbany", "щелбаны": "schelbany", "щелбанчики": "schelbany",
    "забег за мороженым": "morozhenoe", "сбегать за мороженым": "morozhenoe", "мороженое": "morozhenoe",
    "караоке": "karaoke", "спеть дуэтом": "karaoke", "спеть вместе": "karaoke",
    "искать клад": "klad", "клад": "klad", "найти сокровище": "klad",
    "битва подушками": "podushki", "подушками подраться": "podushki", "подушечный бой": "podushki",
    "угадать желание": "zhelanie", "загадать желание": "zhelanie", "желание угадать": "zhelanie",
}

_PROPOSE_PHRASES_DEFAULT = {
    "romashka": {
        "propose": [
            "{actor} срывает ромашку и предлагает {target} погадать: любит — не любит? 🌼",
            "{actor} протягивает {target} ромашку — гадаем на «любит/не любит»? 🌼",
            "У {actor} завалялась одна ромашка для гадания с {target}. Пробуем? 🌼",
            "{actor} зовёт {target} узнать правду через ромашку. Рискнём? 🌼",
            "Судьба ждёт ответа: {actor} предлагает {target} погадать на ромашке 🌼",
        ],
        "agree": [
            "{target} срывает первый лепесток вместе с {actor} — гадание начинается! 🌼",
            "Есть согласие! {actor} и {target} гадают на ромашке прямо сейчас 🌼",
            "Ромашка побеждает — {target} и {actor} приступают к гаданию 🌼",
            "Гадание одобрено: {target} и {actor} по очереди рвут лепестки 🌼",
            "{target} говорит «любопытно» — {actor}, начинайте гадать! 🌼",
        ],
        "decline": [
            "{target} сегодня не в настроении для ромашек — гадание отменяется 🥀",
            "Ромашка так и остаётся целой: {target} отвечает {actor} отказом 🥀",
            "{target} машет рукой: не сегодня, {actor} 🥀",
            "Гадание откладывается — {target} предпочитает не искушать судьбу 🥀",
            "{target} прячет руки за спину и отказывается гадать с {actor} 🥀",
        ],
    },
    "schelbany": {
        "propose": [
            "{actor} вызывает {target} на дуэль щелбанчиков! Готовы подставить лоб? 👉",
            "{actor} разминает пальцы и предлагает {target} сразиться в щелбаны 👉",
            "Лёгкая боль во имя чести: {actor} зовёт {target} на дуэль щелбанчиков 👉",
            "{actor} предлагает {target} решить спор честно — щелбанами! 👉",
            "Кто кого? {actor} вызывает {target} на щелбанную дуэль 👉",
        ],
        "agree": [
            "{target} подставляет лоб — дуэль щелбанчиков с {actor} начинается! 👉",
            "Вызов принят! {target} и {actor} готовятся к щелбанам 👉",
            "{target} соглашается на дуэль — {actor}, цельтесь точнее! 👉",
            "Щелбанная дуэль одобрена: {target} и {actor} встают друг напротив друга 👉",
            "{target} хрустит пальцами в ответ {actor} — дуэль начинается! 👉",
        ],
        "decline": [
            "{target} прикрывает лоб рукой и отказывается от дуэли с {actor} 🙅",
            "Щелбаны отменяются — {target} бережёт лоб от {actor} 🙅",
            "{target} говорит «в другой раз» {actor} 🙅",
            "Дуэль не состоится: {target} предпочитает мир, а не щелбаны 🙅",
            "{target} прячется за спину соседа, лишь бы не дуэлиться с {actor} 🙅",
        ],
    },
    "morozhenoe": {
        "propose": [
            "{actor} предлагает {target} устроить забег до ларька за мороженым! На старт? 🍦",
            "{actor} чувствует зов мороженого и зовёт {target} наперегонки до ларька 🍦",
            "Кто быстрее добежит до ларька? {actor} вызывает {target} на забег за мороженым 🍦",
            "{actor} предлагает {target} размяться — забег за мороженым, проигравший платит 🍦",
            "Жара требует мороженого: {actor} зовёт {target} на забег до ларька 🍦",
        ],
        "agree": [
            "{target} уже завязывает шнурки — забег с {actor} начинается! 🍦",
            "Вызов принят! {target} и {actor} срываются в сторону ларька 🍦",
            "{target} соглашается — на старт, внимание, мороженое! Вместе с {actor} 🍦",
            "Забег одобрен: {target} и {actor} несутся к ларьку наперегонки 🍦",
            "{target} машет рукой «догоняй» {actor} — забег начался! 🍦",
        ],
        "decline": [
            "{target} машет рукой: сегодня не бегается, {actor} 🙅",
            "Забег отменяется — {target} предпочитает остаться на месте 🙅",
            "{target} говорит «лень» в ответ {actor} 🙅",
            "Мороженое подождёт: {target} отказывается от забега с {actor} 🙅",
            "{target} зевает и остаётся сидеть, несмотря на предложение {actor} 🙅",
        ],
    },
    "karaoke": {
        "propose": [
            "{actor} хватает микрофон и зовёт {target} спеть дуэтом караоке! 🎤",
            "{actor} предлагает {target} устроить импровизированный концерт — дуэтом! 🎤",
            "Сцена ждёт: {actor} приглашает {target} спеть вместе караоке 🎤",
            "{actor} включает минусовку и зовёт {target} к микрофону 🎤",
            "Голос требует выхода: {actor} предлагает {target} спеть дуэтом 🎤",
        ],
        "agree": [
            "{target} хватает второй микрофон — дуэт с {actor} начинается! 🎤",
            "Вызов принят! {target} и {actor} выходят на импровизированную сцену 🎤",
            "{target} соглашается подпевать {actor} — концерт начинается! 🎤",
            "Дуэт одобрен: {target} и {actor} готовятся взять высокую ноту 🎤",
            "{target} прочищает горло и кивает {actor} — поехали! 🎤",
        ],
        "decline": [
            "{target} прячет голос и отказывается петь с {actor} 🙅",
            "Караоке отменяется — {target} сегодня не в голосе 🙅",
            "{target} машет рукой: не сегодня, {actor} 🙅",
            "Дуэт не сложился: {target} предпочитает роль зрителя 🙅",
            "{target} мотает головой в ответ на предложение {actor} 🙅",
        ],
    },
    "klad": {
        "propose": [
            "{actor} находит старую карту и зовёт {target} искать клад во дворе! 🗺️",
            "{actor} предлагает {target} отправиться на поиски сокровища прямо во дворе 🗺️",
            "Клад не найдёт себя сам: {actor} зовёт {target} на поиски 🗺️",
            "{actor} берёт лопату и предлагает {target} копать вместе — там точно клад! 🗺️",
            "Приключение зовёт: {actor} приглашает {target} искать сокровище во дворе 🗺️",
        ],
        "agree": [
            "{target} хватает вторую лопату — поиски клада с {actor} начинаются! 🗺️",
            "Экспедиция одобрена: {target} и {actor} отправляются во двор 🗺️",
            "{target} соглашается — карта разворачивается, {actor} готов копать 🗺️",
            "Клад ждёт: {target} и {actor} выходят на поиски сокровища 🗺️",
            "{target} кивает и хватает фонарик — вперёд с {actor}! 🗺️",
        ],
        "decline": [
            "{target} отказывается копать — клад подождёт, {actor} 🙅",
            "Поиски отменяются: {target} сегодня не в настроении для приключений 🙅",
            "{target} машет рукой: пусть клад лежит спокойно, {actor} 🙅",
            "Экспедиция не состоится — {target} предпочитает диван 🙅",
            "{target} прячет лопату подальше от предложения {actor} 🙅",
        ],
    },
    "podushki": {
        "propose": [
            "{actor} хватает подушку и вызывает {target} на битву! 🛏️",
            "{actor} предлагает {target} устроить честный подушечный бой 🛏️",
            "Пух летит в разные стороны: {actor} зовёт {target} на битву подушками 🛏️",
            "{actor} готовит оружие — подушку — и зовёт {target} сразиться 🛏️",
            "Кто победит? {actor} вызывает {target} на подушечную дуэль 🛏️",
        ],
        "agree": [
            "{target} хватает подушку в ответ — битва с {actor} начинается! 🛏️",
            "Вызов принят! {target} и {actor} готовятся к бою 🛏️",
            "{target} соглашается — перья уже летят вместе с {actor} 🛏️",
            "Битва одобрена: {target} и {actor} занимают позиции 🛏️",
            "{target} кивает и заряжает подушку — начали, {actor}! 🛏️",
        ],
        "decline": [
            "{target} откладывает подушку — битва не состоится, {actor} 🙅",
            "Бой отменяется: {target} предпочитает мир 🙅",
            "{target} машет рукой: не сегодня, {actor} 🙅",
            "Подушечная дуэль не сложилась — {target} сдаётся заранее 🙅",
            "{target} прячет подушку под одеяло, лишь бы не драться с {actor} 🙅",
        ],
    },
    "zhelanie": {
        "propose": [
            "{actor} загадывает желание и предлагает {target} угадать его 🎁",
            "{actor} предлагает {target} сыграть в угадай-желание — кто окажется ближе к правде? 🎁",
            "Тайна зовёт: {actor} приглашает {target} угадать желание друг друга 🎁",
            "{actor} готовит подсказку и зовёт {target} попробовать угадать 🎁",
            "{actor} предлагает {target} узнать, кто кого лучше понимает — угадаем желания? 🎁",
        ],
        "agree": [
            "{target} закрывает глаза и соглашается угадывать вместе с {actor} 🎁",
            "Игра одобрена: {target} и {actor} начинают угадывать желания 🎁",
            "{target} кивает — интрига начинается вместе с {actor}! 🎁",
            "Вызов принят! {target} и {actor} пробуют прочитать мысли друг друга 🎁",
            "{target} соглашается — {actor}, загадывайте первым! 🎁",
        ],
        "decline": [
            "{target} качает головой: секреты остаются секретами, {actor} 🙅",
            "Игра отменяется — {target} бережёт свои мысли в тайне 🙅",
            "{target} машет рукой: не сегодня, {actor} 🙅",
            "Угадайка не сложилась: {target} предпочитает молчать 🙅",
            "{target} прячет мысли поглубже, несмотря на предложение {actor} 🙅",
        ],
    },
}
```

В `bot.py` `main()`, сразу после `await db.ensure_self_actions_table()` (`bot.py:21086`), добавить:

```python
    await db.ensure_propose_actions_table()
    await db.ensure_propose_action_synonyms_table()
    await db.ensure_propose_phrases_table()
    await db.ensure_propose_requests_table()
    await db.ensure_propose_cooldowns_table()
```

Сразу после `await db.seed_self_actions_if_empty(_SELF_ACTIONS_DEFAULT)` (`bot.py:21129`), добавить:

```python
    await db.seed_propose_actions_if_empty(_PROPOSE_ACTION_KEYS_DEFAULT)
    await db.seed_propose_action_synonyms_if_empty(_PROPOSE_ACTION_SYNONYMS_DEFAULT)
    await db.seed_propose_phrases_if_empty(_PROPOSE_PHRASES_DEFAULT)
```

- [ ] **Step 5: Проверить, что бот по-прежнему импортируется, и что миграции «привязаны»**

Run: `python -c "import os; os.environ.setdefault('BOT_TOKEN','123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN'); os.environ.setdefault('OWNER_IDS','1'); import bot"`
Expected: без исключений. Если в окружении нет настоящего aiogram/aiomysql — упадёт на импорте пакета ещё до наших правок; в этом случае проверка делается на машине с `.venv`.

Run: `pytest tests/test_migrations_wired.py -v`
Expected: PASS — новые `ensure_propose_*` функции найдены в `db.py` и обнаружены как вызванные (мы их вызвали в `main()` на Step 4).

- [ ] **Step 6: Commit**

```bash
git add db.py bot.py
git commit -m "feat(propose): БД-слой — таблицы, CRUD, сидирование 7 дефолтных действий"
```

---

### Task 2: Матчинг триггера + отправка предложения (бот)

**Files:**
- Modify: `bot.py` (глобальные кэши, `load_caches()` — рядом с блоком RP на `bot.py:580-586`; матчинг и хендлер — новый блок рядом с РП-действиями, после `handle_rp_action`, `bot.py:7004`)
- Create: `tests/test_propose_actions.py`

**Interfaces:**
- Consumes: `db.list_propose_actions`, `db.list_propose_action_synonyms`, `db.check_and_touch_propose_cooldown`, `db.create_or_replace_propose_request` (Task 1); `resolve_command_target` (существует, `bot.py:7884`); `display_name_link` (существует).
- Produces: `PROPOSE_ACTIONS: dict[str, dict]`, `PROPOSE_ACTION_SYNONYMS: dict[str, str]` (глобальные кэши бота, читаются Task 3/6); `_match_propose_action_prefix(text: str) -> Optional[tuple[str, int]]`; `refresh_propose_caches() -> None` (используется Task 4/6); `handle_propose_action(message: Message)` (роутер-хендлер).

- [ ] **Step 1: Написать падающий тест на матчинг триггера**

Создать `tests/test_propose_actions.py`:

```python
"""«Предложить действие» — матчинг триггера и отправка предложения.

Похоже на РП-действия (bot.py:handle_rp_action), но с обязательным префиксом
«предложить» и таблицей ожидания ответа (propose_requests) вместо мгновенного
выполнения.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from types import SimpleNamespace

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


def _make(text, reply_from_id=None):
    replied = None
    if reply_from_id is not None:
        replied = Message(
            message_id=2, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
            from_user=User(id=reply_from_id, is_bot=False, first_name="Партнёр"), text="привет",
        )
    m = Message(
        message_id=3, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=555, is_bot=False, first_name="Инициатор"), text=text,
        reply_to_message=replied,
    )
    sent = []

    async def fake_answer(t, **kwargs):
        sent.append((t, kwargs))
        return SimpleNamespace(message_id=999)  # id отправленного сообщения

    object.__setattr__(m, "answer", fake_answer)
    return m, sent


@pytest.mark.parametrize(
    "text,expected_key,expected_n",
    [
        ("предложить ромашка", "romashka", 2),
        ("предложить погадать на ромашке", "romashka", 4),
        ("предложить дуэль на щелбанчики", "schelbany", 4),
        ("предложить искать клад", "klad", 3),
        ("предложить полить цветы", None, None),  # не из дефолтного списка — не матчится
    ],
)
def test_матчинг_многословных_синонимов(monkeypatch, text, expected_key, expected_n):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {
        "ромашка": "romashka", "погадать на ромашке": "romashka",
        "дуэль на щелбанчики": "schelbany", "искать клад": "klad",
    })
    result = bot_module._match_propose_action_prefix(text)
    if expected_key is None:
        assert result is None
    else:
        assert result == (expected_key, expected_n)


def test_регистр_и_лишние_пробелы_не_мешают(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {"ромашка": "romashka"})
    assert bot_module._match_propose_action_prefix("ПРЕДЛОЖИТЬ   Ромашка") == ("romashka", 2)


def test_без_префикса_предложить_не_матчится(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {"ромашка": "romashka"})
    assert bot_module._match_propose_action_prefix("ромашка") is None


def test_отправка_предложения_по_reply(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["{actor} зовёт {target} гадать на ромашке 🌼"],
                     "agree": ["ok"], "decline": ["no"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {"ромашка": "romashka"})

    async def display_name_link(chat_id, u):
        return getattr(u, "full_name", None) or getattr(u, "first_name", "N")

    async def check_and_touch_propose_cooldown(*a, **k):
        return None

    created = {}
    message_id_updates = {}

    async def create_or_replace_propose_request(chat_id, message_id, action_key, from_user_id, to_user_id):
        created.update(chat_id=chat_id, message_id=message_id, action_key=action_key,
                       from_user_id=from_user_id, to_user_id=to_user_id)
        return 42

    async def set_propose_request_message_id(request_id, message_id):
        message_id_updates.update(request_id=request_id, message_id=message_id)

    monkeypatch.setattr(bot_module, "display_name_link", display_name_link)
    monkeypatch.setattr(bot_module.db, "check_and_touch_propose_cooldown", check_and_touch_propose_cooldown)
    monkeypatch.setattr(bot_module.db, "create_or_replace_propose_request", create_or_replace_propose_request)
    monkeypatch.setattr(bot_module.db, "set_propose_request_message_id", set_propose_request_message_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложить ромашка", reply_from_id=777)
    asyncio.run(bot_module.handle_propose_action(m))

    assert sent, "бот должен был отправить сообщение с предложением"
    text, kwargs = sent[0]
    assert "гадать на ромашке" in text
    kb = kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].callback_data == "propose_yes:42"
    assert kb.inline_keyboard[0][1].callback_data == "propose_no:42"
    assert created == {
        "chat_id": CHAT_ID, "message_id": 0, "action_key": "romashka",
        "from_user_id": 555, "to_user_id": 777,
    }
    assert message_id_updates == {"request_id": 42, "message_id": 999}


def test_самому_себе_нельзя(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x {actor} {target}"], "agree": ["a"], "decline": ["d"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {"ромашка": "romashka"})
    m, sent = _make("предложить ромашка", reply_from_id=555)  # reply на самого себя
    asyncio.run(bot_module.handle_propose_action(m))
    assert sent and "сам" in sent[0][0].casefold()


def test_кулдаун_блокирует_повторное_предложение(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x {actor} {target}"], "agree": ["a"], "decline": ["d"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {"ромашка": "romashka"})

    async def check_and_touch_propose_cooldown(*a, **k):
        return 42  # 42 секунды ещё ждать

    monkeypatch.setattr(bot_module.db, "check_and_touch_propose_cooldown", check_and_touch_propose_cooldown)
    m, sent = _make("предложить ромашка", reply_from_id=777)
    asyncio.run(bot_module.handle_propose_action(m))
    assert sent and "42" in sent[0][0]


def test_неизвестное_действие_пропускается(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {})
    monkeypatch.setattr(bot_module, "PROPOSE_ACTION_SYNONYMS", {})
    m, sent = _make("предложить ромашка", reply_from_id=777)
    with pytest.raises(SkipHandler):
        asyncio.run(bot_module.handle_propose_action(m))
    assert not sent
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_propose_actions.py -v`
Expected: FAIL/ERROR — `bot_module._match_propose_action_prefix`/`bot_module.handle_propose_action` не существуют, `PROPOSE_ACTIONS`/`PROPOSE_ACTION_SYNONYMS` не существуют.

- [ ] **Step 3: Добавить глобальные кэши и загрузку в `load_caches()`**

В `bot.py`, рядом с объявлением `RP_ACTIONS = {}`/`RP_ACTION_SYNONYMS = {}` (там же, где эти глобальные dict впервые объявлены на уровне модуля — до `load_caches()`), добавить:

```python
PROPOSE_ACTIONS: dict[str, dict] = {}
PROPOSE_ACTION_SYNONYMS: dict[str, str] = {}
_PROPOSE_ACTION_ALL_KEYS: list[str] = []
```

В `load_caches()`, сразу после блока (`bot.py:584-586`):
```python
    rp_synonyms = await db.list_rp_action_synonyms()
    RP_ACTION_SYNONYMS.clear()
    RP_ACTION_SYNONYMS.update(rp_synonyms or _RP_ACTION_SYNONYMS_DEFAULT)
```
добавить:
```python

    propose_actions = await db.list_propose_actions(active_only=True)
    PROPOSE_ACTIONS.clear()
    PROPOSE_ACTIONS.update(propose_actions)

    propose_synonyms = await db.list_propose_action_synonyms()
    PROPOSE_ACTION_SYNONYMS.clear()
    PROPOSE_ACTION_SYNONYMS.update(propose_synonyms)

    global _PROPOSE_ACTION_ALL_KEYS
    _PROPOSE_ACTION_ALL_KEYS = sorted(
        PROPOSE_ACTION_SYNONYMS.keys(), key=lambda k: len(k.split()), reverse=True,
    )
```
(добавить `_PROPOSE_ACTION_ALL_KEYS` в список `global`-имён в начале `load_caches()`, рядом с `global HELP_RP_ACTIONS_TEXT, _RP_ACTION_ALL_KEYS` на `bot.py:572`.)

- [ ] **Step 4: Добавить матчинг, `refresh_propose_caches()` и хендлер**

Сразу после конца `handle_rp_action` (после `bot.py:7004`, перед комментарием `# Управление РП-действиями через бота`), добавить:

```python
def _match_propose_action_prefix(text: Optional[str]) -> Optional[tuple[str, int]]:
    """«предложить <синоним>» — синонимы бывают многословными («полить цветы»,
    «дуэль на щелбанчики»), поэтому проверяются от самых длинных к самым
    коротким (см. _match_rp_action_prefix). Возвращает (action_key, n), где n —
    число слов в «предложить» + синониме (для resolve_command_target)."""
    if not text:
        return None
    words = text.strip().casefold().split()
    if not words or words[0] != "предложить":
        return None
    rest = words[1:]
    for synonym in _PROPOSE_ACTION_ALL_KEYS:
        syn_words = synonym.split()
        n = len(syn_words)
        if len(rest) >= n and rest[:n] == syn_words:
            return PROPOSE_ACTION_SYNONYMS[synonym], n + 1
    return None


def _is_propose_action_command(t: Optional[str]) -> bool:
    return _match_propose_action_prefix(t) is not None


async def refresh_propose_caches() -> None:
    """Лёгкий рефреш кэшей «Предложить действие» — вызывается после правок
    через личку/сайт и из panel_action_reload_loop, без полного load_caches()."""
    global _PROPOSE_ACTION_ALL_KEYS

    propose_actions = await db.list_propose_actions(active_only=True)
    PROPOSE_ACTIONS.clear()
    PROPOSE_ACTIONS.update(propose_actions)

    propose_synonyms = await db.list_propose_action_synonyms()
    PROPOSE_ACTION_SYNONYMS.clear()
    PROPOSE_ACTION_SYNONYMS.update(propose_synonyms)

    _PROPOSE_ACTION_ALL_KEYS = sorted(
        PROPOSE_ACTION_SYNONYMS.keys(), key=lambda k: len(k.split()), reverse=True,
    )


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(_is_propose_action_command),
)
async def handle_propose_action(message: Message):
    action_key, n = _match_propose_action_prefix(message.text)
    if action_key not in PROPOSE_ACTIONS:
        raise SkipHandler  # неизвестно или выключено — молча, как выключенные РП

    target, _remaining = await resolve_command_target(message, trigger_words=n)
    if target is None and message.reply_to_message:
        target = message.reply_to_message.from_user
    if target is None:
        await message.reply(
            "Укажите, кому предлагаете: ответьте (reply) на сообщение или укажите @username."
        )
        return
    if target.id is None:
        await message.reply(
            f"Не удалось найти @{html.escape(target.username or '')} — бот его ещё не видел в этом чате. "
            "Попробуйте ответом на его сообщение, если оно есть."
        )
        return
    if target.id == message.from_user.id:
        await message.reply("Предложить это самому себе? Пожалуй, воздержимся 🙂")
        return
    if target.is_bot:
        await message.reply("Боту такое не предложишь 🙂")
        return

    wait_seconds = await db.check_and_touch_propose_cooldown(
        message.chat.id, action_key, message.from_user.id, target.id,
        PROPOSE_ACTIONS[action_key]["cooldown_seconds"],
    )
    if wait_seconds is not None:
        await message.reply(f"Подождите ещё {wait_seconds}с — не так часто ⏳")
        return

    actor_name = await display_name_link(message.chat.id, message.from_user)
    target_name = await display_name_link(message.chat.id, target)
    phrase = random.choice(PROPOSE_ACTIONS[action_key]["propose"]).format(actor=actor_name, target=target_name)

    # request_id нужен ДО отправки (чтобы сразу вшить его в callback_data), а
    # настоящий message_id известен только ПОСЛЕ отправки (Telegram отдаёт его
    # только в ответе) — поэтому строка сперва создаётся с message_id=0 и
    # дописывается сразу после отправки, без повторной правки клавиатуры.
    request_id = await db.create_or_replace_propose_request(
        message.chat.id, 0, action_key, message.from_user.id, target.id,
    )
    sent = await message.answer(
        phrase,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data=f"propose_yes:{request_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"propose_no:{request_id}"),
        ]]),
    )
    await db.set_propose_request_message_id(request_id, sent.message_id)
    await db.add_log(f"propose_{action_key}", chat_id=message.chat.id, actor_id=message.from_user.id, target_id=target.id)
```

- [ ] **Step 5: Прогнать тесты — должны пройти**

Run: `pytest tests/test_propose_actions.py -v`
Expected: PASS (9 тестов), либо `SKIPPED` целиком без настоящего aiogram.

- [ ] **Step 6: Прогнать весь набор, чтобы убедиться, что РП-действия не сломаны**

Run: `pytest tests/ -k "rp or propose" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bot.py tests/test_propose_actions.py
git commit -m "feat(propose): матчинг триггера и отправка предложения с Да/Нет"
```

---

### Task 3: Callback Да/Нет + просрочка предложений

**Files:**
- Modify: `bot.py` (новый блок рядом с `_role_proposal_decision`, после `bot.py:7004`+добавок Task 2 — конкретно после `handle_propose_action`)
- Modify: `bot.py` `main()` — добавить `asyncio.create_task(propose_expiry_loop())` (делается в Task 6, не здесь)
- Test: `tests/test_propose_actions.py` (дополнить)

**Interfaces:**
- Consumes: `db.get_propose_request`, `db.delete_propose_request`, `db.list_expired_propose_requests` (Task 1); `PROPOSE_ACTIONS` (Task 2); `display_name_by_id(chat_id: int, user_id: int) -> str` (существует, `bot.py:1112-1129` — в отличие от `display_name_link`, не требует живого `User`-объекта, только id, что и есть в строке `propose_requests`).
- Produces: `propose_yes_callback`/`propose_no_callback` (роутеры `F.data.startswith("propose_yes:")`/`"propose_no:"`); `_process_expired_propose_requests() -> int` (используется Task 6 из `propose_expiry_loop`); `propose_expiry_loop() -> None` (тонкая обёртка, сама не тестируется — см. Global Constraints про `while True`-лупы).

- [ ] **Step 1: Написать падающий тест на callback и на просрочку**

Добавить в конец `tests/test_propose_actions.py`:

```python
from aiogram.types import CallbackQuery  # noqa: E402


def _make_callback(data, from_user_id, chat_id=CHAT_ID, message_id=3):
    msg = Message(
        message_id=message_id, date=datetime.now(), chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=1, is_bot=True, first_name="Бот"), text="{actor} зовёт {target}...",
    )
    edits = []

    async def fake_edit_text(text, **kwargs):
        edits.append(text)

    object.__setattr__(msg, "edit_text", fake_edit_text)

    cb = CallbackQuery(
        id="1", from_user=User(id=from_user_id, is_bot=False, first_name="U"),
        chat_instance="ci", data=data, message=msg,
    )
    answers = []

    async def fake_answer(text=None, **kwargs):
        answers.append((text, kwargs.get("show_alert", False)))

    object.__setattr__(cb, "answer", fake_answer)
    return cb, edits, answers


def _propose_request_row(**overrides):
    row = {
        "id": 42, "chat_id": CHAT_ID, "message_id": 3, "action_key": "romashka",
        "from_user_id": 555, "to_user_id": 777, "created_at": datetime.utcnow(),
    }
    row.update(overrides)
    return row


def test_согласие_редактирует_сообщение_и_чистит_запись(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x"], "agree": ["Есть контакт! {target} и {actor} гадают 🌼"],
                     "decline": ["no"], "cooldown_seconds": 300, "timeout_seconds": 120},
    })

    async def get_propose_request(request_id):
        assert request_id == 42
        return _propose_request_row()

    deleted = {}

    async def delete_propose_request(request_id):
        deleted["id"] = request_id
        return True

    async def display_name_by_id(chat_id, user_id):
        return "N"

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", delete_propose_request)
    monkeypatch.setattr(bot_module, "display_name_by_id", display_name_by_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    cb, edits, answers = _make_callback("propose_yes:42", from_user_id=777)
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert edits and "Есть контакт" in edits[0]
    assert deleted == {"id": 42}
    assert answers


def test_отказ_редактирует_сообщение(monkeypatch):
    monkeypatch.setattr(bot_module, "PROPOSE_ACTIONS", {
        "romashka": {"propose": ["x"], "agree": ["ok"], "decline": ["{target} отказывает {actor} 🥀"],
                     "cooldown_seconds": 300, "timeout_seconds": 120},
    })

    async def get_propose_request(request_id):
        return _propose_request_row()

    async def display_name_by_id(chat_id, user_id):
        return "N"

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", lambda request_id: asyncio.sleep(0, result=True))
    monkeypatch.setattr(bot_module, "display_name_by_id", display_name_by_id)
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    cb, edits, answers = _make_callback("propose_no:42", from_user_id=777)
    asyncio.run(bot_module.propose_no_callback(cb))

    assert edits and "отказывает" in edits[0]


def test_чужой_клик_не_меняет_состояние(monkeypatch):
    async def get_propose_request(request_id):
        return _propose_request_row()  # to_user_id=777

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)

    cb, edits, answers = _make_callback("propose_yes:42", from_user_id=999)  # не 777
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert not edits
    assert answers and answers[0][1] is True  # show_alert=True
    assert "не вам" in answers[0][0]


def test_несуществующая_или_протухшая_заявка(monkeypatch):
    async def get_propose_request(request_id):
        return None

    monkeypatch.setattr(bot_module.db, "get_propose_request", get_propose_request)

    cb, edits, answers = _make_callback("propose_yes:999", from_user_id=777)
    asyncio.run(bot_module.propose_yes_callback(cb))

    assert not edits
    assert answers and "не активно" in answers[0][0].casefold()


def test_просроченный_запрос_обрабатывается_фоновым_лупом(monkeypatch):
    from datetime import timedelta

    processed = []

    async def list_expired_propose_requests(now):
        return [{
            "id": 42, "chat_id": CHAT_ID, "message_id": 3, "action_key": "romashka",
            "from_user_id": 555, "to_user_id": 777,
            "created_at": now - timedelta(seconds=999),
        }]

    async def delete_propose_request(request_id):
        processed.append(request_id)
        return True

    class FakeBot:
        def __init__(self):
            self.edits = []

        async def edit_message_text(self, chat_id, message_id, text, **kwargs):
            self.edits.append((chat_id, message_id, text))

    fake_bot = FakeBot()
    monkeypatch.setattr(bot_module, "bot", fake_bot)
    monkeypatch.setattr(bot_module.db, "list_expired_propose_requests", list_expired_propose_requests)
    monkeypatch.setattr(bot_module.db, "delete_propose_request", delete_propose_request)

    n = asyncio.run(bot_module._process_expired_propose_requests())

    assert n == 1
    assert processed == [42]
    assert fake_bot.edits and "устарело" in fake_bot.edits[0][2].casefold()
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `pytest tests/test_propose_actions.py -v`
Expected: FAIL/ERROR — `propose_yes_callback`/`propose_no_callback`/`_process_expired_propose_requests` не существуют.

- [ ] **Step 3: Реализовать callback-хендлеры и просрочку**

Сразу после `handle_propose_action` (добавленного в Task 2), добавить:

```python
async def _propose_decision(callback: CallbackQuery, agree: bool) -> None:
    """Общая логика Да/Нет — по образцу _role_proposal_decision: ответ
    отображается изменением того же сообщения, без отдельного текста."""
    try:
        request_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer()
        return

    req = await db.get_propose_request(request_id)
    if req is None:
        # Не трогаем клавиатуру: если запись уже удалена (отвечено/протухло/
        # перезаписано новым предложением), повторный клик так и будет получать
        # тот же alert — этого достаточно, отдельная правка сообщения не нужна.
        await callback.answer("Предложение больше не активно.", show_alert=True)
        return

    if callback.from_user.id != req["to_user_id"]:
        await callback.answer("Это предложение адресовано не вам", show_alert=True)
        return

    action_key = req["action_key"]
    action = PROPOSE_ACTIONS.get(action_key)
    kind = "agree" if agree else "decline"
    phrases = action[kind] if action else ["Готово."]

    # В момент клика под рукой только id (строка propose_requests), а не живой
    # aiogram User — display_name_link ждёт объект с .full_name и упадёт;
    # display_name_by_id как раз для этого случая ("объекта User нет под рукой").
    actor_name = await display_name_by_id(req["chat_id"], req["from_user_id"])
    target_name = await display_name_by_id(req["chat_id"], req["to_user_id"])
    phrase = random.choice(phrases).format(actor=actor_name, target=target_name)

    try:
        await callback.message.edit_text(phrase, reply_markup=None)
    except TelegramBadRequest:
        pass
    await db.delete_propose_request(request_id)
    await db.add_log(
        f"propose_{action_key}_{kind}", chat_id=req["chat_id"],
        actor_id=req["from_user_id"], target_id=req["to_user_id"],
    )
    await callback.answer("Готово ✅" if agree else "Отклонено")


@router.callback_query(F.data.startswith("propose_yes:"))
async def propose_yes_callback(callback: CallbackQuery):
    await _propose_decision(callback, agree=True)


@router.callback_query(F.data.startswith("propose_no:"))
async def propose_no_callback(callback: CallbackQuery):
    await _propose_decision(callback, agree=False)


async def _process_expired_propose_requests() -> int:
    """Одна проверка просроченных предложений — вызывается из
    propose_expiry_loop (Task 6) и напрямую тестами. Возвращает число
    обработанных строк."""
    rows = await db.list_expired_propose_requests(datetime.utcnow())
    for row in rows:
        try:
            await bot.edit_message_text(
                chat_id=row["chat_id"], message_id=row["message_id"],
                text="⌛ Предложение устарело.",
            )
        except TelegramBadRequest:
            pass
        except Exception:
            logger.exception("propose_expiry: не удалось отредактировать сообщение %s", row["id"])
        await db.delete_propose_request(row["id"])
    return len(rows)


async def propose_expiry_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await _process_expired_propose_requests()
        except Exception:
            logger.exception("propose_expiry_loop: ошибка обработки просрочки")
```

`SimpleNamespace`, `TelegramBadRequest`, `logger`, `datetime` уже импортированы в `bot.py` на уровне модуля.

- [ ] **Step 4: Прогнать тесты — должны пройти**

Run: `pytest tests/test_propose_actions.py -v`
Expected: PASS (14 тестов), либо `SKIPPED` целиком без настоящего aiogram.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_propose_actions.py
git commit -m "feat(propose): callback Да/Нет + просрочка неотвеченных предложений"
```

---

### Task 4: Управление через бота (личка) + права + хелп

**Files:**
- Modify: `bot.py` (COMMAND_REGISTRY — после `bot.py:832`; новый блок команд — после `refresh_propose_caches`/callback-хендлеров, добавленных в Task 2/3)
- Modify: `help_texts.py` (новый ключ `"propose"` в `subsections` раздела `"rp"`, `help_texts.py:21-87`)
- Create: `tests/test_propose_admin_commands.py`

**Interfaces:**
- Consumes: весь CRUD из Task 1 (`db.add_propose_phrase` и т.д.), `refresh_propose_caches()` (Task 2), `has_level`/`required_level`/`get_level`/`level_name` (существуют).
- Produces: `COMMAND_REGISTRY["propose_manage"]`; `PROPOSE_ADMIN_HELP`; `propose_admin_command(message: Message)` (роутер, триггер — первое слово «предложения» в личке).

- [ ] **Step 1: Написать падающий тест на команды**

Создать `tests/test_propose_admin_commands.py`:

```python
"""Управление действиями «Предложить» текстовыми командами в личке боту —
по образцу rp_admin_command (bot.py)."""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from datetime import datetime

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

PRIV_CHAT = 555


def _make(text, user_id=555):
    m = Message(
        message_id=1, date=datetime.now(), chat=Chat(id=PRIV_CHAT, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Админ"), text=text,
    )
    sent = []

    async def fake_answer(t, **kwargs):
        sent.append(t)

    async def fake_reply(t, **kwargs):
        sent.append(t)

    object.__setattr__(m, "answer", fake_answer)
    object.__setattr__(m, "reply", fake_reply)
    return m, sent


def _grant_senior(monkeypatch, user_id=555):
    monkeypatch.setattr(bot_module, "admin_levels", {user_id: bot_module.LEVEL_SENIOR})


def test_без_прав_молчит_если_не_админ(monkeypatch):
    monkeypatch.setattr(bot_module, "admin_levels", {})
    m, sent = _make("предложения список", user_id=999)
    asyncio.run(bot_module.propose_admin_command(m))
    assert not sent


def test_без_прав_объясняет_если_админ_но_ниже_уровня(monkeypatch):
    monkeypatch.setattr(bot_module, "admin_levels", {555: bot_module.LEVEL_MODERATOR})
    m, sent = _make("предложения список")
    asyncio.run(bot_module.propose_admin_command(m))
    assert sent and "Старший администратор" in sent[0]


def test_добавить_создаёт_действие_и_первую_фразу(monkeypatch):
    _grant_senior(monkeypatch)
    created = {}

    async def add_propose_phrase(action_key, kind, phrase):
        created.update(action_key=action_key, kind=kind, phrase=phrase)
        return 1

    monkeypatch.setattr(bot_module.db, "add_propose_phrase", add_propose_phrase)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения добавить турнир | {actor} вызывает {target} на турнир!")
    asyncio.run(bot_module.propose_admin_command(m))

    assert created == {"action_key": "турнир", "kind": "propose",
                        "phrase": "{actor} вызывает {target} на турнир!"}
    assert sent and "Фраза добавлена" in sent[0]


def test_фраза_добавляет_вид_согласие(monkeypatch):
    _grant_senior(monkeypatch)
    created = {}

    async def add_propose_phrase(action_key, kind, phrase):
        created.update(action_key=action_key, kind=kind, phrase=phrase)
        return 2

    monkeypatch.setattr(bot_module.db, "add_propose_phrase", add_propose_phrase)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения фраза турнир согласие | Есть контакт!")
    asyncio.run(bot_module.propose_admin_command(m))

    assert created == {"action_key": "турнир", "kind": "agree", "phrase": "Есть контакт!"}


def test_вкл_выкл(monkeypatch):
    _grant_senior(monkeypatch)
    calls = []

    async def set_propose_action_active(action_key, is_active):
        calls.append((action_key, is_active))
        return 1

    monkeypatch.setattr(bot_module.db, "set_propose_action_active", set_propose_action_active)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, _ = _make("предложения выкл романшка")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls == [("романшка", False)]


def test_кулдаун_и_таймаут(monkeypatch):
    """Команда меняет только одно из двух полей за раз (db.set_propose_action_settings
    делает частичный UPDATE) — обработчик не должен читать «текущее» значение
    второго поля из кэша, поэтому оба вызова проверяются независимо."""
    _grant_senior(monkeypatch)
    calls = []

    async def set_propose_action_settings(action_key, cooldown_seconds=None, timeout_seconds=None):
        calls.append((action_key, cooldown_seconds, timeout_seconds))
        return True

    monkeypatch.setattr(bot_module.db, "set_propose_action_settings", set_propose_action_settings)
    monkeypatch.setattr(bot_module, "refresh_propose_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr(bot_module.db, "add_log", lambda *a, **k: asyncio.sleep(0))

    m, sent = _make("предложения кулдаун romashka 600")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls[-1] == ("romashka", 600, None)

    m, sent = _make("предложения таймаут romashka 60")
    asyncio.run(bot_module.propose_admin_command(m))
    assert calls[-1] == ("romashka", None, 60)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_propose_admin_commands.py -v`
Expected: FAIL/ERROR — `propose_admin_command` не существует, `COMMAND_REGISTRY["propose_manage"]` не найден.

- [ ] **Step 3: Добавить запись в `COMMAND_REGISTRY`**

В `bot.py`, сразу после `"self_manage"` (`bot.py:832`):

```python
    "propose_manage":  {"phrase": "предложения (в личке боту, текстом) / карточка «Предложения» в админ-панели", "category": "РП", "level": LEVEL_SENIOR},
```

- [ ] **Step 4: Добавить хендлер команд**

Сразу после `propose_expiry_loop` (добавленного в Task 3), добавить:

```python
# ----------------------------------------------------------------------------
# Управление действиями «Предложить» через бота (в личке) — по образцу
# rp_admin_command. Каждая мутирующая команда сразу вызывает
# refresh_propose_caches(), чтобы новое действие/фраза/синоним заработали в
# чатах немедленно.
# ----------------------------------------------------------------------------

_PROPOSE_KIND_ALIASES = {"предложение": "propose", "согласие": "agree", "отказ": "decline"}

PROPOSE_ADMIN_HELP = (
    "🛠 <b>Управление «Предложить действие»</b> (только в личке боту)\n"
    + DIVIDER +
    "<code>предложения добавить ключ | фраза-предложения</code>\n"
    "Создаёт действие (если такого ключа ещё не было) и его первую фразу «предложение». "
    "В фразе можно использовать <code>{actor}</code> и <code>{target}</code>.\n\n"
    "<code>предложения фраза ключ вид | фраза</code>\n"
    "Добавляет ещё вариант фразы к существующему действию. вид — предложение/согласие/отказ.\n"
    "Пример: <code>предложения фраза ромашка согласие | Есть контакт! {target} и {actor} гадают 🌼</code>\n\n"
    "<code>предложения синоним синоним | ключ</code> — добавляет синоним-триггер.\n"
    "<code>предложения список</code> — все действия, кулдаун/таймаут, число фраз.\n"
    "<code>предложения удалить_фраза id</code> / <code>предложения удалить_синоним синоним</code>\n"
    "<code>предложения вкл ключ</code> / <code>предложения выкл ключ</code>\n"
    "<code>предложения кулдаун ключ секунды</code> / <code>предложения таймаут ключ секунды</code>\n"
)


@router.message(
    F.chat.type == "private",
    F.text.func(lambda t: bool(t) and t.strip().casefold().split()[0] == "предложения"),
)
async def propose_admin_command(message: Message):
    # Важно: и «нет сообщения об отказе» (обычный пользователь — не спалить
    # само существование команды), и «есть сообщение об отказе» (админ ниже
    # нужного уровня) — оба случая должны ОСТАНОВИТЬ выполнение, поэтому
    # return в обеих ветках, а не только когда есть текст отказа.
    if not has_level(message.from_user.id, required_level("propose_manage")):
        if get_level(message.from_user.id) > 0:
            await message.reply(
                f"⛔ Команда доступна только с уровнем «{level_name(required_level('propose_manage'))}» и выше."
            )
        return

    tokens = message.text.strip().split(maxsplit=2)
    sub = tokens[1].casefold() if len(tokens) >= 2 else ""
    rest = tokens[2] if len(tokens) >= 3 else ""

    if not sub or sub in {"помощь", "хелп", "help"}:
        await message.answer(PROPOSE_ADMIN_HELP)
        return

    if sub == "добавить":
        key_part, sep, phrase_part = rest.partition("|")
        action_key = key_part.strip().casefold()
        phrase = phrase_part.strip()
        if not sep or not action_key or not phrase:
            await message.reply(
                "Формат: <code>предложения добавить ключ | фраза</code>\n"
                "Пример: <code>предложения добавить турнир | {actor} вызывает {target} на турнир!</code>"
            )
            return
        await db.add_propose_phrase(action_key, "propose", phrase)
        await refresh_propose_caches()
        await db.add_log("propose_phrase_added", actor_id=message.from_user.id, details=f"{action_key}: {phrase}")
        await message.answer(f"✅ Фраза добавлена (действие «{html.escape(action_key)}»).")
        return

    if sub == "фраза":
        head, sep, phrase_part = rest.partition("|")
        head_tokens = head.split()
        phrase = phrase_part.strip()
        if not sep or len(head_tokens) != 2 or not phrase:
            await message.reply(
                "Формат: <code>предложения фраза ключ вид | фраза</code> "
                "(вид — предложение/согласие/отказ)\n"
                "Пример: <code>предложения фраза ромашка согласие | Есть контакт! 🌼</code>"
            )
            return
        action_key, kind_word = head_tokens[0].casefold(), head_tokens[1].casefold()
        kind = _PROPOSE_KIND_ALIASES.get(kind_word)
        if kind is None:
            await message.reply("Вид должен быть один из: предложение, согласие, отказ.")
            return
        await db.add_propose_phrase(action_key, kind, phrase)
        await refresh_propose_caches()
        await db.add_log("propose_phrase_added", actor_id=message.from_user.id, details=f"{action_key}/{kind}: {phrase}")
        await message.answer(f"✅ Фраза добавлена (действие «{html.escape(action_key)}», вид «{kind_word}»).")
        return

    if sub == "синоним":
        syn_part, sep, key_part = rest.partition("|")
        synonym = syn_part.strip().casefold()
        action_key = key_part.strip().casefold()
        if not sep or not synonym or not action_key:
            await message.reply(
                "Формат: <code>предложения синоним синоним | ключ</code>\n"
                "Пример: <code>предложения синоним погадать на ромашке | romashka</code>"
            )
            return
        await db.add_propose_action_synonym(synonym, action_key)
        await refresh_propose_caches()
        await db.add_log("propose_synonym_added", actor_id=message.from_user.id, details=f"{synonym} -> {action_key}")
        await message.answer(f"✅ Синоним «{html.escape(synonym)}» → «{html.escape(action_key)}» добавлен.")
        return

    if sub == "список":
        rows = await db.list_propose_actions_rows()
        if not rows:
            await message.answer("Действий пока нет.")
            return
        lines = ["🎲 <b>Предложить действие</b>", DIVIDER]
        for r in rows:
            status = "✅" if r["is_active"] else "🚫"
            lines.append(
                f"{status} <b>{html.escape(r['action_key'])}</b> — "
                f"кулдаун {r['cooldown_seconds']}с, таймаут {r['timeout_seconds']}с"
            )
        await message.answer("\n".join(lines))
        return

    if sub == "удалить_фраза":
        try:
            phrase_id = int(rest.strip())
        except ValueError:
            await message.reply("Формат: <code>предложения удалить_фраза id</code>")
            return
        if not await db.delete_propose_phrase(phrase_id):
            await message.answer(f"Фраза с id {phrase_id} не найдена.")
            return
        await refresh_propose_caches()
        await db.add_log("propose_phrase_deleted", actor_id=message.from_user.id, details=str(phrase_id))
        await message.answer(f"🗑 Фраза #{phrase_id} удалена.")
        return

    if sub == "удалить_синоним":
        synonym = rest.strip().casefold()
        if not synonym or not await db.delete_propose_action_synonym(synonym):
            await message.answer(f"Синоним «{html.escape(synonym)}» не найден.")
            return
        await refresh_propose_caches()
        await db.add_log("propose_synonym_deleted", actor_id=message.from_user.id, details=synonym)
        await message.answer(f"🗑 Синоним «{html.escape(synonym)}» удалён.")
        return

    if sub in {"вкл", "выкл"}:
        action_key = rest.strip().casefold()
        if not action_key:
            await message.reply(f"Формат: <code>предложения {sub} ключ</code>")
            return
        is_active = sub == "вкл"
        changed = await db.set_propose_action_active(action_key, is_active)
        if not changed:
            await message.answer(f"Действие «{html.escape(action_key)}» не найдено.")
            return
        await refresh_propose_caches()
        await db.add_log(
            "propose_action_toggled", actor_id=message.from_user.id,
            details=f"{action_key}: {'on' if is_active else 'off'}",
        )
        state_text = "включено ✅" if is_active else "выключено 🚫"
        await message.answer(f"Действие «{html.escape(action_key)}» {state_text}.")
        return

    if sub in {"кулдаун", "таймаут"}:
        parts = rest.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await message.reply(f"Формат: <code>предложения {sub} ключ секунды</code>")
            return
        action_key, seconds = parts[0].casefold(), int(parts[1])
        kwargs = {"cooldown_seconds": seconds} if sub == "кулдаун" else {"timeout_seconds": seconds}
        if not await db.set_propose_action_settings(action_key, **kwargs):
            await message.answer(f"Действие «{html.escape(action_key)}» не найдено.")
            return
        await refresh_propose_caches()
        await db.add_log(f"propose_{sub}_set", actor_id=message.from_user.id, details=f"{action_key}: {seconds}")
        await message.answer(f"✅ {sub.capitalize()} действия «{html.escape(action_key)}» — {seconds}с.")
        return

    await message.reply(PROPOSE_ADMIN_HELP)
```

- [ ] **Step 5: Обновить хелп**

В `help_texts.py`, `subsections` раздела `"rp"` — это `dict` с именованными ключами (`marriage`, `relations`, `actions`, `self`, `shipping`, `help_texts.py:21-86`), не список. Добавить новый ключ `"propose"` сразу после `"shipping"` (после закрывающей `},` подраздела `shipping`, строка 86, перед закрывающей `},` самого `subsections` на строке 87):

```python
                "propose": {
                    "title": "🎲 Предложения",
                    "text": (
                        "Предложите другому участнику сделать что-то весёлое: "
                        "<code>предложить &lt;действие&gt;</code> (ответом на его сообщение или с @username). "
                        "Например: «предложить погадать на ромашке», «предложить дуэль на щелбанчики». "
                        "Бот покажет адресату кнопки Да/Нет.\n\n"
                        "Список действий и все тексты можно посмотреть и поменять на сайте (карточка "
                        "«Предложения» рядом с РП-действиями) — для этого нужен уровень «Старший "
                        "администратор» или тот, что назначил владелец во вкладке «Дерево команд»."
                    ),
                },
```

- [ ] **Step 6: Прогнать тесты — должны пройти**

Run: `pytest tests/test_propose_admin_commands.py -v`
Expected: PASS (7 тестов), либо `SKIPPED` целиком без настоящего aiogram.

Run: `pytest tests/test_help_texts_accuracy.py -v`
Expected: PASS — существующие тесты не должны сломаться на новом подразделе (это просто добавленный текст, не меняющий формат остальных).

- [ ] **Step 7: Commit**

```bash
git add bot.py help_texts.py tests/test_propose_admin_commands.py
git commit -m "feat(propose): управление через бота (личка) + права через Дерево команд + хелп"
```

---

### Task 5: Панель — управление действиями (backend)

**Files:**
- Modify: `webpanel/app.py` (новые эндпоинты, рядом с `/api/action-sets/{kind}`, после `bot.py`-эквивалента — конкретно после блока `ACTION_SETS`/`api_action_set`, `webpanel/app.py:1341`)
- Create: `tests/test_panel_propose_actions.py`

**Interfaces:**
- Consumes: весь CRUD из Task 1; `roles.load()`, `db.list_command_levels()` (существуют); `PanelUser.tg_user_id`/`is_owner` (существует, `webpanel/auth.py:53-60`).
- Produces: `GET /api/propose-actions`, `POST /api/propose-actions/phrases`, `PUT /api/propose-actions/phrases/{id}`, `DELETE /api/propose-actions/phrases/{id}`, `POST /api/propose-actions/synonyms`, `DELETE /api/propose-actions/synonyms/{synonym}`, `POST /api/propose-actions/{key}/active`, `POST /api/propose-actions/{key}/settings`; `require_propose_edit` (FastAPI-зависимость, используется всеми мутирующими эндпоинтами).

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_panel_propose_actions.py`:

```python
"""Управление действиями «Предложить» через сайт.

GET  /api/propose-actions            — владелец и админ панели видят список
POST/PUT/DELETE .../phrases          — правка фраз (по уровню propose_manage)
POST .../synonyms, DELETE .../synonyms/{synonym}
POST .../{key}/active, .../{key}/settings
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel import roles
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "actions": {
            "romashka": {"cooldown_seconds": 300, "timeout_seconds": 120, "is_active": 1},
        },
        "phrases": [
            {"id": 1, "action_key": "romashka", "kind": "propose", "phrase": "{actor} зовёт {target} 🌼", "sort_order": 0, "is_active": 1},
            {"id": 2, "action_key": "romashka", "kind": "agree", "phrase": "ок 🌼", "sort_order": 0, "is_active": 1},
        ],
        "synonyms": {"ромашка": "romashka"},
        "admins": [],
        "command_levels": {},
        "reload_value": None, "logs": [],
    }
    next_id = {"v": 100}

    async def list_propose_actions_rows():
        return [{"action_key": k, **v} for k, v in state["actions"].items()]

    async def list_propose_phrases_rows():
        return [dict(p) for p in state["phrases"]]

    async def list_propose_action_synonyms():
        return dict(state["synonyms"])

    async def add_propose_phrase(action_key, kind, phrase, sort_order=None):
        next_id["v"] += 1
        state["actions"].setdefault(action_key, {"cooldown_seconds": 300, "timeout_seconds": 120, "is_active": 1})
        state["phrases"].append({"id": next_id["v"], "action_key": action_key, "kind": kind,
                                 "phrase": phrase, "sort_order": 0, "is_active": 1})
        return next_id["v"]

    async def update_propose_phrase(phrase_id, phrase):
        for p in state["phrases"]:
            if p["id"] == phrase_id:
                p["phrase"] = phrase
                return True
        return False

    async def delete_propose_phrase(phrase_id):
        before = len(state["phrases"])
        state["phrases"] = [p for p in state["phrases"] if p["id"] != phrase_id]
        return len(state["phrases"]) < before

    async def add_propose_action_synonym(synonym, action_key):
        state["synonyms"][synonym] = action_key

    async def delete_propose_action_synonym(synonym):
        return state["synonyms"].pop(synonym, None) is not None

    async def set_propose_action_active(action_key, is_active):
        if action_key not in state["actions"]:
            return 0
        state["actions"][action_key]["is_active"] = 1 if is_active else 0
        return 1

    async def set_propose_action_settings(action_key, cooldown_seconds, timeout_seconds):
        if action_key not in state["actions"]:
            return False
        state["actions"][action_key]["cooldown_seconds"] = cooldown_seconds
        state["actions"][action_key]["timeout_seconds"] = timeout_seconds
        return True

    async def list_admins():
        return state["admins"]

    async def fetch_settings():
        return {}

    async def list_command_levels():
        return dict(state["command_levels"])

    async def set_data(key, value, updated_by=None):
        if key == "panel_action_reload":
            state["reload_value"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    for name, fn in [
        ("list_propose_actions_rows", list_propose_actions_rows),
        ("list_propose_phrases_rows", list_propose_phrases_rows),
        ("list_propose_action_synonyms", list_propose_action_synonyms),
        ("add_propose_phrase", add_propose_phrase),
        ("update_propose_phrase", update_propose_phrase),
        ("delete_propose_phrase", delete_propose_phrase),
        ("add_propose_action_synonym", add_propose_action_synonym),
        ("delete_propose_action_synonym", delete_propose_action_synonym),
        ("set_propose_action_active", set_propose_action_active),
        ("set_propose_action_settings", set_propose_action_settings),
        ("list_admins", list_admins), ("fetch_settings", fetch_settings),
        ("list_command_levels", list_command_levels),
        ("set_data", set_data), ("add_log", add_log),
    ]:
        monkeypatch.setattr(db, name, fn, raising=False)

    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    roles.invalidate()  # кэш ролей живёт 30с — между тестами он бы протух не вовремя

    client = TestClient(panel.app)
    client.state = state
    yield client
    panel.app.dependency_overrides.clear()


def _as_owner(client):
    owner = PanelUser(id=1, username="owner", role="owner", tg_user_id=1)
    client.state["admins"] = []
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    return owner


def _as_senior_admin(client):
    admin = PanelUser(id=2, username="senior", role="admin", tg_user_id=42)
    client.state["admins"] = [{"user_id": 42, "level": roles.LEVEL_SENIOR}]
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def _as_junior_admin(client):
    admin = PanelUser(id=3, username="moder", role="admin", tg_user_id=43)
    client.state["admins"] = [{"user_id": 43, "level": roles.LEVEL_MODERATOR}]
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def overview(client):
    res = client.get("/api/propose-actions")
    assert res.status_code == 200, res.text
    return res.json()


def test_действия_видны_с_фразами_по_видам(panel_client):
    _as_owner(panel_client)
    data = overview(panel_client)
    romashka = next(a for a in data["actions"] if a["key"] == "romashka")
    assert [p["phrase"] for p in romashka["phrases"]["propose"]] == ["{actor} зовёт {target} 🌼"]
    assert [p["phrase"] for p in romashka["phrases"]["agree"]] == ["ок 🌼"]
    assert romashka["phrases"]["decline"] == []
    assert romashka["cooldown_seconds"] == 300
    assert romashka["synonyms"] == ["ромашка"]


def test_владелец_может_редактировать(panel_client):
    _as_owner(panel_client)
    assert overview(panel_client)["can_edit"] is True


def test_старший_админ_может_редактировать_по_умолчанию(panel_client):
    """propose_manage по умолчанию требует LEVEL_SENIOR — без оверрайда старший
    администратор проходит."""
    _as_senior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is True


def test_младший_админ_не_может_редактировать_по_умолчанию(panel_client):
    _as_junior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is False


def test_оверрайд_дерева_команд_поднимает_порог(panel_client):
    """Владелец поднял propose_manage до уровня владельца через Дерево команд —
    даже старший администратор больше не может редактировать."""
    panel_client.state["command_levels"] = {"propose_manage": roles.OWNER_LEVEL}
    _as_senior_admin(panel_client)
    assert overview(panel_client)["can_edit"] is False


def test_фраза_добавляется_и_создаёт_новое_действие(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "turnir", "kind": "propose", "phrase": "{actor} зовёт {target} на турнир"})
    assert res.status_code == 200, res.text
    keys = {a["key"] for a in overview(panel_client)["actions"]}
    assert "turnir" in keys


def test_младший_админ_не_может_добавить_фразу(panel_client):
    _as_junior_admin(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "romashka", "kind": "propose", "phrase": "x {actor} {target}"})
    assert res.status_code == 403


def test_неизвестный_вид_фразы_отвергается(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/phrases",
                            json={"action_key": "romashka", "kind": "wrong", "phrase": "x {actor} {target}"})
    assert res.status_code == 400


def test_действие_включается_выключается(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/romashka/active", json={"active": False})
    assert res.status_code == 200, res.text
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert romashka["active"] is False


def test_кулдаун_и_таймаут_сохраняются(panel_client):
    _as_owner(panel_client)
    res = panel_client.post("/api/propose-actions/romashka/settings",
                            json={"cooldown_seconds": 600, "timeout_seconds": 60})
    assert res.status_code == 200, res.text
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert romashka["cooldown_seconds"] == 600
    assert romashka["timeout_seconds"] == 60


def test_синоним_добавляется_и_удаляется(panel_client):
    _as_owner(panel_client)
    assert panel_client.post("/api/propose-actions/synonyms",
                             json={"synonym": "маргаритка", "action_key": "romashka"}).status_code == 200
    assert overview(panel_client)["actions"][0]["synonyms"] or True  # см. следующий ассерт
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert "маргаритка" in romashka["synonyms"]
    assert panel_client.request("DELETE", "/api/propose-actions/synonyms/маргаритка").status_code == 200
    romashka = next(a for a in overview(panel_client)["actions"] if a["key"] == "romashka")
    assert "маргаритка" not in romashka["synonyms"]


def test_правка_поднимает_флаг_перечитки(panel_client):
    _as_owner(panel_client)
    assert panel_client.state["reload_value"] is None
    panel_client.post("/api/propose-actions/romashka/active", json={"active": False})
    assert panel_client.state["reload_value"] is not None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_panel_propose_actions.py -v`
Expected: FAIL — `404 Not Found` на всех запросах (эндпоинтов ещё нет).

- [ ] **Step 3: Добавить эндпоинты в `webpanel/app.py`**

Добавить в `webpanel/app.py`, сразу после конца блока `api_action_set`/`ACTION_SETS` (после `webpanel/app.py:1341`, перед `@app.get("/api/member/capabilities")`):

```python
# --- «Предложить действие» ---------------------------------------------------
_PROPOSE_KINDS = ("propose", "agree", "decline")


async def _propose_manage_level() -> int:
    overrides = await db.list_command_levels()
    return overrides.get("propose_manage", roles.LEVEL_SENIOR)


async def _can_edit_propose(user: PanelUser) -> bool:
    if user.is_owner:
        return True
    if user.tg_user_id is None:
        return False
    role_map = await roles.load()
    return role_map.level_of(user.tg_user_id) >= await _propose_manage_level()


async def require_propose_edit(user: PanelUser = Depends(auth.require_user)) -> PanelUser:
    if not await _can_edit_propose(user):
        raise HTTPException(403, "Недостаточно прав для правки действий.")
    return user


@app.get("/api/propose-actions")
async def api_propose_actions(user: PanelUser = Depends(auth.require_user)):
    action_rows = await db.list_propose_actions_rows()
    phrase_rows = await db.list_propose_phrases_rows()
    synonyms = await db.list_propose_action_synonyms()
    synonyms_by_action: dict[str, list[str]] = {}
    for synonym, key in synonyms.items():
        synonyms_by_action.setdefault(key, []).append(synonym)

    actions: dict[str, dict] = {}
    for r in action_rows:
        actions[r["action_key"]] = {
            "key": r["action_key"], "active": bool(r["is_active"]),
            "cooldown_seconds": r["cooldown_seconds"], "timeout_seconds": r["timeout_seconds"],
            "phrases": {kind: [] for kind in _PROPOSE_KINDS},
            "synonyms": synonyms_by_action.get(r["action_key"], []),
        }
    for p in phrase_rows:
        entry = actions.get(p["action_key"])
        if entry is not None:
            entry["phrases"][p["kind"]].append({"id": p["id"], "phrase": p["phrase"]})

    return {"actions": list(actions.values()), "can_edit": await _can_edit_propose(user)}


class ProposePhraseBody(BaseModel):
    action_key: str
    kind: str
    phrase: str


@app.post("/api/propose-actions/phrases")
async def api_propose_add_phrase(
    body: ProposePhraseBody, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if body.kind not in _PROPOSE_KINDS:
        raise HTTPException(400, "Вид фразы должен быть propose/agree/decline.")
    action_key = body.action_key.strip().casefold()
    phrase = body.phrase.strip()
    if not action_key or len(action_key) > 64:
        raise HTTPException(400, "Некорректный ключ действия.")
    if not phrase or len(phrase) > 512:
        raise HTTPException(400, "Некорректная фраза.")
    new_id = await db.add_propose_phrase(action_key, body.kind, phrase)
    await db.add_log("propose_phrase_added", actor_id=user.id, details=f"{action_key}/{body.kind}: {phrase}")
    await _signal_action_reload()
    return {"ok": True, "id": new_id}


class ProposePhraseUpdateBody(BaseModel):
    phrase: str


@app.put("/api/propose-actions/phrases/{phrase_id}")
async def api_propose_update_phrase(
    phrase_id: int, body: ProposePhraseUpdateBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    phrase = body.phrase.strip()
    if not phrase or len(phrase) > 512:
        raise HTTPException(400, "Некорректная фраза.")
    if not await db.update_propose_phrase(phrase_id, phrase):
        raise HTTPException(404, "Фраза не найдена.")
    await db.add_log("propose_phrase_updated", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/propose-actions/phrases/{phrase_id}")
async def api_propose_delete_phrase(
    phrase_id: int, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.delete_propose_phrase(phrase_id):
        raise HTTPException(404, "Фраза не найдена.")
    await db.add_log("propose_phrase_deleted", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


class ProposeSynonymBody(BaseModel):
    synonym: str
    action_key: str


@app.post("/api/propose-actions/synonyms")
async def api_propose_add_synonym(
    body: ProposeSynonymBody, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    synonym = body.synonym.strip().casefold()
    action_key = body.action_key.strip().casefold()
    if not synonym or not action_key or len(synonym) > 64:
        raise HTTPException(400, "Некорректный синоним или ключ.")
    await db.add_propose_action_synonym(synonym, action_key)
    await db.add_log("propose_synonym_added", actor_id=user.id, details=f"{synonym} -> {action_key}")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/propose-actions/synonyms/{synonym}")
async def api_propose_delete_synonym(
    synonym: str, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.delete_propose_action_synonym(synonym):
        raise HTTPException(404, "Синоним не найден.")
    await db.add_log("propose_synonym_deleted", actor_id=user.id, details=synonym)
    await _signal_action_reload()
    return {"ok": True}


class ProposeActiveBody(BaseModel):
    active: bool


@app.post("/api/propose-actions/{action_key}/active")
async def api_propose_set_active(
    action_key: str, body: ProposeActiveBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.set_propose_action_active(action_key, body.active):
        raise HTTPException(404, "Действие не найдено.")
    await db.add_log("propose_action_toggled", actor_id=user.id, details=f"{action_key}: {body.active}")
    await _signal_action_reload()
    return {"ok": True}


class ProposeSettingsBody(BaseModel):
    cooldown_seconds: int
    timeout_seconds: int


@app.post("/api/propose-actions/{action_key}/settings")
async def api_propose_set_settings(
    action_key: str, body: ProposeSettingsBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not (0 < body.cooldown_seconds <= 86400) or not (0 < body.timeout_seconds <= 86400):
        raise HTTPException(400, "Кулдаун и таймаут должны быть от 1 до 86400 секунд.")
    if not await db.set_propose_action_settings(action_key, body.cooldown_seconds, body.timeout_seconds):
        raise HTTPException(404, "Действие не найдено.")
    await db.add_log(
        "propose_settings_set", actor_id=user.id,
        details=f"{action_key}: cooldown={body.cooldown_seconds} timeout={body.timeout_seconds}",
    )
    await _signal_action_reload()
    return {"ok": True}
```

`roles`, `auth`, `db`, `BaseModel`, `Depends`, `HTTPException`, `Request`, `PanelUser` уже импортированы в `webpanel/app.py` (используются существующими эндпоинтами выше). Коды ошибок — голыми числами (`403`, `404`, `400`), как и во всех существующих эндпоинтах этого файла (`status.HTTP_*` тут не используется и не импортирован).

- [ ] **Step 4: Прогнать тесты — должны пройти**

Run: `pytest tests/test_panel_propose_actions.py -v`
Expected: PASS (13 тестов).

- [ ] **Step 5: Прогнать весь набор тестов панели**

Run: `pytest tests/ -k panel -v`
Expected: PASS (ничего не сломано).

- [ ] **Step 6: Commit**

```bash
git add webpanel/app.py tests/test_panel_propose_actions.py
git commit -m "feat(propose): панель — CRUD действий/фраз/синонимов, права через Дерево команд"
```

---

### Task 6: Живая перечитка + фоновая просрочка при старте

**Files:**
- Modify: `bot.py` (`panel_action_reload_loop`, `bot.py:3451-3462`; `main()`, рядом с `asyncio.create_task(panel_action_reload_loop())`, `bot.py:21161`)

**Interfaces:**
- Consumes: `refresh_propose_caches()` (Task 2), `propose_expiry_loop()` (Task 3).

- [ ] **Step 1: Добавить перечитку кэшей «Предложить» в `panel_action_reload_loop`**

В `bot.py`, внутри `panel_action_reload_loop`, сразу после блока `reward_degree_level_overrides` (после строки `reward_degree_level_overrides.update(await db.list_reward_degree_levels())`, перед `logger.info(...)`):

```python
                await refresh_propose_caches()
```

Итоговый блок для сверки:

```python
                command_level_overrides.clear()
                command_level_overrides.update(await db.list_command_levels())
                reward_degree_level_overrides.clear()
                reward_degree_level_overrides.update(await db.list_reward_degree_levels())
                await refresh_propose_caches()
                logger.info("РП/себяшки/жесты отн/фильтр слов/права команд/предложения перечитаны по сигналу из панели")
```

- [ ] **Step 2: Запустить фоновую просрочку при старте**

В `bot.py` `main()`, сразу после `asyncio.create_task(panel_action_reload_loop())` (`bot.py:21161`):

```python
    asyncio.create_task(propose_expiry_loop())
```

- [ ] **Step 3: Убедиться, что бот всё ещё импортируется без ошибок**

Run: `python -c "import os; os.environ.setdefault('BOT_TOKEN','123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN'); os.environ.setdefault('OWNER_IDS','1'); import bot"`
Expected: без исключений.

Отдельного автотеста на сам `panel_action_reload_loop`/`propose_expiry_loop` (оба — `while True` с `asyncio.sleep`) в проекте нет и раньше не было для аналогичных блоков (`command_level_overrides`, `reward_degree_level_overrides`) — не добавляем его и здесь, чтобы не отклоняться от установленного подхода. Логика, которую эти лупы вызывают (`refresh_propose_caches`, `_process_expired_propose_requests`), уже покрыта тестами в Task 2/3.

- [ ] **Step 4: Commit**

```bash
git add bot.py
git commit -m "feat(propose): живая перечитка кэшей с сайта + фоновая просрочка при старте"
```

---

### Task 7: Фронтенд — карточка «Предложения» рядом с РП-действиями

**Files:**
- Modify: `webpanel/static/index.html` (внутри `#view-actions`, после `#synonyms-card`, `webpanel/static/index.html:544-556`)
- Modify: `webpanel/static/app.js` (новый блок рядом с логикой РП-действий, после `webpanel/static/app.js:1496`; плюс один вызов в переключателе вкладок, строка 1032)

**Interfaces:**
- Consumes: `GET /api/propose-actions`, `POST /api/propose-actions/phrases`, `PUT /api/propose-actions/phrases/{id}`, `DELETE /api/propose-actions/phrases/{id}`, `POST /api/propose-actions/synonyms`, `DELETE /api/propose-actions/synonyms/{synonym}`, `POST /api/propose-actions/{key}/active`, `POST /api/propose-actions/{key}/settings` (Task 5).
- Produces: ничего, чем пользуются другие задачи (лист-узел).

Существующий экран РП-действий/себяшек (`#view-actions`) устроен так: один `actionKind` (`"rp"`/`"self"`), общие `loadActions()`/`renderActions()`/`bindActionControls()`, где `a.phrases` — плоский массив (`webpanel/static/app.js:1335-1444`). У «Предложений» `a.phrases` — объект с тремя списками (`propose`/`agree`/`decline`), поэтому карточка «Предложения» — **отдельный, самостоятельный блок** на той же вкладке (не третье значение `actionKind`), со своими функциями, но тем же визуальным языком (`.card.action-card`, `.action-head`, `.action-body.collapsed`, `.phrase-row`, `icon(...)`, `say(...)`, `api(...)` — все уже существуют и используются остальной панелью).

- [ ] **Step 1: Добавить карточку в разметку**

В `webpanel/static/index.html`, внутри `<section class="view hidden" id="view-actions">`, сразу после закрывающего `</div>` блока `#synonyms-card` (строка 556) и перед комментарием `<!-- Отн-жесты ... -->` (строка 558):

```html
      <div class="card" style="margin-top: var(--gap-4)" id="propose-actions-card">
        <h3><svg class="ic"><use href="#ic-wand"/></svg>Предложения
          <span class="muted">(команды «предложить …» — с кнопками Да/Нет)</span></h3>
        <p class="sub">У каждого действия — 3 набора фраз (предложение / согласие / отказ, бот берёт
          случайную) и свои кулдаун/таймаут в секундах. Правки применяются в чатах через несколько секунд.</p>
        <form class="row" id="propose-action-add">
          <label class="narrow"><span>Ключ</span>
            <input type="text" id="propose-action-key" maxlength="64" placeholder="например: romashka" required>
          </label>
          <label><span>Фраза предложения</span>
            <input type="text" id="propose-action-phrase" maxlength="512" placeholder="{actor} зовёт {target}…" required>
          </label>
          <button class="primary" type="submit"><svg class="ic"><use href="#ic-plus"/></svg>Добавить</button>
        </form>
        <div id="propose-actions-list"></div>
        <h3 style="margin-top: var(--gap-3)">Синонимы <span class="muted">(альтернативные слова триггера)</span></h3>
        <form class="row" id="propose-synonym-add">
          <label class="narrow"><span>Слово</span>
            <input type="text" id="propose-synonym-word" maxlength="64" placeholder="ромашка" required>
          </label>
          <label class="narrow"><span>Действие</span>
            <input type="text" id="propose-synonym-key" maxlength="64" placeholder="romashka" required>
          </label>
          <button class="primary" type="submit"><svg class="ic"><use href="#ic-plus"/></svg>Добавить</button>
        </form>
        <div id="propose-synonyms-list"></div>
      </div>
```

- [ ] **Step 2: Добавить JS-логику**

В `webpanel/static/app.js`, сразу после конца блока РП-действий (после строки 1496, перед комментарием `// --- Отн-жесты ...`), добавить:

```javascript
// --- «Предложить действие» --------------------------------------------------
const PROPOSE_KIND_LABELS = { propose: "Предложение", agree: "Согласие", decline: "Отказ" };

async function loadProposeActions() {
  $("#propose-actions-list").innerHTML = skeleton(3);
  try {
    const data = await api("/api/propose-actions");
    renderProposeActions(data.actions, data.can_edit);
  } catch (err) {
    $("#propose-actions-list").innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderProposeActions(actions, canEdit) {
  if (!actions.length) {
    $("#propose-actions-list").innerHTML = `<div class="card"><div class="empty">${icon("empty")}<span>Действий пока нет</span></div></div>`;
    bindProposeActionControls(canEdit);
    return;
  }
  $("#propose-actions-list").innerHTML = actions.map((a) => `
    <div class="card action-card${a.active ? "" : " off"}" data-propose-action="${escapeHtml(a.key)}">
      <div class="action-head">
        <h3>${escapeHtml(a.key)}</h3>
        ${canEdit ? `
          <div class="action-head-controls">
            <button class="ghost small ${a.active ? "" : "danger"}" data-propose-toggle="${escapeHtml(a.key)}" data-active="${a.active ? 1 : 0}">
              ${icon("power")}${a.active ? "Включено" : "Выключено"}
            </button>
            <button class="disclosure ghost small" data-propose-expand aria-expanded="false" title="Показать">${icon("chevron")}</button>
          </div>` : `<span class="chip${a.active ? "" : " chip-muted"}">${a.active ? "Включено" : "Выключено"}</span>`}
      </div>
      <div class="action-body collapsed">
        ${["propose", "agree", "decline"].map((kind) => `
          <h4>${PROPOSE_KIND_LABELS[kind]}</h4>
          <div class="action-phrases">
            ${a.phrases[kind].map((p) => `
              <div class="phrase-row" data-phrase="${p.id}">
                <span class="phrase-text">${escapeHtml(p.phrase)}</span>
                ${canEdit ? `
                  <button class="ghost small" data-propose-edit-phrase="${p.id}" title="Изменить">${icon("edit")}</button>
                  <button class="ghost small danger" data-propose-del-phrase="${p.id}" title="Удалить">${icon("trash")}</button>` : ""}
              </div>`).join("") || `<div class="empty"><span class="muted">Фраз пока нет</span></div>`}
          </div>
          ${canEdit ? `
            <form class="row phrase-add" data-propose-add-to="${escapeHtml(a.key)}" data-propose-kind="${kind}">
              <input type="text" maxlength="512" placeholder="Новая фраза…" required>
              <button class="ghost small" type="submit">${icon("plus")}Фраза</button>
            </form>` : ""}
        `).join("")}
        <h4>Синонимы</h4>
        <div class="action-phrases">
          ${a.synonyms.map((s) => `
            <div class="phrase-row" data-propose-synonym="${escapeHtml(s)}">
              <span class="phrase-text">${escapeHtml(s)}</span>
              ${canEdit ? `<button class="ghost small danger" data-propose-del-synonym="${escapeHtml(s)}" title="Удалить">${icon("trash")}</button>` : ""}
            </div>`).join("") || `<div class="empty"><span class="muted">Синонимов пока нет</span></div>`}
        </div>
        ${canEdit ? `
          <form class="row" data-propose-synonym-add-to="${escapeHtml(a.key)}">
            <input type="text" maxlength="64" placeholder="новый синоним…" required>
            <button class="ghost small" type="submit">${icon("plus")}Синоним</button>
          </form>
          <form class="row propose-settings" data-propose-settings-for="${escapeHtml(a.key)}">
            <label class="narrow"><span>Кулдаун, сек</span>
              <input type="number" min="1" max="86400" value="${a.cooldown_seconds}" data-field="cooldown_seconds" required>
            </label>
            <label class="narrow"><span>Таймаут, сек</span>
              <input type="number" min="1" max="86400" value="${a.timeout_seconds}" data-field="timeout_seconds" required>
            </label>
            <button class="ghost small" type="submit">${icon("check")}Сохранить</button>
          </form>` : `<p class="sub">Кулдаун ${a.cooldown_seconds}с, таймаут ${a.timeout_seconds}с</p>`}
      </div>
    </div>`).join("");
  bindProposeActionControls(canEdit);
}

function bindProposeActionControls(canEdit) {
  $$("[data-propose-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const body = btn.closest(".action-card").querySelector(".action-body");
      const nowCollapsed = body.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
    });
  });
  if (!canEdit) return;

  $$("[data-propose-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const active = btn.dataset.active !== "1";
      try {
        await api(`/api/propose-actions/${encodeURIComponent(btn.dataset.proposeToggle)}/active`,
                  { method: "POST", body: { active } });
        say("#global-msg", active ? "Действие включено" : "Действие выключено");
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-del-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Удалить эту фразу?")) return;
      try {
        await api(`/api/propose-actions/phrases/${btn.dataset.proposeDelPhrase}`, { method: "DELETE" });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-edit-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".phrase-row");
      const current = row.querySelector(".phrase-text").textContent;
      const next = prompt("Новый текст фразы:", current);
      if (next === null || !next.trim()) return;
      try {
        await api(`/api/propose-actions/phrases/${btn.dataset.proposeEditPhrase}`,
                  { method: "PUT", body: { phrase: next.trim() } });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-add-to]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      const phrase = input.value.trim();
      if (!phrase) return;
      try {
        await api("/api/propose-actions/phrases", {
          method: "POST",
          body: { action_key: form.dataset.proposeAddTo, kind: form.dataset.proposeKind, phrase },
        });
        input.value = "";
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-del-synonym]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/propose-actions/synonyms/${encodeURIComponent(btn.dataset.proposeDelSynonym)}`, { method: "DELETE" });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-synonym-add-to]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      const synonym = input.value.trim().toLowerCase();
      if (!synonym) return;
      try {
        await api("/api/propose-actions/synonyms", {
          method: "POST", body: { synonym, action_key: form.dataset.proposeSynonymAddTo },
        });
        input.value = "";
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$(".propose-settings").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const cooldown = Number(form.querySelector('[data-field="cooldown_seconds"]').value);
      const timeout = Number(form.querySelector('[data-field="timeout_seconds"]').value);
      try {
        await api(`/api/propose-actions/${encodeURIComponent(form.dataset.proposeSettingsFor)}/settings`, {
          method: "POST", body: { cooldown_seconds: cooldown, timeout_seconds: timeout },
        });
        say("#global-msg", "Кулдаун/таймаут сохранены");
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });
}

$("#propose-action-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const action_key = $("#propose-action-key").value.trim();
  const phrase = $("#propose-action-phrase").value.trim();
  if (!action_key || !phrase) return;
  try {
    await api("/api/propose-actions/phrases", { method: "POST", body: { action_key, kind: "propose", phrase } });
    say("#global-msg", `Действие «${action_key}» добавлено`);
    $("#propose-action-key").value = "";
    $("#propose-action-phrase").value = "";
    loadProposeActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

$("#propose-synonym-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const synonym = $("#propose-synonym-word").value.trim().toLowerCase();
  const action_key = $("#propose-synonym-key").value.trim();
  if (!synonym || !action_key) return;
  try {
    await api("/api/propose-actions/synonyms", { method: "POST", body: { synonym, action_key } });
    say("#global-msg", "Синоним добавлен");
    $("#propose-synonym-word").value = "";
    $("#propose-synonym-key").value = "";
    loadProposeActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});
```

- [ ] **Step 3: Подключить загрузку к переключателю вкладок**

В `webpanel/static/app.js`, строка 1032, заменить:

```javascript
    if (view === "actions") { loadActions(); loadGestures(); }
```

на:

```javascript
    if (view === "actions") { loadActions(); loadGestures(); loadProposeActions(); }
```

- [ ] **Step 4: Проверить синтаксис**

Run: `node --check webpanel/static/app.js`
Expected: без ошибок (пустой вывод).

- [ ] **Step 5: Проверить вручную в браузере**

В проекте нет JS-тестового рантайма — проверка ручная:

1. Запустить панель локально (`python -m webpanel`).
2. Зайти под владельцем → вкладка «Действия» → под РП-действиями/себяшками/синонимами должна появиться карточка «Предложения» с 7 действиями по умолчанию.
3. Раскрыть любое действие (кнопка-шеврон) → видно 3 группы фраз (Предложение/Согласие/Отказ) по 5 штук, список синонимов, поля кулдаун/таймаут.
4. Добавить фразу любого вида → появляется в списке без перезагрузки страницы; после F5 сохраняется.
5. Поменять кулдаун/таймаут и нажать «Сохранить» → сообщение «Кулдаун/таймаут сохранены», значения видны после F5.
6. Выключить действие (кнопка «Включено»/«Выключено») → пропадает из работы бота (проверить в группе: триггер на выключенное действие больше не срабатывает).
7. Зайти под админом с уровнем ниже «Старший администратор» → карточка видна, но кнопок редактирования/форм нет (только чипы «Включено»/«Выключено» и текст кулдауна/таймаута).
8. В группе, где бот состоит: `предложить <синоним>` ответом на чьё-то сообщение → приходит сообщение с Да/Нет; нажать Да с аккаунта адресата → сообщение меняется на фразу согласия; повторный запрос той же паре сразу же — должен сработать кулдаун («Подождите ещё …с»).

- [ ] **Step 6: Commit**

```bash
git add webpanel/static/index.html webpanel/static/app.js
git commit -m "feat(panel): карточка «Предложения» — фразы, синонимы, кулдаун/таймаут"
```

---

## Порядок выполнения

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7.

Task 4 и Task 5 оба зависят только от Task 1 (CRUD) — можно поменять местами. Task 6 логически зависит от Task 2 (`refresh_propose_caches`) и Task 3 (`propose_expiry_loop`), но код не пересекается с Task 4/5 — можно делать сразу после Task 3, параллельно с Task 4/5, если удобнее. Task 7 зависит только от Task 5 (контракт эндпоинтов).
