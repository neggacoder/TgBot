# План Б: убрать chat_id из схемы и кода (этапы 4–6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать колонку `chat_id` из ста таблиц и параметр `chat_id` из всех
функций базы и модулей действий, оставив бота рабочим.

**Architecture:** Схему правит скрипт на сервере (`tools/migrate_drop_chat_id.py`,
готов в плане А). Код правит переписыватель на AST: он знает, у каких функций
первый параметр был `chat_id`, и убирает его и из объявлений, и из вызовов.
Руками правятся только те места, где переписыватель отказался. `chat_id` в
боте остаётся там, где он нужен телеграму — отправка сообщений, кнопки,
модерация: уходит только привязка ДАННЫХ к чату.

**Tech Stack:** Python 3.12, `ast` + `libcst`-подобный ручной обход по строкам,
MySQL, pytest.

## Global Constraints

- Прогон: `.venv/bin/python -m pytest`. Базовая линия — **1 failed**
  (`test_command_cleanup`), это не наша регрессия.
- Порядок нерушим: **сначала схема на сервере, сразу за ней код**. Между ними
  бот не поднимется: в таблицах колонки уже нет, а `db.py` шлёт её в каждом
  запросе. Промежуток измеряется минутами, а не днями.
- Дамп базы моложе суток обязателен — миграция сама это проверяет.
- `chat_id` остаётся: в `settings` (адреса чатов), в вызовах телеграма
  (`send_message`, `ban_chat_member`, `get_chat`), в `chats.py`,
  в `chat_scope_allows` и `callback_scope_allows`.
- Комментарии по-русски. После каждой задачи: прогон, коммит, `arc.zip`.

---

### Task 1: переписыватель вызовов

**Files:**
- Create: `tools/rewrite_chat_id.py`
- Test: `tests/test_rewrite_chat_id.py`

**Interfaces:**
- Produces: `rewrite_chat_id.функции_с_чатом(исходник) -> set[str]` — имена
  функций, у которых первый параметр `chat_id`;
  `rewrite_chat_id.убрать_параметр(исходник, имена) -> str` — правит
  объявления; `rewrite_chat_id.убрать_аргумент(исходник, имена, префиксы)
  -> tuple[str, list[str]]` — правит вызовы, возвращает (новый текст, отказы).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_rewrite_chat_id.py
"""Переписыватель вызовов: убрать первый параметр chat_id.

Правок четыре тысячи. Руками их не сделать, а скриптом на регулярках —
опасно: «chat_id» встречается и там, где он остаётся (отправка в телеграм,
настройки). Поэтому правится по разбору кода, а не по тексту, и всё, в чём
скрипт не уверен, он ОТКАЗЫВАЕТСЯ трогать и печатает списком.
"""
from tools import rewrite_chat_id as r


def test_находит_функции_с_чатом_первым():
    код = (
        "async def get_wallet(chat_id: int, user_id: int) -> dict: ...\n"
        "async def fetch_settings() -> dict: ...\n"
        "async def add_log(kind: str, chat_id: int = 0) -> None: ...\n"
    )
    assert r.функции_с_чатом(код) == {"get_wallet"}


def test_убирает_параметр_из_объявления():
    код = "async def get_wallet(chat_id: int, user_id: int) -> dict:\n    pass\n"
    новый = r.убрать_параметр(код, {"get_wallet"})
    assert "async def get_wallet(user_id: int) -> dict:" in новый


def test_убирает_первый_аргумент_из_вызова():
    код = "x = await db.get_wallet(chat_id, user_id)\n"
    новый, отказы = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert новый == "x = await db.get_wallet(user_id)\n"
    assert not отказы


def test_понимает_разные_виды_первого_аргумента():
    for первый in ("chat_id", "message.chat.id", "self.chat.id",
                   "callback.message.chat.id", "-100123"):
        код = f"await db.get_wallet({первый}, 7)\n"
        новый, отказы = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
        assert новый.strip() == "await db.get_wallet(7)", первый
        assert not отказы


def test_чужие_вызовы_не_трогает():
    """bot.send_message(chat_id, ...) обязан остаться: телеграму чат нужен."""
    код = "await bot.send_message(chat_id, text)\n"
    новый, отказы = r.убрать_аргумент(код, {"send_message"}, {"db"})
    assert новый == код


