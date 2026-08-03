"""
Генератор графика активности пользователя («Статистика активности» — как на
карточке профиля у Iris) для команды «кто я» / «профиль» в bot.py.

Рисует столбчатую диаграмму количества сообщений по дням за последние
ACTIVITY_CHART_DAYS дней (по умолчанию 57 — как на референсе Iris: чуть
меньше двух месяцев). Сегодняшний столбец выделяется отдельным цветом.

Использование (из bot.py):

    from activity_chart import render_activity_chart, ACTIVITY_CHART_DAYS

    rows = await db.list_daily_counts_for_user(chat_id, user_id, since_day)
    png_bytes = render_activity_chart(rows)   # BytesIO, готов к send_photo

Вынесено в отдельный файл, а не в bot.py, по двум причинам:
1. matplotlib — тяжёлая и не всегда нужная зависимость (нужна только для
   этого одного графика) — держим её импорт локализованным в одном модуле.
2. Это чистая функция рендера без сети/aiogram/БД — её легко тестировать и
   менять оформление графика отдельно от логики бота.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO

import matplotlib

matplotlib.use("Agg")  # без дисплея — рендерим на сервере в файл/память

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# Сколько дней показывать на графике по умолчанию (если у пользователя
# достаточно долгая история — см. ACTIVITY_CHART_MIN_DAYS ниже и подбор
# фактического периода в bot.py._render_profile_chart).
ACTIVITY_CHART_DAYS = 57
# Минимальная ширина графика (в днях) — даже для совсем нового участника
# показываем хотя бы этот период, чтобы график не схлопывался в 1-2 столбца.
ACTIVITY_CHART_MIN_DAYS = 7

# Цвета — под стиль референса (салатовые столбцы, синеватый заголовок,
# сегодняшний столбец — отдельным акцентным цветом).
BAR_COLOR = "#c6e654"
BAR_COLOR_TODAY = "#ff7043"
GRID_COLOR = "#eeeef3"
BASELINE_COLOR = "#d8d9e3"
AXIS_COLOR = "#a3a7b7"
TITLE_COLOR = "#5b6bd6"

# "Круглые" шаги для делений оси Y — как у референса (0/20/40/…/300), а не
# рваные числа вроде 0/17.25/34.5. Подбирается наименьший шаг из списка,
# дающий не больше ~7 делений на всю высоту графика.
_Y_STEP_CANDIDATES = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)


def _nice_y_step(max_value: int) -> int:
    target = max(max_value, 1)
    for step in _Y_STEP_CANDIDATES:
        if target / step <= 7:
            return step
    return _Y_STEP_CANDIDATES[-1]


def _daily_series(rows: list[dict], days: int,
                  today: date | None = None) -> tuple[list[date], list[int]]:
    """Достраивает непрерывный ряд по дням за последние `days` дней (включая
    сегодня) — дни без сообщений получают 0. Без этого столбцы графика были
    бы расставлены только по «активным» дням, а не по равномерной шкале дат,
    как на референсе.

    Сегодня — по UTC, потому что rows приходят из message_daily, а её сутки
    размечены UTC при записи. Раньше тут стоял date.today() — зона
    ОПЕРАЦИОННОЙ СИСТЕМЫ: на сервере восточнее UTC последний столбец графика
    оказывался завтрашним днём, а сегодняшние сообщения в ряд не попадали
    вовсе."""
    today = today or datetime.utcnow().date()
    counts_by_day = {row["day"]: row["message_count"] for row in rows}
    series_days = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    series_counts = [int(counts_by_day.get(d, 0)) for d in series_days]
    return series_days, series_counts


def render_activity_chart(
    rows: list[dict], days: int = ACTIVITY_CHART_DAYS, title: str = "Статистика активности",
    today: date | None = None,
) -> BytesIO:
    """rows — результат db.list_daily_counts_for_user(...) (или
    db.list_daily_counts_for_chat(...) — формат строк одинаковый):
    [{"day": date(...), "message_count": int}, ...] (порядок не важен).

    title — заголовок графика; по умолчанию как в профиле пользователя
    («Статистика активности»), но для «Чат стата»/«Чат инфо» вызывающий код
    передаёт «Статистика чата», чтобы график читался однозначно.

    Возвращает PNG-картинку в памяти (BytesIO, позиция уже сброшена на
    начало — готова для BufferedInputFile/send_photo)."""
    series_days, series_counts = _daily_series(rows, days, today)

    fig, ax = plt.subplots(figsize=(7.4, 3.6), dpi=130)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    colors = [BAR_COLOR] * len(series_days)
    if colors:
        colors[-1] = BAR_COLOR_TODAY  # сегодняшний столбец — акцентным цветом

    ax.bar(series_days, series_counts, color=colors, width=0.72, zorder=3)

    ax.set_title(title, color=TITLE_COLOR, fontsize=13.5, fontweight="bold", pad=12)

    # Числа делений — справа от графика, без подписи оси (référence не
    # подписывает "Сообщений" отдельно — это и так понятно из контекста).
    ax.yaxis.tick_right()

    max_count = max(series_counts, default=0)
    y_step = _nice_y_step(max_count)
    y_top = ((max_count // y_step) + 1) * y_step if max_count else y_step
    ax.set_ylim(0, y_top)
    ax.yaxis.set_major_locator(plt.MultipleLocator(y_step))

    # Сетка — ровно по каждому делению оси Y, во всю ширину графика (как у
    # референса), а не только "внутри" столбцов.
    ax.grid(axis="y", color=GRID_COLOR, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.axhline(0, color=BASELINE_COLOR, linewidth=1, zorder=2)  # тонкая база под столбцами

    ax.tick_params(axis="y", colors=AXIS_COLOR, labelsize=8.5, length=0)
    ax.tick_params(axis="x", colors=AXIS_COLOR, labelsize=8.5, length=0)

    # Шаг подписей дат — под фактическую длину периода (~10-12 подписей
    # на график), а не фиксированный: для новых участников период короче
    # (см. ACTIVITY_CHART_MIN_DAYS в bot.py), и с шагом «раз в 4 дня» там
    # могла бы остаться всего одна подпись на весь график.
    tick_step = max(1, round(days / 11))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_step))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.autofmt_xdate(rotation=0, ha="center")

    ax.set_xlim(series_days[0] - timedelta(days=0.6), series_days[-1] + timedelta(days=0.6))

    fig.tight_layout(pad=1.2)

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def render_hourly_chart(
    rows: list[dict], title: str = "Статистика по часам", highlight_hour: "int | None" = None
) -> BytesIO:
    """Столбчатая диаграмма активности по часам суток (0-23).

    rows — [{"hour": int (0-23), "message_count": int}, ...] (порядок не
    важен, часы без сообщений можно не передавать — достраиваются нулями).
    Используется и для «типичного дня» пользователя (db.list_hourly_pattern_for_user
    — агрегат по многим дням), и для «последних 24 часов» чата
    (db.list_hourly_last_24h_for_chat, где нужно предварительно свернуть
    строки по (day, hour) в один час суток на стороне вызывающего кода, если
    там встречаются оба дня диапазона).

    highlight_hour — если задан (0-23), этот час подсвечивается акцентным
    цветом (текущий час — как «сегодняшний» столбец в render_activity_chart).

    Возвращает PNG в памяти (BytesIO, готов к отправке)."""
    counts_by_hour = {int(row["hour"]): int(row["message_count"]) for row in rows}
    hours = list(range(24))
    series_counts = [counts_by_hour.get(h, 0) for h in hours]
    labels = [f"{h:02d}" for h in hours]

    fig, ax = plt.subplots(figsize=(7.4, 3.6), dpi=130)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    colors = [BAR_COLOR] * 24
    if highlight_hour is not None and 0 <= highlight_hour < 24:
        colors[highlight_hour] = BAR_COLOR_TODAY

    ax.bar(hours, series_counts, color=colors, width=0.72, zorder=3)

    ax.set_title(title, color=TITLE_COLOR, fontsize=13.5, fontweight="bold", pad=12)
    ax.yaxis.tick_right()

    max_count = max(series_counts, default=0)
    y_step = _nice_y_step(max_count)
    y_top = ((max_count // y_step) + 1) * y_step if max_count else y_step
    ax.set_ylim(0, y_top)
    ax.yaxis.set_major_locator(plt.MultipleLocator(y_step))

    ax.grid(axis="y", color=GRID_COLOR, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.axhline(0, color=BASELINE_COLOR, linewidth=1, zorder=2)

    ax.tick_params(axis="y", colors=AXIS_COLOR, labelsize=8.5, length=0)
    ax.tick_params(axis="x", colors=AXIS_COLOR, labelsize=8, length=0)
    ax.set_xticks(hours)
    ax.set_xticklabels(labels, rotation=0)
    # Каждую вторую подпись прячем — иначе 24 подписи слипаются на ширине графика.
    for i, tick_label in enumerate(ax.get_xticklabels()):
        if i % 2 == 1:
            tick_label.set_visible(False)

    ax.set_xlim(-0.7, 23.7)

    fig.tight_layout(pad=1.2)

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf
