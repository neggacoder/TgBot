# Долги и коллекторы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать долгу понятный срок, коллектора и объяснимый минус вместо внезапного списания по непредсказуемому порогу.

**Architecture:** Правила — в новом чистом модуле `collectors.py` (без БД и Telegram). Фоновый цикл `bank_penalty_loop` в `bot.py` спрашивает у модуля, что делать с каждым просроченным кредитом, и делает. Существующая ветка принудительного списания не переписывается — меняется только повод её срабатывания.

**Tech Stack:** Python 3.12, aiomysql, pytest.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-28-debt-collector-design.md`.
- Тесты запускаются ТОЛЬКО из venv: `.venv/bin/python -m pytest` (сейчас 2155 проходят).
- `collectors.py` — ЧИСТЫЙ модуль: без `db`, без `aiogram`, без `bot`. Как `pets.py`, `farming.py`, `market.py` рядом.
- Все тексты для человека — по-русски.
- Комментарии объясняют ПОЧЕМУ так, а не что делает строка.
- Сообщения коммитов — по-русски, с объяснением причины, с трейлером `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Существующие тесты — сетка, правка их под новый код запрещена.
- Ветка `gifts-and-debts`, worktree не создавать.
- Пеня после взыскания начисляться не должна НИКОГДА: это единственное место, где ошибка делает игру безвыходной.

---

## Файловая структура

| Файл | Ответственность |
|---|---|
| `collectors.py` (создать) | Ступень коллектора, повод взыскания, тексты |
| `db.py` (дописать) | Две колонки настроек + чтение/запись, отметка визита |
| `bot.py` (править) | `bank_penalty_loop` спрашивает модуль; кошелёк объясняет минус; кредит не дают при минусе |
| `chat_settings.py` (дописать) | Две новые настройки в реестр веб-панели |
| `tests/test_collectors.py` (создать) | Чистые правила |
| `tests/test_debt_collection.py` (создать) | Взыскание и цикл на заглушке БД |

---

### Task 1: Чистые правила — `collectors.py`

**Files:**
- Create: `collectors.py`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Consumes: ничего
- Produces: `Stage`, `STAGES`, `stage_for(visits)`, `should_visit(overdue_days, after_days, last_visit_days)`, `should_seize(overdue_days, seize_after_days, debt, principal)`, `visit_text(stage, mention, debt)`, `SEIZE_DEBT_MULTIPLIER`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_collectors.py`:

```python
"""Правила коллектора: когда приходить и когда взыскивать.

Числа и тексты без БД и телеграма — как pets.py и farming.py рядом.
Фоновый цикл ходит по всем чатам сразу, поэтому ошибка в этих правилах
бьёт по всем и разом; их и проверяем отдельно от цикла.
"""

from __future__ import annotations

import pytest

import collectors


def test_ступени_идут_по_нарастающей():
    """Первый визит вежливый, последний наглый. Порядок — часть замысла."""
    assert len(collectors.STAGES) >= 3
    assert [s.visits for s in collectors.STAGES] == sorted(s.visits for s in collectors.STAGES)


@pytest.mark.parametrize("visits,ожидаем", [(0, 0), (1, 0), (2, 1), (5, len(collectors.STAGES) - 1)])
def test_ступень_по_числу_визитов(visits, ожидаем):
    assert collectors.STAGES.index(collectors.stage_for(visits)) == ожидаем


def test_ступень_не_выходит_за_последнюю():
    """Сто визитов — та же наглость, что и на последней ступени, а не сбой."""
    assert collectors.stage_for(100) is collectors.STAGES[-1]


def test_у_каждой_ступени_есть_чем_сказать():
    for stage in collectors.STAGES:
        assert stage.texts, stage.key
        for text in stage.texts:
            assert "{кто}" in text, f"{stage.key}: некому адресовать"
            assert "{долг}" in text, f"{stage.key}: не названа сумма"


def test_текст_подставляет_имя_и_сумму():
    text = collectors.visit_text(collectors.STAGES[0], "@вася", 1234)
    assert "@вася" in text and "1234" in text
    assert "{" not in text, "плейсхолдер остался неподставленным"


# --- когда приходить -------------------------------------------------------

def test_коллектор_не_идёт_раньше_срока():
    assert not collectors.should_visit(overdue_days=0, after_days=1, last_visit_days=None)


