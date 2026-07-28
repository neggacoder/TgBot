"""Экономика при отрицательном балансе.

Принудительное взыскание (см. collectors.py и _seize_debt в bot.py) сделало
минус штатным состоянием кошелька. Вся экономика вокруг писалась в
предположении «монет не меньше нуля», и в местах, где ноль считался дном
любого баланса, долг стал стираться сам собой. Здесь проверяется, что этого
больше не происходит — и что плюсовому балансу от починки не досталось ни
монеты разницы.
"""

from __future__ import annotations

import asyncio
import functools
import re

import pytest

import db as db_module
import robbery


CHAT_ID = -1001112223334
USER_ID = 42


def _sync(fn):
    """pytest-asyncio в проекте нет: соседние файлы гоняют корутины через
    asyncio.run (см. test_debt_collection.py)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


# --- потеря при провале ограбления/налёта ----------------------------------

@pytest.mark.parametrize("баланс", [-1, -50, -50_000, -1_000_000])
def test_провал_при_минусе_ничего_не_отнимает(баланс):
    """Процент от отрицательного баланса — отрицательное число, а
    отрицательная «потеря» в налёте превращается в add_coins(-loss), то есть
    в выплату должнику за провал."""
    assert robbery.compute_fail_loss(баланс, False, False) == 0
    assert robbery.compute_fail_loss(баланс, False, True) == 0


@pytest.mark.parametrize("баланс", [-1, -50_000])
def test_провал_никогда_не_приносит_дохода(баланс):
    """Ровно тот вид, в котором налёт использует результат: add_coins(-loss).
    Стоит loss уйти в минус — и провал становится заработком по кулдауну."""
    for свинка in (False, True):
        assert -robbery.compute_fail_loss(баланс, False, свинка) <= 0


@pytest.mark.parametrize("баланс,ожидаем,ожидаем_свинка", [
    (0, 0, 0),
    (1, 0, 0),          # round(0.4) → 0 по банковскому округлению, как и было
    (100, 40, 20),
    (1000, 400, 200),
    (12_345, 4938, 2469),
])
def test_плюсовой_баланс_теряет_столько_же_сколько_раньше(баланс, ожидаем, ожидаем_свинка):
    """Нижняя граница не должна была тронуть обычную игру: числа взяты из
    старой формулы round(balance * percent / 100)."""
    assert robbery.compute_fail_loss(баланс, False, False) == ожидаем
    assert robbery.compute_fail_loss(баланс, False, True) == ожидаем_свинка


def test_счастливая_монета_по_прежнему_спасает_целиком():
    assert robbery.compute_fail_loss(10_000, True, False) == 0


# --- сколько можно унести ---------------------------------------------------

@pytest.mark.parametrize("баланс", [0, -1, -50_000])
def test_с_должника_унести_нечего(баланс):
    """Через зеркало жертвы в расчёт приходит баланс самого грабителя, и он
    бывает отрицательным. max(1, ...) отдавал бы монету оттуда, где её нет."""
    assert robbery.compute_steal_amount(баланс, False) == 0
    assert robbery.compute_steal_amount(баланс, True) == 0


@pytest.mark.parametrize("баланс", [1, 100, 10_000])
def test_с_плюсового_кошелька_уносят_как_раньше(баланс):
    """Границы формулы не изменились: не меньше монеты и не больше того,
    что лежит в кошельке."""
    for свинка in (False, True):
        унесли = robbery.compute_steal_amount(баланс, свинка)
        assert 1 <= унесли <= баланс


# --- нижняя граница в самом SQL --------------------------------------------
#
# MySQL тесты не поднимают (см. tests/conftest.py), а проверять надо именно
# арифметику UPDATE: клампа в коде мало, потому что «списать ноль» с
# отрицательного баланса через GREATEST(coins - 0, 0) обнуляло долг целиком.
# Поэтому перехватываем текст запроса и считаем по нему — подмени кто-нибудь
# нижнюю границу обратно на 0, и числа разойдутся.

_SET_RE = re.compile(r"SET coins = (.+?) WHERE")


def _eval_wallet_set(query: str, coins: int, amount: int) -> int:
    """Во что превратится баланс по САМОМУ тексту UPDATE.

    GREATEST/LEAST в MySQL — это max/min питона на целых числах, так что
    выражение считается один в один, без базы."""
    выражение = _SET_RE.search(" ".join(query.split())).group(1)
    выражение = выражение.replace("%s", str(amount))
    выражение = выражение.replace("GREATEST", "max").replace("LEAST", "min")
    выражение = выражение.replace("coins", str(coins))
    return int(eval(выражение))  # noqa: S307 — считаем свой же SQL, не чужой ввод


@pytest.fixture
def кошельковые_запросы(monkeypatch):
    """Перехватывает UPDATE-ы economy_wallets, не поднимая базы."""
    запросы: list[tuple[str, tuple]] = []

    async def fake_execute(query, args=()):
        собранный = " ".join(query.split())
        if "economy_wallets SET coins" in собранный:
            запросы.append((собранный, args))
        return 1

    async def fake_fetchone(query, args=()):
        return {"coins": 0, "chat_id": CHAT_ID, "user_id": USER_ID,
                "star_level": 0, "total_farms": 0, "last_farm_at": None,
                "attempts": 0, "successes": 0, "fails": 0}

    monkeypatch.setattr(db_module, "_execute", fake_execute)
    monkeypatch.setattr(db_module, "_fetchone", fake_fetchone)
    return запросы


@_sync
async def test_провал_ограбления_не_стирает_долг(кошельковые_запросы):
    """Ключевой случай: потеря = 0 (с должника брать нечего), и списание
    нуля обязано оставить долг на месте, а не обнулить его."""
    await db_module.apply_robbery_fail(CHAT_ID, USER_ID, 0)
    query, args = кошельковые_запросы[-1]
    assert _eval_wallet_set(query, coins=-50_000, amount=args[0]) == -50_000


@_sync
async def test_списание_с_должника_не_углубляет_яму(кошельковые_запросы):
    """Обратная сторона той же границы: у должника и отнимать нечего —
    списание не должно уводить его ещё ниже."""
    await db_module.apply_robbery_fail(CHAT_ID, USER_ID, 700)
    query, args = кошельковые_запросы[-1]
    assert _eval_wallet_set(query, coins=-50_000, amount=args[0]) == -50_000


@_sync
@pytest.mark.parametrize("было,списываем,станет", [
    (1000, 400, 600),
    (1000, 1000, 0),
    (1000, 4000, 0),      # больше, чем есть — дном остаётся ноль, как и раньше
    (0, 400, 0),
])
async def test_плюсовой_кошелёк_списывается_как_раньше(
        кошельковые_запросы, было, списываем, станет):
    await db_module.apply_robbery_fail(CHAT_ID, USER_ID, списываем)
    query, args = кошельковые_запросы[-1]
    assert _eval_wallet_set(query, coins=было, amount=args[0]) == станет


@_sync
@pytest.mark.parametrize("было,выплата,станет", [
    (-50_000, 300, -49_700),   # выплата гасит часть долга, а не весь долг
    (-300, 300, 0),            # ровно в ноль — долг закрыт честно
    (-100, 300, 200),
    (0, 300, 300),
    (1000, 300, 1300),
])
async def test_массовая_выплата_складывается_а_не_обнуляет(
        кошельковые_запросы, было, выплата, станет):
    """«Раздача» и «Благотворительность» платят через add_coins_to_users, и
    благотворительность выбирает беднейших — должник в её списке первый."""
    await db_module.add_coins_to_users(CHAT_ID, [USER_ID], выплата)
    query, args = кошельковые_запросы[-1]
    assert _eval_wallet_set(query, coins=было, amount=args[0]) == станет


# --- топ по монетам ---------------------------------------------------------
#
# Спека: «В топе по монетам должники не прячутся: показываются как есть».
# Условие coins > 0 писалось, когда минус был невозможен, и отсекало нули;
# с приходом взыскания оно стало прятать людей — вместе с занижением счётчика
# участников и враньём «Пока ни у кого нет i¢» там, где у всех отняли всё.

_УСЛОВИЕ_RE = re.compile(r"AND (coins\s*(?:<>|!=|>=|>|<=|<)\s*-?\d+)")


def _попадает_в_топ(query: str, coins: int) -> bool:
    """Пройдёт ли кошелёк с таким балансом условие САМОГО запроса."""
    условие = _УСЛОВИЕ_RE.search(" ".join(query.split())).group(1)
    return bool(eval(условие.replace("<>", "!=").replace("coins", str(coins))))


@pytest.fixture
def запросы_топа(monkeypatch):
    """Оба запроса топа: счётчик участников и сама страница."""
    запросы: list[str] = []

    async def fake_fetchone(query, args=()):
        запросы.append(" ".join(query.split()))
        return {"total": 0}

    async def fake_fetchall(query, args=()):
        запросы.append(" ".join(query.split()))
        return []

    monkeypatch.setattr(db_module, "_fetchone", fake_fetchone)
    monkeypatch.setattr(db_module, "_fetchall", fake_fetchall)
    return запросы


@_sync
async def test_должник_виден_в_топе_и_в_счётчике(запросы_топа):
    """Оба запроса, а не один: разойдись они, человек пропал бы из списка,
    но остался в числе участников (или наоборот)."""
    await db_module.list_coins_top(CHAT_ID)
    assert len(запросы_топа) == 2
    for query in запросы_топа:
        assert _попадает_в_топ(query, -50_000), f"должник спрятан: {query}"
        assert _попадает_в_топ(query, -1), f"должник спрятан: {query}"


@_sync
async def test_пустые_кошельки_в_топ_по_прежнему_не_лезут(запросы_топа):
    """Строка кошелька заводится при первом обращении к экономике, так что
    нулей в чате больше, чем ненулевых, — они растянулись бы на страницы."""
    await db_module.list_coins_top(CHAT_ID)
    for query in запросы_топа:
        assert not _попадает_в_топ(query, 0), f"ноль пролез в топ: {query}"


@_sync
async def test_обычный_кошелёк_в_топе_остался(запросы_топа):
    await db_module.list_coins_top(CHAT_ID)
    for query in запросы_топа:
        assert _попадает_в_топ(query, 1)
        assert _попадает_в_топ(query, 100_000)


@_sync
async def test_должники_стоят_внизу_списка(запросы_топа):
    """Сортировка по убыванию — она же и ставит их после всех остальных,
    так что видимость должников не портит верх топа."""
    await db_module.list_coins_top(CHAT_ID)
    страница = next(q for q in запросы_топа if "ORDER BY" in q)
    assert "ORDER BY coins DESC" in страница


@_sync
async def test_конфискация_не_обнуляет_долг(кошельковые_запросы):
    """take_coins_up_to живёт по тем же правилам: сумма считается от
    прочитанного мгновением раньше баланса, и ноль дном для должника
    означал бы прощение долга гонкой."""
    await db_module.take_coins_up_to(CHAT_ID, USER_ID, 500)
    query, args = кошельковые_запросы[-1]
    assert _eval_wallet_set(query, coins=-50_000, amount=args[0]) == -50_000
    assert _eval_wallet_set(query, coins=1000, amount=args[0]) == 500
