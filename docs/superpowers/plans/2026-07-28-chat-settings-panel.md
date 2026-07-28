# Настройки чатов в веб-панели — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать администраторам править 23 настройки чата через сайт, с правами по уровню в боте.

**Architecture:** Чистый модуль `chat_settings.py` описывает каждую настройку (где лежит, какого типа, каких границ, какой командой гейтится). Общий слой в `db.py` читает и пишет по этому описанию. Панель импортирует модуль напрямую и собирает форму сама, ничего не зная про банк или рынок в отдельности. Права берутся из уровня человека в боте, а не из панельной роли.

**Tech Stack:** Python 3.12, FastAPI, aiomysql, pytest, обычный JS без сборки.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-28-chat-settings-panel-design.md`.
- Тесты запускаются ТОЛЬКО из venv: `.venv/bin/python -m pytest`. Системный python3 без pytest.
- Модуль `chat_settings.py` — чистый: без `import db`, без aiogram, без обращений к сети. Как `pets.py`, `farming.py`, `market.py` рядом.
- Панель не может импортировать `bot.py` — это подняло бы второго бота. Реестр команд она читает из таблицы `command_registry`.
- Все тексты для человека — по-русски.
- Комментарии в коде объясняют ПОЧЕМУ так, а не что делает строка. Стиль — как в соседних модулях.
- Сообщения коммитов — по-русски, с объяснением причины, с трейлером `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- После каждой законченной задачи пересобирать `arc.zip` командой из памяти проекта.
- Команды в боте не трогаем: сайт добавляется рядом, а не вместо.
- Существующие 123 маршрута панели на новую проверку прав НЕ переводим.

---

## Файловая структура

| Файл | Ответственность |
|---|---|
| `chat_settings.py` (создать) | Реестр настроек: что есть, где лежит, каких границ. Чистые правила |
| `db.py` (дописать) | Слой чтения/записи по описанию из реестра |
| `webpanel/permissions.py` (создать) | Уровень человека в боте, требуемый уровень команды, проверка |
| `webpanel/chat_settings_api.py` (создать) | Роутер `/api/chat-settings`. Отдельным файлом: `webpanel/app.py` уже 4377 строк |
| `webpanel/app.py` (дописать) | Одна строка `include_router` |
| `webpanel/static/index.html` (дописать) | Кнопка в меню и пустая секция вкладки |
| `webpanel/static/app.js` (дописать) | Загрузка и отрисовка формы |
| `tests/test_chat_settings.py` (создать) | Реестр как чистый модуль + сторож границ |
| `tests/test_panel_permissions.py` (создать) | Уровень из бота, а не из панельной роли |
| `tests/test_panel_chat_settings.py` (создать) | API через TestClient |

---

### Task 1: Реестр настроек

**Files:**
- Create: `chat_settings.py`
- Test: `tests/test_chat_settings.py`

**Interfaces:**
- Consumes: ничего (первая задача)
- Produces: `Setting` (dataclass), `SETTINGS: tuple[Setting, ...]`, `BY_KEY: dict[str, Setting]`, `GROUPS: tuple[str, ...]`, `validate(setting, raw) -> object`, константы `STORAGE_COLUMN`/`STORAGE_DATA`/`STORAGE_SETTINGS`, `KIND_NUMBER`/`KIND_BOOL`/`KIND_CHOICE`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_chat_settings.py`:

```python
"""Реестр настроек чата: чистые правила без БД и телеграма."""

from __future__ import annotations

import pytest

import chat_settings


def test_ключи_не_повторяются():
    keys = [s.key for s in chat_settings.SETTINGS]
    assert len(keys) == len(set(keys))


def test_все_группы_объявлены():
    """GROUPS задаёт порядок блоков в форме. Группа, которой в нём нет,
    оказалась бы внизу в случайном месте."""
    assert {s.group for s in chat_settings.SETTINGS} <= set(chat_settings.GROUPS)


def test_число_настроек_как_в_спеке():
    """23 — не магия: столько перечислено в спеке. Тест ловит потерянную
    строку при правках, а не проверяет арифметику."""
    assert len(chat_settings.SETTINGS) == 23


@pytest.mark.parametrize("setting", chat_settings.SETTINGS, ids=lambda s: s.key)
def test_границы_осмысленны(setting):
    if setting.kind != chat_settings.KIND_NUMBER:
        return
    assert setting.minimum is not None and setting.maximum is not None
    assert setting.minimum <= setting.maximum
    assert setting.minimum <= setting.default <= setting.maximum


@pytest.mark.parametrize("setting", chat_settings.SETTINGS, ids=lambda s: s.key)
def test_у_выбора_умолчание_из_списка(setting):
    if setting.kind != chat_settings.KIND_CHOICE:
        return
    assert setting.choices
    assert setting.default in [value for value, _label in setting.choices]


@pytest.mark.parametrize("setting", chat_settings.SETTINGS, ids=lambda s: s.key)
def test_колоночная_настройка_знает_таблицу_и_колонку(setting):
    if setting.storage != chat_settings.STORAGE_COLUMN:
        return
    assert setting.target and setting.column


def test_валидация_числа():
    s = chat_settings.BY_KEY["market.max_goods"]
    assert chat_settings.validate(s, "5") == 5
    with pytest.raises(ValueError):
        chat_settings.validate(s, "не число")
    with pytest.raises(ValueError):
        chat_settings.validate(s, "0")        # ниже минимума
    with pytest.raises(ValueError):
        chat_settings.validate(s, "1000")     # выше максимума


def test_валидация_переключателя():
    s = chat_settings.BY_KEY["stock.enabled"]
    assert chat_settings.validate(s, "1") is True
    assert chat_settings.validate(s, "0") is False
    with pytest.raises(ValueError):
        chat_settings.validate(s, "да")


def test_валидация_выбора():
    s = chat_settings.BY_KEY["market.mode"]
    assert chat_settings.validate(s, "auto_accept") == "auto_accept"
    with pytest.raises(ValueError):
        chat_settings.validate(s, "как-нибудь")