def test_первый_визит_после_срока():
    assert collectors.should_visit(overdue_days=1, after_days=1, last_visit_days=None)


def test_не_чаще_раза_в_сутки():
    assert not collectors.should_visit(overdue_days=5, after_days=1, last_visit_days=0)
    assert collectors.should_visit(overdue_days=5, after_days=1, last_visit_days=1)


def test_ноль_выключает_коллектора():
    """Чату, которому это не нужно, банк остаётся прежним."""
    assert not collectors.should_visit(overdue_days=99, after_days=0, last_visit_days=None)


# --- когда взыскивать ------------------------------------------------------

def test_взыскание_по_сроку():
    assert collectors.should_seize(overdue_days=5, seize_after_days=5, debt=100, principal=1000)
    assert not collectors.should_seize(overdue_days=4, seize_after_days=5, debt=100, principal=1000)


def test_взыскание_по_росту_долга_втрое():
    """Старый повод остаётся: при большой пене долг утроится раньше срока,
    и ждать в этом случае незачем."""
    assert collectors.should_seize(overdue_days=1, seize_after_days=5, debt=3000, principal=1000)
    assert not collectors.should_seize(overdue_days=1, seize_after_days=5, debt=2999, principal=1000)


def test_ноль_выключает_только_срок_а_не_рост():
    """Выключенный срок не должен делать долг вечным: порог по росту
    остаётся последней защитой."""
    assert not collectors.should_seize(overdue_days=99, seize_after_days=0, debt=100, principal=1000)
    assert collectors.should_seize(overdue_days=99, seize_after_days=0, debt=3000, principal=1000)


