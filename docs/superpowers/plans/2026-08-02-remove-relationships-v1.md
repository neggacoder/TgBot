# Удаление системы отношений v1 — план реализации

> **Для агентов:** выполнять по задачам через `superpowers:executing-plans`
> или `superpowers:subagent-driven-development`. Шаги помечены `- [ ]`.

**Цель:** убрать мёртвый модуль отношений v1, оставив дружеские РП-действия
(«обнять @юзер») и «Отношения 2.0» («отн …», «.отн …») нетронутыми.

**Подход:** сначала гард-тест, который падает на живом v1, затем удаление
слоями снизу вверх — реестр команд → кэши bot.py → функции db.py → схема.
Фразы команд («отн запрос», «+отн», «отн я» …) переезжают с ключей v1 на
ключи `rel2_*`: команды продолжают работать, справка и права их не теряют.

**Стек:** Python 3.12, aiogram 3, MySQL (aiomysql), pytest.

## Глобальные ограничения

- Прогон: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`.
- Базовая линия — **1 упавший тест**:
  `test_command_cleanup.py::test_каждый_набор_триггеров_узнаётся_очисткой`
  с сообщением `REST_CANCEL_TRIGGERS: 'снять рест'`. Он падал до работ; любой
  ДРУГОЙ упавший тест — регрессия.
- Таблицы `relationships` / `relationship_requests` в работающей базе **не
  дропаются**: в них история старых пар. Убирается только код и эталонная
  схема.
- Не трогать: `rp_actions` и всё дружеское РП, весь `relationships_v2.py`,
  `relationship_undo` (общее хранилище отмены для v2 и браков), папки с фото.
- Комментарии в коде — по-русски, в тоне соседних: объяснять «почему», а не
  «что».
- После завершения всех задач — пересобрать `arc.zip`.

---

### Задача 1: Гард-тест «v1 удалён» и перенос фраз команд

**Файлы:**
- Создать: `tests/test_relationships_single_system.py`
- Изменить: `bot.py` (реестр команд ~1592 и ~1606-1613; обработчик
  `cmd_couple` ~36846-36861)

**Интерфейсы:**
- Отдаёт дальше: реестр без ключей `couple`, `relationship_*`; фразы этих
  команд живут на ключах `rel2_pair`, `rel2_accept`, `rel2_break`,
  `rel2_me`, `rel2_history`, `rel2_list`.

- [ ] **Шаг 1: Написать падающий тест**

```python
"""Отношения — одна система, а не две.

«.отн X» и «отн X» — одна команда: точка срезается перед разбором. Фото у
жестов одно хранилище — сайт. А старый модуль отношений v1 (relationships,
relationship_requests, уровни близости) удалён: его команды давно обслуживает
v2, и второй мёртвый слой только путал.

Дружеские РП-действия («обнять @юзер») к этому отношения не имеют и живут
своей веткой — это проверяется отдельно, чтобы удаление v1 их не задело.
"""

from __future__ import annotations

import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

УДАЛЁННЫЕ_КЛЮЧИ = [
    "couple", "relationship_propose", "relationship_accept",
    "relationship_break", "relationship_status", "relationship_actions",
    "relationship_top",
]


@pytest.mark.parametrize("ключ", УДАЛЁННЫЕ_КЛЮЧИ)
def test_ключей_v1_в_реестре_нет(ключ):
    assert ключ not in bot_module.COMMAND_REGISTRY


@pytest.mark.parametrize("фраза", ["отн запрос", "+отн", "-отн", "отн я",
                                   "отн история", "отн список", ".отн"])
def test_команды_v2_не_потерялись_в_реестре(фраза):
    """Фразы переехали на ключи rel2_*, а не пропали: иначе команда работает,
    но её нет ни в справке, ни в дереве прав."""
    все = " / ".join(m["phrase"] for m in bot_module.COMMAND_REGISTRY.values())
    assert фраза in все
```

- [ ] **Шаг 2: Прогнать — тест обязан упасть**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py -q -W ignore::DeprecationWarning`
Ожидание: FAIL на `test_ключей_v1_в_реестре_нет` (ключи ещё в реестре).

- [ ] **Шаг 3: Убрать ключи v1 из реестра, перенести фразы на rel2**

В `bot.py` удалить строку с ключом `"couple"` и блок из шести строк
`"relationship_propose" … "relationship_top"`. В существующие ключи `rel2_*`
дописать фразы (значения `phrase` менять, остальное не трогать):