def test_ошибка_валидации_по_русски():
    """Текст уходит человеку в панель как есть."""
    s = chat_settings.BY_KEY["market.max_goods"]
    with pytest.raises(ValueError) as err:
        chat_settings.validate(s, "1000")
    assert "1" in str(err.value) and "100" in str(err.value)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_chat_settings.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'chat_settings'`

- [ ] **Step 3: Написать модуль**

Создать `chat_settings.py`:

```python
"""Настройки чата: что вообще настраивается, где лежит и в каких границах.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как pets.py и farming.py
рядом. Чтение и запись — в db.py, форма — в панели.

Зачем реестр вместо страницы на каждую подсистему. Настройка живёт в трёх
местах сразу: обработчик в боте, эндпоинт панели, поле в форме. Опиши её
руками трижды — и однажды забудешь одно из трёх, а бот про это не скажет.
С реестром новая настройка — одна строка, и на сайте она появляется сама.

ТРИ ХРАНИЛИЩА, а не одно, и это не небрежность, а то, как сложилось:
  * STORAGE_COLUMN   — колонка початовой таблицы (bank_settings и другие);
  * STORAGE_DATA     — ключ в общем key-value (норма, боссы, автоотказ);
  * STORAGE_SETTINGS — колонка глобальной строки settings (исход дуэли).
Умей реестр только первое — треть настроек уехала бы в исключения, и подход
развалился бы там же, где его выбрали.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STORAGE_COLUMN = "column"
STORAGE_DATA = "data"
STORAGE_SETTINGS = "settings"

KIND_NUMBER = "number"
KIND_BOOL = "bool"
KIND_CHOICE = "choice"


@dataclass(frozen=True)
class Setting:
    key: str            # устойчивый ключ для API: "bank.rate_1d"
    group: str          # заголовок блока в форме
    command_key: str    # команда бота — отсюда берётся требуемый уровень
    title: str
    kind: str
    storage: str
    # STORAGE_COLUMN — имя таблицы; STORAGE_DATA — шаблон ключа с {chat_id};
    # STORAGE_SETTINGS — имя колонки глобальной строки.
    target: str
    column: str = ""
    default: object = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    # Переключатель, у которого НАЛИЧИЕ ключа означает «выключено». Так
    # устроены боссы (boss_off:{chat_id}), и притворяться, что это обычный
    # флаг, нельзя: включение здесь — удаление ключа, а не запись нуля.
    inverted: bool = False
    # Настройка одна на всех, а не на чат. Панель обязана это подписать,
    # иначе правка в одном чате незаметно изменит все.
    is_global: bool = False

    @property
    def integer(self) -> bool:
        """Целое ли число. Дробные у нас только проценты и ставки."""
        return isinstance(self.default, int) and not isinstance(self.default, bool)


GROUPS: tuple[str, ...] = (
    "Банк", "Рынок", "Биржа", "Брак", "Ферма", "Активность", "Боссы", "Дуэли",
)

_PERCENT = "Проценты, от 0 до 100."

SETTINGS: tuple[Setting, ...] = (
    # --- Банк ---------------------------------------------------------------
    Setting("bank.rate_1d", "Банк", "bank_manage", "Ставка вклада на 1 день, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_1d",
            default=5.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.rate_3d", "Банк", "bank_manage", "Ставка вклада на 3 дня, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_3d",
            default=7.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.rate_7d", "Банк", "bank_manage", "Ставка вклада на 7 дней, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_7d",
            default=10.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.credit_fee_percent", "Банк", "bank_manage", "Комиссия по кредиту, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_fee_percent",
            default=20.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.credit_term_days", "Банк", "bank_manage", "Срок кредита, дней",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_term_days",
            default=7, minimum=1, maximum=365),
    Setting("bank.credit_penalty_percent", "Банк", "bank_manage", "Пеня по кредиту, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_penalty_percent",
            default=10.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.min_deposit", "Банк", "bank_manage", "Минимальный вклад, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "min_deposit",
            default=1000, minimum=1, maximum=1_000_000_000),
    Setting("bank.auto_reject", "Банк", "bank_auto_reject_toggle",
            "Автоотказ по заявкам на кредит",
            KIND_BOOL, STORAGE_DATA, "bank_autoreject:{chat_id}",
            default=False,
            hint="Включено — новые заявки на кредит отбиваются сразу."),

    # --- Рынок --------------------------------------------------------------
    Setting("market.mode", "Рынок", "market_manage", "Разбор заявок",
            KIND_CHOICE, STORAGE_COLUMN, "market_settings", "mode",
            default="manual",
            choices=(("manual", "вручную — заявки ждут решения"),
                     ("auto_accept", "автопринятие — одобряются сразу"),
                     ("auto_reject", "автоотклонение — новые не принимаются"))),
    Setting("market.commission_percent", "Рынок", "market_manage", "Комиссия с продажи, %",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "commission_percent",
            default=10.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("market.max_price", "Рынок", "market_manage", "Потолок цены товара, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "max_price",
            default=50_000, minimum=1, maximum=100_000_000),
    Setting("market.max_goods", "Рынок", "market_manage", "Товаров на человека",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "max_goods",
            default=3, minimum=1, maximum=100),

    # --- Биржа --------------------------------------------------------------
    Setting("stock.enabled", "Биржа", "stock_toggle", "Биржа включена",
            KIND_BOOL, STORAGE_COLUMN, "stock_settings", "enabled",
            default=True,
            hint="Выключенная биржа сохраняет акции и дивиденды."),
    Setting("stock.min_change_percent", "Биржа", "stock_settings", "Минимальный шаг курса, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "min_change_percent",
            default=-15.0, minimum=-100, maximum=0,
            hint="Отрицательное число: насколько курс может упасть за шаг."),
    Setting("stock.max_change_percent", "Биржа", "stock_settings", "Максимальный шаг курса, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "max_change_percent",
            default=15.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("stock.dividend_percent", "Биржа", "stock_settings", "Дивиденды, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "dividend_percent",
            default=5.0, minimum=0, maximum=100, hint=_PERCENT),

    # --- Брак ---------------------------------------------------------------
    Setting("marriage.renew_price", "Брак", "marriage_price_set", "Цена продления, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "marriage_settings", "renew_price",
            default=500, minimum=0, maximum=1_000_000_000),
    Setting("marriage.divorce_mode", "Брак", "marriage_mode_set", "Истёкший брак",
            KIND_CHOICE, STORAGE_COLUMN, "marriage_settings", "divorce_mode",
            default="off",
            choices=(("off", "остаётся в силе"),
                     ("auto", "расторгается сам"))),
    Setting("marriage.rating_enabled", "Брак", "marriage_rating_toggle", "Рейтинг браков",
            KIND_BOOL, STORAGE_COLUMN, "marriage_settings", "rating_enabled",
            default=True),

    # --- Ферма --------------------------------------------------------------
    Setting("economy.farm_yield", "Ферма", "farm_yield_set", "Урожайность фермы, %",
            KIND_NUMBER, STORAGE_COLUMN, "economy_settings", "farm_yield",
            default=100.0, minimum=1, maximum=1000,
            hint="100 — обычная. Множитель выдачи команды «ферма»."),

    # --- Активность ---------------------------------------------------------
    Setting("activity.norm", "Активность", "set_norm", "Недельная норма сообщений",
            KIND_NUMBER, STORAGE_DATA, "norm:{chat_id}",
            default=0, minimum=0, maximum=100_000,
            hint="0 — норма снята. Кто не набрал — команда «не в норме»."),

    # --- Боссы --------------------------------------------------------------
    Setting("boss.enabled", "Боссы", "boss_toggle", "Боссы приходят в чат",
            KIND_BOOL, STORAGE_DATA, "boss_off:{chat_id}",
            default=True, inverted=True),

    # --- Дуэли --------------------------------------------------------------
    Setting("duel.outcome", "Дуэли", "duel_outcome", "Что бывает проигравшему",
            KIND_CHOICE, STORAGE_SETTINGS, "duel_outcome",
            default="kick", is_global=True,
            choices=(("0", "ничего не делать"),
                     ("kick", "кик"),
                     ("ban_minute", "бан на 1 минуту"),
                     ("ban_10min", "бан на 10 минут"),
                     ("ban_hour", "бан на 1 час"),
                     ("ban_day", "бан на сутки"),
                     ("ban_forever", "бан навсегда"),
                     ("mute_minute", "мут на 1 минуту"),
                     ("mute_10min", "мут на 10 минут"),
                     ("mute_hour", "мут на 1 час"),
                     ("mute_day", "мут на сутки"),
                     ("mute_forever", "мут навсегда"))),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}


def validate(setting: Setting, raw) -> object:
    """Значение из формы — в то, что можно писать в базу.

    Бросает ValueError с русским текстом: он уходит человеку в панель как
    есть, поэтому «invalid literal for int()» здесь недопустим.
    """
    if setting.kind == KIND_BOOL:
        text = str(raw).strip()
        if text in ("1", "true", "True"):
            return True
        if text in ("0", "false", "False"):
            return False
        raise ValueError("Переключатель принимает только 1 или 0.")

    if setting.kind == KIND_CHOICE:
        text = str(raw).strip()
        allowed = [value for value, _label in setting.choices]
        if text not in allowed:
            raise ValueError("Такого варианта нет. Доступны: " + ", ".join(allowed))
        return text

    text = str(raw).strip().replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        raise ValueError("Нужно число.") from None
    if setting.minimum is not None and number < setting.minimum:
        raise ValueError(f"Слишком мало: допустимо от {_num(setting.minimum)} "
                         f"до {_num(setting.maximum)}.")
    if setting.maximum is not None and number > setting.maximum:
        raise ValueError(f"Слишком много: допустимо от {_num(setting.minimum)} "
                         f"до {_num(setting.maximum)}.")
    return int(number) if setting.integer else number


def _num(value) -> str:
    """Число для текста ошибки: без хвоста «.0» у целых."""
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else str(value)
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_chat_settings.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add chat_settings.py tests/test_chat_settings.py
git commit -m "$(cat <<'EOF'
Реестр настроек чата: одно описание вместо трёх

Настройка живёт в трёх местах сразу — обработчик бота, эндпоинт панели,
поле формы. Описанная руками трижды, она однажды теряется в одном из
трёх, и бот про это не скажет. Реестр делает описание единственным.

Хранилищ три, а не одно: колонки початовых таблиц, общий key-value и
глобальная строка settings. Умей реестр только первое, треть настроек
уехала бы в исключения.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Сторож границ — реестр не расходится с ботом

**Files:**
- Modify: `tests/test_chat_settings.py` (дописать в конец)

**Interfaces:**
- Consumes: `chat_settings.BY_KEY` из Task 1
- Produces: ничего (только тесты)

Смысл задачи: реестр объявляет умолчания и границы, а у бота свои. Разойдутся — сайт и чат начнут принимать разные значения, и никто не заметит. Сверяем с двумя источниками: константами чистых модулей и умолчаниями в DDL.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_chat_settings.py`:

```python
# --- сторож: реестр не расходится с ботом ----------------------------------

def test_умолчания_рынка_совпадают_с_модулем():
    """market.py — источник правды для рынка. Разъедься умолчания, сайт
    показывал бы одно, а бот применял другое."""
    import market
    assert chat_settings.BY_KEY["market.commission_percent"].default == market.DEFAULT_COMMISSION
    assert chat_settings.BY_KEY["market.max_price"].default == market.DEFAULT_MAX_PRICE
    assert chat_settings.BY_KEY["market.max_goods"].default == market.DEFAULT_MAX_GOODS
    assert chat_settings.BY_KEY["market.mode"].default == market.DEFAULT_MODE


def test_варианты_рынка_совпадают_с_модулем():
    import market
    ours = [value for value, _ in chat_settings.BY_KEY["market.mode"].choices]
    assert ours == list(market.MODES)


def _ddl_defaults(table: str) -> dict[str, str]:
    """Умолчания колонок из CREATE TABLE в исходнике db.py.

    Читаем исходник, а не базу: тесты не поднимают MySQL, а умолчания банка
    и брака больше нигде не записаны — только в DDL.
    """
    import inspect
    import re
    import db
    source = inspect.getsource(db)
    start = source.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    tail = source[start:start + 2000]
    return {m.group(1): m.group(2)
            for m in re.finditer(r'"(\w+) [A-Z]+(?:\([\d,]+\))?[^"]*?DEFAULT ([^\s,"]+)', tail)}


@pytest.mark.parametrize("key", [
    "bank.rate_1d", "bank.rate_3d", "bank.rate_7d",
    "bank.credit_fee_percent", "bank.credit_term_days",
    "bank.credit_penalty_percent", "bank.min_deposit",
    "marriage.renew_price", "marriage.divorce_mode",
    "stock.min_change_percent", "stock.max_change_percent", "stock.dividend_percent",
    "economy.farm_yield",
])
def test_умолчание_совпадает_с_ddl(key):
    setting = chat_settings.BY_KEY[key]
    defaults = _ddl_defaults(setting.target)
    raw = defaults[setting.column].strip("'")
    ours = setting.default
    if setting.kind == chat_settings.KIND_CHOICE:
        assert raw == ours
    else:
        assert float(raw) == float(ours), f"{key}: в DDL {raw}, в реестре {ours}"


def test_варианты_исхода_дуэли_совпадают_с_ботом():
    """Список исходов живёт в bot.DUEL_OUTCOME_LABELS. Вариант, которого там
    нет, панель предложит, бот не применит, и человек решит, что сломалось."""
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module
    ours = {value for value, _ in chat_settings.BY_KEY["duel.outcome"].choices}
    assert ours == set(bot_module.DUEL_OUTCOME_LABELS)


def test_варианты_развода_совпадают_с_ботом():
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module
    ours = {value for value, _ in chat_settings.BY_KEY["marriage.divorce_mode"].choices}
    assert ours == set(bot_module.MARRIAGE_DIVORCE_MODES)


def test_каждая_настройка_привязана_к_настоящей_команде():
    """command_key даёт требуемый уровень. Ключ-опечатка означал бы, что
    настройка гейтится уровнем по умолчанию, то есть чем попало."""
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module
    лишние = sorted({s.command_key for s in chat_settings.SETTINGS}
                    - set(bot_module.COMMAND_REGISTRY))
    assert not лишние, f"команд нет в реестре бота: {лишние}"
```

- [ ] **Step 2: Запустить — убедиться, что падает или проходит осмысленно**

Run: `.venv/bin/python -m pytest tests/test_chat_settings.py -q`
Expected: если реестр из Task 1 верен — PASS. Если какой-то тест падает, значит в Task 1 ошиблись в умолчании: правим РЕЕСТР, а не тест.

- [ ] **Step 3: Проверить, что сторож не мнимый**

Временно поменять в `chat_settings.py` умолчание `bank.rate_1d` с `5.0` на `6.0`.

Run: `.venv/bin/python -m pytest tests/test_chat_settings.py -q`
Expected: FAIL с текстом `bank.rate_1d: в DDL 5.00, в реестре 6.0`

Вернуть `5.0` обратно и убедиться, что снова PASS.

- [ ] **Step 4: Коммит**

```bash
git add tests/test_chat_settings.py
git commit -m "$(cat <<'EOF'
Сторож: реестр настроек не расходится с ботом

Реестр объявляет умолчания и границы, а у обработчиков бота свои.
Разойдутся — сайт и чат начнут принимать разные значения, и узнает об
этом первым пользователь. Сверяем с константами чистых модулей и с
умолчаниями из DDL; сторож проверен намеренной поломкой.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Слой чтения и записи в `db.py`

**Files:**
- Modify: `db.py` (дописать рядом с остальными настройками чата)
- Test: `tests/test_chat_settings_storage.py` (создать)

**Interfaces:**
- Consumes: `chat_settings.Setting`, `chat_settings.STORAGE_*` из Task 1
- Produces:
  - `async def get_chat_setting_values(chat_id: int, settings: list) -> dict[str, object]`
  - `async def set_chat_setting_value(chat_id: int, setting, value) -> None`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_chat_settings_storage.py`:

```python
"""Чтение и запись настроек чата по описанию из реестра.

