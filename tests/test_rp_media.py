"""Подбор картинок-реакций для РП-жестов (relationships_v2).

Проверяем чистую логику: определение папки пары по полу и выбор файла из
папки (с откатом на другие пары). Файловую систему подменяем через tmp_path —
настоящие картинки в репозиторий не кладём.
"""

from __future__ import annotations

import os

import pytest

# relationships_v2 поднимает Router на настоящем aiogram (F/Router/FSInputFile).
# Заглушка из conftest их не даёт, поэтому под системным Python тест
# пропускается — запускать интерпретатором из .venv (как и test_bot_routing).
aiogram = pytest.importorskip("aiogram", reason="нужен aiogram (см. .venv)")
if not hasattr(aiogram, "Dispatcher"):
    pytest.skip(
        "установлена заглушка aiogram, а не настоящий пакет — запустите из .venv",
        allow_module_level=True,
    )

import relationships_v2 as rel  # noqa: E402


def test_папка_пары_по_полу():
    assert rel._rp_pairing("м", "м") == "mm"
    assert rel._rp_pairing("ж", "ж") == "ff"
    assert rel._rp_pairing("м", "ж") == "mf"
    assert rel._rp_pairing("ж", "м") == "mf"
    # неизвестный пол или «другой» → нейтральная mf
    assert rel._rp_pairing(None, "м") == "mf"
    assert rel._rp_pairing("др", "ж") == "mf"
    assert rel._rp_pairing(None, None) == "mf"


def test_нет_картинок_вернёт_none(monkeypatch, tmp_path):
    # пустая папка — картинок нет, ожидаем None (тогда жест выводится текстом)
    monkeypatch.setattr(rel, "RP_MEDIA_ROOT", str(tmp_path))
    assert rel._pick_rp_media("hugs", "м", "ж") is None


def test_берёт_картинку_из_точной_папки(monkeypatch, tmp_path):
    monkeypatch.setattr(rel, "RP_MEDIA_ROOT", str(tmp_path))
    d = tmp_path / "hugs" / "mm"
    d.mkdir(parents=True)
    (d / "pic.jpg").write_bytes(b"fake")
    picked = rel._pick_rp_media("hugs", "м", "м")
    assert picked is not None and picked.endswith("pic.jpg")
    assert os.path.dirname(picked).endswith(os.path.join("hugs", "mm"))


def test_откат_на_другую_пару(monkeypatch, tmp_path):
    # для точной пары (mm) картинок нет, но есть в mf — должны взять оттуда
    monkeypatch.setattr(rel, "RP_MEDIA_ROOT", str(tmp_path))
    d = tmp_path / "kisses" / "mf"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(b"fake")
    picked = rel._pick_rp_media("kisses", "м", "м")
    assert picked is not None and picked.endswith("a.png")


def test_несуществующая_папка_вернёт_none(monkeypatch, tmp_path):
    monkeypatch.setattr(rel, "RP_MEDIA_ROOT", str(tmp_path))
    assert rel._pick_rp_media("несуществующее", "м", "ж") is None
    assert rel._pick_rp_media(None, "м", "ж") is None


def test_ответные_шаблоны_форматируются():
    # reply необязателен (минет/куни намеренно без ответной реакции — «сухая
    # надпись»); если он есть — должен корректно форматироваться {actor}/{target}.
    for key, info in rel.SIMPLE_RP_ACTIONS.items():
        reply = info.get("reply")
        if not reply:
            continue
        out = reply.format(actor="Аня", target="Боря")
        assert "Аня" in out and "Боря" in out


def test_жесты_минет_куни_счётчики_без_фото():
    g = rel.default_gestures()
    # оба жеста заведены как шуточные счётчики
    assert "minet" in g and "kuni" in g
    assert "минет" in g["minet"]["aliases"] and "куни" in g["kuni"]["aliases"]
    # алиасы маршрутизируются на нужные ключи (счётчики minet/kuni в карточке)
    assert rel.SIMPLE_RP_ALIAS_MAP.get("минет") == "minet"
    assert rel.SIMPLE_RP_ALIAS_MAP.get("куни") == "kuni"
    # фото нет: media_folder указывает на несуществующую папку → _pick_rp_media None
    for key in ("minet", "kuni"):
        assert g[key]["phrases"], f"у {key} нет фраз"
        for phrase in g[key]["phrases"]:
            out = phrase.format(actor="Аня", target="Боря")
            assert "Аня" in out and "Боря" in out
        assert not g[key].get("reply")  # намеренно без ответной реакции


# ---------------------------------------------------------------------------
# Карточка «отн я»: форматтеры
# ---------------------------------------------------------------------------

def test_формат_тысяч():
    assert rel._fmt_thousands(9734) == "9.734"
    assert rel._fmt_thousands(10000) == "10.000"
    assert rel._fmt_thousands(75) == "75"


def test_длительность_пары():
    from datetime import datetime, timedelta

    assert rel._pair_duration_text(datetime.utcnow() - timedelta(days=64)) == "2мес. 4д"
    assert rel._pair_duration_text(datetime.utcnow() - timedelta(days=5)) == "5д"
    assert rel._pair_duration_text(datetime.utcnow()) == "0д"


def test_load_gestures_из_бд(monkeypatch):
    import asyncio

    async def list_g(active_only=False):
        return [{
            "gesture_key": "wink", "name": "Подмигнуть",
            "reply_template": "{target} подмигивает в ответ.", "media_folder": "winks",
            "is_active": True, "sort_order": 0,
            "phrases": [{"id": 1, "phrase": "{actor} подмигивает {target}."}],
            "aliases": ["подмигнуть", "вжух"],
        }]

    monkeypatch.setattr(rel.db, "list_rel2_gestures", list_g)
    try:
        asyncio.run(rel.load_gestures())
        assert "wink" in rel.SIMPLE_RP_ACTIONS
        assert rel.SIMPLE_RP_ACTIONS["wink"]["media_folder"] == "winks"
        assert rel.SIMPLE_RP_ALIAS_MAP["вжух"] == "wink"
        # дефолтные жесты вытеснены загрузкой из БД
        assert "hug" not in rel.SIMPLE_RP_ACTIONS
    finally:
        # восстанавливаем дефолт, чтобы не влиять на другие тесты
        rel.SIMPLE_RP_ACTIONS.clear()
        rel.SIMPLE_RP_ACTIONS.update(rel._gesture_cache_from_default())
        rel.SIMPLE_RP_ALIAS_MAP.clear()
        rel.SIMPLE_RP_ALIAS_MAP.update(
            {a: k for k, v in rel._SIMPLE_RP_ACTIONS_DEFAULT.items() for a in v["aliases"]}
        )


def test_пустая_бд_оставляет_дефолт(monkeypatch):
    import asyncio

    async def empty(active_only=False):
        return []

    monkeypatch.setattr(rel.db, "list_rel2_gestures", empty)
    asyncio.run(rel.load_gestures())
    assert "hug" in rel.SIMPLE_RP_ACTIONS  # дефолт не тронут
