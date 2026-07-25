# Награды — пороги по ролям (сайт) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** модератор выдаёт награды до степени 3, админ — до 4, старший админ — до 5, степени 6-8 — только владелец; владелец может менять эти пороги на сайте (панель), правки долетают до бота без перезапуска.

**Architecture:** правки — только к уже существующей системе наград (`rewards`/`reward_degree_levels`, 8 степеней). Меняем дефолтную формулу порогов в `bot.py`, добавляем владелец-only редактор на сайте (`webpanel/app.py` + `webpanel/static/`) поверх уже существующего механизма `_signal_action_reload()` → `panel_action_reload_loop`, которым панель и так применяет правки к работающему боту без рестарта.

**Tech Stack:** Python 3.13, aiogram (бот), FastAPI + aiomysql (панель, `webpanel/app.py`), ванильный JS (`webpanel/static/app.js`), pytest (тесты, `tests/conftest.py` подменяет aiogram/aiomysql заглушками там, где настоящих нет).

## Global Constraints

- Пороги по умолчанию: степень 1-3 → модератор, 4 → админ, 5 → старший админ, 6-8 → только владелец (`OWNER_LEVEL=99`).
- Правку порогов на сайте видит и владелец, и админ панели, но **менять** может только владелец (`can_edit` / `require_owner`).
- Существующая бот-команда «право степень N уровень» (`bot.py: _handle_reward_degree_permission`) НЕ меняется — она остаётся доступной админам в рамках их уровня, как и раньше. Ограничение «только владелец» действует исключительно для правки через сайт.
- Число степеней (8), сама выдача награды (`cmd_reward`) и схема БД не меняются.
- Никаких `git commit` — пользователь запретил коммитить что-либо без отдельного явного запроса в моменте.
- Тесты запускаются из `tg-bot/` (conftest.py сам добавляет корень в `sys.path`): `pytest tests/<file>.py -v`.

---

### Task 1: Дефолтные пороги наград + хелп

**Files:**
- Modify: `bot.py:12972-12978` (`_default_reward_degree_level`)
- Modify: `help_texts.py:829-836` (раздел «rewards» → «main» → `text`)
- Create: `tests/test_reward_degree_levels.py`
- Modify: `tests/test_help_texts_accuracy.py` (добавить тест в конец файла)

**Interfaces:**
- Produces: `bot._default_reward_degree_level(degree: int) -> int` — читается `bot.required_reward_level()` (уже существует, не меняется) и панелью в Task 2 (своя копия формулы в `webpanel/roles.py`, не импорт).

- [ ] **Step 1: Написать падающий тест на новую формулу порогов**

Создать `tests/test_reward_degree_levels.py`:

```python
"""Дефолтные пороги доступа к степеням наград (bot.py).

Модератор — до степени 3, админ — до 4, старший админ — до 5, степени 6-8 —
только владелец. Проверяем формулу напрямую (не через полный запуск бота).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

import bot as bot_module  # noqa: E402


@pytest.mark.parametrize(
    "degree,expected_level",
    [
        (1, "LEVEL_MODERATOR"),
        (2, "LEVEL_MODERATOR"),
        (3, "LEVEL_MODERATOR"),
        (4, "LEVEL_ADMIN"),
        (5, "LEVEL_SENIOR"),
        (6, "OWNER_LEVEL"),
        (7, "OWNER_LEVEL"),
        (8, "OWNER_LEVEL"),
    ],
)
def test_дефолтный_порог_по_степени(degree, expected_level):
    expected = getattr(bot_module, expected_level)
    assert bot_module._default_reward_degree_level(degree) == expected


def test_оверрайд_из_бд_важнее_дефолта():
    """required_reward_level уже умеет читать оверрайды — формула дефолта не
    должна её ломать."""
    bot_module.reward_degree_level_overrides[1] = bot_module.OWNER_LEVEL
    try:
        assert bot_module.required_reward_level(1) == bot_module.OWNER_LEVEL
    finally:
        bot_module.reward_degree_level_overrides.pop(1, None)
```

- [ ] **Step 2: Убедиться, что тест падает (старая формула)**

