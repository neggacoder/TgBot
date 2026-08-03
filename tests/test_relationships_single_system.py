"""Отношения — одна система, а не две.

«.отн X» и «отн X» — одна команда: точка срезается перед разбором, обе формы
идут в один обработчик и в одно хранилище фото. Разными картинки выглядели
потому, что файл из папки жеста выбирается случайно на каждый вызов.

А вот старый модуль отношений v1 (таблицы relationships/relationship_requests,
уровни близости, очки за действия) был мёртвым грузом: его команды давно
обслуживает v2, ни одна его функция из bot.py по делу не вызывалась, панель
его не редактировала. Он удалён целиком — тесты ниже стерегут, чтобы он не
вернулся по кускам.

Дружеские РП-действия («обнять @юзер») к отношениям отношения не имеют и живут
своей веткой: работают на всех, тогда как «отн обнять» — только на партнёре.
Это тоже проверяется, чтобы удаление v1 их не задело.
"""

from __future__ import annotations

import inspect
import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

УДАЛЁННЫЕ_КЛЮЧИ = [
    "couple", "relationship_propose", "relationship_accept",
    "relationship_break", "relationship_status", "relationship_actions",
    "relationship_top",
]


@pytest.mark.parametrize("ключ", УДАЛЁННЫЕ_КЛЮЧИ)
def test_ключей_v1_в_реестре_нет(ключ):
    assert ключ not in bot_module.COMMAND_REGISTRY


@pytest.mark.parametrize("фраза", ["отн запрос", "+отн", "-отн", "отн я",
                                   "отн история", "отн список", ".отн"])
def test_команды_v2_не_потерялись_в_реестре(фраза):
    """Фразы переехали на ключи rel2_*, а не пропали: иначе команда работает,
    но её нет ни в справке, ни в дереве прав, ни в автоочистке."""
    все = " / ".join(m["phrase"] for m in bot_module.COMMAND_REGISTRY.values())
    assert фраза in все


def test_в_боте_не_осталось_кэшей_v1():
    """Кэши уровней близости и очков за действия — часть удалённого модуля.
    Оставь их — и при старте бот продолжит ходить в таблицы, которых больше
    нет ни в схеме, ни в коде."""
    for имя in ("RELATIONSHIP_LEVELS", "REL_ACTION_POINTS",
                "REL_ONLY_PARTNER_ACTIONS", "relationship_level_index",
                "relationship_level_name", "relationship_next_level_info",
                "relationship_status_lines"):
        assert not hasattr(bot_module, имя), f"{имя} остался в bot.py"


def test_в_db_не_осталось_функций_v1():
    """Мёртвый слой обязан уйти целиком: половина удалённого модуля — это
    ловушка для следующей правки, а не экономия.

    relationship_undo остаётся намеренно: несмотря на имя, это общее хранилище
    «отмены расставания», и им пользуются И «Отношения 2.0», И браки.
    """
    import db as db_module

    оставляем = {"ensure_relationship_undo_table"}
    лишние = [
        имя for имя in dir(db_module)
        if "relationship" in имя and "rel2" not in имя and имя not in оставляем
    ]
    assert not лишние, f"функции v1 остались: {лишние}"


def test_общий_резолвер_цели_не_называется_отношениями():
    """Функция ищет цель по ответу или упоминанию и используется кланами.
    Имя из удалённого модуля осталось бы единственным его следом в живом
    коде — и первым, кого удалят «заодно» в следующий раз."""
    assert hasattr(bot_module, "resolve_reply_or_mention_target")
    assert not hasattr(bot_module, "resolve_relationship_target")


# ---------------------------------------------------------------------------
# То, с чего началась жалоба
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("форма", ["отн", "отн обнять", "отн я", "отн список"])
def test_точка_перед_отн_ничего_не_меняет(форма):
    """«.отн обнять» и «отн обнять» — одна команда: точка срезается перед
    разбором, обе формы идут в один обработчик и в одно хранилище фото.

    Разными картинки выглядели потому, что файл из папки жеста выбирается
    случайно на каждый вызов, а не потому, что систем было две."""
    import relationships_v2 as rel2

    assert rel2._first_word_is(форма, "отн")
    assert rel2._first_word_is(f".{форма}", "отн")
    assert rel2._strip_dot_prefix(f".{форма}") == форма


