# «Предложить действие» — предложения между участниками с Да/Нет

Дата: 2026-07-23
Статус: одобрено пользователем в чате, ожидает записи в план реализации.

## Контекст

Второй независимый подпроект из более крупного запроса (после «Награды —
пороги по ролям», см. `2026-07-23-reward-role-thresholds-design.md`).
Следующий в очереди — привязка админ-аккаунта к тг-аккаунту (отдельный спек).

Один участник чата предлагает другому что-то сделать («предложить убраться»,
«предложить полить цветы»), бот показывает адресату сообщение с инлайн-
кнопками Да/Нет; при согласии/отказе сообщение меняется на соответствующий
текст. Список действий (7 штук по умолчанию), их синонимы-триггеры и текст
всех трёх стадий редактируются владельцем и админами через бота и через сайт.

Похожие механики уже есть в коде, из них и собирается дизайн:

- **РП-действия** (`bot.py:6899-7004`, `db.py:3117-3327`) — уже дают почти
  всё нужное для «конфигурации»: таблицы `rp_actions`
  (`id, action_key, phrase, sort_order, is_active, created_at`) +
  `rp_action_synonyms` (`synonym PK, action_key`), несколько вариантов фразы
  на действие, `random.choice(RP_ACTIONS[action]).format(actor=, target=)`
  (`bot.py:6994`), многословные синонимы матчатся от самых длинных к самым
  коротким (`_match_rp_action_prefix`, `bot.py:6899-6914`), правка через
  бота в личке (`rp_admin_command`/FSM-меню, `bot.py:3076-3410`) и через сайт
  (обобщённый `ACTION_SETS`, `webpanel/app.py:1169-1341`).
- **`rel2_requests`** (`relationships_v2.py:3058-3203`, `db.py:3552-3561,
  3920`) — лёгкая таблица «ожидания ответа» (`id, chat_id, from_user_id,
  to_user_id, created_at`), новый запрос от того же отправителя
  перезаписывает старый (DELETE+INSERT), проверка адресата —
  `callback.from_user.id != to_user_id` → alert «это не вам»
  (`relationships_v2.py:3145,3172`).
- **`resolve_command_target`** (`bot.py:7884-…`) — уже умеет доставать цель
  команды из reply ИЛИ из @username/text_mention/голого ID в самом тексте
  (`trigger_words` — сколько слов в начале составляют сам триггер); именно
  так реализовано «и то, и другое» для адресата.
- **Live-reload между ботом и панелью** (разные процессы, общая БД):
  `_signal_action_reload()` (`webpanel/app.py:1206-1209`) пишет флаг в
  `bot_data`, `panel_action_reload_loop` (`bot.py:3425-3466`) раз в
  `PANEL_RELOAD_INTERVAL=10` сек его проверяет и перечитывает кэши.
- **`COMMAND_REGISTRY`** (`bot.py:762+`) — `rp_manage` требует уровень
  `LEVEL_SENIOR` по умолчанию (`bot.py:831`), точный уровень владелец меняет
  на сайте во вкладке «Дерево команд» — тот же механизм закроет требование
  «владелец+админы, кто именно — управляется через ДК».

Тяжёлая state-machine дуэлей (`bot.py:8748-9265`, `db.py:5037-5145`,
статусы `pending/active`, ходы, `aim`) сюда не подходит и не переиспользуется
— после согласия никакой многоходовой игры нет, только один обмен
сообщениями.

## Требования (согласовано в чате)

- Адресат указывается **reply ИЛИ @username** (оба способа).
- Действие живёт только в группах (как РП-действия), не в личке.
- На каждое действие — **4 настраиваемых текста**: триггер+синонимы,
  предложение, согласие, отказ. Все три «текстовых» (предложение/согласие/
  отказ) — по **5 вариантов фразы**, бот берёт случайный при показе.
- Список действий — **глобальный** для всего бота (не per-chat), как
  РП-действия и пороги наград.
- Добавление/удаление/вкл-выкл действия — и через бота (текстовые команды в
  личке), и через сайт; доступ регулируется через `COMMAND_REGISTRY` +
  вкладку «Дерево команд» (не отдельный ad-hoc список ролей).
