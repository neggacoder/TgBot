"""Правила реста и текст-памятка о нём.

Модуль намеренно не знает ни про базу, ни про Telegram: bot.py сам достаёт
данные (стаж участника, предыдущий рест, настройки) и передаёт их сюда, а
обратно получает либо готовый текст отказа, либо None. Так правила можно
проверять тестами без базы и без сети, а bot.py (и без того огромный) не
обрастает ещё одной пачкой веток.

Все лимиты живут в настройках бота (таблица settings, см. db.py) и правятся
и через личку бота, и через веб-панель. Значение 0 у любого лимита-срока
выключает соответствующую проверку — так владелец может временно снять
ограничение, не трогая код.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

# Памятка, которую видит участник при подаче заявки и админ при одобрении.
# Плейсхолдеры подставляет render_rest_template(); текст правится через
# настройку rest_rules_template, дефолт нужен только для «свежей» базы.
DEFAULT_REST_TEMPLATE = (
    "дата начала реста: {дата_начала}\n"
    "дата окончания реста: {дата_окончания}\n"
    "причина реста: {причина}\n"
    "\n"
    "максимальная продолжительность реста составляет две недели. Если у вас возникла "
    "необходимость взять рест на более длительный срок, пожалуйста, обсудите это с "
    "владельцем и будьте готовы предоставить конкретную причину.\n"
    "\n"
    "обратите внимание, что рест не предоставляется за три дня до проведения чистки\n"
    "\n"
    "также хотим подчеркнуть, что рест недоступен для новичков, которые находятся в чате "
    "менее двух недель. нам важно увидеть вашу начальную заинтересованность в чате\n"
    "\n"
    "повторный рест становится доступным только через две недели после завершения предыдущего"
)

# Имена плейсхолдеров — показываем их админу подсказкой, когда он правит шаблон.
REST_PLACEHOLDERS = (
    "{дата_начала}",
    "{дата_окончания}",
    "{причина}",
    "{участник}",
    "{срок}",
)

REASON_FALLBACK = "не указана"

DATE_FMT = "%d.%m.%Y"
DATETIME_FMT = "%d.%m.%Y %H:%M"

# Десять лет — заведомо больше любого осмысленного лимита, но защищает от
# случайной «даты» вместо срока (01082026 днями чата не бывает).
DAYS_SETTING_MAX = 3650


def parse_days_setting(raw: Optional[str]) -> Optional[int]:
    """Число дней из пользовательского ввода; None — значение не годится.

    Проверяют одинаково оба входа (панель и личка бота), иначе «14 дней»
    отвергалось бы в одном месте и молча превращалось в дефолт в другом.
    """
    if raw is None:
        return None
    text = raw.strip()
    # isdigit() пропускает арабо-индийские и прочие юникод-цифры, которые int()
    # разберёт, а человек в настройке не узнает — сверяемся с ASCII явно.
    if not text or not all(ch in "0123456789" for ch in text):
        return None
    value = int(text)
    return value if value <= DAYS_SETTING_MAX else None


@dataclass(frozen=True)
class RestLimits:
    """Настраиваемые ограничения реста (все сроки — в днях).

    cleanup_date — дата ближайшей чистки; пока она не задана, проверка окна
    перед чисткой не работает (бот сам чистки не проводит и знать о них
    неоткуда, дату ставит админ)."""

    max_days: int = 14
    cooldown_days: int = 14
    min_member_days: int = 14
    cleanup_date: Optional[date] = None
    cleanup_block_days: int = 3


def format_dt(moment: datetime) -> str:
    """Момент времени так, как он выглядит во всех сообщениях о ресте."""
    return f"{moment.strftime(DATETIME_FMT)} UTC"


def parse_settings_date(raw: Optional[str]) -> Optional[date]:
    """Дата из настройки (ДД.ММ.ГГГГ). Мусор и пустая строка → None: настройку
    правит человек руками, и опечатка не должна ронять обработчик заявки."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), DATE_FMT).date()
    except ValueError:
        return None


def render_rest_template(
    template: Optional[str],
    *,
    start: datetime,
    end: datetime,
    reason: Optional[str],
    member: str,
    duration_text: str,
) -> str:
    """Подставляет данные реста в шаблон-памятку.

    Подстановка — заменой известных ключей, а не str.format: шаблон правит
    человек, и одинокая фигурная скобка в его тексте не должна приводить к
    исключению вместо сообщения.

    member приходит уже готовой HTML-ссылкой-упоминанием (mention_id), поэтому
    его не экранируем; причину — экранируем, её пишет сам участник.
    """
    values = {
        "{дата_начала}": format_dt(start),
        "{дата_окончания}": format_dt(end),
        "{причина}": html.escape(reason) if reason else REASON_FALLBACK,
        "{участник}": member,
        "{срок}": duration_text,
    }
    text = template if template and template.strip() else DEFAULT_REST_TEMPLATE
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def _plural_days(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день"
    if days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        return f"{days} дня"
    return f"{days} дней"


def check_rest_rules(
    *,
    now: datetime,
    duration: timedelta,
    first_seen_at: Optional[datetime],
    last_rest_end: Optional[datetime],
    limits: RestLimits,
) -> Optional[str]:
    """Проверяет заявку на рест по правилам чата.

    Возвращает готовый текст отказа (его бот отправляет участнику) или None,
    если заявку можно оформлять. Правила действуют одинаково для всех, включая
    администраторов и владельца.

    Нехватка данных проверку не включает, а выключает: если бот ещё не видел,
    когда участник пришёл в чат (first_seen_at=None), или прошлых рестов не
    было (last_rest_end=None) — придираться не к чему.
    """
    if limits.max_days > 0 and duration > timedelta(days=limits.max_days):
        return (
            f"⚠️ Максимальная продолжительность реста — {_plural_days(limits.max_days)}.\n\n"
            "Если рест нужен на больший срок, обсудите это с владельцем и подготовьте "
            "конкретную причину."
        )

    if limits.min_member_days > 0 and first_seen_at is not None:
        available_at = first_seen_at + timedelta(days=limits.min_member_days)
        if now < available_at:
            return (
                f"⚠️ Рест недоступен новичкам: в чате нужно пробыть хотя бы "
                f"{_plural_days(limits.min_member_days)}.\n\n"
                f"Вы сможете взять рест с {format_dt(available_at)}."
            )

    if limits.cooldown_days > 0 and last_rest_end is not None:
        available_at = last_rest_end + timedelta(days=limits.cooldown_days)
        if now < available_at:
            return (
                f"⚠️ Повторный рест доступен только через {_plural_days(limits.cooldown_days)} "
                f"после окончания предыдущего.\n\n"
                f"Прошлый рест закончился {format_dt(last_rest_end)}, "
                f"следующий можно взять с {format_dt(available_at)}."
            )

    if limits.cleanup_date is not None and limits.cleanup_block_days > 0:
        block_start = limits.cleanup_date - timedelta(days=limits.cleanup_block_days)
        if block_start <= now.date() <= limits.cleanup_date:
            return (
                f"⚠️ Рест не предоставляется за {_plural_days(limits.cleanup_block_days)} "
                f"до чистки (чистка — {limits.cleanup_date.strftime(DATE_FMT)}).\n\n"
                "Подайте заявку после неё."
            )

    return None