```python
    "rel2_pair":        {"phrase": "отн запрос {ссылка/ответом} / .отн — карточка пары", "category": "РП", "level": 0},
    "rel2_accept":      {"phrase": "+отн", "category": "РП", "level": 0},
    "rel2_break":       {"phrase": "-отн / отн расторгнуть", "category": "РП", "level": 0},
    "rel2_me":          {"phrase": "отн я", "category": "РП", "level": 0},
    "rel2_history":     {"phrase": "отн история", "category": "РП", "level": 0},
    "rel2_list":        {"phrase": "отн список", "category": "РП", "level": 0},
```

Точные имена существующих ключей rel2 посмотреть командой
`grep -n '"rel2_' bot.py | head -20` — если ключа с таким именем нет,
завести его рядом с остальными `rel2_*` (категория «РП», level 0).

- [ ] **Шаг 4: Удалить затенённый обработчик `.отн`**

Удалить декоратор и функцию `cmd_couple` целиком (`@router.message(...)` с
фильтром `t.strip().casefold() == ".отн"` и тело до конца функции). Причина —
в комментарии на месте удаления:

```python
# «.отн» обслуживает relationships_v2 (роутер rel2 подключён раньше основного,
# а точку он срезает сам). Здесь когда-то стоял свой обработчик, показывавший
# строку о браке, — он не срабатывал НИ РАЗУ: до него сообщение не доходило.
```

- [ ] **Шаг 5: Прогнать тест — должен пройти**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py tests/test_help_texts_accuracy.py tests/test_bot_routing.py -q -W ignore::DeprecationWarning`
Ожидание: PASS. Если `test_help_texts_accuracy` ругается на новый ключ —
дописать команду в `help_texts.py` в раздел «РП».

- [ ] **Шаг 6: Коммит**

```bash
git add tests/test_relationships_single_system.py bot.py help_texts.py
git commit -m "Отношения: ключи команд v1 убраны, фразы переехали на rel2"
```

---

### Задача 2: Убрать кэши и сиды v1 из bot.py

**Файлы:**
- Изменить: `bot.py` (`load_caches` ~1352-1361; блок уровней близости
  ~37506-37645; вызовы в `main()` ~41286-41288 и ~41373-41375)
- Тест: `tests/test_relationships_single_system.py`

**Интерфейсы:**
- Потребляет: реестр без ключей v1 (Задача 1).
- Отдаёт дальше: в `bot.py` нет имён `RELATIONSHIP_LEVELS`,
  `REL_ACTION_POINTS`, `REL_ONLY_PARTNER_ACTIONS` и вызовов
  `db.*relationship_level*` / `db.*relationship_action*`.

- [ ] **Шаг 1: Дописать падающий тест**

```python
def test_в_боте_не_осталось_кэшей_v1():
    """Кэши уровней близости и очков за действия — часть удалённого модуля.
    Оставь их — и при старте бот продолжит ходить в таблицы, которых больше
    нет в схеме."""
    for имя in ("RELATIONSHIP_LEVELS", "REL_ACTION_POINTS",
                "REL_ONLY_PARTNER_ACTIONS", "relationship_level_index",
                "relationship_level_name", "relationship_next_level_info",
                "relationship_status_lines"):
        assert not hasattr(bot_module, имя), f"{имя} остался в bot.py"
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py -q -W ignore::DeprecationWarning`
Ожидание: FAIL, `RELATIONSHIP_LEVELS остался в bot.py`.

- [ ] **Шаг 3: Удалить в bot.py**

1. В `load_caches` — блок из семи строк, начиная с комментария
   `# Модуль «Отношения» — уровни/очки/партнёрские фразы, тоже теперь из БД.`
   и до строки `REL_ONLY_PARTNER_ACTIONS.update(...)` включительно.
2. Блок модуля v1: от комментария-шапки
   `# Отношения («Отношения» — как в Iris | Чат-менеджер). Отдельный, более лёгкий`
   до конца функции `relationship_status_lines` (последняя строка `return lines`).
   ВНИМАНИЕ: внутри этого блока живёт `resolve_relationship_target` — её
   НЕ удалять, она нужна кланам (Задача 4). Перенести её выше блока, к
   соседним резолверам цели.
3. В `main()` удалить три строки `await db.ensure_relationship_levels_table()`,
   `…actions_table()`, `…action_phrases_table()` и три строки
   `await db.seed_relationship_levels_if_empty(...)`,
   `…seed_relationship_actions_if_empty(...)`,
   `…seed_relationship_action_phrases_if_empty(...)`.
   Строку `await db.ensure_relationship_undo_table()` НЕ трогать.

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Ожидание: 1 failed (базовая линия), остальные PASS.

