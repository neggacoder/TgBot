"""Закрепы профиля как экипировка (см. pins.py) и удаление оплаты звёздами.

Главное, что проверяется: у КАЖДОЙ ачивки есть тема. Ачивка без темы попала бы
в закреп и молча ничего не давала — та самая «пустая безделушка», от которой
уходили в остальных механиках.
"""

from __future__ import annotations

import os

import pytest

import pins as PIN

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402
import shop_effects as SE  # noqa: E402


# --- темы ачивок ------------------------------------------------------------

def test_у_каждой_ачивки_есть_тема():
    без_темы = [k for k in bot_module.ACHIEVEMENTS if PIN.theme_of(k) is None]
    assert not без_темы, f"эти ачивки в закрепе ничего не дадут: {без_темы}"


def test_все_темы_описаны_и_бьют_по_существующим_эффектам():
    known = set(PIN.ACTIVITY_KEYS) | {"reputation", "casino_win", "lootbox"}
    for theme, (emoji, name, target, percent) in PIN.ACHIEVEMENT_THEMES.items():
        assert emoji and name and percent > 0, theme
        assert target in known or target == PIN.EFFECT_ANY_ACTIVITY, target


def test_тема_труд_прибавляет_к_любому_занятию():
    for activity in (SE.ACTIVITY_FARM, SE.ACTIVITY_FISHING, SE.ACTIVITY_TREASURE,
                     SE.ACTIVITY_SIDE_JOB, SE.ACTIVITY_WORK):
        assert PIN.achievement_bonus("farm_100", activity) > 0


def test_экономика_бьёт_именно_по_ежедневному_бонусу():
    """У «Труда» цель — любое занятие, а ежедневный бонус тоже занятие: точное
    совпадение обязано выигрывать, иначе тема «Экономика» ничего не значит."""
    assert PIN.achievement_bonus("coins_1m", SE.ACTIVITY_DAILY_BONUS) == \
        PIN.ACHIEVEMENT_THEMES["economy"][3]
    assert PIN.achievement_bonus("coins_1m", SE.ACTIVITY_FARM) == 0


def test_чужой_эффект_прибавки_не_получает():
    assert PIN.achievement_bonus("msg_100", "casino_win") == 0
    assert PIN.achievement_bonus("casino_win_big", "reputation") == 0


def test_неизвестная_ачивка_не_ломает_расчёт():
    """Ачивку могли добавить и не вписать сюда — тогда закреп просто не даёт
    прибавки, а не падает."""
    assert PIN.theme_of("совсем_новая_ачивка") is None
    assert PIN.achievement_bonus("совсем_новая_ачивка", "reputation") == 0
    assert PIN.achievement_bonus(None, "reputation") == 0
    assert PIN.achievement_text(None) == ""


def test_описание_темы_человеческое():
    text = PIN.achievement_text("msg_100")
    assert "%" in text and "репутаци" in text


# --- числа слотов -----------------------------------------------------------

def test_закреплённому_питомцу_порог_ниже_обычного():
    import pets as P
    assert 0 < PIN.PET_LOW_STAT < P.LOW_STAT, (
        "закреп должен прощать пропущенную кормёжку, но не отменять уход")


def test_самопочинка_не_чаще_раза_в_сутки():
    assert PIN.BUSINESS_SELF_REPAIR_HOURS >= 24


def test_рыба_прибавляет_к_улову():
    assert PIN.FISH_CATCH_PERCENT > 0


# --- звёзды убраны ----------------------------------------------------------

def test_оплаты_звёздами_больше_нет():
    import relationships_v2 as R
    for key, egg in R.EGG_CATALOG.items():
        assert "price_stars" not in egg, f"{key}: звёзды должны быть убраны совсем"
        assert egg["price_sparks"] and egg["price_sparks"] > 0, key


def test_премиум_яйцо_дороже_золотого():
    import relationships_v2 as R
    assert R.EGG_CATALOG["premium"]["price_sparks"] > R.EGG_CATALOG["golden"]["price_sparks"]


def test_в_коде_не_осталось_упоминаний_оплаты_звёздами():
    import inspect
    import relationships_v2 as R
    src = inspect.getsource(R)
    assert "price_stars" not in src


# --- самопочинка закреплённого бизнеса --------------------------------------

def test_самопочинка_подключена_к_обоим_местам():
    """Сломанный бизнес ничего не копит, поэтому за доходом к нему не идут —
    идут смотреть список. Хук только в «собрать» означал бы, что слот не
    срабатывает почти никогда."""
    import inspect
    for fn in (bot_module.cmd_business_collect, bot_module.cmd_business_mine):
        assert "_pinned_business_self_repair" in inspect.getsource(fn), fn.__name__


def test_о_починке_говорят_даже_при_пустых_копилках():
    """У владельца одного бизнеса это самый вероятный исход: сломанный бизнес
    не копит, значит gross == 0 — и сообщение о починке терялось бы.

    Проверяем именно ветку «копилки пусты»: она обязана упоминать repaired,
    иначе починка происходит молча."""
    import inspect
    src = inspect.getsource(bot_module.cmd_business_collect)
    branch = src[src.index("if gross <= 0"):src.index("Копилки пусты")]
    tail = src[src.index("Копилки пусты"):]
    empty_branch = branch + tail[:tail.index("return")]
    assert "repaired" in empty_branch, "починку в пустой ветке не объявляют"
