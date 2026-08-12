"""Витрина: достижения и коллекции. Только чтение.

Шестнадцатый модуль того же устройства, и единственный, который ничего не
меняет — ни монет, ни предметов. Отсюда его главное правило: он ничего и не
должен уметь менять. Закрепление достижения, выдача титула за коллекцию,
проверка «а не собралась ли она» — всё это живёт там, где происходят сами
события, и звать это из витрины значило бы, что открытие экрана начинает
что-то выдавать.

Второе: НЕПОЛУЧЕННОЕ ПОКАЗЫВАЕТСЯ ТОЖЕ. Список только собранного отвечает на
вопрос «что у меня есть» и молчит о том, ради чего сюда и заходят, — что
осталось. В чате так же: полученные списком, остальные под катом.

Третье: ЧУЖИЕ ДОСТИЖЕНИЯ МОЖНО СКРЫТЬ. Это настройка человека («-ачивки»), и
на сайте она обязана значить то же самое: скрывший показывает их только себе.
"""

from __future__ import annotations

import logging
from typing import Optional

import achievements_meta
import collections_meta
import db

logger = logging.getLogger(__name__)


async def achievements(chat_id: int, user_id: int) -> dict:
    """Все достижения: полученные и оставшиеся, в порядке реестра.

    Порядок именно реестра, а не выдачи: он сгруппирован по смыслу (награды,
    сообщения, стрик, игры), и сортировка по дате получения рассыпала бы
    группы, ради которых список и читают.
    """
    получены = {r["code"] for r in await db.get_achievements(chat_id, user_id)}
    список = []
    for код, о in achievements_meta.ACHIEVEMENTS.items():
        список.append({
            "code": код, "emoji": о["emoji"], "title": о["title"],
            "desc": о["desc"], "earned": код in получены,
        })
    return {
        "total": len(achievements_meta.ACHIEVEMENTS),
        "earned": len(получены & set(achievements_meta.ACHIEVEMENTS)),
        "items": список,
    }


async def collection_progress(chat_id: int, user_id: int,
                              pet_specs: Optional[dict] = None,
                              season_key: Optional[str] = None) -> dict:
    """Для каждой коллекции — сколько собрано из скольких.

    Каталог питомцев и текущий сезон принимаются снаружи: первый чат может
    расширить своими питомцами (и без них коллекция была бы уже неполной), а
    второй считается по местному времени чата, которое знает вызывающий.
    """
    из_каталога = {}

    свои_бизнесы = await db.list_user_businesses(chat_id, user_id)
    import businesses as business_catalog
    всего_бизнесов = len(business_catalog.BUSINESSES)
    из_каталога["tycoon"] = (len(свои_бизнесы), всего_бизнесов)
    прокачано = sum(1 for row in свои_бизнесы
                    if int(row["level"]) >= business_catalog.MAX_LEVEL)
    из_каталога["empire"] = (прокачано, всего_бизнесов)

    # Считаем по КАТАЛОГУ ЧАТА, а не по встроенному списку: админ мог завести
    # своих питомцев, и без них коллекция была бы уже неполной. Наградные
    # виды исключаем: их нельзя купить, а Единорог сам выдаётся за Зоопарк —
    # требовать его для этой же ачивки означало бы неразрешимый цикл.
    каталог = pet_specs or {}
    доступные = {
        key for key, spec in каталог.items()
        if not bool(getattr(spec, "by_achievement", False))
    }
    свои_питомцы = {row["pet_key"] for row in await db.list_pets(chat_id, user_id)}
    из_каталога["zoo"] = (len(свои_питомцы & доступные), len(доступные))

    # Хлам считаем по инвентарю: предметы обычные, спецэффектов у них нет, и
    # единственный их смысл — собраться полностью.
    инвентарь = {row["item_key"] for row in await db.list_inventory(chat_id, user_id)}
    из_каталога["junk"] = (len(инвентарь & set(db.JUNK_ITEM_KEYS)), len(db.JUNK_ITEM_KEYS))

    # Хлев и рыба — те же «собрать по одному виду», только их естественный
    # дом не инвентарь. Для садка важны не конкретные рыбы, а все реальные
    # редкости: хлам в сетку не попадает, поэтому требовать его было бы
    # невозможно.
    import livestock
    свои_животные = {row["animal_key"] for row in await db.list_farm_animals(chat_id, user_id)}
    виды_животных = set(livestock.BY_KEY)
    из_каталога["barn"] = (len(свои_животные & виды_животных), len(виды_животных))

    import fishing
    редкости = {spec.rarity for spec in fishing.SPECIES if not spec.is_junk}
    сетка = await db.list_net(chat_id, user_id)
    свои_редкости = {
        spec.rarity for row in сетка
        if (spec := fishing.BY_KEY.get(row["species_key"])) is not None and not spec.is_junk
    }
    из_каталога["angler"] = (len(свои_редкости & редкости), len(редкости))

    # Кукла вуду — именной сувенир в отдельной таблице, поэтому в эту
    # коллекцию не входит. Остальные результаты рецептов лежат в инвентаре
    # и не расходуются другими рецептами.
    import crafting
    крафты = {recipe.result for recipe in crafting.RECIPES if recipe.result}
    из_каталога["crafts"] = (len(инвентарь & крафты), len(крафты))

    # Оснащение хранится отдельно для каждого бизнеса. Считаем слоты, а не
    # только полностью экипированные бизнесы: так витрина честно показывает,
    # какая именно часть большого набора уже закрыта.
    все_слоты = {
        (business.key, upgrade.key)
        for business in business_catalog.BUSINESSES
        for upgrade in business_catalog.UPGRADES
    }
    свои_слоты = set()
    for business in business_catalog.BUSINESSES:
        upgrades = await db.list_business_upgrades(chat_id, user_id, business.key)
        свои_слоты.update((business.key, upgrade) for upgrade in upgrades)
    из_каталога["equipped"] = (len(свои_слоты & все_слоты), len(все_слоты))

    титулы = {row["title_key"] for row in await db.list_user_titles(chat_id, user_id)}
    if season_key:
        import seasons
        подряд = collections_meta.season_streak_keys(season_key, seasons.previous_of)
        взято = sum(1 for key in подряд
                    if any(f"season_{key}_{место}" in титулы
                           for место in range(1, seasons.PLACES + 1)))
        из_каталога["dynasty"] = (взято, collections_meta.SEASON_STREAK)
    else:
        из_каталога["dynasty"] = (0, collections_meta.SEASON_STREAK)
    return из_каталога


async def collections(chat_id: int, user_id: int, pet_specs: Optional[dict] = None,
                      season_key: Optional[str] = None) -> dict:
    прогресс = await collection_progress(chat_id, user_id, pet_specs, season_key)
    титулы = {row["title_key"] for row in await db.list_user_titles(chat_id, user_id)}
    список = []
    for c in collections_meta.COLLECTIONS:
        собрано, всего = прогресс.get(c.key, (0, 0))
        список.append({
            "key": c.key, "name": c.name, "emoji": c.emoji,
            "description": c.description, "done": собрано, "total": всего,
            # Титул за полный сбор уже на руках — значит коллекция закрыта, и
            # даже если каталог с тех пор вырос, заслуга остаётся.
            "rewarded": c.title_key in титулы,
            "title_name": c.title_name,
        })
    return {"items": список}
