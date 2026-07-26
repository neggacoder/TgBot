"""Бизнесы: каталог, уровни, налог, накопление копилки.

Здесь проверяются ЧИСЛА, а не команды: спецификацию переносили в код руками,
а пятнадцать клеток «доход/потолок» — ровно то место, где опечатка проходит
незамеченной и всплывает через месяц перекошенной экономикой.
"""

from __future__ import annotations

import pytest

import businesses as B


# --- каталог ---------------------------------------------------------------

def test_каталог_на_месте():
    assert [b.key for b in B.BUSINESSES] == [
        "shaurma", "magazin", "juvelirka", "avtosalon", "aeroport",
    ]
    assert len(B.BY_KEY) == len(B.BUSINESSES)


@pytest.mark.parametrize("key, price", [
    ("shaurma", 12_500), ("magazin", 25_000), ("juvelirka", 50_000),
    ("avtosalon", 75_000), ("aeroport", 100_000),
])
def test_цены_из_спецификации(key, price):
    assert B.BY_KEY[key].price == price


@pytest.mark.parametrize("key, expected", [
    ("shaurma",   ((250, 1_000), (300, 1_200), (500, 2_000))),
    ("magazin",   ((500, 2_000), (750, 3_000), (1_000, 4_000))),
    ("juvelirka", ((1_250, 5_000), (1_500, 6_500), (2_000, 8_000))),
    ("avtosalon", ((2_000, 8_000), (2_500, 10_000), (3_000, 12_000))),
    ("aeroport",  ((3_250, 13_000), (3_750, 15_000), (4_250, 17_000))),
])
def test_доход_и_потолки_по_уровням(key, expected):
    item = B.BY_KEY[key]
    for level, (income, cap) in enumerate(expected, start=1):
        assert item.income(level) == income, (key, level)
        assert item.cap(level) == cap, (key, level)


def test_потолок_это_четыре_часа_дохода_кроме_одной_клетки():
    """У 14 клеток из 15 потолок ровно вчетверо больше часового дохода.
    Исключение одно и оно подтверждённое: Ювелирная на 2 уровне копит 6500,
    а не 6000. Если этот тест упал на ДРУГОЙ клетке — в таблицу заехала
    опечатка, а не новая задумка.
    """
    exceptions = {("juvelirka", 2): 6_500}
    for item in B.BUSINESSES:
        for level in (1, 2, 3):
            special = exceptions.get((item.key, level))
            if special is not None:
                assert item.cap(level) == special
                continue
            assert item.cap(level) == item.income(level) * 4, (item.key, level)


def test_доход_и_потолок_растут_с_уровнем():
    for item in B.BUSINESSES:
        assert item.income(1) < item.income(2) < item.income(3), item.key
        assert item.cap(1) < item.cap(2) < item.cap(3), item.key


def test_уровень_за_границами_не_ломает_расчёт():
    """Из базы может прийти что угодно — 0 или 99. Считаем по ближайшему
    допустимому уровню, но не падаем."""
    item = B.BY_KEY["shaurma"]
    assert item.income(0) == item.income(1)
    assert item.income(99) == item.income(3)
    assert item.cap(-5) == item.cap(1)


# --- цена апгрейда и выкуп -------------------------------------------------

@pytest.mark.parametrize("key", [b.key for b in B.BUSINESSES])
def test_апгрейд_стоит_20_и_50_процентов(key):
    item = B.BY_KEY[key]
    assert item.upgrade_cost(2) == int(item.price * 0.20)
    assert item.upgrade_cost(3) == int(item.price * 0.50)
    assert item.upgrade_cost(4) == 0, "выше третьего уровня подниматься некуда"


@pytest.mark.parametrize("key", [b.key for b in B.BUSINESSES])
def test_бот_возвращает_70_процентов(key):
    item = B.BY_KEY[key]
    assert item.buyback() == int(item.price * 0.70)
    assert item.buyback() < item.price, "выкуп обязан быть дешевле покупки"


