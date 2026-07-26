"""Отрисовка одного бабла: фон, имя, ответ-на-сообщение, медиа, текст."""

from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import assets, shapes, text as text_mod, theme
from .theme import s


def _metrics(font, size: int) -> tuple:
    """Подъём и спуск строки.

    Считаются от кегля, а не от конкретных букв: иначе строка «привет» и
    строка «Ёлка» получили бы разную высоту и бабл бы «дышал».
    """
    ascent, descent = font.getmetrics()
    return (
        max(ascent, round(size * theme.ASCENT_FACTOR)),
        max(descent, round(size * theme.DESCENT_FACTOR)),
    )


def _color_for(styles: frozenset) -> tuple:
    """Цвет отрезка. Порядок важен — как в оригинале: моноширинный
    перебивает ссылку, ссылка перебивает спойлер."""
    if "mono" in styles:
        return theme.COLOR_MONO
    if "link" in styles:
        return theme.COLOR_LINK
    return theme.TEXT_COLOR


def _alpha_for(styles: frozenset) -> int:
    if "spoiler" in styles:
        return round(255 * theme.SPOILER_ALPHA)
    return 255


def draw_line(
    canvas: Image.Image,
    line,
    x: float,
    baseline: float,
    size: int,
    *,
    color_override: Optional[tuple] = None,
    skip_emoji: bool = False,
    skip_text: bool = False,
) -> None:
    """Рисует одну готовую строку с форматированием и эмодзи.

    color_override — красит все текстовые отрезки одним цветом (нужно именам:
    у них цвет задаёт собеседник, а не разметка).
    skip_emoji — не рисовать эмодзи-отрезки: ими займётся второй проход,
    поверх градиента, иначе градиент затрёт их цвет (см. _render_name).
    skip_text — наоборот, только эмодзи (тот самый второй проход).

    Начертание берётся ИСКЛЮЧИТЕЛЬНО из styles отрезка. Флага «рисовать
    жирным» здесь намеренно нет: ширину отрезка раскладка измерила заранее
    тем шрифтом, который следует из styles, и любое расхождение между
    «чем измерили» и «чем рисуем» срезает хвост строки по краю холста.
    Имена делаются жирными через _bold_entity() — на этапе раскладки.
    """
    draw = ImageDraw.Draw(canvas, "RGBA")
    emoji_size = round(size * theme.EMOJI_SCALE)
    cursor = x

    for seg in line.segments:
        if seg.is_emoji:
            if skip_emoji:
                cursor += seg.width
                continue
            img = assets.emoji_image(seg.value, emoji_size)
            top = baseline - size * theme.EMOJI_BASELINE_LIFT
            if img is not None:
                canvas.alpha_composite(img, (round(cursor), round(top)))
            else:
                # Картинки нет (нет сети или эмодзи свежее набора) — пробуем
                # нарисовать шрифтом, но только если глиф там реально есть:
                # иначе шрифт подставит пустой квадрат, а он выглядит хуже,
                # чем просто пропуск.
                font = assets.font(size)
                if not assets.glyph_missing(font, seg.value[0]):
                    draw.text((cursor, baseline), seg.value, font=font,
                              fill=color_override or theme.TEXT_COLOR, anchor="ls")
            cursor += seg.width
            continue

        if skip_text:
            cursor += seg.width
            continue

        font = text_mod._font_for(seg.styles, size)
        color = color_override or _color_for(seg.styles)
        alpha = _alpha_for(seg.styles)
        draw.text((cursor, baseline), seg.value, font=font,
                  fill=(*color, alpha), anchor="ls")

        thickness = max(1, round(size * theme.DECOR_THICKNESS_FACTOR))
        if "strike" in seg.styles:
            y = baseline - size * theme.STRIKE_OFFSET_FACTOR
            draw.rectangle([cursor, y, cursor + seg.width, y + thickness],
                           fill=(*color, alpha))
        if "underline" in seg.styles:
            y = baseline + s(theme.UNDERLINE_OFFSET)
            draw.rectangle([cursor, y, cursor + seg.width, y + thickness],
                           fill=(*color, alpha))

        cursor += seg.width


