# План А: герметичность и подготовка к вычистке chat_id (этапы 0–3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать систему доказуемо одночатовой (панель перестаёт принимать
чат снаружи), убрать данные третьего чата и получить утверждённый список
таблиц, у которых колонка `chat_id` подлежит удалению.

**Architecture:** Появляется `chats.py` — единственное место, где читаются
настройки рабочего чата и чата заявок; бот и панель зовут его вместо россыпи
`settings.get(...)`. Все 17 member-эндпоинтов панели перестают принимать
`chat_id` из запроса и берут рабочий чат сами. С восьми экранов кабинета
уходит выбор чата. Отдельно пишутся два скрипта — отчёт по данным чатов и
классификатор таблиц; первый запускается на сервере, второй работает по
исходникам.

**Tech Stack:** Python 3.12, aiogram 3, FastAPI, aiomysql, pytest, ванильный
JS (без сборки).

## Global Constraints

- Прогон тестов: только из `.venv` (`.venv/bin/python -m pytest`), системный
  python без зависимостей.
- Базовая линия прогона: **1 failed** — `tests/test_command_cleanup.py::
  test_каждый_набор_триггеров_узнаётся_очисткой`. Это не наша регрессия.
- База данных из среды разработки **недоступна** (нет сети до MySQL, нет
  клиентов `mysql`/`mysqldump`). Всё, что требует живой базы, оформляется
  скриптом с инструкцией запуска на сервере.
- Комментарии и сообщения — по-русски, как во всём проекте.
- После каждой задачи: прогон, коммит, пересборка `arc.zip`.
- Ничего не удаляется из базы без предварительного дампа.

---

### Task 1: `chats.py` — единственный источник правды о чатах

**Files:**
- Create: `chats.py`
- Test: `tests/test_chats_module.py`

**Interfaces:**
- Produces: `chats.work_chat_id() -> Optional[int]`,
  `chats.gate_chat_id() -> Optional[int]`,
  `chats.is_work_chat(chat_id: int) -> bool`,
  `chats.is_known_chat(chat_id: int) -> bool`.
  Все асинхронные, читают `db.fetch_settings()`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_chats_module.py
"""Один источник правды о чатах.

Настройки чатов читались россыпью settings.get(...) по всему боту — сто семь
мест. Пока их много, «рабочий чат» и «чат заявок» легко перепутать: так уже
было с ролями и чисткой, которые взяли notify_chat_id вместо complaint.
"""
import asyncio
import functools

import pytest

import chats


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


class _Settings:
    def __init__(self, работа=None, заявки=None):
        self.значения = {"complaint_chat_id": работа, "notify_chat_id": заявки}

    async def fetch_settings(self):
        return dict(self.значения)


@pytest.fixture
def настройки(monkeypatch):
    s = _Settings(работа=-100111, заявки=-100222)
    monkeypatch.setattr(chats, "db", s)
    return s


@_sync
async def test_рабочий_и_заявочный_чаты_различаются(настройки):
    assert await chats.work_chat_id() == -100111
    assert await chats.gate_chat_id() == -100222


@_sync
async def test_свой_чат_узнаётся(настройки):
    assert await chats.is_work_chat(-100111) is True
    assert await chats.is_work_chat(-100222) is False
    assert await chats.is_known_chat(-100222) is True
    assert await chats.is_known_chat(-100999) is False


@_sync
async def test_ненастроенный_бот_не_считает_чужие_чаты_своими(monkeypatch):
    """Свежая установка: чаты ещё не привязаны. is_work_chat обязан отвечать
    «нет» — иначе первый попавшийся чат станет рабочим."""
    monkeypatch.setattr(chats, "db", _Settings())
    assert await chats.work_chat_id() is None
    assert await chats.is_work_chat(-100999) is False
    assert await chats.is_known_chat(-100999) is False
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_chats_module.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chats'`

- [ ] **Step 3: Написать модуль**

