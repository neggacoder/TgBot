-- ============================================================================
-- Миграция: система уровней администраторов (1-3) + произвольное хранилище
-- Выполните этот файл на существующей БД один раз:
--   mysql -u <user> -p <db_name> < migration.sql
-- ============================================================================

-- 1. Добавляем колонку level в таблицу admins (если её ещё нет).
--    ВНИМАНИЕ: Колонка уже существует в базе данных, поэтому ALTER закомментирован,
--    чтобы избежать ошибки "Duplicate column name".
--
-- ALTER TABLE admins
--     ADD COLUMN level TINYINT NOT NULL DEFAULT 1 AFTER user_id;

-- На всякий случай убедимся, что у всех существующих админов проставлен
-- валидный уровень (по умолчанию — 1, «Модератор»). Если хотите, чтобы все
-- ваши текущие админы стали 3 уровня («Старший администратор»), раскомментируйте:
-- UPDATE admins SET level = 3;

-- 2. Таблица для произвольных данных (команды /setval, /getval, /delval, /listval).
CREATE TABLE IF NOT EXISTS bot_data (
    data_key   VARCHAR(191) NOT NULL PRIMARY KEY,
    data_value TEXT NULL,
    updated_by BIGINT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================================
-- Миграция: модуль «Созывы» (позывной-эмодзи, анрег). Выполните на
-- существующей БД один раз:
--   mysql -u <user> -p <db_name> < migration.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS call_signs (
    chat_id    BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    emoji      VARCHAR(16) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS call_unregs (
    chat_id    BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    message    VARCHAR(256) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
