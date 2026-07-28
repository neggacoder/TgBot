# Кабинет участника: каркас и питомцы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вынести игровые действия с питомцами из `bot.py` в общий модуль и открыть их участнику на сайте, не написав в чат ни одного лишнего сообщения.

**Architecture:** Новый модуль `game_actions.py` делает действие и возвращает `ActionResult` — отчёт плюс список объявлений. Он не знает ни про aiogram, ни про Telegram, поэтому отправить ничего не может физически. Бот после переноса только зовёт его и отвечает; панель зовёт то же самое и молчит.

**Tech Stack:** Python 3.12, aiomysql, FastAPI, pytest, обычный JS без сборки.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-28-member-cabinet-design.md`.
- Тесты запускаются ТОЛЬКО из venv: `.venv/bin/python -m pytest`. Системный python3 без pytest.
- `game_actions.py` НЕ импортирует `bot`, `aiogram`, `webpanel`. Разрешено: `db`, чистые модули (`pets`, `pins`, `shop_effects`, `ru_text`), стандартная библиотека.
- Панель НЕ импортирует `bot.py` — это подняло бы второго бота.
- Все тексты для человека — по-русски, ровно те же, что даёт бот сейчас. Разные тексты в чате и на сайте — третья правда.
- Комментарии объясняют ПОЧЕМУ так, а не что делает строка.
- Сообщения коммитов — по-русски, с объяснением причины, с трейлером `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Команды бота обязаны продолжать работать: существующие тесты — сетка, их не править под новый код.
- После каждой законченной задачи пересобирать `arc.zip` командой из памяти проекта.
- Ветка `member-cabinet`, worktree не создавать.

## Что входит и что нет

Переносим действия, которые нужны кабинету: список своих, каталог, купить,
продать, кормить, гладить/обнять/поцеловать, гулять (одиночные и массовые
формы), купить корм, назвать, закрепить, открепить.

НЕ переносим в этом плане: эволюцию, смену способности, админские «пет
раздать» и «пет удалить». Их в кабинете нет, и трогать работающий код без
нужды — лишний риск. Они остаются в `bot.py` как есть.

---

## Файловая структура

| Файл | Ответственность |
|---|---|
| `game_actions.py` (создать) | `ActionResult`, `Announcement` и действия с питомцами |
| `bot.py` (править) | Обработчики становятся обёртками: позвал, ответил |
| `webpanel/member_game_api.py` (создать) | Роутер `/api/member/game/pets` |
| `webpanel/app.py` (править) | Одна строка `include_router` |
| `webpanel/static/webapp.html`, `webapp.js` (править) | Вкладка «Питомцы» в кабинете |
| `tests/test_game_actions.py` (создать) | Действия на заглушке `db` |
| `tests/test_game_parity.py` (создать) | Сторож: чат и сайт дают одно и то же |
| `tests/test_member_game_api.py` (создать) | Роутер через `TestClient` + сторож тишины |

---

### Task 1: Каркас `game_actions.py` и первое действие — кормление

**Files:**
- Create: `game_actions.py`
- Modify: `bot.py` (`cmd_pet_feed`)
- Test: `tests/test_game_actions.py`

**Interfaces:**
- Consumes: `db`, `pets` (как `pets_catalog`), `pins`
- Produces: `Announcement`, `ActionResult`, `feed_pet(chat_id, user_id, key) -> ActionResult`, а также перенесённые из `bot.py` помощники `pet_feed_left`, `pet_display`, `no_food_text`, `pick_pet`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_game_actions.py`:

```python
"""Игровые действия без Telegram.

Модуль game_actions делает действие и возвращает результат. Отправить он
ничего не может — у него нет бота, и это не забывчивость, а конструкция:
тишина на сайте получается сама, а не заглушкой, которую можно забыть.
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timedelta

import pytest

import game_actions
import pets as pets_catalog


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. tests/test_farming.py)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: только то, что трогает кормление."""

    def __init__(self):
        now = datetime.utcnow()
        self.pets = [{
            "pet_key": "kot", "name": None, "hunger": 10, "mood": 80,
            "xp": 0, "xp_tick_at": now, "fed_at": now - timedelta(days=1),
            "petted_at": now - timedelta(days=1), "hunger_tick_at": now,
            "mood_tick_at": now, "last_walk_at": None, "evolved": False,
            "ability": "", "ability2": "",
        }]
        self.inventory = {pets_catalog.FOOD_ITEM_KEY: 3}
        self.card = {}
        self.saved = []

    async def list_pets(self, chat_id, user_id):
        return [dict(p) for p in self.pets]

    async def get_pet(self, chat_id, user_id, key):
        return next((dict(p) for p in self.pets if p["pet_key"] == key), None)

    async def list_chat_pet_species(self, chat_id):
        return []

    async def get_profile_card(self, chat_id, user_id):
        return dict(self.card)

    async def get_inventory_quantity(self, chat_id, user_id, item_key):
        return self.inventory.get(item_key, 0)

    async def remove_inventory_item(self, chat_id, user_id, item_key, amount=1):
        have = self.inventory.get(item_key, 0)
        if have < amount:
            return False
        self.inventory[item_key] = have - amount
        return True

    async def update_pet(self, chat_id, user_id, key, **fields):
        for p in self.pets:
            if p["pet_key"] == key:
                p.update(fields)
        self.saved.append((key, fields))
        return True


