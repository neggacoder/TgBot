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


@pytest.mark.parametrize("text", ["черное", "чёрное", "ЧЁРНОЕ", " Черное "])
def test_слово_команды_узнаётся_в_любом_написании(text):
    """is_command_like смотрит по первому слову — на нём и проверяем."""
    assert bot_module.is_command_like(text + " что-то")


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
