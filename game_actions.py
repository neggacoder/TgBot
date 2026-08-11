"""Игровые действия: сделать и вернуть результат. Ничего не отправляет.

Зачем модуль вообще. Панель — отдельный процесс и bot.py импортировать не
может: это подняло бы второго бота. А игровая логика жила именно там,
вперемешку с ответами в Telegram. Значит либо панель повторяет правила у
себя — и появляется вторая правда о ценах и кулдаунах, — либо действия
переезжают сюда. Переехали.

Здесь НЕТ бота и НЕТ отправки сообщений, и это не упущение, а главное
свойство: тишина на сайте получается сама. Заглушку «не отвечать» можно
забыть поставить в новом эндпоинте; отсутствующего клиента Telegram забыть
нельзя.

Отчёт возвращается вызывающему. Объявления — ачивка, новый уровень, новая
звезда — отдаются отдельным списком: их положено показать в чате, даже если
кнопку нажали на сайте, и решает это тот, кто позвал.
"""

from __future__ import annotations

import html
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional

import collections_meta
import db
import pets as pets_catalog
import pins

logger = logging.getLogger(__name__)

ANNOUNCE_ACHIEVEMENT = "achievement"
ANNOUNCE_PET_LEVEL = "pet_level"
ANNOUNCE_FARM_STAR = "farm_star"


@dataclass(frozen=True)
class Announcement:
    """То, что положено объявить в чат отдельным сообщением."""
    kind: str
    text: str


@dataclass(frozen=True)
class ActionResult:
    """Итог действия: что показать сделавшему и что объявить чату.

    ok=False — не ошибка программы, а законный исход игры: не хватило
    монет, не вышел кулдаун, счёт заморожен. Текст в обоих случаях один и
    тот же, поэтому в чате и на сайте человек читает одно и то же.

    announcements нужны ТОЛЬКО тому вызывающему, чей отчёт в чат не попадает,
    — то есть панели: её text уходит в HTTP-ответ, и без отдельного сообщения
    чат о новом уровне не узнает. Боту они не нужны и вредны: он этот же text
    печатает ответом, «⭐ Новый уровень» уже внутри него, и отправка второго
    сообщения означала бы дубль, а в массовых сводках — по сообщению на
    каждого выросшего питомца поверх сводки, где они уже перечислены.
    """
    ok: bool
    text: str
    announcements: tuple[Announcement, ...] = ()

    @classmethod
    def fail(cls, text: str) -> "ActionResult":
        return cls(False, text)