@pytest.fixture
def мир(monkeypatch):
    world = _World()
    monkeypatch.setattr(game_actions, "db", world)
    return world


@_sync
async def test_кормление_поднимает_сытость_и_тратит_корм(мир):
    было = мир.inventory[pets_catalog.FOOD_ITEM_KEY]
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert res.ok, res.text
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == было - 1
    assert мир.pets[0]["hunger"] > 10


@_sync
async def test_без_корма_кормление_не_проходит(мир):
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 0
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert not res.ok
    assert "корм" in res.text.lower()
    assert мир.pets[0]["hunger"] == 10, "неудача не должна ничего менять"


@_sync
async def test_сытого_кормить_нельзя(мир):
    мир.pets[0]["hunger"] = 100
    мир.pets[0]["fed_at"] = datetime.utcnow()
    было = мир.inventory[pets_catalog.FOOD_ITEM_KEY]
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert not res.ok
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == было, "корм не тратится впустую"


@_sync
async def test_неизвестный_питомец(мир):
    res = await game_actions.feed_pet(-100, 7, "дракон")
    assert not res.ok


@_sync
async def test_результат_не_умеет_отправлять():
    """Ключевое свойство: у модуля нет ни бота, ни отправки. Тишина на сайте
    — следствие конструкции, а не забытой проверки."""
    import inspect
    src = inspect.getsource(game_actions)
    assert "aiogram" not in src
    assert "send_message" not in src
    assert "import bot" not in src


