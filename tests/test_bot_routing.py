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

    # Награда больше не просто запись: она даёт монеты, репутацию и ачивки,
    # и на пару «кто → кому» есть суточный кулдаун.
    async def _zero(*a, **k):
        return 0

    monkeypatch.setattr(bot_module.db, "last_reward_between", _noop)
    monkeypatch.setattr(bot_module.db, "add_coins", _noop)
    monkeypatch.setattr(bot_module.db, "change_reputation", _zero)
    monkeypatch.setattr(bot_module.db, "count_rewards", _zero)
    monkeypatch.setattr(bot_module, "_check_coin_achievements", _noop)
    monkeypatch.setattr(bot_module, "grant_achievement", _noop)

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


# --- декоратор приклеен к тому, что задумано --------------------------------
#
# «Бизнес собрать» перестал работать целиком, и никакой тест этого не увидел:
# между @router.message(...) и cmd_business_collect однажды вставили служебную
# функцию. aiogram зарегистрировал обработчиком её — она ждёт (chat_id,
# user_id), а получает Message, — а настоящий обработчик остался вообще без
# декоратора. Ошибка ловится только чтением исходника: код синтаксически
# безупречен, импортируется молча и падает уже в чате.

_EVENT_ARGS = {"message", "callback", "query", "event", "update"}
_HANDLER_DECORATORS = ("router.message", "router.callback_query",
                       "router.chat_member", "router.inline_query",
                       "router.my_chat_member")