def test_без_известной_суммы_кредита_работает_только_срок():
    """principal=None бывает у старых записей — не повод взыскать внезапно."""
    assert not collectors.should_seize(overdue_days=1, seize_after_days=5, debt=999999, principal=None)
    assert collectors.should_seize(overdue_days=5, seize_after_days=5, debt=999999, principal=None)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_collectors.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'collectors'`

- [ ] **Step 3: Написать модуль**

Создать `collectors.py`:

```python
"""Коллектор: когда приходить к должнику и когда взыскивать.

Здесь только правила и тексты, без БД и телеграма — как pets.py и farming.py
рядом. Причина не в чистоте ради чистоты: фоновый цикл ходит по всем чатам
сразу, и ошибка в этих правилах бьёт по всем разом. Отдельный модуль можно
проверить арифметикой, не поднимая ни базы, ни бота.

Порог «долг вырос втрое» существовал в боте и раньше, но был единственным:
он зависит от ставки пени и размера кредита, поэтому человек не мог
предсказать, когда за ним придут. Теперь рядом стоит понятный срок в днях, а
старый порог остаётся последней защитой на случай, когда пеня раздувает долг
быстрее срока.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

# Во сколько раз долг должен превысить взятую сумму, чтобы взыскать не
# дожидаясь срока. Число досталось от прежней реализации — меняя его,
# помните, что оно меняет поведение уже выданных кредитов.
SEIZE_DEBT_MULTIPLIER = 3


@dataclass(frozen=True)
class Stage:
    key: str
    visits: int          # с какого визита ступень действует
    texts: tuple[str, ...]


# Ступени по нарастающей: первый визит вежливый, дальше хуже. Несколько
# текстов на ступень, чтобы коллектор не повторялся дословно — иначе его
# перестают читать после второго раза.
STAGES: tuple[Stage, ...] = (
    Stage("polite", 0, (
        "💼 {кто}, напоминаем: за вами долг {долг} i¢. Банк пока вежлив.",
        "💼 {кто}, срок по кредиту вышел. Долг — {долг} i¢. Ждём.",
    )),
    Stage("firm", 2, (
        "📿 {кто}, долг {долг} i¢ никуда не делся. Банк начинает нервничать.",
        "📿 {кто}, {долг} i¢ висят на вас уже неприлично долго.",
    )),
    Stage("rude", 4, (
        "🔨 {кто}, {долг} i¢. Мы знаем, где вы пишете сообщения.",
        "🔨 {кто}, долг {долг} i¢. Дальше будет опись имущества, и это не шутка.",
    )),
)


def stage_for(visits: int) -> Stage:
    """Ступень по числу уже сделанных визитов. Сверх последней не растёт."""
    подходящие = [s for s in STAGES if visits >= s.visits]
    return подходящие[-1] if подходящие else STAGES[0]


def visit_text(stage: Stage, mention: str, debt: int) -> str:
    return random.choice(stage.texts).replace("{кто}", mention).replace("{долг}", str(debt))


def should_visit(overdue_days: int, after_days: int,
                 last_visit_days: Optional[int]) -> bool:
    """Пора ли коллектору прийти.

    after_days == 0 — чат выключил коллектора совсем, и это не повод молча
    считать «значит сразу»: банк остаётся таким, каким был.
    """
    if after_days <= 0 or overdue_days < after_days:
        return False
    return last_visit_days is None or last_visit_days >= 1


def should_seize(overdue_days: int, seize_after_days: int,
                 debt: int, principal: Optional[int]) -> bool:
    """Пора ли взыскивать. Срабатывает то из двух, что наступит раньше.

    principal бывает неизвестен у старых записей — тогда остаётся только
    срок: внезапно взыскать по неизвестной сумме было бы нечестно.
    """
    if seize_after_days > 0 and overdue_days >= seize_after_days:
        return True
    return bool(principal) and debt >= principal * SEIZE_DEBT_MULTIPLIER
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_collectors.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add collectors.py tests/test_collectors.py
git commit -m "$(cat <<'EOF'
Правила коллектора отдельным модулем

Порог взыскания был один — «долг вырос втрое», — и он зависит от ставки
пени и размера кредита. Предсказать, когда за тобой придут, человек не
мог. Рядом появляется понятный срок в днях; старый порог остаётся
последней защитой, когда пеня раздувает долг быстрее срока.

Правила вынесены в чистый модуль не ради чистоты: фоновый цикл ходит по
всем чатам сразу, ошибка в них бьёт по всем разом, а отдельный модуль
проверяется арифметикой без базы и бота.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Настройки чата и отметка визита

**Files:**
- Modify: `db.py`
- Modify: `chat_settings.py`
- Test: `tests/test_debt_collection.py` (создать)

**Interfaces:**
- Consumes: `collectors` из Task 1
- Produces: колонки `collector_after_days`, `seize_after_days`, `credit_last_visit_at`, `credit_visits`; функции `db.mark_credit_visit(chat_id, user_id)`; настройки `bank.collector_after_days`, `bank.seize_after_days` в реестре

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_debt_collection.py`:

```python
"""Взыскание долга: настройки, отметка визитов, поведение цикла."""

from __future__ import annotations

import inspect
import os

import pytest

import chat_settings

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402


def test_настройки_коллектора_есть_в_реестре():
    """Без строки в реестре настройка не появится в веб-панели, и админ
    будет думать, что её нет."""
    assert "bank.collector_after_days" in chat_settings.BY_KEY
    assert "bank.seize_after_days" in chat_settings.BY_KEY


@pytest.mark.parametrize("key", ["bank.collector_after_days", "bank.seize_after_days"])
def test_настройка_привязана_к_банковской_команде(key):
    setting = chat_settings.BY_KEY[key]
    assert setting.command_key == "bank_manage"
    assert setting.group == "Банк"
    assert setting.minimum == 0, "ноль обязан быть допустим — им выключают"


@pytest.mark.parametrize("column", [
    "collector_after_days", "seize_after_days",
])
def test_колонки_настроек_заведены(column):
    источник = inspect.getsource(db_module)
    начало = источник.index("CREATE TABLE IF NOT EXISTS bank_settings (")
    кусок = источник[начало:источник.index(") ENGINE=", начало)]
    assert column in кусок, f"{column} нет в определении bank_settings"


@pytest.mark.parametrize("column", ["credit_last_visit_at", "credit_visits"])
def test_колонки_визитов_заведены(column):
    источник = inspect.getsource(db_module)
    assert f'"{column}' in источник or f"'{column}" in источник, column


def test_есть_чем_отметить_визит():
    assert hasattr(db_module, "mark_credit_visit")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py -q`
Expected: FAIL, `assert 'bank.collector_after_days' in ...`

- [ ] **Step 3: Завести колонки в `db.py`**

В `ensure_bank_tables` (там, где создаётся `bank_settings`) добавить в CREATE две колонки:

```
"collector_after_days INT NOT NULL DEFAULT 1, "
"seize_after_days INT NOT NULL DEFAULT 5, "
```

и рядом, для уже существующих чатов, — досоздание через уже имеющийся `_add_column_if_missing`:

```python
    # Досоздаём для чатов, где таблица уже есть: без этого настройка
    # появилась бы только у новых чатов, а старые молча остались бы без неё.
    await _add_column_if_missing("bank_settings", "collector_after_days",
                                 "INT NOT NULL DEFAULT 1")
    await _add_column_if_missing("bank_settings", "seize_after_days",
                                 "INT NOT NULL DEFAULT 5")
    await _add_column_if_missing("bank_accounts", "credit_last_visit_at",
                                 "DATETIME NULL")
    await _add_column_if_missing("bank_accounts", "credit_visits",
                                 "INT NOT NULL DEFAULT 0")
```

- [ ] **Step 4: Добавить отметку визита в `db.py`**

Рядом с `apply_bank_credit_penalty`:

```python
async def mark_credit_visit(chat_id: int, user_id: int) -> int:
    """Отметить визит коллектора. Возвращает, каким по счёту он вышел.

    Счётчик живёт на самом кредите, поэтому обнуляется вместе с ним: новый
    кредит — новый разговор, а не продолжение старого.
    """
    await _execute(
        "UPDATE bank_accounts SET credit_visits = credit_visits + 1, "
        "credit_last_visit_at = UTC_TIMESTAMP() WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    row = await _fetchone(
        "SELECT credit_visits FROM bank_accounts WHERE chat_id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return int(row["credit_visits"]) if row else 0
```

Также расширить выборку просроченных, чтобы цикл видел настройки и визиты:
в `list_overdue_bank_credits` в `SELECT` добавить `bs.collector_after_days, bs.seize_after_days`.

- [ ] **Step 5: Добавить настройки в реестр веб-панели**

В `chat_settings.py`, в группу «Банк», рядом с остальными настройками банка:

```python
    Setting("bank.collector_after_days", "Банк", "bank_manage",
            "Коллектор приходит через, дней просрочки",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "collector_after_days",
            default=1, minimum=0, maximum=365,
            hint="0 — коллектор не приходит совсем."),
    Setting("bank.seize_after_days", "Банк", "bank_manage",
            "Взыскание через, дней просрочки",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "seize_after_days",
            default=5, minimum=0, maximum=365,
            hint="0 — по сроку не взыскивать. Долг всё равно взыщут, если "
                 "вырастет втрое от взятой суммы."),
```

Поправить в том же файле тест числа настроек: их станет 25 вместо 23 — это `tests/test_chat_settings.py`, проверка `len(chat_settings.SETTINGS) == 23`.

- [ ] **Step 6: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py tests/test_chat_settings.py -q`
Expected: PASS

- [ ] **Step 7: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Коммит**

```bash
git add db.py chat_settings.py tests/test_debt_collection.py tests/test_chat_settings.py
git commit -m "$(cat <<'EOF'
Сроки коллектора и взыскания — настройки чата, а не число в коде

Порог взыскания был зашит в bot.py константой, и чат не мог ни смягчить
его, ни выключить. Обе настройки заводятся в bank_settings рядом с
остальными и сразу попадают в веб-панель через общий реестр.

Колонки досоздаются и для чатов, где таблица уже есть: иначе настройка
появилась бы только у новых, а старые молча остались бы без неё.

Счётчик визитов живёт на самом кредите и обнуляется вместе с ним — новый
кредит это новый разговор, а не продолжение старого.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Коллектор приходит, взыскание по сроку

**Files:**
- Modify: `bot.py` (`bank_penalty_loop`)
- Modify: `tests/test_debt_collection.py`

**Interfaces:**
- Consumes: `collectors` (Task 1), `db.mark_credit_visit` и новые колонки (Task 2)
- Produces: изменённое поведение цикла

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_debt_collection.py`:

```python
# --- поведение цикла -------------------------------------------------------

def test_цикл_спрашивает_правила_а_не_считает_сам():
    """Числа и пороги живут в collectors. Посчитай цикл сам — правила
    раздвоятся, и проверить их без базы станет нельзя."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "collectors.should_seize" in src
    assert "collectors.should_visit" in src


