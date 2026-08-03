#!/usr/bin/env bash
# Полный дамп базы ПЕРЕД любыми изменениями схемы или удалением строк.
# Запускать на сервере: bash tools/backup_db.sh
#
# Без этого дампа шаг DROP COLUMN необратим: колонку можно вернуть, а данные,
# которые в ней были, — нет.
set -euo pipefail
: "${DB_NAME:=neongelion}"
: "${DB_USER:=neongelion}"
имя="db_backup_$(date +%Y%m%d_%H%M%S).sql"
mysqldump --single-transaction --routines --events \
  -u "$DB_USER" ${DB_PASSWORD:+-p"$DB_PASSWORD"} "$DB_NAME" > "$имя"
echo "дамп готов: $имя ($(du -h "$имя" | cut -f1))"