@_sync
async def test_новый_уровень_становится_объявлением(мир):
    """Ачивки и уровни объявляются в чат даже когда действие сделано с сайта:
    их ради этого и добывают. Модуль их не шлёт, а возвращает."""
    мир.pets[0]["xp"] = pets_catalog.xp_for_level(2) - 1
    res = await game_actions.feed_pet(-100, 7, "kot")
    assert res.ok
    if res.announcements:
        assert all(a.text for a in res.announcements)
        assert all(a.kind for a in res.announcements)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_game_actions.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'game_actions'`

- [ ] **Step 3: Создать модуль с каркасом**

Создать `game_actions.py`. Начало файла — дословно:

```python
"""Игровые действия: сделать и вернуть результат. Ничего не отправляет.

Зачем модуль вообще. Панель — отдельный процесс и bot.py импортировать не
может: это подняло бы второго бота. А игровая логика жила именно там,
вперемешку с ответами в Telegram. Значит либо панель повторяет правила у
себя — и появляется вторая правда о ценах и кулдаунах, — либо действия
переезжают сюда. Переехали.

Здесь НЕТ бота и НЕТ отправки сообщений, и это не упущение, а главное
свойство: тишина на сайте получается сама. Заглушку «не отвечать» можно
забыть поставить в новом эндпоинте; отсутствующего клиента Telegram забыть
нельзя.

Отчёт возвращается вызывающему. Объявления — ачивка, новый уровень, новая
звезда — отдаются отдельным списком: их положено показать в чате, даже если
кнопку нажали на сайте, и решает это тот, кто позвал.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import db
import pets as pets_catalog
import pins

ANNOUNCE_ACHIEVEMENT = "achievement"
ANNOUNCE_PET_LEVEL = "pet_level"
ANNOUNCE_FARM_STAR = "farm_star"


@dataclass(frozen=True)
class Announcement:
    """То, что положено объявить в чат, даже если действие сделано с сайта."""
    kind: str
    text: str


@dataclass(frozen=True)
class ActionResult:
    """Итог действия: что показать сделавшему и что объявить чату.

    ok=False — не ошибка программы, а законный исход игры: не хватило
    монет, не вышел кулдаун, счёт заморожен. Текст в обоих случаях один и
    тот же, поэтому в чате и на сайте человек читает одно и то же.
    """
    ok: bool
    text: str
    announcements: tuple[Announcement, ...] = ()

    @classmethod
    def fail(cls, text: str) -> "ActionResult":
        return cls(False, text)
```

Затем ПЕРЕНЕСТИ из `bot.py` в этот модуль, не меняя тел, функции:
`_pet_now`, `_pet_level`, `_effective_abilities`, `_pet_specs`,
`_pet_is_active`, `_pinned_pet_key`, `_pet_family_bonus`, `PetAura`,
`_pet_aura`, `_pet_aura_for`, `_pet_ability_sums`, `_pet_bonus`,
`_pet_feed_left`, `_pet_display`, `_pet_no_food_text`, `_feed_pet`.

Имена в новом модуле — без ведущего подчёркивания у того, что зовут снаружи
(`pet_feed_left`, `pet_display`, `no_food_text`, `pet_aura_for`); остальное
остаётся приватным. В `bot.py` эти определения УДАЛИТЬ и заменить импортом
`import game_actions`, а обращения — на `game_actions.имя`.

Добавить само действие:

```python
async def pick_pet(chat_id: int, user_id: int,
                   raw: Optional[str]) -> tuple[Optional[object], Optional[dict], str]:
    """(вид, строка питомца, текст ошибки). Вид None — питомец не найден.

    Отдельно от обработчика, потому что «какого питомца имели в виду» —
    правило игры, одинаковое в чате и на сайте: без ключа берём
    единственного, с ключом — названного.
    """
    rows = await db.list_pets(chat_id, user_id)
    if not rows:
        return None, None, "У вас нет питомцев. Каталог — «пет каталог»."
    specs = await _pet_specs(chat_id)
    if raw:
        spec = pets_catalog.resolve(raw)
        if spec is None:
            return None, None, "Такого вида нет — посмотрите «пет каталог»."
        row = next((r for r in rows if r["pet_key"] == spec.key), None)
        if row is None:
            return None, None, f"У вас нет питомца «{spec.name}»."
        return specs.get(spec.key, spec), row, ""
    if len(rows) > 1:
        имена = ", ".join(sorted(r["pet_key"] for r in rows))
        return None, None, f"У вас несколько питомцев — укажите ключ: {имена}."
    row = rows[0]
    spec = specs.get(row["pet_key"])
    if spec is None:
        return None, None, "Этот вид убрали из каталога чата."
    return spec, row, ""


async def feed_pet(chat_id: int, user_id: int,
                   raw: Optional[str] = None) -> ActionResult:
    """Покормить питомца. Корм списывается только при удачном кормлении."""
    spec, row, err = await pick_pet(chat_id, user_id, raw)
    if spec is None:
        return ActionResult.fail(err)
    left = pet_feed_left(row)
    if left is not None:
        return ActionResult.fail(
            f"🍽 {spec.name} пока сыт — покормить снова через {format_left(left)}.")
    aura = await pet_aura_for(chat_id, user_id)
    result = await _feed_pet(chat_id, user_id, spec, row, datetime.utcnow(), aura)
    if result is None:
        return ActionResult.fail(no_food_text())
    hunger, level_before, level_after = result
    text = (f"🍽 {pet_display(row, spec)} накормлен(а). Сытость: "
            f"{pets_catalog.bar(hunger)} {hunger}")
    announcements: list[Announcement] = []
    if level_after > level_before:
        text += f"\n⭐ Новый уровень: {level_after}!"
        announcements.append(Announcement(
            ANNOUNCE_PET_LEVEL,
            f"⭐ {pet_display(row, spec)} вырос(ла) до уровня {level_after}!"))
    left_food = await db.get_inventory_quantity(chat_id, user_id,
                                                pets_catalog.FOOD_ITEM_KEY)
    text += f"\n{pets_catalog.FOOD_ITEM_EMOJI} Корма осталось: {left_food}"
    return ActionResult(True, text, tuple(announcements))
```

`format_left` — перенести сюда `format_duration_ru` из `bot.py` под именем
`format_left`, а в `bot.py` оставить `format_duration_ru = game_actions.format_left`,
чтобы ~40 существующих вызовов не переписывать.

- [ ] **Step 4: Перевести обработчик бота на модуль**

Заменить тело `cmd_pet_feed` в `bot.py` целиком на:

```python
async def cmd_pet_feed(message: Message):
    if not _check_misc_access(message.from_user.id, "pet_care"):
        return
    raw = PET_FEED_RE.match(message.text.strip()).group(1)
    result = await game_actions.feed_pet(message.chat.id, message.from_user.id, raw)
    await message.reply(result.text)
    await _announce(message.chat.id, result)
```

И добавить рядом общего отправителя объявлений:

```python
async def _announce(chat_id: int, result: "game_actions.ActionResult") -> None:
    """Объявления в чат. Отдельной функцией, потому что их шлют ВСЕ
    обработчики одинаково, а забыть про них в одном — значит, что ачивка
    из этой команды не показывается, и заметить это можно только случайно."""
    for item in result.announcements:
        try:
            await bot.send_message(chat_id, item.text)
        except Exception:
            logger.exception("Не удалось объявить: %s", item.kind)
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_game_actions.py -q`
Expected: PASS

- [ ] **Step 6: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, 2056+ тестов. Существующие тесты питомцев — сетка: они
проверяют команды бота и обязаны пройти без правок. Если какой-то упал,
значит перенос изменил поведение — чинить перенос, а не тест.

- [ ] **Step 7: Убедиться, что модуль чист**

Run: `.venv/bin/python -c "import game_actions, sys; assert 'aiogram' not in sys.modules or True; print(open('game_actions.py').read().count('aiogram'))"`
Expected: `0`

- [ ] **Step 8: Коммит**

```bash
git add game_actions.py bot.py tests/test_game_actions.py
git commit -m "$(cat <<'EOF'
Игровые действия переезжают из bot.py: каркас и кормление

Панель не может импортировать bot.py — поднялся бы второй бот, — а
игровая логика жила там вперемешку с ответами в Telegram. Оставить как
есть значило бы завести вторую правду о ценах и кулдаунах: сайт считал бы
своё, чат своё, и разошлись бы они молча.

game_actions ничего не отправляет, потому что у него нет бота. Тишина на
сайте выходит свойством конструкции, а не заглушкой, которую можно забыть
поставить в новом эндпоинте.

Объявления — ачивки и уровни — возвращаются списком, а не шлются: их
положено показать в чате даже за действие с сайта, и решает это
вызывающий.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Сторож паритета — чат и сайт дают одно и то же

**Files:**
- Test: `tests/test_game_parity.py` (создать)

**Interfaces:**
- Consumes: `game_actions.feed_pet`, `bot.cmd_pet_feed`
- Produces: ничего

Смысл: вторая правда о правилах — главный риск всей работы. Сторож ловит её
возврат: если кто-нибудь начнёт считать в обработчике, а не звать модуль,
результаты разойдутся.

- [ ] **Step 1: Написать тест**

Создать `tests/test_game_parity.py`:

```python
"""Одно действие — один результат, из чата и с сайта.

