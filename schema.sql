-- ============================================================================
-- Нормализованная схема базы данных для Telegram-бота (neongelion)
-- Собраны все миграции, удалены дубликаты и исправлен синтаксис.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS neongelion
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE neongelion;

-- ----------------------------------------------------------------------------
-- 1. Настройки бота
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    id                      TINYINT UNSIGNED NOT NULL PRIMARY KEY DEFAULT 1,
    notify_chat_id          BIGINT NULL,
    notify_topic_id         BIGINT NULL,
    invite_link             VARCHAR(512) NULL,
    welcome_message         TEXT NULL,
    link_message_template   TEXT NULL,
    reject_message          TEXT NULL,
    complaint_chat_id       BIGINT NULL,
    CONSTRAINT chk_settings_single_row CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO settings (id) VALUES (1);

-- ----------------------------------------------------------------------------
-- 2. Известные участники (логирование активности)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS known_users (
    chat_id       BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    full_name     VARCHAR(255) NOT NULL,
    username      VARCHAR(64) NULL,
    last_seen_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id),
    INDEX idx_known_users_seen (chat_id, last_seen_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 3. Администраторы (включая изменения из migration.sql)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    user_id     BIGINT NOT NULL PRIMARY KEY,
    level       TINYINT NOT NULL DEFAULT 1,
    added_by    BIGINT NULL,
    added_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 4. Тест-режим администраторов
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_mode_admins (
    user_id     BIGINT NOT NULL PRIMARY KEY,
    enabled_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 5. Заявки на вход
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS request_messages (
    message_id  BIGINT NOT NULL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    is_anchor   TINYINT(1) NOT NULL DEFAULT 0,
    status      ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by  BIGINT NULL,
    decided_at  DATETIME NULL,
    INDEX idx_request_user (user_id),
    INDEX idx_request_anchor (user_id, is_anchor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 6. Браки
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marriages (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    user1_id    BIGINT NOT NULL,
    user2_id    BIGINT NOT NULL,
    married_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_pair (chat_id, user1_id, user2_id),
    INDEX idx_marriage_user1 (chat_id, user1_id),
    INDEX idx_marriage_user2 (chat_id, user2_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 7. Отношения и очки близости
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationships (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id         BIGINT NOT NULL,
    user1_id        BIGINT NOT NULL,
    user2_id        BIGINT NOT NULL,
    points          BIGINT NOT NULL DEFAULT 0,
    level           TINYINT UNSIGNED NOT NULL DEFAULT 0,
    started_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_action_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_relationship_pair (chat_id, user1_id, user2_id),
    INDEX idx_relationship_user1 (chat_id, user1_id),
    INDEX idx_relationship_user2 (chat_id, user2_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 8. Запросы на отношения
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationship_requests (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id       BIGINT NOT NULL,
    from_user_id  BIGINT NOT NULL,
    to_user_id    BIGINT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_relreq_to (chat_id, to_user_id, created_at DESC),
    INDEX idx_relreq_from (chat_id, from_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 9. Локальные никнеймы
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nicknames (
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    nickname    VARCHAR(64) NOT NULL,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 10. Анкеты / Профили пользователей (соединены все поля)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profile_cards (
    chat_id         BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    title           VARCHAR(30) NULL,
    motto           VARCHAR(100) NULL,
    is_citizen      TINYINT(1) NOT NULL DEFAULT 0,
    gender          ENUM('м','ж','др') NULL,
    city            VARCHAR(64) NULL,
    about_text      VARCHAR(1000) NULL,
    anketa_visible  TINYINT(1) NOT NULL DEFAULT 1,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 11. Муты
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mutes (
    chat_id      BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    muted_by     BIGINT NOT NULL,
    muted_until  DATETIME NULL,
    reason       VARCHAR(255) NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id),
    INDEX idx_mutes_until (muted_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 12. Баны
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bans (
    chat_id      BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    banned_by    BIGINT NOT NULL,
    reason       VARCHAR(255) NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 13. Предупреждения (Варны)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warns (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    warned_by   BIGINT NOT NULL,
    reason      VARCHAR(255) NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_warns_user (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 14. Правила чатов
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_rules (
    chat_id     BIGINT NOT NULL PRIMARY KEY,
    rules_text  TEXT NOT NULL,
    updated_by  BIGINT NULL,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 15. Жалобы
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS complaints (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    target_id    BIGINT NOT NULL,
    reporter_id  BIGINT NOT NULL,
    anonymous    TINYINT(1) NOT NULL DEFAULT 0,
    reason       TEXT NOT NULL,
    status       ENUM('pending','accepted','declined') NOT NULL DEFAULT 'pending',
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by   BIGINT NULL,
    decided_at   DATETIME NULL,
    INDEX idx_complaints_target (target_id, status),
    INDEX idx_complaints_reporter (reporter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 16. Статистика сообщений
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_stats (
    chat_id          BIGINT NOT NULL,
    user_id          BIGINT NOT NULL,
    message_count    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    first_seen_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id),
    INDEX idx_stats_leaderboard (chat_id, message_count DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 17. Персональные ответы триггеры
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS custom_responses (
    user_id     BIGINT NOT NULL PRIMARY KEY,
    message     TEXT NOT NULL,
    added_by    BIGINT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 18. Права доступа команд
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS command_permissions (
    command_key VARCHAR(64) NOT NULL PRIMARY KEY,
    min_level   TINYINT NOT NULL,
    updated_by  BIGINT NULL,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 19. Системные логи бота
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type  VARCHAR(64) NOT NULL,
    chat_id     BIGINT NULL,
    actor_id    BIGINT NULL,
    target_id   BIGINT NULL,
    details     TEXT NULL,
    INDEX idx_logs_created (created_at),
    INDEX idx_logs_type (event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 20. Система наград (медали)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rewards (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    chat_id    BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    degree     TINYINT UNSIGNED NOT NULL,
    reason     VARCHAR(500) NULL,
    awarded_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rewards_chat_user (chat_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reward_degree_levels (
    degree     TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    min_level  TINYINT NOT NULL,
    updated_by BIGINT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 21. Произвольные данные бота (из файла migration.sql)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bot_data (
    data_key   VARCHAR(191) NOT NULL PRIMARY KEY,
    data_value TEXT NULL,
    updated_by BIGINT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 22. Созывы (модуль «Зазывала»): позывной-эмодзи и анрег (временный отказ
--     участника от упоминаний в созывах текущего чата, до его следующего
--     сообщения в чат).
-- ----------------------------------------------------------------------------
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
