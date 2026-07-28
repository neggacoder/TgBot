"""Взыскание долга: настройки, отметка визитов, поведение цикла."""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
from datetime import datetime, timedelta

import pytest

import chat_settings

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import db as db_module  # noqa: E402


def test_настройки_коллектора_есть_в_реестре():
    """Без строки в реестре настройка не появится в веб-панели, и админ
    будет думать, что её нет."""
    assert "bank.collector_after_days" in chat_settings.BY_KEY
    assert "bank.seize_after_days" in chat_settings.BY_KEY


@pytest.mark.parametrize("key", ["bank.collector_after_days", "bank.seize_after_days"])
def test_настройка_привязана_к_банковской_команде(key):
    setting = chat_settings.BY_KEY[key]
    assert setting.command_key == "bank_manage"
    assert setting.group == "Банк"
    assert setting.minimum == 0, "ноль обязан быть допустим — им выключают"


@pytest.mark.parametrize("column", [
    "collector_after_days", "seize_after_days",
])
def test_колонки_настроек_заведены(column):
    источник = inspect.getsource(db_module)
    начало = источник.index("CREATE TABLE IF NOT EXISTS bank_settings (")
    кусок = источник[начало:источник.index(") ENGINE=", начало)]
    assert column in кусок, f"{column} нет в определении bank_settings"


@pytest.mark.parametrize("column", ["credit_last_visit_at", "credit_visits"])
def test_колонки_визитов_заведены(column):
    """bank_accounts существовала до задачи, поэтому этим колонкам взяться
    неоткуда, кроме ALTER — проверяем сам вызов миграции, а не поиск имени по
    всему исходнику: имя колонки всё равно встретится в mark_credit_visit
    (SQL-текст, обращение к строке результата), и тест был бы зелёным даже
    без миграции, хотя старые чаты остались бы без колонок вовсе."""
    источник = inspect.getsource(db_module)
    assert f'_add_column_if_missing("bank_accounts", "{column}"' in источник, column


def test_есть_чем_отметить_визит():
    assert hasattr(db_module, "mark_credit_visit")


# --- команды правки в чате --------------------------------------------------
#
# Настройка в реестре без команды в боте правилась бы только с сайта — в чате
# её как будто нет. Заводим команды рядом с остальными «банк кредит …», по
# тому же образцу: тот же уровень доступа, тот же формат «слово + число».

def test_команда_коллектора_разбирает_дни():
    assert bot_module.BANK_CREDIT_COLLECTOR_RE.match("банк кредит коллектор 3")
    assert bot_module.BANK_CREDIT_COLLECTOR_RE.match("банк кредит коллектор 0"), \
        "0 обязан разбираться — им коллектора выключают"
    assert not bot_module.BANK_CREDIT_COLLECTOR_RE.match("банк кредит коллектор")
    assert not bot_module.BANK_CREDIT_COLLECTOR_RE.match("банк кредит коллектор -1"), \
        "отрицательное число не должно проходить регэксп"


def test_команда_взыскания_разбирает_дни():
    assert bot_module.BANK_CREDIT_SEIZE_RE.match("банк кредит взыскание 5")
    assert bot_module.BANK_CREDIT_SEIZE_RE.match("банк кредит взыскание 0"), \
        "0 обязан разбираться — им взыскание по сроку выключают"
    assert not bot_module.BANK_CREDIT_SEIZE_RE.match("банк кредит взыскание")


@pytest.mark.parametrize("handler", [
    "cmd_bank_credit_collector_set", "cmd_bank_credit_seize_set",
])
def test_обработчики_команд_существуют(handler):
    assert hasattr(bot_module, handler)


def test_обработчики_гейтятся_bank_manage():
    """Тот же уровень доступа, что у соседних «банк кредит комиссия/пеня/срок» —
    иначе новую настройку сможет менять кто попало, пока остальные защищены."""
    for handler in ("cmd_bank_credit_collector_set", "cmd_bank_credit_seize_set"):
        источник = inspect.getsource(getattr(bot_module, handler))
        assert 'required_level("bank_manage")' in источник


def test_фраза_реестра_команд_упоминает_новые_формы():
    """Фраза в COMMAND_REGISTRY — единственное место, где админ в чате видит
    список доступных форм команды «банк». Потерянная форма означает, что
    команда есть, а узнать о ней неоткуда."""
    phrase = bot_module.COMMAND_REGISTRY["bank_manage"]["phrase"]
    assert "коллектор" in phrase
    assert "взыскание" in phrase