MySQL тесты не поднимают, поэтому подменяем два нижних уровня db (_fetchone,
_fetchall, _execute) и проверяем, ЧТО именно слой запрашивает и пишет.
"""

from __future__ import annotations

import asyncio
import functools

import pytest

import chat_settings
import db


@pytest.fixture
def запросы(monkeypatch):
    """Собирает выполненные запросы и отдаёт заранее заготовленные ответы."""
    written: list[tuple[str, tuple]] = []
    rows: dict[str, dict] = {}
    seen: list[str] = []

    async def fake_execute(query, args=()):
        written.append((" ".join(query.split()), args))
        return 1

    async def fake_fetchone(query, args=()):
        seen.append(query)
        for table, row in rows.items():
            if f"FROM {table}" in query:
                return row
        return None

    monkeypatch.setattr(db, "_execute", fake_execute)
    monkeypatch.setattr(db, "_fetchone", fake_fetchone)
    return type("Q", (), {"written": written, "rows": rows, "seen": seen})


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. tests/test_farming.py). Один декоратор вместо
    asyncio.run в каждом тесте."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@_sync
async def test_читает_колонку_початовой_таблицы(запросы):
    запросы.rows["bank_settings"] = {"rate_1d": 7.5, "min_deposit": 2000}
    s = [chat_settings.BY_KEY["bank.rate_1d"], chat_settings.BY_KEY["bank.min_deposit"]]
    out = await db.get_chat_setting_values(-100, s)
    assert out["bank.rate_1d"] == 7.5
    assert out["bank.min_deposit"] == 2000


@_sync
async def test_нет_строки_чата_значит_умолчание(запросы):
    s = [chat_settings.BY_KEY["bank.rate_1d"]]
    out = await db.get_chat_setting_values(-100, s)
    assert out["bank.rate_1d"] == chat_settings.BY_KEY["bank.rate_1d"].default


@_sync
async def test_одна_таблица_читается_одним_запросом(запросы):
    """Семь настроек банка — не семь походов в базу. Счётчик ведёт фикстура,
    подменять db прямо в тесте нельзя: подмена пережила бы тест."""
    запросы.rows["bank_settings"] = {"rate_1d": 1, "rate_3d": 2, "rate_7d": 3}
    s = [chat_settings.BY_KEY[k] for k in ("bank.rate_1d", "bank.rate_3d", "bank.rate_7d")]
    await db.get_chat_setting_values(-100, s)
    assert len(запросы.seen) == 1


@_sync
async def test_пишет_колонку_с_апсертом(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.rate_1d"], 8.0)
    query, args = запросы.written[-1]
    assert "bank_settings" in query and "rate_1d" in query
    assert -100 in args and 8.0 in args


@_sync
async def test_переключатель_в_data_пишется_единицей(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.auto_reject"], True)
    query, args = запросы.written[-1]
    assert "bot_data" in query
    assert "bank_autoreject:-100" in args and "1" in args


@_sync
async def test_выключение_в_data_удаляет_ключ(запросы):
    await db.set_chat_setting_value(-100, chat_settings.BY_KEY["bank.auto_reject"], False)
    query, _args = запросы.written[-1]
    assert "DELETE FROM bot_data" in query


@_sync
async def test_перевёрнутый_переключатель_наоборот(запросы):
    """Боссы: ключ boss_off есть — боссы ВЫКЛЮЧЕНЫ. Включение стирает ключ."""
    boss = chat_settings.BY_KEY["boss.enabled"]
    await db.set_chat_setting_value(-100, boss, True)
    assert "DELETE FROM bot_data" in запросы.written[-1][0]
    await db.set_chat_setting_value(-100, boss, False)
    query, args = запросы.written[-1]
    assert "INSERT INTO bot_data" in query and "boss_off:-100" in args


@_sync
async def test_перевёрнутый_читается_наоборот(запросы):
    boss = chat_settings.BY_KEY["boss.enabled"]
    out = await db.get_chat_setting_values(-100, [boss])
    assert out["boss.enabled"] is True          # ключа нет — боссы включены
    запросы.rows["bot_data"] = {"data_key": "boss_off:-100", "data_value": "1"}
    out = await db.get_chat_setting_values(-100, [boss])
    assert out["boss.enabled"] is False


@_sync
async def test_глобальная_настройка_читается_из_settings(запросы):
    запросы.rows["settings"] = {"duel_outcome": "ban_day"}
    out = await db.get_chat_setting_values(-100, [chat_settings.BY_KEY["duel.outcome"]])
    assert out["duel.outcome"] == "ban_day"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_chat_settings_storage.py -q`
Expected: FAIL, `AttributeError: module 'db' has no attribute 'get_chat_setting_values'`

- [ ] **Step 3: Написать слой**

Дописать в `db.py` перед `async def ensure_seasons_table`:

```python
# ----------------------------------------------------------------------------
# НАСТРОЙКИ ЧАТА ДЛЯ ПАНЕЛИ (описание — chat_settings.py)
#
# Общий слой возможен только потому, что все початовые таблицы настроек
# устроены одинаково: «строка чата или значения по умолчанию». Читаем по одному
# запросу на таблицу, а не на поле: у банка семь настроек, и семь походов в
# базу ради одной формы — это заметно.
# ----------------------------------------------------------------------------
async def get_chat_setting_values(chat_id: int, settings: list) -> dict:
    """Текущие значения перечисленных настроек. Нет строки чата — умолчание."""
    import chat_settings as cs

    out: dict = {}
    by_table: dict[str, list] = {}
    for setting in settings:
        if setting.storage == cs.STORAGE_COLUMN:
            by_table.setdefault(setting.target, []).append(setting)
        elif setting.storage == cs.STORAGE_DATA:
            row = await get_data(setting.target.format(chat_id=chat_id))
            out[setting.key] = _chat_setting_from_data(setting, row)
        else:
            row = await _fetchone(
                f"SELECT {setting.target} FROM settings WHERE id = 1"
            )
            value = row[setting.target] if row else None
            out[setting.key] = value if value is not None else setting.default

    for table, group in by_table.items():
        columns = ", ".join(sorted({s.column for s in group}))
        row = await _fetchone(
            f"SELECT {columns} FROM {table} WHERE chat_id = %s", (chat_id,)
        )
        for setting in group:
            value = row[setting.column] if row else None
            if value is None:
                out[setting.key] = setting.default
            elif setting.kind == cs.KIND_BOOL:
                out[setting.key] = bool(value)
            elif setting.kind == cs.KIND_CHOICE:
                out[setting.key] = str(value)
            else:
                out[setting.key] = int(value) if setting.integer else float(value)
    return out


def _chat_setting_from_data(setting, row) -> object:
    """Значение настройки, живущей в общем key-value.

    Перевёрнутые (inverted) читаются наоборот: у боссов НАЛИЧИЕ ключа
    boss_off означает «выключено», и притворяться, что это обычный флаг,
    нельзя — иначе включение писало бы ноль вместо удаления ключа.
    """
    import chat_settings as cs

    if setting.kind == cs.KIND_BOOL:
        present = row is not None and (setting.inverted or row.get("data_value") == "1")
        return (not present) if setting.inverted else present
    if row is None:
        return setting.default
    raw = row.get("data_value")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return setting.default
    return int(number) if setting.integer else number


async def set_chat_setting_value(chat_id: int, setting, value) -> None:
    """Запись значения. Значение уже проверено chat_settings.validate."""
    import chat_settings as cs

    if setting.storage == cs.STORAGE_COLUMN:
        await _execute(
            f"INSERT INTO {setting.target} (chat_id, {setting.column}) VALUES (%s, %s) "
            f"ON DUPLICATE KEY UPDATE {setting.column} = VALUES({setting.column})",
            (chat_id, value),
        )
        return

    if setting.storage == cs.STORAGE_SETTINGS:
        await _execute(
            f"UPDATE settings SET {setting.target} = %s WHERE id = 1", (value,)
        )
        return

    key = setting.target.format(chat_id=chat_id)
    if setting.kind == cs.KIND_BOOL:
        # Для перевёрнутых «включить» — это стереть ключ, а не записать ноль.
        write = (not value) if setting.inverted else bool(value)
        if write:
            await set_data(key, "1")
        else:
            await delete_data(key)
        return
    await set_data(key, str(value))
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_chat_settings_storage.py -q`
Expected: PASS

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, ни один существующий тест не сломан

- [ ] **Step 6: Коммит**

```bash
git add db.py tests/test_chat_settings_storage.py
git commit -m "$(cat <<'EOF'
Слой чтения и записи настроек чата по описанию из реестра

Одна функция на все настройки вместо getter/setter на каждую: таблицы
устроены одинаково («строка чата или умолчания»), и это делает общий слой
возможным. Читаем по запросу на ТАБЛИЦУ, а не на поле — у банка семь
настроек, и семь походов в базу ради одной формы заметны.

Перевёрнутые переключатели (боссы: наличие ключа boss_off означает
«выключено») обрабатываются явно: включение стирает ключ, а не пишет ноль.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Права панели по уровню в боте

**Files:**
- Create: `webpanel/permissions.py`
- Test: `tests/test_panel_permissions.py`

**Interfaces:**
- Consumes: `webpanel.auth.PanelUser`, `webpanel.roles.owner_ids()`, `db.get_admin_level`, `db.list_command_levels`, `db.list_command_registry`
- Produces:
  - `async def bot_level(user) -> int`
  - `async def required_level(command_key: str) -> int`
  - `async def ensure(user, command_key: str) -> None` (бросает `HTTPException(403)`)
  - `def level_name(level: int) -> str`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_panel_permissions.py`:

```python
"""Права панели берутся из уровня человека в БОТЕ, а не из панельной роли.