def _log_suppressed(where: str, exc: BaseException) -> None:
    """Записать ошибку, которую мы осознанно НЕ пробрасываем дальше.

    Своя копия, а не импорт из bot.py: оттуда сюда импортировать нельзя в
    принципе — ради этого модуль и заводился. Дублируется одна строка
    журналирования, а не правило игры, поэтому разъехаться тут нечему.
    """
    logger.warning("Подавлена ошибка в %s: %s: %s", where, type(exc).__name__, exc)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Верное русское склонение числительного: 1 день, 2 дня, 5 дней и т.п."""
    n_abs = abs(n)
    if 11 <= n_abs % 100 <= 14:
        return many
    last = n_abs % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def format_left(td: timedelta) -> str:
    """Человекочитаемая длительность вроде «2 дня 3 часа» или «45 минут» —
    полными словами (день/час/минута/секунда), а не однобуквенными кодами.
    Показывает два самых крупных ненулевых разряда, чтобы не загромождать вывод."""
    total_seconds = int(td.total_seconds())
    if total_seconds <= 0:
        return "0 секунд"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    units = [
        (days, "день", "дня", "дней"),
        (hours, "час", "часа", "часов"),
        (minutes, "минута", "минуты", "минут"),
        (seconds, "секунда", "секунды", "секунд"),
    ]
    parts = [f"{value} {_plural_ru(value, one, few, many)}" for value, one, few, many in units if value]
    return " ".join(parts[:2]) if parts else "0 секунд"


# --- питомцы: время, опыт, уровень ------------------------------------------

def _pet_hours(row: dict) -> float:
    last = row.get("last_tick_at")
    if not last:
        return 0.0
    return max(0.0, (datetime.utcnow() - last).total_seconds() / 3600)


def _pet_xp_hours(row: dict) -> float:
    """Отдельная метка от _pet_hours: xp_tick_at не имеет истории с покупки
    питомца (см. миграцию в db.ensure_pets_table) — считать опыт от
    last_tick_at выдало бы старым питомцам мгновенный максимальный уровень."""
    last = row.get("xp_tick_at")
    if not last:
        return 0.0
    return max(0.0, (datetime.utcnow() - last).total_seconds() / 3600)


def _pet_xp_now(row: dict) -> int:
    return pets_catalog.xp_now(int(row.get("xp") or 0), _pet_xp_hours(row))


def _pet_level(row: dict) -> int:
    return pets_catalog.level_for_xp(_pet_xp_now(row))


def _pet_now(row: dict, mood_slowdown: int = 0,
             hunger_slowdown: int = 0) -> tuple[int, int]:
    """Сытость и настроение ПРЯМО СЕЙЧАС, с учётом прошедшего времени.

    mood_slowdown — на сколько процентов медленнее падает настроение
    («Компаньон»). Передаётся снаружи, чтобы расчёт остался синхронным:
    он зовётся в отрисовке списков и в профиле.
    """
    hours = _pet_hours(row)
    mood_hours = hours * (100 - max(0, min(mood_slowdown, 90))) / 100
    hunger_hours = hours * (100 - max(0, min(hunger_slowdown, 90))) / 100
    stored_hunger = int(row.get("hunger") or 0)
    hunger = (pets_catalog.hunger_now_evolved(stored_hunger, hunger_hours)
              if row.get("evolved")
              else pets_catalog.hunger_now(stored_hunger, hunger_hours))
    return hunger, pets_catalog.mood_now(int(row.get("mood") or 0), mood_hours)


# --- питомцы: способности и каталог -----------------------------------------

def _effective_ability(row: dict, spec) -> str:
    """Способность питомца У ЭТОГО хозяина: своя, если её меняли за деньги
    (row['ability'] — override, см. пет способность), иначе — способность
    вида из каталога. NULL/пусто в row означает «override не задан»."""
    override = row.get("ability")
    if override:
        return override
    return spec.ability if spec else pets_catalog.ABILITY_NONE


def _effective_abilities(row: dict, spec) -> tuple[str, ...]:
    """Все способности питомца: своя (или вида) плюс вторая, если он
    эволюционировал. Считаются обе — в этом и смысл эволюции."""
    out = [_effective_ability(row, spec)]
    second = row.get("ability2")
    if second and second != pets_catalog.ABILITY_NONE:
        out.append(second)
    return tuple(a for a in out if a and a != pets_catalog.ABILITY_NONE)


# Настройки видов питомцев в конкретном чате: выключен ли вид и есть ли
# потолок численности. Заполняется _pet_specs(), читается покупкой.
_pet_settings: dict[str, dict] = {}


async def _pet_specs(chat_id: int) -> dict:
    """Каталог питомцев чата: встроенные из pets.py плюс заведённые админом.

    Живёт в БД, потому что админ может создать своего питомца в панели;
    встроенные при каждом обращении досеиваются, чтобы новые из кода доезжали
    и в чаты, где каталог уже есть.
    """
    await db.ensure_pet_catalog(chat_id, pets_catalog.PETS)
    out: dict = {}
    settings_by_key = _pet_settings
    for row in await db.list_pet_catalog(chat_id):
        spec = pets_catalog.Pet(
            key=row["pet_key"],
            # Название, эмодзи и звук пишет админ (в боте они режутся только
            # по длине), а показываются они и в чате, и в кабинете на сайте —
            # а там текст вставляется как HTML на том же адресе, где живёт
            # админ-панель со своей кукой. Раньше такой текст просто отвергал
            # Telegram, теперь он исполняется в чужом браузере. Экранируем
            # здесь — это единственная точка, где строки каталога чата
            # становятся видом; ниже их разбирает по текстам полтора десятка
            # мест, и забыть одно из них было бы вопросом времени.
            name=html.escape(row["name"] or ""),
            emoji=html.escape(row["emoji"] or ""),
            price=int(row["price"]), sound=html.escape(row["sound"] or ""),
            # Без этого способность терялась при чтении из базы и все питомцы
            # молча становились бесполезными: в каталоге эффект есть, а
            # в объекте — ABILITY_NONE по умолчанию.
            ability=row.get("ability") or pets_catalog.ABILITY_NONE,
            # За какую ачивку выдаётся — только у встроенных: админ наградных
            # видов не заводит, и хранить это в БД незачем. Без переноса
            # наградный питомец, прочитанный из каталога, оказался бы обычным
            # покупным — ровно как когда-то терялась способность.
            achievement=(pets_catalog.BY_KEY.get(row["pet_key"])
                         or pets_catalog.Pet("", "", "", 0, "")).achievement,
        )
        # Выключатель и потолок численности живут только в базе (их правит
        # панель), поэтому кладём их рядом со спецификацией, а не в саму
        # неизменяемую Pet — она описывает вид, а не его настройку в чате.
        out[row["pet_key"]] = spec
        settings_by_key[row["pet_key"]] = {
            "is_active": bool(row.get("is_active", True)),
            "max_count": row.get("max_count"),
        }
    return out


async def _pet_spec(chat_id: int, raw: Optional[str]):
    """Питомец по ключу или по-русски, с учётом созданных админом."""
    if not raw:
        return None
    specs = await _pet_specs(chat_id)
    key = " ".join(raw.strip().casefold().split())
    if key in specs:
        return specs[key]
    # Русские названия: сначала встроенные синонимы, потом по самому названию.
    builtin = pets_catalog.resolve(raw)
    if builtin is not None and builtin.key in specs:
        return specs[builtin.key]
    for spec in specs.values():
        # Название в specs уже экранировано (см. _pet_specs), а человек пишет
        # его как есть — сравнивать надо с исходным, иначе вид с амперсандом в
        # названии перестал бы находиться по названию.
        if html.unescape(spec.name).casefold() == key:
            return spec
    return None


async def _pinned_pet_key(chat_id: int, user_id: int) -> Optional[str]:
    try:
        card = await db.get_profile_card(chat_id, user_id)
    except Exception as exc:
        _log_suppressed("_pinned_pet_key", exc)
        return None
    return (card or {}).get("pinned_pet")


# --- питомцы: сила способностей ---------------------------------------------

ABILITY_PET_MOOD = "pet_mood"
ABILITY_PET_HUNGER = "pet_hunger"
ABILITY_PET_XP = "pet_xp"
ABILITY_PET_WALK = "pet_walk"
ABILITY_PET_FEED = "pet_feed"
ABILITY_PET_CARE = "pet_care"
ABILITY_PET_FIND = "pet_find"


def _pet_is_active(row: dict, hunger: int, mood: int,
                   pinned_key: Optional[str]) -> bool:
    """Работает ли способность этого питомца прямо сейчас.

    У закреплённого порог ниже обычного: закреп — слот экипировки, и его
    смысл в том, что закреплённому прощается пропущенная кормёжка. Не
    «никогда не засыпает» — ухаживать всё равно надо.
    """
    if pinned_key and row.get("pet_key") == pinned_key:
        return hunger >= pins.PET_LOW_STAT and mood >= pins.PET_LOW_STAT
    return pets_catalog.is_active(hunger, mood)


def _pet_family_bonus(rows: list[dict], specs: dict, ability: str,
                      pinned_key: Optional[str] = None) -> int:
    """Сила способности, которая действует на ВСЕХ питомцев хозяина сразу.

    Таких семь: «Компаньон» (настроение), «Хозяйственный» (сытость),
    «Наставник» (опыт), «Следопыт» (монеты с прогулки), а также усиленные
    кормление, ласка и поиск находок. Считаются они одинаково, поэтому и код
    один: разойдись он на семь копий, однажды
    одна из них забыла бы про эволюцию или про закреп.

    Рекурсии здесь нет намеренно: сам носитель проверяется по состоянию БЕЗ
    поблажки — иначе он поддерживал бы сам себя, и вопрос «работает ли он» не
    имел бы однозначного ответа.
    """
    total = 0
    found = pets_catalog.ABILITY_BY_KEY.get(ability)
    if found is None:
        return 0
    for row in rows:
        spec = specs.get(row["pet_key"])
        if spec is None or ability not in _effective_abilities(row, spec):
            continue
        hunger, mood = _pet_now(row)          # без поблажки — см. докстринг
        if not _pet_is_active(row, hunger, mood, pinned_key):
            continue
        total += pets_catalog.ability_percent(
            ability, _pet_level(row), evolved=bool(row.get("evolved")))
    return total


@dataclass(frozen=True)
class PetAura:
    """Что способности ваших питомцев дают ВСЕМ вашим питомцам сразу.

    Одной структурой, а не россыпью процентов по аргументам: таких способностей
    уже семь, и следующая иначе потребовала бы править сигнатуру кормёжки,
    ласки и прогулки разом — а забыть одну из трёх проще простого.
    """
    mood: int = 0      # «Компаньон» — настроение падает медленнее
    hunger: int = 0    # «Хозяйственный» — сытость падает медленнее
    xp: int = 0        # «Наставник» — опыт растёт быстрее
    walk: int = 0      # «Следопыт» — больше монет с прогулки
    feed: int = 0      # «Заботливый» — корм лучше насыщает
    care: int = 0      # «Ласковый» — ласка лучше поднимает настроение
    find: int = 0      # «Искатель» — выше шанс находки на прогулке

    def xp_gain(self, base: int) -> int:
        return base + base * max(0, self.xp) // 100

    def walk_coins(self, base: int) -> int:
        return base + base * max(0, self.walk) // 100

    def feed_gain(self, base: int) -> int:
        return base + base * max(0, self.feed) // 100

    def care_gain(self, base: int) -> int:
        return base + base * max(0, self.care) // 100

    def find_chance(self, base: int) -> int:
        return min(100, base + base * max(0, self.find) // 100)


def _pet_aura(rows: list[dict], specs: dict,
              pinned_key: Optional[str] = None) -> PetAura:
    return PetAura(
        mood=_pet_family_bonus(rows, specs, ABILITY_PET_MOOD, pinned_key),
        hunger=_pet_family_bonus(rows, specs, ABILITY_PET_HUNGER, pinned_key),
        xp=_pet_family_bonus(rows, specs, ABILITY_PET_XP, pinned_key),
        walk=_pet_family_bonus(rows, specs, ABILITY_PET_WALK, pinned_key),
        feed=_pet_family_bonus(rows, specs, ABILITY_PET_FEED, pinned_key),
        care=_pet_family_bonus(rows, specs, ABILITY_PET_CARE, pinned_key),
        find=_pet_family_bonus(rows, specs, ABILITY_PET_FIND, pinned_key),
    )


async def pet_aura_for(chat_id: int, user_id: int) -> "PetAura":
    """То же самое, но когда строк питомцев под рукой нет (поштучные команды).

    Ошибку глотаем по той же причине, что и в _pet_bonus: поблажка — приятная
    добавка, а не основа расчёта, и упавший запрос не должен ломать кормёжку.
    """
    try:
        rows = await db.list_pets(chat_id, user_id)
        if not rows:
            return PetAura()
        return _pet_aura(rows, await _pet_specs(chat_id),
                         await _pinned_pet_key(chat_id, user_id))
    except Exception as exc:
        _log_suppressed("pet_aura_for", exc)
        return PetAura()


def _pet_ability_sums(rows: list[dict], specs: dict, pinned_key: Optional[str],
                      aura: "PetAura", abilities: tuple[str, ...]) -> dict[str, int]:
    """Сила сразу нескольких способностей за один проход по питомцам.

    Отдельной функцией, потому что владельцев два: поштучный _pet_bonus и
    огород, которому нужны три способности разом. Разойдись подсчёт на две
    копии — одна однажды забыла бы про эволюцию или про закреп.

    Закреплённому питомцу способность засыпает позже: это его слот экипировки
    (см. pins.PET_LOW_STAT). Карточку читает вызывающий — один раз на весь
    проход, а не по разу на питомца.
    """
    total = {ability: 0 for ability in abilities}
    for row in rows:
        spec = specs.get(row["pet_key"])
        if spec is None:
            continue
        own = _effective_abilities(row, spec)
        hit = [ability for ability in abilities if ability in own]
        if not hit:
            continue
        hunger, mood = _pet_now(row, aura.mood, aura.hunger)
        if not _pet_is_active(row, hunger, mood, pinned_key):
            continue
        for ability in hit:
            total[ability] += pets_catalog.ability_percent(
                ability, _pet_level(row), evolved=bool(row.get("evolved")))
    return total


async def _pet_bonus(chat_id: int, user_id: int, ability: str) -> int:
    """Прибавка в процентах от питомцев с этой способностью.

    Считаются ТОЛЬКО сытые и довольные (pets.is_active): в этом и смысл
    ухода — перестал кормить, потерял выгоду. Складывается, если питомцев
    с одной способностью несколько.

    Ошибку глотаем: способность питомца — приятный бонус, а не основа
    начисления, и упавший запрос не должен ронять саму ферму или налёт.
    """
    if not ability:
        return 0
    try:
        rows = await db.list_pets(chat_id, user_id)
        if not rows:
            return 0
        specs = await _pet_specs(chat_id)
    except Exception as exc:
        _log_suppressed("_pet_bonus", exc)
        return 0

    # «Компаньон» замедляет падение настроения — учитываем его ДО проверки
    # активности остальных, иначе панда не могла бы вытянуть загрустившую
    # компанию, ради чего она и заводится.
    pinned_key = await _pinned_pet_key(chat_id, user_id)
    aura = _pet_aura(rows, specs, pinned_key)
    return _pet_ability_sums(rows, specs, pinned_key, aura, (ability,))[ability]


# --- питомцы: откаты, имена, кормление --------------------------------------

def _pet_cooldown_left(row: dict, field: str, minutes: int) -> Optional[timedelta]:
    """Сколько ещё ждать до повтора действия. None — можно прямо сейчас.

    Отдельная функция, потому что откат теперь проверяется в четырёх местах:
    поштучно и массово, для кормёжки и для ласки. В массовой команде он не
    ошибка, а строка в сводке, — и разъехавшиеся копии проверки означали бы
    «поштучно рано, а пачкой уже можно».
    """
    last = row.get(field)
    if not last:
        return None
    left = timedelta(minutes=minutes) - (datetime.utcnow() - last)
    return left if left > timedelta(0) else None


def pet_feed_left(row: dict) -> Optional[timedelta]:
    return _pet_cooldown_left(row, "last_fed_at", pets_catalog.FEED_COOLDOWN_MINUTES)


def pet_care_left(row: dict) -> Optional[timedelta]:
    return _pet_cooldown_left(row, "last_care_at", pets_catalog.CARE_COOLDOWN_MINUTES)


def pet_walk_left(row: dict) -> Optional[timedelta]:
    return _pet_cooldown_left(row, "last_walk_at",
                              int(pets_catalog.WALK_COOLDOWN_HOURS * 60))


def pet_display(row: dict, spec=None) -> str:
    """Как питомец называется в тексте. spec можно передать снаружи, чтобы
    не ходить в каталог второй раз; без него берётся встроенный, а для
    заведённого админом — просто ключ.

    Эволюционировавший показывается НОВЫМ обликом: ради него эволюцию и
    делают, и видеть в списке прежнего хомяка было бы обидно."""
    spec = spec or pets_catalog.BY_KEY.get(row["pet_key"])
    grown = pets_catalog.evolution_of(row["pet_key"]) if row.get("evolved") else None
    if grown is not None:
        base = f"{grown.emoji} {grown.name}"
    else:
        # Вида нет в каталоге — показываем ключ, а его тоже заводит админ:
        # экранируем, как и всё остальное из каталога чата.
        base = spec.title if spec else html.escape(row["pet_key"])
    given = row.get("pet_name")
    return f"{base} «{html.escape(given)}»" if given else base


def no_food_text() -> str:
    return (f"{pets_catalog.FOOD_ITEM_EMOJI} Корма нет — кормить нечем.\n"
            f"Купить: <code>пет корм 10</code> "
            f"(1 шт. — {pets_catalog.FOOD_ITEM_PRICE} i¢).")


def pet_waiting_line(waiting: list[tuple[object, timedelta]]) -> str:
    """Строка «ждут отката» для массовых команд. Общая для кормёжки, ласки и
    прогулки — три копии однажды показали бы разное число «и ещё N»."""
    shown = ", ".join(f"{spec.name} ({format_left(left)})"
                      for spec, left in waiting[:5])
    tail = f" и ещё {len(waiting) - 5}" if len(waiting) > 5 else ""
    return f"⏳ Ждут отката: {shown}{tail}"


async def pets_for_bulk(chat_id: int, user_id: int) -> tuple[list[tuple[dict, object]], str]:
    """Питомцы хозяина парами (строка, вид) для массовых команд.

    Второй элемент — текст ошибки, если пар нет; пустая строка иначе. Ответ
    в чат тут не шлётся: сам список нужен и панели, у которой отчёт уходит
    в HTTP, а не сообщением.
    """
    rows = await db.list_pets(chat_id, user_id)
    if not rows:
        return [], "У вас нет питомцев — каталог: <code>пет каталог</code>."
    specs = await _pet_specs(chat_id)
    # Вид могли удалить из каталога чата: такого питомца не нарисовать и не
    # описать, поэтому в пачку он не идёт (поштучно на него ругнётся pick_pet).
    pairs = [(row, specs[row["pet_key"]]) for row in rows if row["pet_key"] in specs]
    if not pairs:
        return [], ("Ваши питомцы больше не значатся в каталоге чата — "
                    "спросите администрацию.")
    return pairs, ""


async def _feed_pet(chat_id: int, user_id: int, spec, row: dict,
                    now: datetime, aura: "PetAura" = None) -> Optional[tuple[int, int, int]]:
    """Одно кормление: тратит корм и банкует статы.

    Возвращает (сытость, уровень до, уровень после) или None — корма не
    хватило. Списание И ЕСТЬ проверка запаса: между «посмотрели, сколько
    корма» и «покормили» его могли потратить соседним сообщением, а два
    отдельных шага «проверить и списать» разошлись бы именно на этом.

    Корм уходит ДО записи статов и возвращается, если запись не удалась, —
    тем же порядком, каким при покупке питомца сначала списываются деньги,
    а потом возвращаются при неудаче.
    """
    aura = aura or PetAura()
    if not await db.remove_inventory_item(chat_id, user_id, pets_catalog.FOOD_ITEM_KEY):
        return None
    # Поблажка «Компаньона» обязана участвовать здесь: настроение отсюда
    # БАНКУЕТСЯ, и посчитанное без неё стёрло бы её накопленный эффект.
    hunger, mood = _pet_now(row, aura.mood, aura.hunger)
    hunger = pets_catalog.gain(hunger, aura.feed_gain(pets_catalog.FEED_GAIN))
    level_before = _pet_level(row)
    xp = pets_catalog.xp_add(_pet_xp_now(row), aura.xp_gain(pets_catalog.XP_BONUS_FEED))
    try:
        await db.set_pet_stats(chat_id, user_id, spec.key, hunger, mood, xp,
                               now, fed_at=now)
    except Exception:
        await db.add_inventory_item(chat_id, user_id, pets_catalog.FOOD_ITEM_KEY)
        raise
    return hunger, level_before, pets_catalog.level_for_xp(xp)


def _care_gain(verb: str) -> int:
    if verb.startswith(("поцел", "целов")):
        return pets_catalog.KISS_GAIN
    if verb.startswith("обн"):
        return pets_catalog.HUG_GAIN
    return pets_catalog.PET_GAIN


def _care_past(verb: str) -> str:
    """Как назвать сделанное в ответе."""
    if verb.startswith(("поцел", "целов")):
        return "поцеловали"
    if verb.startswith("обн"):
        return "обняли"
    return "погладили"


async def _care_pet(chat_id: int, user_id: int, spec, row: dict, verb: str,
                    now: datetime, aura: "PetAura" = None) -> tuple[int, int, int]:
    """Одна ласка: (настроение, уровень до, уровень после). Ласка бесплатна —
    платить нужно за еду, а не за внимание.

    aura — способности, действующие на всех ваших питомцев (см. PetAura):
    настроение отсюда БАНКУЕТСЯ, и посчитать его без поблажки значило бы
    стирать её при каждой ласке."""
    aura = aura or PetAura()
    hunger, mood = _pet_now(row, aura.mood, aura.hunger)
    mood = pets_catalog.gain(mood, aura.care_gain(_care_gain(verb)))
    level_before = _pet_level(row)
    xp = pets_catalog.xp_add(_pet_xp_now(row), aura.xp_gain(pets_catalog.XP_BONUS_CARE))
    await db.set_pet_stats(chat_id, user_id, spec.key, hunger, mood, xp,
                           now, care_at=now)
    return mood, level_before, pets_catalog.level_for_xp(xp)


async def pick_pet(chat_id: int, user_id: int,
                   raw: Optional[str]) -> tuple[Optional[object], Optional[dict], str]:
    """(вид, строка питомца, текст ошибки). Вид None — питомец не найден.

    Отдельно от обработчика, потому что «какого питомца имели в виду» —
    правило игры, одинаковое в чате и на сайте: без ключа берём
    единственного, с ключом — названного.
    """
    if raw:
        spec = await _pet_spec(chat_id, raw)
        if spec is None:
            return None, None, "Такого питомца нет — посмотрите <code>пет каталог</code>."
        row = await db.get_pet(chat_id, user_id, spec.key)
        if row is None:
            return None, None, f"{spec.title} у вас нет."
        return spec, row, ""
    rows = await db.list_pets(chat_id, user_id)
    if not rows:
        return None, None, "У вас нет питомцев — каталог: <code>пет каталог</code>."
    if len(rows) > 1:
        return None, None, ("У вас несколько питомцев — укажите, кого именно "
                            "(<code>пет кормить кот</code>) или сразу всех "
                            "(<code>пет кормить все</code>).")
    row = rows[0]
    spec = (await _pet_specs(chat_id)).get(row["pet_key"])
    if spec is None:
        # Вид убрали из каталога чата. Раньше в этом случае возвращался
        # питомец без вида, обработчик молча выходил, и человек не понимал,
        # почему команда не сработала, — тот же довод, что в массовых.
        return None, None, "Ваш питомец больше не значится в каталоге чата — " \
                           "спросите администрацию."
    return spec, row, ""


def _level_up_announcement(row: dict, spec, level: int) -> Announcement:
    """Объявление о новом уровне питомца — кормёжка, ласка и обе массовые
    формы показывают его слово в слово. Вынесено в одно место, потому что ни
    один текстовый тест не сверяет эту строку целиком: будущая переформулировка
    иначе попала бы в часть копий и разошлась бы молча с остальными.
    """
    return Announcement(
        ANNOUNCE_PET_LEVEL,
        f"⭐ {pet_display(row, spec)} вырос(ла) до уровня {level}!")


async def feed_pet(chat_id: int, user_id: int,
                   raw: Optional[str] = None) -> ActionResult:
    """Покормить питомца. Корм списывается только при удачном кормлении."""
    spec, row, err = await pick_pet(chat_id, user_id, raw)
    if spec is None:
        return ActionResult.fail(err)
    left = pet_feed_left(row)
    if left is not None:
        return ActionResult.fail(
            f"🍽 {spec.name} пока сыт — покормить снова через {format_left(left)}.")
    aura = await pet_aura_for(chat_id, user_id)
    result = await _feed_pet(chat_id, user_id, spec, row, datetime.utcnow(), aura)
    if result is None:
        return ActionResult.fail(no_food_text())
    hunger, level_before, level_after = result
    text = (f"🍽 {pet_display(row, spec)} накормлен(а). Сытость: "
            f"{pets_catalog.bar(hunger)} {hunger}")
    announcements: list[Announcement] = []
    if level_after > level_before:
        text += f"\n⭐ Новый уровень: {level_after}!"
        announcements.append(_level_up_announcement(row, spec, level_after))
    left_food = await db.get_inventory_quantity(chat_id, user_id,
                                                pets_catalog.FOOD_ITEM_KEY)
    text += f"\n{pets_catalog.FOOD_ITEM_EMOJI} Корма осталось: {left_food}"
    return ActionResult(True, text, tuple(announcements))


async def care_pet(chat_id: int, user_id: int, verb: str,
                   raw: Optional[str] = None) -> ActionResult:
    """Погладить, обнять или поцеловать питомца. Ласка бесплатна и делит
    один откат на все три слова — это одно действие, а не три механики.

    verb приходит уже разобранным из регулярки бота (см. PET_CARE_VERBS):
    здесь он не текст сообщения, а выбор игрока, что и роднит чат с сайтом.
    """
    spec, row, err = await pick_pet(chat_id, user_id, raw)
    if spec is None:
        return ActionResult.fail(err)
    left = pet_care_left(row)
    if left is not None:
        return ActionResult.fail(
            f"😊 {spec.name} уже доволен(а) — ещё раз через {format_left(left)}.")
    aura = await pet_aura_for(chat_id, user_id)
    mood, level_before, level_after = await _care_pet(
        chat_id, user_id, spec, row, verb, datetime.utcnow(), aura)
    text = (f"💞 Вы {_care_past(verb)} {pet_display(row, spec)} — {spec.sound}. "
            f"Настроение: {pets_catalog.bar(mood)} {mood}")
    announcements: list[Announcement] = []
    if level_after > level_before:
        text += f"\n⭐ Новый уровень: {level_after}!"
        announcements.append(_level_up_announcement(row, spec, level_after))
    return ActionResult(True, text, tuple(announcements))


# Разделитель в сводках массовых команд. Своя копия константы из bot.py (там
# она общая на весь бот, добрая сотня мест) — рукописная копия строкового
# литерала может разойтись молча, поэтому test_game_parity.py отдельно
# сверяет её с bot.DIVIDER построчно.
_DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


async def _bulk_aura(chat_id: int, user_id: int,
                     pairs: list[tuple[dict, object]]) -> tuple["PetAura", Optional[str]]:
    """Аура и закреп для массовой команды — общий пролог кормёжки, ласки и
    прогулки: взять пары, собрать вид по ключу, узнать закреп. Вынесено в
    одно место, потому что три чуть разных места набора одних и тех же трёх
    строк рано или поздно разъехались бы при следующей правке одного из них.

    Закреп отдаётся отдельно, а не прячется внутри PetAura: прогулке он нужен
    ещё раз — для проверки, кто из питомцев в настроении идти.
    """
    pinned_key = await _pinned_pet_key(chat_id, user_id)
    aura = _pet_aura([row for row, _ in pairs],
                     {spec.key: spec for _, spec in pairs}, pinned_key)
    return aura, pinned_key


async def feed_all(chat_id: int, user_id: int) -> ActionResult:
    """«пет покормить все» — накормить всех, на кого хватит корма.

    Считается ЦЕЛИКОМ здесь, а не в обработчике: разница между «покормил
    одного» и «покормил, кого хватило корма», — то, что сайту иначе пришлось
    бы повторять от себя.
    """
    pairs, err = await pets_for_bulk(chat_id, user_id)
    if err:
        return ActionResult.fail(err)
    now = datetime.utcnow()
    aura, _pinned_key = await _bulk_aura(chat_id, user_id, pairs)
    waiting: list[tuple[object, timedelta]] = []
    hungry: list[tuple[dict, object]] = []
    for row, spec in pairs:
        left = pet_feed_left(row)
        if left is not None:
            waiting.append((spec, left))
        else:
            hungry.append((row, spec))
    if not hungry:
        return ActionResult.fail("🍽 Все ваши питомцы уже сыты.\n" + pet_waiting_line(waiting))
    fed: list[tuple[dict, object, tuple[int, int, int]]] = []
    unfed = 0
    for i, (row, spec) in enumerate(hungry):
        result = await _feed_pet(chat_id, user_id, spec, row, now, aura)
        if result is None:
            # Корм кончился — остальных кормить нечем, дальше идти незачем.
            unfed = len(hungry) - i
            break
        fed.append((row, spec, result))
    if not fed:
        return ActionResult.fail(no_food_text())
    lines = [f"🍽 <b>Покормлено: {len(fed)} из {len(hungry)}</b>", _DIVIDER]
    announcements: list[Announcement] = []
    for row, spec, (hunger, before, after) in fed:
        line = f"{pet_display(row, spec)} — {pets_catalog.bar(hunger)} {hunger}"
        if after > before:
            line += f"\n   ⭐ Новый уровень: {after}!"
            announcements.append(_level_up_announcement(row, spec, after))
        lines.append(line)
    if unfed:
        lines.append(f"{pets_catalog.FOOD_ITEM_EMOJI} Корма не хватило ещё на "
                     f"{unfed} — купить: <code>пет корм 10</code>")
    if waiting:
        lines.append(pet_waiting_line(waiting))
    left_food = await db.get_inventory_quantity(chat_id, user_id,
                                                pets_catalog.FOOD_ITEM_KEY)
    lines.append(f"{pets_catalog.FOOD_ITEM_EMOJI} Корма осталось: {left_food}")
    return ActionResult(True, "\n".join(lines), tuple(announcements))


async def care_all(chat_id: int, user_id: int, verb: str) -> ActionResult:
    """«пет обнять все» — приласкать всех разом."""
    pairs, err = await pets_for_bulk(chat_id, user_id)
    if err:
        return ActionResult.fail(err)
    now = datetime.utcnow()
    aura, _pinned_key = await _bulk_aura(chat_id, user_id, pairs)
    waiting: list[tuple[object, timedelta]] = []
    done: list[tuple[dict, object, tuple[int, int, int]]] = []
    for row, spec in pairs:
        left = pet_care_left(row)
        if left is not None:
            waiting.append((spec, left))
            continue
        done.append((row, spec,
                     await _care_pet(chat_id, user_id, spec, row, verb, now, aura)))
    if not done:
        return ActionResult.fail("😊 Все ваши питомцы уже довольны.\n" + pet_waiting_line(waiting))
    lines = [f"💞 Вы {_care_past(verb)} всех — {len(done)} из {len(pairs)}", _DIVIDER]
    announcements: list[Announcement] = []
    for row, spec, (mood, before, after) in done:
        line = f"{pet_display(row, spec)} — {pets_catalog.bar(mood)} {mood} ({spec.sound})"
        if after > before:
            line += f"\n   ⭐ Новый уровень: {after}!"
            announcements.append(_level_up_announcement(row, spec, after))
        lines.append(line)
    if waiting:
        lines.append(pet_waiting_line(waiting))
    return ActionResult(True, "\n".join(lines), tuple(announcements))


async def _walk_pet(chat_id: int, user_id: int, spec, row: dict, now: datetime,
                    aura: "PetAura") -> tuple[str, int]:
    """Одна прогулка: (что рассказать, сколько монет). Монеты 0 — принесён предмет.

    Питомец тратит немного сытости и получает настроение: гулять ему нравится,
    но нагуливается и аппетит — иначе прогулка была бы бесплатным источником
    монет, не связанным с кормом.

    Уровень здесь не сравнивается до/после, хотя кормёжка и ласка это делают:
    он взят только на масштаб монет, а объявления о новом уровне прогулка не
    показывала и до переезда — перенос сохраняет это, а не добавляет от себя.
    """
    hunger, mood = _pet_now(row, aura.mood, aura.hunger)
    hunger = max(0, hunger - pets_catalog.WALK_HUNGER_COST)
    mood = pets_catalog.gain(mood, pets_catalog.WALK_MOOD_GAIN)
    level = _pet_level(row)
    xp = pets_catalog.xp_add(_pet_xp_now(row), aura.xp_gain(pets_catalog.WALK_XP_BONUS))
    await db.set_pet_stats(chat_id, user_id, spec.key, hunger, mood, xp, now,
                           walk_at=now)
    finds = pets_catalog.walk_finds(spec.key)
    if finds and random.randint(1, 100) <= aura.find_chance(pets_catalog.WALK_ITEM_CHANCE):
        find = random.choice(finds)
        # Товар мог быть не засеян в этом чате — тогда в инвентаре он выглядел
        # бы голым ключом, поэтому засеваем каталог перед выдачей.
        await db.seed_default_shop_items(chat_id)
        await db.add_inventory_item(chat_id, user_id, find.item_key)
        item = await db.get_shop_item(chat_id, find.item_key)
        name = f"{item['emoji']} {html.escape(item['name'])}" if item else find.item_key
        return f"{find.text} — {name}", 0
    coins = aura.walk_coins(pets_catalog.walk_coins(
        level, random.randint(pets_catalog.WALK_COINS_MIN, pets_catalog.WALK_COINS_MAX)))
    await db.add_coins(chat_id, user_id, coins)
    return f"нагулял(а) <b>{coins}</b> i¢", coins


async def walk_pet(chat_id: int, user_id: int,
                   raw: Optional[str] = None) -> ActionResult:
    """«пет гулять {ключ}» — питомец уходит и приносит находку или монеты."""
    spec, row, err = await pick_pet(chat_id, user_id, raw)
    if spec is None:
        return ActionResult.fail(err)
    left = pet_walk_left(row)
    if left is not None:
        return ActionResult.fail(
            f"🚶 {spec.name} уже нагулялся(-ась) — снова через {format_left(left)}.")
    aura = await pet_aura_for(chat_id, user_id)
    hunger, mood = _pet_now(row, aura.mood, aura.hunger)
    if not _pet_is_active(row, hunger, mood, await _pinned_pet_key(chat_id, user_id)):
        return ActionResult.fail(
            f"😔 {spec.name} никуда не пойдёт — сначала покормите и приласкайте.")
    told, _coins = await _walk_pet(chat_id, user_id, spec, row, datetime.utcnow(), aura)
    text = (f"🚶 {pet_display(row, spec)} сходил(а) погулять и {told}.\n"
            f"Следующая прогулка — через {pets_catalog.WALK_COOLDOWN_HOURS} ч.")
    return ActionResult(True, text)


async def walk_all(chat_id: int, user_id: int) -> ActionResult:
    """«пет гулять все» — выгулять всех, кто может идти."""
    pairs, err = await pets_for_bulk(chat_id, user_id)
    if err:
        return ActionResult.fail(err)
    now = datetime.utcnow()
    aura, pinned_key = await _bulk_aura(chat_id, user_id, pairs)
    waiting: list[tuple[object, timedelta]] = []
    lines: list[str] = []
    tired: list[str] = []
    for row, spec in pairs:
        left = pet_walk_left(row)
        if left is not None:
            waiting.append((spec, left))
            continue
        hunger, mood = _pet_now(row, aura.mood, aura.hunger)
        if not _pet_is_active(row, hunger, mood, pinned_key):
            tired.append(spec.name)
            continue
        told, _coins = await _walk_pet(chat_id, user_id, spec, row, now, aura)
        lines.append(f"{pet_display(row, spec)} {told}")
    if not lines:
        parts = ["🚶 Гулять сейчас некому."]
        if tired:
            parts.append(f"😔 Не в настроении: {', '.join(tired)} — покормите и приласкайте.")
        if waiting:
            parts.append(pet_waiting_line(waiting))
        return ActionResult.fail("\n".join(parts))
    out = [f"🚶 <b>Прогулка</b> — {len(lines)} из {len(pairs)}", _DIVIDER] + lines
    if tired:
        out.append(f"😔 Не в настроении: {', '.join(tired)}")
    if waiting:
        out.append(pet_waiting_line(waiting))
    return ActionResult(True, "\n".join(out))


# --- питомцы: заморозка счёта и списание монет -------------------------------
#
# Заморозка и списание — не правило питомцев, а правило экономики чата целиком
# (то же самое проверяют покупка в магазине, ферма, бизнесы...). Бот держит
# свою версию с кэшем списка «+бесконечность» (см. bot.spend_coins) — заводить
# вторую здесь значило бы дать этому кэшу разойтись с базой. Поэтому buy_pet
# и sell_pet принимают проверку АРГУМЕНТОМ: бот передаёт свою is_account_frozen
# и spend_coins (те же функции, что и раньше — их можно подменить в тестах, и
# заморозка в чате не перестаёт проверяться), а вызов без аргумента (сайт,
# прямой вызов модуля) использует версию ниже — она беднее (нет обхода для
# владельца с «+бесконечность», сайту он ни к чему), но честно ходит в ту же
# базу.

async def _default_is_frozen(chat_id: int, user_id: int) -> bool:
    row = await db.get_data(f"frozen:{chat_id}:{user_id}")
    return bool(row and row.get("data_value") == "1")


async def _default_spend(chat_id: int, user_id: int, amount: int) -> bool:
    if amount <= 0:
        return True
    return await db.try_spend_coins(chat_id, user_id, amount)


def _lower_first(text: str) -> str:
    """«Завести всех питомцев» → «завести всех питомцев» — описания коллекций
    (collections_meta) написаны как самостоятельное предложение с большой
    буквы, а сюда они подставляются серединой фразы в скобках."""
    return text[:1].lower() + text[1:] if text else text


def _default_achievement_info(code: str) -> Optional[dict]:
    """Название и описание ачивки «по умолчанию» — без словаря ACHIEVEMENTS,
    которого здесь нет и быть не может (он в bot.py, общий на ВСЕ ачивки бота,
    не только питомцев, — тащить его сюда значило бы тащить сюда bot.py).

    Умеет закрыть только достижения за коллекции (код вида «collection_*»):
    для них название и описание есть и в чистом collections_meta — том же
    модуле, которым уже пользуется _check_collections. У наградных питомцев
    ровно так устроена одна из трёх (единорог — collection_zoo). Для двух
    остальных (за число сообщений, за брак) человекочитаемого текста ВНЕ
    bot.py не существует вовсе, и без явно переданного achievement_info в
    сообщении останется голый код — известная незакрытая дыра, см. отчёт
    задачи 5, находка 3: закрыть её можно, только выделив нужные ачивки (или
    все) в свой чистый модуль по образцу collections_meta, а это отдельная
    работа, не эта.
    """
    key = code.removeprefix("collection_")
    if key == code:
        return None
    collection = collections_meta.BY_KEY.get(key)
    if collection is None:
        return None
    return {"title": collection.name, "desc": _lower_first(collection.description)}


# --- питомцы: покупка, продажа, имя, закреп, списки --------------------------

async def buy_pet(chat_id: int, user_id: int, raw_key: str, *,
                  is_frozen: Optional[Callable[[int, int], Awaitable[bool]]] = None,
                  spend: Optional[Callable[[int, int, int], Awaitable[bool]]] = None,
                  achievement_info: Optional[Callable[[str], Optional[dict]]] = None,
                  on_bought: Optional[Callable[[int, int], Awaitable[None]]] = None
                  ) -> ActionResult:
    """«пет купить {ключ}» — завести питомца.

    is_frozen/spend — см. блок выше про заморозку и списание.

    achievement_info(код) -> {"title", "desc"} — название и описание ачивки
    для наградного питомца. Сам словарь (ACHIEVEMENTS) — тексты ачивок ВООБЩЕ,
    не только питомцев, и живёт в bot.py; тянуть его сюда ради одной строки в
    отказе значило бы тащить сюда часть bot.py. Без аргумента используется
    _default_achievement_info — он честно закрывает ачивки за коллекции
    (полностью, из чистого collections_meta), а для остальных отдаёт None, и
    в сообщении остаётся код ачивки вместо человеческого названия (см. её
    докстринг — это открытая, а не забытая дыра).

    on_bought(chat_id, user_id) — что сделать ПОСЛЕ удачной покупки, кроме неё
    самой: бот проверяет тут собранные коллекции (см. _check_collections), а
    та функция умеет сама написать в чат при завершении коллекции — то самое,
    чего у этого модуля нет и быть не должно. Без аргумента ничего лишнего не
    происходит; коллекции досчитаются при следующем действии, которое их
    проверяет.
    """
    # Корм — товар, а не вид питомца, но наши же подсказки зовут его «корм», и
    # «пет купить корм» напрашивается само. Отвечать «такого питомца нет» на
    # осмысленную просьбу — худшее, что тут можно сделать.
    if raw_key.casefold() in (pets_catalog.FOOD_ITEM_KEY, "корм", "корма", "еда", "еду"):
        return ActionResult.fail(
            f"{pets_catalog.FOOD_ITEM_EMOJI} Корм покупается так: "
            f"<code>пет корм 10</code> ({pets_catalog.FOOD_ITEM_PRICE} i¢ за штуку).")
    spec = await _pet_spec(chat_id, raw_key)
    if spec is None:
        return ActionResult.fail("Такого питомца нет — посмотрите <code>пет каталог</code>.")
    if spec.by_achievement:
        info_fn = achievement_info or _default_achievement_info
        info = info_fn(spec.achievement) or {}
        return ActionResult.fail(
            f"{spec.title} не продаётся — его выдают за ачивку "
            f"«{info.get('title') or spec.achievement}»"
            + (f" ({info['desc']})." if info.get("desc") else "."))
    if await db.get_pet(chat_id, user_id, spec.key):
        return ActionResult.fail(f"{spec.title} у вас уже есть.")
    # Вид могли временно выключить или ограничить численность (панель).
    conf = _pet_settings.get(spec.key) or {}
    if not conf.get("is_active", True):
        return ActionResult.fail(f"{spec.title} сейчас недоступен — заходите позже.")
    limit = conf.get("max_count")
    if limit is not None:
        taken = await db.count_pet_owners(chat_id, spec.key)
        if taken >= int(limit):
            return ActionResult.fail(
                f"{spec.title} разобрали: их в чате всего {limit}, "
                f"и все уже нашли хозяев.")
    frozen = is_frozen or _default_is_frozen
    if await frozen(chat_id, user_id):
        return ActionResult.fail("🧊 Ваш счёт заморожен администрацией.")
    spend_fn = spend or _default_spend
    if not await spend_fn(chat_id, user_id, spec.price):
        wallet = await db.get_wallet(chat_id, user_id)
        return ActionResult.fail(
            f"Недостаточно монет: {spec.name} стоит <b>{spec.price}</b> i¢, "
            f"а у вас {wallet.get('coins', 0)} i¢.")
    # Если этого же питомца уже продавали, счётчик платных смен способности
    # возвращается вместе с ним — продажа не должна работать как дешёвый
    # сброс подорожания (см. db.remember_pet_rerolls).
    rerolls = await db.recall_pet_rerolls(chat_id, user_id, spec.key)
    if not await db.add_pet(chat_id, user_id, spec.key, datetime.utcnow(), rerolls):
        await db.add_coins(chat_id, user_id, spec.price)   # гонка — деньги назад
        return ActionResult.fail("Не удалось завести питомца — попробуйте ещё раз.")
    await db.add_log("pet_buy", chat_id=chat_id, actor_id=user_id,
                     details=f"{spec.key}:{spec.price}")
    if on_bought is not None:
        await on_bought(chat_id, user_id)
    ability = pets_catalog.ability_text(spec.ability)
    lines = [f"🐾 У вас появился {spec.title}!"]
    if ability:
        lines.append(f"✨ {ability} — пока он сыт и доволен.")
    key_shown = html.escape(spec.key)          # ключ вида тоже пишет админ
    lines += [f"Назвать: <code>пет назвать {key_shown} {{имя}}</code>",
              f"Кормить: <code>пет кормить {key_shown}</code> — тратит корм "
              f"(<code>пет корм 10</code>)"]
    if rerolls:
        lines.append(f"✨ Смен способности за вами уже числится {rerolls} — "
                     f"цена следующей это учитывает.")
    return ActionResult(True, "\n".join(lines))


async def sell_pet(chat_id: int, user_id: int, raw_key: Optional[str],
                   confirm: bool = False, *,
                   is_frozen: Optional[Callable[[int, int], Awaitable[bool]]] = None
                   ) -> ActionResult:
    """«пет продать кот» показывает цену, confirm=True («... да») — продаёт.

    Два шага, как у платной смены способности: цену нужно узнать ДО того, как
    питомца не станет, а не после. Уровень и опыт при продаже сгорают — их
    нажили временем, и выкупить обратно нельзя.

    is_frozen — см. buy_pet: та же заморозка, тот же довод для аргумента.
    """
    spec, row, err = await pick_pet(chat_id, user_id, raw_key)
    if spec is None:
        return ActionResult.fail(err)
    if spec.by_achievement:
        return ActionResult.fail(f"{spec.title} не продаётся — это знак отличия, "
                                 f"а не имущество.")
    price = pets_catalog.sell_price(spec.price)
    level = _pet_level(row)
    rerolls = int(row.get("ability_rerolls") or 0)
    if not confirm:
        lines = [f"🐾 {pet_display(row, spec)} — продажа за <b>{price}</b> i¢ "
                f"(половина цены каталога, {spec.price} i¢).",
                f"Сгорят уровень ⭐{level} и весь опыт — обратно их не выкупить."]
        # Купленная способность — обычно самое дорогое, что теряется, а из
        # слов «уровень и опыт» этого не видно. Счётчик смен при этом
        # останется, то есть вернуть её будет стоить как следующую смену.
        if row.get("ability"):
            bought = pets_catalog.ability_text_at_level(row["ability"], level)
            lines.append(f"✨ Купленная способность ({bought}) тоже сгорит, "
                         f"а счётчик смен ({rerolls}) останется — вернуть её "
                         f"будет стоить "
                         f"{pets_catalog.ability_reroll_price(spec.price, rerolls)} i¢.")
        lines.append(
            f"Подтвердить: <code>пет продать {html.escape(spec.key)} да</code>")
        return ActionResult(True, "\n".join(lines))
    frozen = is_frozen or _default_is_frozen
    if await frozen(chat_id, user_id):
        return ActionResult.fail("🧊 Ваш счёт заморожен администрацией.")
    # Счётчик платных смен способности переживает продажу: иначе продать и
    # купить заново было бы дешёвым способом сбросить подорожавшие смены
    # (см. pets.ability_reroll_price).
    if rerolls:
        await db.remember_pet_rerolls(chat_id, user_id, spec.key, rerolls)
    if not await db.delete_pet(chat_id, user_id, spec.key):
        # Гонка: два «пет продать ... да» подряд. Деньги начислять нельзя.
        return ActionResult.fail(f"{spec.title} у вас уже нет.")
    await db.add_coins(chat_id, user_id, price)
    card = await db.get_profile_card(chat_id, user_id)
    if card and card.get("pinned_pet") == spec.key:
        await db.set_pinned_pet(chat_id, user_id, None)
    await db.add_log("pet_sell", chat_id=chat_id, actor_id=user_id,
                     details=f"{spec.key}:{price}")
    return ActionResult(
        True, f"🐾 {pet_display(row, spec)} продан(а) за <b>{price}</b> i¢.\n"
             f"Завести снова: <code>пет купить {html.escape(spec.key)}</code>")


async def rename_pet(chat_id: int, user_id: int, raw_key: str, raw_name: str) -> ActionResult:
    """«пет назвать {ключ} {имя}» — имя обрезается по длине, а не отклоняется."""
    spec = await _pet_spec(chat_id, raw_key)
    if spec is None:
        return ActionResult.fail("Такого питомца нет — посмотрите <code>пет каталог</code>.")
    if not await db.get_pet(chat_id, user_id, spec.key):
        return ActionResult.fail(f"{spec.title} у вас нет.")
    name = raw_name.strip()[:pets_catalog.NAME_MAX]
    await db.rename_pet(chat_id, user_id, spec.key, name)
    return ActionResult(True, f"🐾 Теперь это {spec.title} «{html.escape(name)}».")


async def pin_pet(chat_id: int, user_id: int, raw_key: str) -> ActionResult:
    """«пет закрепить {ключ}» — этот питомец показывается в профиле."""
    spec = await _pet_spec(chat_id, raw_key)
    if spec is None:
        return ActionResult.fail("Такого питомца нет — посмотрите <code>пет каталог</code>.")
    if not await db.get_pet(chat_id, user_id, spec.key):
        return ActionResult.fail(f"{spec.title} вам не принадлежит.")
    await db.set_pinned_pet(chat_id, user_id, spec.key)
    return ActionResult(True, f"📌 {spec.title} закреплён(а) в профиле.")


async def unpin_pet(chat_id: int, user_id: int) -> ActionResult:
    """«пет открепить» — без ключа: закреплён максимум один питомец."""
    await db.set_pinned_pet(chat_id, user_id, None)
    return ActionResult(True, "📌 Питомец больше не показывается в профиле.")


async def buy_food(chat_id: int, user_id: int, raw_qty: Optional[str]) -> ActionResult:
    """«пет корм [N]» — короткий путь к тому же товару, что «купить korm».

    Возвращает ActionResult ВСЕГДА — как и любое другое действие модуля.
    Раньше при заданном количестве отдавался None («покупку посчитает
    вызывающий сам»), и это был единственный неоднородный контракт среди
    публичных действий: обобщённый вызывающий (панель) не мог отличить
    «закономерный отказ» от «здесь этой ветки просто нет», и падал на
    result.ok с AttributeError.

    Без количества — показать цену и остаток, ActionResult(True, ...).

    С количеством — честный отказ, а не попытка посчитать покупку: она
    идёт через общий магазинный путь (см. bot._shop_buy, которым же покупают
    и «купить korm 10») — распродажа события, скидка «Торгаша» и остаток на
    полке общие для обоих способов купить корм, и второй раз считать их
    здесь значило бы завести именно ту вторую правду, ради которой этот
    модуль вообще заводился. bot.cmd_pet_food_buy вызывает эту функцию ради
    побочного эффекта (досев товара) и ветки без числа, а для покупки с
    числом полагается не на её ответ, а на _shop_buy напрямую.
    """
    # Корм мог ещё не доехать в магазин этого чата: витрину с момента
    # обновления бота могли ни разу не открыть, а купить его уже нужно.
    await db.seed_extra_shop_items(chat_id, pets_catalog.SHOP_ITEMS)
    if raw_qty is not None:
        return ActionResult.fail(
            f"{pets_catalog.FOOD_ITEM_EMOJI} Купить корм сразу нужным "
            f"количеством пока можно только командой боту в чате — "
            f"<code>пет корм 10</code>.")
    have = await db.get_inventory_quantity(chat_id, user_id, pets_catalog.FOOD_ITEM_KEY)
    return ActionResult(True, (
        f"{pets_catalog.FOOD_ITEM_EMOJI} <b>Корм</b> — "
        f"{pets_catalog.FOOD_ITEM_PRICE} i¢ за штуку.\n"
        f"У вас: {have} шт. Одно кормление — один корм.\n"
        f"Купить: <code>пет корм 10</code>"))


async def my_pets_text(chat_id: int, user_id: int, own: bool) -> ActionResult:
    """«пет» / «петы» — список питомцев: своих (own=True, с подсказками
    команд) или чужих (own=False, только состояние)."""
    rows = await db.list_pets(chat_id, user_id)
    if not rows:
        text = ("🐾 <b>Питомцы</b>\n\nПока ни одного.\n"
                "Каталог — <code>пет каталог</code>, купить — "
                "<code>пет купить {ключ}</code>." if own
                else "🐾 У этого человека пока нет питомцев.")
        return ActionResult(True, text)
    specs = await _pet_specs(chat_id)
    pinned_key = await _pinned_pet_key(chat_id, user_id)
    aura = _pet_aura(rows, specs, pinned_key)
    lines = [f"🐾 <b>Питомцы</b> — {len(rows)}", _DIVIDER]
    for row in rows:
        spec = specs.get(row["pet_key"])
        hunger, mood = _pet_now(row, aura.mood, aura.hunger)
        xp = _pet_xp_now(row)
        level, gained, needed = pets_catalog.level_progress(xp)
        level_label = ("MAX" if level >= pets_catalog.MAX_PET_LEVEL
                       else f"{level}/{pets_catalog.MAX_PET_LEVEL}")
        line = (f"{pet_display(row, spec)} (<code>{html.escape(row['pet_key'])}</code>) "
                f"— ⭐ ур. {level_label}\n"
                f"   🍽 {pets_catalog.bar(hunger)} {hunger}   "
                f"😊 {pets_catalog.bar(mood)} {mood}   {pets_catalog.state_text(hunger, mood)}")
        if level < pets_catalog.MAX_PET_LEVEL:
            progress = round(100 * gained / needed) if needed else 100
            line += f"\n   📈 {pets_catalog.bar(progress)} {gained}/{needed} опыта"
        # Способности и то, работают ли они сейчас: иначе непонятно, зачем
        # вообще кормить. Процент — уже с прибавкой за уровень, а у
        # эволюционировавшего ещё и с удвоенной базой. Способностей может быть
        # две — вторая появляется как раз с эволюцией.
        evolved = bool(row.get("evolved"))
        works = "✅" if _pet_is_active(row, hunger, mood, pinned_key) else "💤 спит"
        for ability_key in (_effective_abilities(row, spec) if spec else ()):
            found = pets_catalog.ABILITY_BY_KEY.get(ability_key)
            if found is None:
                continue
            percent = pets_catalog.ability_percent(ability_key, level, evolved)
            line += f"\n   ✨ {found.description.format(p=percent)} — {works}"
        if evolved:
            line += "\n   🌟 Эволюционировал(а)"
        lines.append(line)
    if own:
        food = await db.get_inventory_quantity(chat_id, user_id, pets_catalog.FOOD_ITEM_KEY)
        lines += ["", f"{pets_catalog.FOOD_ITEM_EMOJI} Корма у вас: {food} "
                      f"(одно кормление — один корм, "
                      f"<code>пет корм 10</code>)",
                  "<code>пет кормить {ключ}</code> · "
                  "<code>пет гладить {ключ}</code> · "
                  "<code>пет обнять {ключ}</code> · "
                  "<code>пет поцеловать {ключ}</code>",
                  "<code>пет гулять {ключ}</code> — питомец принесёт находку "
                  f"(раз в {pets_catalog.WALK_COOLDOWN_HOURS} ч)",
                  "<code>пет кормить все</code> · <code>пет обнять все</code> · "
                  "<code>пет гулять все</code> — сразу всем",
                  "<code>пет назвать {ключ} {имя}</code> · "
                  "<code>пет закрепить {ключ}</code>",
                  "<code>пет продать {ключ}</code> — вернуть половину цены",
                  "<code>пет способность {ключ} {номер}</code> — сменить "
                  "способность за i¢, список номеров: <code>пет способности</code>",
                  "⭐ Уровень растёт сам по себе со временем, кормёжка и "
                  "ласка ускоряют."]
    return ActionResult(True, "\n".join(lines))


async def my_pets_list(chat_id: int, user_id: int) -> list[dict]:
    """Питомцы хозяина данными, а не текстом: ключ, название вида, эмодзи.

    Нужен кабинету на сайте: кнопку «покормить» там надо нарисовать на
    каждого питомца, и ключ для неё должен прийти отдельным полем. Достать
    его разбором готового текста списка можно, но такой разбор ломается от
    любой правки формулировки — молча и не у всех.

    Название и эмодзи отдаются В ИСХОДНОМ виде: в каталоге они уже
    экранированы для HTML (см. _pet_specs), а отсюда значение уходит в JSON,
    где экранирует его уже сама страница, — второе экранирование показало бы
    человеку «&lt;» вместо букв.
    """
    pairs, _err = await pets_for_bulk(chat_id, user_id)
    return [{"key": row["pet_key"],
             "name": html.unescape(spec.name),
             "emoji": html.unescape(spec.emoji)}
            for row, spec in pairs]


async def my_pets_cards(chat_id: int, user_id: int) -> dict:
    """Питомцы ДАННЫМИ: уровень, сытость, настроение, опыт, способности.

    Зачем отдельно от my_pets_text. Тот собирает готовую строку для чата — с
    полосками из ▰▱ и эмодзи, — и на сайте она читается как стена текста.
    Разбирать её обратно нельзя (см. my_pets_list: разбор ломается от любой
    правки формулировки, молча и не у всех), поэтому те же числа отдаются
    отдельно, а рисует их уже экран.

    Числа считаются ЗДЕСЬ же, теми же функциями, что и текст: сытость с
    настроением падают лениво (_pet_now), опыт растёт лениво (_pet_xp_now), и
    посчитай их страница сама — она разойдётся с чатом ровно на время между
    двумя обращениями.
    """
    rows = await db.list_pets(chat_id, user_id)
    if not rows:
        return {"pets": [], "food": 0, "food_emoji": pets_catalog.FOOD_ITEM_EMOJI}

    specs = await _pet_specs(chat_id)
    pinned_key = await _pinned_pet_key(chat_id, user_id)
    aura = _pet_aura(rows, specs, pinned_key)

    карточки = []
    for row in rows:
        spec = specs.get(row["pet_key"])
        hunger, mood = _pet_now(row, aura.mood, aura.hunger)
        xp = _pet_xp_now(row)
        level, gained, needed = pets_catalog.level_progress(xp)
        evolved = bool(row.get("evolved"))
        активен = _pet_is_active(row, hunger, mood, pinned_key)

        способности = []
        for ability_key in (_effective_abilities(row, spec) if spec else ()):
            found = pets_catalog.ABILITY_BY_KEY.get(ability_key)
            if found is None:
                continue
            percent = pets_catalog.ability_percent(ability_key, level, evolved)
            способности.append({
                "key": ability_key,
                "text": html.unescape(found.description.format(p=percent)),
                "percent": percent,
                "works": активен,
            })

        карточки.append({
            "key": row["pet_key"],
            # Имя и эмодзи В ИСХОДНОМ виде: в каталоге они уже экранированы
            # для HTML, а отсюда уходят в JSON, где экранирует уже страница.
            "name": html.unescape(row.get("name") or (spec.name if spec else row["pet_key"])),
            "species": html.unescape(spec.name) if spec else "",
            "emoji": html.unescape(spec.emoji) if spec else "🐾",
            "level": level,
            "max_level": pets_catalog.MAX_PET_LEVEL,
            "is_max": level >= pets_catalog.MAX_PET_LEVEL,
            "hunger": hunger,
            "mood": mood,
            "state": pets_catalog.state_text(hunger, mood),
            "xp": gained,
            "xp_need": needed,
            "xp_percent": (round(100 * gained / needed) if needed else 100),
            "abilities": способности,
            "evolved": evolved,
            "pinned": row["pet_key"] == pinned_key,
            "active": активен,
        })

    return {
        "pets": карточки,
        "food": await db.get_inventory_quantity(chat_id, user_id,
                                                pets_catalog.FOOD_ITEM_KEY),
        "food_emoji": pets_catalog.FOOD_ITEM_EMOJI,
        "food_price": pets_catalog.FOOD_ITEM_PRICE,
    }


async def catalog_text(chat_id: int, user_id: int, *,
                       achievement_info: Optional[Callable[[str], Optional[dict]]] = None
                       ) -> ActionResult:
    """«пет каталог» — витрина видов чата: цена, уже есть или выдаётся за ачивку.

    achievement_info — см. buy_pet: тот же довод для аргумента вместо словаря.
    """
    owned = {r["pet_key"] for r in await db.list_pets(chat_id, user_id)}
    specs = await _pet_specs(chat_id)
    lines = ["🐾 <b>Питомцы</b> — кого можно завести", _DIVIDER]
    for spec in sorted(specs.values(), key=lambda s: s.price):
        if spec.key in owned:
            mark = " ✅ уже есть"
        elif getattr(spec, "achievement", ""):
            info_fn = achievement_info or _default_achievement_info
            info = info_fn(spec.achievement) or {}
            mark = f" 🏅 за ачивку «{info.get('title') or spec.achievement}»"
        else:
            mark = f" — {spec.price} i¢"
        lines.append(f"{spec.title} (<code>{html.escape(spec.key)}</code>){mark}")
        text = pets_catalog.ability_text(spec.ability)
        if text:
            lines.append(f"   ✨ {text}")
    lines += [
        "",
        f"Сытость падает на {pets_catalog.HUNGER_PER_HOUR} в час, "
        f"настроение — на {pets_catalog.MOOD_PER_HOUR}. Кормите и гладьте.",
        f"{pets_catalog.FOOD_ITEM_EMOJI} Кормление тратит корм — "
        f"{pets_catalog.FOOD_ITEM_PRICE} i¢ за штуку "
        f"(<code>пет корм 10</code>). Ласка бесплатна.",
        "Купить: <code>пет купить {ключ}</code>, "
        "продать обратно за половину: <code>пет продать {ключ}</code>",
    ]
    return ActionResult(True, "\n".join(lines))
