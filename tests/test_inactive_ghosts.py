"""«Кто неактив» и «молчуны» не должны показывать вышедших.

История бага в два слоя, и первый слой был вылечен не до конца:

1. Списки читали known_users — таблицу всех, кого бот когда-либо видел, —
   и вышедшие оттуда не удаляются никогда. Починили соединением с ростером
   current_users.
2. Но сам ростер чистится ТОЛЬКО когда бот получил событие выхода. Бот был
   выключен, Telegram не доставил апдейт в большой супергруппе — и человек
   остаётся в ростере навсегда. В списке неактивных такой призрак вылезает
   первым: он «не писал» дольше всех.

Поэтому список сверяется с Telegram напрямую и вычищает найденных призраков
из ростера — со второго вызова лишних запросов уже нет.
"""

from __future__ import annotations

import asyncio
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ROWS = [
    {"user_id": 1, "full_name": "Живой", "username": "alive"},
    {"user_id": 2, "full_name": None, "username": None},      # призрак без имени
    {"user_id": 3, "full_name": "Тоже живой", "username": None},
]


def _member(status):
    return type("M", (), {"status": status})()


@pytest.fixture
def world(monkeypatch):
    state = {"deleted": [], "statuses": {1: "member", 2: "left", 3: "member"}}

    async def get_chat_member(chat_id, user_id):
        status = state["statuses"].get(user_id)
        if isinstance(status, Exception):
            raise status
        return _member(status)

    async def delete_current_user(chat_id, user_id):
        state["deleted"].append(user_id)

    monkeypatch.setattr(bot_module.bot, "get_chat_member", get_chat_member, raising=False)
    monkeypatch.setattr(bot_module.db, "delete_current_user",
                        delete_current_user, raising=False)
    return state


def _filter(rows=None):
    # Именно «is None», а не «or»: пустой список ложный, и с «or» проверка
    # пустого входа молча подставляла бы полный набор.
    return asyncio.run(bot_module._drop_left_members(
        CHAT_ID, ROWS if rows is None else rows))


def test_вышедший_не_попадает_в_список(world):
    kept = _filter()
    assert [r["user_id"] for r in kept] == [1, 3]


def test_вышедший_вычищается_из_ростера(world):
    """Иначе он вернулся бы в список при следующем вызове — и так каждый раз."""
    _filter()
    assert world["deleted"] == [2]


def test_второй_вызов_уже_чистый(world):
    _filter()
    world["statuses"].pop(2, None)
    remaining = [r for r in ROWS if r["user_id"] != 2]
    kept = _filter(remaining)
    assert [r["user_id"] for r in kept] == [1, 3]


@pytest.mark.parametrize("status", ["left", "kicked"])
def test_и_вышедшие_и_выгнанные_убираются(world, status):
    world["statuses"][2] = status
    kept = _filter()
    assert 2 not in [r["user_id"] for r in kept]


def test_неизвестный_пользователь_тоже_убирается(world):
    """Telegram отвечает ошибкой и на «пользователя не существует» — такого
    в чате точно нет."""
    from aiogram.exceptions import TelegramBadRequest
    world["statuses"][2] = TelegramBadRequest(method=None, message="user not found")
    kept = _filter()
    assert 2 not in [r["user_id"] for r in kept]
    assert world["deleted"] == [2]


def test_сетевой_сбой_не_выкидывает_живого(world):
    """Самое важное здесь: показать лишнего не страшно, а выкинуть настоящего
    участника из-за обрыва сети — уже потеря данных, ведь мы бы и из ростера
    его удалили."""
    world["statuses"][3] = RuntimeError("сеть отвалилась")
    kept = _filter()
    assert 3 in [r["user_id"] for r in kept], "при сбое человека оставляем"
    assert 3 not in world["deleted"], "и уж точно не удаляем из ростера"


def test_пустой_список_не_ломается(world):
    assert _filter([]) == []


def test_все_живы_никого_не_трогаем(world):
    world["statuses"] = {1: "member", 2: "administrator", 3: "creator"}
    kept = _filter()
    assert len(kept) == 3
    assert world["deleted"] == []