# Имя в шапку бабла не обрезается по ширине (бабл сам растягивается под него),
# поэтому раскладке даётся заведомо недостижимый предел — она нужна тут не ради
# переноса, а ради разбора имени на отрезки: только так в имени работают эмодзи.
_NAME_NO_LIMIT = 1 << 20


def _bold_entity(text: str) -> list:
    """Разметка «всё имя — полужирное».

    Именно entity, а не флаг при отрисовке: раскладка меряет ширину отрезка
    тем шрифтом, который следует из его styles. Пометь жирность в обход
    entity — измерят обычным шрифтом, нарисуют жирным (он шире), и хвост
    имени срежется по краю. length — в кодовых единицах UTF-16, как в Bot API
    (у эмодзи вне BMP их два, и раскладка это учитывает).
    """
    return [{"type": "bold", "offset": 0,
             "length": len(text.encode("utf-16-le")) // 2}]


def _name_lines(name: str, size: int, max_width: float, max_lines: int) -> list:
    return text_mod.layout(name, _bold_entity(name), size, max_width, max_lines)


def _render_name(name: str, color: tuple, size: int) -> Image.Image:
    """Имя отправителя с лёгким горизонтальным градиентом — как в оригинале
    (сплошная заливка выглядит заметно площе).

    Рисуется в ДВА прохода. Градиент делается через альфа-маску нарисованного
    текста, а маска убивает цвет — для букв это и нужно, но эмодзи-картинку
    так превратило бы в цветное пятно. Поэтому сначала буквы (под градиент),
    потом поверх готового градиента — эмодзи, в своём цвете.

    Раньше имя рисовалось одним draw.text() шрифтом Noto: эмодзи в имени
    (а в Telegram они у половины чата) выходило пустым квадратом-notdef.
    """
    lines = _name_lines(name, size, _NAME_NO_LIMIT, 1)
    ascent, descent = _metrics(assets.font(size, bold=True), size)
    height = ascent + descent
    if not lines:
        return Image.new("RGBA", (1, height), (0, 0, 0, 0))

    line = lines[0]
    width = max(1, round(line.width))

    # проход 1: только буквы, белым — это будущая маска градиента
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_line(layer, line, 0, ascent, size,
              color_override=(255, 255, 255), skip_emoji=True)

    lighter = tuple(min(255, round(c * 1.25)) for c in color)
    gradient = shapes.linear_gradient(width, height, color, lighter)
    gradient = gradient.convert("RGBA")
    gradient.putalpha(layer.getchannel("A"))

    # проход 2: эмодзи поверх градиента, своими цветами
    draw_line(gradient, line, 0, ascent, size, skip_text=True)
    return gradient


def _fit_media(data: bytes, max_size: int) -> Optional[Image.Image]:
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    w, h = img.size
    if not w or not h:
        return None
    # вписываем по короткой стороне, как оригинал
    new_w = w * (max_size / h)
    new_h = max_size
    if new_w >= max_size:
        new_w = max_size
        new_h = h * (max_size / w)
    return img.resize((max(1, round(new_w)), max(1, round(new_h))), Image.LANCZOS)


class _Block:
    """Готовый к вставке кусок содержимого бабла."""

    def __init__(self, image: Image.Image, gap_after: int = 0):
        self.image = image
        self.gap_after = gap_after


def _render_reply(msg, accent: tuple, max_width: int) -> Optional[Image.Image]:
    """Плашка «в ответ на» — подложка акцентным цветом и полоса слева."""
    if not msg.reply_name or not msg.reply_text:
        return None

    name_size = s(theme.FONT_REPLY_NAME)
    text_size = s(theme.FONT_REPLY_TEXT)
    pad_l, pad_r = s(theme.BLOCK_PAD_L), s(theme.BLOCK_PAD_R)
    pad_y = s(theme.BLOCK_PAD_Y)
    gap = s(theme.BLOCK_GAP)

    inner_max = max_width - pad_l - pad_r
    name_lines = _name_lines(msg.reply_name, name_size, inner_max, 1)
    # Реплай несёт больше информации: до двух строк текста (как в quotly),
    # а не одна обрезанная — так видно, на что именно отвечали.
    text_lines = text_mod.layout(msg.reply_text, None, text_size, inner_max, 2)
    if not name_lines and not text_lines:
        return None

    name_asc, name_desc = _metrics(assets.font(name_size, bold=True), name_size)
    text_asc, text_desc = _metrics(assets.font(text_size), text_size)
    name_h = name_asc + name_desc
    text_line_h = round(text_size * theme.LINE_HEIGHT_FACTOR)
    text_block_h = (
        (len(text_lines) - 1) * text_line_h + text_asc + text_desc if text_lines else 0
    )

    content_w = max(
        [ln.width for ln in name_lines] + [ln.width for ln in text_lines] + [1]
    )
    width = round(min(max_width, content_w + pad_l + pad_r))
    height = pad_y * 2 + name_h + gap + text_block_h

    block = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    corners = shapes.rounded_mask(width, height, s(theme.BLOCK_RADIUS))

    tint = Image.new("RGBA", (width, height), (*accent, round(255 * theme.BLOCK_TINT)))
    block.paste(tint, (0, 0), corners)

    # полосу тоже обрезаем по скруглению — иначе её прямые углы торчат
    bar_w = max(1, round(s(theme.BLOCK_BAR)))
    bar = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rectangle([0, 0, bar_w, height], fill=(*accent, 255))
    block.paste(bar, (0, 0), ImageChops.multiply(bar.getchannel("A"), corners))

    if name_lines:
        # Именно name_lines, а не сырое msg.reply_name: раскладка уже обрезала
        # имя по ширине плашки и разобрала его на отрезки. Рисовать здесь
        # исходную строку одним шрифтом (как было) означало сразу две беды —
        # длинное имя вылезало за плашку, а эмодзи в имени превращалось в
        # пустой квадрат.
        draw_line(block, name_lines[0], pad_l, pad_y + name_asc, name_size,
                  color_override=accent)
    baseline = pad_y + name_h + gap + text_asc
    for line in text_lines:
        draw_line(block, line, pad_l, baseline, text_size)
        baseline += text_line_h

    return block


def render_bubble(
    msg,
    *,
    show_name: bool,
    radii: tuple,
    tail: bool,
    max_width: int,
) -> tuple:
    """Рисует бабл одного сообщения.

    Возвращает (изображение, extra_left) — extra_left нужен, потому что
    хвостик выступает левее самого бабла.
    """
    text_size = s(theme.FONT_TEXT)
    name_size = s(theme.FONT_NAME)
    pad_x, pad_y = s(theme.PAD_X), s(theme.PAD_Y)
    gap = s(theme.GAP)

    content_max = max_width - pad_x * 2
    accent_name = theme.name_color(msg.user_id)

    blocks: list = []

    if show_name:
        blocks.append(_Block(_render_name(msg.name, accent_name, name_size), gap))

    reply_accent = theme.name_color(msg.reply_chat_id or msg.user_id)
    reply_block = _render_reply(msg, reply_accent, content_max)
    if reply_block is not None:
        blocks.append(_Block(reply_block, gap))

    if msg.media_bytes:
        media = _fit_media(msg.media_bytes, content_max)
        if media is not None:
            # скругление накладывается НА собственную прозрачность картинки,
            # иначе у стикера с альфой появился бы непрозрачный прямоугольник
            corners = shapes.rounded_mask(*media.size, s(theme.MEDIA_ROUND))
            media.putalpha(ImageChops.multiply(media.getchannel("A"), corners))
            blocks.append(_Block(media, gap))

    lines = []
    if msg.text:
        lines = text_mod.layout(msg.text, msg.entities, text_size, content_max, 30)

    text_ascent, text_descent = _metrics(assets.font(text_size), text_size)
    line_height = round(text_size * theme.LINE_HEIGHT_FACTOR)

    text_height = 0
    if lines:
        text_height = (len(lines) - 1) * line_height + text_ascent + text_descent

    content_w = max(
        [b.image.width for b in blocks]
        + [ln.width for ln in lines]
        + [s(theme.MIN_WIDTH) - pad_x * 2]
    )
    bubble_w = round(content_w + pad_x * 2)
    bubble_h = pad_y * 2 + sum(b.image.height + b.gap_after for b in blocks) + text_height
    if not lines and blocks:
        # последний блок не нуждается в отступе под текст
        bubble_h -= blocks[-1].gap_after

    tail_size = s(theme.TAIL) if tail else 0
    mask, extra_left = shapes.bubble_mask(bubble_w, bubble_h, radii, tail_size)

    canvas = Image.new("RGBA", (mask.width, mask.height), (0, 0, 0, 0))
    background = shapes.linear_gradient(
        mask.width, mask.height, theme.BG_GRADIENT_FROM, theme.BG_GRADIENT_TO
    ).convert("RGBA")
    canvas.paste(background, (0, 0), mask)

    _add_glass(canvas, mask)

    x0 = extra_left + pad_x
    y = pad_y
    for block in blocks:
        canvas.alpha_composite(block.image, (round(x0), round(y)))
        y += block.image.height + block.gap_after

    baseline = y + text_ascent
    for line in lines:
        draw_line(canvas, line, x0, baseline, text_size)
        baseline += line_height

    return canvas, extra_left


def _add_glass(canvas: Image.Image, mask: Image.Image) -> None:
    """Тонкая светлая обводка по краю и подсветка сверху — «стеклянный» край,
    из-за которого бабл не выглядит плоской заливкой."""
    width = max(1, round(s(theme.GLASS) * 2))

    # Кайма по внутреннему краю = маска минус её размытая версия: у границы
    # размытие «проседает», внутри остаётся 255 и разность обнуляется.
    # Морфологическое расширение дало бы тот же контур, но ранговый фильтр
    # на порядок медленнее и съедал больше половины времени рендера.
    blurred = mask.filter(ImageFilter.GaussianBlur(width))
    edge = ImageChops.subtract(mask, blurred).point(lambda v: min(255, v * 2))

    # Накладывать эти блики можно ТОЛЬКО alpha_composite: paste с маской
    # заменяет пиксели целиком, вместе с альфой, и полупрозрачная обводка
    # пробила бы в непрозрачном крае бабла белёсую дыру по всему периметру.
    stroke_alpha = theme.GLASS_STROKE[3]
    stroke = Image.new("RGBA", mask.size, theme.GLASS_STROKE[:3] + (255,))
    stroke.putalpha(edge.point(lambda v: v * stroke_alpha // 255))
    canvas.alpha_composite(stroke)

    top_h = max(1, round(mask.height * theme.GLASS_TOP_HEIGHT_FACTOR))
    ramp = ImageOps.invert(Image.linear_gradient("L").resize((mask.size[0], top_h)))
    top_ramp = Image.new("L", mask.size, 0)
    top_ramp.paste(ramp, (0, 0))

    highlight_alpha = theme.GLASS_TOP_FROM[3]
    highlight = Image.new("RGBA", mask.size, theme.GLASS_TOP_FROM[:3] + (255,))
    highlight.putalpha(
        ImageChops.multiply(top_ramp, edge).point(lambda v: v * highlight_alpha // 255)
    )
    canvas.alpha_composite(highlight)


def add_shadow(bubble: Image.Image) -> Image.Image:
    """Мягкая тень под баблом. Холст расширяется, чтобы тень не обрезалась."""
    blur = s(theme.SHADOW_BLUR)
    offset_y = s(theme.SHADOW_OFFSET_Y)
    pad = blur * 2

    out = Image.new(
        "RGBA", (bubble.width + pad * 2, bubble.height + pad * 2 + offset_y), (0, 0, 0, 0)
    )
    shadow = Image.new("RGBA", bubble.size, theme.SHADOW_COLOR)
    shadow.putalpha(
        bubble.getchannel("A").point(lambda a: round(a * theme.SHADOW_COLOR[3] / 255))
    )
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    layer.paste(shadow, (pad, pad + offset_y))
    layer = layer.filter(ImageFilter.GaussianBlur(blur / 2))

    out = Image.alpha_composite(out, layer)
    out.alpha_composite(bubble, (pad, pad))
    return out
