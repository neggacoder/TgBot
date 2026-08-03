"""Магазин и инвентарь в кабинете: доступ и правила."""

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
import shop_actions  # noqa: E402
from webpanel import member_shop_api as api  # noqa: E402


def test_права_известны_боту():
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = set(api._ACTION_COMMANDS.values()) | {api._LIST_COMMAND}
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_заморозка_закрывает_магазин_и_на_сайте():
    assert "is_account_frozen" in inspect.getsource(api.api_member_shop_action)


def test_чужой_чат_не_открывается():
    for fn in (api.api_member_shop, api.api_member_shop_action):
        исходник = inspect.getsource(fn)
        assert "require_member_in_chat" in исходник and "permissions.ensure" in исходник


def test_числа_магазина_общие_с_ботом():
    assert shop_actions.BUY_MAX_QTY == bot_module.SHOP_BUY_MAX_QTY
    # 80% — та же доля, что в чате (см. cmd_item_sell).
    assert shop_actions.SELL_PERCENT == 80


def test_гейт_лавки_стоит_в_правилах_а_не_в_витрине():
    """Спрячь товар только из списка — и любой, кто знает ключ, купит его в
    обход ротации."""
    исходник = inspect.getsource(shop_actions.buy)
    assert "POOL_KEYS" in исходник and "rotation_day" in исходник
    assert "is_reward" in исходник, "награды не продаются"


def test_остаток_возвращается_если_денег_не_хватило():
    """Иначе товар исчезал бы с полки от каждой неудачной попытки купить."""
    исходник = inspect.getsource(shop_actions.buy)
    assert "return_shop_stock" in исходник
    assert исходник.index("try_take_shop_stock") < исходник.index("try_spend_coins")


def test_порядок_скидок_зафиксирован():
    """Событие множит базу, личные скидки режут результат. Переставь — и одна
    и та же скидка начнёт значить разные деньги."""
    исходник = inspect.getsource(shop_actions.price_for)
    assert исходник.index("event_multiplier") < исходник.index("discount_shop")
    assert исходник.index("discount_shop") < исходник.index("PERK_SHOP_DISCOUNT")
