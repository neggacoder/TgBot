"""Бизнесы в кабинете: права, ачивки и то, чего сайту делать нельзя."""

from __future__ import annotations

import inspect
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)
pytest.importorskip("fastapi", reason="нужен fastapi (см. .venv)")

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import business_actions  # noqa: E402
from webpanel import member_business_api as api  # noqa: E402


def test_у_каждого_действия_есть_право():
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = set(api._ACTION_COMMANDS.values()) | {api._LIST_COMMAND}
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_сделка_с_человеком_только_через_согласие():
    """Сайт умеет ПРЕДЛОЖИТЬ, но не перевести. Согласие даёт вторая сторона
    кнопкой в чате: односторонняя сделка отдала бы человеку чужой бизнес без
    спроса — вместе с налогом на копилку и обязанностью его чинить."""
    assert set(api._ACTION_COMMANDS) >= {"offer", "give"}
    # Предложение ничего не двигает: деньги и владелец меняются только в
    # accept_deal, а её зовёт обработчик кнопки в боте.
    исходник = inspect.getsource(business_actions.offer)
    for запрет in ("move_business", "add_coins", "try_spend_coins"):
        assert запрет not in исходник, f"offer не должна трогать {запрет}"
    assert "move_business" in inspect.getsource(business_actions.accept_deal)


def test_подтвердить_может_только_получатель():
    исходник = inspect.getsource(business_actions.accept_deal)
    assert 'presser_id != сделка["buyer"]' in исходник
    # Отказаться вправе обе стороны — и передумавший владелец тоже.
    assert "seller" in inspect.getsource(business_actions.decline_deal)


def test_предложение_живёт_в_базе_и_протухает():
    """В чате сделка лежит в памяти процесса бота. С сайта так нельзя:
    предлагает панель, а кнопку нажимают в другом процессе."""
    assert business_actions.deal_key(-100, 7) == "bizdeal:-100:7"
    assert business_actions.OFFER_TTL_SECONDS > 0
    assert "expires" in inspect.getsource(business_actions.load_deal)


def test_формат_кнопки_совпадает_с_обработчиком_бота():
    """Кнопку рисует панель, а нажатие ловит бот. Разъедься префикс — кнопка
    молча перестанет работать."""
    разметка = api._deal_keyboard(7, 500)
    данные = [b["callback_data"] for b in разметка["inline_keyboard"][0]]
    assert данные == ["bizdeal:7:ok", "bizdeal:7:no"]
    assert all(len(d.encode()) <= 64 for d in данные)
    assert bot_module.BIZ_DEAL_PREFIX == "bizdeal:"


def test_заморозка_закрывает_бизнесы_и_на_сайте():
    assert "is_account_frozen" in inspect.getsource(api.api_member_business_action)


def test_чужой_чат_не_открывается():
    for fn in (api.api_member_business, api.api_member_business_action):
        исходник = inspect.getsource(fn)
        assert "require_member_in_chat" in исходник and "permissions.ensure" in исходник


def test_поздравления_совпадают_с_ботом():
    for код, текст in api.ACHIEVEMENT_TEXTS.items():
        meta = bot_module.ACHIEVEMENTS.get(код)
        assert meta, f"{код} пропал из ACHIEVEMENTS бота"
        assert meta["title"] in текст and meta["desc"] in текст and meta["emoji"] in текст


def test_ачивки_бизнесов_объявляются_все():
    коды = set()
    with open(business_actions.__file__, encoding="utf-8") as f:
        текст = f.read()
    for строка in текст.split("\n"):
        if строка.strip().startswith('return ["coins'):
            коды.add(строка.split('"')[1])
    assert коды <= set(api.ACHIEVEMENT_TEXTS), f"не объявляются: {sorted(коды - set(api.ACHIEVEMENT_TEXTS))}"


def test_правила_общие_с_ботом():
    """Каталог бизнесов у бота и у сайта — один и тот же модуль."""
    assert bot_module.business_catalog is business_actions.catalog