Дыра, которую это чинит: панельная роль admin давала все админские
эндпоинты независимо от уровня в боте — хоть нулевого. Человек-модератор с
панельным аккаунтом admin получал на сайте больше, чем в чате.
"""

from __future__ import annotations

import asyncio
import functools
import importlib

import pytest
from fastapi import HTTPException

import db
from webpanel.auth import PanelUser

permissions = importlib.import_module("webpanel.permissions")


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@pytest.fixture
def мир(monkeypatch):
    уровни = {555: 1, 777: 2}

    async def get_admin_level(user_id):
        return уровни.get(user_id, 0)

    async def list_command_levels():
        return {"bank_manage": 3}

    async def list_command_registry():
        return [
            {"command_key": "bank_manage", "default_level": 2},
            {"command_key": "farm_yield_set", "default_level": 2},
        ]

    monkeypatch.setattr(db, "get_admin_level", get_admin_level, raising=False)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels, raising=False)
    monkeypatch.setattr(db, "list_command_registry", list_command_registry, raising=False)
    monkeypatch.setattr(permissions.roles, "owner_ids", lambda: {1})
    permissions.forget_cache()
    return уровни


@_sync
async def test_аккаунт_без_привязки_имеет_нулевой_уровень(мир):
    """Панельный admin, не привязавший Telegram, — никто с точки зрения бота."""
    user = PanelUser(id=9, username="admin", role="admin", tg_user_id=None)
    assert await permissions.bot_level(user) == 0


@_sync
async def test_уровень_берётся_из_бота(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    assert await permissions.bot_level(user) == 1


@_sync
async def test_владелец_из_env_проходит_всегда(мир):
    """Иначе владелец может запереть себя снаружи."""
    user = PanelUser(id=9, username="own", role="member", tg_user_id=1)
    assert await permissions.bot_level(user) == permissions.OWNER_LEVEL


@_sync
async def test_панельный_владелец_тоже_проходит(мир):
    user = PanelUser(id=1, username="own", role="owner", tg_user_id=None)
    assert await permissions.bot_level(user) == permissions.OWNER_LEVEL


@_sync
async def test_требуемый_уровень_берёт_оверрайд(мир):
    """«право bank_manage 3» должно действовать и на сайте."""
    assert await permissions.required_level("bank_manage") == 3
    assert await permissions.required_level("farm_yield_set") == 2


@_sync
async def test_неизвестная_команда_требует_максимума(мир):
    """Опечатка в ключе не должна ОТКРЫВАТЬ доступ."""
    assert await permissions.required_level("такой нет") == permissions.LEVEL_SENIOR


@_sync
async def test_модератор_не_проходит_туда_где_нужен_админ(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    with pytest.raises(HTTPException) as err:
        await permissions.ensure(user, "farm_yield_set")
    assert err.value.status_code == 403


@_sync
async def test_админ_проходит(мир):
    user = PanelUser(id=9, username="adm", role="admin", tg_user_id=777)
    await permissions.ensure(user, "farm_yield_set")     # не бросает


@_sync
async def test_в_ошибке_названо_нужное_право(мир):
    user = PanelUser(id=9, username="mod", role="admin", tg_user_id=555)
    with pytest.raises(HTTPException) as err:
        await permissions.ensure(user, "farm_yield_set")
    assert "Администратор" in err.value.detail
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_panel_permissions.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'webpanel.permissions'`

- [ ] **Step 3: Написать модуль**

Создать `webpanel/permissions.py`:

```python
"""Права панели — по уровню человека в БОТЕ, а не по панельной роли.