# --- налог -----------------------------------------------------------------

@pytest.mark.parametrize("amount, tax", [
    (0, 0),
    (100, 5),          # 100 × 5%
    (2_000, 100),      # вся первая ступень
    (3_000, 200),      # 2000×5% + 1000×10%
    (5_000, 400),      # 2000×5% + 3000×10%
    (10_000, 1_150),   # + 5000×15%
    (17_000, 2_550),   # + 7000×20% — полная копилка Аэропорта 3 ур.
])
def test_налог_считается_по_частям(amount, tax):
    assert B.tax_for(amount) == tax


def test_налог_не_берётся_с_пустого():
    assert B.tax_for(0) == 0
    assert B.tax_for(-100) == 0


def test_больше_забрал_больше_получил():
    """Главная причина брать прогрессию ПО ЧАСТЯМ, а не по границе: при
    «одна ставка на всю сумму» на каждой границе появлялся бы обрыв, где
    забрать больше означало получить меньше, и игроки бы недобирали нарочно.
    """
    previous = -1
    for amount in range(0, 17_001, 7):
        net = amount - B.tax_for(amount)
        assert net >= previous, f"обрыв на сумме {amount}"
        previous = net


def test_налог_никогда_не_больше_суммы():
    for amount in (1, 999, 2_001, 9_999, 17_000, 1_000_000):
        assert 0 <= B.tax_for(amount) < amount


def test_крупная_сумма_облагается_сильнее_мелкой_в_долях():
    """Смысл прогрессии: ларёк платит меньше в процентах, чем аэропорт."""
    small = B.tax_for(1_000) / 1_000
    large = B.tax_for(17_000) / 17_000
    assert small < large


# --- накопление копилки ----------------------------------------------------

def test_копилка_растёт_по_часам():
    item = B.BY_KEY["shaurma"]                      # 250 i¢/час, потолок 1000
    assert B.accrued_now(1, item, 0, 0) == 0
    assert B.accrued_now(1, item, 0, 1) == 250
    assert B.accrued_now(1, item, 0, 2.5) == 625    # дробные часы тоже считаются


def test_копилка_упирается_в_потолок():
    item = B.BY_KEY["shaurma"]
    assert B.accrued_now(1, item, 0, 4) == 1_000
    assert B.accrued_now(1, item, 0, 100) == 1_000, "сутки простоя не дают больше потолка"


def test_копилка_учитывает_уже_накопленное():
    item = B.BY_KEY["shaurma"]
    assert B.accrued_now(1, item, 500, 1) == 750
    assert B.accrued_now(1, item, 900, 1) == 1_000, "и всё равно не выше потолка"


def test_отрицательное_время_не_отматывает_копилку():
    """Часы бота и базы могут разъехаться — накопленное от этого пропасть
    не должно."""
    item = B.BY_KEY["shaurma"]
    assert B.accrued_now(1, item, 400, -5) == 400


def test_апгрейд_поднимает_потолок_для_уже_накопленного():
    """Копилка была полна на 1 уровне; после апгрейда потолок выше и деньги
    снова пошли, а не сгорели."""
    item = B.BY_KEY["shaurma"]
    full_at_1 = B.accrued_now(1, item, 0, 10)
    assert full_at_1 == 1_000
    assert B.accrued_now(2, item, full_at_1, 1) == 1_200


def test_сколько_часов_до_полной():
    item = B.BY_KEY["shaurma"]
    assert B.hours_to_full(1, item, 0) == pytest.approx(4.0)
    assert B.hours_to_full(1, item, 750) == pytest.approx(1.0)
    assert B.hours_to_full(1, item, 1_000) == 0.0
    assert B.hours_to_full(1, item, 5_000) == 0.0, "переполненная — не отрицательное время"


# --- ввод названий ---------------------------------------------------------

