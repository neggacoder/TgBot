"""Маршрутизация команд бота — на настоящем aiogram.

До появления venv с зависимостями bot.py в тестах вообще не открывался, и
фильтры проверялись глазами. Здесь строятся настоящие объекты Message и
спрашивается роутер: какой обработчик их возьмёт. Так ловятся ошибки, которые
не видны при чтении, — перехваченная команда, опечатка в триггере, потерянная
подпись к фото.

Если aiogram недоступен (машина без venv), тесты пропускаются: заглушка из
conftest роутер не поднимет, а врать зелёным прогоном нельзя.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest

# Именно НАСТОЯЩИЙ aiogram: conftest кладёт в sys.modules заглушку, поэтому
# простого importorskip мало — он бы её и нашёл. Заглушка не умеет Dispatcher
# и роутер на ней не поднять.
aiogram = pytest.importorskip("aiogram", reason="нужен aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — "
        "запустите тесты интерпретатором из .venv",
        allow_module_level=True,
    )

from aiogram.types import Chat, Message, User  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890


def message(text=None, caption=None, chat_type="supergroup"):
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=CHAT_ID, type=chat_type),
        from_user=User(id=555, is_bot=False, first_name="Тестер"),
        text=text,
        caption=caption,
    )


def handlers_for(msg) -> list[str]:
    """Имена обработчиков, которые берут это сообщение. Пусто — команду никто
    не обработает."""
    async def run():
        found = []
        for handler in bot_module.router.message.handlers:
            ok, _ = await handler.check(msg, bot=bot_module.bot)
            if ok:
                found.append(handler.callback.__name__)
        return found

    return asyncio.run(run())


def test_роутер_поднялся():
    assert len(bot_module.router.message.handlers) > 100


# ---------------------------------------------------------------------------
# Созывы: команда может прийти подписью к фотографии
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caption", ["созыв", "созыв, все сюда", "калл", "СОЗЫВ!"])
def test_созыв_подписью_к_фото_доходит_до_обработчика(caption):
    """Ровно тот случай, который был сломан: у фото message.text пустой, всё
    лежит в caption."""
    assert "cmd_call_all" in handlers_for(message(caption=caption))


def test_созыв_текстом_работает_как_прежде():
    assert "cmd_call_all" in handlers_for(message(text="созыв"))


def test_созыв_админов_не_поднимает_весь_чат():
    taken = handlers_for(message(text="созыв админов"))
    assert "cmd_call_admins" in taken
    assert "cmd_call_all" not in taken


def test_обычный_текст_не_запускает_созыв():
    assert "cmd_call_all" not in handlers_for(message(text="а потом был созыв"))


# ---------------------------------------------------------------------------
# +рстик / -рстик: тумблер случайных стикеров — только на точное совпадение
# ---------------------------------------------------------------------------

def test_рстик_тумблер_доходит():
    assert "cmd_random_sticker_toggle" in handlers_for(message(text="+рстик"))
    assert "cmd_random_sticker_toggle" in handlers_for(message(text="-рстик"))


def test_текст_со_словом_рстик_не_триггерит_тумблер():
    assert "cmd_random_sticker_toggle" not in handlers_for(message(text="я поставил рстик на аватарку"))


# ---------------------------------------------------------------------------
# Кнопка «Сайт» из private_menu_kb — её текст должен вести в cmd_site_code
# ---------------------------------------------------------------------------

def test_кнопка_сайт_ведёт_в_команду_сайта():
    assert "cmd_site_code" in handlers_for(message(text="Сайт", chat_type="private"))


# ---------------------------------------------------------------------------
# !кто / бот кто — оба варианта ведут в misc_who, а просто «бот» — нет
# ---------------------------------------------------------------------------

def test_кто_и_бот_кто_ведут_в_misc_who():
    assert "cmd_misc_who" in handlers_for(message(text="!кто гей"))
    assert "cmd_misc_who" in handlers_for(message(text="бот кто заснёт первым"))


def test_просто_бот_не_триггерит_misc_who():
    taken = handlers_for(message(text="бот"))
    assert "cmd_misc_who" not in taken
    assert "cmd_misc_ping" in taken  # «бот» → пинг-ответ, как прежде


# ---------------------------------------------------------------------------
# «бот <команда>» для выбери / данет / жребий / скажи (плюс старые «!»-формы)
# ---------------------------------------------------------------------------

def test_бот_выбери_и_восклик():
    assert "cmd_misc_choose" in handlers_for(message(text="бот выбери чай или кофе"))
    assert "cmd_misc_choose" in handlers_for(message(text="!выбери чай или кофе"))


def test_бот_данет_и_варианты():
    assert "cmd_misc_yesno" in handlers_for(message(text="бот данет будет дождь"))
    assert "cmd_misc_yesno" in handlers_for(message(text="бот да нет будет дождь"))
    assert "cmd_misc_yesno" in handlers_for(message(text="!данет будет дождь"))


def test_бот_жребий_и_восклик():
    assert "cmd_misc_draw" in handlers_for(message(text="бот жребий Аня, Вася"))
    assert "cmd_misc_draw" in handlers_for(message(text="!жребий Аня, Вася"))


def test_бот_скажи_и_восклик():
    assert "cmd_misc_say" in handlers_for(message(text="бот скажи привет"))
    assert "cmd_misc_say" in handlers_for(message(text="!скажи привет"))


# ---------------------------------------------------------------------------
# Варны: настоящий и обманный не должны пересекаться
# ---------------------------------------------------------------------------

def test_настоящий_варн():
    taken = handlers_for(message(text="варн спам"))
    assert "cmd_warn" in taken
    assert "cmd_fake_warn" not in taken


def test_обманный_варн():
    taken = handlers_for(message(text="&варн спам"))
    assert "cmd_fake_warn" in taken
    assert "cmd_warn" not in taken


def test_снятие_варна():
    assert "cmd_unwarn" in handlers_for(message(text="-варн"))


def test_вернуть_брак_доходит():
    assert "cmd_restore_marriage" in handlers_for(message(text="вернуть брак"))
    assert "cmd_restore_marriage" not in handlers_for(message(text="вернуть"))  # только полная фраза


def test_список_варнов_и_обманных_не_путается():
    assert "cmd_list_warns" in handlers_for(message(text="варны"))
    assert "cmd_list_fake_warns" in handlers_for(message(text="&варны"))
    assert "cmd_list_warns" not in handlers_for(message(text="&варны"))


# ---------------------------------------------------------------------------
# Одно сообщение — один обработчик
# ---------------------------------------------------------------------------

def test_поиск_ролей():
    """Новая команда не должна перехватываться списком «роли» и наоборот."""
    assert "cmd_role_search" in handlers_for(message(text="роль найти Аска"))
    assert "cmd_role_search" in handlers_for(message(text="найти роль Аска"))
    assert "cmd_role_search" not in handlers_for(message(text="роли"))
    assert "cmd_role_list" not in handlers_for(message(text="роль найти Аска"))


@pytest.mark.parametrize("text", ["варн спам", "&варн спам", "созыв", "варны", "роли", "роль найти Аска"])
def test_команду_не_перехватывают_двое(text):
    """Два обработчика на одну команду — это гонка: сработает тот, кто
    зарегистрирован раньше, и второй молча не выполнится."""
    taken = handlers_for(message(text=text))
    assert len(taken) <= 1, f"«{text}» берут сразу несколько: {taken}"


# ---------------------------------------------------------------------------
# Фильтр слов (middleware)
# ---------------------------------------------------------------------------

def test_фильтр_удаляет_сообщение_с_запретным_словом(monkeypatch):
    """Обычный участник написал запретное слово — сообщение удаляется, и до
    счётчиков/обработчиков не доходит."""
    import asyncio

    bot_module.WORD_FILTER.clear()
    bot_module.WORD_FILTER.add("спам")
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)

    deleted = {"v": False}

    async def fake_delete():
        deleted["v"] = True

    async def fake_log(*a, **k):
        return None

    monkeypatch.setattr(bot_module.db, "add_log", fake_log)

    msg = message(text="это спам")
    object.__setattr__(msg, "delete", fake_delete)

    hit = asyncio.run(bot_module._enforce_word_filter(msg))
    assert hit is True and deleted["v"] is True
    bot_module.WORD_FILTER.clear()


def test_фильтр_не_трогает_админа(monkeypatch):
    import asyncio
    bot_module.WORD_FILTER.clear()
    bot_module.WORD_FILTER.add("спам")
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: True)

    msg = message(text="это спам")
    assert asyncio.run(bot_module._enforce_word_filter(msg)) is False
    bot_module.WORD_FILTER.clear()


def test_фильтр_пропускает_чистое_сообщение(monkeypatch):
    import asyncio
    bot_module.WORD_FILTER.clear()
    bot_module.WORD_FILTER.add("спам")
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)

    msg = message(text="обычное сообщение")
    assert asyncio.run(bot_module._enforce_word_filter(msg)) is False
    bot_module.WORD_FILTER.clear()


# ---------------------------------------------------------------------------
# Ссылка на сообщение, где выдан варн (t.me/c/…)
# ---------------------------------------------------------------------------

def test_ссылка_на_сообщение_супергруппы():
    # -100 + 1234567890 → внутренний id 1234567890
    assert bot_module.chat_message_link(-1001234567890, 42) == "https://t.me/c/1234567890/42"


def test_ссылки_нет_без_message_id():
    # старый варн без сохранённого id — показываем без ссылки
    assert bot_module.chat_message_link(-1001234567890, None) is None


def test_ссылки_нет_в_обычной_группе():
    # у обычных групп (без префикса -100) публичных ссылок на сообщение нет
    assert bot_module.chat_message_link(-1234567890, 42) is None


# ---------------------------------------------------------------------------
# Реплика РП-действия: местоимение-указатель цели — это не реплика
# ---------------------------------------------------------------------------

def test_местоимение_цели_не_реплика():
    # «поцелуй его»: триггер «поцелуй» (1 слово), хвост «его» — указание цели
    assert bot_module._rp_reply_text(["поцелуй", "его"], 1) == ""
    assert bot_module._rp_reply_text(["обнять", "её"], 1) == ""


def test_свободный_текст_после_действия_детектируется():
    # непустой результат = после действия есть свободный текст → это не команда
    assert bot_module._rp_reply_text(["обнять", "снова", "тест"], 1) == "снова тест"


def test_чистое_действие_без_свободного_текста():
    assert bot_module._rp_reply_text(["обнять"], 1) == ""


# ---------------------------------------------------------------------------
# Поженить пару / .мойпол — новые команды доходят до своих обработчиков
# ---------------------------------------------------------------------------

def test_поженить_пару_доходит():
    taken = handlers_for(message(text="поженить пару @a @b"))
    assert "cmd_marry_pair" in taken
    # не должно перехватываться обычным «брак»
    assert "propose_marriage" not in taken


def test_поженить_пару_матчер():
    assert bot_module._is_marry_pair_command("поженить пару @a @b") is True
    assert bot_module._is_marry_pair_command("Поженить Пару @a") is True
    assert bot_module._is_marry_pair_command("поженить") is False
    assert bot_module._is_marry_pair_command("поженились наконец") is False


def test_мойпол_доходит():
    assert "cmd_gender_compact" in handlers_for(message(text=".мойпол м"))
    assert "cmd_gender_compact" in handlers_for(message(text="мойпол ж"))


@pytest.mark.parametrize("text", ["поженить пару @a @b", ".мойпол м"])
def test_новые_команды_без_двойного_перехвата(text):
    taken = handlers_for(message(text=text))
    assert len(taken) <= 1, f"«{text}» берут сразу несколько: {taken}"


# ---------------------------------------------------------------------------
# Превью текущего значения настройки (обзор текстов в админке)
# ---------------------------------------------------------------------------

def test_превью_настройки_пусто():
    assert bot_module._setting_preview("") == "— не задано —"
    assert bot_module._setting_preview(None, empty="— отключено —") == "— отключено —"


def test_превью_настройки_схлопывает_и_экранирует():
    assert bot_module._setting_preview("привет\n\n  мир") == "привет мир"
    assert bot_module._setting_preview("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"


def test_превью_настройки_обрезает():
    out = bot_module._setting_preview("я" * 300, limit=50)
    assert out.endswith("…") and len(out) <= 51


# ---------------------------------------------------------------------------
# Чистка /clearUsers
# ---------------------------------------------------------------------------

def test_clearusers_доходит():
    # Вариант с @упоминанием бота («/clearusers@Bot») здесь не гоняем: у других
    # обработчиков есть aiogram-фильтр Command, который для @-упоминания лезет в
    # сеть за bot.me() — с тестовым токеном это падает. Разбор @ покрыт
    # юнит-тестом матчера ниже (без сети).
    assert "cmd_clear_users" in handlers_for(message(text="/clearUsers"))


def test_clearusers_матчер():
    assert bot_module._is_clear_users_command("/clearUsers") is True
    assert bot_module._is_clear_users_command("/clearusers@bot и аргументы") is True
    assert bot_module._is_clear_users_command("clearusers") is False   # без слеша
    assert bot_module._is_clear_users_command("/clear") is False


def test_норма_неделя_с_субботы():
    # неделя нормы теперь стартует с субботы (weekday()==5)
    assert bot_module._current_week_start().weekday() == 5


def test_рп_действие_строго_1в1(monkeypatch):
    """«обнять» (ответом) выполняет действие; «обнять снова тест» — свободный
    текст после действия, значит это обычная фраза: действие НЕ выполняется, а
    обработчик пропускает сообщение дальше (SkipHandler)."""
    import asyncio

    from aiogram.dispatcher.event.bases import SkipHandler

    monkeypatch.setattr(bot_module, "RP_ACTIONS", {"обнять": ["{actor} обнимает {target}"]})
    monkeypatch.setattr(bot_module, "RP_ACTION_SYNONYMS", {})
    monkeypatch.setattr(bot_module, "_RP_ACTION_ALL_KEYS", ["обнять"])

    async def display_name_link(chat_id, u):
        return "N"

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(bot_module, "display_name_link", display_name_link)
    monkeypatch.setattr(bot_module.db, "add_log", _noop)

    partner = User(id=999, is_bot=False, first_name="Партнёр")

    def make(text):
        replied = Message(message_id=2, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
                          from_user=partner, text="ое")
        m = Message(message_id=3, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
                    from_user=User(id=555, is_bot=False, first_name="A"), text=text, reply_to_message=replied)
        answers = []

        async def fake_answer(t, **kwargs):
            answers.append(t)

        object.__setattr__(m, "answer", fake_answer)
        return m, answers

    m1, answers1 = make("обнять")
    asyncio.run(bot_module.handle_rp_action(m1))
    assert answers1 and "обнимает" in answers1[0]

    m2, answers2 = make("обнять снова тест")
    with pytest.raises(SkipHandler):
        asyncio.run(bot_module.handle_rp_action(m2))
    assert not answers2  # действие не выполнено


def test_наградить_выдаёт_награду(monkeypatch):
    """Прямой happy-path команды «наградить N» ответом: админ, валидная цель —
    награда пишется в БД и приходит ответ «Награда выдана». Ловит регрессии в
    самой команде (парсинг степени/причины, гейт доступа, вызов add_reward)."""
    import asyncio

    monkeypatch.setattr(bot_module, "get_level",
                        lambda uid: bot_module.LEVEL_SENIOR if uid == 555 else 0)
    monkeypatch.setattr(bot_module, "required_reward_level", lambda d: bot_module.LEVEL_MODERATOR)

    given = {}

    async def add_reward(chat_id, uid, degree, reason, by):
        given.update(uid=uid, degree=degree, reason=reason)
        return 7

    async def _noop(*a, **k):
        return None

    async def display_name(chat_id, u):
        return "X"

    monkeypatch.setattr(bot_module.db, "add_reward", add_reward)
    monkeypatch.setattr(bot_module.db, "add_log", _noop)
    monkeypatch.setattr(bot_module, "display_name", display_name)
    # Вместе с наградой в инвентарь кладётся трофей (см. shop_effects) —
    # здесь проверяется сама команда, поэтому магазин и инвентарь молчат.
    monkeypatch.setattr(bot_module.db, "seed_extra_shop_items", _noop, raising=False)
    monkeypatch.setattr(bot_module.db, "add_inventory_item", _noop, raising=False)

    target = User(id=999, is_bot=False, first_name="Цель")
    replied = Message(message_id=2, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
                      from_user=target, text="привет")
    msg = Message(message_id=3, date=datetime.now(), chat=Chat(id=CHAT_ID, type="supergroup"),
                  from_user=User(id=555, is_bot=False, first_name="Админ"),
                  text="наградить 5\nЗа помощь новичкам", reply_to_message=replied)

    replies = []

    async def fake_reply(text, **kwargs):
        replies.append(text)

    object.__setattr__(msg, "reply", fake_reply)
    asyncio.run(bot_module.cmd_reward(msg))

    assert given.get("uid") == 999 and given.get("degree") == 5
    assert given.get("reason") == "За помощь новичкам"
    # текст ответа менялся: сейчас это «<эмодзи><степень> Награда X вручена»
    assert any("Награда" in r and "вручена" in r for r in replies), replies


# ---------------------------------------------------------------------------
# 20-й модуль «Браки»: подкоманды слова «Брак» не должны съедаться
# предложением руки и сердца, а сами команды — доходить до своих обработчиков
# ---------------------------------------------------------------------------

def test_предложение_брака_доходит():
    assert "propose_marriage" in handlers_for(message(text="брак @someone"))


@pytest.mark.parametrize("text,handler", [
    ("брак да", "cmd_marriage_yes"),
    ("Брак нет", "cmd_marriage_no"),
    ("брак продлить 7", "cmd_marriage_extend"),
    ("брак цена продления 500", "cmd_marriage_renew_price"),
    ("брак режим развода авто", "cmd_marriage_divorce_mode"),
])
def test_подкоманды_брака_идут_в_свои_обработчики(text, handler):
    taken = handlers_for(message(text=text))
    assert handler in taken
    # самое важное: предложение руки и сердца их НЕ перехватывает
    assert "propose_marriage" not in taken, f"«{text}» ушло в предложение брака"


@pytest.mark.parametrize("text,handler", [
    ("мой брак", "cmd_my_marriage"),
    ("твой брак @someone", "cmd_their_marriage"),
    ("браки 3", "cmd_marriages_page"),
    ("топ браков", "cmd_marriage_top"),
    ("развести пару @a @b", "cmd_divorce_pair"),
    ("развести вышедших", "cmd_divorce_departed"),
    ("!сброс браков", "cmd_marriages_reset"),
    ("+брак рейтинг", "cmd_marriage_rating_toggle"),
    ("-брак рейтинг", "cmd_marriage_rating_toggle"),
])
def test_команды_модуля_браков_доходят(text, handler):
    assert handler in handlers_for(message(text=text))


def test_развод_принимает_оба_написания():
    assert "cmd_divorce" in handlers_for(message(text=".развод"))
    assert "cmd_divorce" in handlers_for(message(text="!развод"))


def test_топ_браков_не_перехватывается_статистикой():
    """«топ …» ловит общий обработчик статистики — «топ браков» обязан быть
    исключением, иначе рейтинг браков недостижим."""
    taken = handlers_for(message(text="топ браков"))
    assert "cmd_stat_period" not in taken


def test_браки_без_номера_остаются_на_старом_обработчике():
    taken = handlers_for(message(text="браки"))
    assert "cmd_marriages" in taken
    assert "cmd_marriages_page" not in taken


# ---------------------------------------------------------------------------
# Новые способы заработка: рыбалка и клад
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["рыбалка", "Рыбачить", "удочка", "рыбка"])
def test_рыбалка_доходит_по_всем_синонимам(text):
    assert "cmd_fishing" in handlers_for(message(text=text))


def test_топ_уловов_не_перехватывается_статистикой():
    taken = handlers_for(message(text="топ уловов"))
    assert "cmd_fishing_top" in taken
    assert "cmd_stat_period" not in taken


# ---------------------------------------------------------------------------
# Топ по стрикам — листаемый рейтинг, отдельный от общей статистики
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["топ стриков", "топ по стрику", "топ стрик", "ТОП СТРИКОВ"])
def test_топ_стриков_не_перехватывается_статистикой(text):
    """«топ стриков» подходил под фильтр и cmd_streak_top, и cmd_stat_period,
    и доставался тому, кто зарегистрирован раньше в файле. Работало по
    случайности порядка строк: перенос обработчика молча увёл бы команду
    в общую статистику, где никакого рейтинга стриков нет."""
    taken = handlers_for(message(text=text))
    assert "cmd_streak_top" in taken
    assert "cmd_stat_period" not in taken


@pytest.mark.parametrize("text", ["топ 20", "стата за неделю", "стата неделя"])
def test_обычная_статистика_за_период_не_задета(text):
    """Обратная сторона той же правки: исключать надо ровно стрики."""
    assert "cmd_stat_period" in handlers_for(message(text=text))


@pytest.mark.parametrize("text", ["клад", "копать"])
def test_клад_доходит(text):
    assert "cmd_treasure_dig" in handlers_for(message(text=text))


def test_клад_инфа_отдельная_команда():
    taken = handlers_for(message(text="клад инфа"))
    assert "cmd_treasure_info" in taken
    assert "cmd_treasure_dig" not in taken


def test_упоминание_клада_в_разговоре_не_триггерит_команду():
    assert "cmd_treasure_dig" not in handlers_for(message(text="вчера нашли клад в лесу"))


def test_предложить_клад_остаётся_совместным_занятием():
    """«клад» есть и среди синонимов «предложить …» — новая команда не должна
    его перехватывать: у них разные первые слова."""
    taken = handlers_for(message(text="предложить клад @someone"))
    assert "cmd_treasure_dig" not in taken


# ---------------------------------------------------------------------------
# Часовой пояс
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["время", "часовой пояс", "часовой пояс Москва", "часовой пояс +3"])
def test_команда_часового_пояса_доходит(text):
    assert "cmd_timezone" in handlers_for(message(text=text))


def test_слово_время_внутри_фразы_не_триггерит():
    assert "cmd_timezone" not in handlers_for(message(text="сколько сейчас время"))


# ---------------------------------------------------------------------------
# Мини-приложение Telegram
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["приложение", "Приложение", "/app", "апп", "мини"])
def test_команда_приложения_доходит_в_личке(text):
    assert "cmd_webapp" in handlers_for(message(text=text, chat_type="private"))


def test_приложение_не_срабатывает_в_группе():
    """web_app-кнопку Telegram разрешает только в личке — в группе она бы
    просто не отрисовалась, поэтому и команды там быть не должно."""
    assert "cmd_webapp" not in handlers_for(message(text="приложение"))


def test_упоминание_слова_в_разговоре_не_триггерит():
    taken = handlers_for(message(text="скачал приложение вчера", chat_type="private"))
    assert "cmd_webapp" not in taken
