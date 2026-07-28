"""Лавка: ассортимент дня и целостность каталога.

Каталог лавки — список ключей, которые обязаны существовать в других
каталогах: ключ с опечаткой не сломает ничего заметно, он просто никогда не
попадёт в продажу. Поэтому проверяем не только выбор ассортимента, но и то,
что каждому ключу пула есть чем стать строкой в shop_items.
"""

from __future__ import annotations

import random

import black_market as BM
import robbery
import shop_effects as SE


def test_rotation_picks_three_or_four_distinct_items():
    for seed in range(50):
        rotation = BM.pick_rotation(random.Random(seed))
        assert 3 <= len(rotation) <= 4
        assert set(rotation) <= BM.POOL_KEYS


def test_rotation_stock_never_exceeds_item_limit():
    limits = {slot.key: slot.max_stock for slot in BM.POOL}
    for seed in range(50):
        for key, stock in BM.pick_rotation(random.Random(seed)).items():
            assert 1 <= stock <= limits[key]


def test_strongest_items_never_come_in_batches():
    """Медвежатник за 75 000 и отмазка за 20 000 — не больше одного за раз."""
    limits = {slot.key: slot.max_stock for slot in BM.POOL}
    assert limits["medvezhatnik"] == 1
    assert limits[robbery.SURVEILLANCE_PASS_ITEM_KEY] == 1


def test_every_pool_key_can_become_a_shop_row():
    """У каждого ключа пула есть строка, которой он засеется в shop_items.

    Источников три: предметы ограбления, предметы-эффекты и новинки лавки.
    Ключ, которого нет ни в одном, ротация выберет — и купить его будет
    нельзя, потому что строки в магазине не появится.
    """
    seedable = (
        set(robbery.ROBBERY_ITEMS)
        | set(SE.BY_KEY)
        | {row[0] for row in BM.NEW_ITEMS}
    )
    assert BM.POOL_KEYS <= seedable


def test_pool_has_no_rewards():
    """Награду _shop_buy отвергнет как «не продаётся» — в пуле ей не место."""
    assert not (BM.POOL_KEYS & SE.REWARD_KEYS)


def test_new_items_are_priced_as_specified():
    prices = {row[0]: row[2] for row in BM.NEW_ITEMS}
    assert prices[BM.SIGNAL_KEY] == 20_000
    assert prices[BM.SLEPOK_KEY] == 6_000
