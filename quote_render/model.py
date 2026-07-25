"""Входные данные рендера — то, что бот собирает из Telegram-сообщения."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QuoteMessage:
    """Одно сообщение для цитаты.

    entities — список aiogram MessageEntity как есть; рендер сам разберётся,
    что из них умеет рисовать. avatar_bytes/media_bytes — уже скачанные
    файлы, ходить в сеть за ними рендер не будет.
    """

    user_id: int
    name: str
    text: str = ""
    entities: Optional[list] = None
    avatar_bytes: Optional[bytes] = None
    media_bytes: Optional[bytes] = None
    reply_name: Optional[str] = None
    reply_text: Optional[str] = None
    reply_chat_id: int = 0

    def __post_init__(self) -> None:
        if self.entities is None:
            self.entities = []
