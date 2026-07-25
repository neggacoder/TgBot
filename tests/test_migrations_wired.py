"""Все миграции схемы должны кем-то вызываться при старте.

Миграции в этом проекте — обычные функции ensure_*() в db.py, которые бот
вызывает на старте (см. хвост bot.py). Забыть добавить вызов легко, а
последствие неприятное и молчаливое: функция есть, выглядит рабочей, но колонки
в базе нет — и первая же попытка сохранить настройку падает уже в проде.
Тестами с замоканной базой такое не ловится, поэтому проверяем статически.

Именно так и случилось с ensure_rest_settings_columns: написана, но не вызвана.
"""

from __future__ import annotations

import ast
import io
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name: str) -> str:
    return io.open(os.path.join(_ROOT, name), encoding="utf-8").read()


def _project_sources() -> list[str]:
    """Все модули проекта, включая пакеты вроде webpanel/: панель поднимается
    отдельным процессом и часть миграций запускает сама (ensure_panel_tables).
    Тесты и служебные каталоги пропускаем."""
    skipped = {"tests", "venv", ".venv", "__pycache__", "quote_render", "deploy"}
    found = []
    for base, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs if d not in skipped and not d.startswith(".")]
        found += [os.path.join(base, f) for f in files if f.endswith(".py")]
    return found


def _defined_migrations() -> set[str]:
    tree = ast.parse(_source("db.py"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name.startswith("ensure_")
    }


def _called_migrations() -> set[str]:
    """Вызовы ensure_* во всех модулях проекта: миграции запускает не только
    bot.py — свои есть у relationships_v2 и admin_holds.

    Ищем именно вызовы через AST, а не текстом: строка «async def ensure_x()»
    для регулярного выражения выглядит точно так же, как вызов, и тест
    начинает считать любую определённую миграцию вызванной — то есть молча
    перестаёт проверять хоть что-нибудь.
    """
    called: set[str] = set()
    for path in _project_sources():
        for node in ast.walk(ast.parse(io.open(path, encoding="utf-8").read())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # db.ensure_x() или просто ensure_x()
            target = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if target.startswith("ensure_"):
                called.add(target)
    return called


def test_каждая_миграция_вызывается():
    defined = _defined_migrations()
    assert defined, "в db.py не нашлось ни одной ensure_*-функции — сломался разбор"

    called = _called_migrations()
    forgotten = sorted(defined - called)
    assert not forgotten, (
        "эти миграции определены в db.py, но нигде не вызываются — "
        f"колонок/таблиц в базе не появится: {forgotten}"
    )