Run: `pytest tests/test_reward_degree_levels.py -v`
Expected: FAIL на степенях 3, 4, 5 (старая формула отдаёт `LEVEL_ADMIN` для 3 и `LEVEL_SENIOR`/иное для 4-5) — либо `SKIPPED`, если в окружении нет настоящего aiogram (тогда переходите к Step 3 и проверяйте по коду; финальный прогон теста будет на машине с `.venv`).

- [ ] **Step 3: Поменять формулу в `bot.py`**

В `bot.py` заменить (строки 12972-12978):

```python
def _default_reward_degree_level(degree: int) -> int:
    """Уровень доступа по умолчанию для выдачи награды степени degree, если нет override."""
    if degree <= 2:
        return LEVEL_MODERATOR
    if degree <= 5:
        return LEVEL_ADMIN
    return LEVEL_SENIOR
```

на:

```python
def _default_reward_degree_level(degree: int) -> int:
    """Уровень доступа по умолчанию для выдачи награды степени degree, если нет override.

    1-3 — модератор, 4 — админ, 5 — старший админ, 6-8 — только владелец."""
    if degree <= 3:
        return LEVEL_MODERATOR
    if degree == 4:
        return LEVEL_ADMIN
    if degree == 5:
        return LEVEL_SENIOR
    return OWNER_LEVEL
```

- [ ] **Step 4: Прогнать тест — должен пройти**

Run: `pytest tests/test_reward_degree_levels.py -v`
Expected: PASS (или `SKIPPED`, если окружение без настоящего aiogram — в этом
случае финальную проверку делает исполнитель на машине с `.venv`).

- [ ] **Step 5: Обновить хелп и тест на соответствие**

В `help_texts.py` заменить (строки 834-836):

```python
                        "Доступ к степени зависит от уровня: 1-2 — Модератор, 3-5 — Администратор, "
                        "6-8 — Старший администратор (настраивается командой «право степень N "
                        "уровень»)\n\n"
```

на:

```python
                        "Доступ к степени зависит от уровня: 1-3 — Модератор, 4 — Администратор, "
                        "5 — Старший администратор, 6-8 — только Владелец. Пороги можно поменять "
                        "командой «право степень N уровень» или в панели на сайте (вкладка "
                        "«Дерево команд» — там менять пороги может только владелец)\n\n"
```

Добавить в конец `tests/test_help_texts_accuracy.py`:

```python
def test_награды_хелп_соответствует_порогам_по_умолчанию():
    """Хелп называет конкретные степени по ролям — если формула в bot.py
    поменяется, а хелп нет, админы будут объяснять новичкам неверные пороги."""
    bot = _source("bot.py")
    help_src = _help_text()

    body = bot[bot.index("def _default_reward_degree_level"):]
    body = body[:body.index("\n\ndef ")]
    assert "degree <= 3" in body
    assert "degree == 4" in body
    assert "degree == 5" in body
    assert "return OWNER_LEVEL" in body

    assert "1-3 — Модератор" in help_src
    assert "4 — Администратор" in help_src
    assert "5 — Старший администратор" in help_src
    assert "6-8 — только Владелец" in help_src
```

- [ ] **Step 6: Прогнать оба теста**

Run: `pytest tests/test_reward_degree_levels.py tests/test_help_texts_accuracy.py -v`
Expected: PASS (пороговый тест — PASS либо SKIPPED без настоящего aiogram; тест хелпа — PASS всегда, он не импортирует bot.py, только читает текст файлов).

- [ ] **Step 7: Commit**

Не коммитить — пользователь запретил любые `git commit` без отдельного явного запроса в моменте.

---

### Task 2: Панель — редактор порогов наград (backend)

**Files:**
- Modify: `webpanel/roles.py` (добавить константы и хелпер рядом с существующими `LEVEL_*`)
- Modify: `webpanel/app.py` (два новых эндпоинта, рядом с `/api/command-tree*`, после строки 1264)
- Create: `tests/test_panel_reward_levels.py`

