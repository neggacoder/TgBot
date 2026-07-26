"""
Плагин «Отношения 2.0» — расширенная система виртуальных отношений (по мотивам
гайда «Отношения» из Iris | Чат-менеджер: https://teletype.in/@celestiana/relationship_help).

⚠️ СТАТУС / ПЛАН РАЗВИТИЯ
В bot.py уже есть более лёгкий модуль «Отношения» (см. блок с комментарием
«Отношения (как в Iris)», таблицы relationships/relationship_requests). Этот
файл — НЕ патч к нему, а отдельная, более полная система (со своими таблицами
rel2_* в db.py), которая рано или поздно должна его заменить. Пока это не
сделано, оба модуля могут технически сосуществовать, но нельзя подключать оба
роутера с одинаковыми командами одновременно — будет конфликт хендлеров
aiogram (сработает тот, что зарегистрирован первым). Смотри раздел
«ИНТЕГРАЦИЯ» в самом низу файла.

Здесь реализованы ПЕРВЫЕ ЧЕТЫРЕ модуля из гайда:

  1. 💑 НАЧИНАНИЕ ОТНОШЕНИЙ — предложение/принятие/отклонение/расторжение,
     профиль пары, топ пар чата.
  2. 🔥 ИСКРЫ — жизненная сила отношений: формула дневного расхода искр по
     уровню (+10% за ребёнка, -30% для премиума), ежедневный бонус (раз в
     12 часов), автоматическое списание расхода, разрушение отношений при
     нуле искр (премиум получает одноразовую страховку +500), история
     операций.
  3. 🏠 ДОМ — каталог домов/комнат/улучшений, постройка (с ускорением для
     премиума), еженедельное обслуживание с предупреждением и сносом при
     неуплате, действия в комнатах с наградой (модификаторы: уровень
     комнаты, престиж дома, премиум), продажа дома.
  4. 🐾 ПИТОМЦЫ — яйца трёх видов со своими шансами редкости, характер
     (-10..+10, влияет на скорость изменения настроения), положительные и
     отрицательные навыки (эффективны при настроении ≥30% и только у
     активного питомца), кормление из казны пары раз в 24 часа, здоровье и
     гибель при истощении, действия (играть/погладить/тренировать/дать
     лакомство), прокачка уровня (100×уровень^1.5, потолок зависит от
     редкости), домики с комнатами и суммируемыми бонусами.

Плюс шесть новых модулей поверх базы (дом/питомцы/дети):

  5. 👶 ДЕТИ — «отн родить» работает как предложение отношений (запрос +
     кнопки принять/отклонить), итог — запись в rel2_children. Три
     абстрактных характеристики (здоровье/интеллект/харизма), настроение,
     уровень (120×уровень^1.4), три действия с откатом (play/care/teach),
     лимит 10/30 детей (премиум), команды «ребенок …». Альтернативный путь
     к ребёнку — полноценная беременность (см. п.12).
  6. 🎓 СЕКЦИИ ДЛЯ ДЕТЕЙ — разовая запись усиливает действие, чья
     характеристика совпадает с профилем секции («ребенок секция»).
  7. 🎉 СЕМЕЙНЫЕ СОБЫТИЯ — оплаченное событие даёт бонус настроения/опыта
     сразу всем детям пары, с откатом в днях («ребенок событие»).
  8. 🏆 ДУЭЛИ ПИТОМЦЕВ — активный питомец пары бросает вызов питомцу другой
     пары в чате; победитель по «мощи» забирает искры проигравшей пары
     («отн пт дуэль»).
  9. 🎲 СЛУЧАЙНЫЕ СОБЫТИЯ ДОМА — «дом действие» может неожиданно дать бонус
     или небольшой штраф к награде.
 10. 🏅 РЕЙТИНГ ДОМОВ ЧАТА — «дом топ» показывает топ-10 пар по престижу дома.
 11. 💞 РП-ДЕЙСТВИЯ — 30 действий с партнёром («сделать комплимент», «сделать
     подарок» и т.д.), каждое открывается на своём уровне пары (действие
     №N — на уровне N), с наградой в искрах и индивидуальным откатом
     («отн действия» — список со статусом ✅/⏳/🔒, «отн сделать ‹...›» —
     выполнить). Плюс простые несексуальные жесты («отн обнять» и т.п.) и
     премиум-действия («отн премиум ‹...›»).
 12. 🛡 ЗАЩИТА ОТ БЕРЕМЕННОСТИ И БЕРЕМЕННОСТЬ — «отн презик» переключает
     защиту (включена по умолчанию), «отн секс» / «отн кекс» — попытка с
     шансом на успех, без описания процесса. Успех запускает полноценную
     беременность на 40 игровых недель (rel2_pregnancies, сжато в реальное
     время — см. PREGNANCY_HOURS_PER_WEEK), с вехами по неделям и прогресс-
     баром («отн беременность»); когда неделя 40 достигнута — «отн родить»
     закрывает именно эту беременность. Путь без зачатия («отн родить» без
     активной беременности) по-прежнему работает как раньше.

Остальные разделы гайда (подарки, задания, покупка искр за звёзды,
премиум-действия между партнёрами) по-прежнему НЕ входят в этот файл —
материал для следующих этапов (см. TODO в конце).

Архитектурно модуль самодостаточен, как activity_chart.py: не импортирует
глобальный `bot` из bot.py (чтобы не ловить циклический импорт), а получает
экземпляр Bot через message.bot / callback.message.bot. Единственная внешняя
зависимость — db.py (слой MySQL, тех же конвенций, что и весь остальной
проект: async-функции, пул aiomysql).
"""
from __future__ import annotations

import html
import json
import logging
import os
import random
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    ReplyParameters,
)

import db
import rp_photos

logger = logging.getLogger(__name__)

router = Router(name="relationships_v2")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


def _strip_dot_prefix(text: str) -> str:
    """«.отн …» — альтернативная запись «отн …» (привычка из других ботов).
    Точка — чисто визуальный префикс, вырезаем перед разбором команды."""
    t = text.strip()
    return t[1:].strip() if t.startswith(".") else t


def _first_word_is(text: Optional[str], word: str) -> bool:
    if not text:
        return False
    t = _strip_dot_prefix(text)
    parts = t.split()
    return bool(parts) and parts[0].casefold() == word


# ============================================================================
# 🔥 ИСКРЫ — формула, вехи уровней, начисление/списание
# ============================================================================

# Формула дневного расхода искр по уровню — из гайда, раздел «Формула
# расхода искр в день». Проверено на примерах гайда:
#   уровень 10 → 550/день, уровень 20 → 3500/день, уровень 30 → 18000/день.
def daily_spark_cost(level: int) -> int:
    level = max(1, min(level, 30))
    if level <= 5:
        return 15 * level
    if level <= 10:
        return 50 * level + 50
    if level <= 15:
        return 80 * level + 200
    if level <= 20:
        return 150 * level + 500
    if level <= 25:
        return 300 * level + 1500
    return 500 * level + 3000


def effective_daily_cost(level: int, children_count: int, premium: bool) -> int:
    """Итоговый дневной расход с модификаторами: +10% за каждого ребёнка,
    -30% для премиума (применяются друг за другом, как в гайде)."""
    cost = daily_spark_cost(level) * (1 + 0.10 * max(children_count, 0))
    if premium:
        cost *= 0.70
    return max(round(cost), 0)


# Именные вехи уровней — из гайда, раздел «Таблица уровней и названий».
# Гайд называет только опорные уровни (1/5/10/15/20/25/30); промежуточные
# уровни (2-4, 6-9 и т.д.) наследуют название последней пройденной вехи —
# ровно как показано в самом гайде («На каждом уровне открываются новые
# действия... но названы явно только вехи»).
_LEVEL_MILESTONES: list[tuple[int, str]] = [
    (1, "Зарождение интереса"),
    (5, "Первая близость"),
    (10, "Безусловная любовь"),
    (15, "Гармоничная связь"),
    (20, "Идеальная гармония"),
    (25, "Нерушимый союз"),
    (30, "Легендарная любовь"),
]

MAX_LEVEL = 30

# РЕШЕНО: сколько ИСКР на балансе нужно держать, чтобы считаться на уровне N.
# Гайд задаёт только принцип («уровень зависит от количества искр»), точные
# пороги — наш выбор: порог(N) = порог(N-1) + 5 дневных расходов уровня (N-1),
# т.е. «пять дней жизни на предыдущем уровне» — умеренно нарастающая кривая,
# не требующая от игрока копить искры неделями ради левел-апа.
# Значения живут в БД (таблица rel2_levels) и правятся там же без деплоя —
# этот список только сид для первого запуска.
def build_rel2_level_table() -> list[tuple[int, str, int]]:
    milestone_by_level = dict(_LEVEL_MILESTONES)
    rows: list[tuple[int, str, int]] = []
    threshold = 0
    current_name = milestone_by_level[1]
    for level in range(1, MAX_LEVEL + 1):
        if level in milestone_by_level:
            current_name = milestone_by_level[level]
        if level > 1:
            threshold += 5 * daily_spark_cost(level - 1)
        rows.append((level, current_name, threshold))
    return rows


# Живой кэш — заполняется в load_rel2_caches() из db.list_rel2_levels() (или
# из build_rel2_level_table(), пока БД не проинициализирована).
REL2_LEVELS: list[tuple[int, str, int]] = build_rel2_level_table()


# --- выдача ачивок из этого модуля -----------------------------------------
# Ачивки живут в bot.py (реестр ACHIEVEMENTS + grant_achievement), а bot.py
# импортирует этот модуль — значит, импортировать его отсюда нельзя, будет
# круг. Поэтому bot.py на старте кладёт сюда свою функцию (см. set_achievement
# _granter в main()), а до тех пор выдача просто ничего не делает.
#
# Раньше здесь стоял прямой вызов grant_achievement(...) — имени, которого в
# этом модуле нет. Ачивка «Многодетный» не только никогда не выдавалась: сам
# NameError ронял обработку кнопки «👶 Принять» у пары с пятью детьми.
FAMILY_ACHIEVEMENT_CHILDREN = 5

_achievement_granter = None


def set_achievement_granter(fn) -> None:
    """Вызывается из bot.py: fn(chat_id, user_id, code) — корутина."""
    global _achievement_granter
    _achievement_granter = fn


async def grant_achievement(chat_id: int, user_id: int, code: str) -> None:
    if _achievement_granter is None:
        logger.debug("Ачивка %s не выдана: bot.py ещё не подключил выдачу", code)
        return
    try:
        await _achievement_granter(chat_id, user_id, code)
    except Exception:
        # Ачивка — приятный бонус, а не суть операции: её падение не должно
        # отменять уже добавленного ребёнка.
        logger.exception("Не удалось выдать ачивку %s пользователю %s", code, user_id)


async def load_rel2_caches() -> None:
    """Вызывать в main() бота после db.ensure_rel2_tables()/seed_rel2_levels_if_empty(),
    по аналогии с load_caches() в bot.py."""
    rows = await db.list_rel2_levels()
    if rows:
        REL2_LEVELS[:] = rows


def level_from_sparks(sparks: int) -> int:
    """Уровень пары определяется ТЕКУЩИМ балансом искр (не накопленным
    максимумом) — если искры потрачены/сгорели, уровень падает вместе с ними."""
    level = 1
    for lvl, _name, threshold in REL2_LEVELS:
        if sparks >= threshold:
            level = lvl
    return level


def level_name(level: int) -> str:
    for lvl, name, _threshold in REL2_LEVELS:
        if lvl == level:
            return name
    return REL2_LEVELS[-1][1] if REL2_LEVELS else "?"


def next_level_info(sparks: int) -> Optional[tuple[int, str, int]]:
    """(след. уровень, его название, сколько искр не хватает) либо None на максимуме."""
    for lvl, name, threshold in REL2_LEVELS:
        if sparks < threshold:
            return lvl, name, threshold - sparks
    return None


# Ежедневный бонус (раз в 12 часов, см. «отн бонус» ниже). Гайд не приводит
# точную сумму — здесь разумный дефолт, растущий с уровнем, чтобы бонус не
# терялся на фоне расхода искр на верхних уровнях. +20% для премиума.
def daily_bonus_amount(level: int, premium: bool) -> int:
    amount = 100 + level * 20
    if premium:
        amount = round(amount * 1.2)
    return amount


SPARK_LOG_LABELS: dict[str, str] = {
    "bonus": "🔋 Ежедневный бонус",
    "daily_charge": "🔥 Дневной расход",
    "premium_insurance": "🛡️ Страховка отношений",
    "admin_grant": "🛠 Начислено администратором",
    "rp_action": "💞 РП-действие",
    "rp_premium_action": "✨ Особое РП-действие",
}


def spark_log_label(reason: str) -> str:
    return SPARK_LOG_LABELS.get(reason, reason)


def _fmt_thousands(n: int) -> str:
    """Число с точкой-разделителем тысяч (как в карточке пары: 9.734)."""
    return f"{int(n):,}".replace(",", ".")


def _pair_duration_text(started_at: datetime) -> str:
    """Длительность отношений компактно: «2мес. 4д», «1г. 3мес.», «5д»."""
    total_days = max((datetime.utcnow() - started_at).days, 0)
    years, rem = divmod(total_days, 365)
    months, days = divmod(rem, 30)
    parts = []
    if years:
        parts.append(f"{years}г.")
    if months:
        parts.append(f"{months}мес.")
    if days or not parts:
        parts.append(f"{days}д")
    return " ".join(parts)


# ============================================================================
# 🏠 МОДУЛЬ 3 — СИСТЕМА ДОМОВ (постройка, обслуживание, комнаты, престиж,
# улучшения). Один дом на пару (rel2_houses.pair_id UNIQUE). Все каталоги
# ниже — редактируемые Python-словари; гайд не приводит точный прайс-лист,
# только диапазоны и примеры («дом за 100 000 искр с 0.2%», «действие в
# гостиной = 800 искр, откат 10ч») — эти примеры используются как якоря при
# подборе конкретных чисел ниже.
# ============================================================================

# РЕШЕНО: полный каталог домов. Гайд задаёт только диапазоны (постройка
# 2-12 дней, обслуживание 0.06%-0.5% от стоимости в неделю) — 6 домов ниже
# растянуты по этим диапазонам равномерно, от дешёвого/дорогого-в-содержании
# до дорогого/дешёвого-в-содержании. room_slots растёт пропорционально цене
# (3 → 24 слота), чтобы дорогой дом ощутимо превосходил дешёвый по вместимости.
HOUSE_CATALOG: dict[str, dict] = {
    "hut":        {"name": "🛖 Хижина",             "price": 20_000,    "build_days": 2,  "maintenance_pct": 0.50, "room_slots": 3},
    "cottage":    {"name": "🏡 Загородный дом",      "price": 60_000,    "build_days": 4,  "maintenance_pct": 0.35, "room_slots": 5},
    "townhouse":  {"name": "🏘 Таунхаус",            "price": 150_000,   "build_days": 6,  "maintenance_pct": 0.25, "room_slots": 8},
    "villa":      {"name": "🏖 Вилла",               "price": 350_000,   "build_days": 8,  "maintenance_pct": 0.15, "room_slots": 12},
    "mansion":    {"name": "🏰 Особняк",             "price": 700_000,   "build_days": 10, "maintenance_pct": 0.10, "room_slots": 16},
    "castle":     {"name": "🏯 Замок",               "price": 1_500_000, "build_days": 12, "maintenance_pct": 0.06, "room_slots": 24},
}

# РЕШЕНО: стартовый каталог комнат — 17 штук (все 15 названных в гайде + 2
# тематических добавления: зимний сад, библиотека), заявленных 24 добирать
# не стали, чтобы не дописывать комнаты с придуманными названиями и ценами.
# Каталог — обычный словарь: дополнить до 24 позже — значит дописать ещё
# пункты по той же схеме, без правки остальной логики.
# reward/cooldown_hours — только у комнат с действием («действие в комнате»);
# у декоративных комнат их нет, просто множитель к престижу дома.
ROOM_CATALOG: dict[str, dict] = {
    # Жилые
    "bedroom":     {"name": "🛏 Спальня",           "category": "жилая",          "price": 15_000, "prestige": 2, "reward": None, "cooldown_hours": None},
    "living_room": {"name": "🛋 Гостиная",          "category": "жилая",          "price": 25_000, "prestige": 3, "reward": 800,  "cooldown_hours": 10, "action_name": "Киномарафон"},
    "kitchen":     {"name": "🍳 Кухня",             "category": "жилая",          "price": 20_000, "prestige": 3, "reward": 500,  "cooldown_hours": 6,  "action_name": "Совместная готовка"},
    "dining_room": {"name": "🍽 Столовая",          "category": "жилая",          "price": 12_000, "prestige": 2, "reward": None, "cooldown_hours": None},
    # Функциональные
    "bathroom":    {"name": "🛁 Ванная",            "category": "функциональная", "price": 14_000, "prestige": 2, "reward": None, "cooldown_hours": None},
    "laundry":     {"name": "🧺 Прачечная",         "category": "функциональная", "price": 10_000, "prestige": 1, "reward": None, "cooldown_hours": None},
    "storage":     {"name": "📦 Кладовая",          "category": "функциональная", "price": 9_000,  "prestige": 1, "reward": None, "cooldown_hours": None},
    "workshop":    {"name": "🔧 Мастерская",        "category": "функциональная", "price": 18_000, "prestige": 3, "reward": 400,  "cooldown_hours": 5,  "action_name": "Мастерить вместе"},
    # Развлекательные
    "game_room":   {"name": "🎮 Игровая",           "category": "развлекательная","price": 22_000, "prestige": 3, "reward": 450,  "cooldown_hours": 4,  "action_name": "Игровой турнир"},
    "cinema":      {"name": "🎬 Кинотеатр",         "category": "развлекательная","price": 30_000, "prestige": 4, "reward": 650,  "cooldown_hours": 8,  "action_name": "Премьерный показ"},
    "gym":         {"name": "🏋 Спортзал",          "category": "развлекательная","price": 26_000, "prestige": 4, "reward": 500,  "cooldown_hours": 6,  "action_name": "Совместная тренировка"},
    "pool":        {"name": "🏊 Бассейн",           "category": "развлекательная","price": 40_000, "prestige": 5, "reward": 700,  "cooldown_hours": 9,  "action_name": "Заплыв вдвоём"},
    "garden":      {"name": "🌳 Зимний сад",        "category": "развлекательная","price": 28_000, "prestige": 4, "reward": 550,  "cooldown_hours": 7,  "action_name": "Прогулка по саду"},
    "library":     {"name": "📚 Библиотека",        "category": "развлекательная","price": 24_000, "prestige": 3, "reward": 400,  "cooldown_hours": 5,  "action_name": "Чтение вслух"},
    # Особые комнаты: в гайде это были «премиум-комнаты», но премиум выдан
    # всем — доступны всем парам как обычные (флаг premium_only оставлен, чтобы
    # не переписывать проверки, но он ни на кого не влияет: премиум у всех).
    "private_club":{"name": "🥂 Частный клуб",      "category": "особые",        "price": 60_000, "prestige": 8, "reward": 1200, "cooldown_hours": 12, "action_name": "Приватный вечер", "premium_only": True},
    "wine_cellar": {"name": "🍷 Винный погреб",     "category": "особые",        "price": 45_000, "prestige": 6, "reward": 900,  "cooldown_hours": 10, "action_name": "Дегустация", "premium_only": True},
    "sauna":       {"name": "♨️ Сауна",             "category": "особые",        "price": 50_000, "prestige": 7, "reward": 1000, "cooldown_hours": 11, "action_name": "Отдых в сауне", "premium_only": True},
}

# РЕШЕНО: прайс улучшений. 8 видов и 4 уровня — из гайда, точные числа —
# наш выбор: цена растёт геометрически (×1.8 за уровень, см.
# house_upgrade_price ниже), престиж — линейно в границах диапазона гайда
# (1-32 суммарно за улучшение), чтобы верхние уровни ощутимо били по кошельку,
# но не были заградительно дорогими.
UPGRADE_CATALOG: dict[str, dict] = {
    "electricity": {"name": "⚡ Электрика",        "base_price": 8_000, "prestige_per_level": 2},
    "heating":     {"name": "🔥 Отопление",        "base_price": 9_000, "prestige_per_level": 2},
    "internet":    {"name": "📶 Интернет",         "base_price": 10_000,"prestige_per_level": 3},
    "water":       {"name": "🚰 Водоснабжение",    "base_price": 8_000, "prestige_per_level": 2},
    "gas":         {"name": "🔵 Газоснабжение",    "base_price": 9_000, "prestige_per_level": 2},
    "sewerage":    {"name": "🚽 Канализация",      "base_price": 8_500, "prestige_per_level": 2},
    "garbage":     {"name": "🗑 Утилизация мусора","base_price": 6_000, "prestige_per_level": 1},
    "water_clean": {"name": "💧 Очистка воды",     "base_price": 7_500, "prestige_per_level": 2},
}
UPGRADE_MAX_LEVEL = 4
HOUSE_MAINTENANCE_PERIOD_DAYS = 7
HOUSE_MAINTENANCE_GRACE_DAYS = 3
HOUSE_SELL_RATE = 0.35
HOUSE_SELL_RATE_PREMIUM = 0.60


def house_upgrade_price(upgrade_key: str, next_level: int) -> int:
    base = UPGRADE_CATALOG[upgrade_key]["base_price"]
    return round(base * (1.8 ** (next_level - 1)))


def house_prestige(rooms: list[dict], upgrades: list[dict]) -> int:
    total = 0
    for room in rooms:
        info = ROOM_CATALOG.get(room["room_key"])
        if info:
            total += info["prestige"] * room["level"]
    for upgrade in upgrades:
        info = UPGRADE_CATALOG.get(upgrade["upgrade_key"])
        if info:
            total += info["prestige_per_level"] * upgrade["level"]
    return total


def house_prestige_bonus(prestige: int) -> float:
    """+0.2% к наградам за каждую единицу престижа (см. гайд, «Система престижа»)."""
    return prestige * 0.002


def house_build_ready_at(house_key: str, premium: bool) -> datetime:
    from datetime import timedelta
    days = HOUSE_CATALOG[house_key]["build_days"]
    if premium:
        days *= 0.70  # -30% времени постройки для премиума
    return datetime.utcnow() + timedelta(days=days)


def house_weekly_maintenance(house_key: str) -> int:
    """Обслуживание раз в 7 дней = maintenance_pct% от цены дома (гайд,
    пример: дом 100 000 искр × 0.2% = 200 искр/неделю — то есть maintenance_pct
    уже является итоговой недельной ставкой, без дополнительного домножения)."""
    price = HOUSE_CATALOG[house_key]["price"]
    pct = HOUSE_CATALOG[house_key]["maintenance_pct"]
    return max(round(price * pct / 100), 1)


def room_action_reward(room_key: str, room_level: int, prestige: int, premium: bool) -> int:
    info = ROOM_CATALOG[room_key]
    base = info["reward"] or 0
    reward = base * (1 + 0.15 * (room_level - 1))  # уровень комнаты: +15% за уровень
    reward *= (1 + house_prestige_bonus(prestige))
    if premium:
        reward *= 1.25
    return round(reward)


def room_action_cooldown_hours(room_key: str, premium: bool) -> float:
    info = ROOM_CATALOG[room_key]
    hours = info["cooldown_hours"] or 0
    if premium:
        hours *= 0.70
    return hours


def room_next_level_price(room_key: str, current_level: int) -> int:
    base = ROOM_CATALOG[room_key]["price"]
    return round(base * 0.5 * current_level)  # улучшение дешевле повторной покупки


def house_sell_amount(price: int, premium: bool) -> int:
    rate = HOUSE_SELL_RATE_PREMIUM if premium else HOUSE_SELL_RATE
    return round(price * rate)


def _house_catalog_lines() -> str:
    lines = []
    for key, info in HOUSE_CATALOG.items():
        lines.append(
            f"🏠 <code>{key}</code> — {info['name']}: {info['price']} искр, "
            f"постройка {info['build_days']} дн., слотов {info['room_slots']}, "
            f"обслуживание {info['maintenance_pct']}%/нед"
        )
    return "\n".join(lines)


def _house_room_catalog_lines(category: Optional[str] = None) -> str:
    lines = []
    for key, info in ROOM_CATALOG.items():
        if category and info["category"] != category:
            continue
        action = f" · действие «{info['action_name']}»: {info['reward']} искр/{info['cooldown_hours']}ч" if info["reward"] else ""
        lines.append(f"🚪 <code>{key}</code> — {info['name']} ({info['price']} искр, +{info['prestige']} престижа/ур.){action}")
    return "\n".join(lines)


async def _get_pair_or_reply(message: Message) -> Optional[dict]:
    pair = await db.get_rel2_pair(message.chat.id, message.from_user.id)
    if not pair:
        await message.reply(
            "Вы пока ни с кем не в отношениях. Команда <b>отн запрос</b> ответом на "
            "сообщение человека — сделать предложение."
        )
        return None
    return pair


