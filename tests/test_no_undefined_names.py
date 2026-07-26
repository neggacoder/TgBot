"""В коде не должно быть обращений к несуществующим именам.

Этот тест появился после того, как разом нашлись четыре таких места, и каждое
молча ломало живую функцию:

  * bot.py — регулярка `!биржа цена` объявилась ВНУТРИ тела предыдущей
    функции, а фильтр обработчика ссылался на неё как на глобальную. Проверка
    фильтра падала NameError на каждом сообщении, и все команды ниже по файлу
    переставали работать;
  * db.list_active_chat_ids звала несуществующую get_pool() — из-за чего
    ежедневная награда за топ активности не начислялась НИ РАЗУ: цикл ловил
    исключение и просто писал в лог;
  * relationships_v2 звал grant_achievement/user1_id/user2_id, которых в
    модуле нет, — ачивка «Многодетный» не выдавалась, а кнопка «👶 Принять»
    у пары с пятью детьми падала;
  * webpanel/app.py использовал `date` без импорта.

Обычными тестами такое почти не ловится: код внутри `except Exception` или в
редкой ветке выполняется не в каждом прогоне, а импорт модуля проходит
успешно — Python проверяет имена только в момент выполнения строки.
"""

from __future__ import annotations

import io
import os

import pytest

pyflakes_api = pytest.importorskip(
    "pyflakes.api", reason="нужен pyflakes (см. requirements.txt)"
)
from pyflakes import reporter as pyflakes_reporter  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Каталоги, которые проверять незачем: окружение, кэши, сама папка тестов
# (в тестах namespace специально шаманят с monkeypatch).
_SKIP_DIRS = {"tests", "venv", ".venv", "__pycache__", "deploy", "backups", "node_modules"}

# Сообщения pyflakes, означающие именно «имени не существует».
_FATAL_MARKERS = ("undefined name", "local variable defined in enclosing scope")


def _project_files() -> list[str]:
    found = []
    for base, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        found += [os.path.join(base, f) for f in sorted(files) if f.endswith(".py")]
    return sorted(found)


def _pyflakes_report(paths: list[str]) -> list[str]:
    out, err = io.StringIO(), io.StringIO()
    reporter = pyflakes_reporter.Reporter(out, err)
    for path in paths:
        pyflakes_api.checkPath(path, reporter)
    return (out.getvalue() + err.getvalue()).splitlines()


def test_нет_обращений_к_несуществующим_именам():
    paths = _project_files()
    assert paths, "не нашлось ни одного .py — сломался обход каталогов"

    problems = [
        line for line in _pyflakes_report(paths)
        if any(marker in line for marker in _FATAL_MARKERS)
    ]
    assert not problems, (
        "обращение к несуществующему имени — это NameError в рантайме, "
        "и падает оно только когда до строки дойдёт выполнение:\n"
        + "\n".join(problems)
    )


def test_нет_функций_и_ключей_объявленных_дважды():
    """Второе объявление молча затирает первое.

    Так в db.py жили две копии set_birthday/get_birthday, а в bot.py — две
    roulette_number_color и задвоенные ключи РП-фраз: правка «верхней» копии
    не давала никакого эффекта, а часть фраз не попадала в чат никогда.
    """
    problems = [
        line for line in _pyflakes_report(_project_files())
        if "redefinition of unused" in line or "repeated with different values" in line
    ]
    assert not problems, (
        "объявлено дважды — работает только последнее объявление:\n"
        + "\n".join(problems)
    )
