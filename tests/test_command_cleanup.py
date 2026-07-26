"""Свой срок автоочистки у отдельной команды (панель → «Дерево команд»).

Главная и единственная хитрая часть — опознать команду по тексту сообщения.
Решение принимается в middleware, ДО выбора обработчика, поэтому ключ команды
восстанавливается из её фразы в COMMAND_REGISTRY. Фразы там человеческие
(«титул — список титулов»), и тесты ниже закрепляют, где проходит граница
между «слово команды» и началом описания.
"""

from __future__ import annotations

import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402


# --- разбор фраз реестра ---------------------------------------------------

def test_фраза_обрезается_на_описании():
    """«титул — список титулов»: слово команды одно, дальше проза."""
    assert bot_module._phrase_prefixes("титул — список титулов") == [("титул",)]


def test_фраза_обрезается_на_плейсхолдере():
    assert bot_module._phrase_prefixes("титул купить {ключ}") == [("титул", "купить")]


def test_фраза_обрезается_на_скобке():
    assert bot_module._phrase_prefixes("ферма (синонимы: !бизнес, фарма") == [("ферма",)]


def test_несколько_форм_через_слэш():
    assert bot_module._phrase_prefixes("титул надеть {ключ} / титул снять") == [
        ("титул", "надеть"), ("титул", "снять"),
    ]


def test_слэш_внутри_пояснения_не_режет_фразу():
    """«@username/ID» — это одно пояснение, а не две формы команды."""
    assert bot_module._phrase_prefixes("мут (ответом или @username/ID)") == [("мут",)]


# --- опознание команды по тексту -------------------------------------------

@pytest.mark.parametrize("text,key", [
    ("титул", "titles_list"),
    ("Титул", "titles_list"),                 # регистр не важен
    ("титул купить dragon", "title_buy"),     # длинная форма выигрывает у короткой
    ("титул надеть dragon", "title_equip"),
    ("титул снять", "title_equip"),
    ("!работа", "prof_run"),
    ("!работать", "prof_run"),
    ("!работа устроиться повар", "prof_join"),
    ("!работа топ", "prof_top"),
    ("стрик", "streak"),
    ("топ стриков", "streak_top"),
    ("магазин", "shop_list"),
])
def test_команда_опознаётся_по_тексту(text, key):
    assert bot_module.resolve_command_key(text) == key


@pytest.mark.parametrize("text", ["", "   ", "просто болтовня", None])
def test_не_команда_даёт_none(text):
    assert bot_module.resolve_command_key(text) is None


@pytest.mark.parametrize("text,key", [
    ("-мут", "unmute"),
    ("-бан", "unban"),
    ("-варн", "unwarn"),
    ("-чат", "chat_lock"),
    ("-смс", "delete_message"),
    ("-события", "chat_events_toggle"),
])
def test_команды_с_минусом_опознаются(text, key):
    """Дефис — это начало самой команды, а не описания. Приняв его за прозу,
    разбор терял бы «-мут», «-варн» и весь минусовой набор целиком."""
    assert bot_module.resolve_command_key(text) == key


def test_почти_все_команды_реестра_опознаются():
    """Опознаваемость — не «в среднем хорошо», а свойство каждой строки: под
    неопознаваемую команду панель не должна показывать поле срока."""
    unresolved = [k for k in bot_module.COMMAND_REGISTRY if not bot_module.is_cleanup_targetable(k)]
    # Эти четыре не отличить в принципе: две вызываются кнопкой в панели, ещё
    # две начинаются ровно так же, как соседняя команда.
    assert set(unresolved) == {"self_manage", "ship_target", "club_delete_admin", "club_coins"}, unresolved


def test_неотличимая_команда_помечена_явно():
    assert bot_module.is_cleanup_targetable("titles_list") is True
    assert bot_module.is_cleanup_targetable("club_coins") is False
    assert bot_module.is_cleanup_targetable("такой команды нет") is False


def test_каждый_ключ_из_индекса_есть_в_реестре():
    """Индекс строится из реестра — расхождение означало бы, что сроки
    сохраняются под ключом, которого панель не покажет."""
    for entries in bot_module._COMMAND_PREFIX_INDEX.values():
        for _order, key, _prefix in entries:
            assert key in bot_module.COMMAND_REGISTRY


# --- выбор срока -----------------------------------------------------------

@pytest.fixture
def _clean(monkeypatch):
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "15")
    bot_module.command_cleanup_overrides.clear()
    yield
    bot_module.command_cleanup_overrides.clear()


def test_без_своих_сроков_работает_общий(_clean):
    assert bot_module.cmd_cleanup_minutes_for("титул") == 15
    assert bot_module.cmd_cleanup_minutes_for("что-то своё") == 15


def test_свой_срок_перебивает_общий(_clean):
    bot_module.command_cleanup_overrides["titles_list"] = 3
    assert bot_module.cmd_cleanup_minutes_for("титул") == 3
    # у соседней команды своего срока нет — она осталась на общем
    assert bot_module.cmd_cleanup_minutes_for("титул купить dragon") == 15


def test_ноль_означает_не_удалять(_clean):
    bot_module.command_cleanup_overrides["titles_list"] = 0
    assert bot_module.cmd_cleanup_minutes_for("титул") == 0


def test_срок_подрезается_потолком(_clean):
    """В базе могло остаться значение, записанное в обход панели."""
    bot_module.command_cleanup_overrides["titles_list"] = 999_999
    assert bot_module.cmd_cleanup_minutes_for("титул") == bot_module.CMD_CLEANUP_MAX_MINUTES


def test_неопознанный_текст_идёт_по_общему_сроку(_clean):
    bot_module.command_cleanup_overrides["titles_list"] = 1
    assert bot_module.cmd_cleanup_minutes_for("привет всем") == 15
