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
        for _order, key, _prefix, _open in entries:
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


# --- «команда это или живая речь» ------------------------------------------
#
# По is_command_like решают, ставить ли сообщение в очередь на удаление, так
# что ошибка здесь стоит переписки. Ловушка, из-за которой тесты появились:
# опознание шло по ПЕРВОМУ СЛОВУ, а у команды «не в норме» первое слово — «не».
# Любая фраза, начинающаяся с «не», уезжала в очистку.

_ЖИВАЯ_РЕЧЬ = [
    "не хочу тя учить,но если она понимающая и добрая подруга",
    "не знаю даже что сказать",
    "вне зависимости от этого всё равно норм",
    "где ты был вчера",
    "о чём вообще речь",
    "мой брат сказал что придёт",
    "моя мама так не думает",
    "мои друзья уже там",
    "твой ход",
    "названия у них смешные",
    "кто бы говорил",
    "клан распался давно",
    "банк закрыт до понедельника",
    "война это ужасно",
    "список покупок скинь",
    "удалить страшно жалко",
    "создать бы такое же",
    "участники все на месте",
    "общий сбор в семь",
    "чат тупит опять",
]


@pytest.mark.parametrize("text", _ЖИВАЯ_РЕЧЬ)
def test_обычная_фраза_не_считается_командой(text):
    assert not bot_module.is_command_like(text), text


@pytest.mark.parametrize("text,ключ", [
    ("не в норме", "norm_check"),
    ("вне нормы", "norm_check"),
    ("где мы", "whereami"),
    ("о себе", "about"),
    ("названия рангов", None),
    ("мой клан", None),
    ("моя анкета", None),
])
def test_многословная_команда_остаётся_командой(text, ключ):
    """Первое слово у них — обычное русское, командой делает вся форма."""
    assert bot_module.is_command_like(text)
    if ключ is not None:
        assert bot_module.resolve_command_key(text) == ключ


@pytest.mark.parametrize("text", [
    "не в норме сегодня", "где мы вообще", "названия рангов у нас смешные",
    "мой клан развалился", "дерево красивое", "профиль обнови пожалуйста",
    "команды какие есть", "бонус завтра дадут", "клад искать пойдём",
])
def test_команда_без_аргументов_не_ловится_с_хвостом(text):
    """«дерево» — команда, «дерево красивое» — нет. Форму без аргументов
    узнаём целиком: приставить к ней слово может только живая речь."""
    assert not bot_module.is_command_like(text), text


@pytest.mark.parametrize("text", [
    "помощь ачивки", "право 181 админ", "рп обнял всех", "рест 3д",
    "титул купить dragon", "мут @vasya 10м", "мои закладки 2",
])
def test_команда_с_аргументами_ловится_с_хвостом(text):
    """У этих форм хвост — сам аргумент, целиком их требовать нельзя."""
    assert bot_module.is_command_like(text), text


@pytest.mark.parametrize("text", ["о себе\nтекст про меня", "названия рангов\nПервый"])
def test_значение_со_следующей_строки_не_ломает_форму(text):
    """У «о себе» значение пишут со следующей строки — форму ищем в первой."""
    assert bot_module.is_command_like(text), text


@pytest.mark.parametrize("text", ["... ну ладно", ".. что", "- да ладно", "-", "+", "..."])
def test_знак_без_слова_не_команда(text):
    """Тире в диалоге, многоточие и одинокий «плюсую» — не команды."""
    assert not bot_module.is_command_like(text), text


@pytest.mark.parametrize("text", ["-мут", "+чат", ".инфа", "!орёл", "+1"])
def test_знак_со_словом_остаётся_командой(text):
    assert bot_module.is_command_like(text), text


def test_каждая_форма_из_реестра_опознаётся():
    """Сетка от обратной ошибки: сузили опознание — и половина команд перестала
    убираться. Проверяем не выборочно, а все формы всех команд разом."""
    непонятые = [
        " ".join(форма)
        for entry in bot_module.COMMAND_REGISTRY.values()
        for форма in bot_module._phrase_prefixes(entry["phrase"])
        if not bot_module.is_command_like(" ".join(форма))
    ]
    assert not непонятые, "формы команд не опознаны:\n" + "\n".join(непонятые)


def test_цель_с_упоминанием_не_требует_дословного_кому():
    """«досье @кому» в реестре — плейсхолдер: в чате там живой @username."""
    assert bot_module.is_command_like("досье @vasya")
    assert bot_module.resolve_command_key("досье @vasya") == "item_dossier"
    assert bot_module.resolve_command_key("саботаж @vasya") == "item_sabotage"


# --- ключи прав в обработчиках ---------------------------------------------
#
# _check_misc_access(user_id, "ключ") решает, пустить ли человека в команду.
# Ключ, которого нет в реестре, required_level вернёт по умолчанию, то есть
# проверка будет всегда проходить, а панель — сохранять уровень, который ничего
# не значит. Ровно тот же класс ошибки, что «право сохраняется и молча ничего
# не делает»; ловится только чтением исходника, потому что вызов ничем не
# отличается от правильного.

