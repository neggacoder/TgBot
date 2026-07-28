"""Кабинет участника: питомцы через сайт, без единого слова в чат."""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import db
import game_actions
import pets as pets_catalog
from webpanel import permissions
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")
member_game = importlib.import_module("webpanel.member_game_api")


def _права(monkeypatch, пороги: dict | None = None, мой_уровень: int = 0) -> None:
    """Уровни команд для permissions.ensure — те же, что у бота.

    Без подмены проверка прав ушла бы в неподнятый пул соединений: реестр
    команд и переопределённые уровни живут в БД. Умолчания здесь нулевые,
    как в реестре бота, — обычный участник проходит.
    """
    async def list_command_registry():
        return [{"command_key": k, "default_level": 0}
                for k in ("pet_list", "pet_buy", "pet_care")]

    async def list_command_levels():
        return dict(пороги or {})

    async def get_admin_level(user_id):
        return мой_уровень

    async def list_admins():
        return []

    async def fetch_settings():
        return {}

    monkeypatch.setattr(db, "list_command_registry", list_command_registry, raising=False)
    monkeypatch.setattr(db, "list_command_levels", list_command_levels, raising=False)
    monkeypatch.setattr(db, "get_admin_level", get_admin_level, raising=False)
    monkeypatch.setattr(db, "list_admins", list_admins, raising=False)
    monkeypatch.setattr(db, "fetch_settings", fetch_settings, raising=False)
    monkeypatch.setattr(permissions.roles, "owner_ids", lambda: set())
    # Оба кэша модульные и живут дольше теста: без сброса порог из соседнего
    # теста утёк бы сюда, и проверка проходила бы или падала по порядку
    # запуска.
    permissions.forget_cache()
    permissions.roles.invalidate()


@pytest.fixture
def client(monkeypatch):
    отправлено = []
    сделано = []

    async def feed_pet(chat_id, user_id, raw=None):
        сделано.append(("feed", chat_id, user_id, raw))
        return game_actions.ActionResult(
            True, "🍽 Кот накормлен(а).",
            (game_actions.Announcement(game_actions.ANNOUNCE_PET_LEVEL,
                                       "⭐ Кот вырос до уровня 2!"),))

    async def my_pets_text(chat_id, user_id, own=True):
        # own=True добавлен сверх брифа: у настоящей game_actions.my_pets_text
        # это обязательный (без значения по умолчанию) параметр, а роутер
        # обязан звать его так же, как bot.cmd_pets_mine — иначе первый же
        # настоящий вызов упал бы TypeError'ом мимо этой заглушки.
        return game_actions.ActionResult(True, "🐾 Ваши питомцы: Кот")

    async def my_pets_list(chat_id, user_id):
        # Настоящую проверку этого поля делает test_список_отдаёт_питомцев_
        # отдельным_полем поверх подменённой db; здесь заглушка нужна, чтобы
        # список не ушёл в неподнятый пул соединений.
        return [{"key": "kot", "name": "Кот", "emoji": "🐈"}]

    class _Bot:
        async def send_message(self, chat_id, text, **kw):
            отправлено.append((chat_id, text))

    async def in_chat(user, chat_id):
        if chat_id != -100:
            from fastapi import HTTPException
            raise HTTPException(403, "Вы не состоите в этом чате")

    monkeypatch.setattr(member_game.game_actions, "feed_pet", feed_pet)
    monkeypatch.setattr(member_game.game_actions, "my_pets_text", my_pets_text)
    monkeypatch.setattr(member_game.game_actions, "my_pets_list", my_pets_list)
    monkeypatch.setattr(member_game, "get_bot", lambda: _Bot())
    monkeypatch.setattr(member_game, "require_member_in_chat", in_chat)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    monkeypatch.setattr(db, "add_log", lambda *a, **k: _none(), raising=False)
    _права(monkeypatch)

    c = TestClient(panel.app)
    c.отправлено = отправлено
    c.сделано = сделано
    yield c
    panel.app.dependency_overrides.clear()


async def _none():
    return None


