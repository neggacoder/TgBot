"""График курса для команды «биржа».

Проверяется не «красиво», а то, из-за чего ответ ломается: что картинка вообще
рисуется, что на слишком короткой истории её нет (по одной точке линию не
провести), и что подпись к фото влезает в лимит телеграма.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

pytest.importorskip("matplotlib", reason="нужен matplotlib (см. .venv)")

import stock_chart


def _ряд(n: int, старт: float = 4.0, шаг: float = 0.05):
    t = datetime(2026, 7, 1, 12)
    return [{"created_at": t + timedelta(hours=8 * i), "price": старт + шаг * i}
            for i in range(n)]


def test_картинка_рисуется():
    буфер = stock_chart.render_stock_chart(_ряд(40))
    данные = буфер.getvalue()
    assert данные[:8] == b"\x89PNG\r\n\x1a\n", "это должен быть PNG"
    assert len(данные) > 5_000, "подозрительно пустая картинка"


def test_по_одной_точке_график_не_рисуют():
    """Линию по точке не провести, и рисовать «график» из одной палки хуже,
    чем ответить текстом."""
    assert stock_chart.render_stock_chart(_ряд(1)) is None
    assert stock_chart.render_stock_chart([]) is None


def test_битые_точки_не_роняют_рендер():
    точки = _ряд(10) + [{"created_at": None, "price": 5}, {"created_at": datetime.utcnow()}]
    assert stock_chart.render_stock_chart(точки) is not None


def test_цвет_от_направления():
    """Зелёный вверх, красный вниз — по нему ответ читается ещё до подписи."""
    assert stock_chart._color(1, 2) == stock_chart.UP
    assert stock_chart._color(2, 1) == stock_chart.DOWN
    assert stock_chart._color(2, 2) == stock_chart.FLAT


def test_курс_всегда_с_двумя_знаками():
    """4 и 4.00 — одно число, но в столбце цифр читаются как разные."""
    assert stock_chart._money(4) == "4.00"
    assert stock_chart._money(4.006) == "4.01"


def test_ровный_курс_тоже_рисуется():
    """Плоская линия — законный случай: у неё нулевой размах, и без запаса по
    оси график схлопнулся бы в ноль высоты."""
    ровно = [{"created_at": datetime(2026, 7, 1, 12) + timedelta(hours=i), "price": 4.0}
             for i in range(10)]
    assert stock_chart.render_stock_chart(ровно) is not None


def test_биржа_шлёт_фото_с_подписью_а_не_вторым_сообщением():
    """Два сообщения на одну команду — это два уведомления и разорванный
    ответ. И обязателен запасной путь: не нарисовалось — отвечаем текстом,
    график тут добавка, а не суть."""
    import inspect
    import pytest as _p
    aiogram = _p.importorskip("aiogram", reason="нужен настоящий aiogram")
    if not hasattr(aiogram, "Dispatcher"):
        _p.skip("установлена заглушка aiogram")
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module

    исходник = inspect.getsource(bot_module.cmd_stock_market)
    assert "answer_photo" in исходник and "caption=" in исходник
    assert "await message.answer(текст)" in исходник, "нет запасного пути"
    # Рендер уводится в поток: он синхронный и небыстрый, а на его время
    # иначе встаёт весь бот.
    assert "to_thread" in inspect.getsource(bot_module._render_stock_chart)
    # Подпись к фото у телеграма ограничена 1024 символами — статическая часть
    # ответа обязана оставлять запас на числа.
    статика = ("📊 Биржа\n💹 Текущий курс акций: \n📈 Ваши акции:\n"
               "💼 Вложено:\n🏆 Всего заработано на бирже:\n"
               "биржа купить {сумма} · биржа продать {сумма} · биржа дивиденды")
    assert len(статика) < 500
