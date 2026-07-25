"""Система ограблений («!ограбить»).

Кошельки (i¢) уже есть в db.py (economy_wallets) — этот модуль добавляет
поверх них только саму механику: шанс успеха, сумму кражи и предметы
магазина, которые эти числа немного меняют.

Все числа ниже — константы, их можно смело менять на глаз.
"""

from __future__ import annotations

import random
from datetime import timedelta

# ----------------------------------------------------------------------------
# Баланс — правьте эти числа, больше ничего трогать не нужно.
# ----------------------------------------------------------------------------
ROBBERY_COOLDOWN = timedelta(hours=2)          # как часто можно грабить
ROBBERY_MIN_VICTIM_BALANCE = 50                # у жертвы должно быть хотя бы столько i¢
ROBBERY_MIN_PERCENT = 5                        # минимум кражи от баланса жертвы, %
ROBBERY_MAX_PERCENT = 40                       # максимум кражи от баланса жертвы, %

BASE_SUCCESS_CHANCE = 50                       # базовый шанс успеха, %
RABBIT_PAW_BONUS_CHANCE = 15                   # 🐇 бонус к шансу успеха, %

DEFAULT_FAIL_LOSS_PERCENT = 40                 # сколько теряет грабитель при провале, %
GOLD_PIG_FAIL_LOSS_PERCENT = 20                # с 🐷 при провале теряется меньше
GOLD_PIG_LOOT_BONUS_PERCENT = 40               # 🐷 бонус к сумме удачной кражи, %

ROBBERY_ITEM_MAX_QUANTITY = 3                  # больше стольки штук не докупить одновременно
SURVEILLANCE_STRIKES_LIMIT = 3
SURVEILLANCE_PARDON_PRICE = 100_000
SURVEILLANCE_PASS_ITEM_KEY = "surveillance_pass"


# ----------------------------------------------------------------------------
# Каталог предметов ограбления — попадают в обычный магазин чата теми же
# ключами/ценами (см. db.seed_robbery_items ниже).
# ----------------------------------------------------------------------------
ROBBERY_ITEMS: dict[str, dict] = {
    "binokl": {
        "name": "Бинокль",
        "emoji": "🔭",
        "price": 800,
        "description": (
            "Позволяет выбрать конкретную жертву ограбления вместо случайной. "
            "Использовать: «!ограбить бинокль @username» (или ответом)."
        ),
    },
    "survilence_pass":{
        "name": "Отмазка",
        "price": 20000,
        "description": "При поимке на ограблении списывается вместо страйка «под надзором» — провал не идёт в счёт.",
        "emoji": "🕶️",
    },
    "rabbit_paw": {
        "name": "Кроличья лапка",
        "emoji": "🐇",
        "price": 600,
        "description": f"+{RABBIT_PAW_BONUS_CHANCE}% к шансу успеха ограбления. Срабатывает сама.",
    },
    "bronik": {
        "name": "Бронежилет",
        "emoji": "🦺",
        "price": 900,
        "description": "Блокирует одну попытку ограбления против вас. Срабатывает сам.",
    },
    "gold_pig": {
        "name": "Золотая свинка",
        "emoji": "🐷",
        "price": 1500,
        "description": (
            f"+{GOLD_PIG_LOOT_BONUS_PERCENT}% к добыче при удаче, "
            f"при провале теряете только {GOLD_PIG_FAIL_LOSS_PERCENT}% вместо "
            f"{DEFAULT_FAIL_LOSS_PERCENT}%. Срабатывает сама."
        ),
    },
    
    "dymovushka": {
        "name": "Дымовая шашка",
        "emoji": "💨",
        "price": 500,
        "description": "При неудачном ограблении жертва не узнает, кто это был. Срабатывает сама.",
    },
    "lucky_coin": {
        "name": "Счастливая монета",
        "emoji": "🍀",
        "price": 1200,
        "description": "При неудачном ограблении вы не теряете ни копейки. Срабатывает сама.",
    },
    "getaway_car": {
        "name": "Тачка для отхода",
        "emoji": "🚗",
        "price": 700,
        "description": "После попытки (успешной или нет) кулдаун сокращается вдвое. Срабатывает сама.",
    },

}

ROBBERY_SHOP_ITEMS: list[tuple[str, str, int, str, str]] = [
    (key, info["name"], info["price"], info["description"], info["emoji"])
    for key, info in ROBBERY_ITEMS.items()
]


def success_chance(has_rabbit_paw: bool) -> int:
    chance = BASE_SUCCESS_CHANCE
    if has_rabbit_paw:
        chance += RABBIT_PAW_BONUS_CHANCE
    return max(1, min(chance, 95))


def roll_success(has_rabbit_paw: bool) -> bool:
    return random.randint(1, 100) <= success_chance(has_rabbit_paw)


def compute_steal_amount(victim_balance: int, has_gold_pig: bool) -> int:
    percent = random.randint(ROBBERY_MIN_PERCENT, ROBBERY_MAX_PERCENT)
    amount = victim_balance * percent / 100
    if has_gold_pig:
        amount *= 1 + GOLD_PIG_LOOT_BONUS_PERCENT / 100
    return max(1, min(int(round(amount)), victim_balance))


def compute_fail_loss(robber_balance: int, has_lucky_coin: bool, has_gold_pig: bool) -> int:
    if has_lucky_coin:
        return 0
    percent = GOLD_PIG_FAIL_LOSS_PERCENT if has_gold_pig else DEFAULT_FAIL_LOSS_PERCENT
    return int(round(robber_balance * percent / 100))