**Interfaces:**
- Consumes: `db.list_reward_degree_levels() -> dict[int, int]`, `db.set_reward_degree_level(degree: int, min_level: int, updated_by: int|None) -> None`, `db.reset_reward_degree_level(degree: int) -> None` (все три уже существуют в `db.py`, не меняются); `roles.load() -> RoleMap` (существует); `PanelUser.is_owner` (существует); `_signal_action_reload()` (существует, `webpanel/app.py:1206`).
- Produces: `roles.REWARD_DEGREE_EMOJI: dict[int, str]`, `roles.default_reward_degree_level(degree: int) -> int` — используются эндпоинтом ниже и могут переиспользоваться фронтендом/другими частями панели. `GET /api/reward-levels`, `POST /api/reward-levels/level` — контракт см. в шагах ниже.

- [ ] **Step 1: Написать падающие тесты для панели**

Создать `tests/test_panel_reward_levels.py`:

```python
"""Пороги наград по степеням — панель.

GET  /api/reward-levels        — список порогов 1-8 (владелец и админ панели видят)
POST /api/reward-levels/level  — изменить/сбросить порог (только владелец)
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")


@pytest.fixture
def client(monkeypatch):
    state = {"overrides": {}, "reload_value": None, "logs": []}

    async def list_reward_degree_levels():
        return dict(state["overrides"])

    async def set_reward_degree_level(degree, min_level, updated_by=None):
        state["overrides"][degree] = min_level

    async def reset_reward_degree_level(degree):
        state["overrides"].pop(degree, None)

    async def set_data(key, value, updated_by=None):
        if key == "panel_action_reload":
            state["reload_value"] = value

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    async def fetch_settings():
        return {}

    async def list_admins():
        return []

    monkeypatch.setattr(db, "list_reward_degree_levels", list_reward_degree_levels)
    monkeypatch.setattr(db, "set_reward_degree_level", set_reward_degree_level)
    monkeypatch.setattr(db, "reset_reward_degree_level", reset_reward_degree_level)
    monkeypatch.setattr(db, "set_data", set_data)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings)
    monkeypatch.setattr(db, "list_admins", list_admins)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    c = TestClient(panel.app)
    c.state = state
    yield c
    panel.app.dependency_overrides.clear()


def _as_owner():
    owner = PanelUser(id=1, username="owner", role="owner")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: owner
    panel.app.dependency_overrides[panel.auth.require_owner] = lambda: owner
    return owner


def _as_staff():
    admin = PanelUser(id=2, username="admin", role="admin")
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: admin
    return admin


def test_админ_видит_пороги_без_права_правки(client):
    _as_staff()
    d = client.get("/api/reward-levels").json()
    assert len(d["degrees"]) == 8
    deg1 = next(x for x in d["degrees"] if x["degree"] == 1)
    assert deg1["level"] == 1  # LEVEL_MODERATOR по умолчанию
    deg6 = next(x for x in d["degrees"] if x["degree"] == 6)
    assert deg6["level"] == 99  # OWNER_LEVEL по умолчанию
    assert d["can_edit"] is False


def test_владелец_видит_право_правки(client):
    _as_owner()
    d = client.get("/api/reward-levels").json()
    assert d["can_edit"] is True


def test_владелец_меняет_порог(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 4, "level": 3})
    assert res.status_code == 200, res.text
    assert client.state["overrides"][4] == 3
    assert res.json() == {"ok": True, "level": 3, "overridden": True}
    assert client.state["reload_value"] is not None
    assert "reward_degree_level_set" in client.state["logs"]


def test_сброс_порога_к_умолчанию(client):
    _as_owner()
    client.state["overrides"][4] = 3
    res = client.post("/api/reward-levels/level", json={"degree": 4, "level": None})
    assert res.status_code == 200, res.text
    assert 4 not in client.state["overrides"]
    assert res.json() == {"ok": True, "level": 2, "overridden": False}  # LEVEL_ADMIN — дефолт для степени 4
    assert "reward_degree_level_reset" in client.state["logs"]


def test_недопустимая_степень(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 9, "level": 1})
    assert res.status_code == 400


def test_недопустимый_уровень(client):
    _as_owner()
    res = client.post("/api/reward-levels/level", json={"degree": 1, "level": 5})
    assert res.status_code == 400


def test_админ_не_может_менять_порог(client, monkeypatch):
    """require_owner сам вызывает require_user внутри (не через Depends), поэтому
    dependency_overrides для require_user тут не сработал бы — подменяем
    require_user напрямую в модуле, чтобы реальная проверка is_owner в
    require_owner отработала и вернула 403."""
    admin = PanelUser(id=2, username="admin", role="admin")

    async def fake_require_user(request):
        return admin

    monkeypatch.setattr(panel.auth, "require_user", fake_require_user)
    res = client.post("/api/reward-levels/level", json={"degree": 1, "level": 2})
    assert res.status_code == 403
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_panel_reward_levels.py -v`
Expected: FAIL — `404 Not Found` на всех запросах (эндпоинтов ещё нет).