- Кулдаун и таймаут — **свои у каждого действия**, оба настраиваются на
  сайте (числом секунд).
- Дефолтный набор действий (7 штук, шутливые/неожиданные — см. «Контент»).
- Задокументировать в `help_texts.py` и на сайте.

## Дизайн

### 1. Схема БД (`db.py`, новые `ensure_*_table`, вызываются в `main()`
рядом с `ensure_rp_actions_table()` и т.п.)

```sql
CREATE TABLE IF NOT EXISTS propose_actions (
    action_key VARCHAR(64) NOT NULL PRIMARY KEY,
    cooldown_seconds INT NOT NULL DEFAULT 300,
    timeout_seconds INT NOT NULL DEFAULT 120,
    is_active BOOL NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS propose_action_synonyms (
    synonym VARCHAR(64) NOT NULL PRIMARY KEY,
    action_key VARCHAR(64) NOT NULL,
    INDEX idx_propose_action_synonyms_key (action_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS propose_phrases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    action_key VARCHAR(64) NOT NULL,
    kind ENUM('propose','agree','decline') NOT NULL,
    phrase VARCHAR(512) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOL NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_propose_phrases_key (action_key, kind, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS propose_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    action_key VARCHAR(64) NOT NULL,
    from_user_id BIGINT NOT NULL,
    to_user_id BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_propose_requests_pair (chat_id, action_key, from_user_id, to_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS propose_cooldowns (
    chat_id BIGINT NOT NULL,
    action_key VARCHAR(64) NOT NULL,
    from_user_id BIGINT NOT NULL,
    to_user_id BIGINT NOT NULL,
    last_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, action_key, from_user_id, to_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`propose_actions`/`propose_action_synonyms`/`propose_phrases` — без
`chat_id`, глобальная конфигурация (как `rp_actions`). `propose_requests`/
`propose_cooldowns` — рантайм-состояние конкретного чата/пары, с `chat_id`
(как игровые данные дуэлей/`rel2_requests`). Флаг «дефолтное действие»
(`is_builtin` и т.п.) сознательно не заводим — редактируется и удаляется
любое действие одинаково, различие есть только в момент однократного
сидирования пустой таблицы.

Сидирование дефолтов — `seed_propose_actions_if_empty()` /
`seed_propose_action_synonyms_if_empty()` / `seed_propose_phrases_if_empty()`
по образцу `seed_rp_actions_if_empty` (`db.py:3155-3184`), вызывается один
раз в `main()`, только если таблицы пустые.

CRUD в `db.py` — по прямой аналогии с `rp_actions`:
`list_propose_actions_rows()` (для панели, все строки + `is_active`),
`add_propose_phrase(action_key, kind, phrase)`,
`update_propose_phrase(id, phrase)`, `delete_propose_phrase(id)`,
`set_propose_action_active(action_key, is_active)`,
`list_propose_action_synonyms()`, `add_propose_action_synonym`,
`delete_propose_action_synonym`, плюс новые (не имеющие аналога в rp_actions):
`set_propose_action_settings(action_key, cooldown_seconds, timeout_seconds)`,
`get_propose_action_settings_map()` (весь `propose_actions` в dict для кэша),
`create_or_replace_propose_request(...)` (DELETE+INSERT как
`create_rel2_request`), `get_propose_request(id)`, `delete_propose_request(id)`,
`list_expired_propose_requests(now)` (для фонового лупа очистки),
`check_and_touch_propose_cooldown(chat_id, action_key, from_id, to_id,
cooldown_seconds)` (читает `last_at`, если кулдаун не прошёл — возвращает
оставшееся время и НЕ трогает строку; если прошёл — `INSERT ... ON DUPLICATE
KEY UPDATE last_at=NOW()` и возвращает `None`).

### 2. Кэши и матчинг триггера (`bot.py`)

Живые dict-кэши как `RP_ACTIONS`/`RP_ACTION_SYNONYMS`:
`PROPOSE_ACTIONS` (`action_key -> {"propose": [...], "agree": [...],
"decline": [...], "cooldown_seconds": int, "timeout_seconds": int}`),
`PROPOSE_ACTION_SYNONYMS` (`synonym -> action_key`), загружаются в
`load_caches()` и перечитываются в `refresh_propose_caches()`.

Матчинг — `_match_propose_action_prefix(text)`, копия
`_match_rp_action_prefix` (`bot.py:6899-6914`), но проверяет префикс
`"предложить "` (регистронезависимо) перед сопоставлением остатка текста с
`PROPOSE_ACTION_SYNONYMS`-ключами от самых длинных к самым коротким —
поддерживает многословные синонимы («полить цветы», «дуэль на щелбанчики»).
Возвращает `(action_key, n)`, где `n` = 1 (слово «предложить») + число слов
в совпавшем синониме — это и есть `trigger_words` для
`resolve_command_target(message, trigger_words=n, text=first_line)`
(`bot.py:7884`), с тем же паттерном фолбэка на `message.reply_to_message`,
что уже используется у РП-действий (`bot.py:6971-6973`) — покрывает
«и reply, и @username».

### 3. Хендлер предложения (`bot.py`, группы/супергруппы, не личка)

```
handle_propose_command(message):
    action_key, n = _match_propose_action_prefix(message.text)
    if action_key is None or action_key not in PROPOSE_ACTIONS: raise SkipHandler
    if not PROPOSE_ACTIONS[action_key]["is_active"]: raise SkipHandler  # тихо, как выключенные RP
    target = resolve_command_target(...) или reply_to_message.from_user
    if target is None: подсказка «ответьте на сообщение или укажите @username»
    if target.id == message.from_user.id: «нельзя предложить самому себе»
    if target — бот: «боту не предложишь»
    остаток = check_and_touch_propose_cooldown(...)
    if остаток: await message.reply(f"Подождите ещё {остаток}с — не так часто ⏳")
    propose_phrase = random.choice(PROPOSE_ACTIONS[action_key]["propose"]).format(actor=, target=)
    отправить сообщение с InlineKeyboardMarkup(Да -> propose_yes:{id}, Нет -> propose_no:{id})
    id = create_or_replace_propose_request(chat_id, message_id_отправленного, action_key, from_id, to_id)