Главный риск этой работы: кто-нибудь однажды посчитает прямо в обработчике
бота, и правила раздвоятся. Разойдутся они молча — в чате одно, на сайте
другое, — и узнаем мы об этом от людей.
"""

from __future__ import annotations

import ast
import inspect
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import game_actions  # noqa: E402

# Обработчик -> действие, которое он ОБЯЗАН звать вместо своих расчётов.
ПЕРЕВЕДЁННЫЕ = {
    "cmd_pet_feed": "feed_pet",
}


@pytest.mark.parametrize("handler,action", sorted(ПЕРЕВЕДЁННЫЕ.items()))
def test_обработчик_зовёт_общий_модуль(handler, action):
    src = inspect.getsource(getattr(bot_module, handler))
    assert f"game_actions.{action}" in src, (
        f"{handler} обязан звать game_actions.{action}, а не считать сам")


@pytest.mark.parametrize("handler", sorted(ПЕРЕВЕДЁННЫЕ))
def test_переведённый_обработчик_не_считает_сам(handler):
    """У обёртки нет своей арифметики: разбор аргументов, вызов, ответ.
    Появились расчёты — значит правила раздвоились."""
    tree = ast.parse(inspect.getsource(getattr(bot_module, handler)))
    запретные = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "db"]
    assert not запретные, (
        f"{handler} ходит в базу напрямую — это работа game_actions")


def test_общий_модуль_не_знает_про_telegram():
    src = inspect.getsource(game_actions)
    for запрет in ("aiogram", "send_message", "import bot", "message."):
        assert запрет not in src, f"в game_actions просочилось «{запрет}»"
```

- [ ] **Step 2: Запустить — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_game_parity.py -q`
Expected: PASS

- [ ] **Step 3: Проверить, что сторож не мнимый**

Временно добавить в `cmd_pet_feed` строку `await db.get_wallet(message.chat.id, message.from_user.id)`.

Run: `.venv/bin/python -m pytest tests/test_game_parity.py -q`
Expected: FAIL с текстом «ходит в базу напрямую»

Убрать строку, убедиться, что снова PASS.

- [ ] **Step 4: Коммит**

```bash
git add tests/test_game_parity.py
git commit -m "$(cat <<'EOF'
Сторож паритета: обработчик зовёт общий модуль, а не считает сам

Вторая правда о правилах — главный риск переноса. Она возвращается тихо:
кто-нибудь посчитает прямо в обработчике, в чате станет одно, на сайте
другое, и узнаем мы от людей. Сторож читает исходник обёрток и требует,
чтобы они звали game_actions и не ходили в базу. Проверен намеренной
поломкой.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Остальные действия ухода — ласка и массовые формы

**Files:**
- Modify: `game_actions.py`, `bot.py`, `tests/test_game_actions.py`, `tests/test_game_parity.py`

**Interfaces:**
- Consumes: каркас из Task 1
- Produces: `care_pet(chat_id, user_id, verb, raw)`, `feed_all(chat_id, user_id)`, `care_all(chat_id, user_id, verb)`

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_game_actions.py`:

```python
@_sync
async def test_ласка_поднимает_настроение(мир):
    мир.pets[0]["mood"] = 40
    res = await game_actions.care_pet(-100, 7, "гладить", "kot")
    assert res.ok, res.text
    assert мир.pets[0]["mood"] > 40


@_sync
async def test_ласка_имеет_кулдаун(мир):
    await game_actions.care_pet(-100, 7, "гладить", "kot")
    было = мир.pets[0]["mood"]
    res = await game_actions.care_pet(-100, 7, "гладить", "kot")
    assert not res.ok
    assert мир.pets[0]["mood"] == было


@_sync
async def test_массовое_кормление_кормит_всех_кому_хватило(мир):
    мир.pets.append(dict(мир.pets[0], pet_key="panda", hunger=20))
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 1
    res = await game_actions.feed_all(-100, 7)
    assert res.ok
    assert мир.inventory[pets_catalog.FOOD_ITEM_KEY] == 0
    assert "1" in res.text


@_sync
async def test_массовое_кормление_без_корма(мир):
    мир.inventory[pets_catalog.FOOD_ITEM_KEY] = 0
    res = await game_actions.feed_all(-100, 7)
    assert not res.ok
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_game_actions.py -q`
Expected: FAIL, `AttributeError: module 'game_actions' has no attribute 'care_pet'`

- [ ] **Step 3: Перенести логику**

Перенести из `bot.py` в `game_actions.py` тела `cmd_pet_care`, `cmd_pet_feed_all`,
`cmd_pet_care_all`, убрав из них `message` и `_check_misc_access`: вместо
`await message.reply(текст)` возвращать `ActionResult.fail(текст)` или
`ActionResult(True, текст, объявления)`. Глагол ласки (`гладить`, `обнять`,
`поцеловать` и их синонимы) передаётся аргументом `verb`.

Объявления собирать те же, что в Task 1: новый уровень питомца.

- [ ] **Step 4: Перевести обработчики бота**

Три обработчика становятся обёртками по образцу `cmd_pet_feed` из Task 1:
разобрать аргументы регуляркой, позвать действие, ответить `result.text`,
вызвать `_announce`.

- [ ] **Step 5: Расширить сторож паритета**

В `tests/test_game_parity.py` дописать в словарь `ПЕРЕВЕДЁННЫЕ`:

```python
    "cmd_pet_care": "care_pet",
    "cmd_pet_feed_all": "feed_all",
    "cmd_pet_care_all": "care_all",
```

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add game_actions.py bot.py tests/test_game_actions.py tests/test_game_parity.py
git commit -m "$(cat <<'EOF'
Ласка и массовые формы переехали в общий модуль

Продолжение переноса. Массовые команды («пет кормить все») считались в
обработчике целиком — именно там и живёт разница между «покормил одного» и
«покормил кого хватило корма», которую сайту пришлось бы повторять.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Прогулка

**Files:**
- Modify: `game_actions.py`, `bot.py`, `tests/test_game_actions.py`, `tests/test_game_parity.py`

**Interfaces:**
- Produces: `walk_pet(chat_id, user_id, raw)`, `walk_all(chat_id, user_id)`

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_game_actions.py`:

```python
@_sync
async def test_прогулка_даёт_монеты_и_ставит_кулдаун(мир, monkeypatch):
    начислено = []

    async def add_coins(chat_id, user_id, amount):
        начислено.append(amount)
        return amount

    async def add_inventory_item(chat_id, user_id, item_key, amount=1):
        мир.inventory[item_key] = мир.inventory.get(item_key, 0) + amount

    monkeypatch.setattr(мир, "add_coins", add_coins, raising=False)
    monkeypatch.setattr(мир, "add_inventory_item", add_inventory_item, raising=False)
    monkeypatch.setattr(game_actions.random, "randint", lambda a, b: b)
    res = await game_actions.walk_pet(-100, 7, "kot")
    assert res.ok, res.text
    assert мир.pets[0]["last_walk_at"] is not None


@_sync
async def test_голодный_гулять_не_идёт(мир):
    мир.pets[0]["hunger"] = 0
    мир.pets[0]["mood"] = 0
    res = await game_actions.walk_pet(-100, 7, "kot")
    assert not res.ok
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_game_actions.py -q`
Expected: FAIL, `AttributeError: module 'game_actions' has no attribute 'walk_pet'`

- [ ] **Step 3: Перенести логику**

Перенести тела `cmd_pet_walk` и `cmd_pet_walk_all` тем же приёмом. Находки
кладутся в инвентарь, монеты начисляются, кулдаун ставится — всё как сейчас.

- [ ] **Step 4: Перевести обработчики и расширить сторож**

Обёртки по образцу Task 1. В `ПЕРЕВЕДЁННЫЕ` дописать:

```python
    "cmd_pet_walk": "walk_pet",
    "cmd_pet_walk_all": "walk_all",
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add game_actions.py bot.py tests/test_game_actions.py tests/test_game_parity.py
git commit -m "$(cat <<'EOF'
Прогулка питомцев переехала в общий модуль

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Покупка, продажа, корм, имя и закреп

**Files:**
- Modify: `game_actions.py`, `bot.py`, `tests/test_game_actions.py`, `tests/test_game_parity.py`

**Interfaces:**
- Produces: `buy_pet`, `sell_pet`, `buy_food`, `rename_pet`, `pin_pet`, `unpin_pet`, `my_pets_text`, `catalog_text`

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_game_actions.py`:

```python
@_sync
async def test_наградного_питомца_не_купить(мир, monkeypatch):
    """Питомец за ачивку — знак отличия, а не товар. Правило одно на чат и
    сайт, иначе через кабинет его можно было бы купить за монеты."""
    награда = next(p for p in pets_catalog.PETS if p.by_achievement)
    res = await game_actions.buy_pet(-100, 7, награда.key)
    assert not res.ok


@_sync
async def test_наградного_питомца_не_продать(мир):
    награда = next(p for p in pets_catalog.PETS if p.by_achievement)
    мир.pets.append(dict(мир.pets[0], pet_key=награда.key))
    res = await game_actions.sell_pet(-100, 7, награда.key, confirm=True)
    assert not res.ok


@_sync
async def test_имя_обрезается_по_длине(мир):
    res = await game_actions.rename_pet(-100, 7, "kot", "и" * 500)
    assert not res.ok or len(мир.pets[0].get("name") or "") <= pets_catalog.NAME_MAX
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_game_actions.py -q`
Expected: FAIL, `AttributeError: module 'game_actions' has no attribute 'buy_pet'`

- [ ] **Step 3: Перенести логику**

Перенести тела `cmd_pet_buy`, `cmd_pet_sell`, `cmd_pet_food_buy`,
`cmd_pet_rename`, `cmd_pet_pin`, `cmd_pet_unpin`, `cmd_pets_mine`,
`cmd_pets_catalog` тем же приёмом. Списки возвращают готовый текст —
`my_pets_text` и `catalog_text` возвращают `ActionResult` с `ok=True`.

Продажа требует подтверждения («пет продать kot да») — в модуле это
аргумент `confirm: bool`, а не разбор текста.

- [ ] **Step 4: Перевести обработчики и расширить сторож**

В `ПЕРЕВЕДЁННЫЕ` дописать все восемь пар.

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add game_actions.py bot.py tests/test_game_actions.py tests/test_game_parity.py
git commit -m "$(cat <<'EOF'
Питомцы переехали в общий модуль целиком: покупка, продажа, имя, закреп

Осталось в bot.py только то, чего нет в кабинете: эволюция, смена
способности и админские команды. Трогать работающий код без нужды — лишний
риск.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: API кабинета — раздел «Питомцы»

**Files:**
- Create: `webpanel/member_game_api.py`
- Modify: `webpanel/app.py` (одна строка `include_router`)
- Test: `tests/test_member_game_api.py` (создать)

**Interfaces:**
- Consumes: `game_actions.*`, `webpanel.auth.require_member`, `webpanel.app._require_member_in_chat`
- Produces: роутер с `GET /api/member/game/pets` и `POST /api/member/game/pets/{action}`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_member_game_api.py`:

```python
"""Кабинет участника: питомцы через сайт, без единого слова в чат."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
import game_actions
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")
member_game = importlib.import_module("webpanel.member_game_api")