async def cmd_house_menu(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])

    if house is None:
        lines = [
            "🏠 <b>У вас пока нет дома.</b>",
            "Выберите дом из каталога командой <b>дом купить &lt;ключ&gt;</b>:",
            DIVIDER,
            _house_catalog_lines(),
        ]
        await message.reply("\n".join(lines))
        return

    info = HOUSE_CATALOG[house["house_key"]]
    if house["status"] == "building":
        remaining = house["ready_at"] - datetime.utcnow()
        hours_left = max(int(remaining.total_seconds() // 3600), 0)
        await message.reply(
            f"🏗 <b>{info['name']}</b> строится…\nОсталось примерно {hours_left} ч."
        )
        return

    rooms = await db.list_rel2_house_rooms(house["id"])
    upgrades = await db.list_rel2_house_upgrades(house["id"])
    prestige = house_prestige(rooms, upgrades)
    maintenance = house_weekly_maintenance(house["house_key"])

    lines = [
        f"🏠 <b>{info['name']}</b>",
        DIVIDER,
        f"⭐ Престиж: <b>{prestige}</b> (+{house_prestige_bonus(prestige) * 100:.1f}% к наградам)",
        f"🚪 Комнат: {len(rooms)}/{info['room_slots']}",
        f"🔧 Улучшений: {len(upgrades)}/{len(UPGRADE_CATALOG)}",
        f"💰 Обслуживание: {maintenance} искр / {HOUSE_MAINTENANCE_PERIOD_DAYS} дн.",
    ]
    if house["maintenance_warning_at"]:
        lines.append("⚠️ <b>Просрочена оплата обслуживания!</b> Пополните искры — иначе дом снесут.")
    if rooms:
        lines.append(DIVIDER)
        lines.append("🚪 <b>Ваши комнаты:</b>")
        for room in rooms:
            room_info = ROOM_CATALOG.get(room["room_key"])
            if not room_info:
                continue
            lines.append(f"· {room_info['name']} (ур. {room['level']})")
    lines.append(DIVIDER)
    lines.append(
        "Команды: <b>дом комнаты</b> [категория] — каталог комнат, "
        "<b>дом комната &lt;ключ&gt;</b> — купить, "
        "<b>дом улучшить &lt;ключ&gt;</b> — улучшения, "
        "<b>дом действие &lt;ключ комнаты&gt;</b> — заработать искры, "
        "<b>дом продать</b> — снести дом."
    )
    await message.reply("\n".join(lines))


async def cmd_house_buy(message: Message, house_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house_key = house_key.strip().casefold()
    if house_key not in HOUSE_CATALOG:
        await message.reply(f"Неизвестный дом. Доступные варианты:\n{_house_catalog_lines()}")
        return
    if await db.get_rel2_house(pair["id"]):
        await message.reply("У вашей пары уже есть дом (или он строится).")
        return

    price = HOUSE_CATALOG[house_key]["price"]
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}, у вас {pair['sparks']}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "house_purchase")
    ready_at = house_build_ready_at(house_key, True)
    house_id = await db.create_rel2_house(pair["id"], house_key, ready_at)
    if house_id is None:
        # Гонка (два одновременных запроса) — вернуть искры.
        await db.adjust_rel2_sparks(pair["id"], price, "house_purchase_refund")
        await message.reply("Не получилось — возможно, дом уже куплен.")
        return

    days = HOUSE_CATALOG[house_key]["build_days"] * (0.70 if True else 1)
    await message.reply(
        f"🏗 Началось строительство: <b>{HOUSE_CATALOG[house_key]['name']}</b> "
        f"(≈{days:.1f} дн.). Команда <b>дом</b> покажет прогресс."
    )
    await db.add_log("relationship2_house_bought", chat_id=message.chat.id, actor_id=message.from_user.id)


async def cmd_house_rooms_catalog(message: Message, category: str = "") -> None:
    category = category.strip().casefold()
    valid = {"жилая", "функциональная", "развлекательная", "особые"}
    if category and category not in valid:
        category = ""
    text = _house_room_catalog_lines(category or None)
    await message.reply(f"🚪 <b>Каталог комнат</b>{f' — {category}' if category else ''}\n{DIVIDER}\n{text}")


async def cmd_house_buy_room(message: Message, room_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    if not house or house["status"] != "active":
        await message.reply("У вас нет готового дома.")
        return
    room_key = room_key.strip().casefold()
    if room_key not in ROOM_CATALOG:
        await message.reply("Неизвестная комната. Посмотрите <b>дом комнаты</b>.")
        return
    room_info = ROOM_CATALOG[room_key]
    rooms = await db.list_rel2_house_rooms(house["id"])
    if any(r["room_key"] == room_key for r in rooms):
        await message.reply("Эта комната уже куплена — используйте <b>дом улучшить</b>.")
        return
    slots = HOUSE_CATALOG[house["house_key"]]["room_slots"]
    if len(rooms) >= slots:
        await message.reply(f"Нет свободных слотов ({len(rooms)}/{slots}).")
        return

    price = room_info["price"]
    if True:
        price = round(price * 0.85)  # -15% премиум скидка
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}, у вас {pair['sparks']}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "house_room_purchase")
    await db.add_rel2_house_room(house["id"], room_key)
    await message.reply(f"🚪 Комната <b>{room_info['name']}</b> куплена за {price} искр!")


async def cmd_house_upgrade_room(message: Message, room_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    if not house or house["status"] != "active":
        await message.reply("У вас нет готового дома.")
        return
    room_key = room_key.strip().casefold()
    room = await db.get_rel2_house_room(house["id"], room_key)
    if not room:
        await message.reply("У вас нет такой комнаты.")
        return
    room_info = ROOM_CATALOG.get(room_key)
    if not room_info:
        await message.reply("Неизвестная комната.")
        return
    if room["level"] >= 4:
        await message.reply("Комната уже максимального уровня (4).")
        return

    price = room_next_level_price(room_key, room["level"])
    if True:
        price = round(price * 0.85)
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}, у вас {pair['sparks']}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "house_room_upgrade")
    await db.upgrade_rel2_house_room_level(house["id"], room_key)
    await message.reply(f"🔧 {room_info['name']} улучшена до уровня {room['level'] + 1} за {price} искр!")


async def cmd_house_upgrades_catalog(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    upgrades_by_key = {}
    if house and house["status"] == "active":
        for row in await db.list_rel2_house_upgrades(house["id"]):
            upgrades_by_key[row["upgrade_key"]] = row["level"]

    lines = ["🔧 <b>Улучшения дома</b>", DIVIDER]
    for key, info in UPGRADE_CATALOG.items():
        level = upgrades_by_key.get(key, 0)
        next_price = house_upgrade_price(key, level + 1) if level < UPGRADE_MAX_LEVEL else None
        status = f"ур. {level}/{UPGRADE_MAX_LEVEL}"
        price_text = f", след. ур. за {next_price} искр" if next_price else " (макс.)"
        lines.append(f"· <code>{key}</code> — {info['name']} ({status}{price_text})")
    lines.append(DIVIDER)
    lines.append("Команда <b>дом улучшить &lt;ключ&gt;</b> — купить следующий уровень.")
    await message.reply("\n".join(lines))


async def cmd_house_buy_upgrade(message: Message, upgrade_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    if not house or house["status"] != "active":
        await message.reply("У вас нет готового дома.")
        return
    upgrade_key = upgrade_key.strip().casefold()
    if upgrade_key not in UPGRADE_CATALOG:
        await message.reply("Неизвестное улучшение. Посмотрите <b>дом улучшения</b>.")
        return

    current = await db.get_rel2_house_upgrade(house["id"], upgrade_key)
    level = current["level"] if current else 0
    if level >= UPGRADE_MAX_LEVEL:
        await message.reply("Это улучшение уже максимального уровня.")
        return

    price = house_upgrade_price(upgrade_key, level + 1)
    if True:
        price = round(price * 0.85)
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}, у вас {pair['sparks']}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "house_upgrade_purchase")
    await db.bump_rel2_house_upgrade(house["id"], upgrade_key)
    name = UPGRADE_CATALOG[upgrade_key]["name"]
    await message.reply(f"🔧 {name} улучшено до уровня {level + 1} за {price} искр!")


# ============================================================================
# 🎲 МОДУЛЬ 9 — СЛУЧАЙНЫЕ СОБЫТИЯ ДОМА (расширение модуля 3). Каждый раз при
# «дом действие …» есть небольшой шанс на модификатор награды — как приятный
# сюрприз, так и небольшую неудачу (см. применение в cmd_house_action ниже).
# ============================================================================
HOUSE_RANDOM_EVENTS: list[dict] = [
    {"key": "guests",  "text": "🎉 Неожиданно заглянули гости и оставили щедрые чаевые!", "chance": 0.08, "mult": 1.5},
    {"key": "jackpot", "text": "🍀 Невероятная удача — джекпот!",                        "chance": 0.02, "mult": 2.0},
    {"key": "mess",    "text": "🧹 Кто-то устроил беспорядок — пришлось убираться.",       "chance": 0.10, "mult": 0.6},
]


def roll_house_event(reward: int) -> tuple[int, Optional[str]]:
    roll = random.random()
    cumulative = 0.0
    for event in HOUSE_RANDOM_EVENTS:
        cumulative += event["chance"]
        if roll < cumulative:
            return round(reward * event["mult"]), event["text"]
    return reward, None


# ============================================================================
# 🏅 МОДУЛЬ 10 — РЕЙТИНГ ДОМОВ ЧАТА (расширение модуля 3). Считает престиж
# каждого активного дома в чате (та же house_prestige(), что и в «дом меню»)
# и показывает топ-10 пар по этому показателю.
# ============================================================================
async def cmd_house_top(message: Message) -> None:
    rows = await db.list_rel2_houses_in_chat(message.chat.id)
    if not rows:
        await message.reply("В этом чате пока нет ни одного готового дома.")
        return

    scored = []
    for row in rows:
        rooms = await db.list_rel2_house_rooms(row["id"])
        upgrades = await db.list_rel2_house_upgrades(row["id"])
        prestige = house_prestige(rooms, upgrades)
        scored.append((prestige, row))
    scored.sort(key=lambda x: x[0], reverse=True)

    lines = ["🏅 <b>Рейтинг домов чата</b>", DIVIDER]
    for i, (prestige, row) in enumerate(scored[:10], start=1):
        name1 = await _display_name_by_id(message.chat.id, row["user1_id"], message.bot)
        name2 = await _display_name_by_id(message.chat.id, row["user2_id"], message.bot)
        house_name = HOUSE_CATALOG[row["house_key"]]["name"]
        lines.append(f"{i}. {name1} & {name2} — {house_name}, престиж <b>{prestige}</b>")
    await message.reply("\n".join(lines))


