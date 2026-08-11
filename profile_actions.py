"""Профиль и топы: собрать и вернуть. Ничего не отправляет.

Шестой модуль того же устройства. В отличие от предыдущих, здесь нет действий
— только чтение: карточка человека и таблицы лучших.

Главное правило: границы периодов НЕ считаются заново. Неделя и месяц берутся
из db.period_start_day — общей для всего бота, — потому что однажды профиль и
топ уже разошлись ровно на этом: профиль считал неделю с понедельника, топ с
субботы, и человек видел «25 за неделю» в одном месте и «125» в другом.

Имена людей отдаём как есть из реестра бота: панель не ходит в Telegram за
именами (Bot API этого и не умеет для чужих), а known_users помнит последнее
виденное.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import db
import farm_actions
import fishing
import professions

logger = logging.getLogger(__name__)


def _name(row: dict) -> str:
    """Как показать человека. Юзернейм — запасной вариант, id — последний."""
    return (row.get("full_name") or row.get("username")
            or f"id {row.get('user_id') or '—'}")


async def _names(chat_id: int, ids: list[int]) -> dict[int, dict]:
    """Имена пачкой: строчка топа без имени — просто число, а по одному
    запросу на строку топ из десяти превратился бы в десять походов в базу."""
    итог: dict[int, dict] = {}
    for uid in ids:
        try:
            row = await db.get_known_user(chat_id, uid)
        except Exception as exc:
            logger.warning("_names: %s", exc)
            row = None
        итог[uid] = row or {"user_id": uid}
    return итог


# ----------------------------------------------------------------------------
# Профиль
# ----------------------------------------------------------------------------
async def profile(chat_id: int, user_id: int) -> dict:
    """Карточка участника: кто, сколько написал, чем владеет, чем занят.

    Всё, что не прочиталось, просто отсутствует: профиль — витрина, и упавший
    запрос по питомцам не должен уносить с собой сообщения и монеты.
    """
    известен = await db.get_known_user(chat_id, user_id) or {"user_id": user_id}
    stats = await db.get_message_stats(chat_id, user_id) or {}
    сообщений = int(stats.get("message_count") or 0)

    async def безопасно(корутина, запасное):
        try:
            return await корутина
        except Exception as exc:
            logger.warning("profile: %s", exc)
            return запасное

    место = await безопасно(db.get_message_rank(chat_id, user_id), None) if stats else None
    актив = await безопасно(db.get_activity_breakdown(chat_id, user_id), {})
    wallet = await безопасно(db.get_wallet(chat_id, user_id), {}) or {}
    card = await безопасно(db.get_profile_card(chat_id, user_id), {}) or {}
    ачивки = await безопасно(db.get_achievements(chat_id, user_id), []) or []
    клан = await безопасно(db.get_user_clan(chat_id, user_id), None)
    рыбалка = await безопасно(db.get_fishing_stats(chat_id, user_id), {}) or {}
    работа = await безопасно(db.get_profession_stats(chat_id, user_id), {}) or {}
    бизнесы = await безопасно(db.list_user_businesses(chat_id, user_id), []) or []
    питомцы = await безопасно(db.list_pets(chat_id, user_id), []) or []

    монеты = int(wallet.get("coins") or 0)
    звёзд, в_звезде, на_звезду = farm_actions.farm_star_progress(
        int(wallet.get("total_farms") or 0))

    профессия = работа.get("profession_key")
    prof = professions.PROFESSIONS.get(профессия) if профессия else None
    вид_рыбы = fishing.BY_KEY.get(рыбалка.get("best_weight_species") or "")

    return {
        "user_id": user_id,
        "name": _name(известен),
        "username": известен.get("username"),
        "first_seen": (stats.get("first_seen_at").isoformat()
                       if stats.get("first_seen_at") else None),
        "last_message": (stats.get("last_message_at").isoformat()
                         if stats.get("last_message_at") else None),
        "messages": сообщений,
        "rank": место,
        # Имена столбцов — как их отдаёт db.get_activity_breakdown, а не как
        # хотелось бы их назвать. Так API профиля и Telegram-карточка остаются в
        # одинаковых периодах: 24 часа, текущий день, неделя и месяц.
        "activity": {
            "last_24h": int((актив or {}).get("last_24h_count") or 0),
            "day": int((актив or {}).get("today_count") or 0),
            "week": int((актив or {}).get("week_count") or 0),
            "month": int((актив or {}).get("month_count") or 0),
        },
        "coins": монеты,
        "stars": звёзд,
        "star_progress": {"have": в_звезде, "need": на_звезду},
        "title": card.get("active_title"),
        "achievements": len(ачивки),
        "clan": (клан or {}).get("name"),
        "clan_role": (клан or {}).get("role"),
        "fishing": {
            "catches": int(рыбалка.get("total_catches") or 0),
            "best_weight": int(рыбалка.get("best_weight") or 0),
            "best_weight_text": fishing.format_weight(int(рыбалка.get("best_weight") or 0)),
            "best_species": вид_рыбы.name if вид_рыбы else None,
        },
        "work": {
            "profession": профессия,
            "name": prof["name"] if prof else None,
            "emoji": prof["emoji"] if prof else None,
            "level": int(работа.get("prof_level") or 0),
            "shifts": int(работа.get("total_shifts") or 0),
            "streak": int(работа.get("work_streak") or 0),
        },
        "businesses": len(бизнесы),
        "pets": len(питомцы),
    }


# ----------------------------------------------------------------------------
# Топы
# ----------------------------------------------------------------------------
# Каждый топ — что показать, откуда взять и как назвать значение. Список, а не
# ветвление по строке: добавить топ должно означать добавить строку, а не
# править три места (обработчик, экран и права).
TOPS = {
    "messages": {"title": "Сообщения", "emoji": "💬", "unit": "сообщ.",
                 "command": "top"},
    "week": {"title": "Сообщения за неделю", "emoji": "🗓", "unit": "сообщ.",
             "command": "top"},
    "coins": {"title": "Монеты", "emoji": "💰", "unit": "i¢", "command": "farm_top"},
    "fishing": {"title": "Рыбалка: рекорд по весу", "emoji": "🎣", "unit": "",
                "command": "fishing_top"},
    # Показываем УРОВЕНЬ, потому что по нему топ и отсортирован (см.
    # db.list_profession_top: ORDER BY prof_level, prof_xp). Раньше здесь
    # стояли смены — столбца с ними запрос не отдаёт вовсе, и у всех
    # честно выходил ноль, а порядок строк не сходился с показанным числом.
    "work": {"title": "Работа", "emoji": "💼", "unit": "ур.",
             "command": "prof_top"},
    "achievements": {"title": "Достижения", "emoji": "🏆", "unit": "шт.",
                     "command": "top"},
}


async def top(chat_id: int, kind: str, limit: int = 10) -> dict:
    """Одна таблица лучших. Неизвестный вид — пустая таблица, а не ошибка:
    экран рисует то, что знает, а не падает целиком."""
    описание = TOPS.get(kind)
    if описание is None:
        return {"kind": kind, "rows": [], "title": "", "unit": ""}

    строки: list[dict] = []
    if kind == "messages":
        rows, _всего = await db.list_top_messages(chat_id, limit=limit)
        строки = [{"user_id": r["user_id"], "value": int(r["message_count"] or 0)}
                  for r in rows]
    elif kind == "week":
        начало = db.period_start_day("week")
        rows, _всего = await db.list_top_messages_period(chat_id, начало, limit=limit)
        строки = [{"user_id": r["user_id"], "value": int(r.get("message_count") or 0)}
                  for r in rows]
    elif kind == "coins":
        rows, _всего = await db.list_coins_top(chat_id, limit=limit)
        строки = [{"user_id": r["user_id"], "value": int(r.get("coins") or 0)}
                  for r in rows]
    elif kind == "fishing":
        rows = await db.list_fishing_weight_top(chat_id, limit=limit)
        for r in rows:
            вид = fishing.BY_KEY.get(r.get("best_weight_species") or "")
            строки.append({
                "user_id": r["user_id"],
                "value": int(r.get("best_weight") or 0),
                "text": fishing.format_weight(int(r.get("best_weight") or 0)),
                "note": (f"{вид.emoji} {вид.name}" if вид else None),
            })
    elif kind == "work":
        rows = await db.list_profession_top(chat_id, limit=limit)
        for r in rows:
            prof = professions.PROFESSIONS.get(r.get("profession_key") or "")
            заработано = int(r.get("total_earned") or 0)
            строки.append({
                "user_id": r["user_id"],
                "value": int(r.get("prof_level") or 0),
                "note": (f"{prof['emoji']} {prof['name']}" if prof else None)
                        + (f" · {заработано:,} i¢".replace(",", " ") if заработано else ""),
            })
    else:
        rows = await db.get_achievements_top(chat_id, limit=limit)
        строки = [{"user_id": r["user_id"], "value": int(r.get("total") or 0)}
                  for r in rows]

    имена = await _names(chat_id, [s["user_id"] for s in строки])
    for место, строка in enumerate(строки, 1):
        строка["place"] = место
        строка["name"] = _name(имена.get(строка["user_id"], {}))
        строка["username"] = имена.get(строка["user_id"], {}).get("username")
    return {"kind": kind, "title": описание["title"], "emoji": описание["emoji"],
            "unit": описание["unit"], "rows": строки}


async def tops(chat_id: int, limit: int = 10) -> dict:
    """Все таблицы разом: экран показывает их вкладками, и по запросу на
    каждую он бы моргал при переключении."""
    return {
        "now": datetime.utcnow().isoformat(),
        "kinds": [{"key": k, "title": v["title"], "emoji": v["emoji"]}
                  for k, v in TOPS.items()],
        "tables": {k: await top(chat_id, k, limit) for k in TOPS},
    }