```

Обработчик callback (`propose_yes:{id}`/`propose_no:{id}`):
- `req = get_propose_request(id)`; если `None` — «Предложение больше не
  активно» (протухло/уже отвечено/перезаписано новым), убрать клавиатуру.
- `callback.from_user.id != req["to_user_id"]` → `callback.answer("Это
  предложение адресовано не вам", show_alert=True)` (как в браке/rel2).
- Если `now - req["created_at"] > timeout_seconds` → тот же путь, что и
  фоновая просрочка (см. п.4): отредактировать на «⌛ Предложение
  устарело», удалить строку.
- Иначе — `random.choice(PROPOSE_ACTIONS[action_key]["agree"|"decline"])`,
  `edit_text` исходного сообщения (без клавиатуры), `delete_propose_request`,
  `db.add_log("propose_" + action_key, ...)`.

Текстовый фолбэк «да»/«нет» без нажатия кнопки (как есть у `rel2`) в рамках
этой задачи не делаем — не запрашивалось; кнопки остаются единственным
способом ответить.

### 4. Фоновая просрочка («кнопки гаснут сами»)

Отдельный `asyncio` таск `propose_expiry_loop()`, стартует в `main()` рядом
с `panel_action_reload_loop` (`bot.py:21161`), раз в 30 сек:
`list_expired_propose_requests(now)` (join с `propose_actions` по
`timeout_seconds` на стороне SQL) → для каждой строки редактирует её
сообщение (`chat_id`+`message_id`, оба уже сохранены в `propose_requests`)
на исходный текст + «\n\n⌛ Предложение устарело», без клавиатуры, и
удаляет строку. Ошибки редактирования (сообщение удалено пользователем)
просто логируются и пропускаются — не блокируют очистку остальных строк.

### 5. Управление через бота (личка, по образцу `rp_admin_command`,
`bot.py:7065-7196`, доступ — `_propose_manage_allowed`, зеркало
`_rp_manage_allowed`)

