"""Новые списки с листанием: «мои титулы», «профессии», топ по стрикам, топ монет.

Проверяется то, ради чего они и заводились: показать нужное, а не всё подряд,
и не пересчитывать тяжёлый рейтинг на каждое нажатие стрелки.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 555


def _returns(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


# --- мои титулы ------------------------------------------------------------

@pytest.fixture
def _titles(monkeypatch):
    def setup(owned, active=None):
        monkeypatch.setattr(bot_module.db, "list_user_titles", _returns(owned), raising=False)
        monkeypatch.setattr(bot_module.db, "get_profile_card",
                            _returns({"active_title": active}), raising=False)
    return setup


def test_без_титулов_объясняет_как_получить(_titles):
    _titles([])
    text, kb = asyncio.run(bot_module.my_titles_page(CHAT_ID, USER_ID, 0))
    assert "нет ни одного титула" in text
    assert "титул купить" in text
    assert kb is None


def test_показывает_только_свои_и_отмечает_надетый(_titles):
    _titles([{"title_key": "a", "name": "Первый"}, {"title_key": "b", "name": "Второй"}], active="b")
    text, kb = asyncio.run(bot_module.my_titles_page(CHAT_ID, USER_ID, 0))
    assert "Первый" in text and "Второй" in text
    assert "надет" in text.split("Второй")[1].split("\n")[0], "пометка должна стоять у активного"
    assert kb is None, "две строки на одной странице — кнопки листания не нужны"


def test_длинный_список_листается(_titles):
    owned = [{"title_key": f"k{i}", "name": f"Титул {i}"} for i in range(20)]
    _titles(owned)
    text, kb = asyncio.run(bot_module.my_titles_page(CHAT_ID, USER_ID, 0))
    assert kb is not None
    assert "Титул 0" in text and "Титул 19" not in text

    last = asyncio.run(bot_module.my_titles_page(CHAT_ID, USER_ID, 99))   # за пределами
    assert "Титул 19" in last[0], "страница за пределами должна прижаться к последней"


# --- профессии -------------------------------------------------------------

@pytest.fixture
def _prof_chat(monkeypatch):
    def setup(days_in_chat=0, coins=0, current=None):
        first_seen = datetime.utcnow() - timedelta(days=days_in_chat)
        monkeypatch.setattr(bot_module.db, "get_member_first_seen",
                            _returns(first_seen), raising=False)
        monkeypatch.setattr(bot_module.db, "get_wallet", _returns({"coins": coins}), raising=False)
        monkeypatch.setattr(bot_module.db, "get_profession_stats",
                            _returns({"profession_key": current}), raising=False)
    return setup


def _all_profession_pages() -> str:
    size = bot_module.PROFESSIONS_PAGE_SIZE
    pages = (len(bot_module.PROFESSIONS) + size - 1) // size
    return "".join(
        asyncio.run(bot_module.professions_page(CHAT_ID, USER_ID, p))[0] for p in range(pages)
    )


def test_каталог_покрывает_все_профессии(_prof_chat):
    """Ни одна профессия не должна потеряться между страницами."""
    _prof_chat()
    seen = _all_profession_pages()
    for key, prof in bot_module.PROFESSIONS.items():
        assert key in seen, f"профессия {key} не попала ни на одну страницу"
        assert prof["name"] in seen


def test_первая_страница_листается(_prof_chat):
    _prof_chat()
    _, kb = asyncio.run(bot_module.professions_page(CHAT_ID, USER_ID, 0))
    assert kb is not None, "профессий больше, чем помещается на страницу"


def test_новичку_видно_чего_не_хватает(_prof_chat):
    _prof_chat(days_in_chat=0, coins=0)
    text, _ = asyncio.run(bot_module.professions_page(CHAT_ID, USER_ID, 0))
    assert "🟢 доступна" in text, "уборщик доступен без требований"
    assert "нужен стаж" in _all_profession_pages()


def test_своя_профессия_отмечена(_prof_chat):
    _prof_chat(days_in_chat=1000, coins=1_000_000, current="уборщик")
    text, _ = asyncio.run(bot_module.professions_page(CHAT_ID, USER_ID, 0))
    assert "✅ ваша" in text


# --- топ по стрикам --------------------------------------------------------

@pytest.fixture
def _streaks(monkeypatch):
    """Чат с N участниками, у i-го — стрик на i дней. Считаем походы в базу."""
    def setup(count):
        calls = {"days": 0}
        today = bot_module.utc_today()
        users = [{"user_id": i, "full_name": f"Ю{i}", "username": None} for i in range(1, count + 1)]

        async def list_recent(chat_id, limit=300):
            return users

        async def list_active_days(chat_id, user_id):
            calls["days"] += 1
            return [today - timedelta(days=d) for d in range(user_id)]

        monkeypatch.setattr(bot_module.db, "list_recent_active_users", list_recent, raising=False)
        monkeypatch.setattr(bot_module.db, "list_active_days", list_active_days, raising=False)
        bot_module._streak_top_cache.clear()
        return calls
    yield setup
    bot_module._streak_top_cache.clear()


def test_пустой_топ_говорит_прямо(_streaks):
    _streaks(0)
    text, kb = asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    assert "нет активного стрика" in text and kb is None


def test_топ_листается_и_нумерация_сквозная(_streaks):
    _streaks(25)
    first, kb = asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    assert kb is not None, "25 участников — одной страницей не влезают"
    assert "🥇" in first and "25 дн. подряд" in first          # самый длинный стрик сверху
    second, _ = asyncio.run(bot_module.streak_top_page(CHAT_ID, 1))
    assert "11." in second, "нумерация продолжается со второй страницы, а не начинается заново"
    assert "🥇" not in second


def test_листание_не_пересчитывает_рейтинг(_streaks):
    """Ради этого кэш и заведён: без него каждая стрелка — до 300 запросов."""
    calls = _streaks(25)
    asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    after_first = calls["days"]
    assert after_first == 25
    for page in (1, 2, 0, 1):
        asyncio.run(bot_module.streak_top_page(CHAT_ID, page))
    assert calls["days"] == after_first, "рейтинг должен браться из кэша"


def test_кэш_протухает(_streaks, monkeypatch):
    calls = _streaks(5)
    asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    stamp, ranking = bot_module._streak_top_cache[CHAT_ID]
    bot_module._streak_top_cache[CHAT_ID] = (
        stamp - bot_module.STREAK_TOP_CACHE_TTL - timedelta(seconds=1), ranking,
    )
    asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    assert calls["days"] == 10, "после протухания рейтинг считается заново"


def test_кэш_свой_у_каждого_чата(_streaks):
    calls = _streaks(5)
    asyncio.run(bot_module.streak_top_page(CHAT_ID, 0))
    asyncio.run(bot_module.streak_top_page(CHAT_ID - 1, 0))
    assert calls["days"] == 10, "чужой чат не должен получать чужой рейтинг из кэша"


# --- топ монет -------------------------------------------------------------

@pytest.fixture
def _wallets(monkeypatch):
    """Чат с N ненулевыми кошельками. Заглушка режет страницу сама — так же,
    как это делает SQL с LIMIT/OFFSET, — и запоминает, с каким offset её
    позвали: сквозная нумерация держится именно на нём."""
    def setup(count):
        seen = {"offsets": []}
        rows = [{"user_id": 1000 + i, "coins": (count - i) * 100, "star_level": 0}
                for i in range(count)]

        async def list_coins_top(chat_id, limit=10, offset=0):
            seen["offsets"].append(offset)
            return rows[offset:offset + limit], count

        monkeypatch.setattr(bot_module.db, "list_coins_top", list_coins_top, raising=False)
        monkeypatch.setattr(bot_module, "display_name_by_id",
                            _returns("Кто-то"), raising=False)
        return seen
    return setup


def test_пустой_топ_монет_говорит_прямо(_wallets):
    _wallets(0)
    text, kb = asyncio.run(bot_module.farm_top_page(CHAT_ID, 0))
    assert "Пока ни у кого нет" in text and kb is None


def test_короткий_топ_монет_без_кнопок(_wallets):
    """Одна страница — листать нечего, кнопки были бы мусором."""
    _wallets(4)
    text, kb = asyncio.run(bot_module.farm_top_page(CHAT_ID, 0))
    assert "4 участников" in text
    assert kb is None


def test_топ_монет_листается_и_нумерация_сквозная(_wallets):
    seen = _wallets(25)

    def places(text):
        """Номера мест на странице. Сравнивать подстрокой нельзя: «1. » входит
        и в «11. », из-за чего проверка «первого места тут нет» врала бы."""
        return [line.split(".", 1)[0] for line in text.splitlines()
                if line[:1].isdigit()]

    first, kb = asyncio.run(bot_module.farm_top_page(CHAT_ID, 0))
    assert places(first) == [str(n) for n in range(1, 11)]
    assert [b.text for b in kb.inline_keyboard[0]] == ["1/3", "➡️"]

    second, kb2 = asyncio.run(bot_module.farm_top_page(CHAT_ID, 1))
    assert places(second) == [str(n) for n in range(11, 21)]
    assert [b.text for b in kb2.inline_keyboard[0]] == ["⬅️", "2/3", "➡️"]

    last, kb3 = asyncio.run(bot_module.farm_top_page(CHAT_ID, 2))
    assert places(last) == [str(n) for n in range(21, 26)]
    assert [b.text for b in kb3.inline_keyboard[0]] == ["⬅️", "3/3"]
    assert seen["offsets"] == [0, 10, 20], "страница должна браться offset'ом, а не срезом всего топа"


def test_смытая_страница_откатывается_на_первую(_wallets):
    """Пока человек листал, кто-то потратил монеты и топ укоротился. Показывать
    пустоту с кнопкой «назад» некуда — возвращаемся на первую страницу."""
    seen = _wallets(5)
    text, kb = asyncio.run(bot_module.farm_top_page(CHAT_ID, 7))
    assert "1. " in text
    assert kb is None
    assert seen["offsets"] == [70, 0]


def test_таймер_получает_топ_монет_строкой(_wallets):
    """«топ монет» умеет выполняться по таймеру (TIMER_RUNNABLE_COMMANDS), а
    исполнитель обязан вернуть именно строку — клавиатуру приложить некуда."""
    _wallets(25)
    text = asyncio.run(bot_module._farm_top_text(CHAT_ID))
    assert isinstance(text, str)
    assert "Топ по коинам" in text

    runner = bot_module.TIMER_RUNNABLE_COMMANDS["топ монет"]
    assert isinstance(asyncio.run(runner(CHAT_ID, USER_ID)), str)
