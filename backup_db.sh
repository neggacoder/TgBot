#!/usr/bin/env bash
#
# Полный дамп MySQL-базы бота (mysqldump) в backups/.
# Не зависит от процесса бота — запускается отдельно через cron, поэтому
# бэкап делается, даже если сам бот упал/перезапускается.
#
# Настройка (один раз):
#   chmod +x backup_db.sh
#   crontab -e
#   0 9 * * * /полный/путь/к/backup_db.sh >> /полный/путь/к/backups/backup.log 2>&1
#
# Источник настроек — тот же .env, что использует db.py (DB_HOST/DB_PORT/
# DB_USER/DB_PASSWORD/DB_NAME), поэтому редактировать этот файл не нужно.

set -euo pipefail

# Папка, где лежит сам скрипт (и, соответственно, .env с проектом) —
# так cron может запускать его из любого рабочего каталога.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# Не делаем `source .env` целиком — файл может содержать строки, невалидные
# как bash (пробелы вокруг "=", списки через запятую и т.п. — например,
# OWNER_IDS= 123 , 456). Вместо этого построчно вытаскиваем только нужные
# переменные через grep, не выполняя остальной файл.
_env_get() {
    local key="$1"
    [[ -f "$ENV_FILE" ]] || { echo ""; return 0; }
    { grep -E "^${key}[[:space:]]*=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2- \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
              -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"; } || true
    return 0
}

DB_HOST="$(_env_get DB_HOST)"; DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="$(_env_get DB_PORT)"; DB_PORT="${DB_PORT:-3306}"
DB_USER="$(_env_get DB_USER)"; DB_USER="${DB_USER:-neongelion}"
DB_PASSWORD="$(_env_get DB_PASSWORD)"; DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="$(_env_get DB_NAME)"; DB_NAME="${DB_NAME:-neongelion}"

BACKUP_DIR="${SCRIPT_DIR}/backups"
# Сколько дней хранить старые бэкапы (0 — не удалять вообще).
RETENTION_DAYS="$(_env_get BACKUP_RETENTION_DAYS)"; RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"
TMP_FILE="${OUT_FILE}.part"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Старт бэкапа ${DB_NAME} -> ${OUT_FILE}"

mysqldump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --password="$DB_PASSWORD" \
    --single-transaction \
    --routines \
    --triggers \
    --default-character-set=utf8mb4 \
    "$DB_NAME" | gzip > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Готово: $(du -h "$OUT_FILE" | cut -f1)"

# Чистка старых бэкапов
if [[ "$RETENTION_DAYS" -gt 0 ]]; then
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Удалены бэкапы старше ${RETENTION_DAYS} дн."
fi
