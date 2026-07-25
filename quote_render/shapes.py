"""Геометрия: форма бабла, скруглённые маски, градиенты.

Pillow рисует фигуры без сглаживания и не умеет скруглять углы разными
радиусами — а баблу нужно и то, и другое (у сгруппированных сообщений угол,
обращённый к соседу, скруглён слабее). Поэтому путь собирается точками
вручную, а маска рисуется вдвое крупнее и ужимается — так края получаются
гладкими.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

# Во сколько раз крупнее рисуется маска перед уменьшением.
_SUPERSAMPLE = 2
# Сегментов на дугу/кривую — на глаз неотличимо от гладкой при любом размере.
_ARC_STEPS = 16


def _arc_points(cx: float, cy: float, r: float, start_deg: float, end_deg: float) -> list:
    """Точки дуги от start_deg до end_deg (по часовой, 0° — вправо)."""
    if r <= 0:
        return [(cx, cy)]
    points = []
    for i in range(_ARC_STEPS + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * i / _ARC_STEPS)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _bezier_points(p0, p1, p2, p3) -> list:
    """Точки кубической кривой Безье."""
    points = []
    for i in range(_ARC_STEPS + 1):
        t = i / _ARC_STEPS
        mt = 1 - t
        x = (mt ** 3) * p0[0] + 3 * (mt ** 2) * t * p1[0] + 3 * mt * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (mt ** 3) * p0[1] + 3 * (mt ** 2) * t * p1[1] + 3 * mt * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        points.append((x, y))
    return points


def bubble_path(w: float, h: float, radii: tuple, tail: float) -> list:
    """Контур бабла в его собственных координатах (0,0 — левый верх).

    radii — (tl, tr, br, bl). tail > 0 добавляет хвостик слева снизу: низ
    бабла продолжается плоско влево (в отрицательные x) и возвращается к
    левому краю дугой — так рисует хвостик оригинальный quotly, это не
    треугольник.
    """
    tl, tr, br, bl = (min(r, w / 2, h / 2) for r in radii)

    points: list = []
    # верхний край слева направо
    points.append((tl, 0.0))
    points.append((w - tr, 0.0))
    points += _arc_points(w - tr, tr, tr, 270, 360)
    # правый край вниз
    points.append((w, h - br))
    points += _arc_points(w - br, h - br, br, 0, 90)
    # нижний край справа налево
    if tail > 0:
        points.append((-tail, h))
        points += _bezier_points(
            (-tail, h), (-tail * 0.4, h), (0.0, h - bl * 0.3), (0.0, h - bl)
        )
    else:
        points.append((bl, h))
        points += _arc_points(bl, h - bl, bl, 90, 180)
    # левый край вверх
    points.append((0.0, tl))
    points += _arc_points(tl, tl, tl, 180, 270)
    return points


def bubble_mask(w: int, h: int, radii: tuple, tail: float) -> tuple:
    """Маска бабла со сглаженными краями.

    Возвращает (маска, extra_left): хвостик уходит левее нуля, поэтому маска
    шире бабла, а extra_left говорит, на сколько её сдвинуть при вставке.
    """
    extra_left = math.ceil(tail * 0.8) if tail > 0 else 0
    mask_w, mask_h = w + extra_left, h

    ss = _SUPERSAMPLE
    big = Image.new("L", (mask_w * ss, mask_h * ss), 0)
    path = [((x + extra_left) * ss, y * ss) for x, y in bubble_path(w, h, radii, tail)]
    ImageDraw.Draw(big).polygon(path, fill=255)

    return big.resize((mask_w, mask_h), Image.LANCZOS), extra_left


def rounded_mask(w: int, h: int, radii) -> Image.Image:
    """Скруглённая прямоугольная маска — для медиа и превью в reply."""
    if isinstance(radii, (int, float)):
        radii = (radii, radii, radii, radii)
    ss = _SUPERSAMPLE
    big = Image.new("L", (w * ss, h * ss), 0)
    path = [(x * ss, y * ss) for x, y in bubble_path(w, h, radii, 0)]
    ImageDraw.Draw(big).polygon(path, fill=255)
    return big.resize((w, h), Image.LANCZOS)


def circle_mask(size: int) -> Image.Image:
    ss = _SUPERSAMPLE
    big = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * ss - 1, size * ss - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


_GRID = 64
_ramp_cache: dict = {}


def _diagonal_ramp(weight: float) -> Image.Image:
    """Сетка перехода 0→1 по диагонали.

    Доля вдоль диагонали сводится к `weight * u + (1 - weight) * v`, то есть
    зависит только от пропорций прямоугольника, а не от его размера. Поэтому
    сетка считается один раз на пропорцию (округлённую до сотых) и потом
    просто растягивается под нужный размер.
    """
    key = round(weight, 2)
    cached = _ramp_cache.get(key)
    if cached is not None:
        return cached

    ramp = Image.new("L", (_GRID, _GRID))
    pixels = ramp.load()
    for y in range(_GRID):
        base = (1 - key) * (y / (_GRID - 1))
        for x in range(_GRID):
            t = base + key * (x / (_GRID - 1))
            pixels[x, y] = min(255, max(0, int(t * 255 + 0.5)))

    _ramp_cache[key] = ramp
    return ramp


def linear_gradient(w: int, h: int, color_from: tuple, color_to: tuple) -> Image.Image:
    """Диагональный градиент из левого верха в правый низ."""
    denom = float(w * w + h * h) or 1.0
    ramp = _diagonal_ramp((w * w) / denom).resize((w, h), Image.BILINEAR)
    start = Image.new("RGB", (w, h), color_from)
    end = Image.new("RGB", (w, h), color_to)
    return Image.composite(end, start, ramp)