```python
# chats.py
"""Какие чаты у бота свои.

Чатов ровно два и у каждого своя роль:

* рабочий (настройка complaint_chat_id, команда «жалобы сюда») — здесь бот
  работает на все сто;
* чат заявок (настройка notify_chat_id, команда «чат сюда») — здесь он молчит
  на всё, кроме заявок на вступление.

Модуль заведён потому, что настройки читались россыпью — сто семь мест в одном
bot.py. Пока их много, перепутать рабочий чат с заявочным ничего не стоит: так
уже было с ролями и чисткой, которые брали notify_chat_id и молча работали не
там. Одно место — одна правда.

Здесь НЕТ кэша: настройка меняется командой «жалобы сюда» на ходу, и
запомненное значение пережило бы перепривязку. Чтение идёт через
db.fetch_settings(), у которого своя строка настроек одна на оба процесса.
"""

from __future__ import annotations

from typing import Optional

import db


async def _настройки() -> dict:
    try:
        return await db.fetch_settings() or {}
    except Exception:
        # Бот обязан подниматься даже с недоступной базой: без настроек он
        # просто не считает своим ни один чат.
        return {}


async def work_chat_id() -> Optional[int]:
    """Рабочий чат («жалобы сюда») или None, если ещё не привязан."""
    значение = (await _настройки()).get("complaint_chat_id")
    return int(значение) if значение else None


async def gate_chat_id() -> Optional[int]:
    """Чат заявок («чат сюда») или None."""
    значение = (await _настройки()).get("notify_chat_id")
    return int(значение) if значение else None


async def is_work_chat(chat_id: int) -> bool:
    рабочий = await work_chat_id()
    return рабочий is not None and chat_id == рабочий


async def is_known_chat(chat_id: int) -> bool:
    """Свой ли это чат вообще — рабочий или заявок."""
    свои = {await work_chat_id(), await gate_chat_id()} - {None}
    return chat_id in свои
```

- [ ] **Step 4: Прогнать тест**

Run: `.venv/bin/python -m pytest tests/test_chats_module.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Коммит**

```bash
git add chats.py tests/test_chats_module.py
git commit -m "chats.py: один источник правды о рабочем чате и чате заявок"
```

---

### Task 2: панель пускает только рабочий чат

**Files:**
- Modify: `webpanel/app.py:1895-1899` (`_require_member_in_chat`)
- Test: `tests/test_member_chat_scope.py`

**Interfaces:**
- Consumes: `chats.work_chat_id()` из Task 1.
- Produces: `_require_member_in_chat(user, chat_id)` бросает `HTTPException(403)`
  на любой чат, кроме рабочего.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_member_chat_scope.py
"""Кабинет работает только в рабочем чате.

Проверка «бот видел вас в этом чате» пускала любой чат из истории — включая
тот, где бот давно не работает. Через игровые экраны туда уходили деньги и
данные под чужим chat_id.
"""
import asyncio
import functools
import os

import pytest

pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")
os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

from fastapi import HTTPException  # noqa: E402

from webpanel import app as panel  # noqa: E402
from webpanel.auth import PanelUser  # noqa: E402


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper


РАБОЧИЙ, ЧУЖОЙ = -100111, -100999


@pytest.fixture
def свой_чат(monkeypatch):
    async def work_chat_id():
        return РАБОЧИЙ

    async def видел(chat_id, user_id):
        return {"user_id": user_id}

    monkeypatch.setattr(panel.chats, "work_chat_id", work_chat_id)
    monkeypatch.setattr(panel.db, "get_known_user", видел)


@_sync
async def test_рабочий_чат_пускают(свой_чат):
    user = PanelUser(id=1, username="кто-то", role="member", tg_user_id=7)
    await panel._require_member_in_chat(user, РАБОЧИЙ)


@_sync
async def test_чужой_чат_не_пускают_даже_если_бот_там_видел(свой_чат):
    """Именно «даже если видел»: старая проверка на этом и держалась."""
    user = PanelUser(id=1, username="кто-то", role="member", tg_user_id=7)
    with pytest.raises(HTTPException) as ошибка:
        await panel._require_member_in_chat(user, ЧУЖОЙ)
    assert ошибка.value.status_code == 403
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_member_chat_scope.py -q`
Expected: FAIL — второй тест не бросает `HTTPException` (старая проверка
пускает чужой чат).