async def cmd_house_action(message: Message, room_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    if not house or house["status"] != "active":
        await message.reply("У вас нет готового дома.")
        return
    room_key = room_key.strip().casefold()
    room = await db.get_rel2_house_room(house["id"], room_key)
    room_info = ROOM_CATALOG.get(room_key)
    if not room or not room_info:
        await message.reply("У вас нет такой комнаты.")
        return
    if not room_info["reward"]:
        await message.reply("В этой комнате нет активного действия.")
        return

    if room["last_action_at"]:
        cooldown = room_action_cooldown_hours(room_key, True)
        elapsed = (datetime.utcnow() - room["last_action_at"]).total_seconds() / 3600
        if elapsed < cooldown:
            remaining_h = cooldown - elapsed
            hours, minutes = int(remaining_h), int((remaining_h % 1) * 60)
            await message.reply(f"⏳ Действие ещё восстанавливается: осталось {hours} ч {minutes} мин.")
            return

    rooms = await db.list_rel2_house_rooms(house["id"])
    upgrades = await db.list_rel2_house_upgrades(house["id"])
    prestige = house_prestige(rooms, upgrades)
    reward = room_action_reward(room_key, room["level"], prestige, True)
    reward, event_text = roll_house_event(reward)

    new_balance = await db.adjust_rel2_sparks(pair["id"], reward, "house_room_action")
    await db.set_rel2_house_room_last_action(house["id"], room_key)
    new_level = level_from_sparks(new_balance) if new_balance is not None else pair["level_index"]
    if new_balance is not None and new_level != pair["level_index"]:
        await db.set_rel2_level(pair["id"], new_level)

    event_line = f"\n{event_text}" if event_text else ""
    await message.reply(
        f"✨ <b>{room_info.get('action_name', room_info['name'])}</b> в комнате «{room_info['name']}»: "
        f"+{reward} искр!{event_line}\nБаланс: {new_balance}."
    )


async def cmd_house_sell(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    house = await db.get_rel2_house(pair["id"])
    if not house:
        await message.reply("У вас нет дома.")
        return
    price = HOUSE_CATALOG[house["house_key"]]["price"]
    amount = house_sell_amount(price, True)
    await db.delete_rel2_house(house["id"])
    await db.adjust_rel2_sparks(pair["id"], amount, "house_sold")
    await message.reply(f"🏚 Дом продан за <b>{amount}</b> искр.")


async def house_maintenance_loop(bot, interval_seconds: int = 3600) -> None:
    """Раз в час: списывает обслуживание домов (раз в 7 дней на дом), выдаёт
    предупреждение при нехватке искр и сносит дом, если не оплачено в течение
    HOUSE_MAINTENANCE_GRACE_DAYS дней (см. гайд, «Система предупреждений»)."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            # 1. Завершить готовые постройки.
            for row in await db.list_rel2_houses_building_due():
                await db.finish_rel2_house_construction(row["id"])
                pair = await db.get_rel2_pair_by_id(row["pair_id"])
                if pair:
                    name = HOUSE_CATALOG[row["house_key"]]["name"]
                    text = f"🏠 Строительство завершено: <b>{name}</b> готов к заселению!"
                    try:
                        await bot.send_message(pair["chat_id"], text)
                    except Exception:
                        pass

            # 2. Списать обслуживание тем, кому пора.
            for row in await db.list_rel2_houses_due_for_maintenance(HOUSE_MAINTENANCE_PERIOD_DAYS):
                cost = house_weekly_maintenance(row["house_key"])
                if row["sparks"] >= cost:
                    pair = await db.get_rel2_pair_by_id(row["pair_id"])
                    if pair:
                        await db.adjust_rel2_sparks(pair["id"], -cost, "house_maintenance")
                    await db.set_rel2_house_maintenance_paid(row["id"])
                else:
                    if not row["maintenance_warning_at"]:
                        await db.set_rel2_house_maintenance_warning(row["id"])
                        text = (
                            f"⚠️ Не хватает искр на обслуживание дома ({cost} искр). "
                            f"У вас {HOUSE_MAINTENANCE_GRACE_DAYS} дня, иначе дом будет снесён."
                        )
                        for uid in (row["user1_id"], row["user2_id"]):
                            try:
                                await bot.send_message(uid, text)
                            except Exception:
                                pass

            # 3. Снести дома с просроченной оплатой.
            for row in await db.list_rel2_houses_overdue(HOUSE_MAINTENANCE_GRACE_DAYS):
                await db.delete_rel2_house(row["id"])
                text = f"🏚 Дом «{HOUSE_CATALOG[row['house_key']]['name']}» снесён из-за неуплаты обслуживания."
                for uid in (row["user1_id"], row["user2_id"]):
                    try:
                        await bot.send_message(uid, text)
                    except Exception:
                        pass
        except Exception:
            logger.exception("Ошибка в house_maintenance_loop")
        await asyncio.sleep(interval_seconds)


# ============================================================================
# Диспетчер команд «дом» (аналогично «отн» выше — первый токен, без точки:
# в реальном чате пишется просто «дом …», как и «отн …»).
# ============================================================================

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().split()[0].casefold() == "дом"),
)
async def cmd_house_word(message: Message) -> None:
    parts = message.text.strip().split()
    sub = parts[1].casefold() if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    arg_rest = " ".join(parts[2:]) if len(parts) > 2 else ""

    if sub == "" or sub == "меню":
        await cmd_house_menu(message)
    elif sub == "купить" and arg:
        await cmd_house_buy(message, arg)
    elif sub == "комнаты":
        await cmd_house_rooms_catalog(message, arg_rest)
    elif sub == "комната" and arg:
        await cmd_house_buy_room(message, arg)
    elif sub == "улучшения":
        await cmd_house_upgrades_catalog(message)
    elif sub == "улучшить" and arg:
        await cmd_house_upgrade_room(message, arg) if await _room_exists_for_pair(message, arg) else await cmd_house_buy_upgrade(message, arg)
    elif sub == "действие" and arg:
        await cmd_house_action(message, arg)
    elif sub == "продать":
        await cmd_house_sell(message)
    elif sub == "топ":
        await cmd_house_top(message)
    else:
        await message.reply(
            "Доступно: <b>дом</b>, <b>дом купить &lt;ключ&gt;</b>, <b>дом комнаты</b> [категория], "
            "<b>дом комната &lt;ключ&gt;</b>, <b>дом улучшения</b>, <b>дом улучшить &lt;ключ&gt;</b>, "
            "<b>дом действие &lt;ключ комнаты&gt;</b>, <b>дом продать</b>, <b>дом топ</b>."
        )


async def _room_exists_for_pair(message: Message, room_key: str) -> bool:
    """«дом улучшить X» — X может быть и ключом комнаты (апгрейд уровня
    комнаты), и ключом инженерного улучшения (UPGRADE_CATALOG). Разруливаем
    по тому, что уже куплено у пары; если ничего не куплено — считаем, что
    это инженерное улучшение (можно купить с нуля)."""
    pair = await db.get_rel2_pair(message.chat.id, message.from_user.id)
    if not pair:
        return False
    house = await db.get_rel2_house(pair["id"])
    if not house or house["status"] != "active":
        return False
    room = await db.get_rel2_house_room(house["id"], room_key.strip().casefold())
    return room is not None


# ============================================================================
# 🐾 МОДУЛЬ 4 — СИСТЕМА ПИТОМЦЕВ (яйца/редкость/характер/навыки/настроение и
# здоровье/кормление/действия/прокачка/домики). Питомец принадлежит паре
# (rel2_pets.pair_id) и кормится из общей казны искр — как в гайде.
# ============================================================================

# РЕШЕНО: цены и шансы взяты из гайда дословно, без изменений.
EGG_CATALOG: dict[str, dict] = {
    "common": {
        "name": "🥚 Обычное яйцо", "price_sparks": 10_000, "price_stars": None,
        "weights": {"обычный": 70, "необычный": 20, "редкий": 8, "эпический": 1.5, "легендарный": 0.5},
    },
    "golden": {
        "name": "🥚✨ Золотое яйцо", "price_sparks": 50_000, "price_stars": None,
        "weights": {"обычный": 2, "необычный": 13, "редкий": 45, "эпический": 38, "легендарный": 2},
    },
    "premium": {
        "name": "🌟🥚 Премиум яйцо", "price_sparks": None, "price_stars": 25,
        "weights": {"необычный": 5, "редкий": 25, "эпический": 60, "легендарный": 10},
    },
}

# Редкость → (макс. уровень, кол-во навыков, диапазон еды/дня, диапазон воды/дня) — из гайда.
RARITY_TABLE: dict[str, dict] = {
    "обычный":     {"emoji": "⚪️", "max_level": 10, "skills": 1, "food": (10, 20), "water": (8, 15)},
    "необычный":   {"emoji": "🟢", "max_level": 20, "skills": 2, "food": (12, 25), "water": (8, 18)},
    "редкий":      {"emoji": "🔵", "max_level": 30, "skills": 2, "food": (15, 30), "water": (10, 20)},
    "эпический":   {"emoji": "🟣", "max_level": 40, "skills": 3, "food": (20, 40), "water": (15, 30)},
    "легендарный": {"emoji": "🟡", "max_level": 50, "skills": 5, "food": (40, 70), "water": (30, 50)},
}

# РЕШЕНО: стартовый список видов — 40 (гайд говорит «более 100», но не
# перечисляет их; выдумывать 100 названий ради самого числа смысла не было).
# Список ни на что в механике не влияет (вид выбирается случайно, без связи
# с редкостью), поэтому расширяется одной строкой на вид в любой момент.
PET_SPECIES: list[str] = [
    "Собака", "Кот", "Лиса", "Волк", "Дракон", "Феникс", "Единорог", "Кролик",
    "Хомяк", "Панда", "Тигр", "Лев", "Медведь", "Енот", "Сова", "Ворон",
    "Ящерица", "Черепаха", "Змея", "Хорёк", "Белка", "Ёж", "Пони", "Олень",
    "Кабан", "Выдра", "Летучая мышь", "Пингвин", "Тюлень", "Дельфин", "Акула",
    "Осьминог", "Краб", "Бабочка", "Стрекоза", "Скорпион", "Паук", "Гриф",
    "Грифон", "Слизень",
]

# Положительные навыки — дословно из гайда (ключ → уровни 1-3: значения).
PET_POSITIVE_SKILLS: dict[str, dict] = {
    "spark_talisman":   {"name": "✨ Талисман искр",        "levels": [(4, 3), (6, 5), (8, 7)]},          # (%действия партнёра, %дом)
    "cooldown_cutter":  {"name": "⏱️ Сокращатель откатов",  "levels": [(-3, -2), (-5, -4), (-7, -6)]},
    "thrifty_house":    {"name": "🏠 Экономный домовой",     "levels": [(-5, -3), (-8, -5), (-10, -7)]},   # (%содержание, %улучшения)
    "nanny":            {"name": "👶 Нянька",                "levels": [(5,), (7,), (10,)]},
    "coupon":           {"name": "🎟️ Купонщик",              "levels": [(-5,), (-7,), (-10,)]},
    "realtor":          {"name": "🧱 Риелтор",                "levels": [(-5, -3), (-10, -6), (-15, -10)]}, # (%время, %цена)
    "lucky_companion":  {"name": "🍀 Удачливый компаньон",    "levels": [(2, 5), (3, 7), (5, 10)]},         # (%шанс, %бонус)
    "midwife_helper":   {"name": "🩺 Акушер-помощник",        "levels": [(-10,), (-15,), (-20,)]},
    "resale_luck":       {"name": "💸 Удачная перепродажа",   "levels": [(5,), (10,), (15,)]},
}

PET_NEGATIVE_SKILLS: dict[str, dict] = {
    "gluttonous":  {"name": "🍽️ Прожорливый",   "levels": [(4, -80), (6, -120), (10, -180)]},  # (%шанс, -искр)
    "lazy":        {"name": "💤 Ленивый",        "levels": [(5,), (10,), (15,)]},
    "spender":     {"name": "💳 Растратчик",      "levels": [(5,), (10,), (15,)]},
    "house_wrecker": {"name": "🏚️ Дом-разрушитель", "levels": [(8, 6), (15, 10), (22, 15)]},
    "jealous":     {"name": "😾 Ревнивый",        "levels": [(3, -15), (5, -20), (8, -30)]},
    "evil_eye":    {"name": "🧿 Сглаз",           "levels": [(6,), (12,), (18,)]},
    "anti_nanny":  {"name": "🤒 Антинянька",      "levels": [(-6,), (-12,), (-18,)]},
    "unlucky":     {"name": "📉 Неудачник",       "levels": [(-3, -50), (-5, -80), (-8, -120)]},
    "time_thief":  {"name": "🧨 Вор времени",     "levels": [(10,), (20,), (30,)]},
}

PET_ACTIONS: dict[str, dict] = {
    "play":  {"name": "🎾 Играть",         "mood": 20, "xp": 15, "cooldown_min": 30, "price": 0},
    "pet":   {"name": "🤗 Погладить",      "mood": 10, "xp": 5,  "cooldown_min": 10, "price": 0},
    "train": {"name": "🏃 Тренировать",    "mood": 5,  "xp": 25, "cooldown_min": 60, "price": 50},
    "treat": {"name": "🦴 Дать лакомство", "mood": 15, "xp": 10, "cooldown_min": 40, "price": 100},
}

PET_HOME_CATALOG: dict[str, dict] = {
    "box":     {"name": "📦 Картонная коробка",   "price": 0,       "slots": 0, "mood_bonus": 0,  "xp_bonus": 0,   "skill_bonus": 0,   "mood_decay_bonus": 0},
    "cottage": {"name": "🏡 Уютный коттедж",       "price": 75_000,  "slots": 2, "mood_bonus": 5,  "xp_bonus": 0,   "skill_bonus": 0,   "mood_decay_bonus": 0},
    "mansion": {"name": "🏰 Просторный особняк",   "price": 200_000, "slots": 4, "mood_bonus": 10, "xp_bonus": 0.10,"skill_bonus": 0,   "mood_decay_bonus": 0},
    "castle":  {"name": "🏛️ Величественный замок", "price": 500_000, "slots": 6, "mood_bonus": 15, "xp_bonus": 0.20,"skill_bonus": 0.15,"mood_decay_bonus": 0.10},
}

PET_HOME_ROOM_CATALOG: dict[str, dict] = {
    "playroom":     {"name": "🎮 Игровая комната", "price": 20_000, "mood_bonus": 3},
    "restaurant":   {"name": "🍽️ Ресторан",        "price": 25_000, "mood_decay_bonus": 0.04, "consumption_cut": 0.05},
    "gym":          {"name": "🏋️ Тренажёрный зал",  "price": 28_000, "xp_bonus": 0.05},
    "spa":          {"name": "🛀 СПА-зона",         "price": 30_000, "mood_growth_bonus": 0.05},
    "meditation":   {"name": "🧘 Комната медитации", "price": 32_000, "mood_decay_bonus": 0.03, "mood_growth_bonus": 0.03},
    "art_studio":   {"name": "🎨 Арт-студия",       "price": 35_000, "mood_bonus": 2, "xp_bonus": 0.03},
    "library":      {"name": "📚 Библиотека",       "price": 40_000, "skill_bonus": 0.04},
    "observatory":  {"name": "🔭 Обсерватория",     "price": 45_000, "skill_bonus": 0.03, "xp_bonus": 0.04},
}

PET_XP_EXPONENT = 1.5


def pet_xp_threshold(level: int) -> int:
    return round(100 * (level ** PET_XP_EXPONENT))


def roll_egg_rarity(egg_key: str) -> str:
    weights = EGG_CATALOG[egg_key]["weights"]
    rarities = list(weights.keys())
    return random.choices(rarities, weights=[weights[r] for r in rarities], k=1)[0]


def roll_pet_temperament() -> int:
    """-10..+10, экстремальные значения — редкость (нормальное распределение,
    обрезанное по диапазону, как и указано в гайде — «большинство ближе к нулю»)."""
    value = round(random.gauss(0, 3.3))
    return max(-10, min(10, value))


def temperament_multipliers(temperament: int) -> tuple[float, float]:
    """Возвращает (множитель_падения, множитель_роста) настроения — каждая
    единица характера = 5% разницы (см. гайд, «Как именно это работает»)."""
    decay = 1 - temperament * 0.05
    growth = 1 + temperament * 0.05
    return max(decay, 0.1), max(growth, 0.1)


def temperament_type_name(temperament: int) -> str:
    if temperament <= -7:
        return "😔 Меланхоличный"
    if temperament <= -3:
        return "😞 Грустный"
    if temperament <= 2:
        return "😐 Спокойный"
    if temperament <= 6:
        return "😊 Жизнерадостный"
    return "🤩 Восторженный"


def roll_pet_skills(rarity: str) -> list[dict]:
    count = RARITY_TABLE[rarity]["skills"]
    pool = list(PET_POSITIVE_SKILLS.keys()) + list(PET_NEGATIVE_SKILLS.keys())
    chosen = random.sample(pool, k=min(count, len(pool)))
    return [{"key": key, "level": random.randint(1, 3)} for key in chosen]


def _skill_info(skill_key: str) -> Optional[dict]:
    return PET_POSITIVE_SKILLS.get(skill_key) or PET_NEGATIVE_SKILLS.get(skill_key)


def pet_skill_effectiveness(pet: dict) -> float:
    """Множитель эффективности навыков (0 если неактивен/настроение <30%,
    иначе растёт с настроением и уровнем — до +10% на 50 уровне, см. гайд)."""
    if not pet["is_active"] or pet["mood"] < 30:
        return 0.0
    level_bonus = pet["level_index"] * 0.002
    mood_factor = pet["mood"] / 100
    return round((1 + level_bonus) * mood_factor, 4)


def pet_home_bonus_totals(home: Optional[dict]) -> dict:
    """Суммирует бонусы домика + всех купленных комнат (см. гайд — «Бонусы от
    домика и всех комнат суммируются»)."""
    totals = {"mood_bonus": 0, "mood_decay_bonus": 0.0, "mood_growth_bonus": 0.0,
              "xp_bonus": 0.0, "skill_bonus": 0.0, "consumption_cut": 0.0}
    if not home:
        return totals
    base = PET_HOME_CATALOG.get(home["home_key"], {})
    for k in ("mood_bonus", "mood_decay_bonus", "xp_bonus", "skill_bonus"):
        totals[k] += base.get(k, 0)
    for room_key in home["rooms"]:
        room = PET_HOME_ROOM_CATALOG.get(room_key, {})
        for k in totals:
            totals[k] += room.get(k, 0)
    return totals


def pet_food_water_cost(pet: dict, home: Optional[dict]) -> int:
    bonuses = pet_home_bonus_totals(home)
    cut = 1 - bonuses["consumption_cut"]
    food_cost = pet["food_need"] * cut * 5
    water_cost = pet["water_need"] * cut * 3
    return round(food_cost + water_cost)


def _pet_card_lines(pet: dict, home: Optional[dict]) -> list[str]:
    rarity_info = RARITY_TABLE[pet["rarity"]]
    decay_mult, growth_mult = temperament_multipliers(pet["temperament"])
    lines = [
        f"{rarity_info['emoji']} <b>{html.escape(pet['name'])}</b> — {pet['species']} "
        f"({'активен' if pet['is_active'] else 'неактивен'})",
        f"⭐ Уровень: {pet['level_index']}/{rarity_info['max_level']} · XP: {pet['xp']}",
        f"❤️ HP: {pet['hp']}% · 😊 Настроение: {pet['mood']}%",
        f"🎭 Характер: {temperament_type_name(pet['temperament'])} "
        f"(📉 Падение: {decay_mult:.2f}x | 📈 Рост: {growth_mult:.2f}x)",
        f"🍖 Еда: {pet['food_need']}/день · 💧 Вода: {pet['water_need']}/день",
    ]
    if pet["skills"]:
        lines.append("🎯 Навыки:")
        for skill in pet["skills"]:
            info = _skill_info(skill["key"])
            if info:
                lines.append(f"  · {info['name']} (ур. {skill['level']})")
    eff = pet_skill_effectiveness(pet)
    lines.append(f"⚙️ Эффективность навыков сейчас: {eff * 100:.0f}%")
    if home:
        home_info = PET_HOME_CATALOG[home["home_key"]]
        lines.append(f"🏠 Домик: {home_info['name']} (комнат: {len(home['rooms'])}/{home_info['slots']})")
    else:
        lines.append("🏠 Домик: нет (📦 картонная коробка по умолчанию)")
    return lines


async def cmd_pet_menu(message: Message, arg_rest: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    pets = await db.list_rel2_pets(pair["id"])
    if not pets:
        lines = [
            "🐾 <b>У вас пока нет питомцев.</b>",
            "Купите яйцо: <b>отн пт яйцо &lt;ключ&gt;</b>",
            DIVIDER,
        ]
        for key, info in EGG_CATALOG.items():
            price = f"{info['price_sparks']} искр" if info["price_sparks"] else f"{info['price_stars']} ⭐"
            lines.append(f"· <code>{key}</code> — {info['name']} ({price})")
        await message.reply("\n".join(lines))
        return

    lines = ["🐾 <b>Ваши питомцы</b>", DIVIDER]
    for pet in pets:
        rarity_info = RARITY_TABLE[pet["rarity"]]
        marker = "⭐" if pet["is_active"] else "·"
        lines.append(
            f"{marker} #{pet['id']} {rarity_info['emoji']} {html.escape(pet['name'])} "
            f"({pet['species']}, ур. {pet['level_index']}, {pet['mood']}% настроения)"
        )
    lines.append(DIVIDER)
    lines.append(
        "Команды: <b>отн пт карта &lt;id&gt;</b>, <b>отн пт действие &lt;id&gt; &lt;действие&gt;</b>, "
        "<b>отн пт актив &lt;id&gt;</b>, <b>отн пт имя &lt;id&gt; &lt;имя&gt;</b>, "
        "<b>отн пт домик &lt;id&gt; &lt;ключ&gt;</b>, <b>отн пт комната &lt;id&gt; &lt;ключ&gt;</b>, "
        "<b>отн пт отпустить &lt;id&gt;</b>, <b>отн пт яйцо &lt;ключ&gt;</b>."
    )
    await message.reply("\n".join(lines))


async def cmd_pet_buy_egg(message: Message, egg_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    egg_key = egg_key.strip().casefold()
    if egg_key not in EGG_CATALOG:
        await message.reply("Неизвестное яйцо. Варианты: common, golden, premium.")
        return
    egg = EGG_CATALOG[egg_key]

    if egg["price_stars"] is not None:
        await message.reply(
            f"🌟 {egg['name']} покупается за {egg['price_stars']} звёзд — оплата звёздами "
            f"пока не подключена к этой команде, обратитесь к разделу «отн прем»/«отн искры»."
        )
        return

    price = egg["price_sparks"]
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}, у вас {pair['sparks']}.")
        return

    rarity = roll_egg_rarity(egg_key)
    rarity_info = RARITY_TABLE[rarity]
    species = random.choice(PET_SPECIES)
    temperament = roll_pet_temperament()
    skills = roll_pet_skills(rarity)
    food_need = random.randint(*rarity_info["food"])
    water_need = random.randint(*rarity_info["water"])
    default_name = species

    await db.adjust_rel2_sparks(pair["id"], -price, "pet_egg_purchase")
    pet_id = await db.create_rel2_pet(
        pair["id"], default_name, species, rarity, egg_key, temperament, skills, food_need, water_need
    )
    pet = await db.get_rel2_pet(pet_id)

    lines = [f"🥚 Яйцо вскрылось! Вылупился {rarity_info['emoji']} <b>{species}</b>!", DIVIDER]
    lines += _pet_card_lines(pet, None)
    await message.reply("\n".join(lines))


async def _find_pair_pet(pair_id: int, pet_id: int) -> Optional[dict]:
    pet = await db.get_rel2_pet(pet_id)
    if not pet or pet["pair_id"] != pair_id:
        return None
    return pet


async def cmd_pet_card(message: Message, pet_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца — см. <b>отн пт</b>.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    home = await db.get_rel2_pet_home(pet_id)
    await message.reply("\n".join(_pet_card_lines(pet, home)))


async def cmd_pet_set_active(message: Message, pet_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    await db.set_rel2_active_pet(pair["id"], pet_id)
    await message.reply(f"⭐ <b>{html.escape(pet['name'])}</b> теперь активный питомец.")


async def cmd_pet_rename(message: Message, pet_id_str: str, new_name: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    new_name = new_name.strip()
    if not (2 <= len(new_name) <= 20):
        await message.reply("Имя должно быть от 2 до 20 символов.")
        return
    await db.rename_rel2_pet(pet_id, new_name)
    await message.reply(f"✏️ Питомец переименован в <b>{html.escape(new_name)}</b>.")


async def cmd_pet_release(message: Message, pet_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    await db.release_rel2_pet(pet_id)
    await message.reply(f"💔 {html.escape(pet['name'])} отпущен на волю. Это необратимо.")


async def cmd_pet_action(message: Message, pet_id_str: str, action_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    action_key = action_key.strip().casefold()
    action = PET_ACTIONS.get(action_key)
    if not action:
        await message.reply("Действия: play, pet, train, treat.")
        return

    last_at = pet.get(f"last_action_{action_key}")
    if last_at:
        elapsed_min = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed_min < action["cooldown_min"]:
            remaining = int(action["cooldown_min"] - elapsed_min)
            await message.reply(f"⏳ Действие восстановится через {remaining} мин.")
            return

    if action["price"] > 0:
        if pair["sparks"] < action["price"]:
            await message.reply(f"Не хватает искр: нужно {action['price']}.")
            return
        await db.adjust_rel2_sparks(pair["id"], -action["price"], "pet_action")

    _, growth_mult = temperament_multipliers(pet["temperament"])
    home = await db.get_rel2_pet_home(pet_id)
    bonuses = pet_home_bonus_totals(home)
    mood_gain = round(action["mood"] * growth_mult * (1 + bonuses["mood_growth_bonus"]))
    xp_gain = round(action["xp"] * (1 + bonuses["xp_bonus"]))

    max_level = RARITY_TABLE[pet["rarity"]]["max_level"]
    await db.set_rel2_pet_action_cooldown(pet_id, action_key)
    updated = await db.add_rel2_pet_xp_mood(pet_id, xp_gain, mood_gain, max_level)

    await message.reply(
        f"{action['name']}: настроение +{mood_gain}, опыт +{xp_gain}. "
        f"Уровень: {updated['level_index']}, настроение: {updated['mood']}%."
    )


async def cmd_pet_set_home(message: Message, pet_id_str: str, home_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    home_key = home_key.strip().casefold()
    if home_key not in PET_HOME_CATALOG:
        lines = ["Неизвестный домик. Варианты:", DIVIDER]
        for key, info in PET_HOME_CATALOG.items():
            lines.append(f"· <code>{key}</code> — {info['name']} ({info['price']} искр, слотов: {info['slots']})")
        await message.reply("\n".join(lines))
        return

    new_price = PET_HOME_CATALOG[home_key]["price"]
    current_home = await db.get_rel2_pet_home(pet_id)
    refund = 0
    if current_home:
        old_price = PET_HOME_CATALOG.get(current_home["home_key"], {}).get("price", 0)
        refund = round(old_price * 0.30)  # старый домик продаётся за 30%
    net_cost = max(new_price - refund, 0)
    if pair["sparks"] < net_cost:
        await message.reply(f"Не хватает искр: нужно {net_cost} (с учётом скидки за старый домик).")
        return

    if net_cost:
        await db.adjust_rel2_sparks(pair["id"], -net_cost, "pet_home_purchase")
    await db.set_rel2_pet_home(pair["id"], pet_id, home_key)
    note = " ⚠️ Все комнаты в старом домике потеряны." if current_home and current_home["rooms"] else ""
    await message.reply(f"🏠 Домик сменён на <b>{PET_HOME_CATALOG[home_key]['name']}</b> за {net_cost} искр.{note}")


async def cmd_pet_buy_home_room(message: Message, pet_id_str: str, room_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID питомца.")
        return
    pet = await _find_pair_pet(pair["id"], pet_id)
    if not pet:
        await message.reply("Питомец не найден.")
        return
    home = await db.get_rel2_pet_home(pet_id)
    if not home:
        await message.reply("У питомца нет домика (кроме бесплатной коробки без слотов). Купите домик: <b>отн пт домик</b>.")
        return
    room_key = room_key.strip().casefold()
    if room_key not in PET_HOME_ROOM_CATALOG:
        lines = ["Неизвестная комната. Варианты:", DIVIDER]
        for key, info in PET_HOME_ROOM_CATALOG.items():
            lines.append(f"· <code>{key}</code> — {info['name']} ({info['price']} искр)")
        await message.reply("\n".join(lines))
        return
    slots = PET_HOME_CATALOG[home["home_key"]]["slots"]
    if len(home["rooms"]) >= slots:
        await message.reply(f"Нет свободных слотов ({len(home['rooms'])}/{slots}).")
        return

    price = PET_HOME_ROOM_CATALOG[room_key]["price"]
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}.")
        return

    added = await db.add_rel2_pet_home_room(pet_id, room_key)
    if not added:
        await message.reply("Эта комната уже куплена для этого питомца.")
        return
    await db.adjust_rel2_sparks(pair["id"], -price, "pet_home_room_purchase")
    await message.reply(f"🚪 Комната <b>{PET_HOME_ROOM_CATALOG[room_key]['name']}</b> добавлена в домик за {price} искр.")


async def pet_upkeep_loop(bot, interval_seconds: int = 3600) -> None:
    """Раз в час: тикает настроение (падение ~2%/час, модифицированное
    характером/домиком) и, раз в 24 часа на питомца, кормит его из казны
    пары (см. гайд, «Кормление и содержание»/«Настроение и здоровье»)."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            rows = await db.list_rel2_pets_for_feeding_tick()
            for row in rows:
                pet = db._rel2_pet_row(row)
                home = await db.get_rel2_pet_home(pet["id"])
                bonuses = pet_home_bonus_totals(home)
                decay_mult, _growth_mult = temperament_multipliers(pet["temperament"])
                decay_mult *= (1 - bonuses["mood_decay_bonus"])

                new_mood = pet["mood"] - round(2 * decay_mult)
                new_hp = pet["hp"]

                needs_feeding = (
                    pet["last_fed_at"] is None
                    or (datetime.utcnow() - pet["last_fed_at"]).total_seconds() >= 24 * 3600
                )
                if needs_feeding:
                    cost = pet_food_water_cost(pet, home)
                    if row["sparks"] >= cost:
                        pair = await db.get_rel2_pair_by_id(pet["pair_id"])
                        if pair:
                            await db.adjust_rel2_sparks(pair["id"], -cost, "pet_feeding")
                        await db.set_rel2_pet_last_fed(pet["id"])
                    else:
                        new_hp = max(0, new_hp - 10)

                if pet["last_fed_at"] and (datetime.utcnow() - pet["last_fed_at"]).total_seconds() > 2 * 24 * 3600:
                    new_hp = max(0, new_hp - round(10 / 24))  # 10%/день, применяем почасово

                new_mood = max(0, min(100, new_mood))
                new_hp = max(0, min(100, new_hp))
                await db.set_rel2_pet_mood_hp(pet["id"], new_mood, new_hp)

                if new_hp <= 0:
                    await db.release_rel2_pet(pet["id"])
                    try:
                        await bot.send_message(
                            row["chat_id"], f"💔 Питомец {pet['name']} погиб от истощения."
                        )
                    except Exception:
                        pass
        except Exception:
            logger.exception("Ошибка в pet_upkeep_loop")
        await asyncio.sleep(interval_seconds)


# ============================================================================
# Диспетчер «отн пт …» — встроен в общий диспетчер «отн» (cmd_rel2_word)
# как дополнительная ветка, см. правку в cmd_rel2_word ниже по коду модуля.
# ============================================================================

async def dispatch_pet_command(message: Message, rest: str) -> None:
    parts = rest.split()
    sub = parts[0].casefold() if parts else ""
    a1 = parts[1] if len(parts) > 1 else ""
    a2 = " ".join(parts[2:]) if len(parts) > 2 else ""

    if sub in ("", "меню"):
        await cmd_pet_menu(message, a2)
    elif sub == "яйцо" and a1:
        await cmd_pet_buy_egg(message, a1)
    elif sub == "карта" and a1:
        await cmd_pet_card(message, a1)
    elif sub == "актив" and a1:
        await cmd_pet_set_active(message, a1)
    elif sub == "имя" and a1 and a2:
        await cmd_pet_rename(message, a1, a2)
    elif sub == "отпустить" and a1:
        await cmd_pet_release(message, a1)
    elif sub == "действие" and a1 and a2:
        await cmd_pet_action(message, a1, a2.split()[0])
    elif sub == "домик" and a1 and a2:
        await cmd_pet_set_home(message, a1, a2)
    elif sub == "комната" and a1 and a2:
        await cmd_pet_buy_home_room(message, a1, a2)
    elif sub == "дуэль" and a1:
        await cmd_pet_duel(message, a1)
    else:
        await message.reply(
            "Питомцы: <b>отн пт</b>, <b>отн пт яйцо &lt;ключ&gt;</b>, <b>отн пт карта &lt;id&gt;</b>, "
            "<b>отн пт актив &lt;id&gt;</b>, <b>отн пт имя &lt;id&gt; &lt;имя&gt;</b>, "
            "<b>отн пт действие &lt;id&gt; &lt;play/pet/train/treat&gt;</b>, "
            "<b>отн пт домик &lt;id&gt; &lt;ключ&gt;</b>, <b>отн пт комната &lt;id&gt; &lt;ключ&gt;</b>, "
            "<b>отн пт дуэль &lt;id&gt;</b> ответом на сообщение соперника, "
            "<b>отн пт отпустить &lt;id&gt;</b>."
        )


# ============================================================================
# 🏆 МОДУЛЬ 8 — ДУЭЛИ ПИТОМЦЕВ (расширение модуля 4). Активный питомец пары
# может вызвать на дуэль активного питомца другой пары в том же чате (ответом
# на её сообщение). Победитель определяется «мощью» (уровень × вес редкости ×
# настроение/100 × случайный разброс ±15%) — проигравшая пара платит искры
# победившей. Кулдаун — общий rel2_cooldowns (scope="pet_duel", ref_id=pet_id).
# ============================================================================
PET_DUEL_RARITY_POWER: dict[str, float] = {
    "обычный": 1.0, "необычный": 1.3, "редкий": 1.7, "эпический": 2.2, "легендарный": 3.0,
}
PET_DUEL_COOLDOWN_HOURS = 4
PET_DUEL_BASE_REWARD = 300
PET_DUEL_MAX_REWARD = 5_000  # чтобы не разорять слабую пару за одну дуэль


def pet_duel_power(pet: dict) -> float:
    rarity_weight = PET_DUEL_RARITY_POWER.get(pet["rarity"], 1.0)
    mood_factor = max(pet["mood"], 10) / 100
    return pet["level_index"] * rarity_weight * mood_factor * random.uniform(0.85, 1.15)


async def cmd_pet_duel(message: Message, pet_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        pet_id = int(pet_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID вашего питомца.")
        return
    my_pet = await _find_pair_pet(pair["id"], pet_id)
    if not my_pet:
        await message.reply("Питомец не найден.")
        return

    opponent_user = await resolve_rel2_target(message)
    if opponent_user is None:
        await message.reply(
            "🏆 Ответьте этой командой на сообщение человека, чей активный питомец "
            "должен принять вызов: <b>отн пт дуэль &lt;id вашего питомца&gt;</b>."
        )
        return
    if opponent_user.id == message.from_user.id:
        await message.reply("Нельзя вызвать на дуэль самого себя 🙂")
        return

    opponent_pair = await db.get_rel2_pair(message.chat.id, opponent_user.id)
    if not opponent_pair:
        await message.reply("У этого человека нет пары с питомцами.")
        return
    if opponent_pair["id"] == pair["id"]:
        await message.reply("Нельзя устроить дуэль питомцев внутри одной пары 🙂")
        return
    opponent_pet = await db.get_rel2_active_pet(opponent_pair["id"])
    if not opponent_pet:
        await message.reply("У соперника нет активного питомца.")
        return

    last_at = await db.get_rel2_cooldown("pet_duel", pet_id, "duel")
    if last_at:
        elapsed_h = (datetime.utcnow() - last_at).total_seconds() / 3600
        if elapsed_h < PET_DUEL_COOLDOWN_HOURS:
            remaining = PET_DUEL_COOLDOWN_HOURS - elapsed_h
            await message.reply(f"⏳ Этот питомец сможет драться снова через {remaining:.1f} ч.")
            return

    my_power = pet_duel_power(my_pet)
    opp_power = pet_duel_power(opponent_pet)
    await db.set_rel2_cooldown("pet_duel", pet_id, "duel")

    winner_pair, loser_pair = (pair, opponent_pair) if my_power >= opp_power else (opponent_pair, pair)
    winner_pet, loser_pet = (my_pet, opponent_pet) if my_power >= opp_power else (opponent_pet, my_pet)

    reward = min(PET_DUEL_BASE_REWARD + winner_pet["level_index"] * 40, PET_DUEL_MAX_REWARD)
    reward = min(reward, max(loser_pair["sparks"], 0))  # проигравший не уходит в минус

    if reward > 0:
        await db.adjust_rel2_sparks(loser_pair["id"], -reward, "pet_duel_loss")
        await db.adjust_rel2_sparks(winner_pair["id"], reward, "pet_duel_win")

    await message.reply(
        f"🏆 <b>{html.escape(winner_pet['name'])}</b> побеждает <b>{html.escape(loser_pet['name'])}</b>! "
        f"({my_power:.1f} vs {opp_power:.1f} мощи)\n"
        f"Пара-победитель получает <b>{reward}</b> искр от проигравшей стороны."
    )


# ============================================================================
# 👶 МОДУЛЬ 5 — ДЕТИ. Ребёнком становится реальный пользователь по обоюдному
# согласию: «отн родить @user» работает как предложение отношений —
# запрос/кнопки принять-отклонить, только итог — запись в rel2_children, а не
# новая пара. Этот путь доступен всегда; альтернативный путь — через
# полноценную беременность (модуль 12 ниже), тогда «отн родить» доступен
# только по достижении 40-й недели. Дальше у ребёнка есть
# три абстрактных характеристики (здоровье/интеллект/харизма), настроение и
# уровень, три действия с откатом и — как расширение поверх базы — секции
# (модуль 6) и семейные события (модуль 7).
# ============================================================================

CHILD_LIMIT_NORMAL = 10
CHILD_LIMIT_PREMIUM = 30
CHILD_MAX_LEVEL = 20

# РЕШЕНО: сознательное упрощение. Гайд описывает полноценных детей с 20+
# характеристиками, кружками/школами/карьерами — здесь только три базовые
# характеристики (health/intellect/charisma). Это рабочая база, на которую
# модули 6-7 (секции, семейные события) накатываются поверх без переделки
# ядра; недостающие характеристики можно добавлять по той же схеме позже.
CHILD_ACTIONS: dict[str, dict] = {
    "play":  {"name": "🧸 Поиграть",        "mood": 15, "xp": 10, "stat_key": None,       "stat_delta": 0, "cooldown_min": 30, "price": 0},
    "care":  {"name": "🛁 Позаботиться",     "mood": 20, "xp": 8,  "stat_key": "health",    "stat_delta": 2, "cooldown_min": 45, "price": 50},
    "teach": {"name": "📖 Позаниматься",     "mood": 5,  "xp": 20, "stat_key": "intellect", "stat_delta": 3, "cooldown_min": 90, "price": 150},
}


def child_xp_threshold(level: int) -> int:
    return round(120 * (level ** 1.4))


def child_limit(premium: bool) -> int:
    return CHILD_LIMIT_PREMIUM if premium else CHILD_LIMIT_NORMAL


def _child_card_lines(child: dict) -> list[str]:
    lines = [
        f"👶 <b>{html.escape(child['name'])}</b>",
        f"⭐ Уровень: {child['level_index']}/{CHILD_MAX_LEVEL} · XP: {child['xp']}",
        f"😊 Настроение: {child['mood']}%",
        f"❤️ Здоровье: {child['health']} · 🧠 Интеллект: {child['intellect']} · ✨ Харизма: {child['charisma']}",
    ]
    if child["section_key"]:
        section = CHILD_SECTIONS.get(child["section_key"])
        if section:
            lines.append(f"🎓 Секция: {section['name']}")
    born_at: datetime = child["born_at"]
    lines.append(f"📅 В семье с: {born_at.strftime('%d.%m.%Y')}")
    lines.append(f"🆔 ID: <code>{child['id']}</code>")
    return lines


async def _find_pair_child(pair_id: int, child_id: int) -> Optional[dict]:
    child = await db.get_rel2_child(child_id)
    if child and child["pair_id"] == pair_id:
        return child
    return None


async def cmd_child_propose(message: Message, name_hint: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    actor = message.from_user
    target = await resolve_rel2_target(message)
    if target is None:
        await message.reply(
            "👶 Чтобы предложить кому-то стать вашим ребёнком, ответьте на его "
            "сообщение командой <b>отн родить</b> [имя], либо отправьте её с "
            "кликабельной ссылкой на него."
        )
        return
    if target.id == actor.id:
        await message.reply("Нельзя сделать ребёнком самого себя 🙂")
        return
    if target.is_bot:
        await message.reply("Боты пока не встречаются 🤖")
        return
    if target.id == pair["partner_id"]:
        await message.reply("Нельзя сделать ребёнком своего партнёра 🙂")
        return

    count = await db.count_rel2_children(pair["id"])
    # Ачивку «Многодетный» здесь не выдаём: это только ПРЕДЛОЖЕНИЕ, ребёнка
    # ещё нет. Выдача — в child_accept_button, после реального добавления.
    limit = child_limit(True)
    if count >= limit:
        await message.reply(f"Лимит детей исчерпан: {count}/{limit}.")
        return

    # Если у пары есть активная беременность (см. модуль 12) — «отн родить»
    # оформляет именно её, но только когда доношена (неделя 40); до срока
    # путь «отн родить» без зачатия (мгновенное согласие) для этой пары
    # закрыт, чтобы у беременности был смысл ждать. Пары без беременности
    # пользуются «отн родить» как раньше, без ограничений.
    pregnancy_id: Optional[int] = None
    active_pregnancy = await db.get_active_rel2_pregnancy(pair["id"])
    if active_pregnancy:
        if not pregnancy_is_due(active_pregnancy["started_at"], True):
            week = pregnancy_week(active_pregnancy["started_at"], True)
            eta = pregnancy_eta(active_pregnancy["started_at"], True)
            await message.reply(
                f"🤰 Беременность ещё не доношена (неделя {week}/{PREGNANCY_TOTAL_WEEKS}"
                f"{f', осталось ~{eta}' if eta else ''}). Подробнее — <b>отн беременность</b>."
            )
            return
        pregnancy_id = active_pregnancy["id"]

    name = (name_hint or "").strip()[:20] or (getattr(target, "full_name", None) or "Малыш")[:20]

    await db.create_rel2_child_request(message.chat.id, actor.id, target.id, name, pregnancy_id)
    actor_name = await _display_name(message.chat.id, actor, message.bot)
    target_name = await _display_name(message.chat.id, target, message.bot)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="👶 Принять", callback_data=f"child_accept:{actor.id}:{target.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"child_decline:{actor.id}:{target.id}"),
        ]]
    )
    await message.reply(
        f"👶 {actor_name} предлагает {target_name} стать ребёнком в их отношениях "
        f"(имя: <b>{html.escape(name)}</b>)!\n"
        f"{target_name}, решать вам — примите кнопкой ниже.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("child_accept:"))
async def child_accept_button(callback: CallbackQuery):
    _, proposer_id, target_id = callback.data.split(":")
    proposer_id, target_id = int(proposer_id), int(target_id)
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    request = await db.get_latest_rel2_child_request(chat_id, target_id)
    if not request or request["from_user_id"] != proposer_id:
        await callback.answer("Предложение больше не активно.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        return

    pair = await db.get_rel2_pair(chat_id, proposer_id)
    ok = False
    if pair:
        count = await db.count_rel2_children(pair["id"])
        if count < child_limit(True):
            new_child_id = await db.create_rel2_child(pair["id"], target_id, request["child_name"])
            # 🌟 Таланты (1/премиум до 3) и 🩺 врождённое состояние (шанс при рождении)
            await db.set_rel2_child_talents(new_child_id, roll_child_talents(True))
            congenital = roll_child_congenital()
            if congenital:
                await db.set_rel2_child_congenital(new_child_id, congenital)
                await db.set_rel2_child_vitality(new_child_id, child_max_vitality({"congenital_key": congenital}))
            if request.get("pregnancy_id"):
                await db.complete_rel2_pregnancy(request["pregnancy_id"])
            # Пятый ребёнок — ачивка «👨‍👩‍👧 Многодетный» обоим родителям.
            # Считаем ПОСЛЕ добавления (count — это сколько было до), иначе
            # порог срабатывал бы на шестом.
            if count + 1 >= FAMILY_ACHIEVEMENT_CHILDREN:
                for parent_id in (proposer_id, pair["partner_id"]):
                    await grant_achievement(chat_id, parent_id, "family_5kids")
            ok = True

    await db.delete_rel2_child_request(chat_id, proposer_id, target_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    if ok:
        target_name = await _display_name_by_id(chat_id, target_id, callback.bot)
        await callback.answer("Готово! 👶", show_alert=False)
        await callback.message.answer(f"👶 {target_name} теперь часть семьи как «{html.escape(request['child_name'])}»!")
        await db.add_log("relationship2_child_added", chat_id=chat_id, actor_id=proposer_id, target_id=target_id)
    else:
        await callback.answer("Не получилось — возможно, лимит детей исчерпан или отношения закончились.", show_alert=True)


@router.callback_query(F.data.startswith("child_decline:"))
async def child_decline_button(callback: CallbackQuery):
    _, proposer_id, target_id = callback.data.split(":")
    proposer_id, target_id = int(proposer_id), int(target_id)
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    await db.delete_rel2_child_request(chat_id, proposer_id, target_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer("Предложение отклонено.")
    try:
        target_name = await _display_name_by_id(chat_id, target_id, callback.bot)
        await callback.message.answer(f"❌ {target_name} отклонил(а) предложение.")
    except Exception:
        pass


async def cmd_child_list(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    children = await db.list_rel2_children(pair["id"])
    if not children:
        await message.reply(
            "👶 У вас пока нет детей. Ответьте на сообщение человека командой "
            "<b>отн родить</b> [имя], чтобы предложить ему стать вашим ребёнком."
        )
        return
    lines = [f"👶 <b>Дети ({len(children)}/{child_limit(pair['premium'])})</b>", DIVIDER]
    for child in children:
        lines.append(f"· <b>{html.escape(child['name'])}</b> (ID: {child['id']}, ур. {child['level_index']})")
    lines.append(DIVIDER)
    lines.append("Команда <b>ребенок профиль &lt;id&gt;</b> — подробная карточка.")
    await message.reply("\n".join(lines))


async def cmd_child_profile(message: Message, child_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка (см. <b>ребенок список</b>).")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return
    lines = _child_card_lines(child)
    lines.extend(_child_extended_lines(child, True))
    lines.append(DIVIDER)
    lines.extend(await _child_diseases_lines(child_id))
    lines.append(DIVIDER)
    lines.append(
        "Действия: <b>рб действие &lt;id&gt; play/care/teach</b>, "
        "<b>рб секция &lt;id&gt; &lt;ключ&gt;</b>, <b>рб школа &lt;id&gt; &lt;тип&gt;</b>, "
        "<b>рб лечить &lt;id&gt;</b>, <b>рб имя &lt;id&gt; &lt;имя&gt;</b>."
    )
    await message.reply("\n".join(lines))


async def cmd_child_rename(message: Message, child_id_str: str, new_name: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return
    new_name = new_name.strip()[:20]
    if len(new_name) < 2:
        await message.reply("Имя должно быть от 2 до 20 символов.")
        return
    await db.rename_rel2_child(child_id, new_name)
    await message.reply(f"✏️ Ребёнок переименован в <b>{html.escape(new_name)}</b>.")


async def cmd_child_release(message: Message, child_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return
    await db.release_rel2_child(child_id, pair["id"])
    await message.reply(f"💔 {html.escape(child['name'])} покидает семью. Это необратимо.")


async def cmd_child_action(message: Message, child_id_str: str, action_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return
    action_key = action_key.strip().casefold()
    action = CHILD_ACTIONS.get(action_key)
    if not action:
        await message.reply("Действия: play, care, teach.")
        return

    last_at = child.get(f"last_action_{action_key}")
    if last_at:
        elapsed_min = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed_min < action["cooldown_min"]:
            remaining = int(action["cooldown_min"] - elapsed_min)
            await message.reply(f"⏳ Действие восстановится через {remaining} мин.")
            return

    if action["price"] > 0:
        if pair["sparks"] < action["price"]:
            await message.reply(f"Не хватает искр: нужно {action['price']}.")
            return
        await db.adjust_rel2_sparks(pair["id"], -action["price"], "child_action")

    stat_key = action["stat_key"]
    stat_delta = action["stat_delta"]
    xp_gain = action["xp"]
    # Секция (модуль 6) усиливает действие, совпадающее с её характеристикой.
    if child["section_key"] and stat_key:
        section = CHILD_SECTIONS.get(child["section_key"])
        if section and section["stat_key"] == stat_key:
            stat_delta = round(stat_delta * (1 + section["bonus"]))
            xp_gain = round(xp_gain * (1 + section["bonus"] / 2))
    # Модуль 8: премиум (+50% к развитию), таланты, врождённые состояния,
    # школа и предметы дополнительно масштабируют результат действия.
    stat_mult, xp_mult = child_growth_multiplier(pair, child, stat_key)
    stat_delta = round(stat_delta * stat_mult)
    xp_gain = round(xp_gain * xp_mult)

    await db.set_rel2_child_action_cooldown(child_id, action_key)
    updated = await db.add_rel2_child_growth(child_id, xp_gain, action["mood"], stat_key, stat_delta, CHILD_MAX_LEVEL)

    extra = f", {stat_key} +{stat_delta}" if stat_key and stat_delta else ""
    await message.reply(
        f"{action['name']}: настроение +{action['mood']}, опыт +{xp_gain}{extra}. "
        f"Уровень: {updated['level_index']}, настроение: {updated['mood']}%."
    )


async def cmd_child_section(message: Message, child_id_str: str, section_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    section_key = section_key.strip().casefold()
    if section_key in ("нет", "выйти", "none"):
        await db.set_rel2_child_section(child_id, None)
        await message.reply("🎓 Ребёнок больше не посещает секцию.")
        return
    section = CHILD_SECTIONS.get(section_key)
    if not section:
        lines = ["Неизвестная секция. Варианты:", DIVIDER]
        for key, info in CHILD_SECTIONS.items():
            lines.append(f"· <code>{key}</code> — {info['name']} ({info['price']} искр, +{int(info['bonus']*100)}% к {info['stat_key']})")
        lines.append("· <code>нет</code> — покинуть текущую секцию")
        await message.reply("\n".join(lines))
        return
    if child["section_key"] == section_key:
        await message.reply("Ребёнок уже посещает эту секцию.")
        return

    price = section["price"]
    if True:
        price = round(price * 0.90)  # 🎟️ купонщик из гайда — премиум чуть дешевле
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "child_section")
    await db.set_rel2_child_section(child_id, section_key)
    await message.reply(f"🎓 Ребёнок записан в секцию <b>{section['name']}</b> за {price} искр!")


# ============================================================================
# 🎓 МОДУЛЬ 6 — СЕКЦИИ ДЛЯ ДЕТЕЙ (расширение модуля 5). Разовая запись в
# секцию (не абонемент — плата один раз при смене) усиливает конкретное
# действие («ребенок действие … teach/care»), чья характеристика совпадает с
# профилем секции (см. применение бонуса в cmd_child_action выше).
# ============================================================================
CHILD_SECTIONS: dict[str, dict] = {
    "sport":   {"name": "🏃 Спортивная секция",  "price": 8_000,  "stat_key": "health",    "bonus": 0.25},
    "science": {"name": "🔬 Кружок науки",       "price": 9_000,  "stat_key": "intellect", "bonus": 0.25},
    "art":     {"name": "🎨 Кружок рисования",    "price": 6_000,  "stat_key": "charisma",  "bonus": 0.20},
    "music":   {"name": "🎵 Музыкальная школа",   "price": 10_000, "stat_key": "charisma",  "bonus": 0.30},
}


# ============================================================================
# 🎉 МОДУЛЬ 7 — СЕМЕЙНЫЕ СОБЫТИЯ (расширение модуля 5). Одна оплата — бонус
# настроения/опыта сразу ВСЕМ детям пары (см. гайд, «Семейные события… дает
# бонусы всем детям»). Кулдаун — общий (rel2_cooldowns, scope="family_event").
# ============================================================================
FAMILY_EVENTS: dict[str, dict] = {
    "birthday":  {"name": "🎂 День рождения",        "price": 5_000,  "mood": 25, "xp": 15, "cooldown_days": 30},
    "vacation":  {"name": "🏖 Семейный отпуск",       "price": 15_000, "mood": 35, "xp": 25, "cooldown_days": 14},
    "gathering": {"name": "👨‍👩‍👧‍👦 Семейный праздник", "price": 8_000,  "mood": 20, "xp": 10, "cooldown_days": 7},
}


async def cmd_child_family_event(message: Message, event_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    event_key = event_key.strip().casefold()
    event = FAMILY_EVENTS.get(event_key)
    if not event:
        lines = ["Семейные события. Варианты:", DIVIDER]
        for key, info in FAMILY_EVENTS.items():
            lines.append(
                f"· <code>{key}</code> — {info['name']} ({info['price']} искр, "
                f"+{info['mood']} настроения/+{info['xp']} опыта всем детям, откат {info['cooldown_days']} дн.)"
            )
        await message.reply("\n".join(lines))
        return

    children = await db.list_rel2_children(pair["id"])
    if not children:
        await message.reply("У вас пока нет детей — событию некого радовать 🙂")
        return

    last_at = await db.get_rel2_cooldown("family_event", pair["id"], event_key)
    if last_at:
        elapsed_days = (datetime.utcnow() - last_at).total_seconds() / 86400
        if elapsed_days < event["cooldown_days"]:
            remaining = event["cooldown_days"] - elapsed_days
            await message.reply(f"⏳ Это событие можно провести ещё раз через {remaining:.1f} дн.")
            return

    price = event["price"]
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -price, "family_event")
    await db.set_rel2_cooldown("family_event", pair["id"], event_key)
    for child in children:
        await db.add_rel2_child_growth(child["id"], event["xp"], event["mood"], None, 0, CHILD_MAX_LEVEL)

    await message.reply(
        f"{event['name']}: все дети ({len(children)}) получили +{event['mood']} настроения "
        f"и +{event['xp']} опыта! Потрачено {price} искр."
    )


# ============================================================================
# 👶 МОДУЛЬ 8 — ПОЛНАЯ «СИСТЕМА ДЕТЕЙ»: возраст/стадии, таланты, врождённые
# состояния, школа, предметы, карьера/соревнования/поездки/достижения
# (премиум), и «СТАРЕНИЕ, БОЛЕЗНИ И СМЕРТЬ ДЕТЕЙ».
#
# ⚠️ ДОПУЩЕНИЯ (гайд не даёт точных цифр — фиксируем разумные значения, как и
# в остальных модулях этого файла):
#   • Возрастные пороги стадий Младенец/Малыш/Дошкольник/Школьник/Подросток —
#     в гайде указан только диапазон "Подросток — до 18 лет" и вехи взрослых
#     стадий (30/55/70/90+). Ранние пороги (0/1/3/6/13) — наша интерполяция.
#   • Формулы шанса заболеть в тик, стоимости/шанса лечения, наград карьеры/
#     соревнований/поездок и бонусов школ/талантов/предметов — гайд описывает
#     их только качественно ("дороже/чаще/быстрее"), поэтому конкретные %
#     подобраны по аналогии с уже реализованными формулами дома/питомцев.
#   • Команда «.рб преобразование» упомянута в гайде только как название в
#     списке команд без единого слова описания механики — сделана как
#     явная заглушка ("скоро"), чтобы не придумывать функциональность с нуля.
# ============================================================================

REAL_DAYS_PER_GAME_YEAR = 5.0  # 5 реальных дней = 1 игровой год (см. гайд)

# --- Возраст и стадии -------------------------------------------------------

_LIFE_STAGES: list[tuple[float, str]] = [
    (0.0, "👶 Младенец"),
    (1.0, "🧒 Малыш"),
    (3.0, "👦 Дошкольник"),
    (6.0, "👨‍🎓 Школьник"),
    (13.0, "🧑 Подросток"),
    (18.0, "🧑 Молодой"),
    (30.0, "🧑‍🦰 Зрелый"),
    (55.0, "🧓 Пожилой"),
    (70.0, "👴 Старик"),
    (90.0, "🌟 Долгожитель"),
]

ELDERLY_ONSET_AGE = 45.0  # "с пожилого возраста (~45-50 лет) появляются старческие болезни"
MAX_CONCURRENT_DISEASES = 6
ACUTE_DEADLINE_HOURS = 48  # острые болезни смертельны, если не вылечить в срок


def child_age_years(born_at: datetime, premium: bool = False) -> float:
    """5 реальных дней = 1 игровой год. Премиум замедляет старение (продлевает
    жизнь), поэтому у премиум-пар возраст растёт медленнее (см. гайд,
    «Премиум продлевает жизнь… старение медленнее»)."""
    elapsed_days = (datetime.utcnow() - born_at).total_seconds() / 86400
    if premium:
        elapsed_days *= 0.7  # -30% к скорости старения
    return elapsed_days / REAL_DAYS_PER_GAME_YEAR


def child_life_stage(age_years: float) -> str:
    stage = _LIFE_STAGES[0][1]
    for threshold, name in _LIFE_STAGES:
        if age_years >= threshold:
            stage = name
        else:
            break
    return stage


def child_disease_onset_chance(age_years: float, premium: bool) -> float:
    """Вероятность подхватить новую болезнь за один часовой тик."""
    if age_years < ELDERLY_ONSET_AGE:
        return 0.0
    excess = min(age_years - ELDERLY_ONSET_AGE, 45.0)  # насыщение к 90 годам
    chance = 0.002 + (excess / 45.0) * 0.02  # 0.2% → 2.2% в час
    if premium:
        chance *= 0.5  # премиум: болезни реже
    return chance


# --- Каталог болезней (30 штук, 3 типа по 10) -------------------------------

DISEASE_CATALOG: dict[str, dict] = {
    # 💊 Излечимые — лечатся полностью при удачном лечении
    "cataract":       {"name": "💊 Катаракта",   "type": "curable", "drain": 1, "cost": 1500, "chance": 0.55},
    "anemia":         {"name": "💊 Анемия",      "type": "curable", "drain": 1, "cost": 1200, "chance": 0.60},
    "pneumonia":      {"name": "💊 Пневмония",   "type": "curable", "drain": 3, "cost": 2500, "chance": 0.50},
    "bronchitis":     {"name": "💊 Бронхит",     "type": "curable", "drain": 2, "cost": 1800, "chance": 0.55},
    "gastritis":      {"name": "💊 Гастрит",     "type": "curable", "drain": 1, "cost": 1300, "chance": 0.60},
    "angina":         {"name": "💊 Ангина",      "type": "curable", "drain": 2, "cost": 1400, "chance": 0.60},
    "flu":            {"name": "💊 Тяжёлый грипп","type": "curable", "drain": 2, "cost": 1600, "chance": 0.55},
    "dermatitis":     {"name": "💊 Дерматит",    "type": "curable", "drain": 1, "cost": 1000, "chance": 0.65},
    "conjunctivitis": {"name": "💊 Конъюнктивит","type": "curable", "drain": 1, "cost": 900,  "chance": 0.65},
    "cystitis":       {"name": "💊 Цистит",      "type": "curable", "drain": 1, "cost": 1100, "chance": 0.60},
    # ♾️ Хронические — не лечатся полностью, можно только «вести» (подавить)
    "arthritis":      {"name": "♾️ Артрит",       "type": "chronic", "drain": 2, "cost": 1500, "chance": 0.50},
    "diabetes":       {"name": "♾️ Диабет",       "type": "chronic", "drain": 2, "cost": 2000, "chance": 0.45},
    "alzheimer":      {"name": "♾️ Альцгеймер",   "type": "chronic", "drain": 3, "cost": 3000, "chance": 0.35},
    "hypertension":   {"name": "♾️ Гипертония",   "type": "chronic", "drain": 2, "cost": 1600, "chance": 0.50},
    "asthma":         {"name": "♾️ Астма",        "type": "chronic", "drain": 2, "cost": 1500, "chance": 0.50},
    "gout":           {"name": "♾️ Подагра",      "type": "chronic", "drain": 1, "cost": 1200, "chance": 0.55},
    "osteoporosis":   {"name": "♾️ Остеопороз",   "type": "chronic", "drain": 2, "cost": 1700, "chance": 0.45},
    "glaucoma":       {"name": "♾️ Глаукома",     "type": "chronic", "drain": 1, "cost": 1400, "chance": 0.50},
    "psoriasis":      {"name": "♾️ Псориаз",      "type": "chronic", "drain": 1, "cost": 1100, "chance": 0.55},
    "copd":           {"name": "♾️ ХОБЛ",         "type": "chronic", "drain": 3, "cost": 2200, "chance": 0.40},
    # 🚑 Острые — смертельны, если не вылечить в срок (48 реальных часов)
    "heart_attack":   {"name": "🚑 Инфаркт",      "type": "acute", "drain": 8, "cost": 6000, "chance": 0.45},
    "stroke":         {"name": "🚑 Инсульт",      "type": "acute", "drain": 8, "cost": 6500, "chance": 0.40},
    "cancer":         {"name": "🚑 Онкология",    "type": "acute", "drain": 6, "cost": 9000, "chance": 0.30},
    "thrombosis":     {"name": "🚑 Тромбоз",      "type": "acute", "drain": 7, "cost": 5500, "chance": 0.45},
    "aneurysm":       {"name": "🚑 Аневризма",    "type": "acute", "drain": 7, "cost": 7000, "chance": 0.35},
    "sepsis":         {"name": "🚑 Сепсис",       "type": "acute", "drain": 8, "cost": 6000, "chance": 0.40},
    "peritonitis":    {"name": "🚑 Перитонит",    "type": "acute", "drain": 7, "cost": 5800, "chance": 0.40},
    "pulmonary_edema":{"name": "🚑 Отёк лёгких",  "type": "acute", "drain": 8, "cost": 6200, "chance": 0.40},
    "kidney_failure": {"name": "🚑 Острая почечная недостаточность", "type": "acute", "drain": 6, "cost": 5500, "chance": 0.45},
    "meningitis":     {"name": "🚑 Менингит",     "type": "acute", "drain": 8, "cost": 7000, "chance": 0.35},
}

TREAT_COOLDOWN_MINUTES = 20


def disease_treat_cost(disease_key: str, premium: bool) -> int:
    info = DISEASE_CATALOG[disease_key]
    cost = info["cost"]
    if premium:
        cost = round(cost * 0.75)  # скидка на лечение
    return cost


def disease_cure_chance(disease_key: str, premium: bool) -> float:
    info = DISEASE_CATALOG[disease_key]
    chance = info["chance"]
    if premium:
        chance = min(0.95, chance + 0.20)  # выше шанс излечения
    return chance


# --- Таланты (врождённые, 1 / премиум до 3) ---------------------------------

CHILD_TALENTS: dict[str, dict] = {
    "sporty":    {"name": "🏃 Спортивный",   "stat_key": "health",    "growth_bonus": 0.20},
    "genius":    {"name": "🧠 Одарённый",     "stat_key": "intellect", "growth_bonus": 0.20},
    "charmer":   {"name": "✨ Обаятельный",   "stat_key": "charisma",  "growth_bonus": 0.20},
    "resilient": {"name": "💪 Крепкий",       "stat_key": None,        "vitality_drain_resist": 0.30},
    "prodigy":   {"name": "🎓 Вундеркинд",    "stat_key": None,        "xp_bonus": 0.15},
    "lucky":     {"name": "🍀 Везунчик",      "stat_key": None,        "xp_bonus": 0.08, "chance_bonus_xp": 0.05},
}

# --- Врождённые состояния (дебафф на рост характеристик) --------------------

CONGENITAL_CONDITIONS: dict[str, dict] = {
    "weak_lungs": {"name": "🫁 Слабые лёгкие",       "stat_key": "health",    "growth_penalty": 0.15},
    "dyslexia":   {"name": "📖 Дислексия",           "stat_key": "intellect", "growth_penalty": 0.15},
    "shyness":    {"name": "🙈 Застенчивость",       "stat_key": "charisma",  "growth_penalty": 0.15},
    "fragile":    {"name": "🩹 Хрупкое здоровье",     "stat_key": None,        "max_vitality_penalty": 20},
}
CONGENITAL_CHANCE = 0.12  # шанс получить врождённое состояние при рождении

# --- Школы -------------------------------------------------------------------

CHILD_SCHOOLS: dict[str, dict] = {
    "public":  {"name": "🏫 Обычная школа",     "price": 0,      "growth_bonus": 0.0,  "premium_only": False},
    "private": {"name": "🎒 Частная школа",     "price": 20_000, "growth_bonus": 0.15, "premium_only": False},
    "elite":   {"name": "🏛️ Элитная академия", "price": 50_000, "growth_bonus": 0.30, "premium_only": True},
}

# --- Предметы (пассивные бонусы к росту характеристик) -----------------------

CHILD_ITEMS: dict[str, dict] = {
    "amulet_health": {"name": "🧿 Амулет здоровья",  "price": 8_000, "stat_key": "health",    "growth_bonus": 0.05},
    "book_wisdom":   {"name": "📕 Книга мудрости",   "price": 8_000, "stat_key": "intellect", "growth_bonus": 0.05},
    "bracelet_charm":{"name": "💫 Браслет обаяния",  "price": 8_000, "stat_key": "charisma",  "growth_bonus": 0.05},
}

# --- Карьеры (премиум, доступны с 14 лет) -----------------------------------

CHILD_CAREER_MIN_AGE = 14
CHILD_CAREERS: dict[str, dict] = {
    "artist":     {"name": "🎨 Художник",  "weekly_income": 400},
    "athlete":    {"name": "🏅 Спортсмен", "weekly_income": 500},
    "scientist":  {"name": "🔬 Учёный",    "weekly_income": 600},
    "musician":   {"name": "🎵 Музыкант",  "weekly_income": 450},
}

# --- Соревнования / поездки (премиум) ---------------------------------------

COMPETITION_PRICE = 3_000
COMPETITION_COOLDOWN_DAYS = 3
COMPETITION_WIN_CHANCE = 0.55

TRIP_PRICE = 10_000
TRIP_COOLDOWN_DAYS = 7


def child_talent_keys(child: dict) -> list[str]:
    import json as _json
    raw = child.get("talents_json")
    if raw is None:
        return child.get("talents", []) or []
    try:
        return _json.loads(raw) or []
    except (TypeError, ValueError):
        return []


def child_item_keys(child: dict) -> list[str]:
    import json as _json
    raw = child.get("item_keys_json")
    if raw is None:
        return child.get("item_keys", []) or []
    try:
        return _json.loads(raw) or []
    except (TypeError, ValueError):
        return []


def child_growth_multiplier(pair: dict, child: dict, stat_key: Optional[str]) -> tuple[float, float]:
    """Возвращает (множитель для stat_delta, множитель для xp) с учётом премиума
    пары (+50% к развитию детей), таланта, врождённого состояния, школы и
    предметов ребёнка."""
    stat_mult = 1.0
    xp_mult = 1.0
    if pair.get("premium"):
        stat_mult *= 1.5
        xp_mult *= 1.5  # "Развитие детей в 1.5 раза быстрее"

    for key in child_talent_keys(child):
        talent = CHILD_TALENTS.get(key)
        if not talent:
            continue
        if stat_key and talent.get("stat_key") == stat_key:
            stat_mult *= (1 + talent["growth_bonus"])
        if talent.get("xp_bonus"):
            xp_mult *= (1 + talent["xp_bonus"])

    congenital_key = child.get("congenital_key")
    if congenital_key and congenital_key in CONGENITAL_CONDITIONS:
        cond = CONGENITAL_CONDITIONS[congenital_key]
        if stat_key and cond.get("stat_key") == stat_key:
            stat_mult *= (1 - cond["growth_penalty"])

    school_key = child.get("school_key")
    if school_key and school_key in CHILD_SCHOOLS:
        stat_mult *= (1 + CHILD_SCHOOLS[school_key]["growth_bonus"])

    for key in child_item_keys(child):
        item = CHILD_ITEMS.get(key)
        if item and stat_key and item["stat_key"] == stat_key:
            stat_mult *= (1 + item["growth_bonus"])

    return stat_mult, xp_mult


def child_max_vitality(child: dict) -> int:
    congenital_key = child.get("congenital_key")
    if congenital_key and congenital_key in CONGENITAL_CONDITIONS:
        penalty = CONGENITAL_CONDITIONS[congenital_key].get("max_vitality_penalty", 0)
        return 100 - penalty
    return 100


def roll_child_talents(premium: bool) -> list[str]:
    count = 3 if premium else 1
    keys = list(CHILD_TALENTS.keys())
    random.shuffle(keys)
    return keys[:count]


def roll_child_congenital() -> Optional[str]:
    if random.random() < CONGENITAL_CHANCE:
        return random.choice(list(CONGENITAL_CONDITIONS.keys()))
    return None


def _child_extended_lines(child: dict, pair_premium: bool) -> list[str]:
    """Строки карточки ребёнка для раздела возраста/здоровья/талантов —
    добавляются к _child_card_lines()."""
    age = child_age_years(child["born_at"], pair_premium)
    stage = child_life_stage(age)
    lines = [f"🎂 Возраст: {age:.1f} игр. лет — {stage}"]

    max_vit = child_max_vitality(child)
    lines.append(f"❤️‍🩹 Жизненные силы: {child.get('vitality', 100)}/{max_vit}")

    talents = child_talent_keys(child)
    if talents:
        names = ", ".join(CHILD_TALENTS[k]["name"] for k in talents if k in CHILD_TALENTS)
        lines.append(f"🌟 Таланты: {names}")

    congenital_key = child.get("congenital_key")
    if congenital_key and congenital_key in CONGENITAL_CONDITIONS:
        lines.append(f"🩺 Врождённое состояние: {CONGENITAL_CONDITIONS[congenital_key]['name']}")

    school_key = child.get("school_key")
    if school_key and school_key in CHILD_SCHOOLS:
        lines.append(f"🏫 Образование: {CHILD_SCHOOLS[school_key]['name']}")

    career_key = child.get("career_key")
    if career_key and career_key in CHILD_CAREERS:
        lines.append(f"💼 Карьера: {CHILD_CAREERS[career_key]['name']}")

    items = child_item_keys(child)
    if items:
        names = ", ".join(CHILD_ITEMS[k]["name"] for k in items if k in CHILD_ITEMS)
        lines.append(f"🎒 Предметы: {names}")

    return lines


async def _child_diseases_lines(child_id: int) -> list[str]:
    diseases = await db.list_child_diseases(child_id)
    if not diseases:
        return ["✅ Болезней нет."]
    lines = [f"🩺 Активные болезни ({len(diseases)}/{MAX_CONCURRENT_DISEASES}):"]
    for d in diseases:
        info = DISEASE_CATALOG.get(d["disease_key"])
        if not info:
            continue
        lines.append(f"  · {info['name']} (ID болезни: {d['id']})")
    return lines


async def cmd_child_treat(message: Message, child_id_str: str, disease_query: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    diseases = await db.list_child_diseases(child_id)
    if not diseases:
        await message.reply("✅ У ребёнка сейчас нет болезней.")
        return

    if not disease_query:
        lines = [f"🩺 Болезни ребёнка «{html.escape(child['name'])}»:", DIVIDER]
        for d in diseases:
            info = DISEASE_CATALOG.get(d["disease_key"])
            if not info:
                continue
            cost = disease_treat_cost(d["disease_key"], True)
            chance = disease_cure_chance(d["disease_key"], True)
            kind = {"curable": "излечима", "chronic": "хроническая, можно подавить симптомы", "acute": "🚨 ОСТРАЯ — лечите срочно!"}[info["type"]]
            lines.append(
                f"· <code>{d['disease_key']}</code> — {info['name']} ({kind})\n"
                f"  Лечение: {cost} искр, шанс успеха {int(chance*100)}%"
            )
        lines.append(DIVIDER)
        lines.append("Чтобы лечить: <b>рб лечить &lt;id ребёнка&gt; &lt;ключ болезни&gt;</b>")
        await message.reply("\n".join(lines))
        return

    disease_row = next((d for d in diseases if d["disease_key"] == disease_query.strip().casefold()), None)
    if not disease_row:
        await message.reply("У ребёнка нет такой болезни. Посмотрите список: <b>рб лечить &lt;id&gt;</b>.")
        return

    last_at = child.get("last_treat_at")
    if last_at:
        elapsed_min = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed_min < TREAT_COOLDOWN_MINUTES:
            remaining = int(TREAT_COOLDOWN_MINUTES - elapsed_min)
            await message.reply(f"⏳ Лечение можно повторить через {remaining} мин.")
            return

    disease_key = disease_row["disease_key"]
    info = DISEASE_CATALOG[disease_key]
    cost = disease_treat_cost(disease_key, True)
    if pair["sparks"] < cost:
        await message.reply(f"Не хватает искр: нужно {cost}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -cost, "child_treatment")
    await db.set_rel2_child_treat_cooldown(child_id)
    chance = disease_cure_chance(disease_key, True)
    success = random.random() < chance

    if success:
        if info["type"] == "chronic":
            await db.mark_child_disease_managed(disease_row["id"])
            await message.reply(
                f"💊 Симптомы «{info['name']}» удалось подавить (хроническую болезнь нельзя вылечить полностью, "
                f"но состояние ребёнка временно улучшено)."
            )
        else:
            await db.remove_child_disease(disease_row["id"])
            await message.reply(f"✅ «{info['name']}» полностью вылечена! Потрачено {cost} искр.")
    else:
        await message.reply(f"❌ Лечение не помогло в этот раз. Потрачено {cost} искр. Попробуйте снова позже.")


async def cmd_child_hall_of_fame(message: Message, scope: str) -> None:
    global_scope = scope.strip().casefold() in ("глобально", "global", "все")
    chat_id = None if global_scope else message.chat.id

    hof = await db.list_hall_of_fame(chat_id, limit=10)
    living = await db.list_living_oldest(chat_id, limit=10)

    scope_label = "🌍 глобально" if global_scope else "в этом чате"
    lines = [f"🏆 <b>Долгожители ({scope_label})</b>", DIVIDER, "🥇 Зал славы (рекорды по возрасту на момент смерти):"]
    if hof:
        for i, row in enumerate(hof, 1):
            lines.append(f"{i}. {html.escape(row['name'])} — {float(row['age_years']):.1f} лет ({row['cause']})")
    else:
        lines.append("· пока пусто")

    lines.append(DIVIDER)
    lines.append("👴 Ныне живущие старейшие:")
    if living:
        for i, row in enumerate(living, 1):
            age = child_age_years(row["born_at"])
            lines.append(f"{i}. {html.escape(row['name'])} — {age:.1f} лет")
    else:
        lines.append("· пока пусто")

    lines.append(DIVIDER)
    lines.append("Подсказка: <b>рб долгожители глобально</b> — общий рейтинг по всем чатам.")
    await message.reply("\n".join(lines))


async def cmd_child_school(message: Message, child_id_str: str, school_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    school_key = school_key.strip().casefold()
    school = CHILD_SCHOOLS.get(school_key)
    if not school:
        lines = ["Доступные школы:", DIVIDER]
        for key, info in CHILD_SCHOOLS.items():
            lines.append(f"· <code>{key}</code> — {info['name']}, {info['price']} искр, +{int(info['growth_bonus']*100)}% к росту")
        await message.reply("\n".join(lines))
        return
    if child.get("school_key") == school_key:
        await message.reply("Ребёнок уже учится в этой школе.")
        return

    price = school["price"]
    if True:
        price = round(price * 0.85)
    if pair["sparks"] < price:
        await message.reply(f"Не хватает искр: нужно {price}.")
        return
    if price:
        await db.adjust_rel2_sparks(pair["id"], -price, "child_school")
    await db.set_rel2_child_school(child_id, school_key)
    await message.reply(f"🏫 Ребёнок теперь учится в «{school['name']}»!")


async def cmd_child_career(message: Message, child_id_str: str, career_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    age = child_age_years(child["born_at"], True)
    if age < CHILD_CAREER_MIN_AGE:
        await message.reply(f"Карьера доступна с {CHILD_CAREER_MIN_AGE} игровых лет (сейчас: {age:.1f}).")
        return

    career_key = career_key.strip().casefold()
    career = CHILD_CAREERS.get(career_key)
    if not career:
        lines = ["Доступные карьеры:", DIVIDER]
        for key, info in CHILD_CAREERS.items():
            lines.append(f"· <code>{key}</code> — {info['name']} (+{info['weekly_income']} искр/нед)")
        await message.reply("\n".join(lines))
        return

    await db.set_rel2_child_career(child_id, career_key)
    await message.reply(f"💼 Ребёнок начинает карьеру: «{career['name']}» (+{career['weekly_income']} искр/нед в казну пары).")


async def cmd_child_competition(message: Message, child_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    last_at = child.get("last_competition_at")
    if last_at:
        elapsed_days = (datetime.utcnow() - last_at).total_seconds() / 86400
        if elapsed_days < COMPETITION_COOLDOWN_DAYS:
            remaining = COMPETITION_COOLDOWN_DAYS - elapsed_days
            await message.reply(f"⏳ Следующее соревнование можно провести через {remaining:.1f} дн.")
            return
    if pair["sparks"] < COMPETITION_PRICE:
        await message.reply(f"Не хватает искр: нужно {COMPETITION_PRICE}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -COMPETITION_PRICE, "child_competition")
    await db.set_rel2_child_competition_cooldown(child_id)
    won = random.random() < COMPETITION_WIN_CHANCE
    if won:
        reward = round(COMPETITION_PRICE * 2.5)
        await db.adjust_rel2_sparks(pair["id"], reward, "child_competition_prize")
        await db.add_rel2_child_growth(child_id, 60, 20, "charisma", 3, CHILD_MAX_LEVEL)
        await message.reply(f"🏆 Победа на престижном соревновании! Награда: {reward} искр, +опыт, +харизма.")
    else:
        await message.reply("😔 В этот раз не получилось выиграть, но опыт участия бесценен.")


async def cmd_child_trip(message: Message, child_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    last_at = child.get("last_trip_at")
    if last_at:
        elapsed_days = (datetime.utcnow() - last_at).total_seconds() / 86400
        if elapsed_days < TRIP_COOLDOWN_DAYS:
            remaining = TRIP_COOLDOWN_DAYS - elapsed_days
            await message.reply(f"⏳ Следующая поездка доступна через {remaining:.1f} дн.")
            return
    if pair["sparks"] < TRIP_PRICE:
        await message.reply(f"Не хватает искр: нужно {TRIP_PRICE}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -TRIP_PRICE, "child_trip")
    await db.set_rel2_child_trip_cooldown(child_id)
    await db.add_rel2_child_growth(child_id, 100, 30, "intellect", 4, CHILD_MAX_LEVEL)
    await message.reply("✈️ Незабываемая поездка позади: +настроение, +опыт, +интеллект!")


async def cmd_child_item(message: Message, child_id_str: str, item_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    item_key = item_key.strip().casefold()
    item = CHILD_ITEMS.get(item_key)
    if not item:
        lines = ["Доступные предметы:", DIVIDER]
        for key, info in CHILD_ITEMS.items():
            lines.append(f"· <code>{key}</code> — {info['name']} ({info['price']} искр, +{int(info['growth_bonus']*100)}% к {info['stat_key']})")
        await message.reply("\n".join(lines))
        return
    if item_key in child_item_keys(child):
        await message.reply("У ребёнка уже есть этот предмет.")
        return
    if pair["sparks"] < item["price"]:
        await message.reply(f"Не хватает искр: нужно {item['price']}.")
        return

    await db.adjust_rel2_sparks(pair["id"], -item["price"], "child_item")
    await db.add_rel2_child_item(child_id, item_key)
    await message.reply(f"🎒 Ребёнок получает предмет «{item['name']}»!")


async def cmd_child_achievements(message: Message, child_id_str: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    try:
        child_id = int(child_id_str)
    except ValueError:
        await message.reply("Нужен числовой ID ребёнка.")
        return
    child = await _find_pair_child(pair["id"], child_id)
    if not child:
        await message.reply("Ребёнок не найден.")
        return

    age = child_age_years(child["born_at"], True)
    achievements = []
    if child["level_index"] >= 10:
        achievements.append("⭐ Уровень 10+")
    if child["level_index"] >= CHILD_MAX_LEVEL:
        achievements.append("🏅 Максимальный уровень")
    if age >= 18:
        achievements.append("🎓 Совершеннолетие")
    if age >= 70:
        achievements.append("👴 Достиг старости")
    if child.get("career_key"):
        achievements.append("💼 Начал карьеру")
    if child_item_keys(child):
        achievements.append("🎒 Обладатель предметов")
    if not achievements:
        achievements.append("Пока нет достижений — развивайте ребёнка!")

    lines = [f"🏆 <b>Достижения: {html.escape(child['name'])}</b>", DIVIDER]
    lines.extend(f"· {a}" for a in achievements)
    await message.reply("\n".join(lines))


async def cmd_child_report(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    children = await db.list_rel2_children(pair["id"])
    if not children:
        await message.reply("У вас пока нет детей.")
        return
    lines = [f"📋 <b>Отчёт о развитии детей ({len(children)})</b>", DIVIDER]
    for child in children:
        age = child_age_years(child["born_at"], True)
        stage = child_life_stage(age)
        disease_count = await db.count_child_diseases(child["id"])
        health_flag = "🩺" if disease_count else "✅"
        lines.append(
            f"👶 <b>{html.escape(child['name'])}</b> (ID {child['id']}) — {stage}, {age:.1f} лет\n"
            f"   ⭐ Ур. {child['level_index']}/{CHILD_MAX_LEVEL} · ❤️ {child['health']} · 🧠 {child['intellect']} · "
            f"✨ {child['charisma']} · ❤️‍🩹 {child.get('vitality', 100)} {health_flag}"
        )
    await message.reply("\n".join(lines))


async def cmd_child_transformation_stub(message: Message) -> None:
    # ⚠️ См. докстринг модуля 8: гайд упоминает «.рб преобразование» только в
    # списке команд без описания механики — сознательная заглушка.
    await message.reply("🔧 «Преобразование» скоро появится — следите за обновлениями гайда.")


async def child_aging_loop(bot, interval_seconds: int = 3600) -> None:
    """Раз в час: катит новые болезни пожилым детям, тикает жизненные силы от
    активных болезней, проверяет дедлайн острых болезней и обрабатывает смерть
    (см. гайд, «Старение, болезни и смерть детей»). Плюс — еженедельная
    выплата за карьеру ребёнка (премиум)."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            rows = await db.list_rel2_children_for_aging_tick()
            for row in rows:
                child = db.rel2_child_row(row)
                premium = bool(row["pair_premium"])
                chat_id = row["chat_id"]
                pair_id = row["pair_id2"]
                age = child_age_years(child["born_at"], premium)

                # Карьера: выплата раз в 7 дней
                career_key = child.get("career_key")
                if career_key and career_key in CHILD_CAREERS:
                    last_payout = child.get("last_career_payout_at")
                    due = last_payout is None or (datetime.utcnow() - last_payout).total_seconds() >= 7 * 86400
                    if due:
                        income = CHILD_CAREERS[career_key]["weekly_income"]
                        await db.adjust_rel2_sparks(pair_id, income, "child_career_income", floor_at_zero=False)
                        await db.set_rel2_child_career_payout(child["id"])

                if age < ELDERLY_ONSET_AGE:
                    continue  # болезни начинаются только с пожилого возраста

                diseases = await db.list_child_diseases(child["id"])

                # Новая болезнь
                if len(diseases) < MAX_CONCURRENT_DISEASES:
                    onset_chance = child_disease_onset_chance(age, premium)
                    if random.random() < onset_chance:
                        existing_keys = {d["disease_key"] for d in diseases}
                        candidates = [k for k in DISEASE_CATALOG if k not in existing_keys]
                        if candidates:
                            new_key = random.choice(candidates)
                            await db.add_child_disease(child["id"], new_key)
                            diseases.append({"disease_key": new_key, "acquired_at": datetime.utcnow(), "id": None, "managed_at": None})
                            try:
                                await bot.send_message(
                                    chat_id,
                                    f"🩺 У {child['name']} обнаружена болезнь: {DISEASE_CATALOG[new_key]['name']}. "
                                    f"Используйте <b>рб лечить {child['id']}</b>.",
                                )
                            except Exception:
                                pass

                # Урон от болезней + дедлайн острых
                resilient = "resilient" in child_talent_keys(child)
                total_drain = 0
                died_of: Optional[str] = None
                for d in diseases:
                    info = DISEASE_CATALOG.get(d["disease_key"])
                    if not info:
                        continue
                    drain = info["drain"]
                    if info["type"] == "chronic" and d.get("managed_at"):
                        managed_recently = (datetime.utcnow() - d["managed_at"]).total_seconds() < 48 * 3600
                        if managed_recently:
                            drain = max(0, drain // 2)
                    if resilient:
                        drain = round(drain * (1 - CHILD_TALENTS["resilient"]["vitality_drain_resist"]))
                    total_drain += drain

                    if info["type"] == "acute" and d.get("id") is not None:
                        age_of_disease_hours = (datetime.utcnow() - d["acquired_at"]).total_seconds() / 3600
                        if age_of_disease_hours > ACUTE_DEADLINE_HOURS:
                            died_of = info["name"]

                new_vitality = await db.adjust_rel2_child_vitality(child["id"], -total_drain) if total_drain else child.get("vitality", 100)

                if died_of is None and new_vitality <= 0:
                    died_of = "истощение жизненных сил"

                if died_of:
                    final_age = child_age_years(child["born_at"], premium)
                    await db.add_hall_of_fame_entry(chat_id, pair_id, child["name"], final_age, died_of)
                    await db.release_rel2_child(child["id"], pair_id)
                    try:
                        await bot.send_message(
                            chat_id,
                            f"💔 {child['name']} скончал(ся/ась) в возрасте {final_age:.1f} лет ({died_of}). "
                            f"Имя останется в Зале славы — <b>рб долгожители</b>.",
                        )
                    except Exception:
                        pass
        except Exception:
            logger.exception("Ошибка в child_aging_loop")
        await asyncio.sleep(interval_seconds)


async def pregnancy_announce_loop(bot, interval_seconds: int = 1800) -> None:
    """Раз в 30 минут: проверяет активные беременности и один раз шлёт в чат
    сообщение о каждой новой пройденной вехе (см. PREGNANCY_MILESTONES) —
    без спама, last_milestone_week пишется в БД, чтобы не повторяться."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            rows = await db.list_active_rel2_pregnancies_for_tick()
            for row in rows:
                premium = bool(row["pair_premium"])
                week = pregnancy_week(row["started_at"], premium)
                if week <= row["last_milestone_week"]:
                    continue
                reached = [w for w, _ in PREGNANCY_MILESTONES if row["last_milestone_week"] < w <= week]
                if not reached:
                    await db.set_rel2_pregnancy_milestone(row["id"], week)
                    continue
                text = pregnancy_milestone_text(week)
                try:
                    await bot.send_message(
                        row["chat_id"],
                        f"🤰 Беременность, неделя {week}/{PREGNANCY_TOTAL_WEEKS}: {text}",
                    )
                except Exception:
                    pass
                await db.set_rel2_pregnancy_milestone(row["id"], week)
        except Exception:
            logger.exception("Ошибка в pregnancy_announce_loop")
        await asyncio.sleep(interval_seconds)


# ============================================================================
# 💑 НАЧИНАНИЕ ОТНОШЕНИЙ — хелперы поиска цели/показа имени
# ============================================================================

async def _display_name_by_id(chat_id: int, user_id: int, bot) -> str:
    """Локальный аналог display_name_by_id() из bot.py — модуль намеренно не
    импортирует bot.py (см. докстринг файла), поэтому у него своя маленькая
    копия: ник из БД (если задан в этом чате) либо имя из Telegram."""
    nickname = await db.get_nickname(chat_id, user_id)
    if nickname:
        name = html.escape(nickname)
        return f'<a href="tg://user?id={user_id}">{name}</a>'
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        name = html.escape(member.user.full_name or str(user_id))
        username = member.user.username
    except Exception:
        return f'<a href="tg://user?id={user_id}">{user_id}</a>'
    if username:
        return f'<a href="https://telegram.me/{username}">{name}</a>'
    return f'<a href="tg://user?id={user_id}">{name}</a>'


async def _plain_name_by_id(chat_id: int, user_id: int, bot) -> str:
    """Имя без HTML-ссылки — для вставки внутрь <pre>/<code>, где Telegram
    ссылки и разметку не рендерит (там нужен чистый текст)."""
    nickname = await db.get_nickname(chat_id, user_id)
    if nickname:
        return nickname
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.user.full_name or str(user_id)
    except Exception:
        return str(user_id)


async def _display_name(chat_id: int, user, bot) -> str:
    nickname = await db.get_nickname(chat_id, user.id)
    raw = nickname or getattr(user, "full_name", None) or "Без имени"
    name = html.escape(raw)
    username = getattr(user, "username", None)
    if username:
        return f'<a href="https://telegram.me/{username}">{name}</a>'
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def resolve_rel2_target(message: Message):
    """Цель команды: ответ на сообщение или кликабельная ссылка-упоминание в
    самом тексте (text_mention/@username). Возвращает Telegram User-подобный
    объект (id/full_name/username/is_bot) либо None."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user:
            return entity.user
        if entity.type == "mention":
            username = message.text[entity.offset : entity.offset + entity.length].lstrip("@")
            try:
                chat = await message.bot.get_chat(username)
            except Exception:
                continue
            if chat.type != "private":
                continue
            return SimpleNamespace(
                id=chat.id,
                full_name=chat.full_name or chat.first_name or username,
                username=chat.username,
                is_bot=False,
            )
    return None


# ============================================================================
# Команды: «отн запрос», «+отн», «-отн», «отн я», «отн список», «отн бонус»,
# «отн история». Используем отдельные слова первого токена, чтобы не
# конфликтовать по тексту со старым модулем — при переключении на rel2 как
# основной модуль эти проверки можно упростить до простого «отн», как раньше
# (см. докстринг файла, раздел «ИНТЕГРАЦИЯ»).
# ============================================================================

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().split()[0].casefold() in ("ребенок", "ребёнок", "рб")),
)
async def cmd_child_word(message: Message) -> None:
    parts = message.text.strip().split()
    sub = parts[1].casefold() if len(parts) > 1 else ""
    a1 = parts[2] if len(parts) > 2 else ""
    a2 = " ".join(parts[3:]) if len(parts) > 3 else ""

    if sub in ("", "список"):
        await cmd_child_list(message)
    elif sub == "профиль" and a1:
        await cmd_child_profile(message, a1)
    elif sub == "имя" and a1 and a2:
        await cmd_child_rename(message, a1, a2)
    elif sub == "действие" and a1 and a2:
        await cmd_child_action(message, a1, a2.split()[0])
    elif sub == "секция" and a1:
        await cmd_child_section(message, a1, a2.split()[0] if a2 else "нет")
    elif sub == "мсекции":
        lines = ["Доступные секции:", DIVIDER]
        for key, info in CHILD_SECTIONS.items():
            lines.append(f"· <code>{key}</code> — {info['name']} ({info['price']} искр, +{int(info['bonus']*100)}% к {info['stat_key']})")
        await message.reply("\n".join(lines))
    elif sub == "осекцию" and a1:
        await cmd_child_section(message, a1, "нет")
    elif sub == "школа" and a1:
        await cmd_child_school(message, a1, a2.split()[0] if a2 else "")
    elif sub == "лечить" and a1:
        await cmd_child_treat(message, a1, a2.split()[0] if a2 else "")
    elif sub == "долгожители":
        await cmd_child_hall_of_fame(message, a1 or "")
    elif sub in ("отказаться", "отпустить") and a1:
        await cmd_child_release(message, a1)
    elif sub == "событие":
        await cmd_child_family_event(message, a1)
    elif sub == "отчет":
        await cmd_child_report(message)
    elif sub == "карьера" and a1:
        await cmd_child_career(message, a1, a2.split()[0] if a2 else "")
    elif sub == "соревнование" and a1:
        await cmd_child_competition(message, a1)
    elif sub == "поездка" and a1:
        await cmd_child_trip(message, a1)
    elif sub == "достижение" and a1:
        await cmd_child_achievements(message, a1)
    elif sub == "предмет" and a1:
        await cmd_child_item(message, a1, a2.split()[0] if a2 else "")
    elif sub == "преобразование":
        await cmd_child_transformation_stub(message)
    else:
        await message.reply(
            "Доступно (короткий алиас — <b>.рб</b>): <b>рб список</b>, <b>рб профиль &lt;id&gt;</b>, "
            "<b>рб имя &lt;id&gt; &lt;имя&gt;</b>, "
            "<b>рб действие &lt;id&gt; play/care/teach</b>, "
            "<b>рб секция &lt;id&gt; &lt;ключ&gt;</b> (или <b>нет</b>, чтобы выйти), "
            "<b>рб школа &lt;id&gt; &lt;тип&gt;</b>, <b>рб лечить &lt;id&gt; [ключ болезни]</b>, "
            "<b>рб долгожители</b> [глобально], <b>рб событие</b> [ключ], <b>рб отчет</b>, "
            "<b>рб отказаться &lt;id&gt;</b>.\n"
            "Ещё: <b>рб карьера &lt;id&gt; &lt;ключ&gt;</b>, <b>рб предмет &lt;id&gt; &lt;ключ&gt;</b>, "
            "<b>рб соревнование &lt;id&gt;</b>, <b>рб поездка &lt;id&gt;</b>, <b>рб достижение &lt;id&gt;</b>.\n"
            "Чтобы завести ребёнка: <b>отн родить</b> [имя] ответом на сообщение человека."
        )


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: _first_word_is(t, "отн")),
)
async def cmd_rel2_word(message: Message):
    parts = _strip_dot_prefix(message.text).split(maxsplit=1)
    sub = parts[1].strip().casefold() if len(parts) > 1 else ""

    if sub == "я" or sub.startswith("я "):
        # Хвост после «я» (например «отн я Ник») игнорируем — карточка всегда о
        # своей паре («Твоя половинка»).
        await cmd_rel2_me(message)
        return
    if sub in ("вернуть", "верни"):
        await message.reply(await _restore_rel2(message.chat.id, message.from_user.id, message.bot))
        return
    if sub in ("список",):
        await cmd_rel2_list(message)
        return
    if sub in ("бонус",):
        await cmd_rel2_bonus(message)
        return
    if sub in ("история",):
        await cmd_rel2_history(message)
        return
    if sub in ("действия", "действие"):
        await cmd_rel2_actions_catalog(message)
        return
    if sub == "сделать" or sub.startswith("сделать "):
        query = parts[1][len("сделать"):].strip() if len(parts) > 1 else ""
        if not query:
            await message.reply(
                "Укажите действие: <b>отн сделать &lt;название или номер&gt;</b>. "
                "Полный список — <b>отн действия</b>."
            )
            return
        await cmd_rel2_do_action(message, query)
        return
    if sub in SIMPLE_RP_ALIAS_MAP:
        await cmd_rel2_simple_action(message, SIMPLE_RP_ALIAS_MAP[sub])
        return
    # «отн особые» — новое, нейтральное имя. «отн премиум» оставлено рабочим,
    # чтобы у тех, кто привык к старой команде, ничего не сломалось.
    if sub in ("особые", "премиум") or sub.startswith("особые ") or sub.startswith("премиум "):
        keyword = "особые" if sub.startswith("особые") else "премиум"
        query = parts[1][len(keyword):].strip() if len(parts) > 1 else ""
        if not query:
            await cmd_rel2_premium_catalog(message)
        else:
            await cmd_rel2_premium_action(message, query)
        return
    if sub == "презик":
        await cmd_rel2_toggle_contraception(message)
        return
    if sub in ("секс", "кекс","пошалить"):
        await cmd_rel2_conceive(message)
        return
    if sub in ("беременность", "беременна", "берем"):
        await cmd_rel2_pregnancy_status(message)
        return
    if sub == "пт" or sub.startswith("пт "):
        rest = parts[1][2:].strip() if len(parts) > 1 else ""
        await dispatch_pet_command(message, rest)
        return
    if sub == "родить" or sub.startswith("родить "):
        name_hint = parts[1][len("родить"):].strip() if len(parts) > 1 else ""
        await cmd_child_propose(message, name_hint)
        return
    if sub in ("запрос", "расторгнуть", ""):
        # «отн запрос @user», «отн запрос» ответом, либо голое «отн» ответом —
        # все ведут в один обработчик предложения/разрыва (см. ниже).
        await _handle_rel2_propose_or_break(message)
        return

    await message.reply(
        "Доступно: <b>отн запрос</b> [@user/ответом], <b>отн расторгнуть</b>, "
        "<b>отн я</b>, <b>отн список</b>, <b>отн бонус</b>, <b>отн история</b>, "
        "<b>отн действия</b> — список РП-действий по уровням, "
        "<b>отн сделать &lt;название/номер&gt;</b> — выполнить действие (например "
        "<b>отн сделать комплимент</b>), "
        "<b>отн обнять</b> / <b>отн поцеловать</b> (или <b>тьмок</b>/<b>чмок</b>) / "
        "<b>отн кусь</b> / <b>отн шлёп</b> (или <b>шлеп</b>/<b>отшлепать</b>) / "
        "<b>отн уебать</b> — простые жесты для пары, без уровня, "
        "<b>отн премиум</b> [название] — премиум-действия для премиум-пар, "
        "<b>отн презик</b> — включить/выключить защиту от беременности (по умолчанию включена), "
        "<b>отн кекс</b> (или <b>отн секс</b>) — попытка, зависит от защиты, "
        "<b>отн беременность</b> — прогресс текущей беременности (40 недель), "
        "<b>отн родить</b> [имя] ответом на сообщение — предложить стать ребёнком "
        "(дальше — команды <b>ребенок …</b>, см. <b>ребенок помощь</b>).\n"
        "Перед «отн» можно ставить точку — <b>.отн</b> работает так же, как <b>отн</b>."
    )


async def _handle_rel2_propose_or_break(message: Message) -> None:
    actor = message.from_user
    target = await resolve_rel2_target(message)

    if target is None:
        await message.reply(
            "💞 Чтобы предложить отношения, ответьте на сообщение человека командой "
            "<b>отн запрос</b> или отправьте её с кликабельной ссылкой на него."
        )
        return
    if target.id == actor.id:
        await message.reply("Нельзя предложить отношения самому себе 🙂")
        return
    if target.is_bot:
        await message.reply("Боты пока не встречаются 🤖")
        return

    existing_actor = await db.get_rel2_pair(message.chat.id, actor.id)
    if existing_actor and existing_actor["partner_id"] == target.id:
        # Команда ответом на текущего партнёра = разрыв.
        await _do_rel2_break(message, existing_actor)
        return
    if existing_actor:
        partner_name = await _display_name_by_id(message.chat.id, existing_actor["partner_id"], message.bot)
        await message.reply(f"Вы уже состоите в отношениях с {partner_name} 💞")
        return

    existing_target = await db.get_rel2_pair(message.chat.id, target.id)
    if existing_target:
        target_name = await _display_name(message.chat.id, target, message.bot)
        await message.reply(f"{target_name} уже состоит в отношениях с кем-то другим 💔")
        return

    await db.create_rel2_request(message.chat.id, actor.id, target.id)
    actor_name = await _display_name(message.chat.id, actor, message.bot)
    target_name = await _display_name(message.chat.id, target, message.bot)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💞 Принять", callback_data=f"rel2_accept:{actor.id}:{target.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rel2_decline:{actor.id}:{target.id}"),
        ]]
    )
    await message.reply(
        f"💌 {actor_name} предлагает {target_name} начать отношения!\n"
        f"{target_name}, решать вам — примите кнопкой ниже или командой <b>+отн</b> ответом.",
        reply_markup=keyboard,
    )


async def _create_rel2_pair_and_announce(message_or_callback, chat_id: int, proposer_id: int, target_id: int) -> bool:
    """Общая часть принятия заявки (из кнопки и из команды «+отн»). Возвращает
    True, если пара создана и уведомление отправлено."""
    bot = message_or_callback.bot
    if await db.get_rel2_pair(chat_id, proposer_id) or await db.get_rel2_pair(chat_id, target_id):
        await db.delete_rel2_request(chat_id, proposer_id, target_id)
        return False

    pair_id = await db.create_rel2_pair(chat_id, proposer_id, target_id)
    if pair_id is None:
        return False

    await db.clear_rel2_requests_for(chat_id, proposer_id)
    await db.clear_rel2_requests_for(chat_id, target_id)

    proposer_name = await _display_name_by_id(chat_id, proposer_id, bot)
    target_name = await _display_name_by_id(chat_id, target_id, bot)
    text = (
        f"💞 {proposer_name} и {target_name} теперь в отношениях!\n"
        f"🔥 Стартовый баланс: 0 искр. Не забывайте про <b>отн бонус</b> каждые 12 часов — "
        f"без искр отношения не проживут."
    )
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        pass

    await db.add_log("relationship2_created", chat_id=chat_id, actor_id=proposer_id, target_id=target_id)
    return True


@router.callback_query(F.data.startswith("rel2_accept:"))
async def rel2_accept_button(callback: CallbackQuery):
    _, proposer_id, target_id = callback.data.split(":")
    proposer_id, target_id = int(proposer_id), int(target_id)
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    request = await db.get_latest_rel2_request(chat_id, target_id)
    if not request or request["from_user_id"] != proposer_id:
        await callback.answer("Заявка больше не активна.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        return

    created = await _create_rel2_pair_and_announce(callback, chat_id, proposer_id, target_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer("Отношения начаты! 💞" if created else "Не получилось — кто-то уже занят.", show_alert=not created)


@router.callback_query(F.data.startswith("rel2_decline:"))
async def rel2_decline_button(callback: CallbackQuery):
    _, proposer_id, target_id = callback.data.split(":")
    proposer_id, target_id = int(proposer_id), int(target_id)
    chat_id = callback.message.chat.id

    if callback.from_user.id != target_id:
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    await db.delete_rel2_request(chat_id, proposer_id, target_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await db.add_log("relationship2_declined", chat_id=chat_id, actor_id=proposer_id, target_id=target_id)
    await callback.answer("Предложение отклонено.")
    try:
        target_name = await _display_name_by_id(chat_id, target_id, callback.bot)
        await callback.message.answer(f"💔 {target_name} отклонил(а) предложение отношений.")
    except Exception:
        pass


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().casefold() == "+отн"),
)
async def cmd_rel2_accept_word(message: Message):
    actor = message.from_user
    request = await db.get_latest_rel2_request(message.chat.id, actor.id)
    if not request:
        await message.reply("У вас нет активных предложений отношений.")
        return
    proposer_id = request["from_user_id"]
    created = await _create_rel2_pair_and_announce(message, message.chat.id, proposer_id, actor.id)
    if not created:
        await message.reply("Не получилось принять — кто-то из вас уже в отношениях.")


async def _do_rel2_break(message: Message, pair: dict) -> None:
    # Подтверждение перед расторжением (можно случайно ответить партнёру «отн»).
    partner_name = await _display_name_by_id(message.chat.id, pair["partner_id"], message.bot)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💔 Да, расторгнуть", callback_data=f"rel2_break_yes:{message.from_user.id}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"rel2_break_no:{message.from_user.id}"),
    ]])
    await message.reply(
        f"💔 Точно расторгнуть отношения с {partner_name}? Вернуть можно в течение 72 часов.",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("rel2_break_no:"))
async def cb_rel2_break_no(callback: CallbackQuery):
    try:
        initiator = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    if callback.from_user.id != initiator:
        await callback.answer("Это не ваши отношения 🙂", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text("Расторжение отменено 🙂")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("rel2_break_yes:"))
async def cb_rel2_break_yes(callback: CallbackQuery):
    try:
        initiator = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    if callback.from_user.id != initiator:
        await callback.answer("Это не ваши отношения 🙂", show_alert=True)
        return
    chat_id = callback.message.chat.id
    pair = await db.get_rel2_pair(chat_id, initiator)
    if not pair:
        await callback.answer("Отношения уже расторгнуты.", show_alert=True)
        try:
            await callback.message.edit_text("💔 Отношения уже расторгнуты.")
        except TelegramBadRequest:
            pass
        return
    partner_id = pair["partner_id"]
    raw = await db.get_rel2_pair_row(chat_id, initiator)
    if raw:  # снимок для отмены 72 ч (искры/уровень/дети сохранятся)
        await db.snapshot_dissolution("rel2", chat_id, initiator, partner_id, json.dumps(raw, default=str))
    await db.delete_rel2_pair(chat_id, initiator)
    await db.add_log("relationship2_broken", chat_id=chat_id, actor_id=initiator, target_id=partner_id)
    a = await _display_name_by_id(chat_id, initiator, callback.bot)
    b = await _display_name_by_id(chat_id, partner_id, callback.bot)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Вернуть отношения", callback_data=f"rel2_undo:{initiator}"),
    ]])
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"💔 {a} разрывает отношения с {b}.\nПередумали? Вернуть можно 72 часа — командой «отн вернуть» или кнопкой.",
            reply_markup=kb,
        )
    except TelegramBadRequest:
        pass


async def _restore_rel2(chat_id: int, user_id: int, bot) -> str:
    undo = await db.get_recent_dissolution("rel2", chat_id, user_id)
    if not undo:
        return "↩️ Нечего возвращать — либо вы не расторгали, либо прошло больше 72 часов."
    if not await db.restore_rel2_pair_row(json.loads(undo["payload"])):
        return "Кто-то из вас уже в новых отношениях 💔"
    await db.consume_dissolution(undo["id"])
    a = await _display_name_by_id(chat_id, undo["user_a"], bot)
    b = await _display_name_by_id(chat_id, undo["user_b"], bot)
    return f"💞 {a} и {b} восстановили отношения!"


@router.callback_query(F.data.startswith("rel2_undo:"))
async def cb_rel2_undo(callback: CallbackQuery):
    try:
        initiator = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    if callback.from_user.id != initiator:
        await callback.answer("Это не ваши отношения 🙂", show_alert=True)
        return
    text = await _restore_rel2(callback.message.chat.id, initiator, callback.bot)
    await callback.answer()
    try:
        await callback.message.edit_text(text)
    except TelegramBadRequest:
        pass


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text.func(lambda t: bool(t) and t.strip().casefold() == "-отн"),
)
async def cmd_rel2_break_word(message: Message):
    pair = await db.get_rel2_pair(message.chat.id, message.from_user.id)
    if not pair:
        await message.reply("Вы ни с кем не в отношениях.")
        return
    await _do_rel2_break(message, pair)


async def cmd_rel2_me(message: Message) -> None:
    """«отн я» — профиль своей пары (искры/уровень/расход/премиум)."""
    subject = message.from_user
    pair = await db.get_rel2_pair(message.chat.id, subject.id)
    if not pair:
        await message.reply(
            "Вы пока ни с кем не в отношениях. Команда <b>отн запрос</b> ответом на "
            "сообщение человека — сделать предложение."
        )
        return

    partner_name = await _display_name_by_id(message.chat.id, pair["partner_id"], message.bot)
    level = pair["level_index"]
    sparks = pair["sparks"]
    nxt = next_level_info(sparks)
    denom = sparks + nxt[2] if nxt else sparks
    daily_cost = effective_daily_cost(level, pair["children_count"], True)
    protection = "вкл" if pair["contraception"] else "выкл"
    duration = _pair_duration_text(pair["started_at"])

    counts = await db.get_rel2_action_counts(pair["id"])

    # Сыновья/дочери — по анкетному полу «детей» (это реальные участники чата,
    # ставшие ребёнком через «отн родить»). Если пол не указан — ребёнок не
    # попадёт ни в сыновья, ни в дочери: другого признака пола у нас нет.
    sons = daughters = 0
    for child in await db.list_rel2_children(pair["id"]):
        gender = await _gender_by_id(message.chat.id, child["child_user_id"])
        if gender == "м":
            sons += 1
        elif gender == "ж":
            daughters += 1

    header = [
        f"❤️ • Твоя половинка: {partner_name}",
        f"🆔 ID: <code>{pair['partner_id']}</code>",
        f"💠 • Уровень: {level_name(level)} ({level})",
        f"🔥 • Искра: {_fmt_thousands(sparks)}/{_fmt_thousands(denom)}",
        f"📈 • Текущее потребление искр (24ч): {daily_cost}",
        f"🕙 • Длительность: {duration}",
        f"🛡 • Презик: {protection}",
    ]
    # Счётчики действий — инлайн-моношрифтом (<code> = одинарный `), как просили.
    # Минеты/куни — шуточные счётчики (жесты «отн минет»/«отн куни»), без фото
    # и без графики: акт не описывается, растёт просто циферка.
    counters = (
        f"🤗 • Обнимашек: {counts.get('hug', 0)}\n"
        f"😘 • Поцелуев: {counts.get('kiss', 0)}\n"
        f"🧛 • Укусов: {counts.get('bite', 0)}\n"
        f"🤚 • Шлёпов: {counts.get('spank', 0)}\n"
        f"💋 • Минетов: {counts.get('minet', 0)}\n"
        f"👅 • Куни: {counts.get('kuni', 0)}\n"
        f"🔞 • Кексов: {counts.get('kex', 0)}\n"
        f"👊 • Удары: {counts.get('smack', 0)}"
    )
    children_lines = [
        f"👶 • Сыновья: {sons}",
        f"👩 • Дочери: {daughters}",
    ]
    text = "\n".join(header) + f"\n<code>{counters}</code>\n" + "\n".join(children_lines)

    keyboard = None
    if _bonus_available(pair):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔋 Забрать бонус искр", callback_data="rel2_bonus")]]
        )
    else:
        wait = _bonus_wait_text(pair)
        if wait:
            text += f"\n\n🔋 Бонус будет доступен через {wait}."

    await message.reply(text, reply_markup=keyboard)


RELATIONSHIPS2_PAGE_SIZE = 10


async def rel2_list_page(chat_id: int, page: int, bot) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    page = max(page, 0)
    rows, total = await db.list_rel2_pairs(
        chat_id, limit=RELATIONSHIPS2_PAGE_SIZE, offset=page * RELATIONSHIPS2_PAGE_SIZE
    )
    if not rows and page:
        page = 0
        rows, total = await db.list_rel2_pairs(chat_id, limit=RELATIONSHIPS2_PAGE_SIZE)
    if not rows:
        return (
            "💞 <b>Топ пар чата</b>\n\nПока нет ни одной пары.\n"
            "Команда <b>отн запрос</b> ответом на сообщение человека — стать первой!",
            None,
        )

    lines = []
    for index, row in enumerate(rows, start=page * RELATIONSHIPS2_PAGE_SIZE + 1):
        first = await _display_name_by_id(chat_id, row["user1_id"], bot)
        second = await _display_name_by_id(chat_id, row["user2_id"], bot)
        lines.append(
            f"{index}. {first} 💞 {second} · 🔥{row['sparks']} · Ур. {row['level_index']}"
        )

    pages = (total + RELATIONSHIPS2_PAGE_SIZE - 1) // RELATIONSHIPS2_PAGE_SIZE
    text = f"💞 <b>Топ пар чата — {total}</b>\n\n" + "\n".join(lines)
    if pages == 1:
        return text, None

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"rel2_list_page:{page - 1}"))
    buttons.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"rel2_list_page:{page + 1}"))
    return text, InlineKeyboardMarkup(inline_keyboard=[buttons])


async def cmd_rel2_list(message: Message) -> None:
    text, keyboard = await rel2_list_page(message.chat.id, 0, message.bot)
    await message.reply(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("rel2_list_page:"))
async def paginate_rel2_list(callback: CallbackQuery):
    try:
        page = int((callback.data or "").split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        await callback.answer("Не удалось открыть эту страницу.", show_alert=True)
        return
    text, keyboard = await rel2_list_page(callback.message.chat.id, page, callback.bot)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()


# ============================================================================
# 🔋 Ежедневный бонус искр (раз в 12 часов)
# ============================================================================

BONUS_COOLDOWN_HOURS = 12


def _bonus_available(pair: dict) -> bool:
    last = pair.get("last_bonus_at")
    if last is None:
        return True
    return (datetime.utcnow() - last).total_seconds() >= BONUS_COOLDOWN_HOURS * 3600


def _bonus_wait_text(pair: dict) -> Optional[str]:
    last = pair.get("last_bonus_at")
    if last is None:
        return None
    remaining = BONUS_COOLDOWN_HOURS * 3600 - (datetime.utcnow() - last).total_seconds()
    if remaining <= 0:
        return None
    hours, rem = divmod(int(remaining), 3600)
    minutes = rem // 60
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


async def _grant_rel2_bonus(chat_id: int, user_id: int, bot) -> str:
    pair = await db.get_rel2_pair(chat_id, user_id)
    if not pair:
        return "Вы пока ни с кем не в отношениях."
    if not _bonus_available(pair):
        wait = _bonus_wait_text(pair) or "скоро"
        return f"🔋 Бонус уже забирали. Следующий будет доступен через {wait}."

    amount = daily_bonus_amount(pair["level_index"], True)
    new_balance = await db.adjust_rel2_sparks(pair["id"], amount, "bonus")
    await db.set_rel2_last_bonus_at(pair["id"])
    if new_balance is not None:
        new_level = level_from_sparks(new_balance)
        if new_level != pair["level_index"]:
            await db.set_rel2_level(pair["id"], new_level)
    return f"🔋 Получено <b>+{amount}</b> искр! Баланс: <b>{new_balance}</b>."


async def cmd_rel2_bonus(message: Message) -> None:
    text = await _grant_rel2_bonus(message.chat.id, message.from_user.id, message.bot)
    await message.reply(text)


@router.callback_query(F.data == "rel2_bonus")
async def rel2_bonus_button(callback: CallbackQuery):
    text = await _grant_rel2_bonus(callback.message.chat.id, callback.from_user.id, callback.bot)
    await callback.answer(text.replace("<b>", "").replace("</b>", ""), show_alert=True)


# ============================================================================
# 📊 История операций с искрами («отн история»)
# ============================================================================

async def cmd_rel2_history(message: Message) -> None:
    pair = await db.get_rel2_pair(message.chat.id, message.from_user.id)
    if not pair:
        await message.reply("Вы пока ни с кем не в отношениях.")
        return
    entries = await db.list_rel2_spark_log(pair["id"], limit=15)
    if not entries:
        await message.reply("📊 История операций с искрами пока пуста.")
        return

    lines = ["📊 <b>История искр — последние операции</b>", DIVIDER]
    for entry in entries:
        sign = "+" if entry["delta"] >= 0 else ""
        when = entry["created_at"].strftime("%d.%m %H:%M")
        lines.append(
            f"{when} · {spark_log_label(entry['reason'])} · {sign}{entry['delta']} "
            f"(баланс: {entry['balance_after']})"
        )
    await message.reply("\n".join(lines))


# ============================================================================
# 💞 МОДУЛЬ 11 — РП-ДЕЙСТВИЯ («отн сделать …», «отн действия»). Первая часть
# TODO «РП-действия и премиум-действия между партнёрами» из шапки файла: 30
# действий из гайда, каждое открывается на своём уровне пары (действие №N —
# на уровне N, 1:1, т.к. в гайде ровно 30 действий и ровно 30 уровней) и
# имеет собственный откат — используем уже существующую generic-таблицу
# кулдаунов (db.rel2_cooldowns, scope="rp_action", ref_id=pair_id), отдельная
# таблица не нужна.
# РЕШЕНО: семантика значков статуса. Гайд не разделяет «✅/🔐/🔒» по смыслу —
# здесь это сделано явно: ✅ открыто и готово сейчас, ⏳ открыто, но на откате,
# 🔒 ещё не открыто (не хватает уровня). Премиум даёт +25% к награде и -30%
# к времени отката — так же, как у остальных РП-действий в доме/с питомцами,
# чтобы бонус премиума был единообразным по всему боту.
# ============================================================================

RP_ACTIONS: list[dict] = [
    {
        "level": 1, "key": "compliment", "name": "Сделать комплимент",
        "verb": "сделал(а) комплимент",
        "phrases": [
            "Ты удивительно талантлив(а).",
            "Рядом с тобой я чувствую себя счастливее.",
            "Твоя улыбка — лучшее, что случалось со мной сегодня.",
            "Ты потрясающий(ая) человек, и мне повезло быть с тобой.",
        ],
        "reward": 15, "cooldown_minutes": 5,
    },
    {
        "level": 2, "key": "breakfast", "name": "Сделать завтрак",
        "verb": "приготовил(а) завтрак",
        "phrases": ["Свежие тосты и любимый кофе — специально для тебя."],
        "reward": 35, "cooldown_minutes": 8,
    },
    {
        "level": 3, "key": "flowers", "name": "Подарить цветы",
        "verb": "подарил(а) цветы",
        "phrases": [],  # без цитаты — просто действие
        "reward": 60, "cooldown_minutes": 11,
    },{
    "level": 4, "key": "movie", "name": "Посмотреть фильм",
    "verb": "посмотрел(а) фильм вместе",
    "phrases": [
        "Любой фильм становится лучше, если смотреть его рядом с тобой.",
        "Сегодня главный сюжет — это мы.",
        "Я бы пересматривал(а) этот вечер бесконечно.",
    ],
    "reward": 80, "cooldown_minutes": 15,
},
{
    "level": 5, "key": "massage", "name": "Сделать массаж",
    "verb": "сделал(а) массаж",
    "phrases": [
        "Пусть усталость уйдёт, а останется только спокойствие.",
        "Хочу, чтобы ты чувствовал(а) себя лучше благодаря мне.",
        "Ты заслуживаешь заботы каждый день.",
    ],
    "reward": 120, "cooldown_minutes": 20,
},
{
    "level": 6, "key": "dinner", "name": "Романтический ужин",
    "verb": "устроил(а) романтический ужин",
    "phrases": [
        "Самое вкусное сегодня — время, проведённое вместе.",
        "Каждый ужин с тобой становится маленьким праздником.",
        "Ты — мой любимый повод улыбаться.",
    ],
    "reward": 170, "cooldown_minutes": 30,
},
{
    "level": 7, "key": "gift", "name": "Сделать подарок",
    "verb": "сделал(а) подарок",
    "phrases": [
        "Этот подарок — лишь маленькая часть моей заботы о тебе.",
        "Твоя радость для меня бесценна.",
        "Мне нравится делать тебя счастливее.",
    ],
    "reward": 230, "cooldown_minutes": 38,
},
{
    "level": 8, "key": "trip", "name": "Туристическая поездка",
    "verb": "отправился(ась) в путешествие",
    "phrases": [
        "Самые красивые места — те, где мы вместе.",
        "Каждая дорога с тобой становится приключением.",
        "Главный сувенир этой поездки — наши воспоминания.",
    ],
    "reward": 300, "cooldown_minutes": 45,
},
{
    "level": 9, "key": "astronomy", "name": "Вечер астрономии",
    "verb": "провёл(а) вечер под звёздами",
    "phrases": [
        "Даже звёзды сегодня светят чуть ярче.",
        "Когда ты рядом, небо кажется бесконечно красивым.",
        "Самая яркая звезда сейчас — это ты.",
    ],
    "reward": 400, "cooldown_minutes": 60,
},
{
    "level": 10, "key": "memories", "name": "Приятные воспоминания",
    "verb": "вспомнил(а) лучшие моменты",
    "phrases": [
        "Наши воспоминания — сокровище, которое всегда со мной.",
        "Каждый момент с тобой хочется сохранить навсегда.",
        "Прошлое прекрасно, потому что в нём есть ты.",
    ],
    "reward": 500, "cooldown_minutes": 80,
},
{
    "level": 11, "key": "photoshoot", "name": "Совместная фотосессия",
    "verb": "устроил(а) совместную фотосессию",
    "phrases": [
        "На каждой фотографии есть причина улыбнуться.",
        "Самые красивые кадры — это моменты рядом с тобой.",
        "Эти снимки будут согревать нас ещё долгие годы.",
    ],
    "reward": 700, "cooldown_minutes": 90,
},
{
    "level": 12, "key": "tradition", "name": "Создать традицию",
    "verb": "создал(а) новую традицию",
    "phrases": [
        "Пусть эта традиция напоминает, как дороги мы друг другу.",
        "Маленькие привычки создают большое счастье.",
        "Хочу, чтобы у нас всегда были особенные моменты.",
    ],
    "reward": 900, "cooldown_minutes": 100,
},
{
    "level": 13, "key": "project", "name": "Совместный проект",
    "verb": "начал(а) совместный проект",
    "phrases": [
        "Вместе мы способны на гораздо большее.",
        "Любое дело становится легче рядом с тобой.",
        "Мне нравится создавать что-то вместе с тобой.",
    ],
    "reward": 1100, "cooldown_minutes": 110,
},
{
    "level": 14, "key": "genealogy", "name": "Исследовать родословную",
    "verb": "исследовал(а) родословную",
    "phrases": [
        "Интересно узнавать, какой путь привёл нас друг к другу.",
        "История семьи делает настоящее ещё ценнее.",
        "Каждая история начинается с любви.",
    ],
    "reward": 1400, "cooldown_minutes": 120,
},
{
    "level": 15, "key": "future", "name": "Спланировать будущее",
    "verb": "спланировал(а) будущее",
    "phrases": [
        "Мне нравится мечтать о завтрашнем дне вместе с тобой.",
        "Будущее кажется светлее, когда ты рядом.",
        "Пусть впереди нас ждёт ещё много счастливых дней.",
    ],
    "reward": 1700, "cooldown_minutes": 130,
},
{
    "level": 16, "key": "wish", "name": "Исполнить желание",
    "verb": "исполнил(а) желание",
    "phrases": [
        "Твоя улыбка стоит любых усилий.",
        "Мне приятно делать тебя счастливым(ой).",
        "Пусть мечты становятся реальностью.",
    ],
    "reward": 2100, "cooldown_minutes": 140,
},
{
    "level": 17, "key": "anniversary", "name": "Годовщина отношений",
    "verb": "отметил(а) годовщину",
    "phrases": [
        "Каждый год рядом с тобой — настоящий подарок.",
        "Спасибо за все моменты, которые мы разделили.",
        "Это только начало нашей истории.",
    ],
    "reward": 2500, "cooldown_minutes": 150,
},
{
    "level": 18, "key": "home", "name": "Обустроить жилище",
    "verb": "сделал(а) дом уютнее",
    "phrases": [
        "Дом становится настоящим, когда в нём есть ты.",
        "Самый уютный уголок мира — рядом с тобой.",
        "Хочу, чтобы сюда всегда хотелось возвращаться.",
    ],
    "reward": 3000, "cooldown_minutes": 160,
},
{
    "level": 19, "key": "spirit", "name": "Духовное единение",
    "verb": "укрепил(а) духовную связь",
    "phrases": [
        "Иногда слова не нужны, чтобы понять друг друга.",
        "Наше доверие — самая крепкая связь.",
        "Я ценю всё, что объединяет нас.",
    ],
    "reward": 3500, "cooldown_minutes": 170,
},
{
    "level": 20, "key": "retreat", "name": "Уединенный отдых",
    "verb": "устроил(а) уединённый отдых",
    "phrases": [
        "Иногда весь мир может подождать.",
        "Самое ценное место — там, где мы вдвоём.",
        "Покой рядом с тобой бесценен.",
    ],
    "reward": 4000, "cooldown_minutes": 180,
},
{
    "level": 21, "key": "vow", "name": "Написать клятву",
    "verb": "написал(а) клятву",
    "phrases": [
        "Каждое слово написано от всего сердца.",
        "Пусть эти обещания будут крепче времени.",
        "Ты вдохновляешь меня быть лучше.",
    ],
    "reward": 4800, "cooldown_minutes": 200,
},
{
    "level": 22, "key": "talisman", "name": "Создать талисман",
    "verb": "создал(а) талисман",
    "phrases": [
        "Пусть этот талисман хранит наше счастье.",
        "Он будет напоминать о самых тёплых моментах.",
        "Немного магии для нашей истории.",
    ],
    "reward": 5600, "cooldown_minutes": 220,
},
{
    "level": 23, "key": "song", "name": "Написать песню",
    "verb": "написал(а) песню",
    "phrases": [
        "Каждая строчка звучит благодаря тебе.",
        "У нашей любви есть собственная мелодия.",
        "Эта песня навсегда останется особенной.",
    ],
    "reward": 6500, "cooldown_minutes": 240,
},
{
    "level": 24, "key": "garden", "name": "Вырастить сад",
    "verb": "вырастил(а) сад",
    "phrases": [
        "Пусть каждый цветок напоминает о нашей заботе.",
        "Красота растёт там, где есть любовь.",
        "Этот сад будет цвести вместе с нашими чувствами.",
    ],
    "reward": 7500, "cooldown_minutes": 260,
},
{
    "level": 25, "key": "dance", "name": "Танцевальный вечер",
    "verb": "пригласил(а) на танец",
    "phrases": [
        "Пока играет музыка, существует только этот момент.",
        "Самый красивый танец — рядом с тобой.",
        "Неважно, умеем ли мы танцевать. Главное — вместе.",
    ],
    "reward": 8500, "cooldown_minutes": 280,
},
{
    "level": 26, "key": "family_council", "name": "Семейный совет",
    "verb": "провёл(а) семейный совет",
    "phrases": [
        "Любое решение легче принимать вместе.",
        "Мы — одна команда.",
        "Наше единство важнее любых разногласий.",
    ],
    "reward": 10000, "cooldown_minutes": 300,
},
{
    "level": 27, "key": "star", "name": "Назвать звезду",
    "verb": "назвал(а) звезду",
    "phrases": [
        "Теперь даже на небе есть напоминание о тебе.",
        "Некоторые чувства невозможно измерить расстоянием.",
        "Ты сияешь ярче любой звезды.",
    ],
    "reward": 11500, "cooldown_minutes": 320,
},
{
    "level": 28, "key": "book", "name": "Написать книгу",
    "verb": "написал(а) книгу",
    "phrases": [
        "Каждая глава хранит частичку нашей истории.",
        "Эту историю хочется перечитывать снова и снова.",
        "Лучшие страницы ещё впереди.",
    ],
    "reward": 13000, "cooldown_minutes": 340,
},
{
    "level": 29, "key": "celebration", "name": "Организовать праздник",
    "verb": "организовал(а) праздник",
    "phrases": [
        "Сегодня повод улыбаться есть у каждого.",
        "Самый лучший праздник — тот, где мы вместе.",
        "Пусть этот день запомнится надолго.",
    ],
    "reward": 15000, "cooldown_minutes": 360,
},
{
    "level": 30, "key": "eternal_love", "name": "Вечная любовь",
    "verb": "признался(ась) в вечной любви",
    "phrases": [
        "Если бы мне пришлось выбирать снова, я всё равно выбрал(а) бы тебя.",
        "Любовь — это каждый день выбирать друг друга.",
        "Пусть наша история никогда не заканчивается.",
        "Ты — мой самый дорогой человек.",
    ],
    "reward": 18000, "cooldown_minutes": 400,
},
]

RP_ACTION_COOLDOWN_SCOPE = "rp_action"


def rp_action_reward(action: dict, premium: bool) -> int:
    reward = action["reward"]
    if premium:
        reward = round(reward * 1.25)
    return reward


def rp_action_cooldown_minutes(action: dict, premium: bool) -> float:
    minutes = action["cooldown_minutes"]
    if premium:
        minutes *= 0.70
    return minutes


def _format_rp_cooldown(minutes: float) -> str:
    total = round(minutes)
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}ч. {mins}м"
    if hours:
        return f"{hours}ч"
    return f"{mins}м"


def find_rp_action(query: str) -> Optional[dict]:
    """Ищет действие по номеру («отн сделать 1»), ключу или (частичному)
    названию («отн сделать комплимент» найдёт «Сделать комплимент»)."""
    q = query.strip().strip("«»\"'").casefold()
    if not q:
        return None
    if q.isdigit():
        idx = int(q)
        for action in RP_ACTIONS:
            if action["level"] == idx:
                return action
        return None
    for action in RP_ACTIONS:
        if action["key"] == q or action["name"].casefold() == q:
            return action
    candidates = [a for a in RP_ACTIONS if q in a["name"].casefold()]
    if candidates:
        candidates.sort(key=lambda a: len(a["name"]))
        return candidates[0]
    return None


async def cmd_rel2_actions_catalog(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    level = pair["level_index"]

    lines = ["💞 <b>РП-действия — открываются по уровню пары</b>", DIVIDER]
    for action in RP_ACTIONS:
        if level < action["level"]:
            icon = "🔒"
        else:
            last_at = await db.get_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])
            cooldown = rp_action_cooldown_minutes(action, True)
            on_cooldown = bool(
                last_at and (datetime.utcnow() - last_at).total_seconds() < cooldown * 60
            )
            icon = "⏳" if on_cooldown else "✅"
        reward = rp_action_reward(action, True)
        cooldown_text = _format_rp_cooldown(rp_action_cooldown_minutes(action, True))
        lines.append(
            f"[{action['level']}] {icon} • «{action['name']}» | 🔥+{reward}|{cooldown_text}"
        )
    lines.append(DIVIDER)
    lines.append(
        "Выполнить: <b>отн сделать &lt;название или номер&gt;</b>, например "
        "<b>отн сделать комплимент</b> или <b>отн сделать 1</b>."
    )
    await message.reply("\n".join(lines))


async def cmd_rel2_do_action(message: Message, query: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return

    action = find_rp_action(query)
    if action is None:
        await message.reply(
            "Не нашёл такое действие. Список всех действий — <b>отн действия</b>."
        )
        return

    if pair["level_index"] < action["level"]:
        await message.reply(
            f"🔒 Действие «{action['name']}» открывается на уровне {action['level']} "
            f"(сейчас у вас уровень {pair['level_index']})."
        )
        return

    last_at = await db.get_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])
    cooldown = rp_action_cooldown_minutes(action, True)
    if last_at:
        elapsed_minutes = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed_minutes < cooldown:
            remaining = _format_rp_cooldown(cooldown - elapsed_minutes)
            await message.reply(f"⏳ «{action['name']}» ещё восстанавливается: осталось {remaining}.")
            return

    reward = rp_action_reward(action, True)
    new_balance = await db.adjust_rel2_sparks(pair["id"], reward, "rp_action")
    await db.set_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])

    level_up_line = ""
    if new_balance is not None:
        new_level = level_from_sparks(new_balance)
        if new_level != pair["level_index"]:
            await db.set_rel2_level(pair["id"], new_level)
            level_up_line = f"\n🆙 Новый уровень: <b>{new_level} ({level_name(new_level)})</b>!"

    actor_name = await _display_name_by_id(message.chat.id, message.from_user.id, message.bot)
    target_name = await _display_name_by_id(message.chat.id, pair["partner_id"], message.bot)

    verb = action.get("verb") or action["name"].lower()
    phrases = action.get("phrases") or []
    quote_part = f" «{random.choice(phrases)}»" if phrases else ""

    text = (
        f"☺️ • {actor_name} {verb}{quote_part} своей половинке {target_name}\n"
        f"🔥 • Искры +{reward}\n"
        f"🕙 • Следующие действия будут доступны через {_format_rp_cooldown(cooldown)}"
        f"{level_up_line}"
    )
    await message.reply(text)

# ============================================================================
# 💋 МОДУЛЬ 11b — ПРОСТЫЕ РП-ЖЕСТЫ («отн обнять», «отн поцеловать/тьмок/чмок»,
# «отн кусь», «отн шлёп/шлеп/отшлепать», «отн уебать»). В отличие от
# RP_ACTIONS выше — не требуют уровня отношений и не начисляют искры, это
# просто эмоции для пары, направленные автоматически на партнёра (цель не
# нужно указывать — она у пары одна). Небольшой общий откат — чтобы не
# спамить в чат одной и той же фразой.
#
# ⚠️ Из присланного списка НЕ реализованы явно сексуализированные пункты
# («минет», «куни», «секс/кекс/пошалить», «презик») — это генерация
# сексуального контента, адресованного напрямую конкретному человеку в
# группе, без возможности проверить возраст участников чата. Такое я не
# пишу вне зависимости от формулировки запроса. Остальные жесты (объятия,
# поцелуй, шутливый шлепок/«уёб» как дружеская потасовка) — обычные,
# не сексуальные РП-emoji-действия, они реализованы.
# ============================================================================


# У каждого жеста есть «reply» — ответное действие собеседника (партнёра). Его
# бот показывает мини-строкой снизу в моноблоке (см. cmd_rel2_simple_action):
# партнёр отвечает тем же жестом. Плейсхолдеры {actor}/{target} — чистые имена
# (без ссылок): внутри <pre> Telegram ссылки не рендерит.
# РП-жесты «отн» (обнять/поцеловать/…). Раньше были захардкожены здесь; теперь
# живут в БД (rel2_gestures/_phrases/_aliases), чтобы админы правили их из
# панели. Этот словарь — сид и фолбэк: им наполняется БД при первом запуске
# (db.seed_rel2_gestures_if_empty) и он же в кэше, пока БД ещё не загружена.
# media_folder — папка с фото жеста внутри rp_media (см. _pick_rp_media).
_SIMPLE_RP_ACTIONS_DEFAULT: dict[str, dict] = {
    "hug": {
        "name": "Обнять", "media_folder": "hugs", "aliases": ["обнять"],
        "phrases": [
            "🤗 {actor} крепко обнимает {target}.",
            "🤗 {actor} обнимает {target} и не отпускает ещё пару секунд.",
        ],
        "reply": "{target} обнимает {actor} в ответ.",
    },
    "kiss": {
        "name": "Поцеловать", "media_folder": "kisses", "aliases": ["поцеловать", "тьмок", "чмок"],
        "phrases": [
            "😘 {actor} нежно целует {target}.",
            "💋 {actor} чмокает {target} в щёку.",
        ],
        "reply": "{target} целует {actor} в ответ.",
    },
    "bite": {
        "name": "Кусь", "media_folder": "bites", "aliases": ["кусь"],
        "phrases": [
            "😈 {actor} легонько кусает {target} — кусь!",
            "🦷 {actor} игриво кусает {target} за плечо.",
        ],
        "reply": "{target} кусает {actor} в ответ — кусь!",
    },
    "spank": {
        "name": "Шлёп", "media_folder": "spanks", "aliases": ["шлёп", "шлеп", "отшлепать"],
        "phrases": [
            "✋ {actor} шутя шлёпает {target}.",
            "✋ {actor} отвешивает {target} дружеский шлепок.",
        ],
        "reply": "{target} отвечает {actor} тем же — шлёп!",
    },
    "smack": {
        "name": "Уебать", "media_folder": "smacks", "aliases": ["уебать"],
        "phrases": [
            "💥 {actor} от души уёбывает {target} — незабываемые ощущения (в шутку, конечно)!",
            "💥 {actor} несётся и от всей души влетает {target}ой — оба потом смеются.",
        ],
        "reply": "{target} со смехом отвечает {actor} тем же.",
    },
    # Минет/куни — просто шуточные счётчики в карточке пары, БЕЗ фото и без
    # графики: надпись сухая и «зацензуренная», сам акт не описывается. Папок
    # media_folder не существует → фото-реакции не будет. Считаются по ключам
    # minet/kuni (см. карточку «отн я»).
    "minet": {
        "name": "Минет", "media_folder": "minet", "aliases": ["минет"],
        "phrases": [
            "😏 {actor} и {target} уединились на пару минут… счётчик минетов +1. Что было — осталось между ними.",
            "🙈 {actor} отсосала своей половинке  {target}.",
        ],
    },
    "kuni": {
        "name": "Куни", "media_folder": "kuni", "aliases": ["куни"],
        "phrases": [
            "😏 {actor} балует своим язычком {target}… ",
            "🙈 {actor} отлизал своей половинке  {target}",
        ],
    },
}


def default_gestures() -> dict:
    """Дефолтные жесты — для сида БД при старте бота (см. bot.py)."""
    return _SIMPLE_RP_ACTIONS_DEFAULT


def _gesture_cache_from_default() -> dict:
    return {
        key: {
            "name": info["name"],
            "phrases": list(info["phrases"]),
            "reply": info.get("reply"),
            "media_folder": info.get("media_folder", key),
        }
        for key, info in _SIMPLE_RP_ACTIONS_DEFAULT.items()
    }


# Живые кэши: при импорте = дефолт (бот работает даже без БД), при старте и по
# сигналу перечитки — обновляются из БД (load_gestures). Диспетчер «отн» и
# cmd_rel2_simple_action читают именно их.
SIMPLE_RP_ACTIONS: dict[str, dict] = _gesture_cache_from_default()
SIMPLE_RP_ALIAS_MAP: dict[str, str] = {
    alias: key for key, info in _SIMPLE_RP_ACTIONS_DEFAULT.items() for alias in info["aliases"]
}


async def load_gestures() -> None:
    """Перечитывает жесты из БД в кэш. Если в БД пусто (ещё не засеяно) —
    оставляет дефолт. Правки в панели подхватываются здесь по общему сигналу
    перечитки (bot.py вызывает при старте и в цикле перечитки)."""
    rows = await db.list_rel2_gestures(active_only=True)
    if not rows:
        return
    actions: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for g in rows:
        actions[g["gesture_key"]] = {
            "name": g["name"],
            "phrases": [p["phrase"] for p in g["phrases"]],
            "reply": g["reply_template"],
            "media_folder": g["media_folder"],
        }
        for alias in g["aliases"]:
            aliases[alias] = g["gesture_key"]
    SIMPLE_RP_ACTIONS.clear()
    SIMPLE_RP_ACTIONS.update(actions)
    SIMPLE_RP_ALIAS_MAP.clear()
    SIMPLE_RP_ALIAS_MAP.update(aliases)


# --- Картинки-реакции к жестам ---------------------------------------------
# К жесту снизу прикладывается мини-фото (аниме) — в папке жеста (media_folder)
# и по полу пары. Структура: rp_media/<media_folder>/<пара>/<файлы>, где пара —
# mf (парень+девушка), mm (парень+парень), ff (девушка+девушка). Пол — из анкеты
# (db.get_profile_card → gender). Фото кладут админы через панель; пока папка
# пуста — жест выводится текстом.
# Ссылки на картинки-реакции к жестам, по папке жеста (media_folder у gesture)
# и по полу пары: "ff" (обе девушки), "mm" (оба парня), "mf" (смешанная/по
# умолчанию). Ключи верхнего уровня — те же media_folder, что и раньше у
# файловых жестов (hugs, kisses, bites, spanks, smacks, minet, kuni).
PHOTOS: dict[str, dict[str, list[str]]] = {
    "hugs": {
        "ff": ["https://i.pinimg.com/736x/e6/b1/33/e6b13302ba093f6dcabc4de9b54afce0.jpg", "https://i.pinimg.com/736x/40/34/49/403449f08ed9101f81f13f03a7ed7338.jpg"],
        "mf": ["https://i.pinimg.com/736x/a9/2c/28/a92c28b1f7d8d16944bd1e5ded0b8931.jpg","https://i.pinimg.com/originals/03/9d/46/039d46d4805e425d481259c77d183c59.jpg", "https://i.pinimg.com/1200x/4e/69/fc/4e69fc56b54a5a13a740630c5bbfaaf0.jpg"],
        "mm": ["link1", "link2"],
    },
    "kisses": {
        "ff": ["https://i.pinimg.com/736x/1f/84/ac/1f84ac36990c15125fbb3c03fd4ae198.jpg", "https://i.pinimg.com/736x/1d/3b/96/1d3b96d8f087aaed48912cb2d689436d.jpg"],
        "mf": ["https://i.pinimg.com/736x/38/44/98/384498e6dd3a1de16b94de2ed9f0851a.jpg", "https://i.pinimg.com/736x/97/d1/61/97d1613d26aa09f86339a4b33a2e576e.jpg",""],
        "mm": ["link1", "link2"],
    },
    "bites": {
        "ff": ["link1", "link2"],
        "mf": ["link1", "link2"],
        "mm": ["link1", "link2"],
    },
    "spanks": {
        "ff": ["link1", "link2"],
        "mf": ["link1", "link2"],
        "mm": ["link1", "link2"],
    },
    "smacks": {
        "ff": ["link1", "link2"],
        "mf": ["link1", "link2"],
        "mm": ["link1", "link2"],
    },
    "minet": {
        "ff": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
        "mf": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
        "mm": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
    },
    "kuni": {
        "ff": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
        "mf": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
        "mm": ["https://i.pinimg.com/736x/fb/10/1d/fb101d67ea7286c09dbed81dc9cd8eca.jpg"],
    },
}


def _rp_pairing(gender_a: Optional[str], gender_b: Optional[str]) -> str:
    """Ключ пары по двум анкетным полам: mm / ff / mf. Неизвестный пол или
    «другой» → mf (нейтральная папка по умолчанию)."""
    genders = {gender_a, gender_b}
    if genders == {"м"}:
        return "mm"
    if genders == {"ж"}:
        return "ff"
    return "mf"


def _real_photo_urls(urls) -> list:
    """Только настоящие ссылки из legacy-словаря PHOTOS.

    Часть пар в нём не заполнена — стоят заглушки («link1», «link2», пустая
    строка). Отдавать их Telegram нельзя, и — что важнее — непустой список
    заглушек раньше «выигрывал» у пары с настоящими картинками, из-за чего
    у «оба парня» фото не появлялось никогда.
    """
    return [u for u in (urls or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]


def _pick_rp_photo_url(folder, gender_a, gender_b):
    """Ссылка на картинку-реакцию для жеста и пары — или None, если картинок
    нет (тогда жест уходит обычным текстом).

    ПОРЯДОК ИСТОЧНИКОВ ВАЖЕН.
    1. Свои файлы из хранилища (rp_photos.MEDIA_ROOT) — ссылкой на публичный
       эндпоинт панели /rp/…. Это основной путь: картинки лежат у нас, их
       видно и можно менять через панель, и ссылка не протухнет оттого, что
       чужой сайт удалил файл.
    2. Только если своих файлов для жеста нет — старый словарь PHOTOS со
       ссылками на сторонние хостинги. Оставлен, чтобы жесты, которым ещё не
       залили картинки, не осиротели разом; по мере загрузки файлов надобность
       в нём отпадёт.

    В обоих случаях сначала пробуем точную пару по полу, потом остальные.
    """
    if not folder:
        return None

    own = rp_photos.pick_photo_url(folder, _rp_pairing(gender_a, gender_b))
    if own:
        return own

    bucket = PHOTOS.get(folder)
    if not bucket:
        return None
    order, seen = [], set()
    for pairing in (_rp_pairing(gender_a, gender_b), "mf", "mm", "ff"):
        if pairing not in seen:
            seen.add(pairing)
            order.append(pairing)
    for pairing in order:
        urls = _real_photo_urls(bucket.get(pairing))
        if urls:
            return random.choice(urls)
    return None


async def _gender_by_id(chat_id: int, user_id: int) -> Optional[str]:
    card = await db.get_profile_card(chat_id, user_id)
    return card.get("gender") if card else None


async def cmd_rel2_simple_action(message: Message, action_key: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    info = SIMPLE_RP_ACTIONS.get(action_key)
    if info is None:
        return  # жест удалили/выключили между показом и вызовом



    actor_name = await _display_name_by_id(message.chat.id, message.from_user.id, message.bot)
    target_name = await _display_name_by_id(message.chat.id, pair["partner_id"], message.bot)
    phrases = info.get("phrases") or []
    if phrases:
        phrase = random.choice(phrases).format(actor=actor_name, target=target_name)
    else:
        # у жеста нет фраз (админ не добавил) — не падаем, показываем нейтрально
        phrase = f"{html.escape(info['name'])}: {actor_name} → {target_name}"

    await db.increment_rel2_action_count(pair["id"], action_key)  # счётчик для «отн я»

    # Фраза действия + фото (аниме) из rp_media для этого жеста и пола пары —
    # ОДНИМ сообщением: фото с фразой в подписи (caption), а не двумя разными
    # сообщениями (текст, а потом фото отдельным реплаем на него — из-за этого
    # в Telegram получалась громоздкая карточка с задвоенной цитатой и
    # огромным фото). Если фото для жеста ещё не залито (папки пусты) —
    # уходит обычное текстовое сообщение. Чтобы фото появилось, залейте его
    # через панель («Действия» → отн-жесты → «Фото по полу пары») — файлы
    # лягут в rp_photos.MEDIA_ROOT, а в чат уйдёт ссылка на наш публичный
    # эндпоинт /rp/…, по которой Telegram и нарисует превью.
    gender_actor = await _gender_by_id(message.chat.id, message.from_user.id)
    gender_partner = await _gender_by_id(message.chat.id, pair["partner_id"])
    photo_url = _pick_rp_photo_url(info.get("media_folder"), gender_actor, gender_partner)

    if photo_url:
        try:
            await message.reply(
                phrase,
                link_preview_options=LinkPreviewOptions(
                    url=photo_url,
                    is_disabled=False,
                    # МАЛЕНЬКОЕ превью, а не во всю ширину: жест — это в
                    # первую очередь фраза, картинка к ней приложение.
                    # Большое фото раздувало сообщение на пол-экрана и
                    # выталкивало из виду сам текст действия.
                    prefer_small_media=True,
                    show_above_text=False,
                ),
            )
            return
        except TelegramBadRequest:
            pass  # битая ссылка — падаем ниже на обычный текст без превью
    await message.answer(phrase)


# ============================================================================
# ✨ МОДУЛЬ 11c — ОСОБЫЕ РП-ДЕЙСТВИЯ («отн особые» / «отн премиум», + название).
# Доступны всем парам, без привязки к уровню — фэнтезийные, несексуальные
# «эпические» жесты со своей наградой в искрах.
# РЕШЕНО: награда и откат для премиум-действий. ТЗ называет только сами
# названия, без чисел — числа подобраны по аналогии с топовыми действиями
# RP_ACTIONS (уровень 21-30), так что премиум ощущается как логичное
# продолжение прогрессии, а не отдельная несбалансированная ветка.
# Список — обычный словарь, правится без изменения остальной логики.
# ============================================================================

PREMIUM_RP_ACTIONS: list[dict] = [
    {"key": "empathy_aura",  "name": "✨ Аура эмпатии",         "reward": 5000,  "cooldown_minutes": 360},
    {"key": "neural_link",   "name": "🧠 Нейронная связь",       "reward": 8000,  "cooldown_minutes": 480},
    {"key": "parallel_world","name": "🌀 Параллельный мир",      "reward": 12000, "cooldown_minutes": 600},
    {"key": "dna_love",      "name": "🧬 ДНК любовь",            "reward": 16000, "cooldown_minutes": 720},
    {"key": "quantum_fusion","name": "⚛️ Квантовое слияние",     "reward": 25000, "cooldown_minutes": 1080},
    {"key": "chrono_sync",   "name": "⏳ Хроносинхронизация",    "reward": 32000, "cooldown_minutes": 1200},
    {"key": "divine_unity",  "name": "🌟 Божественная унификация","reward": 40000, "cooldown_minutes": 1440},
]

PREMIUM_RP_COOLDOWN_SCOPE = "rp_premium"


def find_premium_rp_action(query: str) -> Optional[dict]:
    q = query.strip().strip("«»\"'").casefold()
    if not q:
        return None
    for action in PREMIUM_RP_ACTIONS:
        if action["key"] == q or action["name"].casefold() == q:
            return action
    candidates = [a for a in PREMIUM_RP_ACTIONS if q in a["name"].casefold()]
    if candidates:
        candidates.sort(key=lambda a: len(a["name"]))
        return candidates[0]
    return None


async def cmd_rel2_premium_catalog(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return

    lines = ["✨ <b>Особые РП-действия</b>", DIVIDER]
    for action in PREMIUM_RP_ACTIONS:
        last_at = await db.get_rel2_cooldown(PREMIUM_RP_COOLDOWN_SCOPE, pair["id"], action["key"])
        on_cooldown = bool(
            last_at
            and (datetime.utcnow() - last_at).total_seconds() < action["cooldown_minutes"] * 60
        )
        icon = "⏳" if on_cooldown else "✅"
        cooldown_text = _format_rp_cooldown(action["cooldown_minutes"])
        lines.append(f"{icon} • «{action['name']}» | 🔥+{action['reward']}|{cooldown_text}")
    lines.append(DIVIDER)
    lines.append("Выполнить: <b>отн особые &lt;название&gt;</b>, например <b>отн особые аура эмпатии</b>.")
    await message.reply("\n".join(lines))


async def cmd_rel2_premium_action(message: Message, query: str) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    action = find_premium_rp_action(query)
    if action is None:
        await message.reply("Не нашёл такое действие. Список — <b>отн особые</b>.")
        return

    last_at = await db.get_rel2_cooldown(PREMIUM_RP_COOLDOWN_SCOPE, pair["id"], action["key"])
    if last_at:
        elapsed = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed < action["cooldown_minutes"]:
            remaining = _format_rp_cooldown(action["cooldown_minutes"] - elapsed)
            await message.reply(f"⏳ «{action['name']}» ещё восстанавливается: осталось {remaining}.")
            return

    new_balance = await db.adjust_rel2_sparks(pair["id"], action["reward"], "rp_premium_action")
    await db.set_rel2_cooldown(PREMIUM_RP_COOLDOWN_SCOPE, pair["id"], action["key"])

    level_up_line = ""
    if new_balance is not None:
        new_level = level_from_sparks(new_balance)
        if new_level != pair["level_index"]:
            await db.set_rel2_level(pair["id"], new_level)
            level_up_line = f"\n🆙 Новый уровень: <b>{new_level} ({level_name(new_level)})</b>!"

    await message.reply(
        f"✨ «{action['name']}»: +{action['reward']} искр!\nБаланс: {new_balance}.{level_up_line}"
    )


# ============================================================================
# 🛡 МОДУЛЬ 12 — ЗАЩИТА ОТ БЕРЕМЕННОСТИ, «ПОПЫТКА ЗАЧАТЬ» И САМА БЕРЕМЕННОСТЬ
# («отн презик», «отн зачать», «отн беременность»). Ненавязчивая, несексуальная
# механика: без описания самого процесса, просто шанс на исход + затем полный
# игровой цикл беременности. По умолчанию у каждой пары contraception=TRUE
# (защита включена) — «отн зачать» тогда гарантированно ничего не даёт, пока
# защиту не выключат явно командой «отн презик».
#
# РЕШЕНО: полноценная беременность в 40 недель, как в гайде — реализована как
# ОТДЕЛЬНЫЙ путь к ребёнку, параллельный уже существующему «отн родить»
# (мгновенное оформление по обоюдному согласию — своего рода «усыновление»,
# им как раньше можно пользоваться без зачатия вообще). «Отн зачать» при
# успехе запускает запись в rel2_pregnancies; 40 игровых недель сжаты в
# реальное время (см. PREGNANCY_HOURS_PER_WEEK) — с полным сроком меньше чем
# в сутки играть неинтересно, а с настоящими 40 календарными неделями никто
# не дождётся результата. Пока беременность активна и не доношена, «отн
# родить» для этой пары заблокирован (используйте «отн беременность», чтобы
# смотреть прогресс) — как только неделя 40 достигнута, «отн родить»
# работает как обычно, но при подтверждении автоматически закрывает именно
# эту беременность. Осознанно нет риска потери/осложнений — только позитивные
# вехи: у бота уже есть достаточно тяжёлый контент (болезни/смерть питомцев и
# пожилых детей), плодить второй источник негатива в геймплее не стали.
# ============================================================================

CONCEIVE_COOLDOWN_SCOPE = "rp_conceive"
CONCEIVE_COOLDOWN_MINUTES = 60
CONCEIVE_CHANCE = 0.35
CONCEIVE_CHANCE_PREMIUM = 0.45

PREGNANCY_TOTAL_WEEKS = 40
PREGNANCY_HOURS_PER_WEEK = 6          # 40 недель × 6ч = 240ч = 10 суток на весь срок
PREGNANCY_HOURS_PER_WEEK_PREMIUM = 4.5  # премиум: 40 × 4.5ч = 180ч = 7.5 суток — быстрее, как страховка/скидки в других модулях

# Вехи по неделям — как _LEVEL_MILESTONES выше: называем только опорные точки,
# промежуточные недели наследуют текст последней пройденной вехи.
PREGNANCY_MILESTONES: list[tuple[int, str]] = [
    (1, "🤰 Тест положительный — начался отсчёт."),
    (6, "🔍 Первое УЗИ: уже видно крошечное сердцебиение."),
    (13, "🌿 Конец первого триместра — самое тревожное время позади."),
    (20, "👣 Видно ручки и ножки, пол пока остаётся общей тайной."),
    (24, "🎶 Малыш уже слышит ваши голоса."),
    (28, "🌙 Начался третий триместр — финишная прямая."),
    (36, "🎒 Почти готово — сумка «в роддом» собрана."),
    (40, "👶 Пора! Роды доступны — используйте «отн родить»."),
]


def _pregnancy_hours_per_week(premium: bool) -> float:
    return PREGNANCY_HOURS_PER_WEEK_PREMIUM if premium else PREGNANCY_HOURS_PER_WEEK


def pregnancy_week(started_at: datetime, premium: bool) -> int:
    """Текущая неделя беременности (1..40), исходя из прошедшего времени."""
    elapsed_hours = (datetime.utcnow() - started_at).total_seconds() / 3600
    week = int(elapsed_hours // _pregnancy_hours_per_week(premium)) + 1
    return max(1, min(PREGNANCY_TOTAL_WEEKS, week))


def pregnancy_is_due(started_at: datetime, premium: bool) -> bool:
    return pregnancy_week(started_at, premium) >= PREGNANCY_TOTAL_WEEKS


def pregnancy_trimester(week: int) -> str:
    if week <= 13:
        return "1 триместр"
    if week <= 27:
        return "2 триместр"
    return "3 триместр"


def pregnancy_milestone_text(week: int) -> str:
    text = PREGNANCY_MILESTONES[0][1]
    for milestone_week, milestone_text in PREGNANCY_MILESTONES:
        if week >= milestone_week:
            text = milestone_text
        else:
            break
    return text


def pregnancy_eta(started_at: datetime, premium: bool) -> Optional[str]:
    """Сколько осталось примерно до 40-й недели, либо None если уже доношена."""
    if pregnancy_is_due(started_at, premium):
        return None
    hours_per_week = _pregnancy_hours_per_week(premium)
    total_hours = PREGNANCY_TOTAL_WEEKS * hours_per_week
    elapsed_hours = (datetime.utcnow() - started_at).total_seconds() / 3600
    remaining_hours = max(0.0, total_hours - elapsed_hours)
    if remaining_hours < 1:
        return f"{round(remaining_hours * 60)} мин"
    if remaining_hours < 48:
        return f"{round(remaining_hours)} ч"
    return f"{round(remaining_hours / 24, 1)} дн"


def _pregnancy_progress_bar(week: int, length: int = 20) -> str:
    filled = round(length * week / PREGNANCY_TOTAL_WEEKS)
    return "🟩" * filled + "⬜️" * (length - filled)


async def cmd_rel2_toggle_contraception(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    new_state = not pair["contraception"]
    await db.set_rel2_contraception(pair["id"], new_state)
    if new_state:
        await message.reply("🛡 Защита от беременности включена. «Отн секс теперь ничего не даст.")
    else:
        await message.reply(
            "⚠️ Защита от беременности выключена. Теперь у <b>отн секс</b> есть реальный шанс на успех."
        )


async def cmd_rel2_conceive(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return

    active_pregnancy = await db.get_active_rel2_pregnancy(pair["id"])
    if active_pregnancy:
        week = pregnancy_week(active_pregnancy["started_at"], True)
        await message.reply(
            f"🤰 У вас уже есть беременность в процессе (неделя {week}/{PREGNANCY_TOTAL_WEEKS}). "
            f"Подробности — <b>отн беременность</b>."
        )
        return

    last_at = await db.get_rel2_cooldown(CONCEIVE_COOLDOWN_SCOPE, pair["id"], "attempt")
    if last_at:
        elapsed = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed < CONCEIVE_COOLDOWN_MINUTES:
            remaining = _format_rp_cooldown(CONCEIVE_COOLDOWN_MINUTES - elapsed)
            await message.reply(f"⏳ Пробовать снова можно через {remaining}.")
            return
    await db.set_rel2_cooldown(CONCEIVE_COOLDOWN_SCOPE, pair["id"], "attempt")
    await db.increment_rel2_action_count(pair["id"], "kex")  # «Кексов» в карточке «отн я»

    if pair["contraception"]:
        await message.reply(
            "🛡 У вас включена защита от беременности (<b>отн презик</b>, чтобы выключить) — "
            "в этот раз ничего не произошло."
        )
        return

    chance = CONCEIVE_CHANCE_PREMIUM if True else CONCEIVE_CHANCE
    if random.random() < chance:
        await db.create_rel2_pregnancy(pair["id"], message.chat.id, message.from_user.id)
        hours_per_week = _pregnancy_hours_per_week(True)
        total_days = round(PREGNANCY_TOTAL_WEEKS * hours_per_week / 24, 1)
        await message.reply(
            "🎉 Похоже, получилось! Начался отсчёт беременности — "
            f"{PREGNANCY_TOTAL_WEEKS} недель (~{total_days} дн. реального времени).\n"
            "Следить за прогрессом — <b>отн беременность</b>. Когда срок подойдёт — "
            "<b>отн родить</b> [имя] ответом на сообщение того, кто станет вашим ребёнком."
        )
    else:
        await message.reply("😅 В этот раз не вышло. Можно попробовать снова позже.")


async def cmd_rel2_pregnancy_status(message: Message) -> None:
    pair = await _get_pair_or_reply(message)
    if pair is None:
        return
    pregnancy = await db.get_active_rel2_pregnancy(pair["id"])
    if not pregnancy:
        await message.reply(
            "Сейчас беременности нет. Попробовать — <b>отн зачать</b> (сначала выключите "
            "защиту: <b>отн презик</b>)."
        )
        return

    week = pregnancy_week(pregnancy["started_at"], True)
    lines = [
        "🤰 <b>Беременность</b>",
        DIVIDER,
        f"Неделя: <b>{week}/{PREGNANCY_TOTAL_WEEKS}</b> · {pregnancy_trimester(week)}",
        _pregnancy_progress_bar(week),
        pregnancy_milestone_text(week),
    ]
    eta = pregnancy_eta(pregnancy["started_at"], True)
    if eta:
        lines.append(f"⏳ Примерно до родов: {eta}")
    else:
        lines.append("👶 Срок подошёл! Используйте <b>отн родить</b> [имя] ответом на будущего ребёнка.")
    lines.append(DIVIDER)
    lines.append(f"🗓 Начало: {pregnancy['started_at'].strftime('%d.%m.%Y %H:%M')}")
    await message.reply("\n".join(lines))


# ============================================================================
# 🔥 Фоновый цикл: ежедневное списание искр + разрушение отношений при нуле
# ============================================================================

async def spark_decay_loop(bot, interval_seconds: int = 3600) -> None:
    """Раз в час проверяет пары, которым пора списать дневной расход искр
    (db.list_rel2_pairs_due_for_charge — сработает не чаще раза в 24 часа на
    пару, независимо от того, как часто крутится сам цикл). При обнулении
    баланса отношения разрушаются безвозвратно (премиум получает одноразовую
    страховку +500 искр — см. гайд, раздел «Искры»)."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    while True:
        try:
            due = await db.list_rel2_pairs_due_for_charge(hours=24)
            for row in due:
                pair_id = row["id"]
                cost = effective_daily_cost(row["level_index"], row["children_count"], row["premium"])
                new_balance = await db.adjust_rel2_sparks(pair_id, -cost, "daily_charge", floor_at_zero=True)
                await db.set_rel2_last_charge_at(pair_id)
                if new_balance is None:
                    continue

                if new_balance > 0:
                    new_level = level_from_sparks(new_balance)
                    if new_level != row["level_index"]:
                        await db.set_rel2_level(pair_id, new_level)
                    continue

                # Баланс дошёл до нуля — либо страховка (премиум, один раз), либо разрыв.
                if row["premium"] and not row["premium_insurance_used"]:
                    await db.adjust_rel2_sparks(pair_id, 500, "premium_insurance", floor_at_zero=True)
                    await db.mark_rel2_premium_insurance_used(pair_id)
                    await db.set_rel2_level(pair_id, level_from_sparks(500))
                    text = (
                        "🛡️ Искры дошли до нуля, но страховка спасла отношения: "
                        "начислено +500 искр (страховка одноразовая, больше не сработает)."
                    )
                    for uid in (row["user1_id"], row["user2_id"]):
                        try:
                            await bot.send_message(uid, text)
                        except Exception:
                            pass
                    continue

                deleted_pair_id = await db.delete_rel2_pair(row["chat_id"], row["user1_id"])
                text = "💔 Искры закончились — отношения разрушены безвозвратно."
                for uid in (row["user1_id"], row["user2_id"]):
                    try:
                        await bot.send_message(uid, text)
                    except Exception:
                        pass
                try:
                    await bot.send_message(row["chat_id"], text)
                except Exception:
                    pass
                await db.add_log(
                    "relationship2_broken_sparks", chat_id=row["chat_id"],
                    actor_id=row["user1_id"], target_id=row["user2_id"],
                )
                if deleted_pair_id is None:
                    logger.warning("rel2: пара %s уже была удалена к моменту списания", pair_id)
        except Exception:
            logger.exception("Ошибка в spark_decay_loop")
        await asyncio.sleep(interval_seconds)


# ============================================================================
# ИНТЕГРАЦИЯ (что добавить в bot.py, когда модуль будет готов к подключению)
# ============================================================================
#
# import relationships_v2
#
# dp.include_router(relationships_v2.router)   # ДО старого router'а с «отн»,
#                                               # либо вместо него — см. докстринг
#
# в main():
#     await db.ensure_rel2_tables()
#     await db.ensure_rel2_house_tables()      # модуль 3 — дома
#     await db.ensure_rel2_pet_tables()        # модуль 4 — питомцы
#     await db.ensure_rel2_children_tables()   # модуль 5 — дети
#     await db.ensure_rel2_pregnancy_tables()  # модуль 12 — беременность (40 недель)
#     await db.ensure_rel2_cooldown_table()    # модули 7/8/12 — семейные события, дуэли питомцев, зачатие
#     await db.seed_rel2_levels_if_empty(relationships_v2.build_rel2_level_table())
#     await relationships_v2.load_rel2_caches()
#     asyncio.create_task(relationships_v2.spark_decay_loop(bot))
#     asyncio.create_task(relationships_v2.house_maintenance_loop(bot))
#     asyncio.create_task(relationships_v2.pet_upkeep_loop(bot))
#     asyncio.create_task(relationships_v2.child_aging_loop(bot))
#     asyncio.create_task(relationships_v2.pregnancy_announce_loop(bot))  # модуль 12 — вехи беременности
#
# TODO (следующие модули из гайда, каждый — отдельным этапом):
#   - РП-действия (модуль 11, «отн действия» / «отн сделать …») готовы: 30
#     действий, открываются по уровню пары, требуют db.ensure_rel2_cooldown_table()
#     (используется и модулями 7/8). Премиум-действия сверху этого — отдельный
#     этап (пока премиум просто даёт +25%/-30% ко всем РП-действиям).
#   - Беременность (модуль 12) готова: 40 недель, вехи, прогресс-бар,
#     привязка к «отн родить» — см. докстринг файла.
#   - ~~Премиум (покупка/продление, звёзды)~~ — больше не нужно: премиум
#     выдан всем бесплатно (rel2_pairs.premium = TRUE по умолчанию + разовый
#     бэкафилл в db.ensure_rel2_tables(), см. РЕШЕНО там же).
#   - Подарки, задания
#   - Оплата премиум-яйца звёздами (сейчас «отн пт яйцо premium» лишь
#     сообщает цену — нужна интеграция с Telegram Stars invoicing)