@pytest.mark.parametrize("raw, key", [
    ("shaurma", "shaurma"), ("шаурма", "shaurma"), ("ЛАРЁК", "shaurma"),
    ("магазин", "magazin"), ("продуктовый", "magazin"),
    ("ювелирка", "juvelirka"), ("Ювелирная", "juvelirka"),
    ("автосалон", "avtosalon"), ("авто", "avtosalon"),
    ("аэропорт", "aeroport"), ("  Аэро  ", "aeroport"),
])
def test_бизнес_находится_по_ключу_и_по_русски(raw, key):
    found = B.resolve(raw)
    assert found is not None and found.key == key


@pytest.mark.parametrize("raw", ["", "   ", "казино", "шаурмаа", None])
def test_чужое_слово_не_считается_бизнесом(raw):
    assert B.resolve(raw) is None


# --- поломки ---------------------------------------------------------------

def test_у_каждого_бизнеса_есть_свои_поломки():
    """Общая заглушка «поломка» скучна — у шаурмичной должен ломаться гриль,
    а не «оборудование вообще»."""
    for item in B.BUSINESSES:
        kinds = B.BREAKDOWNS.get(item.key)
        assert kinds, item.key
        assert all(k and isinstance(k, str) for k in kinds)


def test_ремонт_стоит_ровно_одну_полную_копилку():
    """Считается от cap(), а не от «доход × 4»: у Ювелирной на 2 уровне
    потолок выше четырёх часов, и cap() держит это исключение сам."""
    for item in B.BUSINESSES:
        for level in (1, 2, 3):
            assert B.repair_cost(item, level) == item.cap(level)


def test_ремонт_дороже_у_дорогих_бизнесов():
    assert B.repair_cost(B.BY_KEY["shaurma"], 1) < B.repair_cost(B.BY_KEY["aeroport"], 1)


# --- срочные предложения ---------------------------------------------------

def test_у_каждого_бизнеса_есть_свои_предложения():
    for item in B.BUSINESSES:
        assert B.OFFERS.get(item.key), item.key


def test_предложение_выгодно_но_не_бесплатно():
    """Смысл механики: вложение должно окупаться, иначе его никто не возьмёт,
    но не быть подарком."""
    for item in B.BUSINESSES:
        for level in (1, 2, 3):
            cost = B.offer_cost(item, level)
            profit = B.offer_profit(item, level)
            assert cost > 0
            assert profit > cost, (item.key, level, cost, profit)


def test_надбавка_считается_по_кускам_времени():
    """Самое хрупкое место всей механики: копилка считается лениво, и между
    двумя обращениями надбавка могла и начаться, и кончиться. Оба куска
    обязаны посчитаться по своим ставкам."""
    item = B.BY_KEY["aeroport"]          # 3250 i¢/час, потолок 13000
    # 2 часа с надбавкой +50% и 1 час без неё
    expected = int(3250 * 1.5 * 2 + 3250 * 1)
    assert B.accrued_with_boost(1, item, 0, normal_hours=1, boosted_hours=2) == expected


def test_надбавка_не_пробивает_потолок():
    item = B.BY_KEY["shaurma"]           # потолок 1000 на 1 уровне
    assert B.accrued_with_boost(1, item, 0, normal_hours=0, boosted_hours=100) == 1_000


def test_без_надбавки_считается_как_обычно():
    """Нулевой boosted_hours обязан давать ровно то же, что accrued_now —
    иначе две ветки расчёта разъедутся."""
    item = B.BY_KEY["magazin"]
    for hours in (0, 0.5, 1, 3.9):
        assert (B.accrued_with_boost(2, item, 100, normal_hours=hours, boosted_hours=0)
                == B.accrued_now(2, item, 100, hours))


def test_отрицательное_время_в_надбавке_не_крадёт_копилку():
    item = B.BY_KEY["shaurma"]
    assert B.accrued_with_boost(1, item, 300, normal_hours=-1, boosted_hours=-1) == 300