- [ ] **Step 3: Добавить хелперы в `webpanel/roles.py`**

Добавить в `webpanel/roles.py` после блока `LEVEL_ALIASES` (после строки 61, перед `def owner_ids()`):

```python
# Награды (медали): 8 степеней, порог доступа к каждой хранится в БД
# (reward_degree_levels) с фолбэком на формулу по умолчанию — дублирует
# _default_reward_degree_level из bot.py, править вместе с ней.
REWARD_DEGREE_EMOJI = {
    1: "🎗", 2: "🥉", 3: "🥈", 4: "🥇", 5: "🎖", 6: "🏅", 7: "🏆", 8: "🏵",
}


def default_reward_degree_level(degree: int) -> int:
    if degree <= 3:
        return LEVEL_MODERATOR
    if degree == 4:
        return LEVEL_ADMIN
    if degree == 5:
        return LEVEL_SENIOR
    return OWNER_LEVEL
```

- [ ] **Step 4: Добавить эндпоинты в `webpanel/app.py`**

Добавить в `webpanel/app.py` сразу после `api_command_tree_set_level` (после строки 1264, перед `@app.get("/api/action-sets/{kind}")`):

```python
# --- Пороги наград (степени 1-8 → минимальный уровень доступа) -------------
REWARD_DEGREES = tuple(range(1, 9))
REWARD_LEVELS = (roles.LEVEL_MODERATOR, roles.LEVEL_ADMIN, roles.LEVEL_SENIOR, roles.OWNER_LEVEL)


@app.get("/api/reward-levels")
async def api_reward_levels(user: PanelUser = Depends(auth.require_user)):
    overrides = await db.list_reward_degree_levels()
    role_map = await roles.load()
    degrees = [
        {
            "degree": degree,
            "emoji": roles.REWARD_DEGREE_EMOJI[degree],
            "level": overrides.get(degree, roles.default_reward_degree_level(degree)),
            "overridden": degree in overrides,
        }
        for degree in REWARD_DEGREES
    ]
    return {
        "degrees": degrees,
        "level_names": {str(level): role_map.name_of(level) for level in REWARD_LEVELS},
        "can_edit": user.is_owner,
    }


class RewardLevelBody(BaseModel):
    degree: int
    level: Optional[int] = None  # None — сбросить к уровню по умолчанию


@app.post("/api/reward-levels/level")
async def api_reward_levels_set_level(
    body: RewardLevelBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    if body.degree not in REWARD_DEGREES:
        raise HTTPException(400, "Степень должна быть от 1 до 8.")

    if body.level is None:
        await db.reset_reward_degree_level(body.degree)
        await db.add_log("reward_degree_level_reset", actor_id=user.id, details=str(body.degree))
        result = {"ok": True, "level": roles.default_reward_degree_level(body.degree), "overridden": False}
    else:
        if body.level not in REWARD_LEVELS:
            raise HTTPException(400, "Недопустимый уровень.")
        await db.set_reward_degree_level(body.degree, body.level, updated_by=user.id)
        await db.add_log(
            "reward_degree_level_set", actor_id=user.id, details=f"{body.degree} -> {body.level}",
        )
        result = {"ok": True, "level": body.level, "overridden": True}

    await _signal_action_reload()
    return result
```

`roles` уже импортирован в `webpanel/app.py` (см. `from . import auth, roles` — строка 59), так что дополнительных импортов не требуется.

- [ ] **Step 5: Прогнать тесты — должны пройти**

