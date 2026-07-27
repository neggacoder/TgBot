"""Закрепы в профиле — не витрина, а экипировка.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как pets.py и businesses.py
рядом.

В профиле пять закрепов: предмет, бизнес, питомец, ачивка, рыба. Раньше все
пятеро были украшением; предмет уже усилен (см. shop_effects.PIN_MULTIPLIER),
здесь описаны остальные. Слот один на вид, поэтому закреп — это выбор под свой
стиль игры, а не бесплатная прибавка ко всему сразу.
"""

from __future__ import annotations

from typing import Optional

# --- 🏢 бизнес --------------------------------------------------------------
# Закреплённый бизнес чинится сам, но не чаще раза в сутки: иначе поломки
# перестали бы что-либо значить, а ремкомплект — продаваться.
BUSINESS_SELF_REPAIR_HOURS = 24

# --- 🐾 питомец -------------------------------------------------------------
# У закреплённого питомца способность засыпает позже: порог активности ниже
# обычного pets.LOW_STAT. Не «никогда не засыпает» — ухаживать всё равно надо,
# просто закреплённому прощается пропущенная кормёжка.
PET_LOW_STAT = 15

# --- 🐟 рыба ----------------------------------------------------------------
# Трофей на стене прибавляет к улову. Рыба и так не портится и не продаётся,
# пока закреплена, — теперь у трофея есть и польза, а не только сентиментальная
# ценность.
FISH_CATCH_PERCENT = 15

# --- 🏅 ачивка --------------------------------------------------------------
# Ачивок 53 в 34 группах — придумывать эффект каждой бессмысленно, их пришлось
# бы держать в голове. Вместо этого пять тем: закрепляешь ту ачивку, чья тема
# совпадает с тем, как ты играешь.
#
# «Отношения» намеренно слиты с «общением»: искры живут в отдельном модуле
# (relationships_v2), и тянуть туда прибавку значило бы связать модули ради
# одной строки. Тематически это одно и то же — социальная игра.
ACHIEVEMENT_THEMES: dict[str, tuple[str, str, str, int]] = {
    # тема -> (эмодзи, название, на что влияет, процент)
    "social":     ("💬", "Общение",    "reputation",   20),
    "economy":    ("💰", "Экономика",  "daily_bonus",  15),
    "gamble":     ("🎰", "Азарт",      "casino_win",   15),
    "collector":  ("📚", "Коллекции",  "lootbox",      20),
    "labour":     ("🔨", "Труд",       "activity",     10),
}

# Префикс ключа ачивки -> тема. Ключи вида «msg_100» разбираются по первому
# слову: так новая ачивка той же группы подхватывается сама.
_PREFIX_THEME: dict[str, str] = {
    # общение и отношения
    "msg": "social", "streak": "social", "days": "social", "night": "social",
    "early": "social", "popular": "social", "matchmaker": "social",
    "married": "social", "family": "social", "house": "social", "pets": "social",
    # экономика
    "coins": "economy", "investor": "economy", "generous": "economy",
    # азарт
    "casino": "gamble", "race": "gamble", "robber": "gamble", "duel": "gamble",
    "lootbox": "gamble",
    # коллекции и знаки отличия
    "collection": "collector", "season": "collector", "quotes": "collector",
    "bookmarks": "collector", "club": "collector", "clan": "collector",
    "role": "collector", "rewarded": "collector",
    # труд
    "work": "labour", "prof": "labour", "farm": "labour", "fish": "labour",
    "treasure": "labour", "sidejob": "labour",
}

# Занятия (shop_effects.ACTIVITY_*) — тема «Труд» прибавляет к любому из них.
# Отдельным значением "activity" в ACHIEVEMENT_THEMES, чтобы не перечислять их
# там шестью строками.
EFFECT_ANY_ACTIVITY = "activity"
ACTIVITY_KEYS = frozenset({"work", "farm", "fishing", "treasure",
                           "side_job", "daily_bonus"})


def theme_of(achievement_key: Optional[str]) -> Optional[str]:
    """Тема ачивки. None — ачивки нет или её группа неизвестна.

    Неизвестная группа не ошибка: ачивку могли добавить, а сюда не вписать.
    Тогда закреп просто не даёт прибавки — это лучше, чем гадать за автора.
    """
    if not achievement_key:
        return None
    return _PREFIX_THEME.get(str(achievement_key).split("_")[0])


def achievement_bonus(achievement_key: Optional[str], effect_key: str) -> int:
    """Прибавка в процентах от закреплённой ачивки к этому эффекту.

    effect_key — либо конкретное («reputation», «casino_win», «lootbox»,
    «daily_bonus»), либо название занятия: тема «Труд» прибавляет к любому.
    Ежедневный бонус — тоже занятие, но у него своя тема «Экономика», и она
    должна выигрывать, поэтому точное совпадение проверяется первым.
    """
    theme = theme_of(achievement_key)
    if theme is None:
        return 0
    _emoji, _name, target, percent = ACHIEVEMENT_THEMES[theme]
    if target == effect_key:
        return percent
    if target == EFFECT_ANY_ACTIVITY and effect_key in ACTIVITY_KEYS:
        return percent
    return 0


def achievement_text(achievement_key: Optional[str]) -> str:
    """Человеческое описание того, что даёт закреплённая ачивка."""
    theme = theme_of(achievement_key)
    if theme is None:
        return ""
    emoji, name, target, percent = ACHIEVEMENT_THEMES[theme]
    what = {
        "reputation": "к получаемой репутации",
        "daily_bonus": "к ежедневному бонусу",
        "casino_win": "к выигрышу в казино",
        "lootbox": "к шансу редкого приза из лутбокса",
        EFFECT_ANY_ACTIVITY: "к доходу с фермы, рыбалки, клада, подработки и смены",
    }[target]
    return f"{emoji} {name}: +{percent}% {what}"