def test_порог_втрое_больше_не_зашит_в_цикле():
    """Он переехал в collectors.SEIZE_DEBT_MULTIPLIER; оставшаяся копия
    разошлась бы с ним молча."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "* 3" not in src.replace(" ", "").replace("*3", "* 3")


def test_взыскание_закрывает_кредит_и_пеня_больше_не_капает():
    """Единственное место, где ошибка делает игру безвыходной: если после
    взыскания долг остаётся, пеня растёт быстрее любого заработка."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "reduce_bank_credit_debt" in src, "долг обязан обнуляться"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py -q`
Expected: FAIL, `assert 'collectors.should_seize' in src`

- [ ] **Step 3: Переписать тело цикла**

В `bot.py`, в `bank_penalty_loop`, заменить вычисление порога и добавить визит.
Внутри цикла по `rows`, после проверки `event_flag`:

```python
                overdue_days = _days_since(row.get("credit_due_at"))
                debt = int(row["credit_debt"])
                principal = row.get("credit_amount")

                if collectors.should_seize(
                        overdue_days, int(row.get("seize_after_days") or 0),
                        debt, principal):
                    await _seize_debt(chat_id, user_id, debt)
                    continue

                if collectors.should_visit(
                        overdue_days, int(row.get("collector_after_days") or 0),
                        _days_since(row.get("credit_last_visit_at"))):
                    visits = await db.mark_credit_visit(chat_id, user_id)
                    stage = collectors.stage_for(visits - 1)
                    try:
                        await bot.send_message(
                            chat_id,
                            collectors.visit_text(stage, mention_id(user_id), debt))
                    except Exception as exc:
                        log_suppressed("bank_penalty_loop", exc)
```

