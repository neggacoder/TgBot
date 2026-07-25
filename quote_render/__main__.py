"""Демо-рендер: python -m quote_render [папка]

Рисует набор характерных случаев в PNG, чтобы вид можно было проверить
глазами, не поднимая бота. Полезно после любой правки рендера.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

from .layout import render_quote
from .model import QuoteMessage

# Фон под стикером — сам стикер прозрачный, но на прозрачном ничего не видно.
_PREVIEW_BG = (23, 23, 28)


def _cases() -> list:
    long_text = (
        "Съешь ещё этих мягких французских булок да выпей чаю. "
        "Проверяем, как переносится длинный текст и не разъезжается ли бабл."
    )
    return [
        ("simple", [QuoteMessage(user_id=1, name="Айгерим", text="Привет! Как дела?")]),
        ("long", [QuoteMessage(user_id=2, name="Дидар Амантай", text=long_text)]),
        ("emoji", [QuoteMessage(
            user_id=3, name="Мария",
            text="Ну ты даёшь 😂😂😂 я в шоке 🔥 давай завтра 👋🏽 ок?",
        )]),
        ("formatting", [QuoteMessage(
            user_id=4, name="Разработчик",
            text="жирный курсив код зачёркнутый ссылка спойлер",
            entities=[
                {"type": "bold", "offset": 0, "length": 6},
                {"type": "italic", "offset": 7, "length": 6},
                {"type": "code", "offset": 14, "length": 3},
                {"type": "strikethrough", "offset": 18, "length": 11},
                {"type": "url", "offset": 30, "length": 6},
                {"type": "spoiler", "offset": 37, "length": 7},
            ],
        )]),
        ("reply", [QuoteMessage(
            user_id=5, name="Асель", text="Согласна, так и сделаем",
            reply_name="Ержан", reply_text="Может встретимся в четверг вечером?",
            reply_chat_id=6,
        )]),
        ("group", [
            QuoteMessage(user_id=7, name="Тимур", text="Слушай"),
            QuoteMessage(user_id=7, name="Тимур", text="я тут подумал"),
            QuoteMessage(user_id=7, name="Тимур", text="а давай просто перенесём на понедельник?"),
        ]),
        ("dialog", [
            QuoteMessage(user_id=8, name="Камила", text="Ты уже видел отчёт?"),
            QuoteMessage(user_id=9, name="Нурлан", text="Видел, там всё плохо 😅"),
            QuoteMessage(user_id=9, name="Нурлан", text="переделываю"),
            QuoteMessage(user_id=8, name="Камила", text="Окей, жду"),
        ]),
        ("newlines", [QuoteMessage(
            user_id=10, name="Список",
            text="Планы:\n1. Проснуться\n2. Выпить кофе\n3. Написать бота",
        )]),
        ("one_word", [QuoteMessage(user_id=11, name="Кто-то", text="Да")]),
    ]


def check() -> int:
    """Диагностика ассетов: почему не рисуются эмодзи или подставился не тот
    шрифт. Печатает, что именно не работает, и куда смотреть."""
    import urllib.request

    from . import assets

    problems = 0
    print("Папки ассетов")
    for label, path in (("шрифты", assets.FONTS_DIR), ("эмодзи", assets.EMOJI_DIR)):
        exists = os.path.isdir(path)
        count = len(os.listdir(path)) if exists else 0
        print(f"  {label:8} {path}")
        print(f"           {'есть' if exists else 'НЕТ'}, файлов: {count}")

    print("\nПрава на запись")
    try:
        os.makedirs(assets.EMOJI_DIR, exist_ok=True)
        probe = os.path.join(assets.EMOJI_DIR, ".write-test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        print("  OK — папка доступна на запись")
    except Exception as exc:
        problems += 1
        print(f"  ОШИБКА: {type(exc).__name__}: {exc}")
        print("  Боту нечем сохранить скачанное. Проверьте владельца папки:")
        print(f"    sudo chown -R $USER {os.path.dirname(assets.EMOJI_DIR)}")

    print("\nДоступ в сеть")
    for label, url in (
        ("шрифт Noto", assets._FONT_SOURCES["NotoSans-Regular.ttf"]),
        ("картинка эмодзи", f"{assets._EMOJI_CDN}/1f600.png"),
    ):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": assets._USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                size = len(resp.read())
            print(f"  OK   {label}: {size} байт")
        except Exception as exc:
            problems += 1
            print(f"  СБОЙ {label}: {type(exc).__name__}: {exc}")
            print(f"       {url}")
            if "CERTIFICATE" in str(exc).upper() or "SSL" in type(exc).__name__.upper():
                print("       Похоже на просроченные сертификаты. Лечится так:")
                print("         sudo apt install --reinstall ca-certificates")

    print("\nЗагрузка эмодзи через сам модуль")
    for cluster in ("😀", "🔥", "👋🏽", "❤️"):
        img = assets.emoji_image(cluster, 48)
        names = assets._emoji_filenames(cluster)
        if img is None:
            problems += 1
            print(f"  СБОЙ {cluster} — не нашёлся; пробовались файлы {names}")
        else:
            print(f"  OK   {cluster} -> {names[0]} {img.size}")

    print("\nШрифт")
    font = assets.font(24)
    path = getattr(font, "path", None)
    if isinstance(path, str) and "NotoSans" in path:
        print(f"  OK   используется {os.path.basename(path)}")
    else:
        problems += 1
        print(f"  ВНИМАНИЕ: Noto Sans не подключился, взят запасной: {path}")
        print("  Текст будет выглядеть иначе, чем в quotly.")

    print("\n" + ("Всё в порядке." if not problems else f"Проблем найдено: {problems}"))
    return 1 if problems else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    out_dir = sys.argv[1] if len(sys.argv) > 1 else "demo_out"
    os.makedirs(out_dir, exist_ok=True)

    for name, messages in _cases():
        image = render_quote(messages)
        # уменьшаем, как это сделает бот при упаковке в стикер
        scale = 512 / max(image.size)
        preview = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )
        backdrop = Image.new("RGBA", preview.size, _PREVIEW_BG)
        backdrop.alpha_composite(preview)

        path = os.path.join(out_dir, f"{name}.png")
        backdrop.convert("RGB").save(path)
        print(f"{name:12} {image.size[0]:5}x{image.size[1]:<5} -> {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
