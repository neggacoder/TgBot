"""Распознавание команд созыва (call_commands.py).

Отдельно стережём случай, из-за которого этот модуль и появился: созыв,
отправленный подписью к фотографии. У такого сообщения message.text пустой,
текст лежит в caption, и фильтр по одному .text команду не видел.
"""

from __future__ import annotations

import pytest

from call_commands import (
    call_header,
    command_text,
    is_call_admins_cmd,
    is_call_all_cmd,
    is_call_stop_cmd,
)


class FakeMessage:
    """Сообщение с теми полями, которые смотрит command_text. Настоящий
    aiogram для этого не нужен — и в тестах его нет."""

    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption


# ---------------------------------------------------------------------------
# Где лежит текст команды
# ---------------------------------------------------------------------------

def test_текст_обычного_сообщения():
    assert command_text(FakeMessage(text="созыв все сюда")) == "созыв все сюда"


def test_подпись_к_фото_это_тоже_команда():
    """Фото с подписью «созыв ...»: text пустой, всё в caption."""
    assert command_text(FakeMessage(caption="созыв все сюда")) == "созыв все сюда"


def test_фото_без_подписи_не_команда():
    assert command_text(FakeMessage()) is None


def test_созыв_подписью_к_фото_распознаётся():
    """Ровно тот случай, который был сломан: команда приходит из caption."""
    photo = FakeMessage(caption="созыв, все на стрим")
    assert is_call_all_cmd(command_text(photo))
    assert call_header(command_text(photo)) == "все на стрим"


def test_созыв_админов_подписью_к_фото_распознаётся():
    photo = FakeMessage(caption="калладминс срочно")
    assert is_call_admins_cmd(command_text(photo))
    assert not is_call_all_cmd(command_text(photo))


def test_стоп_подписью_к_фото_распознаётся():
    assert is_call_stop_cmd(command_text(FakeMessage(caption="стоп")))


# ---------------------------------------------------------------------------
# Сами триггеры
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["созыв", "калл", "call", "all", "алл", "СОЗЫВ", "  созыв  "])
def test_триггеры_созыва(text):
    assert is_call_all_cmd(text)


@pytest.mark.parametrize("text", [
    "созыв, все сюда", "созыв! срочно", "созыв. подходим", "калл, го", "созыв: сбор",
])
def test_пунктуация_после_команды_не_мешает(text):
    """«созыв, все сюда» — обычный способ написать это по-русски. Без снятия
    запятой первое слово получалось «созыв,» и команда молча не срабатывала."""
    assert is_call_all_cmd(text)


@pytest.mark.parametrize("text", ["стоп!", "стоп.", "отмена,"])
def test_остановка_с_пунктуацией(text):
    assert is_call_stop_cmd(text)


@pytest.mark.parametrize("text", ["калладминс", "созыв админов", "call admins", "КаллАдминс"])
def test_триггеры_созыва_админов(text):
    assert is_call_admins_cmd(text)


def test_созыв_админов_не_считается_общим_созывом():
    """Иначе «созыв админов» поднял бы весь чат — обе команды начинаются
    одинаково."""
    assert not is_call_all_cmd("созыв админов")


@pytest.mark.parametrize("text", [None, "", "   ", "созывать", "калловый", "всё"])
def test_посторонний_текст_не_команда(text):
    assert not is_call_all_cmd(text)
    assert not is_call_admins_cmd(text)
    assert not is_call_stop_cmd(text)


def test_слово_в_середине_не_запускает_созыв():
    """Команда — только первое слово: иначе рассказ «а потом был созыв» звал бы
    весь чат."""
    assert not is_call_all_cmd("а потом был созыв")


# ---------------------------------------------------------------------------
# Заголовок
# ---------------------------------------------------------------------------

def test_заголовок_из_остатка_строки():
    assert call_header("созыв все на стрим") == "все на стрим"


@pytest.mark.parametrize("text", ["созыв", "созыв   ", None, ""])
def test_без_пояснения_заголовка_нет(text):
    assert call_header(text) is None
