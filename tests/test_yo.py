"""«е» и «ё» в командах не различаются.

casefold() приводит регистр, но не ё↔е, поэтому набор триггеров с «чёрное» не
узнавал «черное», а «пет кормить всё» не совпадало с «все». Часть мест была
залатана вручную («нал[её]т», «орёл|орел», синонимы питомцев) — это и есть
признак того, что чинили симптомы, а не причину.
"""

from __future__ import annotations

import os
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import ru_text  # noqa: E402


def test_нормализация_убирает_ё():
    assert ru_text.yo("чёрное") == "черное"
    assert ru_text.yo("Ёлка") == "Елка"
    assert ru_text.yo("") == ""
    assert ru_text.yo(None) == ""


@pytest.mark.parametrize("text", ["налет", "налёт", "НАЛЁТ", " Налет "])
def test_команда_узнаётся_в_любом_написании(text):
    """Берём настоящую команду с «ё» («налёт»), а не слово из описания:
    аргументы вроде цвета рулетки «чёрное» командой не являются и узнаваться
    не обязаны — раньше они попадали в триггеры по ошибке разбора."""
    assert bot_module.is_command_like(text + " @кто-то")
    assert bot_module.resolve_command_key(text) == "business_raid"


def test_наборы_триггеров_не_держат_недостижимых_записей():
    """Вход приводится к «е», поэтому запись через «ё» без е-двойника
    недостижима НИ В ОДНОМ написании — то есть хуже, чем до нормализации.
    Ловим это на всех наборах сразу, а не на тех, о которых вспомнили."""
    import relationships_v2 as rel2
    плохие = []
    for module in (bot_module, rel2):
        for name, value in vars(module).items():
            if not isinstance(value, (set, frozenset)) or not value:
                continue
            if not all(isinstance(x, str) for x in value):
                continue
            for entry in value:
                if "ё" in entry and entry.replace("ё", "е") not in value:
                    плохие.append(f"{module.__name__}.{name}: {entry!r}")
    assert not плохие, "недостижимые триггеры:\n" + "\n".join(плохие)


def test_индексы_форм_команд_нормализованы():
    """Тест выше умеет заглядывать только в множества строк, а формы команд
    лежат в словаре списков кортежей — мимо него. Вход в resolve_command_key и
    is_command_like нормализован, поэтому «ё» в самом индексе делает форму
    недостижимой в обоих написаниях сразу."""
    плохие = []
    for имя, индекс in (
        ("_COMMAND_PREFIX_INDEX", bot_module._COMMAND_PREFIX_INDEX),
        ("_CLEANUP_PREFIX_INDEX", bot_module._CLEANUP_PREFIX_INDEX),
    ):
        for ключ, записи in индекс.items():
            формы = [з[2] for з in записи] if имя == "_COMMAND_PREFIX_INDEX" else [з[0] for з in записи]
            for слово in (ключ, *(w for форма in формы for w in форма)):
                if "ё" in слово:
                    плохие.append(f"{имя}: {слово!r}")
    assert not плохие, "формы команд не в е-написании:\n" + "\n".join(sorted(set(плохие)))


@pytest.mark.parametrize("text", [
    "пет кормить все", "пет кормить всё", "пет покормить всё",
])
def test_массовое_кормление_понимает_оба_написания(text):
    assert bot_module.PET_FEED_ALL_RE.match(text), text


@pytest.mark.parametrize("text", ["пет обнять все", "пет обнять всё"])
def test_массовая_ласка_понимает_оба_написания(text):
    assert bot_module.PET_CARE_ALL_RE.match(text), text


@pytest.mark.parametrize("text", ["!орел", "!орёл"])
def test_казино_понимает_оба_написания(text):
    assert bot_module.CASINO_COIN_RE.match(f"{text} 100"), text


@pytest.mark.parametrize("text", ["налет", "налёт", "бизнес налет"])
def test_налёт_понимает_оба_написания(text):
    assert bot_module.RAID_RE.match(text), text


def test_все_команды_собраны_через_rx():
    """Регулярка, скомпилированная напрямую через re.compile, снова начнёт
    различать ё — и заметят это не сразу. Проверяем инвариант: голых «е»/«ё»
    вне символьных классов в шаблонах не осталось.

    Прошлая версия этого теста разбирала pattern.pattern на слова и после
    преобразования не находила там ни одного — то есть не проверяла ничего.
    """
    import relationships_v2 as rel2
    плохие = []
    for module in (bot_module, rel2):
        for name, pattern in vars(module).items():
            if not isinstance(pattern, re.Pattern):
                continue
            if _bare_yo(pattern.pattern):
                плохие.append(f"{module.__name__}.{name}")
    assert not плохие, ("эти шаблоны различают ё — соберите их через "
                        "ru_text.rx:\n" + "\n".join(плохие))


def _bare_yo(pattern: str) -> bool:
    """Есть ли в шаблоне «е»/«ё» ВНЕ символьного класса. Разбор тот же, что
    в ru_text.yo_pattern, — иначе тест проверял бы не то, что делает код."""
    in_class = escaped = False
    for char in pattern:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif not in_class and char in "еЕёЁ":
            return True
    return False
