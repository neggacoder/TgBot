"""Рубильник заработка: в админ-панели выключается источник, и его команда
перестаёт отвечать СОВСЕМ.

Главное требование — тишина. Не «⛔ команда выключена», не реакция, вообще
ничего: выключенный источник должен выглядеть так, будто такой команды у бота
нет. Поэтому заслон стоит middleware'ом, до обработчика: любой ответ, который
обработчик успел бы отправить, — уже нарушение.

Второе требование — не задеть соседей. «биржа цена 50» и «биржа настройки» —
не заработок, а админские настройки: выключив биржу, админ не должен потерять
возможность ею управлять.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _сообщение(text: str) -> Message:
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Игрок"),
        text=text,
    )


@pytest.fixture
def _рубильник(monkeypatch):
    """Кэш выключенных источников — глобальный, соседние тесты обязаны видеть
    его чистым."""
    было = set(bot_module.earnings_off)
    bot_module.earnings_off.clear()
    yield bot_module.earnings_off
    bot_module.earnings_off.clear()
    bot_module.earnings_off.update(было)


async def _прогнать(text: str, chat_id: int = CHAT_ID) -> list:
    """Гоняет сообщение через заслон и возвращает список «обработчик позвали»."""
    дошло = []

    async def handler(event, data):
        дошло.append(event.text)
        return "результат"

    сообщение = _сообщение(text)
    if chat_id != CHAT_ID:
        object.__setattr__(сообщение, "chat", Chat(id=chat_id, type="supergroup"))
    await bot_module.EarningsSwitchMiddleware()(handler, сообщение, {})
    return дошло


ДРУГОЙ_ЧАТ = -1009999999999


def test_рубильник_действует_в_игровом_чате(_рубильник, monkeypatch):
    """Рубильник — про игровой чат (тот, что задан «жалобы сюда»): в нём
    экономика и живёт."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    _рубильник.add("dice")
    assert asyncio.run(_прогнать("!кости 5 4", CHAT_ID)) == []


def test_в_чужом_чате_рубильник_молчит(_рубильник, monkeypatch):
    """В другой группе бот продолжает работать как раньше — админ выключал
    заработок у себя, а не у всех, куда бота позвали."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    _рубильник.add("dice")
    assert asyncio.run(_прогнать("!кости 5 4", ДРУГОЙ_ЧАТ)) == ["!кости 5 4"]


def test_без_настроенного_чата_рубильник_гасит_везде(_рубильник, monkeypatch):
    """Иначе выключатель молча не делает ничего — худший вид настройки."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", None)
    _рубильник.add("dice")
    assert asyncio.run(_прогнать("!кости 5 4", ДРУГОЙ_ЧАТ)) == []


# --- тишина -----------------------------------------------------------------

def test_выключенные_кости_молчат(_рубильник):
    """Тот самый сценарий из задачи: «!кости 5 4» не отвечает НИЧЕГО."""
    _рубильник.add("dice")
    assert asyncio.run(_прогнать("!кости 5 4")) == [], "обработчик всё-таки позвали"


def test_включённые_кости_работают_как_раньше(_рубильник):
    assert asyncio.run(_прогнать("!кости 5 4")) == ["!кости 5 4"]


def test_заслон_не_отвечает_ни_словом(_рубильник):
    """Если бы заслон писал «выключено», это была бы не тишина. Проверяем, что
    он вообще не трогает Telegram: любой ответ здесь — упавший тест."""
    _рубильник.add("dice")
    сообщение = _сообщение("!кости 5 4")

    async def нельзя(*args, **kwargs):
        raise AssertionError("заслон ответил в чат")

    object.__setattr__(сообщение, "reply", нельзя)
    object.__setattr__(сообщение, "answer", нельзя)

    async def handler(event, data):
        raise AssertionError("обработчик не должен был запуститься")

    asyncio.run(bot_module.EarningsSwitchMiddleware()(handler, сообщение, {}))


# --- какие формы команд узнаются -------------------------------------------

