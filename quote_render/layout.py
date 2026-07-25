"""Склейка баблов в готовую картинку-цитату.

Подряд идущие сообщения одного человека образуют группу и рисуются так же,
как в самом Telegram: имя подписано только над первым, аватар стоит только у
последнего, хвостик — тоже у последнего, а углы, которыми баблы смотрят друг
на друга, скруглены слабее.
"""

from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import assets, bubble as bubble_mod, shapes, theme
from .theme import s


def _group(messages: list) -> list:
    """Разбивает подряд идущие сообщения одного автора на группы."""
    groups: list = []
    for msg in messages:
        if groups and groups[-1][0].user_id == msg.user_id:
            groups[-1].append(msg)
        else:
            groups.append([msg])
    return groups


def _radii(position: str) -> tuple:
    """Радиусы углов (tl, tr, br, bl) по месту сообщения в группе."""
    big = theme.RADIUS
    small = theme.RADIUS_GROUPED
    tl = small if position in ("middle", "last") else big
    bl = small if position in ("first", "middle") else big
    return (s(tl), s(big), s(big), s(bl))


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _avatar(msg, size: int) -> Image.Image:
    """Круглый аватар. Без фото — цветной кружок с инициалами, как в
    Telegram (цвет привязан к user_id, поэтому у человека он не скачет)."""
    circle = shapes.circle_mask(size)

    if msg.avatar_bytes:
        try:
            photo = Image.open(BytesIO(msg.avatar_bytes)).convert("RGB")
            photo = ImageOps.fit(photo, (size, size), Image.LANCZOS)
            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            out.paste(photo, (0, 0), circle)
            return out
        except Exception:
            pass

    color_from, color_to = theme.avatar_gradient(msg.user_id)
    background = shapes.linear_gradient(size, size, color_from, color_to).convert("RGBA")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(background, (0, 0), circle)

    initials = _initials(msg.name)
    font_size = round(size * (0.48 if len(initials) == 1 else 0.38))
    font = assets.font(font_size, bold=True)
    ImageDraw.Draw(out).text(
        (size / 2, size / 2), initials, font=font, fill=(255, 255, 255, 255),
        anchor="mm",
    )
    return out


def _draw_shadow(canvas: Image.Image, bubble_img: Image.Image, position: tuple) -> None:
    """Подкладывает под бабл мягкую тень.

    Тень строится на маленьком холсте по размеру самого бабла, а не по всему
    полотну: размывать полноразмерный слой на каждое сообщение — работа,
    растущая вместе с числом сообщений в цитате.
    """
    blur = s(theme.SHADOW_BLUR)
    pad = blur * 2

    tint = Image.new("RGBA", bubble_img.size, theme.SHADOW_COLOR[:3] + (255,))
    tint.putalpha(
        bubble_img.getchannel("A").point(
            lambda a: round(a * theme.SHADOW_COLOR[3] / 255)
        )
    )

    patch = Image.new("RGBA", (bubble_img.width + pad * 2, bubble_img.height + pad * 2),
                      (0, 0, 0, 0))
    patch.paste(tint, (pad, pad))
    patch = patch.filter(ImageFilter.GaussianBlur(blur / 2))

    x = position[0] - pad
    y = position[1] - pad + s(theme.SHADOW_OFFSET_Y)

    # тень может выходить за край полотна — обрезаем, иначе alpha_composite
    # откажется работать с отрицательными координатами
    left, top = max(0, -x), max(0, -y)
    right = min(patch.width, canvas.width - x)
    bottom = min(patch.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    patch = patch.crop((left, top, right, bottom))
    canvas.alpha_composite(patch, (x + left, y + top))


def render_quote(messages: list, max_width: int = 512) -> Image.Image:
    """Рисует цитату из одного или нескольких сообщений.

    Картинка возвращается в полном масштабе рендера (крупнее итоговой) —
    ужимать её должен вызывающий, вместе с приведением под формат стикера:
    downscale в самом конце даёт заметно более гладкий результат.
    """
    if not messages:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    avatar_size = s(theme.AVATAR)
    bubble_x = avatar_size + s(theme.AVATAR_GAP)
    content_limit = s(max_width) - bubble_x - s(theme.SHADOW_PAD)

    groups = _group(messages)

    rendered: list = []   # (изображение, extra_left, показывать_аватар, сообщение)
    for group in groups:
        for index, msg in enumerate(group):
            if len(group) == 1:
                position = "single"
            elif index == 0:
                position = "first"
            elif index == len(group) - 1:
                position = "last"
            else:
                position = "middle"

            is_last = position in ("single", "last")
            image, extra_left = bubble_mod.render_bubble(
                msg,
                show_name=position in ("single", "first"),
                radii=_radii(position),
                tail=is_last,
                max_width=content_limit,
            )
            rendered.append((image, extra_left, is_last, msg))

    # высота: баблы + зазоры (внутри группы теснее, между группами шире)
    gaps: list = []
    for i in range(1, len(messages)):
        same_author = messages[i].user_id == messages[i - 1].user_id
        gaps.append(s(theme.GAP_SAME_AUTHOR if same_author else theme.GAP_DIFF_AUTHOR))

    total_h = sum(img.height for img, _, _, _ in rendered) + sum(gaps)
    max_bubble_w = max(img.width - extra for img, extra, _, _ in rendered)

    canvas_w = bubble_x + max_bubble_w + s(theme.SHADOW_PAD)
    canvas_h = s(theme.SHADOW_PAD_TOP) + total_h + s(theme.SHADOW_PAD)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # сначала все тени — чтобы соседний бабл не оказался под чужой тенью
    y = s(theme.SHADOW_PAD_TOP)
    positions: list = []
    for i, (image, extra_left, is_last, msg) in enumerate(rendered):
        x = bubble_x - extra_left
        positions.append((x, y))
        _draw_shadow(canvas, image, (x, y))
        y += image.height + (gaps[i] if i < len(gaps) else 0)

    for (image, extra_left, is_last, msg), (x, y) in zip(rendered, positions):
        canvas.alpha_composite(image, (x, y))
        if is_last:
            avatar = _avatar(msg, avatar_size)
            canvas.alpha_composite(avatar, (0, y + image.height - avatar_size))

    return canvas
