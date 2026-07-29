"""Справка бота не должна расходиться с тем, что код на самом деле делает.

Неверная справка хуже отсутствующей: человек по ней принимает решения. Здесь
проверяются те утверждения, которые уже успели разойтись с кодом или легко
разойдутся при следующей правке.
"""

from __future__ import annotations

import ast
import io
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name: str) -> str:
    return io.open(os.path.join(_ROOT, name), encoding="utf-8").read()


def _help_text() -> str:
    return _source("help_texts.py")


def test_роль_покинувшего_чат_освобождается_а_не_удаляется():
    """Код зовёт release_role_by_holder — роль переходит в «свободна» и
    остаётся в списке. Справка одно время утверждала обратное, и админы ждали,
    что список сам почистится."""
    bot = _source("bot.py")
    db = _source("db.py")

    # в db роль именно освобождается: UPDATE, а не DELETE
    body = db[db.index("async def release_role_by_holder"):]
    body = body[:body.index("\n\nasync def")]
    assert "UPDATE chat_roles" in body
    assert "DELETE" not in body.upper()

    # обработчик выхода из чата зовёт освобождение
    assert "release_role_by_holder" in bot

    # и справка не обещает удаления
    text = _help_text()
    for line in text.splitlines():
        if "покинувш" in line or "покидает чат" in line:
            assert "удаляется" not in line, f"справка обещает удаление роли: {line.strip()}"


def test_срок_варна_по_умолчанию_совпадает_с_кодом():
    """«срок по умолч. 7д» в справке и WARN_DEFAULT_DURATION в коде — одно и
    то же число; разъехавшись, они дезинформируют модератора о том, когда варн
    сгорит."""
    bot = _source("bot.py")
    match = re.search(r"WARN_DEFAULT_DURATION\s*=\s*timedelta\(days=(\d+)\)", bot)
    assert match, "не нашёлся WARN_DEFAULT_DURATION"
    days = match.group(1)

    text = _help_text()
    mentions = [l for l in text.splitlines() if "срок по умолч" in l]
    assert mentions, "в справке пропало упоминание срока варна по умолчанию"
    for line in mentions:
        assert f"{days}д" in line, f"справка расходится с кодом ({days} дней): {line.strip()}"


def test_обманные_варны_не_упоминаются_в_справке():
    """«&варн» — розыгрыш. Дерево команд и справка открыты всем, и упоминание
    команды там раскрыло бы её первому же читателю."""
    assert "&варн" not in _help_text()

    bot = _source("bot.py")
    registry = bot[bot.index("COMMAND_REGISTRY: dict[str, dict] = {"):bot.index("COMMAND_IDS: dict[str, int]")]
    assert "&варн" not in registry and "fake_warn" not in registry


def test_команды_из_справки_существуют_в_реестре():
    """Пробегаем по фразам реестра команд: если команду переименовали в коде,
    а в справке забыли, тест это покажет."""
    bot = _source("bot.py")
    registry = bot[bot.index("COMMAND_REGISTRY: dict[str, dict] = {"):bot.index("COMMAND_IDS: dict[str, int]")]
    phrases = re.findall(r'"phrase":\s*"([^"]+)"', registry)
    assert len(phrases) > 100, "реестр команд разобрался неверно"

    # ключевые команды модерации обязаны быть описаны в справке
    text = _help_text()
    for command in ["варн", "мут", "кик", "созыв"]:
        assert command in text, f"команда «{command}» не описана в справке"


def _registry_command_words() -> list[tuple[str, str]]:
    """(ключ команды, её первое слово) для всех записей реестра.

    Первое слово фразы — это и есть имя команды: «биржа вкл / биржа выкл — …»
    даёт «биржа». Служебные префиксы !, +, -, . отбрасываем, потому что в
    справке они пишутся не всегда единообразно.
    """
    bot = _source("bot.py")
    registry = bot[
        bot.index("COMMAND_REGISTRY: dict[str, dict] = {"):
        bot.index("COMMAND_IDS: dict[str, int]")
    ]
    pairs = re.findall(r'"([a-z0-9_]+)":\s*\{"phrase":\s*"([^"]+)"', registry)
    out = []
    for key, phrase in pairs:
        head = phrase.split("—")[0].split("/")[0].strip().split()
        if not head:
            continue
        word = head[0].lstrip("!+.-").lower()
        if len(word) >= 3:
            out.append((key, word))
    return out


def test_каждая_команда_реестра_описана_в_справке():
    """Справка должна покрывать ВСЕ команды, а не выборочно проверяемые четыре.

    Прежний тест сверял только «варн/мут/кик/созыв», поэтому целые новые
    разделы (биржа вкл/выкл, сетка, саботаж, компромат, досье, мегафон)
    доезжали до реестра прав, но не до справки — и человек про них просто
    не узнавал. Здесь проверяется каждая запись реестра.

    Список исключений намеренно пуст: если команду действительно незачем
    показывать людям, ей не место и в реестре команд.

    ⚠️ Предел проверки: сверяется ПЕРВОЕ слово. Подкоманду уже описанного
    раздела («биржа вкл» при описанной «бирже») тест не поймает — справка
    для него уже «содержит биржу». Двусловную сверку пробовали, она даёт
    ложные срабатывания: справка пишет «купить {ключ}», а реестр —
    «магазин купить», и таких расхождений в формулировках десяток.
    Добавляете подкоманду к существующему разделу — проверьте справку
    глазами, автоматика тут не поможет.
    """
    text = _help_text().lower()
    missing = sorted({
        f"{key} («{word}»)"
        for key, word in _registry_command_words()
        if word not in text
    })
    assert not missing, (
        "команды есть в реестре, но не описаны в справке:\n  "
        + "\n  ".join(missing)
    )