Дыра, которую это чинит. Роли панели (owner/admin/member) живут отдельно от
уровней бота. Панельный admin дёргал все админские эндпоинты независимо от
того, какой у него уровень в боте, — хоть нулевой. Человек-модератор с
панельным аккаунтом admin получал на сайте больше, чем в чате.

Уровни в боте ГЛОБАЛЬНЫЕ: в таблице admins нет chat_id, и «модератор в этом
чате» как понятие не существует. Здесь мы это не чиним, а честно повторяем —
две разные правды о правах были бы хуже одной неудобной.

Владелец (OWNER_IDS или панельная роль owner) проходит всегда: иначе владелец
может запереть себя снаружи и остаться без доступа к собственной панели.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException, status

import db

from . import roles

LEVEL_MEMBER = roles.LEVEL_MEMBER
LEVEL_MODERATOR = roles.LEVEL_MODERATOR
LEVEL_ADMIN = roles.LEVEL_ADMIN
LEVEL_SENIOR = roles.LEVEL_SENIOR
OWNER_LEVEL = roles.OWNER_LEVEL

# Реестр команд и оверрайды уровней меняются редко, а спрашиваются на каждое
# поле формы. Кэш на минуту: правка через «право» доедет почти сразу, а сотня
# полей не превратится в сотню запросов.
_CACHE_TTL_SECONDS = 60
_cache: Optional[tuple[float, dict[str, int]]] = None