- [ ] **Step 3: Починить проверку**

Заменить тело `_require_member_in_chat` в `webpanel/app.py`:

```python
async def _require_member_in_chat(user: PanelUser, chat_id: int) -> None:
    """Кабинет работает ТОЛЬКО в рабочем чате.

    Раньше здесь стояло «бот видел вас в этом чате», и этого хватало: любой
    чат из истории открывал игровые экраны, а деньги и данные уходили под
    чужой chat_id. Список своих чатов знает chats.py — здесь только проверка.
    """
    if not user.tg_user_id:
        raise HTTPException(400, "Аккаунт не привязан к Telegram")
    рабочий = await chats.work_chat_id()
    if рабочий is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан — «жалобы сюда» в чате")
    if chat_id != рабочий:
        raise HTTPException(403, "Кабинет работает только в основном чате")
    if not await db.get_known_user(chat_id, user.tg_user_id):
        raise HTTPException(403, "Бот не видел вас в этом чате")
```

Добавить импорт `chats` рядом с остальными в `webpanel/app.py`.

- [ ] **Step 4: Прогнать тест**

Run: `.venv/bin/python -m pytest tests/test_member_chat_scope.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Полный прогон и коммит**

```bash
.venv/bin/python -m pytest -q -p no:randomly 2>&1 | tail -3
git add webpanel/app.py tests/test_member_chat_scope.py
git commit -m "Кабинет: только рабочий чат, а не любой из истории"
```

Ожидание прогона: 1 failed (известный `test_command_cleanup`).

---

### Task 3: эндпоинты перестают принимать chat_id

**Files:**
- Modify: `webpanel/member_farm_api.py`, `webpanel/member_casino_api.py`,
  `webpanel/member_business_api.py`, `webpanel/member_activity_api.py`,
  `webpanel/member_shop_api.py`, `webpanel/member_profile_api.py`,
  `webpanel/member_game_api.py`
- Test: `tests/test_member_chat_scope.py` (дополняется)

**Interfaces:**
- Consumes: `chats.work_chat_id()` из Task 1.
- Produces: у всех 17 member-эндпоинтов исчезает параметр `chat_id`
  (и из query, и из тел запросов); чат берётся из `chats.work_chat_id()`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_member_chat_scope.py`:

```python
def test_ни_один_эндпоинт_не_принимает_чат_снаружи():
    """Чат приходил в теле запроса, то есть его выбирал браузер. Даже с
    проверкой это лишний параметр, которым можно ошибиться; чат один, и знать
    его должен сервер."""
    import pathlib
    import re
    корень = pathlib.Path(panel.__file__).parent
    плохие = []
    for файл in sorted(корень.glob("member_*_api.py")):
        текст = файл.read_text(encoding="utf-8")
        for строка in текст.split("\n"):
            # Тела запросов (pydantic) и параметры обработчиков.
            if re.search(r"^\s+chat_id: int", строка):
                плохие.append(f"{файл.name}: {строка.strip()}")
            if re.search(r"async def api_\w+\([^)]*chat_id", строка):
                плохие.append(f"{файл.name}: {строка.strip()}")
    assert not плохие, "чат приходит снаружи:\n" + "\n".join(плохие)
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_member_chat_scope.py::test_ни_один_эндпоинт_не_принимает_чат_снаружи -q`
Expected: FAIL — перечислены `chat_id: int` из шести модулей.

- [ ] **Step 3: Переписать эндпоинты**

Для каждого модуля:

1. В pydantic-теле убрать строку `chat_id: int`.
2. В GET-обработчиках убрать параметр `chat_id: int` из сигнатуры.
3. В начале каждого обработчика получить чат:

```python
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
```

4. Все `body.chat_id` заменить на `chat_id`.

Пример для `member_farm_api.py` (остальные — по тому же образцу):