@pytest.fixture
def client(monkeypatch):
    отправлено = []
    сделано = []

    async def feed_pet(chat_id, user_id, raw=None):
        сделано.append(("feed", chat_id, user_id, raw))
        return game_actions.ActionResult(
            True, "🍽 Кот накормлен(а).",
            (game_actions.Announcement(game_actions.ANNOUNCE_PET_LEVEL,
                                       "⭐ Кот вырос до уровня 2!"),))

    async def my_pets_text(chat_id, user_id):
        return game_actions.ActionResult(True, "🐾 Ваши питомцы: Кот")

    class _Bot:
        async def send_message(self, chat_id, text, **kw):
            отправлено.append((chat_id, text))

    async def in_chat(user, chat_id):
        if chat_id != -100:
            from fastapi import HTTPException
            raise HTTPException(403, "Вы не состоите в этом чате")

    monkeypatch.setattr(member_game.game_actions, "feed_pet", feed_pet)
    monkeypatch.setattr(member_game.game_actions, "my_pets_text", my_pets_text)
    monkeypatch.setattr(member_game, "get_bot", lambda: _Bot())
    monkeypatch.setattr(member_game, "require_member_in_chat", in_chat)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    monkeypatch.setattr(db, "add_log", lambda *a, **k: _none(), raising=False)

    c = TestClient(panel.app)
    c.отправлено = отправлено
    c.сделано = сделано
    yield c
    panel.app.dependency_overrides.clear()