def test_сеттер_бд_принимает_новые_настройки():
    """set_bank_credit_settings — общая точка записи кредитных настроек банка;
    коллектор и взыскание должны писаться через неё же, а не отдельной веткой,
    которую легко забыть при следующей правке."""
    params = inspect.signature(db_module.set_bank_credit_settings).parameters
    assert "collector_after_days" in params
    assert "seize_after_days" in params


# --- сброс счётчика визитов при новом/закрытом кредите ----------------------
#
# mark_credit_visit обещает докстрингом: счётчик живёт на кредите и
# обнуляется вместе с ним. Без этого человек гасит кредит, берёт новый,
# просрочивает — и коллектор приходит сразу с последней (самой наглой)
# ступени, унаследованной от прошлого долга.
#
# MySQL тесты не поднимают (см. tests/conftest.py), поэтому подменяем
# db._execute/db._fetchone и проверяем, ЧТО именно уходит в SQL — тот же
# приём, что в test_chat_settings_storage.py, а не обычная подмена всего
# db-модуля целиком (там не нужна логика get_bank_account внутри).

CHAT_ID = -1001112223334
USER_ID = 42


@pytest.fixture
def bank_queries(monkeypatch):
    written: list[tuple[str, tuple]] = []
    row = {"credit_debt": 0}

    async def fake_execute(query, args=()):
        written.append((" ".join(query.split()), args))
        return 1

    async def fake_fetchone(query, args=()):
        return dict(row)

    monkeypatch.setattr(db_module, "_execute", fake_execute)
    monkeypatch.setattr(db_module, "_fetchone", fake_fetchone)
    return type("Q", (), {"written": written, "row": row})


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. test_chat_settings_storage.py)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@_sync
async def test_открытие_кредита_сбрасывает_визиты(bank_queries):
    await db_module.open_bank_credit(CHAT_ID, USER_ID, 1000, 1200, 7)
    query, _args = bank_queries.written[-1]
    assert "credit_visits = 0" in query
    assert "credit_last_visit_at = NULL" in query


@_sync
async def test_полное_погашение_сбрасывает_визиты(bank_queries):
    """Тот же сброс нужен и на закрытии — принудительное взыскание
    (_seize_debt) тоже закрывает кредит через reduce_bank_credit_debt, а не
    отдельной веткой, так что один сброс здесь покрывает оба способа
    закрыть кредит: обычное погашение и принудительное взыскание."""
    bank_queries.row["credit_debt"] = 500
    new_debt = await db_module.reduce_bank_credit_debt(CHAT_ID, USER_ID, 500)
    assert new_debt == 0
    query, _args = bank_queries.written[-1]
    assert "credit_visits = 0" in query
    assert "credit_last_visit_at = NULL" in query


@_sync
async def test_частичное_погашение_не_трогает_визиты(bank_queries):
    """Кредит остаётся открытым — разговор с коллектором не заканчивается,
    поэтому счётчик наглости сбрасывать рано."""
    bank_queries.row["credit_debt"] = 500
    new_debt = await db_module.reduce_bank_credit_debt(CHAT_ID, USER_ID, 200)
    assert new_debt == 300
    query, _args = bank_queries.written[-1]
    assert "credit_visits" not in query
    assert "credit_last_visit_at" not in query


def test_цикл_спрашивает_правила_а_не_считает_сам():
    """Числа и пороги живут в collectors. Посчитай цикл сам — правила
    раздвоятся, и проверить их без базы станет нельзя."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "collectors.should_seize" in src
    assert "collectors.should_visit" in src


def test_порог_втрое_больше_не_зашит_в_цикле():
    """Он переехал в collectors.SEIZE_DEBT_MULTIPLIER; оставшаяся копия
    разошлась бы с ним молча."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "* 3" not in src.replace(" ", "").replace("*3", "* 3")


def test_взыскателю_передают_тот_же_долг_что_сверяли_с_порогом():
    """collectors.should_seize и _seize_debt обязаны получить одну и ту же
    сумму. Разойдись они (например, взыскать успели бы меньше, чем видел
    порог) — кредит закроется не до конца и на следующем проходе цикл найдёт
    тот же долг снова."""
    src = inspect.getsource(bot_module.bank_penalty_loop)
    assert "_seize_debt(chat_id, user_id, debt)" in src


