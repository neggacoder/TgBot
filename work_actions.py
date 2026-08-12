"""Работа: смена, перерыв, состояние. Ничего не отправляет.

Пятый модуль того же устройства. Числа профессий лежат в professions.py и
здесь не повторяются.

Смена перенесена из bot.py по шагам, а не пересказана: порядок множителей в
ней значащий. Настроение множит базу, уровень и курсы — следом, выгорание
режет уже полученное, событие чата множит после всего, надбавка предметов
идёт последней перед настройкой чата, а настройка чата — самой последней.
Переставь два шага местами, и «+20% от курсов» начнёт значить разные деньги в
зависимости от того, идёт ли сегодня аврал.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import chat_events
import db
import farm_actions
import game_actions
import professions
import shop_effects

logger = logging.getLogger(__name__)

MAX_COOLDOWN_CUT_PERCENT = 90


async def cooldown_for(chat_id: int, user_id: int) -> timedelta:
    """Ожидание между сменами с учётом «кофемашины»."""
    срез = await farm_actions.item_perk(chat_id, user_id,
                                        shop_effects.PERK_WORK_COOLDOWN)
    if not срез:
        return professions.WORK_COOLDOWN
    срез = min(срез, MAX_COOLDOWN_CUT_PERCENT)
    return timedelta(
        seconds=professions.WORK_COOLDOWN.total_seconds() * (100 - срез) / 100)


async def passive_percent(chat_id: int, user_id: int) -> int:
    activity = shop_effects.ACTIVITY_WORK
    try:
        keys = [i["item_key"] for i in await db.list_inventory(chat_id, user_id)]
        percent = shop_effects.passive_percent(keys, activity)
        percent += await game_actions._pet_bonus(chat_id, user_id, activity)
    except Exception as exc:
        logger.warning("passive_percent: %s", exc)
        return 0
    return percent


async def chat_income(chat_id: int, amount: int) -> int:
    """Множитель заработка чата — ПОСЛЕДНИМ, после всех надбавок."""
    if amount <= 0:
        return amount
    percent = await db.get_income_percent(chat_id, "profession")
    if percent == 100:
        return amount
    if percent <= 0:
        return 0
    return max(1, round(amount * percent / 100))


@dataclass
class WorkResult:
    ok: bool
    error: str = ""
    profession: str = ""
    income: int = 0
    xp: int = 0
    level: int = 0
    level_up: bool = False
    energy: int = 0
    mood: int = 0
    health: int = 0
    streak: int = 0
    burnout: bool = False
    union: int = 0            # сколько коллег в чате (0 — профсоюза нет)
    event: str = ""           # случай на смене
    office: bool = False      # смена вне очереди по «офису»
    mentor_share: int = 0     # сколько ушло наставнику
    graduated: bool = False
    next_at: Optional[str] = None
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0


async def join(chat_id: int, user_id: int, raw_key: Optional[str], *,
               now: Optional[datetime] = None) -> WorkResult:
    """Устроиться на профессию — общая версия команды и кнопки сайта."""
    key = (raw_key or "").strip().casefold()
    prof = professions.PROFESSIONS.get(key)
    if prof is None:
        return WorkResult(False, "Выберите профессию из списка.")
    stats = await db.get_profession_stats(chat_id, user_id)
    if stats.get("profession_key"):
        return WorkResult(False, "У вас уже есть профессия. Сначала увольтесь в чате.")
    now = now or datetime.utcnow()
    first_seen = await db.get_member_first_seen(chat_id, user_id)
    days_in_chat = (now - first_seen).days if first_seen else 0
    if days_in_chat < prof["req_days"]:
        return WorkResult(False, f"Нужно быть в чате минимум {prof['req_days']} дн. "
                                 f"(сейчас {days_in_chat}).")
    wallet = await db.get_wallet(chat_id, user_id) or {}
    if int(wallet.get("coins") or 0) < prof["req_coins"]:
        return WorkResult(False, f"Нужно {prof['req_coins']} i¢ на входе "
                                 f"(у вас {int(wallet.get('coins') or 0)} i¢).")
    await db.set_profession(chat_id, user_id, key)
    return WorkResult(True, profession=key, level=1, user_id=user_id)


async def shift(chat_id: int, user_id: int, *,
                now: Optional[datetime] = None,
                today: Optional[date] = None) -> WorkResult:
    """Рабочая смена. Порядок множителей — см. докстринг модуля."""
    now = now or datetime.utcnow()
    today = today or now.date()
    stats = await db.get_profession_stats(chat_id, user_id)
    ключ = stats.get("profession_key")
    if not ключ or ключ not in professions.PROFESSIONS:
        return WorkResult(False, "У вас пока нет профессии — сначала устройтесь.")

    последняя = stats.get("last_work_at")
    ожидание = await cooldown_for(chat_id, user_id)
    офис = False
    if последняя and (now - последняя) < ожидание:
        # «Собственный офис» даёт одну внеочередную смену в сутки.
        if not await db.has_profession_upgrade(chat_id, user_id, "офис") \
                or not await db.use_profession_office(chat_id, user_id, today):
            итог = WorkResult(False, "Следующая смена ещё не скоро.")
            итог.next_at = (последняя + ожидание).isoformat()
            return итог
        офис = True

    prof = professions.PROFESSIONS[ключ]
    инструменты = await db.has_profession_upgrade(chat_id, user_id, "инструменты")
    расход = prof["energy"] // 2 if инструменты else prof["energy"]
    # «Робот работяги» экономит силы. Минимум 1: иначе смена стала бы вовсе
    # бесплатной по энергии и отдых потерял бы смысл.
    экономия = await farm_actions.item_perk(chat_id, user_id,
                                            shop_effects.PERK_ENERGY_SAVE)
    if экономия:
        расход = max(1, round(расход * (100 - экономия) / 100))
    коллеги = await db.count_profession_colleagues(chat_id, ключ)
    профсоюз = коллеги >= professions.UNION_MIN_MEMBERS
    if профсоюз:
        расход = max(1, round(расход * (100 - professions.UNION_ENERGY_CUT) / 100))

    if stats["energy"] < расход:
        return WorkResult(False, f"Не хватает энергии ({stats['energy']}/{расход}) — "
                                 "нужен перерыв.")

    уровень = stats["prof_level"]
    настроение = 0.5 + (stats["mood"] / 200)
    база = random.randint(*prof["income"])
    за_уровень = 1 + professions.LEVEL_INCOME_BONUS.get(уровень, 0)
    курсы = 1.2 if await db.has_profession_upgrade(chat_id, user_id, "курсы") else 1.0
    доход = int(база * настроение * за_уровень * курсы)

    качество = random.uniform(0.8, 1.2)
    опыт = int(доход / 10) + int(качество * 2)

    # Выгорание считаем ДО смены: на десятой подряд без перерыва доход уже
    # урезан, а не после неё.
    выгорание = int(stats.get("shifts_since_break") or 0) >= professions.BURNOUT_AFTER
    if выгорание:
        доход = max(1, round(доход * (100 - professions.BURNOUT_PENALTY) / 100))

    наставник = stats.get("mentor_id")
    if наставник:
        опыт = round(опыт * (100 + professions.STUDENT_XP_BONUS) / 100)

    прошлый_день = stats.get("last_shift_day")
    if прошлый_день == today - timedelta(days=1):
        серия = stats["work_streak"] + 1
    elif прошлый_день == today:
        серия = stats["work_streak"]
    else:
        серия = 1
    if серия >= 30:
        опыт += 100
    elif серия >= 10:
        опыт += 25
    elif серия >= 5:
        опыт += 10

    случай = ""
    # «День профсоюза» — смена не тратит энергию.
    без_энергии = chat_events.flag(
        await farm_actions.active_event(chat_id), chat_events.F_NO_ENERGY)
    энергия_дельта = 0 if без_энергии else -расход
    настроение_дельта = -random.randint(0, 5)
    здоровье_дельта = 0
    if random.random() < 0.15:
        бросок = random.choice(["premium", "hurt", "insight", "theft", "treat", "bonus"])
        if бросок == "premium":
            доход = int(доход * 1.5)
            случай = "🎉 Премия! +50% к доходу за смену."
        elif бросок == "hurt":
            здоровье_дельта -= 20
            настроение_дельта -= 10
            случай = "💔 Несчастный случай: −20 здоровья, −10 настроения."
        elif бросок == "insight":
            опыт += 30
            случай = "🧠 Озарение! +30 XP."
        elif бросок == "theft":
            доход = int(доход * 0.7)
            случай = "💸 Кража: −30% от дохода."
        elif бросок == "treat":
            энергия_дельта += 20
            случай = "🤝 Коллега угостил: +20 энергии."
        else:
            доход += 50
            случай = "📈 Курс вырос: +50 i¢ бонус."

    # Аврал (событие чата) множит заработок смены.
    доход = int(доход * chat_events.multiplier(
        await farm_actions.active_event(chat_id), chat_events.T_WORK))
    процент = await passive_percent(chat_id, user_id)
    if процент:
        доход = max(1, round(доход * (100 + процент) / 100))
    доход = await chat_income(chat_id, доход)
    await db.add_coins(chat_id, user_id, доход)

    # Доля наставника — СВЕРХ дохода ученика, а не из него: иначе
    # наставничество было бы для ученика налогом.
    доля = 0
    if наставник:
        доля = max(1, round(доход * professions.MENTOR_SHARE / 100))
        await db.add_coins(chat_id, int(наставник), доля)

    stats = await db.update_profession_after_shift(
        chat_id, user_id, опыт, доход, энергия_дельта, настроение_дельта,
        здоровье_дельта, серия, today)

    итог = WorkResult(True, profession=ключ, income=доход, xp=опыт,
                      energy=stats["energy"], mood=stats["mood"],
                      health=stats["health"], streak=серия, burnout=выгорание,
                      union=коллеги if профсоюз else 0, event=случай,
                      office=офис, mentor_share=доля,
                      next_at=(now + ожидание).isoformat(), user_id=user_id)
    if int(stats.get("total_shifts") or 0) >= 20:
        итог.achievements.append("work_20")

    новый = professions.level_from_xp(stats["prof_xp"])
    итог.level = новый
    if новый > уровень:
        await db.set_profession_level(chat_id, user_id, новый)
        итог.level_up = True
    # Ученик доучился — отпускаем сам, чтобы наставник не кормился с него вечно.
    if наставник and новый >= professions.STUDENT_MAX_LEVEL:
        await db.set_profession_mentor(chat_id, user_id, None)
        итог.graduated = True
    return итог


async def rest(chat_id: int, user_id: int, *,
               now: Optional[datetime] = None) -> WorkResult:
    """Перерыв: немного энергии и обнуление счётчика выгорания.

    У перерыва свой кулдаун. Без него его жали подряд, энергия всегда была на
    сотне, и вместе с ней теряли смысл аптечка, буст и «инструменты»."""
    now = now or datetime.utcnow()
    stats = await db.get_profession_stats(chat_id, user_id)
    if not stats.get("profession_key"):
        return WorkResult(False, "У вас нет профессии — отдыхать не от чего.")
    последний = stats.get("last_break_at")
    if последний and now - последний < professions.BREAK_COOLDOWN:
        итог = WorkResult(False, "Перерыв ещё не заслужен.")
        итог.next_at = (последний + professions.BREAK_COOLDOWN).isoformat()
        return итог
    выгорал = int(stats.get("shifts_since_break") or 0) >= professions.BURNOUT_AFTER
    энергия = await db.take_profession_break(
        chat_id, user_id, professions.BREAK_ENERGY, now)
    return WorkResult(True, energy=int(энергия), burnout=выгорал,
                      mood=int(stats.get("mood") or 0),
                      health=int(stats.get("health") or 0), user_id=user_id)


async def state(chat_id: int, user_id: int, *,
                now: Optional[datetime] = None) -> dict:
    """Профессия, силы, серия и каталог — всё, что рисует экран."""
    now = now or datetime.utcnow()
    stats = await db.get_profession_stats(chat_id, user_id)
    ключ = stats.get("profession_key")
    prof = professions.PROFESSIONS.get(ключ) if ключ else None
    уровень = int(stats.get("prof_level") or 1)
    опыт = int(stats.get("prof_xp") or 0)
    следующий = professions.LEVEL_XP.get(min(уровень + 1, professions.MAX_LEVEL), 0)

    ожидание = await cooldown_for(chat_id, user_id)
    последняя = stats.get("last_work_at")
    последний_перерыв = stats.get("last_break_at")
    смен_без_перерыва = int(stats.get("shifts_since_break") or 0)
    коллеги = await db.count_profession_colleagues(chat_id, ключ) if ключ else 0

    улучшения = {}
    for key in professions.UPGRADES:
        улучшения[key] = bool(await db.has_profession_upgrade(chat_id, user_id, key))

    return {
        "now": now.isoformat(),
        "profession": ключ,
        "name": prof["name"] if prof else None,
        "emoji": prof["emoji"] if prof else None,
        "income": list(prof["income"]) if prof else None,
        "energy_cost": prof["energy"] if prof else None,
        "level": уровень,
        "max_level": professions.MAX_LEVEL,
        "xp": опыт,
        "xp_next": следующий,
        "energy": int(stats.get("energy") or 0),
        "mood": int(stats.get("mood") or 0),
        "health": int(stats.get("health") or 0),
        "regen_per_hour": professions.regen_per_hour(уровень),
        "streak": int(stats.get("work_streak") or 0),
        "total_shifts": int(stats.get("total_shifts") or 0),
        "shifts_since_break": смен_без_перерыва,
        "burnout_after": professions.BURNOUT_AFTER,
        "burnout": смен_без_перерыва >= professions.BURNOUT_AFTER,
        "burnout_penalty": professions.BURNOUT_PENALTY,
        "next_at": ((последняя + ожидание).isoformat()
                    if последняя and now - последняя < ожидание else None),
        "break_at": ((последний_перерыв + professions.BREAK_COOLDOWN).isoformat()
                     if последний_перерыв
                     and now - последний_перерыв < professions.BREAK_COOLDOWN else None),
        "union": коллеги >= professions.UNION_MIN_MEMBERS,
        "colleagues": коллеги,
        "union_min": professions.UNION_MIN_MEMBERS,
        "upgrades": улучшения,
        "upgrade_catalog": [{"key": k, "name": v["name"], "price": v["price"],
                             "effect": v["effect"]}
                            for k, v in professions.UPGRADES.items()],
        "catalog": [{"key": k, "name": v["name"], "emoji": v["emoji"],
                     "income": list(v["income"]), "energy": v["energy"],
                     "req_days": v["req_days"], "req_coins": v["req_coins"],
                     "current": k == ключ}
                    for k, v in professions.PROFESSIONS.items()],
    }
