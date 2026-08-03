"""Казино в кабинете: права, ачивки и кнопка «показать в чате».

Кнопка — самое опасное место всей работы: она пишет в общий чат от имени бота.
Поэтому здесь проверяется не то, что она работает, а то, что она не умеет
лишнего: текст берётся с сервера, показывается один раз и не чаще паузы.
"""

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
import casino_actions  # noqa: E402
from webpanel import member_casino_api as api  # noqa: E402


def test_у_каждой_игры_есть_право():
    assert set(api._GAME_COMMANDS) == set(casino_actions.GAMES)
    реестр = set(bot_module.COMMAND_REGISTRY)
    ключи = set(api._GAME_COMMANDS.values()) | set(api._MONEY_COMMANDS.values())
    ключи.add(api._LIST_COMMAND)
    assert ключи <= реестр, f"нет в реестре бота: {sorted(ключи - реестр)}"


def test_показ_в_чат_не_принимает_текст_снаружи():
    """Главная защита кнопки: в теле запроса нет и не должно быть поля с
    текстом. Появись оно — сайт стал бы способом написать в чат от имени бота
    что угодно, включая чужой выигрыш, которого не было."""
    поля = set(api.CasinoBody.model_fields)
    # chat_id из тела ушёл: чат один и знает его сервер (chats.work_chat_id).
    assert поля == {"bet", "color", "guess", "side", "amount"}
    исходник = inspect.getsource(api._share)
    assert "body" not in исходник, "показ обязан брать текст только из базы"
    assert "get_data" in исходник and "send_message" in исходник


def test_показ_одноразовый_и_с_паузой():
    исходник = inspect.getsource(api._share)
    assert "delete_data" in исходник, "отметку надо снимать — иначе показ бесконечный"
    assert "SHARE_COOLDOWN_SECONDS" in исходник
    assert api.SHARE_COOLDOWN_SECONDS >= 30
    # Отметка снимается ПОСЛЕ отправки: иначе не дошедшее сообщение оставило
    # бы человека без возможности повторить. (Раннее delete_data в ветке
    # «результат устарел» законно — сравниваем с последним.)
    assert исходник.index("send_message") < исходник.rindex("delete_data")


def test_показ_называет_игрока():
    """Результат приходит с сайта сам по себе: без имени чат увидит выигрыш
    ничей."""
    исходник = inspect.getsource(api.api_member_casino_play)
    assert "_player_name" in исходник
    assert "render_share" in исходник
    assert "html.escape" in inspect.getsource(api._player_name)


def test_ключи_показа_разные():
    """Отметка «что показать» и отметка «когда показывали» обязаны быть
    разными: показ стирает первую, и общая забывала бы про паузу."""
    assert api._share_key(-100, 7) != api._share_at_key(-100, 7)
    assert api._share_key(-100, 7) == "casino_share:-100:7"


def test_поздравления_совпадают_с_ботом():
    for код, текст in api.ACHIEVEMENT_TEXTS.items():
        meta = bot_module.ACHIEVEMENTS.get(код)
        assert meta, f"{код} пропал из ACHIEVEMENTS бота"
        assert meta["title"] in текст, f"{код}: название разъехалось"
        assert meta["desc"] in текст, f"{код}: описание разъехалось"
        assert meta["emoji"] in текст


def test_ачивки_казино_объявляются_все():
    """Что модуль правил умеет выдать, кабинет обязан уметь объявить."""
    коды = set()
    with open(casino_actions.__file__, encoding="utf-8") as f:
        for строка in f:
            if "achievements.append(" in строка:
                коды.add(строка.split('"')[1])
    assert коды <= set(api.ACHIEVEMENT_TEXTS), (
        f"не объявляются: {sorted(коды - set(api.ACHIEVEMENT_TEXTS))}")


def test_заморозка_закрывает_казино_и_на_сайте():
    for fn in (api.api_member_casino_play, api.api_member_casino_money):
        assert "is_account_frozen" in inspect.getsource(fn)


def test_чужой_чат_не_открывается():
    for fn in (api.api_member_casino, api.api_member_casino_play,
               api.api_member_casino_money):
        исходник = inspect.getsource(fn)
        assert "require_member_in_chat" in исходник
        assert "permissions.ensure" in исходник


def test_правила_общие_с_ботом():
    """Стык, ради которого модуль и заводился: выплаты считает одно место."""
    assert bot_module.CASINO_COLOR_ALIASES is casino_actions.COLOR_ALIASES
    assert bot_module._evaluate_poker_hand is casino_actions.evaluate_poker_hand
    assert bot_module.roulette_number_color is casino_actions.roulette_number_color
    assert bot_module.RED_ROULETTE_NUMBERS is casino_actions.RED_NUMBERS
    assert bot_module.CASINO_MAX_BET == casino_actions.MAX_BET


def test_старый_заход_показать_нельзя():
    """Отметка лежит в базе и переживает закрытие вкладки. Без срока годности
    человек, вернувшийся назавтра, отправил бы в чат вчерашний выигрыш — а
    соседи прочитали бы его как только что случившийся."""
    исходник = inspect.getsource(api._fresh_share)
    assert "SHARE_TTL_SECONDS" in исходник
    assert "delete_data" in исходник, "протухшую отметку надо убирать"
    assert api.SHARE_TTL_SECONDS <= 60 * 60
    # И показ, и рисование кнопки обязаны спрашивать одно и то же место —
    # иначе кнопка есть, а нажатие отвечает «нечего показывать».
    assert "_fresh_share" in inspect.getsource(api._share)
    assert "_fresh_share" in inspect.getsource(api.api_member_casino)