async def _none():
    return None


def _as_member(tg_user_id=7):
    user = PanelUser(id=9, username="участник", role="member", tg_user_id=tg_user_id)
    panel.app.dependency_overrides[panel.auth.require_member] = lambda: user
    return user


def test_список_питомцев_отдаётся(client):
    _as_member()
    r = client.get("/api/member/game/pets?chat_id=-100")
    assert r.status_code == 200
    assert "Кот" in r.json()["text"]


def test_кормление_с_сайта_не_пишет_отчёт_в_чат(client):
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "накормлен" in r.json()["text"]
    тексты = [t for _chat, t in client.отправлено]
    assert not any("накормлен" in t for t in тексты), "отчёт ушёл в чат — это спам"


def test_награда_всё_равно_объявляется(client):
    _as_member()
    client.post("/api/member/game/pets/feed", json={"chat_id": -100, "key": "kot"})
    тексты = [t for _chat, t in client.отправлено]
    assert any("уровня 2" in t for t in тексты), "ачивки и уровни объявлять надо"


def test_чужой_чат_отбивается(client):
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -999, "key": "kot"})
    assert r.status_code == 403
    assert not client.сделано


def test_неизвестное_действие(client):
    _as_member()
    r = client.post("/api/member/game/pets/станцевать",
                    json={"chat_id": -100})
    assert r.status_code == 400