def forget_cache() -> None:
    """Сбросить кэш — нужен тестам и после правки уровня из панели."""
    global _cache
    _cache = None


async def _levels() -> dict[str, int]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    registry = {r["command_key"]: int(r["default_level"])
                for r in await db.list_command_registry()}
    registry.update(await db.list_command_levels())
    _cache = (now, registry)
    return registry


async def bot_level(user) -> int:
    """Уровень этого человека в боте."""
    if getattr(user, "is_owner", False):
        return OWNER_LEVEL
    tg_id = getattr(user, "tg_user_id", None)
    if tg_id is None:
        # Аккаунт не привязан к Telegram — бот про такого человека не знает.
        return LEVEL_MEMBER
    if tg_id in roles.owner_ids():
        return OWNER_LEVEL
    return int(await db.get_admin_level(tg_id))


async def required_level(command_key: str) -> int:
    """Уровень, нужный для этой команды: оверрайд, иначе умолчание реестра.

    Неизвестный ключ требует максимума, а не минимума: опечатка не должна
    ОТКРЫВАТЬ доступ.
    """
    return (await _levels()).get(command_key, LEVEL_SENIOR)


def level_name(level: int) -> str:
    return roles.DEFAULT_LEVEL_NAMES.get(level, f"уровень {level}").lstrip("🛡⭐👑🔱 ")


async def ensure(user, command_key: str) -> None:
    """403 с названием нужного уровня, если человек не дотягивает."""
    need = await required_level(command_key)
    have = await bot_level(user)
    if have >= need:
        return
    if getattr(user, "tg_user_id", None) is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Аккаунт не привязан к Telegram — бот не знает вашего уровня. "
            "Привязать можно в панели, раздел «Аккаунты».",
        )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Нужен уровень «{level_name(need)}» и выше.",
    )
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_panel_permissions.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add webpanel/permissions.py tests/test_panel_permissions.py
git commit -m "$(cat <<'EOF'
Права панели — по уровню в боте, а не по панельной роли

Панельная роль admin давала все админские эндпоинты независимо от уровня
в боте, хоть нулевого: человек-модератор с панельным аккаунтом получал на
сайте больше, чем в чате.

Уровни в боте глобальные (в таблице admins нет chat_id), и здесь мы это не
чиним, а честно повторяем: две разные правды о правах хуже одной неудобной.

Владелец проходит всегда — иначе он может запереть себя снаружи. Опечатка
в ключе команды требует МАКСИМУМА, а не минимума: неизвестное имя не
должно открывать доступ.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: API настроек чата

**Files:**
- Create: `webpanel/chat_settings_api.py`
- Modify: `webpanel/app.py` (одна строка `include_router` рядом с определением `app`)
- Test: `tests/test_panel_chat_settings.py`

**Interfaces:**
- Consumes: `chat_settings` (Task 1), `db.get_chat_setting_values` / `db.set_chat_setting_value` (Task 3), `webpanel.permissions` (Task 4), `webpanel.auth.require_user`
- Produces: `router` (`fastapi.APIRouter`), маршруты `GET /api/chat-settings`, `POST /api/chat-settings`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_panel_chat_settings.py`:

```python
"""Настройки чата в панели: чтение всем сотрудникам, правка — по уровню."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import chat_settings
import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")
permissions = importlib.import_module("webpanel.permissions")


@pytest.fixture
def client(monkeypatch):
    записано: list = []
    журнал: list = []

    async def _noop(*a, **k):
        return None

    async def get_values(chat_id, settings):
        return {s.key: s.default for s in settings}

    async def set_value(chat_id, setting, value):
        записано.append((chat_id, setting.key, value))

    async def add_log(event_type, **kwargs):
        журнал.append((event_type, kwargs))

    async def list_current_chats():
        return [{"chat_id": -100, "members": 5, "last_seen": None}]

    async def list_command_registry():
        return [{"command_key": s.command_key, "default_level": 2}
                for s in chat_settings.SETTINGS]

    async def list_command_levels():
        return {}

    async def get_admin_level(user_id):
        return {555: 1, 777: 2}.get(user_id, 0)

    monkeypatch.setattr(db, "get_chat_setting_values", get_values, raising=False)
    monkeypatch.setattr(db, "set_chat_setting_value", set_value, raising=False)
    monkeypatch.setattr(db, "add_log", add_log, raising=False)
    monkeypatch.setattr(db, "list_current_chats", list_current_chats, raising=False)
    monkeypatch.setattr(db, "list_command_registry", list_command_registry, raising=False)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels, raising=False)
    monkeypatch.setattr(db, "get_admin_level", get_admin_level, raising=False)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    monkeypatch.setattr(permissions.roles, "owner_ids", lambda: {1})
    permissions.forget_cache()

    c = TestClient(panel.app)
    c.записано = записано
    c.журнал = журнал
    yield c
    panel.app.dependency_overrides.clear()


def _as(role, tg_user_id):
    user = PanelUser(id=9, username=role, role=role, tg_user_id=tg_user_id)
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: user
    return user


def test_список_отдаёт_группы_и_значения(client):
    _as("admin", 777)
    r = client.get("/api/chat-settings?chat_id=-100")
    assert r.status_code == 200
    data = r.json()
    groups = {g["group"] for g in data["groups"]}
    assert "Банк" in groups and "Рынок" in groups
    all_keys = {s["key"] for g in data["groups"] for s in g["settings"]}
    assert all_keys == set(chat_settings.BY_KEY)


def test_модератор_видит_поля_но_не_может_править(client):
    _as("admin", 555)
    data = client.get("/api/chat-settings?chat_id=-100").json()
    поля = [s for g in data["groups"] for s in g["settings"]]
    assert поля, "поля обязаны показываться, а не прятаться"
    assert all(not s["can_edit"] for s in поля)

    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert not client.записано


def test_админ_правит(client):
    _as("admin", 777)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 200
    assert client.записано == [(-100, "bank.rate_1d", 9.0)]


def test_правка_попадает_в_журнал(client):
    _as("admin", 777)
    client.post("/api/chat-settings",
                json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert client.журнал and client.журнал[0][0] == "chat_setting_set"


def test_неизвестный_ключ_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "нет.такого", "value": "1"})
    assert r.status_code == 400


def test_значение_вне_границ_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "market.max_goods", "value": "1000"})
    assert r.status_code == 400
    assert "1" in r.json()["detail"]
    assert not client.записано


def test_неизвестный_чат_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -999, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 400


def test_аккаунт_без_привязки_не_правит(client):
    _as("admin", None)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert "Telegram" in r.json()["detail"]


def test_глобальная_настройка_помечена(client):
    _as("owner", 1)
    data = client.get("/api/chat-settings?chat_id=-100").json()
    поле = next(s for g in data["groups"] for s in g["settings"]
                if s["key"] == "duel.outcome")
    assert поле["global"] is True
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_panel_chat_settings.py -q`
Expected: FAIL, 404 на `/api/chat-settings`

- [ ] **Step 3: Написать роутер**

Создать `webpanel/chat_settings_api.py`:

```python
"""Настройки чата в панели.