def test_взыскание_закрывает_кредит_и_пеня_больше_не_капает():
    """Единственное место, где ошибка делает игру безвыходной: если после
    взыскания долг остаётся, пеня растёт быстрее любого заработка.

    Сама ветка списания переехала в _seize_debt (bank_penalty_loop теперь
    только решает, пора ли звать взыскание) — поэтому и смотрим в её
    источник, а не в источник цикла."""
    src = inspect.getsource(bot_module._seize_debt)
    assert "reduce_bank_credit_debt" in src, "долг обязан обнуляться"


class _FakeCreditDB:
    """Дублёр db.py ровно в объёме, который трогает _seize_debt.

    reduce_bank_credit_debt повторяет реальное поведение (обнуляет долг и
    снимает срок), не потому что мы проверяем БД, а потому что от этого
    поведения зависит вывод теста: закрытый кредит обязан перестать
    подходить под условие повторной выборки.
    """

    def __init__(self, credit_debt: int):
        self.account = {"credit_debt": credit_debt, "credit_due_at": datetime.utcnow()}
        self.warns = 0
        self.logs = []
        self.coin_changes = []

    async def reduce_bank_credit_debt(self, chat_id, user_id, amount):
        new_debt = max(0, self.account["credit_debt"] - amount)
        self.account["credit_debt"] = new_debt
        if new_debt == 0:
            self.account["credit_due_at"] = None
        return new_debt

    async def add_coins(self, chat_id, user_id, amount):
        self.coin_changes.append(amount)

    async def add_warn(self, chat_id, user_id, *args):
        self.warns += 1
        return self.warns

    async def add_log(self, action, **kwargs):
        self.logs.append((action, kwargs))


async def _noop_send(*args, **kwargs):
    pass


def test_взыскание_обнуляет_долг_полностью(monkeypatch):
    """_seize_debt должен получать и списывать весь текущий долг — частичное
    списание оставило бы кредит открытым и открытым для пени."""
    fake = _FakeCreditDB(credit_debt=900)
    monkeypatch.setattr(bot_module, "db", fake)
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)

    asyncio.run(bot_module._seize_debt(CHAT_ID, USER_ID, 900))

    assert fake.account["credit_debt"] == 0
    assert len(fake.logs) == 1 and fake.logs[0][0] == "bank_credit_force_collected"


def test_взысканный_кредит_не_подходит_под_условие_повторной_выборки(monkeypatch):
    """list_overdue_bank_credits берёт только credit_debt > 0 и
    credit_due_at IS NOT NULL. После _seize_debt оба условия ложны — второй
    проход цикла по тому же кредиту уже ничего не найдёт, и повторного
    взыскания не будет."""
    fake = _FakeCreditDB(credit_debt=900)
    monkeypatch.setattr(bot_module, "db", fake)
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)

    asyncio.run(bot_module._seize_debt(CHAT_ID, USER_ID, 900))

    источник = inspect.getsource(db_module.list_overdue_bank_credits)
    assert "credit_debt > 0" in источник
    assert "credit_due_at IS NOT NULL" in источник
    assert not (fake.account["credit_debt"] > 0)
    assert fake.account["credit_due_at"] is None


class _FakeLoopDB:
    """Дублёр db.py для одного прохода bank_penalty_loop — только та
    поверхность, которую трогает ветка визита коллектора."""

    def __init__(self, row, frozen: bool = False):
        self.row = row
        self._frozen = frozen
        self.visit_calls = 0
        self.penalty_calls = []
        self.seized = []
        self.coin_changes = []

    async def list_overdue_bank_credits(self):
        """Повторяет условие настоящей выборки, а не отдаёт строку всегда.

        Иначе сквозной тест взыскания ничего не доказывает: закрылся кредит
        или нет, на следующем проходе цикл всё равно увидел бы его снова."""
        живой = int(self.row["credit_debt"]) > 0 and self.row["credit_due_at"] is not None
        return [self.row] if живой else []

    async def mark_credit_visit(self, chat_id, user_id):
        self.visit_calls += 1
        return self.visit_calls

    async def apply_bank_credit_penalty(self, chat_id, user_id, new_debt):
        self.penalty_calls.append(new_debt)

    async def get_data(self, key):
        """Заморозка счёта живёт в общем key-value хранилище бота
        (см. bot._frozen_key)."""
        return {"data_key": key, "data_value": "1"} if self._frozen else None

    # --- ниже поверхность _seize_debt: он зовёт db напрямую ---------------
    async def reduce_bank_credit_debt(self, chat_id, user_id, amount):
        """Повторяет настоящее поведение: погашенный до нуля кредит теряет и
        долг, и срок — именно это выводит его из выборки цикла."""
        self.seized.append(amount)
        self.row["credit_debt"] = max(0, int(self.row["credit_debt"]) - amount)
        if not self.row["credit_debt"]:
            self.row["credit_due_at"] = None
        return self.row["credit_debt"]

    async def add_coins(self, chat_id, user_id, amount):
        self.coin_changes.append(amount)
        return amount

    async def add_warn(self, chat_id, user_id, *args):
        return 1

    async def add_log(self, action, **kwargs):
        pass


