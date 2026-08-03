"""Сколько строк каждого чата лежит в каждой таблице.

Запускать НА СЕРВЕРЕ, где доступна база:

    .venv/bin/python -m tools.chat_report

Зачем. Перед тем как убирать колонку chat_id, надо знать, чьи данные вообще
есть: убрать её — значит слить чаты в один, и если в таблице лежат строки
двух людей из разных чатов, они станут одной строкой.

Список таблиц берётся ИЗ СХЕМЫ, а не из перечисления руками: перечисление
устареет на первой же миграции, и отчёт молча пропустит таблицу — то есть
соврёт, что чужих данных там нет.
"""

from __future__ import annotations

import asyncio
import sys

import db


def запрос_таблиц() -> str:
    return (
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND column_name = 'chat_id' "
        "ORDER BY table_name"
    )


def запрос_для(таблица: str) -> str:
    return f"SELECT chat_id, COUNT(*) AS n FROM {таблица} GROUP BY chat_id"


def отчёт(строки: dict[str, dict[int, int]], свои: list[int]) -> str:
    """Таблица «таблица × чат × строк». Свои чаты помечены, чужие тоже —
    глазами по числам чат не опознать."""
    чаты = sorted({ч for c in строки.values() for ч in c})
    ширина = max([len(т) for т in строки] + [16])
    шапка = "таблица".ljust(ширина) + "".join(f"{ч:>17}" for ч in чаты)
    метки = " " * ширина + "".join(
        f"{('свой' if ч in свои else 'чужой'):>17}" for ч in чаты)
    тело = [
        т.ljust(ширина) + "".join(f"{строки[т].get(ч, 0):>17}" for ч in чаты)
        for т in sorted(строки)
    ]
    if not чаты:
        return "\n".join([шапка, "-" * ширина, *[т for т in sorted(строки)],
                          "", "Строк с chat_id в базе нет вовсе."])
    return "\n".join([шапка, метки, "-" * len(шапка), *тело])


async def main() -> None:
    await db.init_pool()
    таблицы = [r["table_name"] for r in await db._fetchall(запрос_таблиц())]
    строки: dict[str, dict[int, int]] = {}
    for таблица in таблицы:
        try:
            строки[таблица] = {
                int(r["chat_id"]): int(r["n"])
                for r in await db._fetchall(запрос_для(таблица))
                if r["chat_id"] is not None
            }
        except Exception as exc:
            # Таблица могла исчезнуть между выборкой имён и запросом — это не
            # повод обрывать весь отчёт.
            print(f"пропущена {таблица}: {exc}", file=sys.stderr)
    настройки = await db.fetch_settings() or {}
    свои = [int(настройки[k]) for k in ("complaint_chat_id", "notify_chat_id")
            if настройки.get(k)]
    print(отчёт(строки, свои))
    print(f"\nСвои чаты: {свои or 'не привязаны'}")


if __name__ == "__main__":
    asyncio.run(main())
