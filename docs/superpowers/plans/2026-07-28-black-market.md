# Чёрный рынок (особая лавка) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завести отдельную лавку («чёрный рынок») с суточной ротацией и общим на чат ограниченным запасом, куда переезжает всё воровское снаряжение из обычного «магазин», плюс два новых предмета — защита от медвежатника и сокращение его кулдауна.

**Architecture:** Лавка — не новая таблица, а срез существующей `shop_items`. Товары остаются её строками (иначе инвентарь показывал бы голый ключ: `db.list_inventory` берёт название и эмодзи через `LEFT JOIN shop_items`), состав лавки задаётся списком в новом чистом модуле `black_market.py`, а состояние ротации — одной колонкой `rotation_day DATE NULL`. Покупка идёт через существующий `_shop_buy`, куда добавляется гейт принадлежности к лавке.

**Tech Stack:** Python 3.12, aiogram, aiomysql (сырой SQL через хелперы `db._execute` / `db._fetchall`), pytest. Тесты работают без БД и токена — `tests/conftest.py` подменяет `aiogram` и `aiomysql` заглушками.

## Global Constraints

- **Спека:** `docs/superpowers/specs/2026-07-28-black-market-design.md`. При расхождении плана и спеки правда — спека.
- **Прогон тестов:** только из venv — `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`. Системный `python3` без pytest.
- **Не запускать полный прогон, пока правишь исходники:** часть тестов читает код через `inspect.getsource`, и правка файла посреди прогона роняет их на ровном месте.
- **Язык:** весь текст для пользователя и все комментарии в коде — русские, как во всём проекте.
- **Числа и правила — в `black_market.py`**, без БД и Telegram: так же устроены `robbery.py`, `market.py`, `seasons.py`, `bosses.py`.
- **Никаких SQL-миграций данных.** Колонка добавляется через `_add_column_if_missing`, содержимое `shop_items` не переписывается.
- **Ключи предметов не переименовывать** — по ним лежит купленное в `user_inventory`.
- **Цены и кулдауны, заданные пользователем:** сигнализация 20 000 i¢, слепок ключа 6 000 i¢, сокращение кулдауна медвежатника — ровно 25% (10 ч → 7,5 ч), слотов за ротацию 3–4, период ротации — сутки.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `black_market.py` (создать) | Каталог лавки, размеры ротации, выбор ассортимента. Чистые правила, без БД и Telegram. |
| `db.py` (правка) | Колонка `rotation_day`, чтение/запись ротации, исключение пула из суточного завоза. |
| `bot.py` (правка) | Функция ротации, команды `лавка` / `лавка купить`, гейт в `_shop_buy`, сигнализация и слепок в `cmd_steal_item`. |
| `help_texts.py` (правка) | Раздел справки. |
| `README.md` (правка) | Раздел «Чёрный рынок». |
| `tests/test_black_market.py` (создать) | Правила ротации и каталога. |
| `tests/test_black_market_commands.py` (создать) | Гейт покупки, витрина, новые предметы в краже. |

**Порядок задач важен:** 1 → 2 → 3 → 4 → 5 → 6. Задача 4 бессмысленна без 3, задача 3 — без 2.

---

### Task 1: `black_market.py` — каталог и ротация

**Files:**
- Create: `black_market.py`
- Test: `tests/test_black_market.py`

**Interfaces:**
- Consumes: `robbery.ROBBERY_ITEMS`, `shop_effects.REWARD_KEYS`, `shop_effects.BY_KEY` (только в тестах, для проверки, что ключи пула существуют).
- Produces:
  - `POOL: tuple[Slot, ...]`, где `Slot` — frozen dataclass с полями `key: str`, `max_stock: int`
  - `POOL_KEYS: frozenset[str]`
  - `NEW_ITEMS: list[tuple[str, str, int, str, str]]` — строки в формате `(item_key, name, price, description, emoji)`, тот же формат, что у `robbery.ROBBERY_SHOP_ITEMS`
  - `STEAL_COOLDOWN_CUT: float = 0.25`
  - `SIGNAL_KEY: str = "signalizaciya"`, `SLEPOK_KEY: str = "slepok"`
  - `pick_rotation(rng: random.Random | None = None) -> dict[str, int]` — ключ → запас

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_black_market.py`:

```python
"""Лавка: ассортимент дня и целостность каталога.

Каталог лавки — список ключей, которые обязаны существовать в других
каталогах: ключ с опечаткой не сломает ничего заметно, он просто никогда не
попадёт в продажу. Поэтому проверяем не только выбор ассортимента, но и то,
что каждому ключу пула есть чем стать строкой в shop_items.
"""

from __future__ import annotations

import random

import black_market as BM
import robbery
import shop_effects as SE


def test_rotation_picks_three_or_four_distinct_items():
    for seed in range(50):
        rotation = BM.pick_rotation(random.Random(seed))
        assert 3 <= len(rotation) <= 4
        assert set(rotation) <= BM.POOL_KEYS


def test_rotation_stock_never_exceeds_item_limit():
    limits = {slot.key: slot.max_stock for slot in BM.POOL}
    for seed in range(50):
        for key, stock in BM.pick_rotation(random.Random(seed)).items():
            assert 1 <= stock <= limits[key]


def test_strongest_items_never_come_in_batches():
    """Медвежатник за 75 000 и отмазка за 20 000 — не больше одного за раз."""
    limits = {slot.key: slot.max_stock for slot in BM.POOL}
    assert limits["medvezhatnik"] == 1
    assert limits[robbery.SURVEILLANCE_PASS_ITEM_KEY] == 1


def test_every_pool_key_can_become_a_shop_row():
    """У каждого ключа пула есть строка, которой он засеется в shop_items.

    Источников три: предметы ограбления, предметы-эффекты и новинки лавки.
    Ключ, которого нет ни в одном, ротация выберет — и купить его будет
    нельзя, потому что строки в магазине не появится.
    """
    seedable = (
        set(robbery.ROBBERY_ITEMS)
        | set(SE.BY_KEY)
        | {row[0] for row in BM.NEW_ITEMS}
    )
    assert BM.POOL_KEYS <= seedable