def _as_member(tg_user_id=7):
    user = PanelUser(id=9, username="участник", role="member", tg_user_id=tg_user_id)
    panel.app.dependency_overrides[panel.auth.require_member] = lambda: user
    return user


def test_список_питомцев_отдаётся(client):
    _as_member()
    r = client.get("/api/member/game/pets?chat_id=-100")
    assert r.status_code == 200
    assert "Кот" in r.json()["text"]


def test_кормление_с_сайта_не_пишет_отчёт_в_чат(client):
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "накормлен" in r.json()["text"]
    тексты = [t for _chat, t in client.отправлено]
    assert not any("накормлен" in t for t in тексты), "отчёт ушёл в чат — это спам"


def test_награда_всё_равно_объявляется(client):
    _as_member()
    client.post("/api/member/game/pets/feed", json={"chat_id": -100, "key": "kot"})
    тексты = [t for _chat, t in client.отправлено]
    assert any("уровня 2" in t for t in тексты), "ачивки и уровни объявлять надо"


def test_упавшее_объявление_не_отменяет_действие(client, monkeypatch):
    """Проверено вживую: бота выгнали из чата — питомец уже накормлен и
    уровень записан, а человек получал 500, и запись в журнале не появлялась
    вовсе. Действие исчезало из аудита из-за чужой неудачи."""
    записи = []

    class _ВыгнанныйБот:
        async def send_message(self, chat_id, text, **kw):
            raise RuntimeError("бот выгнан из чата")

    async def add_log(event_type, **kwargs):
        записи.append(event_type)

    monkeypatch.setattr(member_game, "get_bot", lambda: _ВыгнанныйБот())
    monkeypatch.setattr(db, "add_log", add_log, raising=False)
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200, r.text
    assert "накормлен" in r.json()["text"], "отчёт о сделанном обязан вернуться"
    assert записи == ["member_game"], "действие пропало из журнала"