def test_фото_жестов_только_из_хранилища_сайта():
    """Второго источника картинок нет и появиться не должно: раньше рядом жил
    словарь ссылок на чужие хостинги, половина которых протухла."""
    import relationships_v2 as rel2
    import rp_photos

    src = inspect.getsource(rel2._pick_rp_photo_url)
    assert "rp_photos.pick_photo_url" in src
    assert rp_photos.MEDIA_ROOT.endswith(os.path.join("webpanel", "static", "rp_media"))


def test_дружеское_рп_осталось_отдельной_веткой():
    """«обнять @юзер» работает на всех, «отн обнять» — только на партнёре.
    Это разные вселенные, и удаление v1 не должно было их смешать."""
    import relationships_v2 as rel2

    assert bot_module._is_rp_action_command("обнять @vasya")
    assert "обнять" in bot_module.RP_ACTIONS
    assert "обнять" in rel2.SIMPLE_RP_ALIAS_MAP, "жест пары — своей веткой"


# ---------------------------------------------------------------------------
# Точка работает у всей семьи «отн», а не только у самой «отн»
#
# «.отн …» разбирался через _strip_dot_prefix, а соседние команды — «+отн»,
# «-отн», «рб …», «дом …» — сверялись с текстом буквально. Получалось, что
# половина модуля точку понимает, а половина молчит: предложение подаётся
# «.отн запрос», а принять его «.+отн» уже нельзя. Справка при этом сама
# предлагает короткий алиас «.рб».
# ---------------------------------------------------------------------------
СЕМЬЯ_ОТН = [
    "отн", "отн запрос", "отн я", "отн список", "отн обнять",
    "+отн", "-отн",
    "рб список", "ребенок список", "дом", "дом топ",
]


@pytest.mark.parametrize("команда", СЕМЬЯ_ОТН)
def test_точка_работает_у_всей_семьи(команда):
    """Обе формы обязан взять ОДИН и тот же обработчик: разные — это уже две
    команды, которые однажды разъедутся."""
    import asyncio
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    import relationships_v2 as rel2

    async def кто(текст):
        msg = Message(message_id=1, date=datetime.now(),
                      chat=Chat(id=-1003673552861, type="supergroup"),
                      from_user=User(id=555, is_bot=False, first_name="Т"), text=текст)
        for роутер in (rel2.router, bot_module.router):
            for h in роутер.message.handlers:
                try:
                    ok, _ = await h.check(msg, bot=bot_module.bot)
                except Exception:
                    continue
                if ok:
                    return h.callback.__name__
        return None

    без_точки = asyncio.run(кто(команда))
    с_точкой = asyncio.run(кто(f".{команда}"))
    assert без_точки is not None, f"«{команда}» не берёт никто"
    assert с_точкой == без_точки, f"«.{команда}» → {с_точкой}, а «{команда}» → {без_точки}"


# ---------------------------------------------------------------------------
# «отн запрос @username» — предложение с целью в тексте
#
# Разбор клал в «подкоманду» ВЕСЬ хвост: у «отн запрос @vasya» это
# «запрос @vasya», а ветка сверялась с голым словом «запрос» — и не совпадала
# никогда. Человек получал в ответ простыню со списком команд, где та же
# форма «отн запрос [@user/ответом]» и была написана.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("текст", [
    "отн запрос",
    "отн запрос @vasya",
    ".отн запрос @vasya",
    "отн запрос @Vasya_123",
    "отн расторгнуть",
    "отн расторгнуть @vasya",
    "отн",
])
def test_запрос_с_целью_доходит_до_обработчика(текст, monkeypatch):
    import asyncio
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    import relationships_v2 as rel2

    дошло = []

    async def перехват(message):
        дошло.append(message.text)

    monkeypatch.setattr(rel2, "_handle_rel2_propose_or_break", перехват)

    msg = Message(message_id=1, date=datetime.now(),
                  chat=Chat(id=-1003673552861, type="supergroup"),
                  from_user=User(id=555, is_bot=False, first_name="Т"), text=текст)
    ответы = []

    async def reply(t, **kwargs):
        ответы.append(t)

    object.__setattr__(msg, "reply", reply)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert дошло == [текст], f"вместо предложения бот ответил: {ответы}"


