"""Дефолтные пороги доступа к степеням наград (bot.py).

Модератор — до степени 3, админ — до 4, старший админ — до 5, степени 6-8 —
только владелец. Проверяем формулу напрямую (не через полный запуск бота).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

import bot as bot_module  # noqa: E402


@pytest.mark.parametrize(
    "degree,expected_level",
    [
        (1, "LEVEL_MEMBER"),
        (2, "LEVEL_MODERATOR"),
        (3, "LEVEL_MODERATOR"),
        (4, "LEVEL_ADMIN"),
        (5, "LEVEL_SENIOR"),
        (6, "OWNER_LEVEL"),
        (7, "OWNER_LEVEL"),
        (8, "OWNER_LEVEL"),
    ],
)
def test_дефолтный_порог_по_степени(degree, expected_level):
    expected = getattr(bot_module, expected_level)
    assert bot_module._default_reward_degree_level(degree) == expected


def test_оверрайд_из_бд_важнее_дефолта():
    """required_reward_level уже умеет читать оверрайды — формула дефолта не
    должна её ломать."""
    bot_module.reward_degree_level_overrides[1] = bot_module.OWNER_LEVEL
    try:
        assert bot_module.required_reward_level(1) == bot_module.OWNER_LEVEL
    finally:
        bot_module.reward_degree_level_overrides.pop(1, None)