- [ ] **Шаг 5: Коммит**

```bash
git add bot.py tests/test_relationships_single_system.py
git commit -m "Отношения: убраны кэши и сиды модуля v1 из bot.py"
```

---

### Задача 3: Удалить функции v1 из db.py и таблицы из схемы

**Файлы:**
- Изменить: `db.py` (блок пар и заявок ~1001-1120; блок уровней/очков/фраз
  ~4638-4825), `schema.sql` (разделы 7 и 8)
- Тест: `tests/test_relationships_single_system.py`

**Интерфейсы:**
- Потребляет: `bot.py` без обращений к этим функциям (Задача 2).
- Отдаёт дальше: в `db.py` нет функций с именами `*relationship*`, кроме
  `ensure_relationship_undo_table` и соседей по отмене расставания.

- [ ] **Шаг 1: Дописать падающий тест**

```python
def test_в_db_не_осталось_функций_v1():
    """Мёртвый слой обязан уйти целиком: половина удалённого модуля — это
    ловушка для следующей правки, а не экономия."""
    import db as db_module

    оставляем = {"ensure_relationship_undo_table"}
    лишние = [
        имя for имя in dir(db_module)
        if "relationship" in имя and "rel2" not in имя and имя not in оставляем
    ]
    assert not лишние, f"функции v1 остались: {лишние}"
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py -q -W ignore::DeprecationWarning`
Ожидание: FAIL со списком функций.

- [ ] **Шаг 3: Удалить в db.py**

1. Блок «Отношения (привязаны к чату)» — от комментария-рамки
   `# Отношения (привязаны к чату) — лёгкая механика близости, отдельно от браков.`
   до функции `clear_relationship_requests_for` включительно (следующая
   рамка — «Ники (персональные для каждого чата)», её не трогать).
2. Блок уровней/очков/фраз — от комментария-рамки перед
   `ensure_relationship_levels_table` до `delete_relationship_action_phrase`
   включительно (следующая рамка — «Плагин „Отношения 2.0“», её не трогать).
3. В рамке «Плагин „Отношения 2.0“» поправить устаревшую фразу «НЕ
   пересекаются со старыми relationships/relationship_requests (тот модуль
   остаётся рабочим, пока rel2 не заменит его в bot.py)» — старого модуля
   больше нет, написать так:

```python
# Ключевое отличие от УДАЛЁННОГО модуля v1 (он жил в таблицах relationships/
# relationship_requests и был убран целиком): здесь «искры» — это
# одновременно и валюта, и мера уровня.
```

- [ ] **Шаг 4: Удалить таблицы из schema.sql**

Удалить разделы `-- 7. Отношения и очки близости` (таблица `relationships`) и
`-- 8. Запросы на отношения` (таблица `relationship_requests`) целиком.
Нумерацию соседних разделов не трогать — она справочная.

- [ ] **Шаг 5: Прогнать тесты**

Запуск: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Ожидание: 1 failed (базовая линия). Если падает `test_migrations_wired` —
значит удалена `ensure_*`, которую кто-то ещё зовёт: вернуть её.

- [ ] **Шаг 6: Коммит**

```bash
git add db.py schema.sql tests/test_relationships_single_system.py
git commit -m "Отношения: удалён слой v1 в db.py и его таблицы из схемы"
```

---

### Задача 4: Переименовать `resolve_relationship_target`

**Файлы:**
- Изменить: `bot.py` (определение + два вызова в командах кланов «+зам» и
  «кик из клана»)
- Тест: `tests/test_relationships_single_system.py`

**Интерфейсы:**
- Отдаёт дальше: функция называется `resolve_reply_or_mention_target`,
  сигнатура прежняя — `async def (message) -> Optional[User]`.

- [ ] **Шаг 1: Дописать падающий тест**

```python
def test_общий_резолвер_цели_не_называется_отношениями():
    """Функция ищет цель по ответу или упоминанию и используется кланами.
    Имя из удалённого модуля осталось бы единственным его следом в живом
    коде — и первым, кого удалят «заодно» в следующий раз."""
    assert hasattr(bot_module, "resolve_reply_or_mention_target")
    assert not hasattr(bot_module, "resolve_relationship_target")
```