def _routed_functions(module):
    """(имя функции, имя первого аргумента) для всего, что навешено на router."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(module))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if ast.unparse(decorator).startswith(_HANDLER_DECORATORS):
                args = [a.arg for a in node.args.args]
                out.append((node.name, args[0] if args else None))
                break
    return out


def test_обработчики_принимают_событие_а_не_чужие_аргументы():
    """Первый аргумент обработчика — само событие. Функция, ждущая chat_id,
    в этой роли не работает никогда, и заметно это только в чате."""
    routed = _routed_functions(bot_module)
    assert routed, "не нашли ни одного обработчика — сломался разбор, а не код"
    чужие = [f"{name}(первый аргумент: {first})"
             for name, first in routed if first not in _EVENT_ARGS]
    assert not чужие, "декоратор навешен на служебную функцию: " + ", ".join(чужие)


def test_сбор_дохода_с_бизнеса_зарегистрирован():
    """Именно эта команда и потерялась. Закрепляем поимённо: общий сторож
    выше поймал бы подмену, но не полное исчезновение обработчика."""
    names = {name for name, _ in _routed_functions(bot_module)}
    assert "cmd_business_collect" in names
    assert "_pinned_business_self_repair" not in names


# ---------------------------------------------------------------------------
# Кнопки лички не должны уезжать заявкой на вступление
#
# handle_user_message ловит ЛЮБОЕ сообщение в личке без состояния и объявлен
# в файле раньше половины команд — значит забирает себе всё, что объявлено
# ниже. Так молча не работали «Логи» и «РЕЙД НАЧАЛСЯ»: нажатие уезжало
# админам как заявка, а команда не выполнялась никогда.
# ---------------------------------------------------------------------------

def _клавиатура_со_всеми_правами(monkeypatch, user_id=555):
    """Клавиатура лички, как её видит человек с максимальными правами."""
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: True)
    monkeypatch.setattr(bot_module, "has_level", lambda uid, lvl: True)
    monkeypatch.setattr(bot_module, "is_owner", lambda uid: True)
    return bot_module.private_menu_kb(user_id)


def test_каждая_кнопка_меню_перечислена_в_пропуске(monkeypatch):
    """Список кнопок явный, а не собранный из клавиатуры: полный набор не
    выдаётся никому — у админа своя половина, у обычного своя. Значит его
    обязан сторожить тест, иначе следующая новая кнопка сломается молча."""
    kb = _клавиатура_со_всеми_правами(monkeypatch)
    кнопки = {b.text for row in kb.keyboard for b in row}

    потерянные = sorted(кнопки - bot_module.PRIVATE_MENU_BUTTONS)
    assert not потерянные, (
        "кнопки уедут заявкой на вступление вместо своей команды: "
        + ", ".join(потерянные)
    )


def test_обычный_пользователь_тоже_покрыт(monkeypatch):
    monkeypatch.setattr(bot_module, "is_admin", lambda uid: False)
    monkeypatch.setattr(bot_module, "is_owner", lambda uid: False)
    kb = bot_module.private_menu_kb(555)
    кнопки = {b.text for row in kb.keyboard for b in row}

    assert not (кнопки - bot_module.PRIVATE_MENU_BUTTONS)


@pytest.mark.parametrize("текст", [
    "Логи", "Помощь", "Админка", "Моя роль", "🌴 Рест",
    "фарт", "Фарт", "подкрутить",
])
def test_кнопки_и_команды_лички_проходят_мимо_заявки(текст):
    assert bot_module.is_private_passthrough(текст), текст


@pytest.mark.parametrize("текст", ["логи", "ЛОГИ", "мой рынок", "МОЙ РЫНОК",
                                   "админка", "помощь"])
def test_набранное_руками_работает_в_любом_регистре(текст):
    """Кнопка подписана «Логи», а руками то же самое пишут «логи». Сравнивай
    мы буквально — нажатие работало бы, а набранное слово уезжало админам
    заявкой. Ровно так и было сломано «мой рынок»."""
    assert bot_module.is_private_passthrough(текст), текст


def test_все_кнопки_проходят_и_кнопкой_и_словом():
    """Сплошная проверка вместо поштучной: следующая новая кнопка обязана
    работать в обоих видах сразу, а не только в том, который вспомнили."""
    непрошедшие = [t for t in bot_module.PRIVATE_MENU_BUTTONS
                   if not (bot_module.is_private_passthrough(t)
                           and bot_module.is_private_passthrough(t.lower()))]
    assert not непрошедшие, "уедут заявкой: " + ", ".join(sorted(непрошедшие))


@pytest.mark.parametrize("текст", [
    "привет, хочу в чат",
    "здравствуйте",
    "логин от аккаунта",       # начинается похоже, но это не кнопка
    "",
    None,
])
def test_живая_заявка_остаётся_заявкой(текст):
    """Пропустить лишнее — значит потерять заявку человека: она уйдёт в
    никуда, и он останется без ответа."""
    assert not bot_module.is_private_passthrough(текст), текст


def test_заявочный_обработчик_отдаёт_кнопку_дальше():
    """SkipHandler, а не return: обычный выход из обработчика в aiogram
    ОСТАНАВЛИВАЕТ разбор, и кнопка провалилась бы в тишину вместо команды."""
    from aiogram.dispatcher.event.bases import SkipHandler

    async def run():
        msg = message(bot_module.BTN_RAID_ON, chat_type="private")
        with pytest.raises(SkipHandler):
            await bot_module.handle_user_message(msg)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Декоратор обязан стоять над СВОЕЙ функцией
#
# Дважды подряд новая функция, вставленная перед существующим обработчиком,
# забирала себе его декоратор: сначала «ферма собрать», потом «ферма посадить».
# Оба раза старый обработчик оставался вообще без регистрации, а новый — под
# чужим фильтром. Существующий тест это не ловил: у обоих первый аргумент
# называется message, и «декоратор на служебной функции» не срабатывал.
# ---------------------------------------------------------------------------

_ОЖИДАЕМАЯ_МАРШРУТИЗАЦИЯ = [
    ("ферма посадить картошка", "cmd_farm_plant"),
    ("ферма посадить картошка 5", "cmd_farm_plant"),
    ("ферма расширить", "cmd_farm_expand"),
    ("ферма расширить 20", "cmd_farm_expand"),
    ("ферма расширить все", "cmd_farm_expand"),
    ("купить грядку", "cmd_farm_expand"),
    ("ферма грядки", "cmd_farm_garden"),
    ("ферма собрать", "cmd_farm_harvest"),
    ("ферма скот", "cmd_barn"),
    ("ферма купить корова", "cmd_barn_buy"),
    ("ферма продать корова", "cmd_barn_sell"),
    ("магазин купить bronik все", "cmd_shop_buy"),
    ("лавка купить binokl 2", "cmd_black_market_buy"),
    # «античк» — слово целиком, без аргументов: цель показывается ответом.
    ("античк", "cmd_cleanup_keep"),
]


@pytest.mark.parametrize("текст,ожидается", _ОЖИДАЕМАЯ_МАРШРУТИЗАЦИЯ)
def test_команда_доходит_до_своего_обработчика(текст, ожидается):
    """Проверяем ИМЯ обработчика, а не сам факт совпадения: перехваченный
    декоратор даёт и то и другое — команда «работает», просто выполняет чужой
    код, а её собственный не выполняется никогда."""
    взяли = handlers_for(message(текст))
    assert взяли, f"{текст!r} не берёт никто"
    assert взяли[0] == ожидается, f"{текст!r} ушло в {взяли[0]}, а не в {ожидается}"


def test_у_каждого_обработчика_свой_фильтр():
    """Одна и та же функция, зарегистрированная дважды, — верный признак
    съеденного декоратора: чужая регистрация досталась ей вдобавок к своей."""
    from collections import Counter

    имена = Counter(getattr(h.callback, "__name__", "?")
                    for h in bot_module.router.message.handlers)
    дважды = sorted(имя for имя, n in имена.items()
                    if n > 1 and имя in {n for _, n in _ОЖИДАЕМАЯ_МАРШРУТИЗАЦИЯ})
    assert not дважды, "зарегистрированы дважды: " + ", ".join(дважды)
