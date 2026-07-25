# Установка MySQL и запуск бота на Ubuntu

## 1. Установка MySQL Server

```bash
sudo apt update
sudo apt install -y mysql-server
```

Проверить, что служба запущена и добавлена в автозапуск:

```bash
sudo systemctl start mysql
sudo systemctl enable mysql
sudo systemctl status mysql
```

(Необязательно, но рекомендуется) базовая защита установки — задать пароль root, убрать анонимных пользователей и тестовую БД:

```bash
sudo mysql_secure_installation
```

## 2. Создание пользователя и базы данных

Зайдите в MySQL от имени root:

```bash
sudo mysql
```

Внутри консоли MySQL выполните (замените `СЛОЖНЫЙ_ПАРОЛЬ` на свой):

```sql
CREATE USER 'neongelion'@'localhost' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE IF NOT EXISTS neongelion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON neongelion.* TO 'neongelion'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

## 3. Создание таблиц

Из папки с ботом (там, где лежит `schema.sql`):

```bash
mysql -u neongelion -p neongelion < schema.sql
```

(Введёт пароль пользователя `neongelion`, который вы задали выше. Скрипт сам создаёт базу `neongelion`, если её вдруг нет, и все таблицы: `settings`, `admins`, `test_mode_admins`, `request_messages`, `marriages`, `nicknames`, `logs`.)

Проверить, что таблицы создались:

```bash
mysql -u neongelion -p -e "USE neongelion; SHOW TABLES;"
```

## 4. Python-зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Если ставите без venv — добавляйте `--break-system-packages`:

```bash
pip install -r requirements.txt --break-system-packages
```

## 5. Настройка `.env`

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
nano .env
```

```env
BOT_TOKEN=токен_вашего_бота
OWNER_IDS=123456789,987654321

DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=neongelion
DB_PASSWORD=СЛОЖНЫЙ_ПАРОЛЬ
DB_NAME=neongelion
```

## 6. Запуск бота

```bash
python3 bot.py
```

Для постоянной работы в фоне рекомендуется systemd-сервис или `screen`/`tmux`:

```bash
sudo apt install -y tmux
tmux new -s neongelion
python3 bot.py
# Ctrl+B, затем D — чтобы отсоединиться от сессии, не останавливая бота
```

## 7. (Опционально) резервное копирование БД

```bash
mysqldump -u neongelion -p neongelion > backup_$(date +%F).sql
```

## 8. Обновление БД на уже работающем боте

Если бот уже стоит и просто обновился код (новая версия `bot.py`), таблицы
нужно доподнать — накатите миграции по порядку (безопасно повторять, ничего
не удаляют):

```bash
mysql -u neongelion -p neongelion < migration.sql
mysql -u neongelion -p neongelion < migration_2_permissions.sql
mysql -u neongelion -p neongelion < migration_3_warns_rules.sql
mysql -u neongelion -p neongelion < migration_4_complaints.sql
mysql -u neongelion -p neongelion < migration_5_rewards.sql
mysql -u neongelion -p neongelion < migration_6_profile_card.sql
mysql -u neongelion -p neongelion < migration_7_complaint_picker.sql
mysql -u neongelion -p neongelion < migration_8_relationships.sql
```

- `migration.sql` — уровни админов (1-3) + таблица `bot_data` для
  «запомни/вспомни/забудь/хранилище».
- `migration_2_permissions.sql` — таблица `command_permissions` для «дерева
  команд» (слово «команды» и настройка «право ключ уровень»).
- `migration_3_warns_rules.sql`, `migration_4_complaints.sql`,
  `migration_5_rewards.sql` — варны/правила, жалобы, награды.
- `migration_6_profile_card.sql` — таблица `profile_cards` для анкеты
  (звание, девиз, гражданство), используется командой `профиль`.
- `migration_7_complaint_picker.sql` — таблица `known_users` и столбец
  `settings.complaint_chat_id` для выбора цели жалобы из списка (см. README).
- `migration_8_relationships.sql` — таблицы `relationships` и
  `relationship_requests` для модуля «Отношения» (команды `отн`, `+отн`,
  `-отн`, `статус отн`, `отн действия`, `отн топ` — см. README). Полностью
  отдельно от «Браков», ничего в существующих таблицах не меняет.

После миграции просто перезапустите бота — новые таблицы подхватятся сами.
