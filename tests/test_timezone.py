"""Часовой пояс показа времени (tz_settings).

Разбор общий у чата («часовой пояс Москва») и у панели (поле «timezone»), и
именно поэтому он вынесен в отдельный модуль: разъехавшись, они начали бы
принимать разные значения — на сайте сохранилось бы, а в чате отвергалось.

Главное свойство, которое здесь закреплено: настройка меняет ТОЛЬКО показ.
Хранение и расчёты остаются в UTC, иначе смена пояса сдвигала бы уже идущие
сроки мутов и варнов.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

import pytest

import tz_settings


# --- разбор ввода ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Europe/Moscow", "Europe/Moscow"),
    ("мск", "Europe/Moscow"),
    ("МСК", "Europe/Moscow"),
    ("Москва", "Europe/Moscow"),
    ("москве", "Europe/Moscow"),
    ("Алматы", "Asia/Almaty"),
    ("Asia/Tokyo", "Asia/Tokyo"),
    ("utc", "UTC"),
    ("+0", "UTC"),
])
def test_понятные_человеку_названия_приводятся_к_ключу_зоны(raw, expected):
    assert tz_settings.parse_timezone(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("+3", "UTC+3"),
    ("-5", "UTC-5"),
    ("UTC+03:00", "UTC+3"),
    ("gmt-8", "UTC-8"),
    ("+5:30", "UTC+5:30"),
])
def test_смещения_принимаются_и_нормализуются(raw, expected):
    assert tz_settings.parse_timezone(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Марс/Олимп", "+30", "абракадабра", None])
def test_несуществующая_зона_отвергается(raw):
    """Проверять надо на ВВОДЕ: попав в базу, такое значение ломало бы каждый
    показ времени, а не одну команду."""
    assert tz_settings.parse_timezone(raw) is None


# --- подписи ---------------------------------------------------------------

def test_у_популярных_зон_короткая_подпись():
    assert tz_settings.timezone_label("Europe/Moscow") == "МСК"
    assert tz_settings.timezone_label("UTC") == "UTC"


def test_незнакомая_зона_подписывается_смещением():
    label = tz_settings.timezone_label("Asia/Tokyo")
    assert label.startswith("UTC+"), label


def test_смещение_подписывается_само_собой():
    assert tz_settings.timezone_label("UTC+5") == "UTC+5"


# --- перевод времени -------------------------------------------------------

def test_наивное_время_считается_utc_и_переводится():
    """Весь бот пишет в базу datetime.utcnow() — наивное UTC. Если бы to_zone
    считал его локальным, время уезжало бы на смещение дважды."""
    moment = datetime(2026, 7, 25, 14, 30)
    moscow = tz_settings.to_zone(moment, "Europe/Moscow")
    assert (moscow.hour, moscow.minute) == (17, 30)


def test_осведомлённое_время_просто_переводится():
    moment = datetime(2026, 7, 25, 14, 30, tzinfo=dt_timezone.utc)
    assert tz_settings.to_zone(moment, "UTC+5").hour == 19


def test_utc_оставляет_время_как_есть():
    moment = datetime(2026, 7, 25, 14, 30)
    assert tz_settings.to_zone(moment, "UTC").hour == 14
    assert tz_settings.to_zone(moment, None).hour == 14


def test_около_полуночи_меняется_дата():
    """Ради этого дата тоже переводится, а не печатается как есть: 23:30 UTC —
    это уже следующий день в Москве."""
    moment = datetime(2026, 7, 25, 23, 30)
    assert tz_settings.to_zone(moment, "Europe/Moscow").strftime("%d.%m.%Y") == "26.07.2026"


def test_разница_между_моментами_не_зависит_от_зоны():
    """Смена пояса не должна сдвигать уже идущие сроки — только их показ."""
    a, b = datetime(2026, 7, 25, 14, 0), datetime(2026, 7, 25, 15, 0)
    for zone in ("UTC", "Europe/Moscow", "UTC-8", "Asia/Tokyo"):
        left = tz_settings.to_zone(b, zone) - tz_settings.to_zone(a, zone)
        assert left == timedelta(hours=1), zone


def test_голая_дата_возвращается_как_есть():
    """У datetime.date нет ни времени суток, ни tzinfo.

    Переводить её бессмысленно, а попытка это сделать раньше падала
    AttributeError — и роняла «не в норме», «чистка по норме» и «участники за
    неделю», где границы периода считаются именно датами.
    """
    from datetime import date

    day = date(2026, 7, 25)
    for zone in ("UTC", "Europe/Moscow", "UTC-8", None):
        assert tz_settings.to_zone(day, zone) == day, zone


def test_недоступная_зона_не_роняет_показ():
    """На образе без tzdata ZoneInfo падает. Показ времени обязан пережить это
    (пусть и в UTC) — иначе бот перестал бы отвечать на половину команд."""
    assert tz_settings.tzinfo_from_name("Несуществующая/Зона") is dt_timezone.utc
    assert tz_settings.timezone_available("Несуществующая/Зона") is False
    # смещение работает всегда, база зон ему не нужна
    assert tz_settings.timezone_available("UTC+3") is True
