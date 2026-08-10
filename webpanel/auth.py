"""Аккаунты, сессии и права веб-панели.

Панель рассчитана на публикацию наружу (Tailscale Funnel отдаёт её в
интернет, а не только в вашу сеть), поэтому здесь всё нарочито строго:
пароли — только argon2id-хешем, сессия — подписанная кука с истечением,
неудачные входы считаются и блокируются, а любой мутирующий запрос требует
CSRF-токен.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import secrets
import sys
from dataclasses import dataclass
from typing import Optional

# см. комментарий в __init__.py — модули бота лежат уровнем выше
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import aiomysql

import db
import webapp_auth

logger = logging.getLogger(__name__)

SESSION_COOKIE = "botpanel_session"
CSRF_COOKIE = "botpanel_csrf"
CSRF_HEADER = "X-CSRF-Token"

SESSION_TTL_SECONDS = 12 * 3600
# Порог перебора: после стольких неудач за окно вход временно закрывается.
LOGIN_FAIL_LIMIT = 7
LOGIN_FAIL_WINDOW_MINUTES = 15

MIN_PASSWORD_LENGTH = 10

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
STAFF_ROLES = (ROLE_OWNER, ROLE_ADMIN)

_hasher = PasswordHasher()


@dataclass
class PanelUser:
    id: int
    username: str
    role: str
    tg_user_id: Optional[int] = None
    tg_full_name: Optional[str] = None

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER

    @property
    def is_member(self) -> bool:
        return self.role == ROLE_MEMBER

    @property
    def display_name(self) -> str:
        return self.tg_full_name or self.username


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: Optional[str], password: str) -> bool:
    # У старых аккаунтов участников и автоматически созданных строк Mini App
    # password_hash может быть NULL, пока человек не выполнит «аккаунт» в
    # личке боту. Без этой проверки argon2 получал бы None и падал уже
    # TypeError'ом — а разный ответ на «нет такого логина» (401) и «логин есть,
    # но без пароля» (500) выдавал бы наружу, какие аккаунты существуют.
    if not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def validate_password(password: str) -> Optional[str]:
    """Возвращает текст ошибки или None, если пароль годится."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов."
    if password.isdigit():
        return "Пароль из одних цифр слишком легко подобрать."
    if password.lower() in {"password", "qwerty123456", "administrator"}:
        return "Это слишком очевидный пароль."
    return None


def validate_username(username: str) -> Optional[str]:
    if not (3 <= len(username) <= 64):
        return "Логин должен быть от 3 до 64 символов."
    if not all(ch.isalnum() or ch in "._-" for ch in username):
        return "В логине можно использовать буквы, цифры, точку, дефис и подчёркивание."
    return None


# --- сессии ---------------------------------------------------------------

def _session_secret() -> str:
    """Ключ подписи сессий.

    Берётся из окружения; если не задан — генерируется разовый, и тогда все
    сессии умрут при перезапуске. Это неудобно, но безопаснее, чем зашитый
    в код секрет.
    """
    secret = os.getenv("PANEL_SESSION_SECRET")
    if not secret:
        secret = _RUNTIME_SECRET
    return secret


_RUNTIME_SECRET = secrets.token_urlsafe(48)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(), salt="botpanel-session")


def session_fingerprint(password_hash: Optional[str]) -> str:
    """Отпечаток учётных данных, вшиваемый в сессию.

    Смена пароля меняет argon2-хеш, а значит и отпечаток — и все ранее выданные
    куки перестают подходить. Без этого угнанная сессия переживала бы смену
    пароля: сам токен подписан и живёт до 12 часов, отозвать его было нечем.
    У аккаунтов-участников пароля нет, отпечаток пустой — отзывать нечего.
    """
    if not password_hash:
        return ""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def issue_session(user_id: int, password_hash: Optional[str] = None) -> str:
    return _serializer().dumps({"uid": user_id, "fp": session_fingerprint(password_hash)})


def read_session(token: str) -> Optional[tuple[int, str]]:
    """(id аккаунта, отпечаток) либо None, если кука не наша/протухла."""
    try:
        data = _serializer().loads(token, max_age=SESSION_TTL_SECONDS)
        return int(data["uid"]), str(data.get("fp") or "")
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# --- защита от перебора ---------------------------------------------------

