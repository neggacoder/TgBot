"""Свой срок автоочистки у отдельной команды (панель → «Дерево команд»).

Главная и единственная хитрая часть — опознать команду по тексту сообщения.
Решение принимается в middleware, ДО выбора обработчика, поэтому ключ команды
восстанавливается из её фразы в COMMAND_REGISTRY. Фразы там человеческие
(«титул — список титулов»), и тесты ниже закрепляют, где проходит граница
между «слово команды» и началом описания.
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
# Чисткой is_command_like больше НЕ управляет — её решает список «чк». Но
# ответ «бот знает такую форму?» остался нужен подсказкам: «+чк» ответом ищет
# по нему границу команды. Ловушка, из-за которой тесты появились: опознание
# шло по ПЕРВОМУ СЛОВУ, а у команды «не в норме» первое слово — «не», и любая
# фраза с «не» считалась командой.

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


# ---------------------------------------------------------------------------
# «дом» и остальные команды relationships_v2
#
# Симптом был такой: «дом» в чате жалоб не убирался никогда. Причин у него
# оказалось ДВЕ, независимые друг от друга, и каждая в одиночку ломала чистку
# целиком. Поэтому и тестов два.
# ---------------------------------------------------------------------------

def test_очистка_живёт_на_диспетчере_а_не_на_роутере():
    """Причина №1 — порядок роутеров.

    relationships_v2.router подключён к диспетчеру РАНЬШЕ основного, а в
    очередь на удаление сообщение ставила middleware, висевшая на основном
    роутере. Всё, что разбирал rel2 («дом», «отн», «рб»), до неё не доходило
    и в очередь не попадало никогда.

    Проверяем именно место регистрации: вернись эта логика на роутер — и
    команды rel2 молча выпадут из чистки снова, а поймать это по поведению
    без живого Telegram нечем.
    """
    на_диспетчере = [type(m).__name__ for m in bot_module.dp.message.outer_middleware]
    assert "CommandCleanupMiddleware" in на_диспетчере, (
        "middleware очистки обязана стоять на диспетчере — иначе команды "
        "relationships_v2 в очередь не попадают"
    )


@pytest.mark.parametrize("text", [
    "дом",
    "дом купить cottage",
    "дом комнаты",
    "дом комнаты декор",
    "дом комната kitchen",
    "дом улучшения",
    "дом улучшить kitchen",
    "дом действие kitchen",
    "дом продать",
    "дом топ",
])
def test_все_формы_дома_опознаются(text):
    """Причина №2 — фраза реестра без плейсхолдеров.

    «дом купить» было записано как форма БЕЗ аргумента, то есть требовало
    совпадения целиком, и «дом купить cottage» не опознавалось вовсе. Одной
    починки роутера было бы мало: чистилось бы голое «дом», а всё остальное
    продолжало бы висеть.
    """
    assert bot_module.is_command_like(text), text
    assert bot_module.resolve_command_key(text) == "rel2_house", text


@pytest.mark.parametrize("text", [
    "отн пт",
    "отн пт яйцо kot",
    "отн пт карта 5",
    "отн пт имя 5 Барсик",
    "отн пт действие 5 play",
    "отн пт домик 5 box",
    "отн пт комната 5 kitchen",
    "отн пт отпустить 5",
])
def test_все_формы_питомцев_пары_опознаются(text):
    assert bot_module.is_command_like(text), text
    assert bot_module.resolve_command_key(text) == "rel2_pets", text


def test_дом_в_живой_речи_остаётся_речью():
    """Голое «дом» намеренно оставлено полной формой: обработчик rel2 отвечает
    на любое сообщение, начинающееся этим словом, но удалять из-за этого чужую
    фразу бот не должен. Кому нужно иначе — есть ручной список «+чк дом»."""
    assert not bot_module.is_command_like("дом у меня далеко")


# ---------------------------------------------------------------------------
# Ручной список чистки — команды «чк», «+чк», «-чк»
# ---------------------------------------------------------------------------

@pytest.fixture
def пустой_список():
    """Список глобальный, поэтому соседние тесты обязаны видеть его чистым."""
    было = list(bot_module.cleanup_extra_phrases)
    bot_module.cleanup_extra_phrases.clear()
    bot_module.rebuild_cleanup_extra_forms()
    yield
    bot_module.cleanup_extra_phrases[:] = было
    bot_module.rebuild_cleanup_extra_forms()


def test_ручной_список_добирает_то_чего_не_узнал_реестр(пустой_список):
    """Ровно тот сценарий, ради которого «чк» и заводили."""
    assert not bot_module.is_command_like("дом у меня далеко")

    bot_module.cleanup_extra_phrases.append("дом")
    bot_module.rebuild_cleanup_extra_forms()

    assert bot_module.is_command_like("дом у меня далеко")

    bot_module.cleanup_extra_phrases.clear()
    bot_module.rebuild_cleanup_extra_forms()

    assert not bot_module.is_command_like("дом у меня далеко"), (
        "«-чк» обязан возвращать всё как было"
    )


def test_ручная_запись_ловит_по_началу_сообщения(пустой_список):
    """Смысл слов «чистить эту команду» для многоформенной команды — покрыть
    все её формы разом, а не только голое название."""
    bot_module.cleanup_extra_phrases.append("дом")
    bot_module.rebuild_cleanup_extra_forms()

    assert bot_module.is_command_like("дом топ")
    assert bot_module.is_command_like("дом купить cottage")
    # Но по началу СЛОВА, а не строки: «домик» — другое слово.
    assert not bot_module.is_command_like("домик у озера")
    # И только с начала сообщения, а не откуда попало.
    assert not bot_module.is_command_like("мой дом топ")


def test_ручная_запись_нормализуется_как_входящее_сообщение(пустой_список):
    """По обе стороны сравнения — один и тот же разбор: ё→е и синоним первого
    слова. Разбери мы фразу иначе — «+чк налёт» записал бы форму, до которой
    входящее «налет» уже не доходит."""
    bot_module.cleanup_extra_phrases.append("Налёт Соседа")
    bot_module.rebuild_cleanup_extra_forms()

    assert bot_module.is_command_like("налет соседа сегодня")


def test_пустая_фраза_в_список_не_годится():
    """Запись, распадающаяся в ноль слов, лежала бы в списке и молча ничего не
    ловила — худший вид настройки."""
    assert bot_module.normalize_cleanup_phrase("   ") == ()
    assert bot_module.normalize_cleanup_phrase("дом") == ("дом",)


def test_неприкосновенные_команды_перечислены_верно():
    """CLEANUP_KEEP_NAMES показывают админу в выводе «чк», а решает всё
    регулярка рядом. Разъедься они — «чк» начнёт врать про то, что чистится, а
    что нет."""
    невыполненные = [n for n in bot_module.CLEANUP_KEEP_NAMES
                     if not bot_module.is_cleanup_exempt(n)]
    assert not невыполненные, ("названы в «чк» как неприкосновенные, но чистятся: "
                               + ", ".join(невыполненные))


def test_вывод_чк_помещается_в_свёрнутую_цитату(пустой_список):
    """Секций четыре, а список персональных сроков растёт без предела —
    развёрнутым это заняло бы весь экран у всех в чате."""
    текст = bot_module._cleanup_status_text()
    assert "<blockquote expandable>" in текст and "</blockquote>" in текст
    # Про приоритет неприкосновенных сказано прямо: иначе «+чк перевод»
    # выглядит как молча не сработавшая настройка.
    assert "НЕ ЧИСТИТСЯ НИКОГДА" in текст
    # «&варн» экранирован — голый амперсанд Telegram примет за HTML-сущность.
    assert "&варн" not in текст and "&amp;варн" in текст


def test_аргумент_читается_и_с_тире_и_без():
    """«+чк — дом» пишут ровно так же часто, как «+чк дом», а фраза,
    записанная вместе с тире, не совпала бы уже ни с чем."""
    assert bot_module._cleanup_arg("+чк дом") == "дом"
    assert bot_module._cleanup_arg("+чк — дом") == "дом"
    assert bot_module._cleanup_arg("+чк - дом") == "дом"
    assert bot_module._cleanup_arg("-чк  —  дом купить") == "дом купить"
    assert bot_module._cleanup_arg("чк") == ""


@pytest.mark.parametrize("text,ожидание", [
    ("+чк -чат", "-чат"),
    ("+чк -правила", "-правила"),
    ("+чк -босс", "-босс"),
    ("-чк -мут", "-мут"),
])
def test_команда_с_дефисом_не_теряет_дефис(text, ожидание):
    """Худшая из возможных ошибок разбора аргумента.

    С дефиса начинается целое семейство настоящих команд. Срежь его заодно с
    тире-разделителем — и «+чк -чат» запишет в список голое слово «чат», а
    список сопоставляется по НАЧАЛУ сообщения: бот начнёт удалять любую живую
    фразу, начинающуюся словом «чат». Админ получил бы не «не сработало», а
    «сработало не то и хуже». Разделяет их пробел после дефиса.
    """
    assert bot_module._cleanup_arg(text) == ожидание


def test_свои_сроки_показаны_формой_а_не_первым_словом(пустой_список, monkeypatch):
    """«титул» вместо «титул купить» склеило бы четыре разные команды в одну
    строку — а весь смысл раздела в том, чтобы показать, что настроено."""
    monkeypatch.setitem(bot_module.command_cleanup_overrides, "title_buy", 1)
    текст = bot_module._cleanup_status_text()
    assert "титул купить" in текст


@pytest.mark.parametrize("text", ["чк", "+чк дом", "-чк дом"])
def test_сами_команды_чк_тоже_чистятся(text):
    """Команда о чистке, уезжающая мимо чистки, — отдельный сорт стыда."""
    assert bot_module.is_command_like(text), text


# ---------------------------------------------------------------------------
# Обработчики «+чк» / «-чк» целиком: важно не «что ответил бот», а обновился ли
# кэш. База и разбор могут быть правы по отдельности, а команда — молча не
# работать до перезапуска, потому что список в памяти остался старым.
# ---------------------------------------------------------------------------

class _ЗаписьВЧат:
    """Минимальное Message: текст, автор и собранные ответы."""

    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": -1001234567890, "type": "supergroup"})()
        self.from_user = type("U", (), {"id": 1, "is_bot": False})()
        self.reply_to_message = None
        self.ответы = []

    async def reply(self, text, **kwargs):
        self.ответы.append(text)


@pytest.fixture
def _чк(monkeypatch, пустой_список):
    """Подменяет таблицу списком в памяти — так же, как её видит бот."""
    хранилище: list[str] = []

    async def add(phrase, added_by=None):
        if phrase in хранилище:
            return False
        хранилище.append(phrase)
        return True

    async def remove(phrase):
        if phrase not in хранилище:
            return False
        хранилище.remove(phrase)
        return True

    async def listing():
        return sorted(хранилище)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module.db, "add_cleanup_extra_command", add, raising=False)
    monkeypatch.setattr(bot_module.db, "remove_cleanup_extra_command", remove, raising=False)
    monkeypatch.setattr(bot_module.db, "list_cleanup_extra_commands", listing, raising=False)
    monkeypatch.setattr(bot_module.db, "add_log", noop, raising=False)
    monkeypatch.setattr(bot_module, "has_level", lambda *a, **k: True)
    return хранилище


def test_плюс_чк_начинает_чистить_сразу(_чк):
    """Без перезапуска бота: кэш обновляется в том же обработчике."""
    assert not bot_module.is_command_like("дом у меня далеко")

    msg = _ЗаписьВЧат("+чк дом")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["дом"]
    assert bot_module.is_command_like("дом у меня далеко"), (
        "фраза записана в базу, но кэш в памяти не пересобран"
    )
    assert "✅" in msg.ответы[0]


def test_минус_чк_перестаёт_чистить_сразу(_чк):
    asyncio.run(bot_module.cmd_cleanup_add(_ЗаписьВЧат("+чк дом")))

    msg = _ЗаписьВЧат("-чк дом")
    asyncio.run(bot_module.cmd_cleanup_del(msg))

    assert _чк == []
    assert not bot_module.is_command_like("дом у меня далеко")
    assert "✅" in msg.ответы[0]


def test_повторное_добавление_честно_говорит_что_уже_есть(_чк):
    asyncio.run(bot_module.cmd_cleanup_add(_ЗаписьВЧат("+чк дом")))

    msg = _ЗаписьВЧат("+чк дом")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["дом"], "дубля в списке быть не должно"
    assert "уже в списке" in msg.ответы[0]


def test_удаление_несуществующего_не_врёт_про_успех(_чк):
    msg = _ЗаписьВЧат("-чк несуществующая")
    asyncio.run(bot_module.cmd_cleanup_del(msg))

    assert "не было" in msg.ответы[0]


def test_плюс_чк_без_аргумента_объясняет_как_пользоваться(_чк):
    msg = _ЗаписьВЧат("+чк")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == []
    assert "+чк" in msg.ответы[0]


def test_неприкосновенную_команду_в_чистку_не_пускают(_чк):
    """Проверка на неприкосновенность стоит в middleware РАНЬШЕ расчёта срока,
    поэтому «+чк перевод» не заработал бы никогда. Отказать вслух честнее, чем
    записать строку, которая ничего не делает."""
    msg = _ЗаписьВЧат("+чк перевод")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == []
    assert "не чистятся никогда" in msg.ответы[0]


# ---------------------------------------------------------------------------
# Сквозной прогон: сообщение проходит через middleware и оказывается в очереди
# ---------------------------------------------------------------------------

def _сообщение(text: str, chat_id: int):
    from datetime import datetime as _dt

    from aiogram.types import Chat, Message, User
    return Message(
        message_id=42,
        date=_dt.now(),
        chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=555, is_bot=False, first_name="Тестер"),
        text=text,
    )


def _прогнать_через_очистку(monkeypatch, text: str) -> list[tuple]:
    """Гоняет сообщение через CommandCleanupMiddleware и возвращает то, что
    уехало в очередь на удаление."""
    очередь: list[tuple] = []
    ЧАТ_ЖАЛОБ = -1009999999999

    async def add_cleanup_entry(chat_id, message_id, delete_at, root_message_id=None):
        очередь.append((chat_id, message_id))

    async def handler(event, data):
        return None

    monkeypatch.setattr(bot_module.db, "add_cleanup_entry", add_cleanup_entry, raising=False)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЧАТ_ЖАЛОБ)
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "15")

    mw = bot_module.CommandCleanupMiddleware()
    asyncio.run(mw(handler, _сообщение(text, ЧАТ_ЖАЛОБ), {}))
    return очередь


@pytest.mark.parametrize("text", ["дом", "дом купить cottage", "дом топ"])
def test_команды_rel2_доезжают_до_очереди_на_удаление(monkeypatch, пустой_список, text):
    """Та самая жалоба, с которой всё началось: «дом» висел в чате вечно.

    Проверка сквозная, а не по кусочкам: между «команда попала в список» и
    «строка появилась в очереди» стоит middleware, и ровно там всё ломалось —
    сообщения relationships_v2 до неё не доходили вовсе.
    """
    bot_module.cleanup_extra_phrases.append("дом")
    bot_module.rebuild_cleanup_extra_forms()

    assert _прогнать_через_очистку(monkeypatch, text), f"{text!r} не попало в очередь"


def test_чистится_только_то_что_в_списке(monkeypatch, пустой_список):
    """Главное правило: решает админ, а не бот.

    Раньше в очередь уезжала любая из 335 команд реестра плюс всё, что
    начинается со служебного знака. Теперь пустой список означает, что не
    убирается ничего, а полный — что убирается ровно перечисленное.
    """
    assert not _прогнать_через_очистку(monkeypatch, "баланс")
    assert not _прогнать_через_очистку(monkeypatch, "!ограбить")
    assert not _прогнать_через_очистку(monkeypatch, "дом топ")

    bot_module.cleanup_extra_phrases.append("баланс")
    bot_module.rebuild_cleanup_extra_forms()

    assert _прогнать_через_очистку(monkeypatch, "баланс")
    assert not _прогнать_через_очистку(monkeypatch, "!ограбить"), (
        "соседняя команда попала в очистку заодно"
    )


def test_живая_речь_в_очередь_не_едет(monkeypatch, пустой_список):
    bot_module.cleanup_extra_phrases.append("дом")
    bot_module.rebuild_cleanup_extra_forms()
    assert _прогнать_через_очистку(monkeypatch, "дом у меня далеко"), (
        "запись ловит по началу сообщения — это её объявленное поведение"
    )
    assert not _прогнать_через_очистку(monkeypatch, "погода сегодня хорошая")


def test_перевод_в_очередь_не_едет(monkeypatch, пустой_список):
    """Расписка о переводе обязана остаться в чате: спор о деньгах через час
    восстанавливать будет нечем.

    Проверяем с ЗАПОЛНЕННЫМ списком: пустой не доказывает ничего — при нём не
    чистится и так ничего. Неприкосновенность обязана пережить даже прямую
    попытку внести «перевод» в список.
    """
    bot_module.cleanup_extra_phrases.append("перевод")
    bot_module.rebuild_cleanup_extra_forms()
    assert not _прогнать_через_очистку(monkeypatch, "перевод 500 @kto")


def test_добавленное_через_чк_доезжает_до_очереди(monkeypatch, пустой_список):
    """Полный путь ручного списка: «+чк дом» → фраза в кэше → сообщение в
    очереди. Каждое звено по отдельности уже проверено, здесь — что они
    соединены."""
    assert not _прогнать_через_очистку(monkeypatch, "дом у меня далеко")

    bot_module.cleanup_extra_phrases.append("дом")
    bot_module.rebuild_cleanup_extra_forms()

    assert _прогнать_через_очистку(monkeypatch, "дом у меня далеко")


# ---------------------------------------------------------------------------
# «+чк» ответом: бот сам отделяет команду от аргументов
#
# Иначе «+чк» ответом на «.рулетка 400 красное» записал бы в список всю
# строку целиком — а список сравнивается с НАЧАЛОМ сообщения. Такая запись не
# совпала бы уже никогда, кроме случая, когда кто-то поставит ровно столько же
# и на тот же цвет. То есть настройка тихо не работала бы.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("сообщение,команда", [
    # аргументы отбрасываются
    (".рулетка 400 красное", ".рулетка"),
    ("рулетка 400 красное", "рулетка"),
    ("дом купить cottage", "дом купить"),
    ("отн пт карта 5", "отн пт карта"),
    # а вот у топов форма берётся ЦЕЛИКОМ: «топ стриков» и «топ монет» — разные
    # команды, и сократить их до «топ» значило бы чистить не ту.
    ("топ стриков", "топ стриков"),
    ("топ монет", "топ монет"),
    ("топ по стрику", "топ по стрику"),
    # многословная форма из реестра — тоже целиком
    ("!ограбить бинокль @kto", "!ограбить бинокль"),
    # первое слово приводится к написанию реестра, как и у входящих сообщений
    ("петы кормить kot", "пет кормить"),
])
def test_команда_отделяется_от_аргументов(сообщение, команда):
    assert bot_module.guess_command_form(сообщение) == команда


def test_команда_по_служебному_знаку_узнаётся_без_реестра():
    """«.рулетка», «!орёл», «+чат» бот считает командами по одному знаку в
    начале, и перечислять их в реестре никто не обязан. Такие команды всегда в
    одно слово — его и берём."""
    assert bot_module.guess_command_form("+чат") == "+чат"
    assert bot_module.guess_command_form(".кости 5 на удачу") == ".кости"


@pytest.mark.parametrize("текст", ["привет как дела", "просто текст", "", "   ", None])
def test_из_живой_речи_команда_не_выдумывается(текст):
    """Гадать нельзя: ошибка кладёт в список кусок живой речи, а список ловит
    по началу сообщения. Лучше честное «не понял»."""
    assert bot_module.guess_command_form(текст) is None


class _ЗаписьСОтветом(_ЗаписьВЧат):
    """Сообщение-команда, отправленное ответом на другое."""

    def __init__(self, text, на_что):
        super().__init__(text)
        self.reply_to_message = type("R", (), {"text": на_что, "caption": None})()


def test_плюс_чк_реплаем_кладёт_в_список_только_команду(_чк):
    """Тот самый сценарий из просьбы: человек отвечает «+чк» на живое
    сообщение со ставкой, а в список уходит одна команда."""
    msg = _ЗаписьСОтветом("+чк", ".рулетка 400 красное")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == [".рулетка"], "в список уехали аргументы"
    assert "аргументы отброшены" in msg.ответы[0], (
        "человек должен увидеть, что именно бот принял за команду"
    )


def test_плюс_чк_реплаем_на_топ_берёт_форму_целиком(_чк):
    msg = _ЗаписьСОтветом("+чк", "топ стриков")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["топ стриков"], "«топ стриков» сократили до «топ» — это другая команда"


def test_написанное_руками_сильнее_угаданного(_чк):
    """Человек, указавший команду явно, знает, чего хочет, лучше разбора."""
    msg = _ЗаписьСОтветом("+чк дом", ".рулетка 400 красное")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["дом"]


def test_реплай_на_обычный_текст_объясняет_а_не_гадает(_чк):
    msg = _ЗаписьСОтветом("+чк", "привет всем, как дела")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == [], "в список уехал кусок живой речи"
    assert "обычный текст" in msg.ответы[0]


def test_минус_чк_тоже_понимает_реплай(_чк):
    asyncio.run(bot_module.cmd_cleanup_add(_ЗаписьВЧат("+чк .рулетка")))

    msg = _ЗаписьСОтветом("-чк", ".рулетка 400 красное")
    asyncio.run(bot_module.cmd_cleanup_del(msg))

    assert _чк == []
    assert "✅" in msg.ответы[0]


def test_без_реплая_и_без_аргумента_подсказка_рассказывает_про_оба_способа(_чк):
    msg = _ЗаписьВЧат("+чк")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == []
    assert "ответом" in msg.ответы[0]
    assert ".рулетка" in msg.ответы[0], "пример нужен: без него способ не очевиден"


# ---------------------------------------------------------------------------
# Групповая запись «+чк рп»
#
# РП-действий 34, у каждого второго есть повелительная форма («обними» к
# «обнять»), плюс 21 себяшка — и всё это правится в панели. Поштучно такое в
# список не занесёшь, а занёсший «обнять» получал чистку ровно на «обнять»:
# «обними» оставалось в чате. Отсюда и жалоба «рп-команды не подчиняются чк».
# ---------------------------------------------------------------------------

@pytest.fixture
def группа_рп(пустой_список):
    """Список глобальный (см. пустой_список), поэтому включаем группу только
    на время теста — с восстановлением, как и всё остальное в этом файле."""
    bot_module.cleanup_extra_phrases[:] = [bot_module.CLEANUP_GROUP_RP]
    bot_module.rebuild_cleanup_extra_forms()
    return bot_module.cleanup_extra_phrases


@pytest.mark.parametrize("text", [
    "обнять",                 # цель — из ответа на сообщение
    "обнять @vasya",
    "обнять 12345",
    "обними",                 # повелительная форма: та самая, что не ловилась
    "обними его",
    "взять за руку @vasya",   # многословное действие
    "[пукнуть",               # себяшка
    "[пукнуть громко",        # хвост себяшки обработчик игнорирует и отвечает
])
def test_рп_команды_доезжают_до_очереди(monkeypatch, группа_рп, text):
    assert _прогнать_через_очистку(monkeypatch, text), f"{text!r} не попало в очередь"


@pytest.mark.parametrize("text", [
    "обнять снова тест",      # обработчик такое пропускает (SkipHandler)
    "обнять его сегодня",
    "привет, обними меня",
    "погода сегодня хорошая",
])
def test_живая_речь_под_группу_не_попадает(monkeypatch, группа_рп, text):
    """Правило группы: убирается то, на что бот ОТВЕТИЛ. Здесь он молчит —
    значит, это просто разговор, и трогать его нельзя.

    Тем и отличается от ручной записи: «+чк обнять» ловит по началу сообщения
    и «обнять снова тест» уберёт. Группа — уже нет, и это намеренно."""
    assert not _прогнать_через_очистку(monkeypatch, text)


def test_без_группы_рп_остаётся_в_чате(monkeypatch, пустой_список):
    """Обратная сторона: пока «рп» не добавили, ничего РП не чистится."""
    assert not _прогнать_через_очистку(monkeypatch, "обними @vasya")
    assert not _прогнать_через_очистку(monkeypatch, "[пукнуть")


def test_действие_добавленное_в_панели_под_группу_попадает(monkeypatch, группа_рп):
    """Ради этого группа и проверяется условием обработчика, а не словами из
    списка: новое действие из панели должно чиститься само, без похода в «чк»."""
    assert not _прогнать_через_очистку(monkeypatch, "боднуть @vasya"), "такого действия ещё нет"

    async def list_rp_actions(active_only=True):
        return {**bot_module.RP_ACTIONS, "боднуть": ["{actor} бодает {target}"]}

    async def list_rp_action_synonyms():
        return {**bot_module.RP_ACTION_SYNONYMS, "боднй": "боднуть"}

    monkeypatch.setattr(bot_module.db, "list_rp_actions", list_rp_actions, raising=False)
    monkeypatch.setattr(bot_module.db, "list_rp_action_synonyms", list_rp_action_synonyms,
                        raising=False)
    было = dict(bot_module.RP_ACTIONS), dict(bot_module.RP_ACTION_SYNONYMS)
    try:
        asyncio.run(bot_module.refresh_rp_caches())
        assert _прогнать_через_очистку(monkeypatch, "боднуть @vasya")
    finally:
        # RP_ACTIONS живут в модуле — monkeypatch их не откатит.
        bot_module.RP_ACTIONS.clear(); bot_module.RP_ACTIONS.update(было[0])
        bot_module.RP_ACTION_SYNONYMS.clear(); bot_module.RP_ACTION_SYNONYMS.update(было[1])
        asyncio.run(bot_module.refresh_rp_caches())


def test_подпись_к_фото_под_группу_не_попадает(monkeypatch, группа_рп):
    """Обработчики РП стоят на F.text: на фото с подписью «обнять» бот не
    отвечает ничем. Удалить за ним чужую картинку — это уже не чистка команд,
    а удаление сообщений участников."""
    from datetime import datetime as _dt

    from aiogram.types import Chat, Message, User

    очередь: list[tuple] = []
    ЧАТ_ЖАЛОБ = -1009999999999

    async def add_cleanup_entry(chat_id, message_id, delete_at, root_message_id=None):
        очередь.append((chat_id, message_id))

    async def handler(event, data):
        return None

    monkeypatch.setattr(bot_module.db, "add_cleanup_entry", add_cleanup_entry, raising=False)
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", ЧАТ_ЖАЛОБ)
    monkeypatch.setitem(bot_module.settings, "command_cleanup_minutes", "15")

    фото = Message(
        message_id=43, date=_dt.now(), chat=Chat(id=ЧАТ_ЖАЛОБ, type="supergroup"),
        from_user=User(id=555, is_bot=False, first_name="Тестер"), caption="обнять",
    )
    asyncio.run(bot_module.CommandCleanupMiddleware()(handler, фото, {}))

    assert очередь == []


def test_плюс_чк_рп_объясняет_что_это_группа(_чк):
    msg = _ЗаписьВЧат("+чк рп")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["рп"]
    ответ = msg.ответы[0]
    assert "группа" in ответ.casefold(), "иначе выглядит как обычная запись из одного слова"
    assert "себяшки" in ответ.casefold()


def test_плюс_чк_на_одиночное_действие_подсказывает_про_группу(_чк):
    """Добавивший «обнять» должен узнать про «обними» сразу, а не через неделю
    по неубранным сообщениям."""
    msg = _ЗаписьВЧат("+чк обнять")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["обнять"]
    assert "+чк рп" in msg.ответы[0]


def test_плюс_чк_реплаем_на_рп_понимает_действие(_чк):
    """Раньше «+чк» ответом на РП-сообщение отвечал «не похоже на команду» —
    при том что бот на это сообщение как раз ответил."""
    msg = _ЗаписьСОтветом("+чк", "обними @vasya")
    asyncio.run(bot_module.cmd_cleanup_add(msg))

    assert _чк == ["обними"], "форма берётся та, что написана в чате"


def test_чк_рассказывает_про_группу_в_списке(группа_рп):
    текст = bot_module._cleanup_status_text()
    assert "ГРУППА" in текст, "строка «рп» в списке выглядит как обычная запись"


def test_минус_чк_рп_выключает_группу(_чк):
    """Флаг группы живёт в модуле, и если его не сбросить при удалении записи,
    чистка продолжит убирать РП уже после «-чк рп». Невыключаемая чистка хуже
    той, ради которой всё затевалось."""
    asyncio.run(bot_module.cmd_cleanup_add(_ЗаписьВЧат("+чк рп")))
    assert bot_module.matches_cleanup_rp_group("обними @vasya")

    asyncio.run(bot_module.cmd_cleanup_del(_ЗаписьВЧат("-чк рп")))

    assert _чк == []
    assert not bot_module.matches_cleanup_rp_group("обними @vasya")
    assert not bot_module.matches_cleanup_rp_group("[пукнуть")