Существующую ветку «пеня превысила 200%» вынести в `_seize_debt`, не меняя её
содержания, и добавить рядом помощника:

```python
def _days_since(moment) -> int:
    """Сколько полных суток прошло. None — считаем, что нисколько."""
    if not moment:
        return 0
    return max(0, (datetime.utcnow() - moment).days)


async def _seize_debt(chat_id: int, user_id: int, debt: int) -> None:
    """Взыскание: долг уходит из банка в кошелёк, возможно в минус.

    Кредит закрывается здесь же, и это не деталь: пока он открыт, пеня
    продолжает капать, а минус растёт быстрее любого заработка — выбраться
    станет невозможно.
    """
    await db.reduce_bank_credit_debt(chat_id, user_id, debt)
    await db.add_coins(chat_id, user_id, -debt)
    warn_count = await db.add_warn(
        chat_id, user_id, 0, "Просрочка кредита — взыскание",
        datetime.utcnow() + WARN_DEFAULT_DURATION)
    try:
        await bot.send_message(
            chat_id,
            f"🚨 {mention_id(user_id)}, долг {debt} i¢ взыскан принудительно — "
            f"баланс мог уйти в минус. Пока он отрицательный, покупать нельзя, "
            f"а любой заработок идёт в счёт долга. Предупреждение "
            f"({warn_count}/{WARN_LIMIT}).")
    except Exception as exc:
        log_suppressed("_seize_debt", exc)
    await db.add_log("bank_credit_force_collected", chat_id=chat_id,
                     target_id=user_id, details=str(debt))
```

Добавить `import collectors` к остальным импортам в `bot.py`.

- [ ] **Step 4: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py -q`
Expected: PASS

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add bot.py tests/test_debt_collection.py
git commit -m "$(cat <<'EOF'
Коллектор приходит, а взыскание получило понятный срок

Раньше должника не трогали вовсе, а потом однажды списывали всё разом по
порогу, который он не мог предсказать: тот зависел от ставки пени и
размера кредита. Теперь сначала приходит коллектор с нарастающей
наглостью, а взыскание наступает по сроку из настроек чата.

Взыскание вынесено в свою функцию и закрывает кредит — это не деталь:
пока он открыт, пеня капает, минус растёт быстрее заработка, и выбраться
становится невозможно.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Минус объяснён человеку, кредит при минусе не дают

**Files:**
- Modify: `bot.py` (кошелёк, выдача кредита)
- Modify: `tests/test_debt_collection.py`

**Interfaces:**
- Consumes: всё предыдущее
- Produces: ничего для других задач

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_debt_collection.py`:

