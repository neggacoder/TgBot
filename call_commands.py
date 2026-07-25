"""Распознавание команд созыва.

Вынесено из bot.py по той же причине, что и rest_rules.py: модуль не знает ни
про Telegram, ни про базу, поэтому его можно проверить тестами без сети — а
bot.py к этому моменту около мегабайта, и класть туда ещё одну пачку условий
незачем.

Главная тонкость здесь — где у сообщения лежит текст. Созыв часто пишут
подписью к картинке («созыв, все сюда» + афиша), а у медиа-сообщения
message.text пустой: Telegram кладёт подпись в message.caption. Фильтр,
смотрящий только на .text, такую команду не видит вовсе — именно поэтому созыв
«не работал с фотографиями».
"""

from __future__ import annotations

from typing import Optional

CALL_TRIGGERS = ("созыв", "калл", "call", "all", "алл","хуйланы_сюда","хуйланысюда")
CALL_ADMIN_PHRASES = ("калладминс", "созыв админов", "call admins")
CALL_STOP_TRIGGERS = ("стоп", "стой", "отмена", "остановить призыв", "stopcall")


# Знаки, которыми обычно кончается обращение: «созыв, все сюда», «созыв!».
# Без их снятия первое слово получается «созыв,» и с триггером не совпадает —
# команда молча не срабатывает, а человек видит, что бот его игнорирует.
TRIGGER_PUNCTUATION = ".,!?:;—-…"


def first_word(text: Optional[str]) -> str:
    return text.strip().split(maxsplit=1)[0].casefold() if text and text.strip() else ""


def trigger_word(text: Optional[str]) -> str:
    """Первое слово без обрамляющей пунктуации — то, что сравнивается с
    триггерами команд."""
    return first_word(text).strip(TRIGGER_PUNCTUATION)


def command_text(message) -> Optional[str]:
    """Текст команды: у обычного сообщения — .text, у фото, видео и документа —
    .caption. Принимает любой объект с этими полями, поэтому проверяется без
    настоящего aiogram."""
    return getattr(message, "text", None) or getattr(message, "caption", None)


def is_call_admins_cmd(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return False
    low = text.strip().casefold()
    return trigger_word(text) == "калладминс" or any(low.startswith(p) for p in CALL_ADMIN_PHRASES)


def is_call_all_cmd(text: Optional[str]) -> bool:
    """Созыв всех. Созыв админов — отдельная команда, и её первое слово тоже
    начинается на «созыв», поэтому её здесь явно исключаем."""
    if not text or not text.strip():
        return False
    return trigger_word(text) in CALL_TRIGGERS and not is_call_admins_cmd(text)


def is_call_stop_cmd(text: Optional[str]) -> bool:
    """Остановка — команда из одного слова, поэтому здесь сравнивается вся
    строка целиком (со снятой пунктуацией: «стоп!» — та же команда)."""
    if not text or not text.strip():
        return False
    return text.strip().casefold().strip(TRIGGER_PUNCTUATION) in CALL_STOP_TRIGGERS


def call_header(text: Optional[str]) -> Optional[str]:
    """Текст, который бот повторит над каждой пачкой упоминаний: всё, что идёт
    после самого слова команды. None, если команду прислали без пояснения."""
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
