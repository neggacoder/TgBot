"""Настройки чата в панели: чтение всем сотрудникам, правка — по уровню."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import chat_settings
import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")
permissions = importlib.import_module("webpanel.permissions")


def _patch_db(monkeypatch):
    """Общие подмены db для тестов эндпоинта. Не трогает auth.verify_csrf —
    это отдельный выбор каждой фикстуры, а не общий по умолчанию."""
    записано: list = []
    журнал: list = []
    сигналы: list = []

    async def get_values(chat_id, settings):
        return {s.key: s.default for s in settings}

    async def set_value(chat_id, setting, value):
        записано.append((chat_id, setting.key, value))

    async def add_log(event_type, **kwargs):
        журнал.append((event_type, kwargs))

    async def list_current_chats():
        return [{"chat_id": -100, "members": 5, "last_seen": None}]

    async def list_command_registry():
        return [{"command_key": s.command_key, "default_level": 2}
                for s in chat_settings.SETTINGS]

    async def list_command_levels():
        return {}

    async def get_admin_level(user_id):
        return {555: 1, 777: 2}.get(user_id, 0)

    async def set_data(key, value, updated_by=None):
        сигналы.append((key, value))

    # Названия уровней панель берёт из карты ролей (roles.load), а та ходит
    # за таблицей админов и за переименованиями в settings.
    async def list_admins():
        return [{"user_id": 555, "level": 1}, {"user_id": 777, "level": 2}]

    async def fetch_settings():
        return {}

    monkeypatch.setattr(db, "list_admins", list_admins, raising=False)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings, raising=False)
    monkeypatch.setattr(db, "set_data", set_data, raising=False)
    monkeypatch.setattr(db, "get_chat_setting_values", get_values, raising=False)
    monkeypatch.setattr(db, "set_chat_setting_value", set_value, raising=False)
    monkeypatch.setattr(db, "add_log", add_log, raising=False)
    monkeypatch.setattr(db, "list_current_chats", list_current_chats, raising=False)
    monkeypatch.setattr(db, "list_command_registry", list_command_registry, raising=False)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels, raising=False)
    monkeypatch.setattr(db, "get_admin_level", get_admin_level, raising=False)
    monkeypatch.setattr(permissions.roles, "owner_ids", lambda: {1})
    permissions.forget_cache()
    # Карта ролей кэшируется на 30 секунд в модульной переменной: без сброса
    # она перетекала бы из теста в тест, и проверка переименованного уровня
    # проходила или падала бы в зависимости от порядка запуска.
    permissions.roles.invalidate()
    return записано, журнал, сигналы


@pytest.fixture
def client(monkeypatch):
    записано, журнал, сигналы = _patch_db(monkeypatch)
    # Подмена CSRF — сознательный выбор именно этой фикстуры: большинству
    # тестов ниже нужны только права и валидация, а не сам механизм CSRF.
    # Кто проверяет CSRF — берёт client_real_csrf, где эта строка отсутствует.
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)

    c = TestClient(panel.app)
    c.записано = записано
    c.журнал = журнал
    c.сигналы = сигналы
    yield c
    panel.app.dependency_overrides.clear()


@pytest.fixture
def client_real_csrf(monkeypatch):
    """Как client, но с НАСТОЯЩЕЙ проверкой CSRF: если убрать
    auth.verify_csrf(request) из обработчика, этот клиент обязан заметить —
    иначе удаление единственной защиты записи от подделки с чужого сайта
    осталось бы незамеченным (панель смотрит в интернет через Funnel)."""
    записано, журнал, сигналы = _patch_db(monkeypatch)
    c = TestClient(panel.app)
    c.записано = записано
    c.журнал = журнал
    c.сигналы = сигналы
    yield c
    panel.app.dependency_overrides.clear()


def _as(role, tg_user_id):
    user = PanelUser(id=9, username=role, role=role, tg_user_id=tg_user_id)
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: user
    return user


def test_список_отдаёт_группы_и_значения(client):
    _as("admin", 777)
    r = client.get("/api/chat-settings?chat_id=-100")
    assert r.status_code == 200
    data = r.json()
    groups = {g["group"] for g in data["groups"]}
    assert "Банк" in groups and "Рынок" in groups
    all_keys = {s["key"] for g in data["groups"] for s in g["settings"]}
    assert all_keys == set(chat_settings.BY_KEY)


def test_модератор_видит_поля_но_не_может_править(client):
    _as("admin", 555)
    data = client.get("/api/chat-settings?chat_id=-100").json()
    поля = [s for g in data["groups"] for s in g["settings"]]
    assert поля, "поля обязаны показываться, а не прятаться"
    assert all(not s["can_edit"] for s in поля)

    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert not client.записано


def test_админ_правит(client):
    _as("admin", 777)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 200
    assert client.записано == [(-100, "bank.rate_1d", 9.0)]


def test_правка_попадает_в_журнал(client):
    user = _as("admin", 777)
    client.post("/api/chat-settings",
                json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert client.журнал and client.журнал[0][0] == "chat_setting_set"
    # Тип события мало что стоит без автора: если actor_id потеряется,
    # запись останется, а разбирательство — нет.
    kwargs = client.журнал[0][1]
    assert kwargs["actor_id"] == user.tg_user_id
    assert "bank.rate_1d" in kwargs["details"]


def test_владелец_без_привязки_к_telegram_не_теряет_след_в_журнале(client):
    """permissions.bot_level отдаёт владельцу максимум ДО проверки привязки
    к Telegram (иначе он может запереть себя снаружи) — значит actor_id тут
    всегда пуст. Именно у этого класса аккаунтов доступ есть всегда, поэтому
    автор обязан остаться определимым хоть где-то в записи.

    Имя аккаунта нарочно не совпадает с ролью (в отличие от `_as`): иначе
    тест прошёл бы и на строке-заглушке вместо настоящего user.username."""
    user = PanelUser(id=9, username="хозяйка-панели", role="owner", tg_user_id=None)
    panel.app.dependency_overrides[panel.auth.require_user] = lambda: user
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 200
    kwargs = client.журнал[0][1]
    assert kwargs["actor_id"] is None
    assert "хозяйка-панели" in kwargs["details"]


def test_запись_без_csrf_токена_отклоняется(client_real_csrf):
    """Фикстура НЕ подменяет verify_csrf — без этого удаление проверки в
    обработчике осталось бы незамеченным всеми остальными тестами файла."""
    _as("owner", 1)
    r = client_real_csrf.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert not client_real_csrf.записано


def test_неизвестный_ключ_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "нет.такого", "value": "1"})
    assert r.status_code == 400


def test_значение_вне_границ_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "market.max_goods", "value": "1000"})
    assert r.status_code == 400
    assert "1" in r.json()["detail"]
    assert not client.записано


def test_неизвестный_чат_отбивается(client):
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -999, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 400


def test_аккаунт_без_привязки_не_правит(client):
    _as("admin", None)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert "Telegram" in r.json()["detail"]


def test_глобальная_настройка_помечена(client):
    _as("owner", 1)
    data = client.get("/api/chat-settings?chat_id=-100").json()
    поле = next(s for g in data["groups"] for s in g["settings"]
                if s["key"] == "duel.outcome")
    assert поле["global"] is True


def test_переименованный_уровень_называется_как_в_чате(client, monkeypatch):
    """Владелец переименовал «Администратор» — панель обязана звать уровень
    так же, как чат, и в подписи поля, и в отказе.

    Доступ этим не чинится, чинится объяснимость: услышав про уровень,
    которого у себя не найдёшь, человек не поймёт, какого права ему не
    хватает и у кого его просить."""
    import json

    async def fetch_settings():
        return {"level_names": json.dumps({"2": "🐺 Смотрящий"}, ensure_ascii=False)}

    monkeypatch.setattr(db, "fetch_settings", fetch_settings, raising=False)
    permissions.roles.invalidate()

    _as("admin", 555)  # уровень 1 — до правки не дотягивает
    data = client.get("/api/chat-settings?chat_id=-100").json()
    поле = next(s for g in data["groups"] for s in g["settings"]
                if s["key"] == "bank.rate_1d")
    assert поле["level_name"] == "🐺 Смотрящий"

    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "bank.rate_1d", "value": "9"})
    assert r.status_code == 403
    assert "🐺 Смотрящий" in r.json()["detail"]


# --- доезжает ли правка до живого бота ---------------------------------------
# Панель и бот — разные процессы. Запись в базу сама по себе ничего не меняет
# в чате: бот держит настройки в памяти. Две половины одного пути — панель
# обязана поднять флаг перечитки, бот обязан читать значение уже после неё.


def test_запись_поднимает_флаг_перечитки(client):
    """Без флага сайт пишет в базу, отвечает «Сохранено», а чат живёт
    по-старому до перезапуска бота — или до случайной правки чего-то ещё
    через панель, которая флаг всё-таки поднимет."""
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "duel.outcome", "value": "ban_day"})
    assert r.status_code == 200
    ключи = [key for key, _value in client.сигналы]
    assert db.PANEL_RELOAD_KEY in ключи, "бот не узнает о правке настройки чата"


def test_неудачная_запись_флаг_не_поднимает(client):
    """Флаг — обещание «в базе что-то поменялось». Поднимать его на отбитой
    валидации значит гонять бота по кругу без причины."""
    _as("owner", 1)
    r = client.post("/api/chat-settings",
                    json={"chat_id": -100, "key": "duel.outcome", "value": "чепуха"})
    assert r.status_code == 400
    assert not client.сигналы


@pytest.mark.parametrize("исход", ["0", "ban_day"])
def test_исход_дуэли_берётся_свежим_из_настроек(monkeypatch, исход):
    """Вторая половина пути. Раньше исход читался из глобальной DUEL_OUTCOME,
    а её заполняет только load_caches() на старте — перечитка settings по
    флагу из панели её не трогала, и дуэли до перезапуска бота наказывали
    по-старому (по умолчанию — киком).

    Здесь словарь настроек правится ровно так, как это делает
    panel_action_reload_loop, и проверяется, что применилось новое значение,
    а не стартовое."""
    import asyncio
    import os
    os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")
    os.environ.setdefault("OWNER_IDS", "1")
    import bot as bot_module

    monkeypatch.setitem(bot_module.settings, "duel_outcome", исход)

    вызовы: list = []

    class FakeBot:
        async def ban_chat_member(self, **kwargs):
            вызовы.append(("ban", kwargs.get("until_date")))

        async def unban_chat_member(self, **kwargs):
            вызовы.append(("unban", None))

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bot_module, "bot", FakeBot())
    monkeypatch.setattr(bot_module.db, "add_log", noop)
    monkeypatch.setattr(bot_module.db, "add_ban", noop)

    текст = asyncio.run(bot_module._apply_duel_outcome(-100, 555))

    # Кик — это пара ban+unban; именно её делало старое стартовое значение.
    assert [c for c, _ in вызовы] != ["ban", "unban"], "применился стартовый исход, а не свежий"
    if исход == "0":
        assert not вызовы, "наказание отключено, а бот всё равно полез в Telegram"
        assert "отключено" in текст
    else:
        assert [c for c, _ in вызовы] == ["ban"]
        assert вызовы[0][1] is not None, "бан на сутки обязан быть срочным"


# --- разметка ---------------------------------------------------------------

def test_вкладка_есть_в_меню_и_в_разметке():
    """Кнопка без секции (и наоборот) даёт мёртвый пункт меню: нажимается и
    ничего не открывает. Проверяем обе половины сразу."""
    import pathlib
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'data-view="chatsettings"' in html
    assert 'id="view-chatsettings"' in html
    js = (static / "app.js").read_text(encoding="utf-8")
    assert 'view === "chatsettings"' in js, "вкладку забыли подключить к навигации"
    assert "loadChatSettings" in js
    # saveChatSetting пишет результат через say("#chatsettings-msg", …) — эта
    # связка не закреплена ничем, кроме буквального совпадения строки. Пропади
    # div из разметки — say() упадёт на null.innerHTML внутри catch, и вместе
    # с сообщением перестанет работать перерисовка формы при неудачном
    # сохранении: человек увидит галочку там, где в базе ничего не легло.
    assert 'id="chatsettings-msg"' in html
    assert '#chatsettings-msg' in js
