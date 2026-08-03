"""Бизнесы: сделать и вернуть результат. Ничего не отправляет.

Третий модуль того же устройства, что farm_actions и casino_actions, и по той
же причине: панель — отдельный процесс, bot.py ей недоступен, а правила
покупки, копилки и налога жили вперемешку с ответами в чат.

Числа (цены, доход, потолки, налог, оснащение) лежат в businesses.py и здесь
не повторяются — этот модуль соединяет их с базой.

Главное, что нельзя посчитать дважды по-разному, — НАЛОГ. Он берётся от всей
снимаемой суммы разом, а не с каждого бизнеса отдельно: иначе владелец пяти
бизнесов платил бы по нижней ставке пять раз и в сумме меньше, чем владелец
одного крупного.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import businesses as catalog
import db
import game_actions
import seasons
import shop_effects

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Копилка
# ----------------------------------------------------------------------------
def hours_since(last_tick) -> float:
    if not last_tick:
        return 0.0
    return max(0.0, (datetime.utcnow() - last_tick).total_seconds() / 3600)


def pending(row: dict) -> int:
    """Сколько в копилке этого бизнеса ПРЯМО СЕЙЧАС.

    Сломанный не копит вообще: накопленное до поломки сохраняется (оно уже
    зафиксировано в accrued в момент поломки), но не растёт.

    Если действовала надбавка от срочного предложения, интервал делится на два
    куска — под надбавкой и без неё: копилка считается лениво, и между двумя
    обращениями надбавка могла успеть и начаться, и кончиться.
    """
    item = catalog.BY_KEY.get(row["business_key"])
    if item is None:
        return 0
    level = int(row["level"])
    stored = int(row["accrued"] or 0)
    upgrades = row.get("upgrades") or ()
    if row.get("broken_kind"):
        return max(0, min(stored, catalog.effective_cap(item, level, upgrades)))

    last_tick = row.get("last_tick_at")
    всего_часов = hours_since(last_tick)
    boost_until = row.get("boost_until")
    if not boost_until or not last_tick or boost_until <= last_tick:
        return catalog.accrued_now(level, item, stored, всего_часов, upgrades)

    конец = min(datetime.utcnow(), boost_until)
    под_надбавкой = max(0.0, (конец - last_tick).total_seconds() / 3600)
    return catalog.accrued_with_boost(
        level, item, stored,
        normal_hours=max(0.0, всего_часов - под_надбавкой),
        boosted_hours=под_надбавкой,
        upgrades=upgrades,
    )


async def load_all(chat_id: int, user_id: int) -> list[dict]:
    """Бизнесы человека вместе с оснащением.

    Оснащение подмешивается в строку, чтобы pending() остался синхронным: его
    зовут в циклах и в отрисовке, и поход в базу оттуда превратил бы каждый
    показ списка в десяток запросов.
    """
    rows = await db.list_user_businesses(chat_id, user_id)
    for row in rows:
        row["upgrades"] = await db.list_business_upgrades(
            chat_id, user_id, row["business_key"])
    return rows


async def load_one(chat_id: int, user_id: int, key: str) -> Optional[dict]:
    row = await db.get_user_business(chat_id, user_id, key)
    if row is None:
        return None
    row["upgrades"] = await db.list_business_upgrades(chat_id, user_id, key)
    return row


# ----------------------------------------------------------------------------
# Результат
# ----------------------------------------------------------------------------
@dataclass
class BizResult:
    ok: bool
    error: str = ""
    key: str = ""
    gross: int = 0            # снято до налога
    tax: int = 0
    net: int = 0              # на руки
    spent: int = 0
    level: int = 0
    count: int = 0            # сколько бизнесов затронуто
    free: bool = False        # оплачено «бизнес-планом», а не монетами
    achievements: list[str] = field(default_factory=list)
    user_id: int = 0
    deal_id: int = 0          # номер предложения (сделка между людьми)


async def _coin_achievements(chat_id: int, user_id: int) -> list[str]:
    """Пороги «богача» — те же, что в чате."""
    wallet = await db.get_wallet(chat_id, user_id) or {}
    монеты = int(wallet.get("coins") or 0)
    if монеты >= 100_000:
        return ["coins_100000"]
    if монеты >= 10_000:
        return ["coins_10000"]
    return []


async def _add_season_points(chat_id: int, user_id: int, points: int,
                             today: Optional[date] = None) -> None:
    """Очки сезона за доход. Сбой глотаем: очки — надстройка над игрой, и
    упавший запрос не должен отменять уже забранные деньги."""
    if points <= 0:
        return
    try:
        await db.add_season_points(chat_id, seasons.season_key(today or datetime.utcnow().date()),
                                   user_id, points)
    except Exception as exc:
        logger.warning("_add_season_points: %s", exc)


# ----------------------------------------------------------------------------
# Действия
# ----------------------------------------------------------------------------
async def buy(chat_id: int, user_id: int, raw_key: str) -> BizResult:
    """Купить бизнес. Второй такой же не положен."""
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    if await db.get_user_business(chat_id, user_id, item.key):
        return BizResult(False, f"{item.name} у вас уже есть — второй такой не положен.")
    if not await db.try_spend_coins(chat_id, user_id, item.price):
        wallet = await db.get_wallet(chat_id, user_id) or {}
        return BizResult(False, f"Недостаточно монет: {item.name} стоит {item.price} i¢, "
                                f"а у вас {int(wallet.get('coins') or 0)} i¢.")
    if not await db.add_business(chat_id, user_id, item.key, datetime.utcnow()):
        # Гонка: такой же успели завести между проверкой и вставкой. Деньги
        # уже списаны — возвращаем, иначе человек заплатил за воздух.
        await db.add_coins(chat_id, user_id, item.price)
        return BizResult(False, "Не удалось оформить покупку — попробуйте ещё раз.")
    return BizResult(True, key=item.key, spent=item.price, level=1, user_id=user_id)


async def collect(chat_id: int, user_id: int, raw_key: Optional[str] = None, *,
                  today: Optional[date] = None) -> BizResult:
    """Забрать доход. Налог — от всей суммы разом (см. докстринг модуля)."""
    rows = await load_all(chat_id, user_id)
    if not rows:
        return BizResult(False, "У вас нет ни одного бизнеса.")
    if raw_key:
        item = catalog.resolve(raw_key)
        if item is None:
            return BizResult(False, "Такого бизнеса нет.")
        rows = [r for r in rows if r["business_key"] == item.key]
        if not rows:
            return BizResult(False, f"{item.name} вам не принадлежит.")

    gross = sum(pending(r) for r in rows)
    if gross <= 0:
        return BizResult(False, "Копилки пусты — зайдите позже.")

    tax = catalog.tax_for(gross)
    net = gross - tax
    now = datetime.utcnow()
    for row in rows:
        await db.set_business_accrual(chat_id, user_id, row["business_key"], 0, now)
    if net > 0:
        await db.add_coins(chat_id, user_id, net)
    if tax > 0:
        await db.add_chat_coins(chat_id, tax)
    await _add_season_points(chat_id, user_id, seasons.points_for_coins(net), today)
    итог = BizResult(True, gross=gross, tax=tax, net=net, count=len(rows),
                     user_id=user_id)
    итог.achievements = await _coin_achievements(chat_id, user_id)
    return итог


async def upgrade(chat_id: int, user_id: int, raw_key: str) -> BizResult:
    """Поднять уровень. «Бизнес-план» платит вместо монет."""
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    row = await load_one(chat_id, user_id, item.key)
    if row is None:
        return BizResult(False, f"{item.name} вам не принадлежит.")
    level = int(row["level"])
    if level >= catalog.MAX_LEVEL:
        return BizResult(False, f"{item.name} уже {level} уровня — это максимум.")

    цена = item.upgrade_cost(level + 1)
    прораб = await game_actions._pet_bonus(chat_id, user_id, "discount_upgrade")
    if прораб:
        цена = max(1, цена - цена * прораб // 100)
    # Заряд тратится ТОЛЬКО здесь, когда апгрейд точно состоится: проверки
    # выше пройдены, максимальный уровень отсеян.
    бесплатно = await db.consume_item_effect(chat_id, user_id,
                                             shop_effects.EFFECT_FREE_UPGRADE)
    if not бесплатно and not await db.try_spend_coins(chat_id, user_id, цена):
        wallet = await db.get_wallet(chat_id, user_id) or {}
        return BizResult(False, f"Недостаточно монет: апгрейд до {level + 1} ур. "
                                f"стоит {цена} i¢, а у вас "
                                f"{int(wallet.get('coins') or 0)} i¢.")
    if бесплатно:
        цена = 0

    # Копилку фиксируем ИМЕННО СЕЙЧАС: у нового уровня свой потолок, и без
    # пересчёта накопленное посчиталось бы задним числом по новым правилам.
    накоплено = pending(row)
    await db.set_business_level(chat_id, user_id, item.key, level + 1, накоплено,
                                datetime.utcnow())
    return BizResult(True, key=item.key, spent=цена, level=level + 1,
                     free=бесплатно, user_id=user_id)


async def repair(chat_id: int, user_id: int, raw_key: str) -> BizResult:
    """Починить сломанный. Сломанный не копит вовсе, поэтому чинить выгодно
    сразу."""
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    row = await db.get_user_business(chat_id, user_id, item.key)
    if row is None:
        return BizResult(False, f"{item.name} вам не принадлежит.")
    if not row.get("broken_kind"):
        return BizResult(False, f"{item.name} и так работает — чинить нечего.")

    цена = catalog.repair_cost(item, int(row["level"]))
    ремонтник = await game_actions._pet_bonus(chat_id, user_id, "discount_repair")
    if ремонтник:
        цена = max(1, цена - цена * ремонтник // 100)
    if not await db.try_spend_coins(chat_id, user_id, цена):
        wallet = await db.get_wallet(chat_id, user_id) or {}
        return BizResult(False, f"Ремонт стоит {цена} i¢, а у вас "
                                f"{int(wallet.get('coins') or 0)} i¢.")
    if not await db.repair_business(chat_id, user_id, item.key, datetime.utcnow()):
        await db.add_coins(chat_id, user_id, цена)      # починили из другого места
        return BizResult(False, f"{item.name} уже починили.")
    return BizResult(True, key=item.key, spent=цена, user_id=user_id)


async def equip(chat_id: int, user_id: int, raw_key: str, raw_upgrade: str) -> BizResult:
    """Поставить оснащение: охрана, аппаратура, реклама, сейф."""
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    up = catalog.resolve_upgrade(raw_upgrade or "")
    if up is None:
        return BizResult(False, "Такого оснащения нет.")
    row = await db.get_user_business(chat_id, user_id, item.key)
    if row is None:
        return BizResult(False, f"{item.name} вам не принадлежит.")
    поставлено = await db.list_business_upgrades(chat_id, user_id, item.key)
    if up.key in поставлено:
        return BizResult(False, f"{up.name} уже стоит на этом бизнесе.")
    # Цена оснащения — доля от цены САМОГО бизнеса: сейф в ювелирную стоит не
    # столько же, сколько в ларёк (см. Upgrade.price в businesses.py).
    цена = up.price(item)
    if not await db.try_spend_coins(chat_id, user_id, цена):
        wallet = await db.get_wallet(chat_id, user_id) or {}
        return BizResult(False, f"{up.name} стоит {цена} i¢, а у вас "
                                f"{int(wallet.get('coins') or 0)} i¢.")
    if not await db.add_business_upgrade(chat_id, user_id, item.key, up.key,
                                         datetime.utcnow()):
        await db.add_coins(chat_id, user_id, цена)   # успели поставить параллельно
        return BizResult(False, f"{up.name} уже стоит на этом бизнесе.")
    return BizResult(True, key=item.key, spent=цена, user_id=user_id)


async def sell_to_bot(chat_id: int, user_id: int, raw_key: str) -> BizResult:
    """Продать боту за долю цены. Копилка забирается вместе с продажей: иначе
    накопленное сгорело бы молча."""
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    row = await load_one(chat_id, user_id, item.key)
    if row is None:
        return BizResult(False, f"{item.name} вам не принадлежит.")

    накоплено = pending(row)
    цена = item.buyback()
    if not await db.delete_business(chat_id, user_id, item.key):
        return BizResult(False, f"{item.name} уже продан.")
    await db.clear_business_upgrades(chat_id, user_id, item.key)
    await db.add_coins(chat_id, user_id, цена + накоплено)
    return BizResult(True, key=item.key, net=цена + накоплено, gross=накоплено,
                     user_id=user_id)


# ----------------------------------------------------------------------------
# Состояние для экрана
# ----------------------------------------------------------------------------
async def state(chat_id: int, user_id: int) -> dict:
    """Свои бизнесы, каталог и оснащение — одним куском."""
    wallet = await db.get_wallet(chat_id, user_id) or {}
    rows = await load_all(chat_id, user_id)
    свои = []
    сумма = 0
    for row in rows:
        item = catalog.BY_KEY.get(row["business_key"])
        if item is None:
            continue
        уровень = int(row["level"])
        оснащение = sorted(row.get("upgrades") or ())
        накоплено = pending(row)
        сумма += накоплено
        потолок = catalog.effective_cap(item, уровень, оснащение)
        свои.append({
            "key": item.key, "name": item.name,
            "level": уровень, "max_level": catalog.MAX_LEVEL,
            "income": catalog.effective_income(item, уровень, оснащение),
            "accrued": накоплено, "cap": потолок,
            "full_percent": min(100, round(накоплено * 100 / потолок)) if потолок else 0,
            "hours_to_full": round(catalog.hours_to_full(уровень, item, накоплено), 1),
            "broken": row.get("broken_kind") or None,
            "repair_cost": catalog.repair_cost(item, уровень),
            "upgrade_cost": (item.upgrade_cost(уровень + 1)
                             if уровень < catalog.MAX_LEVEL else None),
            "sell_price": item.buyback(),
            "upgrades": оснащение,
            "gear_prices": {u.key: u.price(item) for u in catalog.UPGRADES},
            "boost_until": (row["boost_until"].isoformat()
                            if row.get("boost_until") else None),
        })

    есть = {b["key"] for b in свои}
    витрина = [{
        "key": b.key, "name": b.name, "price": b.price,
        "income": b.income(1), "cap": b.cap(1), "owned": b.key in есть,
        "affordable": int(wallet.get("coins") or 0) >= b.price,
    } for b in catalog.BUSINESSES]

    return {
        "now": datetime.utcnow().isoformat(),
        "coins": int(wallet.get("coins") or 0),
        "mine": свои,
        "pending_total": сумма,
        # Налог показываем ДО сбора: он зависит от суммы, и узнавать о нём
        # постфактум — худший способ (человек снял бы по частям).
        "tax_now": catalog.tax_for(сумма),
        "catalog": витрина,
        # Цена оснащения зависит от бизнеса, поэтому в каталоге её нет: она
        # проставлена у каждого своего бизнеса ниже.
        "gear": [{"key": u.key, "name": u.name, "emoji": u.emoji,
                  "hint": u.description} for u in catalog.UPGRADES],
        "max_level": catalog.MAX_LEVEL,
    }


# ----------------------------------------------------------------------------
# Сделка между людьми: предложить и подтвердить
#
# Сделка живёт В БАЗЕ, а не в памяти. В чате она лежит в словаре процесса бота
# (_business_offers), и для чата этого хватает: предложил и подтвердили в одном
# процессе. С сайта так нельзя — предлагает панель, а кнопку нажимают в
# телеграме, то есть в ДРУГОМ процессе, и память одного для другого не
# существует. Заодно сделка переживает перезапуск бота.
#
# Подтверждает всегда ВТОРАЯ сторона. Односторонняя передача с сайта отдала бы
# человеку чужой бизнес без спроса — а вместе с ним и налог на копилку, и
# обязанность его чинить.
# ----------------------------------------------------------------------------
OFFER_TTL_SECONDS = 10 * 60


def deal_key(chat_id: int, deal_id: int) -> str:
    return f"bizdeal:{chat_id}:{deal_id}"


def _deal_seq_key(chat_id: int) -> str:
    return f"bizdeal_seq:{chat_id}"


async def cash_out(chat_id: int, user_id: int, row: dict) -> tuple[int, int]:
    """Инкассирует копилку одного бизнеса: владельцу за вычетом налога, налог —
    в казну чата, копилку обнуляет. (на руки, налог); (0, 0) — было пусто.

    Сначала обнуляем, потом платим: упади начисление, человек останется без
    денег, но не с возможностью инкассировать одно и то же дважды.
    """
    gross = pending(row)
    now = datetime.utcnow()
    if gross <= 0:
        await db.set_business_accrual(chat_id, user_id, row["business_key"], 0, now)
        return 0, 0
    tax = catalog.tax_for(gross)
    net = gross - tax
    await db.set_business_accrual(chat_id, user_id, row["business_key"], 0, now)
    if net > 0:
        await db.add_coins(chat_id, user_id, net)
    if tax > 0:
        await db.add_chat_coins(chat_id, tax)
    return net, tax


async def offer(chat_id: int, seller_id: int, buyer_id: int, raw_key: str,
                price: int = 0) -> BizResult:
    """Предложить сделку. price=0 — передача в дар.

    Ничего не двигает и денег не трогает: только запоминает предложение и
    отдаёт его номер. Всё случается в accept_deal, когда согласится покупатель.
    """
    item = catalog.resolve(raw_key or "")
    if item is None:
        return BizResult(False, "Такого бизнеса нет.")
    if buyer_id == seller_id:
        return BizResult(False, "Продать бизнес самому себе не выйдет 🙂")
    price = max(0, int(price or 0))
    row = await load_one(chat_id, seller_id, item.key)
    if row is None:
        return BizResult(False, f"{item.name} вам не принадлежит.")
    if await db.get_user_business(chat_id, buyer_id, item.key):
        return BizResult(False, f"У получателя уже есть {item.name} — "
                                "второй такой не положен.")

    try:
        строка = await db.get_data(_deal_seq_key(chat_id))
        номер = int((строка or {}).get("data_value") or 0) + 1
    except (TypeError, ValueError):
        номер = 1
    await db.set_data(_deal_seq_key(chat_id), str(номер), updated_by=seller_id)
    await db.set_data(deal_key(chat_id, номер), json.dumps({
        "seller": seller_id, "buyer": buyer_id, "key": item.key,
        "price": price, "expires": int(time.time()) + OFFER_TTL_SECONDS,
    }, ensure_ascii=False), updated_by=seller_id)

    итог = BizResult(True, key=item.key, spent=price, level=int(row["level"]),
                     gross=pending(row), user_id=seller_id)
    итог.deal_id = номер
    return итог


async def load_deal(chat_id: int, deal_id: int) -> Optional[dict]:
    """Живое предложение или None (нет такого либо просрочено)."""
    строка = await db.get_data(deal_key(chat_id, deal_id))
    if not строка:
        return None
    try:
        сделка = json.loads(строка["data_value"])
    except (ValueError, TypeError):
        await db.delete_data(deal_key(chat_id, deal_id))
        return None
    if int(сделка.get("expires") or 0) < int(time.time()):
        await db.delete_data(deal_key(chat_id, deal_id))
        return None
    return сделка


async def decline_deal(chat_id: int, deal_id: int, presser_id: int) -> BizResult:
    """Отказ. Отказаться может любая из сторон — и покупатель, и передумавший
    продавец."""
    сделка = await load_deal(chat_id, deal_id)
    if сделка is None:
        return BizResult(False, "Предложение устарело.")
    if presser_id not in (сделка["buyer"], сделка["seller"]):
        return BizResult(False, "Это предложение не вам.")
    await db.delete_data(deal_key(chat_id, deal_id))
    return BizResult(True, key=сделка["key"], user_id=presser_id)


async def accept_deal(chat_id: int, deal_id: int, presser_id: int) -> BizResult:
    """Подтверждение покупателем. Здесь и только здесь двигаются деньги.

    Порядок выбран так, чтобы ни один сбой не создавал и не терял денег:
    сначала списываем с покупателя (не хватило — ничего не произошло), потом
    инкассируем копилку продавцу, потом переносим бизнес, и только если
    перенос удался — платим продавцу. Не удался — деньги возвращаем.
    """
    сделка = await load_deal(chat_id, deal_id)
    if сделка is None:
        return BizResult(False, "Предложение устарело.")
    if presser_id != сделка["buyer"]:
        return BizResult(False, "Это предложение не вам.")

    item = catalog.BY_KEY.get(сделка["key"])
    продавец, покупатель, цена = сделка["seller"], сделка["buyer"], int(сделка["price"])
    row = await load_one(chat_id, продавец, сделка["key"])
    if item is None or row is None:
        await db.delete_data(deal_key(chat_id, deal_id))
        return BizResult(False, "Продавец уже расстался с этим бизнесом.")
    if await db.get_user_business(chat_id, покупатель, сделка["key"]):
        return BizResult(False, f"У вас уже есть {item.name}.")
    if цена and not await db.try_spend_coins(chat_id, покупатель, цена):
        return BizResult(False, f"Нужно {цена} i¢, а у вас меньше.")

    # Копилка НЕ переезжает: продавец забирает её себе с налогом, бизнес
    # переходит пустым. Иначе покупатель платил бы за бизнес, а получал бы
    # бизнес плюс чужие накопления — и цена перестала бы что-то значить.
    net, tax = await cash_out(chat_id, продавец, row)
    if not await db.move_business(chat_id, продавец, покупатель, сделка["key"],
                                  datetime.utcnow()):
        if цена:
            await db.add_coins(chat_id, покупатель, цена)
        return BizResult(False, "Сделка сорвалась, деньги вернулись.")
    # Оснащение не переезжает к новому хозяину — иначе перепродажа копила бы
    # его бесплатно.
    await db.clear_business_upgrades(chat_id, продавец, сделка["key"])
    if цена:
        await db.add_coins(chat_id, продавец, цена)
    await db.delete_data(deal_key(chat_id, deal_id))
    return BizResult(True, key=сделка["key"], spent=цена, net=net, tax=tax,
                     level=int(row["level"]), user_id=покупатель)
