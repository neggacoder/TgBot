"""Раскладка текста: entities → стилизованные отрезки → строки по ширине.

Здесь же живёт вечная ловушка Telegram Bot API: offset/length в entities
считаются в кодовых единицах UTF-16, а Python индексирует строку по
кодпоинтам. Любое эмодзи вне BMP занимает два UTF-16-юнита — и если не
пересчитать, всё форматирование после первого эмодзи в сообщении уезжает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import assets, emoji as emoji_mod, theme

# Типы entity, которые рисуются моноширинным шрифтом.
_MONO_TYPES = {"code", "pre", "pre_code"}
# Типы, которые красятся в «ссылочный» цвет.
_LINK_TYPES = {
    "mention", "text_mention", "hashtag", "cashtag", "email",
    "phone_number", "bot_command", "url", "text_link",
}
_STYLE_BY_TYPE = {
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "strikethrough": "strike",
    "spoiler": "spoiler",
}


@dataclass
class Segment:
    """Непрерывный кусок с одинаковым оформлением: либо текст, либо эмодзи."""

    kind: str                       # "text" | "emoji"
    value: str
    styles: frozenset = frozenset()
    width: float = 0.0

    @property
    def is_emoji(self) -> bool:
        return self.kind == "emoji"


@dataclass
class Line:
    segments: list = field(default_factory=list)
    width: float = 0.0


def _entity_attr(entity, name, default=None):
    """Достаёт поле из aiogram-объекта или из словаря — рендер не должен
    зависеть от того, чем именно его накормили."""
    if isinstance(entity, dict):
        return entity.get(name, default)
    return getattr(entity, name, default)


def _utf16_offsets(text: str) -> list:
    """Для каждого UTF-16 смещения — соответствующий индекс в Python-строке."""
    mapping = {}
    u = 0
    for i, ch in enumerate(text):
        mapping[u] = i
        u += 2 if ord(ch) > 0xFFFF else 1
    mapping[u] = len(text)
    return mapping


def _styles_per_char(text: str, entities: Optional[list]) -> list:
    """Набор стилей для каждого символа строки."""
    per_char = [set() for _ in text]
    if not entities:
        return per_char

    u16 = _utf16_offsets(text)
    limit = len(text)

    for entity in entities:
        etype = _entity_attr(entity, "type")
        if not etype:
            continue
        if etype in _MONO_TYPES:
            style = "mono"
        elif etype in _LINK_TYPES:
            style = "link"
        else:
            style = _STYLE_BY_TYPE.get(etype)
        if style is None:
            continue

        offset = _entity_attr(entity, "offset", 0) or 0
        length = _entity_attr(entity, "length", 0) or 0
        start = u16.get(offset)
        end = u16.get(offset + length)
        # Смещение может указывать внутрь суррогатной пары или за конец
        # строки, если сообщение где-то по дороге обрезали — не падаем.
        if start is None:
            start = min(offset, limit)
        if end is None:
            end = min(offset + length, limit)
        for i in range(max(0, start), min(end, limit)):
            per_char[i].add(style)

    return per_char


def _font_for(styles: frozenset, size: int):
    if "mono" in styles:
        return assets.font(size, mono=True)
    return assets.font(size, bold="bold" in styles, italic="italic" in styles)


def build_segments(text: str, entities: Optional[list], size: int) -> list:
    """Текст + entities → список отрезков, готовых к измерению и отрисовке.

    Отрезок обрывается на смене оформления, на границе эмодзи и на переводе
    строки (перевод отдаётся отдельным отрезком-маркером).
    """
    per_char = _styles_per_char(text, entities)
    emoji_size = round(size * theme.EMOJI_SCALE)
    segments: list = []

    for token in emoji_mod.tokenize(text):
        if token.kind == "emoji":
            styles = frozenset(per_char[token.start]) if token.start < len(per_char) else frozenset()
            segments.append(
                Segment("emoji", token.value, styles, float(emoji_size))
            )
            continue

        # обычный текст: режем по сменам стиля и переводам строки
        buf = ""
        buf_styles: Optional[frozenset] = None
        for i in range(token.start, token.end):
            ch = text[i]
            styles = frozenset(per_char[i]) if i < len(per_char) else frozenset()
            if ch == "\n":
                if buf:
                    segments.append(_make_text_segment(buf, buf_styles, size))
                    buf, buf_styles = "", None
                segments.append(Segment("newline", "\n", styles, 0.0))
                continue
            if buf_styles is None or styles == buf_styles:
                buf += ch
                buf_styles = styles
            else:
                segments.append(_make_text_segment(buf, buf_styles, size))
                buf, buf_styles = ch, styles
        if buf:
            segments.append(_make_text_segment(buf, buf_styles, size))

    return segments


def _make_text_segment(value: str, styles: Optional[frozenset], size: int) -> Segment:
    styles = styles or frozenset()
    font = _font_for(styles, size)
    return Segment("text", value, styles, font.getlength(value))


def _split_into_words(segments: list, size: int) -> list:
    """Группирует отрезки в «слова» — единицы, которые нельзя разрывать.

    Возвращает список групп; группа = (список отрезков, это_перевод_строки).
    Пробелы прилипают к предыдущему слову, чтобы при переносе они не
    оказывались в начале новой строки.
    """
    words: list = []
    current: list = []

    def flush():
        if current:
            words.append((list(current), False))
            current.clear()

    for seg in segments:
        if seg.kind == "newline":
            flush()
            words.append(([], True))
            continue
        if seg.is_emoji:
            # эмодзи — само по себе слово, рвать вокруг него можно
            flush()
            words.append(([seg], False))
            continue

        # текстовый отрезок режем по пробелам
        parts = seg.value.split(" ")
        for idx, part in enumerate(parts):
            if idx > 0:
                space = _make_text_segment(" ", seg.styles, size)
                if current:
                    # пробел завершает набранное слово
                    current.append(space)
                    flush()
                elif words and not words[-1][1]:
                    # слово уже закрыто (например, отрезком-эмодзи) — пробел
                    # прилипает к нему, иначе «👋 как» склеится в «👋как»
                    words[-1][0].append(space)
                else:
                    # пробел в начале строки — сохраняем отдельным словом
                    words.append(([space], False))
            if part:
                current.append(Segment("text", part, seg.styles, 0.0))
    flush()
    return words


def layout(
    text: str,
    entities: Optional[list],
    size: int,
    max_width: float,
    max_lines: int,
) -> list:
    """Раскладывает текст в строки, влезающие в max_width.

    Длиннее max_lines не возвращает — хвост заменяется многоточием.
    """
    segments = build_segments(text, entities, size)
    words = _split_into_words(segments, size)

    lines: list = []
    current: list = []
    current_width = 0.0
    # текст кончился не сам — упёрлись в лимит строк, нужно многоточие
    overflowed = False

    def push_line():
        nonlocal current, current_width
        # хвостовые пробелы не должны раздувать ширину бабла
        while current and current[-1].kind == "text" and not current[-1].value.strip():
            current_width -= current[-1].width
            current.pop()
        lines.append(Line(list(current), max(0.0, current_width)))
        current = []
        current_width = 0.0

    for index, (word_segments, is_newline) in enumerate(words):
        if len(lines) >= max_lines:
            overflowed = True
            break

        if is_newline:
            push_line()
            continue

        word_width = sum(_measure(seg, size) for seg in word_segments)

        # не влезает в текущую строку — переносим
        if current and current_width + word_width > max_width:
            push_line()
            if len(lines) >= max_lines:
                # слово, ради которого переносили, уже некуда положить
                overflowed = True
                break

        # не влезает даже в пустую строку (длинная ссылка) — режем посимвольно
        if word_width > max_width:
            for piece in _break_long_word(word_segments, size, max_width):
                if current and current_width + piece.width > max_width:
                    push_line()
                    if len(lines) >= max_lines:
                        overflowed = True
                        break
                current.append(piece)
                current_width += piece.width
            if overflowed:
                break
            continue

        current.extend(word_segments)
        current_width += word_width

    if current:
        if len(lines) < max_lines:
            push_line()
        else:
            overflowed = True

    if overflowed and lines:
        _append_ellipsis(lines[-1], size, max_width)
    return lines


def _measure(seg: Segment, size: int) -> float:
    if seg.is_emoji:
        return round(size * theme.EMOJI_SCALE)
    if not seg.width:
        seg.width = _font_for(seg.styles, size).getlength(seg.value)
    return seg.width


def _break_long_word(word_segments: list, size: int, max_width: float) -> list:
    """Режет слишком длинное слово на куски, влезающие в строку."""
    out: list = []
    for seg in word_segments:
        if seg.is_emoji:
            _measure(seg, size)
            out.append(seg)
            continue
        font = _font_for(seg.styles, size)
        buf = ""
        for ch in seg.value:
            trial = buf + ch
            if buf and font.getlength(trial) > max_width:
                out.append(Segment("text", buf, seg.styles, font.getlength(buf)))
                buf = ch
            else:
                buf = trial
        if buf:
            out.append(Segment("text", buf, seg.styles, font.getlength(buf)))
    return out


def _append_ellipsis(line: Line, size: int, max_width: float) -> None:
    """Дописывает «…» в конец строки, ужимая её при необходимости."""
    styles = line.segments[-1].styles if line.segments else frozenset()
    font = _font_for(styles, size)
    dots_width = font.getlength("…")

    while line.segments and line.width + dots_width > max_width:
        dropped = line.segments.pop()
        line.width -= dropped.width
        if dropped.kind == "text" and len(dropped.value) > 1:
            # от длинного куска отрезаем по символу, а не выкидываем целиком
            shortened = dropped.value[:-1]
            while shortened and line.width + font.getlength(shortened) + dots_width > max_width:
                shortened = shortened[:-1]
            if shortened:
                seg = Segment("text", shortened, dropped.styles, font.getlength(shortened))
                line.segments.append(seg)
                line.width += seg.width
            break

    line.segments.append(Segment("text", "…", styles, dots_width))
    line.width += dots_width