def _trusted_proxies() -> list:
    """Сети, чьему X-Forwarded-For можно верить.

    По умолчанию — только локальные адреса: Tailscale Funnel ходит в панель
    через loopback. Переопределяется PANEL_TRUSTED_PROXIES (список сетей через
    запятую), если панель поставят за другой прокси.
    """
    raw = os.getenv("PANEL_TRUSTED_PROXIES", "127.0.0.0/8,::1/128")
    nets = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            logger.warning("PANEL_TRUSTED_PROXIES: не разобрал сеть %r — пропускаю", chunk)
    return nets


def client_ip(request: Request) -> Optional[str]:
    """IP клиента с учётом обратного прокси Tailscale.

    X-Forwarded-For слушаем ТОЛЬКО если запрос пришёл от доверенного прокси:
    заголовок подделывается одной строкой, а по нему считаются неудачные входы
    (см. login_is_blocked). Раньше любой желающий менял его на каждый запрос и
    тем самым обнулял счётчик перебора по адресу.

    Берём последний элемент списка, а не первый: его дописал наш собственный
    прокси, а всё, что левее, мог прислать сам клиент.
    """
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer:
        try:
            peer_addr = ipaddress.ip_address(peer)
        except ValueError:
            peer_addr = None
        if peer_addr is not None and any(peer_addr in net for net in _trusted_proxies()):
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1][:64]
    return peer[:64] if peer else None


async def login_is_blocked(username: str, ip: Optional[str]) -> bool:
    fails = await db.count_failed_logins(username, ip, LOGIN_FAIL_WINDOW_MINUTES)
    return fails >= LOGIN_FAIL_LIMIT


# --- проверка запроса -----------------------------------------------------

async def current_user(request: Request) -> Optional[PanelUser]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    parsed = read_session(token)
    if parsed is None:
        return None
    user_id, fingerprint = parsed
    row = await db.get_panel_user_by_id(user_id)
    if not row or row.get("disabled"):
        return None
    # Пароль сменили (или сбросили) — старые куки больше не годятся.
    if not secrets.compare_digest(fingerprint, session_fingerprint(row.get("password_hash"))):
        return None
    return PanelUser(
        id=row["id"], username=row["username"], role=row["role"],
        tg_user_id=row.get("tg_user_id"), tg_full_name=row.get("tg_full_name"),
    )


async def require_user(request: Request) -> PanelUser:
    """Доступ для ПЕРСОНАЛА (owner/admin). Участник (member) сюда НЕ проходит —
    так все существующие админ-эндпоинты, висящие на require_user, остаются
    закрытыми для участников без пере-аудита каждого. Участник ходит через
    require_member (отдельные read-only эндпоинты)."""
    user = await current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход")
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только администраторам")
    return user


WEBAPP_INIT_DATA_HEADER = "X-Telegram-Init-Data"