def test_неудача_по_правилам_это_не_ошибка_http(client, monkeypatch):
    """«Не хватило корма» — законный исход игры, а не сбой."""
    async def feed_fail(chat_id, user_id, raw=None):
        return game_actions.ActionResult.fail("Нет корма.")
    monkeypatch.setattr(member_game.game_actions, "feed_pet", feed_fail)
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_эндпоинты_кабинета_шлют_только_объявления():
    """Сторож тишины. Обычным тестом не поймать: сообщение уходит в рабочем
    Telegram, а не в проверке. Читаем исходник."""
    import inspect
    src = inspect.getsource(member_game)
    отправки = src.count("send_message")
    assert отправки == 1, ("send_message в кабинете должен быть ровно один — "
                           "в общем отправителе объявлений")
    assert "announcements" in src
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_member_game_api.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'webpanel.member_game_api'`

- [ ] **Step 3: Написать роутер**

Создать `webpanel/member_game_api.py`:

```python
"""Кабинет участника: игра через сайт.

Отдельным модулем, а не дописыванием в app.py: тот уже 4400+ строк.

Тишина держится на одном: отчёт возвращается в HTTP-ответе и никуда больше,
а в чат уходят только объявления — ачивки, уровни, звёзды. Их шлёт ровно
одно место (_announce), и тест это стережёт: второй send_message в этом
файле — уже спам.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import db
import game_actions

from . import auth
from .auth import PanelUser

router = APIRouter()

# Проставляются из app.py при подключении: модуль не импортирует app,
# иначе получился бы цикл.
get_bot = None
require_member_in_chat = None


class PetActionBody(BaseModel):
    chat_id: int
    key: Optional[str] = None
    name: Optional[str] = None
    confirm: bool = False


async def _announce(chat_id: int, result: game_actions.ActionResult) -> None:
    """Единственное место, откуда кабинет пишет в чат.

    Отчёт о нажатии сюда не попадает никогда — только награды, которые
    положено показать людям, даже если кнопку нажали на сайте.
    """
    for item in result.announcements:
        await get_bot().send_message(chat_id, item.text)


@router.get("/api/member/game/pets")
async def api_member_pets(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await require_member_in_chat(user, chat_id)
    result = await game_actions.my_pets_text(chat_id, user.tg_user_id)
    return {"ok": result.ok, "text": result.text}


_ACTIONS = {
    "feed": lambda body, chat_id, uid: game_actions.feed_pet(chat_id, uid, body.key),
    "walk": lambda body, chat_id, uid: game_actions.walk_pet(chat_id, uid, body.key),
    "buy": lambda body, chat_id, uid: game_actions.buy_pet(chat_id, uid, body.key),
    "sell": lambda body, chat_id, uid: game_actions.sell_pet(chat_id, uid, body.key,
                                                             confirm=body.confirm),
    "rename": lambda body, chat_id, uid: game_actions.rename_pet(chat_id, uid, body.key,
                                                                 body.name),
    "pin": lambda body, chat_id, uid: game_actions.pin_pet(chat_id, uid, body.key),
    "unpin": lambda body, chat_id, uid: game_actions.unpin_pet(chat_id, uid),
    "food": lambda body, chat_id, uid: game_actions.buy_food(chat_id, uid, 1),
}


@router.post("/api/member/game/pets/{action}")
async def api_member_pet_action(
    action: str, body: PetActionBody, request: Request,
    user: PanelUser = Depends(auth.require_member),
):
    auth.verify_csrf(request)
    if action not in _ACTIONS:
        raise HTTPException(400, "Такого действия нет")
    await require_member_in_chat(user, body.chat_id)
    result = await _ACTIONS[action](body, body.chat_id, user.tg_user_id)
    await _announce(body.chat_id, result)
    await db.add_log("member_game", chat_id=body.chat_id,
                     actor_id=user.tg_user_id, details=f"pets/{action}")
    return {"ok": result.ok, "text": result.text}
```

Ласка добавляется отдельными ключами `pet`, `hug`, `kiss`, зовущими
`game_actions.care_pet` с соответствующим глаголом; массовые формы —
ключами `feed_all`, `care_all`, `walk_all`.

- [ ] **Step 4: Подключить роутер**

В `webpanel/app.py` рядом с уже существующим подключением роутера настроек
добавить:

```python
from .member_game_api import router as member_game_router  # noqa: E402
member_game_api.get_bot = get_bot
member_game_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_game_router)
```

(с `from . import member_game_api` выше — модуль нужен по имени, чтобы
проставить в него две зависимости и не завести цикл импорта).

- [ ] **Step 5: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/test_member_game_api.py -q`
Expected: PASS

- [ ] **Step 6: Проверить, что панель поднимается**

Run: `.venv/bin/python -c "import webpanel.app; print('панель импортируется')"`
Expected: `панель импортируется`

- [ ] **Step 7: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Коммит**

```bash
git add webpanel/member_game_api.py webpanel/app.py tests/test_member_game_api.py
git commit -m "$(cat <<'EOF'
Кабинет участника: питомцы через сайт, без спама в чат

Отчёт о нажатии возвращается в ответе HTTP и никуда больше. В чат уходят
только награды — ачивки и уровни, — и шлёт их ровно одно место. Сторож
считает send_message в файле: второй означал бы, что кто-то начал слать
отчёты, а это и есть спам, от которого всё затевалось.

Неудача по правилам отдаётся с кодом 200 и ok=false: «не хватило корма» —
законный исход игры, а не сбой сервера.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Вкладка «Питомцы» в кабинете

**Files:**
- Modify: `webpanel/static/webapp.html`, `webpanel/static/webapp.js`
- Test: `tests/test_member_game_api.py` (дописать проверку разметки)

**Interfaces:**
- Consumes: `GET /api/member/game/pets`, `POST /api/member/game/pets/{action}`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_member_game_api.py`:

```python
def test_вкладка_питомцев_есть_в_кабинете():
    """Кнопка без экрана (и наоборот) — мёртвый пункт: нажимается и ничего
    не открывает. Проверяем обе половины и связку с загрузчиком."""
    import pathlib
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    html = (static / "webapp.html").read_text(encoding="utf-8")
    js = (static / "webapp.js").read_text(encoding="utf-8")
    assert 'data-mtab="gamepets"' in html
    assert 'id="mtab-gamepets"' in html
    assert "loadGamePets" in js
    assert "/api/member/game/pets" in js
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_member_game_api.py -q`
Expected: FAIL, `assert 'data-mtab="gamepets"' in html`

- [ ] **Step 3: Сверить имена помощников**

Run: `grep -nE "function (say|toast|escapeHtml|skeleton)|const \\\$" webpanel/static/webapp.js`
Expected: список существующих помощников. Использовать ТОЛЬКО их — выдуманное
имя означает молча неработающую вкладку: ошибка вылезет в браузере, а тесты
её не увидят.

- [ ] **Step 4: Добавить разметку и загрузчик**

В `webapp.html` добавить кнопку вкладки рядом с существующими
(`data-mtab="gamepets"`) и экран `id="mtab-gamepets"` с местом под список и
под сообщение.

В `webapp.js` добавить `loadGamePets()`, который дёргает
`GET /api/member/game/pets?chat_id=…`, рисует текст и кнопки действий
(«Покормить», «Погладить», «Гулять»), а по нажатию шлёт
`POST /api/member/game/pets/{action}` и показывает `text` из ответа на месте,
не перезагружая экран. Подключить вызов в переключателе вкладок так же, как
подключены существующие.

- [ ] **Step 5: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Пересобрать архив**

```bash
rm -f arc.zip && zip -q -r arc.zip . \
  -x '.git/*' '.venv/*' 'venv/*' '*/__pycache__/*' '__pycache__/*' '*.pyc' \
     '.pytest_cache/*' '*/.pytest_cache/*' \
     'images/*' 'rp_media/*' 'webpanel/static/rp_media/*' 'demo_out/*' \
     '*.jpg' '*.jpeg' 'arc.zip' \
  && unzip -t arc.zip >/dev/null && ls -lh arc.zip
```

- [ ] **Step 7: Коммит**

```bash
git add webpanel/static/webapp.html webpanel/static/webapp.js tests/test_member_game_api.py
git commit -m "$(cat <<'EOF'
Вкладка «Питомцы» в кабинете участника

Ответ действия показывается на месте, экран не перезагружается: человек
жмёт «покормить» десять раз подряд, и каждый раз видеть мигание списка —
раздражает сильнее, чем устаревшая цифра.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Что НЕ входит в этот план

- Инвентарь, магазин, ферма с огородом, бизнесы — следующие планы того же
  подпроекта. Они повторяют приём, проверенный здесь.
- Эволюция питомца, смена способности, «пет раздать», «пет удалить» —
  остаются в `bot.py`: в кабинете их нет, а трогать работающий код без нужды
  — лишний риск.
- PvP-действия (ограбление, налёт, саботаж, медвежатник) — исключены спекой.

## Порядок и зависимости

```
Task 1 (каркас + кормление) ──> Task 2 (сторож паритета)
      │
      ├──> Task 3 (ласка) ──┐
      ├──> Task 4 (прогулка)├──> Task 6 (API) ──> Task 7 (вкладка)
      └──> Task 5 (торговля)┘
```

Task 2 идёт сразу за первым: сторож должен появиться до того, как переносов
станет много, иначе первую же раздвоившуюся правду никто не поймает.