@pytest.mark.parametrize("текст,куда", [
    ("отн список", "cmd_rel2_list"),
    ("отн список 2", "cmd_rel2_list"),
    ("отн история", "cmd_rel2_history"),
    ("отн история 5", "cmd_rel2_history"),
    ("отн обнять", "cmd_rel2_simple_action"),
    ("отн обнять @vasya", "cmd_rel2_simple_action"),
    ("отн кусь @vasya", "cmd_rel2_simple_action"),
    (".отн обнять @vasya", "cmd_rel2_simple_action"),
    ("отн бонус", "cmd_rel2_bonus"),
    ("отн действия", "cmd_rel2_actions_catalog"),
])
def test_лишний_хвост_не_превращает_команду_в_справку(текст, куда, monkeypatch):
    """В «подкоманде» лежит ВЕСЬ хвост после «отн», поэтому любая ветка,
    сверяющаяся с ним целиком, ломается от первого же аргумента: «отн обнять
    @vasya» — привычка из дружеских РП-действий — вместо жеста выдавала
    простыню со списком команд. Сверяем первое слово хвоста."""
    import asyncio
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    import relationships_v2 as rel2

    попало = []
    for имя in ("cmd_rel2_list", "cmd_rel2_history", "cmd_rel2_simple_action",
                "cmd_rel2_bonus", "cmd_rel2_actions_catalog"):
        async def ловушка(*a, __имя=имя, **k):
            попало.append(__имя)
        monkeypatch.setattr(rel2, имя, ловушка)

    msg = Message(message_id=1, date=datetime.now(),
                  chat=Chat(id=-1003673552861, type="supergroup"),
                  from_user=User(id=555, is_bot=False, first_name="Т"), text=текст)
    ответы = []

    async def reply(t, **kwargs):
        ответы.append(t)

    object.__setattr__(msg, "reply", reply)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert попало == [куда], f"вместо {куда} бот ответил: {ответы}"


def test_неизвестная_подкоманда_по_прежнему_объясняется():
    """Терпимость к хвосту не должна проглатывать опечатки: «отн фигня» —
    это не команда, и человек обязан увидеть список."""
    import asyncio
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    import relationships_v2 as rel2

    msg = Message(message_id=1, date=datetime.now(),
                  chat=Chat(id=-1003673552861, type="supergroup"),
                  from_user=User(id=555, is_bot=False, first_name="Т"), text="отн фигня")
    ответы = []

    async def reply(t, **kwargs):
        ответы.append(t)

    object.__setattr__(msg, "reply", reply)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert ответы and "Доступно:" in ответы[0]


# ---------------------------------------------------------------------------
# Кнопки «да/нет» в отношениях
#
# Своего цвета у inline-кнопок Telegram нет — клавиатура всегда серая. Цвет
# даёт кружок в подписи, поэтому вид кнопок и есть их «цвет»: зелёный слева,
# красный справа. Разъедься подписи между предложением отношений, ребёнком и
# расторжением — и одинаковые по смыслу кнопки станут выглядеть по-разному.
# ---------------------------------------------------------------------------
def test_кнопки_да_нет_одинаковы_во_всём_модуле():
    import re

    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "relationships_v2.py"), encoding="utf-8").read()
    подписи = re.findall(r'InlineKeyboardButton\(text="([^"]+)", callback_data=f"(rel2_accept|rel2_decline|child_accept|child_decline|rel2_break_yes|rel2_break_no)',
                         src)
    assert подписи, "кнопки согласия/отказа не найдены — изменилась разметка?"
    for подпись, действие in подписи:
        ожидаем = "🟢 Да" if действие.endswith(("accept", "yes")) else "🔴 Нет"
        assert подпись == ожидаем, f"{действие}: подпись «{подпись}», ожидалась «{ожидаем}»"


