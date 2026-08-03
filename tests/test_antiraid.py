"""Антирейд: кнопки «РЕЙД НАЧАЛСЯ» / «РЕЙД ОКОНЧЕН» в личке бота.

Ломается такое в двух местах: в порядке действий (бан сотни человек занимает
минуту, и если он идёт до закрытия чата — рейд эту минуту продолжает работать)
и в отборе, кого банить: задень своих — и антирейд станет хуже рейда.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
ADMIN_ID = 7


class _Сообщение:
    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": ADMIN_ID, "type": "private"})()
        self.from_user = type("U", (), {"id": ADMIN_ID, "is_bot": False})()
        self.ответы = []

    async def answer(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def рейд(monkeypatch):
    """Всё разрешено, все вызовы записываются по порядку."""
    состояние = {"режим": False, "порядок": [], "баны": [], "новички": []}

    async def get_data(key):
        return {"data_value": "1"} if состояние["режим"] else None

    async def set_data(key, value, updated_by=None):
        состояние["режим"] = True
        состояние["порядок"].append("режим")

    async def delete_data(key):
        состояние["режим"] = False
        return True

    async def lock(chat_id, until=None):
        состояние["порядок"].append("закрыть")
        return True

    async def unlock(chat_id):
        состояние["порядок"].append("открыть")
        return True

    async def rotate(chat_id):
        состояние["порядок"].append("ссылка")
        return "https://t.me/+new"

    async def новички(chat_id, since, limit=500):
        состояние["порядок"].append("список")
        return состояние["новички"]

    async def ban(chat_id, user_id):
        состояние["порядок"].append("бан")
        состояние["баны"].append(user_id)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(bot_module.db, "get_data", get_data, raising=False)
    monkeypatch.setattr(bot_module.db, "set_data", set_data, raising=False)
    monkeypatch.setattr(bot_module.db, "delete_data", delete_data, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", noop, raising=False)
    monkeypatch.setattr(bot_module.db, "list_new_members_without_role_since",
                        новички, raising=False)
    monkeypatch.setattr(bot_module, "_lock_chat", lock, raising=False)
    monkeypatch.setattr(bot_module, "_unlock_chat", unlock, raising=False)
    monkeypatch.setattr(bot_module, "_raid_rotate_invite", rotate, raising=False)
    monkeypatch.setattr(bot_module.bot, "ban_chat_member", ban, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: True)
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: uid == ADMIN_ID)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    return состояние


def _новичок(uid):
    return {"user_id": uid, "full_name": f"Гость{uid}", "username": None,
            "first_seen_at": datetime.utcnow()}


def test_чат_закрывается_раньше_банов(рейд):
    """Бан сотни человек — это сотня запросов к Telegram. Сделай его до
    закрытия — и рейд получит на это лишнюю минуту в открытом чате."""
    рейд["новички"] = [_новичок(100), _новичок(101)]

    asyncio.run(bot_module.cmd_raid_start(_Сообщение(bot_module.BTN_RAID_ON)))

    порядок = рейд["порядок"]
    assert порядок.index("закрыть") < порядок.index("бан")
    assert порядок.index("ссылка") < порядок.index("бан"), (
        "пока баним, по старой ссылке заходили бы дальше"
    )


def test_банятся_свежие_новички(рейд):
    рейд["новички"] = [_новичок(100), _новичок(101), _новичок(102)]

    msg = _Сообщение(bot_module.BTN_RAID_ON)
    asyncio.run(bot_module.cmd_raid_start(msg))

    assert рейд["баны"] == [100, 101, 102]
    assert "3" in msg.ответы[0]


def test_своего_админа_антирейд_не_трогает(рейд):
    """Админ, зашедший минуту назад, — не рейд. Задень своих, и антирейд
    станет хуже рейда."""
    рейд["новички"] = [_новичок(100), _новичок(ADMIN_ID)]

    asyncio.run(bot_module.cmd_raid_start(_Сообщение(bot_module.BTN_RAID_ON)))

    assert рейд["баны"] == [100]


def test_владельца_бота_не_банят(рейд, monkeypatch):
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)
    владелец = next(iter(bot_module.OWNER_IDS))
    рейд["новички"] = [_новичок(владелец), _новичок(100)]

    asyncio.run(bot_module.cmd_raid_start(_Сообщение(bot_module.BTN_RAID_ON)))

    assert рейд["баны"] == [100]


def test_повторное_нажатие_не_банит_второй_раз(рейд):
    рейд["новички"] = [_новичок(100)]
    asyncio.run(bot_module.cmd_raid_start(_Сообщение(bot_module.BTN_RAID_ON)))

    msg = _Сообщение(bot_module.BTN_RAID_ON)
    asyncio.run(bot_module.cmd_raid_start(msg))

    assert рейд["баны"] == [100], "второе нажатие прошло по второму кругу"
    assert "уже включён" in msg.ответы[0]


def test_упёршийся_в_потолок_список_объявляется(рейд):
    """Молча обрезать список нельзя: админ решит, что накрыли всех."""
    рейд["новички"] = [_новичок(i) for i in range(bot_module.RAID_BAN_LIMIT)]

    msg = _Сообщение(bot_module.BTN_RAID_ON)
    asyncio.run(bot_module.cmd_raid_start(msg))

    assert "потолок" in msg.ответы[0]


def test_окончание_открывает_чат(рейд):
    asyncio.run(bot_module.cmd_raid_start(_Сообщение(bot_module.BTN_RAID_ON)))

    msg = _Сообщение(bot_module.BTN_RAID_OFF)
    asyncio.run(bot_module.cmd_raid_stop(msg))

    assert "открыть" in рейд["порядок"]
    assert not рейд["режим"]
    assert "выключен" in msg.ответы[0]


def test_без_режима_рейда_чат_не_открывают(рейд):
    """Чат могли закрыть обычным «-чат» по другой причине — кнопка не имеет
    права отменять чужое решение."""
    msg = _Сообщение(bot_module.BTN_RAID_OFF)
    asyncio.run(bot_module.cmd_raid_stop(msg))

    assert "открыть" not in рейд["порядок"]
    assert "не был включён" in msg.ответы[0]


def test_окно_пять_минут():
    """Число из просьбы. Поменяют — тест упадёт и заставит поправить справку."""
    assert bot_module.RAID_WINDOW == timedelta(minutes=5)


def test_кнопки_видны_только_с_правами():
    """Кнопка антирейда в чужой клавиатуре — это закрытый чат от промаха."""
    клавиатура = bot_module.private_menu_kb(ADMIN_ID)
    тексты = [b.text for row in клавиатура.keyboard for b in row]
    assert bot_module.BTN_RAID_ON in тексты or not bot_module.is_admin(ADMIN_ID)


# ---------------------------------------------------------------------------
# Как антирейд ЗАПУСКАЮТ
#
# Реестр команд обещает фразу «рейд начался / рейд окончен», а обработчики
# сверялись с текстом КНОПКИ — вместе с эмодзи. Получалось худшее из
# возможного: набранное руками в личке «рейд начался» уезжало админам ЗАЯВКОЙ
# НА ВСТУПЛЕНИЕ, а в самом чате — где админ и находится, когда рейд идёт, —
# не делало вообще ничего. Молча, в самый неподходящий момент.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("текст", [
    "🚨 РЕЙД НАЧАЛСЯ",      # кнопка из меню лички
    "рейд начался",
    "Рейд Начался",         # регистр не важен
    "  рейд начался  ",
])
def test_антирейд_включается_и_кнопкой_и_фразой(текст):
    assert bot_module._is_raid_on_phrase(текст)
    assert not bot_module._is_raid_off_phrase(текст)


@pytest.mark.parametrize("текст", ["✅ РЕЙД ОКОНЧЕН", "рейд окончен", "РЕЙД ОКОНЧЕН"])
def test_антирейд_выключается_и_кнопкой_и_фразой(текст):
    assert bot_module._is_raid_off_phrase(текст)
    assert not bot_module._is_raid_on_phrase(текст)


@pytest.mark.parametrize("текст", ["рейд", "рейды начались", "начался рейд", "", None])
def test_похожие_фразы_антирейд_не_включают(текст):
    """Ошибиться здесь дорого в обе стороны: лишний запуск закрывает чат и
    банит новичков."""
    assert not bot_module._is_raid_on_phrase(текст)
    assert not bot_module._is_raid_off_phrase(текст)


def test_набранная_фраза_не_уедет_заявкой():
    """is_private_passthrough решает, отправить ли написанное админам как
    заявку. Пока фразы там не было, «рейд начался» из лички уходило именно
    туда — вместе с профилем написавшего.

    Проверяем ВСЕ формы разом, а не перечисленные руками: два списка легко
    разъезжаются, и добавленная в один форма снова начнёт уезжать заявкой."""
    for фраза in bot_module.RAID_ON_PHRASES | bot_module.RAID_OFF_PHRASES:
        assert bot_module.is_private_passthrough(фраза), фраза
    assert bot_module.is_private_passthrough(bot_module.BTN_RAID_ON)
    assert bot_module.is_private_passthrough(bot_module.BTN_RAID_OFF)


def test_антирейд_работает_и_в_чате_и_в_личке():
    """Фильтр обработчика обязан пускать оба места: кнопки живут в личке, но
    рейд случается в чате, и туда админ пишет первым делом."""
    import inspect
    for fn in (bot_module.cmd_raid_start, bot_module.cmd_raid_stop):
        флаги = inspect.getsource(fn)
        assert "private" in флаги and "supergroup" in флаги, fn.__name__


def test_из_лички_фраза_доходит_до_своего_обработчика():
    """Заявочный обработчик стоит в файле раньше антирейда и ловит в личке всё.
    Он обязан ПРОПУСТИТЬ фразу дальше (SkipHandler), а не забрать себе."""
    from aiogram.dispatcher.event.bases import SkipHandler

    msg = _Сообщение("рейд начался")
    with pytest.raises(SkipHandler):
        asyncio.run(bot_module.handle_user_message(msg))
    assert msg.ответы == [], "антирейд не должен получить ответ вместо действия"