_ФОРМЫ = [
    ("farm", "ферма"), ("farm", "фарма"), ("farm", "фармить"), ("farm", "!бизнес"),
    ("garden", "огород"), ("garden", "грядки"), ("garden", "ферма посадить tykva"),
    ("garden", "ферма собрать"), ("garden", "собрать урожай"),
    ("garden", "ферма расширить"), ("garden", "культуры"), ("garden", "ферма помочь @a"),
    ("barn", "хлев"), ("barn", "скот"), ("barn", "ферма скот"),
    ("barn", "ферма купить korova"), ("barn", "ферма продать korova"),
    ("work", "!работа"), ("work", "!работать"), ("work", "!работа вместе @vasya"),
    ("work", "!работа заказ"),
    ("side_job", "подработка"), ("side_job", "халтура"), ("side_job", "шабашка"),
    ("hat", "шапка"), ("hat", "шапка по кругу"), ("hat", "скинемся"),
    ("business", "бизнес"), ("business", "бизнесы"), ("business", "бизнес собрать"),
    ("business", "бизнес купить kiosk"), ("business", "бизнес улучшить kiosk"),
    ("business", "бизнес продать kiosk"), ("business", "бизнес починить kiosk"),
    # «забрать» — синоним «собрать», которого нет во фразе реестра
    ("business", "бизнес забрать"), ("business", "бизнес забрать kiosk"),
    ("raid", "налёт"), ("raid", "налет"), ("raid", "бизнес налёт"),
    ("fishing", "рыбалка"), ("fishing", "рыбачить"), ("fishing", "удочка"),
    ("fishing", "сетка"), ("fishing", "сетка продать 1"),
    ("treasure", "клад"), ("treasure", "копать"), ("treasure", "искать клад"),
    # Самая частая форма — с целью и без бинокля: у реестра она закрытая, и
    # именно её рубильник пропускал.
    ("robbery", "!ограбить"), ("robbery", "!ограбить бинокль @vasya"),
    ("robbery", "!ограбить @vasya"), ("robbery", "ограбить @vasya"),
    ("stock", "биржа"), ("stock", "биржа купить 100"), ("stock", "биржа продать 5"),
    ("stock", "биржа дивиденды"), ("stock", "!биржа купить 10"),
    ("market", "рынок"), ("market", "рынок купить key 2"),
    ("market", "рынок заявка key 500 Ботинки"),
    ("boss", "босс"), ("boss", "боссы"),
    ("lootbox", "!лутбокс"), ("lootbox", "!лутбокс купить rare"),
    ("lootbox", "!лутбокс открыть rare 2"),
    ("dice", "!кости 5 4"), ("dice", "!кости 100 1"),
    ("coin", "!орёл 50"), ("coin", "!решка 50"), ("coin", "!орел 50"),
    ("roulette", "рулетка"), ("roulette", "рулетка 100 красное"),
    ("poker", "!покер 50"), ("poker", "покер 50"),
    ("racing", "!гонки 100"), ("racing", "гонки 100"),
]


@pytest.mark.parametrize("источник,текст", _ФОРМЫ)
def test_все_формы_команды_попадают_под_рубильник(_рубильник, источник, текст):
    """Пропущенная форма — дыра в рубильнике: админ выключил, а команда живёт."""
    _рубильник.add(источник)
    assert asyncio.run(_прогнать(текст)) == [], текст


@pytest.mark.parametrize("источник,текст", _ФОРМЫ)
def test_чужой_рубильник_команду_не_трогает(_рубильник, источник, текст):
    """Выключаем всё, кроме самого источника и зонтиков над ним (зонтик гасит
    подопечных по определению — см. EarningSource.covers)."""
    for другой in bot_module.EARNING_SOURCES:
        if другой.key != источник and источник not in другой.covers:
            _рубильник.add(другой.key)
    assert asyncio.run(_прогнать(текст)) == [текст], текст


# --- что выключать нельзя ---------------------------------------------------

@pytest.mark.parametrize("текст", [
    # админское управление источником
    "биржа цена 50", "биржа настройки рост 5", "биржа вкл",
    "рынок заявки", "рынок комиссия 5", "рынок режим ручной",
    "+босс", "-босс", "босс призвать Дракон",
    "ферма урожайность 10",
    # справочное: рейтинги и статистика — не заработок
    "!работа профиль", "!работа топ", "топ уловов", "топ грабителей",
    "стата ограблений", "клад инфа", "топ монет",
    # соседние модули, которых рубильник не касается вовсе
    # «!казино баланс» здесь БОЛЬШЕ НЕТ: кошелёк казино гасится вместе с
    # казино (см. зонтик), иначе выключенное казино продолжает отвечать.
    "монеты", "инвентарь", "лавка", "!банк", "бонус",
])
def test_соседние_команды_не_задеты(_рубильник, текст):
    """Выключив источник, админ обязан сохранить управление им, а «топ уловов» —
    это рейтинг, а не рыбалка."""
    for источник in bot_module.EARNING_SOURCES:
        _рубильник.add(источник.key)
    assert asyncio.run(_прогнать(текст)) == [текст], текст