# ---------------------------------------------------------------------------
# «отн запрос» ответом на сообщение — путь целиком
#
# Форма с @ником чинилась отдельно (подкомандой считался весь хвост), и после
# такой правки легко не заметить, что сломалась вторая форма. Здесь путь
# проходится целиком: команда → цель из ответа → заявка в базе → кнопки.
# ---------------------------------------------------------------------------
def _сообщение_ответом(текст, автор_id=555, цель_id=777, цель_бот=False):
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    чат = Chat(id=-1003673552861, type="supergroup")
    исходное = Message(
        message_id=10, date=datetime.now(), chat=чат,
        from_user=User(id=цель_id, is_bot=цель_бот, first_name="Цель"), text="привет",
    )
    msg = Message(
        message_id=11, date=datetime.now(), chat=чат,
        from_user=User(id=автор_id, is_bot=False, first_name="Автор"),
        text=текст, reply_to_message=исходное,
    )
    ответы: list[tuple] = []

    async def reply(t, **kwargs):
        ответы.append((t, kwargs.get("reply_markup")))

    object.__setattr__(msg, "reply", reply)
    return msg, ответы


@pytest.fixture
def отношения(monkeypatch):
    import relationships_v2 as rel2

    состояние = {"пары": {}, "заявки": []}

    async def get_rel2_pair(chat_id, user_id):
        return состояние["пары"].get(user_id)

    async def create_rel2_request(chat_id, from_id, to_id):
        состояние["заявки"].append((from_id, to_id))

    async def имя(*a, **k):
        return "Кто-то"

    monkeypatch.setattr(rel2.db, "get_rel2_pair", get_rel2_pair, raising=False)
    monkeypatch.setattr(rel2.db, "create_rel2_request", create_rel2_request, raising=False)
    monkeypatch.setattr(rel2, "_display_name", имя)
    monkeypatch.setattr(rel2, "_display_name_by_id", имя)
    return состояние


@pytest.mark.parametrize("текст", ["отн запрос", ".отн запрос", "отн", "ОТН ЗАПРОС"])
def test_запрос_ответом_создаёт_заявку(текст, отношения):
    """Цель берётся из сообщения, на которое отвечают, — @ник указывать не
    нужно. Это основная форма, ею пользуются чаще всего."""
    import asyncio

    import relationships_v2 as rel2

    msg, ответы = _сообщение_ответом(текст)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert отношения["заявки"] == [(555, 777)], f"заявка не создана, бот ответил: {ответы}"
    текст_ответа, клавиатура = ответы[-1]
    assert "предлагает" in текст_ответа
    подписи = [b.text for ряд in клавиатура.inline_keyboard for b in ряд]
    assert подписи == ["🟢 Да", "🔴 Нет"]


def test_запрос_ответом_самому_себе_отбивается(отношения):
    import asyncio

    import relationships_v2 as rel2

    msg, ответы = _сообщение_ответом("отн запрос", автор_id=555, цель_id=555)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert отношения["заявки"] == []
    assert "самому себе" in ответы[-1][0]


def test_запрос_ответом_боту_отбивается(отношения):
    import asyncio

    import relationships_v2 as rel2

    msg, ответы = _сообщение_ответом("отн запрос", цель_бот=True)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert отношения["заявки"] == []
    assert "Боты" in ответы[-1][0]


def test_запрос_ответом_партнёру_предлагает_расторжение(отношения):
    """Та же команда ответом на своего партнёра — это разрыв, и он обязан
    спросить подтверждение, а не рвать молча."""
    import asyncio

    import relationships_v2 as rel2

    отношения["пары"][555] = {"partner_id": 777, "id": 1}
    msg, ответы = _сообщение_ответом("отн запрос")
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert отношения["заявки"] == []
    текст_ответа, клавиатура = ответы[-1]
    assert "расторгнуть" in текст_ответа
    подписи = [b.text for ряд in клавиатура.inline_keyboard for b in ряд]
    assert подписи == ["🟢 Да", "🔴 Нет"]


