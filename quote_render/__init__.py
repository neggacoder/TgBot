"""Рендер цитат-стикеров в виде телеграм-баблов (как у бота @QuotLyBot)."""

from .model import QuoteMessage

__all__ = ["QuoteMessage", "render_quote"]


def render_quote(messages, max_width: int = 512):
    """Рисует список сообщений одним изображением-цитатой.

    Импорт рендера отложен внутрь функции: он тянет за собой шрифты и сеть, а
    сам пакет импортируется при старте бота, когда рисовать ещё нечего.
    """
    from .layout import render_quote as _render

    return _render(messages, max_width=max_width)
