"""Проверка подписи Telegram Mini App (initData).

Когда мини-приложение открывается кнопкой из чата, Telegram передаёт странице
строку initData: обычный query-string с полями user, auth_date, chat и т.п. и
контрольной суммой hash. Подпись считается на СЕКРЕТЕ БОТА, поэтому подделать
её, не зная токена, нельзя — а значит, содержимому можно верить и спрашивать
пароль не нужно вовсе.

Схема из документации Telegram:

    secret_key       = HMAC_SHA256(key="WebAppData", msg=<токен бота>)
    data_check_string= "\\n".join(f"{k}={v}" for k, v in sorted(поля без hash))
    ожидаемый hash   = HMAC_SHA256(key=secret_key, msg=data_check_string)

Модуль намеренно чистый: ни FastAPI, ни базы, ни aiogram — только stdlib. Так
его можно проверить тестами целиком, а он тут единственное, что стоит между
чатом и чужим аккаунтом.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

# Сколько живёт подпись. initData попадает в адресную строку webview, поэтому
# теоретически может утечь (скриншот, лог прокси, история). Ограничение по
# времени превращает такую утечку из «вечного ключа» в «ключ на сутки».
# Сутки — с запасом: Telegram не переоткрывает мини-приложение при каждом
# действии, и пользователь может держать его открытым весь день.
MAX_AUTH_AGE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class WebAppUser:
    """Пользователь, подтверждённый подписью Telegram."""

    id: int
    first_name: str = ""
    last_name: str = ""
    username: Optional[str] = None

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or (f"@{self.username}" if self.username else str(self.id))


def _bot_token() -> Optional[str]:
    return os.getenv("BOT_TOKEN") or None


def _expected_hash(data_check_string: str, bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def check_init_data(
    init_data: Optional[str],
    bot_token: Optional[str] = None,
    max_age_seconds: int = MAX_AUTH_AGE_SECONDS,
) -> tuple[Optional[WebAppUser], str]:
    """(пользователь, короткая причина отказа).

    Причина нужна для диагностики: без неё «не пустило» — это чёрный ящик, в
    котором одинаково выглядят «панель запущена с другим токеном бота»,
    «время на сервере убежало» и «клиент вообще ничего не прислал». Наружу
    причина отдаётся только владельцу через /api/webapp-check и в лог; ни
    токена, ни самой подписи в ней нет, подобрать по ней ничего нельзя.
    """
    if not init_data:
        return None, "нет данных от Telegram"
    token = bot_token or _bot_token()
    if not token:
        return None, "у панели не задан BOT_TOKEN — подпись проверять нечем"

    # strict_parsing: мусор вместо query-string должен быть отказом, а не
    # молча разобранной половиной строки.
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
    except ValueError:
        return None, "данные не разбираются как query-string"

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None, "в данных нет поля hash"

    # ПРО signature. Новые клиенты добавляют ещё и Ed25519-подпись отдельным
    # полем. В контрольную строку для hash она, по всем известным реализациям,
    # не входит — но документация на этот счёт менялась, а цена ошибки здесь
    # «не пускает вообще никого». Поэтому проверяем оба варианта: и без
    # signature, и с ним. Безопасность не страдает — обе строки считаются тем
    # же секретом бота по реально присланным полям, подделать любую из них
    # по-прежнему нельзя.
    signature = pairs.pop("signature", None)
    variants = ["\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))]
    if signature is not None:
        with_signature = dict(pairs, signature=signature)
        variants.append("\n".join(f"{k}={with_signature[k]}" for k in sorted(with_signature)))

    if not any(
        hmac.compare_digest(_expected_hash(v, token), received_hash) for v in variants
    ):
        return None, "подпись не сошлась — обычно это другой BOT_TOKEN у панели и у бота"

    # Свежесть: подпись без срока годности — это украденный навсегда доступ.
    raw_auth_date = pairs.get("auth_date")
    if not raw_auth_date:
        return None, "в данных нет auth_date"
    try:
        auth_date = int(raw_auth_date)
    except ValueError:
        return None, "auth_date не число"
    age = time.time() - auth_date
    if age > max_age_seconds:
        return None, f"подпись старше {max_age_seconds // 3600} ч — переоткройте приложение"
    if age < -300:
        return None, "auth_date из будущего — разъехалось время на сервере"

    raw_user = pairs.get("user")
    if not raw_user:
        return None, "подпись верна, но в ней нет пользователя"
    try:
        user = json.loads(raw_user)
    except (ValueError, TypeError):
        return None, "поле user не разбирается как JSON"
    if not isinstance(user, dict):
        return None, "поле user не объект"

    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return None, "в user нет числового id"
    if user.get("is_bot"):
        return None, "это бот, а не человек"

    return WebAppUser(
        id=user_id,
        first_name=str(user.get("first_name") or "")[:64],
        last_name=str(user.get("last_name") or "")[:64],
        username=(str(user["username"])[:64] if user.get("username") else None),
    ), ""


def parse_init_data(
    init_data: Optional[str],
    bot_token: Optional[str] = None,
    max_age_seconds: int = MAX_AUTH_AGE_SECONDS,
) -> Optional[WebAppUser]:
    """Пользователь или None. Никаких «почти валидно»: любая осечка — отказ."""
    user, _reason = check_init_data(init_data, bot_token, max_age_seconds)
    return user


def build_init_data(user: dict, bot_token: str, auth_date: Optional[int] = None) -> str:
    """Собирает подписанную initData — нужно тестам (и только им).

    Держим рядом с проверкой намеренно: если формат контрольной строки
    поменяется, тесты, собранные этой же функцией, перестанут что-либо
    проверять молча. Поэтому здесь она собирается независимо, «как Telegram».
    """
    fields = {
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAF_test",
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    fields["hash"] = _expected_hash(data_check_string, bot_token)
    from urllib.parse import urlencode

    return urlencode(fields)
