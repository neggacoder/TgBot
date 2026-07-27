# db.py
"""
Асинхронный слой доступа к MySQL для бота.
Использует пул соединений aiomysql. Все функции — корутины, вызывать через await.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import aiomysql

logger = logging.getLogger(__name__)

_pool: Optional[aiomysql.Pool] = None


# ----------------------------------------------------------------------------
# Инициализация пула
# ----------------------------------------------------------------------------
async def init_pool() -> None:
    global _pool
    _pool = await aiomysql.create_pool(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "neongelion"),
        password=os.getenv("DB_PASSWORD", ""),
        db=os.getenv("DB_NAME", "neongelion"),
        charset="utf8mb4",
        autocommit=True,
        minsize=1,
        maxsize=10,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


def _require_pool() -> aiomysql.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized — call init_pool() first")
    return _pool


async def _fetchone(query: str, args: tuple = ()) -> Optional[dict]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, args)
            return await cur.fetchone()


async def _fetchall(query: str, args: tuple = ()) -> list[dict]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(query, args)
            return list(await cur.fetchall())


async def _execute(query: str, args: tuple = ()) -> int:
    """Возвращает lastrowid (для INSERT) или rowcount."""
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return cur.lastrowid or cur.rowcount


async def _column_exists(table: str, column: str) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return row is not None


async def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    """Безопасный аналог 'ALTER TABLE ... ADD COLUMN IF NOT EXISTS' — сам синтаксис
    IF NOT EXISTS для ADD COLUMN понимает только MySQL 8.0.29+/новые MariaDB,
    поэтому здесь проверяем information_schema заранее, чтобы работало и на
    более старых серверах (например, MySQL 5.7)."""
    if await _column_exists(table, column):
        return
    await _execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def _add_unique_index_if_missing(table: str, index_name: str, column: str) -> None:
    """Безопасный аналог 'ALTER TABLE ... ADD UNIQUE INDEX IF NOT EXISTS' — проверяем
    information_schema заранее, чтобы работало и на более старых серверах MySQL."""
    row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index_name),
    )
    if row and row["cnt"]:
        return
    await _execute(f"ALTER TABLE {table} ADD UNIQUE INDEX {index_name} ({column})")


# ----------------------------------------------------------------------------
# Настройки (одна строка id=1)
# ----------------------------------------------------------------------------
async def fetch_settings() -> dict:
    row = await _fetchone("SELECT * FROM settings WHERE id = 1")
    if row is None:
        await _execute("INSERT IGNORE INTO settings (id) VALUES (1)")
        row = await _fetchone("SELECT * FROM settings WHERE id = 1")
    return row


_ALLOWED_SETTING_FIELDS = {
    "notify_chat_id",
    "notify_topic_id",
    "invite_link",
    "welcome_message",
    "link_message_template",
    "reject_message",
    "complaint_chat_id",
    "level_names",
    "admin_icon",
    "warn_limit",
    "role_reserve_timeout_hours",
    "timer_limit",
    "duel_outcome",
    # приветствие, которое бот пишет в самой группе при входе новичка;
    # колонка добавляется миграцией ensure_group_join_column()
    "group_join_message",
    # правила реста и памятка о нём (см. rest_rules.py); колонки добавляются
    # миграцией ensure_rest_settings_columns()
    "rest_rules_template",
    "rest_max_days",
    "rest_cooldown_days",
    "rest_min_member_days",
    "rest_cleanup_date",
    "rest_cleanup_block_days",
    # показывать ли обманные варны («&варн») в списке «варны» у самого
    # разыгранного; колонка добавляется миграцией ensure_fake_warn_column()
    "fake_warns_in_list",
    "command_cleanup_minutes",
    # Часовой пояс ПОКАЗА времени (внутри всё по-прежнему в UTC), колонка
    # добавляется миграцией ensure_timezone_column()
    "timezone",
}


async def ensure_group_join_column() -> None:
    """Колонка settings.group_join_message.

    Её не было ни в schema.sql, ни в списке разрешённых полей, хотя bot.py
    уже пытался туда писать — из-за чего настройка «Приветствие в группе»
    падала с ValueError ещё до запроса к базе.
    """
    await _add_column_if_missing("settings", "group_join_message", "TEXT NULL")


async def ensure_rest_settings_columns() -> None:
    """Колонки настроек реста: текст-памятка и лимиты (максимальный срок, пауза
    между рестами, минимальный стаж в чате, дата чистки и окно перед ней).

    NULL = «использовать дефолт из rest_rules.RestLimits», поэтому значения по
    умолчанию в самих колонках не задаём: так видно, трогал админ настройку
    или нет. Дату чистки храним строкой в том же виде, в каком её вводит
    админ (ДД.ММ.ГГГГ), — она же показывается ему обратно.
    """
    await _add_column_if_missing("settings", "rest_rules_template", "TEXT NULL")
    await _add_column_if_missing("settings", "rest_max_days", "INT NULL")
    await _add_column_if_missing("settings", "rest_cooldown_days", "INT NULL")
    await _add_column_if_missing("settings", "rest_min_member_days", "INT NULL")
    await _add_column_if_missing("settings", "rest_cleanup_date", "VARCHAR(10) NULL")
    await _add_column_if_missing("settings", "rest_cleanup_block_days", "INT NULL")


async def ensure_word_filter_table() -> None:
    """Слова-фильтры: сообщения с ними бот удаляет (см. word_filter.py и
    MessageCounterMiddleware в bot.py). Список общий для бота, не по чатам —
    у этого бота один рабочий чат."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS word_filter ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "word VARCHAR(128) NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_word (word)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def list_filter_words() -> list[str]:
    rows = await _fetchall("SELECT word FROM word_filter ORDER BY word")
    return [row["word"] for row in rows]


async def add_filter_word(word: str) -> bool:
    """Добавляет слово в фильтр. False — если оно уже есть (UNIQUE)."""
    rowcount = await _execute(
        "INSERT IGNORE INTO word_filter (word) VALUES (%s)", (word,)
    )
    return rowcount > 0


async def delete_filter_word(word: str) -> bool:
    rowcount = await _execute("DELETE FROM word_filter WHERE word = %s", (word,))
    return rowcount > 0


async def ensure_fake_warn_column() -> None:
    """Колонка settings.fake_warns_in_list — показывать ли обманные варны
    («&варн», см. fake_warns.py) в списке «варны» у разыгранного.

    NULL = дефолт из кода (показывать: так розыгрыш выглядит правдоподобнее
    всего). 0 — копить их отдельно, тогда человек в своём списке видит только
    настоящие варны, а модератор смотрит обманные командой «&варны».
    """
    await _add_column_if_missing("settings", "fake_warns_in_list", "TINYINT NULL")

async def ensure_timezone_column() -> None:
    """Колонка settings.timezone — часовой пояс ПОКАЗА времени.

    NULL = UTC, как было до появления настройки. Хранение и все расчёты
    остаются в UTC: колонка влияет только на то, каким время видит человек
    (см. fmt_dt/to_local в bot.py).
    """
    await _add_column_if_missing("settings", "timezone", "VARCHAR(64) NULL")


async def ensure_command_cleanup_column() -> None:
    """Настройка автоочистки команд в чате жалоб/настроек (см. cmd_cleanup_minutes()
    в bot.py). NULL = дефолт 15 минут, 0 = выключено."""
    await _add_column_if_missing("settings", "command_cleanup_minutes", "INT NULL")


async def save_setting(field: str, value: Any) -> None:
    if field not in _ALLOWED_SETTING_FIELDS:
        raise ValueError(f"Недопустимое поле настроек: {field}")
    await _execute(f"UPDATE settings SET {field} = %s WHERE id = 1", (value,))


async def ensure_theme_columns() -> None:
    """Добавляет в settings колонки level_names (JSON с кастомными названиями
    рангов) и admin_icon (кастомная иконка для «Кто админ»), если их ещё нет —
    миграция на лету для модуля «Темы модераторов» (вызывается в main() перед
    load_caches(), как ensure_timers_table())."""
    await _add_column_if_missing("settings", "level_names", "TEXT NULL")
    await _add_column_if_missing("settings", "admin_icon", "VARCHAR(16) NULL")


async def ensure_limits_columns() -> None:
    """Добавляет в settings колонки warn_limit/role_reserve_timeout_hours/
    timer_limit, если их ещё нет — раньше это были env-переменные, читаемые
    один раз при старте (int(os.getenv(...))), теперь live-настройки для
    веб-панели (см. prompt_admin_website.md п.2.8). NULL означает «использовать
    дефолт из переменной окружения / встроенное значение» — см. load_caches()
    в bot.py, где эти три поля читаются с фолбэком на _*_DEFAULT."""
    await _add_column_if_missing("settings", "warn_limit", "INT NULL")
    await _add_column_if_missing("settings", "role_reserve_timeout_hours", "INT NULL")
    await _add_column_if_missing("settings", "timer_limit", "INT NULL")


# ----------------------------------------------------------------------------
# Администраторы — 3 уровня прав (как в Iris-боте):
#   1 — Модератор:             мут/размут, удаление сообщений, закреп/откреп
#   2 — Администратор:         + бан/разбан, сброс статистики
#   3 — Старший администратор: + настройки бота, управление админами 1-2 уровня,
#                                запись произвольных данных в БД
# Владельцы из .env (OWNER_IDS) стоят выше уровня 3 и в этой таблице не хранятся.
# ----------------------------------------------------------------------------
async def list_admins() -> list[dict]:
    """Возвращает [{user_id, level, added_by}, ...] по убыванию уровня."""
    return await _fetchall(
        "SELECT user_id, level, added_by FROM admins ORDER BY level DESC, user_id"
    )


async def get_admin(user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT user_id, level, added_by FROM admins WHERE user_id = %s",
        (user_id,),
    )


async def get_admin_level(user_id: int) -> int:
    row = await get_admin(user_id)
    return int(row["level"]) if row else 0


async def set_admin(user_id: int, level: int, added_by: Optional[int] = None) -> None:
    """Создаёт админа или меняет его уровень (1, 2 или 3)."""
    if level not in (1, 2, 3):
        raise ValueError("Уровень админа должен быть 1, 2 или 3")
    await _execute(
        "INSERT INTO admins (user_id, level, added_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE level = VALUES(level), added_by = VALUES(added_by)",
        (user_id, level, added_by),
    )


# Оставлено для обратной совместимости со старым кодом — добавляет админа 1 уровня,
# если уровень не передан.
async def add_admin(user_id: int, added_by: Optional[int] = None, level: int = 1) -> None:
    await set_admin(user_id, level, added_by)


async def remove_admin(user_id: int) -> None:
    await _execute("DELETE FROM admins WHERE user_id = %s", (user_id,))


async def list_admins_by_level(level: int) -> list[int]:
    rows = await _fetchall("SELECT user_id FROM admins WHERE level = %s", (level,))
    return [r["user_id"] for r in rows]


# ----------------------------------------------------------------------------
# Дерево команд: переопределения требуемого уровня прав для отдельных команд.
# Если для command_key нет строки здесь — используется уровень по умолчанию
# из COMMAND_REGISTRY в bot.py. Команда в чате: «право <ключ> <уровень>».
# ----------------------------------------------------------------------------
async def list_command_levels() -> dict[str, int]:
    rows = await _fetchall("SELECT command_key, min_level FROM command_permissions")
    return {r["command_key"]: int(r["min_level"]) for r in rows}


async def set_command_level(command_key: str, min_level: int, updated_by: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO command_permissions (command_key, min_level, updated_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE min_level = VALUES(min_level), updated_by = VALUES(updated_by), "
        "updated_at = CURRENT_TIMESTAMP",
        (command_key, min_level, updated_by),
    )


async def reset_command_level(command_key: str) -> None:
    await _execute("DELETE FROM command_permissions WHERE command_key = %s", (command_key,))


# ----------------------------------------------------------------------------
# Свой срок автоочистки у отдельной команды. Общий срок лежит в настройках
# (settings.command_cleanup_minutes, см. ensure_command_cleanup_column ниже);
# здесь — только исключения: «топ чистим через час, а баланс через минуту».
# Нет строки — команда живёт по общему сроку. minutes = 0 — не чистить совсем.
# ----------------------------------------------------------------------------
async def ensure_command_cleanup_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS command_cleanup ("
        "command_key VARCHAR(64) NOT NULL PRIMARY KEY, "
        "minutes INT NOT NULL, "
        "updated_by BIGINT NULL, "
        "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def list_command_cleanup() -> dict[str, int]:
    rows = await _fetchall("SELECT command_key, minutes FROM command_cleanup")
    return {r["command_key"]: int(r["minutes"]) for r in rows}


async def set_command_cleanup(command_key: str, minutes: int, updated_by: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO command_cleanup (command_key, minutes, updated_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE minutes = VALUES(minutes), updated_by = VALUES(updated_by), "
        "updated_at = CURRENT_TIMESTAMP",
        (command_key, minutes, updated_by),
    )


async def reset_command_cleanup(command_key: str) -> None:
    await _execute("DELETE FROM command_cleanup WHERE command_key = %s", (command_key,))


# ----------------------------------------------------------------------------
# Зеркало реестра команд (COMMAND_REGISTRY в bot.py) в БД — чтобы веб-панель,
# которая не может импортировать bot.py, могла показать «дерево команд». Бот
# перезаписывает эту таблицу при каждом старте (единый источник — код бота).
# ----------------------------------------------------------------------------
async def ensure_command_registry_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS command_registry ("
        "command_key VARCHAR(64) NOT NULL PRIMARY KEY, "
        "category VARCHAR(32) NOT NULL, "
        "phrase TEXT NOT NULL, "
        "default_level INT NOT NULL DEFAULT 0, "
        "overridable BOOL NOT NULL DEFAULT TRUE, "
        "sort_order INT NOT NULL DEFAULT 0"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Умеет ли бот отличить эту команду по тексту сообщения (см.
    # bot.resolve_command_key). Нужно панели: у команды, которую не отличить
    # от соседней, свой срок автоочистки задать нельзя, и предлагать для неё
    # поле — значит предлагать неработающую настройку.
    await _add_column_if_missing("command_registry", "cleanup_targetable", "BOOL NOT NULL DEFAULT TRUE")


async def replace_command_registry(entries: list[tuple]) -> None:
    """Полностью перезаписывает зеркало реестра. entries: кортежи
    (command_key, category, phrase, default_level, overridable, sort_order,
    cleanup_targetable)."""
    await _execute("DELETE FROM command_registry")
    for e in entries:
        await _execute(
            "INSERT INTO command_registry "
            "(command_key, category, phrase, default_level, overridable, sort_order, "
            "cleanup_targetable) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            e,
        )


async def list_command_registry() -> list[dict]:
    return await _fetchall(
        "SELECT command_key, category, phrase, default_level, overridable, sort_order, "
        "cleanup_targetable "
        "FROM command_registry ORDER BY sort_order, command_key"
    )


# ----------------------------------------------------------------------------
# Произвольные данные (key-value) — команды /setval, /getval, /delval, /listval.
# Позволяет старшим администраторам вписывать в БД любые значения без правки кода.
# ----------------------------------------------------------------------------
async def set_data(key: str, value: str, updated_by: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO bot_data (data_key, data_value, updated_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE data_value = VALUES(data_value), updated_by = VALUES(updated_by), "
        "updated_at = CURRENT_TIMESTAMP",
        (key, value, updated_by),
    )


async def get_data(key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT data_key, data_value, updated_by, updated_at FROM bot_data WHERE data_key = %s",
        (key,),
    )


async def delete_data(key: str) -> bool:
    rowcount = await _execute("DELETE FROM bot_data WHERE data_key = %s", (key,))
    return rowcount > 0


async def list_data_by_prefix(prefix: str) -> list[dict]:
    """Все настройки, ключ которых начинается с prefix (например «digest:»).

    Знаки подстановки в prefix экранируем: ключи вида «rest:%» иначе выбрали
    бы половину таблицы.
    """
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return await _fetchall(
        "SELECT data_key, data_value, updated_by, updated_at FROM bot_data "
        "WHERE data_key LIKE %s ORDER BY data_key",
        (escaped + "%",),
    )


async def list_data(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone("SELECT COUNT(*) AS total FROM bot_data")
    rows = await _fetchall(
        "SELECT data_key, data_value, updated_by, updated_at FROM bot_data "
        "ORDER BY data_key LIMIT %s OFFSET %s",
        (limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


# ----------------------------------------------------------------------------
# Режим «Входящего» (тест заявки)
# ----------------------------------------------------------------------------
async def list_test_mode_admins() -> list[int]:
    rows = await _fetchall("SELECT user_id FROM test_mode_admins")
    return [r["user_id"] for r in rows]


async def enable_test_mode(user_id: int) -> None:
    await _execute(
        "INSERT IGNORE INTO test_mode_admins (user_id) VALUES (%s)", (user_id,)
    )


async def disable_test_mode(user_id: int) -> None:
    await _execute("DELETE FROM test_mode_admins WHERE user_id = %s", (user_id,))


# ----------------------------------------------------------------------------
# Особые (настраиваемые) ответы для конкретных пользователей
# ----------------------------------------------------------------------------
async def list_custom_responses() -> list[dict]:
    return await _fetchall(
        "SELECT user_id, message, added_by, created_at FROM custom_responses ORDER BY created_at DESC"
    )


async def get_custom_response(user_id: int) -> Optional[str]:
    row = await _fetchone("SELECT message FROM custom_responses WHERE user_id = %s", (user_id,))
    return row["message"] if row else None


async def set_custom_response(user_id: int, message: str, added_by: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO custom_responses (user_id, message, added_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE message = VALUES(message), added_by = VALUES(added_by)",
        (user_id, message, added_by),
    )


async def remove_custom_response(user_id: int) -> None:
    await _execute("DELETE FROM custom_responses WHERE user_id = %s", (user_id,))


# ----------------------------------------------------------------------------
# Заявки на вход (связь message_id <-> user_id)
# ----------------------------------------------------------------------------
async def ensure_request_status_columns() -> None:
    """На старых базах таблица request_messages могла быть создана ещё до
    появления mark_request_decided()/get_request_status() и не иметь колонок
    status/decided_by/decided_at. Здесь безопасно добавляем их через
    information_schema (как ensure_theme_columns() и т.п.), без CREATE TABLE
    и без синтаксиса 'ADD COLUMN IF NOT EXISTS', который старые MySQL/MariaDB
    не понимают. Вызывается один раз в main() до старта поллинга."""
    await _add_column_if_missing(
        "request_messages", "status", "VARCHAR(16) NOT NULL DEFAULT 'pending'"
    )
    await _add_column_if_missing("request_messages", "decided_by", "BIGINT NULL")
    await _add_column_if_missing("request_messages", "decided_at", "DATETIME NULL")


async def has_any_request(user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM request_messages WHERE user_id = %s AND is_anchor = 1 LIMIT 1",
        (user_id,),
    )
    return row is not None


async def get_anchor_message_id(user_id: int) -> Optional[int]:
    row = await _fetchone(
        "SELECT message_id FROM request_messages WHERE user_id = %s AND is_anchor = 1 LIMIT 1",
        (user_id,),
    )
    return row["message_id"] if row else None


async def add_request_message(message_id: int, user_id: int, is_anchor: bool) -> None:
    await _execute(
        "INSERT INTO request_messages (message_id, user_id, is_anchor) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)",
        (message_id, user_id, int(is_anchor)),
    )


async def get_user_by_message(message_id: int) -> Optional[int]:
    row = await _fetchone(
        "SELECT user_id FROM request_messages WHERE message_id = %s", (message_id,)
    )
    return row["user_id"] if row else None


async def clear_user_requests(user_id: int) -> None:
    await _execute("DELETE FROM request_messages WHERE user_id = %s", (user_id,))


async def get_request_status(user_id: int) -> Optional[str]:
    """Статус анкорной заявки пользователя ('pending'/'accepted'/'declined'
    и т.п.), или None, если заявок не было. Нужен модулю «Роли», чтобы понять,
    ждёт ли заявитель ещё решения админов (см. bot.py: prompt_role_pick_for_applicant).
    На случай, если ensure_request_status_columns() почему-то ещё не выполнилась
    (старая база без колонки status) — не роняем вызывающий код, а считаем
    заявку "ещё не решённой" (см. использование в role_pick_select)."""
    try:
        row = await _fetchone(
            "SELECT status FROM request_messages WHERE user_id = %s AND is_anchor = 1 LIMIT 1",
            (user_id,),
        )
    except Exception:
        return None
    return row["status"] if row else None


async def mark_request_decided(anchor_message_id: int, status: str, decided_by: int) -> None:
    await _execute(
        "UPDATE request_messages SET status = %s, decided_by = %s, decided_at = %s "
        "WHERE message_id = %s",
        (status, decided_by, datetime.now(), anchor_message_id),
    )


# ----------------------------------------------------------------------------
# Браки (привязаны к чату)
# ----------------------------------------------------------------------------
async def ensure_marriage_module_tables() -> None:
    """20-й модуль «Браки»: срок действия брака и настройки браков в чате.

    Сама таблица marriages есть в schema.sql, но миграция обязана работать и на
    базе, поднятой раньше этого модуля, — поэтому создаём её здесь тоже
    (идемпотентно), а затем добираем новую колонку.

    ВРЕМЯ. married_at пишется через CURRENT_TIMESTAMP (часовой пояс сессии
    MySQL), поэтому и срок брака считается тем же NOW(), а не UTC_TIMESTAMP():
    смешивать две шкалы в одной таблице — верный способ получить брак, который
    «истёк» на три часа раньше, чем показан в чате.
    """
    await _execute(
        "CREATE TABLE IF NOT EXISTS marriages ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user1_id BIGINT NOT NULL, "
        "user2_id BIGINT NOT NULL, "
        "married_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_pair (chat_id, user1_id, user2_id), "
        "INDEX idx_marriage_user1 (chat_id, user1_id), "
        "INDEX idx_marriage_user2 (chat_id, user2_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # NULL = бессрочный брак. Именно NULL, а не «дата в далёком будущем»: все
    # уже существующие браки обязаны остаться бессрочными, иначе включение
    # модуля разом развело бы весь чат.
    await _add_column_if_missing("marriages", "expires_at", "DATETIME NULL")
    await _execute(
        "CREATE TABLE IF NOT EXISTS marriage_settings ("
        "chat_id BIGINT PRIMARY KEY, "
        "renew_price INT NOT NULL DEFAULT 500, "
        "divorce_mode VARCHAR(16) NOT NULL DEFAULT 'off', "
        "rating_enabled BOOL NOT NULL DEFAULT TRUE"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


MARRIAGE_DEFAULT_SETTINGS = {"renew_price": 500, "divorce_mode": "off", "rating_enabled": True}


async def get_marriage_settings(chat_id: int) -> dict:
    """Настройки браков чата; для чата без своей строки — значения по умолчанию."""
    row = await _fetchone(
        "SELECT renew_price, divorce_mode, rating_enabled FROM marriage_settings "
        "WHERE chat_id = %s",
        (chat_id,),
    )
    if not row:
        return dict(MARRIAGE_DEFAULT_SETTINGS)
    return {
        "renew_price": int(row["renew_price"]),
        "divorce_mode": str(row["divorce_mode"]),
        "rating_enabled": bool(row["rating_enabled"]),
    }


async def set_marriage_setting(chat_id: int, field: str, value) -> None:
    if field not in MARRIAGE_DEFAULT_SETTINGS:
        raise ValueError(f"Недопустимая настройка браков: {field}")
    await _execute(
        f"INSERT INTO marriage_settings (chat_id, {field}) VALUES (%s, %s) "
        f"ON DUPLICATE KEY UPDATE {field} = VALUES({field})",
        (chat_id, value),
    )


async def get_marriage(chat_id: int, user_id: int) -> Optional[dict]:
    row = await _fetchone(
        "SELECT id, user1_id, user2_id, married_at, expires_at FROM marriages "
        "WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s) LIMIT 1",
        (chat_id, user_id, user_id),
    )
    if row is None:
        return None
    partner_id = row["user2_id"] if row["user1_id"] == user_id else row["user1_id"]
    return {
        "id": row["id"],
        "partner_id": partner_id,
        "married_at": row["married_at"],
        "expires_at": row.get("expires_at"),
    }


async def list_marriages(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Возвращает страницу браков и их общее количество в чате."""
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM marriages WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user1_id, user2_id, married_at FROM marriages "
        "WHERE chat_id = %s ORDER BY married_at DESC, id DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def create_marriage(chat_id: int, user_a: int, user_b: int) -> bool:
    """Создаёт брак атомарно; возвращает False, если один уже занят."""
    u1, u2 = sorted((user_a, user_b))
    pool = _require_pool()
    lock_name = f"marriage:{chat_id}"
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT GET_LOCK(%s, 5) AS acquired", (lock_name,))
            lock = await cur.fetchone()
            if not lock or lock["acquired"] != 1:
                return False
            try:
                await cur.execute(
                    "SELECT 1 FROM marriages "
                    "WHERE chat_id = %s AND (user1_id IN (%s, %s) OR user2_id IN (%s, %s)) LIMIT 1",
                    (chat_id, u1, u2, u1, u2),
                )
                if await cur.fetchone():
                    return False
                await cur.execute(
                    "INSERT INTO marriages (chat_id, user1_id, user2_id) VALUES (%s, %s, %s)",
                    (chat_id, u1, u2),
                )
                return True
            finally:
                await cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))


async def delete_marriage(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM marriages WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s)",
        (chat_id, user_id, user_id),
    )
    return rowcount > 0


async def extend_marriage(chat_id: int, user_id: int, days: int) -> Optional[datetime]:
    """Продлевает брак на days суток; возвращает новую дату окончания.

    Считаем от МАКСИМУМА из «сейчас» и текущего срока: продление за день до
    конца должно прибавлять дни к остатку, а не обнулять его. У бессрочного
    брака (expires_at IS NULL) срок появляется впервые — от «сейчас».
    """
    updated = await _execute(
        "UPDATE marriages SET expires_at = "
        "  DATE_ADD(GREATEST(COALESCE(expires_at, NOW()), NOW()), INTERVAL %s DAY) "
        "WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s)",
        (days, chat_id, user_id, user_id),
    )
    if not updated:
        return None
    row = await _fetchone(
        "SELECT expires_at FROM marriages WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s)",
        (chat_id, user_id, user_id),
    )
    return row["expires_at"] if row else None


async def reset_marriages(chat_id: int) -> int:
    """«!Сброс браков» — снимает ВСЕ браки чата. Возвращает, сколько снято."""
    return await _execute("DELETE FROM marriages WHERE chat_id = %s", (chat_id,))


async def list_marriages_with_departed(chat_id: int) -> list[dict]:
    """Браки, где хотя бы один из супругов уже не числится в чате.

    «В чате» = есть строка в current_users: её ведёт сам бот по входам/выходам,
    отдельного запроса в Telegram на каждую пару не требуется.
    """
    return await _fetchall(
        "SELECT m.id, m.user1_id, m.user2_id, m.married_at FROM marriages m "
        "WHERE m.chat_id = %s AND ("
        "  NOT EXISTS (SELECT 1 FROM current_users c "
        "              WHERE c.chat_id = m.chat_id AND c.user_id = m.user1_id) "
        "  OR NOT EXISTS (SELECT 1 FROM current_users c "
        "                 WHERE c.chat_id = m.chat_id AND c.user_id = m.user2_id))",
        (chat_id,),
    )


async def delete_marriages_by_ids(ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ", ".join(["%s"] * len(ids))
    return await _execute(f"DELETE FROM marriages WHERE id IN ({placeholders})", tuple(ids))


async def list_marriage_top(chat_id: int, limit: int = 10) -> list[dict]:
    """Топ самых долгих браков чата: чем раньше поженились, тем выше."""
    return await _fetchall(
        "SELECT user1_id, user2_id, married_at, expires_at FROM marriages "
        "WHERE chat_id = %s ORDER BY married_at ASC, id ASC LIMIT %s",
        (chat_id, limit),
    )


async def list_expired_marriages(limit: int = 200) -> list[dict]:
    """Просроченные браки в чатах, где включён авторазвод, — для фоновой задачи.

    Режим хранится в marriage_settings; чат без своей строки живёт с дефолтом
    'off', поэтому JOIN здесь обычный, а не LEFT: нет строки — нет авторазвода.
    """
    return await _fetchall(
        "SELECT m.id, m.chat_id, m.user1_id, m.user2_id, m.expires_at FROM marriages m "
        "JOIN marriage_settings s ON s.chat_id = m.chat_id "
        "WHERE s.divorce_mode = 'auto' AND m.expires_at IS NOT NULL AND m.expires_at <= NOW() "
        "ORDER BY m.expires_at ASC LIMIT %s",
        (limit,),
    )


# ----------------------------------------------------------------------------
# Отмена расторжения брака/отношений в течение 72 часов. Перед удалением брака
# или пары снимаем снимок (payload — JSON), а «вернуть» восстанавливает его,
# если не поздно и ни один из двоих уже не в новом браке/паре. kind — 'marriage'
# или 'rel2'. dissolved_at пишем в UTC (сравнение идёт с UTC_TIMESTAMP()).
# ----------------------------------------------------------------------------
async def ensure_relationship_undo_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS relationship_undo ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "kind VARCHAR(16) NOT NULL, "
        "chat_id BIGINT NOT NULL, "
        "user_a BIGINT NOT NULL, "
        "user_b BIGINT NOT NULL, "
        "payload TEXT NOT NULL, "
        "dissolved_at DATETIME NOT NULL, "
        "INDEX idx_undo_a (kind, chat_id, user_a), "
        "INDEX idx_undo_b (kind, chat_id, user_b)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def snapshot_dissolution(kind: str, chat_id: int, user_a: int, user_b: int, payload: str) -> None:
    # Один снимок на человека: старые снимки для этих двоих убираем.
    await _execute(
        "DELETE FROM relationship_undo WHERE kind = %s AND chat_id = %s "
        "AND (user_a IN (%s, %s) OR user_b IN (%s, %s))",
        (kind, chat_id, user_a, user_b, user_a, user_b),
    )
    await _execute(
        "INSERT INTO relationship_undo (kind, chat_id, user_a, user_b, payload, dissolved_at) "
        "VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())",
        (kind, chat_id, user_a, user_b, payload),
    )


async def get_recent_dissolution(kind: str, chat_id: int, user_id: int, within_hours: int = 72) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, kind, chat_id, user_a, user_b, payload, dissolved_at FROM relationship_undo "
        "WHERE kind = %s AND chat_id = %s AND (user_a = %s OR user_b = %s) "
        "AND dissolved_at > (UTC_TIMESTAMP() - INTERVAL %s HOUR) "
        "ORDER BY dissolved_at DESC LIMIT 1",
        (kind, chat_id, user_id, user_id, within_hours),
    )


async def consume_dissolution(undo_id: int) -> None:
    await _execute("DELETE FROM relationship_undo WHERE id = %s", (undo_id,))


async def cleanup_dissolutions(hours: int = 72) -> int:
    return await _execute(
        "DELETE FROM relationship_undo WHERE dissolved_at < (UTC_TIMESTAMP() - INTERVAL %s HOUR)",
        (hours,),
    )


# ----------------------------------------------------------------------------
# Отношения (привязаны к чату) — лёгкая механика близости, отдельно от браков.
# ----------------------------------------------------------------------------
async def get_relationship(chat_id: int, user_id: int) -> Optional[dict]:
    row = await _fetchone(
        "SELECT user1_id, user2_id, points, level, started_at, last_action_at "
        "FROM relationships WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s) LIMIT 1",
        (chat_id, user_id, user_id),
    )
    if row is None:
        return None
    partner_id = row["user2_id"] if row["user1_id"] == user_id else row["user1_id"]
    return {
        "partner_id": partner_id,
        "points": row["points"],
        "level": row["level"],
        "started_at": row["started_at"],
        "last_action_at": row["last_action_at"],
    }


async def list_relationships(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Топ пар чата по очкам близости (для «отн топ») + общее количество."""
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM relationships WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user1_id, user2_id, points, level, started_at FROM relationships "
        "WHERE chat_id = %s ORDER BY points DESC, id ASC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def create_relationship(chat_id: int, user_a: int, user_b: int) -> bool:
    """Создаёт отношения атомарно; возвращает False, если один уже занят."""
    u1, u2 = sorted((user_a, user_b))
    pool = _require_pool()
    lock_name = f"relationship:{chat_id}"
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT GET_LOCK(%s, 5) AS acquired", (lock_name,))
            lock = await cur.fetchone()
            if not lock or lock["acquired"] != 1:
                return False
            try:
                await cur.execute(
                    "SELECT 1 FROM relationships "
                    "WHERE chat_id = %s AND (user1_id IN (%s, %s) OR user2_id IN (%s, %s)) LIMIT 1",
                    (chat_id, u1, u2, u1, u2),
                )
                if await cur.fetchone():
                    return False
                await cur.execute(
                    "INSERT INTO relationships (chat_id, user1_id, user2_id) VALUES (%s, %s, %s)",
                    (chat_id, u1, u2),
                )
                return True
            finally:
                await cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))


async def delete_relationship(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM relationships WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s)",
        (chat_id, user_id, user_id),
    )
    return rowcount > 0


async def set_relationship_progress(chat_id: int, user_a: int, user_b: int, points: int, level: int) -> None:
    """Обновляет очки/уровень пары (уровень уже посчитан в bot.py по RELATIONSHIP_LEVELS)."""
    u1, u2 = sorted((user_a, user_b))
    points = max(points, 0)
    await _execute(
        "UPDATE relationships SET points = %s, level = %s, last_action_at = CURRENT_TIMESTAMP "
        "WHERE chat_id = %s AND user1_id = %s AND user2_id = %s",
        (points, level, chat_id, u1, u2),
    )


# ----------------------------------------------------------------------------
# Предложения отношений («отн {ссылка}» / ответом, принимаются «+отн»)
# ----------------------------------------------------------------------------
async def create_relationship_request(chat_id: int, from_user_id: int, to_user_id: int) -> None:
    """Новое предложение перезаписывает предыдущее от того же отправителя в чате."""
    await _execute(
        "DELETE FROM relationship_requests WHERE chat_id = %s AND from_user_id = %s",
        (chat_id, from_user_id),
    )
    await _execute(
        "INSERT INTO relationship_requests (chat_id, from_user_id, to_user_id) VALUES (%s, %s, %s)",
        (chat_id, from_user_id, to_user_id),
    )


async def get_latest_relationship_request(chat_id: int, to_user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT from_user_id, to_user_id, created_at FROM relationship_requests "
        "WHERE chat_id = %s AND to_user_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
        (chat_id, to_user_id),
    )


async def delete_relationship_request(chat_id: int, from_user_id: int, to_user_id: int) -> None:
    await _execute(
        "DELETE FROM relationship_requests WHERE chat_id = %s AND from_user_id = %s AND to_user_id = %s",
        (chat_id, from_user_id, to_user_id),
    )


async def clear_relationship_requests_for(chat_id: int, user_id: int) -> None:
    """Убирает все предложения, где участвует user_id (после принятия/начала отношений)."""
    await _execute(
        "DELETE FROM relationship_requests WHERE chat_id = %s AND (from_user_id = %s OR to_user_id = %s)",
        (chat_id, user_id, user_id),
    )


# ----------------------------------------------------------------------------
# Ники (персональные для каждого чата)
# ----------------------------------------------------------------------------
async def get_nickname(chat_id: int, user_id: int) -> Optional[str]:
    row = await _fetchone(
        "SELECT nickname FROM nicknames WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row["nickname"] if row else None


async def set_nickname(chat_id: int, user_id: int, nickname: str) -> None:
    await _execute(
        "INSERT INTO nicknames (chat_id, user_id, nickname) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE nickname = VALUES(nickname)",
        (chat_id, user_id, nickname),
    )


async def delete_nickname(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM nicknames WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


# ----------------------------------------------------------------------------
# Анкета пользователя: звание, девиз, гражданство, пол, город, «о себе»
# (как у Iris, показывается в /профиль и в «Моя анкета»). Одна строка на
# пользователя в каждом чате.
# ----------------------------------------------------------------------------
async def ensure_profile_cards_table() -> None:
    """Анкеты (звание/девиз/пол/город/о себе). Раньше только в schema.sql, без
    ensure-миграции. Дополнительно: gender делаем VARCHAR, а НЕ ENUM('м','ж','др').
    Строгий режим MySQL отвергал запись в кириллический ENUM («Data truncated»),
    из-за чего смена пола падала с 500 (и в панели, и в боте «мой пол»). VARCHAR
    принимает те же значения, чтение не меняется — GENDER_LABEL/EMOJI по-прежнему
    смотрят на 'м'/'ж'/'др'. ALTER ... MODIFY идемпотентен."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS profile_cards ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "title VARCHAR(30) DEFAULT NULL, "
        "motto VARCHAR(100) DEFAULT NULL, "
        "is_citizen TINYINT(1) NOT NULL DEFAULT 0, "
        "gender VARCHAR(8) DEFAULT NULL, "
        "city VARCHAR(64) DEFAULT NULL, "
        "about_text VARCHAR(1000) DEFAULT NULL, "
        "anketa_visible TINYINT(1) NOT NULL DEFAULT 1, "
        "pinned_item VARCHAR(64) DEFAULT NULL, " 
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("profile_cards", "pinned_item", "VARCHAR(64) DEFAULT NULL")
    await _add_column_if_missing("profile_cards", "pinned_achievement", "VARCHAR(64) DEFAULT NULL")
    await _add_column_if_missing("profile_cards", "pinned_business", "VARCHAR(32) DEFAULT NULL")
    # Закреплённая рыба — id строки в fishing_net, а не ключ вида: хвастаются
    # КОНКРЕТНЫМ экземпляром со своим весом, а не «щукой вообще».
    await _add_column_if_missing("profile_cards", "pinned_fish", "BIGINT DEFAULT NULL")
    # Если таблица уже существовала с gender ENUM — конвертируем в VARCHAR.
    await _execute("ALTER TABLE profile_cards MODIFY gender VARCHAR(8) DEFAULT NULL")


async def get_profile_card(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT title, motto, is_citizen, gender, city, about_text, anketa_visible, "
        "pinned_item, active_title, pinned_achievement, pinned_business, pinned_pet, "
        "pinned_fish "
        "FROM profile_cards WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def set_pinned_fish(chat_id: int, user_id: int, fish_id: Optional[int]) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, pinned_fish) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE pinned_fish = VALUES(pinned_fish)",
        (chat_id, user_id, fish_id),
    )


async def set_title(chat_id: int, user_id: int, title: str) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, title) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE title = VALUES(title)",
        (chat_id, user_id, title),
    )


async def clear_title(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE profile_cards SET title = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def set_motto(chat_id: int, user_id: int, motto: str) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, motto) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE motto = VALUES(motto)",
        (chat_id, user_id, motto),
    )


async def clear_motto(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE profile_cards SET motto = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def set_citizenship(chat_id: int, user_id: int, is_citizen: bool) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, is_citizen) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE is_citizen = VALUES(is_citizen)",
        (chat_id, user_id, int(is_citizen)),
    )


async def list_citizens(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT user_id FROM profile_cards WHERE chat_id = %s AND is_citizen = 1 "
        "ORDER BY updated_at ASC",
        (chat_id,),
    )


async def set_gender(chat_id: int, user_id: int, gender: str) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, gender) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE gender = VALUES(gender)",
        (chat_id, user_id, gender),
    )


async def clear_gender(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE profile_cards SET gender = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def set_city(chat_id: int, user_id: int, city: str) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, city) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE city = VALUES(city)",
        (chat_id, user_id, city),
    )


async def clear_city(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE profile_cards SET city = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def set_about(chat_id: int, user_id: int, about_text: str) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, about_text) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE about_text = VALUES(about_text)",
        (chat_id, user_id, about_text),
    )


async def clear_about(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE profile_cards SET about_text = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )

async def set_pinned_item(chat_id: int, user_id: int, item_key: Optional[str]) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, pinned_item) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE pinned_item = VALUES(pinned_item)",
        (chat_id, user_id, item_key),
    )
async def set_pinned_achievement(chat_id: int, user_id: int, code: Optional[str]) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, pinned_achievement) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE pinned_achievement = VALUES(pinned_achievement)",
        (chat_id, user_id, code),
    )


async def set_pinned_business(chat_id: int, user_id: int, key: Optional[str]) -> None:
    """Какой бизнес показывать в карточке профиля. None — не показывать."""
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, pinned_business) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE pinned_business = VALUES(pinned_business)",
        (chat_id, user_id, key),
    )


async def set_anketa_visibility(chat_id: int, user_id: int, visible: bool) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, anketa_visible) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE anketa_visible = VALUES(anketa_visible)",
        (chat_id, user_id, int(visible)),
    )

async def ensure_user_birthdays_table() -> None:
    """Дни рождения пользователей (глобально, не привязано к чату) —
    для авто-поздравления в группах, где бот видел пользователя."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS user_birthdays ("
        "user_id BIGINT NOT NULL PRIMARY KEY, "
        "birth_day TINYINT NOT NULL, "
        "birth_month TINYINT NOT NULL, "
        "birth_year SMALLINT DEFAULT NULL, "
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
# ---------------------------------------------------------------------------
# Дни рождения: глобально по user_id (не привязано к chat_id), т.к. один
# человек может быть в нескольких группах бота — поздравляем во всех сразу.
# ---------------------------------------------------------------------------



async def set_birthday(user_id: int, day: int, month: int, year: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO user_birthdays (user_id, birth_day, birth_month, birth_year) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE birth_day = VALUES(birth_day), "
        "birth_month = VALUES(birth_month), birth_year = VALUES(birth_year)",
        (user_id, day, month, year),
    )


async def get_birthday(user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT birth_day, birth_month, birth_year FROM user_birthdays WHERE user_id = %s",
        (user_id,),
    )


async def clear_birthday(user_id: int) -> None:
    await _execute("DELETE FROM user_birthdays WHERE user_id = %s", (user_id,))


async def list_birthdays_for_day(day: int, month: int) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, birth_year FROM user_birthdays WHERE birth_day = %s AND birth_month = %s",
        (day, month),
    )

# Здесь лежала вторая, дословная копия set_birthday/get_birthday/
# list_birthdays_for_day. Питон оставлял в модуле только её, а первая (вместе
# с clear_birthday между ними) была мёртвой — правка «верхней» копии не дала
# бы никакого эффекта. Копия удалена, рабочими остались функции выше.


# ----------------------------------------------------------------------------
# Муты (привязаны к чату)
# ----------------------------------------------------------------------------
async def add_mute(
    chat_id: int,
    user_id: int,
    muted_by: int,
    muted_until: Optional[datetime],
    reason: Optional[str],
) -> None:
    await _execute(
        "INSERT INTO mutes (chat_id, user_id, muted_by, muted_until, reason) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE muted_by = VALUES(muted_by), "
        "muted_until = VALUES(muted_until), reason = VALUES(reason), "
        "created_at = CURRENT_TIMESTAMP",
        (chat_id, user_id, muted_by, muted_until, reason),
    )


async def remove_mute(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM mutes WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


async def get_mute(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT muted_by, muted_until, reason, created_at FROM mutes "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def list_mutes(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM mutes WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user_id, muted_by, muted_until, reason, created_at FROM mutes "
        "WHERE chat_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


# ----------------------------------------------------------------------------
# Баны (привязаны к чату)
# ----------------------------------------------------------------------------
async def add_ban(chat_id: int, user_id: int, banned_by: int, reason: Optional[str]) -> None:
    await _execute(
        "INSERT INTO bans (chat_id, user_id, banned_by, reason) VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE banned_by = VALUES(banned_by), reason = VALUES(reason), "
        "created_at = CURRENT_TIMESTAMP",
        (chat_id, user_id, banned_by, reason),
    )


async def remove_ban(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM bans WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


async def list_bans(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM bans WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user_id, banned_by, reason, created_at FROM bans "
        "WHERE chat_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def ensure_warn_columns() -> None:
    """Добавляет в warns колонки:
    - expires_at — срок действия варна (по умолчанию варны не вечные, а сгорают
      через неделю, см. WARN_DEFAULT_DURATION в bot.py);
    - message_id — id сообщения, на котором выдали варн (сообщение нарушителя,
      если варн был ответом; иначе сама команда). По нему список «варны» делает
      дату ссылкой t.me/c/… на место выдачи. NULL у старых варнов — без ссылки."""
    await _add_column_if_missing("warns", "expires_at", "DATETIME NULL")
    await _add_column_if_missing("warns", "message_id", "BIGINT NULL")


# ----------------------------------------------------------------------------
# Предупреждения (варны), привязаны к чату. Как у Iris: несколько варнов
# копятся, при достижении лимита — автоматический бан (логика лимита в bot.py).
# У каждого варна есть срок действия (expires_at) — по умолчанию месяц,
# либо явно указанный при выдаче («варн 7д причина»). Все выборки/подсчёты
# ниже учитывают только ещё не истёкшие варны — сгоревший варн не мешает
# новым (не добивает до лимита) и не показывается в списке.
# ----------------------------------------------------------------------------
async def add_warn(
    chat_id: int,
    user_id: int,
    warned_by: int,
    reason: Optional[str],
    expires_at: Optional[datetime] = None,
    message_id: Optional[int] = None,
) -> int:
    """Добавляет варн и возвращает текущее количество ещё активных варнов у пользователя."""
    await _execute(
        "INSERT INTO warns (chat_id, user_id, warned_by, reason, expires_at, message_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (chat_id, user_id, warned_by, reason, expires_at, message_id),
    )
    return await count_warns(chat_id, user_id)


async def update_last_warn_message_id(chat_id: int, user_id: int, message_id: int) -> None:
    """Переставляет ссылку последнего варна на другое сообщение.

    Нужно потому, что сообщение с командой «варн» удаляется сразу после
    выдачи (чтобы «&варн» не выдавал себя амперсандом). Если варн выдали не
    ответом, а по @username, то ссылаться было бы не на что — ставим карточку
    бота: она остаётся в чате и показывает ровно то же самое.
    """
    await _execute(
        "UPDATE warns SET message_id = %s WHERE chat_id = %s AND user_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (message_id, chat_id, user_id),
    )


async def count_warns(chat_id: int, user_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM warns "
        "WHERE chat_id = %s AND user_id = %s AND (expires_at IS NULL OR expires_at > NOW())",
        (chat_id, user_id),
    )
    return int(row["total"] if row else 0)


async def list_warns(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT id, warned_by, reason, created_at, expires_at, message_id FROM warns "
        "WHERE chat_id = %s AND user_id = %s AND (expires_at IS NULL OR expires_at > NOW()) "
        "ORDER BY created_at DESC",
        (chat_id, user_id),
    )


async def remove_last_warn(chat_id: int, user_id: int) -> bool:
    """Снимает самый свежий ещё активный варн пользователя. True, если было что снимать."""
    row = await _fetchone(
        "SELECT id FROM warns WHERE chat_id = %s AND user_id = %s "
        "AND (expires_at IS NULL OR expires_at > NOW()) "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (chat_id, user_id),
    )
    if not row:
        return False
    await _execute("DELETE FROM warns WHERE id = %s", (row["id"],))
    return True


async def clear_warns(chat_id: int, user_id: int) -> int:
    """Снимает все варны пользователя (в т.ч. уже истёкшие — полная очистка), возвращает сколько было снято."""
    return await _execute(
        "DELETE FROM warns WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


async def purge_expired_warns() -> int:
    """Физически удаляет сгоревшие варны (хозяйственная уборка — на подсчёт
    и без этого не влияют, см. фильтр expires_at в count_warns/list_warns)."""
    return await _execute("DELETE FROM warns WHERE expires_at IS NOT NULL AND expires_at <= NOW()")


# ----------------------------------------------------------------------------
# Правила чата (свой текст на каждую группу)
# ----------------------------------------------------------------------------
async def get_rules(chat_id: int) -> Optional[str]:
    row = await _fetchone("SELECT rules_text FROM chat_rules WHERE chat_id = %s", (chat_id,))
    return row["rules_text"] if row else None


async def set_rules(chat_id: int, text: str, updated_by: Optional[int] = None) -> None:
    await _execute(
        "INSERT INTO chat_rules (chat_id, rules_text, updated_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE rules_text = VALUES(rules_text), updated_by = VALUES(updated_by), "
        "updated_at = CURRENT_TIMESTAMP",
        (chat_id, text, updated_by),
    )


# ----------------------------------------------------------------------------
# Жалобы (полностью в личке бота). Пользователь жалуется на кого-то, выбирая
# анонимность (видят ли админы, кто пожаловался) и указывая причину.
# Админы просматривают, принимают/отклоняют — тоже в личке.
# ----------------------------------------------------------------------------
async def add_complaint(target_id: int, reporter_id: int, anonymous: bool, reason: str) -> int:
    return await _execute(
        "INSERT INTO complaints (target_id, reporter_id, anonymous, reason) "
        "VALUES (%s, %s, %s, %s)",
        (target_id, reporter_id, 1 if anonymous else 0, reason),
    )


async def list_complaint_targets() -> list[dict]:
    """Пользователи, на которых есть хоть одна жалоба: [{target_id, total, pending}, ...]."""
    return await _fetchall(
        "SELECT target_id, COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending "
        "FROM complaints GROUP BY target_id ORDER BY pending DESC, total DESC"
    )


async def get_known_names(user_ids: list[int]) -> dict:
    """Имена по списку user_id, из любого чата, где бот их видел.

    Жалобы хранятся без chat_id, поэтому обычный get_known_user (он требует
    чат) здесь не годится. Берём произвольную запись на человека: имя у него
    одно на все чаты.
    """
    ids = [int(uid) for uid in user_ids if uid]
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    rows = await _fetchall(
        f"SELECT user_id, MAX(full_name) AS full_name, MAX(username) AS username "
        f"FROM known_users WHERE user_id IN ({placeholders}) GROUP BY user_id",
        tuple(ids),
    )
    return {int(row["user_id"]): row for row in rows}


async def count_pending_complaints() -> int:
    row = await _fetchone("SELECT COUNT(*) AS total FROM complaints WHERE status = 'pending'")
    return int(row["total"] if row else 0)


async def list_complaints_for_target(target_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT id, reporter_id, anonymous, reason, status, created_at, decided_by, decided_at "
        "FROM complaints WHERE target_id = %s ORDER BY created_at DESC",
        (target_id,),
    )


async def get_complaint(complaint_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, target_id, reporter_id, anonymous, reason, status, created_at "
        "FROM complaints WHERE id = %s",
        (complaint_id,),
    )


async def set_complaint_status(complaint_id: int, status: str, decided_by: int) -> None:
    if status not in ("accepted", "declined", "pending"):
        raise ValueError("Недопустимый статус жалобы")
    await _execute(
        "UPDATE complaints SET status = %s, decided_by = %s, decided_at = CURRENT_TIMESTAMP "
        "WHERE id = %s",
        (status, decided_by, complaint_id),
    )


async def delete_complaint(complaint_id: int) -> None:
    """Полностью удаляет саму жалобу (запись в complaints) — не человека,
    на которого жаловались, и не список известных пользователей (known_users)."""
    await _execute("DELETE FROM complaints WHERE id = %s", (complaint_id,))


# ----------------------------------------------------------------------------
# Анонимные сообщения (личка бота): пользователь выбирает адресата из списка
# известных участников чата (тот же роутер known_users, что и для жалоб) и
# отправляет ему текст без указания, кто автор. sender_id всё равно
# сохраняется в БД — получателю он не показывается никогда, но нужен
# админам для разбора злоупотреблений (см. mark_anon_message_reported).
# ----------------------------------------------------------------------------
async def ensure_anon_messages_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS anon_messages ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "sender_id BIGINT NOT NULL, "
        "target_id BIGINT NOT NULL, "
        "text TEXT NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "delivered TINYINT(1) NOT NULL DEFAULT 1, "
        "reported TINYINT(1) NOT NULL DEFAULT 0, "
        "reported_at TIMESTAMP NULL, "
        "INDEX idx_anon_sender_time (sender_id, created_at), "
        "INDEX idx_anon_target (target_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_anon_opt_out_table() -> None:
    """Пользователи, отключившие получение анонимных сообщений."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS anon_opt_out ("
        "user_id BIGINT NOT NULL PRIMARY KEY, "
        "opted_out_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_anon_deliveries_table() -> None:
    """Карта «доставленное сообщение в личке -> кому отвечать», нужна, чтобы
    Telegram-Reply (ответ свайпом/долгим тапом) на анонимку можно было
    сматчить с тем, кому переслать ответ, и вести анонимную переписку
    туда-обратно. root_id — id самого первого сообщения треда в anon_messages
    (используется для группировки и разбора жалоб на переписку)."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS anon_message_deliveries ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "root_id BIGINT NOT NULL, "
        "sender_id BIGINT NOT NULL, "
        "recipient_id BIGINT NOT NULL, "
        "recipient_message_id BIGINT NOT NULL, "
        "text TEXT NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_recipient_message (recipient_id, recipient_message_id), "
        "INDEX idx_root (root_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_anon_delivery(root_id: int, sender_id: int, recipient_id: int, recipient_message_id: int, text: str) -> int:
    return await _execute(
        "INSERT INTO anon_message_deliveries (root_id, sender_id, recipient_id, recipient_message_id, text) "
        "VALUES (%s, %s, %s, %s, %s)",
        (root_id, sender_id, recipient_id, recipient_message_id, text),
    )


async def get_anon_delivery(recipient_id: int, recipient_message_id: int) -> Optional[dict]:
    """По (кому доставлено, id сообщения в его личке с ботом) находит запись
    треда — используется, чтобы понять, кому переслать Reply-ответ."""
    return await _fetchone(
        "SELECT id, root_id, sender_id, recipient_id, recipient_message_id, text, created_at "
        "FROM anon_message_deliveries WHERE recipient_id = %s AND recipient_message_id = %s",
        (recipient_id, recipient_message_id),
    )


async def add_anon_message(chat_id: int, sender_id: int, target_id: int, text: str, delivered: bool = True) -> int:
    return await _execute(
        "INSERT INTO anon_messages (chat_id, sender_id, target_id, text, delivered) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, sender_id, target_id, text, 1 if delivered else 0),
    )


async def count_recent_anon_messages(sender_id: int, since_minutes: int) -> int:
    """Сколько анонимных сообщений отправитель отправил за последние `since_minutes` минут —
    используется для рейт-лимита."""
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM anon_messages "
        "WHERE sender_id = %s AND created_at > NOW() - INTERVAL %s MINUTE",
        (sender_id, since_minutes),
    )
    return int(row["total"] if row else 0)


async def set_anon_message_delivered(message_id: int, delivered: bool) -> None:
    await _execute(
        "UPDATE anon_messages SET delivered = %s WHERE id = %s",
        (1 if delivered else 0, message_id),
    )


async def get_anon_message(message_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, chat_id, sender_id, target_id, text, created_at, reported "
        "FROM anon_messages WHERE id = %s",
        (message_id,),
    )


async def mark_anon_message_reported(message_id: int) -> Optional[dict]:
    """Помечает сообщение как пожалованное и возвращает его строку (с sender_id — для
    админов, которым нужно разобраться в жалобе). Идемпотентно: если уже помечено,
    просто возвращает текущую запись без повторного UPDATE."""
    row = await get_anon_message(message_id)
    if row is None:
        return None
    if not row["reported"]:
        await _execute(
            "UPDATE anon_messages SET reported = 1, reported_at = CURRENT_TIMESTAMP WHERE id = %s",
            (message_id,),
        )
        row["reported"] = 1
    return row


async def is_anon_opt_out(user_id: int) -> bool:
    row = await _fetchone("SELECT user_id FROM anon_opt_out WHERE user_id = %s", (user_id,))
    return row is not None


async def set_anon_opt_out(user_id: int, opted_out: bool) -> None:
    if opted_out:
        await _execute(
            "INSERT IGNORE INTO anon_opt_out (user_id) VALUES (%s)", (user_id,)
        )
    else:
        await _execute("DELETE FROM anon_opt_out WHERE user_id = %s", (user_id,))


# ----------------------------------------------------------------------------
# Счётчик сообщений (привязан к чату)
# ----------------------------------------------------------------------------
async def increment_message_count(chat_id: int, user_id: int) -> None:
    # last_message_at / first_seen_at — в UTC (UTC_TIMESTAMP()), а не
    # CURRENT_TIMESTAMP: последняя отражает часовой пояс сессии MySQL, а весь
    # остальной код (профиль сравнивает с datetime.utcnow()) считает время в
    # UTC. Ровно этот же перекос уже ловили на known_users.last_seen_at (см.
    # upsert_known_user): если сессия MySQL не в UTC, метка «уезжает» в будущее,
    # разница utcnow()-last_message_at выходит отрицательной, обрезается в 0 —
    # и «Последний актив» у всех показывался «только что». Явное присваивание
    # перебивает и колоночный DEFAULT/ON UPDATE CURRENT_TIMESTAMP.
    await _execute(
        "INSERT INTO message_stats (chat_id, user_id, message_count, first_seen_at, last_message_at) "
        "VALUES (%s, %s, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP()) "
        "ON DUPLICATE KEY UPDATE message_count = message_count + 1, "
        "last_message_at = UTC_TIMESTAMP()",
        (chat_id, user_id),
    )


# ----------------------------------------------------------------------------
# Известные боту участники чата (кто реально писал сообщения). Bot API не
# отдаёт ботам полный список участников группы — только тех, кого бот видел
# сам. Используется для выбора цели жалобы из списка (кнопками, а не по ID).
# ----------------------------------------------------------------------------
async def ensure_stats_columns() -> None:
    """Миграция на лету для модуля 9 «Статистическая информация»:
    - known_users.first_seen_at — момент первого появления участника в чате
      (нужен для «Олды» / «Новички»), не трогается при повторных upsert;
    - known_users.invited_by — кто пригласил участника (для «Кто добавил»);
    - таблица message_daily — посуточные счётчики сообщений, нужны для
      периодической статистики («Стата сутки/неделя/месяц»)."""
    await _add_column_if_missing(
        "known_users", "first_seen_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
    await _add_column_if_missing("known_users", "invited_by", "BIGINT NULL")
    await _execute(
        "CREATE TABLE IF NOT EXISTS message_daily ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "day DATE NOT NULL, "
        "message_count INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, day), "
        "INDEX idx_message_daily_chat_day (chat_id, day)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def upsert_known_user(
    chat_id: int, user_id: int, full_name: str, username: Optional[str], invited_by: Optional[int] = None
) -> None:
    # last_seen_at — в UTC (UTC_TIMESTAMP()), а не CURRENT_TIMESTAMP: последняя
    # отражает часовой пояс сессии/сервера MySQL, а весь остальной код (в т.ч.
    # datetime.utcnow() в bot.py и UTC_TIMESTAMP() в остальных таблицах, см.
    # rest_requests/chat_roles) считает время в UTC. При несовпадении часового
    # пояса last_seen_at «уезжает» в будущее относительно UTC, из-за чего
    # разница datetime.utcnow() - last_seen получается отрицательной и любой
    # порог вида «<= N минут назад» (например, онлайн-статус в «Кто админ»)
    # выполняется всегда — отсюда все админы показывались зелёными.
    await _execute(
        "INSERT INTO known_users (chat_id, user_id, full_name, username, invited_by) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE full_name = VALUES(full_name), username = VALUES(username), "
        "last_seen_at = UTC_TIMESTAMP()",
        (chat_id, user_id, full_name[:255], username, invited_by),
    )


async def delete_known_user(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM known_users WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def list_known_users(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM known_users WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user_id, full_name, username FROM known_users WHERE chat_id = %s "
        "ORDER BY last_seen_at DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def list_known_users_with_counts(chat_id: int, limit: int = 500) -> list[dict]:
    """Известные боту участники чата вместе со счётчиком сообщений и датами
    (для панели: поиск/сортировка по активности). LEFT JOIN — те, кто ни разу
    не писал (в message_stats их нет), тоже попадают, с 0 сообщений."""
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, "
        "COALESCE(ms.message_count, 0) AS message_count, "
        "ms.first_seen_at, ms.last_message_at, ku.last_seen_at "
        "FROM known_users ku "
        "LEFT JOIN message_stats ms ON ms.chat_id = ku.chat_id AND ms.user_id = ku.user_id "
        "WHERE ku.chat_id = %s ORDER BY ku.last_seen_at DESC LIMIT %s",
        (chat_id, limit),
    )


async def search_known_users(chat_id: int, query: str, limit: int = 8, offset: int = 0) -> tuple[list[dict], int]:
    """Поиск по имени/юзернейму среди известных боту участников чата."""
    like = f"%{query}%"
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM known_users WHERE chat_id = %s "
        "AND (full_name LIKE %s OR username LIKE %s)",
        (chat_id, like, like),
    )
    rows = await _fetchall(
        "SELECT user_id, full_name, username FROM known_users WHERE chat_id = %s "
        "AND (full_name LIKE %s OR username LIKE %s) "
        "ORDER BY last_seen_at DESC LIMIT %s OFFSET %s",
        (chat_id, like, like, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


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


async def get_known_user(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT user_id, full_name, username FROM known_users WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def list_user_chats(user_id: int) -> list[int]:
    """Чаты, где бот видел этого пользователя. Нужно участнику на сайте, чтобы
    выбрать чат: брак и отношения привязаны к чату."""
    rows = await _fetchall(
        "SELECT DISTINCT chat_id FROM known_users WHERE user_id = %s", (user_id,)
    )
    return [int(r["chat_id"]) for r in rows]


async def list_known_users_without_role(chat_id: int, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """Известные боту участники этого чата, у которых нет ни занятой, ни
    забронированной роли (chat_roles.status IN ('taken','reserved')).
    Нужно для команды «участники без ролей» — показать, кого ещё можно
    позвать выбрать себе роль. Как и остальные *_known_users выше, не
    проверяет актуальное членство в чате через Bot API (лишние запросы на
    большом чате) — считает того, кого бот видел, известным участником."""
    holders_subquery = (
        "SELECT holder_user_id AS user_id FROM chat_roles "
        "WHERE chat_id = %s AND status = 'taken' AND holder_user_id IS NOT NULL "
        "UNION "
        "SELECT reserved_user_id AS user_id FROM chat_roles "
        "WHERE chat_id = %s AND status = 'reserved' AND reserved_user_id IS NOT NULL"
    )
    count_row = await _fetchone(
        f"SELECT COUNT(*) AS total FROM known_users ku "
        f"WHERE ku.chat_id = %s AND ku.user_id NOT IN ({holders_subquery})",
        (chat_id, chat_id, chat_id),
    )
    rows = await _fetchall(
        f"SELECT ku.user_id, ku.full_name, ku.username FROM known_users ku "
        f"WHERE ku.chat_id = %s AND ku.user_id NOT IN ({holders_subquery}) "
        f"ORDER BY ku.last_seen_at DESC LIMIT %s OFFSET %s",
        (chat_id, chat_id, chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def get_known_user_by_username_in_chat(chat_id: int, username: str) -> Optional[dict]:
    """Ищет пользователя ИМЕННО этого чата по username (без @, регистр не
    важен). В отличие от get_known_user_by_username ниже (глобальный поиск
    по всем чатам, нужен для команд ролей из ЛС), эта версия скоуплена на
    конкретный chat_id — используется резолвером цели команд модерации
    (resolve_command_target), где важно найти того, кто известен именно
    в этом чате, а не тёзку из другого."""
    return await _fetchone(
        "SELECT user_id, full_name, username FROM known_users "
        "WHERE chat_id = %s AND LOWER(username) = LOWER(%s)",
        (chat_id, username),
    )


async def get_known_user_by_username(username: str) -> Optional[dict]:
    """Поиск известного боту участника по юзернейму — БЕЗ привязки к
    конкретному чату. Юзернеймы в Telegram уникальны глобально, а бот мог
    увидеть человека в любом чате (не обязательно в том, что привязан
    командой «чат сюда» для ролей), поэтому чат здесь не фильтруется —
    берём самую свежую запись по этому user_id среди всех чатов.
    Нужно для команд вида «роль отдать @username Название»."""
    return await _fetchone(
        "SELECT ku.user_id, ku.full_name, ku.username "
        "FROM known_users ku "
        "INNER JOIN ("
        "  SELECT user_id, MAX(last_seen_at) AS max_seen FROM known_users "
        "  WHERE LOWER(username) = LOWER(%s) GROUP BY user_id"
        ") latest ON latest.user_id = ku.user_id AND latest.max_seen = ku.last_seen_at "
        "WHERE LOWER(ku.username) = LOWER(%s) LIMIT 1",
        (username, username),
    )


async def get_inviter(chat_id: int, user_id: int) -> Optional[int]:
    """Кто пригласил указанного участника в чат (None, если неизвестно —
    например, бот не видел момент вступления)."""
    row = await _fetchone(
        "SELECT invited_by FROM known_users WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row["invited_by"] if row and row.get("invited_by") else None


async def list_oldtimers(chat_id: int, limit: int = 10) -> list[dict]:
    """Самые старые (по первому появлению в чате) известные боту участники.
    last_message_at (из message_stats) — чтобы отметить недавно активных
    участников значком 🔥 (см. cmd_oldtimers в bot.py)."""
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, ku.first_seen_at, ms.last_message_at "
        "FROM known_users ku "
        "LEFT JOIN message_stats ms ON ms.chat_id = ku.chat_id AND ms.user_id = ku.user_id "
        "WHERE ku.chat_id = %s ORDER BY ku.first_seen_at ASC LIMIT %s",
        (chat_id, limit),
    )


async def list_newcomers(chat_id: int, limit: int = 10) -> list[dict]:
    """Недавно появившиеся (по первому появлению в чате) известные боту участники."""
    return await _fetchall(
        "SELECT user_id, full_name, username, first_seen_at FROM known_users "
        "WHERE chat_id = %s ORDER BY first_seen_at DESC LIMIT %s",
        (chat_id, limit),
    )


async def list_new_members_since(chat_id: int, since: datetime, limit: int = 200) -> list[dict]:
    """Известные боту участники, впервые появившиеся в чате не раньше `since`
    (используется командой «нью {период}», например «нью 2д»)."""
    return await _fetchall(
        "SELECT user_id, full_name, username, first_seen_at FROM known_users "
        "WHERE chat_id = %s AND first_seen_at >= %s ORDER BY first_seen_at DESC LIMIT %s",
        (chat_id, since, limit),
    )


async def list_inactive(chat_id: int, before: datetime, limit: int = 30) -> list[dict]:
    """Участники, не проявлявшие актив (не писавшие сообщений) с указанного
    момента. Те, у кого сейчас активный одобренный рест, в список не попадают —
    они не считаются неактивными, пока рест действует.

    Считаются ТОЛЬКО те, кто сейчас в чате. known_users — это все, кого бот
    когда-либо видел, и оттуда никто не удаляется; ростер вышедших чистит
    handle_member_left, но только в current_users. Без соединения с ростером
    список неактивных возглавляли вышедшие: у них last_seen_at самый старый,
    а сортировка идёт по возрастанию — то есть первыми шли как раз те, кого
    в чате давно нет.
    """
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, ku.last_seen_at FROM known_users ku "
        "JOIN current_users cu ON cu.chat_id = ku.chat_id AND cu.user_id = ku.user_id "
        "WHERE ku.chat_id = %s AND ku.last_seen_at < %s "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM rest_requests r WHERE r.chat_id = ku.chat_id AND r.user_id = ku.user_id "
        "  AND r.status = 'approved' AND r.expires_at > UTC_TIMESTAMP()"
        ") "
        "ORDER BY ku.last_seen_at ASC LIMIT %s",
        (chat_id, before, limit),
    )


async def list_silent(chat_id: int, before: datetime, limit: int = 30) -> list[dict]:
    """Участники, вступившие раньше указанного момента и не написавшие ни
    одного сообщения (молчуны).

    Как и у list_inactive — только те, кто сейчас в чате: вышедшие остаются
    в known_users навсегда и иначе висели бы в списке молчунов вечно.
    """
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, ku.first_seen_at FROM known_users ku "
        "JOIN current_users cu ON cu.chat_id = ku.chat_id AND cu.user_id = ku.user_id "
        "LEFT JOIN message_stats ms ON ms.chat_id = ku.chat_id AND ms.user_id = ku.user_id "
        "WHERE ku.chat_id = %s AND ku.first_seen_at < %s "
        "AND (ms.message_count IS NULL OR ms.message_count = 0) "
        "ORDER BY ku.first_seen_at ASC LIMIT %s",
        (chat_id, before, limit),
    )


async def list_nicknames(chat_id: int, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM nicknames WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user_id, nickname FROM nicknames WHERE chat_id = %s "
        "ORDER BY nickname LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def delete_all_nicknames(chat_id: int) -> int:
    return await _execute("DELETE FROM nicknames WHERE chat_id = %s", (chat_id,))


async def get_last_seen_map(user_ids: list[int]) -> dict[int, datetime]:
    """Момент последней активности (последнего сообщения) каждого из указанных
    user_id — максимум по всем чатам, где бот его знает. Используется как
    практическая замена «онлайн-статуса» (Bot API реального presence не даёт):
    «онлайн», если писал совсем недавно, см. ONLINE_THRESHOLD в bot.py.
    Тех, кого бот вообще не видел ни разу, в возвращённом dict не будет."""
    if not user_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(user_ids))
    rows = await _fetchall(
        f"SELECT user_id, MAX(last_seen_at) AS last_seen_at FROM known_users "
        f"WHERE user_id IN ({placeholders}) GROUP BY user_id",
        tuple(user_ids),
    )
    return {row["user_id"]: row["last_seen_at"] for row in rows if row.get("last_seen_at")}


async def list_known_users_registry() -> list[dict]:
    """Последняя известная запись (имя/юзернейм) по каждому user_id, вне привязки к
    конкретному чату — для глобального кэша отображения тегов/имён вместо ID."""
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username "
        "FROM known_users ku "
        "INNER JOIN ("
        "  SELECT user_id, MAX(last_seen_at) AS max_seen FROM known_users GROUP BY user_id"
        ") latest ON latest.user_id = ku.user_id AND latest.max_seen = ku.last_seen_at"
    )


async def get_message_stats(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT message_count, first_seen_at, last_message_at FROM message_stats "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def get_activity_breakdown(chat_id: int, user_id: int) -> dict:
    """Сообщения пользователя в этом чате за сегодня / текущую неделю / текущий
    месяц (из посуточных счётчиков message_daily) — для строки профиля
    «Актив (д|н|м|весь)», как у Iris. «Весь» берётся отдельно из
    message_stats.message_count (общий счётчик, не зависит от message_daily)."""
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    row = await _fetchone(
        "SELECT "
        "COALESCE(SUM(CASE WHEN day = %s THEN message_count ELSE 0 END), 0) AS today_count, "
        "COALESCE(SUM(CASE WHEN day >= %s THEN message_count ELSE 0 END), 0) AS week_count, "
        "COALESCE(SUM(CASE WHEN day >= %s THEN message_count ELSE 0 END), 0) AS month_count "
        "FROM message_daily WHERE chat_id = %s AND user_id = %s",
        (today, week_start, month_start, chat_id, user_id),
    )
    return row or {"today_count": 0, "week_count": 0, "month_count": 0}


async def get_message_rank(chat_id: int, user_id: int) -> Optional[int]:
    """Место пользователя в топе чата по количеству сообщений (1 = самый активный)."""
    row = await _fetchone(
        "SELECT COUNT(*) + 1 AS user_rank FROM message_stats "
        "WHERE chat_id = %s AND message_count > ("
        "    SELECT message_count FROM message_stats WHERE chat_id = %s AND user_id = %s"
        ")",
        (chat_id, chat_id, user_id),
    )
    return row["user_rank"] if row else None


async def list_top_messages(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM message_stats WHERE chat_id = %s", (chat_id,)
    )
    rows = await _fetchall(
        "SELECT user_id, message_count FROM message_stats WHERE chat_id = %s "
        "ORDER BY message_count DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def reset_message_stats(chat_id: int) -> None:
    await _execute("DELETE FROM message_stats WHERE chat_id = %s", (chat_id,))


async def sum_messages_period(chat_id: int, since_day) -> int:
    """Сколько всего сообщений в чате за период — итог под списком топа.

    since_day=None — за всё время: тогда считаем по message_stats, потому что
    message_daily хранит только посуточную нарезку и за всю историю её может
    не быть (счётчики появились раньше, чем посуточные).
    """
    if since_day is None:
        return await get_chat_total_messages(chat_id)
    row = await _fetchone(
        "SELECT SUM(message_count) AS total FROM message_daily "
        "WHERE chat_id = %s AND day >= %s",
        (chat_id, since_day),
    )
    return int(row["total"]) if row and row.get("total") else 0


async def list_citizens(chat_id: int) -> set[int]:
    """Кто получил гражданство чата — одним запросом на весь список топа,
    а не по строке на каждого участника."""
    rows = await _fetchall(
        "SELECT user_id FROM profile_cards WHERE chat_id = %s AND is_citizen = TRUE",
        (chat_id,),
    )
    return {int(r["user_id"]) for r in rows}


async def get_chat_total_messages(chat_id: int) -> int:
    row = await _fetchone(
        "SELECT SUM(message_count) AS total FROM message_stats WHERE chat_id = %s", (chat_id,)
    )
    return int(row["total"]) if row and row.get("total") else 0


# ----------------------------------------------------------------------------
# Посуточные счётчики сообщений — основа периодической статистики
# («Стата сутки/неделя/месяц», см. ensure_stats_columns() выше).
# ----------------------------------------------------------------------------
async def increment_daily_count(chat_id: int, user_id: int, day) -> None:
    await _execute(
        "INSERT INTO message_daily (chat_id, user_id, day, message_count) VALUES (%s, %s, %s, 1) "
        "ON DUPLICATE KEY UPDATE message_count = message_count + 1",
        (chat_id, user_id, day),
    )


async def list_daily_counts_for_user(chat_id: int, user_id: int, since_day) -> list[dict]:
    """Посуточные счётчики сообщений конкретного пользователя с since_day по
    сегодня — сырые точки для графика активности профиля («кто я»/«профиль»,
    см. activity_chart.py). Дни без сообщений в выборке просто отсутствуют —
    достраивает их до непрерывного ряда уже render_activity_chart()."""
    return await _fetchall(
        "SELECT day, message_count FROM message_daily "
        "WHERE chat_id = %s AND user_id = %s AND day >= %s ORDER BY day",
        (chat_id, user_id, since_day),
    )


async def list_today_active_users(chat_id: int, day, limit: int = 200) -> list[dict]:
    """Кто сегодня писал в чат — по посуточным счётчикам message_daily.

    Порядок по числу сообщений: если получателей окажется больше лимита,
    отсечь логичнее самых молчаливых, а не случайных.
    """
    return await _fetchall(
        "SELECT user_id, message_count FROM message_daily "
        "WHERE chat_id = %s AND day = %s AND message_count > 0 "
        "ORDER BY message_count DESC LIMIT %s",
        (chat_id, day, limit),
    )


async def list_daily_counts_for_chat(chat_id: int, since_day) -> list[dict]:
    """Посуточные счётчики сообщений ВСЕГО чата (сумма по всем участникам) с
    since_day по сегодня — то же самое, что list_daily_counts_for_user, но
    для графика «Чат стата» / карточки «Чат инфо» (см. render_activity_chart
    в activity_chart.py — формат строк {"day":..., "message_count":...}
    у обеих функций одинаковый, поэтому рендерится тем же кодом)."""
    return await _fetchall(
        "SELECT day, SUM(message_count) AS message_count FROM message_daily "
        "WHERE chat_id = %s AND day >= %s GROUP BY day ORDER BY day",
        (chat_id, since_day),
    )


# ----------------------------------------------------------------------------
# Почасовые счётчики сообщений — основа для «Стата по часам» (профиль
# пользователя) и «Чат стата по часам» (чат целиком). В отличие от
# message_daily (один день = одна строка), тут ещё и час суток (0-23), что
# позволяет строить как «типичный» почасовой профиль активности (агрегат по
# многим дням), так и срез за конкретные последние 24 часа.
# ----------------------------------------------------------------------------
async def ensure_hourly_stats_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS message_hourly ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "day DATE NOT NULL, "
        "hour TINYINT NOT NULL, "
        "message_count INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, day, hour), "
        "INDEX idx_message_hourly_chat_day_hour (chat_id, day, hour)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def increment_hourly_count(chat_id: int, user_id: int, day, hour: int) -> None:
    await _execute(
        "INSERT INTO message_hourly (chat_id, user_id, day, hour, message_count) "
        "VALUES (%s, %s, %s, %s, 1) "
        "ON DUPLICATE KEY UPDATE message_count = message_count + 1",
        (chat_id, user_id, day, hour),
    )


async def list_hourly_pattern_for_user(chat_id: int, user_id: int, since_day) -> list[dict]:
    """«Типичная» почасовая активность пользователя — сумма сообщений по
    каждому часу суток (0-23), агрегированная по всем дням с since_day.
    Используется командой «Стата по часам»."""
    return await _fetchall(
        "SELECT hour, SUM(message_count) AS message_count FROM message_hourly "
        "WHERE chat_id = %s AND user_id = %s AND day >= %s "
        "GROUP BY hour ORDER BY hour",
        (chat_id, user_id, since_day),
    )


async def list_hourly_last_24h_for_chat(chat_id: int) -> list[dict]:
    """Почасовая активность ВСЕГО чата за последние ровно 24 часа (24
    часовых корзины, а не «типичный день») — используется командой «Чат
    стата по часам». Час считается в UTC. Разбито на два диапазона, потому
    что окно в 24 часа почти всегда пересекает границу суток:
      — вчера, часы после текущего часа (эксклюзивно);
      — сегодня, часы по текущий час (включительно)."""
    now = datetime.utcnow()
    today = now.date()
    yesterday = today - timedelta(days=1)
    current_hour = now.hour
    return await _fetchall(
        "SELECT day, hour, SUM(message_count) AS message_count FROM message_hourly "
        "WHERE chat_id = %s AND ("
        "  (day = %s AND hour > %s) OR (day = %s AND hour <= %s)"
        ") GROUP BY day, hour ORDER BY day, hour",
        (chat_id, yesterday, current_hour, today, current_hour),
    )


async def list_top_messages_period(chat_id: int, since_day, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Топ по сообщениям за период since_day..сегодня. since_day=None → вся история
    (используется message_stats напрямую вместо message_daily, см. list_top_messages)."""
    count_row = await _fetchone(
        "SELECT COUNT(DISTINCT user_id) AS total FROM message_daily WHERE chat_id = %s AND day >= %s",
        (chat_id, since_day),
    )
    rows = await _fetchall(
        "SELECT user_id, SUM(message_count) AS message_count FROM message_daily "
        "WHERE chat_id = %s AND day >= %s GROUP BY user_id "
        "ORDER BY message_count DESC LIMIT %s OFFSET %s",
        (chat_id, since_day, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)

async def list_active_chat_ids() -> list[int]:
    """Список всех chat_id, по которым в message_stats вообще есть данные
    (используется, чтобы пройтись циклом ежедневной награды по всем чатам,
    где бот считает статистику)."""
    # Раньше здесь стоял `pool = await get_pool()` — функции с таким именем в
    # модуле нет и никогда не было. Из-за этого list_active_chat_ids падала
    # NameError, а вместе с ней молча не работала ЕЖЕДНЕВНАЯ НАГРАДА ЗА ТОП:
    # daily_top_reward_loop получал исключение на первом же шаге, ловил его
    # своим `except Exception` и просто писал в лог — ни один чат не получал
    # начислений ни разу.
    #
    # Заодно переведено на общий _fetchall вместо ручной работы с курсором:
    # тот сам берёт пул и DictCursor, как весь остальной модуль.
    rows = await _fetchall("SELECT DISTINCT chat_id FROM message_stats")
    return [int(r["chat_id"]) for r in rows]
        



async def list_below_norm(chat_id: int, since_day, norm: int, limit: int = 200) -> list[dict]:
    """Известные боту участники чата, чья сумма сообщений с since_day (обычно —
    начало текущей недели) меньше заданной нормы. Те, у кого сейчас активный
    одобренный рест, не включаются — как и в list_inactive, на время реста
    участник не обязан набирать норму. Отсортировано по возрастанию (кто
    дальше всех от нормы — в начале списка)."""
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, "
        "COALESCE(SUM(md.message_count), 0) AS message_count "
        "FROM known_users ku "
        "LEFT JOIN message_daily md ON md.chat_id = ku.chat_id AND md.user_id = ku.user_id AND md.day >= %s "
        "WHERE ku.chat_id = %s "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM rest_requests r WHERE r.chat_id = ku.chat_id AND r.user_id = ku.user_id "
        "  AND r.status = 'approved' AND r.expires_at > UTC_TIMESTAMP()"
        ") "
        "GROUP BY ku.user_id, ku.full_name, ku.username "
        "HAVING COALESCE(SUM(md.message_count), 0) < %s "
        "ORDER BY message_count ASC "
        "LIMIT %s",
        (since_day, chat_id, norm, limit),
    )


async def list_below_norm_joined_before(chat_id: int, since_day, norm: int, limit: int = 1000) -> list[dict]:
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, "
        "COALESCE(SUM(md.message_count), 0) AS message_count "
        "FROM known_users ku "
        "LEFT JOIN message_daily md ON md.chat_id = ku.chat_id AND md.user_id = ku.user_id AND md.day >= %s "
        "LEFT JOIN message_stats ms ON ms.chat_id = ku.chat_id AND ms.user_id = ku.user_id "
        "WHERE ku.chat_id = %s "
        "AND LEAST(ku.first_seen_at, COALESCE(ms.first_seen_at, ku.first_seen_at)) < %s "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM rest_requests r WHERE r.chat_id = ku.chat_id AND r.user_id = ku.user_id "
        "  AND r.status = 'approved' AND r.expires_at > UTC_TIMESTAMP()"
        ") "
        "GROUP BY ku.user_id, ku.full_name, ku.username "
        "HAVING COALESCE(SUM(md.message_count), 0) < %s "
        "ORDER BY message_count ASC "
        "LIMIT %s",
        (since_day, chat_id, since_day, norm, limit),
    )


async def list_by_message_count(chat_id: int, since_day, comparison: str, number: int, limit: int = 200) -> list[dict]:
    """Известные боту участники чата, чья сумма сообщений с since_day
    сравнивается с number через comparison ('>' / '<' / '=').
    Используется командой «Участники сообщения {период} {больше/меньше/равно} {число}»
    — обобщённый вариант list_below_norm с произвольным оператором сравнения.
    comparison ДОЛЖЕН быть провалидирован вызывающим кодом против жёсткого
    списка ('>','<','=') ДО вызова — сюда он подставляется прямо в SQL-текст
    (плейсхолдер для оператора сравнения синтаксически невозможен), поэтому
    непроверенное значение сюда попадать не должно."""
    if comparison not in (">", "<", "="):
        raise ValueError(f"unsupported comparison operator: {comparison!r}")
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, "
        "COALESCE(SUM(md.message_count), 0) AS message_count "
        "FROM known_users ku "
        "LEFT JOIN message_daily md ON md.chat_id = ku.chat_id AND md.user_id = ku.user_id AND md.day >= %s "
        "WHERE ku.chat_id = %s "
        "GROUP BY ku.user_id, ku.full_name, ku.username "
        f"HAVING COALESCE(SUM(md.message_count), 0) {comparison} %s "
        "ORDER BY message_count DESC "
        "LIMIT %s",
        (since_day, chat_id, number, limit),
    )


# ----------------------------------------------------------------------------
# Лог событий
# ----------------------------------------------------------------------------
async def add_log(
    event_type: str,
    chat_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    target_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    await _execute(
        "INSERT INTO logs (event_type, chat_id, actor_id, target_id, details) "
        "VALUES (%s, %s, %s, %s, %s)",
        (event_type, chat_id, actor_id, target_id, details),
    )


async def get_recent_logs(limit: int = 15) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM logs ORDER BY created_at DESC, id DESC LIMIT %s", (limit,)
    )


async def list_log_event_types() -> list[dict]:
    """Какие типы событий вообще встречаются, с числом записей — для
    выпадающего фильтра в панели: список строится по фактическим данным,
    а не по захардкоженному перечню, который рано или поздно отстанет."""
    return await _fetchall(
        "SELECT event_type, COUNT(*) AS n FROM logs "
        "GROUP BY event_type ORDER BY n DESC, event_type ASC"
    )


async def search_logs(
    query: Optional[str] = None,
    event_type: Optional[str] = None,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    since=None,
    until=None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Журнал с поиском и фильтрами. Возвращает (строки, всего_подходящих).

    Условия собираются списком и подставляются параметрами — ни одна часть
    пользовательского ввода не попадает в текст запроса. query ищется по
    details и по идентификаторам, приведённым к строке: админ обычно помнит
    «что-то про 12345», а не в какой именно колонке этот номер лежит.
    """
    where, params = [], []
    if event_type:
        where.append("event_type = %s")
        params.append(event_type)
    if chat_id is not None:
        where.append("chat_id = %s")
        params.append(chat_id)
    if user_id is not None:
        where.append("(actor_id = %s OR target_id = %s)")
        params.extend([user_id, user_id])
    if since is not None:
        where.append("created_at >= %s")
        params.append(since)
    if until is not None:
        where.append("created_at < %s")
        params.append(until)
    if query:
        # LIKE по свободному тексту: escape'им спецсимволы шаблона, иначе
        # «100%» в поиске превратилось бы в «что угодно».
        safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{safe}%"
        where.append(
            "(details LIKE %s OR event_type LIKE %s "
            "OR CAST(actor_id AS CHAR) LIKE %s OR CAST(target_id AS CHAR) LIKE %s "
            "OR CAST(chat_id AS CHAR) LIKE %s)"
        )
        params.extend([like] * 5)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = await _fetchone(f"SELECT COUNT(*) AS n FROM logs{clause}", tuple(params))
    total = int(total_row["n"] or 0) if total_row else 0
    rows = await _fetchall(
        f"SELECT * FROM logs{clause} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    return rows, total


# ----------------------------------------------------------------------------
# Награды (медали) — модуль «Награды», по образцу Iris. 8 степеней, привязаны
# к чату. Нумерация награды в списке пользователя (для «снять награду N») —
# порядковая, от самой старой к самой новой; список всегда отдаётся целиком,
# без пагинации в SQL, т.к. номер должен ссылаться на позицию во всём списке.
# ----------------------------------------------------------------------------
async def ensure_rewards_tables() -> None:
    """Награды (медали) и пороги доступа по степеням. Раньше эти таблицы были
    только в schema.sql, без ensure-миграции: на БД, поднятой НЕ из полного
    schema.sql (а через ensure_*-функции), их не было — и «наградить» молча
    падал на INSERT в несуществующую таблицу. Создаём здесь идемпотентно."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS rewards ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "degree TINYINT UNSIGNED NOT NULL, "
        "reason VARCHAR(500) DEFAULT NULL, "
        "awarded_by BIGINT NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rewards_chat_user (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS reward_degree_levels ("
        "degree TINYINT UNSIGNED NOT NULL PRIMARY KEY, "
        "min_level TINYINT NOT NULL, "
        "updated_by BIGINT DEFAULT NULL, "
        "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_reward(
    chat_id: int, user_id: int, degree: int, reason: Optional[str], awarded_by: int
) -> int:
    """Добавляет награду, возвращает её id."""
    return await _execute(
        "INSERT INTO rewards (chat_id, user_id, degree, reason, awarded_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, user_id, degree, reason, awarded_by),
    )


async def list_rewards(chat_id: int, user_id: int) -> list[dict]:
    """Все награды пользователя в чате, от старых к новым."""
    return await _fetchall(
        "SELECT id, degree, reason, awarded_by, created_at FROM rewards "
        "WHERE chat_id = %s AND user_id = %s ORDER BY created_at ASC, id ASC",
        (chat_id, user_id),
    )


async def count_rewards(chat_id: int, user_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM rewards WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return int(row["total"] if row else 0)


async def get_reward(reward_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, chat_id, user_id, degree, reason, awarded_by, created_at "
        "FROM rewards WHERE id = %s",
        (reward_id,),
    )


async def remove_reward(reward_id: int) -> bool:
    rowcount = await _execute("DELETE FROM rewards WHERE id = %s", (reward_id,))
    return rowcount > 0


async def remove_all_rewards(chat_id: int, user_id: int) -> int:
    """Снимает все награды пользователя, возвращает сколько было снято."""
    return await _execute(
        "DELETE FROM rewards WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


# ----------------------------------------------------------------------------
# Пороги доступа для выдачи наград по степеням — переопределение по аналогии
# с command_permissions (см. list_command_levels выше). Если для степени нет
# строки — используется уровень по умолчанию из bot.py. Команда в чате:
# «право степень <N> <уровень>».
# ----------------------------------------------------------------------------
async def list_reward_degree_levels() -> dict[int, int]:
    rows = await _fetchall("SELECT degree, min_level FROM reward_degree_levels")
    return {int(r["degree"]): int(r["min_level"]) for r in rows}


async def set_reward_degree_level(
    degree: int, min_level: int, updated_by: Optional[int] = None
) -> None:
    await _execute(
        "INSERT INTO reward_degree_levels (degree, min_level, updated_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE min_level = VALUES(min_level), updated_by = VALUES(updated_by), "
        "updated_at = CURRENT_TIMESTAMP",
        (degree, min_level, updated_by),
    )


async def reset_reward_degree_level(degree: int) -> None:
    await _execute("DELETE FROM reward_degree_levels WHERE degree = %s", (degree,))


# ----------------------------------------------------------------------------
# Таймеры — модуль «Таймеры» (см. teletype.in/@iris_cm/commands, раздел 25).
# Отложенные текстовые напоминания: Ирис отправляет указанный текст в чат
# через заданный период («Таймер через») либо в указанную дату/время
# («Таймер на»). Таблица создаётся автоматически при старте бота — см.
# ensure_timers_table(), вызывается один раз в main() до load_caches().
# ----------------------------------------------------------------------------
async def ensure_timers_table() -> None:
    """Создаёт таблицу timers, если она ещё не существует (миграция на лету,
    чтобы модуль «Таймеры» заработал без ручного изменения схемы БД)."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS timers ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "fire_at DATETIME NOT NULL, "
        "text TEXT NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_timers_chat (chat_id), "
        "INDEX idx_timers_fire_at (fire_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_timer(chat_id: int, user_id: int, fire_at: datetime, text: str) -> int:
    """Создаёт таймер, возвращает его id (используется как «номер» в командах)."""
    return await _execute(
        "INSERT INTO timers (chat_id, user_id, fire_at, text) VALUES (%s, %s, %s, %s)",
        (chat_id, user_id, fire_at, text),
    )


async def count_timers(chat_id: int) -> int:
    row = await _fetchone("SELECT COUNT(*) AS total FROM timers WHERE chat_id = %s", (chat_id,))
    return int(row["total"] if row else 0)


async def list_timers(chat_id: int) -> list[dict]:
    """Активные таймеры чата, отсортированные по времени срабатывания."""
    return await _fetchall(
        "SELECT id, user_id, fire_at, text FROM timers WHERE chat_id = %s ORDER BY fire_at ASC",
        (chat_id,),
    )


async def get_timer(timer_id: int, chat_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, chat_id, user_id, fire_at, text FROM timers WHERE id = %s AND chat_id = %s",
        (timer_id, chat_id),
    )


async def delete_timer(timer_id: int, chat_id: int) -> bool:
    rowcount = await _execute("DELETE FROM timers WHERE id = %s AND chat_id = %s", (timer_id, chat_id))
    return rowcount > 0


async def delete_all_timers(chat_id: int) -> int:
    return await _execute("DELETE FROM timers WHERE chat_id = %s", (chat_id,))


async def list_all_pending_timers() -> list[dict]:
    """Все ещё не сработавшие таймеры во всех чатах — для восстановления
    отложенных задач asyncio после перезапуска бота."""
    return await _fetchall("SELECT id, chat_id, user_id, fire_at, text FROM timers")

# ----------------------------------------------------------------------------
# Автоочистка команд в привязанном чате (см. настройку «чистка команд»):
# команда пользователя и ответы бота на неё удаляются через N минут. Опрос
# таблицы идёт по времени, поэтому переживает перезапуск бота без отдельного
# восстановления asyncio-задач (в отличие от timers).
# ----------------------------------------------------------------------------
async def ensure_cmd_cleanup_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS cmd_cleanup_queue ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "message_id BIGINT NOT NULL, "
        "delete_at DATETIME NOT NULL, "
        "INDEX idx_cmd_cleanup_delete_at (delete_at), "
        "UNIQUE KEY uniq_cmd_cleanup_msg (chat_id, message_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_cleanup_entry(chat_id: int, message_id: int, delete_at) -> None:
    await _execute(
        "INSERT IGNORE INTO cmd_cleanup_queue (chat_id, message_id, delete_at) VALUES (%s, %s, %s)",
        (chat_id, message_id, delete_at),
    )


async def list_due_cleanup_entries(now, limit: int = 200) -> list[dict]:
    """Просроченные записи — СТАРЫЕ ПЕРВЫМИ.

    Без ORDER BY сервер отдавал произвольные limit строк: при завале очереди
    (больше limit просроченных) одни и те же поздние записи могли выбираться
    круг за кругом, а самые старые сообщения висели в чате часами. Порядок
    делает выборку честной очередью.
    """
    return await _fetchall(
        "SELECT id, chat_id, message_id FROM cmd_cleanup_queue "
        "WHERE delete_at <= %s ORDER BY delete_at ASC, id ASC LIMIT %s",
        (now, limit),
    )


async def delete_cleanup_entry(entry_id: int) -> None:
    await _execute("DELETE FROM cmd_cleanup_queue WHERE id = %s", (entry_id,))
# ----------------------------------------------------------------------------
# Модуль «Рест»: участник заранее предупреждает, что не будет писать какое-то
# время (болезнь, отпуск, сессия и т.п.), и на этот срок не считается
# неактивным в «список неактив». Заявка идёт через бота админам (в тот же
# топик/чат, что и заявки на вступление — settings.notify_chat_id/topic_id) и
# согласовывается там же кнопками, как и «Дать ссылку»/«Отказать». Одна
# строка = одна заявка; статус approved + expires_at в будущем = рест активен
# прямо сейчас. Старые заявки (rejected или с истёкшим expires_at) не
# удаляются — они же и есть история («рест лог»).
# ----------------------------------------------------------------------------
async def ensure_rest_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rest_requests ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "duration_seconds BIGINT NOT NULL, "
        "reason VARCHAR(500) NULL, "
        "status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending', "
        "requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "decided_by BIGINT NULL, "
        "decided_at TIMESTAMP NULL, "
        "expires_at DATETIME NULL, "
        "INDEX idx_rest_chat_user (chat_id, user_id), "
        "INDEX idx_rest_status (chat_id, status, expires_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_rest_notice_columns() -> None:
    """Куда бот отправил карточку заявки на рест.

    Как и у заявок на роль: решение, принятое в веб-панели, должно закрыть
    карточку с кнопками в чате — иначе второй админ нажмёт «Одобрить» по уже
    обработанной заявке.
    """
    await _add_column_if_missing("rest_requests", "notice_chat_id", "BIGINT NULL")
    await _add_column_if_missing("rest_requests", "notice_message_id", "BIGINT NULL")


async def set_rest_request_message(request_id: int, chat_id: int, message_id: int) -> None:
    await _execute(
        "UPDATE rest_requests SET notice_chat_id = %s, notice_message_id = %s WHERE id = %s",
        (chat_id, message_id, request_id),
    )


async def list_pending_rest_requests(chat_id: int, limit: int = 50) -> list[dict]:
    """Нерассмотренные заявки на рест — для панели. Имя заявителя подтягиваем
    сразу: без него в списке видны одни числовые id."""
    return await _fetchall(
        "SELECT r.*, ku.full_name, ku.username "
        "FROM rest_requests r "
        "LEFT JOIN known_users ku ON ku.chat_id = r.chat_id AND ku.user_id = r.user_id "
        "WHERE r.chat_id = %s AND r.status = 'pending' "
        "ORDER BY r.requested_at LIMIT %s",
        (chat_id, limit),
    )


async def add_rest_request(chat_id: int, user_id: int, duration_seconds: int, reason: Optional[str]) -> int:
    """Создаёт заявку на рест (status='pending'), возвращает её id."""
    return await _execute(
        "INSERT INTO rest_requests (chat_id, user_id, duration_seconds, reason) VALUES (%s, %s, %s, %s)",
        (chat_id, user_id, duration_seconds, reason[:500] if reason else None),
    )


async def get_rest_request(request_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM rest_requests WHERE id = %s", (request_id,)
    )


async def get_pending_rest_request(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM rest_requests WHERE chat_id = %s AND user_id = %s AND status = 'pending' "
        "ORDER BY requested_at DESC LIMIT 1",
        (chat_id, user_id),
    )


async def get_active_rest(chat_id: int, user_id: int) -> Optional[dict]:
    """Активный (одобренный и ещё не истёкший) рест пользователя в чате, если есть."""
    return await _fetchone(
        "SELECT * FROM rest_requests WHERE chat_id = %s AND user_id = %s AND status = 'approved' "
        "AND expires_at > UTC_TIMESTAMP() ORDER BY expires_at DESC LIMIT 1",
        (chat_id, user_id),
    )


async def approve_rest_request(request_id: int, admin_id: int) -> Optional[dict]:
    """Одобряет заявку (если она ещё pending) и сразу считает срок реста от
    текущего момента. Возвращает обновлённую строку или None, если заявку уже
    кто-то обработал (защита от двойного нажатия кнопки разными админами)."""
    rowcount = await _execute(
        "UPDATE rest_requests SET status = 'approved', decided_by = %s, decided_at = UTC_TIMESTAMP(), "
        "expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL duration_seconds SECOND) "
        "WHERE id = %s AND status = 'pending'",
        (admin_id, request_id),
    )
    if not rowcount:
        return None
    return await get_rest_request(request_id)


async def reject_rest_request(request_id: int, admin_id: int) -> Optional[dict]:
    rowcount = await _execute(
        "UPDATE rest_requests SET status = 'rejected', decided_by = %s, decided_at = UTC_TIMESTAMP() "
        "WHERE id = %s AND status = 'pending'",
        (admin_id, request_id),
    )
    if not rowcount:
        return None
    return await get_rest_request(request_id)


async def cancel_active_rest(chat_id: int, user_id: int) -> bool:
    """Досрочно снимает активный рест (например, командой админа)."""
    rowcount = await _execute(
        "UPDATE rest_requests SET expires_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s AND user_id = %s AND status = 'approved' AND expires_at > UTC_TIMESTAMP()",
        (chat_id, user_id),
    )
    return rowcount > 0


async def get_last_finished_rest(chat_id: int, user_id: int) -> Optional[dict]:
    """Последний одобренный рест, который уже закончился, — по нему считается
    пауза до следующего (см. rest_rules.check_rest_rules). Активный рест сюда
    не попадает: пока он идёт, новую заявку и так не принимают."""
    return await _fetchone(
        "SELECT * FROM rest_requests "
        "WHERE chat_id = %s AND user_id = %s AND status = 'approved' "
        "AND expires_at IS NOT NULL AND expires_at <= UTC_TIMESTAMP() "
        "ORDER BY expires_at DESC LIMIT 1",
        (chat_id, user_id),
    )


async def get_member_first_seen(chat_id: int, user_id: int) -> Optional[datetime]:
    """Когда бот впервые увидел участника в этом чате (стаж для правила «рест
    недоступен новичкам»). None — если бот его ещё не видел; тогда проверка
    стажа не применяется, придираться не к чему."""
    row = await _fetchone(
        "SELECT first_seen_at FROM known_users WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row["first_seen_at"] if row else None


async def list_active_rest_user_ids(chat_id: int) -> set[int]:
    """Все user_id, кто сейчас в активном (одобренном, ещё не истёкшем) ресте
    в этом чате — без лимита и без join'а на known_users, для дешёвой отметки
    рестующих в других списках (например, «Участники сообщения»), где их не
    исключают, а просто помечают."""
    rows = await _fetchall(
        "SELECT user_id FROM rest_requests "
        "WHERE chat_id = %s AND status = 'approved' AND expires_at > UTC_TIMESTAMP()",
        (chat_id,),
    )
    return {row["user_id"] for row in rows}


async def list_active_rests(chat_id: int, limit: int = 30) -> list[dict]:
    """Все, кто сейчас в ресте в этом чате, ближайшие по истечению — первыми."""
    return await _fetchall(
        "SELECT r.user_id, r.expires_at, r.reason, ku.full_name, ku.username "
        "FROM rest_requests r "
        "LEFT JOIN known_users ku ON ku.chat_id = r.chat_id AND ku.user_id = r.user_id "
        "WHERE r.chat_id = %s AND r.status = 'approved' AND r.expires_at > UTC_TIMESTAMP() "
        "ORDER BY r.expires_at ASC LIMIT %s",
        (chat_id, limit),
    )


# ----------------------------------------------------------------------------
# Холды администраторов: Telegram не позволяет мутить/банить участника со
# статусом «administrator». Поэтому при муте/бане действующего админа бот
# сначала временно снимает права (сохранив их снимок здесь), затем выполняет
# мут/бан, а позже — автоматически (по истечении срока мута) или вручную
# (когда мут/бан сняли раньше) — возвращает права обратно. На пользователя в
# чате одновременно может быть только один активный холд.
# ----------------------------------------------------------------------------
async def ensure_admin_holds_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS admin_action_holds ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "actor_id BIGINT NOT NULL, "
        "action_type ENUM('mute','ban') NOT NULL, "
        "rights_json TEXT NOT NULL, "
        "custom_title VARCHAR(32) NULL, "
        "until DATETIME NULL, "
        "reason VARCHAR(500) NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_admin_hold (chat_id, user_id), "
        "INDEX idx_admin_holds_until (until)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_admin_hold(
    chat_id: int, user_id: int, actor_id: int, action_type: str,
    rights_json: str, custom_title: Optional[str], until: Optional[datetime], reason: Optional[str],
) -> None:
    """Создаёт холд (или заменяет — если предыдущий по какой-то причине не удалился)."""
    await _execute(
        "INSERT INTO admin_action_holds "
        "(chat_id, user_id, actor_id, action_type, rights_json, custom_title, until, reason) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE actor_id = VALUES(actor_id), action_type = VALUES(action_type), "
        "rights_json = VALUES(rights_json), custom_title = VALUES(custom_title), "
        "until = VALUES(until), reason = VALUES(reason), created_at = CURRENT_TIMESTAMP",
        (chat_id, user_id, actor_id, action_type, rights_json, custom_title, until, reason[:500] if reason else None),
    )


async def get_admin_hold(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM admin_action_holds WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def delete_admin_hold(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM admin_action_holds WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return rowcount > 0


async def list_all_pending_admin_holds() -> list[dict]:
    """Холды со сроком (until IS NOT NULL) — для восстановления отложенных задач
    после перезапуска бота. Бессрочные холды фоновой задачи не требуют — ждут
    только ручного снятия мута/бана."""
    return await _fetchall("SELECT * FROM admin_action_holds WHERE until IS NOT NULL")


# ----------------------------------------------------------------------------
# Лента последних сообщений чата — для плашки в веб-панели, из которой удобно
# отвечать (по клику подставляется reply_to). Панель работает отдельным
# процессом и в память бота (кольцевой буфер recent_chat_messages в bot.py) не
# заглянет, а Bot API историю чата ботам не отдаёт — поэтому лента едет через
# БД. Хранится ПРЕВЬЮ, а не переписка: последние RECENT_MESSAGES_KEEP штук на
# чат, текст обрезан до RECENT_MESSAGE_TEXT_LIMIT символов.
# ----------------------------------------------------------------------------
RECENT_MESSAGES_KEEP = 200        # сколько строк на чат оставляем в БД
RECENT_MESSAGE_TEXT_LIMIT = 500   # длиннее в плашке всё равно не прочитать
# Обрезаем не на каждой вставке: это лишний запрос на каждое сообщение чата.
RECENT_MESSAGES_TRIM_EVERY = 50

_recent_inserts_since_trim: dict[int, int] = {}


async def ensure_recent_messages_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS recent_messages ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "message_id BIGINT NOT NULL, "
        "user_id BIGINT NULL, "
        "full_name VARCHAR(255) NULL, "
        "username VARCHAR(255) NULL, "
        "text VARCHAR(500) NULL, "
        "kind VARCHAR(32) NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        # Одно и то же сообщение может прийти повторно (ретрай апдейта) —
        # ключ не даёт задвоить строку в ленте.
        "UNIQUE KEY uniq_recent_message (chat_id, message_id), "
        "INDEX idx_recent_chat (chat_id, id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_recent_message(
    chat_id: int, message_id: int, user_id: Optional[int],
    full_name: Optional[str], username: Optional[str],
    text: Optional[str], kind: Optional[str],
) -> None:
    """Кладёт сообщение в ленту чата и изредка подчищает старые."""
    await _execute(
        "INSERT INTO recent_messages "
        "(chat_id, message_id, user_id, full_name, username, text, kind) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE text = VALUES(text), kind = VALUES(kind)",
        (
            chat_id, message_id, user_id,
            (full_name or None) and full_name[:255],
            (username or None) and username[:255],
            (text or None) and text[:RECENT_MESSAGE_TEXT_LIMIT],
            kind,
        ),
    )

    seen = _recent_inserts_since_trim.get(chat_id, 0) + 1
    if seen >= RECENT_MESSAGES_TRIM_EVERY:
        _recent_inserts_since_trim[chat_id] = 0
        await trim_recent_messages(chat_id)
    else:
        _recent_inserts_since_trim[chat_id] = seen


async def trim_recent_messages(chat_id: int, keep: int = RECENT_MESSAGES_KEEP) -> int:
    """Оставляет в чате только последние keep строк.

    Вложенный SELECT обёрнут в производную таблицу намеренно: MySQL не даёт
    удалять из той же таблицы, из которой читает подзапрос напрямую
    (ошибка 1093), а через derived table — можно."""
    return await _execute(
        "DELETE FROM recent_messages WHERE chat_id = %s AND id NOT IN ("
        "  SELECT id FROM ("
        "    SELECT id FROM recent_messages WHERE chat_id = %s ORDER BY id DESC LIMIT %s"
        "  ) AS keep_rows"
        ")",
        (chat_id, chat_id, keep),
    )


async def list_recent_messages(chat_id: int, limit: int = 10) -> list[dict]:
    """Последние сообщения чата — в порядке от старых к новым, как в Telegram."""
    rows = await _fetchall(
        "SELECT id, message_id, user_id, full_name, username, text, kind, created_at "
        "FROM recent_messages WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (chat_id, limit),
    )
    rows.reverse()
    return rows


async def list_recent_messages_by_user(chat_id: int, user_id: int, limit: int = 50) -> list[dict]:
    """Последние сохранённые фразы одного человека — для «компромата».

    Глубина ограничена сверху не этим limit'ом, а RECENT_MESSAGES_KEEP: лента
    подрезается до последних 200 строк НА ЧАТ, поэтому в живом чате «старая»
    фраза — это в лучшем случае вчерашняя. Обещать большего нельзя.
    """
    return await _fetchall(
        "SELECT message_id, text, created_at FROM recent_messages "
        "WHERE chat_id = %s AND user_id = %s AND text IS NOT NULL AND text <> '' "
        "ORDER BY id DESC LIMIT %s",
        (chat_id, user_id, limit),
    )


async def list_recent_messages_after(chat_id: int, after_id: int, limit: int = 50) -> list[dict]:
    """Сообщения, появившиеся после указанной строки, — для SSE-потока панели."""
    return await _fetchall(
        "SELECT id, message_id, user_id, full_name, username, text, kind, created_at "
        "FROM recent_messages WHERE chat_id = %s AND id > %s ORDER BY id ASC LIMIT %s",
        (chat_id, after_id, limit),
    )


# ----------------------------------------------------------------------------
# Созывы (модуль «Зазывала»): позывной-эмодзи участника и анрег (временный
# отказ от упоминаний в созывах текущего чата, до следующего сообщения автора
# в чат — см. cmd-обработчики "созыв"/"анрег" в bot.py).
# ----------------------------------------------------------------------------
async def ensure_call_signs_emoji_width() -> None:
    """Раньше колонка call_signs.emoji рассчитывалась только на обычный
    юникод-эмодзи (1-2 кодовые точки). Премиум/кастомные эмодзи Telegram
    («мой эмодзи» + кастомный эмодзи из набора Premium) хранятся здесь как
    HTML-фрагмент вида '<tg-emoji emoji-id="...">🙂</tg-emoji>' (см.
    cmd_call_emoji в bot.py) — это заметно длиннее обычного эмодзи, поэтому
    на всякий случай расширяем колонку, если она уже существует и узкая.
    Если таблицы/колонки ещё нет — ничего не делаем (её создают вне этого
    модуля)."""
    row = await _fetchone(
        "SELECT CHARACTER_MAXIMUM_LENGTH AS len FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'call_signs' AND column_name = 'emoji'"
    )
    if row is None:
        return
    current_len = row.get("len")
    if current_len is not None and current_len < 191:
        await _execute("ALTER TABLE call_signs MODIFY COLUMN emoji VARCHAR(191)")


async def set_call_emoji(chat_id: int, user_id: int, emoji: str) -> None:
    await _execute(
        "INSERT INTO call_signs (chat_id, user_id, emoji) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE emoji = VALUES(emoji), updated_at = CURRENT_TIMESTAMP",
        (chat_id, user_id, emoji),
    )


async def clear_call_emoji(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM call_signs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def get_call_emoji(chat_id: int, user_id: int) -> Optional[str]:
    row = await _fetchone(
        "SELECT emoji FROM call_signs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row["emoji"] if row else None


async def get_or_assign_call_emoji(chat_id: int, user_id: int, pool: list[str]) -> str:
    """Как get_call_emoji, но если у пользователя ещё нет своего позывного —
    назначает и сохраняет ему один по умолчанию (детерминированно, по user_id,
    чтобы у одного и того же человека он не менялся между созывами, пока он
    сам не сменит его командой «мой эмодзи»/«сменить эмодзи»)."""
    existing = await get_call_emoji(chat_id, user_id)
    if existing:
        return existing
    default_emoji = pool[user_id % len(pool)]
    await set_call_emoji(chat_id, user_id, default_emoji)
    return default_emoji


async def set_unreg(chat_id: int, user_id: int, message: Optional[str]) -> None:
    """Помечает участника как временно вышедшего из созывов этого чата (до его
    следующего сообщения в чат — см. MessageCounterMiddleware в bot.py,
    который снимает анрег при первом же новом сообщении автора)."""
    await _execute(
        "INSERT INTO call_unregs (chat_id, user_id, message) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE message = VALUES(message), created_at = CURRENT_TIMESTAMP",
        (chat_id, user_id, message),
    )


async def clear_unreg(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM call_unregs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return rowcount > 0


async def delete_call_data(chat_id: int, user_id: int) -> None:
    """Убирает позывной-эмодзи и анрег пользователя в чате — вызывается при
    выходе участника из группы, чтобы записи не копились впустую."""
    await _execute(
        "DELETE FROM call_signs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    await _execute(
        "DELETE FROM call_unregs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def get_unreg(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT message, created_at FROM call_unregs WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def list_callable_users(chat_id: int, limit: int = 1000) -> list[dict]:
    """Известные боту участники чата (см. ограничение Bot API в README),
    за вычетом тех, кто сейчас в анреге или в активном ресте — то есть
    кандидаты на упоминание в созыве. emoji — персональный позывной, если
    задан."""
    return await _fetchall(
        "SELECT ku.user_id, ku.full_name, ku.username, cs.emoji "
        "FROM known_users ku "
        "LEFT JOIN call_unregs cu ON cu.chat_id = ku.chat_id AND cu.user_id = ku.user_id "
        "LEFT JOIN call_signs cs ON cs.chat_id = ku.chat_id AND cs.user_id = ku.user_id "
        "WHERE ku.chat_id = %s AND cu.user_id IS NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM rest_requests r WHERE r.chat_id = ku.chat_id AND r.user_id = ku.user_id "
        "  AND r.status = 'approved' AND r.expires_at > UTC_TIMESTAMP()"
        ") "
        "ORDER BY ku.last_seen_at DESC LIMIT %s",
        (chat_id, limit),
    )


async def is_unregistered(chat_id: int, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM call_unregs WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    return row is not None


# ----------------------------------------------------------------------------
# Модуль «Роли»: ограниченный набор именных ролей чата, которые может носить
# только один человек одновременно. Статусы: free (свободна) / taken (занята
# участником группы) / reserved (забронирована за user_id, который пока не
# состоит в группе). Новые роли проходят модерацию (approved=FALSE до
# одобрения админом) — см. propose_role/approve_role_proposal.
# ----------------------------------------------------------------------------
async def ensure_chat_roles_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS chat_roles ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "category VARCHAR(64) NULL, "
        "status ENUM('free','taken','reserved') NOT NULL DEFAULT 'free', "
        "holder_user_id BIGINT NULL, "
        "reserved_user_id BIGINT NULL, "
        "reserved_at DATETIME NULL, "
        "proposed_by BIGINT NULL, "
        "approved BOOL NOT NULL DEFAULT TRUE, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_chat_role_name (chat_id, name), "
        "INDEX idx_roles_chat_status (chat_id, status), "
        "INDEX idx_roles_holder (chat_id, holder_user_id), "
        "INDEX idx_roles_reserved (chat_id, reserved_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_role_proposal_message_columns() -> None:
    """Куда бот отправил карточку заявки на роль.

    Нужно, чтобы решение, принятое в веб-панели, доезжало до чата: панель
    правит то самое сообщение с кнопками, которое видят админы. Без этих
    колонок карточка осталась бы висеть с активными кнопками, и второй админ
    нажал бы «Принять» по уже обработанной заявке.
    """
    await _add_column_if_missing("chat_roles", "proposal_chat_id", "BIGINT NULL")
    await _add_column_if_missing("chat_roles", "proposal_message_id", "BIGINT NULL")


async def set_role_proposal_message(
    chat_id: int, role_id: int, message_chat_id: int, message_id: int
) -> None:
    await _execute(
        "UPDATE chat_roles SET proposal_chat_id = %s, proposal_message_id = %s "
        "WHERE chat_id = %s AND id = %s",
        (message_chat_id, message_id, chat_id, role_id),
    )


async def list_roles(chat_id: int, approved_only: bool = True) -> list[dict]:
    """Все роли чата (по умолчанию — только прошедшие модерацию), отсортированные
    по категории — удобно для вывода списком."""
    query = "SELECT * FROM chat_roles WHERE chat_id = %s"
    if approved_only:
        query += " AND approved = TRUE"
    query += " ORDER BY category IS NULL, category, name"
    return await _fetchall(query, (chat_id,))


# Статусы, по которым можно фильтровать поиск. 'pending' — не значение колонки
# status, а approved=FALSE (заявка на модерации); держим их в одном списке,
# потому что для того, кто смотрит список, это такое же состояние роли.
ROLE_SEARCH_STATUSES = ("free", "taken", "reserved", "pending")

# Имена людей лежат не в chat_roles (там только user_id), а в known_users,
# поэтому оба участника роли — держатель и забронировавший — приезжают
# джойнами. Джойн идёт и по chat_id: без него подтянется тёзка из другого чата.
_ROLE_SEARCH_FROM = (
    "FROM chat_roles r "
    "LEFT JOIN known_users h ON h.chat_id = r.chat_id AND h.user_id = r.holder_user_id "
    "LEFT JOIN known_users v ON v.chat_id = r.chat_id AND v.user_id = r.reserved_user_id "
)


def _role_search_where(
    q: Optional[str], status: Optional[str], category: Optional[str]
) -> tuple[str, list]:
    """Условия поиска ролей и параметры к ним (общие у выборки и у счётчика)."""
    where = ["r.chat_id = %s"]
    params: list = []

    if status == "pending":
        where.append("r.approved = FALSE")
    else:
        where.append("r.approved = TRUE")
        if status:
            where.append("r.status = %s")
            params.append(status)

    if category:
        where.append("r.category = %s")
        params.append(category)

    if q:
        # Одно поле ищет и роль, и человека: «кто такая Аска» и «что у Оли» —
        # один и тот же вопрос с разных сторон.
        needle = f"%{q.strip()}%"
        where.append(
            "(r.name LIKE %s OR r.category LIKE %s "
            "OR h.full_name LIKE %s OR h.username LIKE %s "
            "OR v.full_name LIKE %s OR v.username LIKE %s)"
        )
        params.extend([needle] * 6)

    return " WHERE " + " AND ".join(where), params


async def search_chat_roles(
    chat_id: int,
    *,
    q: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Поиск по ролям чата с именами держателя и забронировавшего.

    Порядок — как в списке ролей у бота (категория, потом название), чтобы
    панель и чат показывали одно и то же в одной последовательности.
    """
    where, params = _role_search_where(q, status, category)
    count_row = await _fetchone(
        f"SELECT COUNT(*) AS total {_ROLE_SEARCH_FROM}{where}", (chat_id, *params)
    )
    rows = await _fetchall(
        "SELECT r.id, r.name, r.category, r.status, r.approved, r.reserved_at, "
        "r.holder_user_id, h.full_name AS holder_full_name, h.username AS holder_username, "
        "r.reserved_user_id, v.full_name AS reserved_full_name, v.username AS reserved_username "
        f"{_ROLE_SEARCH_FROM}{where} "
        "ORDER BY r.category IS NULL, r.category, r.name LIMIT %s OFFSET %s",
        (chat_id, *params, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def count_chat_roles_by_status(chat_id: int) -> dict:
    """Сколько ролей в каждом состоянии — для счётчиков на фильтрах, чтобы
    ради цифры не выкачивать все роли целиком."""
    rows = await _fetchall(
        "SELECT status, COUNT(*) AS total FROM chat_roles "
        "WHERE chat_id = %s AND approved = TRUE GROUP BY status",
        (chat_id,),
    )
    counts = {status: 0 for status in ROLE_SEARCH_STATUSES}
    for row in rows:
        counts[row["status"]] = int(row["total"])
    pending = await _fetchone(
        "SELECT COUNT(*) AS total FROM chat_roles WHERE chat_id = %s AND approved = FALSE",
        (chat_id,),
    )
    counts["pending"] = int(pending["total"] if pending else 0)
    return counts


async def list_role_categories(chat_id: int) -> list[str]:
    """Категории одобренных ролей — для фильтра в панели. Роли без категории
    (category IS NULL) сюда не попадают: фильтровать по «пусто» нечего."""
    rows = await _fetchall(
        "SELECT DISTINCT category FROM chat_roles "
        "WHERE chat_id = %s AND approved = TRUE AND category IS NOT NULL AND category <> '' "
        "ORDER BY category",
        (chat_id,),
    )
    return [row["category"] for row in rows]


async def list_free_roles(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND approved = TRUE AND status = 'free' "
        "ORDER BY category IS NULL, category, name",
        (chat_id,),
    )


async def list_pending_role_proposals(chat_id: Optional[int] = None) -> list[dict]:
    if chat_id is None:
        return await _fetchall("SELECT * FROM chat_roles WHERE approved = FALSE ORDER BY created_at")
    return await _fetchall(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND approved = FALSE ORDER BY created_at",
        (chat_id,),
    )


async def rename_role(chat_id: int, role_id: int, name: str, category: Optional[str]) -> bool:
    """Меняет название и категорию роли, сохраняя держателя и бронь.

    Раньше опечатку в названии можно было исправить только удалив роль и
    заведя заново — вместе с ней слетал держатель. Возвращает False, если
    роль с таким названием в чате уже есть (UNIQUE по chat_id+name).
    """
    clash = await get_role_by_name(chat_id, name)
    if clash is not None and clash["id"] != role_id:
        return False
    await _execute(
        "UPDATE chat_roles SET name = %s, category = %s WHERE chat_id = %s AND id = %s",
        (name.strip()[:64], category, chat_id, role_id),
    )
    return True


async def get_role(chat_id: int, role_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND id = %s", (chat_id, role_id)
    )


async def get_role_by_name(chat_id: int, name: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND name = %s", (chat_id, name.strip())
    )


async def get_user_role(chat_id: int, user_id: int) -> Optional[dict]:
    """Роль, которую человек держит сейчас (status='taken')."""
    return await _fetchone(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND holder_user_id = %s AND status = 'taken'",
        (chat_id, user_id),
    )


async def get_user_reservation(chat_id: int, user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND reserved_user_id = %s AND status = 'reserved'",
        (chat_id, user_id),
    )


async def propose_role(
    chat_id: int, name: str, category: Optional[str], proposed_by: int, auto_approved: bool = False
) -> Optional[int]:
    """Создаёт заявку на новую роль (approved=FALSE, если не auto_approved).
    Возвращает id или None, если роль с таким названием уже существует."""
    existing = await get_role_by_name(chat_id, name)
    if existing is not None:
        return None
    return await _execute(
        "INSERT INTO chat_roles (chat_id, name, category, proposed_by, approved) VALUES (%s, %s, %s, %s, %s)",
        (chat_id, name.strip()[:64], category, proposed_by, auto_approved),
    )


async def approve_role_proposal(chat_id: int, role_id: int) -> Optional[dict]:
    rowcount = await _execute(
        "UPDATE chat_roles SET approved = TRUE WHERE chat_id = %s AND id = %s AND approved = FALSE",
        (chat_id, role_id),
    )
    if not rowcount:
        return None
    return await get_role(chat_id, role_id)


async def reject_role_proposal(chat_id: int, role_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM chat_roles WHERE chat_id = %s AND id = %s AND approved = FALSE",
        (chat_id, role_id),
    )
    return rowcount > 0


async def _clear_other_roles_of_user(chat_id: int, user_id: int, keep_role_id: int) -> None:
    """Освобождает все прочие роли и брони человека, кроме указанной.

    Инвариант «одна роль на человека» держится только этой уборкой: занятость
    и бронь — разные колонки, и без явной очистки можно было держать роль и
    одновременно бронь на другую, которая срабатывала при следующем входе.
    """
    await _execute(
        "UPDATE chat_roles SET status = 'free', holder_user_id = NULL "
        "WHERE chat_id = %s AND holder_user_id = %s AND status = 'taken' AND id <> %s",
        (chat_id, user_id, keep_role_id),
    )
    await _execute(
        "UPDATE chat_roles SET status = 'free', reserved_user_id = NULL, reserved_at = NULL "
        "WHERE chat_id = %s AND reserved_user_id = %s AND status = 'reserved' AND id <> %s",
        (chat_id, user_id, keep_role_id),
    )


async def take_role(chat_id: int, role_id: int, user_id: int) -> bool:
    """Назначает свободную роль участнику группы, освобождая его предыдущую.

    Порядок важен: сначала занимаем новую роль и только при успехе отпускаем
    старую. При обратном порядке два человека, выбирающие роль одновременно,
    приводили к тому, что проигравший гонку оставался вообще без роли —
    старую уже освободили, а новую занять не успели.
    """
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'taken', holder_user_id = %s, "
        "reserved_user_id = NULL, reserved_at = NULL "
        "WHERE chat_id = %s AND id = %s AND status = 'free'",
        (user_id, chat_id, role_id),
    )
    if not rowcount:
        return False
    await _clear_other_roles_of_user(chat_id, user_id, role_id)
    return True


async def release_role(chat_id: int, role_id: int) -> bool:
    # снимаем заодно и бронь: иначе освобождённая роль осталась бы висеть с
    # чужим reserved_user_id и «выстрелила» бы при следующем входе этого
    # человека в чат
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'free', holder_user_id = NULL, "
        "reserved_user_id = NULL, reserved_at = NULL "
        "WHERE chat_id = %s AND id = %s AND status = 'taken'",
        (chat_id, role_id),
    )
    return rowcount > 0


async def release_role_by_holder(chat_id: int, user_id: int) -> Optional[str]:
    """Освобождает роль человека, покинувшего чат (выход, кик или бан).

    Роль переводится в status='free' и остаётся в списке — она снова доступна
    для выбора. Заодно снимается бронь этого же человека, иначе она сработала
    бы при его повторном входе.

    Возвращает название роли, если она у него была И реально была освобождена,
    иначе None (в т.ч. если между SELECT и UPDATE роль уже успела перейти
    другому — чужую роль не трогаем и о ложном успехе не сообщаем).
    """
    role = await get_user_role(chat_id, user_id)
    freed: Optional[str] = None
    if role is not None:
        rowcount = await _execute(
            "UPDATE chat_roles SET status = 'free', holder_user_id = NULL, "
            "reserved_user_id = NULL, reserved_at = NULL "
            "WHERE id = %s AND holder_user_id = %s AND status = 'taken'",
            (role["id"], user_id),
        )
        if rowcount:
            freed = role["name"]

    await _execute(
        "UPDATE chat_roles SET status = 'free', reserved_user_id = NULL, reserved_at = NULL "
        "WHERE chat_id = %s AND reserved_user_id = %s AND status = 'reserved'",
        (chat_id, user_id),
    )
    return freed


async def reserve_role(chat_id: int, role_id: int, user_id: int) -> bool:
    """Бронирует свободную роль за человеком, который ещё не в группе.

    Прежние брони того же человека снимаются — но только после того, как
    новая успешно проставлена. Без этой уборки заявитель мог нажать подряд
    все кнопки в списке и забронировать разом десяток ролей, которые потом
    висели занятыми до истечения таймаута.
    """
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'reserved', reserved_user_id = %s, reserved_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s AND id = %s AND status = 'free'",
        (user_id, chat_id, role_id),
    )
    if not rowcount:
        return False
    await _clear_other_roles_of_user(chat_id, user_id, role_id)
    return True


async def cancel_reservation(chat_id: int, role_id: int) -> bool:
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'free', reserved_user_id = NULL, reserved_at = NULL "
        "WHERE chat_id = %s AND id = %s AND status = 'reserved'",
        (chat_id, role_id),
    )
    return rowcount > 0


async def resolve_reservations_on_join(chat_id: int, user_id: int) -> list[dict]:
    """Вызывается при вступлении человека в группу (track_new_chat_members):
    превращает его активные брони в реальное владение ролью. Возвращает
    список ролей, которые реально достались пользователю."""
    rows = await _fetchall(
        "SELECT * FROM chat_roles WHERE chat_id = %s AND reserved_user_id = %s AND status = 'reserved' "
        "ORDER BY reserved_at",
        (chat_id, user_id),
    )
    granted = []
    for role in rows:
        if granted:
            # Человеку положена одна роль. Лишние брони (остались от старых
            # версий, где их можно было наставить пачкой) просто снимаем,
            # иначе он вошёл бы в чат сразу с несколькими ролями.
            await _execute(
                "UPDATE chat_roles SET status = 'free', reserved_user_id = NULL, reserved_at = NULL "
                "WHERE id = %s AND status = 'reserved' AND reserved_user_id = %s",
                (role["id"], user_id),
            )
            continue
        rowcount = await _execute(
            "UPDATE chat_roles SET status = 'taken', holder_user_id = %s, "
            "reserved_user_id = NULL, reserved_at = NULL "
            "WHERE id = %s AND status = 'reserved' AND reserved_user_id = %s",
            (user_id, role["id"], user_id),
        )
        if rowcount:
            granted.append(role)
            # если роль ему уже выдавали раньше (например, админ через
            # «роль отдать»), старую отпускаем — иначе останется занятой
            # без живого держателя
            await _clear_other_roles_of_user(chat_id, user_id, role["id"])
    return granted


async def expire_stale_reservations(timeout_hours: int) -> list[dict]:
    """Снимает брони старше timeout_hours (см. ROLE_RESERVE_TIMEOUT_HOURS в
    bot.py), возвращает те роли, что были освобождены — для уведомлений."""
    rows = await _fetchall(
        "SELECT * FROM chat_roles WHERE status = 'reserved' "
        "AND reserved_at < (UTC_TIMESTAMP() - INTERVAL %s HOUR)",
        (timeout_hours,),
    )
    if rows:
        await _execute(
            "UPDATE chat_roles SET status = 'free', reserved_user_id = NULL, reserved_at = NULL "
            "WHERE status = 'reserved' AND reserved_at < (UTC_TIMESTAMP() - INTERVAL %s HOUR)",
            (timeout_hours,),
        )
    return rows


async def force_set_role(chat_id: int, role_id: int, user_id: Optional[int]) -> bool:
    """Принудительное действие админа: назначить роль конкретному участнику
    (снимая её с прежнего держателя, если был) или снять её вовсе (user_id=None)."""
    if user_id is None:
        rowcount = await _execute(
            "UPDATE chat_roles SET status = 'free', holder_user_id = NULL, "
            "reserved_user_id = NULL, reserved_at = NULL WHERE chat_id = %s AND id = %s",
            (chat_id, role_id),
        )
        return rowcount > 0
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'taken', holder_user_id = %s, "
        "reserved_user_id = NULL, reserved_at = NULL WHERE chat_id = %s AND id = %s",
        (user_id, chat_id, role_id),
    )
    if not rowcount:
        return False
    # прежние роль и бронь этого человека отпускаем только после успеха —
    # иначе при неудаче он остался бы вообще без роли
    await _clear_other_roles_of_user(chat_id, user_id, role_id)
    return True


async def force_reserve_role(chat_id: int, role_id: int, user_id: int) -> bool:
    """Принудительное действие админа: забронировать роль за конкретным
    человеком (в т.ч. ещё не состоящим в группе), сняв её с прежнего
    держателя/забронировавшего, если был, — независимо от текущего статуса
    роли (свободна/занята/уже забронирована кем-то другим). В отличие от
    force_set_role (сразу «taken»), роль остаётся «reserved» и закрепится
    как «taken» автоматически при вступлении user_id в группу — см.
    resolve_reservations_on_join()."""
    role = await get_role(chat_id, role_id)
    if role is None:
        return False
    rowcount = await _execute(
        "UPDATE chat_roles SET status = 'reserved', holder_user_id = NULL, "
        "reserved_user_id = %s, reserved_at = UTC_TIMESTAMP() WHERE chat_id = %s AND id = %s",
        (user_id, chat_id, role_id),
    )
    if not rowcount:
        return False
    # прежние роль и бронь этого человека снимаем после успеха — у человека
    # не может быть больше одной роли
    await _clear_other_roles_of_user(chat_id, user_id, role_id)
    return True


async def delete_role(chat_id: int, role_id: int) -> bool:
    rowcount = await _execute("DELETE FROM chat_roles WHERE chat_id = %s AND id = %s", (chat_id, role_id))
    return rowcount > 0


# ----------------------------------------------------------------------------
# РП-действия («обнять» и т.п.) и себяшки («[поспать» и т.п.) — раньше жили
# как хардкод-словари в bot.py (RP_ACTIONS/RP_ACTION_SYNONYMS/SELF_ACTIONS),
# теперь редактируются через веб-панель администрирования. bot.py читает их
# в load_caches() (см. list_rp_actions/list_rp_action_synonyms/list_self_actions
# ниже) и держит в памяти как обычные dict — сами функции матчинга в bot.py
# не менялись, только источник данных.
#
# is_active — soft-delete: выключенное действие перестаёт матчиться в чате,
# но не пропадает из истории/БД (см. ТЗ п.3 — «включить/выключить действие
# целиком»). Заблокированные действия НЕ отдаются list_rp_actions/
# list_self_actions с active_only=True (используется в bot.py); сайт же
# всегда должен видеть все строки, поэтому там active_only=False.
#
# ВАЖНО: набор RP_ACTIONS_RESTRICTED_NO_TEXT_TARGET (какие action_key относятся
# к сексуализированным/описанным как насильственные действиям и потому не
# могут указывать цель через @username/ID) сознательно НЕ хранится в этих
# таблицах и остаётся хардкодом в bot.py — веб-сайт может только ПОКАЗАТЬ
# read-only, какие action_key туда входят (сверяясь с константой bot.py через
# отдельный небольшой JSON/API-эндпоинт на стороне сайта, не через БД), но не
# может ни добавить туда новый action_key, ни, тем более, добавить новые
# фразы для уже существующих — сайт для этой конкретной категории строго
# read-only на уровне вьюх сайта, без функций «добавить/изменить» в его коде.
# ----------------------------------------------------------------------------
async def ensure_rp_actions_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rp_actions ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "phrase VARCHAR(512) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rp_actions_key (action_key, sort_order)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_rp_action_synonyms_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rp_action_synonyms ("
        "synonym VARCHAR(64) NOT NULL PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "INDEX idx_rp_action_synonyms_key (action_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_self_actions_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS self_actions ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "phrase VARCHAR(512) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_self_actions_key (action_key, sort_order)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def seed_rp_actions_if_empty(defaults: dict[str, list[str]]) -> int:
    """Заполняет rp_actions дефолтными фразами из кода один раз — только если
    таблица ещё вообще пуста (первый запуск после миграции), чтобы поведение
    бота не изменилось. Возвращает число добавленных строк."""
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM rp_actions")
    if row and row["cnt"]:
        return 0
    count = 0
    for action_key, phrases in defaults.items():
        for i, phrase in enumerate(phrases):
            await _execute(
                "INSERT INTO rp_actions (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
                (action_key, phrase, i),
            )
            count += 1
    return count


async def seed_rp_action_synonyms_if_empty(defaults: dict[str, str]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM rp_action_synonyms")
    if row and row["cnt"]:
        return 0
    count = 0
    for synonym, action_key in defaults.items():
        await _execute(
            "INSERT IGNORE INTO rp_action_synonyms (synonym, action_key) VALUES (%s, %s)",
            (synonym, action_key),
        )
        count += 1
    return count


async def seed_self_actions_if_empty(defaults: dict[str, list[str]]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM self_actions")
    if row and row["cnt"]:
        return 0
    count = 0
    for action_key, phrases in defaults.items():
        for i, phrase in enumerate(phrases):
            await _execute(
                "INSERT INTO self_actions (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
                (action_key, phrase, i),
            )
            count += 1
    return count


async def list_rp_actions(active_only: bool = True) -> dict[str, list[str]]:
    """Возвращает {action_key: [фраза, ...]} — готовый формат для RP_ACTIONS
    в bot.py, отсортированный по sort_order. active_only=True — так вызывает
    bot.py (в чате не должны матчиться выключенные действия); сайт для своей
    таблицы редактирования вызывает active_only=False, чтобы видеть и
    выключенные строки тоже (см. list_rp_actions_rows)."""
    query = "SELECT action_key, phrase FROM rp_actions"
    if active_only:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY action_key, sort_order, id"
    rows = await _fetchall(query)
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["action_key"], []).append(r["phrase"])
    return result


async def list_rp_actions_rows() -> list[dict]:
    """Сырые строки (с id/is_active/sort_order) — то, что нужно сайту для
    таблицы редактирования, в отличие от list_rp_actions (плоский dict для
    самого бота)."""
    return await _fetchall(
        "SELECT id, action_key, phrase, sort_order, is_active FROM rp_actions "
        "ORDER BY action_key, sort_order, id"
    )


async def add_rp_action_phrase(action_key: str, phrase: str, sort_order: Optional[int] = None) -> int:
    if sort_order is None:
        row = await _fetchone(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM rp_actions WHERE action_key = %s",
            (action_key,),
        )
        sort_order = row["next_order"] if row else 0
    return await _execute(
        "INSERT INTO rp_actions (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
        (action_key, phrase, sort_order),
    )


async def update_rp_action_phrase(phrase_id: int, phrase: str) -> bool:
    rowcount = await _execute("UPDATE rp_actions SET phrase = %s WHERE id = %s", (phrase, phrase_id))
    return rowcount > 0


async def delete_rp_action_phrase(phrase_id: int) -> bool:
    rowcount = await _execute("DELETE FROM rp_actions WHERE id = %s", (phrase_id,))
    return rowcount > 0


async def set_rp_action_key_active(action_key: str, is_active: bool) -> int:
    """Включает/выключает ЦЕЛИКОМ действие (все его фразы разом) — это и есть
    soft-delete «выключить действие целиком» из ТЗ. Возвращает число строк."""
    return await _execute(
        "UPDATE rp_actions SET is_active = %s WHERE action_key = %s", (is_active, action_key)
    )


async def list_rp_action_synonyms() -> dict[str, str]:
    rows = await _fetchall("SELECT synonym, action_key FROM rp_action_synonyms")
    return {r["synonym"]: r["action_key"] for r in rows}


async def add_rp_action_synonym(synonym: str, action_key: str) -> None:
    await _execute(
        "INSERT INTO rp_action_synonyms (synonym, action_key) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE action_key = VALUES(action_key)",
        (synonym, action_key),
    )


async def delete_rp_action_synonym(synonym: str) -> bool:
    rowcount = await _execute("DELETE FROM rp_action_synonyms WHERE synonym = %s", (synonym,))
    return rowcount > 0


async def list_self_actions(active_only: bool = True) -> dict[str, list[str]]:
    """Готовый формат для SELF_ACTIONS в bot.py (см. docstring list_rp_actions)."""
    query = "SELECT action_key, phrase FROM self_actions"
    if active_only:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY action_key, sort_order, id"
    rows = await _fetchall(query)
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["action_key"], []).append(r["phrase"])
    return result


async def list_self_actions_rows() -> list[dict]:
    return await _fetchall(
        "SELECT id, action_key, phrase, sort_order, is_active FROM self_actions "
        "ORDER BY action_key, sort_order, id"
    )


async def add_self_action_phrase(action_key: str, phrase: str, sort_order: Optional[int] = None) -> int:
    if sort_order is None:
        row = await _fetchone(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM self_actions WHERE action_key = %s",
            (action_key,),
        )
        sort_order = row["next_order"] if row else 0
    return await _execute(
        "INSERT INTO self_actions (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
        (action_key, phrase, sort_order),
    )


async def update_self_action_phrase(phrase_id: int, phrase: str) -> bool:
    rowcount = await _execute("UPDATE self_actions SET phrase = %s WHERE id = %s", (phrase, phrase_id))
    return rowcount > 0


async def delete_self_action_phrase(phrase_id: int) -> bool:
    rowcount = await _execute("DELETE FROM self_actions WHERE id = %s", (phrase_id,))
    return rowcount > 0


async def set_self_action_key_active(action_key: str, is_active: bool) -> int:
    return await _execute(
        "UPDATE self_actions SET is_active = %s WHERE action_key = %s", (is_active, action_key)
    )


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
    # created_at — в UTC (UTC_TIMESTAMP()), а не CURRENT_TIMESTAMP: последняя
    # отражает часовой пояс сессии MySQL, а list_expired_propose_requests
    # сравнивает эту колонку с datetime.utcnow() (см. TIMESTAMPDIFF ниже). Тот
    # же перекос уже ловили на message_stats.last_message_at и
    # known_users.last_seen_at (см. increment_message_count/upsert_known_user):
    # если сессия MySQL не в UTC, created_at «уезжает» в будущее, разница
    # utcnow()-created_at выходит отрицательной — и просроченные предложения
    # никогда бы не находились сканером истечения.
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
    # last_at — та же история, что и created_at в propose_requests выше:
    # check_and_touch_propose_cooldown сравнивает эту колонку с
    # datetime.utcnow() в Python, поэтому колонка должна быть в UTC, а не в
    # часовом поясе сессии MySQL.
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
        "INSERT INTO propose_requests (chat_id, message_id, action_key, from_user_id, to_user_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())",
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
        "VALUES (%s, %s, %s, %s, UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE last_at = UTC_TIMESTAMP()",
        (chat_id, action_key, from_user_id, to_user_id),
    )
    return None


# ----------------------------------------------------------------------------
# Модуль «Отношения»: пороги уровней близости (RELATIONSHIP_LEVELS в bot.py),
# очки за действия (REL_ACTION_POINTS) и партнёрские действия с их фразами
# (REL_ONLY_PARTNER_ACTIONS). Как и rp_actions/self_actions выше — теперь
# живут в БД и редактируются через сайт, bot.py читает их в load_caches().
#
# relationship_actions хранит ОБА вида действий из REL_ACTION_POINTS:
#   - partner_only=FALSE — «общие» действия (обнять/поцеловать/...), они уже
#     есть в RP_ACTIONS/rp_actions, здесь только их points_delta;
#   - partner_only=TRUE  — доступны только с партнёром, их тексты фраз лежат
#     в relationship_action_phrases (аналог REL_ONLY_PARTNER_ACTIONS).
# ----------------------------------------------------------------------------
async def ensure_relationship_levels_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS relationship_levels ("
        "level_index INT NOT NULL PRIMARY KEY, "
        "name VARCHAR(64) NOT NULL, "
        "points_threshold INT NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_relationship_actions_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS relationship_actions ("
        "action_key VARCHAR(64) NOT NULL PRIMARY KEY, "
        "points_delta INT NOT NULL, "
        "partner_only BOOL NOT NULL DEFAULT FALSE"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_relationship_action_phrases_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS relationship_action_phrases ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "action_key VARCHAR(64) NOT NULL, "
        "phrase VARCHAR(512) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0, "
        "INDEX idx_rel_action_phrases_key (action_key, sort_order)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def seed_relationship_levels_if_empty(defaults: list[tuple[str, int]]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM relationship_levels")
    if row and row["cnt"]:
        return 0
    for i, (name, threshold) in enumerate(defaults):
        await _execute(
            "INSERT INTO relationship_levels (level_index, name, points_threshold) VALUES (%s, %s, %s)",
            (i, name, threshold),
        )
    return len(defaults)


async def seed_relationship_actions_if_empty(
    points_defaults: dict[str, int], partner_only_keys: set[str]
) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM relationship_actions")
    if row and row["cnt"]:
        return 0
    for action_key, points in points_defaults.items():
        await _execute(
            "INSERT INTO relationship_actions (action_key, points_delta, partner_only) VALUES (%s, %s, %s)",
            (action_key, points, action_key in partner_only_keys),
        )
    return len(points_defaults)


async def seed_relationship_action_phrases_if_empty(defaults: dict[str, list[str]]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM relationship_action_phrases")
    if row and row["cnt"]:
        return 0
    count = 0
    for action_key, phrases in defaults.items():
        for i, phrase in enumerate(phrases):
            await _execute(
                "INSERT INTO relationship_action_phrases (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
                (action_key, phrase, i),
            )
            count += 1
    return count


async def list_relationship_levels() -> list[tuple[str, int]]:
    """[(имя, порог), ...] по возрастанию level_index — формат для
    RELATIONSHIP_LEVELS в bot.py (порядок важен: relationship_level_index
    и relationship_next_level_info идут по списку от младшего уровня к
    старшему)."""
    rows = await _fetchall(
        "SELECT name, points_threshold FROM relationship_levels ORDER BY level_index"
    )
    return [(r["name"], int(r["points_threshold"])) for r in rows]


async def list_relationship_levels_rows() -> list[dict]:
    return await _fetchall(
        "SELECT level_index, name, points_threshold FROM relationship_levels ORDER BY level_index"
    )


async def upsert_relationship_level(level_index: int, name: str, points_threshold: int) -> None:
    await _execute(
        "INSERT INTO relationship_levels (level_index, name, points_threshold) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE name = VALUES(name), points_threshold = VALUES(points_threshold)",
        (level_index, name, points_threshold),
    )


async def delete_relationship_level(level_index: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM relationship_levels WHERE level_index = %s", (level_index,)
    )
    return rowcount > 0


async def list_relationship_actions() -> dict[str, int]:
    """{action_key: points_delta} — формат для REL_ACTION_POINTS в bot.py."""
    rows = await _fetchall("SELECT action_key, points_delta FROM relationship_actions")
    return {r["action_key"]: int(r["points_delta"]) for r in rows}


async def list_relationship_actions_rows() -> list[dict]:
    return await _fetchall(
        "SELECT action_key, points_delta, partner_only FROM relationship_actions ORDER BY action_key"
    )


async def upsert_relationship_action(action_key: str, points_delta: int, partner_only: bool) -> None:
    await _execute(
        "INSERT INTO relationship_actions (action_key, points_delta, partner_only) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE points_delta = VALUES(points_delta), partner_only = VALUES(partner_only)",
        (action_key, points_delta, partner_only),
    )


async def delete_relationship_action(action_key: str) -> bool:
    rowcount = await _execute(
        "DELETE FROM relationship_actions WHERE action_key = %s", (action_key,)
    )
    # Фразы партнёрского действия (если были) без соответствующей строки в
    # relationship_actions больше не нужны — подчищаем, чтобы не оставалось
    # "осиротевших" фраз без начисления очков за действие.
    await _execute("DELETE FROM relationship_action_phrases WHERE action_key = %s", (action_key,))
    return rowcount > 0


async def list_relationship_action_phrases() -> dict[str, list[str]]:
    """{action_key: [фраза, ...]} — формат для REL_ONLY_PARTNER_ACTIONS в bot.py."""
    rows = await _fetchall(
        "SELECT action_key, phrase FROM relationship_action_phrases ORDER BY action_key, sort_order, id"
    )
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["action_key"], []).append(r["phrase"])
    return result


async def list_relationship_action_phrases_rows() -> list[dict]:
    return await _fetchall(
        "SELECT id, action_key, phrase, sort_order FROM relationship_action_phrases "
        "ORDER BY action_key, sort_order, id"
    )


async def add_relationship_action_phrase(
    action_key: str, phrase: str, sort_order: Optional[int] = None
) -> int:
    if sort_order is None:
        row = await _fetchone(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
            "FROM relationship_action_phrases WHERE action_key = %s",
            (action_key,),
        )
        sort_order = row["next_order"] if row else 0
    return await _execute(
        "INSERT INTO relationship_action_phrases (action_key, phrase, sort_order) VALUES (%s, %s, %s)",
        (action_key, phrase, sort_order),
    )


async def update_relationship_action_phrase(phrase_id: int, phrase: str) -> bool:
    rowcount = await _execute(
        "UPDATE relationship_action_phrases SET phrase = %s WHERE id = %s", (phrase, phrase_id)
    )
    return rowcount > 0


async def delete_relationship_action_phrase(phrase_id: int) -> bool:
    rowcount = await _execute("DELETE FROM relationship_action_phrases WHERE id = %s", (phrase_id,))
    return rowcount > 0


# ============================================================================
# Плагин «Отношения 2.0» (rel2_*) — расширенная система по образцу Iris
# (см. relationships_v2.py). Отдельные таблицы rel2_* — НЕ пересекаются со
# старыми relationships/relationship_requests (тот модуль остаётся рабочим,
# пока rel2 не заменит его в bot.py, см. комментарий в начале relationships_v2.py).
#
# Ключевое отличие от старого модуля: здесь «искры» — это одновременно и
# валюта (тратится/сгорает), и мера уровня (уровень = функция ТЕКУЩЕГО
# баланса искр, а не накопленных очков) — см. rel2_levels ниже.
# ============================================================================
async def ensure_rel2_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_pairs ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user1_id BIGINT NOT NULL, "
        "user2_id BIGINT NOT NULL, "
        "sparks INT NOT NULL DEFAULT 0, "
        "level_index INT NOT NULL DEFAULT 1, "
        "premium BOOL NOT NULL DEFAULT TRUE, "
        "premium_insurance_used BOOL NOT NULL DEFAULT FALSE, "
        "children_count INT NOT NULL DEFAULT 0, "
        "started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "last_bonus_at DATETIME NULL, "
        "last_charge_at DATETIME NULL, "
        "INDEX idx_rel2_pairs_chat (chat_id), "
        "INDEX idx_rel2_pairs_user1 (chat_id, user1_id), "
        "INDEX idx_rel2_pairs_user2 (chat_id, user2_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_requests ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "from_user_id BIGINT NOT NULL, "
        "to_user_id BIGINT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_req_to (chat_id, to_user_id), "
        "INDEX idx_rel2_req_from (chat_id, from_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_spark_log ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL, "
        "delta INT NOT NULL, "
        "reason VARCHAR(64) NOT NULL, "
        "balance_after INT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_spark_log_pair (pair_id, created_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_levels ("
        "level_index INT NOT NULL PRIMARY KEY, "
        "name VARCHAR(64) NOT NULL, "
        "sparks_threshold INT NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # ⚠️ Добавлено позже базовой схемы — безопасная миграция ADD COLUMN IF NOT
    # EXISTS для уже существующих rel2_pairs. Защита от беременности «отн
    # презик»: включена по умолчанию (TRUE), т.е. по умолчанию пара защищена
    # и «отн зачать» ничего не даст, пока защиту явно не выключат.
    await _add_column_if_missing(
        "rel2_pairs", "contraception", "BOOL NOT NULL DEFAULT TRUE"
    )
    # last_bonus_at/last_charge_at заведены в CREATE позже базовой схемы —
    # без этих ALTER на СТАРЫХ rel2_pairs колонок нет, и ежедневное списание
    # (spark_decay_loop → list_rel2_pairs_due_for_charge/set_rel2_last_charge_at)
    # молча падает: искры не тратятся. То же и для «отн бонус» (last_bonus_at).
    await _add_column_if_missing("rel2_pairs", "last_bonus_at", "DATETIME NULL")
    await _add_column_if_missing("rel2_pairs", "last_charge_at", "DATETIME NULL")

    # РЕШЕНО: премиум выдан всем безвозмездно, продажи премиума не будет —
    # значит отдельная колонка premium как «признак платной подписки» больше
    # не нужна, но раскатывать миграцию по удалению колонки (и переписывать
    # все ~40 мест кода, которые читают pair["premium"]) — риск регрессий без
    # реальной пользы: сама механика «премиум даёт бонус» никуда не делась,
    # просто её получают все бесплатно. Поэтому эффект «премиум у всех»
    # реализован в одном месте: default колонки TRUE (новые пары) + разовый
    # бэкафилл существующих пар ниже (старые пары тоже получают доступ).
    # ALTER... SET DEFAULT безопасен и идемпотентен — можно гонять при каждом
    # старте бота.
    await _execute("ALTER TABLE rel2_pairs ALTER premium SET DEFAULT TRUE")
    await _execute("UPDATE rel2_pairs SET premium = TRUE WHERE premium = FALSE")


async def seed_rel2_levels_if_empty(rows: list[tuple[int, str, int]]) -> int:
    """rows: [(level_index, name, sparks_threshold), ...] — см. build_rel2_level_table()
    в relationships_v2.py (формула и вехи названий — из гайда «Отношения»)."""
    existing = await _fetchone("SELECT COUNT(*) AS cnt FROM rel2_levels")
    if existing and existing["cnt"]:
        return 0
    for level_index, name, threshold in rows:
        await _execute(
            "INSERT INTO rel2_levels (level_index, name, sparks_threshold) VALUES (%s, %s, %s)",
            (level_index, name, threshold),
        )
    return len(rows)


async def get_rel2_level_name(level_index: int) -> Optional[str]:
    """Название уровня отношений по индексу (для карточки участника на сайте)."""
    row = await _fetchone(
        "SELECT name FROM rel2_levels WHERE level_index = %s", (level_index,)
    )
    return row["name"] if row else None


async def list_rel2_levels() -> list[tuple[int, str, int]]:
    rows = await _fetchall(
        "SELECT level_index, name, sparks_threshold FROM rel2_levels ORDER BY level_index"
    )
    return [(int(r["level_index"]), r["name"], int(r["sparks_threshold"])) for r in rows]


def _rel2_pair_row_to_dict(row: dict, user_id: int) -> dict:
    partner_id = row["user2_id"] if row["user1_id"] == user_id else row["user1_id"]
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "partner_id": partner_id,
        "sparks": row["sparks"],
        "level_index": row["level_index"],
        "premium": bool(row["premium"]),
        "premium_insurance_used": bool(row["premium_insurance_used"]),
        "children_count": row["children_count"],
        "contraception": bool(row["contraception"]),
        "started_at": row["started_at"],
        "last_bonus_at": row["last_bonus_at"],
        "last_charge_at": row["last_charge_at"],
    }


async def get_rel2_pair(chat_id: int, user_id: int) -> Optional[dict]:
    row = await _fetchone(
        "SELECT id, chat_id, user1_id, user2_id, sparks, level_index, premium, "
        "premium_insurance_used, children_count, contraception, started_at, last_bonus_at, last_charge_at "
        "FROM rel2_pairs WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s) LIMIT 1",
        (chat_id, user_id, user_id),
    )
    if row is None:
        return None
    return _rel2_pair_row_to_dict(row, user_id)


async def get_rel2_pair_by_id(pair_id: int) -> Optional[dict]:
    row = await _fetchone(
        "SELECT id, chat_id, user1_id, user2_id, sparks, level_index, premium, "
        "premium_insurance_used, children_count, contraception, started_at, last_bonus_at, last_charge_at "
        "FROM rel2_pairs WHERE id = %s",
        (pair_id,),
    )
    if row is None:
        return None
    return _rel2_pair_row_to_dict(row, row["user1_id"])


async def list_rel2_pairs(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Топ пар чата по искрам (для «отн список») + общее количество."""
    count_row = await _fetchone("SELECT COUNT(*) AS total FROM rel2_pairs WHERE chat_id = %s", (chat_id,))
    rows = await _fetchall(
        "SELECT id, user1_id, user2_id, sparks, level_index, premium FROM rel2_pairs "
        "WHERE chat_id = %s ORDER BY sparks DESC, id ASC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


async def create_rel2_pair(chat_id: int, user_a: int, user_b: int, start_sparks: int = 0) -> Optional[int]:
    """Создаёт пару атомарно (GET_LOCK, как create_relationship выше);
    возвращает id новой пары либо None, если кто-то из двоих уже занят."""
    u1, u2 = sorted((user_a, user_b))
    pool = _require_pool()
    lock_name = f"rel2_pair:{chat_id}"
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT GET_LOCK(%s, 5) AS acquired", (lock_name,))
            lock = await cur.fetchone()
            if not lock or lock["acquired"] != 1:
                return None
            try:
                await cur.execute(
                    "SELECT 1 FROM rel2_pairs WHERE chat_id = %s "
                    "AND (user1_id IN (%s, %s) OR user2_id IN (%s, %s)) LIMIT 1",
                    (chat_id, u1, u2, u1, u2),
                )
                if await cur.fetchone():
                    return None
                await cur.execute(
                    "INSERT INTO rel2_pairs (chat_id, user1_id, user2_id, sparks, level_index) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (chat_id, u1, u2, start_sparks),
                )
                return cur.lastrowid
            finally:
                await cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))


async def delete_rel2_pair(chat_id: int, user_id: int) -> Optional[int]:
    """Удаляет пару пользователя (разрыв/сгорание искр в ноль). Возвращает id
    удалённой пары (для очистки rel2_spark_log вызывающим кодом) либо None."""
    row = await _fetchone(
        "SELECT id FROM rel2_pairs WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s) LIMIT 1",
        (chat_id, user_id, user_id),
    )
    if row is None:
        return None
    await _execute("DELETE FROM rel2_pairs WHERE id = %s", (row["id"],))
    await _execute("DELETE FROM rel2_spark_log WHERE pair_id = %s", (row["id"],))
    await _execute(
        "UPDATE rel2_pregnancies SET status = 'ended', ended_at = CURRENT_TIMESTAMP "
        "WHERE pair_id = %s AND status = 'active'",
        (row["id"],),
    )
    return row["id"]


async def get_rel2_pair_row(chat_id: int, user_id: int) -> Optional[dict]:
    """Сырая строка пары (все колонки) — для снимка перед разрывом (см. отмену)."""
    return await _fetchone(
        "SELECT * FROM rel2_pairs WHERE chat_id = %s AND (user1_id = %s OR user2_id = %s) LIMIT 1",
        (chat_id, user_id, user_id),
    )


async def restore_rel2_pair_row(row: dict) -> bool:
    """Восстанавливает пару из снимка ТЕМ ЖЕ id: дети (rel2_children) при разрыве
    не удаляются, поэтому по прежнему id переподключаются сами. Искры-лог не
    восстанавливаем (баланс берётся из снимка). False, если кто-то из двоих уже
    в новой паре."""
    chat_id, u1, u2 = row["chat_id"], row["user1_id"], row["user2_id"]
    busy = await _fetchone(
        "SELECT id FROM rel2_pairs WHERE chat_id = %s "
        "AND (user1_id IN (%s, %s) OR user2_id IN (%s, %s)) LIMIT 1",
        (chat_id, u1, u2, u1, u2),
    )
    if busy:
        return False
    await _execute(
        "INSERT INTO rel2_pairs (id, chat_id, user1_id, user2_id, sparks, level_index, premium, "
        "premium_insurance_used, children_count, contraception, started_at, last_bonus_at, last_charge_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (row["id"], chat_id, u1, u2, row["sparks"], row["level_index"], row["premium"],
         row["premium_insurance_used"], row["children_count"], row["contraception"],
         row["started_at"], row.get("last_bonus_at"), row.get("last_charge_at")),
    )
    return True


async def adjust_rel2_sparks(pair_id: int, delta: int, reason: str, floor_at_zero: bool = True) -> Optional[int]:
    """Атомарно меняет баланс искр пары (single UPDATE — без гонок между
    параллельными начислениями) и пишет запись в rel2_spark_log. Возвращает
    новый баланс либо None, если пары уже не существует."""
    expr = "GREATEST(sparks + %s, 0)" if floor_at_zero else "sparks + %s"
    await _execute(f"UPDATE rel2_pairs SET sparks = {expr} WHERE id = %s", (delta, pair_id))
    row = await _fetchone("SELECT sparks FROM rel2_pairs WHERE id = %s", (pair_id,))
    if row is None:
        return None
    new_balance = int(row["sparks"])
    await _execute(
        "INSERT INTO rel2_spark_log (pair_id, delta, reason, balance_after) VALUES (%s, %s, %s, %s)",
        (pair_id, delta, reason, new_balance),
    )
    return new_balance


async def set_rel2_level(pair_id: int, level_index: int) -> None:
    await _execute("UPDATE rel2_pairs SET level_index = %s WHERE id = %s", (level_index, pair_id))


async def set_rel2_contraception(pair_id: int, enabled: bool) -> None:
    await _execute(
        "UPDATE rel2_pairs SET contraception = %s WHERE id = %s", (enabled, pair_id)
    )


# ============================================================================
# 🤰 Модуль 12b — БЕРЕМЕННОСТЬ (rel2_pregnancies). Полноценный цикл в 40 игровых
# недель (см. PREGNANCY_TOTAL_WEEKS/PREGNANCY_HOURS_PER_WEEK в relationships_v2.py),
# запускается успешной попыткой «отн зачать» и завершается через «отн родить»,
# когда неделя 40 достигнута. Одна активная беременность на пару одновременно.
# ============================================================================
async def ensure_rel2_pregnancy_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_pregnancies ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL, "
        "chat_id BIGINT NOT NULL, "
        "initiator_id BIGINT NOT NULL, "
        "status VARCHAR(16) NOT NULL DEFAULT 'active', "
        "last_milestone_week INT NOT NULL DEFAULT 0, "
        "started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "ended_at DATETIME NULL, "
        "INDEX idx_rel2_pregnancies_pair (pair_id), "
        "INDEX idx_rel2_pregnancies_status (status)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("rel2_child_requests", "pregnancy_id", "INT NULL")


async def create_rel2_pregnancy(pair_id: int, chat_id: int, initiator_id: int) -> int:
    await _execute(
        "INSERT INTO rel2_pregnancies (pair_id, chat_id, initiator_id) VALUES (%s, %s, %s)",
        (pair_id, chat_id, initiator_id),
    )
    row = await _fetchone(
        "SELECT id FROM rel2_pregnancies WHERE pair_id = %s ORDER BY id DESC LIMIT 1", (pair_id,)
    )
    return row["id"]


async def get_active_rel2_pregnancy(pair_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM rel2_pregnancies WHERE pair_id = %s AND status = 'active' "
        "ORDER BY id DESC LIMIT 1",
        (pair_id,),
    )


async def get_rel2_pregnancy(pregnancy_id: int) -> Optional[dict]:
    return await _fetchone("SELECT * FROM rel2_pregnancies WHERE id = %s", (pregnancy_id,))


async def set_rel2_pregnancy_milestone(pregnancy_id: int, week: int) -> None:
    await _execute(
        "UPDATE rel2_pregnancies SET last_milestone_week = %s WHERE id = %s", (week, pregnancy_id)
    )


async def complete_rel2_pregnancy(pregnancy_id: int) -> None:
    await _execute(
        "UPDATE rel2_pregnancies SET status = 'born', ended_at = CURRENT_TIMESTAMP WHERE id = %s",
        (pregnancy_id,),
    )


async def cancel_rel2_pregnancy(pregnancy_id: int) -> None:
    await _execute(
        "UPDATE rel2_pregnancies SET status = 'ended', ended_at = CURRENT_TIMESTAMP WHERE id = %s",
        (pregnancy_id,),
    )


async def list_active_rel2_pregnancies_for_tick() -> list[dict]:
    """Для фонового объявления вех (см. pregnancy_announce_loop): активные
    беременности + premium пары (влияет на PREGNANCY_HOURS_PER_WEEK)."""
    return await _fetchall(
        "SELECT p.*, r.premium AS pair_premium FROM rel2_pregnancies p "
        "JOIN rel2_pairs r ON r.id = p.pair_id "
        "WHERE p.status = 'active'"
    )


async def set_rel2_last_bonus_at(pair_id: int) -> None:
    await _execute(
        "UPDATE rel2_pairs SET last_bonus_at = CURRENT_TIMESTAMP WHERE id = %s", (pair_id,)
    )


async def set_rel2_last_charge_at(pair_id: int) -> None:
    await _execute(
        "UPDATE rel2_pairs SET last_charge_at = CURRENT_TIMESTAMP WHERE id = %s", (pair_id,)
    )


async def set_rel2_premium(pair_id: int, premium: bool) -> None:
    await _execute("UPDATE rel2_pairs SET premium = %s WHERE id = %s", (premium, pair_id))


async def mark_rel2_premium_insurance_used(pair_id: int) -> None:
    await _execute(
        "UPDATE rel2_pairs SET premium_insurance_used = TRUE WHERE id = %s", (pair_id,)
    )


async def list_rel2_pairs_due_for_charge(hours: int = 24) -> list[dict]:
    """Пары, которым пора списать дневной расход искр (см. spark_decay_loop()
    в relationship_v2.py) — ни разу не списывали, либо последний раз это было
    больше `hours` часов назад."""
    return await _fetchall(
        "SELECT id, chat_id, user1_id, user2_id, sparks, level_index, premium, "
        "premium_insurance_used, children_count FROM rel2_pairs "
        "WHERE last_charge_at IS NULL OR last_charge_at <= (NOW() - INTERVAL %s HOUR)",
        (hours,),
    )


async def list_rel2_spark_log(pair_id: int, limit: int = 15) -> list[dict]:
    return await _fetchall(
        "SELECT delta, reason, balance_after, created_at FROM rel2_spark_log "
        "WHERE pair_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
        (pair_id, limit),
    )


# ----------------------------------------------------------------------------
# Заявки на отношения 2.0 («отн запрос {ссылка/ответом}», принимаются «+отн»)
# ----------------------------------------------------------------------------
async def create_rel2_request(chat_id: int, from_user_id: int, to_user_id: int) -> None:
    """Новая заявка перезаписывает предыдущую от того же отправителя в чате."""
    await _execute(
        "DELETE FROM rel2_requests WHERE chat_id = %s AND from_user_id = %s",
        (chat_id, from_user_id),
    )
    await _execute(
        "INSERT INTO rel2_requests (chat_id, from_user_id, to_user_id) VALUES (%s, %s, %s)",
        (chat_id, from_user_id, to_user_id),
    )


async def get_latest_rel2_request(chat_id: int, to_user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT from_user_id, to_user_id, created_at FROM rel2_requests "
        "WHERE chat_id = %s AND to_user_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
        (chat_id, to_user_id),
    )


async def delete_rel2_request(chat_id: int, from_user_id: int, to_user_id: int) -> None:
    await _execute(
        "DELETE FROM rel2_requests WHERE chat_id = %s AND from_user_id = %s AND to_user_id = %s",
        (chat_id, from_user_id, to_user_id),
    )


async def clear_rel2_requests_for(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM rel2_requests WHERE chat_id = %s AND (from_user_id = %s OR to_user_id = %s)",
        (chat_id, user_id, user_id),
    )


# ============================================================================
# 🏠 Модуль 3 «Отношения 2.0»: система домов (rel2_houses / rel2_house_rooms /
# rel2_house_upgrades) — см. каталоги HOUSE_CATALOG/ROOM_CATALOG/UPGRADE_CATALOG
# и всю логику в relationships_v2.py. Один дом на пару (rel2_pairs.id),
# комнаты и улучшения — отдельные таблицы 1-N от дома (у комнаты/улучшения
# есть свой уровень 1-4 и, для комнат с действием, свой кулдаун).
# ============================================================================
async def ensure_rel2_house_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_houses ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL UNIQUE, "
        "house_key VARCHAR(64) NOT NULL, "
        "status VARCHAR(16) NOT NULL DEFAULT 'building', "
        "built_at DATETIME NULL, "
        "ready_at DATETIME NOT NULL, "
        "last_maintenance_at DATETIME NULL, "
        "maintenance_warning_at DATETIME NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_houses_pair (pair_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_house_rooms ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "house_id INT NOT NULL, "
        "room_key VARCHAR(64) NOT NULL, "
        "level INT NOT NULL DEFAULT 1, "
        "last_action_at DATETIME NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uq_rel2_house_room (house_id, room_key), "
        "INDEX idx_rel2_house_rooms_house (house_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_house_upgrades ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "house_id INT NOT NULL, "
        "upgrade_key VARCHAR(64) NOT NULL, "
        "level INT NOT NULL DEFAULT 1, "
        "UNIQUE KEY uq_rel2_house_upgrade (house_id, upgrade_key), "
        "INDEX idx_rel2_house_upgrades_house (house_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_rel2_house(pair_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, pair_id, house_key, status, built_at, ready_at, "
        "last_maintenance_at, maintenance_warning_at, created_at "
        "FROM rel2_houses WHERE pair_id = %s",
        (pair_id,),
    )


async def create_rel2_house(pair_id: int, house_key: str, ready_at: datetime) -> Optional[int]:
    """Возвращает id нового дома либо None, если у пары уже есть дом (UNIQUE pair_id)."""
    existing = await get_rel2_house(pair_id)
    if existing:
        return None
    await _execute(
        "INSERT INTO rel2_houses (pair_id, house_key, status, ready_at) "
        "VALUES (%s, %s, 'building', %s)",
        (pair_id, house_key, ready_at),
    )
    row = await _fetchone("SELECT id FROM rel2_houses WHERE pair_id = %s", (pair_id,))
    return row["id"] if row else None


async def finish_rel2_house_construction(house_id: int) -> None:
    await _execute(
        "UPDATE rel2_houses SET status = 'active', built_at = CURRENT_TIMESTAMP, "
        "last_maintenance_at = CURRENT_TIMESTAMP WHERE id = %s",
        (house_id,),
    )


async def list_rel2_houses_building_due() -> list[dict]:
    return await _fetchall(
        "SELECT id, pair_id, house_key FROM rel2_houses "
        "WHERE status = 'building' AND ready_at <= NOW()"
    )


async def delete_rel2_house(house_id: int) -> None:
    await _execute("DELETE FROM rel2_house_rooms WHERE house_id = %s", (house_id,))
    await _execute("DELETE FROM rel2_house_upgrades WHERE house_id = %s", (house_id,))
    await _execute("DELETE FROM rel2_houses WHERE id = %s", (house_id,))


async def list_rel2_house_rooms(house_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT id, room_key, level, last_action_at FROM rel2_house_rooms "
        "WHERE house_id = %s ORDER BY id ASC",
        (house_id,),
    )


async def get_rel2_house_room(house_id: int, room_key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT id, room_key, level, last_action_at FROM rel2_house_rooms "
        "WHERE house_id = %s AND room_key = %s",
        (house_id, room_key),
    )


async def add_rel2_house_room(house_id: int, room_key: str) -> None:
    await _execute(
        "INSERT IGNORE INTO rel2_house_rooms (house_id, room_key, level) VALUES (%s, %s, 1)",
        (house_id, room_key),
    )


async def upgrade_rel2_house_room_level(house_id: int, room_key: str) -> None:
    await _execute(
        "UPDATE rel2_house_rooms SET level = level + 1 WHERE house_id = %s AND room_key = %s",
        (house_id, room_key),
    )


async def remove_rel2_house_room(house_id: int, room_key: str) -> None:
    await _execute(
        "DELETE FROM rel2_house_rooms WHERE house_id = %s AND room_key = %s",
        (house_id, room_key),
    )


async def set_rel2_house_room_last_action(house_id: int, room_key: str) -> None:
    await _execute(
        "UPDATE rel2_house_rooms SET last_action_at = CURRENT_TIMESTAMP "
        "WHERE house_id = %s AND room_key = %s",
        (house_id, room_key),
    )


async def list_rel2_house_upgrades(house_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT upgrade_key, level FROM rel2_house_upgrades WHERE house_id = %s",
        (house_id,),
    )


async def get_rel2_house_upgrade(house_id: int, upgrade_key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT upgrade_key, level FROM rel2_house_upgrades WHERE house_id = %s AND upgrade_key = %s",
        (house_id, upgrade_key),
    )


async def bump_rel2_house_upgrade(house_id: int, upgrade_key: str) -> None:
    await _execute(
        "INSERT INTO rel2_house_upgrades (house_id, upgrade_key, level) VALUES (%s, %s, 1) "
        "ON DUPLICATE KEY UPDATE level = level + 1",
        (house_id, upgrade_key),
    )


async def list_rel2_houses_due_for_maintenance(days: int = 7) -> list[dict]:
    return await _fetchall(
        "SELECT h.id, h.pair_id, h.house_key, h.maintenance_warning_at, p.chat_id, "
        "p.user1_id, p.user2_id, p.premium, p.sparks "
        "FROM rel2_houses h JOIN rel2_pairs p ON p.id = h.pair_id "
        "WHERE h.status = 'active' "
        "AND (h.last_maintenance_at IS NULL OR h.last_maintenance_at <= (NOW() - INTERVAL %s DAY))",
        (days,),
    )


async def set_rel2_house_maintenance_paid(house_id: int) -> None:
    await _execute(
        "UPDATE rel2_houses SET last_maintenance_at = CURRENT_TIMESTAMP, "
        "maintenance_warning_at = NULL WHERE id = %s",
        (house_id,),
    )


async def set_rel2_house_maintenance_warning(house_id: int) -> None:
    await _execute(
        "UPDATE rel2_houses SET maintenance_warning_at = CURRENT_TIMESTAMP WHERE id = %s",
        (house_id,),
    )


async def list_rel2_houses_overdue(grace_days: int = 3) -> list[dict]:
    """Дома, у которых предупреждение об обслуживании висит дольше grace_days —
    подлежат сносу (см. house_maintenance_loop в relationships_v2.py)."""
    return await _fetchall(
        "SELECT h.id, h.pair_id, h.house_key, p.chat_id, p.user1_id, p.user2_id "
        "FROM rel2_houses h JOIN rel2_pairs p ON p.id = h.pair_id "
        "WHERE h.status = 'active' AND h.maintenance_warning_at IS NOT NULL "
        "AND h.maintenance_warning_at <= (NOW() - INTERVAL %s DAY)",
        (grace_days,),
    )


# ============================================================================
# 🐾 Модуль 4 «Отношения 2.0»: система питомцев (rel2_pets / rel2_pet_homes).
# Питомцы принадлежат паре (pair_id) — кормятся из общей казны искр пары,
# как и указано в гайде («Стоимость списывается из казны отношений»).
# skills хранится как JSON-список [{"key":..., "level":...}, ...], т.к. набор
# навыков случаен и произволен по длине — отдельная таблица ради 1-3 строк
# на питомца была бы избыточна.
# ============================================================================
async def ensure_rel2_pet_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_pets ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL, "
        "name VARCHAR(32) NOT NULL, "
        "species VARCHAR(64) NOT NULL, "
        "rarity VARCHAR(16) NOT NULL, "
        "egg_key VARCHAR(32) NOT NULL, "
        "temperament INT NOT NULL, "
        "skills_json TEXT NOT NULL, "
        "level_index INT NOT NULL DEFAULT 1, "
        "xp INT NOT NULL DEFAULT 0, "
        "hp INT NOT NULL DEFAULT 100, "
        "mood INT NOT NULL DEFAULT 100, "
        "food_need INT NOT NULL, "
        "water_need INT NOT NULL, "
        "is_active BOOL NOT NULL DEFAULT FALSE, "
        "home_id INT NULL, "
        "last_action_play DATETIME NULL, "
        "last_action_pet DATETIME NULL, "
        "last_action_train DATETIME NULL, "
        "last_action_treat DATETIME NULL, "
        "last_fed_at DATETIME NULL, "
        "last_mood_tick_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "hatched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_pets_pair (pair_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_pet_homes ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL, "
        "pet_id INT NOT NULL UNIQUE, "
        "home_key VARCHAR(32) NOT NULL, "
        "rooms_json TEXT NOT NULL DEFAULT '[]', "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


def _rel2_pet_row(row: dict) -> dict:
    import json as _json
    d = dict(row)
    d["skills"] = _json.loads(d.pop("skills_json") or "[]")
    d["is_active"] = bool(d["is_active"])
    return d


async def create_rel2_pet(
    pair_id: int, name: str, species: str, rarity: str, egg_key: str,
    temperament: int, skills: list[dict], food_need: int, water_need: int,
) -> int:
    import json as _json
    make_active = not await has_any_active_rel2_pet(pair_id)
    await _execute(
        "INSERT INTO rel2_pets (pair_id, name, species, rarity, egg_key, temperament, "
        "skills_json, food_need, water_need, is_active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (pair_id, name, species, rarity, egg_key, temperament, _json.dumps(skills, ensure_ascii=False),
         food_need, water_need, make_active),
    )
    row = await _fetchone(
        "SELECT id FROM rel2_pets WHERE pair_id = %s ORDER BY id DESC LIMIT 1", (pair_id,)
    )
    return row["id"]


async def has_any_active_rel2_pet(pair_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM rel2_pets WHERE pair_id = %s AND is_active = TRUE LIMIT 1", (pair_id,)
    )
    return row is not None


async def list_rel2_pets(pair_id: int) -> list[dict]:
    rows = await _fetchall(
        "SELECT * FROM rel2_pets WHERE pair_id = %s ORDER BY id ASC", (pair_id,)
    )
    return [_rel2_pet_row(r) for r in rows]


async def get_rel2_pet(pet_id: int) -> Optional[dict]:
    row = await _fetchone("SELECT * FROM rel2_pets WHERE id = %s", (pet_id,))
    return _rel2_pet_row(row) if row else None


async def get_rel2_active_pet(pair_id: int) -> Optional[dict]:
    row = await _fetchone(
        "SELECT * FROM rel2_pets WHERE pair_id = %s AND is_active = TRUE LIMIT 1", (pair_id,)
    )
    return _rel2_pet_row(row) if row else None


async def set_rel2_active_pet(pair_id: int, pet_id: int) -> None:
    await _execute("UPDATE rel2_pets SET is_active = FALSE WHERE pair_id = %s", (pair_id,))
    await _execute(
        "UPDATE rel2_pets SET is_active = TRUE WHERE id = %s AND pair_id = %s", (pet_id, pair_id)
    )


async def rename_rel2_pet(pet_id: int, name: str) -> None:
    await _execute("UPDATE rel2_pets SET name = %s WHERE id = %s", (name, pet_id))


async def release_rel2_pet(pet_id: int) -> None:
    await _execute("DELETE FROM rel2_pet_homes WHERE pet_id = %s", (pet_id,))
    await _execute("DELETE FROM rel2_pets WHERE id = %s", (pet_id,))


async def set_rel2_pet_mood_hp(pet_id: int, mood: int, hp: int) -> None:
    await _execute(
        "UPDATE rel2_pets SET mood = %s, hp = %s, last_mood_tick_at = CURRENT_TIMESTAMP WHERE id = %s",
        (max(0, min(100, mood)), max(0, min(100, hp)), pet_id),
    )


async def set_rel2_pet_last_fed(pet_id: int) -> None:
    await _execute(
        "UPDATE rel2_pets SET last_fed_at = CURRENT_TIMESTAMP WHERE id = %s", (pet_id,)
    )


async def set_rel2_pet_action_cooldown(pet_id: int, action_key: str) -> None:
    column = f"last_action_{action_key}"
    await _execute(
        f"UPDATE rel2_pets SET {column} = CURRENT_TIMESTAMP WHERE id = %s", (pet_id,)
    )


async def add_rel2_pet_xp_mood(pet_id: int, xp_delta: int, mood_delta: int, max_level: int) -> dict:
    """Атомарно добавляет опыт/настроение, пересчитывает уровень по формуле
    100 * level^1.5 (см. pet_xp_threshold() в relationships_v2.py), не выше
    максимума редкости. Возвращает обновлённую строку питомца."""
    pet = await get_rel2_pet(pet_id)
    if pet is None:
        return {}
    new_xp = max(0, pet["xp"] + xp_delta)
    new_mood = max(0, min(100, pet["mood"] + mood_delta))
    new_level = pet["level_index"]
    while new_level < max_level:
        threshold = round(100 * ((new_level + 1) ** 1.5))
        if new_xp >= threshold:
            new_level += 1
        else:
            break
    await _execute(
        "UPDATE rel2_pets SET xp = %s, mood = %s, level_index = %s WHERE id = %s",
        (new_xp, new_mood, new_level, pet_id),
    )
    return await get_rel2_pet(pet_id)


async def list_rel2_pets_for_feeding_tick() -> list[dict]:
    """Питомцы, которых пора кормить/обновить настроение — раз в час, кормление
    само по себе идёт раз в 24 часа по last_fed_at (см. pet_upkeep_loop)."""
    return await _fetchall(
        "SELECT pt.*, p.sparks, p.chat_id, p.premium FROM rel2_pets pt "
        "JOIN rel2_pairs p ON p.id = pt.pair_id"
    )


async def get_rel2_pet_home(pet_id: int) -> Optional[dict]:
    import json as _json
    row = await _fetchone(
        "SELECT id, pair_id, pet_id, home_key, rooms_json FROM rel2_pet_homes WHERE pet_id = %s",
        (pet_id,),
    )
    if row is None:
        return None
    row = dict(row)
    row["rooms"] = _json.loads(row.pop("rooms_json") or "[]")
    return row


async def set_rel2_pet_home(pair_id: int, pet_id: int, home_key: str) -> None:
    """Смена домика: старые комнаты теряются (см. гайд — «При смене домика все
    установленные комнаты теряются»)."""
    await _execute("DELETE FROM rel2_pet_homes WHERE pet_id = %s", (pet_id,))
    await _execute(
        "INSERT INTO rel2_pet_homes (pair_id, pet_id, home_key, rooms_json) VALUES (%s, %s, %s, '[]')",
        (pair_id, pet_id, home_key),
    )


async def add_rel2_pet_home_room(pet_id: int, room_key: str) -> bool:
    import json as _json
    home = await get_rel2_pet_home(pet_id)
    if home is None:
        return False
    rooms = home["rooms"]
    if room_key in rooms:
        return False
    rooms.append(room_key)
    await _execute(
        "UPDATE rel2_pet_homes SET rooms_json = %s WHERE pet_id = %s",
        (_json.dumps(rooms, ensure_ascii=False), pet_id),
    )
    return True


# ============================================================================
# 👶 Модуль 5 «Отношения 2.0»: дети (rel2_children / rel2_child_requests) —
# БАЗОВАЯ версия без беременности (см. TODO в relationships_v2.py): ребёнком
# становится реальный пользователь по обоюдному согласию — аналог предложения
# отношений (rel2_requests), только результат — запись в rel2_children, а не
# новая пара. child_user_id хранит, кто именно «играет» ребёнка (нужен для
# упоминаний в профиле/списке). children_count на rel2_pairs (уже существует)
# синхронизируется при создании/удалении.
# ============================================================================
async def ensure_rel2_children_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_children ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "pair_id INT NOT NULL, "
        "child_user_id BIGINT NOT NULL, "
        "name VARCHAR(32) NOT NULL, "
        "level_index INT NOT NULL DEFAULT 1, "
        "xp INT NOT NULL DEFAULT 0, "
        "mood INT NOT NULL DEFAULT 100, "
        "health INT NOT NULL DEFAULT 100, "
        "intellect INT NOT NULL DEFAULT 0, "
        "charisma INT NOT NULL DEFAULT 0, "
        "section_key VARCHAR(32) NULL, "
        "section_started_at DATETIME NULL, "
        "last_action_play DATETIME NULL, "
        "last_action_care DATETIME NULL, "
        "last_action_teach DATETIME NULL, "
        "born_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_children_pair (pair_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # ⚠️ Расширение раздела «Старение, болезни и смерть детей» + полная версия
    # «Системы детей» (возраст/стадии, таланты, врождённые состояния, школа,
    # премиум-фичи карьеры/соревнований/поездок/предметов). Добавляем колонки
    # безопасной миграцией поверх уже существующей таблицы rel2_children.
    await _add_column_if_missing("rel2_children", "vitality", "INT NOT NULL DEFAULT 100")
    await _add_column_if_missing("rel2_children", "talents_json", "TEXT NOT NULL DEFAULT '[]'")
    await _add_column_if_missing("rel2_children", "congenital_key", "VARCHAR(32) NULL")
    await _add_column_if_missing("rel2_children", "school_key", "VARCHAR(32) NULL")
    await _add_column_if_missing("rel2_children", "career_key", "VARCHAR(32) NULL")
    await _add_column_if_missing("rel2_children", "item_keys_json", "TEXT NOT NULL DEFAULT '[]'")
    await _add_column_if_missing("rel2_children", "last_treat_at", "DATETIME NULL")
    await _add_column_if_missing("rel2_children", "last_competition_at", "DATETIME NULL")
    await _add_column_if_missing("rel2_children", "last_trip_at", "DATETIME NULL")
    await _add_column_if_missing("rel2_children", "last_career_payout_at", "DATETIME NULL")
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_child_diseases ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "child_id INT NOT NULL, "
        "disease_key VARCHAR(32) NOT NULL, "
        "acquired_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "managed_at DATETIME NULL, "
        "INDEX idx_rel2_child_diseases_child (child_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_child_hall_of_fame ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "pair_id INT NOT NULL, "
        "name VARCHAR(32) NOT NULL, "
        "age_years DECIMAL(6,2) NOT NULL, "
        "cause VARCHAR(64) NOT NULL, "
        "died_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_child_hof_chat (chat_id), "
        "INDEX idx_rel2_child_hof_age (age_years)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_child_requests ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "from_user_id BIGINT NOT NULL, "
        "to_user_id BIGINT NOT NULL, "
        "child_name VARCHAR(32) NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_rel2_child_req_to (chat_id, to_user_id), "
        "INDEX idx_rel2_child_req_from (chat_id, from_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def create_rel2_child_request(
    chat_id: int, from_user_id: int, to_user_id: int, child_name: str,
    pregnancy_id: Optional[int] = None,
) -> None:
    await _execute(
        "DELETE FROM rel2_child_requests WHERE chat_id = %s AND from_user_id = %s",
        (chat_id, from_user_id),
    )
    await _execute(
        "INSERT INTO rel2_child_requests (chat_id, from_user_id, to_user_id, child_name, pregnancy_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, from_user_id, to_user_id, child_name, pregnancy_id),
    )


async def get_latest_rel2_child_request(chat_id: int, to_user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT from_user_id, to_user_id, child_name, pregnancy_id, created_at FROM rel2_child_requests "
        "WHERE chat_id = %s AND to_user_id = %s ORDER BY created_at DESC LIMIT 1",
        (chat_id, to_user_id),
    )


async def delete_rel2_child_request(chat_id: int, from_user_id: int, to_user_id: int) -> None:
    await _execute(
        "DELETE FROM rel2_child_requests WHERE chat_id = %s AND from_user_id = %s AND to_user_id = %s",
        (chat_id, from_user_id, to_user_id),
    )


async def clear_rel2_child_requests_for(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM rel2_child_requests WHERE chat_id = %s AND (from_user_id = %s OR to_user_id = %s)",
        (chat_id, user_id, user_id),
    )


async def create_rel2_child(pair_id: int, child_user_id: int, name: str) -> int:
    await _execute(
        "INSERT INTO rel2_children (pair_id, child_user_id, name) VALUES (%s, %s, %s)",
        (pair_id, child_user_id, name),
    )
    await _execute(
        "UPDATE rel2_pairs SET children_count = children_count + 1 WHERE id = %s", (pair_id,)
    )
    row = await _fetchone(
        "SELECT id FROM rel2_children WHERE pair_id = %s ORDER BY id DESC LIMIT 1", (pair_id,)
    )
    return row["id"]


async def list_rel2_children(pair_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM rel2_children WHERE pair_id = %s ORDER BY id ASC", (pair_id,)
    )


async def get_rel2_child(child_id: int) -> Optional[dict]:
    return await _fetchone("SELECT * FROM rel2_children WHERE id = %s", (child_id,))


async def count_rel2_children(pair_id: int) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM rel2_children WHERE pair_id = %s", (pair_id,))
    return row["cnt"] if row else 0


# ----------------------------------------------------------------------------
# Счётчики РП-жестов пары (обнимашки/поцелуи/укусы/шлёпы/удары/кексы) — копятся
# по каждому действию, показываются в карточке «отн я». Одна строка на (пара,
# действие); ключи те же, что у SIMPLE_RP_ACTIONS в relationships_v2 (+«kex»).
# ----------------------------------------------------------------------------
async def ensure_rel2_action_counts_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_action_counts ("
        "pair_id INT NOT NULL, "
        "action_key VARCHAR(32) NOT NULL, "
        "cnt INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (pair_id, action_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def increment_rel2_action_count(pair_id: int, action_key: str) -> None:
    await _execute(
        "INSERT INTO rel2_action_counts (pair_id, action_key, cnt) VALUES (%s, %s, 1) "
        "ON DUPLICATE KEY UPDATE cnt = cnt + 1",
        (pair_id, action_key),
    )


async def get_rel2_action_counts(pair_id: int) -> dict:
    rows = await _fetchall(
        "SELECT action_key, cnt FROM rel2_action_counts WHERE pair_id = %s", (pair_id,)
    )
    return {r["action_key"]: int(r["cnt"]) for r in rows}


# ----------------------------------------------------------------------------
# РП-жесты «отн» в БД (жест + фразы + слова-триггеры) — чтобы админы правили их
# из панели. Сид/фолбэк — relationships_v2.default_gestures(). media_folder —
# папка с фото жеста внутри rp_media.
# ----------------------------------------------------------------------------
async def ensure_rel2_gesture_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_gestures ("
        "gesture_key VARCHAR(32) NOT NULL PRIMARY KEY, "
        "name VARCHAR(64) NOT NULL, "
        "reply_template VARCHAR(255) NULL, "
        "media_folder VARCHAR(64) NOT NULL, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "sort_order INT NOT NULL DEFAULT 0"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_gesture_phrases ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "gesture_key VARCHAR(32) NOT NULL, "
        "phrase VARCHAR(512) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0, "
        "INDEX idx_rel2_gp (gesture_key, sort_order)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_gesture_aliases ("
        "alias VARCHAR(64) NOT NULL PRIMARY KEY, "
        "gesture_key VARCHAR(32) NOT NULL, "
        "INDEX idx_rel2_ga (gesture_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def seed_rel2_gestures_if_empty(defaults: dict) -> int:
    """Первичное наполнение из кода — один раз, если таблица пуста. defaults:
    {key: {name, reply, media_folder, aliases:[...], phrases:[...]}}."""
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM rel2_gestures")
    if row and row["cnt"]:
        return 0
    count = 0
    for order, (key, info) in enumerate(defaults.items()):
        await _execute(
            "INSERT INTO rel2_gestures (gesture_key, name, reply_template, media_folder, sort_order) "
            "VALUES (%s, %s, %s, %s, %s)",
            (key, info["name"], info.get("reply"), info.get("media_folder", key), order),
        )
        for i, phrase in enumerate(info.get("phrases", [])):
            await _execute(
                "INSERT INTO rel2_gesture_phrases (gesture_key, phrase, sort_order) VALUES (%s, %s, %s)",
                (key, phrase, i),
            )
        for alias in info.get("aliases", []):
            await _execute(
                "INSERT IGNORE INTO rel2_gesture_aliases (alias, gesture_key) VALUES (%s, %s)",
                (alias, key),
            )
        count += 1
    return count


async def seed_rel2_gestures_missing(defaults: dict) -> int:
    """Идемпотентно доводит набор жестов до дефолтного: добавляет ключи из
    defaults, которых ещё нет в БД (с их фразами и алиасами). В отличие от
    seed_rel2_gestures_if_empty работает и на НЕпустой таблице — нужно, чтобы
    новые дефолтные жесты (напр. минет/куни) появились на уже засеянных БД.
    Существующие жесты не трогает — правки/удаления админов сохраняются."""
    added = 0
    for key, info in defaults.items():
        if await _fetchone("SELECT gesture_key FROM rel2_gestures WHERE gesture_key = %s", (key,)):
            continue
        order_row = await _fetchone("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM rel2_gestures")
        await _execute(
            "INSERT INTO rel2_gestures (gesture_key, name, reply_template, media_folder, sort_order) "
            "VALUES (%s, %s, %s, %s, %s)",
            (key, info["name"], info.get("reply"), info.get("media_folder", key),
             int(order_row["n"]) if order_row else 0),
        )
        for i, phrase in enumerate(info.get("phrases", [])):
            await _execute(
                "INSERT INTO rel2_gesture_phrases (gesture_key, phrase, sort_order) VALUES (%s, %s, %s)",
                (key, phrase, i),
            )
        for alias in info.get("aliases", []):
            await _execute(
                "INSERT IGNORE INTO rel2_gesture_aliases (alias, gesture_key) VALUES (%s, %s)",
                (alias, key),
            )
        added += 1
    return added


async def list_rel2_gestures(active_only: bool = False) -> list[dict]:
    """Жесты с фразами и алиасами, по sort_order. active_only=True — только
    включённые (для бота); False — все (для панели)."""
    where = "WHERE is_active = TRUE" if active_only else ""
    gestures = await _fetchall(
        f"SELECT gesture_key, name, reply_template, media_folder, is_active, sort_order "
        f"FROM rel2_gestures {where} ORDER BY sort_order, gesture_key"
    )
    if not gestures:
        return []
    phrases = await _fetchall(
        "SELECT id, gesture_key, phrase FROM rel2_gesture_phrases ORDER BY gesture_key, sort_order, id"
    )
    aliases = await _fetchall("SELECT alias, gesture_key FROM rel2_gesture_aliases")
    by_key = {}
    for g in gestures:
        g["is_active"] = bool(g["is_active"])
        g["phrases"] = []
        g["aliases"] = []
        by_key[g["gesture_key"]] = g
    for p in phrases:
        if p["gesture_key"] in by_key:
            by_key[p["gesture_key"]]["phrases"].append({"id": p["id"], "phrase": p["phrase"]})
    for a in aliases:
        if a["gesture_key"] in by_key:
            by_key[a["gesture_key"]]["aliases"].append(a["alias"])
    return list(by_key.values())


async def get_rel2_gesture(key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT gesture_key, name, reply_template, media_folder, is_active FROM rel2_gestures "
        "WHERE gesture_key = %s", (key,)
    )


async def add_rel2_gesture(key: str, name: str, reply_template: Optional[str], media_folder: str) -> bool:
    """Добавляет жест. False, если ключ уже занят."""
    if await _fetchone("SELECT gesture_key FROM rel2_gestures WHERE gesture_key = %s", (key,)):
        return False
    order_row = await _fetchone("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM rel2_gestures")
    await _execute(
        "INSERT INTO rel2_gestures (gesture_key, name, reply_template, media_folder, sort_order) "
        "VALUES (%s, %s, %s, %s, %s)",
        (key, name, reply_template, media_folder, int(order_row["n"]) if order_row else 0),
    )
    return True


async def delete_rel2_gesture(key: str) -> bool:
    await _execute("DELETE FROM rel2_gesture_phrases WHERE gesture_key = %s", (key,))
    await _execute("DELETE FROM rel2_gesture_aliases WHERE gesture_key = %s", (key,))
    return bool(await _execute("DELETE FROM rel2_gestures WHERE gesture_key = %s", (key,)))


async def set_rel2_gesture_active(key: str, is_active: bool) -> int:
    return await _execute(
        "UPDATE rel2_gestures SET is_active = %s WHERE gesture_key = %s", (is_active, key)
    )


async def set_rel2_gesture_reply(key: str, reply_template: Optional[str]) -> int:
    return await _execute(
        "UPDATE rel2_gestures SET reply_template = %s WHERE gesture_key = %s", (reply_template, key)
    )


async def add_rel2_gesture_phrase(key: str, phrase: str) -> Optional[int]:
    if not await _fetchone("SELECT gesture_key FROM rel2_gestures WHERE gesture_key = %s", (key,)):
        return None
    order_row = await _fetchone(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM rel2_gesture_phrases WHERE gesture_key = %s",
        (key,),
    )
    return await _execute(
        "INSERT INTO rel2_gesture_phrases (gesture_key, phrase, sort_order) VALUES (%s, %s, %s)",
        (key, phrase, int(order_row["n"]) if order_row else 0),
    )


async def delete_rel2_gesture_phrase(phrase_id: int) -> bool:
    return bool(await _execute("DELETE FROM rel2_gesture_phrases WHERE id = %s", (phrase_id,)))


async def add_rel2_gesture_alias(alias: str, key: str) -> bool:
    if not await _fetchone("SELECT gesture_key FROM rel2_gestures WHERE gesture_key = %s", (key,)):
        return False
    await _execute(
        "INSERT INTO rel2_gesture_aliases (alias, gesture_key) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE gesture_key = VALUES(gesture_key)",
        (alias, key),
    )
    return True


async def delete_rel2_gesture_alias(alias: str) -> bool:
    return bool(await _execute("DELETE FROM rel2_gesture_aliases WHERE alias = %s", (alias,)))


async def rename_rel2_child(child_id: int, name: str) -> None:
    await _execute("UPDATE rel2_children SET name = %s WHERE id = %s", (name, child_id))


async def release_rel2_child(child_id: int, pair_id: int) -> None:
    await _execute("DELETE FROM rel2_child_diseases WHERE child_id = %s", (child_id,))
    await _execute("DELETE FROM rel2_children WHERE id = %s", (child_id,))
    await _execute(
        "UPDATE rel2_pairs SET children_count = GREATEST(children_count - 1, 0) WHERE id = %s",
        (pair_id,),
    )


async def set_rel2_child_action_cooldown(child_id: int, action_key: str) -> None:
    column = f"last_action_{action_key}"
    await _execute(f"UPDATE rel2_children SET {column} = CURRENT_TIMESTAMP WHERE id = %s", (child_id,))


async def add_rel2_child_growth(
    child_id: int, xp_delta: int, mood_delta: int,
    stat_key: Optional[str], stat_delta: int, max_level: int,
) -> dict:
    """Атомарно добавляет опыт/настроение/характеристику ребёнка и пересчитывает
    уровень по формуле child_xp_threshold() из relationships_v2.py."""
    child = await get_rel2_child(child_id)
    if child is None:
        return {}
    new_xp = max(0, child["xp"] + xp_delta)
    new_mood = max(0, min(100, child["mood"] + mood_delta))
    new_level = child["level_index"]
    while new_level < max_level:
        threshold = round(120 * ((new_level + 1) ** 1.4))
        if new_xp >= threshold:
            new_level += 1
        else:
            break
    fields = ["xp = %s", "mood = %s", "level_index = %s"]
    params: list = [new_xp, new_mood, new_level]
    if stat_key in ("intellect", "charisma", "health") and stat_delta:
        fields.append(f"{stat_key} = LEAST(100, {stat_key} + %s)")
        params.append(stat_delta)
    params.append(child_id)
    await _execute(f"UPDATE rel2_children SET {', '.join(fields)} WHERE id = %s", tuple(params))
    return await get_rel2_child(child_id)


async def set_rel2_child_section(child_id: int, section_key: Optional[str]) -> None:
    await _execute(
        "UPDATE rel2_children SET section_key = %s, section_started_at = CURRENT_TIMESTAMP WHERE id = %s",
        (section_key, child_id),
    )


# ============================================================================
# 👴 Старение, болезни и смерть детей + недостающие части «Системы детей»
# (таланты, врождённые состояния, школа, предметы, карьера, Зал славы).
# talents_json / item_keys_json хранятся как JSON-список строк-ключей,
# аналогично skills_json у питомцев (см. _rel2_pet_row выше).
# ============================================================================

def rel2_child_row(row: dict) -> dict:
    """Разворачивает JSON-колонки ребёнка (таланты/предметы) в списки Python.
    Аналог _rel2_pet_row() для питомцев."""
    import json as _json
    d = dict(row)
    d["talents"] = _json.loads(d.pop("talents_json", None) or "[]")
    d["item_keys"] = _json.loads(d.pop("item_keys_json", None) or "[]")
    return d


async def set_rel2_child_vitality(child_id: int, vitality: int) -> None:
    vitality = max(0, min(100, vitality))
    await _execute("UPDATE rel2_children SET vitality = %s WHERE id = %s", (vitality, child_id))


async def adjust_rel2_child_vitality(child_id: int, delta: int) -> int:
    await _execute(
        "UPDATE rel2_children SET vitality = GREATEST(0, LEAST(100, vitality + %s)) WHERE id = %s",
        (delta, child_id),
    )
    row = await _fetchone("SELECT vitality FROM rel2_children WHERE id = %s", (child_id,))
    return int(row["vitality"]) if row else 0


async def set_rel2_child_talents(child_id: int, talent_keys: list[str]) -> None:
    import json as _json
    await _execute(
        "UPDATE rel2_children SET talents_json = %s WHERE id = %s",
        (_json.dumps(talent_keys, ensure_ascii=False), child_id),
    )


async def set_rel2_child_congenital(child_id: int, congenital_key: Optional[str]) -> None:
    await _execute("UPDATE rel2_children SET congenital_key = %s WHERE id = %s", (congenital_key, child_id))


async def set_rel2_child_school(child_id: int, school_key: Optional[str]) -> None:
    await _execute("UPDATE rel2_children SET school_key = %s WHERE id = %s", (school_key, child_id))


async def set_rel2_child_career(child_id: int, career_key: Optional[str]) -> None:
    await _execute("UPDATE rel2_children SET career_key = %s WHERE id = %s", (career_key, child_id))


async def add_rel2_child_item(child_id: int, item_key: str) -> None:
    import json as _json
    row = await _fetchone("SELECT item_keys_json FROM rel2_children WHERE id = %s", (child_id,))
    items = _json.loads((row["item_keys_json"] if row else None) or "[]")
    if item_key not in items:
        items.append(item_key)
    await _execute(
        "UPDATE rel2_children SET item_keys_json = %s WHERE id = %s",
        (_json.dumps(items, ensure_ascii=False), child_id),
    )


async def set_rel2_child_treat_cooldown(child_id: int) -> None:
    await _execute("UPDATE rel2_children SET last_treat_at = CURRENT_TIMESTAMP WHERE id = %s", (child_id,))


async def set_rel2_child_competition_cooldown(child_id: int) -> None:
    await _execute("UPDATE rel2_children SET last_competition_at = CURRENT_TIMESTAMP WHERE id = %s", (child_id,))


async def set_rel2_child_trip_cooldown(child_id: int) -> None:
    await _execute("UPDATE rel2_children SET last_trip_at = CURRENT_TIMESTAMP WHERE id = %s", (child_id,))


async def set_rel2_child_career_payout(child_id: int) -> None:
    await _execute("UPDATE rel2_children SET last_career_payout_at = CURRENT_TIMESTAMP WHERE id = %s", (child_id,))


async def add_child_disease(child_id: int, disease_key: str) -> None:
    await _execute(
        "INSERT INTO rel2_child_diseases (child_id, disease_key) VALUES (%s, %s)",
        (child_id, disease_key),
    )


async def list_child_diseases(child_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT id, disease_key, acquired_at, managed_at FROM rel2_child_diseases "
        "WHERE child_id = %s ORDER BY acquired_at ASC",
        (child_id,),
    )


async def count_child_diseases(child_id: int) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM rel2_child_diseases WHERE child_id = %s", (child_id,))
    return row["cnt"] if row else 0


async def remove_child_disease(disease_row_id: int) -> None:
    await _execute("DELETE FROM rel2_child_diseases WHERE id = %s", (disease_row_id,))


async def mark_child_disease_managed(disease_row_id: int) -> None:
    await _execute(
        "UPDATE rel2_child_diseases SET managed_at = CURRENT_TIMESTAMP WHERE id = %s", (disease_row_id,)
    )


async def clear_child_diseases(child_id: int) -> None:
    await _execute("DELETE FROM rel2_child_diseases WHERE child_id = %s", (child_id,))


async def list_rel2_children_for_aging_tick() -> list[dict]:
    """Все дети + premium/chat_id их пары — для фонового тика старения/болезней
    (см. child_aging_loop() в relationships_v2.py)."""
    return await _fetchall(
        "SELECT c.*, p.premium AS pair_premium, p.chat_id AS chat_id, p.id AS pair_id2 "
        "FROM rel2_children c JOIN rel2_pairs p ON p.id = c.pair_id"
    )


async def add_hall_of_fame_entry(chat_id: int, pair_id: int, name: str, age_years: float, cause: str) -> None:
    await _execute(
        "INSERT INTO rel2_child_hall_of_fame (chat_id, pair_id, name, age_years, cause) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, pair_id, name, round(age_years, 2), cause),
    )


async def list_hall_of_fame(chat_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    """Зал славы — рекорды по возрасту на момент смерти. chat_id=None → глобально."""
    if chat_id is None:
        return await _fetchall(
            "SELECT name, age_years, cause, died_at FROM rel2_child_hall_of_fame "
            "ORDER BY age_years DESC LIMIT %s",
            (limit,),
        )
    return await _fetchall(
        "SELECT name, age_years, cause, died_at FROM rel2_child_hall_of_fame "
        "WHERE chat_id = %s ORDER BY age_years DESC LIMIT %s",
        (chat_id, limit),
    )


async def list_living_oldest(chat_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    """Ныне живущие старейшие дети (самые ранние born_at). chat_id=None → глобально."""
    if chat_id is None:
        return await _fetchall(
            "SELECT c.name, c.born_at FROM rel2_children c ORDER BY c.born_at ASC LIMIT %s",
            (limit,),
        )
    return await _fetchall(
        "SELECT c.name, c.born_at FROM rel2_children c JOIN rel2_pairs p ON p.id = c.pair_id "
        "WHERE p.chat_id = %s ORDER BY c.born_at ASC LIMIT %s",
        (chat_id, limit),
    )


# ============================================================================
# ⏱ Generic-кулдауны для мелких расширений «Отношения 2.0», которым не нужна
# отдельная таблица ради одной колонки: дуэли питомцев (scope="pet_duel",
# ref_id=pet_id) и семейные события детей (scope="family_event", ref_id=pair_id).
# ============================================================================
async def ensure_rel2_cooldown_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS rel2_cooldowns ("
        "scope VARCHAR(32) NOT NULL, "
        "ref_id INT NOT NULL, "
        "cooldown_key VARCHAR(32) NOT NULL, "
        "last_at DATETIME NOT NULL, "
        "PRIMARY KEY (scope, ref_id, cooldown_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_rel2_cooldown(scope: str, ref_id: int, cooldown_key: str) -> Optional[datetime]:
    row = await _fetchone(
        "SELECT last_at FROM rel2_cooldowns WHERE scope = %s AND ref_id = %s AND cooldown_key = %s",
        (scope, ref_id, cooldown_key),
    )
    return row["last_at"] if row else None


async def set_rel2_cooldown(scope: str, ref_id: int, cooldown_key: str) -> None:
    await _execute(
        "INSERT INTO rel2_cooldowns (scope, ref_id, cooldown_key, last_at) "
        "VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
        "ON DUPLICATE KEY UPDATE last_at = CURRENT_TIMESTAMP",
        (scope, ref_id, cooldown_key),
    )


# ============================================================================
# 🏅 Хелпер для рейтинга домов чата («дом топ» — расширение модуля 3). Престиж
# считается в relationships_v2.py (house_prestige()), т.к. зависит от
# ROOM_CATALOG/UPGRADE_CATALOG, которых в db.py нет — здесь только выборка.
# ============================================================================
async def list_rel2_houses_in_chat(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT h.id, h.pair_id, h.house_key, p.user1_id, p.user2_id, p.premium "
        "FROM rel2_houses h JOIN rel2_pairs p ON p.id = h.pair_id "
        "WHERE h.status = 'active' AND p.chat_id = %s",
        (chat_id,),
    )


# ----------------------------------------------------------------------------
# Пул эмодзи по умолчанию для позывных в созывах (CALL_EMOJI_POOL в bot.py) —
# простой редактируемый список, каждому новому участнику назначается один
# эмодзи из пула детерминированно (см. get_or_assign_call_emoji выше).
# ----------------------------------------------------------------------------
async def ensure_call_emoji_pool_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS call_emoji_pool ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "emoji VARCHAR(191) NOT NULL, "
        "sort_order INT NOT NULL DEFAULT 0"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def seed_call_emoji_pool_if_empty(defaults: list[str]) -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM call_emoji_pool")
    if row and row["cnt"]:
        return 0
    for i, emoji in enumerate(defaults):
        await _execute(
            "INSERT INTO call_emoji_pool (emoji, sort_order) VALUES (%s, %s)", (emoji, i)
        )
    return len(defaults)


async def list_call_emoji_pool() -> list[str]:
    """[эмодзи, ...] по sort_order — формат для CALL_EMOJI_POOL в bot.py."""
    rows = await _fetchall("SELECT emoji FROM call_emoji_pool ORDER BY sort_order, id")
    return [r["emoji"] for r in rows]


async def list_call_emoji_pool_rows() -> list[dict]:
    return await _fetchall("SELECT id, emoji, sort_order FROM call_emoji_pool ORDER BY sort_order, id")


async def add_call_emoji(emoji: str, sort_order: Optional[int] = None) -> int:
    if sort_order is None:
        row = await _fetchone("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM call_emoji_pool")
        sort_order = row["next_order"] if row else 0
    return await _execute(
        "INSERT INTO call_emoji_pool (emoji, sort_order) VALUES (%s, %s)", (emoji, sort_order)
    )


async def delete_call_emoji(emoji_id: int) -> bool:
    rowcount = await _execute("DELETE FROM call_emoji_pool WHERE id = %s", (emoji_id,))
    return rowcount > 0


# ----------------------------------------------------------------------------
# Модуль «Дуэли» (по образцу Iris) — пошаговый бой двух участников: вызов,
# принятие/отклонение/отмена, затем обмен «выстрелами» до первого попадания.
# У каждого пользователя в чате может быть не более одной незавершённой
# (pending/active) дуэли одновременно — см. get_user_active_duel, им же
# ищутся дуэли для «дуэль да/нет/отмена/выстрел/прицелиться».
# ----------------------------------------------------------------------------
async def ensure_duels_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS duels ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "challenger_id BIGINT NOT NULL, "
        "target_id BIGINT NOT NULL, "
        "status ENUM('pending','active') NOT NULL DEFAULT 'pending', "
        "turn_user_id BIGINT NULL, "
        "challenger_aim INT NOT NULL DEFAULT 0, "
        "target_aim INT NOT NULL DEFAULT 0, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_duels_challenger (chat_id, challenger_id), "
        "INDEX idx_duels_target (chat_id, target_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_duel_stats_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS duel_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "wins INT NOT NULL DEFAULT 0, "
        "draws INT NOT NULL DEFAULT 0, "
        "losses INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_duel_outcome_column() -> None:
    """duel_outcome — глобальная настройка исхода проигрыша (см. settings, id=1),
    как warn_limit/role_reserve_timeout_hours выше — не таблица, а колонка
    в settings, потому что бот управляет одним сообществом."""
    await _add_column_if_missing("settings", "duel_outcome", "VARCHAR(32) NOT NULL DEFAULT 'kick'")


async def get_user_active_duel(chat_id: int, user_id: int) -> Optional[dict]:
    """Последняя незавершённая (pending/active) дуэль с участием пользователя
    в этом чате — используется для разрешения «дуэль да/нет/отмена/выстрел/
    прицелиться/сбросить прицел» без указания id дуэли вручную."""
    return await _fetchone(
        "SELECT * FROM duels WHERE chat_id = %s AND (challenger_id = %s OR target_id = %s) "
        "ORDER BY id DESC LIMIT 1",
        (chat_id, user_id, user_id),
    )

async def get_duel_wins(chat_id: int, user_id: int) -> int:
    row = await _fetchone(
        "SELECT wins FROM duel_stats WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    return int(row["wins"]) if row else 0

async def create_duel(chat_id: int, challenger_id: int, target_id: int) -> int:
    return await _execute(
        "INSERT INTO duels (chat_id, challenger_id, target_id, status) VALUES (%s, %s, %s, 'pending')",
        (chat_id, challenger_id, target_id),
    )


async def activate_duel(duel_id: int, first_turn_user_id: int) -> None:
    await _execute(
        "UPDATE duels SET status = 'active', turn_user_id = %s WHERE id = %s",
        (first_turn_user_id, duel_id),
    )


async def delete_duel(duel_id: int) -> None:
    await _execute("DELETE FROM duels WHERE id = %s", (duel_id,))


async def set_duel_turn(duel_id: int, user_id: int) -> None:
    await _execute("UPDATE duels SET turn_user_id = %s WHERE id = %s", (user_id, duel_id))


async def set_duel_aim(duel_id: int, challenger_aim: int, target_aim: int) -> None:
    await _execute(
        "UPDATE duels SET challenger_aim = %s, target_aim = %s WHERE id = %s",
        (challenger_aim, target_aim, duel_id),
    )


async def record_duel_result(chat_id: int, winner_id: int, loser_id: int) -> None:
    await _execute(
        "INSERT INTO duel_stats (chat_id, user_id, wins) VALUES (%s, %s, 1) "
        "ON DUPLICATE KEY UPDATE wins = wins + 1",
        (chat_id, winner_id),
    )
    await _execute(
        "INSERT INTO duel_stats (chat_id, user_id, losses) VALUES (%s, %s, 1) "
        "ON DUPLICATE KEY UPDATE losses = losses + 1",
        (chat_id, loser_id),
    )


async def list_duel_stats(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, wins, draws, losses FROM duel_stats WHERE chat_id = %s "
        "ORDER BY wins DESC, losses ASC LIMIT %s",
        (chat_id, limit),
    )


async def reset_duel_stats(chat_id: int) -> int:
    return await _execute("DELETE FROM duel_stats WHERE chat_id = %s", (chat_id,))


async def seed_roles(chat_id: int, entries: list[dict]) -> int:
    """Массовая первичная загрузка ролей (импорт готового списка названий).
    entries: [{"name":..., "category": Optional[str], "status": "free"/"taken"/"reserved"}].
    Держатель/бронь при импорте неизвестны (в исходном списке есть только
    статус, не Telegram id) — они остаются NULL, их нужно проставить вручную
    через «роль отдать» (см. force_set_role). Роли с уже существующим именем
    в этом чате пропускаются (INSERT IGNORE + UNIQUE(chat_id, name)).
    Возвращает число реально добавленных строк."""
    count = 0
    for e in entries:
        rowcount = await _execute(
            "INSERT IGNORE INTO chat_roles (chat_id, name, category, status, approved) "
            "VALUES (%s, %s, %s, %s, TRUE)",
            (chat_id, e["name"].strip()[:64], e.get("category"), e["status"]),
        )
        if rowcount:
            count += 1
    return count


# ----------------------------------------------------------------------------
# Модуль «Кружки» (по образцу Iris) — аналог «Кланов», но без ограничения
# «один кружок на человека»: пользователь может состоять сразу в нескольких
# кружках чата и создавать несколько своих. «Номер» кружка в командах
# («кружок {номер} ...») — это его id из таблицы clubs (как id роли в
# «роль удалить {id}» — см. seed_roles выше).
# ----------------------------------------------------------------------------
async def ensure_clubs_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS clubs ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "description TEXT NULL, "
        "owner_id BIGINT NOT NULL, "
        "coins INT NOT NULL DEFAULT 0, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_clubs_chat (chat_id), "
        "INDEX idx_clubs_chat_coins (chat_id, coins)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_club_members_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS club_members ("
        "chat_id BIGINT NOT NULL, "
        "club_id INT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "is_home BOOLEAN NOT NULL DEFAULT FALSE, "
        "joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (club_id, user_id), "
        "INDEX idx_club_members_user (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def create_club(chat_id: int, owner_id: int, name: str, description: Optional[str]) -> int:
    """Создаёт кружок и сразу вступает в него создателя (как у Iris — создатель
    клана/кружка автоматически становится его первым участником)."""
    club_id = await _execute(
        "INSERT INTO clubs (chat_id, name, description, owner_id) VALUES (%s, %s, %s, %s)",
        (chat_id, name, description, owner_id),
    )
    await _execute(
        "INSERT IGNORE INTO club_members (chat_id, club_id, user_id) VALUES (%s, %s, %s)",
        (chat_id, club_id, owner_id),
    )
    return club_id


async def get_club(chat_id: int, club_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM clubs WHERE chat_id = %s AND id = %s", (chat_id, club_id)
    )


async def update_club(
    chat_id: int, club_id: int, name: Optional[str] = None, description: Optional[str] = None
) -> bool:
    fields, args = [], []
    if name is not None:
        fields.append("name = %s")
        args.append(name)
    if description is not None:
        fields.append("description = %s")
        args.append(description)
    if not fields:
        return False
    args.extend([chat_id, club_id])
    rowcount = await _execute(
        f"UPDATE clubs SET {', '.join(fields)} WHERE chat_id = %s AND id = %s", tuple(args)
    )
    return rowcount > 0


async def delete_club(chat_id: int, club_id: int) -> bool:
    rowcount = await _execute("DELETE FROM clubs WHERE chat_id = %s AND id = %s", (chat_id, club_id))
    if rowcount:
        await _execute("DELETE FROM club_members WHERE chat_id = %s AND club_id = %s", (chat_id, club_id))
    return rowcount > 0


async def count_club_members(chat_id: int, club_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM club_members WHERE chat_id = %s AND club_id = %s",
        (chat_id, club_id),
    )
    return row["cnt"] if row else 0


async def list_clubs(chat_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    """Список кружков чата, отсортированный по репутации (coins) — чем больше
    коинов вложено, тем выше кружок в списке (см. «Кружок {номер} коины»)."""
    rows = await _fetchall(
        "SELECT c.*, (SELECT COUNT(*) FROM club_members m WHERE m.club_id = c.id) AS members_count "
        "FROM clubs c WHERE c.chat_id = %s ORDER BY c.coins DESC, c.id LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    total_row = await _fetchone("SELECT COUNT(*) AS cnt FROM clubs WHERE chat_id = %s", (chat_id,))
    return rows, (total_row["cnt"] if total_row else 0)


async def list_user_clubs(chat_id: int, user_id: int) -> list[dict]:
    """Кружки, в которых состоит пользователь, с пометкой is_home (основной,
    отмечается «*» — см. «Кружок основа {номер}»)."""
    return await _fetchall(
        "SELECT c.*, m.is_home FROM club_members m JOIN clubs c ON c.id = m.club_id "
        "WHERE m.chat_id = %s AND m.user_id = %s ORDER BY m.is_home DESC, c.name",
        (chat_id, user_id),
    )


async def is_club_member(chat_id: int, club_id: int, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM club_members WHERE chat_id = %s AND club_id = %s AND user_id = %s",
        (chat_id, club_id, user_id),
    )
    return row is not None


async def join_club(chat_id: int, club_id: int, user_id: int) -> bool:
    """True — вступление прошло, False — пользователь уже был в этом кружке."""
    rowcount = await _execute(
        "INSERT IGNORE INTO club_members (chat_id, club_id, user_id) VALUES (%s, %s, %s)",
        (chat_id, club_id, user_id),
    )
    return rowcount > 0


async def leave_club(chat_id: int, club_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM club_members WHERE chat_id = %s AND club_id = %s AND user_id = %s",
        (chat_id, club_id, user_id),
    )
    return rowcount > 0


async def set_home_club(chat_id: int, user_id: int, club_id: int) -> bool:
    """Снимает пометку «основной» со всех кружков пользователя и ставит её
    указанному — вызывающий код обязан заранее убедиться, что пользователь
    состоит в этом кружке (is_club_member)."""
    await _execute(
        "UPDATE club_members SET is_home = FALSE WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    rowcount = await _execute(
        "UPDATE club_members SET is_home = TRUE WHERE chat_id = %s AND club_id = %s AND user_id = %s",
        (chat_id, club_id, user_id),
    )
    return rowcount > 0


async def list_club_members(chat_id: int, club_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    rows = await _fetchall(
        "SELECT user_id, is_home, joined_at FROM club_members "
        "WHERE chat_id = %s AND club_id = %s ORDER BY joined_at LIMIT %s OFFSET %s",
        (chat_id, club_id, limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM club_members WHERE chat_id = %s AND club_id = %s",
        (chat_id, club_id),
    )
    return rows, (total_row["cnt"] if total_row else 0)


async def add_club_coins(chat_id: int, club_id: int, amount: int) -> Optional[int]:
    """Прибавляет (или отнимает, если amount < 0) репутацию кружка, не давая
    ей уйти в минус. Возвращает новое значение coins либо None, если кружка
    с таким id в этом чате не существует."""
    club = await get_club(chat_id, club_id)
    if club is None:
        return None
    new_coins = max(0, club["coins"] + amount)
    await _execute(
        "UPDATE clubs SET coins = %s WHERE chat_id = %s AND id = %s", (new_coins, chat_id, club_id)
    )
    return new_coins


# ----------------------------------------------------------------------------
# Модуль «Кланы» (по образцу Iris, раздел 17) — в отличие от «Кружков»,
# у клана есть иерархия (лидер / замы / участники), казна (coins), звание
# и девиз, а также войны между кланами на очки с общим топом. Состоять можно
# только в одном клане одновременно — это обеспечено самим PRIMARY KEY
# таблицы clan_members (chat_id, user_id), при вступлении в новый клан старая
# запись просто перезаписывается (см. join_clan). Создать клан может любой
# участник — создатель автоматически становится лидером.
# ----------------------------------------------------------------------------
async def ensure_clans_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS clans ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "description TEXT NULL, "
        "title VARCHAR(100) NULL, "
        "motto VARCHAR(100) NULL, "
        "leader_id BIGINT NOT NULL, "
        "coins INT NOT NULL DEFAULT 0, "
        "war_points INT NOT NULL DEFAULT 0, "
        "wars_won INT NOT NULL DEFAULT 0, "
        "wars_drawn INT NOT NULL DEFAULT 0, "
        "wars_lost INT NOT NULL DEFAULT 0, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_clans_chat (chat_id), "
        "INDEX idx_clans_chat_points (chat_id, war_points)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_clan_members_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS clan_members ("
        "chat_id BIGINT NOT NULL, "
        "clan_id INT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "role ENUM('leader','deputy','member') NOT NULL DEFAULT 'member', "
        "joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id), "
        "INDEX idx_clan_members_clan (clan_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_clan_wars_table() -> None:
    """Незавершённые (ожидающие принятия) вызовы на войну между кланами —
    по одной активной паре challenger/target одновременно, аналог таблицы
    duels у обычных дуэлей."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS clan_wars ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "challenger_clan_id INT NOT NULL, "
        "target_clan_id INT NOT NULL, "
        "initiator_id BIGINT NOT NULL, "
        "status ENUM('pending') NOT NULL DEFAULT 'pending', "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_clan_wars_challenger (chat_id, challenger_clan_id), "
        "INDEX idx_clan_wars_target (chat_id, target_clan_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def create_clan(chat_id: int, leader_id: int, name: str, description: Optional[str]) -> int:
    """Создаёт клан и сразу делает создателя лидером (роль 'leader')."""
    clan_id = await _execute(
        "INSERT INTO clans (chat_id, name, description, leader_id) VALUES (%s, %s, %s, %s)",
        (chat_id, name, description, leader_id),
    )
    await _execute(
        "INSERT INTO clan_members (chat_id, clan_id, user_id, role) VALUES (%s, %s, %s, 'leader') "
        "ON DUPLICATE KEY UPDATE clan_id = VALUES(clan_id), role = 'leader'",
        (chat_id, clan_id, leader_id),
    )
    return clan_id


async def get_clan(chat_id: int, clan_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM clans WHERE chat_id = %s AND id = %s", (chat_id, clan_id)
    )


async def update_clan(
    chat_id: int, clan_id: int, name: Optional[str] = None, description: Optional[str] = None
) -> bool:
    fields, args = [], []
    if name is not None:
        fields.append("name = %s")
        args.append(name)
    if description is not None:
        fields.append("description = %s")
        args.append(description)
    if not fields:
        return False
    args.extend([chat_id, clan_id])
    rowcount = await _execute(
        f"UPDATE clans SET {', '.join(fields)} WHERE chat_id = %s AND id = %s", tuple(args)
    )
    return rowcount > 0


async def set_clan_title(chat_id: int, clan_id: int, title: Optional[str]) -> bool:
    """Звание клана — title=None снимает звание (см. «-клан звание»)."""
    rowcount = await _execute(
        "UPDATE clans SET title = %s WHERE chat_id = %s AND id = %s", (title, chat_id, clan_id)
    )
    return rowcount > 0


async def set_clan_motto(chat_id: int, clan_id: int, motto: Optional[str]) -> bool:
    """Девиз клана — motto=None снимает девиз (см. «-клан девиз»)."""
    rowcount = await _execute(
        "UPDATE clans SET motto = %s WHERE chat_id = %s AND id = %s", (motto, chat_id, clan_id)
    )
    return rowcount > 0


async def delete_clan(chat_id: int, clan_id: int) -> bool:
    rowcount = await _execute("DELETE FROM clans WHERE chat_id = %s AND id = %s", (chat_id, clan_id))
    if rowcount:
        await _execute("DELETE FROM clan_members WHERE chat_id = %s AND clan_id = %s", (chat_id, clan_id))
        await _execute(
            "DELETE FROM clan_wars WHERE chat_id = %s AND (challenger_clan_id = %s OR target_clan_id = %s)",
            (chat_id, clan_id, clan_id),
        )
    return rowcount > 0


async def count_clan_members(chat_id: int, clan_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM clan_members WHERE chat_id = %s AND clan_id = %s",
        (chat_id, clan_id),
    )
    return row["cnt"] if row else 0


async def list_clans(chat_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    """Список кланов чата, отсортированный по очкам войн (см. «клан война»),
    затем по казне — чем больше очков и коинов, тем выше клан в списке."""
    rows = await _fetchall(
        "SELECT c.*, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id = c.id) AS members_count "
        "FROM clans c WHERE c.chat_id = %s "
        "ORDER BY c.war_points DESC, c.coins DESC, c.id LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    total_row = await _fetchone("SELECT COUNT(*) AS cnt FROM clans WHERE chat_id = %s", (chat_id,))
    return rows, (total_row["cnt"] if total_row else 0)


async def list_clan_war_top(chat_id: int, limit: int) -> list[dict]:
    """Топ кланов чата по войнам: очки, затем побед больше — выше в топе
    (см. «топ кланов»)."""
    return await _fetchall(
        "SELECT * FROM clans WHERE chat_id = %s "
        "ORDER BY war_points DESC, wars_won DESC, wars_lost ASC LIMIT %s",
        (chat_id, limit),
    )


async def get_user_clan(chat_id: int, user_id: int) -> Optional[dict]:
    """Клан, в котором состоит пользователь (с ролью), либо None — вступление
    и создание кланов гарантируют не более одной строки на пользователя."""
    return await _fetchone(
        "SELECT c.*, m.role FROM clan_members m JOIN clans c ON c.id = m.clan_id "
        "WHERE m.chat_id = %s AND m.user_id = %s",
        (chat_id, user_id),
    )


async def join_clan(chat_id: int, clan_id: int, user_id: int) -> Optional[int]:
    """Вступление в клан рядовым участником. Поскольку в клане можно состоять
    только в одном (PRIMARY KEY chat_id+user_id), запись просто перезаписывает
    предыдущую. Возвращает id клана, который пользователь покинул при этом
    (None, если он никуда раньше не вступал, или если это тот же самый клан)."""
    previous = await get_user_clan(chat_id, user_id)
    previous_id = previous["id"] if previous else None
    if previous_id == clan_id:
        return None
    await _execute(
        "INSERT INTO clan_members (chat_id, clan_id, user_id, role) VALUES (%s, %s, %s, 'member') "
        "ON DUPLICATE KEY UPDATE clan_id = VALUES(clan_id), role = 'member'",
        (chat_id, clan_id, user_id),
    )
    return previous_id


async def leave_clan(chat_id: int, user_id: int) -> bool:
    """Выход из клана — вызывающий код обязан заранее убедиться, что
    пользователь не является лидером (лидер обязан сначала передать клан или
    удалить его, см. «передать клан» / «удалить клан»)."""
    rowcount = await _execute(
        "DELETE FROM clan_members WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    return rowcount > 0


async def kick_clan_member(chat_id: int, clan_id: int, user_id: int) -> bool:
    """Исключение участника из клана (не лидера — проверяется вызывающим
    кодом до вызова, см. «кик из клана»)."""
    rowcount = await _execute(
        "DELETE FROM clan_members WHERE chat_id = %s AND clan_id = %s AND user_id = %s",
        (chat_id, clan_id, user_id),
    )
    return rowcount > 0


async def set_clan_member_role(chat_id: int, clan_id: int, user_id: int, role: str) -> bool:
    """Назначение/снятие зама (role: 'deputy' или 'member') — пользователь
    должен уже состоять в этом клане (иначе rowcount будет 0)."""
    rowcount = await _execute(
        "UPDATE clan_members SET role = %s WHERE chat_id = %s AND clan_id = %s AND user_id = %s",
        (role, chat_id, clan_id, user_id),
    )
    return rowcount > 0


async def transfer_clan_leadership(chat_id: int, clan_id: int, new_leader_id: int) -> bool:
    """Передача лидерства: новый лидер должен уже состоять в клане. Старый
    лидер становится замом, чтобы не потерять статус вовсе."""
    clan = await get_clan(chat_id, clan_id)
    if clan is None:
        return False
    old_leader_id = clan["leader_id"]
    await _execute(
        "UPDATE clans SET leader_id = %s WHERE chat_id = %s AND id = %s", (new_leader_id, chat_id, clan_id)
    )
    await _execute(
        "UPDATE clan_members SET role = 'leader' WHERE chat_id = %s AND clan_id = %s AND user_id = %s",
        (chat_id, clan_id, new_leader_id),
    )
    if old_leader_id != new_leader_id:
        await _execute(
            "UPDATE clan_members SET role = 'deputy' WHERE chat_id = %s AND clan_id = %s AND user_id = %s",
            (chat_id, clan_id, old_leader_id),
        )
    return True


async def list_clan_members(chat_id: int, clan_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    """Список участников клана: лидер первым, затем замы, затем рядовые
    (внутри группы — по дате вступления)."""
    rows = await _fetchall(
        "SELECT user_id, role, joined_at FROM clan_members "
        "WHERE chat_id = %s AND clan_id = %s "
        "ORDER BY FIELD(role, 'leader', 'deputy', 'member'), joined_at LIMIT %s OFFSET %s",
        (chat_id, clan_id, limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM clan_members WHERE chat_id = %s AND clan_id = %s",
        (chat_id, clan_id),
    )
    return rows, (total_row["cnt"] if total_row else 0)


async def add_clan_coins(chat_id: int, clan_id: int, amount: int) -> Optional[int]:
    """Пополняет (или списывает, если amount < 0) казну клана, не давая ей
    уйти в минус. Возвращает новое значение coins либо None, если клана
    с таким id в этом чате не существует."""
    clan = await get_clan(chat_id, clan_id)
    if clan is None:
        return None
    new_coins = max(0, clan["coins"] + amount)
    await _execute(
        "UPDATE clans SET coins = %s WHERE chat_id = %s AND id = %s", (new_coins, chat_id, clan_id)
    )
    return new_coins


async def get_pending_clan_war_for(chat_id: int, clan_id: int) -> Optional[dict]:
    """Последний незавершённый вызов на войну с участием клана (как
    инициатора, так и цели) — используется для разрешения «война да/нет/
    отмена» без явного указания номера клана."""
    return await _fetchone(
        "SELECT * FROM clan_wars WHERE chat_id = %s AND "
        "(challenger_clan_id = %s OR target_clan_id = %s) ORDER BY id DESC LIMIT 1",
        (chat_id, clan_id, clan_id),
    )


async def create_clan_war(chat_id: int, challenger_clan_id: int, target_clan_id: int, initiator_id: int) -> int:
    return await _execute(
        "INSERT INTO clan_wars (chat_id, challenger_clan_id, target_clan_id, initiator_id) "
        "VALUES (%s, %s, %s, %s)",
        (chat_id, challenger_clan_id, target_clan_id, initiator_id),
    )


async def get_clan_war(war_id: int) -> Optional[dict]:
    return await _fetchone("SELECT * FROM clan_wars WHERE id = %s", (war_id,))


async def delete_clan_war(war_id: int) -> None:
    await _execute("DELETE FROM clan_wars WHERE id = %s", (war_id,))


async def record_clan_war_result(
    chat_id: int, winner_clan_id: Optional[int], loser_clan_id: Optional[int], points: int = 3
) -> None:
    """Записывает результат войны в очки/статистику обоих кланов. При ничьей
    (winner_clan_id и loser_clan_id оба None — не используется сейчас, но
    оставлено для симметрии с дуэлями) очки не начисляются никому."""
    if winner_clan_id is not None:
        await _execute(
            "UPDATE clans SET war_points = war_points + %s, wars_won = wars_won + 1 "
            "WHERE chat_id = %s AND id = %s",
            (points, chat_id, winner_clan_id),
        )
    if loser_clan_id is not None:
        await _execute(
            "UPDATE clans SET wars_lost = wars_lost + 1 WHERE chat_id = %s AND id = %s",
            (chat_id, loser_clan_id),
        )


# ----------------------------------------------------------------------------
# Модуль «Закладки» (по образцу Iris, раздел 23) — разметка длинных диалогов
# по темам: закладка хранит название, необязательный текст и (если создана
# ответом на сообщение) «якорь» — chat_id/message_id сообщения, к которому
# можно перейти по ссылке. Закладки всех пользователей чата образуют
# «чатбук» — общий список (excluded=TRUE прячет закладку из чатбука, но не
# удаляет её из личного списка автора, см. «исключить закладку»/«+кладмен»).
# ----------------------------------------------------------------------------
async def ensure_bookmarks_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS bookmarks ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "author_id BIGINT NOT NULL, "
        "title VARCHAR(40) NOT NULL, "
        "description TEXT NULL, "
        "anchor_chat_id BIGINT NULL, "
        "anchor_message_id BIGINT NULL, "
        "excluded BOOLEAN NOT NULL DEFAULT FALSE, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_bookmarks_chat (chat_id, excluded), "
        "INDEX idx_bookmarks_author (chat_id, author_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def create_bookmark(
    chat_id: int,
    author_id: int,
    title: str,
    description: Optional[str],
    anchor_chat_id: Optional[int] = None,
    anchor_message_id: Optional[int] = None,
) -> int:
    return await _execute(
        "INSERT INTO bookmarks (chat_id, author_id, title, description, anchor_chat_id, anchor_message_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (chat_id, author_id, title, description, anchor_chat_id, anchor_message_id),
    )


async def get_bookmark(chat_id: int, bookmark_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM bookmarks WHERE chat_id = %s AND id = %s", (chat_id, bookmark_id)
    )


async def delete_bookmark(chat_id: int, bookmark_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM bookmarks WHERE chat_id = %s AND id = %s", (chat_id, bookmark_id)
    )
    return rowcount > 0


async def set_bookmark_excluded(chat_id: int, bookmark_id: int, excluded: bool) -> bool:
    rowcount = await _execute(
        "UPDATE bookmarks SET excluded = %s WHERE chat_id = %s AND id = %s",
        (excluded, chat_id, bookmark_id),
    )
    return rowcount > 0


async def list_chatbook(chat_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    """Общий «чатбук» — закладки всех авторов чата, кроме исключённых
    (excluded=TRUE, см. «исключить закладку» / «-кладмен»)."""
    rows = await _fetchall(
        "SELECT * FROM bookmarks WHERE chat_id = %s AND excluded = FALSE "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM bookmarks WHERE chat_id = %s AND excluded = FALSE", (chat_id,)
    )
    return rows, (total_row["cnt"] if total_row else 0)


async def list_user_bookmarks(chat_id: int, author_id: int, limit: int, offset: int) -> tuple[list[dict], int]:
    """Полный список закладок автора (в т.ч. исключённых из чатбука —
    исключение прячет закладку только из общего списка, не из личного)."""
    rows = await _fetchall(
        "SELECT * FROM bookmarks WHERE chat_id = %s AND author_id = %s "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (chat_id, author_id, limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM bookmarks WHERE chat_id = %s AND author_id = %s", (chat_id, author_id)
    )
    return rows, (total_row["cnt"] if total_row else 0)


async def set_user_bookmarks_excluded(chat_id: int, author_id: int, excluded: bool) -> int:
    """«Кладмен»: массово прячет/возвращает все закладки автора в чатбуке.
    Возвращает число затронутых закладок."""
    return await _execute(
        "UPDATE bookmarks SET excluded = %s WHERE chat_id = %s AND author_id = %s",
        (excluded, chat_id, author_id),
    )


# ----------------------------------------------------------------------------
# Шипперинг («шипперим» / «пейринг») — хранит пары, которых шипперили в
# чате, с процентом «совместимости», чтобы строить топ пар (по числу раз,
# сколько пару шипперили) как общий по чату, так и глобальный по всем чатам
# бота («ирисята» — все известные боту пользователи). user_a/user_b всегда
# хранятся в отсортированном порядке (a < b), чтобы пара «Аня+Вася» и
# «Вася+Аня» агрегировались как одна и та же запись.
# ----------------------------------------------------------------------------
async def ensure_ship_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS ship_pairs ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_a BIGINT NOT NULL, "
        "user_b BIGINT NOT NULL, "
        "shipped_by BIGINT NOT NULL, "
        "percent INT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_ship_chat_pair (chat_id, user_a, user_b), "
        "INDEX idx_ship_pair_global (user_a, user_b), "
        "INDEX idx_ship_author (chat_id, shipped_by)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS ship_opt_out ("
        "user_id BIGINT NOT NULL PRIMARY KEY, "
        "opted_out_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def is_ship_opt_out(user_id: int) -> bool:
    row = await _fetchone("SELECT 1 FROM ship_opt_out WHERE user_id = %s", (user_id,))
    return row is not None


async def list_ship_opt_out_ids() -> set[int]:
    """Полный набор ID, отказавшихся от шипперинга — таблица маленькая
    (по одному человеку на строку), поэтому дешевле забрать разом и
    фильтровать в Python, чем ходить в БД на каждого кандидата отдельно."""
    rows = await _fetchall("SELECT user_id FROM ship_opt_out")
    return {row["user_id"] for row in rows}


async def set_ship_opt_out(user_id: int, opted_out: bool) -> None:
    if opted_out:
        await _execute("INSERT IGNORE INTO ship_opt_out (user_id) VALUES (%s)", (user_id,))
    else:
        await _execute("DELETE FROM ship_opt_out WHERE user_id = %s", (user_id,))


async def add_ship(chat_id: int, user_a: int, user_b: int, shipped_by: int, percent: int) -> int:
    a, b = sorted((user_a, user_b))
    return await _execute(
        "INSERT INTO ship_pairs (chat_id, user_a, user_b, shipped_by, percent) VALUES (%s, %s, %s, %s, %s)",
        (chat_id, a, b, shipped_by, percent),
    )


async def list_chat_ship_pairs(chat_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Топ пар конкретного чата — по числу раз, сколько их шипперили."""
    rows = await _fetchall(
        "SELECT user_a, user_b, COUNT(*) AS times, MAX(percent) AS best_percent, MAX(created_at) AS last_at "
        "FROM ship_pairs WHERE chat_id = %s GROUP BY user_a, user_b "
        "ORDER BY times DESC, last_at DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM (SELECT 1 FROM ship_pairs WHERE chat_id = %s "
        "GROUP BY user_a, user_b) AS t",
        (chat_id,),
    )
    return rows, int(total_row["cnt"] if total_row else 0)


async def list_global_ship_pairs(limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Топ пар по всем чатам бота разом («общий пейринг»)."""
    rows = await _fetchall(
        "SELECT user_a, user_b, COUNT(*) AS times, MAX(percent) AS best_percent, MAX(created_at) AS last_at "
        "FROM ship_pairs GROUP BY user_a, user_b "
        "ORDER BY times DESC, last_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    total_row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM (SELECT 1 FROM ship_pairs GROUP BY user_a, user_b) AS t"
    )
    return rows, int(total_row["cnt"] if total_row else 0)


async def delete_ships_by_author(chat_id: int, author_id: int) -> int:
    """«!Сбросить пейринг» — удаляет только пары, которые шипперил именно
    этот человек, и только в этом чате (не трогает историю других людей
    и других чатов)."""
    return await _execute(
        "DELETE FROM ship_pairs WHERE chat_id = %s AND shipped_by = %s",
        (chat_id, author_id),
    )

async def count_ships_by_author(chat_id: int, author_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS cnt FROM ship_pairs WHERE chat_id = %s AND shipped_by = %s",
        (chat_id, author_id),
    )
    return int(row["cnt"]) if row else 0


# ----------------------------------------------------------------------------
# Экономика («ферма» / боти-коины). economy_wallets — один кошелёк на
# пользователя в каждом чате (валюта не общая между чатами, как и остальная
# статистика бота). star_level растёт автоматически с общим числом фарма
# (см. record_farm) и повышает выход фермы; farm_yield — чат-wide множитель
# («урожайность»), который настраивают админы командой «ферма урожайность».
# ----------------------------------------------------------------------------
async def ensure_economy_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS economy_wallets ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "coins BIGINT NOT NULL DEFAULT 0, "
        "star_level INT NOT NULL DEFAULT 0, "
        "total_farms INT NOT NULL DEFAULT 0, "
        "last_farm_at DATETIME NULL, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS economy_settings ("
        "chat_id BIGINT NOT NULL PRIMARY KEY, "
        "farm_yield DECIMAL(6,2) NOT NULL DEFAULT 100.00"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_fishing_tables() -> None:
    """🎣 Рыбалка — второй (после фермы) способ заработка i¢.

    Хранит и кулдаун, и рекорд: рекорд нужен для «топ уловов», а без него
    рыбалка была бы просто фермой с другим текстом.
    """
    await _execute(
        "CREATE TABLE IF NOT EXISTS fishing_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "last_fish_at DATETIME NULL, "
        "total_catches INT NOT NULL DEFAULT 0, "
        "best_catch INT NOT NULL DEFAULT 0, "
        "best_catch_name VARCHAR(64) NULL, "
        "PRIMARY KEY (chat_id, user_id), "
        "INDEX idx_fishing_best (chat_id, best_catch DESC)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Рекорд по ВЕСУ — отдельно от денежного. Денежный (best_catch) остаётся
    # как есть: он уже накоплен в живых чатах, и переписывать его весом
    # значило бы обнулить всем рекорды задним числом.
    await _add_column_if_missing("fishing_stats", "best_weight", "INT NOT NULL DEFAULT 0")
    await _add_column_if_missing("fishing_stats", "best_weight_species", "VARCHAR(32) NULL")
    # Сетка: рыба хранится ПОШТУЧНО, у каждой свой вес и своё время поимки —
    # от него считается свежесть (см. fishing.freshness).
    await _execute(
        "CREATE TABLE IF NOT EXISTS fishing_net ("
        "id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "species_key VARCHAR(32) NOT NULL, "
        "grams INT NOT NULL, "
        "caught_at DATETIME NOT NULL, "
        "INDEX idx_net_owner (chat_id, user_id, id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_fishing_stats(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT last_fish_at, total_catches, best_catch, best_catch_name, "
        "       best_weight, best_weight_species "
        "FROM fishing_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if row:
        return row
    return {"last_fish_at": None, "total_catches": 0, "best_catch": 0,
            "best_catch_name": None, "best_weight": 0, "best_weight_species": None}


async def record_catch_weight(
    chat_id: int, user_id: int, grams: int, species_key: str, now: datetime
) -> dict:
    """Записывает заброс и рекорд ПО ВЕСУ — рыба при этом уходит в сетку, а не
    в монеты, поэтому денежного рекорда здесь нет (он обновляется при продаже,
    см. record_catch_price)."""
    await _execute(
        "INSERT INTO fishing_stats (chat_id, user_id, last_fish_at, total_catches, "
        "                           best_weight, best_weight_species) "
        "VALUES (%s, %s, %s, 1, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "  last_fish_at = VALUES(last_fish_at), "
        "  total_catches = total_catches + 1, "
        "  best_weight_species = CASE WHEN VALUES(best_weight) > best_weight "
        "                             THEN VALUES(best_weight_species) "
        "                             ELSE best_weight_species END, "
        "  best_weight = GREATEST(best_weight, VALUES(best_weight))",
        (chat_id, user_id, now, grams, species_key),
    )
    return await get_fishing_stats(chat_id, user_id)


async def record_catch_price(chat_id: int, user_id: int, amount: int, catch_name: str) -> None:
    """Денежный рекорд — обновляется в момент ПРОДАЖИ рыбы из сетки.

    Отдельно от record_catch_weight и без счётчика уловов: продажа — это не
    заброс, и увеличивать total_catches она не должна.
    """
    await _execute(
        "INSERT INTO fishing_stats (chat_id, user_id, best_catch, best_catch_name) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "  best_catch_name = CASE WHEN VALUES(best_catch) > best_catch "
        "                         THEN VALUES(best_catch_name) ELSE best_catch_name END, "
        "  best_catch = GREATEST(best_catch, VALUES(best_catch))",
        (chat_id, user_id, amount, catch_name),
    )


# --- сетка ------------------------------------------------------------------
async def list_net(chat_id: int, user_id: int) -> list[dict]:
    """Рыба в сетке, от старой к новой — в том же порядке её видит человек,
    и по этому же порядку он называет номера в «сетка продать {N}»."""
    return await _fetchall(
        "SELECT id, species_key, grams, caught_at FROM fishing_net "
        "WHERE chat_id = %s AND user_id = %s ORDER BY id ASC",
        (chat_id, user_id),
    )


async def add_to_net(chat_id: int, user_id: int, species_key: str,
                     grams: int, now: datetime) -> int:
    await _execute(
        "INSERT INTO fishing_net (chat_id, user_id, species_key, grams, caught_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, user_id, species_key, grams, now),
    )
    row = await _fetchone(
        "SELECT id FROM fishing_net WHERE chat_id = %s AND user_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (chat_id, user_id),
    )
    return int(row["id"]) if row else 0


async def remove_from_net(chat_id: int, user_id: int, fish_id: int) -> bool:
    """True — рыба была на месте и удалена. Проверка владельца прямо в WHERE:
    id глобальный, и без неё чужую рыбу можно было бы продать по номеру."""
    rowcount = await _execute(
        "DELETE FROM fishing_net WHERE id = %s AND chat_id = %s AND user_id = %s",
        (fish_id, chat_id, user_id),
    )
    return bool(rowcount)


async def refresh_net(chat_id: int, user_id: int, now: datetime) -> int:
    """«Лёд»: отсчёт свежести начинается заново для всей рыбы в сетке."""
    return await _execute(
        "UPDATE fishing_net SET caught_at = %s WHERE chat_id = %s AND user_id = %s",
        (now, chat_id, user_id),
    )


async def list_fishing_top(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, best_catch, best_catch_name, total_catches, "
        "       best_weight, best_weight_species FROM fishing_stats "
        "WHERE chat_id = %s AND best_catch > 0 "
        "ORDER BY best_catch DESC, total_catches DESC LIMIT %s",
        (chat_id, limit),
    )


async def list_fishing_weight_top(chat_id: int, limit: int = 10) -> list[dict]:
    """Рекорды по весу — «кто вытащил самую тяжёлую»."""
    return await _fetchall(
        "SELECT user_id, best_weight, best_weight_species, total_catches "
        "FROM fishing_stats WHERE chat_id = %s AND best_weight > 0 "
        "ORDER BY best_weight DESC, total_catches DESC LIMIT %s",
        (chat_id, limit),
    )


# ----------------------------------------------------------------------------
# Новые способы заработка (ежедневный бонус, подработка, шапка по кругу).
#
# Одна таблица на все три вместо трёх почти одинаковых: у каждой механики есть
# только «когда в последний раз» и, у ежедневных, «сколько дней подряд». Заводить
# ради этого отдельную таблицу на каждую новую команду — это по миграции и по
# четыре функции db на каждую мелочь.
#
# streak/last_day заполняют только ежедневные механики; кулдаунным хватает
# last_at, и они эти колонки не трогают.
# ----------------------------------------------------------------------------
async def ensure_earning_activity_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS earning_activity ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "activity_key VARCHAR(32) NOT NULL, "
        "last_at DATETIME NOT NULL, "
        "streak INT NOT NULL DEFAULT 0, "
        "last_day DATE NULL, "
        "total_earned BIGINT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, activity_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Сколько раз занятие вообще выполнялось — под ачивки вида «50 подработок».
    # total_earned для счёта не годится: он в монетах, а шкала менялась.
    await _add_column_if_missing("earning_activity", "times", "INT NOT NULL DEFAULT 0")


async def get_earning_activity(chat_id: int, user_id: int, activity_key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT last_at, streak, last_day, total_earned, times FROM earning_activity "
        "WHERE chat_id = %s AND user_id = %s AND activity_key = %s",
        (chat_id, user_id, activity_key),
    )


async def touch_earning_activity(
    chat_id: int, user_id: int, activity_key: str, now: datetime,
    streak: Optional[int] = None, day=None, earned: int = 0,
) -> None:
    """Отмечает, что механика только что сработала. Пишется ДО начисления
    монет: упади запись — человек останется без денег, но не с возможностью
    жать команду в цикле."""
    await _execute(
        "INSERT INTO earning_activity "
        "(chat_id, user_id, activity_key, last_at, streak, last_day, total_earned, times) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1) "
        "ON DUPLICATE KEY UPDATE last_at = VALUES(last_at), streak = VALUES(streak), "
        "last_day = VALUES(last_day), total_earned = total_earned + VALUES(total_earned), "
        "times = times + 1",
        (chat_id, user_id, activity_key, now, streak or 0, day, max(0, earned)),
    )


async def ensure_treasure_tables() -> None:
    """💎 Клад — общий на чат «джекпот»: каждая неудачная попытка его растит,
    нашедший забирает всё. Строка на чат + личные кулдауны копающих.
    """
    await _execute(
        "CREATE TABLE IF NOT EXISTS chat_treasure ("
        "chat_id BIGINT NOT NULL PRIMARY KEY, "
        "pot BIGINT NOT NULL DEFAULT 0, "
        "attempts INT NOT NULL DEFAULT 0, "
        "started_at DATETIME NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS treasure_diggers ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "last_dig_at DATETIME NULL, "
        "finds INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_treasure(chat_id: int, seed_pot: int, now: datetime) -> dict:
    """Текущий клад чата; если его ещё нет — закапывает новый с seed_pot."""
    row = await _fetchone(
        "SELECT pot, attempts, started_at FROM chat_treasure WHERE chat_id = %s", (chat_id,)
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO chat_treasure (chat_id, pot, attempts, started_at) "
        "VALUES (%s, %s, 0, %s)",
        (chat_id, seed_pot, now),
    )
    return {"pot": seed_pot, "attempts": 0, "started_at": now}


async def get_digger(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT last_dig_at, finds FROM treasure_diggers WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row or {"last_dig_at": None, "finds": 0}


async def record_dig(chat_id: int, user_id: int, now: datetime, found: bool) -> None:
    await _execute(
        "INSERT INTO treasure_diggers (chat_id, user_id, last_dig_at, finds) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE last_dig_at = VALUES(last_dig_at), finds = finds + VALUES(finds)",
        (chat_id, user_id, now, 1 if found else 0),
    )


async def grow_treasure(chat_id: int, amount: int) -> None:
    await _execute(
        "UPDATE chat_treasure SET pot = pot + %s, attempts = attempts + 1 WHERE chat_id = %s",
        (amount, chat_id),
    )


async def claim_treasure(chat_id: int, seed_pot: int, now: datetime) -> Optional[int]:
    """Отдаёт клад нашедшему и закапывает новый. Возвращает выигранную сумму
    либо None, если клад уже забрал кто-то другой прямо сейчас.

    Забираем условием «pot = тот же, что мы видели»: без этого два счастливчика
    в одну секунду получили бы каждый по полному банку.
    """
    row = await _fetchone("SELECT pot FROM chat_treasure WHERE chat_id = %s", (chat_id,))
    if not row:
        return None
    pot = int(row["pot"])
    updated = await _execute(
        "UPDATE chat_treasure SET pot = %s, attempts = 0, started_at = %s "
        "WHERE chat_id = %s AND pot = %s",
        (seed_pot, now, chat_id, pot),
    )
    return pot if updated else None


async def list_treasure_finders(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, finds FROM treasure_diggers WHERE chat_id = %s AND finds > 0 "
        "ORDER BY finds DESC LIMIT %s",
        (chat_id, limit),
    )


async def get_wallet(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT chat_id, user_id, coins, star_level, total_farms, last_farm_at "
        "FROM economy_wallets WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO economy_wallets (chat_id, user_id) VALUES (%s, %s)", (chat_id, user_id)
    )
    return {
        "chat_id": chat_id, "user_id": user_id, "coins": 0,
        "star_level": 0, "total_farms": 0, "last_farm_at": None,
    }


async def try_spend_coins(chat_id: int, user_id: int, amount: int) -> bool:
    """Атомарно списывает amount, если на балансе столько есть.

    True — списали, False — не хватило (баланс не тронут).

    Проверка и списание ОБЯЗАНЫ быть одним запросом. Раньше вызывающий код
    делал это в три захода — прочитать баланс, сравнить, вычесть, — и между
    чтением и вычитанием пролезала вторая команда того же человека: обе
    видели «денег хватает», обе списывали, баланс уходил в минус. Никакой
    экзотики для воспроизведения не нужно: aiogram обрабатывает апдейты
    параллельно, достаточно отправить две покупки подряд.

    Условие coins >= %s стоит прямо в UPDATE, поэтому решение принимает СУБД
    под блокировкой строки, и второй запрос просто не найдёт, что обновлять.
    """
    if amount <= 0:
        return True
    await get_wallet(chat_id, user_id)  # гарантирует наличие строки
    changed = await _execute(
        "UPDATE economy_wallets SET coins = coins - %s "
        "WHERE chat_id = %s AND user_id = %s AND coins >= %s",
        (amount, chat_id, user_id, amount),
    )
    return bool(changed)


async def take_coins_up_to(chat_id: int, user_id: int, amount: int) -> int:
    """Забирает не больше amount и не больше того, что есть. Возвращает,
    сколько реально забрали.

    Для конфискации и краж: там сумма считается от баланса, прочитанного
    мгновением раньше, и при одновременной трате баланс мог бы уйти в минус.
    GREATEST(..., 0) в самом UPDATE исключает это независимо от гонок.
    """
    if amount <= 0:
        return 0
    await get_wallet(chat_id, user_id)
    row = await _fetchone(
        "SELECT coins FROM economy_wallets WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    before = int(row["coins"]) if row else 0
    await _execute(
        "UPDATE economy_wallets SET coins = GREATEST(coins - %s, 0) "
        "WHERE chat_id = %s AND user_id = %s",
        (amount, chat_id, user_id),
    )
    return min(amount, max(before, 0))


async def add_coins(chat_id: int, user_id: int, amount: int) -> int:
    await get_wallet(chat_id, user_id)  # гарантирует наличие строки
    await _execute(
        "UPDATE economy_wallets SET coins = coins + %s WHERE chat_id = %s AND user_id = %s",
        (amount, chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT coins FROM economy_wallets WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    return int(row["coins"] if row else 0)

# ----------------------------------------------------------------------------
# Биржа: "акции" общие на весь чат (единая цена), у каждого пользователя —
# доля (shares), стоимость которой = shares * текущая_цена. Раз в час цена
# меняется на случайный процент в границах stock_settings этого чата
# (см. stock_market_loop в bot.py), а каждое изменение попадает в
# stock_price_history — из неё веб-панель рисует график. Дивиденды копятся
# раз в сутки (процент — там же, в stock_settings) и забираются командой
# "биржа дивиденды".
# ----------------------------------------------------------------------------
async def ensure_stock_market_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS stock_market ("
        "chat_id BIGINT NOT NULL PRIMARY KEY, "
        "price DECIMAL(14,4) NOT NULL DEFAULT 100.0000, "
        "last_change_date DATE NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("stock_market", "last_change_at", "DATETIME NULL")
    # Настройки биржи на чат — те же принципы, что у bank_settings: строка
    # заводится лениво, значения по умолчанию совпадают с константами бота.
    await _execute(
        "CREATE TABLE IF NOT EXISTS stock_settings ("
        "chat_id BIGINT NOT NULL PRIMARY KEY, "
        # Диапазон симметричный, средний шаг ровно 0: биржа перестаёт быть
        # генератором денег и становится игрой с нулевой суммой. Прежние
        # -10/+50 давали средний +20% в час — это +7850% в сутки, из-за чего
        # экономика и раздувалась. Меняете числа — держите середину около нуля,
        # ответ на «биржа настройки» показывает её прямо в чате.
        "min_change_percent DECIMAL(6,2) NOT NULL DEFAULT -15.00, "
        "max_change_percent DECIMAL(6,2) NOT NULL DEFAULT 15.00, "
        "dividend_percent DECIMAL(6,2) NOT NULL DEFAULT 5.00"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Выключатель биржи на чат. Выключенная биржа именно ЗАМОРАЖИВАЕТСЯ:
    # stock_market_loop пропускает такой чат целиком, поэтому курс не ползёт
    # и дивиденды не копятся, а уже купленные акции лежат нетронутыми до
    # включения обратно. last_change_at при этом не трогаем — иначе после
    # включения цикл досчитывал бы все пропущенные часы разом.
    await _add_column_if_missing("stock_settings", "enabled", "BOOL NOT NULL DEFAULT TRUE")
    # История курса для графика в веб-панели. Точка пишется при каждом
    # изменении цены (плановом и ручном); старше STOCK_HISTORY_KEEP_DAYS
    # чистится фоновым циклом бота.
    await _execute(
        "CREATE TABLE IF NOT EXISTS stock_price_history ("
        "id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "price DECIMAL(14,4) NOT NULL, "
        "change_percent DECIMAL(8,3) NULL, "
        "source VARCHAR(16) NOT NULL DEFAULT 'auto', "
        "created_at DATETIME NOT NULL, "
        "INDEX idx_stock_hist_chat_time (chat_id, created_at), "
        # Отдельный индекс по времени — под чистку старых точек: она идёт
        # одним DELETE по всем чатам сразу, и составной (chat_id, created_at)
        # ей не подходит, там created_at второй колонкой.
        "INDEX idx_stock_hist_time (created_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Затравка графика: чатам, где биржа уже работала, но истории ещё нет,
    # добавляем одну точку с текущей ценой. Без неё график первые часы после
    # обновления показывал бы «точек пока мало» во всех чатах сразу.
    await _execute(
        "INSERT INTO stock_price_history (chat_id, price, change_percent, source, created_at) "
        "SELECT m.chat_id, m.price, NULL, 'seed', COALESCE(m.last_change_at, UTC_TIMESTAMP()) "
        "FROM stock_market m "
        "WHERE NOT EXISTS (SELECT 1 FROM stock_price_history h WHERE h.chat_id = m.chat_id)"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS stock_holdings ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "shares DECIMAL(20,6) NOT NULL DEFAULT 0, "
        "invested INT NOT NULL DEFAULT 0, "
        "pending_dividends DECIMAL(14,2) NOT NULL DEFAULT 0, "
        "total_profit INT NOT NULL DEFAULT 0, "
        "last_accrual_date DATE NULL, "
        "last_dividend_at DATETIME NULL, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


# ----------------------------------------------------------------------------
# Банк: вклады под проценты и кредиты с пеней за просрочку. Один активный
# вклад и один активный кредит на человека в каждом чате одновременно — как
# и остальная экономика бота (см. economy_wallets). Проценты — простые
# (rate% в день * дней), фиксируются в момент открытия вклада, чтобы смена
# ставки админом не переписывала уже открытые вклады задним числом.
# ----------------------------------------------------------------------------
async def ensure_bank_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS bank_accounts ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "deposit_amount BIGINT NOT NULL DEFAULT 0, "
        "deposit_days INT NULL, "
        "deposit_rate DECIMAL(6,2) NULL, "
        "deposit_opened_at DATETIME NULL, "
        "deposit_matures_at DATETIME NULL, "
        "credit_amount BIGINT NOT NULL DEFAULT 0, "
        "credit_debt BIGINT NOT NULL DEFAULT 0, "
        "credit_taken_at DATETIME NULL, "
        "credit_due_at DATETIME NULL, "
        "credit_last_penalty_at DATETIME NULL, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS bank_settings ("
        "chat_id BIGINT NOT NULL PRIMARY KEY, "
        "rate_1d DECIMAL(6,2) NOT NULL DEFAULT 5.00, "
        "rate_3d DECIMAL(6,2) NOT NULL DEFAULT 7.00, "
        "rate_7d DECIMAL(6,2) NOT NULL DEFAULT 10.00, "
        "credit_fee_percent DECIMAL(6,2) NOT NULL DEFAULT 20.00, "
        "credit_term_days INT NOT NULL DEFAULT 7, "
        "credit_penalty_percent DECIMAL(6,2) NOT NULL DEFAULT 10.00, "
        "min_deposit BIGINT NOT NULL DEFAULT 1000"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )

async def ensure_bank_blacklist_table() -> None:
    """Чёрный список банка: пользователям из него недоступны кредиты."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS bank_blacklist ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "added_by BIGINT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def is_bank_blacklisted(chat_id: int, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM bank_blacklist WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row is not None


async def add_bank_blacklist(chat_id: int, user_id: int, added_by: Optional[int] = None) -> bool:
    rowcount = await _execute(
        "INSERT IGNORE INTO bank_blacklist (chat_id, user_id, added_by) VALUES (%s, %s, %s)",
        (chat_id, user_id, added_by),
    )
    return bool(rowcount)


async def remove_bank_blacklist(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM bank_blacklist WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return bool(rowcount)


async def list_bank_blacklist(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, added_by, created_at FROM bank_blacklist "
        "WHERE chat_id = %s ORDER BY created_at DESC",
        (chat_id,),
    )


async def get_bank_settings(chat_id: int) -> dict:
    row = await _fetchone("SELECT * FROM bank_settings WHERE chat_id = %s", (chat_id,))
    if row:
        return row
    await _execute("INSERT IGNORE INTO bank_settings (chat_id) VALUES (%s)", (chat_id,))
    return await _fetchone("SELECT * FROM bank_settings WHERE chat_id = %s", (chat_id,))


async def set_bank_rate(chat_id: int, term_key: str, percent: float) -> None:
    """term_key: 'rate_1d' / 'rate_3d' / 'rate_7d' — проверяется вызывающим кодом
    против жёсткого списка, сюда подставляется прямо в SQL-текст."""
    if term_key not in ("rate_1d", "rate_3d", "rate_7d"):
        raise ValueError(f"unsupported term_key: {term_key!r}")
    await get_bank_settings(chat_id)
    await _execute(f"UPDATE bank_settings SET {term_key} = %s WHERE chat_id = %s", (percent, chat_id))


async def set_bank_credit_settings(
    chat_id: int, fee_percent: Optional[float] = None,
    term_days: Optional[int] = None, penalty_percent: Optional[float] = None,
) -> None:
    await get_bank_settings(chat_id)
    sets, params = [], []
    if fee_percent is not None:
        sets.append("credit_fee_percent = %s"); params.append(fee_percent)
    if term_days is not None:
        sets.append("credit_term_days = %s"); params.append(term_days)
    if penalty_percent is not None:
        sets.append("credit_penalty_percent = %s"); params.append(penalty_percent)
    if not sets:
        return
    params.append(chat_id)
    await _execute(f"UPDATE bank_settings SET {', '.join(sets)} WHERE chat_id = %s", tuple(params))


async def set_bank_min_deposit(chat_id: int, amount: int) -> None:
    await get_bank_settings(chat_id)
    await _execute("UPDATE bank_settings SET min_deposit = %s WHERE chat_id = %s", (amount, chat_id))


async def get_bank_account(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT * FROM bank_accounts WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO bank_accounts (chat_id, user_id) VALUES (%s, %s)", (chat_id, user_id)
    )
    return await _fetchone(
        "SELECT * FROM bank_accounts WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


async def open_bank_deposit(chat_id: int, user_id: int, amount: int, days: int, rate: float) -> None:
    await get_bank_account(chat_id, user_id)
    await _execute(
        "UPDATE bank_accounts SET deposit_amount = %s, deposit_days = %s, deposit_rate = %s, "
        "deposit_opened_at = UTC_TIMESTAMP(), deposit_matures_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s DAY) "
        "WHERE chat_id = %s AND user_id = %s",
        (amount, days, rate, days, chat_id, user_id),
    )


async def close_bank_deposit(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE bank_accounts SET deposit_amount = 0, deposit_days = NULL, deposit_rate = NULL, "
        "deposit_opened_at = NULL, deposit_matures_at = NULL WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def open_bank_credit(chat_id: int, user_id: int, principal: int, debt: int, term_days: int) -> None:
    await get_bank_account(chat_id, user_id)
    await _execute(
        "UPDATE bank_accounts SET credit_amount = %s, credit_debt = %s, credit_taken_at = UTC_TIMESTAMP(), "
        "credit_due_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s DAY), credit_last_penalty_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s AND user_id = %s",
        (principal, debt, term_days, chat_id, user_id),
    )


async def reduce_bank_credit_debt(chat_id: int, user_id: int, amount: int) -> int:
    """Уменьшает долг по кредиту, не давая уйти в минус. Возвращает остаток
    долга; если долг погашен полностью — сразу очищает кредитные поля."""
    account = await get_bank_account(chat_id, user_id)
    new_debt = max(0, int(account["credit_debt"]) - amount)
    if new_debt == 0:
        await _execute(
            "UPDATE bank_accounts SET credit_amount = 0, credit_debt = 0, credit_taken_at = NULL, "
            "credit_due_at = NULL, credit_last_penalty_at = NULL WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id),
        )
    else:
        await _execute(
            "UPDATE bank_accounts SET credit_debt = %s WHERE chat_id = %s AND user_id = %s",
            (new_debt, chat_id, user_id),
        )
    return new_debt


async def list_overdue_bank_credits() -> list[dict]:
    """Кредиты с истёкшим сроком, которым пора начислить дневную пеню (не
    чаще раза в 24 часа — см. credit_last_penalty_at)."""
    return await _fetchall(
        "SELECT ba.*, bs.credit_penalty_percent FROM bank_accounts ba "
        "JOIN bank_settings bs ON bs.chat_id = ba.chat_id "
        "WHERE ba.credit_debt > 0 AND ba.credit_due_at IS NOT NULL AND ba.credit_due_at <= UTC_TIMESTAMP() "
        "AND (ba.credit_last_penalty_at IS NULL OR ba.credit_last_penalty_at <= (UTC_TIMESTAMP() - INTERVAL 1 DAY))"
    )


async def apply_bank_credit_penalty(chat_id: int, user_id: int, new_debt: int) -> None:
    await _execute(
        "UPDATE bank_accounts SET credit_debt = %s, credit_last_penalty_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s AND user_id = %s",
        (new_debt, chat_id, user_id),
    )

async def get_stock_price(chat_id: int) -> float:
    row = await _fetchone("SELECT price FROM stock_market WHERE chat_id = %s", (chat_id,))
    if row:
        return float(row["price"])
    await _execute(
        "INSERT IGNORE INTO stock_market (chat_id, price) VALUES (%s, 100.0000)", (chat_id,)
    )
    return 100.0


async def list_stock_market_rows() -> list[dict]:
    """Все чаты, где биржа уже использовалась — для суточного пересчёта цены
    в фоновом цикле (stock_market_loop)."""
    return await _fetchall("SELECT chat_id, price, last_change_date, last_change_at FROM stock_market")


async def set_stock_price(chat_id: int, price: float, change_date) -> None:
    await _execute(
        "UPDATE stock_market SET price = %s, last_change_date = %s, last_change_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s",
        (max(price, 0.01), change_date, chat_id),
    )


# --- Настройки биржи на чат ---------------------------------------------
STOCK_HISTORY_KEEP_DAYS = 30


async def get_stock_settings(chat_id: int) -> dict:
    row = await _fetchone("SELECT * FROM stock_settings WHERE chat_id = %s", (chat_id,))
    if row:
        return row
    await _execute("INSERT IGNORE INTO stock_settings (chat_id) VALUES (%s)", (chat_id,))
    return await _fetchone("SELECT * FROM stock_settings WHERE chat_id = %s", (chat_id,))


async def is_stock_enabled(chat_id: int) -> bool:
    """Включена ли биржа в этом чате. Отдельная функция, а не чтение поля из
    get_stock_settings на месте: проверка нужна в пяти местах (четыре команды
    и фоновый цикл), и дублировать приведение к bool в каждом не хочется."""
    row = await get_stock_settings(chat_id)
    return bool(row["enabled"]) if row else True


async def set_stock_enabled(chat_id: int, enabled: bool) -> None:
    await get_stock_settings(chat_id)      # заводит строку, если её ещё нет
    await _execute(
        "UPDATE stock_settings SET enabled = %s WHERE chat_id = %s", (enabled, chat_id)
    )


async def set_stock_settings(
    chat_id: int, min_change_percent: Optional[float] = None,
    max_change_percent: Optional[float] = None, dividend_percent: Optional[float] = None,
) -> None:
    """Сохраняет только переданные поля. Границы диапазона и знак процентов
    проверяет вызывающий код (бот и веб-панель) — сюда приходят уже готовые
    значения."""
    await get_stock_settings(chat_id)
    sets, params = [], []
    if min_change_percent is not None:
        sets.append("min_change_percent = %s"); params.append(min_change_percent)
    if max_change_percent is not None:
        sets.append("max_change_percent = %s"); params.append(max_change_percent)
    if dividend_percent is not None:
        sets.append("dividend_percent = %s"); params.append(dividend_percent)
    if not sets:
        return
    params.append(chat_id)
    await _execute(f"UPDATE stock_settings SET {', '.join(sets)} WHERE chat_id = %s", tuple(params))


# --- История курса -------------------------------------------------------
async def add_stock_price_point(
    chat_id: int, price: float, change_percent: Optional[float], created_at, source: str = "auto",
) -> None:
    await _execute(
        "INSERT INTO stock_price_history (chat_id, price, change_percent, source, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, max(price, 0.01), change_percent, source, created_at),
    )


async def list_stock_price_history(chat_id: int, since, limit: int = 2000) -> list[dict]:
    """Точки курса чата начиная с `since`, от старых к новым."""
    return await _fetchall(
        "SELECT price, change_percent, source, created_at FROM stock_price_history "
        "WHERE chat_id = %s AND created_at >= %s ORDER BY created_at ASC LIMIT %s",
        (chat_id, since, limit),
    )


async def prune_stock_price_history(before) -> None:
    """Удаляет точки курса старше `before` во всех чатах разом."""
    await _execute("DELETE FROM stock_price_history WHERE created_at < %s", (before,))


async def get_stock_holding(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT shares, invested, pending_dividends, total_profit, last_accrual_date, last_dividend_at "
        "FROM stock_holdings WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO stock_holdings (chat_id, user_id) VALUES (%s, %s)", (chat_id, user_id)
    )
    return {
        "shares": 0, "invested": 0, "pending_dividends": 0,
        "total_profit": 0, "last_accrual_date": None, "last_dividend_at": None,
    }


async def buy_stock(chat_id: int, user_id: int, amount: int, price: float) -> dict:
    """Покупает акции на `amount` монет по текущей цене `price`. Списание
    монет с кошелька делает вызывающий код (bot.py) ДО вызова — здесь только
    учёт долей."""
    await get_stock_holding(chat_id, user_id)  # гарантирует строку
    shares_bought = amount / price
    await _execute(
        "UPDATE stock_holdings SET shares = shares + %s, invested = invested + %s "
        "WHERE chat_id = %s AND user_id = %s",
        (shares_bought, amount, chat_id, user_id),
    )
    return await get_stock_holding(chat_id, user_id)


async def sell_stock(chat_id: int, user_id: int, sell_value: int, price: float) -> Optional[dict]:
    """Продаёт долю акций стоимостью `sell_value` монет по текущей цене.
    Возвращает {"sold_value":..., "profit":...} либо None, если запрошенная
    сумма больше текущей стоимости всех акций пользователя."""
    holding = await get_stock_holding(chat_id, user_id)
    current_value = float(holding["shares"]) * price
    if sell_value <= 0 or current_value <= 0 or sell_value > current_value + 0.01:
        return None
    proportion = sell_value / current_value
    shares_sold = float(holding["shares"]) * proportion
    invested_reduced = float(holding["invested"]) * proportion
    profit = sell_value - invested_reduced
    profit_gain = int(profit) if profit > 0 else 0
    await _execute(
        "UPDATE stock_holdings SET shares = GREATEST(shares - %s, 0), "
        "invested = GREATEST(invested - %s, 0), total_profit = total_profit + %s "
        "WHERE chat_id = %s AND user_id = %s",
        (shares_sold, int(round(invested_reduced)), profit_gain, chat_id, user_id),
    )
    return {"sold_value": sell_value, "profit": profit}


async def list_stock_holdings_due_for_dividend(chat_id: int, today) -> list[dict]:
    """Держатели акций этого чата, кому ещё не начисляли дивиденды сегодня.

    last_accrual_date — колонка типа DATE, а вызывающий код работает с
    datetime: цикл биржи крутится раз в час. Раньше datetime подставлялся
    в сравнение как есть, и MySQL приводил DATE к полуночи того же дня —
    условие «дата < сегодня 14:30» оставалось истинным весь день, поэтому
    дивиденды капали каждый час вместо раза в сутки. Отсюда явный CAST
    аргумента к дате: сравниваем день с днём."""
    return await _fetchall(
        "SELECT user_id, invested FROM stock_holdings WHERE chat_id = %s AND invested > 0 "
        "AND (last_accrual_date IS NULL OR last_accrual_date < CAST(%s AS DATE))",
        (chat_id, today),
    )


async def accrue_dividend(chat_id: int, user_id: int, amount: float, today) -> None:
    await _execute(
        "UPDATE stock_holdings SET pending_dividends = pending_dividends + %s, "
        "last_accrual_date = CAST(%s AS DATE) "
        "WHERE chat_id = %s AND user_id = %s",
        (amount, today, chat_id, user_id),
    )


async def claim_dividends(chat_id: int, user_id: int) -> float:
    """Забирает накопленные дивиденды, засчитывая их в total_profit (для
    ачивки «Инвестор»). Возвращает забранную сумму (0, если копить было нечего)."""
    holding = await get_stock_holding(chat_id, user_id)
    pending = float(holding["pending_dividends"])
    if pending <= 0:
        return 0.0
    await _execute(
        "UPDATE stock_holdings SET pending_dividends = 0, total_profit = total_profit + %s, "
        "last_dividend_at = CURRENT_TIMESTAMP WHERE chat_id = %s AND user_id = %s",
        (int(round(pending)), chat_id, user_id),
    )
    return pending


# ----------------------------------------------------------------------------
# Казино (отдельный от основного кошелька i¢ баланс — только для игр
# «!кости»/«!орёл»/«!решка»/«!покер»). Раз в сутки начисляется бесплатный
# бонус (см. CASINO_DAILY_BONUS в bot.py).
# ----------------------------------------------------------------------------
async def ensure_casino_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS casino_wallets ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "balance BIGINT NOT NULL DEFAULT 0, "
        "last_bonus_date DATE NULL, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS casino_game_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "games_played INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def increment_casino_games(chat_id: int, user_id: int) -> int:
    await _execute(
        "INSERT INTO casino_game_stats (chat_id, user_id, games_played) VALUES (%s, %s, 1) "
        "ON DUPLICATE KEY UPDATE games_played = games_played + 1",
        (chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT games_played FROM casino_game_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return int(row["games_played"]) if row else 0



async def ensure_racing_stats_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS racing_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "bets INT NOT NULL DEFAULT 0, "
        "wins INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def record_race_bet(chat_id: int, user_id: int, won: bool) -> dict:
    await _execute(
        "INSERT INTO racing_stats (chat_id, user_id, bets, wins) VALUES (%s, %s, 1, %s) "
        "ON DUPLICATE KEY UPDATE bets = bets + 1, wins = wins + VALUES(wins)",
        (chat_id, user_id, 1 if won else 0),
    )
    return await _fetchone(
        "SELECT bets, wins FROM racing_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )

async def get_casino_wallet(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT balance, last_bonus_date FROM casino_wallets WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO casino_wallets (chat_id, user_id) VALUES (%s, %s)", (chat_id, user_id)
    )
    return {"balance": 0, "last_bonus_date": None}


async def add_casino_balance(chat_id: int, user_id: int, amount: int) -> int:
    """Прибавляет (или списывает, если amount<0) баланс казино, не давая
    уйти в минус. Возвращает новый баланс."""
    await get_casino_wallet(chat_id, user_id)
    await _execute(
        "UPDATE casino_wallets SET balance = GREATEST(balance + %s, 0) "
        "WHERE chat_id = %s AND user_id = %s",
        (amount, chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT balance FROM casino_wallets WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    return int(row["balance"]) if row else 0


async def try_spend_casino_balance(chat_id: int, user_id: int, amount: int) -> bool:
    """Атомарно снимает ставку с казино-баланса. True — сняли, False — не хватило.

    То же самое и по той же причине, что try_spend_coins выше: проверка и
    списание одним запросом. Читать баланс, сравнивать и потом вычитать
    нельзя — aiogram обрабатывает апдейты параллельно, и две ставки, посланные
    подряд, обе проходят проверку с одними и теми же деньгами.

    Именно на этом месте add_casino_balance() не выручает: он подрезает баланс
    нулём (GREATEST(...,0)), то есть в минус не пустит, но вторую ставку молча
    ПРОСТИТ — сыграть можно будет дважды, заплатив один раз.
    """
    if amount <= 0:
        return True
    await get_casino_wallet(chat_id, user_id)   # гарантирует наличие строки
    changed = await _execute(
        "UPDATE casino_wallets SET balance = balance - %s "
        "WHERE chat_id = %s AND user_id = %s AND balance >= %s",
        (amount, chat_id, user_id, amount),
    )
    return bool(changed)


async def claim_daily_bonus(
    chat_id: int, user_id: int, bonus_amount: int, today=None,
) -> tuple[bool, int]:
    """Начисляет ежедневный бонус, если он ещё не получен сегодня.
    Возвращает (был ли начислен бонус, баланс после).

    today передаёт вызывающий код: «сегодня» здесь — местные сутки по
    настройке «часовой пояс», а модуль про эту настройку не знает. Раньше
    тут стоял date.today(), то есть зона ОПЕРАЦИОННОЙ СИСТЕМЫ, — бонус
    обновлялся в полночь сервера, а не в полночь чата."""
    wallet = await get_casino_wallet(chat_id, user_id)
    # Запасное значение — UTC, а не date.today(): зона операционной системы
    # не должна влиять на бота вообще нигде.
    today = today or datetime.utcnow().date()
    if wallet.get("last_bonus_date") == today:
        return False, int(wallet["balance"])
    new_balance = await add_casino_balance(chat_id, user_id, bonus_amount)
    await _execute(
        "UPDATE casino_wallets SET last_bonus_date = %s WHERE chat_id = %s AND user_id = %s",
        (today, chat_id, user_id),
    )
    return True, new_balance



    
async def transfer_coins(chat_id: int, from_user_id: int, to_user_id: int, amount: int) -> bool:
    """Атомарный перевод монет между двумя кошельками одного чата.
    False — если у отправителя недостаточно средств (баланс не уходит в минус)."""
    await get_wallet(chat_id, from_user_id)
    await get_wallet(chat_id, to_user_id)
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await conn.begin()
            try:
                await cur.execute(
                    "SELECT coins FROM economy_wallets WHERE chat_id = %s AND user_id = %s FOR UPDATE",
                    (chat_id, from_user_id),
                )
                row = await cur.fetchone()
                if row is None or row["coins"] < amount:
                    await conn.rollback()
                    return False
                await cur.execute(
                    "UPDATE economy_wallets SET coins = coins - %s WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, from_user_id),
                )
                await cur.execute(
                    "UPDATE economy_wallets SET coins = coins + %s WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, to_user_id),
                )
                await conn.commit()
                return True
            except Exception:
                await conn.rollback()
                raise

async def record_farm(chat_id: int, user_id: int, amount: int, farmed_at: datetime, star_cap: int = 10, farms_per_star: int = 20) -> dict:
    """Начисляет монеты за один фарм, обновляет время последнего фарма и
    пересчитывает звёздность от общего числа успешных фармов (по одной
    звезде за каждые `farms_per_star` фармов, максимум `star_cap`)."""
    await get_wallet(chat_id, user_id)
    await _execute(
        "UPDATE economy_wallets SET coins = coins + %s, total_farms = total_farms + 1, "
        "last_farm_at = %s, star_level = LEAST(%s, FLOOR(total_farms / %s)) "
        "WHERE chat_id = %s AND user_id = %s",
        (amount, farmed_at, star_cap, farms_per_star, chat_id, user_id),
    )
    return await get_wallet(chat_id, user_id)


async def get_farm_yield(chat_id: int) -> float:
    row = await _fetchone("SELECT farm_yield FROM economy_settings WHERE chat_id = %s", (chat_id,))
    return float(row["farm_yield"]) if row else 100.0


async def set_farm_yield(chat_id: int, percent: float) -> None:
    await _execute(
        "INSERT INTO economy_settings (chat_id, farm_yield) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE farm_yield = VALUES(farm_yield)",
        (chat_id, percent),
    )


async def list_coins_top(
    chat_id: int, limit: int = 10, offset: int = 0
) -> tuple[list[dict], int]:
    """Страница топа по монетам и ОБЩЕЕ число участников в нём (как
    list_top_messages выше — по этой паре строится листание).

    Пустые кошельки отсекаются намеренно: строка в economy_wallets заводится
    при первом же обращении к экономике, поэтому нулевых записей в чате
    обычно больше, чем ненулевых. Раньше это было не видно — топ отдавал
    только первую десятку, — но при листании нули растянулись бы на страницы
    одинаковых «0 i¢» после реального топа.
    """
    count_row = await _fetchone(
        "SELECT COUNT(*) AS total FROM economy_wallets WHERE chat_id = %s AND coins > 0",
        (chat_id,),
    )
    rows = await _fetchall(
        "SELECT user_id, coins, star_level FROM economy_wallets "
        "WHERE chat_id = %s AND coins > 0 "
        "ORDER BY coins DESC LIMIT %s OFFSET %s",
        (chat_id, limit, offset),
    )
    return rows, int(count_row["total"] if count_row else 0)


# ----------------------------------------------------------------------------
# Бизнесы: пассивный доход (см. businesses.py — там весь баланс и налог).
#
# Фонового цикла у бизнесов НЕТ и не нужно: в строке лежит «сколько уже
# накоплено» (accrued) и «с какого момента копим» (last_tick_at), а текущая
# сумма считается на лету по прошедшему времени. Так бот может простоять
# выключенным сутки и ничего не потеряет — при первом же обращении досчитает.
#
# Первичный ключ включает business_key: одному человеку положено по одному
# бизнесу каждого типа, и это ограничение держит сама база, а не проверка
# в коде — второй «Аэропорт» просто не вставится.
# ----------------------------------------------------------------------------
async def ensure_businesses_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS businesses ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "business_key VARCHAR(32) NOT NULL, "
        "level TINYINT NOT NULL DEFAULT 1, "
        "accrued INT NOT NULL DEFAULT 0, "
        "last_tick_at DATETIME NOT NULL, "
        "bought_at DATETIME NOT NULL, "
        "PRIMARY KEY (chat_id, user_id, business_key), "
        "INDEX idx_businesses_owner (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Поломки и срочные предложения приехали позже самой таблицы — добавляем
    # колонки отдельно, чтобы у тех, кто уже играет, ничего не пересоздавалось.
    await _add_column_if_missing("businesses", "broken_kind", "VARCHAR(64) NULL")
    await _add_column_if_missing("businesses", "broken_at", "DATETIME NULL")
    await _add_column_if_missing("businesses", "boost_until", "DATETIME NULL")
    # Оснащение (охрана, аппаратура, реклама, сейф) — отдельной таблицей, а не
    # колонками: список оснащения будет расти, и каждый раз менять схему
    # businesses ради ещё одного флага не хочется.
    await _execute(
        "CREATE TABLE IF NOT EXISTS business_upgrades ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "business_key VARCHAR(32) NOT NULL, "
        "upgrade_key VARCHAR(32) NOT NULL, "
        "bought_at DATETIME NOT NULL, "
        "PRIMARY KEY (chat_id, user_id, business_key, upgrade_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def ensure_pets_table() -> None:
    """Личные питомцы (см. pets.py). Не путать с питомцами пары из
    «Отношений 2.0» — те живут в своей таблице и принадлежат двоим."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS user_pets ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "pet_key VARCHAR(32) NOT NULL, "
        "pet_name VARCHAR(64) NULL, "
        "hunger INT NOT NULL DEFAULT 100, "
        "mood INT NOT NULL DEFAULT 100, "
        "last_tick_at DATETIME NOT NULL, "
        "last_fed_at DATETIME NULL, "
        "last_care_at DATETIME NULL, "
        "bought_at DATETIME NOT NULL, "
        "ability VARCHAR(32) NULL DEFAULT NULL, "
        "ability_rerolls INT NOT NULL DEFAULT 0, "
        "xp INT NOT NULL DEFAULT 0, "
        "xp_tick_at DATETIME NULL, "
        "PRIMARY KEY (chat_id, user_id, pet_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("profile_cards", "pinned_pet", "VARCHAR(32) DEFAULT NULL")
    # ability = NULL значит «способность вида из каталога»; заполняется, только
    # когда хозяин платно меняет способность именно этому питомцу (см. pets.py
    # ability_reroll_price) — на вид в каталоге и на питомцев других хозяев
    # это не влияет.
    await _add_column_if_missing("user_pets", "ability", "VARCHAR(32) NULL DEFAULT NULL")
    await _add_column_if_missing("user_pets", "ability_rerolls", "INT NOT NULL DEFAULT 0")
    # Уровень растёт от xp, а xp — лениво по часам с xp_tick_at (см. pets.py
    # xp_now). Специально СВОЯ метка времени, а не last_tick_at: у него уже
    # есть история с покупки питомца, и завести уровень от неё значило бы
    # мгновенно выдать всем старым питомцам максимальный уровень в день
    # обновления бота. Поэтому у существующих строк метку старта опыта
    # обнуляем на «сейчас» ниже — прокачка стартует с нуля с этого момента.
    await _add_column_if_missing("user_pets", "xp", "INT NOT NULL DEFAULT 0")
    await _add_column_if_missing("user_pets", "xp_tick_at", "DATETIME NULL")
    await _execute(
        "UPDATE user_pets SET xp_tick_at = %s WHERE xp_tick_at IS NULL",
        (datetime.utcnow(),),
    )


async def ensure_seasons_table() -> None:
    """Очки сезона копятся по мере игры, а не считаются задним числом:
    урон по боссам и собранный доход нигде не хранятся историей, и восстановить
    их в конце месяца было бы уже не из чего."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS season_scores ("
        "chat_id BIGINT NOT NULL, "
        "season VARCHAR(7) NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "points INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, season, user_id), "
        "INDEX idx_season_top (chat_id, season, points DESC)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS season_closed ("
        "chat_id BIGINT NOT NULL, "
        "season VARCHAR(7) NOT NULL, "
        "closed_at DATETIME NOT NULL, "
        "PRIMARY KEY (chat_id, season)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_season_points(chat_id: int, season: str, user_id: int, points: int) -> None:
    if points <= 0:
        return
    await _execute(
        "INSERT INTO season_scores (chat_id, season, user_id, points) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE points = points + VALUES(points)",
        (chat_id, season, user_id, int(points)),
    )


async def list_season_scores(chat_id: int, season: str, limit: int = 50) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, points FROM season_scores "
        "WHERE chat_id = %s AND season = %s AND points > 0 "
        "ORDER BY points DESC, user_id ASC LIMIT %s",
        (chat_id, season, limit),
    )


async def get_season_points(chat_id: int, season: str, user_id: int) -> int:
    row = await _fetchone(
        "SELECT points FROM season_scores "
        "WHERE chat_id = %s AND season = %s AND user_id = %s",
        (chat_id, season, user_id),
    )
    return int(row["points"]) if row else 0


async def close_season(chat_id: int, season: str, now) -> bool:
    """Помечает сезон закрытым. False — его уже закрывали.

    Проверка и запись одним запросом: цикл закрытия может совпасть с ручным
    вызовом, и без этого награды выдались бы дважды.
    """
    return bool(await _execute(
        "INSERT IGNORE INTO season_closed (chat_id, season, closed_at) "
        "VALUES (%s, %s, %s)",
        (chat_id, season, now),
    ))


async def ensure_pet_catalog(chat_id: int, defaults) -> int:
    """Каталог питомцев чата. Встроенные из pets.py досеиваются, свои —
    добавляются админом через панель и живут только здесь.

    Дозасев, а не «только если пусто»: иначе новые встроенные питомцы не
    доехали бы в чаты, где каталог уже создан (та же история, что с товарами
    магазина — см. seed_extra_shop_items)."""
    await _execute(
        "CREATE TABLE IF NOT EXISTS pet_catalog ("
        "chat_id BIGINT NOT NULL, "
        "pet_key VARCHAR(32) NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "emoji VARCHAR(16) NOT NULL DEFAULT '🐾', "
        "price INT NOT NULL, "
        "sound VARCHAR(64) NOT NULL DEFAULT 'радуется', "
        "ability VARCHAR(32) NOT NULL DEFAULT 'none', "
        "PRIMARY KEY (chat_id, pet_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("pet_catalog", "ability", "VARCHAR(32) NOT NULL DEFAULT 'none'")
    # Временное выключение и потолок численности — правятся из панели.
    await _add_column_if_missing("pet_catalog", "is_active", "BOOL NOT NULL DEFAULT TRUE")
    await _add_column_if_missing("pet_catalog", "max_count", "INT NULL")
    added = 0
    for spec in defaults:
        changed = await _execute(
            "INSERT IGNORE INTO pet_catalog "
            "(chat_id, pet_key, name, emoji, price, sound, ability) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (chat_id, spec.key, spec.name, spec.emoji, spec.price, spec.sound,
             spec.ability),
        )
        added += bool(changed)
    return added


async def list_pet_catalog(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT pet_key, name, emoji, price, sound, ability, is_active, max_count "
        "FROM pet_catalog "
        "WHERE chat_id = %s ORDER BY price ASC, pet_key ASC",
        (chat_id,),
    )


async def get_pet_spec(chat_id: int, key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT pet_key, name, emoji, price, sound, ability, is_active, max_count "
        "FROM pet_catalog "
        "WHERE chat_id = %s AND pet_key = %s",
        (chat_id, key),
    )


async def add_pet_spec(chat_id: int, key: str, name: str, emoji: str,
                       price: int, sound: str, ability: str = "none") -> bool:
    changed = await _execute(
        "INSERT IGNORE INTO pet_catalog "
        "(chat_id, pet_key, name, emoji, price, sound, ability) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (chat_id, key, name, emoji, price, sound, ability),
    )
    return bool(changed)


async def update_pet_spec(chat_id: int, key: str, **fields) -> bool:
    """Меняет отдельные поля вида питомца. Пустой набор — ничего не делаем.

    Названия колонок берутся из белого списка, а не из ключей вызова: сюда
    приходят данные из панели, и подстановка произвольного имени в SQL была
    бы дырой.
    """
    allowed = {"name", "emoji", "price", "sound", "ability", "is_active", "max_count"}
    sets, args = [], []
    for column, value in fields.items():
        if column not in allowed:
            continue
        sets.append(f"{column} = %s")
        args.append(value)
    if not sets:
        return False
    args += [chat_id, key]
    return bool(await _execute(
        f"UPDATE pet_catalog SET {', '.join(sets)} "
        "WHERE chat_id = %s AND pet_key = %s",
        tuple(args),
    ))


async def count_pet_owners(chat_id: int, key: str) -> int:
    """Сколько людей в чате уже завели такого питомца — под потолок численности."""
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM user_pets WHERE chat_id = %s AND pet_key = %s",
        (chat_id, key),
    )
    return int(row["total"]) if row else 0


async def delete_pet_spec(chat_id: int, key: str) -> bool:
    return bool(await _execute(
        "DELETE FROM pet_catalog WHERE chat_id = %s AND pet_key = %s", (chat_id, key)
    ))


async def list_pets(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT pet_key, pet_name, hunger, mood, last_tick_at, last_fed_at, "
        "last_care_at, bought_at, ability, ability_rerolls, xp, xp_tick_at "
        "FROM user_pets "
        "WHERE chat_id = %s AND user_id = %s ORDER BY bought_at",
        (chat_id, user_id),
    )


async def get_pet(chat_id: int, user_id: int, key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT pet_key, pet_name, hunger, mood, last_tick_at, last_fed_at, "
        "last_care_at, bought_at, ability, ability_rerolls, xp, xp_tick_at "
        "FROM user_pets "
        "WHERE chat_id = %s AND user_id = %s AND pet_key = %s",
        (chat_id, user_id, key),
    )


async def add_pet(chat_id: int, user_id: int, key: str, now) -> bool:
    """Заводит питомца. False — такой у человека уже есть."""
    changed = await _execute(
        "INSERT IGNORE INTO user_pets "
        "(chat_id, user_id, pet_key, hunger, mood, last_tick_at, bought_at, xp_tick_at) "
        "VALUES (%s, %s, %s, 100, 100, %s, %s, %s)",
        (chat_id, user_id, key, now, now, now),
    )
    return bool(changed)


async def set_pet_stats(chat_id: int, user_id: int, key: str,
                        hunger: int, mood: int, xp: int, now,
                        fed_at=None, care_at=None) -> None:
    """Фиксирует сытость, настроение и опыт на момент now.

    xp — уже посчитанный вызывающим итог (пассивный прирост с прошлого раза
    плюс бонус за действие, см. pets.xp_now): здесь просто банкуется, как
    и hunger/mood. Отметки о кормлении и ласке ставятся только если переданы:
    одно действие не должно сбрасывать откат другого.
    """
    sets = ["hunger = %s", "mood = %s", "last_tick_at = %s", "xp = %s", "xp_tick_at = %s"]
    args: list = [max(0, int(hunger)), max(0, int(mood)), now, max(0, int(xp)), now]
    if fed_at is not None:
        sets.append("last_fed_at = %s")
        args.append(fed_at)
    if care_at is not None:
        sets.append("last_care_at = %s")
        args.append(care_at)
    args += [chat_id, user_id, key]
    await _execute(
        f"UPDATE user_pets SET {', '.join(sets)} "
        "WHERE chat_id = %s AND user_id = %s AND pet_key = %s",
        tuple(args),
    )


async def rename_pet(chat_id: int, user_id: int, key: str, name: Optional[str]) -> None:
    await _execute(
        "UPDATE user_pets SET pet_name = %s "
        "WHERE chat_id = %s AND user_id = %s AND pet_key = %s",
        (name, chat_id, user_id, key),
    )


async def set_pet_ability(chat_id: int, user_id: int, key: str,
                          ability: str, rerolls: int) -> bool:
    """Индивидуальная способность питомца — только у этого хозяина.

    ability здесь никогда не NULL: «сбросить к способности вида» этой
    командой не делают, а явный выбор «без способности» тоже сохраняется
    как значение (pets.ABILITY_NONE), а не NULL — NULL означает «override
    не задан», а не «выбрано отсутствие способности».

    Возвращает, задело ли обновление строку — деньги уже списаны к этому
    моменту, и по False вызывающий обязан их вернуть (гонка: питомца
    отпустили между чтением и списанием).
    """
    return bool(await _execute(
        "UPDATE user_pets SET ability = %s, ability_rerolls = %s "
        "WHERE chat_id = %s AND user_id = %s AND pet_key = %s",
        (ability, rerolls, chat_id, user_id, key),
    ))


async def set_pinned_pet(chat_id: int, user_id: int, key: Optional[str]) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, pinned_pet) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE pinned_pet = VALUES(pinned_pet)",
        (chat_id, user_id, key),
    )


async def list_business_upgrades(chat_id: int, user_id: int, key: str) -> set[str]:
    rows = await _fetchall(
        "SELECT upgrade_key FROM business_upgrades "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (chat_id, user_id, key),
    )
    return {r["upgrade_key"] for r in rows}


async def add_business_upgrade(chat_id: int, user_id: int, key: str,
                               upgrade: str, now) -> bool:
    """Ставит оснащение. False — оно уже стоит (второй раз платить не за что)."""
    changed = await _execute(
        "INSERT IGNORE INTO business_upgrades "
        "(chat_id, user_id, business_key, upgrade_key, bought_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, user_id, key, upgrade, now),
    )
    return bool(changed)


async def clear_business_upgrades(chat_id: int, user_id: int, key: str) -> None:
    """Снимает всё оснащение с бизнеса — при смене владельца и при продаже.

    Оснащение намеренно НЕ переезжает к новому хозяину: иначе перепродажа
    прокачанного бизнеса стала бы выгоднее, чем его содержание.
    """
    await _execute(
        "DELETE FROM business_upgrades "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (chat_id, user_id, key),
    )


async def set_business_broken(chat_id: int, user_id: int, key: str,
                              kind: str, accrued: int, now) -> bool:
    """Ломает бизнес и тут же фиксирует накопленное: сломанный не копит, и
    момент остановки должен быть записан ровно тот, когда он сломался.

    Условие broken_kind IS NULL — защита от повторной поломки уже сломанного:
    иначе тик цикла, наложившийся на предыдущий, обнулил бы счётчик простоя.
    """
    changed = await _execute(
        "UPDATE businesses SET broken_kind = %s, broken_at = %s, accrued = %s, "
        "last_tick_at = %s WHERE chat_id = %s AND user_id = %s AND business_key = %s "
        "AND broken_kind IS NULL",
        (kind, now, max(0, int(accrued)), now, chat_id, user_id, key),
    )
    return bool(changed)


async def repair_business(chat_id: int, user_id: int, key: str, now) -> bool:
    """Чинит бизнес. False — он и не был сломан (значит, деньги брать не за что)."""
    changed = await _execute(
        "UPDATE businesses SET broken_kind = NULL, broken_at = NULL, last_tick_at = %s "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s "
        "AND broken_kind IS NOT NULL",
        (now, chat_id, user_id, key),
    )
    return bool(changed)


async def set_business_boost(chat_id: int, user_id: int, key: str,
                             until, accrued: int, now) -> None:
    """Включает надбавку к доходу до момента until, зафиксировав накопленное:
    дальше копилка считается уже по новой ставке."""
    await _execute(
        "UPDATE businesses SET boost_until = %s, accrued = %s, last_tick_at = %s "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (until, max(0, int(accrued)), now, chat_id, user_id, key),
    )


async def list_chat_businesses(chat_id: int) -> list[dict]:
    """Все бизнесы чата — нужно циклу поломок."""
    return await _fetchall(
        "SELECT user_id, business_key, level, accrued, last_tick_at, broken_kind, boost_until "
        "FROM businesses WHERE chat_id = %s",
        (chat_id,),
    )


_BUSINESS_FIELDS = ("business_key, level, accrued, last_tick_at, bought_at, "
                    "broken_kind, broken_at, boost_until")


async def list_user_businesses(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        f"SELECT {_BUSINESS_FIELDS} "
        "FROM businesses WHERE chat_id = %s AND user_id = %s ORDER BY bought_at",
        (chat_id, user_id),
    )


async def get_user_business(chat_id: int, user_id: int, key: str) -> Optional[dict]:
    return await _fetchone(
        f"SELECT {_BUSINESS_FIELDS} "
        "FROM businesses WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (chat_id, user_id, key),
    )


async def add_business(chat_id: int, user_id: int, key: str, now) -> bool:
    """Заводит бизнес. False — такой у человека уже есть (второй не положен)."""
    changed = await _execute(
        "INSERT IGNORE INTO businesses "
        "(chat_id, user_id, business_key, level, accrued, last_tick_at, bought_at) "
        "VALUES (%s, %s, %s, 1, 0, %s, %s)",
        (chat_id, user_id, key, now, now),
    )
    return bool(changed)


async def set_business_accrual(chat_id: int, user_id: int, key: str, accrued: int, now) -> None:
    """Фиксирует накопленное на момент now — «пересчитали и запомнили»."""
    await _execute(
        "UPDATE businesses SET accrued = %s, last_tick_at = %s "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (max(0, int(accrued)), now, chat_id, user_id, key),
    )


async def set_business_level(chat_id: int, user_id: int, key: str, level: int,
                             accrued: int, now) -> None:
    """Поднимает уровень и одновременно фиксирует накопленное: у нового уровня
    свой потолок, и пересчитывать копилку нужно ровно в этот момент."""
    await _execute(
        "UPDATE businesses SET level = %s, accrued = %s, last_tick_at = %s "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (int(level), max(0, int(accrued)), now, chat_id, user_id, key),
    )


async def delete_business(chat_id: int, user_id: int, key: str) -> bool:
    changed = await _execute(
        "DELETE FROM businesses WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (chat_id, user_id, key),
    )
    return bool(changed)


async def move_business(chat_id: int, from_id: int, to_id: int, key: str, now) -> bool:
    """Передаёт бизнес другому человеку, обнуляя копилку.

    False — либо у отдающего такого бизнеса нет, либо у получателя такой УЖЕ
    есть (по одному каждого типа на человека). Проверка и перенос идут одним
    запросом: между отдельными SELECT и UPDATE получатель успел бы купить
    такой же сам, и перенос затёр бы его бизнес вместе с накопленным.
    """
    changed = await _execute(
        "UPDATE IGNORE businesses SET user_id = %s, accrued = 0, last_tick_at = %s "
        "WHERE chat_id = %s AND user_id = %s AND business_key = %s",
        (to_id, now, chat_id, from_id, key),
    )
    return bool(changed)


async def count_businesses(chat_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM businesses WHERE chat_id = %s", (chat_id,)
    )
    return int(row["total"]) if row else 0


# ----------------------------------------------------------------------------
# «Моя статья» — шуточный «приговор дня». Один и тот же результат закреплён
# за пользователем на календарный день (UTC): при повторном вызове в тот же
# день отдаётся та же пара (статья + шаблон фразы) из daily_articles, на
# следующий день строка для новой даты создаётся заново со свежим рандомом.
# ----------------------------------------------------------------------------
async def ensure_daily_article_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS daily_articles ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "article_date DATE NOT NULL, "
        "article_index INT NOT NULL, "
        "template_index INT NOT NULL, "
        "PRIMARY KEY (chat_id, user_id, article_date)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_or_create_daily_article(
    chat_id: int, user_id: int, article_date: date, article_index: int, template_index: int
) -> dict:
    """Возвращает уже закреплённую за сегодня статью, а если её ещё нет —
    атомарно создаёт её со случайными article_index/template_index,
    переданными вызывающей стороной (см. cmd_my_article в bot.py)."""
    await _execute(
        "INSERT IGNORE INTO daily_articles (chat_id, user_id, article_date, article_index, template_index) "
        "VALUES (%s, %s, %s, %s, %s)",
        (chat_id, user_id, article_date, article_index, template_index),
    )
    row = await _fetchone(
        "SELECT article_index, template_index FROM daily_articles "
        "WHERE chat_id = %s AND user_id = %s AND article_date = %s",
        (chat_id, user_id, article_date),
    )
    return row or {"article_index": article_index, "template_index": template_index}


# ----------------------------------------------------------------------------
# Вложения боти-коинов в чат («Бкоин {число}» переводит монеты из личного
# кошелька в общий баланс чата; «Бтоп стата» показывает историю вложений).
# chat_coins хранится прямо в economy_settings (уже есть строка на чат —
# см. farm_yield), а сама история — отдельной таблицей-леджером.
# ----------------------------------------------------------------------------
async def ensure_chat_investment_table() -> None:
    await _add_column_if_missing("economy_settings", "chat_coins", "BIGINT NOT NULL DEFAULT 0")
    await _execute(
        "CREATE TABLE IF NOT EXISTS chat_coin_investments ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "amount BIGINT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_chat_coin_investments_chat (chat_id, created_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


# ---------------------------------------------------------------------------
# Подписки: «+подписка» на человека, чтобы он мог позвать своих одной командой.
# Подписки живут внутри чата — на одного и того же человека в разных чатах
# подписываются разные люди, и созыв тоже чатовый.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Веб-панель: учётные записи для входа в админку бота.
#
# Пароли хранятся только argon2id-хешем. Роли всего две: owner (может всё,
# включая управление аккаунтами) и admin (всё, кроме аккаунтов).
# ---------------------------------------------------------------------------

async def ensure_panel_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS panel_users ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "username VARCHAR(64) NOT NULL, "
        "password_hash VARCHAR(255) NOT NULL, "
        "role ENUM('owner','admin') NOT NULL DEFAULT 'admin', "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "created_by INT NULL, "
        "last_login_at DATETIME NULL, "
        "disabled BOOL NOT NULL DEFAULT FALSE, "
        "UNIQUE KEY uniq_panel_username (username)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Журнал входов: и для «кто заходил», и для блокировки перебора пароля.
    await _execute(
        "CREATE TABLE IF NOT EXISTS panel_logins ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "username VARCHAR(64) NOT NULL, "
        "ip VARCHAR(64) NULL, "
        "success BOOL NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_panel_logins (username, created_at), "
        "INDEX idx_panel_logins_ip (ip, created_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )

    # Аккаунты-участники: роль 'member', вход по одноразовому коду от бота (без
    # пароля), привязка к Telegram id. ALTER ... MODIFY идемпотентен — можно при
    # каждом старте. Расширяем роль-энум, делаем пароль необязательным (у
    # участников его нет) и добавляем поля привязки.
    await _execute(
        "ALTER TABLE panel_users MODIFY role ENUM('owner','admin','member') "
        "NOT NULL DEFAULT 'admin'"
    )
    await _execute("ALTER TABLE panel_users MODIFY password_hash VARCHAR(255) NULL")
    await _add_column_if_missing("panel_users", "tg_user_id", "BIGINT NULL")
    await _add_column_if_missing("panel_users", "tg_full_name", "VARCHAR(128) NULL")
    # Один tg-аккаунт — не больше одной строки panel_users (ни двум member,
    # ни двум staff, ни member+staff разом). MySQL считает каждый NULL
    # отдельным значением, так что это не мешает множеству ещё не
    # привязанных строк персонала с tg_user_id IS NULL.
    try:
        await _add_unique_index_if_missing("panel_users", "uniq_panel_users_tg", "tg_user_id")
    except aiomysql.IntegrityError:
        logger.error(
            "Не удалось добавить UNIQUE INDEX uniq_panel_users_tg на panel_users.tg_user_id — "
            "в таблице уже есть дублирующиеся значения tg_user_id. Панель продолжит работу БЕЗ "
            "этой защиты на уровне схемы (привязка тг всё ещё проверяется в коде, но без гарантии "
            "уникальности от БД). Чтобы исправить: выполните "
            "'SELECT tg_user_id, COUNT(*) FROM panel_users WHERE tg_user_id IS NOT NULL "
            "GROUP BY tg_user_id HAVING COUNT(*) > 1' и вручную устраните дубли, затем "
            "перезапустите панель."
        )
    # Одноразовые коды входа участника: бот кладёт код с TTL, панель его гасит.
    await _execute(
        "CREATE TABLE IF NOT EXISTS panel_link_codes ("
        "code VARCHAR(16) PRIMARY KEY, "
        "tg_user_id BIGINT NOT NULL, "
        "tg_username VARCHAR(64) NULL, "
        "tg_full_name VARCHAR(128) NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "expires_at DATETIME NOT NULL, "
        "used BOOL NOT NULL DEFAULT FALSE, "
        "INDEX idx_link_codes_tg (tg_user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def create_panel_link_code(
    code: str, tg_user_id: int, tg_username: Optional[str],
    tg_full_name: Optional[str], expires_at,
) -> None:
    """Кладёт одноразовый код входа участника. На пользователя держим один
    активный код — прежние его коды удаляем, чтобы не копились."""
    await _execute("DELETE FROM panel_link_codes WHERE tg_user_id = %s", (tg_user_id,))
    await _execute(
        "INSERT INTO panel_link_codes (code, tg_user_id, tg_username, tg_full_name, expires_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (code, tg_user_id, tg_username, tg_full_name, expires_at),
    )


async def consume_panel_link_code(code: str) -> Optional[dict]:
    """Гасит код: возвращает привязку (tg_user_id и т.п.), только если код есть,
    не использован и не истёк. Одноразовый — сразу помечаем used."""
    row = await _fetchone(
        "SELECT code, tg_user_id, tg_username, tg_full_name FROM panel_link_codes "
        "WHERE code = %s AND used = FALSE AND expires_at > UTC_TIMESTAMP()",
        (code,),
    )
    if not row:
        return None
    await _execute("UPDATE panel_link_codes SET used = TRUE WHERE code = %s", (code,))
    return row


async def get_panel_member_by_tg(tg_user_id: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM panel_users WHERE tg_user_id = %s AND role = 'member'",
        (tg_user_id,),
    )


async def get_panel_user_by_tg(tg_user_id: int) -> Optional[dict]:
    """Любая роль — в отличие от get_panel_member_by_tg (только role='member'),
    нужна проверить «этот tg уже к кому-то привязан», прежде чем создавать
    новую привязку (member или staff)."""
    return await _fetchone(
        "SELECT * FROM panel_users WHERE tg_user_id = %s", (tg_user_id,)
    )


async def is_username_taken_by_other(username: str, exclude_user_id: Optional[int] = None) -> bool:
    """Занят ли логин КЕМ-ТО ДРУГИМ (не самим обновляемым аккаунтом) —
    участник должен иметь возможность повторно ввести свой же логин при
    смене пароля, не получая отказ «занято»."""
    row = await _fetchone(
        "SELECT id FROM panel_users WHERE username = %s AND id != %s",
        (username, exclude_user_id or 0),
    )
    return row is not None


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


async def create_panel_member(tg_user_id: int, username: str, tg_full_name: Optional[str]) -> int:
    return await _execute(
        "INSERT INTO panel_users (username, password_hash, role, tg_user_id, tg_full_name) "
        "VALUES (%s, NULL, 'member', %s, %s)",
        (username, tg_user_id, tg_full_name),
    )


async def update_panel_member_name(user_id: int, tg_full_name: Optional[str]) -> None:
    await _execute(
        "UPDATE panel_users SET tg_full_name = %s WHERE id = %s", (tg_full_name, user_id)
    )


async def count_panel_users() -> int:
    row = await _fetchone("SELECT COUNT(*) AS total FROM panel_users")
    return int(row["total"]) if row else 0


async def get_panel_user(username: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM panel_users WHERE username = %s", (username,)
    )


async def get_panel_user_by_id(user_id: int) -> Optional[dict]:
    return await _fetchone("SELECT * FROM panel_users WHERE id = %s", (user_id,))


async def list_panel_users() -> list[dict]:
    return await _fetchall(
        "SELECT id, username, role, created_at, last_login_at, disabled "
        "FROM panel_users ORDER BY role, username"
    )


async def create_panel_user(
    username: str, password_hash: str, role: str, created_by: Optional[int] = None
) -> int:
    return await _execute(
        "INSERT INTO panel_users (username, password_hash, role, created_by) "
        "VALUES (%s, %s, %s, %s)",
        (username, password_hash, role, created_by),
    )


async def set_panel_password(user_id: int, password_hash: str) -> bool:
    return bool(await _execute(
        "UPDATE panel_users SET password_hash = %s WHERE id = %s",
        (password_hash, user_id),
    ))


async def set_panel_user_tg_link(user_id: int, tg_user_id: int, tg_full_name: Optional[str]) -> bool:
    return bool(await _execute(
        "UPDATE panel_users SET tg_user_id = %s, tg_full_name = %s WHERE id = %s",
        (tg_user_id, tg_full_name, user_id),
    ))


async def set_panel_user_disabled(user_id: int, disabled: bool) -> bool:
    return bool(await _execute(
        "UPDATE panel_users SET disabled = %s WHERE id = %s", (disabled, user_id)
    ))


async def delete_panel_user(user_id: int) -> bool:
    return bool(await _execute("DELETE FROM panel_users WHERE id = %s", (user_id,)))


async def touch_panel_login(user_id: int) -> None:
    await _execute(
        "UPDATE panel_users SET last_login_at = NOW() WHERE id = %s", (user_id,)
    )


async def count_failed_logins_by_ip(username: str, ip: Optional[str], minutes: int) -> int:
    """Неудачные попытки конкретного вида входа с ОДНОГО адреса.

    Отдельно от count_failed_logins: там условие «логин ИЛИ адрес», и для входа
    участника (у которого вместо логина одна и та же служебная метка) это
    означало бы общий счётчик на всех — один перебирающий закрывал бы вход
    всему чату. Здесь порог считается строго по адресу нарушителя.
    """
    if not ip:
        return 0
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM panel_logins "
        "WHERE success = FALSE AND username = %s AND ip = %s "
        "AND created_at >= DATE_SUB(NOW(), INTERVAL %s MINUTE)",
        (username, ip, minutes),
    )
    return int(row["total"]) if row else 0


async def add_panel_login_attempt(username: str, ip: Optional[str], success: bool) -> None:
    await _execute(
        "INSERT INTO panel_logins (username, ip, success) VALUES (%s, %s, %s)",
        (username, ip, success),
    )


async def count_failed_logins(username: str, ip: Optional[str], minutes: int) -> int:
    """Неудачные попытки за период — по логину ИЛИ по адресу.

    Считаем и то и другое: перебор одного пароля по многим логинам ловится по
    ip, а распределённый перебор одного логина — по имени.
    """
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM panel_logins "
        "WHERE success = FALSE "
        "AND created_at >= DATE_SUB(NOW(), INTERVAL %s MINUTE) "
        "AND (username = %s OR (ip IS NOT NULL AND ip = %s))",
        (minutes, username, ip),
    )
    return int(row["total"]) if row else 0


async def list_panel_logins(limit: int = 50) -> list[dict]:
    return await _fetchall(
        "SELECT username, ip, success, created_at FROM panel_logins "
        "ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


async def list_known_chats() -> list[dict]:
    """Чаты, которые бот вообще видел — для выпадающего списка в панели."""
    return await _fetchall(
        "SELECT chat_id, COUNT(*) AS members, MAX(last_seen_at) AS last_seen "
        "FROM known_users GROUP BY chat_id ORDER BY members DESC"
    )


async def list_current_chats() -> list[dict]:
    """Чаты, где бот сейчас состоит — для выпадающего списка в панели.
    Как list_known_chats, но по current_users (актуальный состав), а не
    known_users (кого бот видел когда-либо) — иначе счётчик участников
    только рос бы после разделения known_users/current_users."""
    return await _fetchall(
        "SELECT chat_id, COUNT(*) AS members, MAX(last_seen_at) AS last_seen "
        "FROM current_users GROUP BY chat_id ORDER BY members DESC"
    )


# ---------------------------------------------------------------------------
# Итоги недели: выборки «что произошло в чате за последние N дней».
# Отдельных таблиц не нужно — всё считается по уже накопленным данным.
# ---------------------------------------------------------------------------

async def get_top_active_since(chat_id: int, days: int, limit: int = 5) -> list[dict]:
    """Топ по числу сообщений за последние N дней."""
    return await _fetchall(
        "SELECT md.user_id, SUM(md.message_count) AS total, ku.full_name, ku.username "
        "FROM message_daily md "
        "JOIN known_users ku ON ku.chat_id = md.chat_id AND ku.user_id = md.user_id "
        "WHERE md.chat_id = %s AND md.day >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
        "GROUP BY md.user_id, ku.full_name, ku.username "
        "ORDER BY total DESC LIMIT %s",
        (chat_id, days, limit),
    )


async def count_messages_since(chat_id: int, days: int) -> int:
    row = await _fetchone(
        "SELECT COALESCE(SUM(message_count), 0) AS total FROM message_daily "
        "WHERE chat_id = %s AND day >= DATE_SUB(CURDATE(), INTERVAL %s DAY)",
        (chat_id, days),
    )
    return int(row["total"]) if row else 0


async def get_new_members_since(chat_id: int, days: int, limit: int = 20) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, full_name, username FROM known_users "
        "WHERE chat_id = %s AND first_seen_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
        "ORDER BY first_seen_at DESC LIMIT %s",
        (chat_id, days, limit),
    )


async def get_marriages_since(chat_id: int, days: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user1_id, user2_id, married_at FROM marriages "
        "WHERE chat_id = %s AND married_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
        "ORDER BY married_at DESC LIMIT %s",
        (chat_id, days, limit),
    )


async def get_achievements_since(chat_id: int, days: int, limit: int = 15) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, code, earned_at FROM achievements "
        "WHERE chat_id = %s AND earned_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
        "ORDER BY earned_at DESC LIMIT %s",
        (chat_id, days, limit),
    )


async def get_reputation_gainers_since(chat_id: int, days: int, limit: int = 5) -> list[dict]:
    """Кому за период больше всего накинули репутации (минусы вычитаются)."""
    return await _fetchall(
        "SELECT rl.target_id AS user_id, SUM(rl.amount) AS gained, "
        "ku.full_name, ku.username "
        "FROM reputation_log rl "
        "JOIN known_users ku ON ku.chat_id = rl.chat_id AND ku.user_id = rl.target_id "
        "WHERE rl.chat_id = %s AND rl.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
        "GROUP BY rl.target_id, ku.full_name, ku.username "
        "HAVING gained <> 0 ORDER BY gained DESC LIMIT %s",
        (chat_id, days, limit),
    )


# ---------------------------------------------------------------------------
# Репутация: «+5»/«-3» ответом на сообщение.
#
# Держим две таблицы: текущий счёт и журнал операций. Журнал нужен не ради
# истории, а для лимитов — по нему считается, сколько человек уже раздал за
# сутки и как давно он голосовал за конкретного соседа.
# ---------------------------------------------------------------------------

async def ensure_reputation_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS reputation ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "points INT NOT NULL DEFAULT 0, "
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
        "ON UPDATE CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id), "
        "INDEX idx_rep_top (chat_id, points DESC)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS reputation_log ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "actor_id BIGINT NOT NULL, "
        "target_id BIGINT NOT NULL, "
        "amount INT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "INDEX idx_replog_actor (chat_id, actor_id, created_at), "
        "INDEX idx_replog_pair (chat_id, actor_id, target_id, created_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def change_reputation(chat_id: int, actor_id: int, target_id: int, amount: int) -> int:
    """Меняет репутацию и пишет операцию в журнал. Возвращает новый счёт."""
    await _execute(
        "INSERT INTO reputation (chat_id, user_id, points) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE points = points + VALUES(points)",
        (chat_id, target_id, amount),
    )
    await _execute(
        "INSERT INTO reputation_log (chat_id, actor_id, target_id, amount) "
        "VALUES (%s, %s, %s, %s)",
        (chat_id, actor_id, target_id, amount),
    )
    return await get_reputation(chat_id, target_id)


async def get_reputation(chat_id: int, user_id: int) -> int:
    row = await _fetchone(
        "SELECT points FROM reputation WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return int(row["points"]) if row else 0


async def get_reputation_top(chat_id: int, limit: int = 10, worst: bool = False) -> list[dict]:
    order = "ASC" if worst else "DESC"
    return await _fetchall(
        "SELECT r.user_id, r.points, ku.full_name, ku.username "
        "FROM reputation r "
        "JOIN known_users ku ON ku.chat_id = r.chat_id AND ku.user_id = r.user_id "
        f"WHERE r.chat_id = %s AND r.points <> 0 ORDER BY r.points {order} LIMIT %s",
        (chat_id, limit),
    )


async def get_reputation_rank(chat_id: int, user_id: int) -> Optional[int]:
    """Место человека в рейтинге чата (1 — первый). None, если счёт нулевой."""
    row = await _fetchone(
        "SELECT COUNT(*) + 1 AS rank FROM reputation "
        "WHERE chat_id = %s AND points > (SELECT points FROM reputation "
        "WHERE chat_id = %s AND user_id = %s)",
        (chat_id, chat_id, user_id),
    )
    return int(row["rank"]) if row else None


async def sum_reputation_given(chat_id: int, actor_id: int, hours: int) -> int:
    """Сколько очков человек раздал за последние hours часов (по модулю)."""
    row = await _fetchone(
        "SELECT COALESCE(SUM(ABS(amount)), 0) AS total FROM reputation_log "
        "WHERE chat_id = %s AND actor_id = %s "
        "AND created_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)",
        (chat_id, actor_id, hours),
    )
    return int(row["total"]) if row else 0


async def seconds_since_last_vote(chat_id: int, actor_id: int, target_id: int) -> Optional[int]:
    """Сколько секунд прошло с прошлого голоса этого человека за этого же.
    None — раньше не голосовал."""
    row = await _fetchone(
        "SELECT TIMESTAMPDIFF(SECOND, created_at, NOW()) AS ago FROM reputation_log "
        "WHERE chat_id = %s AND actor_id = %s AND target_id = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (chat_id, actor_id, target_id),
    )
    return int(row["ago"]) if row else None


async def reset_reputation(chat_id: int) -> int:
    await _execute("DELETE FROM reputation_log WHERE chat_id = %s", (chat_id,))
    return await _execute("DELETE FROM reputation WHERE chat_id = %s", (chat_id,))


async def delete_reputation_of_user(chat_id: int, user_id: int) -> None:
    await _execute(
        "DELETE FROM reputation WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )


# ---------------------------------------------------------------------------
# Ачивки: разовые достижения за активность и события в чате.
# Каталог самих достижений живёт в bot.py — здесь только «кто что получил».
# ---------------------------------------------------------------------------

async def ensure_achievements_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS achievements ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "code VARCHAR(64) NOT NULL, "
        "earned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id, code), "
        "INDEX idx_ach_user (chat_id, user_id, earned_at)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def grant_achievement(chat_id: int, user_id: int, code: str) -> bool:
    """True — достижение выдано впервые, False — оно уже было.

    Первичный ключ и INSERT IGNORE делают повторную выдачу безопасной: даже
    если проверка сработает дважды подряд, человек получит уведомление один
    раз — именно по возвращённому rowcount.
    """
    rowcount = await _execute(
        "INSERT IGNORE INTO achievements (chat_id, user_id, code) VALUES (%s, %s, %s)",
        (chat_id, user_id, code),
    )
    return bool(rowcount)


async def get_achievements(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT code, earned_at FROM achievements "
        "WHERE chat_id = %s AND user_id = %s ORDER BY earned_at",
        (chat_id, user_id),
    )


async def get_achievement_codes(chat_id: int, user_id: int) -> set:
    rows = await _fetchall(
        "SELECT code FROM achievements WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return {r["code"] for r in rows}


async def count_achievement_holders(chat_id: int, code: str) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM achievements WHERE chat_id = %s AND code = %s",
        (chat_id, code),
    )
    return int(row["total"]) if row else 0


async def get_achievements_top(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT a.user_id, COUNT(*) AS total, ku.full_name, ku.username "
        "FROM achievements a "
        "JOIN known_users ku ON ku.chat_id = a.chat_id AND ku.user_id = a.user_id "
        "WHERE a.chat_id = %s "
        "GROUP BY a.user_id, ku.full_name, ku.username "
        "ORDER BY total DESC, ku.full_name LIMIT %s",
        (chat_id, limit),
    )


async def ensure_subscriptions_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS subscriptions ("
        "chat_id BIGINT NOT NULL, "
        "subscriber_id BIGINT NOT NULL, "
        "target_id BIGINT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, subscriber_id, target_id), "
        "INDEX idx_subs_target (chat_id, target_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_subscription(chat_id: int, subscriber_id: int, target_id: int) -> bool:
    """True — подписка создана, False — она уже была."""
    row = await _fetchone(
        "SELECT 1 AS x FROM subscriptions "
        "WHERE chat_id = %s AND subscriber_id = %s AND target_id = %s",
        (chat_id, subscriber_id, target_id),
    )
    if row:
        return False
    await _execute(
        "INSERT IGNORE INTO subscriptions (chat_id, subscriber_id, target_id) VALUES (%s, %s, %s)",
        (chat_id, subscriber_id, target_id),
    )
    return True


async def remove_subscription(chat_id: int, subscriber_id: int, target_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM subscriptions "
        "WHERE chat_id = %s AND subscriber_id = %s AND target_id = %s",
        (chat_id, subscriber_id, target_id),
    )
    return bool(rowcount)


async def count_subscriptions_of(chat_id: int, subscriber_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM subscriptions WHERE chat_id = %s AND subscriber_id = %s",
        (chat_id, subscriber_id),
    )
    return int(row["total"]) if row else 0


async def get_subscribers(chat_id: int, target_id: int, limit: int = 200) -> list[dict]:
    """Кто подписан на человека (только те, кто ещё в чате)."""
    return await _fetchall(
        "SELECT s.subscriber_id AS user_id, ku.full_name, ku.username "
        "FROM subscriptions s "
        "JOIN known_users ku ON ku.chat_id = s.chat_id AND ku.user_id = s.subscriber_id "
        "WHERE s.chat_id = %s AND s.target_id = %s "
        "ORDER BY s.created_at LIMIT %s",
        (chat_id, target_id, limit),
    )

async def count_subscribers(chat_id: int, target_id: int) -> int:
    """Сколько человек подписано на target_id — для строки в профиле."""
    row = await _fetchone(
        "SELECT COUNT(*) AS total FROM subscriptions WHERE chat_id = %s AND target_id = %s",
        (chat_id, target_id),
    )
    return int(row["total"]) if row else 0

async def get_subscriptions(chat_id: int, subscriber_id: int, limit: int = 200) -> list[dict]:
    """На кого подписан человек."""
    return await _fetchall(
        "SELECT s.target_id AS user_id, ku.full_name, ku.username "
        "FROM subscriptions s "
        "LEFT JOIN known_users ku ON ku.chat_id = s.chat_id AND ku.user_id = s.target_id "
        "WHERE s.chat_id = %s AND s.subscriber_id = %s "
        "ORDER BY s.created_at LIMIT %s",
        (chat_id, subscriber_id, limit),
    )


async def get_top_subscribed(chat_id: int, limit: int = 10) -> list[dict]:
    """Топ по числу подписчиков в чате."""
    return await _fetchall(
        "SELECT s.target_id AS user_id, COUNT(*) AS subs, ku.full_name, ku.username "
        "FROM subscriptions s "
        "JOIN known_users ku ON ku.chat_id = s.chat_id AND ku.user_id = s.target_id "
        "WHERE s.chat_id = %s "
        "GROUP BY s.target_id, ku.full_name, ku.username "
        "ORDER BY subs DESC, ku.full_name LIMIT %s",
        (chat_id, limit),
    )


async def delete_subscriptions_of_user(chat_id: int, user_id: int) -> int:
    """Убирает и его подписки, и подписки на него — при выходе из чата."""
    return await _execute(
        "DELETE FROM subscriptions "
        "WHERE chat_id = %s AND (subscriber_id = %s OR target_id = %s)",
        (chat_id, user_id, user_id),
    )


async def get_recently_active(chat_id: int, minutes: int, limit: int = 50) -> list[dict]:
    """Кто писал за последние N минут.

    Настоящий онлайн-статус Telegram ботам не отдаёт, поэтому «кто в сети»
    строится по времени последнего сообщения. last_seen_at пишется в UTC
    (см. touch_known_user), поэтому и сравниваем с UTC_TIMESTAMP().
    """
    return await _fetchall(
        "SELECT user_id, full_name, username, last_seen_at FROM known_users "
        "WHERE chat_id = %s AND last_seen_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s MINUTE) "
        "ORDER BY last_seen_at DESC LIMIT %s",
        (chat_id, minutes, limit),
    )


async def get_chat_coins(chat_id: int) -> int:
    row = await _fetchone("SELECT chat_coins FROM economy_settings WHERE chat_id = %s", (chat_id,))
    return int(row["chat_coins"]) if row and row.get("chat_coins") is not None else 0


async def add_chat_coins(chat_id: int, amount: int) -> int:
    await _execute(
        "INSERT INTO economy_settings (chat_id, chat_coins) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE chat_coins = chat_coins + VALUES(chat_coins)",
        (chat_id, amount),
    )
    return await get_chat_coins(chat_id)


# ----------------------------------------------------------------------------
# Помощники для случайных событий чата (см. chat_events.py). Все они массовые:
# событие касается сразу всех, и делать это по одному запросу на человека
# было бы и медленно, и не атомарно.
# ----------------------------------------------------------------------------
async def list_wallet_holders(chat_id: int, min_coins: int = 1, limit: int = 500) -> list[dict]:
    """Кошельки чата, где есть что взять, — от самых полных."""
    return await _fetchall(
        "SELECT user_id, coins FROM economy_wallets "
        "WHERE chat_id = %s AND coins >= %s ORDER BY coins DESC LIMIT %s",
        (chat_id, min_coins, limit),
    )


async def list_poor_wallets(chat_id: int, max_coins: int, limit: int = 200) -> list[dict]:
    """Кошельки беднее max_coins — от самых пустых.

    Сортировка обратная list_wallet_holders намеренно: там нужны те, у кого
    есть что взять, здесь — те, кому нужнее, и при упоре в limit отсечь надо
    именно тех, кто к порогу ближе всех."""
    return await _fetchall(
        "SELECT user_id, coins FROM economy_wallets "
        "WHERE chat_id = %s AND coins < %s ORDER BY coins ASC LIMIT %s",
        (chat_id, max_coins, limit),
    )


async def tax_all_wallets(chat_id: int, percent: float) -> int:
    """Списывает percent% с каждого кошелька чата. Возвращает, сколько всего
    списано, — эта сумма уходит в казну чата вызывающим кодом.

    Считаем и списываем одним запросом: между SELECT и UPDATE человек мог бы
    успеть потратить монеты, и налог ушёл бы в минус."""
    row = await _fetchone(
        "SELECT COALESCE(SUM(FLOOR(coins * %s / 100)), 0) AS total FROM economy_wallets "
        "WHERE chat_id = %s AND coins > 0",
        (percent, chat_id),
    )
    total = int(row["total"] or 0) if row else 0
    if total <= 0:
        return 0
    await _execute(
        "UPDATE economy_wallets SET coins = coins - FLOOR(coins * %s / 100) "
        "WHERE chat_id = %s AND coins > 0",
        (percent, chat_id),
    )
    return total


async def add_coins_to_users(chat_id: int, user_ids: list[int], amount: int) -> int:
    """Начисляет amount каждому из user_ids. Возвращает число получивших."""
    if not user_ids or amount == 0:
        return 0
    placeholders = ", ".join(["%s"] * len(user_ids))
    # Строка кошелька может ещё не существовать — заводим недостающие.
    for uid in user_ids:
        await get_wallet(chat_id, uid)
    await _execute(
        f"UPDATE economy_wallets SET coins = GREATEST(coins + %s, 0) "
        f"WHERE chat_id = %s AND user_id IN ({placeholders})",
        (amount, chat_id, *user_ids),
    )
    return len(user_ids)


async def clear_all_surveillance(chat_id: int) -> int:
    """Амнистия: снимает надзор со всех в чате. Возвращает число помилованных."""
    row = await _fetchone(
        "SELECT COUNT(*) AS n FROM robbery_stats WHERE chat_id = %s AND under_surveillance = 1",
        (chat_id,),
    )
    freed = int(row["n"] or 0) if row else 0
    if freed:
        await _execute(
            "UPDATE robbery_stats SET under_surveillance = 0, surveillance_strikes = 0 "
            "WHERE chat_id = %s AND under_surveillance = 1",
            (chat_id,),
        )
    return freed


async def restock_shop_items(chat_id: int, add: int = 3) -> int:
    """Завоз товара: пополняет остатки у позиций с ограниченным запасом,
    не выше restock_max. Возвращает число затронутых позиций."""
    return await _execute(
        "UPDATE shop_items SET stock = LEAST(COALESCE(stock, 0) + %s, COALESCE(restock_max, 10)) "
        "WHERE chat_id = %s AND stock IS NOT NULL AND is_active = 1 "
        "AND stock < COALESCE(restock_max, 10)",
        (add, chat_id),
    )


async def record_chat_investment(chat_id: int, user_id: int, amount: int) -> Optional[int]:
    """Списывает `amount` с личного кошелька пользователя (в этом чате),
    зачисляет его в общий баланс чата и пишет строку в историю вложений.
    Возвращает новый общий баланс чата или None, если монет не хватило.

    Проверку «хватает ли» делает сам UPDATE: раньше она стояла в вызывающем
    коде отдельным запросом, и между проверкой и списанием пролезала вторая
    команда — кошелёк уходил в минус."""
    await get_wallet(chat_id, user_id)  # гарантирует наличие строки кошелька
    spent = await _execute(
        "UPDATE economy_wallets SET coins = coins - %s "
        "WHERE chat_id = %s AND user_id = %s AND coins >= %s",
        (amount, chat_id, user_id, amount),
    )
    if not spent:
        return None
    await _execute(
        "INSERT INTO chat_coin_investments (chat_id, user_id, amount) VALUES (%s, %s, %s)",
        (chat_id, user_id, amount),
    )
    return await add_chat_coins(chat_id, amount)


async def list_chat_investments(chat_id: int, limit: int = 15) -> list[dict]:
    """Последние вложения в чат — свежие сначала (история для «Бтоп стата»)."""
    return await _fetchall(
        "SELECT user_id, amount, created_at FROM chat_coin_investments "
        "WHERE chat_id = %s ORDER BY created_at DESC LIMIT %s",
        (chat_id, limit),
    )


async def list_chat_investment_top(chat_id: int, limit: int = 10) -> list[dict]:
    """Топ вкладчиков чата — сумма всех вложений на человека."""
    return await _fetchall(
        "SELECT user_id, SUM(amount) AS total_amount FROM chat_coin_investments "
        "WHERE chat_id = %s GROUP BY user_id ORDER BY total_amount DESC LIMIT %s",
        (chat_id, limit),
    )

# ----------------------------------------------------------------------------
# Магазин и инвентарь — простые предметы без спецэффектов за i¢. Каталог
# магазина свой у каждого чата (как ферма-урожайность), инвентарь — личный
# набор пользователя с количеством. Предметы можно дарить друг другу.
# ----------------------------------------------------------------------------
async def ensure_shop_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS shop_items ("
        "id INT AUTO_INCREMENT PRIMARY KEY, "
        "chat_id BIGINT NOT NULL, "
        "item_key VARCHAR(64) NOT NULL, "
        "name VARCHAR(64) NOT NULL, "
        "description VARCHAR(255) NULL, "
        "emoji VARCHAR(16) NOT NULL DEFAULT '🎁', "
        "price INT NOT NULL, "
        "is_active BOOL NOT NULL DEFAULT TRUE, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE KEY uniq_shop_item (chat_id, item_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("shop_items", "stock", "INT NULL")
    await _add_column_if_missing("shop_items", "restock_max", "INT NULL DEFAULT 10")
    # Отложенные эффекты предметов: талисман и страховка не срабатывают сразу,
    # а ждут своего случая (следующего заработка, следующей поломки). Живут
    # зарядами, а не временем: купил — лежит, пока не пригодится.
    await _execute(
        "CREATE TABLE IF NOT EXISTS user_item_effects ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "effect VARCHAR(32) NOT NULL, "
        "charges INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, effect)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS user_inventory ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "item_key VARCHAR(64) NOT NULL, "
        "quantity INT NOT NULL DEFAULT 0, "
        "acquired_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id, item_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
DEFAULT_TITLES: list[tuple] = [
    ("king", "👑 Король чата", 5000, None),
    ("richman", "💰 Магнат", 3000, None),
    ("gambler", "🎰 Азартный игрок", 1000, None),
    ("milfhunter", "🚬 Милфхантер", 2000, None),
    ("boss", "😎 Босс", 6000, None),
    ("millionaire", "💸 Миллионер", 7000, None),
    ("sigma", "🗿 Сигма", 4500, None),
    ("joker", "🃏 Джокер", 2500, None),
    ("wizard", "🧙 Волшебник", 5000, None),
    ("pirate", "🏴‍☠️ Пират", 3500, None),
    ("samurai", "⚔️ Самурай", 4200, None),
    ("ninja", "🥷 Ниндзя", 4300, None),
    ("scientist", "🧪 Учёный", 4500, None),
    ("programmer", "💻 Программист", 3500, None),
    ("hacker", "👾 Хакер", 6500, None),
    ("collector", "📦 Коллекционер", 2800, None),
    ("merchant", "💼 Торговец", 3200, None),
    ("champion", "🥇 Чемпион", 6500, None),
    ("astronaut", "🚀 Космонавт", 7000, None),
    ("dragonlord", "🐉 Повелитель драконов", 12000, None),
    ("phoenix", "🔥 Феникс", 9000, None),
    ("firelord", "🔥 Повелитель огня", 6000, None),
    ("iceking", "❄️ Ледяной", 6000, None),
    ("storm", "⚡ Повелитель молний", 6500, None),
    ("ghost", "👻 Призрак", 3800, None),
    ("devil", "😈 Дьявол", 5500, None),
    ("angel", "😇 Ангел", 5500, None),
    ("wolf", "🐺 Одинокий волк", 3000, None),
    ("catlord", "🐱 Повелитель котов", 2500, None),
    ("doglord", "🐶 Повелитель собак", 2500, None),
    ("alchemist", "⚗️ Алхимик", 3900, None),
    ("coffeeking", "☕ Кофеман", 2200, None),
    ("emperor", "👑 Император", 10000, None),
    ("fox", "🦊 Лис", 2800, None),
    ("gladiator", "🛡️ Гладиатор", 4800, None),
    ("memelord", "😂 Мемолог", 2700, None),
    ("moon", "🌙 Лунный", 4500, None),
    ("oracle", "🔮 Оракул", 6500, None),
    ("owl", "🦉 Мудрец", 4000, None),
    ("shark", "🦈 Акула", 5500, None),
    ("sleepy", "😴 Соня", 1500, None),
    ("sun", "☀️ Солнечный", 4500, None),
    ("vampire", "🧛 Вампир", 5500, None),
    ("void", "🌌 Бездна", 9000, None),

    # Только за достижения
    ("legend", "🏛 Живая легенда", None, "msg_10000"),
    ("night_owl_title", "🦉 Ночная сова", None, "night_owl"),
    ("streak_title", "🔥 Несгибаемый", None, "streak_30"),
    ("rich_title", "💵 Богач", None, "coins_10000"),
    ("tycoon_title", "🏦 Магнат экономики", None, "coins_100000"),
    ("jackpot_title", "🎰 Джекпот", None, "casino_jackpot"),
    ("casino_addict_title", "🃏 Завсегдатай казино", None, "casino_100_games"),
    ("robber_title", "🥷 Гроза карманов", None, "robber_20"),
    ("clan_founder_title", "🏰 Основатель клана", None, "clan_founder"),
    ("club_founder_title", "🎪 Основатель кружка", None, "club_founder"),
    ("archivist_title", "🔖 Архивариус", None, "bookmarks_10"),
    ("quote_master_title", "💬 Мастер цитат", None, "quotes_10"),
    ("duel_master_title", "⚔️ Дуэльный мастер", None, "duel_master"),
    ("cupid_title", "💘 Купидон", None, "matchmaker_50"),
    ("career_title", "💼 Карьерист", None, "prof_level10"),
    ("family_title", "👨‍👩‍👧 Многодетный", None, "family_5kids"),
    ("beastmaster_title", "🐾 Повелитель зверей", None, "pets_5"),
    ("architect_title", "🏠 Архитектор", None, "house_built"),
    ("jockey_title", "🏇 Жокей", None, "race_win"),
    ("champion_jockey_title", "🏆 Чемпион ипподрома", None, "race_master"),
    ("generous_title", "🎁 Щедрая душа", None, "generous_20"),
]
# ----------------------------------------------------------------------------
# Модуль «Профессии» — карьерная система поверх i¢. Один набор характеристик
# (уровень/опыт/энергия/настроение/здоровье) на пользователя в каждом чате.
# ----------------------------------------------------------------------------
async def ensure_profession_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS profession_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "profession_key VARCHAR(32) NULL, "
        "prof_level INT NOT NULL DEFAULT 1, "
        "prof_xp INT NOT NULL DEFAULT 0, "
        "energy INT NOT NULL DEFAULT 100, "
        "mood INT NOT NULL DEFAULT 100, "
        "health INT NOT NULL DEFAULT 100, "
        "work_streak INT NOT NULL DEFAULT 0, "
        "last_work_at DATETIME NULL, "
        "last_shift_day DATE NULL, "
        "total_earned BIGINT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    # Счётчик смен — под ачивку «Работяга». total_earned для этого не годится:
    # он в монетах, а шкала заработков со временем менялась.
    await _add_column_if_missing("profession_stats", "total_shifts", "INT NOT NULL DEFAULT 0")
    await _execute(
        "CREATE TABLE IF NOT EXISTS profession_upgrades ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "upgrade_key VARCHAR(32) NOT NULL, "
        "purchased_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id, upgrade_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_profession_stats(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT * FROM profession_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO profession_stats (chat_id, user_id) VALUES (%s, %s)",
        (chat_id, user_id),
    )
    return {
        "chat_id": chat_id, "user_id": user_id, "profession_key": None,
        "prof_level": 1, "prof_xp": 0, "energy": 100, "mood": 100, "health": 100,
        "work_streak": 0, "last_work_at": None, "last_shift_day": None,
        "total_earned": 0,
    }


async def set_profession(chat_id: int, user_id: int, profession_key: Optional[str]) -> None:
    await get_profession_stats(chat_id, user_id)
    await _execute(
        "UPDATE profession_stats SET profession_key = %s, prof_level = 1, prof_xp = 0, "
        "work_streak = 0 WHERE chat_id = %s AND user_id = %s",
        (profession_key, chat_id, user_id),
    )


async def quit_profession(chat_id: int, user_id: int) -> None:
    """Увольнение: профессия снимается, 50% накопленного опыта теряется (см. ТЗ)."""
    stats = await get_profession_stats(chat_id, user_id)
    await _execute(
        "UPDATE profession_stats SET profession_key = NULL, prof_xp = %s, work_streak = 0 "
        "WHERE chat_id = %s AND user_id = %s",
        (int(stats["prof_xp"] * 0.5), chat_id, user_id),
    )


async def update_profession_after_shift(
    chat_id: int, user_id: int, xp_gain: int, coins_earned: int,
    energy_delta: int, mood_delta: int, health_delta: int,
    new_streak: int, shift_day,
) -> dict:
    await get_profession_stats(chat_id, user_id)
    await _execute(
        "UPDATE profession_stats SET prof_xp = prof_xp + %s, "
        "energy = GREATEST(0, LEAST(100, energy + %s)), "
        "mood = GREATEST(0, LEAST(100, mood + %s)), "
        "health = GREATEST(0, LEAST(100, health + %s)), "
        "work_streak = %s, last_work_at = UTC_TIMESTAMP(), last_shift_day = %s, "
        "total_earned = total_earned + %s, total_shifts = total_shifts + 1 "
        "WHERE chat_id = %s AND user_id = %s",
        (xp_gain, energy_delta, mood_delta, health_delta, new_streak, shift_day,
         coins_earned, chat_id, user_id),
    )
    return await get_profession_stats(chat_id, user_id)


async def set_profession_level(chat_id: int, user_id: int, level: int) -> None:
    await _execute(
        "UPDATE profession_stats SET prof_level = %s WHERE chat_id = %s AND user_id = %s",
        (level, chat_id, user_id),
    )


async def adjust_profession_energy(chat_id: int, user_id: int, delta: int) -> int:
    await get_profession_stats(chat_id, user_id)
    await _execute(
        "UPDATE profession_stats SET energy = GREATEST(0, LEAST(100, energy + %s)) "
        "WHERE chat_id = %s AND user_id = %s",
        (delta, chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT energy FROM profession_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return int(row["energy"]) if row else 100


async def list_profession_top(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, profession_key, prof_level, prof_xp, total_earned "
        "FROM profession_stats WHERE chat_id = %s AND profession_key IS NOT NULL "
        "ORDER BY prof_level DESC, prof_xp DESC LIMIT %s",
        (chat_id, limit),
    )


async def list_profession_market(chat_id: int, limit: int = 100) -> list[dict]:
    """Кто какую профессию выбрал (см. «!работа рынок»)."""
    return await _fetchall(
        "SELECT user_id, profession_key, prof_level FROM profession_stats "
        "WHERE chat_id = %s AND profession_key IS NOT NULL "
        "ORDER BY prof_level DESC LIMIT %s",
        (chat_id, limit),
    )


async def has_profession_upgrade(chat_id: int, user_id: int, upgrade_key: str) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM profession_upgrades WHERE chat_id = %s AND user_id = %s AND upgrade_key = %s",
        (chat_id, user_id, upgrade_key),
    )
    return row is not None


async def add_profession_upgrade(chat_id: int, user_id: int, upgrade_key: str) -> bool:
    rowcount = await _execute(
        "INSERT IGNORE INTO profession_upgrades (chat_id, user_id, upgrade_key) VALUES (%s, %s, %s)",
        (chat_id, user_id, upgrade_key),
    )
    return bool(rowcount)


async def list_profession_upgrades(chat_id: int, user_id: int) -> list[str]:
    rows = await _fetchall(
        "SELECT upgrade_key FROM profession_upgrades WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return [r["upgrade_key"] for r in rows]

DEFAULT_SHOP_ITEMS: list[tuple[str, str, int, str, str]] = [
    # (item_key, name, price, description, emoji)

    ("fishka", "Фишка", 50, "Обычная фишка чата — просто красивая штука для коллекции", "🪙"),
    ("sharik", "Шарик", 40, "Яркий воздушный шарик", "🎈"),
    ("pechenka", "Печенька", 30, "Сладкая печенька", "🍪"),
    ("coffee", "Кофе", 70, "Горячий кофе", "☕"),
    ("cvetok", "Цветок", 80, "Красивый цветок", "🌸"),
    ("tort", "Тортик", 100, "Виртуальный тортик — угостите друга", "🎂"),
    ("chocolate", "Шоколад", 120, "Сладкая плитка шоколада", "🍫"),
    ("morojenoe", "Мороженое", 140, "Освежающее мороженое", "🍦"),
    ("zvezda", "Звезда", 200, "Блестящая звезда", "⭐"),
    ("gift", "Подарок", 250, "Красиво упакованный подарок", "🎁"),
    ("pizza", "Пицца", 300, "Большая горячая пицца", "🍕"),
    ("burger", "Бургер", 280, "Аппетитный бургер", "🍔"),
    ("firework", "Фейерверк", 450, "Праздничный салют", "🎆"),
    ("korona", "Корона", 500, "Почувствуйте себя королём чата", "👑"),
    ("medal", "Медаль", 700, "Памятная медаль", "🏅"),
    ("kubok", "Кубок", 900, "Кубок победителя", "🏆"),
    ("cat", "Котик", 1000, "Милый домашний котик", "🐈"),
    ("dog", "Пёс", 1100, "Верный друг", "🐕"),
    ("ring", "Кольцо", 1500, "Красивое золотое кольцо", "💍"),
    ("diamond", "Алмаз", 2500, "Редкий драгоценный камень", "💎"),
    ("robot", "Робот", 3000, "Электронный помощник", "🤖"),
    ("wand", "Волшебная палочка", 3500, "Полна магии", "🪄"),
    ("book", "Книга заклинаний", 4000, "Древняя книга магии", "📖"),
    ("shield", "Щит", 4500, "Надёжная защита", "🛡️"),
    ("sword", "Меч", 5000, "Оружие героя", "⚔️"),
    ("rocket", "Ракета", 6500, "Настоящая космическая ракета", "🚀"),
    ("dragon", "Дракон", 9000, "Легендарный дракон", "🐉"),
    ("phoenix", "Феникс", 12000, "Мифическая птица", "🔥"),

    # Новые предметы из таблицы
    ("bdsm_pletka", "Бдсм Плетка", 700, "Для ваших маленьких игровых затей", "🪢"),
    ("yabloko", "яблоко", 20, "Яблоко. Просто яблоко", "🍎"),
    ("vip_badge", "Вип", 10000, "Вип значок", "🎁"),
    ("kolco", "Кольцо", 900, "Красивое кольцо", "💍"),
    ("crown_gold", "Золотая корона", 4000, "Настоящая корона", "👑"),
    ("trophy", "Кубок", 3000, "Символ победителя", "🏆"),
    ("ringbell", "Колокольчик", 110, "Звонкий сувенир", "🔔"),
    ("gem", "Самоцвет", 2800, "Таинственный камень", "🔮"),
    ("skull", "Череп", 666, "Для любителей мрачного", "💀"),
    ("ghost", "Призрак", 777, "Жуткий сувенир", "👻"),
    ("pumpkin", "Тыква", 350, "Хэллоуинская тыква", "🎃"),
    ("magicbook", "Книга магии", 2800, "Полна заклинаний", "📖"),
    ("magicwand", "Волшебная палочка", 3500, "Исполняет чудеса", "🪄"),
    ("treasure", "Сундук", 2000, "Полный сокровищ", "🪙"),
]
async def seed_default_shop_items(chat_id: int) -> int:
    """Заполняет магазин чата базовыми товарами — только если он ещё
    совсем пуст (первое обращение к «магазин» в этом чате). Возвращает
    число добавленных товаров."""
    existing = await list_shop_items(chat_id, active_only=False)
    if existing:
        return 0
    count = 0
    for item_key, name, price, description, emoji in DEFAULT_SHOP_ITEMS:
        added = await add_shop_item(chat_id, item_key, name, price, description, emoji)
        if added:
            count += 1
    return count



async def list_shop_items(chat_id: int, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM shop_items WHERE chat_id = %s"
    if active_only:
        query += " AND is_active = TRUE"
    query += " ORDER BY price ASC, id ASC"
    return await _fetchall(query, (chat_id,))


async def get_shop_item(chat_id: int, item_key: str) -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM shop_items WHERE chat_id = %s AND item_key = %s", (chat_id, item_key)
    )


async def add_shop_item(
    chat_id: int, item_key: str, name: str, price: int,
    description: Optional[str] = None, emoji: str = "🎁",
    stock: Optional[int] = None, restock_max: Optional[int] = 10,
) -> bool:
    if await get_shop_item(chat_id, item_key) is not None:
        return False
    await _execute(
        "INSERT INTO shop_items (chat_id, item_key, name, description, emoji, price, stock, restock_max) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (chat_id, item_key, name, description, emoji, price, stock, restock_max),
    )
    return True



async def reset_work_cooldown(chat_id: int, user_id: int) -> None:
    """Смену можно взять сразу (предмет «Кофе бригадира»)."""
    await _execute(
        "UPDATE profession_stats SET last_work_at = NULL "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def restore_profession_state(chat_id: int, user_id: int) -> None:
    """Энергия, настроение и здоровье — обратно в 100 (предмет «Аптечка»)."""
    await _execute(
        "UPDATE profession_stats SET energy = 100, mood = 100, health = 100 "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def reset_earning_cooldowns(chat_id: int, user_id: int) -> None:
    """Обнуляет отметки «когда в последний раз» у фермы, рыбалки и клада —
    все три занятия становятся доступны сразу (предмет «Энергетик»).

    Строк может не быть вовсе (человек ещё не фармил) — UPDATE тогда просто
    никого не тронет, и это правильный исход: кулдауна и так нет.
    """
    await _execute(
        "UPDATE economy_wallets SET last_farm_at = NULL "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    await _execute(
        "UPDATE fishing_stats SET last_fish_at = NULL "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    await _execute(
        "UPDATE treasure_diggers SET last_dig_at = NULL "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )


async def add_item_effect(chat_id: int, user_id: int, effect: str, charges: int = 1) -> None:
    """Кладёт заряд отложенного эффекта (талисман, страховка)."""
    await _execute(
        "INSERT INTO user_item_effects (chat_id, user_id, effect, charges) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE charges = charges + VALUES(charges)",
        (chat_id, user_id, effect, max(1, int(charges))),
    )


async def consume_item_effect(chat_id: int, user_id: int, effect: str) -> bool:
    """Тратит один заряд. True — заряд был и списан, False — эффекта нет.

    Проверка и списание одним запросом: этот вызов стоит на пути начисления
    награды, и «прочитать, потом вычесть» дало бы двойное срабатывание при
    двух командах подряд — талисман удвоил бы и ферму, и рыбалку.
    """
    changed = await _execute(
        "UPDATE user_item_effects SET charges = charges - 1 "
        "WHERE chat_id = %s AND user_id = %s AND effect = %s AND charges > 0",
        (chat_id, user_id, effect),
    )
    return bool(changed)


async def list_item_effects(chat_id: int, user_id: int) -> dict[str, int]:
    rows = await _fetchall(
        "SELECT effect, charges FROM user_item_effects "
        "WHERE chat_id = %s AND user_id = %s AND charges > 0",
        (chat_id, user_id),
    )
    return {r["effect"]: int(r["charges"]) for r in rows}


async def delete_shop_item(chat_id: int, item_key: str) -> bool:
    return bool(await _execute(
        "DELETE FROM shop_items WHERE chat_id = %s AND item_key = %s", (chat_id, item_key)
    ))


async def set_shop_item_active(chat_id: int, item_key: str, is_active: bool) -> bool:
    return bool(await _execute(
        "UPDATE shop_items SET is_active = %s WHERE chat_id = %s AND item_key = %s",
        (is_active, chat_id, item_key),
    ))
    

async def set_shop_item_price(chat_id: int, item_key: str, price: int) -> bool:
    return bool(await _execute(
        "UPDATE shop_items SET price = %s WHERE chat_id = %s AND item_key = %s",
        (price, chat_id, item_key),
    ))


async def set_shop_item_stock(chat_id: int, item_key: str, stock: Optional[int]) -> bool:
    return bool(await _execute(
        "UPDATE shop_items SET stock = %s WHERE chat_id = %s AND item_key = %s",
        (stock, chat_id, item_key),
    ))


async def try_decrement_shop_item_stock(chat_id: int, item_key: str) -> bool:
    """Атомарно списывает 1 шт. остатка. True — списано либо остаток
    безлимитный (stock IS NULL). False — остаток уже 0."""
    row = await get_shop_item(chat_id, item_key)
    if row is None:
        return False
    if row.get("stock") is None:
        return True
    rowcount = await _execute(
        "UPDATE shop_items SET stock = stock - 1 "
        "WHERE chat_id = %s AND item_key = %s AND stock > 0",
        (chat_id, item_key),
    )
    return bool(rowcount)


async def try_take_shop_stock(chat_id: int, item_key: str, amount: int) -> bool:
    """Атомарно списывает amount штук остатка. False — столько нет.

    Проверка и списание одним запросом, как в try_spend_coins: иначе две
    покупки подряд обе увидели бы «хватает» и увели остаток в минус.
    """
    if amount <= 0:
        return False
    row = await get_shop_item(chat_id, item_key)
    if row is None:
        return False
    if row.get("stock") is None:
        return True                      # безлимитный товар
    rowcount = await _execute(
        "UPDATE shop_items SET stock = stock - %s "
        "WHERE chat_id = %s AND item_key = %s AND stock >= %s",
        (amount, chat_id, item_key, amount),
    )
    return bool(rowcount)


async def return_shop_stock(chat_id: int, item_key: str, amount: int) -> None:
    """Возвращает остаток на полку — когда покупка сорвалась после списания."""
    if amount <= 0:
        return
    await _execute(
        "UPDATE shop_items SET stock = stock + %s "
        "WHERE chat_id = %s AND item_key = %s AND stock IS NOT NULL",
        (amount, chat_id, item_key),
    )


async def list_shop_items_for_restock(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT item_key, restock_max FROM shop_items "
        "WHERE chat_id = %s AND restock_max IS NOT NULL AND restock_max > 0",
        (chat_id,),
    )


async def restock_shop_item(chat_id: int, item_key: str, amount: int) -> None:
    """Стакает `amount` к текущему остатку (NULL считаем как 0)."""
    await _execute(
        "UPDATE shop_items SET stock = COALESCE(stock, 0) + %s WHERE chat_id = %s AND item_key = %s",
        (amount, chat_id, item_key),
    )


async def set_shop_item_restock_max(chat_id: int, item_key: str, restock_max: Optional[int]) -> bool:
    return bool(await _execute(
        "UPDATE shop_items SET restock_max = %s WHERE chat_id = %s AND item_key = %s",
        (restock_max, chat_id, item_key),
    ))


async def list_shop_chat_ids() -> list[int]:
    rows = await _fetchall("SELECT DISTINCT chat_id FROM shop_items")
    return [r["chat_id"] for r in rows]


async def add_inventory_item(chat_id: int, user_id: int, item_key: str, amount: int = 1) -> None:
    await _execute(
        "INSERT INTO user_inventory (chat_id, user_id, item_key, quantity) VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)",
        (chat_id, user_id, item_key, amount),
    )


async def remove_inventory_item(chat_id: int, user_id: int, item_key: str, amount: int = 1) -> bool:
    """Списывает amount штук, не давая уйти в минус. False — если недостаточно
    (или предмета нет вовсе)."""
    row = await _fetchone(
        "SELECT quantity FROM user_inventory WHERE chat_id = %s AND user_id = %s AND item_key = %s",
        (chat_id, user_id, item_key),
    )
    if row is None or row["quantity"] < amount:
        return False
    new_qty = row["quantity"] - amount
    if new_qty <= 0:
        await _execute(
            "DELETE FROM user_inventory WHERE chat_id = %s AND user_id = %s AND item_key = %s",
            (chat_id, user_id, item_key),
        )
    else:
        await _execute(
            "UPDATE user_inventory SET quantity = %s WHERE chat_id = %s AND user_id = %s AND item_key = %s",
            (new_qty, chat_id, user_id, item_key),
        )
    return True


async def list_inventory(chat_id: int, user_id: int) -> list[dict]:
    """Инвентарь пользователя + описание из каталога (LEFT JOIN — предмет мог
    быть удалён из магазина, но остаться у людей)."""
    return await _fetchall(
        "SELECT ui.item_key, ui.quantity, ui.acquired_at, si.name, si.description, si.emoji "
        "FROM user_inventory ui "
        "LEFT JOIN shop_items si ON si.chat_id = ui.chat_id AND si.item_key = ui.item_key "
        "WHERE ui.chat_id = %s AND ui.user_id = %s ORDER BY ui.acquired_at DESC",
        (chat_id, user_id),
    )

# ----------------------------------------------------------------------------
# Автоудаление: сообщения указанного пользователя в чате, привязанном как
# complaint_chat_id («жалобы сюда»), бот удаляет сразу, пока для него включён
# этот режим.
# ----------------------------------------------------------------------------
async def ensure_auto_delete_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS auto_delete_targets ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "added_by BIGINT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_auto_delete_target(chat_id: int, user_id: int, added_by: Optional[int] = None) -> bool:
    rowcount = await _execute(
        "INSERT IGNORE INTO auto_delete_targets (chat_id, user_id, added_by) VALUES (%s, %s, %s)",
        (chat_id, user_id, added_by),
    )
    return bool(rowcount)


async def remove_auto_delete_target(chat_id: int, user_id: int) -> bool:
    rowcount = await _execute(
        "DELETE FROM auto_delete_targets WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return bool(rowcount)


async def is_auto_delete_target(chat_id: int, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM auto_delete_targets WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row is not None


async def list_auto_delete_targets(chat_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, added_by, created_at FROM auto_delete_targets "
        "WHERE chat_id = %s ORDER BY created_at DESC",
        (chat_id,),
    )


# ----------------------------------------------------------------------------
# Стрик активности — сколько дней подряд человек писал в чате. Считается по
# уже существующему message_daily, отдельной таблицы не требуется.
# ----------------------------------------------------------------------------
async def list_active_days(chat_id: int, user_id: int, limit_days: int = 400) -> list[date]:
    """Дни (с message_count > 0), от новых к старым — сырьё для compute_streak()
    в bot.py."""
    rows = await _fetchall(
        "SELECT day FROM message_daily WHERE chat_id = %s AND user_id = %s "
        "AND message_count > 0 ORDER BY day DESC LIMIT %s",
        (chat_id, user_id, limit_days),
    )
    return [r["day"] for r in rows]



async def list_recent_active_users(chat_id: int, limit: int = 300) -> list[dict]:
    """Известные боту участники чата, писавшие сегодня или вчера (по
    message_daily) — кандидаты для подсчёта стрика (см. compute_streak() в
    bot.py). У всех остальных участников стрик гарантированно равен 0 —
    полный перебор всех известных пользователей чата не нужен.

    Сутки здесь ОБЯЗАНЫ быть по UTC: message_daily.day пишется из
    datetime.utcnow() (см. increment_daily_count), и раньше стоявший
    date.today() брал зону ОС — на не-UTC сервере стрики читались бы
    не за те дни, что записаны."""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    return await _fetchall(
        "SELECT DISTINCT ku.user_id, ku.full_name, ku.username FROM message_daily md "
        "JOIN known_users ku ON ku.chat_id = md.chat_id AND ku.user_id = md.user_id "
        "WHERE md.chat_id = %s AND md.day IN (%s, %s) AND md.message_count > 0 "
        "LIMIT %s",
        (chat_id, today, yesterday, limit),
    )


# ----------------------------------------------------------------------------
# Использование предметов из инвентаря («использовать {ключ} @username») —
# у каждого ЭКЗЕМПЛЯРА предмета лимит 10 применений ВСЕГО (не в сутки), после
# чего предмет полностью удаляется из инвентаря, независимо от quantity.
# ----------------------------------------------------------------------------
ITEM_USE_LIMIT = 10


async def ensure_item_usage_table() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS item_usage ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "item_key VARCHAR(64) NOT NULL, "
        "used_count INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, item_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def get_item_usage_count(chat_id: int, user_id: int, item_key: str) -> int:
    row = await _fetchone(
        "SELECT used_count FROM item_usage WHERE chat_id = %s AND user_id = %s AND item_key = %s",
        (chat_id, user_id, item_key),
    )
    return int(row["used_count"]) if row else 0


async def increment_item_usage(chat_id: int, user_id: int, item_key: str) -> int:
    """Увеличивает счётчик использований предмета и возвращает новое значение."""
    await _execute(
        "INSERT INTO item_usage (chat_id, user_id, item_key, used_count) VALUES (%s, %s, %s, 1) "
        "ON DUPLICATE KEY UPDATE used_count = used_count + 1",
        (chat_id, user_id, item_key),
    )
    return await get_item_usage_count(chat_id, user_id, item_key)


async def reset_item_usage(chat_id: int, user_id: int, item_key: str) -> None:
    """Сбрасывает счётчик — вызывается при полном удалении предмета из
    инвентаря (лимит исчерпан), чтобы при повторной покупке того же предмета
    счётчик начинался заново."""
    await _execute(
        "DELETE FROM item_usage WHERE chat_id = %s AND user_id = %s AND item_key = %s",
        (chat_id, user_id, item_key),
    )


async def remove_inventory_item_completely(chat_id: int, user_id: int, item_key: str) -> bool:
    """Удаляет предмет из инвентаря целиком, независимо от quantity —
    используется, когда лимит применений исчерпан."""
    rowcount = await _execute(
        "DELETE FROM user_inventory WHERE chat_id = %s AND user_id = %s AND item_key = %s",
        (chat_id, user_id, item_key),
    )
    return rowcount > 0

# ----------------------------------------------------------------------------
# Лутбоксы: случайные коробки, дающие случайный предмет магазина или титул.
# Пять уровней редкости (см. LOOTBOX_TYPES в bot.py). Количество купленных,
# но ещё не открытых боксов хранится по (chat_id, user_id, rarity).
# lootbox_stats — сколько всего открыто (для ачивки «Азартный» и топа).
# ----------------------------------------------------------------------------
async def ensure_lootbox_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS lootboxes ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "rarity VARCHAR(16) NOT NULL, "
        "quantity INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id, rarity)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS lootbox_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "opened_count INT NOT NULL DEFAULT 0, "
        "rare_count INT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )


async def add_lootbox(chat_id: int, user_id: int, rarity: str, amount: int = 1) -> None:
    await _execute(
        "INSERT INTO lootboxes (chat_id, user_id, rarity, quantity) VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)",
        (chat_id, user_id, rarity, amount),
    )


async def get_lootbox_count(chat_id: int, user_id: int, rarity: str) -> int:
    row = await _fetchone(
        "SELECT quantity FROM lootboxes WHERE chat_id = %s AND user_id = %s AND rarity = %s",
        (chat_id, user_id, rarity),
    )
    return int(row["quantity"]) if row else 0


async def remove_lootbox(chat_id: int, user_id: int, rarity: str, amount: int) -> bool:
    """Атомарно списывает amount боксов. False — если их меньше, чем amount."""
    rowcount = await _execute(
        "UPDATE lootboxes SET quantity = quantity - %s "
        "WHERE chat_id = %s AND user_id = %s AND rarity = %s AND quantity >= %s",
        (amount, chat_id, user_id, rarity, amount),
    )
    return rowcount > 0


async def list_user_lootboxes(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT rarity, quantity FROM lootboxes "
        "WHERE chat_id = %s AND user_id = %s AND quantity > 0 ORDER BY rarity",
        (chat_id, user_id),
    )


async def increment_lootbox_stats(chat_id: int, user_id: int, opened_delta: int, rare_delta: int) -> dict:
    await _execute(
        "INSERT INTO lootbox_stats (chat_id, user_id, opened_count, rare_count) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE opened_count = opened_count + VALUES(opened_count), "
        "rare_count = rare_count + VALUES(rare_count)",
        (chat_id, user_id, opened_delta, rare_delta),
    )
    return await get_lootbox_stats(chat_id, user_id)


async def get_lootbox_stats(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT opened_count, rare_count FROM lootbox_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return row or {"opened_count": 0, "rare_count": 0}


async def list_lootbox_top(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, opened_count, rare_count FROM lootbox_stats "
        "WHERE chat_id = %s AND opened_count > 0 "
        "ORDER BY opened_count DESC LIMIT %s",
        (chat_id, limit),
    )

# ============================================================================
# Казино: рулетка (красное/чёрное/зелёное). Ставка — из уже существующего
# кошелька economy_wallets (i¢), выигрыш/проигрыш через уже существующий
# add_coins(). Отдельной таблицы не требуется.
# ============================================================================
RED_ROULETTE_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_number_color(n: int) -> str:
    RED_ROULETTE_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

    if n == 0:
        return "green"
    return "red" if n in RED_ROULETTE_NUMBERS else "black"


# ============================================================================
# Титулы: каталог (titles) + владение (user_titles) + «надетый» титул
# в profile_cards.active_title. Часть титулов покупается за i¢ (price NOT
# NULL), часть выдаётся автоматически за ачивку (achievement_code NOT NULL).
# ============================================================================
async def ensure_titles_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS titles ("
        "title_key VARCHAR(64) NOT NULL PRIMARY KEY, "
        "name VARCHAR(64) NOT NULL, "
        "price INT NULL, "
        "achievement_code VARCHAR(64) NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _execute(
        "CREATE TABLE IF NOT EXISTS user_titles ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "title_key VARCHAR(64) NOT NULL, "
        "acquired_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (chat_id, user_id, title_key)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("profile_cards", "active_title", "VARCHAR(64) DEFAULT NULL")


# (ключ, отображаемое имя, цена в i¢ или None, код ачивки или None)


async def seed_titles_if_empty() -> int:
    row = await _fetchone("SELECT COUNT(*) AS cnt FROM titles")
    if row and row["cnt"]:
        return 0
    for key, name, price, ach in DEFAULT_TITLES:
        await _execute(
            "INSERT INTO titles (title_key, name, price, achievement_code) VALUES (%s, %s, %s, %s)",
            (key, name, price, ach),
        )
    return len(DEFAULT_TITLES)

async def add_title_if_missing(title_key: str, name: str,
                               price: Optional[int] = None) -> None:
    """Заводит титул, если такого ещё нет. Цена None — купить нельзя (см.
    cmd_title_buy: титул без цены не продаётся). Нужно сезонам: их титулы
    выдаются только за место и появляются в каталоге по факту выдачи."""
    await _execute(
        "INSERT IGNORE INTO titles (title_key, name, price, achievement_code) "
        "VALUES (%s, %s, %s, NULL)",
        (title_key, name, price),
    )


async def seed_titles_missing() -> int:
    added = 0
    for key, name, price, ach in DEFAULT_TITLES:
        exists = await _fetchone("SELECT title_key FROM titles WHERE title_key = %s", (key,))
        if exists:
            continue
        await _execute(
            "INSERT INTO titles (title_key, name, price, achievement_code) VALUES (%s, %s, %s, %s)",
            (key, name, price, ach),
        )
        added += 1
    return added

async def list_titles() -> list[dict]:
    return await _fetchall("SELECT * FROM titles ORDER BY price IS NULL, price, name")


async def get_title(title_key: str) -> Optional[dict]:
    return await _fetchone("SELECT * FROM titles WHERE title_key = %s", (title_key,))


async def list_user_titles(chat_id: int, user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT t.title_key, t.name FROM user_titles ut "
        "JOIN titles t ON t.title_key = ut.title_key "
        "WHERE ut.chat_id = %s AND ut.user_id = %s ORDER BY ut.acquired_at",
        (chat_id, user_id),
    )


async def has_title(chat_id: int, user_id: int, title_key: str) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM user_titles WHERE chat_id = %s AND user_id = %s AND title_key = %s",
        (chat_id, user_id, title_key),
    )
    return row is not None


async def grant_title(chat_id: int, user_id: int, title_key: str) -> bool:
    """True — титул выдан впервые, False — уже был."""
    rowcount = await _execute(
        "INSERT IGNORE INTO user_titles (chat_id, user_id, title_key) VALUES (%s, %s, %s)",
        (chat_id, user_id, title_key),
    )
    return bool(rowcount)


async def set_active_title(chat_id: int, user_id: int, title_key: Optional[str]) -> None:
    await _execute(
        "INSERT INTO profile_cards (chat_id, user_id, active_title) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE active_title = VALUES(active_title)",
        (chat_id, user_id, title_key),
    )

async def list_all_active_mutes() -> list[dict]:
    """Ещё не истёкшие муты с ограниченным сроком — для восстановления
    отложенных задач авто-снятия после перезапуска бота."""
    return await _fetchall(
        "SELECT chat_id, user_id, muted_until FROM mutes "
        "WHERE muted_until IS NOT NULL AND muted_until > NOW()"
    )


async def ensure_robbery_tables() -> None:
    await _execute(
        "CREATE TABLE IF NOT EXISTS robbery_stats ("
        "chat_id BIGINT NOT NULL, "
        "user_id BIGINT NOT NULL, "
        "attempts INT NOT NULL DEFAULT 0, "
        "successes INT NOT NULL DEFAULT 0, "
        "fails INT NOT NULL DEFAULT 0, "
        "blocked INT NOT NULL DEFAULT 0, "
        "stolen_total BIGINT NOT NULL DEFAULT 0, "
        "lost_total BIGINT NOT NULL DEFAULT 0, "
        "times_robbed INT NOT NULL DEFAULT 0, "
        "money_lost_as_victim BIGINT NOT NULL DEFAULT 0, "
        "last_robbery_at DATETIME NULL, "
        "PRIMARY KEY (chat_id, user_id)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    await _add_column_if_missing("robbery_stats", "surveillance_strikes", "INT NOT NULL DEFAULT 0")
    await _add_column_if_missing("robbery_stats", "under_surveillance", "TINYINT(1) NOT NULL DEFAULT 0")

async def get_robbery_stats(chat_id: int, user_id: int) -> dict:
    row = await _fetchone(
        "SELECT * FROM robbery_stats WHERE chat_id = %s AND user_id = %s", (chat_id, user_id)
    )
    if row:
        return row
    await _execute(
        "INSERT IGNORE INTO robbery_stats (chat_id, user_id) VALUES (%s, %s)", (chat_id, user_id)
    )
    return {
        "chat_id": chat_id, "user_id": user_id, "attempts": 0, "successes": 0, "fails": 0,
        "blocked": 0, "stolen_total": 0, "lost_total": 0, "times_robbed": 0,
        "money_lost_as_victim": 0, "last_robbery_at": None,
    }


async def add_robbery_strike(chat_id: int, user_id: int, limit: int) -> tuple[int, bool]:
    """Увеличивает счётчик поимок на ограблении. Возвращает (новое число страйков,
    попал ли человек под надзор именно этим страйком)."""
    await get_robbery_stats(chat_id, user_id)
    await _execute(
        "UPDATE robbery_stats SET surveillance_strikes = surveillance_strikes + 1 "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT surveillance_strikes, under_surveillance FROM robbery_stats "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    strikes = int(row["surveillance_strikes"]) if row else 0
    already = bool(row["under_surveillance"]) if row else False
    newly_caught = False
    if strikes >= limit and not already:
        await _execute(
            "UPDATE robbery_stats SET under_surveillance = 1 WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id),
        )
        newly_caught = True
    return strikes, newly_caught


async def is_under_surveillance(chat_id: int, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT under_surveillance FROM robbery_stats WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return bool(row and row["under_surveillance"])


async def clear_robbery_surveillance(chat_id: int, user_id: int) -> None:
    await _execute(
        "UPDATE robbery_stats SET under_surveillance = 0, surveillance_strikes = 0 "
        "WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )

async def set_robbery_last_at(chat_id: int, user_id: int, when: datetime) -> None:
    await get_robbery_stats(chat_id, user_id)
    await _execute(
        "UPDATE robbery_stats SET last_robbery_at = %s WHERE chat_id = %s AND user_id = %s",
        (when, chat_id, user_id),
    )


async def apply_robbery_blocked(chat_id: int, robber_id: int, victim_id: int) -> None:
    await get_robbery_stats(chat_id, robber_id)
    await get_robbery_stats(chat_id, victim_id)
    await _execute(
        "UPDATE robbery_stats SET attempts = attempts + 1, blocked = blocked + 1, "
        "last_robbery_at = UTC_TIMESTAMP() WHERE chat_id = %s AND user_id = %s",
        (chat_id, robber_id),
    )


async def apply_robbery_success(chat_id: int, robber_id: int, victim_id: int, amount: int) -> None:
    await get_wallet(chat_id, robber_id)
    await get_wallet(chat_id, victim_id)
    await get_robbery_stats(chat_id, robber_id)
    await get_robbery_stats(chat_id, victim_id)
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await conn.begin()
            try:
                await cur.execute(
                    "UPDATE economy_wallets SET coins = GREATEST(coins - %s, 0) "
                    "WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, victim_id),
                )
                await cur.execute(
                    "UPDATE economy_wallets SET coins = coins + %s WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, robber_id),
                )
                await cur.execute(
                    "UPDATE robbery_stats SET attempts = attempts + 1, successes = successes + 1, "
                    "stolen_total = stolen_total + %s, last_robbery_at = UTC_TIMESTAMP() "
                    "WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, robber_id),
                )
                await cur.execute(
                    "UPDATE robbery_stats SET times_robbed = times_robbed + 1, "
                    "money_lost_as_victim = money_lost_as_victim + %s "
                    "WHERE chat_id = %s AND user_id = %s",
                    (amount, chat_id, victim_id),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise


async def apply_robbery_fail(chat_id: int, robber_id: int, loss_amount: int) -> None:
    await get_wallet(chat_id, robber_id)
    await get_robbery_stats(chat_id, robber_id)
    await _execute(
        "UPDATE economy_wallets SET coins = GREATEST(coins - %s, 0) WHERE chat_id = %s AND user_id = %s",
        (loss_amount, chat_id, robber_id),
    )
    await _execute(
        "UPDATE robbery_stats SET attempts = attempts + 1, fails = fails + 1, "
        "lost_total = lost_total + %s, last_robbery_at = UTC_TIMESTAMP() "
        "WHERE chat_id = %s AND user_id = %s",
        (loss_amount, chat_id, robber_id),
    )


async def list_robbery_top(chat_id: int, limit: int = 10) -> list[dict]:
    return await _fetchall(
        "SELECT user_id, stolen_total, successes, attempts FROM robbery_stats "
        "WHERE chat_id = %s AND stolen_total > 0 ORDER BY stolen_total DESC LIMIT %s",
        (chat_id, limit),
    )


async def pick_random_robbery_victim(chat_id: int, exclude_user_id: int, min_balance: int) -> Optional[dict]:
    return await _fetchone(
        "SELECT cu.user_id, cu.full_name, cu.username, w.coins FROM current_users cu "
        "JOIN economy_wallets w ON w.chat_id = cu.chat_id AND w.user_id = cu.user_id "
        "WHERE cu.chat_id = %s AND cu.user_id != %s AND w.coins >= %s "
        "ORDER BY RAND() LIMIT 1",
        (chat_id, exclude_user_id, min_balance),
    )


async def seed_extra_shop_items(chat_id: int, items: list[tuple[str, str, int, str, str]]) -> int:
    """Дозасев: в отличие от seed_default_shop_items не требует пустого
    магазина, поэтому новые товары появляются и в уже работающих чатах.

    Ровно это и нужно при добавлении товаров в существующего бота:
    seed_default_shop_items() у непустого магазина возвращает 0 и новинки
    не доедут никогда. add_shop_item() сам пропускает уже существующие
    ключи, так что повторные вызовы безвредны.
    """
    count = 0
    for item_key, name, price, description, emoji in items:
        if await add_shop_item(chat_id, item_key, name, price, description, emoji):
            count += 1
    return count


# Старое имя: функция изначально досеивала только предметы для ограблений,
# потом понадобилась всем. Оставлено, чтобы не ломать вызовы на стороне.
seed_robbery_items = seed_extra_shop_items