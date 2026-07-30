"""«античк» — исключение из чистки для ОДНОГО сообщения.

Чистка команд ставит в очередь на удаление и саму команду, и все ответы бота
на неё. «античк» ответом снимает с удаления всю эту группу — к какой бы её
части ни ответили, — и помечает сообщение реакцией 🕊. Список «чк» при этом
не меняется: следующая такая же команда снова уберётся.

Зачем: большой выигрыш в казино или другой ценный ответ бота нужно оставить в
чате, не выключая чистку для команды целиком.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

ЧАТ = -1009999999999
АДМИН = 555
КОМАНДА_ID = 100      # сообщение человека: «баланс»
ОТВЕТ_БОТА_ID = 101   # ответ бота на него — тот самый ценный текст


class ОчередьЧистки:
    """Очередь на удаление в памяти — по тем же правилам, что и SQL:
    группа = сообщение-команда (root_message_id == его собственный id) плюс
    все ответы бота с этим root_message_id."""

    def __init__(self, rows: list[tuple[int, int, int | None]]):
        # (message_id, root_message_id)
        self.rows = [{"chat_id": c, "message_id": m, "root_message_id": r} for c, m, r in rows]

    async def add_cleanup_entry(self, chat_id, message_id, delete_at, root_message_id=None):
        self.rows.append(
            {"chat_id": chat_id, "message_id": message_id, "root_message_id": root_message_id}
        )

    async def cancel_cleanup_group(self, chat_id, message_id) -> int:
        цель = next(
            (r for r in self.rows if r["chat_id"] == chat_id and r["message_id"] == message_id),
            None,
        )
        if цель is None:
            return 0
        корень = цель["root_message_id"] or цель["message_id"]
        группа = [
            r for r in self.rows
            if r["chat_id"] == chat_id
            and (r["message_id"] == корень or r["root_message_id"] == корень)
        ]
        for r in группа:
            self.rows.remove(r)
        return len(группа)

    @property
    def ids(self) -> list[int]:
        return sorted(r["message_id"] for r in self.rows)


def _очередь(monkeypatch, rows=None) -> ОчередьЧистки:
    if rows is None:
        rows = [
            (ЧАТ, КОМАНДА_ID, КОМАНДА_ID),      # команда: сама себе корень
            (ЧАТ, ОТВЕТ_БОТА_ID, КОМАНДА_ID),   # ответ бота на неё
        ]
    q = ОчередьЧистки(rows)
    monkeypatch.setattr(bot_module.db, "add_cleanup_entry", q.add_cleanup_entry, raising=False)
    monkeypatch.setattr(bot_module.db, "cancel_cleanup_group", q.cancel_cleanup_group, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", _noop, raising=False)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЧАТ)
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "15")
    monkeypatch.setattr(bot_module, "has_level", lambda user_id, level: True)
    return q


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def список_чк():
    """Разобранные формы «чк» живут в модуле и monkeypatch их не откатывает:
    оставленная запись меняла бы поведение чистки в соседних тестах."""
    было = list(bot_module.cleanup_extra_phrases)
    yield
    bot_module.cleanup_extra_phrases[:] = было
    bot_module.rebuild_cleanup_extra_forms()


def _реакции(monkeypatch) -> list[tuple]:
    """Перехватываем реакции на уровне Bot API — через настоящий react()."""
    поставлены: list[tuple] = []

    async def set_message_reaction(chat_id, message_id, reaction, **kwargs):
        поставлены.append((chat_id, message_id, reaction[0].emoji if reaction else None))

    monkeypatch.setattr(bot_module.bot, "set_message_reaction", set_message_reaction)
    return поставлены


def _античк(reply_to: Message | None):
    """Сообщение «античк» (ответом или без) + перехват его текстовых ответов."""
    m = Message(
        message_id=200,
        date=datetime.now(),
        chat=Chat(id=ЧАТ, type="supergroup"),
        from_user=User(id=АДМИН, is_bot=False, first_name="Админ"),
        text="античк",
        reply_to_message=reply_to,
    )
    ответы: list[str] = []

    async def fake_reply(text, **kwargs):
        ответы.append(text)

    object.__setattr__(m, "reply", fake_reply)
    return m, ответы


def _чужое(message_id: int, *, от_бота: bool) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=Chat(id=ЧАТ, type="supergroup"),
        from_user=User(id=42 if от_бота else АДМИН, is_bot=от_бота, first_name="Бот" if от_бота else "Игрок"),
        text="Ваш баланс: 100500" if от_бота else "баланс",
    )


def test_античк_ответом_на_ответ_бота_спасает_и_команду(monkeypatch):
    """Главный сценарий: админ отвечает на ценный ответ бота (выигрыш)."""
    q = _очередь(monkeypatch)
    реакции = _реакции(monkeypatch)
    сообщение, ответы = _античк(_чужое(ОТВЕТ_БОТА_ID, от_бота=True))

    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert q.ids == [], f"из очереди снялось не всё: {q.ids}"
    assert ответы == [], f"на успех бот не должен ничего писать: {ответы}"
    assert реакции == [(ЧАТ, ОТВЕТ_БОТА_ID, bot_module.CLEANUP_KEEP_REACTION)]


def test_античк_ответом_на_команду_спасает_и_ответ_бота(monkeypatch):
    q = _очередь(monkeypatch)
    реакции = _реакции(monkeypatch)
    сообщение, ответы = _античк(_чужое(КОМАНДА_ID, от_бота=False))

    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert q.ids == []
    assert ответы == []
    assert реакции == [(ЧАТ, КОМАНДА_ID, bot_module.CLEANUP_KEEP_REACTION)]


def test_античк_не_меняет_список_чк(monkeypatch, список_чк):
    """Исключение — только для этого сообщения: команда остаётся в чистке и
    следующее такое же сообщение снова встаёт в очередь."""
    q = _очередь(monkeypatch)
    _реакции(monkeypatch)
    monkeypatch.setattr(bot_module, "cleanup_extra_phrases", ["баланс"])
    bot_module.rebuild_cleanup_extra_forms()

    сообщение, _ответы = _античк(_чужое(ОТВЕТ_БОТА_ID, от_бота=True))
    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert bot_module.cleanup_extra_phrases == ["баланс"], "список чк тронут"

    # новое такое же сообщение — снова в очередь
    новое = Message(
        message_id=300, date=datetime.now(), chat=Chat(id=ЧАТ, type="supergroup"),
        from_user=User(id=АДМИН, is_bot=False, first_name="Игрок"), text="баланс",
    )

    async def handler(event, data):
        return None

    asyncio.run(bot_module.CommandCleanupMiddleware()(handler, новое, {}))
    bot_module.rebuild_cleanup_extra_forms()
    assert 300 in q.ids, f"чистка перестала ловить команду: {q.ids}"


def test_античк_ставит_команду_корнем_группы(monkeypatch, список_чк):
    """Группа собирается только если очередь знает корень: команда пишется
    сама себе корнем, иначе «античк» не найдёт ответы бота."""
    q = _очередь(monkeypatch, rows=[])
    monkeypatch.setattr(bot_module, "cleanup_extra_phrases", ["баланс"])
    bot_module.rebuild_cleanup_extra_forms()

    сообщение = Message(
        message_id=КОМАНДА_ID, date=datetime.now(), chat=Chat(id=ЧАТ, type="supergroup"),
        from_user=User(id=АДМИН, is_bot=False, first_name="Игрок"), text="баланс",
    )

    async def handler(event, data):
        return None

    asyncio.run(bot_module.CommandCleanupMiddleware()(handler, сообщение, {}))

    assert q.rows and q.rows[0]["root_message_id"] == КОМАНДА_ID, q.rows


def test_ответ_бота_попадает_в_очередь_с_корнем_команды(monkeypatch):
    """Ответ бота едет в очередь через контекст чистки — с id команды в корне."""
    q = _очередь(monkeypatch, rows=[])
    delete_at = datetime.utcnow() + timedelta(minutes=15)

    class FakeResult:
        message_id = ОТВЕТ_БОТА_ID

    class FakeMethod:
        chat_id = ЧАТ

    async def make_request(bot_obj, method):
        return FakeResult()

    async def run():
        token = bot_module._cleanup_context.set((ЧАТ, delete_at, КОМАНДА_ID))
        try:
            await bot_module.cleanup_tracking_middleware(make_request, None, FakeMethod())
        finally:
            bot_module._cleanup_context.reset(token)
        # Постановка в очередь идёт фоновой задачей — дожидаемся её В ЭТОМ ЖЕ
        # цикле событий: из другого asyncio.run() её уже не докрутить, и
        # проверка держалась бы на порядке гашения задач при закрытии цикла.
        await asyncio.gather(*bot_module._cleanup_pending_tasks)

    asyncio.run(run())

    assert [(r["message_id"], r["root_message_id"]) for r in q.rows] == [
        (ОТВЕТ_БОТА_ID, КОМАНДА_ID)
    ], q.rows


def test_античк_без_реплая_объясняет_как_пользоваться(monkeypatch):
    _очередь(monkeypatch)
    реакции = _реакции(monkeypatch)
    сообщение, ответы = _античк(None)

    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert реакции == []
    assert len(ответы) == 1 and "античк" in ответы[0].lower(), ответы


def test_античк_на_сообщение_вне_очереди_не_врёт_реакцией(monkeypatch):
    """Голубь означает «останется в чате». Если сообщение и так не удаляется,
    ставить его нельзя — иначе пометка ничего не значит."""
    _очередь(monkeypatch, rows=[])
    реакции = _реакции(monkeypatch)
    сообщение, ответы = _античк(_чужое(ОТВЕТ_БОТА_ID, от_бота=True))

    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert реакции == []
    assert len(ответы) == 1 and "не удаляется" in ответы[0], ответы


def test_античк_не_для_всех(monkeypatch):
    q = _очередь(monkeypatch)
    реакции = _реакции(monkeypatch)
    monkeypatch.setattr(bot_module, "has_level", lambda user_id, level: False)
    monkeypatch.setattr(bot_module, "get_level", lambda user_id: bot_module.LEVEL_MODERATOR)
    сообщение, ответы = _античк(_чужое(ОТВЕТ_БОТА_ID, от_бота=True))

    asyncio.run(bot_module.cmd_cleanup_keep(сообщение))

    assert q.ids == [КОМАНДА_ID, ОТВЕТ_БОТА_ID], "очередь тронута без прав"
    assert реакции == []
    assert len(ответы) == 1 and "⛔" in ответы[0], ответы


def test_античк_есть_в_реестре_команд():
    """Реестр — источник прав и панели «Дерево команд»."""
    entry = bot_module.COMMAND_REGISTRY.get("cleanup_keep")
    assert entry is not None, "команда не заведена в реестр"
    assert entry["phrase"].split()[0] == "античк", entry
    assert bot_module.required_level("cleanup_keep") == bot_module.LEVEL_ADMIN


def test_вывод_чк_рассказывает_про_античк(monkeypatch, список_чк):
    """Про исключение должно быть написано там же, где список чистки, — иначе
    о нём никто не узнает."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЧАТ)
    monkeypatch.setattr(bot_module, "cleanup_extra_phrases", ["баланс"])
    bot_module.rebuild_cleanup_extra_forms()
    assert "античк" in bot_module._cleanup_status_text().lower()