```python
def test_кошелёк_объясняет_минус():
    """Отрицательный баланс без пояснения читается как поломка бота."""
    src = inspect.getsource(bot_module._farm_balance_text)
    assert "coins" in src
    assert "взыскан" in src.lower() or "долг" in src.lower(), (
        "в кошельке нет объяснения, откуда минус")


def test_кредит_при_минусе_не_дают():
    src = inspect.getsource(bot_module.cmd_bank_credit)
    assert "< 0" in src or "минус" in src.lower(), (
        "кредит выдаётся поверх непогашенного взыскания")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py -q`
Expected: FAIL на обоих новых тестах

- [ ] **Step 3: Объяснить минус в кошельке**

В `_farm_balance_text` в `bot.py`, там где формируется строка с коинами,
добавить пояснение при отрицательном балансе:

```python
    coins = int(wallet.get("coins", 0))
    if coins < 0:
        lines.append(
            f"🚨 Долг: <b>{-coins}</b> i¢ взыскан по кредиту. Пока баланс "
            f"отрицательный, покупать нельзя, а любой заработок идёт в счёт "
            f"долга — как выйдете в ноль, всё закончится само.")
```

- [ ] **Step 4: Не давать кредит при минусе**

В `cmd_bank_credit`, среди проверок перед выдачей:

```python
    wallet = await db.get_wallet(chat_id, user_id)
    if int(wallet.get("coins") or 0) < 0:
        await message.reply(
            "🚨 За вами уже взыскан долг — баланс отрицательный. "
            "Новый кредит дадут, когда выйдете в ноль.")
        return
```

- [ ] **Step 5: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/test_debt_collection.py -q`
Expected: PASS

- [ ] **Step 6: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add bot.py tests/test_debt_collection.py
git commit -m "$(cat <<'EOF'
Минус в кошельке объяснён, и поверх него кредит не дают

Отрицательный баланс без единого слова читается как поломка бота:
человек видит минус и не понимает ни откуда он, ни что с ним делать.
Теперь кошелёк говорит, что это взыскание, и чем оно кончится.

Новый кредит поверх непогашенного взыскания — способ уйти в минус вдвое
и не выбраться никогда.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Справка

**Files:**
- Modify: `help_texts.py`
- Modify: `docs/superpowers/specs/2026-07-28-debt-collector-design.md`

- [ ] **Step 1: Найти раздел справки про банк**

Run: `grep -n '"bank"\|Банк' help_texts.py | head`
Expected: находится подраздел банка

- [ ] **Step 2: Дописать абзац**

Добавить в найденный подраздел:

```python
                        "\n\n🚨 <b>Если не платить:</b> через сутки просрочки "
                        "приходит коллектор и напоминает в чат, дальше — всё "
                        "настойчивее. Через пять дней долг взыскивают "
                        "принудительно: он списывается с баланса целиком, даже "
                        "если баланс уходит в минус. Пока баланс отрицательный, "
                        "покупать нельзя, а любой заработок идёт в счёт долга — "
                        "как выйдете в ноль, всё закончится само. Пеня после "
                        "взыскания не начисляется. Сроки настраиваются: "
                        "«банк коллектор {дней}» и «банк взыскание {дней}»."
```

- [ ] **Step 3: Прогнать тесты справки**

Run: `.venv/bin/python -m pytest tests/test_help_texts_accuracy.py tests/test_help_length.py -q`
Expected: PASS. Если раздел перерос 4096 символов — разделить надвое, как уже сделано с `pets_own`/`pets_more`.

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add help_texts.py docs/
git commit -m "$(cat <<'EOF'
Справка: что бывает, если не платить по кредиту

Про пеню в справке было, про коллектора и взыскание — ничего. Человек
узнавал о минусе на балансе в тот момент, когда его уже взыскали.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Что НЕ входит

- **Выкуп чужого долга соседом** — следующая работа, требует учёта «кто кому должен».
- **Опись имущества** (изъятие бизнесов и питомцев) — коллектор про неё угрожает, но её нет; это отдельное решение, и делать его молча нельзя.
- **Команды правки новых настроек в чате** (`банк коллектор {дней}`) — если их не окажется в `bank_manage`, настройки правятся только через веб-панель; проверить при выполнении Task 2 и, если команд нет, добавить их там же.

## Порядок и зависимости

```
Task 1 (правила) ──> Task 2 (настройки и колонки) ──> Task 3 (цикл) ──> Task 4 (минус) ──> Task 5 (справка)
```

Строго последовательно: каждая следующая опирается на предыдущую.