def test_награды_хелп_соответствует_порогам_по_умолчанию():
    """Хелп называет конкретные степени по ролям — если формула в bot.py
    поменяется, а хелп нет, админы будут объяснять новичкам неверные пороги."""
    bot = _source("bot.py")
    help_src = _help_text()

    body = bot[bot.index("def _default_reward_degree_level"):]
    body = body[:body.index("\n\ndef ")]
    assert "degree == 1" in body
    assert "degree <= 3" in body
    assert "degree == 4" in body
    assert "degree == 5" in body
    assert "return OWNER_LEVEL" in body

    assert "1 — доступно всем" in help_src
    assert "2-3 — Модератор" in help_src
    assert "4 — Администратор" in help_src
    assert "5 — Старший администратор" in help_src
    assert "6-8 — только Владелец" in help_src


def test_справка_называет_кулдаун_медвежатника():
    """Медвежатник перестал быть кражей без ограничения по времени, но в
    справке остался «крадёт один предмет» — по такому описанию человек
    покупает предмет, а потом обнаруживает, что применить его нельзя ещё
    десять часов. Число берём из кода, чтобы они не разъехались снова."""
    bot = _source("bot.py")
    match = re.search(r"STEAL_COOLDOWN\s*=\s*timedelta\(hours=(\d+)\)", bot)
    assert match, "не нашёлся STEAL_COOLDOWN"
    hours = match.group(1)

    строки = [l for l in _help_text().splitlines() if "Медвежатник" in l]
    assert строки, "медвежатник пропал из справки"
    кусок = _help_text()[_help_text().index("Медвежатник"):][:600]
    assert f"{hours} час" in кусок, (
        f"справка не называет кулдаун медвежатника ({hours} ч)")


def test_справка_описывает_количество_у_подарка():
    """Подарок научился отдавать пачкой, а справка обещала ровно одну штуку:
    человек жал команду десять раз там, где хватало одной."""
    help_src = _help_text()
    assert "магазин подарить {ключ предмета} [количество]" in help_src, (
        "в справке нет формы подарка с количеством")

    # И встроенная подсказка раздела «магазин» — она же первое, что человек
    # видит, набрав команду с ошибкой.
    bot = _source("bot.py")
    assert "магазин подарить {ключ} [количество]" in bot, (
        "подсказка «магазин» обещает подарок без количества")


# ---------------------------------------------------------------------------
# Числа справки против чисел кода
#
# Так и появилась жалоба «в хелпе написано до 7 грядок, мы разве не меняли до
# 40?»: потолок огорода вырос, новый раздел написали, а в соседнем, старом,
# осталось «максимум семь». Правка числа в коде и правка справки — два разных
# действия, и второе забывается молча.
# ---------------------------------------------------------------------------

def _константы():
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot, farming, livestock, robbery, black_market
    import shop_effects as SE
    return bot, farming, livestock, robbery, black_market, SE


def test_справка_знает_настоящий_потолок_грядок():
    bot, farming, *_ = _константы()
    текст = _help_text()

    assert str(farming.PLOTS_MAX) in текст, "потолок огорода в справке не назван"
    # Тот самый забытый кусок: старый потолок как ОБЩИЙ максимум.
    assert "максимум семь" not in текст, (
        "в справке остался старый потолок огорода — звёздность даёт семь, "
        "но весь огород растёт до сорока"
    )


def test_справка_знает_все_источники_грядок():
    bot, farming, livestock, robbery, black_market, SE = _константы()
    текст = _help_text()

    assert str(farming.PLOTS_FROM_STARS_MAX) in текст
    assert str(farming.PLOTS_BUY_MAX) in текст
    for item in SE.ACHIEVEMENT_ITEMS + SE.CRAFT_ITEMS:
        if item.perk == SE.PERK_FARM_PLOTS:
            assert item.name in текст, f"{item.name} даёт грядки, но в справке его нет"


def test_справка_знает_шанс_сигнализации():
    """Он менялся с «гарантированно» на 40%, и текст об этом узнал не сразу."""
    *_, black_market, SE = _константы()
    текст = _help_text()
    assert str(black_market.SIGNAL_BLOCK_CHANCE) in текст


def test_справка_знает_срок_откупа_и_окно_рейда():
    bot, farming, livestock, robbery, *_ = _константы()
    текст = _help_text()

    assert str(robbery.SURVEILLANCE_AUTO_PARDON.days) in текст
    assert str(int(bot.RAID_WINDOW.total_seconds() // 60)) in текст


def test_справка_знает_цены_всего_скота():
    """Цена, поменянная в каталоге и забытая в справке, — обещание, которое
    бот не выполнит."""
    bot, farming, livestock, *_ = _константы()
    текст = _help_text()

    потерянные = []
    for a in livestock.ANIMALS:
        с_пробелом = f"{a.price:,}".replace(",", " ")
        if с_пробелом not in текст and str(a.price) not in текст:
            потерянные.append(f"{a.name} ({a.price})")
    assert not потерянные, "цены не совпали со справкой: " + ", ".join(потерянные)
