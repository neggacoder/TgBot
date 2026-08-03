"""Отчёт по чатам: что где лежит.

Скрипт запускается на сервере — в среде разработки базы нет, — поэтому здесь
проверяется его чистая часть: как собираются запросы и как читается отчёт.
"""

from __future__ import annotations

from tools import chat_report


def test_запрос_считает_строки_по_чатам():
    запрос = chat_report.запрос_для("economy_wallets")
    assert "SELECT chat_id, COUNT(*)" in запрос
    assert "FROM economy_wallets" in запрос
    assert "GROUP BY chat_id" in запрос


def test_таблицы_берутся_из_схемы_а_не_из_списка():
    """Список руками устарел бы на первой же миграции, и отчёт молча пропустил
    бы таблицу — то есть соврал бы, что чужих данных там нет."""
    запрос = chat_report.запрос_таблиц()
    assert "information_schema.columns" in запрос
    assert "column_name = 'chat_id'" in запрос


def test_отчёт_помечает_чужие_чаты():
    строки = {"economy_wallets": {-100111: 30, -100999: 2}}
    отчёт = chat_report.отчёт(строки, свои=[-100111])
    assert "-100999" in отчёт and "чужой" in отчёт
    assert "свой" in отчёт and "economy_wallets" in отчёт


def test_отчёт_переживает_пустую_базу():
    """Свежая установка: таблицы есть, строк нет. Отчёт должен сказать это
    словами, а не упасть на пустом списке чатов."""
    отчёт = chat_report.отчёт({"economy_wallets": {}}, свои=[-100111])
    assert "economy_wallets" in отчёт
