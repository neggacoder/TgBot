"""Разбор текста на обычные символы и эмодзи.

Эмодзи в юникоде — это не «один символ»: 👨‍👩‍👦 состоит из пяти кодпоинтов,
склеенных невидимым разделителем, а 👋🏽 — из основы и модификатора тона кожи.
Рисовать их надо целиком одной картинкой, поэтому текст сначала режется на
кластеры.

Отдельная тонкость: часть символов (©, ‼, цифры) считается эмодзи только если
следом идёт «селектор варианта» U+FE0F. Без него это обычный текст, и
превращать «(c)» в картинку нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass

_ZWJ = 0x200D           # zero width joiner — склейка составных эмодзи
_VS16 = 0xFE0F          # variation selector-16 — «показывать как эмодзи»
_KEYCAP = 0x20E3        # накладка клавиши: 1️⃣
_TAG_START, _TAG_END = 0xE0020, 0xE007E
_TAG_TERM = 0xE007F
_SKIN_FIRST, _SKIN_LAST = 0x1F3FB, 0x1F3FF
_RI_FIRST, _RI_LAST = 0x1F1E6, 0x1F1FF   # regional indicators — флаги стран

# Диапазоны, которые являются эмодзи сами по себе, без селектора варианта.
_ALWAYS_RANGES = (
    (0x1F000, 0x1F0FF),   # маджонг, игральные карты
    (0x1F18E, 0x1F18E),
    (0x1F191, 0x1F19A),
    (0x1F1E6, 0x1F1FF),   # regional indicators
    (0x1F201, 0x1F202),
    (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F),
    (0x1F232, 0x1F23A),
    (0x1F250, 0x1F251),
    (0x1F300, 0x1F320),
    (0x1F32D, 0x1F335),
    (0x1F337, 0x1F37C),
    (0x1F37E, 0x1F393),
    (0x1F3A0, 0x1F3CA),
    (0x1F3CF, 0x1F3D3),
    (0x1F3E0, 0x1F3F0),
    (0x1F3F4, 0x1F3F4),
    (0x1F3F8, 0x1F43E),
    (0x1F440, 0x1F440),
    (0x1F442, 0x1F4FC),
    (0x1F4FF, 0x1F53D),
    (0x1F54B, 0x1F54E),
    (0x1F550, 0x1F567),
    (0x1F57A, 0x1F57A),
    (0x1F595, 0x1F596),
    (0x1F5A4, 0x1F5A4),
    (0x1F5FB, 0x1F64F),
    (0x1F680, 0x1F6C5),
    (0x1F6CC, 0x1F6CC),
    (0x1F6D0, 0x1F6D2),
    (0x1F6D5, 0x1F6D7),
    (0x1F6DC, 0x1F6DF),
    (0x1F6EB, 0x1F6EC),
    (0x1F6F4, 0x1F6FC),
    (0x1F7E0, 0x1F7EB),
    (0x1F7F0, 0x1F7F0),
    (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945),
    (0x1F947, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    # BMP-символы, которые и без селектора показываются как эмодзи
    (0x231A, 0x231B),
    (0x23E9, 0x23EC),
    (0x23F0, 0x23F0),
    (0x23F3, 0x23F3),
    (0x25FD, 0x25FE),
    (0x2614, 0x2615),
    (0x2648, 0x2653),
    (0x267F, 0x267F),
    (0x2693, 0x2693),
    (0x26A1, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26CE, 0x26CE),
    (0x26D4, 0x26D4),
    (0x26EA, 0x26EA),
    (0x26F2, 0x26F3),
    (0x26F5, 0x26F5),
    (0x26FA, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2705, 0x2705),
    (0x270A, 0x270B),
    (0x2728, 0x2728),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2795, 0x2797),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
)

# Диапазоны, которые становятся эмодзи только вместе с U+FE0F.
_VS16_RANGES = (
    # Всё остальное из эмодзи-плоскости, не попавшее в _ALWAYS_RANGES:
    # 🏳 ⛱ 🕹 и десятки других рисуются как эмодзи только с селектором.
    # Дешевле накрыть плоскость целиком, чем перечислять дырки поимённо.
    (0x1F000, 0x1FAFF),
    (0x00A9, 0x00A9),     # ©
    (0x00AE, 0x00AE),     # ®
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),     # ™
    (0x2139, 0x2139),
    (0x2194, 0x21AA),
    (0x231A, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B00, 0x2BFF),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3299),
)


# Досрочный выход в _in_ranges требует возрастающего порядка, а диапазоны
# выше сгруппированы по смыслу, а не по значению — сортируем один раз здесь.
_ALWAYS_RANGES = tuple(sorted(_ALWAYS_RANGES))
_VS16_RANGES = tuple(sorted(_VS16_RANGES))


def _in_ranges(cp: int, ranges: tuple) -> bool:
    for low, high in ranges:
        if cp < low:
            return False
        if cp <= high:
            return True
    return False


def _is_always_emoji(cp: int) -> bool:
    return _in_ranges(cp, _ALWAYS_RANGES)


def _is_emoji_capable(cp: int) -> bool:
    """Может быть эмодзи — сам по себе или в паре с селектором варианта."""
    return _is_always_emoji(cp) or _in_ranges(cp, _VS16_RANGES)


@dataclass
class Token:
    """Кусок текста: либо обычные символы, либо один эмодзи-кластер."""

    kind: str      # "text" | "emoji"
    value: str
    start: int     # позиция в исходной строке, в кодпоинтах Python
    end: int


def _match_cluster(text: str, i: int) -> int:
    """Конец эмодзи-кластера, начинающегося на позиции i. Если там не эмодзи —
    возвращает i (то есть «ничего не съели»)."""
    n = len(text)
    cp = ord(text[i])

    # накладка на клавишу: 1️⃣ #️⃣ — цифра/решётка + (селектор) + U+20E3
    if text[i] in "0123456789#*":
        j = i + 1
        if j < n and ord(text[j]) == _VS16:
            j += 1
        if j < n and ord(text[j]) == _KEYCAP:
            return j + 1
        return i

    # флаг страны — ровно два regional indicator подряд
    if _RI_FIRST <= cp <= _RI_LAST:
        if i + 1 < n and _RI_FIRST <= ord(text[i + 1]) <= _RI_LAST:
            return i + 2
        return i + 1

    # флаги-субрегионы (Англия, Шотландия, Уэльс): основа + теги + терминатор
    if cp == 0x1F3F4:
        j = i + 1
        while j < n and _TAG_START <= ord(text[j]) <= _TAG_END:
            j += 1
        if j > i + 1 and j < n and ord(text[j]) == _TAG_TERM:
            return j + 1

    if not _is_always_emoji(cp):
        # символ вроде © — эмодзи только если следом селектор варианта
        if not (_in_ranges(cp, _VS16_RANGES) and i + 1 < n and ord(text[i + 1]) == _VS16):
            return i

    j = i + 1
    while True:
        # селекторы, тона кожи, накладки клавиш — часть текущего кластера
        while j < n:
            c = ord(text[j])
            if c == _VS16 or c == _KEYCAP or _SKIN_FIRST <= c <= _SKIN_LAST:
                j += 1
            else:
                break
        # склейка составных эмодзи: 👨‍👩‍👦, 🏳️‍🌈
        if j + 1 < n and ord(text[j]) == _ZWJ and _is_emoji_capable(ord(text[j + 1])):
            j += 2
            continue
        break
    return j


def tokenize(text: str) -> list:
    """Режет текст на список Token: обычные куски и отдельные эмодзи."""
    tokens: list = []
    n = len(text)
    i = 0
    plain_start = 0

    def flush(upto: int) -> None:
        if upto > plain_start:
            tokens.append(Token("text", text[plain_start:upto], plain_start, upto))

    while i < n:
        end = _match_cluster(text, i)
        if end > i:
            flush(i)
            tokens.append(Token("emoji", text[i:end], i, end))
            i = end
            plain_start = i
        else:
            i += 1

    flush(n)
    return tokens


def has_emoji(text: str) -> bool:
    return any(t.kind == "emoji" for t in tokenize(text))