Текстовые команды (одна функция-роутер `propose_admin_command`,
аналогично `rp_admin_command`):
- `предложения список` — все action_key + вкл/выкл + число фраз каждого
  вида + кулдаун/таймаут.
- `предложения добавить <ключ> | <фраза-предложения>` — создаёт действие
  (если ключа не было) и первую фразу вида `propose`.
- `предложения фраза <ключ> <propose|agree|decline> | <фраза>` — добавить
  ещё вариант.
- `предложения синоним <синоним> | <ключ>`.
- `предложения удалить фраза <id>` / `предложения удалить синоним <синоним>`.
- `предложения вкл <ключ>` / `предложения выкл <ключ>`.
- `предложения кулдаун <ключ> <секунды>` / `предложения таймаут <ключ>
  <секунды>`.

Каждая мутирующая команда завершается `refresh_propose_caches()` (свой
процесс — читает из тех же переменных, что уже обновила).
Справка — `PROPOSE_ADMIN_HELP`, добавляется в общий список команд личных
сообщений так же, как `RP_ADMIN_HELP`.

FSM-меню на ReplyKeyboard (как `_show_rp_menu`/`_show_rp_action_menu`) —
даём implementer'у на усмотрение в плане: явно не обязательно (пользователь
просил именно «настройку через бота», текстовых команд для этого достаточно;
меню — опциональное удобство, не блокер).

### 6. Управление через сайт (`webpanel/`)

Не переиспользуем `ACTION_SETS` буквально как есть (там одна фраза на
строку, здесь три вида фраз + кулдаун/таймаут — другая форма данных), но
берём тот же дух: один обобщённый набор эндпоинтов, права и live-reload
signal.

- `GET /api/propose-actions` (`Depends(auth.require_user)`) — список
  действий, каждый: `{key, active, cooldown_seconds, timeout_seconds,
  synonyms: [...], phrases: {propose: [...], agree: [...], decline: [...]}}`
  (каждая фраза — `{id, phrase}`), `can_edit` по роли (`owner`/`admin` —
  оба уровня допуска регулируются через `command_level_overrides` для ключа
  `propose_manage`, а не жёстко зашиты в панели, см. п.7).
- `POST /api/propose-actions/phrases` — тело `{action_key, kind, phrase}`
  (если ключа не было — создаёт действие с дефолтными
  cooldown/timeout=300/120).
- `PUT /api/propose-actions/phrases/{id}` — тело `{phrase}`.
- `DELETE /api/propose-actions/phrases/{id}`.
- `POST /api/propose-actions/synonyms` — `{synonym, action_key}`.
- `DELETE /api/propose-actions/synonyms/{synonym}`.
- `POST /api/propose-actions/{key}/active` — `{active: bool}`.
- `POST /api/propose-actions/{key}/settings` — `{cooldown_seconds,
  timeout_seconds}` (валидация: положительные целые, разумный верхний
  предел, например 86400).

Все мутирующие эндпоинты — `Depends(auth.require_user)` + проверка `has
уровень >= required_level("propose_manage")` (не жёстко `require_owner`,
т.к. по требованию доступ — «владелец+админы, кто именно решает владелец
через Дерево команд»), плюс `auth.verify_csrf`, `db.add_log(...)`,
`await _signal_action_reload()`.

**Bot (`bot.py`)** — в `panel_action_reload_loop` добавить рядом с блоком
RP-кэшей: `await refresh_propose_caches()`.

**Frontend** — карточка «🎭 Предложения» рядом с существующим экраном
управления РП-действиями (тот же UI-паттерн: список действий, раскрытие на
клик → 3 колонки/группы фраз propose/agree/decline с кнопками добавить/
удалить, список синонимов, два числовых поля кулдаун/таймаут, тумблер
вкл/выкл).

### 7. Права (`COMMAND_REGISTRY`, `bot.py:762+`)