# ---------------------------------------------------------------------------
# Плановая сверка ростера (roster_sweep_loop). Разовая чистка на показе списка
# лечит только тех, кто в этот список попал; призраки же сидят во ВСЕХ топах,
# потому что после разделения таблиц все выборки спрашивают current_users.
# ---------------------------------------------------------------------------
@pytest.fixture
def roster(monkeypatch):
    # bot.id разбирается aiogram'ом из тестового токена; сверка начинается с
    # вопроса про самого бота — «а этот чат вообще существует и я в нём?».
    state = {
        "deleted": [],
        "checked": [],
        "statuses": {bot_module.bot.id: "administrator",
                     1: "member", 2: "left", 3: "member"},
        "rows": [{"user_id": 1}, {"user_id": 2}, {"user_id": 3}],
    }

    async def get_chat_member(chat_id, user_id):
        state["checked"].append(user_id)
        status = state["statuses"].get(user_id)
        if isinstance(status, Exception):
            raise status
        return _member(status)

    async def delete_current_user(chat_id, user_id):
        state["deleted"].append(user_id)

    async def list_stale_roster_members(chat_id, limit=300):
        return state["rows"]

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(bot_module.bot, "get_chat_member", get_chat_member, raising=False)
    monkeypatch.setattr(bot_module.db, "delete_current_user", delete_current_user, raising=False)
    monkeypatch.setattr(bot_module.db, "list_stale_roster_members",
                        list_stale_roster_members, raising=False)
    monkeypatch.setattr(bot_module.asyncio, "sleep", no_sleep)
    return state


def _sweep():
    return asyncio.run(bot_module._sweep_chat_roster(CHAT_ID))


def test_сверка_убирает_вышедшего_из_ростера(roster):
    assert _sweep() == 1
    assert roster["deleted"] == [2]


def test_сверка_не_трогает_живых(roster):
    roster["statuses"] = {1: "member", 2: "administrator", 3: "creator"}
    assert _sweep() == 0
    assert roster["deleted"] == []


def test_потеря_доступа_к_чату_прерывает_сверку(roster):
    """TelegramForbiddenError здесь про самого бота (выгнали, забрали права),
    а не про участника. Вычистить на этом основании весь ростер — потерять
    состав чата целиком, поэтому останавливаемся."""
    from aiogram.exceptions import TelegramForbiddenError
    roster["statuses"][1] = TelegramForbiddenError(method=None, message="bot was kicked")

    assert _sweep() == 0
    assert roster["deleted"] == []
    assert roster["checked"] == [bot_module.bot.id, 1], "после отказа дальше не идём"


def test_несуществующий_чат_не_обнуляет_ростер(roster):
    """Самое опасное место сверки. Удалённая группа и старый chat_id после
    миграции в супергруппу отвечают «chat not found» — тем же
    TelegramBadRequest, что и «участника тут нет». Разбирайся мы по ответу на
    участника — вычистили бы ростер такого чата целиком, по 300 человек за
    заход. Поэтому первый вопрос — про самого бота."""
    from aiogram.exceptions import TelegramBadRequest
    roster["statuses"][bot_module.bot.id] = TelegramBadRequest(
        method=None, message="chat not found")

    assert _sweep() == 0
    assert roster["deleted"] == []
    assert roster["checked"] == [bot_module.bot.id], "до участников дело не дошло"


def test_бота_выгнали_из_чата_ростер_цел(roster):
    roster["statuses"][bot_module.bot.id] = "left"

    assert _sweep() == 0
    assert roster["deleted"] == []


def test_сетевой_сбой_не_чистит_но_и_не_останавливает(roster):
    roster["statuses"][1] = RuntimeError("сеть отвалилась")

    assert _sweep() == 1
    assert roster["deleted"] == [2], "сбойного оставили, вышедшего убрали"
    assert roster["checked"] == [bot_module.bot.id, 1, 2, 3]


def test_сверка_включена_в_запуск():
    """Цикл бесполезен, если его забыли создать при старте."""
    import inspect
    assert "create_task(roster_sweep_loop())" in inspect.getsource(bot_module.main)


def test_списки_берут_с_запасом_и_режут_после_чистки():
    """Если запрашивать ровно 30 и часть отсеять, список окажется короче
    запрошенного — поэтому берём больше и режем уже после сверки."""
    import inspect
    for fn in (bot_module.cmd_inactive_list, bot_module.cmd_silent_list):
        src = inspect.getsource(fn)
        assert "_drop_left_members" in src, fn.__name__
        assert "limit=50" in src, fn.__name__
        assert "[:30]" in src, fn.__name__
