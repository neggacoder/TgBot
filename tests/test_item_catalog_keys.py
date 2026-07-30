"""Ключи предметов: константы должны совпадать с каталогом, а сам каталог —
не содержать двух разных предметов под одним ключом.

Оба правила выглядят самоочевидными и оба были нарушены — молча, без единой
ошибки в логах, потому что ключ предмета нигде не проверяется: он просто не
находится (и предмет не срабатывает) или находится не тот (и человек получает
чужие способности).

Проверяем на уровне каталогов, а не проводки: каталог — источник обеих
поломок, и тест здесь ловит их в момент правки, а не через месяц по жалобе.
"""

from __future__ import annotations

from collections import Counter

import robbery
import shop_effects as SE


def _all_catalog_items():
    """Все предметы всех каталогов одним списком: (откуда, предмет)."""
    for name, items in (
        ("EFFECT_ITEMS", SE.EFFECT_ITEMS),
        ("REWARD_ITEMS", SE.REWARD_ITEMS),
        ("ACHIEVEMENT_ITEMS", SE.ACHIEVEMENT_ITEMS),
        ("CRAFT_ITEMS", SE.CRAFT_ITEMS),
        ("MATERIAL_ITEMS", SE.MATERIAL_ITEMS),
    ):
        for item in items:
            yield name, item


def test_surveillance_pass_constant_names_a_real_item():
    """Константа «отмазки» обязана указывать на существующий ключ каталога.

    Разъехавшись, они превращают предмет за 20 000 i¢ в мёртвый груз:
    продаётся он под ключом из ROBBERY_ITEMS, а ищут его по константе.
    """
    assert robbery.SURVEILLANCE_PASS_ITEM_KEY in robbery.ROBBERY_ITEMS


def test_item_keys_are_unique_across_catalogs():
    """Один ключ — один предмет. Дубль молча затирается в общем справочнике."""
    keys = [item.key for _, item in _all_catalog_items()]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    assert duplicates == [], f"ключ занят дважды: {duplicates}"


def test_every_achievement_item_is_reachable_by_its_own_key():
    """Поиск по ключу обязан вернуть тот же предмет, что лежит в каталоге.

    ACHIEVEMENT_BY_KEY собирается из ACHIEVEMENT_ITEMS + CRAFT_ITEMS, поэтому
    совпадение ключей отдаёт наградной предмет владельцу крафтового и наоборот
    — вместе с чужими способностями.
    """
    for item in SE.ACHIEVEMENT_ITEMS + SE.CRAFT_ITEMS:
        assert SE.ACHIEVEMENT_BY_KEY[item.key] is item, (
            f"по ключу «{item.key}» находится не «{item.name}»"
        )
