"""Запросы лавки: SQL собирается правильно, а завоз обходит пул стороной.

Настоящей базы в тестах нет (conftest подменяет aiomysql), поэтому
проверяем то, что и ломается на практике: какой текст запроса и какие
параметры уходят в драйвер.

Отдельная причина проверять именно текст — плейсхолдеры. Список «%s» под
IN собирается в рантайме, и собранный не тем способом запрос уезжает в
драйвер с «%%s»: ошибки при этом нет, просто ничего не находится.
"""

from __future__ import annotations

import asyncio
from datetime import date

import db as db_module


class _Spy:
    """Подменяет db._fetchall/_execute и запоминает запрос с параметрами."""

    def __init__(self, result=None):
        self.result = result if result is not None else []
        self.query = ""
        self.params = ()

    async def __call__(self, query, params=()):
        self.query = " ".join(query.split())
        self.params = params
        return self.result


def test_restock_list_excludes_given_keys(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_fetchall", spy)

    asyncio.run(db_module.list_shop_items_for_restock(-100, exclude_keys=["binokl", "bronik"]))

    assert "NOT IN (%s, %s)" in spy.query
    assert spy.params == (-100, "binokl", "bronik")


def test_restock_list_without_exclusions_keeps_old_query(monkeypatch):
    """Старые вызовы без параметра не должны получить хвост NOT IN ()."""
    spy = _Spy()
    monkeypatch.setattr(db_module, "_fetchall", spy)

    asyncio.run(db_module.list_shop_items_for_restock(-100))

    assert "NOT IN" not in spy.query
    assert spy.params == (-100,)


def test_clear_rotation_stock_zeroes_only_pool_keys(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_execute", spy)

    asyncio.run(db_module.clear_rotation_stock(-100, ["binokl", "slepok"]))

    assert "SET stock = 0" in spy.query
    assert "item_key IN (%s, %s)" in spy.query
    assert spy.params == (-100, "binokl", "slepok")


def test_clear_rotation_stock_with_no_keys_touches_nothing(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(db_module, "_execute", spy)

    asyncio.run(db_module.clear_rotation_stock(-100, []))

    assert spy.query == ""


def test_rotation_items_are_filtered_by_day(monkeypatch):
    spy = _Spy(result=[{"item_key": "binokl"}])
    monkeypatch.setattr(db_module, "_fetchall", spy)

    rows = asyncio.run(db_module.list_rotation_items(-100, ["binokl"], date(2026, 7, 28)))

    assert rows == [{"item_key": "binokl"}]
    assert "rotation_day = %s" in spy.query
    assert spy.params == (-100, date(2026, 7, 28), "binokl")


def test_rotation_items_skip_rows_disabled_by_admins(monkeypatch):
    """Выключенный админом товар не должен попадать в витрину лавки.

    _shop_buy отказывает по is_active, а ротация про него не знает: покажи
    лавка такую позицию с ценой и остатком — и каждая покупка отвечала бы
    «товар не найден в магазине», хотя он прямо в списке. Товар, который
    нельзя купить, показывать нельзя.
    """
    spy = _Spy()
    monkeypatch.setattr(db_module, "_fetchall", spy)

    asyncio.run(db_module.list_rotation_items(-100, ["binokl"], date(2026, 7, 28)))

    assert "is_active" in spy.query


def test_rotation_day_is_read_across_the_whole_pool(monkeypatch):
    """День ротации — максимум по пулу: так его хранит сама колонка."""
    spy = _Spy(result={"day": date(2026, 7, 28)})
    monkeypatch.setattr(db_module, "_fetchone", spy)

    day = asyncio.run(db_module.get_rotation_day(-100, ["binokl", "slepok"]))

    assert day == date(2026, 7, 28)
    assert "MAX(rotation_day)" in spy.query
    assert spy.params == (-100, "binokl", "slepok")


def test_set_rotation_writes_stock_and_day_together(monkeypatch):
    """Запас и день ставятся одним запросом: порознь позиция побывала бы
    в состоянии «сегодняшняя, но с вчерашним запасом»."""
    spy = _Spy(result=1)
    monkeypatch.setattr(db_module, "_execute", spy)

    asyncio.run(db_module.set_shop_item_rotation(-100, "binokl", 2, date(2026, 7, 28)))

    assert "SET stock = %s, rotation_day = %s" in spy.query
    assert spy.params == (2, date(2026, 7, 28), -100, "binokl")


def test_no_query_uses_doubled_placeholders(monkeypatch):
    """Ни один запрос лавки не должен уехать в драйвер с «%%s».

    Именно так ломается сборка списка плейсхолдеров через оператор %:
    подставленное значение повторно не обрабатывается, ошибки нет, а
    условие IN молча перестаёт совпадать с чем бы то ни было.
    """
    seen = []

    class _Collect(_Spy):
        async def __call__(self, query, params=()):
            seen.append(query)
            return await super().__call__(query, params)

    collect = _Collect(result={"day": None})
    monkeypatch.setattr(db_module, "_fetchall", collect)
    monkeypatch.setattr(db_module, "_fetchone", collect)
    monkeypatch.setattr(db_module, "_execute", collect)

    keys = ["binokl", "slepok"]
    asyncio.run(db_module.list_shop_items_for_restock(-100, exclude_keys=keys))
    asyncio.run(db_module.clear_rotation_stock(-100, keys))
    asyncio.run(db_module.get_rotation_day(-100, keys))
    asyncio.run(db_module.list_rotation_items(-100, keys, date(2026, 7, 28)))

    assert seen, "ни один запрос не выполнился — тест ничего не проверил"
    for query in seen:
        assert "%%s" not in query