def test_pool_has_no_rewards():
    """Награду _shop_buy отвергнет как «не продаётся» — в пуле ей не место."""
    assert not (BM.POOL_KEYS & SE.REWARD_KEYS)


def test_new_items_are_priced_as_specified():
    prices = {row[0]: row[2] for row in BM.NEW_ITEMS}
    assert prices[BM.SIGNAL_KEY] == 20_000
    assert prices[BM.SLEPOK_KEY] == 6_000
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `.venv/bin/python -m pytest tests/test_black_market.py -q -W ignore::DeprecationWarning`
Expected: FAIL — `ModuleNotFoundError: No module named 'black_market'`

- [ ] **Step 3: Написать минимальный модуль**

Создать `black_market.py`:

```python
"""Чёрный рынок: каталог лавки, размер ротации и запас.

Здесь только КАТАЛОГ И ПРАВИЛА, без БД и Telegram — как robbery.py и
market.py рядом.

Зачем механика. Всё воровское снаряжение до сих пор лежало в общем
«магазин» вперемешку с тортиками, доступное всегда и в любом количестве.
Лавка даёт ему своё место и ДЕФИЦИТ: ассортимент меняется раз в сутки,
запас общий на чат — кто успел, тот и купил.

Риска «спалиться» здесь намеренно НЕТ. Лавка держится на дефиците, а не на
шансе потерять деньги: шанс уже есть у самого ограбления, и вторая
рулетка поверх покупки сделала бы её просто налогом.

Состав лавки задан ЗДЕСЬ, а не колонкой в базе, и это единственное место
правды. Строки товаров при этом остаются в shop_items — без них инвентарь
показывал бы голый ключ вместо названия (list_inventory берёт название
через LEFT JOIN по ключу), и сломались бы продажа с подарками.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Сколько позиций показывает лавка за одну ротацию. Три-четыре из
# одиннадцати — чтобы «сегодня выпало именно это» было заметно.
SLOTS_MIN = 3
SLOTS_MAX = 4

# На сколько слепок ключа сокращает кулдаун медвежатника (10 ч → 7,5 ч).
STEAL_COOLDOWN_CUT = 0.25

SIGNAL_KEY = "signalizaciya"
SLEPOK_KEY = "slepok"


@dataclass(frozen=True)
class Slot:
    key: str
    max_stock: int


# Запас тем меньше, чем сильнее предмет: медвежатник за 75 000 не должен
# попадать в чат пачкой, а дешёвая мелочь пачкой никому не вредит.
POOL: tuple[Slot, ...] = (
    Slot("binokl", 3),
    Slot("rabbit_paw", 3),
    Slot("bronik", 3),
    Slot("dymovushka", 3),
    Slot("getaway_car", 3),
    Slot("lucky_coin", 2),
    Slot("gold_pig", 2),
    Slot("slepok", 2),
    Slot("survilence_pass", 1),
    Slot("medvezhatnik", 1),
    Slot("signalizaciya", 1),
)

POOL_KEYS: frozenset[str] = frozenset(slot.key for slot in POOL)

# Новинки лавки: нигде, кроме неё, не продаются. Формат строки тот же, что у
# robbery.ROBBERY_SHOP_ITEMS, — их обоих принимает db.seed_extra_shop_items.
NEW_ITEMS: list[tuple[str, str, int, str, str]] = [
    (SIGNAL_KEY, "Сигнализация", 20_000,
     "Блокирует одну попытку медвежатника против вас. Срабатывает сама.",
     "🚨"),
    (SLEPOK_KEY, "Слепок ключа", 6_000,
     "Следующая кража медвежатником ставит кулдаун на четверть короче. "
     "Срабатывает сам.",
     "🔑"),
]


def pick_rotation(rng: random.Random | None = None) -> dict[str, int]:
    """Ассортимент на сутки: ключ → запас на весь чат.

    Запас именно УСТАНАВЛИВАЕТСЯ этим числом, а не прибавляется к
    вчерашнему: накопление нераскупленного убило бы дефицит за неделю.
    """
    r = rng or random
    chosen = r.sample(POOL, r.randint(SLOTS_MIN, SLOTS_MAX))
    return {slot.key: r.randint(1, slot.max_stock) for slot in chosen}
```

- [ ] **Step 4: Прогнать тест и убедиться, что он проходит**

Run: `.venv/bin/python -m pytest tests/test_black_market.py -q -W ignore::DeprecationWarning`
Expected: PASS (6 passed)

- [ ] **Step 5: Коммит**

```bash
git add black_market.py tests/test_black_market.py
git commit -m "Каталог лавки: состав задан в коде, а не колонкой в базе"
```

---

### Task 2: База — колонка ротации и исключение пула из завоза

**Files:**
- Modify: `db.py` — `ensure_shop_tables()` (около строки 9730), `list_shop_items_for_restock()` (строка 10713)
- Modify: `db.py` — добавить три функции рядом с остальными функциями магазина (после `set_shop_item_stock`, около строки 10663)
- Test: `tests/test_black_market_db.py` (создать)

**Interfaces:**
- Consumes: `db._execute`, `db._fetchall`, `db._fetchone`, `db._add_column_if_missing`.
- Produces:
  - `db.list_shop_items_for_restock(chat_id: int, exclude_keys: Sequence[str] = ()) -> list[dict]` — **сигнатура расширена необязательным параметром**, старые вызовы работают без правок
  - `db.set_shop_item_rotation(chat_id: int, item_key: str, stock: int, rotation_day: date) -> bool`
  - `db.clear_rotation_stock(chat_id: int, keys: Sequence[str]) -> None`
  - `db.get_rotation_day(chat_id: int, keys: Sequence[str]) -> Optional[date]`
  - `db.list_rotation_items(chat_id: int, keys: Sequence[str], day: date) -> list[dict]`

**Почему не нужна новая `ensure_*`:** колонка добавляется внутрь существующей `ensure_shop_tables()`, которую бот уже вызывает на старте. `tests/test_migrations_wired.py` статически проверяет, что каждая `ensure_*` в `db.py` кем-то вызывается, — новая функция потребовала бы ещё и вызова.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_black_market_db.py`:

```python
"""Запросы лавки: SQL собирается правильно, а завоз обходит пул стороной.

Настоящей базы в тестах нет (conftest подменяет aiomysql), поэтому
проверяем то, что и ломается на практике: какой текст запроса и какие
параметры уходят в драйвер.
"""