# --- таймеры ----------------------------------------------------------------

def test_таймер_не_выполняет_выключенную_ферму(_рубильник, monkeypatch):
    """Таймер умеет ВЫПОЛНЯТЬ «ферма» в обход обработчиков — иначе рубильник
    обходится одной строчкой «таймер ферма».

    Чат передаём явно: у таймера он свой, и в чужом чате гасить нечего.
    """
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    assert bot_module._timer_runnable_command("ферма", CHAT_ID) is not None

    _рубильник.add("farm")
    assert bot_module._timer_runnable_command("ферма", CHAT_ID) is None
    assert bot_module._timer_runnable_command("ферма", ДРУГОЙ_ЧАТ) is not None


# --- панель -----------------------------------------------------------------

def test_кнопка_есть_в_главном_меню():
    тексты = [b.text for row in bot_module.main_menu_kb().keyboard for b in row]
    assert any(bot_module.LBL_EARNINGS in t for t in тексты), тексты


def test_клавиатура_показывает_состояние_каждого_источника(_рубильник):
    _рубильник.add("dice")
    тексты = [b.text for row in bot_module.earnings_menu_kb().keyboard for b in row]
    for источник in bot_module.EARNING_SOURCES:
        assert any(источник.label in t for t in тексты), источник.key
    выключенные = [t for t in тексты if bot_module.EARNINGS_OFF_MARK in t]
    assert len(выключенные) == 1, тексты


def test_переключатель_пишет_в_базу_и_в_кэш(_рубильник, monkeypatch):
    записано = {}

    async def set_data(key, value, updated_by=None):
        записано[key] = value

    async def delete_data(key):
        записано.pop(key, None)
        return True

    monkeypatch.setattr(bot_module.db, "set_data", set_data)
    monkeypatch.setattr(bot_module.db, "delete_data", delete_data)
    monkeypatch.setattr(bot_module.db, "add_log", _асинк_ничего)

    asyncio.run(bot_module.set_earning_enabled("dice", False, actor_id=1))
    assert "dice" in bot_module.earnings_off
    assert записано, "выключение не доехало до базы — переживёт ли перезапуск?"

    asyncio.run(bot_module.set_earning_enabled("dice", True, actor_id=1))
    assert "dice" not in bot_module.earnings_off
    assert not записано


async def _асинк_ничего(*args, **kwargs):
    return None


def test_ключи_источников_уникальны():
    ключи = [i.key for i in bot_module.EARNING_SOURCES]
    assert len(ключи) == len(set(ключи))
    assert {
        "farm", "garden", "barn", "work", "side_job", "hat", "business", "raid",
        "fishing", "treasure", "robbery", "stock", "market", "boss", "lootbox",
        "dice", "coin", "roulette", "poker", "racing",
    } <= set(ключи)


def test_каждый_источник_ссылается_на_живые_команды():
    """Ключ, которого нет в реестре, — мёртвая строка каталога: рубильник её
    покажет, а гасить будет нечего."""
    for источник in bot_module.EARNING_SOURCES:
        чужие = [k for k in источник.command_keys if k not in bot_module.COMMAND_REGISTRY]
        assert not чужие, f"{источник.key}: {чужие}"
        assert источник.command_keys or источник.extra, источник.key


def test_один_ключ_команды_не_у_двух_источников():
    """Иначе выключение одного источника молча гасит команду другого."""
    из_каталога = [k for s in bot_module.EARNING_SOURCES for k in s.command_keys]
    assert len(из_каталога) == len(set(из_каталога))


def test_занятия_сводки_ссылаются_на_живые_источники():
    ключи = {i.key for i in bot_module.EARNING_SOURCES}
    import activities
    for занятие, источник in bot_module.ACTIVITY_EARNING_SOURCE.items():
        assert занятие in activities.BY_KEY, занятие
        assert источник in ключи, источник


def test_заслон_реально_включён_в_роутер():
    """Middleware, не зарегистрированный в роутере, — самый тихий вид мёртвого
    кода: тесты зелёные, а в чате всё работает как раньше."""
    имена = [type(m).__name__
             for m in bot_module.router.message.outer_middleware._middlewares]
    assert "EarningsSwitchMiddleware" in имена, имена
    # Команды «Отношений 2.0» живут в своём роутере — там заслон нужен так же.
    rel2 = [type(m).__name__
            for m in bot_module.relationships_v2.router.message.outer_middleware._middlewares]
    assert "EarningsSwitchMiddleware" in rel2, rel2


