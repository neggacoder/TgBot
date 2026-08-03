"""Огород и хлев: сделать и вернуть результат. Ничего не отправляет.

Зачем модуль. Панель — отдельный процесс и bot.py импортировать не может (это
подняло бы второго бота), а правила посадки, сбора и покупки грядок жили
именно там, вперемешку с текстами ответов в Telegram. Значит, либо сайт
повторяет правила у себя — и появляется вторая правда о ценах, сроках и
вредителях, — либо действия переезжают сюда. Переехали. Тот же приём, что у
game_actions.py для питомцев, и по той же причине.

Здесь НЕТ бота и НЕТ отправки сообщений. Что показать человеку — решает
вызывающий: бот пишет строку в чат, сайт рисует грядку. Объявления (ачивки)
возвращаются отдельным списком: их положено показать в чате, даже если кнопку
нажали на сайте.

Чего здесь тоже нет — своих чисел. Сколько растёт и сколько даёт, лежит в
farming.py и livestock.py; сколько стоит грядка — там же. Этот модуль только
соединяет их с базой.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Awaitable, Callable, Optional

import db
import farming
import game_actions
import livestock
import shop_effects

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Общие помощники: их зовут обе стороны, поэтому живут они здесь, а не в bot.py
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class FarmAura:
    """Что питомцы дают огороду — одной структурой, а не тремя вызовами."""
    harvest: int = 0    # + к урожаю при сборе
    speed: int = 0      # + к скорости роста при посадке
    truffle: int = 0    # шанс трюфеля в процентах


FARM_PET_HARVEST_ABILITY = "side_job"    # 🐝 пчела — больше урожая
FARM_PET_SPEED_ABILITY = "work"          # 🐜 муравей — быстрее растёт
FARM_PET_TRUFFLE_ABILITY = "treasure"    # 🐷 свинка — шанс на трюфель


async def item_perk(chat_id: int, user_id: int, perk: str) -> int:
    """Сила постоянной привилегии от предметов (см. shop_effects.PERK_*).

    Для привилегий-переключателей возвращает 1 или 0 — вызывающему удобнее один
    вид проверки на все случаи. Ошибку глотаем: привилегия — надстройка над
    механикой, и непрочитавшийся инвентарь не должен ронять саму посадку."""
    try:
        keys = [i["item_key"] for i in await db.list_inventory(chat_id, user_id)]
    except Exception as exc:
        logger.warning("item_perk: %s", exc)
        return 0
    if perk in shop_effects.FLAG_PERKS:
        return 1 if shop_effects.has_perk(keys, perk) else 0
    return shop_effects.perk_percent(keys, perk)


async def aura(chat_id: int, user_id: int) -> FarmAura:
    """Способности питомцев, влияющие на огород, за ОДНУ выборку питомцев.

    Через отдельный запрос на способность это был бы тройной поход в базу на
    каждый показ грядок. Ошибку глотаем: питомец на грядке — приятная добавка,
    и упавший запрос не должен ломать посадку."""
    try:
        rows = await db.list_pets(chat_id, user_id)
        if not rows:
            return FarmAura()
        specs = await game_actions._pet_specs(chat_id)
        pinned_key = await game_actions._pinned_pet_key(chat_id, user_id)
    except Exception as exc:
        logger.warning("aura: %s", exc)
        return FarmAura()
    pet_aura = game_actions._pet_aura(rows, specs, pinned_key)
    percent = game_actions._pet_ability_sums(rows, specs, pinned_key, pet_aura, (
        FARM_PET_HARVEST_ABILITY, FARM_PET_SPEED_ABILITY, FARM_PET_TRUFFLE_ABILITY))
    return FarmAura(
        harvest=percent[FARM_PET_HARVEST_ABILITY],
        speed=percent[FARM_PET_SPEED_ABILITY],
        truffle=percent[FARM_PET_TRUFFLE_ABILITY],
    )


def weather_for(chat_id: int, today: date) -> farming.Weather:
    """Погода чата на день. Не хранится — выводится из даты."""
    return farming.weather_for(chat_id, today)


# ----------------------------------------------------------------------------
# Звёздность и заморозка счёта. Живут здесь по той же причине, что и остальное:
# от звёздности зависит число грядок, а заморозка обязана закрывать ферму и на
# сайте тоже, — но обе нужны и чату, и панели, а bot.py панель не импортирует.
# ----------------------------------------------------------------------------
FARM_STAR_CAP = 10
# Было 20 фармов на звезду. При кулдауне в 4 часа это 3,3 суток игры без
# единого пропуска ради одной звезды и месяц с лишним ради максимума — рост
# формально работал, но за ним невозможно было уследить, и звёздности никто
# не видел. Пять фармов — первая звезда за сутки, максимум примерно за неделю.
FARM_FARMS_PER_STAR = 5


def farm_star_progress(total_farms: int) -> tuple[int, int, int]:
    """(звёзд сейчас, фармов в текущей звезде, сколько нужно на следующую).

    На максимуме «набрано» и «нужно» равны — полоса просто полная, а не
    делится на ноль (так же сделано у уровня питомца, см. pets.level_progress).
    """
    total = max(0, int(total_farms))
    stars = min(FARM_STAR_CAP, total // FARM_FARMS_PER_STAR)
    if stars >= FARM_STAR_CAP:
        return stars, FARM_FARMS_PER_STAR, FARM_FARMS_PER_STAR
    return stars, total % FARM_FARMS_PER_STAR, FARM_FARMS_PER_STAR


def wallet_stars(wallet: dict) -> int:
    """Звёздность кошелька — ВСЕГДА из числа фармов, а не из столбца.

    star_level в базе пересчитывается только внутри record_farm, то есть при
    фарме. После правки FARM_FARMS_PER_STAR столбец отстаёт до следующего
    фарма, и кошелёк показывал бы больше звёзд, чем на самом деле даёт бонус
    к доходу и урону по боссу. Столбец остаётся кэшем для сортировок, а
    источник правды — total_farms.
    """
    return farm_star_progress(int(wallet.get("total_farms") or 0))[0]


def events_state_key(chat_id: int) -> str:
    return f"chat_event:{chat_id}"


async def active_event(chat_id: int) -> Optional[dict]:
    """Активное событие чата или None. Истёкшие подчищает на месте, поэтому
    вызывающему коду не нужно самому сверяться с часами.

    Ферме это нужно ради тыквы: она растёт только во время ивента, и сайт
    обязан запирать её ровно тогда же, когда чат."""
    row = await db.get_data(events_state_key(chat_id))
    if not row:
        return None
    try:
        state = json.loads(row["data_value"])
    except (ValueError, TypeError):
        await db.delete_data(events_state_key(chat_id))
        return None
    until = state.get("until")
    if until:
        try:
            if datetime.utcnow() >= datetime.fromisoformat(until):
                return None
        except ValueError:
            return None
    return state


def frozen_key(chat_id: int, user_id: int) -> str:
    return f"frozen:{chat_id}:{user_id}"


async def is_account_frozen(chat_id: int, user_id: int) -> bool:
    row = await db.get_data(frozen_key(chat_id, user_id))
    return bool(row and row.get("data_value") == "1")


def plots_key(chat_id: int, user_id: int) -> str:
    return f"farm_plots:{chat_id}:{user_id}"


def counter_key(chat_id: int, user_id: int, what: str) -> str:
    return f"farm_count_{what}:{chat_id}:{user_id}"


async def bought_plots(chat_id: int, user_id: int) -> int:
    """Сколько грядок человек докупил за монеты. Живёт в общем key-value:
    одно число на человека — не повод заводить таблицу."""
    row = await db.get_data(plots_key(chat_id, user_id))
    try:
        return max(0, int((row or {}).get("data_value") or 0))
    except (TypeError, ValueError):
        return 0


async def set_bought_plots(chat_id: int, user_id: int, value: int) -> None:
    await db.set_data(plots_key(chat_id, user_id), str(max(0, int(value))),
                      updated_by=user_id)


async def bump_counter(chat_id: int, user_id: int, what: str, by: int = 1) -> int:
    """Счётчик посадок/сборов под ачивки. Считаем ГРЯДКИ, а не команды: «посадил
    сто раз по одной» и «десять раз по десять» — одинаковый труд, и различать
    их значило бы награждать за дробление команд."""
    key = counter_key(chat_id, user_id, what)
    row = await db.get_data(key)
    try:
        было = int((row or {}).get("data_value") or 0)
    except (TypeError, ValueError):
        было = 0
    стало = было + max(0, int(by))
    await db.set_data(key, str(стало), updated_by=user_id)
    return стало


async def plot_count(chat_id: int, user_id: int, stars: int) -> int:
    """Сколько у человека грядок всего: звёздность + купленное + предметы."""
    return (await plot_sources(chat_id, user_id, stars))["total"]


async def plot_sources(chat_id: int, user_id: int, stars: int) -> dict:
    """Откуда взялась каждая грядка. Разбивка нужна не для красоты: упершись в
    потолок, человек обязан видеть, какой источник ещё не выбран."""
    bought = await bought_plots(chat_id, user_id)
    items = await item_perk(chat_id, user_id, shop_effects.PERK_FARM_PLOTS)
    return {
        "stars": stars,
        "from_stars": farming.plots_from_stars(stars),
        "bought": bought,
        "items": items,
        "total": farming.plots_for(stars, bought, items),
    }


# ----------------------------------------------------------------------------
# Состояние фермы одним куском: ровно то, что рисует экран
# ----------------------------------------------------------------------------
async def state(chat_id: int, user_id: int, *, stars: int, coins: int,
                event_active: bool = False,
                now: Optional[datetime] = None,
                today: Optional[date] = None) -> dict:
    """Грядки, хлев, погода и цены — за один заход в базу на каждую часть.

    Сроки отдаём абсолютным временем в UTC, а не остатком в секундах: экран
    обновляет таймеры сам, и «осталось 120 секунд» протухло бы ровно в тот
    момент, когда человек отвлёкся на другую вкладку.
    """
    now = now or datetime.utcnow()
    today = today or now.date()
    погода = weather_for(chat_id, today)
    способности = await aura(chat_id, user_id)
    защита = bool(await item_perk(chat_id, user_id, shop_effects.PERK_FARM_NO_PESTS))
    источники = await plot_sources(chat_id, user_id, stars)
    всего = int(источники["total"])

    rows = await db.list_farm_plots(chat_id, user_id)
    занятые: dict[int, dict] = {}
    for row in rows:
        crop = farming.BY_KEY.get(row["crop_key"])
        if crop is None:
            continue
        ready = row["ready_at"]
        planted = row["planted_at"]
        всего_сек = max(1, int((ready - planted).total_seconds()))
        прошло = max(0, int((now - planted).total_seconds()))
        занятые[int(row["slot"])] = {
            "slot": int(row["slot"]),
            "crop": crop.key,
            "name": crop.name,
            "emoji": crop.emoji,
            "planted_at": planted.isoformat(),
            "ready_at": ready.isoformat(),
            "ready": farming.is_ready(now, ready),
            "progress": min(100, round(прошло * 100 / всего_сек)),
            "perish_at": (farming.perish_at(crop, ready).isoformat()
                          if crop.perishable else None),
            "perished": farming.is_perished(crop, ready, now),
            "pests": farming.pests_visible(row.get("pest_at"), now),
            "pest_loss": farming.pest_loss_percent(row.get("pest_at"), now),
        }

    plots = [занятые.get(slot, {"slot": slot, "crop": None}) for slot in range(всего)]

    catalog = []
    for crop in farming.CROPS:
        seconds = farming.grow_seconds(crop, погода, способности.speed)
        catalog.append({
            "key": crop.key, "name": crop.name, "emoji": crop.emoji,
            "price": crop.seed_price, "grow_seconds": seconds,
            "yield_min": crop.yield_min, "yield_max": crop.yield_max,
            "item_name": crop.item_name, "hint": crop.hint,
            "perish_hours": crop.perish_hours,
            "locked": crop.event_only and not event_active,
            "affordable": coins // crop.seed_price if crop.seed_price else 0,
        })

    barn = []
    животные = {r["animal_key"]: r for r in await db.list_farm_animals(chat_id, user_id)}
    for animal in livestock.ANIMALS:
        row = животные.get(animal.key)
        голов = int((row or {}).get("quantity") or 0)
        готово = livestock.produced(animal, (row or {}).get("last_collect_at"),
                                    now, голов) if голов else 0
        следующая = (livestock.next_unit_in(animal, row.get("last_collect_at"), now, голов)
                     if голов and row else None)
        barn.append({
            "key": animal.key, "name": animal.name, "emoji": animal.emoji,
            "price": animal.price, "sell_back": livestock.sell_back(animal),
            "item_name": animal.item_name, "item_emoji": animal.item_emoji,
            "quantity": голов, "max": livestock.MAX_PER_KIND,
            "ready": готово, "cap": livestock.total_cap(animal, голов) if голов else 0,
            "next_at": ((now + следующая).isoformat() if следующая else None),
            "per_day": round(animal.per_day * голов, 1) if голов else animal.per_day,
        })

    куплено = int(источники["bought"])
    место = max(0, min(farming.PLOTS_BUY_MAX - куплено, farming.PLOTS_MAX - всего))
    return {
        "now": now.isoformat(),
        "coins": coins,
        # key нужен сайту: сцена неба рисуется CSS-ом по виду погоды, а не
        # по эмодзи (панель эмодзи не показывает).
        "weather": {"key": погода.key, "emoji": погода.emoji, "name": погода.name,
                    "yield_percent": погода.yield_percent,
                    "grow_percent": погода.grow_percent,
                    "pest_percent": погода.pest_percent},
        "plots": plots,
        "plot_total": всего,
        "plot_free": всего - len(занятые),
        "plot_sources": источники,
        "plot_next_price": farming.plot_price(куплено) if место else None,
        "plot_room": место,
        "crops": catalog,
        "barn": barn,
        "aura": {"harvest": способности.harvest, "speed": способности.speed,
                 "truffle": способности.truffle},
        "pests_off": защита,
    }


# ----------------------------------------------------------------------------
# Результаты действий
# ----------------------------------------------------------------------------
@dataclass
class FarmResult:
    """Что произошло. ok=False — действие не состоялось, и `error` объясняет
    почему словами, которые можно показать человеку как есть."""
    ok: bool
    error: str = ""
    # Чьё действие. Заполняет вызывающий: самому модулю это не нужно, а вот
    # объявлению в чат — нужно, и таскать user_id отдельным параметром рядом с
    # результатом значит однажды передать чужой.
    user_id: int = 0
    planted: int = 0
    harvested: int = 0
    coins_spent: int = 0
    coins_gained: int = 0
    items: dict[str, int] = field(default_factory=dict)   # ключ предмета → сколько
    perished: int = 0        # сколько грядок сгнило (собрали слишком поздно)
    pest_loss: int = 0       # худшая потеря от саранчи, в процентах
    truffles: int = 0        # трюфели свинки
    ready_at: Optional[datetime] = None
    announcements: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)


SpendFn = Callable[[int, int, int], Awaitable[bool]]


async def _default_spend(chat_id: int, user_id: int, amount: int) -> bool:
    return await db.try_spend_coins(chat_id, user_id, amount)


# ----------------------------------------------------------------------------
# Посадка
# ----------------------------------------------------------------------------
async def plant(chat_id: int, user_id: int, crop_key: str, count, *,
                stars: int, coins: int = 0, event_active: bool = False,
                slot: Optional[int] = None,
                spend: Optional[SpendFn] = None,
                now: Optional[datetime] = None,
                today: Optional[date] = None) -> FarmResult:
    """Занять свободные грядки культурой.

    Деньги списываются ДО вставки, а за не занятые грядки возвращаются: между
    проверкой «свободно» и вставкой помещается вторая команда, и посеять на
    занятую грядку нельзя (INSERT IGNORE), — значит, за неё надо вернуть.
    """
    spend = spend or _default_spend
    now = now or datetime.utcnow()
    today = today or now.date()

    crop = farming.resolve(crop_key)
    if crop is None:
        return FarmResult(False, "Не знаю такой культуры.")
    if crop.event_only and not event_active:
        return FarmResult(
            False, f"{crop.emoji} {crop.name} растёт только во время ивента в чате.")

    rows = await db.list_farm_plots(chat_id, user_id)
    total = (await plot_sources(chat_id, user_id, stars))["total"]
    занятые = {r["slot"] for r in rows}
    свободные = [slot for slot in range(total) if slot not in занятые]
    if not свободные:
        return FarmResult(False, f"Все {total} грядок заняты — сначала соберите урожай.")
    # Нажали на конкретную грядку — сажаем в неё, а не в первую попавшуюся:
    # на экране растение всходит там, куда попал палец. В чате слота нет, и
    # порядок остаётся прежним — с младшей свободной.
    if slot is not None and slot in свободные:
        свободные = [slot] + [s for s in свободные if s != slot]

    # «все» — сколько влезет и на сколько хватит монет. Слово, а не число,
    # потому что так же это работает в чате («ферма посадить картошка все»), и
    # два разных языка у одной команды человек воспринимает как поломку.
    if isinstance(count, str):
        по_деньгам = coins // crop.seed_price if crop.seed_price else len(свободные)
        want = min(len(свободные), max(0, по_деньгам))
        if want < 1:
            return FarmResult(
                False, f"На семена не хватает: {crop.name.lower()} стоит {crop.seed_price} i¢.")
    else:
        want = max(0, min(int(count or 1), len(свободные)))
    if want < 1:
        return FarmResult(False, "Сажать по нулю грядок — это не садоводство.")

    cost = crop.seed_price * want
    if not await spend(chat_id, user_id, cost):
        return FarmResult(False, f"Не хватает монет: семена стоят {cost} i¢.")

    погода = weather_for(chat_id, today)
    способности = await aura(chat_id, user_id)
    защита = bool(await item_perk(chat_id, user_id, shop_effects.PERK_FARM_NO_PESTS))
    шанс = farming.pest_chance(погода, защита)
    ready = farming.ready_at(crop, now, погода, способности.speed)

    посажено = 0
    for slot in свободные[:want]:
        pest_at = None
        if шанс and random.randint(1, 100) <= шанс:
            pest_at = farming.pest_moment(now, ready, random.random())
        if await db.plant_farm_crop(chat_id, user_id, slot, crop.key, now, ready, pest_at):
            посажено += 1

    if not посажено:
        await db.add_coins(chat_id, user_id, cost)
        return FarmResult(False, "Грядки уже заняты — семена не тронуты.")
    if посажено < want:
        await db.add_coins(chat_id, user_id, crop.seed_price * (want - посажено))

    итог = FarmResult(True, planted=посажено, coins_spent=crop.seed_price * посажено,
                      ready_at=ready)
    if await bump_counter(chat_id, user_id, "plant", посажено) >= 100:
        итог.achievements.append("farm_plant_100")
    return итог


# ----------------------------------------------------------------------------
# Сбор
# ----------------------------------------------------------------------------
async def harvest(chat_id: int, user_id: int, *,
                  now: Optional[datetime] = None,
                  today: Optional[date] = None) -> FarmResult:
    """Забрать всё поспевшее разом. Сгнившие грядки просто освобождаются."""
    now = now or datetime.utcnow()
    today = today or now.date()

    rows = await db.list_farm_plots(chat_id, user_id)
    спелые = [r for r in rows
              if farming.BY_KEY.get(r["crop_key"]) and farming.is_ready(now, r["ready_at"])]
    if not спелые:
        return FarmResult(False, "Пока нечего собирать — ничего не поспело.")

    погода = weather_for(chat_id, today)
    способности = await aura(chat_id, user_id)
    await db.seed_extra_shop_items(chat_id, farming.SHOP_ITEMS, is_active=False)
    итог = FarmResult(True)
    трюфели = 0

    for row in спелые:
        crop = farming.BY_KEY[row["crop_key"]]
        await db.clear_farm_plot(chat_id, user_id, row["slot"])
        if farming.is_perished(crop, row["ready_at"], now):
            итог.perished += 1             # сгнила: грядка освободилась, урожая нет
            continue
        loss = farming.pest_loss_percent(row.get("pest_at"), now)
        сколько = farming.harvest_units(
            crop, random.randint(crop.yield_min, crop.yield_max),
            погода, способности.harvest, loss)
        итог.pest_loss = max(итог.pest_loss, loss)
        if сколько > 0:
            await db.add_inventory_item(chat_id, user_id, crop.item_key, сколько)
            итог.items[crop.item_key] = итог.items.get(crop.item_key, 0) + сколько
            итог.harvested += сколько
        if способности.truffle and farming.truffle_found(
                способности.truffle, random.randint(1, 100)):
            трюфели += 1

    if трюфели:
        итог.coins_gained = farming.TRUFFLE_COINS * трюфели
        await db.add_coins(chat_id, user_id, итог.coins_gained)
        итог.truffles = трюфели
    if await bump_counter(chat_id, user_id, "harvest", len(спелые)) >= 100:
        итог.achievements.append("farm_harvest_100")
    return итог


# ----------------------------------------------------------------------------
# Покупка грядок
# ----------------------------------------------------------------------------
async def buy_plots(chat_id: int, user_id: int, count, *, stars: int,
                    coins: int, spend: Optional[SpendFn] = None) -> FarmResult:
    """Докупить грядки. count — число или «все» (сколько хватит монет)."""
    spend = spend or _default_spend
    источники = await plot_sources(chat_id, user_id, stars)
    куплено = int(источники["bought"])
    место = min(farming.PLOTS_BUY_MAX - куплено,
                farming.PLOTS_MAX - int(источники["total"]))
    if место <= 0:
        return FarmResult(False, "Больше грядок купить нельзя — достигнут потолок.")

    if isinstance(count, str):
        сколько = farming.plots_affordable(куплено, coins, место)
        if сколько <= 0:
            return FarmResult(
                False, f"На грядку нужно {farming.plot_price(куплено)} i¢, а у вас {coins} i¢.")
    else:
        сколько = max(0, int(count or 1))
        if сколько < 1:
            return FarmResult(False, "Грядок должно быть больше нуля.")
        if сколько > место:
            return FarmResult(False, f"Столько не влезет — можно ещё {место}.")

    цена = farming.plots_total_price(куплено, сколько)
    if not await spend(chat_id, user_id, цена):
        return FarmResult(False, f"Не хватает монет: {сколько} грядок стоят {цена} i¢.")
    await set_bought_plots(chat_id, user_id, куплено + сколько)
    return FarmResult(True, planted=0, coins_spent=цена,
                      announcements=[f"грядок стало {источники['total'] + сколько}"])


# ----------------------------------------------------------------------------
# Хлев
# ----------------------------------------------------------------------------
async def collect_barn(chat_id: int, user_id: int, *,
                       now: Optional[datetime] = None) -> FarmResult:
    """Забрать накопившийся продукт со всего поголовья."""
    now = now or datetime.utcnow()
    rows = await db.list_farm_animals(chat_id, user_id)
    if not rows:
        return FarmResult(False, "Хлев пуст.")

    await db.seed_extra_shop_items(chat_id, livestock.SHOP_ITEMS, is_active=False)
    итог = FarmResult(True)
    собрано: list[str] = []
    for row in rows:
        animal = livestock.BY_KEY.get(row["animal_key"])
        if animal is None:
            continue
        голов = int(row.get("quantity") or 1)
        units = livestock.produced(animal, row["last_collect_at"], now, голов)
        if units <= 0:
            continue
        await db.add_inventory_item(chat_id, user_id, animal.item_key, units)
        итог.items[animal.item_key] = итог.items.get(animal.item_key, 0) + units
        итог.harvested += units
        собрано.append(animal.key)
    await db.touch_farm_animals(chat_id, user_id, собрано, now)
    if not собрано:
        return FarmResult(False, "Продукт ещё копится — забирать нечего.")
    return итог


async def barn_buy(chat_id: int, user_id: int, animal_key: str, count, *,
                   coins: int, spend: Optional[SpendFn] = None,
                   now: Optional[datetime] = None) -> FarmResult:
    """Купить голов скота. count — число или «все» (сколько хватит монет)."""
    spend = spend or _default_spend
    now = now or datetime.utcnow()
    animal = livestock.BY_WORD.get((animal_key or "").strip().casefold())
    if animal is None:
        return FarmResult(False, "Такого в хлев не берут.")

    есть = await db.get_farm_animal_quantity(chat_id, user_id, animal.key)
    место = livestock.MAX_PER_KIND - есть
    if место <= 0:
        return FarmResult(
            False, f"{animal.name} уже {есть} — больше {livestock.MAX_PER_KIND} не держат.")

    if isinstance(count, str):
        сколько = min(место, coins // animal.price)
        if сколько <= 0:
            return FarmResult(False, f"На {animal.name.lower()} нужно {animal.price} i¢.")
    else:
        сколько = max(0, int(count or 1))
        if сколько < 1:
            return FarmResult(False, "Голов должно быть больше нуля.")
        if сколько > место:
            return FarmResult(False, f"Столько не влезет — можно ещё {место}.")

    цена = animal.price * сколько
    if not await spend(chat_id, user_id, цена):
        return FarmResult(False, f"Не хватает монет: {сколько} × {animal.name.lower()} — {цена} i¢.")

    # Накопленное забираем ДО прибавления голов: отметка о сборе у вида одна на
    # всех, и новые животные иначе надоили бы за время, когда их не было.
    собрано = await collect_barn(chat_id, user_id, now=now)
    добавлено = await db.add_farm_animals(chat_id, user_id, animal.key, now,
                                          quantity=сколько,
                                          max_per_kind=livestock.MAX_PER_KIND)
    if добавлено < сколько:
        await db.add_coins(chat_id, user_id, animal.price * (сколько - добавлено))
    if добавлено <= 0:
        return FarmResult(False, "Не получилось — хлев уже полон.")
    await db.seed_extra_shop_items(chat_id, livestock.SHOP_ITEMS, is_active=False)
    return FarmResult(True, planted=добавлено, coins_spent=animal.price * добавлено,
                      items=собрано.items if собрано.ok else {})


async def barn_sell(chat_id: int, user_id: int, animal_key: str, count, *,
                    now: Optional[datetime] = None) -> FarmResult:
    """Продать голов скота за половину цены. count — число или «все»."""
    now = now or datetime.utcnow()
    animal = livestock.BY_WORD.get((animal_key or "").strip().casefold())
    if animal is None:
        return FarmResult(False, "Такого в хлеву не держат.")

    есть = await db.get_farm_animal_quantity(chat_id, user_id, animal.key)
    if есть <= 0:
        return FarmResult(False, f"{animal.name} у вас и нет.")
    сколько = есть if isinstance(count, str) else max(0, int(count or 1))
    if сколько < 1:
        return FarmResult(False, "Голов должно быть больше нуля.")
    if сколько > есть:
        return FarmResult(False, f"У вас {есть} — продать {сколько} не выйдет.")

    собрано = await collect_barn(chat_id, user_id, now=now)
    продано = await db.remove_farm_animals(chat_id, user_id, animal.key, сколько)
    if продано <= 0:
        return FarmResult(False, f"{animal.name} у вас и нет.")
    выручка = livestock.sell_back(animal) * продано
    await db.add_coins(chat_id, user_id, выручка)
    return FarmResult(True, harvested=продано, coins_gained=выручка,
                      items=собрано.items if собрано.ok else {})
