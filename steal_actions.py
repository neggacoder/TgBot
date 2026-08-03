"""Медвежатник: украсть один предмет из чужого инвентаря. Ничего не отправляет.

Десятый модуль того же устройства. Здесь он нужнее прочих: у медвежатника
правила устроены тоньше, чем кажется, и всё тонкое — про ПОРЯДОК. Списать
что-то не в тот момент значит либо подарить бесплатную разведку, либо сжечь
чужую защиту ни за что.

ЧЕМ ПОРЯДОК ВАЖЕН, по шагам.

Сигнализация проверяется ПОСЛЕ проверки «есть ли у жертвы эта вещь». Иначе
опечатка в ключе сжигала бы чужую сигнализацию — за то, что вор промахнулся
мимо несуществующего предмета.

Медвежатник тратится ВСЕГДА, даже когда сигнализация сорвала дело. Иначе им
бесплатно проверяли бы чужие закрома: не вышло — инструмент цел, пробуем
следующего. И защита выдавала бы сама себя.

Сигнализация при ПРОМАХЕ остаётся у жертвы. Она стоит 20 000 и глушит кражу с
шансом; списывать её за несделанную работу значило бы продавать один бросок
кубика.

Слепок ключа тратится ТОЛЬКО на подтверждённой краже. Он сокращает откат, и
на ветке «предмет успели потратить, пока мы вскрывали» сгорел бы зря.

И отдельно: сколько ждать до следующего дела, считает ОДНА функция. Отметка
пишется задним числом (слепок сдвигает её на четверть отката), и вторая
реализация этой арифметики означала бы, что откат разный в зависимости от
того, откуда пришли — из чата или с сайта.

Бросок кубика принимается снаружи (`roll`) — ровно затем, чтобы обе ветки
сигнализации можно было проверить, а не ловить их случайностью.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

import black_market
import chat_events
import db
import farm_actions
import shop_effects

logger = logging.getLogger(__name__)

KEY = "medvezhatnik"
COOLDOWN = timedelta(hours=10)


def cooldown_key(chat_id: int, user_id: int) -> str:
    return f"steal:{chat_id}:{user_id}"


@dataclass
class StealResult:
    ok: bool
    error: str = ""
    # Что случилось: "stolen" — унёс, "blocked" — сорвала сигнализация,
    # "gone" — предмет успели потратить, пока вскрывали.
    outcome: str = ""
    item_key: str = ""
    item_name: str = ""
    target_id: int = 0
    # Сигнализация была, но не сработала. Жертве об этом говорят обязательно:
    # молчание после промаха выглядит как сломанный предмет.
    signal_missed: bool = False
    signal_burned: bool = False
    slepok_used: bool = False
    user_id: int = 0


async def cooldown_left(chat_id: int, user_id: int,
                        now: Optional[datetime] = None) -> Optional[timedelta]:
    """Сколько ещё ждать, или None — можно идти на дело."""
    row = await db.get_data(cooldown_key(chat_id, user_id))
    if not row or not row.get("data_value"):
        return None
    try:
        последний = datetime.fromisoformat(row["data_value"])
    except (ValueError, TypeError):
        return None
    прошло = (now or datetime.utcnow()) - последний
    return None if прошло >= COOLDOWN else COOLDOWN - прошло


async def mark_used(chat_id: int, user_id: int, cut: float = 0.0,
                    now: Optional[datetime] = None) -> None:
    """Отмечает, что медвежатник сработал.

    cut — доля отката, которую снимает слепок ключа: отметка пишется задним
    числом, а не заводится отдельный заряд. Механика та же, что у «тачки для
    отхода» у ограбления — двух механизмов на одну идею быть не должно.
    """
    момент = (now or datetime.utcnow()) - COOLDOWN * cut
    await db.set_data(cooldown_key(chat_id, user_id), момент.isoformat(),
                      updated_by=user_id)


async def _штук(chat_id: int, user_id: int) -> dict[str, int]:
    return {i["item_key"]: i["quantity"] for i in await db.list_inventory(chat_id, user_id)}


async def state(chat_id: int, user_id: int) -> dict:
    """Что показать на экране до дела: есть ли инструмент и когда можно.

    Чужой инвентарь СЮДА НЕ ПОПАДАЕТ, и это не забывчивость. В чате вор
    обязан знать ключ заранее; показать список чужих вещей значило бы выдать
    даром то, за чем существует отдельный платный предмет «Досье», — и
    заодно превратить медвежатник из риска в выбор из меню.
    """
    свои = await _штук(chat_id, user_id)
    ждать = await cooldown_left(chat_id, user_id)
    инструмент = shop_effects.BY_KEY[KEY]
    комендантский = chat_events.flag(await farm_actions.active_event(chat_id),
                                     chat_events.F_NO_ROBBERY)
    return {
        "has_tool": свои.get(KEY, 0) > 0,
        "tool_name": инструмент.name,
        "tool_emoji": инструмент.emoji,
        "tool_price": инструмент.price,
        "cooldown_hours": int(COOLDOWN.total_seconds() // 3600),
        "wait_seconds": int(ждать.total_seconds()) if ждать else 0,
        "curfew": bool(комендантский),
        "signal_chance": black_market.SIGNAL_BLOCK_CHANCE,
        "slepok_cut": black_market.STEAL_COOLDOWN_CUT,
        "has_slepok": свои.get(black_market.SLEPOK_KEY, 0) > 0,
    }


async def loot(chat_id: int, user_id: int, target_id: int) -> list[dict]:
    """Что можно унести у выбранного человека: название, ключ и сколько штук.

    Список ОТКРЫВАЕТСЯ ТОЛЬКО ВЛАДЕЛЬЦУ ИНСТРУМЕНТА. Иначе он превратился бы в
    бесплатный просмотр чужих карманов для всего чата — а это уже не кража, а
    слежка, и покупать для неё ничего не нужно.

    Из списка выброшены две вещи, и обе намеренно.

    НАГРАДЫ — их всё равно не украсть (see is_reward), и показывать в списке
    добычи то, что не берётся, значит звать на заведомо пустой заход.

    СИГНАЛИЗАЦИЯ — потому что защита не должна выдавать сама себя. Увидев её в
    списке, вор просто не пошёл бы к тем, у кого она есть, и предмет за 20 000
    перестал бы что-либо значить: его ценность ровно в том, что о нём узнают
    постфактум. Ровно это же соображение стоит в правиле «инструмент горит
    даже на сорванном деле».
    """
    свои = await _штук(chat_id, user_id)
    if свои.get(KEY, 0) <= 0:
        return []
    добыча = []
    for предмет in await db.list_inventory(chat_id, target_id):
        ключ = предмет["item_key"]
        if ключ == black_market.SIGNAL_KEY or shop_effects.is_reward(ключ):
            continue
        if int(предмет.get("quantity") or 0) <= 0:
            continue
        добыча.append({
            "key": ключ,
            "name": предмет.get("name") or ключ,
            "emoji": предмет.get("emoji") or "",
            "quantity": int(предмет["quantity"]),
        })
    добыча.sort(key=lambda п: п["name"].casefold())
    return добыча


async def steal(chat_id: int, user_id: int, target_id: Optional[int],
                item_key: str, *,
                roll: Optional[Callable[[], int]] = None) -> StealResult:
    """Кража одного предмета. Списывает всё сама; отправка сообщений — снаружи.

    roll — бросок кубика сигнализации, отдельным параметром: со встроенным
    random обе её ветки проверялись бы монеткой.
    """
    бросить = roll or (lambda: random.randint(1, 100))
    ключ = (item_key or "").strip().casefold()
    инструмент = shop_effects.BY_KEY[KEY]

    свои = await _штук(chat_id, user_id)
    if свои.get(KEY, 0) <= 0:
        return StealResult(False, f"У вас нет «{инструмент.name}» — он продаётся "
                                  f"в магазине за {инструмент.price} i¢.", user_id=user_id)

    if chat_events.flag(await farm_actions.active_event(chat_id), chat_events.F_NO_ROBBERY):
        return StealResult(False, "Комендантский час — на улицах патрули. Не сегодня.",
                           user_id=user_id)

    ждать = await cooldown_left(chat_id, user_id)
    if ждать is not None:
        часов = int(COOLDOWN.total_seconds() // 3600)
        return StealResult(False, f"Замки ещё не остыли — на дело можно раз в {часов} ч.",
                           user_id=user_id)

    if not target_id:
        return StealResult(False, "Не выбрана цель.", user_id=user_id)
    if target_id == user_id:
        return StealResult(False, "У себя красть нечего.", user_id=user_id)
    if not ключ:
        return StealResult(False, "Не сказано, что красть.", user_id=user_id)
    if shop_effects.is_reward(ключ):
        return StealResult(False, "Награды и предметы за достижения не крадутся — "
                                  "это чужая заслуга.", user_id=user_id)

    чужие = await _штук(chat_id, target_id)
    if чужие.get(ключ, 0) <= 0:
        # Отказ ДО списания чего бы то ни было: опечатка в ключе не должна
        # стоить ни инструмента, ни чужой сигнализации.
        return StealResult(False, "У этого человека нет такого предмета.",
                           target_id=target_id, item_key=ключ, user_id=user_id)

    signal_missed = False
    if чужие.get(black_market.SIGNAL_KEY, 0) > 0:
        if бросить() <= black_market.SIGNAL_BLOCK_CHANCE:
            # Сорвалось: горят оба — и инструмент, и сигнализация. Инструмент
            # потому, что иначе им бесплатно щупали бы чужие закрома; защита
            # потому, что она свою работу сделала.
            await db.remove_inventory_item(chat_id, user_id, KEY, 1)
            await db.remove_inventory_item(chat_id, target_id, black_market.SIGNAL_KEY, 1)
            await mark_used(chat_id, user_id)
            return StealResult(True, outcome="blocked", item_key=ключ,
                               target_id=target_id, signal_burned=True, user_id=user_id)
        # Промах — сигнализация ОСТАЁТСЯ у жертвы: она стоит 20 000 и не
        # должна тратиться за несделанную работу.
        signal_missed = True

    await db.remove_inventory_item(chat_id, user_id, KEY, 1)
    await mark_used(chat_id, user_id)

    if not await db.remove_inventory_item(chat_id, target_id, ключ, 1):
        # Предмет успели потратить, пока вскрывали. Инструмент уже сгорел, а
        # вот слепок ниже — нет: тратить его за несостоявшуюся кражу нельзя.
        return StealResult(True, outcome="gone", item_key=ключ, target_id=target_id,
                           signal_missed=signal_missed, user_id=user_id)

    await db.add_inventory_item(chat_id, user_id, ключ, 1)

    # Слепок — только теперь, когда кража точно удалась.
    slepok = False
    if (await _штук(chat_id, user_id)).get(black_market.SLEPOK_KEY, 0) > 0:
        await db.remove_inventory_item(chat_id, user_id, black_market.SLEPOK_KEY, 1)
        await mark_used(chat_id, user_id, cut=black_market.STEAL_COOLDOWN_CUT)
        slepok = True

    товар = await db.get_shop_item(chat_id, ключ)
    return StealResult(True, outcome="stolen", item_key=ключ,
                       item_name=(товар["name"] if товар else ключ),
                       target_id=target_id, signal_missed=signal_missed,
                       slepok_used=slepok, user_id=user_id)
