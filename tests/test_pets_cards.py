"""Питомцы данными, а не текстом.

Бот собирает состояние строкой с полосками из ▰▱ — в чате уместно, на сайте
читается как стена. Разбирать эту строку обратно нельзя (ломается от любой
правки формулировки), поэтому те же числа отдаются отдельно.
"""

from __future__ import annotations

import inspect
import os
import re

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import game_actions  # noqa: E402
import pets as pets_catalog  # noqa: E402

СТАТИКА = __import__("pathlib").Path(__file__).resolve().parent.parent / "webpanel" / "static"


def test_карточки_считают_теми_же_функциями_что_и_текст():
    """Посчитай сытость и опыт страница сама — она разойдётся с чатом ровно на
    время между двумя обращениями: оба падают и растут лениво."""
    исходник = inspect.getsource(game_actions.my_pets_cards)
    for функция in ("_pet_now", "_pet_xp_now", "level_progress", "state_text",
                    "ability_percent", "_pet_is_active"):
        assert функция in исходник, f"карточки считают {функция} по-своему"


def test_в_карточках_есть_всё_что_показывает_текст():
    """Если в чате что-то видно, а на сайте нет — человек решит, что сайт
    показывает неправду."""
    текст = inspect.getsource(game_actions.my_pets_text)
    карточки = inspect.getsource(game_actions.my_pets_cards)
    for поле in ("hunger", "mood", "level", "evolved"):
        assert поле in текст and поле in карточки


def test_экран_строит_карточки_из_чисел_а_не_из_текста():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    кусок = js[js.index("function renderPets()"):js.index("async function onPetsClick")]
    assert "d.cards" in кусок, "экран обязан читать числа"
    # Текст оставлен запасным путём — на случай старого сервера.
    assert "d.text" in кусок


def test_в_подписях_питомцев_нет_эмодзи():
    """Эмодзи рисуются шрифтом системы: на одном телефоне одни, на другом
    другие. Иконка одинакова везде и красится темой."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    кусок = js[js.index("function petCardHtml"):js.index("function renderPets()")]
    # Эмодзи самого питомца приходит из каталога — он часть его имени и
    # остаётся. А вот подписи шкал и кнопок обязаны быть иконками.
    подписи = re.findall(r">([^<>{}]*[А-Яа-я][^<>{}]*)<", кусок)
    for подпись in подписи:
        assert all(ord(c) < 0x2190 for c in подпись), f"эмодзи в подписи: {подпись!r}"
    for иконка in ("bowl", "smile", "xp", "star", "pin", "walk"):
        assert f'icon("{иконка}")' in кусок or f'"{иконка}"' in кусок


def test_иконки_карточки_есть_в_спрайте():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    есть = set(re.findall(r'<symbol id="(ic-[\w-]+)"', html))
    нужны = {"ic-bowl", "ic-smile", "ic-xp", "ic-spark", "ic-sleep", "ic-star",
             "ic-pin", "ic-walk", "ic-heart"}
    assert нужны <= есть, f"нет в спрайте: {sorted(нужны - есть)}"


def test_спящая_способность_видна():
    """Пока питомец голоден, способности не работают — и это главное, что надо
    понять по карточке, не читая подписей."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    кусок = js[js.index("function petCardHtml"):js.index("function renderPets()")]
    assert "a.works" in кусок and "sleeping" in кусок
    шкала = js[js.index("function petStat"):js.index("function petCardHtml")]
    assert "low" in шкала, "низкое значение должно краснеть"


def test_потолок_уровня_общий_с_каталогом():
    исходник = inspect.getsource(game_actions.my_pets_cards)
    assert "MAX_PET_LEVEL" in исходник
    assert pets_catalog.MAX_PET_LEVEL == 10