async def telegram_webapp_user(request: Request) -> Optional[PanelUser]:
    """Участник, подтверждённый подписью Telegram Mini App, — или None.

    Мини-приложение открывается кнопкой прямо в чате: Telegram сам присылает
    подписанные данные о том, кто его открыл, и вводить код от бота не нужно.
    Подпись считается на секрете бота (см. webapp_auth), поэтому подделать её
    нельзя, а значит tg_user_id отсюда так же надёжен, как из сессии.

    Строку аккаунта заводим/находим ту же самую, что и для постоянного
    аккаунта участника, чтобы Mini App и браузер не создавали две личности.
    """
    init_data = request.headers.get(WEBAPP_INIT_DATA_HEADER)
    if not init_data:
        return None
    verified, reason = webapp_auth.check_init_data(init_data)
    if verified is None:
        # В лог — с причиной: иначе «не пускает» неотличимо от «панель подняли
        # с другим токеном». Саму подпись не пишем.
        logger.warning("Мини-приложение: вход отклонён (%s)", reason)
        return None

    # Ищем аккаунт по tg_user_id ЛЮБОЙ роли, а не только role='member'.
    #
    # Почему это важно: колонка panel_users.tg_user_id — UNIQUE, а персонал
    # (owner/admin) привязывает к ней свой Telegram сам (команда «код панели»).
    # При поиске только участников такая строка не находилась,
    # мы пытались завести вторую с тем же tg_user_id, упирались в UNIQUE — и
    # отказывали. То есть ВЛАДЕЛЕЦ не мог войти в собственное приложение,
    # а обычный участник мог. Именно так это и проявилось при первом заходе.
    row = await db.get_panel_user_by_tg(verified.id)
    if row is None:
        # Аккаунта нет вовсе — первое открытие, заводим участника. Гонку
        # (приложение дёргает несколько ручек сразу) ловим по UNIQUE.
        try:
            member_id = await db.create_panel_member(
                verified.id, f"tg{verified.id}", verified.full_name
            )
        except aiomysql.IntegrityError:
            row = await db.get_panel_user_by_tg(verified.id)
            if row is None:
                logger.warning("Мини-приложение: не удалось завести аккаунт для tg %s", verified.id)
                return None
            member_id = row["id"]
        role = ROLE_MEMBER
        username = f"tg{verified.id}"
    else:
        if row.get("disabled"):
            # Аккаунт отключили в панели — подпись Telegram это не отменяет.
            logger.warning("Мини-приложение: аккаунт tg %s отключён", verified.id)
            return None
        member_id = row["id"]
        # Роль сохраняем настоящую: привязанный персонал ходит в раздел
        # участника под собой — ровно как и с обычной сессией (см.
        # require_member ниже). Админские ручки при этом остаются закрытыми:
        # их проверяет require_user, а он смотрит только куку.
        role = row.get("role") or ROLE_MEMBER
        username = row.get("username") or f"tg{verified.id}"
        if verified.full_name and row.get("tg_full_name") != verified.full_name:
            await db.update_panel_member_name(member_id, verified.full_name)

    # Помечаем запрос: verify_csrf по этой метке пропустит проверку (см. там же).
    request.state.telegram_webapp = True
    return PanelUser(
        id=member_id, username=username, role=role,
        tg_user_id=verified.id, tg_full_name=verified.full_name,
    )


async def require_member(request: Request) -> PanelUser:
    """Доступ для аккаунта-участника (роль member) — а также для персонала
    (admin/owner), самостоятельно привязавшего свой аккаунт к Telegram
    (POST /api/link-telegram): тогда те же member-эндпоинты работают под их
    собственным tg_user_id, дополнительно к обычной админ-панели.

    Третий способ — мини-приложение в Telegram: там вместо куки приходит
    подписанная initData. Проверяем её ПЕРВОЙ и только при наличии заголовка,
    так что на обычный вход через сайт это никак не влияет.
    """
    from_webapp = await telegram_webapp_user(request)
    if from_webapp is not None:
        return from_webapp

    user = await current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен вход")
    if user.is_member:
        return user
    if user.role in STAFF_ROLES and user.tg_user_id is not None:
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел для участников")


async def require_owner(request: Request) -> PanelUser:
    user = await require_user(request)
    if not user.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только владельцу")
    return user


def verify_csrf(request: Request) -> None:
    """Сверяет токен из заголовка с кукой (double submit cookie).

    Без этого любой сторонний сайт мог бы, пока вы залогинены, заставить ваш
    браузер отправить сообщение от имени бота.

    Мини-приложение Telegram — исключение, и это не послабление. CSRF защищает
    от того, что браузер САМ подставляет куку к чужому запросу; там же куки нет
    вовсе — доступ даёт подписанная initData в заголовке, а выставить свой
    заголовок в кросс-сайтовом запросе чужая страница не может. Метку ставит
    require_member, уже проверив подпись (см. telegram_webapp_user).
    """
    if getattr(request.state, "telegram_webapp", False):
        return
    sent = request.headers.get(CSRF_HEADER)
    expected = request.cookies.get(CSRF_COOKIE)
    if not sent or not expected or not secrets.compare_digest(sent, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный CSRF-токен")


# --- первый запуск --------------------------------------------------------

_setup_token: Optional[str] = None


def setup_token() -> Optional[str]:
    return _setup_token


def generate_setup_token() -> str:
    global _setup_token
    _setup_token = secrets.token_urlsafe(24)
    return _setup_token


def clear_setup_token() -> None:
    global _setup_token
    _setup_token = None


def check_setup_token(token: str) -> bool:
    return bool(_setup_token) and secrets.compare_digest(token, _setup_token or "")
