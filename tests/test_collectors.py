"""Правила коллектора: когда приходить и когда взыскивать.

Числа и тексты без БД и телеграма — как pets.py и farming.py рядом.
Фоновый цикл ходит по всем чатам сразу, поэтому ошибка в этих правилах
бьёт по всем и разом; их и проверяем отдельно от цикла.
"""

from __future__ import annotations

import io
import os
import re

import pytest

import collectors


def test_ступени_идут_по_нарастающей():
    """Первый визит вежливый, последний наглый. Порядок — часть замысла."""
    assert len(collectors.STAGES) >= 3
    assert [s.visits for s in collectors.STAGES] == sorted(s.visits for s in collectors.STAGES)


@pytest.mark.parametrize("visits,ожидаем", [(0, 0), (1, 0), (2, 1), (5, len(collectors.STAGES) - 1)])
def test_ступень_по_числу_визитов(visits, ожидаем):
    assert collectors.STAGES.index(collectors.stage_for(visits)) == ожидаем


def test_ступень_не_выходит_за_последнюю():
    """Сто визитов — та же наглость, что и на последней ступени, а не сбой."""
    assert collectors.stage_for(100) is collectors.STAGES[-1]


def test_у_каждой_ступени_есть_чем_сказать():
    for stage in collectors.STAGES:
        assert stage.texts, stage.key
        for text in stage.texts:
            assert "{кто}" in text, f"{stage.key}: некому адресовать"
            assert "{долг}" in text, f"{stage.key}: не названа сумма"


def test_текст_подставляет_имя_и_сумму():
    text = collectors.visit_text(collectors.STAGES[0], "@вася", 1234)
    assert "@вася" in text and "1234" in text
    assert "{" not in text, "плейсхолдер остался неподставленным"


# --- когда приходить -------------------------------------------------------

def test_коллектор_не_идёт_раньше_срока():
    assert not collectors.should_visit(overdue_days=0, after_days=1, last_visit_days=None)


def test_первый_визит_после_срока():
    assert collectors.should_visit(overdue_days=1, after_days=1, last_visit_days=None)


def test_не_чаще_раза_в_сутки():
    assert not collectors.should_visit(overdue_days=5, after_days=1, last_visit_days=0)
    assert collectors.should_visit(overdue_days=5, after_days=1, last_visit_days=1)


def test_ноль_выключает_коллектора():
    """Чату, которому это не нужно, банк остаётся прежним."""
    assert not collectors.should_visit(overdue_days=99, after_days=0, last_visit_days=None)


# --- когда взыскивать ------------------------------------------------------

def test_взыскание_по_сроку():
    assert collectors.should_seize(overdue_days=5, seize_after_days=5, debt=100, principal=1000)
    assert not collectors.should_seize(overdue_days=4, seize_after_days=5, debt=100, principal=1000)


def test_взыскание_по_росту_долга_втрое():
    """Старый повод остаётся: при большой пене долг утроится раньше срока,
    и ждать в этом случае незачем."""
    assert collectors.should_seize(overdue_days=1, seize_after_days=5, debt=3000, principal=1000)
    assert not collectors.should_seize(overdue_days=1, seize_after_days=5, debt=2999, principal=1000)


def test_ноль_выключает_только_срок_а_не_рост():
    """Выключенный срок не должен делать долг вечным: порог по росту
    остаётся последней защитой."""
    assert not collectors.should_seize(overdue_days=99, seize_after_days=0, debt=100, principal=1000)
    assert collectors.should_seize(overdue_days=99, seize_after_days=0, debt=3000, principal=1000)


def test_без_известной_суммы_кредита_работает_только_срок():
    """principal=None бывает у старых записей — не повод взыскать внезапно."""
    assert not collectors.should_seize(overdue_days=1, seize_after_days=5, debt=999999, principal=None)
    assert collectors.should_seize(overdue_days=5, seize_after_days=5, debt=999999, principal=None)


# --- достижимость ступеней при настройках из коробки ------------------------
#
# Ступень, до которой нельзя дойти, — это мёртвый текст: он написан, лежит в
# модуле и не показывается никому. Проверяем не абстрактную арифметику, а
# ровно тот график, по которому цикл ходит с умолчаниями банка.

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _умолчания_банка() -> tuple[int, int]:
    """Сроки коллектора и взыскания по умолчанию — из определения
    bank_settings в db.py.

    Берём из схемы, а не из головы: подними кто-нибудь умолчание срока — и
    лестница ступеней разъедется с ним молча."""
    схема = io.open(os.path.join(_ROOT, "db.py"), encoding="utf-8").read()
    коллектор = re.search(r"collector_after_days INT NOT NULL DEFAULT (\d+)", схема)
    взыскание = re.search(r"seize_after_days INT NOT NULL DEFAULT (\d+)", схема)
    assert коллектор and взыскание, "умолчания сроков пропали из схемы bank_settings"
    return int(коллектор.group(1)), int(взыскание.group(1))


def _ступени_за_просрочку(after_days: int, seize_after_days: int) -> list[str]:
    """Какие ступени успеет показать коллектор, пока не придёт взыскание.

    Повторяет порядок bank_penalty_loop: раз в сутки сперва проверяется
    взыскание, потом визит; счётчик визитов растёт на каждом визите, а
    ступень выбирается по УЖЕ сделанным (stage_for(visits - 1))."""
    показанные: list[str] = []
    визитов, последний = 0, None
    for день in range(0, 60):
        # principal=0 выключает второй повод взыскания (рост долга втрое) —
        # здесь проверяется только график по сроку.
        if collectors.should_seize(день, seize_after_days, debt=1, principal=0):
            break
        прошло = None if последний is None else день - последний
        if collectors.should_visit(день, after_days, прошло):
            визитов += 1
            последний = день
            показанные.append(collectors.stage_for(визитов - 1).key)
    return показанные


def test_при_умолчаниях_доходит_до_самой_наглой_ступени():
    """Иначе треть написанных текстов коллектора не увидит никто: с
    умолчаниями визитов успевает быть четыре, а ступень с порогом 4 требует
    пятого."""
    показанные = _ступени_за_просрочку(*_умолчания_банка())
    пропущенные = [s.key for s in collectors.STAGES if s.key not in показанные]
    assert not пропущенные, f"ступени недостижимы из коробки: {пропущенные}"


def test_лестница_идёт_только_вверх():
    """Ступень не может стать мягче: разговор с коллектором — это нарастание,
    а откат назад читался бы как сброс счётчика и сбивал бы с толку."""
    порядок = [s.key for s in collectors.STAGES]
    показанные = _ступени_за_просрочку(*_умолчания_банка())
    индексы = [порядок.index(k) for k in показанные]
    assert индексы == sorted(индексы), показанные


def test_первый_разговор_начинается_вежливо():
    """Наглость на первом же визите отменила бы смысл лестницы."""
    показанные = _ступени_за_просрочку(*_умолчания_банка())
    assert показанные and показанные[0] == collectors.STAGES[0].key