def test_выключение_переживает_перезапуск(_рубильник, monkeypatch):
    """Единственный путь, который делает рубильник настоящим: запись легла в
    базу, а load_caches() при старте подняла её обратно в кэш.

    Проверяем кругом, а не по отдельности: между записью и чтением стоит формат
    ключа («earn_off:dice») и имя колонки, и разъехаться они могут молча —
    бот просто поднимется со всеми источниками включёнными.
    """
    база: dict[str, str] = {}

    async def set_data(key, value, updated_by=None):
        база[key] = value

    async def delete_data(key):
        база.pop(key, None)
        return True

    async def list_data_by_prefix(prefix):
        return [{"data_key": k, "data_value": v}
                for k, v in база.items() if k.startswith(prefix)]

    monkeypatch.setattr(bot_module.db, "set_data", set_data)
    monkeypatch.setattr(bot_module.db, "delete_data", delete_data)
    monkeypatch.setattr(bot_module.db, "list_data_by_prefix", list_data_by_prefix)
    monkeypatch.setattr(bot_module.db, "add_log", _асинк_ничего)

    asyncio.run(bot_module.set_earning_enabled("dice", False, actor_id=1))
    asyncio.run(bot_module.set_earning_enabled("stock", False, actor_id=1))

    bot_module.earnings_off.clear()          # как после перезапуска процесса
    asyncio.run(bot_module.load_earnings_off())

    assert bot_module.earnings_off == {"dice", "stock"}, bot_module.earnings_off

    # И обратно: включённое не должно воскресать из базы.
    asyncio.run(bot_module.set_earning_enabled("dice", True, actor_id=1))
    bot_module.earnings_off.clear()
    asyncio.run(bot_module.load_earnings_off())
    assert bot_module.earnings_off == {"stock"}, bot_module.earnings_off


def test_чужие_ключи_bot_data_рубильник_не_включают(_рубильник, monkeypatch):
    """bot_data — общая свалка ключей; строка с незнакомым источником не должна
    гасить ничего (и не должна ронять загрузку)."""
    async def list_data_by_prefix(prefix):
        return [{"data_key": prefix + "выдумка", "data_value": "1"},
                {"data_key": prefix + "farm", "data_value": "1"}]

    monkeypatch.setattr(bot_module.db, "list_data_by_prefix", list_data_by_prefix)
    asyncio.run(bot_module.load_earnings_off())
    assert bot_module.earnings_off == {"farm"}


# --- зонтичные выключатели ---------------------------------------------------

def test_казино_гасится_целиком(_рубильник, monkeypatch):
    """Выключив «Казино», админ ждёт, что замолчит ВСЁ казино, а не только
    кости: отдельные игры — это уточнение, а не единственный способ."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    _рубильник.add("casino")
    for текст in ("!кости 5 4", "!орёл 50", "рулетка 100 красное", "!покер 50",
                  "!гонки 100", "!казино баланс", "!казино пополнить 100",
                  "!казино вывести 100"):
        assert asyncio.run(_прогнать(текст)) == [], текст


def test_кошелёк_казино_гаснет_вместе_с_ним(_рубильник, monkeypatch):
    """Раньше «!казино баланс» отвечал даже при выключенных играх — со стороны
    это и есть «казино всё ещё работает»."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    _рубильник.add("dice")
    assert asyncio.run(_прогнать("!казино баланс")) == ["!казино баланс"]
    _рубильник.add("casino")
    assert asyncio.run(_прогнать("!казино баланс")) == []


def test_одна_игра_гасится_без_остального_казино(_рубильник, monkeypatch):
    """Обратная сторона: точечное выключение по-прежнему точечное."""
    monkeypatch.setitem(bot_module.settings, "complaint_chat_id", CHAT_ID)
    _рубильник.add("poker")
    assert asyncio.run(_прогнать("!покер 50")) == []
    assert asyncio.run(_прогнать("!кости 5 4")) == ["!кости 5 4"]
    assert asyncio.run(_прогнать("!казино баланс")) == ["!казино баланс"]


def test_панель_показывает_игры_погашенными_зонтиком(_рубильник):
    """Иначе экран врёт: казино выключено, а кости на кнопке «✅ работает»."""
    _рубильник.add("casino")
    тексты = [b.text for row in bot_module.earnings_menu_kb().keyboard for b in row]
    for label in ("🎲 Кости", "🃏 Покер", "🐎 Гонки"):
        строка = next(t for t in тексты if label in t)
        assert bot_module.EARNINGS_OFF_MARK in строка, строка


