"""Крафты: из чего и при каких условиях получается предмет.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как pets.py и pins.py рядом.
Сами предметы описаны в shop_effects.CRAFT_ITEMS: это каталог предметов и их
сил, а здесь — как их получить.

Зачем крафт вообще. В магазине 15 предметов хлама, про которые в db.py прямо
написано «намеренно бесполезный: ничего не делает, никуда не влияет», и
единственная причина их держать — коллекция «Барахольщик». Крафт даёт им
вторую жизнь и превращает мусор в лестницу: хлам → мелкие привилегии →
эликсир → эволюция питомца → эволюционировавший питомец как требование
верхних рецептов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ----------------------------------------------------------------------------
# ТРЕБОВАНИЯ. Один общий типизированный список вместо отдельных полей на каждый
# случай: новый вид требования — это одна строка в рецепте и одна ветка в
# проверяльщике, а не новое поле у всех рецептов сразу.
#
# Расходуются только предметы и монеты. Всё остальное — условие допуска:
# титул, уровень питомца, ачивка. Их нельзя «потратить», и отбирать их за
# крафт было бы дико.
# ----------------------------------------------------------------------------
REQ_ITEM = "item"                # предмет в инвентаре
REQ_COINS = "coins"              # монеты
REQ_TITLE = "title"              # титул во владении ("" — любой)
REQ_PET_LEVEL = "pet_level"      # есть питомец уровня не ниже
REQ_PET_EVOLVED = "pet_evolved"  # есть эволюционировавший питомец
REQ_ACHIEVEMENT = "achievement"  # ачивка получена
REQ_STARS = "stars"              # звёздность не ниже
REQ_PROF_LEVEL = "prof_level"    # уровень профессии не ниже

# Коллекции отдельным видом не нужны: за каждую собранную выдаётся ачивка
# collection_*, и REQ_ACHIEVEMENT их покрывает. Новых таблиц не заводим.

CONSUMED_KINDS = frozenset({REQ_ITEM, REQ_COINS})


@dataclass(frozen=True)
class Req:
    kind: str
    key: str = ""      # ключ предмета / титула / ачивки; для чисел не нужен
    amount: int = 1    # сколько штук, монет или какой уровень


@dataclass(frozen=True)
class Recipe:
    key: str                  # как звать в команде: «крафт otmychka»
    result: str               # ключ получаемого предмета (shop_effects.CRAFT_BY_KEY)
    reqs: tuple[Req, ...]
    # Рецепту нужен человек: «крафт кукла @вася». Такое не кладётся в инвентарь
    # — у результата есть цель, а инвентарь хранит только «ключ → количество».
    target: bool = False

    @property
    def consumed(self) -> tuple[Req, ...]:
        return tuple(r for r in self.reqs if r.kind in CONSUMED_KINDS)


def _junk(*keys: str) -> tuple[Req, ...]:
    return tuple(Req(REQ_ITEM, key) for key in keys)


# ----------------------------------------------------------------------------
# РЕЦЕПТЫ. Порядок — от дешёвого к дорогому: так же читается список в команде
# «крафты», и так же по нему поднимаются.
# ----------------------------------------------------------------------------
RECIPES: tuple[Recipe, ...] = (
    Recipe("otmychka", "otmychka",
           _junk("skrepka", "nitka", "gvozd") + (Req(REQ_COINS, amount=5_000),)),
    Recipe("obereg", "obereg",
           _junk("kamen", "pyl", "fantik") + (Req(REQ_COINS, amount=8_000),)),
    Recipe("kompas", "kompas",
           _junk("probka", "chek", "zhvachka") + (Req(REQ_COINS, amount=12_000),)),
    Recipe("set", "set_rybaka",
           _junk("nitka", "vilka", "banan_kozhura") + (Req(REQ_COINS, amount=15_000),)),
    Recipe("termos", "termos",
           _junk("kirpich", "puzyr", "kartoshka") + (Req(REQ_COINS, amount=20_000),)),
    # Дальше — то, что просит не только вещи. Амулет требует ачивку за стрик:
    # предмет, защищающий серию, логично заслужить самой серией.
    Recipe("amulet", "amulet_serii",
           _junk("nosok", "skrepka", "kamen", "probka", "fantik")
           + (Req(REQ_COINS, amount=40_000), Req(REQ_ACHIEVEMENT, "streak_7"))),
    # Эликсир — вершина хламовой ветки и вход в эволюцию.
    Recipe("elixir", "elixir",
           _junk("gvozd", "puzyr", "pyl", "zhvachka", "vilka")
           + (Req(REQ_COINS, amount=100_000),
              Req(REQ_PET_LEVEL, amount=10),
              Req(REQ_TITLE))),
    # --- Ветка фермы ---------------------------------------------------------
    # Материалы сюда приходят не из магазина, а из хлева (см. livestock.py):
    # это первые рецепты, где ингредиент нельзя купить ни за какие деньги.
    # Монеты в них небольшие — платят за них временем животных, а не кошельком.
    Recipe("сыр", "syr",
           (Req(REQ_ITEM, "moloko", 2), Req(REQ_COINS, amount=300))),
    Recipe("пирог", "pirog",
           (Req(REQ_ITEM, "yayca", 4), Req(REQ_ITEM, "moloko", 1),
            Req(REQ_COINS, amount=1_200))),
    Recipe("шарф", "sharf",
           (Req(REQ_ITEM, "sherst", 3), Req(REQ_COINS, amount=1_500))),
    Recipe("тулуп", "tulup",
           (Req(REQ_ITEM, "sherst", 5), Req(REQ_ITEM, "pero", 8),
            Req(REQ_COINS, amount=6_000))),
    # Теплица — вершина ветки фермы и единственный крафт, который РАСШИРЯЕТ
    # огород. Просит обе его половины сразу: и выращенное на грядках, и
    # продукт хлева, — плюс ачивку за сто сборов, то есть доказательство, что
    # человек этим огородом действительно занимался.
    Recipe("теплица", "teplica",
           (Req(REQ_ITEM, "urozhay_podsolnuh", 8), Req(REQ_ITEM, "urozhay_tykva", 5),
            Req(REQ_ITEM, "sherst", 4), Req(REQ_ITEM, "pero", 10),
            Req(REQ_COINS, amount=25_000),
            Req(REQ_ACHIEVEMENT, "farm_harvest_100"))),

    # Кукла вуду — сувенир, а не оружие: ничего не делает, просто лежит и
    # радует. Живёт не в инвентаре, а в своей таблице (см. db.voodoo_dolls) —
    # потому и не теряется, не продаётся и не грабится: всё это ходит по
    # user_inventory, и того, чего там нет, оно не достанет.
    Recipe("кукла", "",
           _junk("nitka", "skrepka", "nosok") + (Req(REQ_COINS, amount=2_000),),
           target=True),
    # Пугало — единственный рецепт из ВЫРАЩЕННОГО, а не из купленного хлама:
    # подсолнух нигде, кроме грядки, не берётся. Огород замыкается сам на себя,
    # и у подсолнуха появляется смысл помимо продажи.
    Recipe("pugalo", "pugalo",
           (Req(REQ_ITEM, "urozhay_podsolnuh", amount=3),
            Req(REQ_ITEM, "urozhay_kartoshka", amount=5),
            Req(REQ_COINS, amount=25_000))),
    # Корона — единственный предмет, дающий прибавку ко ВСЕМ занятиям сразу,
    # и требования у неё под стать: без эволюционировавшего питомца и
    # собранной коллекции её не сделать.
    Recipe("korona", "korona_mastera",
           (Req(REQ_PET_EVOLVED),
            Req(REQ_ACHIEVEMENT, "collection_tycoon"),
            Req(REQ_COINS, amount=250_000))),
)

BY_KEY: dict[str, Recipe] = {r.key: r for r in RECIPES}


def resolve(raw: Optional[str]) -> Optional[Recipe]:
    if not raw:
        return None
    return BY_KEY.get(" ".join(raw.strip().casefold().split()))


# ----------------------------------------------------------------------------
# Как требование называется человеку. Названия предметов, титулов и ачивок
# приходят снаружи — они живут в БД и в bot.py, а этот модуль про БД не знает.
# ----------------------------------------------------------------------------
def req_text(req: Req, item_name: str = "", achievement_name: str = "") -> str:
    if req.kind == REQ_ITEM:
        name = item_name or req.key
        return f"{name} ×{req.amount}" if req.amount > 1 else name
    if req.kind == REQ_COINS:
        return f"{req.amount} i¢"
    if req.kind == REQ_TITLE:
        return f"титул «{req.key}»" if req.key else "любой титул"
    if req.kind == REQ_PET_LEVEL:
        return f"питомец {req.amount} уровня или выше"
    if req.kind == REQ_PET_EVOLVED:
        return "эволюционировавший питомец"
    if req.kind == REQ_ACHIEVEMENT:
        return f"ачивка «{achievement_name or req.key}»"
    if req.kind == REQ_STARS:
        return f"звёздность {req.amount} или выше"
    if req.kind == REQ_PROF_LEVEL:
        return f"профессия {req.amount} уровня или выше"
    return req.kind