Run: `pytest tests/test_panel_reward_levels.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 6: Прогнать весь набор тестов панели, чтобы убедиться, что ничего не сломано**

Run: `pytest tests/ -k panel -v`
Expected: PASS (все существующие `test_panel_*` тесты по-прежнему проходят).

- [ ] **Step 7: Commit**

Не коммитить — см. Global Constraints.

---

### Task 3: Бот подхватывает правки без перезапуска

**Files:**
- Modify: `bot.py:3450-3461` (`panel_action_reload_loop`)

**Interfaces:**
- Consumes: `db.list_reward_degree_levels()` (существует), глобальный `reward_degree_level_overrides` (существует, `bot.py:451`).

- [ ] **Step 1: Добавить перечитку кэша порогов наград**

В `bot.py`, внутри `panel_action_reload_loop`, сразу после блока с `command_level_overrides` (после строки, где `command_level_overrides.update(await db.list_command_levels())`, и перед `logger.info(...)`):

```python
                reward_degree_level_overrides.clear()
                reward_degree_level_overrides.update(await db.list_reward_degree_levels())
```

Итоговый блок должен выглядеть так (для сверки):

```python
                command_level_overrides.clear()
                command_level_overrides.update(await db.list_command_levels())
                reward_degree_level_overrides.clear()
                reward_degree_level_overrides.update(await db.list_reward_degree_levels())
                logger.info("РП/себяшки/жесты отн/фильтр слов/права команд перечитаны по сигналу из панели")
```

- [ ] **Step 2: Убедиться, что бот всё ещё импортируется без ошибок**

Run: `python -c "import os; os.environ.setdefault('BOT_TOKEN','123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN'); os.environ.setdefault('OWNER_IDS','1'); import bot"`
Expected: без исключений (никакого вывода — успешный импорт). Если в окружении нет реального aiogram/aiomysql — команда упадёт на импорте `aiogram`/`aiomysql` ещё до наших правок; в этом случае проверка делается на машине с `.venv`, где реально крутится бот.

Отдельного автотеста на сам цикл `panel_action_reload_loop` в проекте нет и раньше не было (это `while True` с `asyncio.sleep`, аналогичный уже существующий блок с `command_level_overrides` тоже не покрыт тестом) — не добавляем его и здесь, чтобы не отклоняться от установленного в проекте подхода. Проверка «правки долетают до бота» — вручную, см. Task 4 Step 4.

- [ ] **Step 3: Commit**

Не коммитить — см. Global Constraints.

---

### Task 4: Фронтенд — карточка «Пороги наград» во вкладке «Дерево команд»

**Files:**
- Modify: `webpanel/static/index.html` (внутри `#view-cmdtree`, после строки 508)
- Modify: `webpanel/static/app.js` (рядом с `loadCommandTree`/`renderCommandTree`/`cmdSetLevel`, после строки 1106; плюс один вызов в переключателе вкладок, строка 1033)

**Interfaces:**
- Consumes: `GET /api/reward-levels`, `POST /api/reward-levels/level` (Task 2).
- Produces: ничего, чем пользуются другие задачи (лист-узел).

- [ ] **Step 1: Добавить контейнер карточки в разметку**

В `webpanel/static/index.html`, внутри `<section class="view hidden" id="view-cmdtree">`, сразу после `<div id="cmdtree-body"></div>` (строка 508) и перед закрывающим `</section>` (строка 509):

```html
      <header class="page-head" style="margin-top: var(--gap-4)">
        <h2>🎖 Пороги наград</h2>
        <p class="sub">Кто может выдавать награду какой степени. Правки применяются в чатах через несколько секунд.</p>
      </header>
      <div id="reward-levels-body"></div>
```

- [ ] **Step 2: Добавить JS-логику**

В `webpanel/static/app.js`, сразу после конца `renderCommandTree`/`cmdSetLevel`/поиска по дереву команд (после строки 1106, перед комментарием `// --- чаты ---`):

