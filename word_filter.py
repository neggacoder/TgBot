"""Фильтр слов: сопоставление текста сообщения со списком запрещённых слов.

Модуль намеренно ничего не знает ни про Telegram, ни про базу — bot.py держит
список в памяти и передаёт его сюда, а middleware по результату решает, удалять
сообщение или нет. Так логику совпадения можно проверить тестами без сети.

Сопоставление — по ЦЕЛОМУ слову и без учёта регистра. «спам» удалит «это спам»,
но не тронет «спамить» или «антиспам»: подстроковый матч ловил бы «класс» по
слову «асс», а это хуже пропущенного спама. Многословную запись («плохая
фраза») ищем как фразу целиком, тоже по границам слов.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# \w в юникод-режиме (по умолчанию для str) включает кириллицу, латиницу, цифры
# и подчёркивание — этого достаточно, чтобы разбить сообщение на слова.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def normalize(word: str) -> str:
    """Приводит слово к виду для сравнения: без пробелов по краям, в нижнем
    регистре (casefold корректно опускает и кириллицу, и ё/Ё)."""
    return (word or "").strip().casefold()


def tokenize(text: str) -> set:
    """Множество слов сообщения в нижнем регистре — для быстрой проверки
    однословных запретов членством, а не регулярками по каждому слову."""
    return set(_TOKEN_RE.findall((text or "").casefold()))


def find_banned(text: Optional[str], banned: Iterable[str]) -> Optional[str]:
    """Первое запрещённое слово/фраза, найденное в тексте, либо None.

    Возвращает саму запись из списка (как её задал админ) — bot.py пишет её в
    журнал, чтобы модератор видел, что именно сработало.
    """
    if not text or not banned:
        return None

    text_cf = text.casefold()
    tokens = None  # ленивая токенизация: считаем один раз и только если нужна

    for raw in banned:
        word = normalize(raw)
        if not word:
            continue
        if " " in word:
            # Фраза: ищем как целое, ограниченное границами слов, чтобы
            # «плохая фраза» не срабатывала внутри «неплохая фразочка».
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text_cf):
                return raw
        else:
            if tokens is None:
                tokens = tokenize(text)
            if word in tokens:
                return raw
    return None


def has_banned(text: Optional[str], banned: Iterable[str]) -> bool:
    return find_banned(text, banned) is not None