Новая запись:
```python
"propose_manage": {"phrase": "предложения (в личке боту, текстом) / карточка «Предложения» в админ-панели", "category": "РП", "level": LEVEL_SENIOR},
```
Точный требуемый уровень (по умолчанию `LEVEL_SENIOR`, как `rp_manage`)
владелец может изменить на сайте во вкладке «Дерево команд» — это и есть
ответ на «кто именно управляется через ДК от лица владельца», без
отдельного специального флага в панели.

### 8. Контент по умолчанию — 7 действий, 5 вариантов на каждый из 3 текстов,
2-3 синонима-триггера на действие

1. **`romashka`** — «погадать на ромашке» (синонимы: погадать на ромашке,
   ромашка, погадать на любовь)
2. **`schelbany`** — «дуэль на щелбанчики» (синонимы: дуэль на щелбанчики,
   щелбаны, щелбанчики)
3. **`morozhenoe`** — «забег до ларька за мороженым» (синонимы: забег за
   мороженым, сбегать за мороженым, мороженое)
4. **`karaoke`** — «спеть дуэтом караоке» (синонимы: караоке, спеть дуэтом,
   спеть вместе)
5. **`klad`** — «искать клад во дворе» (синонимы: искать клад, клад,
   найти сокровище)
6. **`podushki`** — «битва подушками» (синонимы: битва подушками,
   подушками подраться, подушечный бой)
7. **`zhelanie`** — «угадать желание друг друга» (синонимы: угадать
   желание, загадать желание, желание угадать)

Точные тексты (по 5 штук на propose/agree/decline на каждое из 7 действий,
итого 105 фраз) — implementer пишет сам при реализации задачи «сидирование
дефолтов», в том же несерьёзном/нескучном тоне, что и черновики выше;
здесь не фиксируем дословно, чтобы не раздувать спеку — фиксируем только
ключи, синонимы и общий тон.

### 9. Документация

- `help_texts.py` — новый подраздел (в разделе с РП/дуэлями, стиль как
  «⚔️ Дуэли»): «🎲 Предложения — предложите другому участнику сделать
  что-то весёлое: «предложить <действие>» (ответом на сообщение или с
  @username), список действий и их тексты можно посмотреть и поменять на
  сайте (для этого нужен уровень «Старший администратор» или то, что
  назначил владелец)».
- Сайт — тот же экран, что и карточка управления (см. п.6), достаточно как
  «документация» — отдельной статической страницы не требуется.

## Тесты

Новый `tg-bot/tests/test_propose_actions.py` (бот-логика, без сети —
мокать `db`, как остальные тесты бота) и
`tg-bot/tests/test_panel_propose_actions.py` (панель, `TestClient` как у
`test_panel_reward_levels.py`):
- Матчинг многословных синонимов, самый длинный выигрывает.
- Адресат по reply и по @username — оба пути.
- Самому себе / боту — отказ без создания запроса.
- Кулдаун блокирует повторное предложение той же паре раньше времени.
- Callback от не-адресата → alert, состояние не меняется.
- Согласие/отказ — редактирует сообщение, удаляет `propose_requests`,
  пишет лог.
- Просроченный запрос (протухший `created_at`) — не принимается кликом,
  редактируется на «устарело».
- Панель: `GET /api/propose-actions` — доступность по роли; мутирующие
  эндпоинты — 403 у роли ниже `propose_manage`; кулдаун/таймаут сохраняются
  и попадают в кэш бота после `_signal_action_reload`.

## Не в скобо (сознательно не делаем)

- Текстовый ответ «да»/«нет» без нажатия кнопки (в отличие от `rel2`) — не
  запрашивалось, кнопки — единственный способ ответить.
- Per-chat переопределение набора действий — список действий глобальный,
  как и решено в чате.
- FSM-меню на ReplyKeyboard для управления через бота — опционально,
  implementer решает в плане, достаточно текстовых команд.
- Ограничение действия на конкретные чаты/группы (whitelist) — не
  запрашивалось.

## Открытые вопросы

Нет — дизайн подтверждён пользователем в чате 2026-07-23.
