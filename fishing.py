"""Рыбалка: каталог видов рыбы и правила цены.

Здесь только КАТАЛОГ И ПРАВИЛА, без БД и Telegram — как robbery.py и
businesses.py рядом.

Главное отличие от прежней рыбалки: улов перестал быть строкой в логе и стал
предметом со своей судьбой. У каждой рыбы есть ВИД и ВЕС, вес выпадает
случайно в пределах вида, а цена считается от веса. Поэтому две щуки — разные
рыбы, и «кто вытащил самую тяжёлую» становится осмысленным рекордом, какого
у монетного улова быть не могло.

Цена: price_per_kg * вес.

⚠️ БАЛАНС. Считать надо не «средний улов», а доход при ОПТИМАЛЬНОЙ игре, и
это ровно та ошибка, на которой экономика этого бота уже раздувалась (см.
комментарий у stock_settings в db.py). Событие «Клёв пошёл» (×2) применяется
теперь в момент ПРОДАЖИ, а не поимки, — значит хороший игрок копит рыбу в
сетке и сливает её всю в клёв. Раньше ×2 доставался редким забросам,
попавшим в 20-минутное окно, то есть почти никому.

Что получилось при этих числах (проверяется тестом в tests/test_fishing_net.py):

  * продавать сразу, не глядя на события  — примерно как было раньше;
  * копить и сливать в «Клёв»             — примерно в полтора раза больше.

Полтора раза — это награда за внимание к чату, а не новый источник инфляции.
Правите price_per_kg — прогоните тест: он считает оба числа и падает, если
оптимум уезжает.

Средний вес считается по ТРЕУГОЛЬНОМУ распределению с модой в минимуме
(см. roll_grams), то есть (2*min + max)/3, а не (min+max)/2.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# --- редкость ---------------------------------------------------------------
# Только для показа: на цену влияет вес и price_per_kg, а не эта метка.
JUNK = "junk"
COMMON = "common"
UNCOMMON = "uncommon"
RARE = "rare"
EPIC = "epic"
LEGENDARY = "legendary"

RARITY_LABEL: dict[str, str] = {
    JUNK: "хлам",
    COMMON: "обычная",
    UNCOMMON: "нечастая",
    RARE: "редкая",
    EPIC: "трофейная",
    LEGENDARY: "легендарная",
}


@dataclass(frozen=True)
class Species:
    key: str
    name: str
    emoji: str
    chance: int          # вес в случайном выборе, не килограммы
    min_grams: int
    max_grams: int
    price_per_kg: int
    rarity: str

    @property
    def is_junk(self) -> bool:
        return self.rarity == JUNK


# Хлам (rarity=JUNK) в сетку не кладётся — он сразу превращается в копейки,
# иначе места под настоящую рыбу не осталось бы. «Счастливые снасти» (предмет
# за ачивку «Рыбак») убирают его из таблицы совсем — см. roll_species.
SPECIES: tuple[Species, ...] = (
    # --- хлам -------------------------------------------------------------
    Species("botinok", "старый ботинок", "🥾", 12, 400, 1_500, 30, JUNK),
    Species("vodorosli", "пучок водорослей", "🗑", 10, 100, 800, 110, JUNK),
    Species("banka", "ржавая банка", "🥫", 8, 100, 500, 35, JUNK),
    # --- обычная ----------------------------------------------------------
    Species("rybeshka", "мелкая рыбёшка", "🐟", 18, 50, 350, 1_000, COMMON),
    Species("okun", "полосатый окунь", "🐠", 14, 300, 1_200, 530, COMMON),
    Species("forel", "радужная форель", "🌈", 10, 400, 2_000, 740, COMMON),
    Species("karas", "золотистый карась", "🐟", 10, 200, 1_300, 440, COMMON),
    Species("plotva", "серебристая плотва", "🐟", 9, 100, 800, 300, COMMON),
    # --- нечастая ---------------------------------------------------------
    Species("fugu", "надутый фугу", "🐡", 9, 500, 2_000, 460, UNCOMMON),
    Species("shchuka", "щука", "🐊", 8, 1_000, 6_000, 560, UNCOMMON),
    Species("krab", "камчатский краб", "🦀", 7, 300, 2_000, 990, UNCOMMON),
    Species("kalmar", "кальмар", "🦑", 6, 1_000, 4_000, 360, UNCOMMON),
    Species("sazan", "речной сазан", "🐟", 6, 1_000, 5_000, 600, UNCOMMON),
    Species("leshch", "бронзовый лещ", "🐟", 5, 700, 3_000, 400, UNCOMMON),
    # --- редкая -----------------------------------------------------------
    Species("lobster", "лобстер", "🦞", 5, 600, 2_500, 900, RARE),
    Species("osminog", "осьминог", "🐙", 4, 2_000, 8_000, 400, RARE),
    Species("som", "исполинский сом", "🐋", 3, 5_000, 40_000, 250, RARE),
    Species("tuna", "голубой тунец", "🐟", 2, 5_000, 20_000, 300, RARE),
    Species("dorado", "морской дорадо", "🐠", 2, 500, 2_000, 600, RARE),
    # --- трофейная --------------------------------------------------------
    Species("akulyonok", "акулёнок", "🦈", 2, 5_000, 25_000, 230, EPIC),
    Species("konyok", "морской конёк", "🌊", 2, 20, 100, 56_000, EPIC),
    Species("skat", "электрический скат", "⚡", 1, 2_000, 7_000, 1_000, EPIC),
    Species("mechenos", "рыба-меч", "🗡", 1, 12_000, 30_000, 200, EPIC),
    # --- легендарная ------------------------------------------------------
    Species("zolotaya", "золотая рыбка", "🏆", 1, 100, 500, 25_000, LEGENDARY),
    Species("sunduk", "затонувший сундук", "📦", 1, 3_000, 15_000, 1_100, LEGENDARY),
    Species("marlin", "чёрный марлин", "🐟", 1, 20_000, 40_000, 310, LEGENDARY),
    Species("beluga", "белуга", "🐋", 1, 30_000, 80_000, 120, LEGENDARY),
)

BY_KEY: dict[str, Species] = {s.key: s for s in SPECIES}

_ALL_WEIGHTS = [s.chance for s in SPECIES]
_REAL = [s for s in SPECIES if not s.is_junk]
_REAL_WEIGHTS = [s.chance for s in _REAL]


def roll_species(no_junk: bool = False) -> Species:
    """Случайный вид. no_junk — тянуть только из настоящей рыбы.

    Именно перевзвешенный выбор, а не перезаброс в цикле: так вероятности
    внутри оставшихся видов сохраняют прежние пропорции и не зависят от
    числа попыток.
    """
    table = _REAL if no_junk else SPECIES
    weights = _REAL_WEIGHTS if no_junk else _ALL_WEIGHTS
    return random.choices(table, weights=weights)[0]


def roll_grams(species: Species) -> int:
    """Вес конкретного экземпляра.

    Треугольное распределение, а не равномерное: мелких особей в природе
    больше, и по-настоящему крупный экземпляр должен быть событием, а не
    каждым вторым уловом.
    """
    return int(random.triangular(species.min_grams, species.max_grams,
                                 species.min_grams))


# --- свежесть ---------------------------------------------------------------
# Рыба в сетке портится: держать улов ради удачного «Клёва» можно, но не
# бесконечно. Первые FRESH_HOURS цена полная, дальше линейно падает до
# ROT_FLOOR за ROT_HOURS. Останавливает порчу предмет «Лёд» — он не
# замораживает время, а обнуляет отсчёт (см. bot.py), поэтому здесь никаких
# интервалов помнить не нужно.
FRESH_HOURS = 24
ROT_HOURS = 48
ROT_FLOOR = 0.4


def freshness(hours_in_net: float) -> float:
    """Множитель цены от возраста рыбы в сетке: 1.0 … ROT_FLOOR."""
    if hours_in_net <= FRESH_HOURS:
        return 1.0
    gone = (hours_in_net - FRESH_HOURS) / ROT_HOURS
    return max(ROT_FLOOR, 1.0 - gone * (1.0 - ROT_FLOOR))


def freshness_label(hours_in_net: float) -> str:
    value = freshness(hours_in_net)
    if value >= 1.0:
        return "свежая"
    if value >= 0.8:
        return "полежала"
    if value > ROT_FLOOR:
        return "несвежая"
    return "совсем залежалась"


def base_price(species: Species, grams: int) -> int:
    """Цена рыбы без учёта свежести, ивентов и прибавок — только вид и вес."""
    return max(1, round(species.price_per_kg * grams / 1000))


def price(species: Species, grams: int, hours_in_net: float = 0.0) -> int:
    """Цена с учётом свежести. Ивент и пассивные прибавки накручивает бот."""
    return max(1, round(base_price(species, grams) * freshness(hours_in_net)))


def format_weight(grams: int) -> str:
    """«0.84 кг» / «310 г» — граммы у мелочи читаются лучше килограммов."""
    if grams < 1000:
        return f"{grams} г"
    return f"{grams / 1000:.2f} кг".replace(".", ",")
