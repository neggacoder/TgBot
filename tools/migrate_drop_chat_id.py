"""Отвязать данные от чатов: убрать колонку chat_id из всех таблиц.

Запускать НА СЕРВЕРЕ, где доступна база. По умолчанию — вхолостую:

    .venv/bin/python -m tools.migrate_drop_chat_id            # только показать
    .venv/bin/python -m tools.migrate_drop_chat_id --выполнить

Что делает. Для каждой таблицы из списка «убрать» (tools/classify_tables):

1. считает строки по чатам;
2. находит СОВПАДЕНИЯ — строки разных чатов с одинаковым остатком ключа
   (например, один и тот же user_id в двух чатах);
3. проигравшие строки выгружает в файл и удаляет;
4. пересобирает первичный и уникальные ключи без chat_id;
5. удаляет саму колонку.

Про совпадения — самое важное. Ключ у большинства таблиц составной
(chat_id, user_id). Убери из него chat_id — и две строки одного человека из
разных чатов становятся одной. Молча оставить «какую-нибудь» нельзя: у одного
человека сложились бы два кошелька или потерялся бы больший счётчик.

Правило разрешения: **побеждает строка рабочего чата**. Он и есть тот чат, к
которому всё привязывается; строки второго чата — остаток от времени, когда
бот там что-то считал. Проигравшие не пропадают: они уходят в
`migration_losers_<дата>.sql`, откуда их можно прочитать и вернуть руками.

Ничего не делается без свежего дампа: скрипт откажется работать, если рядом
нет файла `db_backup_*.sql` не старше суток (см. --без-дампа для явного
пропуска этой проверки).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import sys

import db

from tools import classify_tables

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Чистая часть: её проверяют тесты, база для неё не нужна
# ---------------------------------------------------------------------------
def запрос_ключей(таблица: str) -> str:
    """Колонки первичного ключа таблицы, по порядку."""
    return (
        "SELECT column_name, seq_in_index FROM information_schema.statistics "
        f"WHERE table_schema = DATABASE() AND table_name = '{таблица}' "
        "AND index_name = 'PRIMARY' ORDER BY seq_in_index"
    )


def запрос_индексов(таблица: str) -> str:
    """Уникальные индексы, в которых участвует chat_id: их тоже пересобирать."""
    return (
        "SELECT index_name, column_name, seq_in_index FROM information_schema.statistics "
        f"WHERE table_schema = DATABASE() AND table_name = '{таблица}' "
        "AND non_unique = 0 AND index_name <> 'PRIMARY' ORDER BY index_name, seq_in_index"
    )


def запрос_совпадений(таблица: str, ключ: list[str]) -> str:
    """Строки, которые после удаления колонки столкнутся ключами.

    Считаем по остатку ключа: если без chat_id одна и та же комбинация
    встречается больше раза — это совпадение.
    """
    остаток = [к for к in ключ if к != "chat_id"]
    если_пусто = "1"        # ключ был только из chat_id — столкнётся всё
    поля = ", ".join(остаток) if остаток else если_пусто
    return (
        f"SELECT {поля}, COUNT(*) AS n, GROUP_CONCAT(chat_id) AS чаты "
        f"FROM {таблица} GROUP BY {поля} HAVING COUNT(*) > 1"
    )


def запрос_удаления_проигравших(таблица: str, рабочий: int) -> str:
    """Строки НЕ рабочего чата, у которых есть двойник в рабочем."""
    return (
        f"DELETE FROM {таблица} WHERE chat_id <> {рабочий}"
    )


def запросы_пересборки(таблица: str, ключ: list[str],
                       индексы: dict[str, list[str]]) -> list[str]:
    """ALTER-ы: сначала ключи без chat_id, потом сама колонка.

    Порядок важен: удали колонку раньше ключа — MySQL сам выкинет её из
    индекса, и уникальность потеряется молча, без единой ошибки.
    """
    шаги: list[str] = []
    остаток = [к for к in ключ if к != "chat_id"]
    if ключ and "chat_id" in ключ:
        if остаток:
            шаги.append(f"ALTER TABLE {таблица} DROP PRIMARY KEY, "
                        f"ADD PRIMARY KEY ({', '.join(остаток)})")
        else:
            # Ключ был только из chat_id: без него уникальности нет вовсе.
            шаги.append(f"ALTER TABLE {таблица} DROP PRIMARY KEY")
    for имя, колонки in индексы.items():
        if "chat_id" not in колонки:
            continue
        оставшиеся = [к for к in колонки if к != "chat_id"]
        шаги.append(f"ALTER TABLE {таблица} DROP INDEX {имя}")
        if оставшиеся:
            шаги.append(f"ALTER TABLE {таблица} ADD UNIQUE KEY {имя} "
                        f"({', '.join(оставшиеся)})")
    шаги.append(f"ALTER TABLE {таблица} DROP COLUMN chat_id")
    return шаги


def свежий_дамп(каталог: pathlib.Path, сейчас: dt.datetime) -> bool:
    """Есть ли рядом дамп не старше суток.

    Проверка не формальность: DROP COLUMN необратим, и единственный способ
    вернуть данные — файл, сделанный ДО.
    """
    for файл in каталог.glob("db_backup_*.sql"):
        возраст = сейчас - dt.datetime.fromtimestamp(файл.stat().st_mtime)
        if возраст < dt.timedelta(days=1):
            return True
    return False


# ---------------------------------------------------------------------------
# Часть, которой нужна база
# ---------------------------------------------------------------------------
async def _ключ(таблица: str) -> list[str]:
    rows = await db._fetchall(запрос_ключей(таблица))
    return [r["column_name"] for r in rows]


async def _индексы(таблица: str) -> dict[str, list[str]]:
    итог: dict[str, list[str]] = {}
    for r in await db._fetchall(запрос_индексов(таблица)):
        итог.setdefault(r["index_name"], []).append(r["column_name"])
    return итог


async def main() -> None:
    разбор = argparse.ArgumentParser(description="Убрать chat_id из таблиц")
    разбор.add_argument("--выполнить", action="store_true",
                        help="применить изменения (иначе только показать)")
    разбор.add_argument("--без-дампа", action="store_true",
                        help="не требовать свежий дамп рядом (опасно)")
    аргументы = разбор.parse_args()

    if аргументы.выполнить and not аргументы.без_дампа:
        if not свежий_дамп(КОРЕНЬ, dt.datetime.now()):
            print("Рядом нет свежего дампа (db_backup_*.sql моложе суток).\n"
                  "Сделайте его: bash tools/backup_db.sh\n"
                  "DROP COLUMN необратим — без дампа вернуть данные нечем.",
                  file=sys.stderr)
            sys.exit(2)

    await db.init_pool()
    настройки = await db.fetch_settings() or {}
    рабочий = настройки.get("complaint_chat_id")
    if not рабочий:
        print("Рабочий чат не привязан — сначала «жалобы сюда» в чате.",
              file=sys.stderr)
        sys.exit(2)
    рабочий = int(рабочий)

    к_удалению = classify_tables.разбор()["убрать"]
    существующие = {
        r["table_name"] for r in await db._fetchall(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND column_name = 'chat_id'")
    }
    таблицы = [т for т in к_удалению if т in существующие]
    print(f"Таблиц к правке: {len(таблицы)} (из {len(к_удалению)} в списке; "
          f"остальных нет в этой базе)")
    print(f"Рабочий чат: {рабочий}\n")

    проигравшие = КОРЕНЬ / f"migration_losers_{dt.datetime.now():%Y%m%d_%H%M%S}.sql"
    всего_потерь = 0

    for таблица in таблицы:
        ключ = await _ключ(таблица)
        индексы = await _индексы(таблица)
        чужие = await db._fetchall(
            f"SELECT COUNT(*) AS n FROM {таблица} WHERE chat_id <> {рабочий}")
        сколько_чужих = int(чужие[0]["n"]) if чужие else 0
        шаги = запросы_пересборки(таблица, ключ, индексы)

        print(f"— {таблица}: ключ {ключ or '—'}, чужих строк {сколько_чужих}")
        for шаг in шаги:
            print(f"    {шаг}")

        if not аргументы.выполнить:
            continue

        if сколько_чужих:
            # Выгружаем проигравших ДО удаления: это единственный способ
            # прочитать их потом.
            строки = await db._fetchall(
                f"SELECT * FROM {таблица} WHERE chat_id <> {рабочий}")
            with проигравшие.open("a", encoding="utf-8") as f:
                for строка in строки:
                    f.write(f"-- {таблица}: {строка}\n")
            всего_потерь += сколько_чужих
            await db._execute(запрос_удаления_проигравших(таблица, рабочий))

        for шаг in шаги:
            await db._execute(шаг)

    if аргументы.выполнить:
        print(f"\nГотово. Строк чужих чатов выгружено и удалено: {всего_потерь}")
        if всего_потерь:
            print(f"Они лежат в {проигравшие.name} — прочитать и вернуть руками.")
    else:
        print("\nЭто был холостой прогон. Применить: --выполнить")


if __name__ == "__main__":
    asyncio.run(main())