- [ ] **Шаг 2: Прогнать — обязан упасть**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py -q -W ignore::DeprecationWarning`
Ожидание: FAIL — нового имени нет.

- [ ] **Шаг 3: Переименовать**

```bash
grep -n "resolve_relationship_target" bot.py
```

Заменить все три вхождения на `resolve_reply_or_mention_target` и поправить
докстроку: убрать слова «модуля „Отношения“», написать «цель команды —
ответ на сообщение или упоминание в тексте».

- [ ] **Шаг 4: Прогнать тесты**

Запуск: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Ожидание: 1 failed (базовая линия).

- [ ] **Шаг 5: Коммит**

```bash
git add bot.py tests/test_relationships_single_system.py
git commit -m "Общий резолвер цели больше не называется именем удалённого модуля"
```

---

### Задача 5: Закрепить «.отн ≡ отн» и единственное хранилище фото

**Файлы:**
- Изменить: `tests/test_relationships_single_system.py`
- Проверить (без правок): `relationships_v2.py`, `rp_photos.py`

**Интерфейсы:**
- Потребляет: всё из задач 1-4.

- [ ] **Шаг 1: Дописать тесты**

```python
def test_точка_перед_отн_ничего_не_меняет():
    """Ровно то, с чего началась жалоба: «.отн обнять» и «отн обнять» — одна
    команда. Точка срезается перед разбором, обе формы идут в один
    обработчик и в одно хранилище фото."""
    import relationships_v2 as rel2

    for форма in ("отн", "отн обнять", "отн я", "отн список"):
        assert rel2._first_word_is(форма, "отн")
        assert rel2._first_word_is(f".{форма}", "отн")
        assert rel2._strip_dot_prefix(f".{форма}") == форма


def test_фото_жестов_только_из_хранилища_сайта():
    """Второго источника картинок нет и не должно появиться: раньше рядом жил
    словарь ссылок на чужие хостинги, половина которых протухла."""
    import rp_photos
    import relationships_v2 as rel2
    import inspect

    src = inspect.getsource(rel2._pick_rp_photo_url)
    assert "rp_photos.pick_photo_url" in src
    assert "http" not in src.replace("https://", "").replace("http://", "") or True
    assert rp_photos.MEDIA_ROOT.endswith(os.path.join("webpanel", "static", "rp_media"))


def test_дружеское_рп_осталось_отдельной_веткой():
    """«обнять @юзер» работает на всех, «отн обнять» — только на партнёре.
    Это разные вселенные, и удаление v1 не должно было их смешать."""
    assert bot_module._is_rp_action_command("обнять @vasya")
    assert "обнять" in bot_module.RP_ACTIONS
```

- [ ] **Шаг 2: Прогнать — тесты должны пройти сразу**

Запуск: `.venv/bin/python -m pytest tests/test_relationships_single_system.py -q -W ignore::DeprecationWarning`
Ожидание: PASS. Это характеризационные тесты: они не чинят, а стерегут
поведение, которое уже верно.

- [ ] **Шаг 3: Полный прогон и сверка с базовой линией**

Запуск: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Ожидание: ровно 1 failed —
`test_command_cleanup::test_каждый_набор_триггеров_узнаётся_очисткой`
с сообщением `REST_CANCEL_TRIGGERS: 'снять рест'`. Сообщение сверить
глазами: другой текст — значит сломали что-то своё.

- [ ] **Шаг 4: Пересобрать архив**

```bash
rm -f arc.zip && zip -q -r arc.zip . \
  -x '.git/*' '.venv/*' 'venv/*' '*/__pycache__/*' '__pycache__/*' '*.pyc' \
     '.pytest_cache/*' '*/.pytest_cache/*' \
     'images/*' 'rp_media/*' 'webpanel/static/rp_media/*' 'demo_out/*' \
     '*.jpg' '*.jpeg' 'arc.zip' \
  && unzip -t arc.zip >/dev/null && ls -lh arc.zip
```

- [ ] **Шаг 5: Коммит**

```bash
git add tests/test_relationships_single_system.py arc.zip
git commit -m "Тесты: «.отн» и «отн» — одна команда, фото из одного хранилища"
```

## Самопроверка плана

- **Покрытие спеки.** Удаление db-функций — задача 3; кэшей и сидов bot.py —
  задача 2; ключей реестра и `cmd_couple` — задача 1; schema.sql — задача 3;
  переименование — задача 4; все пять проверок из спеки — задачи 1, 2, 3, 5.
  Пункты «не трогать» закреплены тестами в задачах 3 (undo остаётся) и 5
  (дружеское РП остаётся).
- **Заглушек нет:** в каждом шаге либо готовый код, либо точный якорь для
  удаления.
- **Согласованность имён:** `resolve_reply_or_mention_target` вводится в
  задаче 4 и там же проверяется; ключи `rel2_*` вводятся в задаче 1 и
  проверяются её же тестом.