Отдельным файлом, а не дописыванием в app.py: тот уже 4377 строк, и класть
туда ещё один раздел значит закреплять привычку, из-за которой файл и вырос.

Требуемый уровень зависит от НАСТРОЙКИ, а не от маршрута, поэтому зависимостью
FastAPI это не проверить: она про ключ в теле запроса ничего не знает. Проверка
идёт внутри обработчика.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import chat_settings
import db

from . import auth, permissions
from .auth import PanelUser

router = APIRouter()


async def _known_chat(chat_id: int) -> bool:
    return any(row["chat_id"] == chat_id for row in await db.list_current_chats())


@router.get("/api/chat-settings")
async def api_chat_settings(chat_id: int, user: PanelUser = Depends(auth.require_user)):
    if not await _known_chat(chat_id):
        raise HTTPException(400, "Бот не знает такого чата")

    values = await db.get_chat_setting_values(chat_id, list(chat_settings.SETTINGS))
    have = await permissions.bot_level(user)

    groups = []
    for group in chat_settings.GROUPS:
        fields = []
        for setting in chat_settings.SETTINGS:
            if setting.group != group:
                continue
            need = await permissions.required_level(setting.command_key)
            fields.append({
                "key": setting.key,
                "title": setting.title,
                "kind": setting.kind,
                "value": values.get(setting.key),
                "default": setting.default,
                "minimum": setting.minimum,
                "maximum": setting.maximum,
                "choices": [{"value": v, "label": l} for v, l in setting.choices],
                "hint": setting.hint,
                "required_level": need,
                "level_name": permissions.level_name(need),
                # Поле, до которого человек не дотягивает, ПОКАЗЫВАЕМ неактивным,
                # а не прячем: спрятанное читается как «такой настройки нет», и
                # человек идёт спрашивать, почему сайт беднее чата.
                "can_edit": have >= need,
                "global": setting.is_global,
            })
        if fields:
            groups.append({"group": group, "settings": fields})
    return {"groups": groups}


class ChatSettingBody(BaseModel):
    chat_id: int
    key: str
    value: Optional[str] = None


@router.post("/api/chat-settings")
async def api_set_chat_setting(
    body: ChatSettingBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    setting = chat_settings.BY_KEY.get(body.key)
    if setting is None:
        raise HTTPException(400, "Такой настройки нет")
    if not await _known_chat(body.chat_id):
        raise HTTPException(400, "Бот не знает такого чата")

    await permissions.ensure(user, setting.command_key)

    try:
        value = chat_settings.validate(setting, body.value)
    except ValueError as err:
        raise HTTPException(400, str(err)) from None

    await db.set_chat_setting_value(body.chat_id, setting, value)
    await db.add_log(
        "chat_setting_set",
        chat_id=body.chat_id,
        actor_id=user.tg_user_id,
        details=f"{setting.key}={value}",
    )
    return {"ok": True, "value": value}
```

- [ ] **Step 4: Подключить роутер**

В `webpanel/app.py` найти строку, где создаётся `app = FastAPI(...)`, и сразу после блока с middleware добавить:

```python
# Настройки чатов живут отдельным модулем: app.py и без них 4000+ строк.
from .chat_settings_api import router as chat_settings_router  # noqa: E402
app.include_router(chat_settings_router)
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_panel_chat_settings.py -q`
Expected: PASS

- [ ] **Step 6: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add webpanel/chat_settings_api.py webpanel/app.py tests/test_panel_chat_settings.py
git commit -m "$(cat <<'EOF'
API настроек чата: один эндпоинт на все 23 настройки

Требуемый уровень зависит от настройки, а не от маршрута, поэтому
зависимостью FastAPI это не проверить — она про ключ в теле запроса ничего
не знает. Проверка идёт внутри обработчика.

Поля, до которых уровень не дотягивает, отдаём с can_edit=false, а не
прячем: спрятанное поле читается как «такой настройки нет», и человек идёт
спрашивать, почему сайт беднее чата.

Отдельным модулем, а не дописыванием в app.py: тот уже 4377 строк.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Вкладка «Настройки чата» в панели

**Files:**
- Modify: `webpanel/static/index.html` (кнопка меню + пустая секция)
- Modify: `webpanel/static/app.js` (загрузчик и отрисовка)
- Test: `tests/test_panel_chat_settings.py` (дописать проверку разметки)

**Interfaces:**
- Consumes: `GET /api/chat-settings`, `POST /api/chat-settings` из Task 5
- Produces: ничего для других задач

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_panel_chat_settings.py`:

```python
# --- разметка ---------------------------------------------------------------

def test_вкладка_есть_в_меню_и_в_разметке():
    """Кнопка без секции (и наоборот) даёт мёртвый пункт меню: нажимается и
    ничего не открывает. Проверяем обе половины сразу."""
    import pathlib
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'data-view="chatsettings"' in html
    assert 'id="view-chatsettings"' in html
    js = (static / "app.js").read_text(encoding="utf-8")
    assert 'view === "chatsettings"' in js, "вкладку забыли подключить к навигации"
    assert "loadChatSettings" in js
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_panel_chat_settings.py::test_вкладка_есть_в_меню_и_в_разметке -q`
Expected: FAIL, `assert 'data-view="chatsettings"' in html`

- [ ] **Step 3: Добавить кнопку и секцию в `index.html`**

В `webpanel/static/index.html` после строки с `data-view="cmdtree"` добавить:

```html
    <button class="nav-btn" data-view="chatsettings"><svg class="ic"><use href="#ic-sliders"/></svg>Настройки чата</button>
```

Рядом с остальными секциями (после `<section class="view hidden" id="view-cmdtree">…</section>`) добавить:

```html
    <section class="view hidden" id="view-chatsettings">
      <div class="card">
        <label>Чат
          <select id="chatsettings-chat"></select>
        </label>
      </div>
      <div id="chatsettings-out"></div>
    </section>
```

- [ ] **Step 4: Добавить загрузчик в `app.js`**

В `webpanel/static/app.js` в обработчике навигации (там, где `if (view === "cmdtree")`) добавить строку:

```javascript
    if (view === "chatsettings") loadChatSettings();
```

В конец файла добавить:

```javascript
// ===== Настройки чата ======================================================
// Форма собирается из ответа API: панель не знает ни про банк, ни про рынок.
// Появилась настройка в chat_settings.py — появилась и здесь, править нечего.

async function loadChatSettings() {
  const select = $("#chatsettings-chat");
  if (!select.options.length) {
    const { chats } = await api("/api/chats");
    select.innerHTML = chats
      .map((c) => `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`)
      .join("");
    select.addEventListener("change", renderChatSettings);
  }
  await renderChatSettings();
}

async function renderChatSettings() {
  const chatId = $("#chatsettings-chat").value;
  const out = $("#chatsettings-out");
  if (!chatId) { out.innerHTML = ""; return; }
  out.innerHTML = skeleton(3);
  try {
    const { groups } = await api(`/api/chat-settings?chat_id=${chatId}`);
    out.innerHTML = groups.map(chatSettingsGroup).join("");
    $$("#chatsettings-out [data-setting]").forEach((el) =>
      el.addEventListener("change", () => saveChatSetting(el)));
  } catch (e) {
    out.innerHTML = `<div class="card error">${escapeHtml(e.message)}</div>`;
  }
}

function chatSettingsGroup(group) {
  const rows = group.settings.map(chatSettingField).join("");
  return `<section class="card"><h2>${escapeHtml(group.group)}</h2>${rows}</section>`;
}

function chatSettingField(s) {
  const off = s.can_edit ? "" : " disabled";
  let input;
  if (s.kind === "bool") {
    const checked = s.value ? " checked" : "";
    input = `<input type="checkbox" data-setting="${s.key}"${checked}${off}>`;
  } else if (s.kind === "choice") {
    const options = s.choices
      .map((c) => `<option value="${escapeHtml(c.value)}"${c.value === s.value ? " selected" : ""}>${escapeHtml(c.label)}</option>`)
      .join("");
    input = `<select data-setting="${s.key}"${off}>${options}</select>`;
  } else {
    input = `<input type="number" step="any" data-setting="${s.key}" value="${s.value}"${off}
      min="${s.minimum}" max="${s.maximum}">`;
  }
  const notes = [];
  if (s.hint) notes.push(escapeHtml(s.hint));
  if (s.global) notes.push("Действует во ВСЕХ чатах.");
  if (!s.can_edit) notes.push(`Нужен уровень «${escapeHtml(s.level_name)}».`);
  const note = notes.length ? `<div class="muted">${notes.join(" ")}</div>` : "";
  return `<div class="setting-row"><label>${escapeHtml(s.title)}${input}</label>${note}</div>`;
}

async function saveChatSetting(el) {
  const chatId = $("#chatsettings-chat").value;
  const value = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
  try {
    await api("/api/chat-settings", {
      method: "POST",
      body: { chat_id: Number(chatId), key: el.dataset.setting, value: String(value) },
    });
    toast("Сохранено");
  } catch (e) {
    toast(e.message, true);
    // Значение не доехало — перерисовываем, чтобы в поле не осталось то,
    // чего в базе нет: иначе человек уверен, что настроил, а бот работает
    // по-старому.
    await renderChatSettings();
  }
}
```

- [ ] **Step 5: Сверить имена помощников**

Проверить, что `skeleton`, `toast`, `escapeHtml`, `$`, `$$`, `api` существуют в `app.js` именно с такими именами:

Run: `grep -nE "function (skeleton|toast|escapeHtml)|const \\\$\\\$? =|function api" webpanel/static/app.js`
Expected: все шесть находятся. Если `toast` называется иначе — использовать существующее имя, а не заводить новое.

- [ ] **Step 6: Запустить тесты**

Run: `.venv/bin/python -m pytest tests/test_panel_chat_settings.py -q`
Expected: PASS

- [ ] **Step 7: Проверить, что панель поднимается**

Run: `.venv/bin/python -c "import webpanel.app; print('панель импортируется')"`
Expected: `панель импортируется`

- [ ] **Step 8: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 9: Коммит**

```bash
git add webpanel/static/index.html webpanel/static/app.js tests/test_panel_chat_settings.py
git commit -m "$(cat <<'EOF'
Вкладка «Настройки чата»: форма собирается из ответа API

Панель не знает ни про банк, ни про рынок: она рисует то, что пришло.
Появилась настройка в chat_settings.py — появилась и на сайте, править
интерфейс не нужно.

Неудачное сохранение перерисовывает форму: иначе в поле остаётся значение,
которого в базе нет, и человек уверен, что настроил, а бот работает
по-старому.

Тест проверяет кнопку меню, секцию и подключение к навигации разом: кнопка
без секции даёт мёртвый пункт, который нажимается и ничего не открывает.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Справка и архив

**Files:**
- Modify: `help_texts.py` (раздел «Настройка»)
- Modify: `docs/superpowers/specs/2026-07-28-chat-settings-panel-design.md` (пометка о выполнении)

**Interfaces:**
- Consumes: всё предыдущее
- Produces: ничего

- [ ] **Step 1: Найти раздел справки про настройку**

Run: `grep -n '"setup"\|"Настройка"' help_texts.py | head`
Expected: находится подраздел с админскими настройками

- [ ] **Step 2: Дописать в него абзац**

Добавить в текст найденного подраздела (перед закрывающей скобкой `),`):

```python
                        "\n\n🌐 <b>То же самое на сайте:</b> раздел «Настройки чата» "
                        "в веб-панели. Там собраны настройки банка, рынка, биржи, "
                        "брака, фермы, боссов, нормы и дуэлей — те же значения и те "
                        "же границы, что и у команд здесь. Права те же: что нельзя "
                        "в чате, того нельзя и на сайте."