```python
@router.get("/api/member/game/farm")
async def api_member_farm(user: PanelUser = Depends(auth.require_member)):
    chat_id = await chats.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await require_member_in_chat(user, chat_id)
    await permissions.ensure(user, _LIST_COMMAND)
    stars, coins = await _wallet(chat_id, user.tg_user_id)
    return await farm_actions.state(
        chat_id, user.tg_user_id, stars=stars, coins=coins,
        event_active=await farm_actions.active_event(chat_id) is not None,
    )
```

- [ ] **Step 4: Прогнать тесты панели**

Run: `.venv/bin/python -m pytest tests/test_member_chat_scope.py tests/test_member_farm_api.py tests/test_member_casino_api.py tests/test_member_business_api.py tests/test_member_activity_api.py tests/test_member_shop_api.py tests/test_member_profile_api.py tests/test_member_game_api.py -q`
Expected: PASS

- [ ] **Step 5: Полный прогон и коммит**

```bash
.venv/bin/python -m pytest -q -p no:randomly 2>&1 | tail -3
git add webpanel/ tests/test_member_chat_scope.py
git commit -m "Кабинет: чат больше не приходит из браузера"
```

---

### Task 4: с экранов уходит выбор чата

**Files:**
- Modify: `webpanel/static/app.js`
- Test: `tests/test_responsive_layout.py` (дополняется)

**Interfaces:**
- Consumes: эндпоинты без `chat_id` из Task 3.
- Produces: экраны кабинета грузятся одним запросом, без `/api/member/chats`
  и без `<select>`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_responsive_layout.py`:

```python
def test_на_экранах_нет_выбора_чата():
    """Чат один — выбирать нечего. Оставленный список чатов ещё и врал бы:
    он показывал чаты, где бот больше не работает."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    экраны = js[js.index("// ===== Вкладка «Ферма»"):]
    assert "member-farm-chat" not in экраны
    assert "member-casino-chat" not in экраны
    assert "member-biz-chat" not in экраны
    assert "/api/member/chats" not in экраны
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_responsive_layout.py::test_на_экранах_нет_выбора_чата -q`
Expected: FAIL — `member-farm-chat` найден.

- [ ] **Step 3: Убрать выбор чата**

В каждом загрузчике (`loadMemberFarm`, `loadMemberCasino`, `loadMemberBiz`,
`loadActivity`, `loadSimpleScreen`, `loadProfScreen`) убрать запрос
`/api/member/chats`, `<label><span>Чат</span><select…>` и обработчик
`change`; сразу рисовать тело экрана. Пример:

```javascript
async function loadMemberFarm() {
  const box = $("#member-farm");
  box.innerHTML = `<section class="member-block"><h2>${icon("sprout")}Ферма</h2>
    <div class="card">
      <div id="member-farm-msg"></div>
      <div id="member-farm-body"><div class="muted">Загрузка…</div></div>
    </div></section>`;
  if (!_farm.bound) { box.addEventListener("click", onFarmClick); _farm.bound = true; }
  loadFarmState();
}
```

Из запросов убрать `?chat_id=…` и `chat_id` в телах.

- [ ] **Step 4: Прогнать проверки и харнесы**

```bash
node --check webpanel/static/app.js
.venv/bin/python -m pytest tests/test_responsive_layout.py -q
```
Expected: PASS

- [ ] **Step 5: Полный прогон и коммит**

```bash
.venv/bin/python -m pytest -q -p no:randomly 2>&1 | tail -3
git add webpanel/static/app.js tests/test_responsive_layout.py
git commit -m "Экраны кабинета: выбор чата убран, чат знает сервер"
```

---

### Task 5: скрипты для сервера — дамп и отчёт по чатам

**Files:**
- Create: `tools/chat_report.py`
- Create: `tools/backup_db.sh`
- Test: `tests/test_chat_report.py`

**Interfaces:**
- Produces: `tools/chat_report.py` печатает таблицу «таблица × чат × строк»
  и список чатов; `tools/backup_db.sh` делает дамп через `mysqldump`.
  Оба запускаются НА СЕРВЕРЕ, где доступна база.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_chat_report.py
"""Отчёт по чатам: что где лежит.

