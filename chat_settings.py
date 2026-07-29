"""Настройки чата: что вообще настраивается, где лежит и в каких границах.

Здесь только ЧИСЛА И ПРАВИЛА, без БД и Telegram — как pets.py и farming.py
рядом. Чтение и запись — в db.py, форма — в панели.

Зачем реестр вместо страницы на каждую подсистему. Настройка живёт в трёх
местах сразу: обработчик в боте, эндпоинт панели, поле в форме. Опиши её
руками трижды — и однажды забудешь одно из трёх, а бот про это не скажет.
С реестром новая настройка — одна строка, и на сайте она появляется сама.

ТРИ ХРАНИЛИЩА, а не одно, и это не небрежность, а то, как сложилось:
  * STORAGE_COLUMN   — колонка початовой таблицы (bank_settings и другие);
  * STORAGE_DATA     — ключ в общем key-value (норма, боссы, автоотказ);
  * STORAGE_SETTINGS — колонка глобальной строки settings (исход дуэли).
Умей реестр только первое — треть настроек уехала бы в исключения, и подход
развалился бы там же, где его выбрали.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

STORAGE_COLUMN = "column"
STORAGE_DATA = "data"
STORAGE_SETTINGS = "settings"

KIND_NUMBER = "number"
KIND_BOOL = "bool"
KIND_CHOICE = "choice"


@dataclass(frozen=True)
class Setting:
    key: str            # устойчивый ключ для API: "bank.rate_1d"
    group: str          # заголовок блока в форме
    command_key: str    # команда бота — отсюда берётся требуемый уровень
    title: str
    kind: str
    storage: str
    # STORAGE_COLUMN — имя таблицы; STORAGE_DATA — шаблон ключа с {chat_id};
    # STORAGE_SETTINGS — имя колонки глобальной строки.
    target: str
    column: str = ""
    default: object = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    # Переключатель, у которого НАЛИЧИЕ ключа означает «выключено». Так
    # устроены боссы (boss_off:{chat_id}), и притворяться, что это обычный
    # флаг, нельзя: включение здесь — удаление ключа, а не запись нуля.
    inverted: bool = False
    # Настройка одна на всех, а не на чат. Панель обязана это подписать,
    # иначе правка в одном чате незаметно изменит все.
    is_global: bool = False

    @property
    def integer(self) -> bool:
        """Целое ли число. Дробные у нас только проценты и ставки."""
        return isinstance(self.default, int) and not isinstance(self.default, bool)


GROUPS: tuple[str, ...] = (
    "Банк", "Рынок", "Биржа", "Брак", "Ферма", "Заработок", "Активность",
    "Боссы", "Дуэли",
)

# Источники, КОТОРЫЕ СОЗДАЮТ МОНЕТЫ ИЗ ВОЗДУХА («краны»), — и только они.
# Ограбление с налётом сюда не входят: они перекладывают деньги между людьми,
# и множитель менял бы не объём денег в чате, а скорость их перемешивания.
#
# Ключ — то же слово, которым зовётся команда: второго словаря названий
# заводить нельзя, иначе «доход подработка 50» и «подработка» разъедутся.
#
# Фермы здесь НЕТ намеренно: у неё своя, более старая ручка
# economy.farm_yield. Две настройки на одно число — это гарантированный
# вопрос «а какая из них главная».
INCOME_SOURCES: tuple[tuple[str, str, str], ...] = (
    # (ключ настройки, слово команды, подпись в панели)
    ("daily_bonus", "бонус",      "🎁 Бонус"),
    ("side_job",    "подработка", "💼 Подработка"),
    ("profession",  "работа",     "👷 Работа"),
    ("fishing",     "рыбалка",    "🎣 Рыбалка"),
    ("treasure",    "клад",       "⛏ Клад"),
)

INCOME_BY_WORD: dict[str, str] = {word: key for key, word, _ in INCOME_SOURCES}
INCOME_TITLES: dict[str, str] = {key: title for key, _, title in INCOME_SOURCES}

# Ключ настройки множителя по ключу источника — он же шаблон хранения.
def income_setting_key(source: str) -> str:
    return f"economy.income.{source}"

_PERCENT = "Проценты, от 0 до 100."

SETTINGS: tuple[Setting, ...] = (
    # --- Банк ---------------------------------------------------------------
    Setting("bank.rate_1d", "Банк", "bank_manage", "Ставка вклада на 1 день, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_1d",
            default=5.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.rate_3d", "Банк", "bank_manage", "Ставка вклада на 3 дня, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_3d",
            default=7.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.rate_7d", "Банк", "bank_manage", "Ставка вклада на 7 дней, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "rate_7d",
            default=10.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.credit_fee_percent", "Банк", "bank_manage", "Комиссия по кредиту, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_fee_percent",
            default=20.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.credit_term_days", "Банк", "bank_manage", "Срок кредита, дней",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_term_days",
            default=7, minimum=1, maximum=365),
    Setting("bank.credit_penalty_percent", "Банк", "bank_manage", "Пеня по кредиту, %",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "credit_penalty_percent",
            default=10.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("bank.min_deposit", "Банк", "bank_manage", "Минимальный вклад, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "min_deposit",
            default=1000, minimum=1, maximum=1_000_000_000),
    Setting("bank.auto_reject", "Банк", "bank_auto_reject_toggle",
            "Автоотказ по заявкам на кредит",
            KIND_BOOL, STORAGE_DATA, "bank_autoreject:{chat_id}",
            default=False,
            hint="Включено — новые заявки на кредит отбиваются сразу."),
    Setting("bank.collector_after_days", "Банк", "bank_manage",
            "Коллектор приходит через, дней просрочки",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "collector_after_days",
            default=1, minimum=0, maximum=365,
            hint="0 — коллектор не приходит совсем."),
    Setting("bank.seize_after_days", "Банк", "bank_manage",
            "Взыскание через, дней просрочки",
            KIND_NUMBER, STORAGE_COLUMN, "bank_settings", "seize_after_days",
            default=5, minimum=0, maximum=365,
            hint="0 — по сроку не взыскивать. Долг всё равно взыщут, если "
                 "вырастет втрое от взятой суммы."),

    # --- Рынок --------------------------------------------------------------
    Setting("market.mode", "Рынок", "market_manage", "Разбор заявок",
            KIND_CHOICE, STORAGE_COLUMN, "market_settings", "mode",
            default="manual",
            choices=(("manual", "вручную — заявки ждут решения"),
                     ("auto_accept", "автопринятие — одобряются сразу"),
                     ("auto_reject", "автоотклонение — новые не принимаются"))),
    # Комиссия и лимит товаров — не шире, чем у команды «рынок …» в боте. Бот
    # читает колонку как есть, поэтому комиссия 90%, выставленная с сайта,
    # реально работала бы в чате, хотя командой её туда не поставить: панель
    # оказалась бы дверью в обход защитных рамок экономики. Сторож —
    # test_границы_не_шире_чем_у_бота.
    Setting("market.commission_percent", "Рынок", "market_manage", "Комиссия с продажи, %",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "commission_percent",
            default=10.0, minimum=0, maximum=50,
            hint="Процент с продажи в казну чата, от 0 до 50."),
    Setting("market.max_price", "Рынок", "market_manage", "Потолок цены товара, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "max_price",
            default=50_000, minimum=1, maximum=100_000_000),
    Setting("market.max_goods", "Рынок", "market_manage", "Товаров на человека",
            KIND_NUMBER, STORAGE_COLUMN, "market_settings", "max_goods",
            default=3, minimum=1, maximum=20),

    # --- Биржа --------------------------------------------------------------
    Setting("stock.enabled", "Биржа", "stock_toggle", "Биржа включена",
            KIND_BOOL, STORAGE_COLUMN, "stock_settings", "enabled",
            default=True,
            hint="Выключенная биржа сохраняет акции и дивиденды."),
    Setting("stock.min_change_percent", "Биржа", "stock_settings", "Минимальный шаг курса, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "min_change_percent",
            default=-15.0, minimum=-100, maximum=0,
            hint="Отрицательное число: насколько курс может упасть за шаг."),
    Setting("stock.max_change_percent", "Биржа", "stock_settings", "Максимальный шаг курса, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "max_change_percent",
            default=15.0, minimum=0, maximum=100, hint=_PERCENT),
    Setting("stock.dividend_percent", "Биржа", "stock_settings", "Дивиденды, %",
            KIND_NUMBER, STORAGE_COLUMN, "stock_settings", "dividend_percent",
            default=5.0, minimum=0, maximum=100, hint=_PERCENT),

    # --- Брак ---------------------------------------------------------------
    Setting("marriage.renew_price", "Брак", "marriage_price_set", "Цена продления, i¢",
            KIND_NUMBER, STORAGE_COLUMN, "marriage_settings", "renew_price",
            default=500, minimum=0, maximum=10_000_000,
            hint="От 0 (бесплатно) до 10 000 000 i¢ за сутки."),
    Setting("marriage.divorce_mode", "Брак", "marriage_mode_set", "Истёкший брак",
            KIND_CHOICE, STORAGE_COLUMN, "marriage_settings", "divorce_mode",
            default="off",
            choices=(("off", "остаётся в силе"),
                     ("auto", "расторгается сам"))),
    Setting("marriage.rating_enabled", "Брак", "marriage_rating_toggle", "Рейтинг браков",
            KIND_BOOL, STORAGE_COLUMN, "marriage_settings", "rating_enabled",
            default=True),

    # --- Ферма --------------------------------------------------------------
    # Бот в «ферма урожайность» не отвергает выход за 10…1000, а поджимает к
    # границе. Здесь отвергаем: молча превратить введённое число в другое —
    # худший из двух вариантов, человек уйдёт со страницы уверенным, что
    # поставил своё.
    Setting("economy.farm_yield", "Ферма", "farm_yield_set", "Урожайность фермы, %",
            KIND_NUMBER, STORAGE_COLUMN, "economy_settings", "farm_yield",
            default=100.0, minimum=10, maximum=1000,
            hint="От 10 до 1000; 100 — обычная. Множитель выдачи команды «ферма»."),

    # --- Заработок ----------------------------------------------------------
    # Множители «кранов». 100 — как задумано в коде; ни одна константа при
    # этом не тронута: появляется ручка, а не новое «правильное» значение,
    # выбранное вслепую. Ноль — законное состояние («в этом чате рыбалки
    # нет»), а не ошибка, поэтому нижняя граница именно 0.
    *(
        Setting(income_setting_key(_key), "Заработок", "income_set",
                f"{_title} — доход, %",
                KIND_NUMBER, STORAGE_DATA, "income_" + _key + ":{chat_id}",
                default=100, minimum=0, maximum=1000,
                hint="100 — как задумано, 0 — источник выключен. "
                     "Команда в чате: «доход " + _word + " {процент}».")
        for _key, _word, _title in INCOME_SOURCES
    ),
    # Не процент, а штука: сколько раз в сутки человек может взять подработку.
    # Кулдаун в 45 минут даёт физический потолок в 32 раза, то есть до 51 200
    # i¢ в сутки — в семь раз больше фермы. Лимит бьёт только по тому, ради
    # кого вводится: до потолка обычная игра просто не доходит, а кулдаун или
    # срезанная выплата задели бы всех одинаково.
    Setting("economy.side_job_daily_limit", "Заработок", "income_set",
            "💼 Подработок в сутки", KIND_NUMBER, STORAGE_DATA,
            "side_job_limit:{chat_id}",
            default=16, minimum=0, maximum=100,
            hint="0 — без лимита. Счётчик обнуляется в полночь UTC."),

    # --- Активность ---------------------------------------------------------
    Setting("activity.norm", "Активность", "set_norm", "Недельная норма сообщений",
            KIND_NUMBER, STORAGE_DATA, "norm:{chat_id}",
            default=0, minimum=0, maximum=100_000,
            hint="0 — норма снята. Кто не набрал — команда «не в норме»."),

    # --- Боссы --------------------------------------------------------------
    Setting("boss.enabled", "Боссы", "boss_toggle", "Боссы приходят в чат",
            KIND_BOOL, STORAGE_DATA, "boss_off:{chat_id}",
            default=True, inverted=True),

    # --- Дуэли --------------------------------------------------------------
    Setting("duel.outcome", "Дуэли", "duel_outcome", "Что бывает проигравшему",
            KIND_CHOICE, STORAGE_SETTINGS, "duel_outcome",
            default="kick", is_global=True,
            choices=(("0", "ничего не делать"),
                     ("kick", "кик"),
                     ("ban_minute", "бан на 1 минуту"),
                     ("ban_10min", "бан на 10 минут"),
                     ("ban_hour", "бан на 1 час"),
                     ("ban_day", "бан на сутки"),
                     ("ban_forever", "бан навсегда"),
                     ("mute_minute", "мут на 1 минуту"),
                     ("mute_10min", "мут на 10 минут"),
                     ("mute_hour", "мут на 1 час"),
                     ("mute_day", "мут на сутки"),
                     ("mute_forever", "мут навсегда"))),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}


def validate(setting: Setting, raw) -> object:
    """Значение из формы — в то, что можно писать в базу.

    Бросает ValueError с русским текстом: он уходит человеку в панель как
    есть, поэтому «invalid literal for int()» здесь недопустим.
    """
    if setting.kind == KIND_BOOL:
        text = str(raw).strip()
        if text in ("1", "true", "True"):
            return True
        if text in ("0", "false", "False"):
            return False
        raise ValueError("Переключатель принимает только 1 или 0.")

    if setting.kind == KIND_CHOICE:
        text = str(raw).strip()
        allowed = [value for value, _label in setting.choices]
        if text not in allowed:
            raise ValueError("Такого варианта нет. Доступны: " + ", ".join(allowed))
        return text

    text = str(raw).strip().replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        raise ValueError("Нужно число.") from None
    # NaN и бесконечность не парсируются как ValueError, пропускаются проверками
    # границ (nan < x и nan > x оба False), попадают в базу или вызывают ошибку
    # при конвертации в int. Отвергаем их явно.
    if not math.isfinite(number):
        raise ValueError("Нужно конечное число, не бесконечность и не NaN.")
    if setting.minimum is not None and number < setting.minimum:
        raise ValueError(f"Слишком мало: допустимо от {_num(setting.minimum)} "
                         f"до {_num(setting.maximum)}.")
    if setting.maximum is not None and number > setting.maximum:
        raise ValueError(f"Слишком много: допустимо от {_num(setting.minimum)} "
                         f"до {_num(setting.maximum)}.")
    return int(number) if setting.integer else number


def _num(value) -> str:
    """Число для текста ошибки: без хвоста «.0» у целых."""
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else str(value)
