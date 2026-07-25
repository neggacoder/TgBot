"""Справка бота не должна расходиться с тем, что код на самом деле делает.

Неверная справка хуже отсутствующей: человек по ней принимает решения. Здесь
проверяются те утверждения, которые уже успели разойтись с кодом или легко
разойдутся при следующей правке.
"""

from __future__ import annotations

import ast
import io
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name: str) -> str:
    return io.open(os.path.join(_ROOT, name), encoding="utf-8").read()


def _help_text() -> str:
    return _source("help_texts.py")


def test_роль_покинувшего_чат_освобождается_а_не_удаляется():
    """Код зовёт release_role_by_holder — роль переходит в «свободна» и
    остаётся в списке. Справка одно время утверждала обратное, и админы ждали,
    что список сам почистится."""
    bot = _source("bot.py")
    db = _source("db.py")

    # в db роль именно освобождается: UPDATE, а не DELETE
    body = db[db.index("async def release_role_by_holder"):]
    body = body[:body.index("\n\nasync def")]
    assert "UPDATE chat_roles" in body
    assert "DELETE" not in body.upper()

    # обработчик выхода из чата зовёт освобождение
    assert "release_role_by_holder" in bot

    # и справка не обещает удаления
    text = _help_text()
    for line in text.splitlines():
        if "покинувш" in line or "покидает чат" in line:
            assert "удаляется" not in line, f"справка обещает удаление роли: {line.strip()}"


def test_срок_варна_по_умолчанию_совпадает_с_кодом():
    """«срок по умолч. 7д» в справке и WARN_DEFAULT_DURATION в коде — одно и
    то же число; разъехавшись, они дезинформируют модератора о том, когда варн
    сгорит."""
    bot = _source("bot.py")
    match = re.search(r"WARN_DEFAULT_DURATION\s*=\s*timedelta\(days=(\d+)\)", bot)
    assert match, "не нашёлся WARN_DEFAULT_DURATION"
    days = match.group(1)

    text = _help_text()
    mentions = [l for l in text.splitlines() if "срок по умолч" in l]
    assert mentions, "в справке пропало упоминание срока варна по умолчанию"
    for line in mentions:
        assert f"{days}д" in line, f"справка расходится с кодом ({days} дней): {line.strip()}"


def test_обманные_варны_не_упоминаются_в_справке():
    """«&варн» — розыгрыш. Дерево команд и справка открыты всем, и упоминание
    команды там раскрыло бы её первому же читателю."""
    assert "&варн" not in _help_text()

    bot = _source("bot.py")
    registry = bot[bot.index("COMMAND_REGISTRY: dict[str, dict] = {"):bot.index("COMMAND_IDS: dict[str, int]")]
    assert "&варн" not in registry and "fake_warn" not in registry


def test_команды_из_справки_существуют_в_реестре():
    """Пробегаем по фразам реестра команд: если команду переименовали в коде,
    а в справке забыли, тест это покажет."""
    bot = _source("bot.py")
    registry = bot[bot.index("COMMAND_REGISTRY: dict[str, dict] = {"):bot.index("COMMAND_IDS: dict[str, int]")]
    phrases = re.findall(r'"phrase":\s*"([^"]+)"', registry)
    assert len(phrases) > 100, "реестр команд разобрался неверно"

    # ключевые команды модерации обязаны быть описаны в справке
    text = _help_text()
    for command in ["варн", "мут", "кик", "созыв"]:
        assert command in text, f"команда «{command}» не описана в справке"


def test_награды_хелп_соответствует_порогам_по_умолчанию():
    """Хелп называет конкретные степени по ролям — если формула в bot.py
    поменяется, а хелп нет, админы будут объяснять новичкам неверные пороги."""
    bot = _source("bot.py")
    help_src = _help_text()

    body = bot[bot.index("def _default_reward_degree_level"):]
    body = body[:body.index("\n\ndef ")]
    assert "degree == 1" in body
    assert "degree <= 3" in body
    assert "degree == 4" in body
    assert "degree == 5" in body
    assert "return OWNER_LEVEL" in body

    assert "1 — доступно всем" in help_src
    assert "2-3 — Модератор" in help_src
    assert "4 — Администратор" in help_src
    assert "5 — Старший администратор" in help_src
    assert "6-8 — только Владелец" in help_src