```javascript
// ===== Пороги наград (владелец) ============================================
let _rewardLevels = null;

async function loadRewardLevels() {
  const body = $("#reward-levels-body");
  body.innerHTML = skeleton(2);
  try {
    _rewardLevels = await api("/api/reward-levels");
    renderRewardLevels();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderRewardLevels() {
  const body = $("#reward-levels-body");
  if (!body || !_rewardLevels) return;
  const names = _rewardLevels.level_names || {};
  const canEdit = _rewardLevels.can_edit;
  const lvlName = (l) => escapeHtml(names[String(l)] || ("ур. " + l));
  const levels = [1, 2, 3, 99];
  const options = (sel) => levels.map((l) =>
    `<option value="${l}"${l === sel ? " selected" : ""}>${lvlName(l)}</option>`).join("");
  let out = `<div class="cmdtree-cat">`;
  for (const d of _rewardLevels.degrees) {
    const ctl = canEdit
      ? `<select class="reward-level" data-degree="${d.degree}">${options(d.level)}</select>`
      : `<span class="chip${d.overridden ? " chip-accent" : ""}">${lvlName(d.level)}</span>`;
    const reset = (canEdit && d.overridden)
      ? `<button class="ghost small reward-reset" data-degree="${d.degree}" title="Сбросить к умолчанию">${icon("undo")}</button>` : "";
    out += `<div class="cmdtree-row">
      <div class="cmdtree-cmd"><code>${d.emoji} степень ${d.degree}</code></div>
      <div class="cmdtree-ctl">${ctl}${reset}</div></div>`;
  }
  out += `</div>`;
  body.innerHTML = out;
  if (canEdit) {
    $$(".reward-level").forEach((sel) => sel.addEventListener("change",
      () => rewardSetLevel(Number(sel.dataset.degree), Number(sel.value))));
    $$(".reward-reset").forEach((btn) => btn.addEventListener("click",
      () => rewardSetLevel(Number(btn.dataset.degree), null)));
  }
}

async function rewardSetLevel(degree, level) {
  try {
    const d = await api("/api/reward-levels/level", { method: "POST", body: { degree, level } });
    const row = _rewardLevels.degrees.find((x) => x.degree === degree);
    if (row) { row.level = d.level; row.overridden = d.overridden; }
    renderRewardLevels();
    say("#global-msg", "Порог награды обновлён");
  } catch (err) { say("#global-msg", err.message, "err"); renderRewardLevels(); }
}
```

- [ ] **Step 3: Подключить загрузку к переключателю вкладок**

В `webpanel/static/app.js`, строка 1033, заменить:

```javascript
    if (view === "cmdtree") loadCommandTree();
```

на:

```javascript
    if (view === "cmdtree") { loadCommandTree(); loadRewardLevels(); }
```

- [ ] **Step 4: Проверить вручную в браузере**

В проекте нет JS-тестового рантайма (jest и т.п. не подключены — только pytest для Python-частей), поэтому для фронтенда проверка ручная:

1. Запустить панель локально (см. `README.md`/`INSTALL.md` в `tg-bot/` — обычно `python -m webpanel`).
2. Зайти под владельцем → вкладка «Дерево команд» → под списком команд должна появиться карточка «🎖 Пороги наград» с 8 строками (эмодзи + «степень N»), у каждой — выпадающий список уровня.
3. Поменять уровень для какой-нибудь степени → должно появиться сообщение «Порог награды обновлён», значение сохраняется после обновления страницы (F5).
4. Нажать кнопку сброса (иконка ↺) у изменённой строки → возвращается к дефолтному уровню, кнопка сброса исчезает.
5. Зайти под обычным админом (не владельцем) → та же карточка видна, но вместо выпадающих списков — просто текстовые чипы с уровнем, без кнопки сброса.
6. В боте (в группе, где он состоит) через ~10 сек после правки на сайте выполнить `наградить N` от лица человека с изменённым уровнем — доступ должен соответствовать новому порогу (это же можно проверить логом `"...перечитаны по сигналу из панели"` в консоли бота).

- [ ] **Step 5: Commit**

Не коммитить — см. Global Constraints.

---

## Порядок выполнения

Task 1 → Task 2 → Task 3 → Task 4 (каждая задача самостоятельно тестируема; Task 3 логически зависит от Task 2 в БД, но код не пересекается — можно делать и в обратном порядке между собой, если удобнее).