Скрипт запускается на сервере (в среде разработки базы нет), поэтому здесь
проверяется его чистая часть — сборка запросов и формат отчёта.
"""
import pytest

from tools import chat_report


def test_запрос_считает_строки_по_чатам():
    запрос = chat_report.запрос_для("economy_wallets")
    assert "SELECT chat_id, COUNT(*)" in запрос
    assert "FROM economy_wallets" in запрос
    assert "GROUP BY chat_id" in запрос


def test_таблицы_берутся_из_схемы_а_не_из_списка():
    """Список руками устарел бы на следующей же миграции."""
    запрос = chat_report.запрос_таблиц()
    assert "information_schema.columns" in запрос
    assert "column_name = 'chat_id'" in запрос


def test_отчёт_помечает_чужие_чаты():
    строки = {"economy_wallets": {-100111: 30, -100999: 2}}
    отчёт = chat_report.отчёт(строки, свои=[-100111])
    assert "-100999" in отчёт and "чужой" in отчёт
    assert "economy_wallets" in отчёт
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_chat_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Написать скрипты**

```python
# tools/__init__.py
```

```python
# tools/chat_report.py
"""Сколько строк каждого чата лежит в каждой таблице.

Запускать НА СЕРВЕРЕ, где доступна база:

    .venv/bin/python -m tools.chat_report

Список таблиц берётся из схемы, а не из перечисления руками: перечисление
устарело бы на первой же миграции, и отчёт молча пропустил бы таблицу.
"""

from __future__ import annotations

import asyncio
import sys

import db


def запрос_таблиц() -> str:
    return (
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND column_name = 'chat_id' "
        "ORDER BY table_name"
    )


def запрос_для(таблица: str) -> str:
    return f"SELECT chat_id, COUNT(*) AS n FROM {таблица} GROUP BY chat_id"


def отчёт(строки: dict[str, dict[int, int]], свои: list[int]) -> str:
    чаты = sorted({ч for c in строки.values() for ч in c})
    ширина = max((len(т) for т in строки), default=10)
    шапка = "таблица".ljust(ширина) + "".join(f"{ч:>16}" for ч in чаты)
    метки = " " * ширина + "".join(
        f"{'свой' if ч in свои else 'чужой':>16}" for ч in чаты)
    тело = [
        т.ljust(ширина) + "".join(f"{строки[т].get(ч, 0):>16}" for ч in чаты)
        for т in sorted(строки)
    ]
    return "\n".join([шапка, метки, "-" * len(шапка), *тело])


async def main() -> None:
    await db.init_pool()
    таблицы = [r["table_name"] for r in await db._fetchall(запрос_таблиц())]
    строки: dict[str, dict[int, int]] = {}
    for таблица in таблицы:
        try:
            строки[таблица] = {
                int(r["chat_id"]): int(r["n"])
                for r in await db._fetchall(запрос_для(таблица))
                if r["chat_id"] is not None
            }
        except Exception as exc:      # таблица могла исчезнуть между шагами
            print(f"пропущена {таблица}: {exc}", file=sys.stderr)
    настройки = await db.fetch_settings() or {}
    свои = [int(настройки[k]) for k in ("complaint_chat_id", "notify_chat_id")
            if настройки.get(k)]
    print(отчёт(строки, свои))


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
# tools/backup_db.sh
#!/usr/bin/env bash
# Полный дамп базы ПЕРЕД любыми изменениями схемы или удалением строк.
# Запускать на сервере: bash tools/backup_db.sh
set -euo pipefail
: "${DB_NAME:=neongelion}"
: "${DB_USER:=neongelion}"
имя="db_backup_$(date +%Y%m%d_%H%M%S).sql"
mysqldump --single-transaction --routines --events \
  -u "$DB_USER" ${DB_PASSWORD:+-p"$DB_PASSWORD"} "$DB_NAME" > "$имя"
echo "дамп готов: $имя ($(du -h "$имя" | cut -f1))"
```

- [ ] **Step 4: Прогнать тест**

Run: `.venv/bin/python -m pytest tests/test_chat_report.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Коммит**

```bash
chmod +x tools/backup_db.sh
git add tools/ tests/test_chat_report.py
git commit -m "Скрипты для сервера: дамп базы и отчёт по чатам"
```

---

### Task 6: классификатор таблиц

**Files:**
- Create: `tools/classify_tables.py`
- Test: `tests/test_classify_tables.py`

**Interfaces:**
- Consumes: исходники `db.py` и `bot.py` (работает статически, без базы).
- Produces: `tools/classify_tables.py` печатает три списка — «оставить
  колонку», «убрать колонку», «спорные».

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_classify_tables.py
"""Классификатор таблиц: у кого чат один, у кого правда два.