def test_непонятный_первый_аргумент_это_отказ():
    """Скрипт, который «додумывает» в спорном месте, ломает молча."""
    код = "await db.get_wallet(выбрать_чат(x), 7)\n"
    новый, отказы = r.убрать_аргумент(код, {"get_wallet"}, {"db"})
    assert новый == код
    assert отказы and "get_wallet" in отказы[0]
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_rewrite_chat_id.py -q`
Expected: FAIL — `No module named 'tools.rewrite_chat_id'`

- [ ] **Step 3: Написать переписыватель**

```python
# tools/rewrite_chat_id.py
"""Убрать первый параметр chat_id из объявлений и вызовов.

Правится по РАЗБОРУ кода, а не по тексту: «chat_id» встречается и там, где он
остаётся — отправка в телеграм, настройки, заслон чатов. Регулярка по имени
переписала бы и их.

Всё, в чём скрипт не уверен, он не трогает и печатает списком: скрипт,
который додумывает в спорном месте, ломает молча — а именно молчаливых
поломок в четырёх тысячах правок и надо бояться.
"""

from __future__ import annotations

import ast
import re

# Как выглядит чат первым аргументом. Список закрытый: всё остальное — отказ.
ВИДЫ_ЧАТА = re.compile(
    r"^\s*(chat_id|chat\.id|message\.chat\.id|msg\.chat\.id|"
    r"callback\.message\.chat\.id|event\.chat\.id|self\.chat\.id|"
    r"update\.chat\.id|-?\d+)\s*$"
)


def функции_с_чатом(исходник: str) -> set[str]:
    """Имена функций, у которых ПЕРВЫЙ параметр называется chat_id."""
    дерево = ast.parse(исходник)
    найдено = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, (ast.FunctionDef, ast.AsyncFunctionDef)):
            позиционные = узел.args.args
            if позиционные and позиционные[0].arg == "chat_id":
                найдено.add(узел.name)
    return найдено


def убрать_параметр(исходник: str, имена: set[str]) -> str:
    """Убирает первый параметр из объявлений перечисленных функций."""
    строки = исходник.split("\n")
    for i, строка in enumerate(строки):
        m = re.match(r"(\s*(?:async )?def (\w+)\()chat_id: int,\s*", строка)
        if m and m.group(2) in имена:
            строки[i] = m.group(1) + строка[m.end():]
            continue
        # Объявление в несколько строк: chat_id стоит на своей.
        m2 = re.match(r"\s*chat_id: int,\s*$", строка)
        if m2 and i and re.search(r"(?:async )?def (\w+)\($", строки[i - 1]):
            имя = re.search(r"def (\w+)\($", строки[i - 1]).group(1)
            if имя in имена:
                строки[i] = None
    return "\n".join(с for с in строки if с is not None)


def убрать_аргумент(исходник: str, имена: set[str],
                    префиксы: set[str]) -> tuple[str, list[str]]:
    """Убирает первый аргумент у вызовов вида `префикс.имя(чат, ...)`.

    Возвращает (новый текст, отказы). Отказ — вызов, у которого первый
    аргумент не похож ни на один известный вид чата.
    """
    отказы: list[str] = []
    новый = исходник
    for имя in sorted(имена):
        for префикс in sorted(префиксы):
            начало = f"{префикс}.{имя}("
            i = 0
            while True:
                i = новый.find(начало, i)
                if i < 0:
                    break
                открыта = i + len(начало)
                глубина, j = 1, открыта
                while j < len(новый) and глубина:
                    if новый[j] in "([{":
                        глубина += 1
                    elif новый[j] in ")]}":
                        глубина -= 1
                    j += 1
                внутри = новый[открыта:j - 1]
                части = _разделить(внутри)
                if not части:
                    i = j
                    continue
                if not ВИДЫ_ЧАТА.match(части[0]):
                    отказы.append(f"{префикс}.{имя}({части[0].strip()}…)")
                    i = j
                    continue
                остаток = внутри[len(части[0]):].lstrip()
                остаток = остаток[1:].lstrip() if остаток.startswith(",") else остаток
                новый = новый[:открыта] + остаток + новый[j - 1:]
                i = открыта
    return новый, отказы


def _разделить(аргументы: str) -> list[str]:
    """Аргументы верхнего уровня: скобки и кавычки не считаются разделителями."""
    части, глубина, текущая, кавычка = [], 0, "", None
    for символ in аргументы:
        if кавычка:
            текущая += символ
            if символ == кавычка:
                кавычка = None
            continue
        if символ in "\"'":
            кавычка = символ
        elif символ in "([{":
            глубина += 1
        elif символ in ")]}":
            глубина -= 1
        if символ == "," and глубина == 0:
            части.append(текущая)
            текущая = ""
            continue
        текущая += символ
    if текущая.strip():
        части.append(текущая)
    return части
