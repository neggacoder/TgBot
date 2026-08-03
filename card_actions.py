"""Анкета: звание, девиз, город, «о себе», гражданство, видимость.

Одиннадцатый модуль того же устройства. Правил тут немного, и все они про
ОДНО — про длину и про то, чем пустая строка отличается от снятого поля.

Длины разъезжаются легче всего. В чате «+звание» отбивает текст длиннее
тридцати символов, а поле в базе шире; напиши сайт своё число — и одно и то же
звание в чате не принимается, а с сайта проходит. Поэтому пределы объявлены
здесь, а бот берёт их отсюда.

Пустая строка — это СНЯТЬ, а не «сохранить пустоту». В чате для снятия есть
отдельная команда («-девиз»), на сайте её роль играет пустое поле: человек
стирает текст и уходит. Записать пустую строку значило бы оставить в анкете
строку-призрак, которую видно только по пустому месту.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import db

logger = logging.getLogger(__name__)

# Пределы длины. Общие с ботом: разъедься они — и текст, который в чате не
# принимают, спокойно проходил бы с сайта.
TITLE_MAX = 30          # звание
MOTTO_MAX = 100         # девиз
CITY_MAX = 64
ABOUT_MAX = 1000

# Поле → (предел, как называется в отказе). Список закрытый: всё, чего здесь
# нет, экран править не может, и это не забывчивость — остальные поля карточки
# (закреплённый предмет, питомец, рыба) ставятся своими экранами, где рядом
# есть из чего выбирать.
ПОЛЯ = {
    "title": (TITLE_MAX, "Звание"),
    "motto": (MOTTO_MAX, "Девиз"),
    "city": (CITY_MAX, "Город"),
    "about": (ABOUT_MAX, "«О себе»"),
}


@dataclass
class CardResult:
    ok: bool
    error: str = ""
    field: str = ""
    value: str = ""
    cleared: bool = False


async def state(chat_id: int, user_id: int) -> dict:
    """Анкета как её показывает и правит экран."""
    card = await db.get_profile_card(chat_id, user_id) or {}
    return {
        "title": card.get("title") or "",
        "motto": card.get("motto") or "",
        "city": card.get("city") or "",
        "about": card.get("about_text") or "",
        "gender": card.get("gender") or "",
        "citizen": bool(card.get("is_citizen")),
        # Видимость: NULL в базе означает «видна». Считать её скрытой по
        # умолчанию значило бы спрятать анкеты всем, кто никогда её не трогал.
        "visible": card.get("anketa_visible") is None or bool(card.get("anketa_visible")),
        "limits": {имя: предел for имя, (предел, _) in ПОЛЯ.items()},
    }


async def set_field(chat_id: int, user_id: int, field: str,
                    value: Optional[str]) -> CardResult:
    if field not in ПОЛЯ:
        return CardResult(False, "Такого поля в анкете нет.")
    предел, название = ПОЛЯ[field]
    текст = (value or "").strip()

    if not текст:
        # Пустое поле — это снять. Записать пустую строку значило бы оставить
        # в анкете строку-призрак: места она занимает столько же, а прочесть
        # в ней нечего.
        await {
            "title": db.clear_title, "motto": db.clear_motto,
            "city": db.clear_city, "about": db.clear_about,
        }[field](chat_id, user_id)
        return CardResult(True, field=field, cleared=True)

    if len(текст) > предел:
        return CardResult(False, f"{название}: слишком длинно, максимум {предел} символов.")

    await {
        "title": db.set_title, "motto": db.set_motto,
        "city": db.set_city, "about": db.set_about,
    }[field](chat_id, user_id, текст)
    return CardResult(True, field=field, value=текст)


async def set_citizen(chat_id: int, user_id: int, on: bool) -> CardResult:
    await db.set_citizenship(chat_id, user_id, on)
    return CardResult(True, field="citizen", value="1" if on else "")


async def set_visible(chat_id: int, user_id: int, on: bool) -> CardResult:
    """Видимость анкеты для остальных. Скрытая анкета остаётся видна себе —
    иначе человек не смог бы её править вслепую."""
    await db.set_anketa_visibility(chat_id, user_id, on)
    return CardResult(True, field="visible", value="1" if on else "")