Ошибка здесь стоит смешанных данных двух чатов без пути назад, поэтому
проверяется не «работает», а конкретные решения на понятных примерах.
"""
from tools import classify_tables


def test_таблицы_людей_остаются_с_колонкой():
    """В чат заявок бот пишет участников и их сообщения — там чатов два."""
    for таблица in ("known_users", "current_users", "message_stats",
                    "message_daily"):
        assert classify_tables.решение(таблица) == "оставить", таблица


def test_игровые_таблицы_теряют_колонку():
    """Играть в чате заявок нельзя: заслон пускает туда только ответы админов
    и кнопки заявок."""
    for таблица in ("economy_wallets", "farm_plots", "casino_wallets",
                    "businesses", "user_pets", "fishing_stats"):
        assert classify_tables.решение(таблица) == "убрать", таблица


def test_неизвестная_таблица_идёт_в_спорные():
    """Молчаливое «убрать» для незнакомой таблицы — это и есть тот самый
    риск смешать данные."""
    assert classify_tables.решение("таблица_которой_нет") == "спорные"
```

- [ ] **Step 2: Прогнать и убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_classify_tables.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.classify_tables'`

- [ ] **Step 3: Написать классификатор**

```python
# tools/classify_tables.py
"""Кому из таблиц нужен chat_id, а кому нет.

Правило: колонка остаётся тогда и только тогда, когда в таблицу пишет код,
достижимый из ОБОИХ чатов. В чат заявок заслон (bot.chat_scope_allows)
пропускает только ответы админов заявителю и нажатия кнопок, поэтому играть
там нельзя — вся экономика, занятия и социальное одночатовые.

Незнакомая таблица попадает в «спорные», а не в «убрать»: молчаливое решение
за человека здесь стоит смешанных данных двух чатов без пути назад.