def _one_pass_row(**overrides):
    row = {
        "chat_id": CHAT_ID, "user_id": USER_ID,
        "credit_debt": 500, "credit_amount": 1000, "credit_penalty_percent": 5.0,
        "credit_due_at": datetime.utcnow() - timedelta(days=3),
        "credit_last_visit_at": None,
        "collector_after_days": 1, "seize_after_days": 0,
    }
    row.update(overrides)
    return row


async def _run_passes(monkeypatch, fake, passes: int = 1):
    """Прогоняет bank_penalty_loop заданное число проходов: подменяет
    asyncio.sleep так, чтобы лишний такт оборвал while True отменой — так же,
    как это сделал бы настоящий asyncio.CancelledError при остановке бота.

    Тактом считается только сон в начале прохода: между сообщениями цикл тоже
    спит (BANK_PENALTY_SEND_PAUSE, чтобы не словить 429), и считать эти паузы
    проходами значило бы обрывать цикл на середине списка должников.

    Возвращает список этих пауз — по нему проверяется, что цикл вообще
    притормаживает между отправками."""
    calls = {"n": 0}
    паузы: list[float] = []

    async def fake_sleep(seconds):
        if seconds != bot_module.BANK_PENALTY_CHECK_INTERVAL:
            паузы.append(seconds)
            return
        calls["n"] += 1
        if calls["n"] > passes:
            raise asyncio.CancelledError()

    async def no_event(chat_id, name):
        return False

    monkeypatch.setattr(bot_module, "db", fake)
    monkeypatch.setattr(bot_module, "event_flag", no_event)
    monkeypatch.setattr(bot_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await bot_module.bank_penalty_loop()
    return паузы


def test_первый_визит_коллектора_наступает_для_ещё_не_посещённого_кредита(monkeypatch):
    """_days_since(None) возвращает 0, а collectors.should_visit трактует 0
    как «уже приходили сегодня» — это разные вещи. Без явной подмены на None
    для непосещённого кредита (credit_last_visit_at IS NULL) коллектор не
    придёт вообще никогда: заводить визит некому, и NULL так и останется
    NULL на следующем проходе."""
    fake = _FakeLoopDB(_one_pass_row())
    sent = []

    async def send(chat_id, text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.visit_calls == 1, "коллектор обязан прийти на первый же просроченный день"
    assert sent and "💼" in sent[0], "первый визит — вежливая ступень (Stage 'polite')"


def test_визит_не_взыскание_кредит_остаётся_открыт(monkeypatch):
    """Визит коллектора — это предупреждение, а не списание: до срока
    взыскания (seize_after_days) кредит обязан остаться на месте."""
    fake = _FakeLoopDB(_one_pass_row())
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.penalty_calls, "пеня по-прежнему должна начисляться дальше — визит её не отменяет"


# --- сквозной прогон цикла через ветку взыскания ----------------------------
#
# Спека называет это риском 3, и не зря: взыскание — единственное место, где
# ошибка делает игру безвыходной. Отдельно проверены и _seize_debt, и ветка
# визита, но стык между ними — тот самый, где решается, закроется ли кредит, —
# до сих пор не проверялся ничем.

def test_цикл_целиком_взыскивает_просроченный_кредит(monkeypatch):
    """Полный прогон bank_penalty_loop по кредиту, которому пора: долг уходит
    в кошелёк (возможно, в минус), кредит закрывается, а следующий проход его
    уже не находит — иначе взыскание повторялось бы каждый час."""
    fake = _FakeLoopDB(_one_pass_row(credit_debt=900, seize_after_days=1))
    sent = []

    async def send(chat_id, text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(_run_passes(monkeypatch, fake, passes=2))

    assert fake.seized == [900], f"взысканий за два прохода: {fake.seized}"
    assert fake.coin_changes == [-900], "долг обязан уйти из банка в кошелёк целиком"
    assert fake.row["credit_debt"] == 0
    assert fake.row["credit_due_at"] is None
    assert fake.penalty_calls == [], "на закрытый кредит пеня капать не должна"
    assert fake.visit_calls == 0, "взыскание вместо визита: разговоры кончились"
    assert len(sent) == 1 and "взыскан" in sent[0]


def test_взыскание_идёт_раньше_визита_и_пени(monkeypatch):
    """Порог по росту долга втрое срабатывает раньше срока коллектора.
    Прийти с уговорами к тому, у кого уже всё забрали, — бессмыслица."""
    fake = _FakeLoopDB(_one_pass_row(
        credit_debt=3000, credit_amount=1000, seize_after_days=0))
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)
    asyncio.run(_run_passes(monkeypatch, fake, passes=2))

    assert fake.seized == [3000]
    assert fake.visit_calls == 0 and fake.penalty_calls == []


# --- одно сообщение в сутки и пауза между отправками ------------------------
#
# Визит коллектора и объявление о пене уходили друг за другом: два сообщения
# про один и тот же долг за один проход, да ещё с разными суммами (визит
# называл долг до пени, объявление — после). А сообщения всем должникам чата
# шли подряд без пауз, и хвост списка Telegram отбивал 429 — те люди о своём
# долге не узнавали вовсе.

def test_за_проход_уходит_одно_сообщение(monkeypatch):
    fake = _FakeLoopDB(_one_pass_row())
    sent = []

    async def send(chat_id, text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert len(sent) == 1, f"должнику ушло {len(sent)} сообщения за сутки"


def test_единственное_сообщение_называет_долг_после_пени(monkeypatch):
    """Пеня начислена — значит и сумма в сообщении обязана быть новой.
    Иначе человек видит одно число, а гасить ему другое."""
    fake = _FakeLoopDB(_one_pass_row(credit_debt=500, credit_penalty_percent=10.0))
    sent = []

    async def send(chat_id, text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.penalty_calls == [550], "пеня 10% на долг 500 — это 550"
    assert "550" in sent[0], f"в сообщении не тот долг: {sent[0]}"
    assert "500 i¢" not in sent[0], f"названа сумма до пени: {sent[0]}"


def test_сутки_отсчитывает_сама_выборка_а_не_цикл():
    """На чём вообще держится «одно сообщение в сутки»: цикл просыпается
    каждый час, и единственность сообщения обеспечивает не он, а условие
    выборки — кредит с уже начисленной сегодня пеней в неё не попадает.
    Пропади это условие, и сообщение уходило бы двадцать четыре раза в
    сутки вместо одного."""
    источник = inspect.getsource(db_module.list_overdue_bank_credits)
    assert "credit_last_penalty_at" in источник and "INTERVAL 1 DAY" in источник, (
        "выборка просроченных кредитов перестала ограничивать пеню сутками")
    # И вторая половина той же пары: без отметки времени условие выше
    # никогда не станет ложным.
    assert "credit_last_penalty_at = UTC_TIMESTAMP()" in inspect.getsource(
        db_module.apply_bank_credit_penalty), "начисление пени не отмечает дату"


def test_между_отправками_цикл_ждёт(monkeypatch):
    """Просрочек в чате бывает два десятка — без паузы хвост уедет в 429."""
    fake = _FakeLoopDB(_one_pass_row())
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)
    паузы = asyncio.run(_run_passes(monkeypatch, fake))

    assert паузы == [bot_module.BANK_PENALTY_SEND_PAUSE]
    assert 0 < bot_module.BANK_PENALTY_SEND_PAUSE < bot_module.BANK_PENALTY_CHECK_INTERVAL


# --- кого цикл не трогает вовсе --------------------------------------------
#
# Спека требовала прямо: «Замороженному коллектор не приходит и взыскания
# нет: человек лишён возможности зарабатывать, а значит и выбраться».
# Заморозка стоит на всём заработке разом (см. is_account_frozen по всему
# bot.py), поэтому загнанный ею в минус не может сделать вообще ничего.

def test_замороженного_цикл_пропускает_целиком(monkeypatch):
    """Ни визита, ни пени, ни взыскания: зарабатывать ему нечем, и любое
    из трёх делает положение безвыходным."""
    fake = _FakeLoopDB(_one_pass_row(seize_after_days=1), frozen=True)
    sent = []

    async def send(chat_id, text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(bot_module.bot, "send_message", send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.visit_calls == 0, "коллектор пришёл к замороженному"
    assert fake.penalty_calls == [], "пеня начислена замороженному"
    assert fake.seized == [], "долг взыскан у того, кому нечем зарабатывать"
    assert sent == [], "замороженному ушло сообщение о долге"


def test_незамороженного_цикл_обрабатывает(monkeypatch):
    """Обратная половина: проверка не должна выключать цикл всем подряд."""
    fake = _FakeLoopDB(_one_pass_row(), frozen=False)
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.visit_calls == 1
    assert fake.penalty_calls


def test_владельца_с_бесконечными_деньгами_взыскание_не_трогает(monkeypatch):
    """«+бесконечность» означает, что монеты у человека не расходуются
    вовсе, — долга у него быть не может, и взыскивать не с чего."""
    fake = _FakeLoopDB(_one_pass_row(seize_after_days=1))
    monkeypatch.setattr(bot_module.bot, "send_message", _noop_send)
    monkeypatch.setattr(bot_module, "INFINITE_MONEY_USERS", {USER_ID})
    asyncio.run(_run_passes(monkeypatch, fake))

    assert fake.seized == [], "долг взыскан у владельца с «+бесконечностью»"
    assert fake.visit_calls == 0 and fake.penalty_calls == []


# --- минус в кошельке объяснён, кредит поверх него не дают ------------------
#
# Взыскание списывает долг с баланса целиком, даже уводя его в минус
# (см. _seize_debt). Дальше человек видит отрицательный остаток без единого
# слова — неотличимо от поломки бота.

def test_кошелёк_объясняет_минус():
    """Отрицательный баланс без пояснения читается как поломка бота."""
    src = inspect.getsource(bot_module._farm_balance_text)
    assert "coins" in src
    assert "взыскан" in src.lower() or "долг" in src.lower(), (
        "в кошельке нет объяснения, откуда минус")


def test_кредит_при_минусе_не_дают():
    src = inspect.getsource(bot_module.cmd_bank_credit)
    assert "< 0" in src or "минус" in src.lower(), (
        "кредит выдаётся поверх непогашенного взыскания")


# --- минус объяснён и в карточках -------------------------------------------
#
# Свой кошелёк объясняет минус подробно, а профиль и досье показывали голую
# цифру со знаком. В досье это особенно глухо: про ЧУЖОЙ минус узнать больше
# неоткуда — в чужой кошелёк за объяснением не заглянешь.

@pytest.mark.parametrize("баланс", [0, 1, 100_000])
def test_плюсовому_балансу_пометки_нет(баланс):
    """Пометка появляется только там, где есть что объяснять: иначе она
    висела бы в каждой карточке чата."""
    assert bot_module.debt_note(баланс) == ""


@pytest.mark.parametrize("баланс,сумма", [(-1, "1"), (-500, "500"), (-50_000, "50 000")])
def test_минус_назван_суммой_долга(баланс, сумма):
    """Долг называется положительным числом: «долг −50 000» читается как
    «минус долг», то есть наоборот."""
    note = bot_module.debt_note(баланс)
    assert сумма in note
    assert "-" not in note and "−" not in note


def test_пометка_называет_причину():
    """Без слова «кредит» пометка объясняет не больше, чем сама цифра."""
    note = bot_module.debt_note(-500).lower()
    assert "кредит" in note and "долг" in note


@pytest.mark.parametrize("карточка", ["build_profile_card", "cmd_dossier"])
def test_обе_карточки_зовут_общую_пометку(карточка):
    """Одна формулировка на оба места: разъехавшись, копии объяснили бы одно
    и то же по-разному, а третье место (кошелёк) добавило бы третий вариант."""
    src = inspect.getsource(getattr(bot_module, карточка))
    assert "debt_note(" in src, f"{карточка} показывает минус без объяснения"
