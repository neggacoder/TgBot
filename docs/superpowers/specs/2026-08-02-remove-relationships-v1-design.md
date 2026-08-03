# Удаление системы отношений v1

Дата: 2026-08-02. Статус: утверждено владельцем.

## Зачем

Владелец: «мне не нравится, что для `.отн` и `отн` используются разные фото;
надо удалить relationships v1 и оставить одну систему».

Разбор показал, что жалоба состоит из двух разных вещей, и лечатся они
по-разному.

**Про фото.** `.отн обнять` и `отн обнять` — это уже один и тот же код: точка
срезается перед разбором команды (`relationships_v2._strip_dot_prefix`), обе
формы идут в `cmd_rel2_word`. Разными картинки выглядят потому, что
`rp_photos.pick_photo_url` выбирает файл из папки жеста **случайно** при
каждом вызове. Двух наборов фотографий нет: бот читает единственное
хранилище `webpanel/static/rp_media` и отдаёт ссылку на публичный эндпоинт
панели. Менять здесь нечего — только закрепить это тестом, чтобы формы не
разъехались в будущем.

**Про две системы.** Их действительно две, но не те, что подозревались:

| | «обнять @юзер» | «отн обнять» / «.отн обнять» |
|---|---|---|
| Таблица | `rp_actions` | `rel2_gestures` |
| Раздел на сайте | «РП-действия» | «Действия → отн-жесты» |
| Фото | нет | есть |
| На ком работает | на всех | только на партнёре |

Владелец подтвердил: **так и должно быть**. «обнять» — дружеское РП-действие,
к модулю отношений отношения не имеет и остаётся как есть.

А вот старый **модуль отношений v1** (`relationships`,
`relationship_requests`, уровни близости, очки за действия) — мёртвый груз:
его команды давно обслуживает v2, ни одна его функция из `bot.py` не
вызывается по делу, панель его не редактирует. Он и удаляется.

## Что удаляется

### db.py

Функции старого модуля (никем не вызываются, кроме соседей внутри `db.py`):

* пары и заявки: `get_relationship`, `list_relationships`,
  `create_relationship`, `delete_relationship`, `set_relationship_progress`,
  `create_relationship_request`, `get_latest_relationship_request`,
  `delete_relationship_request`, `clear_relationship_requests_for`;
* уровни, очки и фразы: `ensure_relationship_levels_table`,
  `ensure_relationship_actions_table`,
  `ensure_relationship_action_phrases_table`,
  `seed_relationship_levels_if_empty`, `seed_relationship_actions_if_empty`,
  `seed_relationship_action_phrases_if_empty`, `list_relationship_levels`,
  `list_relationship_levels_rows`, `upsert_relationship_level`,
  `delete_relationship_level`, `list_relationship_actions`,
  `list_relationship_actions_rows`, `upsert_relationship_action`,
  `delete_relationship_action`, `list_relationship_action_phrases`,
  `list_relationship_action_phrases_rows`, `add_relationship_action_phrase`,
  `update_relationship_action_phrase`, `delete_relationship_action_phrase`.

### bot.py

* вызовы `ensure_relationship_*` и `seed_relationship_*` при старте;
* строки загрузки кэшей v1 в `load_caches`;
* кэши и константы: `RELATIONSHIP_LEVELS`, `_RELATIONSHIP_LEVELS_DEFAULT`,
  `REL_ACTION_POINTS`, `_REL_ACTION_POINTS_DEFAULT`,
  `REL_ONLY_PARTNER_ACTIONS`, `_REL_ONLY_PARTNER_ACTIONS_DEFAULT`,
  `_REL_PARTNER_ONLY_KEYS_DEFAULT`;
* помощники уровней близости: `relationship_level_index`,
  `relationship_level_name`, `relationship_next_level_info`,
  `relationship_status_lines`;
* ключи реестра команд `relationship_propose`, `relationship_accept`,
  `relationship_break`, `relationship_status`, `relationship_actions`,
  `relationship_top` — их фразы переезжают на ключи `rel2_*`, чтобы справка,
  права и автоочистка не потеряли команды, которые продолжают работать;
* ключ реестра `couple` («.отн») и обработчик `cmd_couple`: он **затенён**
  роутером v2 и не срабатывает уже сейчас. «.отн» остаётся рабочей формой v2.

### schema.sql

Таблицы `relationships` и `relationship_requests` убираются из эталонной
схемы: на новой установке они больше не нужны.

## Что НЕ трогается

* **`rp_actions` и всё дружеское РП** — «обнять @юзер» работает на всех, как
  и работало. Это отдельная вселенная, к отношениям отношения не имеет.
* **v2 целиком** — «отн обнять» только на партнёре, всё верно.
* **Хранилище фото.** Бот читает `webpanel/static/rp_media` и отдаёт ссылку
  на эндпоинт панели. Корневой `rp_media/` не читает никто; владелец перенёс
  оттуда файлы сам, папку не трогаем.
* **`relationship_undo`** — несмотря на имя, это общее хранилище «отмены
  расставания» и его используют И v2, И браки (`cb_rel2_undo`,
  `cb_marriage_undo`). Остаётся.
* **Таблицы v1 в работающей базе не дропаются.** В них лежит история старых
  пар. Код уходит, данные остаются; отдельный DROP — по запросу владельца.
* **`LOG_LABELS`** для событий `relationship_created/declined/broken`: старые
  строки журнала должны продолжать читаться.

## Переименование

`resolve_relationship_target` остаётся — его используют команды кланов
(«+зам», «кик из клана»), к отношениям он давно не привязан. Переименовать в
`resolve_reply_or_mention_target`, чтобы в живом коде не осталось названий
удалённого модуля. Три места: определение и два вызова.

## Проверки

Тесты (новый файл `tests/test_relationships_single_system.py`):

1. `.отн X` и `отн X` — одна и та же команда: обе формы забирает
   `cmd_rel2_word`, для набора жестов результат разбора совпадает.
2. Фото у жестов берутся только из хранилища сайта (`rp_photos.MEDIA_ROOT`), и
   другого источника в коде нет.
3. «обнять» и «отн обнять» — разные ветки, и это осознанно: первую берёт
   `handle_rp_action`, вторую `cmd_rel2_word`.
4. v1 не воскресает: в `db.py` не осталось функций старого модуля, а в
   `bot.py` — обращений к ним и к его таблицам.
5. Все команды реестра по-прежнему кем-то обслуживаются (проверка на всём
   реестре, чтобы перенос фраз с ключей v1 на `rel2_*` ничего не потерял).

Прогон: полный `pytest`. Базовая линия — 1 упавший тест
(`test_command_cleanup::test_каждый_набор_триггеров_узнаётся_очисткой`,
падает и до правок).

## Риски

* **Потеря команды при переносе фраз.** Ключи v1 держат фразы «отн запрос»,
  «+отн», «-отн», «отн я», «отн история», «отн список». Если просто удалить
  ключи, команды пропадут из справки и потеряют настройку прав, продолжая
  работать, — это хуже, чем было. Поэтому фразы переезжают на ключи v2, а
  тест на реестр это стережёт.
* **Затенённый `cmd_couple`.** Удаляется вместе с ключом; «.отн» продолжает
  работать через v2 — это проверяется тестом.
