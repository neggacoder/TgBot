"""График курса акций для команды «биржа».

Зачем. Раньше «биржа» отвечала голым текстом: курс, сколько у тебя акций,
сколько заработано. Числа верные, но по ним не видно ГЛАВНОГО — куда курс
идёт. Решение «покупать или продавать» принимается по форме кривой, а её в
тексте нет вовсе.

Картинка уходит ВМЕСТЕ с текстом (подписью к фото), а не отдельным сообщением:
два сообщения подряд в чате — это две уведомления и разорванный ответ на одну
команду.

Рисуем линию с заливкой и подписываем прямо на ней то, ради чего в график
смотрят: сегодняшний курс, минимум и максимум периода, изменение за период.
Цвет — от направления: вырос зелёный, упал красный. Так ответ читается с
одного взгляда, ещё до чтения подписи.

Модуль отдельный по той же причине, что и activity_chart: matplotlib тяжёлый,
и его импорт стоит держать в одном месте, а сама отрисовка — чистая функция
без сети, БД и aiogram, которую легко проверить отдельно.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional, Sequence

import matplotlib

matplotlib.use("Agg")      # без дисплея — рендерим на сервере в память

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# Тёмный фон под стиль сайта: биржу смотрят в чате, но карточка должна быть
# узнаваемо той же, что и панель.
BG = "#14100f"
PANEL = "#201917"
GRID = "#3a2d2a"
TEXT = "#f3ecec"
MUTED = "#ab9ea3"
UP = "#43d6a0"
DOWN = "#ff5c6c"
FLAT = "#ffb454"

# Меньше двух точек — это не график, а точка: линию по ней не провести, и
# честнее ответить текстом (см. bot.py, там это и решается).
MIN_POINTS = 2


def _color(first: float, last: float) -> str:
    if last > first:
        return UP
    if last < first:
        return DOWN
    return FLAT


def _money(value: float) -> str:
    """Курс всегда с двумя знаками: 4 и 4.00 — одно и то же число, но в
    столбце цифр они читаются как разные."""
    return f"{value:.2f}"


def render_stock_chart(
    points: Sequence[dict],
    *,
    title: str = "Курс акций",
    holding_shares: float = 0.0,
    holding_value: int = 0,
    width: float = 8.0,
    height: float = 4.0,
) -> Optional[BytesIO]:
    """PNG с кривой курса или None, если рисовать нечего.

    points — строки db.list_stock_price_history: price и created_at, от старых
    к новым. Всё остальное (сколько у человека акций) подписывается сбоку и на
    саму кривую не влияет.
    """
    ряд = [(p["created_at"], float(p["price"])) for p in points
           if p.get("created_at") is not None and p.get("price") is not None]
    if len(ряд) < MIN_POINTS:
        return None

    даты = [t for t, _ in ряд]
    цены = [c for _, c in ряд]
    первая, последняя = цены[0], цены[-1]
    минимум, максимум = min(цены), max(цены)
    цвет = _color(первая, последняя)
    изменение = ((последняя - первая) / первая * 100) if первая else 0.0

    fig, ax = plt.subplots(figsize=(width, height), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    ax.plot(даты, цены, color=цвет, linewidth=2.2, solid_capstyle="round", zorder=3)
    ax.fill_between(даты, цены, минимум, color=цвет, alpha=0.14, zorder=2)
    # Последняя точка — жирнее: это «сейчас», и глаз должен находить её сразу.
    ax.plot([даты[-1]], [последняя], marker="o", markersize=7, color=цвет, zorder=4)

    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.6, zorder=1)
    ax.set_axisbelow(True)
    for край in ("top", "right", "left", "bottom"):
        ax.spines[край].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)

    # Подписи дат: сколько именно точек, заранее неизвестно (история может быть
    # и за час, и за месяц) — пусть matplotlib подберёт сам, иначе на длинном
    # периоде подписи слипаются в чёрную полосу.
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))

    запас = max((максимум - минимум) * 0.15, максимум * 0.02, 0.05)
    ax.set_ylim(минимум - запас, максимум + запас)

    знак = "+" if изменение > 0 else ""
    ax.set_title(f"{title}   {_money(последняя)} i¢   {знак}{изменение:.1f}%",
                 color=TEXT, fontsize=13, fontweight="bold", pad=12, loc="left")

    подписи = [f"мин {_money(минимум)}", f"макс {_money(максимум)}"]
    if holding_shares:
        подписи.append(f"у вас {holding_shares:g} шт. на {holding_value} i¢")
    ax.text(0.995, 1.03, "   ·   ".join(подписи), transform=ax.transAxes,
            ha="right", va="bottom", color=MUTED, fontsize=9)

    fig.tight_layout()
    буфер = BytesIO()
    fig.savefig(буфер, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    буфер.seek(0)
    буфер.name = "stock.png"
    return буфер
