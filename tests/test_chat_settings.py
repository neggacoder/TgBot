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
    """25 — не магия: столько перечислено в спеке. Тест ловит потерянную
    строку при правках, а не проверяет арифметику."""
    assert len(chat_settings.SETTINGS) == 25


@pytest.mark.parametrize(
    "setting",
    [s for s in chat_settings.SETTINGS if s.kind == chat_settings.KIND_NUMBER],
    ids=lambda s: s.key
)
def test_границы_осмысленны(setting):
    assert setting.minimum is not None and setting.maximum is not None
    assert setting.minimum <= setting.maximum
    assert setting.minimum <= setting.default <= setting.maximum


@pytest.mark.parametrize(
    "setting",
    [s for s in chat_settings.SETTINGS if s.kind == chat_settings.KIND_CHOICE],
    ids=lambda s: s.key
)
def test_у_выбора_умолчание_из_списка(setting):
    assert setting.choices
    assert setting.default in [value for value, _label in setting.choices]


@pytest.mark.parametrize(
    "setting",
    [s for s in chat_settings.SETTINGS if s.storage == chat_settings.STORAGE_COLUMN],
    ids=lambda s: s.key
)
def test_колоночная_настройка_знает_таблицу_и_колонку(setting):
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
    # Границы берём из самой настройки, а не буквами: иначе тест придётся
    # править каждый раз, когда рамки сузятся вслед за ботом.
    assert chat_settings._num(s.minimum) in str(err.value)
    assert chat_settings._num(s.maximum) in str(err.value)


def test_валидация_отвергает_nan_дробное():
    """NaN не парсируется как ошибка float(), пропускает проверки границ,
    но попадает в базу некорректно. Отвергаем явно с русским текстом."""
    s = chat_settings.BY_KEY["bank.rate_1d"]  # дробное число
    with pytest.raises(ValueError) as err:
        chat_settings.validate(s, "nan")
    assert "конечное" in str(err.value).lower()


def test_валидация_отвергает_nan_целое():
    """Для целых чисел NaN вызывает необработанное английское исключение
    при int(float("nan")). Должно быть отвергнуто ДО этого с русским текстом."""
    s = chat_settings.BY_KEY["market.max_goods"]  # целое число
    with pytest.raises(ValueError) as err:
        chat_settings.validate(s, "nan")
    # Проверяем, что исключение наше русское, не английское int()
    assert "конечное" in str(err.value).lower()
    assert "cannot convert" not in str(err.value)


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

    Срезаем ровно до конца определения таблицы (до ") ENGINE="), чтобы не
    захватить колонки из соседних таблиц, которые иначе попадут в словарь
    и сторож может проверить умолчание ПО ЧУЖОЙ ТАБЛИЦЕ.
    """
    import inspect
    import re
    import db
    source = inspect.getsource(db)
    start = source.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    end = source.index(") ENGINE=", start)
    tail = source[start:end + len(") ENGINE=")]
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


def test_ddl_разбор_не_заезжает_в_соседние_таблицы():
    """_ddl_defaults ограничена концом определения таблицы (до ") ENGINE="),
    чтобы не вытащить колонки из соседних таблиц и не проверить реестр по
    чужим умолчаниям. Гарантируем: economy_settings содержит farm_yield
    (своё поле) и ТОЧНО не содержит total_catches (из fishing_stats)."""
    defaults = _ddl_defaults("economy_settings")
    assert "farm_yield" in defaults, "farm_yield должен быть в economy_settings"
    assert "total_catches" not in defaults, "total_catches из fishing_stats не должны попасть"
    assert "best_catch" not in defaults, "best_catch из fishing_stats не должны попасть"


def test_ddl_разбор_stock_не_вмешивает_соседние_таблицы():
    """stock_settings должна содержать только свои колонки, не вмешивая
    колонки из stock_price_history (source, BOOL и т.д.)."""
    defaults = _ddl_defaults("stock_settings")
    # Ожидаемые колонки stock_settings
    assert "min_change_percent" in defaults
    assert "max_change_percent" in defaults
    assert "dividend_percent" in defaults
    # Не должно быть колонок из stock_price_history
    assert "source" not in defaults, "source из stock_price_history не должны попасть"
    assert "BOOL" not in defaults, "BOOL из stock_price_history не должны попасть"


def _bot_module():
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module
    return bot_module


# Границы бота лежат не константами, а прямо в проверках его команд, — читаем
# их из исходника обработчика. Записать те же числа сюда буквами значило бы
# завести ЧЕТВЁРТОЕ место с теми же рамками, а разъехались они ровно потому,
# что мест уже было слишком много.
_BOT_BOUNDS = {
    # ключ реестра: (обработчик бота, регэксп с группами «нижняя, верхняя»)
    "market.commission_percent": (
        "cmd_market_config",
        r'not (\d+) <= value <= (\d+):\s*\n\s*await message\.reply\("Комиссия',
    ),
    "market.max_goods": (
        "cmd_market_config",
        r'not (\d+) <= value <= (\d+):\s*\n\s*await message\.reply\("Лимит товаров',
    ),
    "economy.farm_yield": (
        "cmd_farm_set_yield",
        r"max\(([\d.]+), min\(([\d.]+), percent\)\)",
    ),
    "marriage.renew_price": (
        "cmd_marriage_renew_price",
        r"price is None or price < ([\d_]+):.*?if price > ([\d_]+):",
    ),
}


@pytest.mark.parametrize("key", sorted(_BOT_BOUNDS))
def test_границы_не_шире_чем_у_бота(key):
    """Рамки экономики в командах бота старше панели и обдуманнее. Панель не
    имеет права принимать то, что бот своей же командой запрещает: колонку он
    читает как есть, поэтому комиссия 90%, невозможная в чате, с сайта
    выставилась бы и заработала.

    Не равенство, а «не шире»: у потолка цены бот проверяет только «больше
    нуля», и реестр там законно строже.
    """
    import inspect
    import re
    handler_name, pattern = _BOT_BOUNDS[key]
    source = inspect.getsource(getattr(_bot_module(), handler_name))
    # re.S — у брака нижняя и верхняя границы стоят в разных проверках, между
    # ними переводы строк. Точку как «любой символ» шаблоны не используют
    # (в них она везде экранирована), так что флаг остальным не мешает.
    m = re.search(pattern, source, re.S)
    assert m, f"в {handler_name} не нашлась проверка границ для {key} — регэксп устарел"
    низ, верх = float(m.group(1)), float(m.group(2))
    setting = chat_settings.BY_KEY[key]
    assert setting.minimum >= низ, f"{key}: панель принимает от {setting.minimum}, бот — от {низ}"
    assert setting.maximum <= верх, f"{key}: панель принимает до {setting.maximum}, бот — до {верх}"


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