```

- [ ] **Step 3: Прогнать тесты справки**

Run: `.venv/bin/python -m pytest tests/test_help_texts_accuracy.py tests/test_help_length.py -q`
Expected: PASS. Если раздел перерос 4096 символов — разделить его надвое, как уже сделано с `pets_own`/`pets_more`.

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Пересобрать архив**

```bash
rm -f arc.zip && zip -q -r arc.zip . \
  -x '.git/*' '.venv/*' 'venv/*' '*/__pycache__/*' '__pycache__/*' '*.pyc' \
     '.pytest_cache/*' '*/.pytest_cache/*' \
     'images/*' 'rp_media/*' 'webpanel/static/rp_media/*' 'demo_out/*' \
     '*.jpg' '*.jpeg' 'arc.zip' \
  && unzip -t arc.zip >/dev/null && ls -lh arc.zip
```

Expected: около 3,4 МБ, ~222 файла

- [ ] **Step 6: Коммит**

```bash
git add help_texts.py docs/ arc.zip
git commit -m "$(cat <<'EOF'
Справка: про настройки чата на сайте

Раздел «Настройка» рассказывал только про команды. Человек, у которого есть
панель, не догадается, что то же самое есть на сайте, — а именно ради этого
всё и делалось.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Что НЕ входит в этот план

Перечислено, чтобы не выяснилось на середине, что «забыли»:

- **Списочные настройки** (магазин чата, ЧС банка, каталог питомцев, заявки рынка) — подпроект П2.
- **Разовые действия** («чат сюда», сбросы, выдачи, `clearUsers`) — П3.
- **Мелочи** (хранилище, модерация закладок/кланов/кружков, темы, правила) — П4.
- **Перевод существующих 123 маршрутов панели** на новую проверку прав — сломало бы доступ действующим пользователям без предупреждения.
- **Переписывание обработчиков бота** на реестр — вместо этого сторожевой тест из Task 2.
- **Початовые уровни админов** — в боте их нет, добавление `chat_id` в таблицу `admins` крупнее всего этого плана.

## Порядок и зависимости

```
Task 1 (реестр) ──> Task 2 (сторож)
      │
      ├──> Task 3 (хранение) ──┐
      │                        ├──> Task 5 (API) ──> Task 6 (интерфейс) ──> Task 7 (справка)
      └──> Task 4 (права) ─────┘
```

Task 2 и Task 3 можно делать параллельно после Task 1. Task 4 ни от чего, кроме Task 1, не зависит и может идти первым, если так удобнее.