def test_без_ответа_и_без_ника_бот_объясняет_как_надо(отношения):
    import asyncio
    from datetime import datetime

    from aiogram.types import Chat, Message, User

    import relationships_v2 as rel2

    msg = Message(message_id=1, date=datetime.now(),
                  chat=Chat(id=-1003673552861, type="supergroup"),
                  from_user=User(id=555, is_bot=False, first_name="Т"), text="отн запрос")
    ответы = []

    async def reply(t, **kwargs):
        ответы.append(t)

    object.__setattr__(msg, "reply", reply)
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert отношения["заявки"] == []
    assert "ответьте на сообщение" in ответы[0]


# ---------------------------------------------------------------------------
# «отн запрос @ник» — цель ищется в реестре бота, а не у Telegram
#
# Bot API не умеет превращать @ник в user_id: getChat по юзернейму обычного
# человека отвечает ошибкой. Поэтому весь остальной бот (муты, награды,
# подарки) ищет цель среди известных ему участников чата — а «отн запрос»
# ходил в getChat и всегда получал None. Со стороны: «ответьте на сообщение
# человека», хотя ник указан прямо в команде.
# ---------------------------------------------------------------------------
def _сообщение_с_ником(текст, ник="DOLKA_MANDARINKY"):
    from datetime import datetime

    from aiogram.types import Chat, Message, MessageEntity, User

    смещение = текст.index("@")
    msg = Message(
        message_id=11, date=datetime.now(),
        chat=Chat(id=-1003673552861, type="supergroup"),
        from_user=User(id=555, is_bot=False, first_name="Автор"),
        text=текст,
        entities=[MessageEntity(type="mention", offset=смещение, length=len(ник) + 1)],
    )
    ответы: list[tuple] = []

    async def reply(t, **kwargs):
        ответы.append((t, kwargs.get("reply_markup")))

    object.__setattr__(msg, "reply", reply)
    return msg, ответы


@pytest.fixture
def реестр_участников(monkeypatch, отношения):
    """Бот знает DOLKA_MANDARINKY по этому чату — как и любого, кто в нём писал."""
    import relationships_v2 as rel2

    async def in_chat(chat_id, username):
        if username.casefold() == "dolka_mandarinky":
            return {"user_id": 777, "full_name": "Долька", "username": "DOLKA_MANDARINKY"}
        return None

    async def globally(username):
        return None

    monkeypatch.setattr(rel2.db, "get_known_user_by_username_in_chat", in_chat, raising=False)
    monkeypatch.setattr(rel2.db, "get_known_user_by_username", globally, raising=False)
    return отношения


@pytest.mark.parametrize("текст", [
    "отн запрос @DOLKA_MANDARINKY",
    ".отн запрос @DOLKA_MANDARINKY",
    "отн запрос @dolka_mandarinky",
])
def test_запрос_с_ником_находит_цель(текст, реестр_участников):
    import asyncio

    import relationships_v2 as rel2

    msg, ответы = _сообщение_с_ником(текст, "DOLKA_MANDARINKY" if "@D" in текст else "dolka_mandarinky")
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert реестр_участников["заявки"] == [(555, 777)], f"бот ответил: {ответы}"


def test_незнакомый_ник_объясняется_отдельно(реестр_участников):
    """«Ответьте на сообщение» в ответ на команду С НИКОМ — неверная подсказка:
    человек всё указал правильно, просто бот этого участника ещё не видел."""
    import asyncio

    import relationships_v2 as rel2

    msg, ответы = _сообщение_с_ником("отн запрос @nekto_neznakomyi", "nekto_neznakomyi")
    asyncio.run(rel2.cmd_rel2_word(msg))

    assert реестр_участников["заявки"] == []
    assert "не видел" in ответы[-1][0]
