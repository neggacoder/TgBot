"""Медвежатник: правила кражи одного предмета.

Здесь всё про ПОРЯДОК. Списать что-то не в тот момент — значит либо подарить
бесплатную разведку по чужим закромам, либо сжечь чужую защиту ни за что; и
то и другое выглядит работающим, пока не посчитаешь, что осталось на руках.

Четыре порядка, каждый из которых переписывание переставит молча:

1. сигнализация проверяется ПОСЛЕ «есть ли у жертвы эта вещь» — иначе опечатка
   в ключе сжигает чужую защиту;
2. медвежатник тратится ВСЕГДА, даже когда дело сорвали, — иначе им бесплатно
   щупают чужие закрома, пока не найдётся ценное;
3. сигнализация при ПРОМАХЕ остаётся у жертвы — она стоит 20 000 и не должна
   продаваться как один бросок кубика;
4. слепок ключа тратится ТОЛЬКО на подтверждённой краже — на ветке «предмет
   успели потратить» он сгорел бы зря.

Бросок кубика принимается параметром: со встроенным random обе ветки
сигнализации проверялись бы монеткой.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib
import re
from datetime import datetime, timedelta

import pytest

import black_market
import steal_actions

ЧАТ, ВОР, ЖЕРТВА = -100, 7, 888
ДОБЫЧА = "diamond"


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class _World:
    """Заглушка db: инвентари, откат и витрина."""

    def __init__(self, у_вора=(steal_actions.KEY,), у_жертвы=(ДОБЫЧА,)):
        self.инвентари = {
            ВОР: {k: 1 for k in у_вора},
            ЖЕРТВА: {k: 1 for k in у_жертвы},
        }
        self.данные: dict[str, str] = {}
        self.порядок: list[str] = []
        self.пропало: set[str] = set()      # «успели потратить, пока вскрывали»

    async def list_inventory(self, chat_id, user_id):
        return [{"item_key": k, "quantity": q}
                for k, q in self.инвентари.get(user_id, {}).items() if q > 0]

    async def remove_inventory_item(self, chat_id, user_id, key, qty=1):
        self.порядок.append(f"снять {key} у {'вора' if user_id == ВОР else 'жертвы'}")
        if key in self.пропало:
            return False
        было = self.инвентари.get(user_id, {}).get(key, 0)
        if было < qty:
            return False
        self.инвентари[user_id][key] = было - qty
        return True

    async def add_inventory_item(self, chat_id, user_id, key, qty=1):
        self.порядок.append(f"выдать {key} вору")
        self.инвентари.setdefault(user_id, {})[key] = \
            self.инвентари.get(user_id, {}).get(key, 0) + qty

    async def get_shop_item(self, chat_id, key):
        return {"name": f"Предмет {key}"}

    async def get_data(self, key):
        значение = self.данные.get(key)
        return {"data_key": key, "data_value": значение} if значение is not None else None

    async def set_data(self, key, value, updated_by=None):
        self.порядок.append("отметить откат")
        self.данные[key] = value

    async def delete_data(self, key):
        self.данные.pop(key, None)


@pytest.fixture
def мир(monkeypatch):
    w = _World()
    monkeypatch.setattr(steal_actions, "db", w)

    async def без_события(chat_id):
        return None
    monkeypatch.setattr(steal_actions.farm_actions, "active_event", без_события)
    return w


СРАБОТАЛА = lambda: 1                                  # noqa: E731
ПРОМАХ = lambda: black_market.SIGNAL_BLOCK_CHANCE + 1   # noqa: E731


# --- отказы до списаний ------------------------------------------------------

@_sync
async def test_без_инструмента_ничего_не_происходит(мир):
    мир.инвентари[ВОР] = {}
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=СРАБОТАЛА)
    assert not итог.ok and "нет" in итог.error
    assert мир.порядок == []


@_sync
async def test_опечатка_в_ключе_ничего_не_сжигает(мир):
    """Сигнализация проверяется ПОСЛЕ «есть ли вещь». Иначе промах мимо
    несуществующего предмета стоил бы жертве её защиты."""
    мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, "нетакого", roll=СРАБОТАЛА)
    assert not итог.ok
    assert мир.порядок == [], "что-то списали на несуществующем предмете"
    assert мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] == 1
    assert мир.инвентари[ВОР][steal_actions.KEY] == 1


@_sync
async def test_у_себя_красть_нечего(мир):
    итог = await steal_actions.steal(ЧАТ, ВОР, ВОР, ДОБЫЧА, roll=ПРОМАХ)
    assert not итог.ok
    assert мир.порядок == []


@_sync
async def test_награды_не_крадутся(мир, monkeypatch):
    monkeypatch.setattr(steal_actions.shop_effects, "is_reward", lambda k: k == "medal")
    мир.инвентари[ЖЕРТВА]["medal"] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, "medal", roll=ПРОМАХ)
    assert not итог.ok and "заслуга" in итог.error
    assert мир.порядок == []


@_sync
async def test_комендантский_час_запирает_дело(мир, monkeypatch):
    async def комендантский(chat_id):
        return {"key": "curfew", "flags": [steal_actions.chat_events.F_NO_ROBBERY]}
    monkeypatch.setattr(steal_actions.farm_actions, "active_event", комендантский)
    monkeypatch.setattr(steal_actions.chat_events, "flag", lambda ev, name: bool(ev))
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert not итог.ok and "патрули" in итог.error
    assert мир.порядок == []


@_sync
async def test_откат_не_даёт_пойти_второй_раз(мир):
    await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    мир.инвентари[ВОР][steal_actions.KEY] = 1      # купил ещё один
    мир.инвентари[ЖЕРТВА][ДОБЫЧА] = 1
    мир.порядок.clear()
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert not итог.ok and "не остыли" in итог.error
    assert мир.порядок == []


# --- сигнализация ------------------------------------------------------------

@_sync
async def test_сигнализация_сработала_обе_вещи_сгорают(мир):
    """Инструмент — потому что иначе им бесплатно щупали бы чужие закрома и
    защита выдавала бы сама себя. Защита — потому что она сработала."""
    мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=СРАБОТАЛА)
    assert итог.ok and итог.outcome == "blocked" and итог.signal_burned
    assert мир.инвентари[ВОР][steal_actions.KEY] == 0
    assert мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] == 0
    assert мир.инвентари[ЖЕРТВА][ДОБЫЧА] == 1, "вещь всё-таки унесли"
    assert "отметить откат" in мир.порядок, "откат не отмечен — можно сразу ещё раз"


@_sync
async def test_промах_сигнализации_оставляет_её_жертве(мир):
    """Она стоит 20 000 и глушит кражу с шансом. Списывать её за несделанную
    работу значило бы продавать один бросок кубика."""
    мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert итог.ok and итог.outcome == "stolen" and итог.signal_missed
    assert мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] == 1
    assert мир.инвентари[ВОР][ДОБЫЧА] == 1


@_sync
async def test_без_сигнализации_кража_проходит(мир):
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=СРАБОТАЛА)
    assert итог.ok and итог.outcome == "stolen"
    assert итог.signal_missed is False, "сказали про промах там, где защиты не было"
    assert мир.инвентари[ЖЕРТВА][ДОБЫЧА] == 0


# --- порядок списаний --------------------------------------------------------

@_sync
async def test_инструмент_тратится_раньше_добычи(мир):
    await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    сняли_инструмент = мир.порядок.index(f"снять {steal_actions.KEY} у вора")
    сняли_добычу = мир.порядок.index(f"снять {ДОБЫЧА} у жертвы")
    выдали = мир.порядок.index(f"выдать {ДОБЫЧА} вору")
    assert сняли_инструмент < сняли_добычу < выдали


@_sync
async def test_инструмент_сгорает_даже_если_вещь_успели_потратить(мир):
    """Иначе жать медвежатником по чужим закромам было бы бесплатно."""
    мир.пропало.add(ДОБЫЧА)
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert итог.ok and итог.outcome == "gone"
    assert мир.инвентари[ВОР][steal_actions.KEY] == 0
    assert f"выдать {ДОБЫЧА} вору" not in мир.порядок


# --- слепок ключа ------------------------------------------------------------

@_sync
async def test_слепок_сокращает_откат_после_удачной_кражи(мир):
    мир.инвентари[ВОР][black_market.SLEPOK_KEY] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert итог.ok and итог.slepok_used
    assert мир.инвентари[ВОР][black_market.SLEPOK_KEY] == 0

    осталось = await steal_actions.cooldown_left(ЧАТ, ВОР)
    полный = steal_actions.COOLDOWN
    # Отметка сдвинута задним числом на четверть отката — ждать меньше.
    assert осталось < полный * (1 - black_market.STEAL_COOLDOWN_CUT + 0.01)
    assert осталось > нижняя_граница(полный)


def нижняя_граница(полный: timedelta) -> timedelta:
    """Нижняя граница ожидания со слепком: чуть меньше трёх четвертей."""
    return полный * (1 - black_market.STEAL_COOLDOWN_CUT) - timedelta(seconds=5)


@_sync
async def test_слепок_переживает_сорванное_дело(мир):
    """Кражи не было — сокращать нечего."""
    мир.инвентари[ВОР][black_market.SLEPOK_KEY] = 1
    мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] = 1
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=СРАБОТАЛА)
    assert итог.outcome == "blocked" and not итог.slepok_used
    assert мир.инвентари[ВОР][black_market.SLEPOK_KEY] == 1


@_sync
async def test_слепок_переживает_исчезнувшую_добычу(мир):
    """Ветка «предмет успели потратить»: кражи не случилось, слепок цел."""
    мир.инвентари[ВОР][black_market.SLEPOK_KEY] = 1
    мир.пропало.add(ДОБЫЧА)
    итог = await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    assert итог.outcome == "gone" and not итог.slepok_used
    assert мир.инвентари[ВОР][black_market.SLEPOK_KEY] == 1


# --- что видно до дела -------------------------------------------------------

@_sync
async def test_состояние_не_выдаёт_чужой_инвентарь(мир):
    """Общее состояние экрана — про себя: инструмент, откат, комендантский
    час. Чужие карманы приходят отдельным запросом и только по выбранной
    цели: в состоянии, которое грузится при открытии магазина, им делать
    нечего."""
    s = await steal_actions.state(ЧАТ, ВОР)
    плоско = repr(s)
    assert ДОБЫЧА not in плоско, "в состоянии видно, что лежит у других"
    assert str(ЖЕРТВА) not in плоско
    assert s["has_tool"] is True and s["curfew"] is False


# --- карманы цели ------------------------------------------------------------

@_sync
async def test_карманы_видны_с_названием_и_ключом(мир):
    добыча = await steal_actions.loot(ЧАТ, ВОР, ЖЕРТВА)
    assert [и["key"] for и in добыча] == [ДОБЫЧА]
    assert добыча[0]["name"], "название не пришло — по одному ключу не выбрать"
    assert добыча[0]["quantity"] == 1


@_sync
async def test_карманы_открыты_только_владельцу_инструмента(мир):
    """Иначе список стал бы бесплатным просмотром чужих карманов для всего
    чата — а это уже слежка, и покупать для неё ничего не нужно."""
    мир.инвентари[ВОР] = {}
    assert await steal_actions.loot(ЧАТ, ВОР, ЖЕРТВА) == []


@_sync
async def test_сигнализация_в_карманах_не_показывается(мир):
    """Защита не должна выдавать сама себя. Увидев её в списке, вор просто не
    пошёл бы к тем, у кого она есть, и предмет за 20 000 перестал бы что-либо
    значить: его ценность ровно в том, что о нём узнают постфактум."""
    мир.инвентари[ЖЕРТВА][black_market.SIGNAL_KEY] = 1
    ключи = [и["key"] for и in await steal_actions.loot(ЧАТ, ВОР, ЖЕРТВА)]
    assert black_market.SIGNAL_KEY not in ключи
    assert ДОБЫЧА in ключи, "заодно спрятали и то, что красть можно"


@_sync
async def test_награды_в_карманах_не_показываются(мир, monkeypatch):
    """Их всё равно не украсть — звать на заведомо пустой заход незачем."""
    monkeypatch.setattr(steal_actions.shop_effects, "is_reward", lambda k: k == "medal")
    мир.инвентари[ЖЕРТВА]["medal"] = 1
    ключи = [и["key"] for и in await steal_actions.loot(ЧАТ, ВОР, ЖЕРТВА)]
    assert "medal" not in ключи and ДОБЫЧА in ключи


@_sync
async def test_пустые_остатки_в_карманы_не_попадают(мир):
    мир.инвентари[ЖЕРТВА]["ghost"] = 0
    ключи = [и["key"] for и in await steal_actions.loot(ЧАТ, ВОР, ЖЕРТВА)]
    assert "ghost" not in ключи


@_sync
async def test_состояние_показывает_сколько_ждать(мир):
    await steal_actions.steal(ЧАТ, ВОР, ЖЕРТВА, ДОБЫЧА, roll=ПРОМАХ)
    s = await steal_actions.state(ЧАТ, ВОР)
    assert s["wait_seconds"] > 0
    assert s["has_tool"] is False, "инструмент потрачен, а экран говорит обратное"


# --- одни правила на чат и сайт ---------------------------------------------

КОРЕНЬ = pathlib.Path(__file__).resolve().parent.parent


def test_бот_и_панель_идут_через_общие_правила():
    """Порядок списаний тут такой, что вторая реализация разойдётся молча:
    выглядеть будет так же, а на руках останется другое."""
    бот = (КОРЕНЬ / "bot.py").read_text(encoding="utf-8")
    панель = (КОРЕНЬ / "webpanel" / "member_steal_api.py").read_text(encoding="utf-8")
    for имя, текст in (("бот", бот), ("панель", панель)):
        assert "steal_actions.steal(" in текст, f"{имя} крадёт по-своему"
    # Ни один из входов не должен трогать инвентарь мимо правил.
    for запрет in ("db.remove_inventory_item", "db.add_inventory_item"):
        assert запрет not in панель, f"панель лезет в инвентарь мимо правил: {запрет}"
    assert "SIGNAL_BLOCK_CHANCE" not in бот.split("async def cmd_steal_item")[1][:3000] \
        or "random" not in бот.split("async def cmd_steal_item")[1][:3000], (
        "бросок кубика снова живёт в обработчике команды")


def test_кража_с_сайта_такая_же_громкая():
    """В чате кража громкая: сообщение видят все, жертве приходит личка.
    Промолчи сайт — и он стал бы тихим способом красть, то есть другой игрой,
    а не тем же действием через другое окно."""
    панель = (КОРЕНЬ / "webpanel" / "member_steal_api.py").read_text(encoding="utf-8")
    кусок = панель[панель.index("async def _рассказать"):конец_помощника(панель)]
    assert кусок.count("send_message") == 2, "сайт объявляет кражу не всем и не жертве"
    вызов = панель[панель.index("async def api_member_steal_do"):]
    assert "_рассказать(" in вызов, "кража с сайта проходит молча"


def конец_помощника(текст: str) -> int:
    return текст.index("@router.post")


def test_эндпоинт_не_принимает_чат_снаружи():
    """Чат один, и знать его должен сервер. Смотрим только на ОБРАБОТЧИКИ и
    тело запроса: внутренние помощники чат принимают законно — им его уже
    выдал сервер, и запрет на параметр там означал бы протаскивать его через
    глобальную переменную."""
    панель = (КОРЕНЬ / "webpanel" / "member_steal_api.py").read_text(encoding="utf-8")
    плохие = []
    for строка in панель.split("\n"):
        if re.match(r"\s+chat_id: int", строка):          # поле в теле запроса
            плохие.append(строка.strip())
        if re.match(r"async def api_\w+\(.*chat_id", строка):   # параметр обработчика
            плохие.append(строка.strip())
    assert not плохие, f"чат приходит снаружи: {плохие}"
    assert "chats.work_chat_id()" in панель