Запуск: .venv/bin/python -m tools.classify_tables
"""

from __future__ import annotations

import pathlib
import re

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent

# Таблицы, которые пишутся в обоих чатах. Список явный, потому что это
# решение, а не вывод: участники, их имена, счётчики сообщений, модерация,
# заявки и журналы живут и в чате заявок.
ОБА_ЧАТА = {
    "known_users", "current_users", "message_stats", "message_daily",
    "message_hourly", "nicknames", "call_signs", "mutes", "warns",
    "bot_data", "logs", "auto_delete_targets", "chat_rules",
}

# Признаки одночатовых областей — по имени таблицы. Игра и экономика в чате
# заявок недоступны.
ОДИН_ЧАТ = re.compile(
    r"wallet|coin|bank|credit|stock|market|shop|inventory|item|business|"
    r"invest|casino|lootbox|farm|fish|profession|pet|craft|treasure|robbery|"
    r"collector|relation|marriage|family|clan|reputation|gift|profile_card|"
    r"title|achievement|duel|racing|season|club|voodoo|propose|subscription|"
    r"earning|daily_article"
)


def таблицы_с_колонкой() -> list[str]:
    """Таблицы, у которых в схеме есть chat_id."""
    db = (КОРЕНЬ / "db.py").read_text(encoding="utf-8")
    найдено = []
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)", db):
        имя = m.group(1)
        кусок = db[m.start():m.start() + 2000]
        конец = кусок.find(")\"")
        if "chat_id" in (кусок[:конец] if конец > 0 else кусок):
            найдено.append(имя)
    # ALTER TABLE ... ADD COLUMN chat_id — тоже считается.
    найдено += re.findall(r'_add_column_if_missing\("(\w+)", "chat_id"', db)
    return sorted(set(найдено))


def решение(таблица: str) -> str:
    if таблица in ОБА_ЧАТА:
        return "оставить"
    if ОДИН_ЧАТ.search(таблица):
        return "убрать"
    return "спорные"


def main() -> None:
    итог: dict[str, list[str]] = {"оставить": [], "убрать": [], "спорные": []}
    for таблица in таблицы_с_колонкой():
        итог[решение(таблица)].append(таблица)
    for имя in ("оставить", "убрать", "спорные"):
        print(f"\n=== {имя} ({len(итог[имя])}) ===")
        for таблица in итог[имя]:
            print(" ", таблица)
    print("\nСпорные решаются человеком до этапа 4 — молчаливое «убрать» "
          "смешает данные двух чатов.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Прогнать тест и сам классификатор**

```bash
.venv/bin/python -m pytest tests/test_classify_tables.py -q
.venv/bin/python -m tools.classify_tables
```
Expected: тесты PASS; классификатор печатает три списка.

- [ ] **Step 5: Коммит**

```bash
git add tools/classify_tables.py tests/test_classify_tables.py
git commit -m "Классификатор таблиц: кому нужен chat_id, а кому нет"
```

---

### Task 7: отчёт владельцу и остановка перед необратимым

**Files:**
- Create: `docs/superpowers/reports/2026-08-02-single-chat-stage-a.md`

**Interfaces:**
- Consumes: вывод `tools/classify_tables.py` из Task 6.
- Produces: отчёт со списками таблиц и инструкцией, что запустить на сервере.

- [ ] **Step 1: Собрать отчёт**

```bash
mkdir -p docs/superpowers/reports
{
  echo "# Этап А: что сделано и что решать"
  echo
  echo "## Классификация таблиц"
  echo '```'
  .venv/bin/python -m tools.classify_tables
  echo '```'
  echo
  echo "## Запустить на сервере (базы в среде разработки нет)"
  echo
  echo '```bash'
  echo "bash tools/backup_db.sh                      # дамп ДО всего"
  echo ".venv/bin/python -m tools.chat_report        # кто где лежит"
  echo '```'
  echo
  echo "## Решения владельца"
  echo
  echo "1. Утвердить список «убрать колонку» (или перенести отдельные"
  echo "   таблицы в «оставить»)."
  echo "2. Спорные таблицы — по каждой решение отдельно."
  echo "3. Третий чат: удалять его строки целиком или оставить?"
  echo "4. Позывные и мут чата заявок (7 и 1 строка по дампу) — нужны?"
  echo
  echo "До ответов этап 4 (DROP COLUMN) не выполняется: он необратим."
} > docs/superpowers/reports/2026-08-02-single-chat-stage-a.md
```

- [ ] **Step 2: Коммит**

```bash
git add docs/superpowers/reports/
git commit -m "Отчёт этапа А: что вычищать и что запустить на сервере"
```

- [ ] **Step 3: Остановиться**

План Б (этапы 4–6) пишется только после утверждения списка. Необратимый шаг
без утверждения не делается.

---

## Проверка плана по спеке

| Требование спеки | Задача |
|---|---|
| Этап 0: дамп | Task 5 (`tools/backup_db.sh`) |
| Этап 1: `chats.py` | Task 1 |
| Этап 1: панель пускает только рабочий чат | Task 2 |
| Этап 1: эндпоинты без `chat_id` | Task 3 |
| Этап 1: экраны без выбора чата | Task 4 |
| Этап 2: отчёт по данным | Task 5 (`tools/chat_report.py`) |
| Этап 2: удаление третьего чата | Task 7 — решение владельца |
| Этап 3: классификация | Task 6 |
| Заслон «эндпоинты не принимают chat_id» | Task 3, Step 1 |
| Заслон «`chats.py` — единственный источник» | вводится в План Б вместе с
  переводом ста семи мест в `bot.py` |
