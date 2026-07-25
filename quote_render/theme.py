"""Константы оформления — портированы из исходников LyoSU/quote-api (движок
бота @QuotLyBot), чтобы стикер выглядел один в один как у него.

Все размеры — в логических пикселях: рендер идёт в SCALE раз крупнее, а
итоговая картинка ужимается до 512 (см. layout.py). Числа не подбирались на
глаз — рядом с каждым блоком указан файл-первоисточник.
"""

from __future__ import annotations

# Во сколько раз рендерим крупнее логического размера. У quote-api дефолт 2
# (methods/generate.js), но мы всё равно ужимаем результат до 512 под стикер,
# поэтому берём 3 — запас на сглаживание при downscale.
SCALE = 3

# --- геометрия бабла (utils/quote-generate/composer.js, объект SP) ---------
PAD_X = 16              # горизонтальный внутренний отступ
PAD_Y = 12              # вертикальный внутренний отступ
GAP = 5                 # вертикальный зазор между блоками внутри бабла
RADIUS = 25             # радиус скругления бабла
RADIUS_GROUPED = 7      # радиус угла, обращённого к соседнему баблу автора
SHADOW_PAD = 12         # поле канваса справа/снизу под тень
SHADOW_PAD_TOP = 4      # то же сверху
GLASS = 1.25            # толщина «стеклянной» линии по краю бабла
TAIL = 14               # размер хвостика (рисуется только когда есть аватар)
MIN_WIDTH = 100         # минимальная ширина бабла
AVATAR = 50             # диаметр аватара
AVATAR_GAP = 10         # зазор аватар → бабл
MEDIA_ROUND = 12        # радиус скругления медиа внутри бабла
REPLY_THUMB = 34        # сторона миниатюры в reply-блоке

# Зазоры между соседними сообщениями (methods/generate.js)
GAP_SAME_AUTHOR = 2     # внутри группы одного отправителя
GAP_DIFF_AUTHOR = 6     # между группами разных отправителей

# --- accent-блок: reply и цитата (composer.js, SP.block) -------------------
BLOCK_PAD_Y = 6
BLOCK_PAD_L = 10
BLOCK_PAD_R = 10
BLOCK_BAR = 3.5         # ширина вертикальной полосы слева
BLOCK_RADIUS = 7
BLOCK_TINT = 0.14       # прозрачность подложки блока
BLOCK_GAP = 3

# --- шрифты (utils/quote-generate/index.js) -------------------------------
FONT_NAME = 18          # имя отправителя (всегда bold)
FONT_TEXT = 24          # текст сообщения
FONT_REPLY_NAME = 14
FONT_REPLY_TEXT = 15
LINE_HEIGHT_FACTOR = 1.2  # text-prepare.js: lineHeight = fontSize * 1.2

# Метрики строки считаются детерминированно, а не по реальным глифам
# (text-prepare.js:51-67) — иначе высота бабла скакала бы от того, есть ли в
# строке буквы с выносными элементами.
ASCENT_FACTOR = 0.85
DESCENT_FACTOR = 0.30

# --- цвета ----------------------------------------------------------------
# Фон бабла — линейный градиент по диагонали (color.js: базовый '#292232'
# осветляется на 35% для старта и затемняется на 15% для конца).
BG_GRADIENT_FROM = (0x37, 0x2E, 0x44)
BG_GRADIENT_TO = (0x23, 0x1D, 0x2B)

TEXT_COLOR = (0xFF, 0xFF, 0xFF)

# Палитра имён. Индекс — abs(user_id) % 7.
#
# Это уже ИТОГОВЫЕ цвета: в оригинале палитра из constants.js прогоняется
# через коррекцию контраста относительно фона (index.js:74-78), и для нашего
# фона она срабатывает на всех семи цветах. Считать её в рантайме незачем —
# фон у нас фиксированный, поэтому таблица посчитана заранее. Исходные цвета
# палитры указаны в комментариях: видно, что сдвиг мелкий (−5…+4 на канал).
NAME_COLORS_DARK = [
    (0xFF, 0x8E, 0x86),   # #FF8E86 — не изменился
    (0xFB, 0x9F, 0x53),   # #FFA357 −4
    (0xB5, 0x93, 0xFF),   # #B18FFF +4 (синий упёрся в 255)
    (0x4F, 0xD8, 0xC1),   # #4DD6BF +2
    (0x42, 0xE5, 0xCE),   # #45E8D1 −3
    (0x75, 0xC4, 0xFA),   # #7AC9FF −5
    (0xFE, 0x7E, 0xD4),   # #FF7FD5 −1
]

# Градиенты кружка-заглушки аватара (constants.js) — тот же индекс.
AVATAR_GRADIENTS = [
    ((0xFF, 0x88, 0x5E), (0xFF, 0x51, 0x6A)),
    ((0xFF, 0xCD, 0x6A), (0xFF, 0xA8, 0x5C)),
    ((0xE0, 0xA2, 0xF3), (0xD6, 0x69, 0xED)),
    ((0xA0, 0xDE, 0x7E), (0x54, 0xCB, 0x68)),
    ((0x53, 0xED, 0xD6), (0x28, 0xC9, 0xB7)),
    ((0x72, 0xD5, 0xFD), (0x2A, 0x9E, 0xF1)),
    ((0xFF, 0xA8, 0xA8), (0xFF, 0x71, 0x9A)),
]

# Цвета форматирования (text-render.js). Приоритет именно такой:
# моноширинный перебивает ссылку, ссылка перебивает спойлер.
COLOR_MONO = (0x58, 0x87, 0xA7)
COLOR_LINK = (0x6A, 0xB7, 0xEC)
SPOILER_ALPHA = 0.15

# Тень бабла (composer.js)
SHADOW_COLOR = (0, 0, 0, 61)   # rgba(0,0,0,0.24)
SHADOW_BLUR = 6
SHADOW_OFFSET_Y = 2

# Стеклянная подсветка края бабла (canvas-utils.js)
GLASS_STROKE = (0xFF, 0xFF, 0xFF, 18)   # rgba(255,255,255,0.07)
GLASS_TOP_FROM = (0xFF, 0xFF, 0xFF, 41)  # rgba(255,255,255,0.16)
GLASS_TOP_HEIGHT_FACTOR = 0.4

# Эмодзи рисуются чуть крупнее кегля и приподняты над базовой линией
# (constants.js: EMOJI_SCALE, text-render.js).
EMOJI_SCALE = 1.15
EMOJI_BASELINE_LIFT = 0.85   # верх картинки = baseline - 0.85 * fontSize

# Декоративные линии (text-render.js)
STRIKE_OFFSET_FACTOR = 1 / 2.8   # выше базовой линии
UNDERLINE_OFFSET = 2             # ниже базовой линии; в оригинале не масштабируется
DECOR_THICKNESS_FACTOR = 0.1


def s(value: float) -> int:
    """Логический размер → пиксели рендера."""
    return round(value * SCALE)


def name_color(user_id: int) -> tuple:
    return NAME_COLORS_DARK[abs(user_id) % len(NAME_COLORS_DARK)]


def avatar_gradient(user_id: int) -> tuple:
    return AVATAR_GRADIENTS[abs(user_id) % len(AVATAR_GRADIENTS)]