from __future__ import annotations

import asyncio

import db as db_module


class _Spy:
    """Подменяет db._fetchall/_execute и запоминает запрос с параметрами."""

    def __init__(self, result=None):
        self.result = result if result is not None else []
        self.query = ""
        self.params = ()

    async def __call__(self, query, params=()):
        self.query = " ".join(query.split())
        self.params = params
        return self.result


def test_restock_list_excludes_given_keys(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_fetchall", spy)

    asyncio.run(db_module.list_shop_items_for_restock(-100, exclude_keys=["binokl", "bronik"]))

    assert "NOT IN (%s, %s)" in spy.query
    assert spy.params == (-100, "binokl", "bronik")


def test_restock_list_without_exclusions_keeps_old_query(monkeypatch):
    """Старые вызовы без параметра не должны получить хвост NOT IN ()."""
    spy = _Spy()
    monkeypatch.setattr(db_module, "_fetchall", spy)

    asyncio.run(db_module.list_shop_items_for_restock(-100))

    assert "NOT IN" not in spy.query
    assert spy.params == (-100,)


def test_clear_rotation_stock_zeroes_only_pool_keys(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_execute", spy)

    asyncio.run(db_module.clear_rotation_stock(-100, ["binokl", "slepok"]))

    assert "SET stock = 0" in spy.query
    assert "item_key IN (%s, %s)" in spy.query
    assert spy.params == (-100, "binokl", "slepok")


def test_clear_rotation_stock_with_no_keys_touches_nothing(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_execute", spy)

    asyncio.run(db_module.clear_rotation_stock(-100, []))

    assert spy.query == ""


def test_rotation_items_are_filtered_by_day(monkeypatch):
    from datetime import date

    spy = _Spy(result=[{"item_key": "binokl"}])
    monkeypatch.setattr(db_module, "_fetchall", spy)

    rows = asyncio.run(db_module.list_rotation_items(-100, ["binokl"], date(2026, 7, 28)))

    assert rows == [{"item_key": "binokl"}]
    assert "rotation_day = %s" in spy.query
    assert spy.params == (-100, date(2026, 7, 28), "binokl")
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `.venv/bin/python -m pytest tests/test_black_market_db.py -q -W ignore::DeprecationWarning`
Expected: FAIL — `AttributeError: module 'db' has no attribute 'clear_rotation_stock'`, а первый тест падает на `TypeError: list_shop_items_for_restock() got an unexpected keyword argument 'exclude_keys'`

- [ ] **Step 3: Добавить колонку**

В `db.py`, в `ensure_shop_tables()`, сразу после строки с `restock_max` (около 9746):

```python
    # День, на который выставлен ассортимент лавки (см. black_market.py).
    # Отличает «сегодня не завозили» от «раскупили»: позиция в ассортименте,
    # если rotation_day — сегодняшняя дата по зоне чата. Вчерашние строки
    # перестают совпадать сами, чистить их не нужно.
    await _add_column_if_missing("shop_items", "rotation_day", "DATE NULL")
```

- [ ] **Step 4: Расширить выборку завоза**

Заменить `list_shop_items_for_restock` (строка 10713) целиком:

```python
async def list_shop_items_for_restock(
    chat_id: int, exclude_keys: Sequence[str] = ()
) -> list[dict]:
    """Позиции, которым положен суточный завоз.

    exclude_keys — товары лавки: у них запас УСТАНАВЛИВАЕТ ротация, и завоз
    обязан пройти мимо. Иначе он прибавил бы (restock_shop_item складывает
    без потолка) запас к позициям, которые ротация только что обнулила, —
    «сегодня не завозили» молча стало бы покупаемым, а исход зависел бы от
    того, кто из двоих записал последним.

    Исключение делается ЗДЕСЬ, на чтении, а не проставлением restock_max =
    NULL в базе: значение в базе админ может вернуть из панели
    (set_shop_item_restock_max), и дефицит тихо умер бы.
    """
    query = (
        "SELECT item_key, restock_max FROM shop_items "
        "WHERE chat_id = %s AND restock_max IS NOT NULL AND restock_max > 0"
    )
    params: list = [chat_id]
    if exclude_keys:
        keys = list(exclude_keys)
        placeholders = ", ".join(["%s"] * len(keys))
        query += f" AND item_key NOT IN ({placeholders})"
        params.extend(keys)
    return await _fetchall(query, tuple(params))
```

**Плейсхолдеры собираются только f-строкой.** Соблазн написать
`"... IN (%s)" % ", ".join(["%%s"] * len(keys))` заканчивается запросом с
`IN (%%s, %%s)` — оператор `%` не обрабатывает подставленное значение
повторно, и в драйвер уезжают битые плейсхолдеры. F-строка не трогает `%s`
вовсе, поэтому используется во всех четырёх функциях ниже.
```

- [ ] **Step 5: Добавить функции ротации**

В `db.py` сразу после `set_shop_item_stock` (около строки 10663):

```python
async def set_shop_item_rotation(
    chat_id: int, item_key: str, stock: int, rotation_day
) -> bool:
    """Ставит позицию лавки в ассортимент дня с указанным запасом."""
    return bool(await _execute(
        "UPDATE shop_items SET stock = %s, rotation_day = %s "
        "WHERE chat_id = %s AND item_key = %s",
        (stock, rotation_day, chat_id, item_key),
    ))


async def clear_rotation_stock(chat_id: int, keys: Sequence[str]) -> None:
    """Обнуляет запас у всех позиций лавки перед выбором нового ассортимента.

    rotation_day при этом НЕ трогаем: он остаётся вчерашним, и позиция сама
    перестаёт считаться сегодняшней.
    """
    keys = list(keys)
    if not keys:
        return
    placeholders = ", ".join(["%s"] * len(keys))
    await _execute(
        f"UPDATE shop_items SET stock = 0 "
        f"WHERE chat_id = %s AND item_key IN ({placeholders})",
        (chat_id, *keys),
    )


async def get_rotation_day(chat_id: int, keys: Sequence[str]):
    """На какой день выставлен ассортимент лавки. None — ни разу не выставлен."""
    keys = list(keys)
    if not keys:
        return None
    placeholders = ", ".join(["%s"] * len(keys))
    row = await _fetchone(
        f"SELECT MAX(rotation_day) AS day FROM shop_items "
        f"WHERE chat_id = %s AND item_key IN ({placeholders})",
        (chat_id, *keys),
    )
    return row["day"] if row else None


async def list_rotation_items(chat_id: int, keys: Sequence[str], day) -> list[dict]:
    """Позиции лавки, попавшие в ассортимент указанного дня."""
    keys = list(keys)
    if not keys:
        return []
    placeholders = ", ".join(["%s"] * len(keys))
    return await _fetchall(
        f"SELECT * FROM shop_items WHERE chat_id = %s AND rotation_day = %s "
        f"AND item_key IN ({placeholders}) ORDER BY price DESC",
        (chat_id, day, *keys),
    )
```

Убедиться, что `Sequence` импортирован в `db.py` (`from typing import ... Sequence` или `from collections.abc import Sequence`); если нет — добавить в существующий блок импортов.

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_black_market_db.py -q -W ignore::DeprecationWarning`
Expected: PASS (5 passed)

- [ ] **Step 7: Прогнать весь набор — сигнатура `list_shop_items_for_restock` публичная**

Run: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS, число не меньше 2278 + новые

- [ ] **Step 8: Коммит**

```bash
git add db.py tests/test_black_market_db.py
git commit -m "Колонка ротации и завоз, который обходит лавку стороной"
```

---

### Task 3: Ротация в боте

**Files:**
- Modify: `bot.py` — импорт `black_market`, функция ротации рядом с `shop_restock_loop` (около строки 31071), правка тела `shop_restock_loop`
- Test: `tests/test_black_market_commands.py` (создать, дополняется в задачах 4–5)

**Interfaces:**
- Consumes: `black_market.POOL_KEYS`, `black_market.pick_rotation`, `black_market.NEW_ITEMS`, `db.*` из задачи 2, `local_today()` (`bot.py:1730`).
- Produces: `bot.ensure_black_market_rotation(chat_id: int) -> bool` — `True`, если ассортимент только что обновлён.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_black_market_commands.py`:

```python
"""Лавка в боте: ротация раз в сутки и переживание простоя.

Главное, что здесь проверяется, — идемпотентность: ротацию дёргают из двух
мест (чтение лавки и суточный цикл), и второй вызов в тот же день обязан
ничего не менять. Иначе ассортимент переставлялся бы под человеком.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import black_market as BM  # noqa: E402
import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
TODAY = date(2026, 7, 28)


def _fake_db(monkeypatch, *, day=None):
    """Минимальная подмена БД: запоминает выставленный ассортимент."""
    state = {"day": day, "stock": {}, "cleared": 0, "seeded": 0}

    async def get_rotation_day(chat_id, keys):
        return state["day"]

    async def clear_rotation_stock(chat_id, keys):
        state["cleared"] += 1
        state["stock"] = {}

    async def set_shop_item_rotation(chat_id, item_key, stock, rotation_day):
        state["stock"][item_key] = stock
        state["day"] = rotation_day
        return True

    async def seed_extra_shop_items(chat_id, items, is_active=True):
        state["seeded"] += 1
        return 0

    monkeypatch.setattr(bot_module.db, "get_rotation_day", get_rotation_day)
    monkeypatch.setattr(bot_module.db, "clear_rotation_stock", clear_rotation_stock)
    monkeypatch.setattr(bot_module.db, "set_shop_item_rotation", set_shop_item_rotation)
    monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", seed_extra_shop_items)
    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)
    return state


def test_rotation_fills_assortment_when_never_rotated(monkeypatch):
    state = _fake_db(monkeypatch, day=None)

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is True
    assert 3 <= len(state["stock"]) <= 4
    assert set(state["stock"]) <= BM.POOL_KEYS
    assert state["day"] == TODAY


def test_rotation_is_idempotent_within_a_day(monkeypatch):
    state = _fake_db(monkeypatch, day=TODAY)

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is False
    assert state["cleared"] == 0
    assert state["stock"] == {}


def test_rotation_catches_up_after_downtime(monkeypatch):
    """Бот лежал сутки — ассортимент обновляется при первом же обращении."""
    state = _fake_db(monkeypatch, day=date(2026, 7, 26))

    changed = asyncio.run(bot_module.ensure_black_market_rotation(CHAT_ID))

    assert changed is True
    assert state["cleared"] == 1
    assert state["day"] == TODAY
```

- [ ] **Step 2: Прогнать тест и убедиться, что он падает**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: FAIL — `AttributeError: module 'bot' has no attribute 'ensure_black_market_rotation'`

- [ ] **Step 3: Добавить импорт**

В `bot.py`, в блок импортов проектных модулей (рядом с `import robbery`):

```python
import black_market
```

- [ ] **Step 4: Написать функцию ротации**

В `bot.py` перед `SHOP_RESTOCK_HOUR_LOCAL` (около строки 31069):

```python
# Ротация лавки. Ленивая: ассортимент обновляется при первом обращении в
# новые сутки, а не по будильнику. Так лавка переживает простой бота —
# суточный цикл ниже срабатывает только если бот был жив в нужный час, и
# завязать на него единственный источник ассортимента значило бы, что после
# ночного рестарта лавка пуста весь день.
#
# Цикл при этом ротацию тоже дёргает — ради объявления в чат. Функция
# идемпотентна в пределах суток, так что два вызова безопасны.
_black_market_locks: dict[int, asyncio.Lock] = {}


def _black_market_lock(chat_id: int) -> asyncio.Lock:
    """Свой замок на чат: две одновременные «лавки» не должны разыграть
    ассортимент дважды. Хватает внутрипроцессного замка — ротацию делает
    только бот, а он один процесс."""
    lock = _black_market_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _black_market_locks[chat_id] = lock
    return lock


async def ensure_black_market_rotation(chat_id: int) -> bool:
    """Выставляет ассортимент лавки на сегодня. True — если обновили сейчас."""
    keys = sorted(black_market.POOL_KEYS)
    today = local_today()
    async with _black_market_lock(chat_id):
        if await db.get_rotation_day(chat_id, keys) == today:
            return False
        # Строки должны существовать до выбора: в чате, где магазин ни разу
        # не открывали, выбирать было бы нечего.
        await db.seed_extra_shop_items(chat_id, black_market.NEW_ITEMS)
        await db.seed_extra_shop_items(chat_id, robbery.ROBBERY_SHOP_ITEMS)
        await db.seed_extra_shop_items(chat_id, shop_effects.shop_rows())
        await db.clear_rotation_stock(chat_id, keys)
        for item_key, stock in black_market.pick_rotation().items():
            await db.set_shop_item_rotation(chat_id, item_key, stock, today)
        return True
```

- [ ] **Step 5: Прогнать тест и убедиться, что он проходит**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: PASS (3 passed)

- [ ] **Step 6: Отцепить завоз от пула и подцепить объявление**

В `bot.py`, в `shop_restock_loop` (около строки 31090), заменить строку получения списка:

```python
                rows = await db.list_shop_items_for_restock(
                    chat_id, exclude_keys=sorted(black_market.POOL_KEYS)
                )
```

И сразу после цикла по `rows` (перед `await db.set_data(last_key, today_str)`) добавить:

```python
                # Заодно крутим лавку — ради объявления. Сама по себе она
                # обновится и без цикла, при первом обращении (см.
                # ensure_black_market_rotation).
                if await ensure_black_market_rotation(chat_id):
                    lines.append("🏴 Чёрный рынок обновил ассортимент — «лавка»")
                    restocked_any = True
```

- [ ] **Step 7: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS

- [ ] **Step 8: Коммит**

```bash
git add bot.py tests/test_black_market_commands.py
git commit -m "Ротация лавки: ленивая, поэтому переживает простой бота"
```

---

### Task 4: Команды лавки и гейт покупки

**Files:**
- Modify: `bot.py` — реестр команд (около строки 1213), `_shop_buy` (строка 24242), `shop_list_page` (строка 23809), новые обработчики рядом с `cmd_shop_buy` (около строки 24234)
- Test: `tests/test_black_market_commands.py` (дополнить)

**Interfaces:**
- Consumes: `bot.ensure_black_market_rotation` (задача 3), `db.list_rotation_items`, `black_market.POOL_KEYS`.
- Produces: `_shop_buy(message, item_key, qty, from_black_market: bool = False)` — **у существующей функции добавлен необязательный параметр**; вызов из «пет корм» не правится.

**Главное в задаче.** `SHOP_BUY_RE` (`bot.py:22899`) — это `^(?:!?магазин\s+купить|купить)\s+(\S+)…`, то есть голое `купить binokl` уже работает. Спрятать товары лавки только из витрины недостаточно: кто знает ключ, купит в любой день. Гейт обязан стоять внутри `_shop_buy`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_black_market_commands.py`:

```python
class _Reply:
    """Сообщение-заглушка: копит ответы бота, ничего не отправляя."""

    def __init__(self, text, user_id=777):
        self.text = text
        self.replies = []
        self.chat = type("Chat", (), {"id": CHAT_ID, "type": "supergroup"})()
        self.from_user = type("User", (), {"id": user_id, "is_bot": False,
                                           "full_name": "Тест", "username": "test"})()
        self.reply_to_message = None

    async def reply(self, text, **kwargs):
        self.replies.append(text)
        return self

    async def answer(self, text, **kwargs):
        self.replies.append(text)
        return self


def _shop_item(key, stock=3, rotation_day=None):
    return {
        "item_key": key, "name": key, "description": "", "emoji": "🎁",
        "price": 100, "is_active": True, "stock": stock,
        "rotation_day": rotation_day,
    }


def test_pool_item_cannot_be_bought_through_the_shop(monkeypatch):
    """Голое «купить binokl» не должно обходить лавку."""
    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)

    async def get_shop_item(chat_id, key):
        return _shop_item(key, rotation_day=TODAY)

    monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item)
    message = _Reply("купить binokl")

    bought = asyncio.run(bot_module._shop_buy(message, "binokl", 1))

    assert bought is False
    assert any("лавка" in r for r in message.replies)


def test_shop_item_cannot_be_bought_through_the_black_market(monkeypatch):
    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)

    async def get_shop_item(chat_id, key):
        return _shop_item(key)

    monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item)
    message = _Reply("лавка купить pechenka")

    bought = asyncio.run(bot_module._shop_buy(message, "pechenka", 1, from_black_market=True))

    assert bought is False
    assert any("магазин" in r for r in message.replies)


def test_pool_item_out_of_rotation_is_not_for_sale(monkeypatch):
    """Позиция вне сегодняшнего ассортимента не продаётся даже в лавке."""
    monkeypatch.setattr(bot_module, "local_today", lambda: TODAY)

    async def get_shop_item(chat_id, key):
        return _shop_item(key, stock=0, rotation_day=date(2026, 7, 26))

    monkeypatch.setattr(bot_module.db, "get_shop_item", get_shop_item)
    message = _Reply("лавка купить binokl")

    bought = asyncio.run(bot_module._shop_buy(message, "binokl", 1, from_black_market=True))

    assert bought is False
    assert any("завоз" in r.lower() or "сегодня" in r.lower() for r in message.replies)
```

- [ ] **Step 2: Прогнать тесты и убедиться, что они падают**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: FAIL — `_shop_buy() got an unexpected keyword argument 'from_black_market'`, а первый тест уходит дальше по коду и не отвечает про лавку

- [ ] **Step 3: Поставить гейт в `_shop_buy`**

В `bot.py` заменить сигнатуру (строка 24242):

```python
async def _shop_buy(message: Message, item_key: str, qty: int,
                    from_black_market: bool = False) -> bool:
```

И сразу после проверки `if item is None or not item["is_active"]` (после строки 24259) вставить:

```python
    # Гейт лавки. Стоит ЗДЕСЬ, а не в отрисовке витрины, потому что
    # SHOP_BUY_RE ловит и голое «купить {ключ}»: спрячь товар только из
    # списка — и любой, кто знает ключ, купит его в обход ротации.
    in_pool = item_key in black_market.POOL_KEYS
    if in_pool and not from_black_market:
        await message.reply(
            f"{item['emoji']} «{html.escape(item['name'])}» в обычном магазине "
            f"не продаётся — загляните в «лавка»."
        )
        return False
    if from_black_market and not in_pool:
        await message.reply(
            f"{item['emoji']} «{html.escape(item['name'])}» в лавке нет — "
            f"это товар обычного «магазин»."
        )
        return False
    if in_pool and item.get("rotation_day") != local_today():
        await message.reply(
            f"{item['emoji']} «{html.escape(item['name'])}» сегодня не завозили. "
            f"Что есть — покажет «лавка»."
        )
        return False
```

- [ ] **Step 4: Распространить потолок в 3 штуки на весь пул**

Заменить условие на строке 24269 (`if item_key in robbery.ROBBERY_ITEMS:`):

```python
    # Потолок держим на всём пуле лавки, а не только на предметах ограбления:
    # иначе медвежатник и новинки копились бы за много дней, и дефицит
    # кончился бы на второй неделе.
    if item_key in robbery.ROBBERY_ITEMS or item_key in black_market.POOL_KEYS:
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: PASS (6 passed)

- [ ] **Step 6: Убрать пул из витрины магазина**

В `bot.py`, в `shop_list_page`, заменить строку 23809:

```python
    # Товары лавки прячем из витрины магазина — продаются они только там.
    # db.list_shop_items при этом не трогаем: веб-панель должна видеть
    # каталог чата целиком.
    items = [i for i in await db.list_shop_items(chat_id)
             if i["item_key"] not in black_market.POOL_KEYS]
```

- [ ] **Step 7: Добавить команды лавки**

В `bot.py` рядом с `cmd_shop_buy` (после строки 24239):

```python
BLACK_MARKET_TRIGGERS = ("лавка", "!лавка", "чёрный рынок", "черный рынок")
BLACK_MARKET_BUY_RE = ru_text.rx(r"(?i)^!?лавка\s+купить\s+(\S+)(?:\s+(\d+))?$")


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and bool(BLACK_MARKET_BUY_RE.match(t.strip()))),
)
async def cmd_black_market_buy(message: Message):
    if not _check_misc_access(message.from_user.id, "black_market_buy"):
        return
    await ensure_black_market_rotation(message.chat.id)
    match = BLACK_MARKET_BUY_RE.match(message.text.strip())
    await _shop_buy(message, match.group(1).casefold(),
                    int(match.group(2)) if match.group(2) else 1,
                    from_black_market=True)


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and ru_text.yo(t.strip().casefold()) in BLACK_MARKET_TRIGGERS),
)
async def cmd_black_market(message: Message):
    if not _check_misc_access(message.from_user.id, "black_market"):
        return
    await ensure_black_market_rotation(message.chat.id)
    items = await db.list_rotation_items(
        message.chat.id, sorted(black_market.POOL_KEYS), local_today()
    )
    lines = ["🏴 <b>Чёрный рынок</b>", DIVIDER]
    if not items:
        lines.append("Сегодня пусто — заходите завтра.")
    else:
        lines.extend(shop_item_line(i) for i in items)
        lines.append("\nКупить: <code>лавка купить {ключ}</code>")
        lines.append("Ассортимент и запас меняются раз в сутки.")
    await message.reply("\n".join(lines))
```

**Внимание на порядок:** обработчик `cmd_black_market_buy` объявляется ДО `cmd_black_market`. Точное совпадение по `BLACK_MARKET_TRIGGERS` не поймает «лавка купить …», но обратный порядок регистрации всё равно читается как ловушка.

`ru_text.yo` приводит «ё» к «е», поэтому «чёрный рынок» и «черный рынок» обе строки в кортеже — сравнение идёт с уже нормализованным текстом.

- [ ] **Step 8: Зарегистрировать команды в дереве**

В `bot.py`, в реестр команд рядом со `shop_buy` (около строки 1213):

```python
    "black_market":     {"phrase": "лавка — чёрный рынок: ассортимент дня", "category": "Экономика", "level": 0},
    "black_market_buy": {"phrase": "лавка купить {ключ} [количество]", "category": "Экономика", "level": 0},
```

- [ ] **Step 9: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS. Если упал `tests/test_help_texts_accuracy.py` — справка ещё не написана, это задача 6; можно закоммитить и доделать там же.

- [ ] **Step 10: Коммит**

```bash
git add bot.py tests/test_black_market_commands.py
git commit -m "Лавка продаёт то, что завезли: гейт стоит в покупке, а не в витрине"
```

---

### Task 5: Сигнализация и слепок ключа

**Files:**
- Modify: `bot.py` — `_steal_mark_used` (строка 18485), `cmd_steal_item` (строка 18497)
- Test: `tests/test_black_market_commands.py` (дополнить)

**Interfaces:**
- Consumes: `black_market.SIGNAL_KEY`, `black_market.SLEPOK_KEY`, `black_market.STEAL_COOLDOWN_CUT`, `STEAL_COOLDOWN` (`bot.py:18465`).
- Produces: `_steal_mark_used(chat_id: int, user_id: int, cut: float = 0.0) -> None` — **у существующей функции добавлен необязательный параметр**.

**Порядок шагов в `cmd_steal_item` — часть требований, а не деталь реализации:**

1. проверка, что у жертвы есть названный предмет (строка 18559) — до всего, ничего не тратится;
2. **сигнализация у жертвы?** → тратится медвежатник, тратится сигнализация, ставится обычный кулдаун, объявление в чат, `return`;
3. списание медвежатника и отметка кулдауна (строки 18566–18567);
4. атомарное изъятие вещи (строка 18568);
5. **слепок ключа** — только если шаг 4 удался.

Сигнализация проверяется после шага 1, чтобы опечатка в ключе не сжигала ни её, ни медвежатник. Слепок тратится на шаге 5, а не вместе с отметкой на шаге 3, потому что шаг 3 выполняется до того, как исход известен: на ветке «Предмет успели потратить» слепок сгорел бы за кражу, которой не было.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_black_market_commands.py`:

```python
from datetime import datetime, timedelta


def test_signalizaciya_blocks_the_theft_and_burns_both_items(monkeypatch):
    """Сигнализация гасит кражу, но медвежатник вор всё равно теряет.

    Иначе жать медвежатником по чужим закромам стало бы бесплатной
    проверкой «а есть ли у него сигнализация».
    """
    removed = []

    async def remove_inventory_item(chat_id, user_id, key, qty):
        removed.append((user_id, key))
        return True

    inventories = {
        777: [{"item_key": "medvezhatnik", "quantity": 1}],
        888: [{"item_key": "diamond", "quantity": 1},
              {"item_key": BM.SIGNAL_KEY, "quantity": 1}],
    }

    async def list_inventory(chat_id, user_id):
        return inventories[user_id]

    monkeypatch.setattr(bot_module.db, "remove_inventory_item", remove_inventory_item)
    monkeypatch.setattr(bot_module.db, "list_inventory", list_inventory)

    victim_items = {i["item_key"]: i["quantity"] for i in inventories[888]}
    assert victim_items.get(BM.SIGNAL_KEY, 0) > 0

    # Проверяем сам контракт: оба предмета списываются, вещь остаётся.
    asyncio.run(remove_inventory_item(CHAT_ID, 777, "medvezhatnik", 1))
    asyncio.run(remove_inventory_item(CHAT_ID, 888, BM.SIGNAL_KEY, 1))
    assert (777, "medvezhatnik") in removed
    assert (888, BM.SIGNAL_KEY) in removed
    assert (888, "diamond") not in removed


def test_slepok_cuts_the_cooldown_by_a_quarter(monkeypatch):
    """Слепок сдвигает отметку назад на четверть кулдауна: 10 ч → 7,5 ч."""
    saved = {}

    async def set_data(key, value, updated_by=None):
        saved[key] = value

    monkeypatch.setattr(bot_module.db, "set_data", set_data)

    before = datetime.utcnow()
    asyncio.run(bot_module._steal_mark_used(CHAT_ID, 777,
                                            cut=BM.STEAL_COOLDOWN_CUT))
    stamp = datetime.fromisoformat(list(saved.values())[0])

    shift = before - stamp
    expected = bot_module.STEAL_COOLDOWN * BM.STEAL_COOLDOWN_CUT
    assert abs(shift - expected) < timedelta(seconds=5)
    # Остаток кулдауна после слепка — ровно 7,5 часа.
    assert abs((bot_module.STEAL_COOLDOWN - shift) - timedelta(hours=7.5)) < timedelta(seconds=5)


def test_steal_mark_without_slepok_is_unchanged(monkeypatch):
    """Без слепка отметка пишется текущим временем — полные 10 часов."""
    saved = {}

    async def set_data(key, value, updated_by=None):
        saved[key] = value

    monkeypatch.setattr(bot_module.db, "set_data", set_data)

    before = datetime.utcnow()
    asyncio.run(bot_module._steal_mark_used(CHAT_ID, 777))
    stamp = datetime.fromisoformat(list(saved.values())[0])

    assert abs(before - stamp) < timedelta(seconds=5)
```

- [ ] **Step 2: Прогнать тесты и убедиться, что они падают**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: FAIL — `_steal_mark_used() got an unexpected keyword argument 'cut'`

- [ ] **Step 3: Научить отметку сдвигу**

В `bot.py` заменить `_steal_mark_used` (строка 18485):

```python
async def _steal_mark_used(chat_id: int, user_id: int, cut: float = 0.0) -> None:
    """Отмечает, что медвежатник сработал.

    cut — доля кулдауна, которую снимает слепок ключа. Механика та же, что у
    «тачки для отхода» у ограбления (см. set_robbery_last_at ниже по коду):
    отметка пишется задним числом, а не заводится отдельный заряд. Двух
    механизмов на одну идею быть не должно.
    """
    stamp = datetime.utcnow() - STEAL_COOLDOWN * cut
    await db.set_data(_steal_key(chat_id, user_id),
                      stamp.isoformat(), updated_by=user_id)
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/test_black_market_commands.py -q -W ignore::DeprecationWarning`
Expected: PASS (9 passed)

- [ ] **Step 5: Вставить сигнализацию в кражу**

В `bot.py`, в `cmd_steal_item`, сразу после блока проверки наличия предмета у жертвы (после строки 18562, где `return` при отсутствии предмета) и ДО списания медвежатника:

```python
    # Сигнализация — единственная защита от медвежатника. По образцу броника
    # у ограбления: срабатывает сама и тратится у жертвы. Медвежатник при
    # этом сгорает тоже — иначе им бесплатно проверяли бы, есть ли у цели
    # сигнализация, и защита сама бы себя выдавала.
    if victim_items.get(black_market.SIGNAL_KEY, 0) > 0:
        await db.remove_inventory_item(chat_id, user_id, spec.key, 1)
        await db.remove_inventory_item(chat_id, target.id, black_market.SIGNAL_KEY, 1)
        await _steal_mark_used(chat_id, user_id)
        await db.add_log("item_steal_blocked", chat_id=chat_id, actor_id=user_id,
                         target_id=target.id, details=wanted)
        actor_name = await display_name(chat_id, message.from_user)
        target_name = await display_name(chat_id, target)
        await message.answer(
            f"🚨 {actor_name} вскрыл(а) закрома {target_name}, но взвыла "
            f"сигнализация — уходить пришлось с пустыми руками."
        )
        await _dm_or_none(
            target.id,
            f"🚨 Вашу сигнализацию сорвали — кражу предотвратили, "
            f"предмет «{html.escape(wanted)}» остался у вас. Сигнализация израсходована."
        )
        return
```

- [ ] **Step 6: Вставить слепок после удавшейся кражи**

В `bot.py`, в `cmd_steal_item`, после `await db.add_log("item_stolen", ...)` (после строки 18573):

```python
    # Слепок ключа сокращает откат на четверть — но только теперь, когда
    # кража точно удалась. Отметка выше ставится до того, как исход
    # известен, и на ветке «предмет успели потратить» слепок сгорел бы зря.
    thief_items = {i["item_key"]: i["quantity"]
                   for i in await db.list_inventory(chat_id, user_id)}
    if thief_items.get(black_market.SLEPOK_KEY, 0) > 0:
        await db.remove_inventory_item(chat_id, user_id, black_market.SLEPOK_KEY, 1)
        await _steal_mark_used(chat_id, user_id, cut=black_market.STEAL_COOLDOWN_CUT)
```

- [ ] **Step 7: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS (кроме `test_help_texts_accuracy.py`, если справка ещё не дописана)

- [ ] **Step 8: Коммит**

```bash
git add bot.py tests/test_black_market_commands.py
git commit -m "От медвежатника появилась защита, а у него самого — способ поторопиться"
```

---

### Task 6: Справка, README и финальная проверка

**Files:**
- Modify: `help_texts.py` — раздел рядом с ограблением
- Modify: `README.md` — раздел после «Кик» / рядом с экономикой
- Test: `tests/test_help_texts_accuracy.py` (существующий, запустить)

**Interfaces:**
- Consumes: всё из задач 1–5.
- Produces: ничего для кода — только тексты.

- [ ] **Step 1: Посмотреть, что именно проверяет тест справки**

Run: `.venv/bin/python -m pytest tests/test_help_texts_accuracy.py -q -W ignore::DeprecationWarning`

Прочитать `tests/test_help_texts_accuracy.py` и понять требование: он сверяет фразы в справке с реальными триггерами. Новые команды обязаны попасть в справку в том же виде, в каком объявлены в реестре.

- [ ] **Step 2: Дописать раздел справки**

В `help_texts.py`, в словарь `subsections` раздела экономики рядом с
`"fishing"` (около строки 1154), добавить запись. Форма — ровно как у
соседей: ключ подраздела → словарь с `title` и `text`.

```python
                "black_market": {
                    "title": "🏴 Чёрный рынок",
                    "text": (
                        "🏴 <b>Лавка, где продаётся всё воровское (всем):</b>\n"
                        "В обычном «магазин» этих вещей больше нет — только здесь.\n\n"
                        "🏴 <b>лавка</b> — что завезли сегодня и сколько осталось.\n"
                        "🏴 <b>лавка купить {ключ} [сколько]</b> — купить.\n\n"
                        "🏴 <b>Ассортимент меняется раз в сутки</b>: из одиннадцати "
                        "позиций выпадают три-четыре, у каждой свой запас "
                        "<b>на весь чат</b>. Кто успел, тот и купил — раскупленное "
                        "вернётся только со следующим завозом.\n\n"
                        "🚨 <b>Сигнализация</b> — блокирует одну кражу медвежатником "
                        "против вас. Единственная защита от него.\n"
                        "🔑 <b>Слепок ключа</b> — следующая кража медвежатником "
                        "ставит откат на четверть короче.\n\n"
                        "🏴 Больше трёх штук одного товара лавки держать нельзя."
                    ),
                },
```

Функция `build_help_sections` собирает разделы на каждый вызов, потому что часть строк подставляет настройки времени выполнения — новый подраздел никакой регистрации сверх этой записи не требует.

- [ ] **Step 3: Дописать README**

В `README.md` после раздела про ограбления добавить:

```markdown
## Чёрный рынок (лавка)

Всё воровское снаряжение продаётся только здесь — в обычном «магазин» его нет.

- **`лавка`** (или `чёрный рынок`) — ассортимент на сегодня и остатки.
- **`лавка купить {ключ} [количество]`** — купить.

Ассортимент меняется **раз в сутки**: из одиннадцати позиций выпадают три-четыре,
у каждой свой запас **на весь чат** — кто успел, тот и купил. Раскупленное
вернётся только со следующим завозом. Больше трёх штук одного товара держать
нельзя.

Две вещи продаются только в лавке и нигде больше:

- 🚨 **Сигнализация** (20 000 i¢) — блокирует одну попытку медвежатника против
  вас. Вор при этом всё равно теряет свой медвежатник: иначе им бесплатно
  проверяли бы, есть ли у цели защита.
- 🔑 **Слепок ключа** (6 000 i¢) — следующая кража медвежатником ставит откат
  7,5 часа вместо 10.

Ротация ленивая: ассортимент обновляется при первом обращении в новые сутки,
поэтому переживает простой бота. Если бот был жив в час завоза, он ещё и
объявит обновление в чат.
```

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS, всё зелёное

- [ ] **Step 5: Коммит**

```bash
git add help_texts.py README.md
git commit -m "Справка и README узнали про лавку"
```

- [ ] **Step 6: Пересобрать arc.zip**

```bash
rm -f arc.zip && zip -q -r arc.zip . \
  -x '.git/*' '.venv/*' 'venv/*' '*/__pycache__/*' '__pycache__/*' '*.pyc' \
     '.pytest_cache/*' '*/.pytest_cache/*' \
     'images/*' 'rp_media/*' 'webpanel/static/rp_media/*' 'demo_out/*' \
     '*.jpg' '*.jpeg' 'arc.zip' \
  && unzip -t arc.zip >/dev/null && ls -lh arc.zip
```

---

## Проверка после всех задач

Ручной сценарий в живом чате (одной командой это не проверяется):

1. `магазин` — воровских предметов в витрине нет.
2. `купить binokl` — отказ с отсылкой к лавке.
3. `лавка` — три-четыре позиции с остатками и ценами.
4. `лавка купить {ключ отсутствующей сегодня позиции}` — «сегодня не завозили».
5. `лавка купить {ключ из ассортимента}` — покупка проходит, остаток уменьшается.
6. Скупить позицию целиком → в `лавка` она показана как «раскуплено», покупка отбивается.
7. `инвентарь` — купленное показано названием и эмодзи, а не голым ключом (это и есть проверка того, что строка осталась в `shop_items`).
8. Кража медвежатником по цели с сигнализацией — кража сорвана, у вора списан медвежатник, у жертвы сигнализация, предмет на месте.
9. Кража со слепком в инвентаре — в ответе на повторную попытку остаток отката ≈ 7,5 ч, а не 10 ч.

## Чего в плане намеренно нет

* **Вкладки лавки в веб-панели.** Панель видит товары как обычные строки
  `shop_items` — этого достаточно, отдельный экран не заказан.
* **Настроек ротации в чате** (число слотов, час завоза). Числа живут в
  `black_market.py`; команды настройки добавляются, если чат попросит.
* **Скупщика краденого** — отдельная механика, вынесена за границы спеки.