def test_запись_в_журнал_идёт_до_объявлений():
    """Порядок стережём отдельно: ловушку вокруг отправки однажды снимут
    (её и не было до ревью), а запись об уже случившемся действии не должна
    зависеть от чужой неудачи ни при какой ловушке."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(member_game.api_member_pet_action))
    строки = {"add_log": None, "_announce": None}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_log":
            строки["add_log"] = node.lineno
        if isinstance(node.func, ast.Name) and node.func.id == "_announce":
            строки["_announce"] = node.lineno
    assert all(строки.values()), f"вызовы не нашлись: {строки}"
    assert строки["add_log"] < строки["_announce"], (
        "запись в журнал стоит после отправки в чат — падение отправки унесёт "
        "её с собой")


def test_чужой_чат_отбивается(client):
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -999, "key": "kot"})
    assert r.status_code == 403
    assert not client.сделано


def test_поднятый_порог_закрывает_действие_и_на_сайте(client, monkeypatch):
    """В чате каждый обработчик питомцев начинается с _check_misc_access, то
    есть админ может закрыть команду словом «право». В кабинете такой
    проверки не было ни одной: «право pet_care 2» закрывало кормление в чате
    и оставляло открытым на сайте — две разные правды об одном праве."""
    _права(monkeypatch, пороги={"pet_care": 2}, мой_уровень=0)
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 403, r.text
    assert not client.сделано, "действие всё-таки выполнилось"


def test_поднятый_порог_закрывает_и_список(client, monkeypatch):
    """Список питомцев в чате закрывается ключом pet_list (cmd_pets_mine), и
    на сайте это тот же экран."""
    _права(monkeypatch, пороги={"pet_list": 3}, мой_уровень=0)
    _as_member()
    assert client.get("/api/member/game/pets?chat_id=-100").status_code == 403


def test_хватающий_уровень_пропускает(client, monkeypatch):
    """Обратная половина: сам по себе поднятый порог не должен закрывать
    доступ тому, у кого уровень есть, — иначе тест выше проходил бы и на
    наглухо сломанной проверке."""
    _права(monkeypatch, пороги={"pet_care": 2}, мой_уровень=2)
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200, r.text


def test_у_каждого_действия_есть_право():
    """Действие без ключа команды — дыра: в чате оно закрыто, на сайте
    открыто. Роутер индексирует таблицу прав напрямую, поэтому забытое
    действие тут же стало бы пятисоткой, — но узнать об этом лучше здесь."""
    без_права = set(member_game._ACTIONS) - set(member_game._ACTION_COMMANDS)
    assert not без_права, f"действия без ключа команды: {без_права}"
    лишние = set(member_game._ACTION_COMMANDS) - set(member_game._ACTIONS)
    assert not лишние, (f"права на несуществующие действия: {лишние} — "
                        f"мёртвая строка молчит о том, что действие убрали")


def test_неизвестное_действие(client):
    _as_member()
    r = client.post("/api/member/game/pets/станцевать",
                    json={"chat_id": -100})
    assert r.status_code == 400


def test_неудача_по_правилам_это_не_ошибка_http(client, monkeypatch):
    """«Не хватило корма» — законный исход игры, а не сбой."""
    async def feed_fail(chat_id, user_id, raw=None):
        return game_actions.ActionResult.fail("Нет корма.")
    monkeypatch.setattr(member_game.game_actions, "feed_pet", feed_fail)
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_покупка_и_продажа_кабинету_недоступны(client, action):
    """Бот покупает с on_bought=_check_collections, а кабинет так не может:
    функция в bot.py, и импортировать его панели нельзя. Купивший с сайта
    последнего питомца «Зоопарка» не получил бы ни титула, ни ачивки, ни
    Единорога. Пока пересчёт не переехал в общий модуль, наружу это не
    выставляем — но отвечаем объяснением, а не «такого действия нет»."""
    _as_member()
    r = client.post(f"/api/member/game/pets/{action}",
                    json={"chat_id": -100, "key": "kot", "confirm": True})
    assert r.status_code == 400, r.text
    assert "в чате" in r.json()["detail"], "отказ должен объяснять, куда идти"
    assert not client.сделано


def test_отключённое_действие_объясняет_причину_а_не_молчит():
    """Отказ обязан быть человеческим текстом, а не пустой строкой: его
    показывают на экране вместо ответа действия."""
    for action, текст in member_game._DISABLED.items():
        assert len(текст) > 30, f"{action}: отказ ничего не объясняет"


def test_переименование_без_имени_это_400_а_не_500(client):
    """rename_pet делает raw_name.strip() без проверки — без имени раньше
    была AttributeError, до панели доехавшая как 500."""
    _as_member()
    r = client.post("/api/member/game/pets/rename",
                    json={"chat_id": -100, "key": "kot"})
    assert r.status_code == 400


def test_переименование_без_ключа_это_400(client):
    _as_member()
    r = client.post("/api/member/game/pets/rename",
                    json={"chat_id": -100, "name": "Барсик"})
    assert r.status_code == 400


def test_приласкать_всех_с_неизвестным_verb_это_400(client):
    """care_all раньше молча подставлял «погладить» на любой непонятный
    verb — человек, просивший «обнять», не понимал, почему обнял не тот
    глагол, и не мог тут же повторить нужным: кулдаун уже общий на все три."""
    _as_member()
    r = client.post("/api/member/game/pets/care_all",
                    json={"chat_id": -100, "verb": "станцевать"})
    assert r.status_code == 400


class _ActionsWorld:
    """Плоская подмена db для сквозной проверки РОУТЕРА (не экономики — та
    проверяется в test_game_actions.py). Единственная цель: дать всем
    действиям таблицы дойти до их настоящей логики, не упав на
    неподнятом пуле соединений — иначе тест на «нет 500» первым делом ловил
    бы «БД не поднята», а не то, что действительно чинится этой задачей.

    Имена и формы возврата — как у настоящего db.py (тот же приём, что и
    _World в test_game_actions.py), одного питомца «kot» достаточно: тест
    проверяет отсутствие 500, а не то, что каждое действие обязано
    закончиться успехом.
    """

    def __init__(self):
        now = datetime.utcnow()
        self.pets = [{
            "pet_key": "kot", "pet_name": None, "hunger": 80, "mood": 80,
            "xp": 0, "xp_tick_at": now, "last_fed_at": None,
            "last_care_at": None, "last_tick_at": now, "last_walk_at": None,
            "evolved": False, "ability": None, "ability2": None,
            "ability_rerolls": 0,
        }]
        self.inventory = {pets_catalog.FOOD_ITEM_KEY: 99}
        self.coins = 100_000
        self.card: dict = {}

    async def ensure_pet_catalog(self, chat_id, defaults):
        return 0

    async def list_pet_catalog(self, chat_id):
        return [{"pet_key": p.key, "name": p.name, "emoji": p.emoji,
                 "price": p.price, "sound": p.sound, "ability": p.ability,
                 "is_active": True, "max_count": None}
                for p in pets_catalog.PETS]

    async def list_pets(self, chat_id, user_id):
        return [dict(p) for p in self.pets]

    async def get_pet(self, chat_id, user_id, key):
        return next((dict(p) for p in self.pets if p["pet_key"] == key), None)

    async def get_profile_card(self, chat_id, user_id):
        return dict(self.card)

    async def get_inventory_quantity(self, chat_id, user_id, item_key):
        return self.inventory.get(item_key, 0)

    async def seed_extra_shop_items(self, chat_id, items, is_active=True):
        return 0

    async def seed_default_shop_items(self, chat_id):
        return 0

    async def get_shop_item(self, chat_id, key):
        return None

    async def remove_inventory_item(self, chat_id, user_id, item_key, amount=1):
        have = self.inventory.get(item_key, 0)
        if have < amount:
            return False
        self.inventory[item_key] = have - amount
        return True

    async def add_inventory_item(self, chat_id, user_id, item_key, amount=1):
        self.inventory[item_key] = self.inventory.get(item_key, 0) + amount

    async def set_pet_stats(self, chat_id, user_id, key, hunger, mood, xp, ts,
                            fed_at=None, care_at=None, walk_at=None):
        for p in self.pets:
            if p["pet_key"] == key:
                p.update(hunger=hunger, mood=mood, xp=xp, last_tick_at=ts)
                if fed_at is not None:
                    p["last_fed_at"] = fed_at
                if care_at is not None:
                    p["last_care_at"] = care_at
                if walk_at is not None:
                    p["last_walk_at"] = walk_at
        return True

    async def rename_pet(self, chat_id, user_id, key, name):
        for p in self.pets:
            if p["pet_key"] == key:
                p["pet_name"] = name

    async def set_pinned_pet(self, chat_id, user_id, key):
        self.card["pinned_pet"] = key

    async def get_data(self, key):
        return None   # никто не заморожен

    async def get_wallet(self, chat_id, user_id):
        return {"coins": self.coins}

    async def try_spend_coins(self, chat_id, user_id, amount):
        if self.coins < amount:
            return False
        self.coins -= amount
        return True

    async def add_coins(self, chat_id, user_id, amount):
        self.coins += amount

    async def count_pet_owners(self, chat_id, key):
        return 0

    async def add_pet(self, chat_id, user_id, key, ts, rerolls=0):
        self.pets.append({
            "pet_key": key, "pet_name": None, "hunger": 100, "mood": 100,
            "xp": 0, "xp_tick_at": ts, "last_fed_at": None, "last_care_at": None,
            "last_tick_at": ts, "last_walk_at": None, "evolved": False,
            "ability": None, "ability2": None, "ability_rerolls": rerolls,
        })
        return True

    async def delete_pet(self, chat_id, user_id, key):
        before = len(self.pets)
        self.pets = [p for p in self.pets if p["pet_key"] != key]
        return len(self.pets) < before

    async def recall_pet_rerolls(self, chat_id, user_id, key):
        return 0

    async def remember_pet_rerolls(self, chat_id, user_id, key, count):
        return None

    async def add_log(self, *args, **kwargs):
        return None


@pytest.fixture
def мир_клиент(monkeypatch):
    """Клиент кабинета, у которого действия доходят до НАСТОЯЩЕЙ game_actions.

    Отдельно от fixture `client` (там game_actions подменён заглушками):
    часть проверок про то, что действие доходит до логики целиком, а часть —
    про то, что роутер правильно разложил запрос. Обвязка одна на всех, а не
    копия в каждом тесте: в копии однажды забыли бы подмену, и тест ушёл бы
    в неподнятый пул соединений вместо проверки.
    """
    world = _ActionsWorld()
    monkeypatch.setattr(game_actions, "db", world)

    class _Bot:
        async def send_message(self, chat_id, text, **kw):
            pass

    async def in_chat(user, chat_id):
        return None

    monkeypatch.setattr(member_game, "get_bot", lambda: _Bot())
    monkeypatch.setattr(member_game, "require_member_in_chat", in_chat)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    # Роутер сам зовёт db.add_log — это db.py настоящий (модуль, а не
    # world выше: game_actions.db подменён, а member_game_api.db — нет), и
    # без подмены упёрся бы в неподнятый пул соединений так же, как в
    # исходном fixture `client`.
    monkeypatch.setattr(db, "add_log", lambda *a, **k: _none(), raising=False)
    _права(monkeypatch)

    _as_member()
    # raise_server_exceptions=False — иначе TestClient пробрасывает
    # необработанное исключение как есть, и «500» никогда не станет
    # response.status_code, которое как раз и требуется проверить.
    yield TestClient(panel.app, raise_server_exceptions=False), world
    panel.app.dependency_overrides.clear()


def test_ни_одно_действие_не_отвечает_500(мир_клиент):
    """Ревью: тесты покрывали только feed и список, поэтому 500 у buy и
    rename спокойно доехал до ревью. Проходим по ВСЕМ действиям из самой
    таблицы роутера (member_game._ACTIONS) — не переписанному руками
    списку, который забыли бы пополнить, — и на полном, и на пустом теле.

    Настоящая game_actions-логика тут работает по-настоящему (см.
    _ActionsWorld) — иначе тест проверял бы только диспетчеризацию роутера
    и не поймал бы баг, который поймало ревью: тот сидел ВНУТРИ вызываемых
    действий (raw_key.casefold() и raw_name.strip() без проверки на None).
    """
    c, _world = мир_клиент
    full_body = {"chat_id": -100, "key": "kot", "name": "Барсик",
                "confirm": True, "verb": "hug"}
    empty_body = {"chat_id": -100}
    for action in member_game._ACTIONS:
        for body, label in ((full_body, "полное тело"), (empty_body, "пустое тело")):
            r = c.post(f"/api/member/game/pets/{action}", json=body)
            assert r.status_code != 500, (
                f"{action} ({label}) отдал 500: {r.text}")


def test_список_отдаёт_питомцев_отдельным_полем(мир_клиент):
    """Кнопке «покормить» нужен ключ того, кого кормят. Достать его из
    готового текста списка можно только разбором HTML в браузере — а тот
    молча ломается от любой правки формулировки. Поэтому ключи приходят
    отдельным полем, рядом с текстом, а не вместо него."""
    c, world = мир_клиент
    world.pets.append(dict(world.pets[0], pet_key="pes"))
    r = c.get("/api/member/game/pets?chat_id=-100")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"], "текст списка никуда не делся"
    assert [p["key"] for p in data["pets"]] == ["kot", "pes"]
    assert all(p["name"] and p["emoji"] for p in data["pets"])


def test_поштучное_действие_доносит_ключ_до_логики(client):
    """У кого питомцев больше одного, действие без ключа отбивается советом
    набрать команду в чате — на сайте так не сделать. Значит ключ обязан
    доехать от кнопки до game_actions, а не потеряться в роутере."""
    _as_member()
    r = client.post("/api/member/game/pets/feed",
                    json={"chat_id": -100, "key": "pes"})
    assert r.status_code == 200, r.text
    assert client.сделано[-1][3] == "pes", "ключ до game_actions не доехал"


def test_массовые_действия_кабинету_доступны(мир_клиент):
    """Второй питомец — норма, а не край: коллекция «Зоопарк» прямо поощряет
    завести всех. Без кнопок «всем» такому человеку пришлось бы жать по три
    кнопки на каждого."""
    c, _world = мир_клиент
    for action, body in (("feed_all", {}), ("walk_all", {}),
                         ("care_all", {"verb": "pet"})):
        r = c.post(f"/api/member/game/pets/{action}",
                   json={"chat_id": -100, **body})
        assert r.status_code == 200, f"{action}: {r.text}"


def test_эндпоинты_кабинета_шлют_только_объявления():
    """Сторож тишины. Обычным тестом не поймать: сообщение уходит в рабочем
    Telegram, а не в проверке. Читаем исходник — но по AST, считая настоящие
    вызовы .send_message(...), а не вхождения подстроки: подстрочный счётчик
    ловил бы и упоминание имени в комментарии или докстринге, а значит само
    слово нельзя было бы даже пояснить в тексте рядом, не сломав сторож (так
    уже случилось с докстрингом модуля при первой версии этого файла)."""
    import ast
    import inspect
    src = inspect.getsource(member_game)
    tree = ast.parse(src)
    вызовы = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_message"
    )
    assert вызовы == 1, ("send_message в кабинете должен вызываться ровно "
                         "один раз — в общем отправителе объявлений")
    assert "announcements" in src


def test_вкладка_питомцев_есть_в_кабинете():
    """Кнопка без экрана (и наоборот) — мёртвый пункт: нажимается и ничего
    не открывает. Проверяем обе половины и связку с загрузчиком."""
    import pathlib
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    html = (static / "webapp.html").read_text(encoding="utf-8")
    js = (static / "webapp.js").read_text(encoding="utf-8")
    assert 'data-mtab="gamepets"' in html
    assert 'id="mtab-gamepets"' in html
    assert "loadGamePets" in js
    assert "/api/member/game/pets" in js


def test_текст_питомцев_не_слипается_в_один_абзац():
    """Ревью нашло: весь экран выводился одной строкой.

    game_actions собирает ответ переводами строк, а вкладка вставляет его в
    innerHTML — в HTML перевод строки это обычный пробел. Список питомцев,
    разделитель, полоски сытости и опыта, подсказки — всё склеивалось в
    один абзац. Глазами это проверить нечем, поэтому стережём само правило:
    оно обязано быть и обязано относиться к контейнерам вкладки.
    """
    import pathlib
    import re
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    css = (static / "webapp.css").read_text(encoding="utf-8")
    # Комментарии убираем: иначе упоминание правила в пояснении рядом
    # засчиталось бы за само правило.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    селекторы = [sel.strip() for sel, тело in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                 if re.search(r"white-space\s*:\s*pre-(wrap|line)\b", тело)]
    for контейнер in ("#gamepets-list", "#gamepets-msg"):
        assert any(контейнер in sel for sel in селекторы), (
            f"у {контейнер} нет правила white-space: pre-wrap — перевод строки "
            f"в HTML это обычный пробел, и весь экран слипается в один абзац")


def test_вкладка_шлёт_ключ_питомца_и_умеет_всех():
    """Ревью нашло: кнопки уходили с одним chat_id, поле key не заполнялось
    никогда. У всякого, у кого питомцев больше одного, действие отбивалось
    советом набрать команду в чате — то есть сайт советовал уйти с сайта.

    Проверяем исходник вкладки: браузера в тестах нет, а разница между
    «кнопка работает» и «кнопка мертва» — ровно одно поле в теле запроса.
    """
    import pathlib
    import re
    static = pathlib.Path(__file__).resolve().parent.parent / "webpanel" / "static"
    js = (static / "webapp.js").read_text(encoding="utf-8")
    assert "data.pets" in js, "вкладка не читает список питомцев из ответа"
    assert "data-pet-key=" in js, "кнопке неоткуда взять ключ питомца"
    assert re.search(r"\.key\s*=\s*btn\.dataset\.petKey", js), \
        "поштучное действие уходит без ключа — оно мертво у всех, кто завёл второго"
    assert re.search(r"\.verb\s*=\s*btn\.dataset\.petVerb", js), \
        "у ласки «всем» слово обязательно, иначе сервер отвечает отказом"
    for действие in ("feed_all", "care_all", "walk_all"):
        assert действие in js, f"нет кнопки «{действие}» — «всем» с сайта не сделать"
