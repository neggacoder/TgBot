"""Панель «чем заняться» — каталог занятий и её отрисовка.

Кулдаунов в боте два десятка, они лежат в шести модулях и ничем не связаны
между собой. Чтобы понять, что сейчас можно сделать, человек вслепую перебирал
команды и раз за разом получал отказ. Панель отвечает на этот вопрос одним
сообщением.

Здесь только то, что не ходит в базу: из чего состоит панель и как она
выглядит. Сама готовность собирается в bot.py (collect_activity_states) — там,
где живут кулдауны и запросы. Такое разделение уже принято в боте у fishing.py,
robbery.py и bosses.py, и оно же позволяет проверить раскладку тестами без
базы и без aiogram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional


@dataclass(frozen=True)
class Activity:
    """Занятие: чем оно является для человека, а не как считается.

    command — то слово, которым его зовут. Оно печатается в <code>, чтобы в
    Telegram копировалось тапом; ради этого же оно пишется точно так, как его
    понимает бот, а не «красиво».
    """
    key: str
    emoji: str
    title: str
    command: str


# Порядок объявления — порядок показа внутри секции «недоступно»; готовые и
# ждущие сортируются иначе (см. render_panel). Список денежного цикла: то, что
# человек делает ради монет и делает регулярно.
CATALOG: tuple[Activity, ...] = (
    Activity("daily_bonus",  "🎁", "бонус",         "бонус"),
    Activity("side_job",     "💼", "подработка",    "подработка"),
    Activity("profession",   "👷", "работа",        "!работа"),
    Activity("fishing",      "🎣", "рыбалка",       "рыбалка"),
    Activity("treasure",     "⛏",  "клад",          "клад"),
    Activity("farm",         "🌾", "ферма",         "ферма"),
    Activity("business",     "🏢", "бизнес собрать", "бизнес собрать"),
    Activity("robbery",      "🥷", "ограбить",      "!ограбить"),
    Activity("raid",         "💥", "налёт",         "налёт"),
    Activity("hat",          "🎩", "шапка",         "шапка"),
)

BY_KEY: dict[str, Activity] = {a.key: a for a in CATALOG}


@dataclass
class ActivityState:
    """Что с занятием у конкретного человека прямо сейчас.

    Состояния ровно три, и это не педантизм: «ещё не время» и «тебе нельзя»
    требуют совершенно разных действий. В первом случае надо ждать, во втором —
    что-то сделать: устроиться на работу, купить бизнес, откупиться от надзора.
    Свали их в одну кучу — и панель начнёт отвечать «когда» там, где вопрос
    «как».

      * blocked не пуст — нельзя вовсе, и там же написано почему;
      * left не пуст — ждать столько;
      * ни того, ни другого — готово.

    wait_note заменяет собой срок у того, чья готовность измеряется не
    временем: у бизнеса копится сумма, и «через сколько» у него нет.
    """
    activity: Activity
    left: Optional[timedelta] = None
    blocked: Optional[str] = None
    wait_note: Optional[str] = None

    @property
    def ready(self) -> bool:
        return not self.blocked and self.left is None and self.wait_note is None


def _code(text: str) -> str:
    return f"<code>{text}</code>"


# Сколько занятий влезает в подсказку под отказом. Четыре — не круглое число:
# подсказка приписывается к чужому сообщению и не должна быть длиннее него,
# иначе отказ начнёт тонуть в совете.
HINT_MAX_ITEMS = 4


def render_hint(
    states: list[ActivityState],
    *,
    exclude: Optional[str] = None,
    format_left,
    max_items: int = HINT_MAX_ITEMS,
) -> str:
    """Строка «а сейчас доступно вот это» — приписка к отказу. Пусто, если
    сказать нечего.

    exclude — занятие, которое человек только что и попробовал. Предлагать его
    же в ответ на «слишком рано» — издевательство.

    Когда готового нет вообще, показываем ближайшее по времени. Это и есть
    ответ на вопрос, ради которого человек долбится в команду: не «нельзя», а
    «через сколько станет можно».
    """
    доступные = [s for s in states if s.ready and s.activity.key != exclude]
    if доступные:
        головы = доступные[:max_items]
        плитки = " · ".join(_code(s.activity.command) for s in головы)
        хвост = (f" …и ещё {len(доступные) - len(головы)}"
                 if len(доступные) > len(головы) else "")
        return f"🎯 Сейчас доступно: {плитки}{хвост}"

    ждущие = [s for s in states
              if s.left is not None and s.activity.key != exclude]
    if ждущие:
        ближайшее = min(ждущие, key=lambda s: s.left)
        return (f"🎯 Ближайшее — {_code(ближайшее.activity.command)} "
                f"через {format_left(ближайшее.left)}")
    return ""


def render_panel(
    states: list[ActivityState],
    *,
    divider: str,
    format_left,
    frozen_note: Optional[str] = None,
) -> str:
    """Текст панели. format_left — как показывать timedelta (бот передаёт свой
    format_duration_ru, чтобы срок выглядел как везде в боте).

    Секция, в которой нечего показать, не печатается совсем: заголовок «Ждём:»
    без единой строки под ним читается как поломка.
    """
    lines = ["🎯 <b>Чем заняться</b>", divider]
    if frozen_note:
        lines.append(frozen_note)

    ready = [s for s in states if s.ready]
    waiting = [s for s in states if not s.ready and not s.blocked]
    blocked = [s for s in states if s.blocked]

    if ready:
        # Одной строкой, а не столбиком: слово «готово» уже сказано заголовком
        # секции, и десять отдельных строк заняли бы пол-экрана ради нуля
        # новой информации.
        плитки = " · ".join(f"{s.activity.emoji} {_code(s.activity.command)}" for s in ready)
        lines.append("")
        lines.append(f"✅ <b>Готово ({len(ready)}):</b> {плитки}")

    if waiting:
        # По возрастанию срока: панель открывают, чтобы понять, чего ждать
        # ближайшим, а не чтобы прочитать список целиком. Занятия без срока
        # (копилка бизнеса) — в конец, сравнивать их со временем нечем.
        without_time = [s for s in waiting if s.left is None]
        with_time = sorted((s for s in waiting if s.left is not None),
                           key=lambda s: s.left)
        lines.append("")
        lines.append("⏳ <b>Ждём:</b>")
        for s in with_time:
            lines.append(f"{s.activity.emoji} {s.activity.title} — {format_left(s.left)}")
        for s in without_time:
            lines.append(f"{s.activity.emoji} {s.activity.title} — {s.wait_note}")

    if blocked:
        # Последними и всегда с причиной: строка «нельзя» без «что делать» —
        # тот самый тупик, ради ухода от которого панель и заводилась.
        lines.append("")
        lines.append("🚫 <b>Недоступно:</b>")
        for s in blocked:
            lines.append(f"{s.activity.emoji} {s.activity.title} — {s.blocked}")

    return "\n".join(lines)