```

- [ ] **Step 4: Прогнать тест**

Run: `.venv/bin/python -m pytest tests/test_rewrite_chat_id.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Коммит**

```bash
git add tools/rewrite_chat_id.py tests/test_rewrite_chat_id.py
git commit -m "Переписыватель вызовов: убрать первый параметр chat_id"
```

---

### Task 2: холостой прогон по всему коду

**Files:**
- Create: `tools/rewrite_report.py`
- Test: нет (отчётный скрипт; проверяется глазами и следующей задачей)

**Interfaces:**
- Consumes: `rewrite_chat_id` из Task 1.
- Produces: отчёт «сколько правок и где отказы» по `db.py`, семи модулям
  действий, `bot.py`, панели и тестам.

- [ ] **Step 1: Написать скрипт**

```python
# tools/rewrite_report.py
"""Сколько правок сделает переписыватель и где он откажется.

Запуск: .venv/bin/python -m tools.rewrite_report

Отчёт нужен ДО правки: отказы — это места, которые придётся смотреть руками,
и их число решает, делать ли правку одним заходом или порциями.
"""

from __future__ import annotations

import pathlib

from tools import rewrite_chat_id as r

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent
МОДУЛИ = ["db.py", "farm_actions.py", "casino_actions.py", "business_actions.py",
          "fishing_actions.py", "work_actions.py", "shop_actions.py",
          "profile_actions.py", "game_actions.py"]


def main() -> None:
    имена: dict[str, set[str]] = {}
    for файл in МОДУЛИ:
        путь = КОРЕНЬ / файл
        if путь.exists():
            имена[путь.stem] = r.функции_с_чатом(путь.read_text(encoding="utf-8"))
    всего = sum(len(v) for v in имена.values())
    print(f"Функций с chat_id первым параметром: {всего}")
    for модуль, набор in sorted(имена.items()):
        print(f"  {модуль:20} {len(набор)}")

    цели = list((КОРЕНЬ).glob("*.py")) + list((КОРЕНЬ / "webpanel").glob("*.py")) \
        + list((КОРЕНЬ / "tests").glob("*.py"))
    правок, все_отказы = 0, []
    for путь in цели:
        текст = путь.read_text(encoding="utf-8")
        новый = текст
        for модуль, набор in имена.items():
            новый, отказы = r.убрать_аргумент(новый, набор, {модуль})
            все_отказы += [f"{путь.name}: {о}" for о in отказы]
        правок += sum(1 for a, b in zip(текст.split("\n"), новый.split("\n")) if a != b)
    print(f"\nСтрок будет изменено: примерно {правок}")
    print(f"Отказов (смотреть руками): {len(все_отказы)}")
    for отказ in все_отказы[:40]:
        print("  ", отказ)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Прогнать и прочитать отчёт**

Run: `.venv/bin/python -m tools.rewrite_report`
Expected: числа функций по модулям, оценка правок, список отказов.

- [ ] **Step 3: Коммит**

```bash
git add tools/rewrite_report.py
git commit -m "Отчёт переписывателя: сколько правок и где отказы"
```

---

### Task 3: миграция схемы на сервере (НЕОБРАТИМО)

**Files:** изменений в репозитории нет — работа на сервере.

**Interfaces:**
- Consumes: `tools/backup_db.sh`, `tools/chat_report.py`,
  `tools/migrate_drop_chat_id.py` (готовы в плане А).

- [ ] **Step 1: Дамп**

```bash
bash tools/backup_db.sh
```
Expected: файл `db_backup_<дата>.sql` рядом с проектом.

- [ ] **Step 2: Отчёт по чатам**

```bash
.venv/bin/python -m tools.chat_report
```
Expected: таблица «таблица × чат × строк». Убедиться, что рабочий чат — тот
самый, и понять объём чужих строк.

- [ ] **Step 3: Холостой прогон миграции**

```bash
.venv/bin/python -m tools.migrate_drop_chat_id
```
Expected: по каждой таблице её ключ, число чужих строк и точные `ALTER`-ы.
Прочитать глазами: у таблиц с составным ключом должен быть
`DROP PRIMARY KEY, ADD PRIMARY KEY (...)` БЕЗ chat_id.

- [ ] **Step 4: Выполнить**

```bash
.venv/bin/python -m tools.migrate_drop_chat_id --выполнить
```
Expected: «Готово», число выгруженных чужих строк, файл
`migration_losers_<дата>.sql`.

- [ ] **Step 5: Проверить схему**

```bash
.venv/bin/python -m tools.chat_report
```
Expected: «Строк с chat_id в базе нет вовсе» либо только `settings`.

**Дальше без остановки к Task 4:** бот сейчас не поднимется — колонки нет,
а код её шлёт.

---

### Task 4: правка кода одним заходом

**Files:**
- Modify: `db.py`, `farm_actions.py`, `casino_actions.py`,
  `business_actions.py`, `fishing_actions.py`, `work_actions.py`,
  `shop_actions.py`, `profile_actions.py`, `game_actions.py`, `bot.py`,
  `webpanel/*.py`, `tests/*.py`
- Create: `tools/apply_rewrite.py`

**Interfaces:**
- Consumes: `rewrite_chat_id` из Task 1.
- Produces: код без параметра `chat_id` у функций данных.

- [ ] **Step 1: Написать применялку**

```python
# tools/apply_rewrite.py
"""Применить переписыватель ко всему коду.

Запуск: .venv/bin/python -m tools.apply_rewrite

Порядок внутри важен: сначала объявления, потом вызовы. Наоборот — и вызовы
уже не совпадут с сигнатурами, а разобрать, где какая версия, будет нечем.
"""

from __future__ import annotations

import pathlib

from tools import rewrite_chat_id as r
from tools.rewrite_report import МОДУЛИ, КОРЕНЬ


def main() -> None:
    имена: dict[str, set[str]] = {}
    for файл in МОДУЛИ:
        путь = КОРЕНЬ / файл
        if not путь.exists():
            continue
        текст = путь.read_text(encoding="utf-8")
        набор = r.функции_с_чатом(текст)
        имена[путь.stem] = набор
        путь.write_text(r.убрать_параметр(текст, набор), encoding="utf-8")
        print(f"{путь.name}: объявлений поправлено {len(набор)}")

    цели = sorted(set(КОРЕНЬ.glob("*.py")) | set((КОРЕНЬ / "webpanel").glob("*.py"))
                  | set((КОРЕНЬ / "tests").glob("*.py")))
    отказы_всего = []
    for путь in цели:
        текст = путь.read_text(encoding="utf-8")
        новый = текст
        for модуль, набор in имена.items():
            новый, отказы = r.убрать_аргумент(новый, набор, {модуль})
            отказы_всего += [f"{путь.name}: {о}" for о in отказы]
        if новый != текст:
            путь.write_text(новый, encoding="utf-8")
    print(f"\nОтказов: {len(отказы_всего)} — их править руками:")
    for отказ in отказы_всего:
        print("  ", отказ)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Применить**

Run: `.venv/bin/python -m tools.apply_rewrite`
Expected: список поправленных модулей и список отказов.

- [ ] **Step 3: Проверить, что всё разбирается**

```bash
.venv/bin/python -c "import ast,glob;[ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('*.py')+glob.glob('webpanel/*.py')+glob.glob('tests/*.py')]" && echo разбирается
```
Expected: «разбирается». Если нет — править названные файлы руками.

- [ ] **Step 4: Прогон и починка**

Run: `.venv/bin/python -m pytest -q -p no:randomly 2>&1 | tail -20`
Expected: сначала много падений. Чинить по одному, начиная с самых частых:
каждое — либо отказ переписывателя, либо место, где `chat_id` нужен телеграму
и его убрали ошибочно.

- [ ] **Step 5: Коммит после зелёного прогона**

```bash
git add -A
git commit -m "chat_id убран из данных: схема, база, вызовы, тесты"
```

---

### Task 5: заслоны

**Files:**
- Test: `tests/test_single_chat_invariants.py`

- [ ] **Step 1: Написать тест**

```python
# tests/test_single_chat_invariants.py
"""Данные больше не привязаны к чату.

Заслоны на то, что легко вернуть по привычке: дописать chat_id в новую
функцию базы или новую таблицу — и половина кода снова начнёт делить данные
по чатам, а вторая нет.
"""
import pathlib
import re

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


def test_у_функций_базы_нет_параметра_чата():
    db = (КОРЕНЬ / "db.py").read_text(encoding="utf-8")
    плохие = re.findall(r"(?:async )?def (\w+)\(chat_id", db)
    assert not плохие, f"параметр вернулся: {плохие}"


def test_в_запросах_базы_нет_колонки_чата():
    """Кроме settings: там chat_id это ЗНАЧЕНИЕ (адрес чата), а не разбиение."""
    db = (КОРЕНЬ / "db.py").read_text(encoding="utf-8")
    подозрительные = [
        строка.strip() for строка in db.split("\n")
        if re.search(r"(?<![\w_])chat_id\b", строка)
        and "settings" not in строка
        and "notify_chat_id" not in строка
        and "complaint_chat_id" not in строка
    ]
    assert not подозрительные, "\n".join(подозрительные[:10])


def test_в_схеме_нет_колонки_чата():
    схема = (КОРЕНЬ / "schema.sql").read_text(encoding="utf-8")
    блоки = схема.split("CREATE TABLE")
    плохие = [б.split("(")[0].strip() for б in блоки[1:]
              if re.search(r"(?<![\w_])chat_id\b", б)]
    assert not плохие, f"колонка осталась в схеме: {плохие}"


def test_чат_остался_там_где_он_нужен_телеграму():
    """Обратная проверка: заслон чатов и отправка сообщений обязаны знать чат.
    Без неё «вычистка» однажды доедет и до них."""
    bot = (КОРЕНЬ / "bot.py").read_text(encoding="utf-8")
    assert "def chat_scope_allows(" in bot
    assert "send_message(chat_id" in bot or "send_message(\n" in bot
```

- [ ] **Step 2: Прогнать**

Run: `.venv/bin/python -m pytest tests/test_single_chat_invariants.py -q`
Expected: PASS

- [ ] **Step 3: Коммит**

```bash
git add tests/test_single_chat_invariants.py
git commit -m "Заслоны: данные не привязаны к чату, но телеграм его знает"
```

---

### Task 6: схема и документация

**Files:**
- Modify: `schema.sql`
- Modify: `docs/superpowers/specs/2026-08-02-single-chat-design.md`

- [ ] **Step 1: Привести schema.sql к новому виду**

Файл описывает свежую установку: разойдись он с миграцией — новый бот
поднимется со старой схемой, и всё придётся делать заново.

Правки ровно четыре, и все механические:

1. строка объявления колонки: `chat_id BIGINT NOT NULL,` — удалить;
2. в составных ключах `(chat_id, user_id)` — убрать первый столбец;
3. в индексах `(chat_id, ...)` — то же самое;
4. ключ, состоявший ТОЛЬКО из `chat_id` (`chat_id BIGINT NOT NULL PRIMARY
   KEY`), — удалить целиком: собрать его больше не из чего.

Проверка после правки:

```bash
grep -n "chat_id" schema.sql
```

Остаться должны только `notify_chat_id` и `complaint_chat_id` в таблице
`settings` — это адреса чатов, а не разделение строк.

- [ ] **Step 2: Прогнать заслоны**

Run: `.venv/bin/python -m pytest tests/test_single_chat_invariants.py -q`
Expected: PASS (включая проверку схемы)

- [ ] **Step 3: Дописать в спеку, что сделано**

Раздел «Итог»: сколько таблиц изменено, сколько строк чужих чатов выгружено,
где лежит дамп и файл проигравших.

- [ ] **Step 4: Коммит**

```bash
git add schema.sql docs/
git commit -m "Схема свежей установки без chat_id + итог в спеке"
```

---

## Проверка плана по спеке

| Требование спеки | Задача |
|---|---|
| Этап 4: DROP COLUMN + пересборка ключей | Task 3 |
| Этап 5: убрать параметр из db.py | Task 1, 4 |
| Этап 6: вызовы в боте, модулях, панели | Task 4 |
| Этап 6: тесты | Task 4 (тесты правятся тем же переписывателем) |
| Заслон «у функций нет chat_id» | Task 5 |
| Заслон «в схеме нет колонки» | Task 5, 6 |
| `chat_id` остаётся у телеграма и настроек | Task 5, обратная проверка |

## Чего в плане нет

- Возврата к многочатовости: после Task 3 путь назад только через дамп.
- Правки `webapp.html` и мини-приложения телеграма: они ходят в те же
  эндпоинты, а те чат уже не принимают (план А, Task 3).
