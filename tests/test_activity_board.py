"""Панель «чем заняться»: что готово сейчас, что ждёт, что недоступно.

Панель существует ради одной вещи — избавить человека от слепого перебора
команд, каждая из которых отвечает «рано». Значит и ломается она двумя
способами: обещает «готово» там, где команда откажет, и валит «ещё не время»
в одну кучу с «тебе нельзя». Тесты закрывают оба.

Отрисовка чистая (activities.py не ходит в базу), поэтому раскладка
проверяется целиком без заглушек.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta

import pytest

import activities

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import robbery  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555

# Ключ из настоящего каталога, а не выдуманный: проверка «профессия есть»
# написана как «prof_key in PROFESSIONS», и на синтетическом ключе тест
# доказывал бы меньше, чем кажется — реальные ключи русские («повар»), и
# латинская заглушка прошла бы мимо боевого пути.
_РЕАЛЬНАЯ_ПРОФЕССИЯ = next(iter(bot_module.PROFESSIONS))


def _состояние(key, **kw):
    return activities.ActivityState(activities.BY_KEY[key], **kw)


def _панель(states, frozen_note=None):
    return activities.render_panel(
        states, divider="---", format_left=bot_module.format_duration_ru,
        frozen_note=frozen_note,
    )


# --- отрисовка --------------------------------------------------------------

def test_готовые_собраны_в_одну_строку():
    """Слово «готово» уже сказано заголовком секции; десять отдельных строк
    заняли бы пол-экрана ради нуля новой информации."""
    текст = _панель([_состояние("daily_bonus"), _состояние("fishing"),
                     _состояние("farm")])

    строка = [s for s in текст.splitlines() if "Готово" in s]
    assert len(строка) == 1
    assert "бонус" in строка[0] and "рыбалка" in строка[0] and "ферма" in строка[0]
    assert "(3)" in строка[0], "число готовых показывается сразу"


def test_команды_обёрнуты_в_code():
    """В Telegram <code> копируется тапом — ради этого готовые и печатаются
    именно командой, а не названием."""
    текст = _панель([_состояние("profession")])
    assert "<code>!работа</code>" in текст


def test_ждущие_идут_по_возрастанию_срока():
    """Панель открывают, чтобы понять, чего дождаться ближайшим."""
    текст = _панель([
        _состояние("treasure", left=timedelta(hours=5)),
        _состояние("robbery", left=timedelta(minutes=12)),
        _состояние("side_job", left=timedelta(hours=1)),
    ])
    строки = [s for s in текст.splitlines() if "—" in s]
    assert строки[0].startswith("🥷"), строки
    assert строки[1].startswith("💼"), строки
    assert строки[2].startswith("⛏"), строки


def test_занятие_без_срока_уходит_в_конец_ожидания():
    """У копилки бизнеса «через сколько» нет вовсе, сравнивать её со временем
    нечем — но и выкидывать нельзя: человек ждёт именно её."""
    текст = _панель([
        _состояние("business", wait_note="копится"),
        _состояние("robbery", left=timedelta(minutes=12)),
    ])
    строки = [s for s in текст.splitlines() if "—" in s]
    assert строки[-1].startswith("🏢")
    assert "копится" in строки[-1]
    assert "0 секунд" not in текст, "поддельный срок — враньё, у копилки его нет"


def test_пустая_секция_не_печатается():
    """Заголовок «Ждём:» без единой строки под ним читается как поломка."""
    текст = _панель([_состояние("daily_bonus")])
    assert "Ждём" not in текст
    assert "Недоступно" not in текст
    assert "Готово" in текст


def test_недоступное_всегда_с_причиной_и_способом_починить():
    """Строка «нельзя» без «что делать» — тот самый тупик, ради ухода от
    которого панель и заводилась."""
    текст = _панель([_состояние("profession", blocked="нет профессии, устроиться: "
                                                      "<code>!работа устроиться</code>")])
    assert "Недоступно" in текст
    assert "нет профессии" in текст
    assert "устроиться" in текст


def test_недоступное_не_считается_готовым():
    """Иначе панель зовёт человека делать то, что ему сейчас запрещено."""
    состояние = _состояние("robbery", blocked="под надзором")
    assert not состояние.ready
    текст = _панель([состояние])
    assert "Готово" not in текст


def test_заморозка_сказана_один_раз_в_шапке():
    """Одна и та же причина, повторённая десять раз подряд, — не информация."""
    текст = _панель([_состояние("daily_bonus"), _состояние("fishing")],
                    frozen_note="🧊 Счёт заморожен администрацией.")
    assert текст.count("заморожен") == 1


def test_каталог_и_индекс_не_разъезжаются():
    """BY_KEY строится из CATALOG — расхождение означало бы занятие, которое
    собирается, но не показывается."""
    assert set(activities.BY_KEY) == {a.key for a in activities.CATALOG}
    assert len(activities.BY_KEY) == len(activities.CATALOG), "дубль ключа"


# --- сбор состояний ---------------------------------------------------------

def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


@pytest.fixture
def мир(monkeypatch):
    """Всё готово, ничего не мешает — дальше каждый тест ломает одну вещь."""
    заглушки = {
        "get_earning_activity": _returns(None),
        "get_fishing_stats": _returns({}),
        "get_digger": _returns({}),
        "get_wallet": _returns({}),
        "get_profession_stats": _returns({"profession_key": _РЕАЛЬНАЯ_ПРОФЕССИЯ,
                                          "last_work_at": None}),
        "get_robbery_stats": _returns({}),
        "is_under_surveillance": _returns(False),
    }
    for имя, fn in заглушки.items():
        monkeypatch.setattr(bot_module.db, имя, fn, raising=False)
    monkeypatch.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    monkeypatch.setattr(bot_module, "_item_perk", _returns(0), raising=False)
    monkeypatch.setattr(bot_module, "_load_businesses", _returns([]), raising=False)
    # Заработок домножается на настройку чата, а подработка ещё и считается
    # за сутки — обе ручки проверяются своими тестами, здесь они «как было».
    monkeypatch.setattr(bot_module.db, "get_income_percent", _returns(100.0), raising=False)
    monkeypatch.setattr(bot_module.db, "get_side_job_daily_limit", _returns(0), raising=False)
    monkeypatch.setattr(bot_module.db, "count_activity_today", _returns(0), raising=False)
    monkeypatch.setattr(bot_module.db, "bump_activity_today", _returns(None), raising=False)
    monkeypatch.setattr(bot_module.db, "touch_earning_activity", _returns(None), raising=False)
    return monkeypatch


def _собрать():
    return asyncio.run(bot_module.collect_activity_states(CHAT_ID, USER_ID))


def _по_ключу(states):
    return {s.activity.key: s for s in states}


def test_новичок_видит_всё_готовым(мир):
    """Ни одной записи в базе — значит ничего не начиналось, ждать нечего."""
    states, frozen = _собрать()
    по = _по_ключу(states)

    assert frozen is None
    assert по["daily_bonus"].ready and по["fishing"].ready and по["farm"].ready
    assert по["robbery"].ready and по["side_job"].ready


def test_забранный_сегодня_бонус_ждёт_до_полуночи_а_не_сутки(мир):
    """Бонус устроен по ДАТЕ (last_day == сегодня). Отсчёт 24 часов от момента
    получения показал бы срок, которого на самом деле нет: забравший бонус
    в 23:50 ждёт десять минут, а не сутки."""
    мир.setattr(bot_module.db, "get_earning_activity",
                _returns({"last_day": bot_module.utc_today(), "last_at": datetime.utcnow()}),
                raising=False)

    бонус = _по_ключу(_собрать()[0])["daily_bonus"]

    assert not бонус.ready
    assert бонус.left <= timedelta(days=1)
    полночь = datetime.combine(bot_module.utc_today() + timedelta(days=1),
                               datetime.min.time())
    assert abs((datetime.utcnow() + бонус.left) - полночь) < timedelta(seconds=5)


def test_вчерашний_бонус_снова_готов(мир):
    мир.setattr(bot_module.db, "get_earning_activity",
                _returns({"last_day": bot_module.utc_today() - timedelta(days=1)}),
                raising=False)

    assert _по_ключу(_собрать()[0])["daily_bonus"].ready


def test_заморозка_объясняется_один_раз(мир):
    мир.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)

    _states, frozen = _собрать()

    assert frozen and "заморожен" in frozen


def test_надзор_закрывает_и_ограбление_и_налёт(мир):
    """Оба запрета — от одной причины, и в ней оба выхода: платный и по сроку."""
    мир.setattr(bot_module.db, "is_under_surveillance", _returns(True), raising=False)
    мир.setattr(bot_module, "_surveillance_left",
                _returns(timedelta(days=3)), raising=False)

    по = _по_ключу(_собрать()[0])

    for ключ in ("robbery", "raid"):
        assert по[ключ].blocked, ключ
        assert "откуп" in по[ключ].blocked, ключ
        assert "подождать" in по[ключ].blocked, ключ
        assert str(robbery.SURVEILLANCE_PARDON_PRICE) in по[ключ].blocked, ключ


def test_без_профессии_это_нельзя_а_не_готово(мир):
    """Команда существует, но человеку недоступна. Показать её готовой значило
    бы позвать делать то, что не получится."""
    мир.setattr(bot_module.db, "get_profession_stats", _returns({}), raising=False)

    работа = _по_ключу(_собрать()[0])["profession"]

    assert работа.blocked and "устроиться" in работа.blocked
    assert not работа.ready


def test_кулдаун_работы_показан_если_профессия_есть(мир):
    мир.setattr(bot_module.db, "get_profession_stats",
                _returns({"profession_key": _РЕАЛЬНАЯ_ПРОФЕССИЯ,
                          "last_work_at": datetime.utcnow() - timedelta(minutes=5)}),
                raising=False)

    работа = _по_ключу(_собрать()[0])["profession"]

    assert not работа.ready and работа.blocked is None
    assert работа.left <= bot_module.PROFESSION_WORK_COOLDOWN


def test_трактор_укорачивает_ожидание_фермы(мир):
    """Перк считается тем же способом, что и в самой команде фермы, — иначе
    панель обещает одно, а бот пускает по другому."""
    мир.setattr(bot_module.db, "get_wallet",
                _returns({"last_farm_at": datetime.utcnow()
                          - bot_module.FARM_COOLDOWN * 0.7}), raising=False)

    без_перка = _по_ключу(_собрать()[0])["farm"]
    assert not без_перка.ready

    мир.setattr(bot_module, "_item_perk", _returns(50), raising=False)
    с_перком = _по_ключу(_собрать()[0])["farm"]
    assert с_перком.ready, "с укороченным кулдауном ферма уже готова"


def test_без_бизнеса_строки_про_сбор_нет_в_готовых(мир):
    """Звать собирать доход с несуществующего бизнеса — худший вид подсказки."""
    бизнес = _по_ключу(_собрать()[0])["business"]

    assert бизнес.blocked and "нет бизнеса" in бизнес.blocked


def test_копилка_с_деньгами_готова_а_пустая_копится(мир):
    мир.setattr(bot_module, "_load_businesses", _returns([{"business_key": "x"}]),
                raising=False)
    мир.setattr(bot_module, "_business_pending", lambda row: 0, raising=False)
    assert _по_ключу(_собрать()[0])["business"].wait_note == "копится"

    мир.setattr(bot_module, "_business_pending", lambda row: 500, raising=False)
    assert _по_ключу(_собрать()[0])["business"].ready


def test_собираются_все_занятия_каталога(мир):
    """Забытое занятие — молчаливая дыра: панель выглядит полной, а команду не
    показывает."""
    states, _ = _собрать()
    assert {s.activity.key for s in states} == set(activities.BY_KEY)


# --- команда ---------------------------------------------------------------

@pytest.mark.parametrize("текст", ["чем заняться", "Чем Заняться", "что делать", "!дела"])
def test_все_формы_команды_опознаются(текст):
    assert bot_module.resolve_command_key(текст) == "activity_board"
    assert bot_module.is_command_like(текст)


@pytest.mark.parametrize("текст", [
    "что делать теперь",
    "чем заняться вечером",
    "не знаю что делать с этим",
])
def test_живая_речь_панель_не_зовёт(текст):
    """Формы намеренно полные: открытая сделала бы командой любую фразу,
    начинающуюся словами «что делать»."""
    assert bot_module.resolve_command_key(текст) != "activity_board"


# ---------------------------------------------------------------------------
# Подсказка под отказом: «нельзя — зато вот что можно»
#
# Отказ без следующего шага — тупик: «слишком рано», и человек снова гадает,
# что попробовать. Подсказка отвечает на этот вопрос там же, где он возник.
# ---------------------------------------------------------------------------

def _подсказка(states, exclude=None, **kw):
    return activities.render_hint(
        states, exclude=exclude, format_left=bot_module.format_duration_ru, **kw
    )


def test_подсказка_перечисляет_готовое():
    текст = _подсказка([
        _состояние("robbery", left=timedelta(hours=1)),
        _состояние("daily_bonus"),
        _состояние("fishing"),
    ])
    assert "<code>бонус</code>" in текст and "<code>рыбалка</code>" in текст


def test_подсказка_не_предлагает_то_что_только_что_отказали():
    """Ответить на «слишком рано» предложением сделать ровно это же —
    издевательство."""
    текст = _подсказка([_состояние("fishing"), _состояние("daily_bonus")],
                       exclude="fishing")
    assert "рыбалка" not in текст
    assert "бонус" in текст


def test_подсказка_не_растёт_длиннее_самого_отказа():
    """Она приписывается к чужому сообщению: перерастя его, совет утопит в
    себе то, к чему был приписан."""
    текст = _подсказка([_состояние(k) for k in
                        ("daily_bonus", "side_job", "fishing", "treasure",
                         "farm", "hat")], max_items=4)
    assert текст.count("<code>") == 4
    assert "и ещё 2" in текст


def test_когда_ничего_не_готово_показывает_ближайшее():
    """Это и есть ответ на вопрос, ради которого человек долбится в команду:
    не «нельзя», а «через сколько станет можно»."""
    текст = _подсказка([
        _состояние("fishing", left=timedelta(hours=3)),
        _состояние("daily_bonus", left=timedelta(minutes=4)),
    ])
    assert "Ближайшее" in текст
    assert "<code>бонус</code>" in текст


def test_ближайшее_не_считает_недоступное():
    """У заблокированного нет срока вовсе — предлагать «подождать» нечего."""
    текст = _подсказка([
        _состояние("profession", blocked="нет профессии"),
        _состояние("fishing", left=timedelta(minutes=5)),
    ])
    assert "работа" not in текст
    assert "рыбалка" in текст


def test_сказать_нечего_значит_молчим():
    """Пустая строка, а не «увы, ничего»: приписка ради приписки — шум."""
    assert _подсказка([_состояние("fishing")], exclude="fishing") == ""
    assert _подсказка([_состояние("profession", blocked="нет профессии")]) == ""


# --- сборщик подсказки в боте ----------------------------------------------

@pytest.fixture
def _без_истории(monkeypatch):
    """Подсказку показывают не чаще раза в 10 минут — соседние тесты не должны
    затыкать друг друга через общий словарь."""
    bot_module._activity_hint_shown.clear()
    yield
    bot_module._activity_hint_shown.clear()


def test_подсказка_приходит_с_переводом_строки(мир, _без_истории):
    """Вызывающий код просто приклеивает её к своему тексту."""
    текст = asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID, "fishing"))
    assert текст.startswith("\n🎯")


def test_повтор_подсказки_придержан(мир, _без_истории):
    """Совет, повторённый под каждым вторым сообщением, перестаёт читаться и
    превращается в обои — а с ним перестаёт читаться и сам отказ."""
    первый = asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID, "fishing"))
    второй = asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID, "treasure"))

    assert первый and второй == ""


def test_придержана_подсказка_а_не_сам_отказ(мир, _без_истории):
    """Молчание подсказки не должно ничего ломать: она приписка, а не ответ."""
    asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID))
    assert asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID)) == ""


def test_замороженному_счёту_предлагать_нечего(мир, _без_истории):
    мир.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    assert asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID)) == ""


def test_сбой_сборки_не_роняет_отказ(мир, _без_истории):
    """Уронить отказ из-за украшения к нему значило бы променять понятное
    «слишком рано» на молчание бота."""
    async def взрыв(*a, **k):
        raise RuntimeError("база отвалилась")

    мир.setattr(bot_module.db, "get_fishing_stats", взрыв, raising=False)

    assert asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID)) == ""


def test_молчание_не_тратит_окно_показа(мир, _без_истории):
    """Если сказать было нечего, следующий отказ обязан попробовать снова —
    иначе одно неудачное совпадение затыкает подсказку на десять минут."""
    мир.setattr(bot_module, "is_account_frozen", _returns(True), raising=False)
    assert asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID)) == ""

    мир.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)
    assert asyncio.run(bot_module.activity_hint(CHAT_ID, USER_ID)).startswith("\n")


# ---------------------------------------------------------------------------
# Отказы на самом деле несут подсказку
#
# Всё выше проверяет подсказку отдельно от отказа. Между ними — приклеивание в
# одиннадцати местах, и именно оно может отвалиться молча: сбор состояний
# гасит исключения, поэтому пропавшая подсказка выглядит как обычный отказ.
# ---------------------------------------------------------------------------

def test_отказ_рыбалки_несёт_подсказку(мир, _без_истории):
    мир.setattr(bot_module.db, "get_fishing_stats",
                _returns({"last_fish_at": datetime.utcnow()}), raising=False)
    мир.setattr(bot_module, "is_account_frozen", _returns(False), raising=False)

    текст = asyncio.run(bot_module._fishing_execute(CHAT_ID, USER_ID))

    assert "Клёва не будет" in текст, текст
    assert "🎯" in текст, "отказ снова стал тупиком"
    assert "<code>рыбалка</code>" not in текст, (
        "предлагать в ответ на «слишком рано» то же самое — издевательство"
    )


def test_отказ_подработки_несёт_подсказку(мир, _без_истории):
    мир.setattr(bot_module.db, "get_earning_activity",
                _returns({"last_at": datetime.utcnow()}), raising=False)

    текст = asyncio.run(bot_module._side_job_execute(CHAT_ID, USER_ID))

    assert "не отдышались" in текст and "🎯" in текст


def test_отказ_напарника_не_показывает_его_кулдауны(мир, _без_истории):
    """«работа вместе»: этот текст читает не владелец, а тот, кто позвал.
    Подсказка выдала бы ему чужие занятия — то самое, ради чего панель сделана
    личной (чужую смотрят платным «досье»)."""
    мир.setattr(bot_module.db, "get_profession_stats",
                _returns({"profession_key": _РЕАЛЬНАЯ_ПРОФЕССИЯ,
                          "last_work_at": datetime.utcnow()}), raising=False)
    # «Собственный офис» даёт внеочередную смену — без заглушки отказа не будет.
    мир.setattr(bot_module.db, "has_profession_upgrade", _returns(False), raising=False)

    свой = asyncio.run(bot_module._profession_execute_work(CHAT_ID, USER_ID))
    bot_module._activity_hint_shown.clear()
    чужой = asyncio.run(
        bot_module._profession_execute_work(CHAT_ID, USER_ID, with_hint=False))

    assert "🎯" in свой
    assert "🎯" not in чужой
    assert "НЕЗАЧЁТ" in чужой, "сам отказ обязан остаться на месте"


def test_каждый_exclude_ведёт_к_настоящему_занятию():
    """Опечатка в ключе не падает, а тихо перестаёт исключать — и бот отвечает
    на «слишком рано» предложением сделать ровно это же."""
    import re
    источник = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot.py"),
        encoding="utf-8",
    ).read()
    ключи = re.findall(r'activity_hint\([^)]*?"([a-zA-Z_]+)"', источник)
    assert ключи, "вызовы с exclude пропали — проверять стало нечего"
    чужие = [k for k in ключи if k not in activities.BY_KEY]
    assert not чужие, "exclude ведёт в никуда: " + ", ".join(чужие)