def test_зонтик_накрывает_живые_источники():
    ключи = {s.key for s in bot_module.EARNING_SOURCES}
    for источник in bot_module.EARNING_SOURCES:
        чужие = [k for k in источник.covers if k not in ключи]
        assert not чужие, f"{источник.key}: {чужие}"
        assert источник.key not in источник.covers, источник.key


# ---------------------------------------------------------------------------
# Дыры в опознавании: обработчик принимает форму, а рубильник её не видит.
#
# Так и всплыла жалоба «выключил рулетку, а она работает»: обработчик казино
# принимает «!рулетка 100 красное» и «.рулетка …», а во фразе реестра, по
# которой рубильник опознаёт команды, служебного знака нет. Тест спрашивает у
# САМОГО РОУТЕРА, команда ли это, — и требует, чтобы рубильник знал её тоже.
# ---------------------------------------------------------------------------

_КОРПУС = [
    "рулетка 100 красное", "рулетка", "кости 5 4", "лутбокс", "лутбокс купить rare",
    "рынок", "рынок купить x", "рынок мои", "мои товары", "биржа купить 5",
    "бизнес собрать", "налёт", "бизнес налёт", "покер 50", "гонки 50", "ферма",
    "подработка", "шапка", "клад", "рыбалка", "сетка", "садок", "босс", "огород",
    "хлев", "ограбить @a",
    # «русскаяру» в корпус не входит: это не источник дохода, а игра на
    # вылет из чата со своим выключателем («+рулетка»/«-рулетка»), который
    # панель теперь показывает отдельной кнопкой — см. тесты ниже.
]
_ФОРМЫ_КОРПУСА = [ф for b in _КОРПУС for ф in (b, "!" + b, "." + b)]


async def _команда_ли(текст: str) -> bool:
    """Берёт ли эту форму хоть один обработчик — по настоящим фильтрам роутера."""
    for h in bot_module.router.message.handlers:
        try:
            ok, _ = await h.check(_сообщение(текст), bot=bot_module.bot)
        except Exception:
            ok = False
        if ok:
            return True
    return False


@pytest.mark.parametrize("текст", _ФОРМЫ_КОРПУСА)
def test_каждая_принимаемая_форма_видна_рубильнику(текст):
    if not asyncio.run(_команда_ли(текст)):
        pytest.skip("бот такую форму и так не принимает")
    assert bot_module.earning_source_for(текст) is not None, (
        f"обработчик берёт {текст!r}, а рубильник её не видит — выключение "
        "такую команду не остановит"
    )


# --- русская рулетка: чужой выключатель, показанный в панели ------------------

def test_панель_показывает_русскую_рулетку():
    """Человек не отличает «рулетку» от «рулетки»: в панели должны быть обе,
    и подписи обязаны их различать."""
    подписи = [i.label for i in bot_module.EARNING_SOURCES] + [bot_module.LBL_RUSSIAN_ROULETTE]
    assert any("казино" in p.lower() for p in подписи), подписи
    assert any("русская" in p.lower() for p in подписи), подписи


def test_кнопка_русской_рулетки_правит_ту_же_настройку(monkeypatch):
    """Второй выключатель для одной игры — гарантированное расхождение: панель
    покажет «работает», а в чате будет выключена. Поэтому кнопка обязана писать
    ровно то же, что и команда «-рулетка» в чате."""
    хранилище = {}

    async def set_data(key, value, updated_by=None):
        хранилище[key] = value

    async def delete_data(key):
        хранилище.pop(key, None)
        return True

    async def get_data(key):
        return {"data_value": хранилище[key]} if key in хранилище else None

    monkeypatch.setattr(bot_module.db, "set_data", set_data)
    monkeypatch.setattr(bot_module.db, "delete_data", delete_data)
    monkeypatch.setattr(bot_module.db, "get_data", get_data)
    monkeypatch.setattr(bot_module.db, "add_log", _асинк_ничего)

    asyncio.run(bot_module.set_roulette_enabled(CHAT_ID, False, actor_id=1))
    assert хранилище.get(bot_module._roulette_enabled_key(CHAT_ID)) == "0"
    assert asyncio.run(bot_module.is_roulette_enabled(CHAT_ID)) is False

    asyncio.run(bot_module.set_roulette_enabled(CHAT_ID, True, actor_id=1))
    assert asyncio.run(bot_module.is_roulette_enabled(CHAT_ID)) is True