def test_права_проверяются_по_ключам_из_реестра():
    import inspect
    import re as _re
    источник = inspect.getsource(bot_module)
    ключи = set(_re.findall(r'_check_misc_access\([^,]+,\s*"([a-z0-9_]+)"\)', источник))
    assert ключи, "не нашли ни одного вызова — сломался разбор, а не код"
    лишние = sorted(k for k in ключи if k not in bot_module.COMMAND_REGISTRY)
    assert not лишние, f"ключей нет в реестре: {лишние}"


# --- синонимы первого слова -------------------------------------------------
#
# Бот зовёт одну команду несколькими словами (PET_WORD = пет|петы|питомец|
# питомцы, FARM_TRIGGERS, синонимы рыбалки), а во фразе реестра записано одно
# из них — остальные молча теряли автоочистку. Так и обнаружилось: «петы» в
# чате не убирались.

@pytest.mark.parametrize("text,ключ", [
    ("петы", "pet_list"),
    ("питомец", "pet_list"),
    ("питомцы", "pet_list"),
    ("петы каталог", "pet_list"),
    ("питомец кормить kot", "pet_care"),
    ("питомцы гулять все", "pet_care"),
    ("фарма", "farm_run"),
    ("фармить", "farm_run"),
    ("рыбачить", "fishing_run"),
    ("рыбка", "fishing_run"),
    ("удочка", "fishing_run"),
    ("садок", "fishing_net"),
])
def test_синоним_узнаётся_как_основная_команда(text, ключ):
    assert bot_module.is_command_like(text), text
    assert bot_module.resolve_command_key(text) == ключ


@pytest.mark.parametrize("text", [
    "рыбка моя, привет",
    "удочка сломалась вчера",
    "питомец у меня кот",
    "фарма это не про нас",
])
def test_синоним_в_живой_речи_не_команда(text):
    """Синонимы — обычные русские слова, и подстановка не должна делать
    командой целую фразу: форма без аргументов требует совпадения целиком."""
    assert not bot_module.is_command_like(text), text


def test_каждый_синоним_ведёт_к_известной_команде():
    """Опечатка в правой части словаря дала бы молчаливый промах: слово
    подменилось, а команды с таким первым словом нет."""
    осиротевшие = [f"{k} -> {v}" for k, v in bot_module._FIRST_WORD_SYNONYMS.items()
                   if v not in bot_module._CLEANUP_PREFIX_INDEX]
    assert not осиротевшие, "синонимы ведут в никуда: " + ", ".join(осиротевшие)


def test_все_написания_питомца_из_регулярки_узнаются():
    """PET_WORD — источник правды о том, как бот зовёт питомцев. Появится там
    пятое написание — этот тест упадёт, а не тихо потеряет очистку."""
    import re as _re
    формы = _re.findall(r"[а-яё]+", bot_module.PET_WORD)
    for форма in формы:
        assert bot_module.is_command_like(f"{форма} кормить kot"), форма


def test_каждый_набор_триггеров_узнаётся_очисткой():
    """Сплошная проверка всех *_TRIGGERS разом.

    Поштучно эту болезнь ловить бесполезно: она возвращается с каждым новым
    синонимом. Бот понимает «халтуру», «дейлик», «искать клад» и ещё два
    десятка написаний, а во фразе реестра записано одно — и все остальные
    молча переставали убираться. Так и вскрылось: «петы» висели в чате.

    Набор триггеров — это то, на что бот РЕАГИРУЕТ. Значит и убирать он
    обязан всё, на что реагирует, без исключений.
    """
    непонятые = []
    наборов = 0
    for имя, значение in sorted(vars(bot_module).items()):
        if not имя.endswith("_TRIGGERS"):
            continue
        if not isinstance(значение, (set, frozenset, tuple, list)):
            continue
        наборов += 1
        for триггер in значение:
            if not isinstance(триггер, str) or not триггер.strip():
                continue
            if not bot_module.is_command_like(триггер):
                непонятые.append(f"{имя}: {триггер!r}")
    assert наборов > 20, "не нашли наборы триггеров — сломался разбор, а не код"
    assert not непонятые, ("бот на это реагирует, а очистка не узнаёт:\n"
                           + "\n".join(непонятые))


@pytest.mark.parametrize("text", [
    "кукла моя красивая",
    "коллекция марок у деда",
    "мини юбка ей идёт",
    "рецепты бабушкины",
    "all in подумай",
    "скинемся на подарок",
    "халтура была тяжёлая",
])
def test_новые_синонимы_не_едят_живую_речь(text):
    """Синонимы — обычные слова. Защищает то же правило, что и раньше: форма
    без аргументов совпадает только целиком."""
    assert not bot_module.is_command_like(text), text
