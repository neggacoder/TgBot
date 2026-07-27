"""Тексты помощи обязаны влезать в сообщение Telegram.

Лимит — 4096 символов. При превышении edit_text падает с «message is too
long», обработчик это глотал, и кнопка раздела выглядела мёртвой: нажимаешь —
ничего не происходит, ошибки никакой. Так и случилось с разделами про
питомцев и полезные предметы, которые росли фичу за фичей.

Этот тест — единственное, что мешает повторить: следующий раздел, доросший до
лимита, свалит его до того, как его увидят в чате.
"""

from __future__ import annotations

import os

import pytest

aiogram = pytest.importorskip("aiogram", reason="нужен настоящий aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip("установлена заглушка aiogram — запускайте из .venv", allow_module_level=True)

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
os.environ.setdefault("OWNER_IDS", "1")

import bot as bot_module  # noqa: E402

TELEGRAM_MESSAGE_LIMIT = 4096
# Небольшой запас: к тексту раздела ничего не приписывается, но правка на
# пару строк не должна сразу ронять раздел в чате.
SAFE_LIMIT = TELEGRAM_MESSAGE_LIMIT - 200


def _all_help_texts():
    for section_key, section in bot_module.HELP_SECTIONS.items():
        text = section.get("text")
        if text:
            yield f"{section_key}", text
        for sub_key, sub in (section.get("subsections") or {}).items():
            yield f"{section_key}:{sub_key}", sub.get("text") or ""


def test_ни_один_раздел_помощи_не_длиннее_лимита():
    длинные = [f"{name} — {len(text)}"
               for name, text in _all_help_texts() if len(text) > SAFE_LIMIT]
    assert not длинные, (
        "эти разделы не откроются в Telegram (лимит "
        f"{TELEGRAM_MESSAGE_LIMIT}, порог теста {SAFE_LIMIT}):\n"
        + "\n".join(длинные)
    )


def test_у_каждого_раздела_есть_текст_и_название():
    for name, text in _all_help_texts():
        assert text.strip(), f"пустой раздел помощи: {name}"


def test_ошибку_показа_помощи_больше_не_глотают():
    """Раньше любой TelegramBadRequest гасился `pass`, и раздел, переросший
    лимит, вёл себя как неработающая кнопка."""
    import inspect
    src = inspect.getsource(bot_module.help_subsection_callback)
    assert "not modified" in src, "повторный тык и настоящая ошибка не разделены"
    assert "show_alert=True" in src, "о настоящей ошибке человеку не сообщают"


# --- описание в профиле -----------------------------------------------------

def test_описание_показывается_в_карточке_профиля():
    """Профиль открывают в первую очередь, и описание человека логичнее видеть
    сразу, чем идти за ним отдельной командой «о себе»."""
    import inspect
    src = inspect.getsource(bot_module.build_profile_card)
    assert "about_text" in src, "описание не попадает в карточку профиля"


def test_описание_в_профиле_уважает_скрытую_анкету():
    """Кто спрятал анкету, тот спрятал и описание — иначе настройка приватности
    обходилась бы через карточку."""
    import inspect
    src = inspect.getsource(bot_module.build_profile_card)
    about_line = next(l for l in src.split("\n") if 'card.get("about_text")' in l)
    assert "anketa_shown" in about_line, about_line.strip()


def test_длинное_описание_в_профиле_подрезается():
    import inspect
    src = inspect.getsource(bot_module.build_profile_card)
    assert "PROFILE_ABOUT_MAX" in src
    assert bot_module.PROFILE_ABOUT_MAX > 0
