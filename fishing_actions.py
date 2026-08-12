"""Рыбалка: забросить, показать сетку, продать. Ничего не отправляет.

То же устройство, что у farm/casino/business_actions, и та же причина: панель
отдельный процесс, bot.py ей недоступен.

Главное правило рыбалки, которое обязано совпадать до копейки: монеты
рождаются при ПРОДАЖЕ, а не при поимке. Поэтому и множитель события («Клёв
пошёл»), и надбавка снастей стоят на продаже — придержать улов до клёва
выгодно, и в этом весь смысл сетки. Единственное исключение — хлам: ботинок
платят сразу, в сетку его не кладут.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import chat_events
import db
import farm_actions
import fishing
import game_actions
import shop_effects

logger = logging.getLogger(__name__)

COOLDOWN = timedelta(hours=2)
NET_CAPACITY = 20

# Насколько снаряжение может срезать ожидание в сумме. Не «сколько дают
# предметы сейчас», а предел на будущее: фишки одного вида складываются, и без
# потолка третья дала бы отрицательный кулдаун.
MAX_COOLDOWN_CUT_PERCENT = 90


async def cooldown_for(chat_id: int, user_id: int) -> timedelta:
    """Ожидание между забросами с учётом «ледобура»."""
    срез = await farm_actions.item_perk(chat_id, user_id,
                                        shop_effects.PERK_FISH_COOLDOWN)
    if not срез:
        return COOLDOWN
    срез = min(срез, MAX_COOLDOWN_CUT_PERCENT)
    return timedelta(seconds=COOLDOWN.total_seconds() * (100 - срез) / 100)


async def passive_percent(chat_id: int, user_id: int) -> int:
    """Прибавка предметов за ачивки и питомцев к рыбалке. Ошибку глотаем:
    надбавка — не основа начисления, и непрочитавшийся инвентарь не должен
    ронять продажу."""
    activity = shop_effects.ACTIVITY_FISHING
    try:
        keys = [i["item_key"] for i in await db.list_inventory(chat_id, user_id)]
        percent = shop_effects.passive_percent(keys, activity)
        percent += await game_actions._pet_bonus(chat_id, user_id, activity)
    except Exception as exc:
        logger.warning("passive_percent: %s", exc)
        return 0
    return percent


async def event_multiplier(chat_id: int) -> float:
    """«Клёв пошёл» — множитель цены при продаже."""
    return chat_events.multiplier(await farm_actions.active_event(chat_id),
                                  chat_events.T_FISHING)


async def chat_income(chat_id: int, amount: int) -> int:
    """Множитель заработка этого чата — ПОСЛЕДНИМ, после всех надбавок.

    Порядок принципиален: событие и предметы множат базу, настройка чата —
    итог. Пол в 1 i¢ при ненулевом множителе: 40% от 2 i¢ это 1, а не 0."""
    if amount <= 0:
        return amount
    percent = await db.get_income_percent(chat_id, "fishing")
    if percent == 100:
        return amount
    if percent <= 0:
        return 0
    return max(1, round(amount * percent / 100))


@dataclass
class FishResult:
    ok: bool
    error: str = ""
    species: str = ""
    name: str = ""
    emoji: str = ""
    rarity: str = ""
    grams: int = 0
    price: int = 0            # ориентировочная цена улова
    junk: bool = False        # хлам: оплачен сразу, в сетку не кладётся
    lucky: bool = False       # сработал талисман
    record: bool = False      # новый личный рекорд по весу
    released: bool = False    # отпустили: сетка полна, а улов самый мелкий
    evicted: str = ""         # кого выбросили из сетки
    coins: int = 0            # сколько получено монет
    sold: int = 0             # сколько рыб продано
    passive: int = 0          # прибавка снастей, %
    multiplier: float = 1.0   # множитель события
    next_at: Optional[str] = None
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0


def view(row: dict, now: datetime) -> tuple[Optional[fishing.Species], int, float]:
    """(вид, цена с учётом свежести, часов в сетке). Вид None — рыба из
    каталога, которого больше нет: такую показываем, но не считаем."""
    species = fishing.BY_KEY.get(row["species_key"])
    if species is None:
        return None, 0, 0.0
    hours = max(0.0, (now - row["caught_at"]).total_seconds() / 3600)
    return species, fishing.price(species, int(row["grams"]), hours), hours


async def cast(chat_id: int, user_id: int, *,
               now: Optional[datetime] = None) -> FishResult:
    """Заброс. Кулдаун пишется ДО сетки: упади запись, человек останется без
    рыбы, но не с возможностью забрасывать в цикле."""
    now = now or datetime.utcnow()
    stats = await db.get_fishing_stats(chat_id, user_id)
    последний = stats.get("last_fish_at")
    ожидание = await cooldown_for(chat_id, user_id)
    if последний and now - последний < ожидание:
        итог = FishResult(False, "🎣 Клёва не будет — рыба ещё не вернулась.")
        итог.next_at = (последний + ожидание).isoformat()
        return итог

    без_хлама = bool(await farm_actions.item_perk(
        chat_id, user_id, shop_effects.PERK_NO_EMPTY_FISHING))
    species = fishing.roll_species(no_junk=без_хлама)
    grams = fishing.roll_grams(species)

    # ХЛАМ не занимает места в сетке: ботинок и банка сразу превращаются в
    # копейки. Иначе сетка забивалась бы мусором, а весь смысл её лимита — в
    # выборе между настоящими рыбами.
    if species.is_junk:
        сумма = fishing.base_price(species, grams)
        сумма = max(1, round(сумма * await event_multiplier(chat_id)))
        процент = await passive_percent(chat_id, user_id)
        if процент:
            сумма = max(1, round(сумма * (100 + процент) / 100))
        сумма = await chat_income(chat_id, сумма)
        await db.record_catch_weight(chat_id, user_id, 0, species.key, now)
        await db.touch_earning_activity(chat_id, user_id, "fishing", now, earned=сумма)
        await db.add_coins(chat_id, user_id, сумма)
        return FishResult(True, species=species.key, name=species.name,
                          emoji=species.emoji, rarity=species.rarity, grams=grams,
                          junk=True, coins=сумма, passive=процент,
                          next_at=(now + ожидание).isoformat(), user_id=user_id)

    # Талисман удваивает ВЕС, а не монеты: монет при забросе нет, а «вдвое
    # тяжелее» и значит «вдвое дороже при продаже». Потолок — видовой максимум,
    # иначе щука выходила бы вдвое тяжелее заявленного и портила топ по весу.
    удача = False
    if await db.consume_item_effect(chat_id, user_id, shop_effects.EFFECT_LUCKY):
        удвоенный = grams * shop_effects.LUCKY_MULTIPLIER
        grams = min(удвоенный, species.max_grams)
        удача = grams > удвоенный // 2

    рекорд = int(stats.get("best_weight") or 0)
    обновлено = await db.record_catch_weight(chat_id, user_id, grams, species.key, now)

    net = await db.list_net(chat_id, user_id)
    card = await db.get_profile_card(chat_id, user_id)
    закреплена = (card or {}).get("pinned_fish")

    итог = FishResult(True, species=species.key, name=species.name,
                      emoji=species.emoji, rarity=species.rarity, grams=grams,
                      price=fishing.base_price(species, grams), lucky=удача,
                      record=grams > рекорд, next_at=(now + ожидание).isoformat(),
                      user_id=user_id)

    if len(net) >= NET_CAPACITY:
        # Сетка полна — вылетает самая дешёвая. Закреплённый трофей
        # неприкосновенен: его для того и закрепляли.
        кандидаты = [f for f in net if f["id"] != закреплена]
        новая_цена = fishing.base_price(species, grams)
        if not кандидаты:
            итог.released = True
            итог.error = "🪣 Сетка забита закреплённой рыбой — новую отпустили."
            return итог
        худшая = min(кандидаты, key=lambda f: fishing.base_price(
            fishing.BY_KEY[f["species_key"]], int(f["grams"]))
            if f["species_key"] in fishing.BY_KEY else 0)
        вид = fishing.BY_KEY.get(худшая["species_key"])
        цена_худшей = fishing.base_price(вид, int(худшая["grams"])) if вид else 0
        if цена_худшей >= новая_цена:
            # Новая рыба — самая мелкая: выбрасывать ради неё чужую добычу
            # неправильно, отпускаем её саму.
            итог.released = True
            return итог
        await db.remove_from_net(chat_id, user_id, int(худшая["id"]))
        итог.evicted = (f"{вид.emoji} {вид.name} "
                        f"({fishing.format_weight(int(худшая['grams']))}, "
                        f"{цена_худшей} i¢)")

    await db.add_to_net(chat_id, user_id, species.key, grams, now)
    if int((обновлено or {}).get("total_catches") or 0) >= 100:
        итог.achievements.append("fish_100")
    return итог


async def sell(chat_id: int, user_id: int, fish_id: Optional[int] = None, *,
               now: Optional[datetime] = None) -> FishResult:
    """Продать всю сетку или одну рыбу. Закреплённый трофей не продаётся."""
    now = now or datetime.utcnow()
    net = await db.list_net(chat_id, user_id)
    if not net:
        return FishResult(False, "🪣 Сетка пуста — продавать нечего.")
    card = await db.get_profile_card(chat_id, user_id)
    закреплена = (card or {}).get("pinned_fish")

    if fish_id is not None:
        выбранные = [f for f in net if int(f["id"]) == int(fish_id)]
        if not выбранные:
            return FishResult(False, "Такой рыбы в сетке нет.")
        if выбранные[0]["id"] == закреплена:
            return FishResult(False, "📌 Эта рыба закреплена как трофей — её не продают.")
    else:
        выбранные = [f for f in net if f["id"] != закреплена]
        if not выбранные:
            return FishResult(False, "📌 В сетке только закреплённый трофей.")

    множитель = await event_multiplier(chat_id)
    всего, продано, лучшая, имя = 0, 0, 0, ""
    for row in выбранные:
        species, цена, _часов = view(row, now)
        if species is None:
            continue
        заработок = max(1, round(цена * множитель))
        всего += заработок
        продано += 1
        if заработок > лучшая:
            лучшая, имя = заработок, species.name
        await db.remove_from_net(chat_id, user_id, int(row["id"]))
    if not продано:
        return FishResult(False, "🪣 Продавать нечего.")

    процент = await passive_percent(chat_id, user_id)
    if процент:
        всего = max(1, round(всего * (100 + процент) / 100))
    всего = await chat_income(chat_id, всего)
    await db.touch_earning_activity(chat_id, user_id, "fishing", now, earned=всего)
    await db.add_coins(chat_id, user_id, всего)
    if лучшая:
        await db.record_catch_price(chat_id, user_id, лучшая, имя)

    итог = FishResult(True, coins=всего, sold=продано, passive=процент,
                      multiplier=множитель, user_id=user_id)
    wallet = await db.get_wallet(chat_id, user_id) or {}
    монеты = int(wallet.get("coins") or 0)
    if монеты >= 100_000:
        итог.achievements.append("coins_100000")
    elif монеты >= 10_000:
        итог.achievements.append("coins_10000")
    return итог


async def release(chat_id: int, user_id: int, fish_id: int) -> FishResult:
    """Выпустить рыбу, не продавая — освободить место под крупную."""
    net = await db.list_net(chat_id, user_id)
    выбранная = next((f for f in net if int(f["id"]) == int(fish_id)), None)
    if выбранная is None:
        return FishResult(False, "Такой рыбы в сетке нет.")
    card = await db.get_profile_card(chat_id, user_id)
    if выбранная["id"] == (card or {}).get("pinned_fish"):
        return FishResult(False, "📌 Эта рыба закреплена как трофей.")
    await db.remove_from_net(chat_id, user_id, int(fish_id))
    species = fishing.BY_KEY.get(выбранная["species_key"])
    return FishResult(True, species=выбранная["species_key"],
                      name=(species.name if species else ""), user_id=user_id)


async def pin(chat_id: int, user_id: int, fish_id: Optional[int]) -> FishResult:
    """Закрепить трофей в профиле (или снять закреп, если fish_id пуст).
    Закреплённую рыбу не продают и не выбрасывают из полной сетки."""
    if fish_id is not None:
        net = await db.list_net(chat_id, user_id)
        if not any(int(f["id"]) == int(fish_id) for f in net):
            return FishResult(False, "Такой рыбы в сетке нет.")
    await db.set_pinned_fish(chat_id, user_id, int(fish_id) if fish_id else None)
    return FishResult(True, user_id=user_id)


async def state(chat_id: int, user_id: int, *,
                now: Optional[datetime] = None) -> dict:
    """Сетка, кулдаун и каталог видов — всё, что рисует экран."""
    now = now or datetime.utcnow()
    stats = await db.get_fishing_stats(chat_id, user_id)
    последний = stats.get("last_fish_at")
    ожидание = await cooldown_for(chat_id, user_id)
    card = await db.get_profile_card(chat_id, user_id)
    закреплена = (card or {}).get("pinned_fish")
    множитель = await event_multiplier(chat_id)

    сетка = []
    сумма = 0
    for row in await db.list_net(chat_id, user_id):
        species, цена, часов = view(row, now)
        if species is None:
            continue
        сумма += цена
        сетка.append({
            "id": int(row["id"]), "key": species.key, "name": species.name,
            "emoji": species.emoji, "rarity": species.rarity,
            "rarity_label": fishing.RARITY_LABEL[species.rarity],
            "grams": int(row["grams"]),
            "weight": fishing.format_weight(int(row["grams"])),
            "price": цена, "hours": round(часов, 1),
            "freshness": fishing.freshness_label(часов),
            # Драйвер БД иногда отдаёт BIGINT строкой, а id сетки — числом.
            # Строгое сравнение тогда рисовало «Закрепить» уже закреплённой
            # рыбе, и с сайта её было невозможно снять.
            "pinned": (закреплена is not None
                       and int(row["id"]) == int(закреплена)),
        })

    return {
        "now": now.isoformat(),
        "net": сетка,
        "capacity": NET_CAPACITY,
        "net_value": сумма,
        # Цену при продаже поднимает событие — видеть это надо ДО продажи,
        # иначе смысл придерживать улов теряется.
        "multiplier": множитель,
        "next_at": ((последний + ожидание).isoformat()
                    if последний and now - последний < ожидание else None),
        "cooldown_seconds": int(ожидание.total_seconds()),
        "best_weight": int(stats.get("best_weight") or 0),
        "total_catches": int(stats.get("total_catches") or 0),
        "species": [{
            "key": s.key, "name": s.name, "emoji": s.emoji, "rarity": s.rarity,
            "rarity_label": fishing.RARITY_LABEL[s.rarity],
            "min_grams": s.min_grams, "max_grams": s.max_grams,
            "junk": s.is_junk,
        } for s in fishing.SPECIES],
    }
