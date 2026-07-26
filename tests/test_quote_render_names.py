"""Имена в стикере-цитате: эмодзи и обрезка по ширине.

Ловится одна и та же поломка в трёх местах: имя автора, имя в плашке
«в ответ на» и инициалы аватара рисовались одним draw.text() шрифтом Noto,
который эмодзи не знает. В чате, где половина никнеймов с эмодзи, вместо
значка выходил пустой квадрат-notdef.

Вторая ловушка тут же рядом: ширину отрезка раскладка меряет ТЕМ ЖЕ шрифтом,
который следует из его styles. Если сделать имя жирным в обход entities —
измерят обычным шрифтом, нарисуют жирным (он шире), и хвост имени срежется
по краю холста. Поэтому имена жирнеют через _bold_entity().
"""

from __future__ import annotations

import pytest

pytest.importorskip("PIL", reason="нужен Pillow (см. .venv)")

from quote_render import bubble, layout as layout_mod, text as text_mod  # noqa: E402

SIZE = 32


# --- инициалы аватара ------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("Мария", "М"),
    ("Мария 🔥", "М"),
    ("🔥Мария", "М"),
    ("🔥 Мария Иванова", "МИ"),
    ("Мария 🔥 Иванова", "МИ"),
    ("·Асель·", "А"),
])
def test_инициалы_берут_буквы_а_не_эмодзи(name, expected):
    """Шрифт аватара эмодзи не знает: раньше кружок получал пустой квадрат."""
    assert layout_mod._initials(name) == expected


def test_имя_из_одних_эмодзи_не_ломает_аватар():
    """Букв нет вообще — нужен хоть какой-то осмысленный кружок, не квадрат."""
    assert layout_mod._initials("🔥🔥") == "?"
    assert layout_mod._initials("") == "?"
    assert layout_mod._initials("7up") == "U"  # первая БУКВА, а не цифра


# --- жирность имени через entity, а не флагом ------------------------------

def test_длина_entity_считается_в_utf16():
    """Bot API меряет offset/length в кодовых единицах UTF-16: у эмодзи вне
    BMP их две. Ошибись тут — жирность оборвётся на первом же эмодзи."""
    assert bubble._bold_entity("абв")[0]["length"] == 3
    assert bubble._bold_entity("аб🔥")[0]["length"] == 4      # 2 + 2
    assert bubble._bold_entity("👋🏽")[0]["length"] == 4       # рука + модификатор


def test_имя_меряется_тем_же_шрифтом_что_рисуется():
    """Сердце бага с обрезкой: все текстовые отрезки имени обязаны нести
    стиль bold, иначе их измерят обычным шрифтом."""
    lines = bubble._name_lines("ОченьДлинноеИмя", SIZE, bubble._NAME_NO_LIMIT, 1)
    text_segments = [s for s in lines[0].segments if not s.is_emoji]
    assert text_segments, "имя должно разобраться на отрезки"
    assert all("bold" in s.styles for s in text_segments)

    # и ширина такой строки совпадает с шириной, которую даёт жирный шрифт
    from quote_render import assets
    expected = assets.font(SIZE, bold=True).getlength("ОченьДлинноеИмя")
    assert lines[0].width == pytest.approx(expected, rel=0.01)


def test_имя_с_эмодзи_разбирается_на_отрезки():
    """Ради этого раскладка тут и нужна: эмодзи должно стать отдельным
    отрезком-картинкой, а не куском текста для Noto."""
    lines = bubble._name_lines("Мария 🔥", SIZE, bubble._NAME_NO_LIMIT, 1)
    kinds = [s.is_emoji for s in lines[0].segments]
    assert any(kinds), "эмодзи в имени должно опознаться как эмодзи"


# --- обрезка длинного имени в плашке реплая --------------------------------

def test_длинное_имя_реплая_обрезается_по_ширине():
    """Плашка реплая шириной не растёт — имя обязано влезть в неё с
    многоточием, а не вылезти за край."""
    limit = 300
    long_name = "ОченьДлинноеИмяКотороеТочноНеВлезаетВПлашкуРеплаяНикакВообще"
    lines = bubble._name_lines(long_name, SIZE, limit, 1)
    assert len(lines) == 1
    assert lines[0].width <= limit
    drawn = "".join(s.value for s in lines[0].segments)
    assert drawn.endswith("…"), "обрезанное имя помечается многоточием"
    assert len(drawn) < len(long_name)


def test_короткое_имя_реплая_не_трогается():
    lines = bubble._name_lines("Ержан", SIZE, 300, 1)
    assert "".join(s.value for s in lines[0].segments) == "Ержан"


# --- отрисовка имени: эмодзи переживает градиент ---------------------------

def _has_color(img) -> bool:
    """Есть ли в картинке хоть один непрозрачный НЕсерый пиксель.

    Градиент имени строится через альфа-маску, а маска убивает цвет. Если
    эмодзи нарисовать до градиента, оно станет одноцветным пятном — значит,
    проверяем именно наличие насыщенного цвета.
    """
    for r, g, b, a in img.convert("RGBA").getdata():
        if a > 40 and max(r, g, b) - min(r, g, b) > 60:
            return True
    return False


def test_эмодзи_в_имени_рисуется_в_своём_цвете():
    """🔥 лежит в assets/emoji, поэтому тест не ходит в сеть."""
    plain = bubble._render_name("Мария", (90, 160, 240), SIZE)
    with_emoji = bubble._render_name("Мария 🔥", (90, 160, 240), SIZE)

    assert with_emoji.width > plain.width, "эмодзи занимает место в имени"
    # у 🔥 оранжево-красная палитра — она обязана уцелеть поверх синего градиента
    assert _has_color(with_emoji.crop((plain.width, 0, with_emoji.width, with_emoji.height)))


def test_имя_целиком_влезает_в_свой_холст():
    """Холст имени строится по измеренной ширине: если измерение и отрисовка
    разойдутся, последняя буква окажется за краем и её срежет."""
    name = "ОченьДлинноеИмяБезПробелов"
    img = bubble._render_name(name, (90, 160, 240), SIZE)
    right_column = img.convert("RGBA").crop((img.width - 1, 0, img.width, img.height))
    # у самого края допустим лишь хвостик антиалиасинга, но не тело буквы
    filled = sum(1 for px in right_column.getdata() if px[3] > 200)
    assert filled <= 2, "имя упирается в край холста — значит, его обрезало"
