"""Миграция «отвязать данные от чатов».

Скрипт запускается на сервере, поэтому здесь проверяется его чистая часть —
та, где рождаются ALTER-ы. Ошибка в них необратима: колонку вернуть можно,
данные, которые из-за неё потерялись, — нет.
"""

from __future__ import annotations

import datetime as dt
import pathlib

from tools import migrate_drop_chat_id as м


def test_первичный_ключ_пересобирается_без_чата():
    шаги = м.запросы_пересборки("economy_wallets", ["chat_id", "user_id"], {})
    assert "DROP PRIMARY KEY, ADD PRIMARY KEY (user_id)" in шаги[0]
    assert шаги[-1] == "ALTER TABLE economy_wallets DROP COLUMN chat_id"


def test_ключ_правится_раньше_колонки():
    """Удали колонку первой — MySQL сам выкинет её из индекса, и уникальность
    потеряется молча, без единой ошибки."""
    шаги = м.запросы_пересборки("t", ["chat_id", "user_id"], {})
    ключ = next(i for i, ш in enumerate(шаги) if "PRIMARY KEY" in ш)
    колонка = next(i for i, ш in enumerate(шаги) if "DROP COLUMN" in ш)
    assert ключ < колонка


def test_уникальные_индексы_тоже_пересобираются():
    шаги = м.запросы_пересборки(
        "t", ["chat_id", "user_id"], {"uniq_slot": ["chat_id", "user_id", "slot"]})
    assert any("DROP INDEX uniq_slot" in ш for ш in шаги)
    assert any("ADD UNIQUE KEY uniq_slot (user_id, slot)" in ш for ш in шаги)


def test_индекс_без_чата_не_трогают():
    шаги = м.запросы_пересборки("t", ["chat_id", "user_id"], {"uniq_key": ["item_key"]})
    assert not any("uniq_key" in ш for ш in шаги)


def test_ключ_только_из_чата_снимается_целиком():
    """Такой ключ после удаления колонки не из чего собрать: оставить его —
    значит оставить ключ по несуществующей колонке."""
    шаги = м.запросы_пересборки("t", ["chat_id"], {})
    assert шаги[0] == "ALTER TABLE t DROP PRIMARY KEY"


def test_совпадения_ищутся_по_остатку_ключа():
    запрос = м.запрос_совпадений("economy_wallets", ["chat_id", "user_id"])
    assert "GROUP BY user_id" in запрос and "HAVING COUNT(*) > 1" in запрос
    assert "chat_id" in запрос, "нужно видеть, из каких чатов строки"


def test_побеждает_рабочий_чат():
    запрос = м.запрос_удаления_проигравших("economy_wallets", -100111)
    assert "DELETE FROM economy_wallets" in запрос
    assert "chat_id <> -100111" in запрос


def test_без_свежего_дампа_миграция_не_идёт(tmp_path):
    """DROP COLUMN необратим, и единственный способ вернуть данные — файл,
    сделанный ДО."""
    assert м.свежий_дамп(tmp_path, dt.datetime.now()) is False
    старый = tmp_path / "db_backup_20200101_000000.sql"
    старый.write_text("-- дамп", encoding="utf-8")
    import os
    прошлое = dt.datetime.now() - dt.timedelta(days=3)
    os.utime(старый, (прошлое.timestamp(), прошлое.timestamp()))
    assert м.свежий_дамп(tmp_path, dt.datetime.now()) is False
    свежий = tmp_path / "db_backup_20260802_120000.sql"
    свежий.write_text("-- дамп", encoding="utf-8")
    assert м.свежий_дамп(tmp_path, dt.datetime.now()) is True


def test_холостой_прогон_по_умолчанию():
    """Скрипт, который правит схему сразу при запуске, однажды запустят
    случайно."""
    исходник = pathlib.Path(м.__file__).read_text(encoding="utf-8")
    assert '"--выполнить"' in исходник
    assert "аргументы.выполнить" in исходник
