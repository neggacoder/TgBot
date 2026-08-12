"""Веб-панель управления ботом.

Отдельный процесс рядом с ботом: своё подключение к той же MySQL и свой
экземпляр Bot для отправки сообщений. Апдейты панель не забирает — их читает
сам бот, а здесь только исходящие вызовы Telegram API, поэтому два процесса
с одним токеном друг другу не мешают.

Запуск:  python -m webpanel
"""
# app.py
from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import os
import re
import secrets
import sys
import time
from datetime import date, datetime, timedelta
from typing import AsyncIterator, Optional

# Модули бота лежат на уровень выше этого пакета. Дублируем правку путей из
# __init__.py: при прямом запуске файла (python webpanel/app.py) пакетный
# __init__ не выполняется, и `import db` не нашёл бы модуль.
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

if __name__ == "__main__":
    # Файл — часть пакета и напрямую не запускается: относительные импорты
    # ниже требуют, чтобы Python знал о пакете webpanel. Без этой подсказки
    # человек увидел бы «attempted relative import with no known parent
    # package» и гадал, что не так.
    raise SystemExit(
        "Этот файл нельзя запускать напрямую.\n"
        "Запуск панели из папки бота:\n"
        "    python -m webpanel\n"
        "или:\n"
        "    uvicorn webpanel.app:app --host 127.0.0.1 --port 8080"
    )

from dotenv import load_dotenv

# .env читаем и здесь. Раньше это делал только webpanel/__main__.py, то
# есть при запуске через «uvicorn webpanel.app:app» (такой способ описан в
# INSTALL.md) панель оставалась без BOT_TOKEN — а на нём считается подпись
# мини-приложения. Вызов идемпотентный: уже заданные переменные окружения
# он не перетирает.
load_dotenv()

import aiomysql
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, LinkPreviewOptions
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import admin_holds
import chats as chats_mod
import db
import owner_flags
import relationships_v2
import rest_rules
import rp_photos
import webapp_auth
import tz_settings

from . import auth, roles
from .auth import PanelUser

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Панель управления ботом", docs_url=None, redoc_url=None)

_bot: Optional[Bot] = None


def get_bot() -> Bot:
    if _bot is None:
        raise HTTPException(503, "Бот не инициализирован")
    return _bot


@app.on_event("startup")
async def on_startup() -> None:
    global _bot
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан — панель не сможет писать от имени бота")
    _bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    await db.init_pool()
    await db.ensure_panel_tables()
    # Ленту создаёт и наполняет бот, но панель могли поднять первой — тогда
    # /api/messages падал бы на несуществующей таблице. CREATE IF NOT EXISTS
    # идемпотентен, так что лишним не будет.
    await db.ensure_recent_messages_table()
    # Панель тоже читает браки (экран участника, /api/member/relationship), и
    # её могли поднять раньше бота — тогда запрос ушёл бы в колонку expires_at,
    # которой ещё нет. Миграция идемпотентна.
    await db.ensure_marriage_module_tables()
    await db.ensure_human_pets_table()
    # Свои сроки автоочистки команд правит только панель — а создаёт таблицу
    # бот. Если панель подняли первой, первая же правка упала бы на
    # несуществующей таблице. Миграция идемпотентна.
    await db.ensure_command_cleanup_table()
    # Зеркало реестра команд наполняет бот, но колонку cleanup_targetable мог
    # не успеть добавить (старая база + панель поднялась первой) — тогда
    # «Дерево команд» падало бы на SELECT несуществующей колонки.
    await db.ensure_command_registry_table()

    if await db.count_panel_users() == 0:
        token = auth.generate_setup_token()
        logger.warning(
            "\n%s\nПАНЕЛЬ ЕЩЁ НЕ НАСТРОЕНА. Откройте один раз ссылку и задайте владельца:\n"
            "    /setup?token=%s\n"
            "Ссылка действует до перезапуска и исчезает после создания владельца.\n%s",
            "=" * 70, token, "=" * 70,
        )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if _bot is not None:
        await _bot.session.close()
    await db.close_pool()


# Мини-приложение Telegram открывается ВНУТРИ клиента: в Telegram Web это
# обычный iframe, поэтому глобальные X-Frame-Options: DENY и frame-ancestors
# 'none' его просто не покажут. Послабление делаем адресно — только для
# страницы мини-аппа, и только на встраивание доменами Telegram. Все /api/*
# и сама панель остаются запрещёнными к встраиванию, как были.
WEBAPP_PATH = "/app"
TELEGRAM_FRAME_ANCESTORS = "https://web.telegram.org https://telegram.org"
# SDK мини-приложения лежит на telegram.org — единственный внешний скрипт во
# всём проекте, и разрешён он ровно на одной странице.
TELEGRAM_SDK_ORIGIN = "https://telegram.org"

_BASE_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' \'unsafe-inline\'; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Заголовки безопасности: панель смотрит в интернет через Funnel."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Куки помечены secure — но без HSTS браузер, впервые пришедший по http,
    # успевает отдать запрос в открытом виде. Funnel всегда https, так что
    # включаем на год и на поддомены.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    is_webapp = request.url.path == WEBAPP_PATH or request.url.path.startswith(WEBAPP_PATH + "/")
    if is_webapp:
        # Встраивание — только клиентам Telegram; X-Frame-Options не ставим
        # вовсе: он умеет лишь DENY/SAMEORIGIN и здесь только помешал бы.
        response.headers["Content-Security-Policy"] = (
            f"{_BASE_CSP}; script-src 'self' {TELEGRAM_SDK_ORIGIN}; "
            f"frame-ancestors {TELEGRAM_FRAME_ANCESTORS}"
        )
    else:
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            f"{_BASE_CSP}; script-src 'self'; frame-ancestors 'none'"
        )
    return response


# Настройки чатов живут отдельным модулем: app.py и без них 4000+ строк.
from .chat_settings_api import router as chat_settings_router  # noqa: E402
app.include_router(chat_settings_router)


# ---------------------------------------------------------------------------
# Действия в отношениях,фразы
# ---------------------------------------------------------------------------
RP_ACTIONS: list[dict] = [
    {
        "level": 1, "key": "compliment", "name": "Сделать комплимент",
        "verb": "сделал(а) комплимент",
        "phrases": [
            "Ты удивительно талантлив(а).",
            "Рядом с тобой я чувствую себя счастливее.",
            "Твоя улыбка — лучшее, что случалось со мной сегодня.",
            "Ты потрясающий(ая) человек, и мне повезло быть с тобой.",
        ],
        "reward": 15, "cooldown_minutes": 5,
    },
    {
        "level": 2, "key": "breakfast", "name": "Сделать завтрак",
        "verb": "приготовил(а) завтрак",
        "phrases": ["Свежие тосты и любимый кофе — специально для тебя."],
        "reward": 35, "cooldown_minutes": 8,
    },
    {
        "level": 3, "key": "flowers", "name": "Подарить цветы",
        "verb": "подарил(а) цветы",
        "phrases": [],  # без цитаты — просто действие
        "reward": 60, "cooldown_minutes": 11,
    },{
    "level": 4, "key": "movie", "name": "Посмотреть фильм",
    "verb": "посмотрел(а) фильм вместе",
    "phrases": [
        "Любой фильм становится лучше, если смотреть его рядом с тобой.",
        "Сегодня главный сюжет — это мы.",
        "Я бы пересматривал(а) этот вечер бесконечно.",
    ],
    "reward": 80, "cooldown_minutes": 15,
},
{
    "level": 5, "key": "massage", "name": "Сделать массаж",
    "verb": "сделал(а) массаж",
    "phrases": [
        "Пусть усталость уйдёт, а останется только спокойствие.",
        "Хочу, чтобы ты чувствовал(а) себя лучше благодаря мне.",
        "Ты заслуживаешь заботы каждый день.",
    ],
    "reward": 120, "cooldown_minutes": 20,
},
{
    "level": 6, "key": "dinner", "name": "Романтический ужин",
    "verb": "устроил(а) романтический ужин",
    "phrases": [
        "Самое вкусное сегодня — время, проведённое вместе.",
        "Каждый ужин с тобой становится маленьким праздником.",
        "Ты — мой любимый повод улыбаться.",
    ],
    "reward": 170, "cooldown_minutes": 30,
},
{
    "level": 7, "key": "gift", "name": "Сделать подарок",
    "verb": "сделал(а) подарок",
    "phrases": [
        "Этот подарок — лишь маленькая часть моей заботы о тебе.",
        "Твоя радость для меня бесценна.",
        "Мне нравится делать тебя счастливее.",
    ],
    "reward": 230, "cooldown_minutes": 38,
},
{
    "level": 8, "key": "trip", "name": "Туристическая поездка",
    "verb": "отправился(ась) в путешествие",
    "phrases": [
        "Самые красивые места — те, где мы вместе.",
        "Каждая дорога с тобой становится приключением.",
        "Главный сувенир этой поездки — наши воспоминания.",
    ],
    "reward": 300, "cooldown_minutes": 45,
},
{
    "level": 9, "key": "astronomy", "name": "Вечер астрономии",
    "verb": "провёл(а) вечер под звёздами",
    "phrases": [
        "Даже звёзды сегодня светят чуть ярче.",
        "Когда ты рядом, небо кажется бесконечно красивым.",
        "Самая яркая звезда сейчас — это ты.",
    ],
    "reward": 400, "cooldown_minutes": 60,
},
{
    "level": 10, "key": "memories", "name": "Приятные воспоминания",
    "verb": "вспомнил(а) лучшие моменты",
    "phrases": [
        "Наши воспоминания — сокровище, которое всегда со мной.",
        "Каждый момент с тобой хочется сохранить навсегда.",
        "Прошлое прекрасно, потому что в нём есть ты.",
    ],
    "reward": 500, "cooldown_minutes": 80,
},
{
    "level": 11, "key": "photoshoot", "name": "Совместная фотосессия",
    "verb": "устроил(а) совместную фотосессию",
    "phrases": [
        "На каждой фотографии есть причина улыбнуться.",
        "Самые красивые кадры — это моменты рядом с тобой.",
        "Эти снимки будут согревать нас ещё долгие годы.",
    ],
    "reward": 700, "cooldown_minutes": 90,
},
{
    "level": 12, "key": "tradition", "name": "Создать традицию",
    "verb": "создал(а) новую традицию",
    "phrases": [
        "Пусть эта традиция напоминает, как дороги мы друг другу.",
        "Маленькие привычки создают большое счастье.",
        "Хочу, чтобы у нас всегда были особенные моменты.",
    ],
    "reward": 900, "cooldown_minutes": 100,
},
{
    "level": 13, "key": "project", "name": "Совместный проект",
    "verb": "начал(а) совместный проект",
    "phrases": [
        "Вместе мы способны на гораздо большее.",
        "Любое дело становится легче рядом с тобой.",
        "Мне нравится создавать что-то вместе с тобой.",
    ],
    "reward": 1100, "cooldown_minutes": 110,
},
{
    "level": 14, "key": "genealogy", "name": "Исследовать родословную",
    "verb": "исследовал(а) родословную",
    "phrases": [
        "Интересно узнавать, какой путь привёл нас друг к другу.",
        "История семьи делает настоящее ещё ценнее.",
        "Каждая история начинается с любви.",
    ],
    "reward": 1400, "cooldown_minutes": 120,
},
{
    "level": 15, "key": "future", "name": "Спланировать будущее",
    "verb": "спланировал(а) будущее",
    "phrases": [
        "Мне нравится мечтать о завтрашнем дне вместе с тобой.",
        "Будущее кажется светлее, когда ты рядом.",
        "Пусть впереди нас ждёт ещё много счастливых дней.",
    ],
    "reward": 1700, "cooldown_minutes": 130,
},
{
    "level": 16, "key": "wish", "name": "Исполнить желание",
    "verb": "исполнил(а) желание",
    "phrases": [
        "Твоя улыбка стоит любых усилий.",
        "Мне приятно делать тебя счастливым(ой).",
        "Пусть мечты становятся реальностью.",
    ],
    "reward": 2100, "cooldown_minutes": 140,
},
{
    "level": 17, "key": "anniversary", "name": "Годовщина отношений",
    "verb": "отметил(а) годовщину",
    "phrases": [
        "Каждый год рядом с тобой — настоящий подарок.",
        "Спасибо за все моменты, которые мы разделили.",
        "Это только начало нашей истории.",
    ],
    "reward": 2500, "cooldown_minutes": 150,
},
{
    "level": 18, "key": "home", "name": "Обустроить жилище",
    "verb": "сделал(а) дом уютнее",
    "phrases": [
        "Дом становится настоящим, когда в нём есть ты.",
        "Самый уютный уголок мира — рядом с тобой.",
        "Хочу, чтобы сюда всегда хотелось возвращаться.",
    ],
    "reward": 3000, "cooldown_minutes": 160,
},
{
    "level": 19, "key": "spirit", "name": "Духовное единение",
    "verb": "укрепил(а) духовную связь",
    "phrases": [
        "Иногда слова не нужны, чтобы понять друг друга.",
        "Наше доверие — самая крепкая связь.",
        "Я ценю всё, что объединяет нас.",
    ],
    "reward": 3500, "cooldown_minutes": 170,
},
{
    "level": 20, "key": "retreat", "name": "Уединенный отдых",
    "verb": "устроил(а) уединённый отдых",
    "phrases": [
        "Иногда весь мир может подождать.",
        "Самое ценное место — там, где мы вдвоём.",
        "Покой рядом с тобой бесценен.",
    ],
    "reward": 4000, "cooldown_minutes": 180,
},
{
    "level": 21, "key": "vow", "name": "Написать клятву",
    "verb": "написал(а) клятву",
    "phrases": [
        "Каждое слово написано от всего сердца.",
        "Пусть эти обещания будут крепче времени.",
        "Ты вдохновляешь меня быть лучше.",
    ],
    "reward": 4800, "cooldown_minutes": 200,
},
{
    "level": 22, "key": "talisman", "name": "Создать талисман",
    "verb": "создал(а) талисман",
    "phrases": [
        "Пусть этот талисман хранит наше счастье.",
        "Он будет напоминать о самых тёплых моментах.",
        "Немного магии для нашей истории.",
    ],
    "reward": 5600, "cooldown_minutes": 220,
},
{
    "level": 23, "key": "song", "name": "Написать песню",
    "verb": "написал(а) песню",
    "phrases": [
        "Каждая строчка звучит благодаря тебе.",
        "У нашей любви есть собственная мелодия.",
        "Эта песня навсегда останется особенной.",
    ],
    "reward": 6500, "cooldown_minutes": 240,
},
{
    "level": 24, "key": "garden", "name": "Вырастить сад",
    "verb": "вырастил(а) сад",
    "phrases": [
        "Пусть каждый цветок напоминает о нашей заботе.",
        "Красота растёт там, где есть любовь.",
        "Этот сад будет цвести вместе с нашими чувствами.",
    ],
    "reward": 7500, "cooldown_minutes": 260,
},
{
    "level": 25, "key": "dance", "name": "Танцевальный вечер",
    "verb": "пригласил(а) на танец",
    "phrases": [
        "Пока играет музыка, существует только этот момент.",
        "Самый красивый танец — рядом с тобой.",
        "Неважно, умеем ли мы танцевать. Главное — вместе.",
    ],
    "reward": 8500, "cooldown_minutes": 280,
},
{
    "level": 26, "key": "family_council", "name": "Семейный совет",
    "verb": "провёл(а) семейный совет",
    "phrases": [
        "Любое решение легче принимать вместе.",
        "Мы — одна команда.",
        "Наше единство важнее любых разногласий.",
    ],
    "reward": 10000, "cooldown_minutes": 300,
},
{
    "level": 27, "key": "star", "name": "Назвать звезду",
    "verb": "назвал(а) звезду",
    "phrases": [
        "Теперь даже на небе есть напоминание о тебе.",
        "Некоторые чувства невозможно измерить расстоянием.",
        "Ты сияешь ярче любой звезды.",
    ],
    "reward": 11500, "cooldown_minutes": 320,
},
{
    "level": 28, "key": "book", "name": "Написать книгу",
    "verb": "написал(а) книгу",
    "phrases": [
        "Каждая глава хранит частичку нашей истории.",
        "Эту историю хочется перечитывать снова и снова.",
        "Лучшие страницы ещё впереди.",
    ],
    "reward": 13000, "cooldown_minutes": 340,
},
{
    "level": 29, "key": "celebration", "name": "Организовать праздник",
    "verb": "организовал(а) праздник",
    "phrases": [
        "Сегодня повод улыбаться есть у каждого.",
        "Самый лучший праздник — тот, где мы вместе.",
        "Пусть этот день запомнится надолго.",
    ],
    "reward": 15000, "cooldown_minutes": 360,
},
{
    "level": 30, "key": "eternal_love", "name": "Вечная любовь",
    "verb": "признался(ась) в вечной любви",
    "phrases": [
        "Если бы мне пришлось выбирать снова, я всё равно выбрал(а) бы тебя.",
        "Любовь — это каждый день выбирать друг друга.",
        "Пусть наша история никогда не заканчивается.",
        "Ты — мой самый дорогой человек.",
    ],
    "reward": 18000, "cooldown_minutes": 400,
},
]

RP_ACTIONS_BY_KEY = {a["key"]: a for a in RP_ACTIONS}
# ---------------------------------------------------------------------------
# Вход и аккаунты
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class SetupBody(BaseModel):
    token: str
    username: str
    password: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = auth.ROLE_ADMIN


class PasswordBody(BaseModel):
    password: str


def _session_cookie_secure(request: Request) -> bool:
    """Сохраняет secure-куки на HTTPS, но позволяет вход через LAN-NGINX.

    NGINX всегда передаёт исходную схему в X-Forwarded-Proto. При отсутствии
    заголовка выбираем безопасный вариант: браузер получит только secure-куку.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",", 1)[0].strip().lower() != "http"


def _set_session_cookies(
    request: Request, response: Response, user_id: int,
    password_hash: Optional[str] = None,
) -> None:
    """Кладёт сессионную и CSRF-куки.

    password_hash — АКТУАЛЬНЫЙ хеш пароля аккаунта: его отпечаток вшивается в
    сессию, чтобы смена пароля обесценивала все ранее выданные куки (см.
    auth.session_fingerprint). У аккаунта-участника пароля нет — None.
    """
    csrf = auth.new_csrf_token()
    secure = _session_cookie_secure(request)
    response.set_cookie(
        auth.SESSION_COOKIE, auth.issue_session(user_id, password_hash),
        httponly=True, secure=secure, samesite="lax", max_age=auth.SESSION_TTL_SECONDS,
    )
    # CSRF-куку намеренно НЕ делаем httponly: её читает наш же скрипт,
    # чтобы отправить обратно заголовком
    response.set_cookie(
        auth.CSRF_COOKIE, csrf,
        httponly=False, secure=secure, samesite="lax", max_age=auth.SESSION_TTL_SECONDS,
    )


@app.post("/api/setup")
async def api_setup(body: SetupBody, request: Request):
    """Создание владельца по одноразовой ссылке из логов первого запуска."""
    if await db.count_panel_users() > 0:
        raise HTTPException(409, "Владелец уже создан")
    if not auth.check_setup_token(body.token):
        raise HTTPException(403, "Ссылка недействительна")

    error = auth.validate_username(body.username) or auth.validate_password(body.password)
    if error:
        raise HTTPException(400, error)

    # Токен гасим ДО создания владельца: иначе два одновременных запроса с одной
    # ссылкой оба проходили бы проверку и заводили по владельцу.
    auth.clear_setup_token()
    password_hash = auth.hash_password(body.password)
    user_id = await db.create_panel_user(body.username, password_hash, auth.ROLE_OWNER)
    await db.add_panel_login_attempt(body.username, auth.client_ip(request), True)

    response = JSONResponse({"ok": True, "role": auth.ROLE_OWNER})
    _set_session_cookies(request, response, user_id, password_hash)
    return response


@app.post("/api/login")
async def api_login(body: LoginBody, request: Request):
    ip = auth.client_ip(request)
    if await auth.login_is_blocked(body.username, ip):
        raise HTTPException(429, "Слишком много неудачных попыток. Подождите 15 минут.")

    row = await db.get_panel_user(body.username)
    ok = bool(row) and not row.get("disabled") and auth.verify_password(
        row["password_hash"], body.password
    )
    await db.add_panel_login_attempt(body.username, ip, ok)
    if not ok:
        # одинаковый ответ и на несуществующий логин, и на неверный пароль —
        # иначе панель подсказывала бы, какие логины существуют
        raise HTTPException(401, "Неверный логин или пароль")

    password_hash = row["password_hash"]
    if auth.needs_rehash(password_hash):
        password_hash = auth.hash_password(body.password)
        await db.set_panel_password(row["id"], password_hash)
    await db.touch_panel_login(row["id"])

    response = JSONResponse({"ok": True, "role": row["role"], "username": row["username"]})
    _set_session_cookies(request, response, row["id"], password_hash)
    return response


@app.post("/api/logout")
async def api_logout(request: Request):
    # CSRF и на выходе: без него любой сайт мог бы выкидывать вас из панели.
    auth.verify_csrf(request)
    response = JSONResponse({"ok": True})
    # Флаги должны совпадать с теми, с которыми куки ставились, иначе браузер
    # не сопоставит их с существующими и те останутся жить до истечения срока.
    secure = _session_cookie_secure(request)
    response.delete_cookie(auth.SESSION_COOKIE, httponly=True, secure=secure, samesite="lax")
    response.delete_cookie(auth.CSRF_COOKIE, httponly=False, secure=secure, samesite="lax")
    return response


@app.get("/api/me")
async def api_me(request: Request):
    user = await auth.current_user(request)
    if user is None:
        return {"authenticated": False, "setup_required": await db.count_panel_users() == 0}
    result = {
        "authenticated": True,
        "username": user.username,
        "role": user.role,
        "name": user.display_name,
    }
    if user.role in auth.STAFF_ROLES:
        # Персонал видит статус собственной привязки к Telegram в панели
        # (блок «Мой Telegram» / доступ к экрану участника) — участнику эти
        # поля не нужны, у него и так есть tg-аккаунт по определению.
        result["tg_user_id"] = user.tg_user_id
        result["tg_full_name"] = user.tg_full_name
    return result


class LinkTelegramBody(BaseModel):
    code: str


@app.post("/api/link-telegram")
async def api_link_telegram(
    body: LinkTelegramBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if user.tg_user_id is not None:
        raise HTTPException(409, "Ваш аккаунт уже привязан к Telegram.")

    row = await db.consume_panel_link_code(body.code.strip().upper())
    if not row:
        raise HTTPException(400, "Код неверный или устарел.")

    existing = await db.get_panel_user_by_tg(row["tg_user_id"])
    if existing and existing["id"] != user.id:
        if user.role not in auth.STAFF_ROLES or existing["role"] != "member":
            raise HTTPException(409, "Этот Telegram уже привязан к другому аккаунту.")
        try:
            merged = await db.merge_panel_member_into_staff(
                user.id, existing["id"], row["tg_user_id"], row.get("tg_full_name")
            )
        except aiomysql.IntegrityError:
            raise HTTPException(409, "Этот Telegram уже привязан к другому аккаунту.")
        if not merged:
            raise HTTPException(409, "Не удалось объединить аккаунты. Получите новый код и повторите.")
        await db.add_log(
            "panel_accounts_merged", actor_id=user.id,
            details=f"member={existing['id']}; tg={row['tg_user_id']}",
        )
        return {"ok": True, "merged": True, "tg_full_name": row.get("tg_full_name")}

    try:
        await db.set_panel_user_tg_link(user.id, row["tg_user_id"], row.get("tg_full_name"))
    except aiomysql.IntegrityError:
        raise HTTPException(409, "Этот Telegram уже привязан к другому аккаунту.")
    await db.add_log("panel_tg_linked", actor_id=user.id, details=str(row["tg_user_id"]))
    return {"ok": True, "tg_full_name": row.get("tg_full_name")}


# ---------------------------------------------------------------------------
# Бесконечные деньги («+бесконечность») — рубильник владельца.
#
# Он же существует командой в чате, и это ровно тот случай, ради которого
# заведён owner_flags: список читается из базы на каждый вопрос, а не из
# множества в памяти бота. Иначе кнопка здесь выглядела бы сработавшей, а бот
# продолжал бы списывать монеты до перезапуска.
#
# Привязка телеграма обязательна и это не формальность: бот знает человека по
# телеграм-идентификатору, а у аккаунта панели его может не быть вовсе.
# Записать нечего — значит рубильник бы молчал.
# ---------------------------------------------------------------------------
class InfiniteMoneyBody(BaseModel):
    enabled: bool


@app.get("/api/owner/infinite-money")
async def api_infinite_money(user: PanelUser = Depends(auth.require_owner)):
    return {
        "linked": user.tg_user_id is not None,
        "enabled": await owner_flags.has_infinite_money(user.tg_user_id),
        # Кому ещё включено — владелец должен видеть, что рубильник не только
        # его: список общий, и выключить чужой отсюда нельзя.
        "others": sorted(u for u in await owner_flags.infinite_money_users()
                         if u != user.tg_user_id),
    }


@app.post("/api/owner/infinite-money")
async def api_infinite_money_set(
    body: InfiniteMoneyBody, request: Request,
    user: PanelUser = Depends(auth.require_owner),
):
    auth.verify_csrf(request)
    if user.tg_user_id is None:
        raise HTTPException(400, "Сначала привяжите телеграм — бот узнаёт вас по нему.")
    await owner_flags.set_infinite_money(user.tg_user_id, body.enabled)
    # Тот же журнал, что у команды в чате: в аудите оба входа выглядят
    # одинаково, и по нему видно, откуда переключали.
    await db.add_log("infinite_money_toggle", actor_id=user.tg_user_id,
                     details=f"{body.enabled} (панель)")
    return {"ok": True, "enabled": body.enabled}


@app.get("/api/users")
async def api_users(user: PanelUser = Depends(auth.require_owner)):
    return {"users": await db.list_panel_users()}


@app.post("/api/users")
async def api_create_user(
    body: CreateUserBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    if body.role not in (auth.ROLE_OWNER, auth.ROLE_ADMIN):
        raise HTTPException(400, "Неизвестная роль")
    error = auth.validate_username(body.username) or auth.validate_password(body.password)
    if error:
        raise HTTPException(400, error)
    if await db.get_panel_user(body.username):
        raise HTTPException(409, "Такой логин уже занят")

    await db.create_panel_user(
        body.username, auth.hash_password(body.password), body.role, created_by=user.id
    )
    return {"ok": True}


@app.delete("/api/users/{user_id}")
async def api_delete_user(
    user_id: int, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    if user_id == user.id:
        raise HTTPException(400, "Нельзя удалить самого себя")
    target = await db.get_panel_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Аккаунт не найден")
    # последнего владельца не удаляем: иначе панель останется без хозяина
    if target["role"] == auth.ROLE_OWNER:
        owners = [u for u in await db.list_panel_users() if u["role"] == auth.ROLE_OWNER]
        if len(owners) <= 1:
            raise HTTPException(400, "Это единственный владелец — его нельзя удалить")
    await db.delete_panel_user(user_id)
    return {"ok": True}


@app.post("/api/password")
async def api_change_password(
    body: PasswordBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    error = auth.validate_password(body.password)
    if error:
        raise HTTPException(400, error)
    password_hash = auth.hash_password(body.password)
    await db.set_panel_password(user.id, password_hash)
    # Смена пароля обесценивает ВСЕ прежние сессии (в том числе чужие, если
    # куку успели угнать) — поэтому себе тут же выдаём новую, иначе панель
    # выкинула бы на форму входа сразу после смены пароля.
    response = JSONResponse({"ok": True})
    _set_session_cookies(request, response, user.id, password_hash)
    return response


@app.get("/api/logins")
async def api_logins(user: PanelUser = Depends(auth.require_owner)):
    return {"logins": await db.list_panel_logins(limit=50)}


# ---------------------------------------------------------------------------
# Чаты, участники, отправка
# ---------------------------------------------------------------------------

@app.get("/api/chats")
async def api_chats(user: PanelUser = Depends(auth.require_user)):
    """Чаты панели. Он один — рабочий.

    Раньше отдавались все чаты, где бот когда-либо состоял, и в каждом разделе
    висел выбор чата. Выбор был обманом: бот работает только в рабочем чате, а
    остальные строки — остаток от прежнего использования. Админ выбирал чат и
    смотрел данные, которых не существует.
    """
    рабочий = await chats_mod.work_chat_id()
    chats = [r for r in await db.list_current_chats()
             if рабочий is not None and r["chat_id"] == рабочий]
    if рабочий is not None and not chats:
        # Бот в рабочем чате есть, а строки в current_users ещё нет (свежая
        # привязка) — чат всё равно надо показать, иначе панель пуста.
        chats = [{"chat_id": рабочий, "members": 0}]
    out = []
    for row in chats:
        chat_id = row["chat_id"]
        title = str(chat_id)
        try:
            chat = await get_bot().get_chat(chat_id)
            title = chat.title or chat.full_name or str(chat_id)
        except Exception:
            # бота могли выгнать из чата — показываем как есть, но не падаем
            title = f"{chat_id} (недоступен)"
        out.append({
            "chat_id": chat_id,
            "title": title,
            "members": row["members"],
            "last_seen": str(row["last_seen"]) if row.get("last_seen") else None,
        })
    return {"chats": out}


@app.get("/api/roles")
async def api_roles(user: PanelUser = Depends(auth.require_user)):
    """Справочник ролей для фильтра. Названия берутся те же, что показывает
    бот в чате, — включая переименованные."""
    role_map = await roles.load()
    return {"roles": role_map.catalog()}


@app.get("/api/members")
async def api_members(
    chat_id: int, q: str = "", role: str = "", sort: str = "recent",
    user: PanelUser = Depends(auth.require_user),
):
    # Со счётчиком сообщений — чтобы показывать активность и сортировать по ней.
    rows = await db.list_current_users_with_counts(chat_id, limit=500)
    total = len(rows)
    role_map = await roles.load()
    role_map.annotate(rows)

    if role:
        # Фильтр из выпадающего списка: ключ роли («owner», «moder», …).
        wanted = roles.KEY_LEVELS.get(role)
        if wanted is None:
            raise HTTPException(400, "Неизвестная роль")
        rows = [r for r in rows if r.get("level") == wanted]

    if q:
        needle = q.casefold()
        rows = [
            r for r in rows
            if needle in (r.get("full_name") or "").casefold()
            or needle in (r.get("username") or "").casefold()
            or needle in str(r.get("user_id"))
            # По роли ищем и текстом: «модер» в общем поиске находит модераторов,
            # чтобы не заставлять человека лезть в отдельный список.
            or role_map.matches(r["user_id"], needle)
        ]

    # Сортировка. По умолчанию (recent) — недавно активные сверху (rows уже по
    # last_seen_at DESC), как было раньше; плюс по количеству сообщений и имени.
    if sort == "messages_desc":
        rows.sort(key=lambda r: r.get("message_count") or 0, reverse=True)
    elif sort == "messages_asc":
        rows.sort(key=lambda r: r.get("message_count") or 0)
    elif sort == "name":
        rows.sort(key=lambda r: (r.get("full_name") or "").casefold())

    return {"members": rows[:200], "total": total}


async def _user_info(chat_id: int, user_id: int) -> dict:
    """Полная карточка пользователя для панели (админ — по любому, участник —
    по себе): сообщения, активность, место в топе, роль, награды, репутация."""
    stats = await db.get_message_stats(chat_id, user_id)
    breakdown = await db.get_activity_breakdown(chat_id, user_id)
    known = await db.get_known_user(chat_id, user_id)
    role = await db.get_user_role(chat_id, user_id)
    return {
        "user_id": user_id,
        "name": (known.get("full_name") if known else None) or str(user_id),
        "username": known.get("username") if known else None,
        "nickname": await db.get_nickname(chat_id, user_id),
        "messages": int(stats["message_count"]) if stats else 0,
        "first_seen": str(stats["first_seen_at"]) if stats and stats.get("first_seen_at") else None,
        "last_active": str(stats["last_message_at"]) if stats and stats.get("last_message_at") else None,
        "last_24h": breakdown.get("last_24h_count", 0),
        "today": breakdown.get("today_count", 0),
        "week": breakdown.get("week_count", 0),
        "month": breakdown.get("month_count", 0),
        "rank": await db.get_message_rank(chat_id, user_id) if stats else None,
        "role": role["name"] if role else None,
        "rewards": await db.count_rewards(chat_id, user_id),
        "warns": await db.count_warns(chat_id, user_id),
        "reputation": await db.get_reputation(chat_id, user_id),
    }


@app.get("/api/user-info")
async def api_user_info(chat_id: int, user_id: int, user: PanelUser = Depends(auth.require_user)):
    return await _user_info(chat_id, user_id)


# ---------------------------------------------------------------------------
# Роли чата (таблица chat_roles) — именные роли участников, которые занимают и
# бронируют из бота. Это НЕ уровни прав: те живут в roles.py и в /api/roles,
# и путь у них поэтому разный — сущности разные, слово общее.
#
# Панель их только показывает. Занимают, выдают и освобождают роли по-прежнему
# в чате, где это часть игры.
# ---------------------------------------------------------------------------

CHAT_ROLES_MAX_LIMIT = 200
ROLE_RESERVE_TIMEOUT_HOURS_DEFAULT = 72  # тот же дефолт, что у бота


def _role_person(row: dict, prefix: str) -> Optional[dict]:
    """Человек из строки поиска ролей: держатель (holder_) или забронировавший
    (reserved_). None, если роль свободна — фронтенд рисует это иначе, поэтому
    пустой словарь тут был бы враньём."""
    user_id = row.get(f"{prefix}_user_id")
    if not user_id:
        return None
    return {
        "user_id": user_id,
        "full_name": row.get(f"{prefix}_full_name"),
        "username": row.get(f"{prefix}_username"),
    }


@app.get("/api/chat-roles")
async def api_chat_roles(
    chat_id: int,
    q: str = "",
    status: str = "",
    category: str = "",
    limit: int = 100,
    offset: int = 0,
    user: PanelUser = Depends(auth.require_user),
):
    if status and status not in db.ROLE_SEARCH_STATUSES:
        raise HTTPException(400, "Неизвестный статус роли")

    limit = max(1, min(limit, CHAT_ROLES_MAX_LIMIT))
    rows, total = await db.search_chat_roles(
        chat_id,
        q=q or None,
        status=status or None,
        category=category or None,
        limit=limit,
        offset=max(0, offset),
    )

    # Срок брони считаем по той же настройке, по которой её гасит бот
    # (settings.role_reserve_timeout_hours): свой срок панель показывала бы
    # уверенно и неправильно.
    settings = await db.fetch_settings() or {}
    raw_hours = settings.get("role_reserve_timeout_hours")
    try:
        timeout_hours = int(raw_hours) if raw_hours is not None else ROLE_RESERVE_TIMEOUT_HOURS_DEFAULT
    except (TypeError, ValueError):
        timeout_hours = ROLE_RESERVE_TIMEOUT_HOURS_DEFAULT

    out = []
    for row in rows:
        reserved_at = row.get("reserved_at")
        out.append({
            "id": row["id"],
            "name": row["name"],
            "category": row.get("category"),
            "status": row["status"],
            "approved": bool(row.get("approved")),
            "holder": _role_person(row, "holder"),
            "reserved_by": _role_person(row, "reserved"),
            "reserved_at": reserved_at.isoformat() if reserved_at else None,
            "reserve_expires_at": (
                (reserved_at + timedelta(hours=timeout_hours)).isoformat() if reserved_at else None
            ),
        })

    return {
        "roles": out,
        "total": total,
        "counts": await db.count_chat_roles_by_status(chat_id),
        "categories": await db.list_role_categories(chat_id),
        "reserve_timeout_hours": timeout_hours,
    }


class RoleDecisionBody(BaseModel):
    chat_id: int
    approve: bool


@app.post("/api/chat-roles/{role_id}/decision")
async def api_chat_role_decision(
    role_id: int, body: RoleDecisionBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Принять или отклонить заявку на новую роль.

    Права те же, что у остальной модерации в панели. Решение обязательно
    доезжает обратно в чат: бот отправлял карточку с кнопками, и её надо
    закрыть — иначе второй администратор нажмёт «Принять» по уже обработанной
    заявке и получит невнятную ошибку.
    """
    auth.verify_csrf(request)
    bot = get_bot()

    role = await db.get_role(body.chat_id, role_id)
    if role is None:
        raise HTTPException(404, "Заявка не найдена")
    if role.get("approved"):
        raise HTTPException(409, "Заявка уже обработана")

    proposer = role.get("proposed_by")
    name = role.get("name") or str(role_id)
    reserved_note = ""

    if body.approve:
        approved = await db.approve_role_proposal(body.chat_id, role_id)
        if approved is None:
            raise HTTPException(409, "Заявка уже обработана")
        # Автор ещё не в группе — держим роль за ним, как это делает бот:
        # иначе одобренную по его заявке роль займёт первый желающий.
        if proposer and not await _is_chat_member(bot, body.chat_id, proposer):
            if await db.reserve_role(body.chat_id, role_id, proposer):
                reserved_note = " (забронирована за автором — он ещё не в группе)"
        await db.add_log(
            "role_approve", chat_id=body.chat_id, actor_id=user.id, details=name,
        )
        decision_line = f"\n\n✅ Принято ({user.username}, через панель){reserved_note}"
        notice = f"✅ Ваша заявка на роль «{html.escape(name)}» одобрена."
    else:
        if not await db.reject_role_proposal(body.chat_id, role_id):
            raise HTTPException(409, "Заявка уже обработана")
        await db.add_log(
            "role_reject", chat_id=body.chat_id, actor_id=user.id, details=name,
        )
        decision_line = f"\n\n❌ Отклонено ({user.username}, через панель)"
        notice = f"❌ Ваша заявка на роль «{html.escape(name)}» отклонена."

    # Карточка в чате: дописываем решение и убираем кнопки. Ошибка здесь не
    # отменяет решение — сообщение могли удалить руками, а заявка уже закрыта.
    message_chat_id = role.get("proposal_chat_id")
    message_id = role.get("proposal_message_id")
    if message_chat_id and message_id:
        try:
            await bot.edit_message_text(
                chat_id=message_chat_id,
                message_id=message_id,
                text=f"📝 Заявка на роль «{html.escape(name)}».{decision_line}",
                reply_markup=None,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Не удалось обновить карточку заявки на роль %s", role_id, exc_info=True
            )

    if proposer:
        try:
            await bot.send_message(proposer, notice)
        except Exception:
            pass  # закрытая личка — не повод отменять решение

    return {"ok": True, "approved": body.approve, "reserved": bool(reserved_note)}


ROLE_NAME_MAX = 64  # столько же, сколько в колонке chat_roles.name


class RoleCreateBody(BaseModel):
    chat_id: int
    name: str
    category: Optional[str] = None


@app.post("/api/chat-roles")
async def api_chat_role_create(
    body: RoleCreateBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    """Добавить роль в список — то же, что «роль добавить» в чате.

    Роль появляется сразу, без модерации: её добавил администратор, одобрять
    нечего и некому.
    """
    auth.verify_csrf(request)
    name = (body.name or "").strip()
    category = (body.category or "").strip() or None

    if not name:
        raise HTTPException(400, "Укажите название роли")
    # Длину проверяем здесь, а не полагаемся на обрезку в базе: молча урезанное
    # название потом не совпадёт с тем, что человек вводил, и он будет искать
    # роль, которой нет.
    if len(name) > ROLE_NAME_MAX:
        raise HTTPException(400, f"Название длиннее {ROLE_NAME_MAX} символов")
    if category and len(category) > ROLE_NAME_MAX:
        raise HTTPException(400, f"Категория длиннее {ROLE_NAME_MAX} символов")

    # proposed_by остаётся пустым: это Telegram-ID, по которому бот пишет
    # автору заявки, а у роли из панели такого автора нет. ID учётки панели
    # означал бы сообщение случайному человеку в Telegram.
    role_id = await db.propose_role(
        body.chat_id, name, category, proposed_by=None, auto_approved=True,
    )
    if role_id is None:
        raise HTTPException(409, "Роль с таким названием уже есть в списке")

    await db.add_log("role_add", chat_id=body.chat_id, actor_id=user.id, details=name)
    return {"ok": True, "id": role_id, "name": name}


class RoleRenameBody(BaseModel):
    chat_id: int
    name: str
    category: Optional[str] = None


@app.patch("/api/chat-roles/{role_id}")
async def api_chat_role_rename(
    role_id: int, body: RoleRenameBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Переименовать роль и/или сменить категорию. Держатель и бронь
    сохраняются — иначе исправление опечатки стоило бы человеку роли."""
    auth.verify_csrf(request)
    name = (body.name or "").strip()
    category = (body.category or "").strip() or None

    if not name:
        raise HTTPException(400, "Укажите название роли")
    if len(name) > ROLE_NAME_MAX:
        raise HTTPException(400, f"Название длиннее {ROLE_NAME_MAX} символов")
    if category and len(category) > ROLE_NAME_MAX:
        raise HTTPException(400, f"Категория длиннее {ROLE_NAME_MAX} символов")

    role = await db.get_role(body.chat_id, role_id)
    if role is None:
        raise HTTPException(404, "Роль не найдена")
    if not await db.rename_role(body.chat_id, role_id, name, category):
        raise HTTPException(409, "Роль с таким названием уже есть в списке")

    await db.add_log(
        "role_rename", chat_id=body.chat_id, actor_id=user.id,
        details=f"{role.get('name')} → {name}",
    )
    return {"ok": True, "name": name}


class RoleDeleteBody(BaseModel):
    chat_id: int


@app.delete("/api/chat-roles/{role_id}")
async def api_chat_role_delete(
    role_id: int, body: RoleDeleteBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Удалить роль. Только свободную — как и в чате: иначе человек лишится
    роли, не узнав об этом. Занятую сначала освобождают кнопкой рядом."""
    auth.verify_csrf(request)
    role = await db.get_role(body.chat_id, role_id)
    if role is None:
        raise HTTPException(404, "Роль не найдена")
    if role.get("status") != "free":
        raise HTTPException(409, "Роль занята или забронирована — сначала освободите её")

    await db.delete_role(body.chat_id, role_id)
    await db.add_log(
        "role_delete", chat_id=body.chat_id, actor_id=user.id, details=role.get("name"),
    )
    return {"ok": True, "name": role.get("name")}


class RoleAssignBody(BaseModel):
    chat_id: int
    user_id: int


class RoleReleaseBody(BaseModel):
    chat_id: int


@app.post("/api/chat-roles/{role_id}/assign")
async def api_chat_role_assign(
    role_id: int, body: RoleAssignBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Закрепить роль за участником — то же, что «роль отдать» в чате.

    Если человека сейчас нет в группе, держателем его сделать нельзя: роль
    бронируется за ним, как при одобрении заявки. Прежнего держателя роль
    теряет — это принудительное назначение, и в боте оно ведёт себя так же.
    """
    auth.verify_csrf(request)
    bot = get_bot()

    role = await db.get_role(body.chat_id, role_id)
    if role is None:
        raise HTTPException(404, "Роль не найдена")
    if not role.get("approved"):
        raise HTTPException(409, "Заявка ещё не одобрена — держателя у такой роли быть не может")

    name = role.get("name") or str(role_id)
    in_chat = await _is_chat_member(bot, body.chat_id, body.user_id)
    if in_chat:
        await db.force_set_role(body.chat_id, role_id, body.user_id)
        notice = f"🎭 Вам выдана роль «{html.escape(name)}»."
    else:
        await db.force_reserve_role(body.chat_id, role_id, body.user_id)
        notice = (
            f"🎭 Роль «{html.escape(name)}» забронирована за вами — "
            "она станет вашей, когда вы вступите в чат."
        )

    await db.add_log(
        "role_force_give", chat_id=body.chat_id, actor_id=user.id,
        target_id=body.user_id, details=name,
    )
    try:
        await bot.send_message(body.user_id, notice)
    except Exception:
        pass  # закрытая личка — не повод отменять выдачу

    return {"ok": True, "reserved": not in_chat, "name": name}


@app.post("/api/chat-roles/{role_id}/release")
async def api_chat_role_release(
    role_id: int, body: RoleReleaseBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Освободить роль — то же, что «роль снять» в чате."""
    auth.verify_csrf(request)
    bot = get_bot()

    role = await db.get_role(body.chat_id, role_id)
    if role is None:
        raise HTTPException(404, "Роль не найдена")
    if role.get("status") == "free":
        raise HTTPException(409, "Роль и так свободна")

    name = role.get("name") or str(role_id)
    # Кому сообщить: у занятой роли это держатель, у забронированной — тот, за
    # кем бронь. release_role снимает и то, и другое.
    affected = role.get("holder_user_id") or role.get("reserved_user_id")
    await db.release_role(body.chat_id, role_id)
    await db.add_log(
        "role_force_take", chat_id=body.chat_id, actor_id=user.id,
        target_id=affected, details=name,
    )
    if affected:
        try:
            await bot.send_message(affected, f"🎭 Роль «{html.escape(name)}» больше не закреплена за вами.")
        except Exception:
            pass

    return {"ok": True, "name": name}


async def _is_chat_member(bot, chat_id: int, user_id: int) -> bool:
    """Состоит ли человек в чате. Любая ошибка — считаем, что нет: так роль
    забронируется за ним, и это безопаснее, чем отдать её другому."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return getattr(member, "status", None) not in (None, "left", "kicked")


# ---------------------------------------------------------------------------
# Фильтр слов
#
# Сообщения с этими словами бот удаляет (по целому слову, админы освобождены —
# см. word_filter.py и MessageCounterMiddleware). Список общий для бота. После
# правки поднимаем тот же флаг перечитки, что и для РП/себяшек, — бот держит
# список в памяти и должен узнать об изменении без перезапуска.
# ---------------------------------------------------------------------------

WORD_FILTER_MAX = 128  # длина колонки word


@app.get("/api/word-filter")
async def api_word_filter(user: PanelUser = Depends(auth.require_user)):
    return {"words": await db.list_filter_words()}


class WordFilterBody(BaseModel):
    word: str


@app.post("/api/word-filter")
async def api_word_filter_add(
    body: WordFilterBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    # Храним и матчим в нижнем регистре: фильтр регистронезависимый, и «Спам»
    # с «спам» не должны заводить два разных правила.
    word = (body.word or "").strip().casefold()
    if not word:
        raise HTTPException(400, "Слово не может быть пустым")
    if len(word) > WORD_FILTER_MAX:
        raise HTTPException(400, f"Слово длиннее {WORD_FILTER_MAX} символов")
    if not await db.add_filter_word(word):
        raise HTTPException(409, "Это слово уже в фильтре")
    await db.add_log("word_filter_added", actor_id=user.id, details=word)
    await _signal_action_reload()
    return {"ok": True, "word": word}


@app.delete("/api/word-filter/{word}")
async def api_word_filter_delete(
    word: str, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if not await db.delete_filter_word((word or "").strip().casefold()):
        raise HTTPException(404, "Слово не найдено")
    await db.add_log("word_filter_deleted", actor_id=user.id, details=word)
    await _signal_action_reload()
    return {"ok": True}


# ---------------------------------------------------------------------------
# РП-действия и себяшки
#
# Оба набора устроены одинаково: action_key → упорядоченный список фраз, каждое
# действие можно включить или выключить целиком. У РП вдобавок есть синонимы
# (слово → action_key). Эндпоинты общие, вид выбирается в пути (kind).
#
# Бот держит эти наборы в памяти (RP_ACTIONS/SELF_ACTIONS) и сам, будучи другим
# процессом, о правке в панели не узнаёт. Поэтому после КАЖДОЙ изменяющей
# операции панель поднимает флаг перечитки в bot_data — бот его опрашивает и
# перечитывает кэши (см. panel_action_reload_loop в bot.py).
# ---------------------------------------------------------------------------

# Потолок автоочистки команд — тот же, что в боте (CMD_CLEANUP_MAX_MINUTES):
# Telegram не позволяет боту удалять сообщения старше 48 часов.
CMD_CLEANUP_MAX_MINUTES = 48 * 60

ACTION_PHRASE_MAX = 512  # длина колонки phrase
ACTION_KEY_MAX = 64      # длина колонки action_key
PANEL_ACTION_RELOAD_KEY = db.PANEL_RELOAD_KEY

# Вид набора → функции db. Синонимы есть только у РП.
ACTION_SETS = {
    "rp": {
        "list_rows": "list_rp_actions_rows",
        "add_phrase": "add_rp_action_phrase",
        "update_phrase": "update_rp_action_phrase",
        "delete_phrase": "delete_rp_action_phrase",
        "set_active": "set_rp_action_key_active",
        "list_synonyms": "list_rp_action_synonyms",
        "add_synonym": "add_rp_action_synonym",
        "delete_synonym": "delete_rp_action_synonym",
    },
    "self": {
        "list_rows": "list_self_actions_rows",
        "add_phrase": "add_self_action_phrase",
        "update_phrase": "update_self_action_phrase",
        "delete_phrase": "delete_self_action_phrase",
        "set_active": "set_self_action_key_active",
        # синонимов у себяшек нет
    },
}


def _action_set(kind: str) -> dict:
    spec = ACTION_SETS.get(kind)
    if spec is None:
        raise HTTPException(404, "Неизвестный набор действий")
    return spec


def _db_call(spec: dict, op: str):
    name = spec.get(op)
    if not name:
        # операция не поддерживается этим видом (например, синонимы у себяшек)
        raise HTTPException(404, "Операция недоступна для этого набора")
    return getattr(db, name)


async def _signal_action_reload() -> None:
    """Поднять флаг, по которому бот перечитает РП/себяшки и настройки.

    Сам хелпер живёт в db: его нужен и chat_settings_api, а тот импортировать
    app.py не может — app.py импортирует его самого, вышел бы цикл."""
    await db.signal_panel_reload()


# --- Дерево команд (зеркало COMMAND_REGISTRY бота в БД) ---------------------
# Значение по умолчанию для автоочистки, если настройку ни разу не трогали.
# Дублирует DEFAULT_CMD_CLEANUP_MINUTES из бота: панель не может импортировать
# bot.py (другой процесс, другие зависимости), а показывать «по умолчанию — ?»
# на экране, где настраивают именно сроки, бессмысленно.
DEFAULT_CMD_CLEANUP_MINUTES = 15


async def _cleanup_default_minutes() -> int:
    """Общий срок очистки из настроек — то, по чему живут команды без своего."""
    row = await db.fetch_settings()
    raw = (row or {}).get("command_cleanup_minutes")
    if raw is None:
        return DEFAULT_CMD_CLEANUP_MINUTES
    try:
        return max(0, min(int(raw), CMD_CLEANUP_MAX_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_CMD_CLEANUP_MINUTES


@app.get("/api/command-tree")
async def api_command_tree(user: PanelUser = Depends(auth.require_user)):
    reg = await db.list_command_registry()
    overrides = await db.list_command_levels()
    names_row = await db.get_data("command_level_names")
    level_names = json.loads(names_row["data_value"]) if names_row else {}
    order_row = await db.get_data("command_category_order")
    cat_order = json.loads(order_row["data_value"]) if order_row else []
    cleanup = await db.list_command_cleanup()
    by_cat: dict = {}
    for r in reg:
        eff = overrides.get(r["command_key"], r["default_level"])
        by_cat.setdefault(r["category"], []).append({
            "key": r["command_key"],
            "phrase": r["phrase"],
            "default_level": r["default_level"],
            "level": eff,
            "overridable": bool(r["overridable"]),
            "overridden": r["command_key"] in overrides,
            # Свой срок автоочистки. null — команда живёт по общему сроку из
            # настроек (его показывает cleanup_default). cleanup_targetable —
            # умеет ли бот отличить эту команду по тексту сообщения; если нет,
            # поле показывать нельзя: настройка сохранилась бы и не работала.
            "cleanup_minutes": cleanup.get(r["command_key"]),
            "cleanup_targetable": bool(r.get("cleanup_targetable", True)),
        })
    ordered = [c for c in cat_order if c in by_cat] + [c for c in by_cat if c not in cat_order]
    categories = [{"category": c, "commands": by_cat[c]} for c in ordered]
    return {"categories": categories, "level_names": level_names,
            "total": len(reg), "can_edit": user.is_owner,
            "cleanup_default": await _cleanup_default_minutes(),
            "cleanup_max": CMD_CLEANUP_MAX_MINUTES}


class CmdLevelBody(BaseModel):
    command_key: str
    level: Optional[int] = None  # None — сбросить к уровню по умолчанию


@app.post("/api/command-tree/level")
async def api_command_tree_set_level(
    body: CmdLevelBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    reg = {r["command_key"]: r for r in await db.list_command_registry()}
    entry = reg.get(body.command_key)
    if not entry:
        raise HTTPException(404, "Команда не найдена.")
    if not entry["overridable"]:
        raise HTTPException(403, "Уровень этой команды зашит в логику прав и не меняется.")
    if body.level is None:
        await db.reset_command_level(body.command_key)
        result = {"ok": True, "level": entry["default_level"], "overridden": False}
    else:
        if body.level not in (0, 1, 2, 3):
            raise HTTPException(400, "Уровень должен быть 0–3.")
        await db.set_command_level(body.command_key, body.level, updated_by=user.id)
        result = {"ok": True, "level": body.level, "overridden": True}
    await _signal_action_reload()  # бот перечитает права команд без перезапуска
    return result


class CmdCleanupBody(BaseModel):
    command_key: str
    minutes: Optional[int] = None  # None — вернуть команду на общий срок


@app.post("/api/command-tree/cleanup")
async def api_command_tree_set_cleanup(
    body: CmdCleanupBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    """Свой срок автоочистки для одной команды.

    Работает только в чате жалоб (там же, где и общая автоочистка), и только
    для сообщений, которые бот опознал как эту команду по её фразе-триггеру.
    0 — не убирать эту команду вовсе.
    """
    auth.verify_csrf(request)
    reg = {r["command_key"]: r for r in await db.list_command_registry()}
    entry = reg.get(body.command_key)
    if entry is None:
        raise HTTPException(404, "Команда не найдена.")
    if not entry.get("cleanup_targetable", True):
        raise HTTPException(
            409,
            "Эту команду бот не отличает в чате от соседней с такой же "
            "фразой — свой срок очистки ей задать нельзя.",
        )
    if body.minutes is None:
        await db.reset_command_cleanup(body.command_key)
        await db.add_log("cmd_cleanup_reset", actor_id=user.id, details=body.command_key)
        result = {"ok": True, "cleanup_minutes": None}
    else:
        if not 0 <= body.minutes <= CMD_CLEANUP_MAX_MINUTES:
            raise HTTPException(
                400,
                f"Срок должен быть от 0 до {CMD_CLEANUP_MAX_MINUTES} мин.: "
                "сообщения старше 48 часов Telegram удалять не даёт.",
            )
        await db.set_command_cleanup(body.command_key, body.minutes, updated_by=user.id)
        await db.add_log(
            "cmd_cleanup_set", actor_id=user.id,
            details=f"{body.command_key} -> {body.minutes} мин.",
        )
        result = {"ok": True, "cleanup_minutes": body.minutes}
    await _signal_action_reload()  # бот перечитает сроки без перезапуска
    return result


# --- Случайные события чата: выключить/включить целиком ---------------------
# Ключ и значение обязаны совпадать с тем, что пишет сам бот по «+события» /
# «-события» (bot._events_off_key): это одна и та же настройка, просто с двумя
# входами. Сигнал перечитки не нужен — бот смотрит в базу на каждой проверке.
def _events_off_key(chat_id: int) -> str:
    return f"chat_events_off:{chat_id}"


@app.get("/api/chat-events")
async def api_chat_events(chat_id: int, user: PanelUser = Depends(auth.require_user)):
    row = await db.get_data(_events_off_key(chat_id))
    return {"chat_id": chat_id, "enabled": row is None}


class ChatEventsBody(BaseModel):
    chat_id: int
    enabled: bool


@app.post("/api/chat-events")
async def api_chat_events_set(
    body: ChatEventsBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    if body.enabled:
        await db.delete_data(_events_off_key(body.chat_id))
    else:
        await db.set_data(_events_off_key(body.chat_id), "1", updated_by=user.id)
    await db.add_log(
        "chat_events_toggle", chat_id=body.chat_id, actor_id=user.id,
        details="вкл" if body.enabled else "выкл",
    )
    return {"ok": True, "enabled": body.enabled}


# --- Биржа: график курса и настройки волатильности -------------------------
# Читает и пишет только персонал (require_user = owner/admin): курс акций —
# это денежная масса чата, участнику здесь делать нечего.
STOCK_PERIODS = {"24h": 1, "7d": 7, "30d": 30}
STOCK_CHANGE_LIMIT = 100.0     # ±100% за шаг — дальше это уже не биржа, а рулетка
STOCK_DIVIDEND_LIMIT = 100.0   # 100% от вложенного в сутки


@app.get("/api/stock")
async def api_stock(
    chat_id: int, period: str = "7d", user: PanelUser = Depends(auth.require_user),
):
    days = STOCK_PERIODS.get(period)
    if days is None:
        raise HTTPException(400, "Период должен быть 24h, 7d или 30d.")
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    settings = await db.get_stock_settings(chat_id)
    history = await db.list_stock_price_history(chat_id, since)
    price = await db.get_stock_price(chat_id)
    points = [
        {
            "t": row["created_at"].isoformat(),
            "price": float(row["price"]),
            "change": float(row["change_percent"]) if row["change_percent"] is not None else None,
            "source": row["source"],
        }
        for row in history
    ]
    # Дотягиваем линию до «сейчас»: курс держится ровно до следующего
    # изменения, так что горизонтальный хвост — не выдумка, а факт. Заодно
    # у чата с единственной точкой (свежая затравка) появляется вторая, и
    # график рисуется вместо заглушки «точек пока мало».
    if points and points[-1]["t"] != now.isoformat():
        points.append({"t": now.isoformat(), "price": price, "change": None, "source": "now"})
    return {
        "price": price,
        "period": period,
        "points": points,
        "settings": {
            "min_change_percent": float(settings["min_change_percent"]),
            "max_change_percent": float(settings["max_change_percent"]),
            "dividend_percent": float(settings["dividend_percent"]),
        },
    }


class StockSettingsBody(BaseModel):
    chat_id: int
    min_change_percent: float
    max_change_percent: float
    dividend_percent: float


@app.post("/api/stock/settings")
async def api_stock_settings(
    body: StockSettingsBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    lo, hi, div = body.min_change_percent, body.max_change_percent, body.dividend_percent
    for value, name in ((lo, "падение"), (hi, "рост")):
        if not -STOCK_CHANGE_LIMIT <= value <= STOCK_CHANGE_LIMIT:
            raise HTTPException(400, f"Максимальное {name} должно быть в пределах ±{STOCK_CHANGE_LIMIT:.0f}%.")
    if lo > hi:
        raise HTTPException(400, "Нижняя граница не может быть выше верхней.")
    if not 0 <= div <= STOCK_DIVIDEND_LIMIT:
        raise HTTPException(400, f"Дивиденды должны быть в пределах 0…{STOCK_DIVIDEND_LIMIT:.0f}%.")
    await db.set_stock_settings(
        body.chat_id, min_change_percent=lo, max_change_percent=hi, dividend_percent=div,
    )
    await db.add_log(
        "stock_settings_set", chat_id=body.chat_id, actor_id=user.id,
        details=f"{lo:+.2f}%..{hi:+.2f}%, дивиденды {div:.2f}%",
    )
    return {"ok": True}


# --- Пороги наград (степени 1-8 → минимальный уровень доступа) -------------
REWARD_DEGREES = tuple(range(1, 9))
REWARD_LEVELS = (roles.LEVEL_MEMBER, roles.LEVEL_MODERATOR, roles.LEVEL_ADMIN, roles.LEVEL_SENIOR, roles.OWNER_LEVEL)


@app.get("/api/reward-levels")
async def api_reward_levels(user: PanelUser = Depends(auth.require_user)):
    overrides = await db.list_reward_degree_levels()
    role_map = await roles.load()
    degrees = [
        {
            "degree": degree,
            "emoji": roles.REWARD_DEGREE_EMOJI[degree],
            "level": overrides.get(degree, roles.default_reward_degree_level(degree)),
            "overridden": degree in overrides,
        }
        for degree in REWARD_DEGREES
    ]
    return {
        "degrees": degrees,
        "level_names": {str(level): role_map.name_of(level) for level in REWARD_LEVELS},
        "can_edit": user.is_owner,
    }


class RewardLevelBody(BaseModel):
    degree: int
    level: Optional[int] = None  # None — сбросить к уровню по умолчанию


@app.post("/api/reward-levels/level")
async def api_reward_levels_set_level(
    body: RewardLevelBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    if body.degree not in REWARD_DEGREES:
        raise HTTPException(400, "Степень должна быть от 1 до 8.")

    if body.level is None:
        await db.reset_reward_degree_level(body.degree)
        await db.add_log("reward_degree_level_reset", actor_id=user.id, details=str(body.degree))
        result = {"ok": True, "level": roles.default_reward_degree_level(body.degree), "overridden": False}
    else:
        if body.level not in REWARD_LEVELS:
            raise HTTPException(400, "Недопустимый уровень.")
        await db.set_reward_degree_level(body.degree, body.level, updated_by=user.id)
        await db.add_log(
            "reward_degree_level_set", actor_id=user.id, details=f"{body.degree} -> {body.level}",
        )
        result = {"ok": True, "level": body.level, "overridden": True}

    await _signal_action_reload()
    return result


@app.get("/api/action-sets/{kind}")
async def api_action_set(kind: str, user: PanelUser = Depends(auth.require_user)):
    spec = _action_set(kind)
    rows = await _db_call(spec, "list_rows")()

    # Группируем плоские строки в {key, active, phrases:[...]}, сохраняя порядок
    # появления ключей (rows уже отсортированы по action_key, sort_order).
    actions: dict[str, dict] = {}
    for row in rows:
        key = row["action_key"]
        entry = actions.setdefault(key, {"key": key, "active": True, "phrases": []})
        # Действие активно, если активна хоть одна его строка: set_active
        # переключает все строки разом, так что они всегда согласованы.
        entry["active"] = bool(row.get("is_active"))
        entry["phrases"].append({"id": row["id"], "phrase": row["phrase"]})

    synonyms = {}
    if "list_synonyms" in spec:
        synonyms = await _db_call(spec, "list_synonyms")()

    return {"actions": list(actions.values()), "synonyms": synonyms}


# --- «Предложить действие» ---------------------------------------------------
_PROPOSE_KINDS = ("propose", "agree", "decline")


async def _propose_manage_level() -> int:
    overrides = await db.list_command_levels()
    return overrides.get("propose_manage", roles.LEVEL_SENIOR)


async def _can_edit_propose(user: PanelUser) -> bool:
    if user.is_owner:
        return True
    if user.tg_user_id is None:
        return False
    role_map = await roles.load()
    return role_map.level_of(user.tg_user_id) >= await _propose_manage_level()


async def require_propose_edit(user: PanelUser = Depends(auth.require_user)) -> PanelUser:
    if not await _can_edit_propose(user):
        raise HTTPException(403, "Недостаточно прав для правки действий.")
    return user


@app.get("/api/propose-actions")
async def api_propose_actions(user: PanelUser = Depends(auth.require_user)):
    action_rows = await db.list_propose_actions_rows()
    phrase_rows = await db.list_propose_phrases_rows()
    synonyms = await db.list_propose_action_synonyms()
    synonyms_by_action: dict[str, list[str]] = {}
    for synonym, key in synonyms.items():
        synonyms_by_action.setdefault(key, []).append(synonym)

    actions: dict[str, dict] = {}
    for r in action_rows:
        actions[r["action_key"]] = {
            "key": r["action_key"], "active": bool(r["is_active"]),
            "cooldown_seconds": r["cooldown_seconds"], "timeout_seconds": r["timeout_seconds"],
            "phrases": {kind: [] for kind in _PROPOSE_KINDS},
            "synonyms": synonyms_by_action.get(r["action_key"], []),
        }
    for p in phrase_rows:
        entry = actions.get(p["action_key"])
        if entry is not None:
            entry["phrases"][p["kind"]].append({"id": p["id"], "phrase": p["phrase"]})

    return {"actions": list(actions.values()), "can_edit": await _can_edit_propose(user)}


class ProposePhraseBody(BaseModel):
    action_key: str
    kind: str
    phrase: str


@app.post("/api/propose-actions/phrases")
async def api_propose_add_phrase(
    body: ProposePhraseBody, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if body.kind not in _PROPOSE_KINDS:
        raise HTTPException(400, "Вид фразы должен быть propose/agree/decline.")
    action_key = body.action_key.strip().casefold()
    phrase = body.phrase.strip()
    if not action_key or len(action_key) > 64:
        raise HTTPException(400, "Некорректный ключ действия.")
    if not phrase or len(phrase) > 512:
        raise HTTPException(400, "Некорректная фраза.")
    new_id = await db.add_propose_phrase(action_key, body.kind, phrase)
    await db.add_log("propose_phrase_added", actor_id=user.id, details=f"{action_key}/{body.kind}: {phrase}")
    await _signal_action_reload()
    return {"ok": True, "id": new_id}


class ProposePhraseUpdateBody(BaseModel):
    phrase: str


@app.put("/api/propose-actions/phrases/{phrase_id}")
async def api_propose_update_phrase(
    phrase_id: int, body: ProposePhraseUpdateBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    phrase = body.phrase.strip()
    if not phrase or len(phrase) > 512:
        raise HTTPException(400, "Некорректная фраза.")
    if not await db.update_propose_phrase(phrase_id, phrase):
        raise HTTPException(404, "Фраза не найдена.")
    await db.add_log("propose_phrase_updated", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/propose-actions/phrases/{phrase_id}")
async def api_propose_delete_phrase(
    phrase_id: int, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.delete_propose_phrase(phrase_id):
        raise HTTPException(404, "Фраза не найдена.")
    await db.add_log("propose_phrase_deleted", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


class ProposeSynonymBody(BaseModel):
    synonym: str
    action_key: str


@app.post("/api/propose-actions/synonyms")
async def api_propose_add_synonym(
    body: ProposeSynonymBody, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    synonym = body.synonym.strip().casefold()
    action_key = body.action_key.strip().casefold()
    if not synonym or not action_key or len(synonym) > 64:
        raise HTTPException(400, "Некорректный синоним или ключ.")
    await db.add_propose_action_synonym(synonym, action_key)
    await db.add_log("propose_synonym_added", actor_id=user.id, details=f"{synonym} -> {action_key}")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/propose-actions/synonyms/{synonym}")
async def api_propose_delete_synonym(
    synonym: str, request: Request, user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.delete_propose_action_synonym(synonym):
        raise HTTPException(404, "Синоним не найден.")
    await db.add_log("propose_synonym_deleted", actor_id=user.id, details=synonym)
    await _signal_action_reload()
    return {"ok": True}


class ProposeActiveBody(BaseModel):
    active: bool


@app.post("/api/propose-actions/{action_key}/active")
async def api_propose_set_active(
    action_key: str, body: ProposeActiveBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not await db.set_propose_action_active(action_key, body.active):
        raise HTTPException(404, "Действие не найдено.")
    await db.add_log("propose_action_toggled", actor_id=user.id, details=f"{action_key}: {body.active}")
    await _signal_action_reload()
    return {"ok": True}


class ProposeSettingsBody(BaseModel):
    cooldown_seconds: int
    timeout_seconds: int


@app.post("/api/propose-actions/{action_key}/settings")
async def api_propose_set_settings(
    action_key: str, body: ProposeSettingsBody, request: Request,
    user: PanelUser = Depends(require_propose_edit),
):
    auth.verify_csrf(request)
    if not (0 < body.cooldown_seconds <= 86400) or not (0 < body.timeout_seconds <= 86400):
        raise HTTPException(400, "Кулдаун и таймаут должны быть от 1 до 86400 секунд.")
    if not await db.set_propose_action_settings(action_key, body.cooldown_seconds, body.timeout_seconds):
        raise HTTPException(404, "Действие не найдено.")
    await db.add_log(
        "propose_settings_set", actor_id=user.id,
        details=f"{action_key}: cooldown={body.cooldown_seconds} timeout={body.timeout_seconds}",
    )
    await _signal_action_reload()
    return {"ok": True}


@app.get("/api/member/capabilities")
async def api_member_capabilities(user: PanelUser = Depends(auth.require_member)):
    """Read-only обзор для участника: что умеет бот — активные РП-действия и
    себяшки (с фразами) плюс синонимы РП. Никаких id/правок: участник только
    смотрит."""
    async def _payload(kind: str) -> dict:
        spec = _action_set(kind)
        rows = await _db_call(spec, "list_rows")()
        grouped: dict[str, dict] = {}
        for row in rows:
            key = row["action_key"]
            entry = grouped.setdefault(key, {"key": key, "active": True, "phrases": []})
            entry["active"] = bool(row.get("is_active"))
            entry["phrases"].append(row["phrase"])
        active = [a for a in grouped.values() if a["active"]]
        synonyms = {}
        if "list_synonyms" in spec:
            synonyms = await _db_call(spec, "list_synonyms")()
        return {"actions": active, "synonyms": synonyms}

    return {
        "name": user.display_name,
        "rp": await _payload("rp"),
        "self": await _payload("self"),
    }


# ---------------------------------------------------------------------------
# Участник: свой брак и отношения (просмотр + развод/разрыв + предложение).
# ВСЁ — только за себя (tg_user_id из сессии) и только в чате, где бот его видел.
# Партнёр подтверждает предложение в самом чате: панель шлёт сообщение своим
# Bot-инстансом с теми же callback'ами, что и обычная команда «Брак», а клик по
# кнопке обрабатывает процесс бота (accept_marriage / decline_marriage).
# ---------------------------------------------------------------------------
async def _member_display(chat_id: int, user_id: int) -> str:
    row = await db.get_known_user(chat_id, user_id)
    if not row:
        return str(user_id)
    return row.get("full_name") or (f"@{row['username']}" if row.get("username") else str(user_id))


async def _require_member_in_chat(user: PanelUser, chat_id: int) -> None:
    """Кабинет работает ТОЛЬКО в рабочем чате.

    Раньше здесь стояло одно «бот видел вас в этом чате», и этого хватало:
    любой чат из истории открывал игровые экраны, а деньги и данные уходили
    под чужой chat_id. Заметить это можно было только по расхождению цифр в
    чате и на сайте.

    Какой чат рабочий, знает chats.py — здесь только проверка.
    """
    if not user.tg_user_id:
        raise HTTPException(400, "Аккаунт не привязан к Telegram")
    рабочий = await chats_mod.work_chat_id()
    if рабочий is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан — скажите «жалобы сюда» в чате")
    if chat_id != рабочий:
        raise HTTPException(403, "Кабинет работает только в основном чате")
    if not await db.get_known_user(chat_id, user.tg_user_id):
        raise HTTPException(403, "Бот не видел вас в этом чате")


class MemberChatBody(BaseModel):
    chat_id: int


class MemberProposeBody(BaseModel):
    chat_id: int
    target_id: int


@app.get("/api/member/chats")
async def api_member_chats(user: PanelUser = Depends(auth.require_member)):
    """Чаты, где работает кабинет. Их ровно один — рабочий.

    Раньше отдавались все чаты, где бота когда-либо видели вместе с человеком,
    и вкладки предлагали выбрать любой. Выбор был бессмысленным (кабинет
    пускает только рабочий) и вредным: человек выбирал чат, где бот давно не
    работает, и получал отказ вместо экрана.
    """
    рабочий = await chats_mod.work_chat_id()
    if рабочий is None:
        return {"chats": []}
    ids = [рабочий] if await db.get_known_user(рабочий, user.tg_user_id) else []
    out = []
    for chat_id in ids:
        title = str(chat_id)
        try:
            chat = await get_bot().get_chat(chat_id)
            title = chat.title or chat.full_name or str(chat_id)
        except Exception:
            title = f"{chat_id}"
        out.append({"chat_id": chat_id, "title": title})
    return {"chats": out}


@app.get("/api/member/relationship")
async def api_member_relationship(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    uid = user.tg_user_id
    marriage = await db.get_marriage(chat_id, uid)
    marriage_out = None
    if marriage:
        marriage_out = {
            "partner_id": marriage["partner_id"],
            "partner_name": await _member_display(chat_id, marriage["partner_id"]),
            "married_at": str(marriage["married_at"]) if marriage.get("married_at") else None,
        }
    pair = await db.get_rel2_pair(chat_id, uid)
    rel_out = None
    if pair:
        bonus_available, bonus_wait = _bonus_state(pair.get("last_bonus_at"))
        rel_out = {
            "partner_id": pair["partner_id"],
            "partner_name": await _member_display(chat_id, pair["partner_id"]),
            "sparks": pair["sparks"],
            "level": pair["level_index"],
            "level_name": await db.get_rel2_level_name(pair["level_index"]),
            "contraception": bool(pair["contraception"]),
            "bonus_available": bonus_available,
            "bonus_wait": bonus_wait,
        }
    card = await db.get_profile_card(chat_id, uid)
    return {
        "marriage": marriage_out,
        "relationship": rel_out,
        "gender": (card.get("gender") if card else None),
        # Можно вернуть в течение 72 ч, если недавно расторгли и сейчас свободны.
        "can_restore_marriage": marriage_out is None and bool(await db.get_recent_dissolution("marriage", chat_id, uid)),
        "can_restore_rel": rel_out is None and bool(await db.get_recent_dissolution("rel2", chat_id, uid)),
    }


MEMBER_GENDERS = {"м", "ж", "др"}
BONUS_COOLDOWN_HOURS = 12  # как в relationships_v2 («отн бонус» раз в 12 ч)


def _bonus_state(last_bonus_at):
    """(доступен ли бонус, текст ожидания). Логика та же, что у бота."""
    if not last_bonus_at:
        return True, None
    elapsed = (datetime.utcnow() - last_bonus_at).total_seconds()
    remaining = BONUS_COOLDOWN_HOURS * 3600 - elapsed
    if remaining <= 0:
        return True, None
    hours, minutes = int(remaining) // 3600, (int(remaining) % 3600) // 60
    return False, (f"{hours} ч {minutes} мин" if hours else f"{minutes} мин")


def _daily_bonus_amount(level: int, premium: bool) -> int:
    amount = 100 + level * 20
    return round(amount * 1.2) if premium else amount


async def _level_from_sparks(sparks: int) -> int:
    level = 1
    for lvl, _name, threshold in await db.list_rel2_levels():
        if sparks >= threshold:
            level = lvl
    return level


@app.post("/api/member/farm-bonus")
async def api_member_farm_bonus(
    body: MemberChatBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    """Забрать ежедневный бонус искр (раз в 12 ч) — «фарм» для своей пары.
    Повторяет логику relationships_v2._grant_rel2_bonus (баланс + уровень)."""
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    available, wait = _bonus_state(pair.get("last_bonus_at"))
    if not available:
        raise HTTPException(429, f"Бонус уже забирали. Следующий через {wait}.")
    amount = _daily_bonus_amount(pair["level_index"], pair["premium"])
    new_balance = await db.adjust_rel2_sparks(pair["id"], amount, "bonus")
    await db.set_rel2_last_bonus_at(pair["id"])
    if new_balance is not None:
        new_level = await _level_from_sparks(new_balance)
        if new_level != pair["level_index"]:
            await db.set_rel2_level(pair["id"], new_level)
    return {"ok": True, "amount": amount, "balance": new_balance}


# ---------------------------------------------------------------------------
# РП-действия отношений — «фарм искр» по уровням пары. Зеркало RP_ACTIONS из
# relationships_v2.py: панель не может импортировать модуль (он тянет aiogram
# на уровне модуля). Выполнить действие = начислить искры и поставить кулдаун,
# ровно как «отн сделать <название/номер>» в боте.
# ---------------------------------------------------------------------------

RP_ACTION_COOLDOWN_SCOPE = "rp_action"

# Второй, урезанный список тех же действий когда-то лежал прямо здесь и молча
# затирал каталог выше: числа в нём совпадали, а «verb» и «phrases» — те, что
# и делают объявление в чате человеческим («сделал(а) комплимент» вместо
# «сделать комплимент», плюс фраза-цитата), — терялись. Каталог должен быть
# один, и он выше по файлу.


def _rp_action_reward(action: dict, premium: bool) -> int:
    return round(action["reward"] * 1.25) if premium else action["reward"]


def _rp_action_cooldown_minutes(action: dict, premium: bool) -> float:
    return action["cooldown_minutes"] * 0.70 if premium else action["cooldown_minutes"]


def _format_rp_cooldown(minutes: float) -> str:
    total = max(0, round(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"


@app.get("/api/member/rp-actions")
async def api_member_rp_actions(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    """Каталог фарм-действий для своей пары: доступность по уровню и кулдауну."""
    await _require_member_in_chat(user, chat_id)
    pair = await db.get_rel2_pair(chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    level, premium = pair["level_index"], pair["premium"]
    now = datetime.utcnow()
    actions = []
    for action in RP_ACTIONS:
        locked = level < action["level"]
        on_cooldown, wait = False, None
        if not locked:
            last_at = await db.get_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])
            cd = _rp_action_cooldown_minutes(action, premium)
            if last_at:
                elapsed = (now - last_at).total_seconds() / 60
                if elapsed < cd:
                    on_cooldown = True
                    wait = _format_rp_cooldown(cd - elapsed)
        actions.append({
            "key": action["key"],
            "name": action["name"],
            "level": action["level"],
            "reward": _rp_action_reward(action, premium),
            "cooldown": _format_rp_cooldown(_rp_action_cooldown_minutes(action, premium)),
            "locked": locked,
            "on_cooldown": on_cooldown,
            "wait": wait,
            "available": not locked and not on_cooldown,
        })
    return {"level": level, "actions": actions}


class MemberRpActionBody(BaseModel):
    chat_id: int
    key: str
    quiet: bool = False


@app.post("/api/member/rp-action")
async def api_member_do_rp_action(
    body: MemberRpActionBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    """Выполнить фарм-действие — начислить искры и поставить кулдаун.
    Повторяет relationships_v2.cmd_rel2_do_action (уровень + кулдаун + апы)."""
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    action = RP_ACTIONS_BY_KEY.get(body.key)
    if not action:
        raise HTTPException(404, "Неизвестное действие")
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    if pair["level_index"] < action["level"]:
        raise HTTPException(
            403, f"«{action['name']}» открывается на уровне {action['level']} (у вас {pair['level_index']})."
        )
    last_at = await db.get_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])
    cd = _rp_action_cooldown_minutes(action, pair["premium"])
    if last_at:
        elapsed = (datetime.utcnow() - last_at).total_seconds() / 60
        if elapsed < cd:
            raise HTTPException(429, f"«{action['name']}» ещё восстанавливается: осталось {_format_rp_cooldown(cd - elapsed)}.")
    reward = _rp_action_reward(action, pair["premium"])
    new_balance = await db.adjust_rel2_sparks(pair["id"], reward, "rp_action")
    await db.set_rel2_cooldown(RP_ACTION_COOLDOWN_SCOPE, pair["id"], action["key"])
    new_level = pair["level_index"]
    if new_balance is not None:
        new_level = await _level_from_sparks(new_balance)
        if new_level != pair["level_index"]:
            await db.set_rel2_level(pair["id"], new_level)
    level_name = await db.get_rel2_level_name(new_level)

    # Действие сделано через сайт — отражаем его в чате, будто участник написал
    # «отн сделать <…>» сам (иначе фарм с сайта невидим для остальных в чате).
    # Best-effort: начисление уже прошло, ошибка отправки его не откатывает.
    # quiet=True — участник явно попросил не публиковать действие в чат.
    if not body.quiet:
        try:
            actor_link = await _member_display_link(body.chat_id, user.tg_user_id)
            target_link = await _member_display_link(body.chat_id, pair["partner_id"])

            verb = action.get("verb") or action["name"].lower()
            phrases = action.get("phrases") or []
            quote_part = f" «{html.escape(random.choice(phrases))}»" if phrases else ""

            text = (
                f"☺️ • {actor_link} {verb}{quote_part} своей половинке {target_link}\n"
                f"🔥 • Искры +{reward}\n"
                f"🕙 • Следующие действия будут доступны через "
                f"{_format_rp_cooldown(_rp_action_cooldown_minutes(action, pair['premium']))}"
            )
            if new_balance is not None and new_level > pair["level_index"]:
                text += f"\n🆙 Новый уровень: <b>{new_level} ({html.escape(level_name or '')})</b>!"
            await get_bot().send_message(body.chat_id, text)
        except Exception:
            pass  # бот не в чате / без прав / имя не разрешилось — искры начислены
    return {
        "ok": True,
        "amount": reward,
        "balance": new_balance,
        "level": new_level,
        "level_name": level_name,
    }


# ---------------------------------------------------------------------------
# Кланы участника. Система кланов живёт в боте/БД (create/join/leave, роли
# leader/deputy/member, казна, звание/девиз, войны). Здесь — управление с сайта
# поверх готовых db-функций. Войны и казну пока не выносим.
# ---------------------------------------------------------------------------
class ClanChatBody(BaseModel):
    chat_id: int


class ClanCreateBody(BaseModel):
    chat_id: int
    name: str
    description: Optional[str] = None


class ClanJoinBody(BaseModel):
    chat_id: int
    clan_id: int


class ClanEditBody(BaseModel):
    chat_id: int
    name: Optional[str] = None
    description: Optional[str] = None


class ClanTextBody(BaseModel):
    chat_id: int
    value: Optional[str] = None  # None/пусто — снять звание/девиз


class ClanMemberBody(BaseModel):
    chat_id: int
    user_id: int


class ClanDeputyBody(BaseModel):
    chat_id: int
    user_id: int
    on: bool


async def _clan_manage(chat_id: int, uid: int, need_leader: bool = False) -> dict:
    """Возвращает клан пользователя (с полем role) и проверяет права: по
    умолчанию нужны лидер/зам, need_leader=True — только лидер."""
    clan = await db.get_user_clan(chat_id, uid)
    if not clan:
        raise HTTPException(404, "Вы не состоите в клане.")
    if need_leader and clan["role"] != "leader":
        raise HTTPException(403, "Только лидер клана может это сделать.")
    if not need_leader and clan["role"] not in ("leader", "deputy"):
        raise HTTPException(403, "Только лидер или зам клана может это сделать.")
    return clan


@app.get("/api/member/clans")
async def api_member_clans(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    uid = user.tg_user_id
    my = await db.get_user_clan(chat_id, uid)
    my_out = None
    if my:
        rows, _total = await db.list_clan_members(chat_id, my["id"], 100, 0)
        members = [
            {"user_id": m["user_id"], "role": m["role"],
            "name": await _member_display(chat_id, m["user_id"])}
            for m in rows
        ]
        my_out = {
            "id": my["id"], "name": my["name"], "description": my.get("description"),
            "title": my.get("title"), "motto": my.get("motto"),
            "coins": my["coins"], "war_points": my["war_points"],
            "wars_won": my["wars_won"], "wars_lost": my["wars_lost"], "wars_drawn": my["wars_drawn"],
            "role": my["role"], "members": members,
        }
    rows, total = await db.list_clans(chat_id, 100, 0)
    clans = [
        {"id": c["id"], "name": c["name"], "members_count": c["members_count"],
        "coins": c["coins"], "war_points": c["war_points"], "title": c.get("title"),
        "leader_name": await _member_display(chat_id, c["leader_id"])}
        for c in rows
    ]
    return {"my": my_out, "clans": clans, "total": total}


@app.post("/api/member/clan/create")
async def api_member_clan_create(body: ClanCreateBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    uid = user.tg_user_id
    if await db.get_user_clan(body.chat_id, uid):
        raise HTTPException(409, "Вы уже состоите в клане — сначала выйдите из текущего.")
    name = (body.name or "").strip()
    if not 1 <= len(name) <= 64:
        raise HTTPException(400, "Название клана: 1–64 символа.")
    desc = (body.description or "").strip() or None
    clan_id = await db.create_clan(body.chat_id, uid, name, desc)
    return {"ok": True, "clan_id": clan_id}


@app.post("/api/member/clan/join")
async def api_member_clan_join(body: ClanJoinBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    uid = user.tg_user_id
    if not await db.get_clan(body.chat_id, body.clan_id):
        raise HTTPException(404, "Клан не найден.")
    current = await db.get_user_clan(body.chat_id, uid)
    if current and current["role"] == "leader":
        raise HTTPException(409, "Вы лидер своего клана — сначала передайте его или удалите.")
    await db.join_clan(body.chat_id, body.clan_id, uid)
    return {"ok": True}


@app.post("/api/member/clan/leave")
async def api_member_clan_leave(body: ClanChatBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    uid = user.tg_user_id
    clan = await db.get_user_clan(body.chat_id, uid)
    if not clan:
        raise HTTPException(404, "Вы не состоите в клане.")
    if clan["role"] == "leader":
        raise HTTPException(409, "Лидер не может выйти — передайте клан другому или удалите его.")
    await db.leave_clan(body.chat_id, uid)
    return {"ok": True}


@app.post("/api/member/clan/edit")
async def api_member_clan_edit(body: ClanEditBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id)  # лидер/зам
    name = body.name.strip() if body.name is not None else None
    if name is not None and not 1 <= len(name) <= 64:
        raise HTTPException(400, "Название клана: 1–64 символа.")
    desc = body.description.strip() if body.description is not None else None
    await db.update_clan(body.chat_id, clan["id"], name=name, description=desc)
    return {"ok": True}


@app.post("/api/member/clan/title")
async def api_member_clan_title(body: ClanTextBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id)
    val = (body.value or "").strip() or None
    if val and len(val) > 100:
        raise HTTPException(400, "Звание: до 100 символов.")
    await db.set_clan_title(body.chat_id, clan["id"], val)
    return {"ok": True, "title": val}


@app.post("/api/member/clan/motto")
async def api_member_clan_motto(body: ClanTextBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id)
    val = (body.value or "").strip() or None
    if val and len(val) > 100:
        raise HTTPException(400, "Девиз: до 100 символов.")
    await db.set_clan_motto(body.chat_id, clan["id"], val)
    return {"ok": True, "motto": val}


@app.post("/api/member/clan/kick")
async def api_member_clan_kick(body: ClanMemberBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    uid = user.tg_user_id
    clan = await _clan_manage(body.chat_id, uid)  # лидер/зам
    if body.user_id == uid:
        raise HTTPException(400, "Себя исключить нельзя.")
    target = await db.get_user_clan(body.chat_id, body.user_id)
    if not target or target["id"] != clan["id"]:
        raise HTTPException(404, "Этот участник не в вашем клане.")
    if target["role"] == "leader":
        raise HTTPException(403, "Лидера исключить нельзя.")
    if target["role"] == "deputy" and clan["role"] != "leader":
        raise HTTPException(403, "Зама может исключить только лидер.")
    await db.kick_clan_member(body.chat_id, clan["id"], body.user_id)
    return {"ok": True}


@app.post("/api/member/clan/deputy")
async def api_member_clan_deputy(body: ClanDeputyBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id, need_leader=True)
    if body.user_id == user.tg_user_id:
        raise HTTPException(400, "Себя назначить нельзя.")
    target = await db.get_user_clan(body.chat_id, body.user_id)
    if not target or target["id"] != clan["id"]:
        raise HTTPException(404, "Этот участник не в вашем клане.")
    await db.set_clan_member_role(body.chat_id, clan["id"], body.user_id, "deputy" if body.on else "member")
    return {"ok": True}


@app.post("/api/member/clan/transfer")
async def api_member_clan_transfer(body: ClanMemberBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id, need_leader=True)
    if body.user_id == user.tg_user_id:
        raise HTTPException(400, "Вы уже лидер.")
    target = await db.get_user_clan(body.chat_id, body.user_id)
    if not target or target["id"] != clan["id"]:
        raise HTTPException(404, "Этот участник не в вашем клане.")
    await db.transfer_clan_leadership(body.chat_id, clan["id"], body.user_id)
    return {"ok": True}


@app.post("/api/member/clan/delete")
async def api_member_clan_delete(body: ClanChatBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    clan = await _clan_manage(body.chat_id, user.tg_user_id, need_leader=True)
    await db.delete_clan(body.chat_id, clan["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# «Семья» пары: дом, питомцы, дети. Просмотр состояния + безопасные действия
# (активный питомец, переименование). Покупки/рост/действия с экономикой искр
# остаются в боте — их логика завязана на каталоги relationships_v2.
# ---------------------------------------------------------------------------
HOUSE_NAMES = {
    "hut": "🛖 Хижина", "cottage": "🏡 Загородный дом", "townhouse": "🏘 Таунхаус",
    "villa": "🏖 Вилла", "mansion": "🏰 Особняк", "castle": "🏯 Замок",
}


@app.get("/api/member/family")
async def api_member_family(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    pair = await db.get_rel2_pair(chat_id, user.tg_user_id)
    if not pair:
        return {"pair": False, "house": None, "pets": [], "children": []}
    house_row = await db.get_rel2_house(pair["id"])
    house = None
    if house_row:
        rooms = await db.list_rel2_house_rooms(house_row["id"])
        upgrades = await db.list_rel2_house_upgrades(house_row["id"])
        house = {
            "name": HOUSE_NAMES.get(house_row["house_key"], house_row["house_key"]),
            "status": house_row["status"],
            "rooms": [{"key": r["room_key"], "level": r["level"]} for r in rooms],
            "upgrades": [{"key": u["upgrade_key"], "level": u["level"]} for u in upgrades],
        }
    pets = [{
        "id": p["id"], "name": p["name"], "species": p["species"], "rarity": p["rarity"],
        "level": p["level_index"], "hp": p["hp"], "mood": p["mood"], "active": bool(p["is_active"]),
    } for p in await db.list_rel2_pets(pair["id"])]
    children = [{
        "id": c["id"], "name": c["name"], "level": c["level_index"], "mood": c["mood"],
        "health": c["health"], "intellect": c["intellect"], "charisma": c["charisma"],
        "section": c.get("section_key"),
    } for c in await db.list_rel2_children(pair["id"])]
    return {"pair": True, "sparks": pair["sparks"], "house": house, "pets": pets, "children": children}


class MemberPetBody(BaseModel):
    chat_id: int
    pet_id: int
    name: Optional[str] = None


class MemberChildBody(BaseModel):
    chat_id: int
    child_id: int
    name: str


async def _member_pet_of_pair(chat_id: int, uid: int, pet_id: int) -> dict:
    pair = await db.get_rel2_pair(chat_id, uid)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях.")
    pet = await db.get_rel2_pet(pet_id)
    if not pet or pet["pair_id"] != pair["id"]:
        raise HTTPException(404, "Питомец не найден у вашей пары.")
    return pet


@app.post("/api/member/pet/active")
async def api_member_pet_active(body: MemberPetBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pet = await _member_pet_of_pair(body.chat_id, user.tg_user_id, body.pet_id)
    await db.set_rel2_active_pet(pet["pair_id"], pet["id"])
    return {"ok": True}


@app.post("/api/member/pet/rename")
async def api_member_pet_rename(body: MemberPetBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pet = await _member_pet_of_pair(body.chat_id, user.tg_user_id, body.pet_id)
    name = (body.name or "").strip()
    if not 1 <= len(name) <= 32:
        raise HTTPException(400, "Имя питомца: 1–32 символа.")
    await db.rename_rel2_pet(pet["id"], name)
    return {"ok": True, "name": name}


@app.post("/api/member/child/rename")
async def api_member_child_rename(body: MemberChildBody, request: Request, user: PanelUser = Depends(auth.require_member)):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях.")
    child = await db.get_rel2_child(body.child_id)
    if not child or child["pair_id"] != pair["id"]:
        raise HTTPException(404, "Ребёнок не найден у вашей пары.")
    name = (body.name or "").strip()
    if not 1 <= len(name) <= 32:
        raise HTTPException(400, "Имя ребёнка: 1–32 символа.")
    await db.rename_rel2_child(child["id"], name)
    return {"ok": True, "name": name}


class MemberContraceptionBody(BaseModel):
    chat_id: int
    on: bool


@app.post("/api/member/rel-contraception")
async def api_member_contraception(
    body: MemberContraceptionBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    await db.set_rel2_contraception(pair["id"], body.on)
    return {"ok": True, "contraception": body.on}


class MemberGenderBody(BaseModel):
    chat_id: int
    gender: str


@app.post("/api/member/gender")
async def api_member_gender(
    body: MemberGenderBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    gender = (body.gender or "").strip().casefold()
    if gender not in MEMBER_GENDERS:
        raise HTTPException(400, "Пол: м / ж / др")
    try:
        await db.set_gender(body.chat_id, user.tg_user_id, gender)
    except Exception as exc:  # noqa: BLE001 — surface the real DB error, not a bare 500
        logger.exception("api_member_gender: set_gender упал")
        raise HTTPException(500, f"Не удалось сохранить пол: {type(exc).__name__}: {exc}")
    return {"ok": True, "gender": gender}


@app.get("/api/member/info")
async def api_member_info(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    """Своя карточка участника (сообщения/активность/роль/награды) в этом чате."""
    await _require_member_in_chat(user, chat_id)
    return await _user_info(chat_id, user.tg_user_id)


class MemberSuggestionBody(BaseModel):
    text: str


@app.post("/api/member/suggestion")
async def api_member_suggestion(
    body: MemberSuggestionBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    """Предложение участника уходит в настроенный чат уведомлений."""
    auth.verify_csrf(request)
    suggestion = (body.text or "").strip()
    if not suggestion:
        raise HTTPException(400, "Напишите, что стоит улучшить или добавить")
    if len(suggestion) > 2000:
        raise HTTPException(400, "Максимальная длина — 2000 символов")
    chat_id = await chats_mod.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await _require_member_in_chat(user, chat_id)
    settings = await db.fetch_settings() or {}
    notify_chat_id = settings.get("notify_chat_id")
    if not notify_chat_id:
        raise HTTPException(503, "Чат уведомлений пока не настроен")
    author = await _member_display_link(chat_id, user.tg_user_id)
    try:
        await get_bot().send_message(
            notify_chat_id,
            f"💡 <b>Предложение по улучшению</b>\n\nОт: {author}\n"
            f"Из сайта · чат: <code>{chat_id}</code>\n\n{html.escape(suggestion)}",
            message_thread_id=settings.get("notify_topic_id"),
        )
    except Exception as exc:
        logger.exception("Не удалось отправить предложение с сайта")
        raise HTTPException(502, "Telegram не принял сообщение. Попробуйте позже") from exc
    return {"ok": True}


# --- участник: ник, топ, свои варны/награды, действия отн (жесты) -----------
NICKNAME_MAX = 32
SIMPLE_RP_COOLDOWN_SCOPE = "rp_simple"
SIMPLE_RP_COOLDOWN_MINUTES = 2


async def _member_display_link(chat_id: int, user_id: int) -> str:
    nick = await db.get_nickname(chat_id, user_id)
    if not nick:
        row = await db.get_known_user(chat_id, user_id)
        nick = (row.get("full_name") if row else None) or str(user_id)
    return f'<a href="tg://user?id={user_id}">{html.escape(nick)}</a>'


async def _member_plain_name(chat_id: int, user_id: int) -> str:
    nick = await db.get_nickname(chat_id, user_id)
    if nick:
        return nick
    row = await db.get_known_user(chat_id, user_id)
    return (row.get("full_name") if row else None) or str(user_id)


class MemberNicknameBody(BaseModel):
    chat_id: int
    nickname: Optional[str] = None


@app.post("/api/member/nickname")
async def api_member_nickname(
    body: MemberNicknameBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    nick = (body.nickname or "").strip()
    if len(nick) > NICKNAME_MAX:
        raise HTTPException(400, f"Ник — не длиннее {NICKNAME_MAX} символов")
    if nick:
        await db.set_nickname(body.chat_id, user.tg_user_id, nick)
    else:
        await db.delete_nickname(body.chat_id, user.tg_user_id)  # пусто — снять ник
    return {"ok": True, "nickname": nick or None}


@app.get("/api/member/top")
async def api_member_top(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    rows, total = await db.list_top_messages(chat_id, limit=20)
    top = []
    for i, r in enumerate(rows, 1):
        known = await db.get_known_user(chat_id, r["user_id"])
        top.append({
            "rank": i,
            "name": (known.get("full_name") if known else None) or str(r["user_id"]),
            "messages": int(r["message_count"]),
            "me": r["user_id"] == user.tg_user_id,
        })
    return {"top": top, "total": total, "my_rank": await db.get_message_rank(chat_id, user.tg_user_id)}


@app.get("/api/member/warns")
async def api_member_warns(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    rows = await db.list_warns(chat_id, user.tg_user_id)
    return {"warns": [{
        "reason": w.get("reason"),
        "created_at": str(w["created_at"]) if w.get("created_at") else None,
        "expires_at": str(w["expires_at"]) if w.get("expires_at") else None,
    } for w in rows]}


@app.get("/api/member/rewards")
async def api_member_rewards(chat_id: int, user: PanelUser = Depends(auth.require_member)):
    await _require_member_in_chat(user, chat_id)
    rows = await db.list_rewards(chat_id, user.tg_user_id)
    return {"rewards": [{
        "degree": r["degree"],
        "reason": r.get("reason"),
        "created_at": str(r["created_at"]) if r.get("created_at") else None,
    } for r in rows]}


@app.get("/api/member/gestures")
async def api_member_gestures(user: PanelUser = Depends(auth.require_member)):
    gestures = await db.list_rel2_gestures(active_only=True)
    return {"gestures": [{"key": g["gesture_key"], "name": g["name"]} for g in gestures]}


def _member_gesture_photo(media_folder: str, g1: Optional[str], g2: Optional[str]) -> Optional[str]:
    """Превью жеста для личного кабинета — по тем же правилам, что и в чате.

    Правило подбора и порядок запасных вариантов берём из rp_photos: своя
    копия здесь уже была, тоже теряла направление, и разойтись им было нечем
    — превью показывало бы одно, а бот присылал другое.

    g1 — кто делает жест, g2 — кому.
    """
    return rp_photos.pick_photo_url(media_folder, rp_photos.pairing_for(g1, g2))


class MemberGestureBody(BaseModel):
    chat_id: int
    key: str


@app.post("/api/member/gesture")
async def api_member_gesture(
    body: MemberGestureBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    """Выполнить отн-жест (обнять/поцеловать/…) со своим партнёром — бот пишет
    результат в чат. Логика повторяет cmd_rel2_simple_action бота: счётчик,
    фраза, фото-превью по полу пары (без отката)."""
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    gesture = next(
        (g for g in await db.list_rel2_gestures(active_only=True) if g["gesture_key"] == body.key),
        None,
    )
    if not gesture:
        raise HTTPException(404, "Жест не найден")

    partner_id = pair["partner_id"]
    actor_link = await _member_display_link(body.chat_id, user.tg_user_id)
    target_link = await _member_display_link(body.chat_id, partner_id)
    phrases = [p["phrase"] for p in gesture.get("phrases", [])]
    if phrases:
        phrase = secrets.choice(phrases).format(actor=actor_link, target=target_link)
    else:
        phrase = f"{html.escape(gesture['name'])}: {actor_link} → {target_link}"

    await db.increment_rel2_action_count(pair["id"], body.key)

    actor_card = await db.get_profile_card(body.chat_id, user.tg_user_id)
    partner_card = await db.get_profile_card(body.chat_id, partner_id)
    gender_actor = actor_card.get("gender") if actor_card else None
    gender_partner = partner_card.get("gender") if partner_card else None
    photo_url = relationships_v2._pick_rp_photo_url(gesture["media_folder"], gender_actor, gender_partner)

    if photo_url:
        try:
            await get_bot().send_message(
                body.chat_id,
                phrase,
                link_preview_options=LinkPreviewOptions(
                    url=photo_url,
                    is_disabled=False,
                    prefer_large_media=True,
                    show_above_text=False,
                ),
            )
            return {"ok": True}
        except TelegramBadRequest:
            pass  # битая ссылка — падаем ниже на обычный текст без превью
        except Exception:
            raise HTTPException(502, "Не удалось отправить в чат — бот не в этом чате или без прав.")

    try:
        await get_bot().send_message(body.chat_id, phrase)
    except Exception:
        raise HTTPException(502, "Не удалось отправить в чат — бот не в этом чате или без прав.")
    return {"ok": True}


@app.post("/api/member/divorce")
async def api_member_divorce(
    body: MemberChatBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    marriage = await db.get_marriage(body.chat_id, user.tg_user_id)
    if not marriage:
        raise HTTPException(404, "В этом чате вы ни с кем не в браке")
    # Снимок для отмены в течение 72 ч (см. /api/member/restore).
    await db.snapshot_dissolution("marriage", body.chat_id, user.tg_user_id, marriage["partner_id"], "{}")
    await db.delete_marriage(body.chat_id, user.tg_user_id)
    await db.add_log(
        "marriage_divorced_web", chat_id=body.chat_id,
        actor_id=user.tg_user_id, target_id=marriage["partner_id"],
    )
    me_name = html.escape(await _member_display(body.chat_id, user.tg_user_id))
    partner_name = html.escape(await _member_display(body.chat_id, marriage["partner_id"]))
    try:
        await get_bot().send_message(body.chat_id, f"💔 {me_name} и {partner_name} развелись.")
    except Exception:
        pass  # не в чате / нет прав — развод в базе всё равно состоялся
    return {"ok": True}


@app.post("/api/member/rel-break")
async def api_member_rel_break(
    body: MemberChatBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    pair = await db.get_rel2_pair(body.chat_id, user.tg_user_id)
    if not pair:
        raise HTTPException(404, "В этом чате вы ни с кем не в отношениях")
    raw = await db.get_rel2_pair_row(body.chat_id, user.tg_user_id)
    if raw:  # снимок пары для отмены в течение 72 ч (искры/уровень/дети сохранятся)
        await db.snapshot_dissolution("rel2", body.chat_id, user.tg_user_id, pair["partner_id"], json.dumps(raw, default=str))
    await db.delete_rel2_pair(body.chat_id, user.tg_user_id)
    await db.add_log(
        "relationship2_broken_web", chat_id=body.chat_id,
        actor_id=user.tg_user_id, target_id=pair["partner_id"],
    )
    me_name = html.escape(await _member_display(body.chat_id, user.tg_user_id))
    partner_name = html.escape(await _member_display(body.chat_id, pair["partner_id"]))
    try:
        await get_bot().send_message(body.chat_id, f"💔 {me_name} разрывает отношения с {partner_name}.")
    except Exception:
        pass
    return {"ok": True}


class MemberRestoreBody(BaseModel):
    chat_id: int
    kind: str


@app.post("/api/member/restore")
async def api_member_restore(
    body: MemberRestoreBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    """Вернуть брак/отношения в течение 72 ч после расторжения (если сейчас
    свободны). Восстанавливает и другую сторону — уведомляем чат."""
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    if body.kind not in ("marriage", "rel2"):
        raise HTTPException(400, "Неизвестный тип")
    undo = await db.get_recent_dissolution(body.kind, body.chat_id, user.tg_user_id)
    if not undo:
        raise HTTPException(404, "Нечего восстанавливать (или прошло больше 72 часов)")
    a, b = undo["user_a"], undo["user_b"]
    if body.kind == "marriage":
        if await db.get_marriage(body.chat_id, a) or await db.get_marriage(body.chat_id, b):
            raise HTTPException(409, "Кто-то из вас уже вступил в новый брак")
        if not await db.create_marriage(body.chat_id, a, b):
            raise HTTPException(409, "Не удалось восстановить брак")
        verb = "брак"
    else:
        if not await db.restore_rel2_pair_row(json.loads(undo["payload"])):
            raise HTTPException(409, "Кто-то из вас уже в новых отношениях")
        verb = "отношения"
    await db.consume_dissolution(undo["id"])
    a_name = html.escape(await _member_display(body.chat_id, a))
    b_name = html.escape(await _member_display(body.chat_id, b))
    try:
        await get_bot().send_message(body.chat_id, f"💞 {a_name} и {b_name} восстановили {verb}!")
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/member/chat-members")
async def api_member_chat_members(
    q: str = "", user: PanelUser = Depends(auth.require_member)
):
    # Чат один, и знает его сервер. Раньше он приходил параметром из браузера:
    # заслон это пропускал, потому что смотрел только в member_*_api.py, а этот
    # эндпоинт живёт здесь. Дыры не было (чужой чат всё равно давал 403), но
    # параметр, которым можно ошибиться, — лишний.
    chat_id = await chats_mod.work_chat_id()
    if chat_id is None:
        raise HTTPException(400, "Рабочий чат ещё не привязан")
    await _require_member_in_chat(user, chat_id)
    rows, _total = await db.list_known_users(chat_id, limit=500, offset=0)
    needle = q.casefold().strip()
    out = []
    for r in rows:
        if r["user_id"] == user.tg_user_id:
            continue  # себя не предлагаем
        if needle and (
            needle not in (r.get("full_name") or "").casefold()
            and needle not in (r.get("username") or "").casefold()
            and needle not in str(r["user_id"])
        ):
            continue
        out.append({"user_id": r["user_id"], "full_name": r.get("full_name"), "username": r.get("username")})
    return {"members": out[:50]}


@app.post("/api/member/propose-marriage")
async def api_member_propose_marriage(
    body: MemberProposeBody, request: Request, user: PanelUser = Depends(auth.require_member)
):
    auth.verify_csrf(request)
    await _require_member_in_chat(user, body.chat_id)
    proposer_id = user.tg_user_id
    target_id = body.target_id
    if target_id == proposer_id:
        raise HTTPException(400, "Нельзя сделать предложение самому себе")
    if not await db.get_known_user(body.chat_id, target_id):
        raise HTTPException(404, "Этого человека нет среди участников чата")
    if await db.get_marriage(body.chat_id, proposer_id):
        raise HTTPException(409, "Вы уже состоите в браке в этом чате")
    if await db.get_marriage(body.chat_id, target_id):
        raise HTTPException(409, "Этот человек уже в браке")

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    me_name = html.escape(await _member_display(body.chat_id, proposer_id))
    target_name = html.escape(await _member_display(body.chat_id, target_id))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💍 Принять", callback_data=f"marriage_accept:{proposer_id}:{target_id}"),
        InlineKeyboardButton(text="💔 Отказать", callback_data=f"marriage_decline:{proposer_id}:{target_id}"),
    ]])
    try:
        await get_bot().send_message(
            body.chat_id,
            "💌 <b>Предложение руки и сердца</b>\n\n"
            f"{me_name} предлагает {target_name} вступить в брак! 💍\n\n"
            f"{target_name}, выберите свой ответ:",
            reply_markup=kb,
        )
    except Exception:
        raise HTTPException(502, "Не удалось отправить предложение — бот не в этом чате или без прав.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Управление РП-жестами «отн» (админ): сами жесты, их фразы, слова-триггеры
# (алиасы) и фото. Жесты живут в БД; правки поднимают сигнал перечитки, и бот
# подхватывает их в чатах за секунды. Фото лежат в rp_media/<media_folder>/
# <mf|mm|ff>/ — бот берёт их оттуда (см. relationships_v2._pick_rp_media);
# менять фото сигнал перечитки не требует (бот читает папку на каждое действие).
# ---------------------------------------------------------------------------
# Хранилище картинок и все пути к нему — в общем модуле rp_photos: раньше
# панель писала файлы в <репозиторий>/rp_media (папки на диске нет), бот брал
# ссылки из отдельного словаря, а сами картинки лежали третьим местом. Теперь
# источник один, и разойтись сторонам нечем.
RP_MEDIA_ROOT = rp_photos.MEDIA_ROOT
# Корзины фото у жеста: три пары по полу плюс общая («all» — файлы прямо в
# папке жеста). Общая нужна тем жестам, где картинка одна на всех: заводить
# ради неё три одинаковые подпапки бессмысленно, а с тех пор как бот берёт
# фото ТОЛЬКО из хранилища (внешних ссылок больше нет), такому жесту иначе
# негде взять картинку.
GESTURE_PAIRINGS = rp_photos.STORAGE_PAIRINGS
_GESTURE_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_PHOTO_EXTS = rp_photos.PHOTO_EXTS
GESTURE_PHOTO_MAX_BYTES = 8 * 1024 * 1024


def _gesture_dir(media_folder: str, pairing: str) -> str:
    """Каталог фото жеста для пары; 400, если путь выводит за пределы
    хранилища (media_folder приходит из БД, доверять ему нельзя)."""
    path = rp_photos.pairing_dir(media_folder, pairing)
    if path is None:
        raise HTTPException(400, "Недопустимый путь")
    return path


def _gesture_photos(media_folder: str) -> dict:
    """Имена файлов по парам — для списка жестов в панели."""
    return {p: rp_photos.list_photos(media_folder, p) for p in GESTURE_PAIRINGS}


# ---------------------------------------------------------------------------
# ПУБЛИЧНАЯ отдача картинок-реакций.
#
# Единственная ручка панели без входа — и так и задумано: превью под
# сообщением рисует сам Telegram, его серверы идут по ссылке из
# LinkPreviewOptions, и предъявить куку им нечем. Наружу открыто ровно чтение
# одного файла картинки: имя жеста и пара сверяются с хранилищем, имя файла
# усекается до basename, расширение — только из белого списка, каталог
# наружу не перечисляется.
#
# Кэш — на год и immutable: имена файлов при загрузке генерируются случайно
# (secrets.token_hex), поэтому содержимое по конкретной ссылке никогда не
# меняется, а Telegram и клиенты не ходят за одной картинкой повторно.
# ---------------------------------------------------------------------------
@app.get("/rp/{folder}/{pairing}/{filename}")
async def rp_photo(folder: str, pairing: str, filename: str):
    path = rp_photos.photo_path(folder, pairing, filename)
    if path is None:
        raise HTTPException(404, "Нет такой картинки")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/rel-gestures")
async def api_rel_gestures(user: PanelUser = Depends(auth.require_user)):
    gestures = await db.list_rel2_gestures(active_only=False)
    for g in gestures:
        g["photos"] = _gesture_photos(g["media_folder"])
    return {"gestures": gestures, "pairings": list(GESTURE_PAIRINGS)}


class GestureBody(BaseModel):
    key: str
    name: str


@app.post("/api/rel-gestures")
async def api_rel_gesture_add(body: GestureBody, request: Request, user: PanelUser = Depends(auth.require_user)):
    auth.verify_csrf(request)
    key = (body.key or "").strip().lower()
    name = (body.name or "").strip()
    if not _GESTURE_KEY_RE.match(key):
        raise HTTPException(400, "Ключ: латиница/цифры/подчёркивание, до 32 символов (например wink)")
    if not name:
        raise HTTPException(400, "Укажите название")
    if not await db.add_rel2_gesture(key, name[:64], None, key):
        raise HTTPException(409, "Жест с таким ключом уже есть")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/rel-gestures/{key}")
async def api_rel_gesture_delete(key: str, request: Request, user: PanelUser = Depends(auth.require_user)):
    auth.verify_csrf(request)
    if not await db.delete_rel2_gesture(key):
        raise HTTPException(404, "Жест не найден")
    await _signal_action_reload()
    return {"ok": True}


class GestureActiveBody(BaseModel):
    active: bool


@app.post("/api/rel-gestures/{key}/active")
async def api_rel_gesture_active(
    key: str, body: GestureActiveBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    if not await db.set_rel2_gesture_active(key, body.active):
        raise HTTPException(404, "Жест не найден")
    await _signal_action_reload()
    return {"ok": True}


class GestureReplyBody(BaseModel):
    reply: Optional[str] = None


@app.post("/api/rel-gestures/{key}/reply")
async def api_rel_gesture_reply(
    key: str, body: GestureReplyBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    reply = (body.reply or "").strip()[:255] or None
    if not await db.set_rel2_gesture_reply(key, reply):
        raise HTTPException(404, "Жест не найден")
    await _signal_action_reload()
    return {"ok": True}


class GesturePhraseBody(BaseModel):
    phrase: str


@app.post("/api/rel-gestures/{key}/phrases")
async def api_rel_gesture_add_phrase(
    key: str, body: GesturePhraseBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    phrase = (body.phrase or "").strip()
    if not phrase or len(phrase) > 512:
        raise HTTPException(400, "Фраза: 1–512 символов")
    if await db.add_rel2_gesture_phrase(key, phrase) is None:
        raise HTTPException(404, "Жест не найден")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/rel-gestures/phrases/{phrase_id}")
async def api_rel_gesture_del_phrase(
    phrase_id: int, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    if not await db.delete_rel2_gesture_phrase(phrase_id):
        raise HTTPException(404, "Фраза не найдена")
    await _signal_action_reload()
    return {"ok": True}


class GestureAliasBody(BaseModel):
    alias: str


@app.post("/api/rel-gestures/{key}/aliases")
async def api_rel_gesture_add_alias(
    key: str, body: GestureAliasBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    alias = (body.alias or "").strip().casefold()
    if not alias or len(alias) > 64:
        raise HTTPException(400, "Слово-триггер: 1–64 символа")
    if not await db.add_rel2_gesture_alias(alias, key):
        raise HTTPException(404, "Жест не найден")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/rel-gestures/{key}/aliases/{alias}")
async def api_rel_gesture_del_alias(
    key: str, alias: str, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    await db.delete_rel2_gesture_alias(alias.casefold())
    await _signal_action_reload()
    return {"ok": True}


@app.post("/api/rel-gestures/{key}/photos")
async def api_rel_gesture_upload_photo(
    key: str, request: Request, pairing: str = Form(...), file: UploadFile = File(...),
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if pairing not in GESTURE_PAIRINGS:
        raise HTTPException(400, "Пара: mf / mm / ff / all (общая)")
    gesture = await db.get_rel2_gesture(key)
    if not gesture:
        raise HTTPException(404, "Жест не найден")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _PHOTO_EXTS:
        raise HTTPException(400, "Только изображения: jpg/jpeg/png/webp/gif")
    data = await file.read(GESTURE_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "Пустой файл")
    if len(data) > GESTURE_PHOTO_MAX_BYTES:
        raise HTTPException(400, "Файл больше 8 МБ")
    directory = _gesture_dir(gesture["media_folder"], pairing)
    os.makedirs(directory, exist_ok=True)
    # имя генерируем сами — не доверяем имени от клиента (обход путей, коллизии)
    name = f"{secrets.token_hex(8)}{ext}"
    with open(os.path.join(directory, name), "wb") as fh:
        fh.write(data)
    await db.add_log("gesture_photo_upload", details=f"{user.username}: {key}/{pairing}")
    return {"ok": True, "name": name}


@app.get("/api/rel-gestures/{key}/photos/{pairing}/{filename}")
async def api_rel_gesture_get_photo(
    key: str, pairing: str, filename: str, user: PanelUser = Depends(auth.require_user)
):
    if pairing not in GESTURE_PAIRINGS:
        raise HTTPException(404)
    gesture = await db.get_rel2_gesture(key)
    if not gesture:
        raise HTTPException(404)
    safe = os.path.basename(filename)  # только имя файла, без путей
    if os.path.splitext(safe)[1].lower() not in _PHOTO_EXTS:
        raise HTTPException(404)
    path = os.path.join(_gesture_dir(gesture["media_folder"], pairing), safe)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)


@app.delete("/api/rel-gestures/{key}/photos/{pairing}/{filename}")
async def api_rel_gesture_del_photo(
    key: str, pairing: str, filename: str, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    if pairing not in GESTURE_PAIRINGS:
        raise HTTPException(400)
    gesture = await db.get_rel2_gesture(key)
    if not gesture:
        raise HTTPException(404)
    path = os.path.join(_gesture_dir(gesture["media_folder"], pairing), os.path.basename(filename))
    if os.path.isfile(path):
        os.remove(path)
    return {"ok": True}


class ActionPhraseBody(BaseModel):
    key: str
    phrase: str


def _validate_phrase(key: str, phrase: str) -> tuple[str, str]:
    key = (key or "").strip()
    phrase = (phrase or "").strip()
    if not key:
        raise HTTPException(400, "Укажите действие (ключ)")
    if len(key) > ACTION_KEY_MAX:
        raise HTTPException(400, f"Ключ действия длиннее {ACTION_KEY_MAX} символов")
    if not phrase:
        raise HTTPException(400, "Фраза не может быть пустой")
    if len(phrase) > ACTION_PHRASE_MAX:
        raise HTTPException(400, f"Фраза длиннее {ACTION_PHRASE_MAX} символов")
    return key, phrase


@app.post("/api/action-sets/{kind}/phrases")
async def api_action_add_phrase(
    kind: str, body: ActionPhraseBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Добавить фразу. Если ключа ещё нет — так создаётся новое действие."""
    auth.verify_csrf(request)
    spec = _action_set(kind)
    key, phrase = _validate_phrase(body.key, body.phrase)
    phrase_id = await _db_call(spec, "add_phrase")(key, phrase)
    await db.add_log(f"{kind}_action_phrase_added", actor_id=user.id, details=f"{key}: {phrase}")
    await _signal_action_reload()
    return {"ok": True, "id": phrase_id, "key": key}


class ActionPhraseEditBody(BaseModel):
    phrase: str


@app.patch("/api/action-sets/{kind}/phrases/{phrase_id}")
async def api_action_edit_phrase(
    kind: str, phrase_id: int, body: ActionPhraseEditBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    spec = _action_set(kind)
    phrase = (body.phrase or "").strip()
    if not phrase:
        raise HTTPException(400, "Фраза не может быть пустой")
    if len(phrase) > ACTION_PHRASE_MAX:
        raise HTTPException(400, f"Фраза длиннее {ACTION_PHRASE_MAX} символов")
    if not await _db_call(spec, "update_phrase")(phrase_id, phrase):
        raise HTTPException(404, "Фраза не найдена")
    await db.add_log(f"{kind}_action_phrase_edited", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/action-sets/{kind}/phrases/{phrase_id}")
async def api_action_delete_phrase(
    kind: str, phrase_id: int, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    spec = _action_set(kind)
    if not await _db_call(spec, "delete_phrase")(phrase_id):
        raise HTTPException(404, "Фраза не найдена")
    await db.add_log(f"{kind}_action_phrase_deleted", actor_id=user.id, details=str(phrase_id))
    await _signal_action_reload()
    return {"ok": True}


class ActionActiveBody(BaseModel):
    active: bool


@app.post("/api/action-sets/{kind}/actions/{key}/active")
async def api_action_set_active(
    kind: str, key: str, body: ActionActiveBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    """Включить или выключить действие целиком (все его фразы разом)."""
    auth.verify_csrf(request)
    spec = _action_set(kind)
    changed = await _db_call(spec, "set_active")(key, body.active)
    if not changed:
        raise HTTPException(404, "Такого действия нет")
    await db.add_log(
        f"{kind}_action_{'enabled' if body.active else 'disabled'}",
        actor_id=user.id, details=key,
    )
    await _signal_action_reload()
    return {"ok": True, "active": body.active}


class SynonymBody(BaseModel):
    synonym: str
    key: str


@app.post("/api/action-sets/{kind}/synonyms")
async def api_action_add_synonym(
    kind: str, body: SynonymBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    spec = _action_set(kind)
    add = _db_call(spec, "add_synonym")  # 404, если у вида нет синонимов
    synonym = (body.synonym or "").strip().casefold()
    key = (body.key or "").strip()
    if not synonym or not key:
        raise HTTPException(400, "Нужны и синоним, и действие")
    if len(synonym) > ACTION_KEY_MAX:
        raise HTTPException(400, f"Синоним длиннее {ACTION_KEY_MAX} символов")
    await add(synonym, key)
    await db.add_log(f"{kind}_synonym_added", actor_id=user.id, details=f"{synonym} → {key}")
    await _signal_action_reload()
    return {"ok": True}


@app.delete("/api/action-sets/{kind}/synonyms/{synonym}")
async def api_action_delete_synonym(
    kind: str, synonym: str, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    spec = _action_set(kind)
    delete = _db_call(spec, "delete_synonym")
    if not await delete(synonym.strip().casefold()):
        raise HTTPException(404, "Синоним не найден")
    await db.add_log(f"{kind}_synonym_deleted", actor_id=user.id, details=synonym)
    await _signal_action_reload()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Жалобы
#
# Жалобу можно подать анонимно, и это обещание панель обязана держать: для
# анонимной жалобы reporter_id не уходит с сервера вообще. Спрятать имя только
# в вёрстке недостаточно — id было бы видно в сетевых запросах браузера, то
# есть анонимности бы не было.
# ---------------------------------------------------------------------------

COMPLAINT_STATUSES = {"pending", "accepted", "declined"}


def _person(names: dict, user_id: Optional[int]) -> Optional[dict]:
    row = names.get(user_id) if user_id else None
    if not row:
        return {"user_id": user_id, "full_name": None, "username": None} if user_id else None
    return {
        "user_id": user_id,
        "full_name": row.get("full_name"),
        "username": row.get("username"),
    }


@app.get("/api/complaints")
async def api_complaints(user: PanelUser = Depends(auth.require_user)):
    """Люди, на которых есть жалобы, — с именами и счётчиком нерассмотренных."""
    rows = await db.list_complaint_targets()
    names = await db.get_known_names([row["target_id"] for row in rows])
    return {
        "targets": [
            {
                "target_id": row["target_id"],
                "full_name": (names.get(row["target_id"]) or {}).get("full_name"),
                "username": (names.get(row["target_id"]) or {}).get("username"),
                "total": int(row.get("total") or 0),
                "pending": int(row.get("pending") or 0),
            }
            for row in rows
        ],
        "pending_total": await db.count_pending_complaints(),
    }


@app.get("/api/complaints/{target_id}")
async def api_complaints_for_target(
    target_id: int, user: PanelUser = Depends(auth.require_user),
):
    rows = await db.list_complaints_for_target(target_id)

    # Имена запрашиваем только для НЕанонимных: незачем тянуть из базы то,
    # что нельзя показывать.
    open_reporters = [row["reporter_id"] for row in rows if not row.get("anonymous")]
    names = await db.get_known_names(open_reporters + [target_id])

    out = []
    for row in rows:
        anonymous = bool(row.get("anonymous"))
        out.append({
            "id": row["id"],
            "anonymous": anonymous,
            # Для анонимной жалобы поля reporter_id в ответе нет вовсе.
            "reporter": None if anonymous else _person(names, row.get("reporter_id")),
            "reason": row.get("reason"),
            "status": row.get("status"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        })

    return {"target": _person(names, target_id), "complaints": out}


class ComplaintStatusBody(BaseModel):
    status: str


@app.post("/api/complaints/{complaint_id}/status")
async def api_complaint_status(
    complaint_id: int, body: ComplaintStatusBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if body.status not in COMPLAINT_STATUSES:
        raise HTTPException(400, "Недопустимый статус жалобы")
    complaint = await db.get_complaint(complaint_id)
    if complaint is None:
        raise HTTPException(404, "Жалоба не найдена")

    await db.set_complaint_status(complaint_id, body.status, user.id)
    await db.add_log(
        f"complaint_{body.status}", actor_id=user.id, target_id=complaint.get("target_id"),
    )
    return {"ok": True, "status": body.status}


@app.delete("/api/complaints/{complaint_id}")
async def api_complaint_delete(
    complaint_id: int, request: Request, user: PanelUser = Depends(auth.require_user),
):
    """Удаляет саму жалобу — не человека и не его запись в known_users."""
    auth.verify_csrf(request)
    complaint = await db.get_complaint(complaint_id)
    if complaint is None:
        raise HTTPException(404, "Жалоба не найдена")

    await db.delete_complaint(complaint_id)
    await db.add_log(
        "complaint_deleted", actor_id=user.id, target_id=complaint.get("target_id"),
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Варны
#
# Панель обязана вести себя как бот: на лимите — автобан со сбросом счётчика,
# снятием мута и записью в таблицу банов. Если панель выдаст варн «мимо» этой
# логики, человек наберёт три предупреждения и останется в чате, а модератор
# будет думать, что бан случился.
# ---------------------------------------------------------------------------

WARN_LIMIT_DEFAULT = 3
WARN_DEFAULT_DAYS = 7  # столько же, сколько WARN_DEFAULT_DURATION в bot.py
# warned_by в таблице — Telegram-ID, а у панельной учётки его нет. Пишем 0:
# это отличимо от настоящего человека и никого собой не подменяет.
WARN_PANEL_AUTHOR = 0


async def _warn_limit() -> int:
    settings = await db.fetch_settings() or {}
    raw = settings.get("warn_limit")
    try:
        return int(raw) if raw is not None else WARN_LIMIT_DEFAULT
    except (TypeError, ValueError):
        return WARN_LIMIT_DEFAULT


@app.get("/api/warns")
async def api_warns(chat_id: int, user_id: int, user: PanelUser = Depends(auth.require_user)):
    rows = await db.list_warns(chat_id, user_id)
    return {
        "warns": [
            {
                "id": row.get("id"),
                "reason": row.get("reason"),
                "by_panel": row.get("warned_by") == WARN_PANEL_AUTHOR,
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
            }
            for row in rows
        ],
        "count": len(rows),
        "limit": await _warn_limit(),
    }


class WarnBody(BaseModel):
    chat_id: int
    user_id: int
    days: Optional[int] = None
    reason: Optional[str] = None


@app.post("/api/warns")
async def api_warn_add(
    body: WarnBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    days = body.days if body.days and body.days > 0 else WARN_DEFAULT_DAYS
    if days > 3650:
        raise HTTPException(400, "Срок больше десяти лет — похоже на опечатку")

    expires_at = datetime.utcnow() + timedelta(days=days)
    count = await db.add_warn(
        body.chat_id, body.user_id, WARN_PANEL_AUTHOR, body.reason or None, expires_at,
    )
    await db.add_log(
        "warn", chat_id=body.chat_id, actor_id=user.id,
        target_id=body.user_id, details=body.reason,
    )

    limit = await _warn_limit()
    result = {"ok": True, "count": count, "limit": limit, "banned": False}
    if count < limit:
        return result

    # Лимит достигнут — повторяем поведение бота целиком.
    await db.clear_warns(body.chat_id, body.user_id)
    try:
        await get_bot().ban_chat_member(chat_id=body.chat_id, user_id=body.user_id)
    except Exception as exc:
        # Варн уже выдан и счётчик сброшен, а бан не удался. Молчать нельзя:
        # модератор решит, что человек забанен.
        result["ban_error"] = str(exc)
        return result

    await db.add_ban(body.chat_id, body.user_id, WARN_PANEL_AUTHOR, f"{limit} варна")
    await db.remove_mute(body.chat_id, body.user_id)
    await db.add_log(
        "warn_autoban", chat_id=body.chat_id, actor_id=user.id, target_id=body.user_id,
    )
    result["banned"] = True
    return result


class WarnRemoveBody(BaseModel):
    chat_id: int
    user_id: int


@app.post("/api/warns/remove")
async def api_warn_remove(
    body: WarnRemoveBody, request: Request, user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    if not await db.remove_last_warn(body.chat_id, body.user_id):
        raise HTTPException(409, "У этого участника нет активных варнов")
    await db.add_log(
        "unwarn", chat_id=body.chat_id, actor_id=user.id, target_id=body.user_id,
    )
    return {"ok": True, "count": await db.count_warns(body.chat_id, body.user_id)}


# ---------------------------------------------------------------------------
# Заявки на рест
#
# Рест — согласованное право временно не писать в чат: пока он действует,
# человек не считается неактивным и его не зовут созывом. Заявки приходят
# админам карточкой с кнопками; здесь то же решение принимается из панели, и
# карточка в чате закрывается — как у заявок на роль.
# ---------------------------------------------------------------------------

@app.get("/api/rest-requests")
async def api_rest_requests(chat_id: int, user: PanelUser = Depends(auth.require_user)):
    rows = await db.list_pending_rest_requests(chat_id)
    out = []
    for row in rows:
        requested_at = row.get("requested_at")
        out.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "full_name": row.get("full_name"),
            "username": row.get("username"),
            "duration_seconds": int(row.get("duration_seconds") or 0),
            "reason": row.get("reason"),
            "requested_at": requested_at.isoformat() if requested_at else None,
        })
    return {"requests": out}


class RestDecisionBody(BaseModel):
    approve: bool


@app.post("/api/rest-requests/{request_id}/decision")
async def api_rest_decision(
    request_id: int, body: RestDecisionBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    bot = get_bot()

    row = await db.get_rest_request(request_id)
    if row is None:
        raise HTTPException(404, "Заявка не найдена")
    if row.get("status") != "pending":
        raise HTTPException(409, "Заявка уже обработана")

    if body.approve:
        updated = await db.approve_rest_request(request_id, user.id)
        if updated is None:
            raise HTTPException(409, "Заявка уже обработана")
        expires_at = updated.get("expires_at")
        until = f" до {expires_at.strftime('%d.%m.%Y %H:%M')} UTC" if expires_at else ""
        decision_line = f"\n\n✅ Одобрено ({user.username}, через панель){until}"
        notice = f"✅ Ваша заявка на рест одобрена{until}."
        log_kind = "rest_approved"
    else:
        updated = await db.reject_rest_request(request_id, user.id)
        if updated is None:
            raise HTTPException(409, "Заявка уже обработана")
        decision_line = f"\n\n❌ Отклонено ({user.username}, через панель)"
        notice = "❌ Ваша заявка на рест отклонена."
        log_kind = "rest_rejected"

    await db.add_log(
        log_kind, chat_id=row.get("chat_id"), actor_id=user.id, target_id=row.get("user_id"),
    )

    # Карточка в чате: дописываем решение и убираем кнопки. Ошибка тут решения
    # не отменяет — сообщение могли удалить руками.
    notice_chat = row.get("notice_chat_id")
    notice_message = row.get("notice_message_id")
    if notice_chat and notice_message:
        try:
            await bot.edit_message_text(
                chat_id=notice_chat,
                message_id=notice_message,
                text=f"🌴 Заявка на рест.{decision_line}",
                reply_markup=None,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Не удалось обновить карточку заявки на рест %s", request_id, exc_info=True
            )

    try:
        await bot.send_message(row["user_id"], notice)
    except Exception:
        pass  # закрытая личка не отменяет решение

    return {"ok": True, "approved": body.approve}


# ---------------------------------------------------------------------------
# Лента последних сообщений чата (плашка на вкладке «Написать»)
#
# Пишет ленту сам бот — см. _remember_recent_message в bot.py. Панель только
# читает: сначала /api/messages отдаёт последние N штук, дальше
# /api/messages/stream досылает новые по мере появления.
# ---------------------------------------------------------------------------

MESSAGES_DEFAULT_LIMIT = 10
MESSAGES_MAX_LIMIT = 50
# Как часто поток заглядывает в БД за новыми строками.
STREAM_POLL_SECONDS = 2.0
# Пустое соединение Funnel и прочие прокси рвут по таймауту, поэтому даже в
# молчащем чате шлём комментарий-heartbeat.
STREAM_HEARTBEAT_SECONDS = 15.0
# Через это время поток закрывается сам, а браузер переподключается (EventSource
# делает это без нашего участия, позицию берём из Last-Event-ID). Нужно, чтобы
# соединение, про которое мы почему-то не узнали, что оно мертво, не жило и не
# опрашивало БД до перезапуска панели.
STREAM_MAX_SECONDS = 300.0


def _message_payload(row: dict) -> dict:
    """Строка ленты в том виде, в каком её ждёт фронтенд."""
    return {
        "id": row["id"],
        "message_id": row["message_id"],
        "user_id": row.get("user_id"),
        "full_name": row.get("full_name") or "?",
        "username": row.get("username"),
        "text": row.get("text"),
        "kind": row.get("kind"),
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "role": row.get("role"),
        "role_key": row.get("role_key"),
    }


@app.get("/api/messages")
async def api_messages(
    chat_id: int, limit: int = MESSAGES_DEFAULT_LIMIT,
    user: PanelUser = Depends(auth.require_user),
):
    limit = max(1, min(limit, MESSAGES_MAX_LIMIT))
    rows = await db.list_recent_messages(chat_id, limit=limit)
    (await roles.load()).annotate(rows)
    messages = [_message_payload(r) for r in rows]
    # last_id — с этого места продолжит поток. Ноль означает «лента пуста»:
    # тогда поток отдаст всё, что появится начиная с подключения.
    return {"messages": messages, "last_id": messages[-1]["id"] if messages else 0}


@app.get("/api/messages/stream")
async def api_messages_stream(
    request: Request, chat_id: int, after_id: int = 0,
    user: PanelUser = Depends(auth.require_user),
):
    """SSE-поток новых сообщений чата.

    При обрыве браузер переподключается сам и присылает заголовок
    Last-Event-ID — берём позицию из него, иначе после каждого обрыва поток
    заново присылал бы всё, что было с момента открытия страницы.
    """
    resume = request.headers.get("last-event-id")
    if resume:
        try:
            after_id = int(resume)
        except ValueError:
            pass

    async def events() -> AsyncIterator[bytes]:
        cursor = after_id
        idle = 0.0
        started = time.monotonic()
        # Пауза перед переподключением. По умолчанию браузер ждёт дольше, а
        # раз в STREAM_MAX_SECONDS мы закрываем поток сами — незачем держать
        # плашку «отключённой» несколько секунд на ровном месте.
        yield b"retry: 2000\n\n"
        while True:
            # Клиент ушёл (закрыл вкладку, сменил чат) — прекращаем опрашивать
            # БД, иначе брошенные потоки копились бы до перезапуска панели.
            if await request.is_disconnected():
                return
            if time.monotonic() - started >= STREAM_MAX_SECONDS:
                return
            try:
                rows = await db.list_recent_messages_after(chat_id, cursor, limit=MESSAGES_MAX_LIMIT)
            except Exception:
                logger.exception("Лента сообщений: запрос к БД не удался")
                rows = []

            if rows:
                role_map = await roles.load()
                role_map.annotate(rows)
                for row in rows:
                    cursor = row["id"]
                    payload = json.dumps(_message_payload(row), ensure_ascii=False)
                    yield f"id: {cursor}\ndata: {payload}\n\n".encode("utf-8")
                idle = 0.0
            else:
                idle += STREAM_POLL_SECONDS
                if idle >= STREAM_HEARTBEAT_SECONDS:
                    idle = 0.0
                    yield b": ping\n\n"

            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx и подобные иначе буферизуют поток и он приезжает пачками
            "X-Accel-Buffering": "no",
        },
    )


class SendBody(BaseModel):
    chat_id: int
    text: str
    reply_to: Optional[int] = None
    topic_id: Optional[int] = None


@app.post("/api/send")
async def api_send(
    body: SendBody, request: Request, user: PanelUser = Depends(auth.require_user)
):
    auth.verify_csrf(request)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Пустое сообщение")
    if len(text) > 4096:
        raise HTTPException(400, "Сообщение длиннее 4096 символов")

    try:
        sent = await get_bot().send_message(
            body.chat_id, text,
            reply_to_message_id=body.reply_to,
            message_thread_id=body.topic_id,
        )
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")

    await db.add_log(
        "panel_send", chat_id=body.chat_id, actor_id=None,
        details=f"{user.username}: {text[:200]}",
    )
    return {"ok": True, "message_id": sent.message_id}


@app.post("/api/send_photo")
async def api_send_photo(
    request: Request,
    chat_id: int = Form(...),
    caption: str = Form(""),
    photo: UploadFile = File(...),
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    data = await photo.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Файл больше 10 МБ")
    try:
        await get_bot().send_photo(
            chat_id, BufferedInputFile(data, filename=photo.filename or "photo.jpg"),
            caption=caption[:1024] or None,
        )
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")
    await db.add_log("panel_send_photo", chat_id=chat_id, details=user.username)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Модерация
# ---------------------------------------------------------------------------

class ModerationBody(BaseModel):
    chat_id: int
    user_id: int
    minutes: Optional[int] = None
    reason: str = ""


@app.post("/api/moderation/{action}")
async def api_moderation(
    action: str, body: ModerationBody, request: Request,
    user: PanelUser = Depends(auth.require_user),
):
    auth.verify_csrf(request)
    bot = get_bot()
    from datetime import datetime, timedelta

    until = None
    if body.minutes:
        until = datetime.utcnow() + timedelta(minutes=body.minutes)

    # Мут/бан администратора бот делает через «холд»: сначала снимает права
    # Telegram (иначе ограничить админа нельзя), запоминает их и возвращает
    # при снятии наказания. Панель обязана закрывать холд ровно так же —
    # иначе человек остаётся без прав: при муте на срок их вернёт фоновая
    # задача бота только когда истечёт исходный срок, а при муте «навсегда»
    # не вернёт никогда.
    restored = False

    try:
        if action == "ban":
            await bot.ban_chat_member(body.chat_id, body.user_id, until_date=until)
            await db.add_ban(body.chat_id, body.user_id, 0, body.reason or "из панели")
        elif action == "unban":
            await bot.unban_chat_member(body.chat_id, body.user_id, only_if_banned=True)
            await db.remove_ban(body.chat_id, body.user_id)
            restored = await admin_holds.release_hold_for(bot, body.chat_id, body.user_id, "ban")
        elif action == "kick":
            await bot.ban_chat_member(body.chat_id, body.user_id)
            await bot.unban_chat_member(body.chat_id, body.user_id, only_if_banned=True)
        elif action == "mute":
            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(
                body.chat_id, body.user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        elif action == "unmute":
            from aiogram.types import ChatPermissions
            await bot.restrict_chat_member(
                body.chat_id, body.user_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                ),
            )
            await db.remove_mute(body.chat_id, body.user_id)
            restored = await admin_holds.release_hold_for(bot, body.chat_id, body.user_id, "mute")
        else:
            raise HTTPException(400, "Неизвестное действие")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")

    await db.add_log(
        f"panel_{action}", chat_id=body.chat_id, target_id=body.user_id,
        details=f"{user.username}: {body.reason}"[:200],
    )
    return {"ok": True, "admin_rights_restored": restored}


# ---------------------------------------------------------------------------
# Администраторы Telegram: назначение, снятие, тонкая настройка прав
#
# Не путать с уровнями бота (roles.py): здесь настоящий статус администратора
# чата средствами Telegram — то же, что команды «+тг админ», «-тг админ» и
# «тг права» в чате.
#
# Доступ только у владельца панели: выдача админки — самое опасное действие
# здесь. Админ с can_promote_members раздаёт права дальше уже без нас.
# ---------------------------------------------------------------------------

class TgAdminBody(BaseModel):
    chat_id: int
    user_id: int
    rights: dict[str, bool] = {}
    custom_title: Optional[str] = None


async def _guard_no_active_hold(chat_id: int, user_id: int) -> None:
    """Не даём трогать права, пока на человеке висит холд.

    Холд — это снятые на время мута/бана права со снимком «как было». Если
    сейчас выдать новые, снятие мута всё равно вернёт старый снимок и правки
    молча пропадут."""
    hold = await db.get_admin_hold(chat_id, user_id)
    if hold:
        raise HTTPException(
            409,
            "У участника сняты права на время мута или бана — панель вернёт их сама, "
            "когда наказание снимут. Сначала снимите мут или бан, потом меняйте права.",
        )


def _clean_title(title: Optional[str]) -> Optional[str]:
    title = (title or "").strip()
    if not title:
        return None
    if len(title) > admin_holds.CUSTOM_TITLE_MAX:
        raise HTTPException(
            400, f"Должность длиннее {admin_holds.CUSTOM_TITLE_MAX} символов — Telegram её не примет"
        )
    return title


def _checked_rights(rights: dict) -> dict:
    unknown = set(rights) - admin_holds.TG_RIGHTS_FIELD_SET
    if unknown:
        raise HTTPException(400, f"Неизвестные права: {', '.join(sorted(unknown))}")
    normalized = admin_holds.normalize_rights(rights)
    if not any(normalized.values()):
        # promoteChatMember со всеми False — это ровно тот вызов, которым
        # админа снимают. Молча «назначить никем» было бы худшим исходом:
        # человек в панели видит успех, а в чате ничего не изменилось.
        raise HTTPException(
            400,
            "Отметьте хотя бы одно право: набор без единого права Telegram понимает "
            "как снятие администратора. Чтобы снять — нажмите «Снять админку».",
        )
    return normalized


@app.get("/api/tg_rights")
async def api_tg_rights(user: PanelUser = Depends(auth.require_owner)):
    """Список настраиваемых прав с подписями — для галочек в интерфейсе."""
    return {
        "fields": [{"key": key, "label": label} for key, label in admin_holds.TG_RIGHTS_FIELDS],
        "defaults": admin_holds.DEFAULT_ADMIN_RIGHTS,
        "title_max": admin_holds.CUSTOM_TITLE_MAX,
    }


@app.get("/api/tg_admins")
async def api_tg_admins(chat_id: int, user: PanelUser = Depends(auth.require_owner)):
    """Действующие администраторы чата — прямо из Telegram, а не из нашей БД:
    их могли назначить и мимо бота."""
    try:
        members = await get_bot().get_chat_administrators(chat_id)
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")

    out = []
    for member in members:
        is_creator = getattr(member, "status", "") == "creator"
        out.append({
            "user_id": member.user.id,
            "full_name": member.user.full_name or str(member.user.id),
            "username": member.user.username,
            "is_bot": bool(member.user.is_bot),
            "status": member.status,
            "is_creator": is_creator,
            "custom_title": getattr(member, "custom_title", None),
            "rights": admin_holds.snapshot_admin_rights(member),
            # Создателя чата Telegram менять не даёт — ни нам, ни кому-либо ещё.
            "editable": not is_creator,
        })
    return {"admins": out}


@app.post("/api/tg_admins/promote")
async def api_tg_admin_promote(
    body: TgAdminBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    await _guard_no_active_hold(body.chat_id, body.user_id)
    rights = _checked_rights(body.rights or admin_holds.DEFAULT_ADMIN_RIGHTS)
    title = _clean_title(body.custom_title)
    bot = get_bot()

    try:
        member = await bot.get_chat_member(body.chat_id, body.user_id)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось получить участника: {exc}")
    if member.user.is_bot:
        raise HTTPException(400, "Ботам права администратора через панель не выдаём")
    if getattr(member, "status", "") == "creator":
        raise HTTPException(400, "Это создатель чата — у него и так все права")

    try:
        await admin_holds.promote_with_rights(bot, body.chat_id, body.user_id, rights)
        if title:
            await bot.set_chat_administrator_custom_title(
                chat_id=body.chat_id, user_id=body.user_id, custom_title=title
            )
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")

    await db.add_log(
        "panel_tg_admin_granted", chat_id=body.chat_id, target_id=body.user_id,
        details=f"{user.username}: {title or ''}"[:200],
    )
    return {"ok": True}


@app.post("/api/tg_admins/rights")
async def api_tg_admin_rights(
    body: TgAdminBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    await _guard_no_active_hold(body.chat_id, body.user_id)
    rights = _checked_rights(body.rights)
    title = _clean_title(body.custom_title)
    bot = get_bot()

    try:
        member = await bot.get_chat_member(body.chat_id, body.user_id)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось получить участника: {exc}")
    if getattr(member, "status", "") == "creator":
        raise HTTPException(400, "Права создателя чата изменить нельзя")
    if getattr(member, "status", "") != "administrator":
        raise HTTPException(400, "Этот участник сейчас не администратор — сначала назначьте его")

    try:
        await admin_holds.promote_with_rights(bot, body.chat_id, body.user_id, rights)
        # Должность сбрасывается вместе с правами, поэтому выставляем её заново
        # каждый раз — в том числе пустую, если её убрали.
        await bot.set_chat_administrator_custom_title(
            chat_id=body.chat_id, user_id=body.user_id, custom_title=title or ""
        )
    except Exception as exc:
        raise HTTPException(400, f"Telegram отказал: {exc}")

    await db.add_log(
        "panel_tg_admin_rights", chat_id=body.chat_id, target_id=body.user_id,
        details=f"{user.username}: {', '.join(k for k, v in rights.items() if v)}"[:200],
    )
    return {"ok": True}


@app.post("/api/tg_admins/demote")
async def api_tg_admin_demote(
    body: TgAdminBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    await _guard_no_active_hold(body.chat_id, body.user_id)
    bot = get_bot()

    if not await admin_holds.demote_admin(bot, body.chat_id, body.user_id):
        raise HTTPException(
            400,
            "Telegram отказал. Обычно это значит, что этого администратора назначал не бот — "
            "снять его может только тот, кто назначил, или создатель чата.",
        )

    await db.add_log(
        "panel_tg_admin_revoked", chat_id=body.chat_id, target_id=body.user_id,
        details=user.username,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Статистика и логи
# ---------------------------------------------------------------------------

def _stats_today() -> date:
    """Сегодняшняя дата (UTC). Отдельной функцией — чтобы тесты могли
    зафиксировать «сегодня» и проверять ряд дней детерминированно."""
    return datetime.utcnow().date()


def _daily_series(rows: list, since_day: date, today: date) -> list[dict]:
    """Непрерывный ряд по дням since_day..today включительно. Дни без
    сообщений заполняются нулём: иначе график схлопнул бы пропуски и ось
    времени бы врала (несколько пустых дней слились бы в один)."""
    by_day = {}
    for row in rows:
        d = row["day"]
        by_day[d.isoformat() if hasattr(d, "isoformat") else str(d)] = int(row["message_count"])
    out = []
    day = since_day
    while day <= today:
        key = day.isoformat()
        out.append({"day": key, "count": by_day.get(key, 0)})
        day += timedelta(days=1)
    return out


def _hourly_series(rows: list) -> list[dict]:
    """Ровно 24 корзины по часам (0-23). Час без сообщений — ноль, а не
    пропуск: 24 столбца всегда на месте, форма суток читается сразу."""
    by_hour = {}
    for row in rows:
        by_hour[int(row["hour"])] = by_hour.get(int(row["hour"]), 0) + int(row["message_count"])
    return [{"hour": h, "count": by_hour.get(h, 0)} for h in range(24)]


@app.get("/api/stats")
async def api_stats(chat_id: int, days: int = 7, user: PanelUser = Depends(auth.require_user)):
    role_map = await roles.load()
    days = max(1, min(days, 365))

    # Границы — датами, а не числом дней: в db.* «since» теперь везде момент,
    # а не «сколько суток назад». Заодно счётчик сообщений считает ровно тот же
    # отрезок, что и график рядом, — раньше он захватывал лишний день.
    today = _stats_today()
    since_day = today - timedelta(days=days - 1)
    since = datetime.combine(since_day, datetime.min.time())

    top_active = role_map.annotate(await db.get_top_active_since(chat_id, since_day, limit=10))
    newcomers = role_map.annotate(await db.get_new_members_since(chat_id, since, limit=20))

    daily = _daily_series(await db.list_daily_counts_for_chat(chat_id, since_day), since_day, today)
    hourly = _hourly_series(await db.list_hourly_last_24h_for_chat(chat_id))
    total = await db.count_messages_since(chat_id, since_day)

    peak_day = max(daily, key=lambda d: d["count"]) if daily else {"day": None, "count": 0}
    peak_hour = max(hourly, key=lambda h: h["count"]) if hourly else {"hour": None, "count": 0}

    return {
        "messages": total,
        "top_active": top_active,
        "reputation": role_map.annotate(await db.get_reputation_top(chat_id, limit=10)),
        "achievements": role_map.annotate(await db.get_achievements_top(chat_id, limit=10)),
        "newcomers": newcomers,
        "daily": daily,
        "hourly": hourly,
        "summary": {
            "total": total,
            "active_users": len(top_active),
            "newcomers": len(newcomers),
            "avg_per_day": round(total / days, 1),
            "peak_day": {"day": peak_day["day"], "count": peak_day["count"]},
            "peak_hour": {"hour": peak_hour["hour"], "count": peak_hour["count"]},
        },
    }


@app.get("/api/logs")
async def api_logs(limit: int = 50, user: PanelUser = Depends(auth.require_user)):
    return {"logs": await db.get_recent_logs(limit=min(limit, 200))}


LOGS_PAGE_MAX = 200


@app.get("/api/logs/search")
async def api_logs_search(
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    days: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    user: PanelUser = Depends(auth.require_user),
):
    """Журнал с поиском, фильтрами и постраничной выдачей."""
    since = None
    if days and days > 0:
        since = datetime.utcnow() - timedelta(days=min(days, 365))
    rows, total = await db.search_logs(
        query=(q or "").strip() or None,
        event_type=(event_type or "").strip() or None,
        chat_id=chat_id,
        user_id=user_id,
        since=since,
        limit=max(1, min(limit, LOGS_PAGE_MAX)),
        offset=max(0, offset),
    )
    return {
        "logs": [
            {
                "id": r["id"],
                # Отдаём ISO в UTC — переводит в местное время уже браузер,
                # у него зона пользователя точнее любой серверной настройки.
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "event_type": r["event_type"],
                "chat_id": r["chat_id"],
                "actor_id": r["actor_id"],
                "target_id": r["target_id"],
                "details": r["details"],
            }
            for r in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "event_types": await db.list_log_event_types(),
    }


# ---------------------------------------------------------------------------
# Настройки бота
# ---------------------------------------------------------------------------

# Через панель правим только тексты. chat_id/topic_id/ссылку намеренно не
# отдаём: ошибка в этих полях уводит заявки в чужой чат, а исправлять это
# придётся уже из Telegram.
ALLOWED_SETTING_KEYS = {
    "welcome_message": "Приветствие в личке (/start)",
    "link_message_template": "Сообщение со ссылкой на вход",
    "reject_message": "Отказ по заявке",
    "group_join_message": "Приветствие в группе при входе",
    "rest_rules_template": "Памятка о ресте (плейсхолдеры: "
    + ", ".join(rest_rules.REST_PLACEHOLDERS)
    + ")",
    "rest_max_days": "Рест: максимальная длительность, дней (0 — без ограничения)",
    "rest_cooldown_days": "Рест: пауза после предыдущего, дней (0 — выключить)",
    "rest_min_member_days": "Рест: минимальный стаж в чате, дней (0 — выключить)",
    "rest_cleanup_date": "Рест: дата ближайшей чистки, ДД.ММ.ГГГГ (пусто — не запланирована)",
    "rest_cleanup_block_days": "Рест: за сколько дней до чистки закрыт, дней (0 — выключить)",
    "fake_warns_in_list": "Шуточные варны («&варн») в списке «варны»: 1 — показывать, 0 — копить отдельно",
    "timezone": (
        "Часовой пояс: GMT+3, Москва, Europe/Moscow (пусто — UTC). "
        "Задаёт, каким время видят люди и где проходит граница суток у ежедневных "
        "начислений. Статистика по дням хранится в UTC и не смещается"
    ),
    "command_cleanup_minutes": (
        "Автоочистка команд в чате жалоб, минут (0 — выключить, пусто — 15). "
        f"Максимум {CMD_CLEANUP_MAX_MINUTES}: сообщения старше 48 часов Telegram удалять не даёт"
    ),
}

# Настройки-переключатели: принимаем только 1/0, чтобы «да» или «вкл» не легли
# в базу строкой, которую бот прочитает как «выключено».
BOOLEAN_SETTING_KEYS = {"fake_warns_in_list"}

# Числовые настройки панель проверяет до сохранения: бот на мусор в колонке
# молча берёт дефолт (см. _rest_setting_int в bot.py), и владелец останется в
# уверенности, что настроил одно, а работать будет другое.
NUMERIC_SETTING_KEYS = {
    "rest_max_days",
    "rest_cooldown_days",
    "rest_min_member_days",
    "rest_cleanup_block_days",
}


def validate_setting(key: str, value: Optional[str]) -> None:
    """Бросает HTTPException(400) с человеческим текстом, если значение не
    доедет до бота в том виде, в каком его задумал владелец.

    Разбор — общий с личкой бота (rest_rules), чтобы одно и то же значение
    везде принималось или везде отвергалось."""
    if key in NUMERIC_SETTING_KEYS:
        if rest_rules.parse_days_setting(value) is None:
            raise HTTPException(
                400,
                f"Нужно целое число дней от 0 до {rest_rules.DAYS_SETTING_MAX}. "
                "0 — правило выключено.",
            )
    elif key in BOOLEAN_SETTING_KEYS:
        if (value or "").strip() not in ("0", "1"):
            raise HTTPException(400, "Нужно 1 (включено) или 0 (выключено).")
    elif key == "rest_cleanup_date":
        raw = (value or "").strip()
        if raw and rest_rules.parse_settings_date(raw) is None:
            raise HTTPException(400, "Дата в формате ДД.ММ.ГГГГ, например 01.08.2026. Пусто — чистка не запланирована.")
    elif key == "timezone":
        # Разбор общий с чатом (tz_settings), поэтому «Москва» и «+3»
        # принимаются здесь ровно так же, как командой «часовой пояс».
        raw = (value or "").strip()
        if raw and tz_settings.parse_timezone(raw) is None:
            raise HTTPException(
                400,
                "Не понял часовой пояс. Подойдёт название зоны (Europe/Moscow), "
                "город (Москва, Алматы) или смещение (+3, UTC-5). Пусто — UTC.",
            )
    elif key == "command_cleanup_minutes":
        raw = (value or "").strip()
        if raw:
            if not raw.isdigit():
                raise HTTPException(400, "Нужно целое число минут (0 — выключить, пусто — 15 по умолчанию).")
            if int(raw) > CMD_CLEANUP_MAX_MINUTES:
                raise HTTPException(
                    400,
                    f"Максимум {CMD_CLEANUP_MAX_MINUTES} мин.: Telegram не даёт ботам "
                    "удалять сообщения старше 48 часов.",
                )


def _timezone_choices() -> list[dict]:
    """Варианты для выпадающего списка: сначала смещения GMT-12…+14,
    затем именованные зоны (у них есть переход на летнее время, поэтому
    для тех, кто хочет «как в Москве», это точнее фиксированного сдвига)."""
    choices = []
    for hour in range(-12, 15):
        raw = f"{hour:+d}"
        value = tz_settings.parse_timezone(raw) or "UTC"
        choices.append({"value": value, "label": f"GMT{hour:+d}" if hour else "GMT+0 (UTC)"})
    for zone, label in tz_settings.TIMEZONE_LABELS.items():
        if zone == "UTC":
            continue
        choices.append({"value": zone, "label": f"{label} — {zone}"})
    return choices


@app.get("/api/settings")
async def api_settings(user: PanelUser = Depends(auth.require_user)):
    settings = await db.fetch_settings() or {}
    editable = {
        key: {
            "title": title,
            "value": settings.get(key),
            # Тип управляет тем, как поле рисует панель: bool — кнопкой-
            # переключателем (не заставляем владельца писать 0/1 руками),
            # number — числовым полем, остальное — текстом.
            "kind": (
                "bool" if key in BOOLEAN_SETTING_KEYS
                else "number" if key in NUMERIC_SETTING_KEYS
                else "timezone" if key == "timezone"
                else "text"
            ),
        }
        for key, title in ALLOWED_SETTING_KEYS.items()
    }
    return {
        "settings": editable,
        "command_levels": await db.list_command_levels(),
        # Готовый список для выпадающего меню часового пояса: смещения GMT
        # плюс именованные зоны из общего модуля — панель не выдумывает
        # свой список, иначе он разошёлся бы с тем, что принимает бот.
        "timezones": _timezone_choices(),
    }


class SettingBody(BaseModel):
    key: str
    value: Optional[str] = None


@app.post("/api/settings")
async def api_set_setting(
    body: SettingBody, request: Request, user: PanelUser = Depends(auth.require_owner)
):
    auth.verify_csrf(request)
    if body.key not in ALLOWED_SETTING_KEYS:
        raise HTTPException(400, "Эту настройку через панель менять нельзя")
    validate_setting(body.key, body.value)

    value = body.value
    if body.key == "timezone":
        # В базу кладём канонический ключ зоны, а не то, что набрал человек:
        # бот читает колонку напрямую, и «Москва» он бы не понял.
        raw = (value or "").strip()
        value = tz_settings.parse_timezone(raw) if raw else None

    await db.save_setting(body.key, value)
    await db.add_log("panel_setting", details=f"{user.username}: {body.key}")
    # Бот держит настройки в памяти и о правке из другого процесса сам не
    # узнает — поднимаем тот же флаг перечитки, что и правки РП (см.
    # panel_action_reload_loop в bot.py). Без него смена часового пояса или
    # автоочистки применялась бы только после перезапуска бота.
    await _signal_action_reload()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Статика
# ---------------------------------------------------------------------------

def _index_html() -> HTMLResponse:
    """index.html с кэш-бастингом статики. К /static/app.js и /static/style.css
    дописываем ?v=<mtime>: поменялся файл — поменялась версия, и браузер/CDN
    берут новую копию, а не старую из кэша (иначе правки панели и, например,
    новые svg-иконки в спрайте не видны). Сам HTML отдаём с no-cache, чтобы
    свежий ?v= всегда доезжал."""
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    try:
        version = int(max(
            os.path.getmtime(os.path.join(STATIC_DIR, "app.js")),
            os.path.getmtime(os.path.join(STATIC_DIR, "style.css")),
        ))
    except OSError:
        version = 0
    html = html.replace("/static/app.js", f"/static/app.js?v={version}")
    html = html.replace("/static/style.css", f"/static/style.css?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/")
async def index():
    return _index_html()


@app.get("/api/webapp-check")
async def api_webapp_check(request: Request):
    """Почему мини-приложение не пустило.

    Без этого отказ выглядит как «Нужен вход» и одинаково означает и
    «панель запущена с другим токеном бота», и «разъехалось время», и
    «клиент ничего не прислал». Ручка публичная, но не выдаёт ничего
    полезного для подбора: ни токена, ни подписи, ни чужих данных —
    только вердикт по тому, что прислал сам вызывающий.
    """
    init_data = request.headers.get(auth.WEBAPP_INIT_DATA_HEADER, "")
    user, reason = webapp_auth.check_init_data(init_data)
    return {
        "ok": user is not None,
        "reason": reason,
        "got_init_data": bool(init_data),
        "bot_token_configured": bool(os.getenv("BOT_TOKEN")),
        "server_time": int(time.time()),
        "user_id": user.id if user else None,
    }


@app.get(WEBAPP_PATH)
async def webapp_page():
    """Страница мини-приложения Telegram.

    Отдаётся без входа — но это НЕ дыра: сама страница ничего не знает,
    все данные она берёт через /api/member/*, а те требуют подписанную
    initData от Telegram (см. auth.telegram_webapp_user). Открыв этот
    адрес браузером, посторонний увидит только предложение открыть
    приложение из чата.

    Кэш-бастинг тот же, что у панели: поменялся файл — поменялась версия.
    """
    with open(os.path.join(STATIC_DIR, "webapp.html"), encoding="utf-8") as f:
        html = f.read()
    try:
        version = int(max(
            os.path.getmtime(os.path.join(STATIC_DIR, "webapp.js")),
            os.path.getmtime(os.path.join(STATIC_DIR, "webapp.css")),
        ))
    except OSError:
        version = 0
    html = html.replace("/static/webapp.js", f"/static/webapp.js?v={version}")
    html = html.replace("/static/webapp.css", f"/static/webapp.css?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/setup")
async def setup_page():
    return _index_html()


# Питомцы кабинета — отдельным модулем, а не рядом с настройками чата у
# верхних импортов (строка ~182): тому роутеру зависимости не нужны, а этот
# берёт get_bot и _require_member_in_chat как значения — их нужно проставить
# ПОСЛЕ того, как оба определены выше в этом файле, иначе получилось бы
# NameError при импорте.
from . import member_game_api  # noqa: E402
from .member_game_api import router as member_game_router  # noqa: E402
member_game_api.get_bot = get_bot
member_game_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_game_router)

from . import member_farm_api  # noqa: E402
from .member_farm_api import router as member_farm_router  # noqa: E402
member_farm_api.get_bot = get_bot
member_farm_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_farm_router)

from . import member_casino_api  # noqa: E402
from .member_casino_api import router as member_casino_router  # noqa: E402
member_casino_api.get_bot = get_bot
member_casino_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_casino_router)

from . import member_business_api  # noqa: E402
from .member_business_api import router as member_business_router  # noqa: E402
member_business_api.get_bot = get_bot
member_business_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_business_router)

from . import member_activity_api  # noqa: E402
from .member_activity_api import router as member_activity_router  # noqa: E402
member_activity_api.get_bot = get_bot
member_activity_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_activity_router)

from . import member_profile_api  # noqa: E402
from .member_profile_api import router as member_profile_router  # noqa: E402
member_profile_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_profile_router)

from . import member_shop_api  # noqa: E402
from .member_shop_api import router as member_shop_router  # noqa: E402
member_shop_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_shop_router)

from . import member_stock_api  # noqa: E402
from .member_stock_api import router as member_stock_router  # noqa: E402
member_stock_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_stock_router)

from . import member_bank_api  # noqa: E402
from .member_bank_api import router as member_bank_router  # noqa: E402
member_bank_api.get_bot = get_bot
member_bank_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_bank_router)

from . import member_steal_api  # noqa: E402
from .member_steal_api import router as member_steal_router  # noqa: E402
member_steal_api.get_bot = get_bot
member_steal_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_steal_router)

from . import member_card_api  # noqa: E402
from .member_card_api import router as member_card_router  # noqa: E402
member_card_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_card_router)

from . import member_lootbox_api  # noqa: E402
from .member_lootbox_api import router as member_lootbox_router  # noqa: E402
member_lootbox_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_lootbox_router)

from . import member_market_api  # noqa: E402
from .member_market_api import router as member_market_router  # noqa: E402
member_market_api.get_bot = get_bot
member_market_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_market_router)

from . import member_gallery_api  # noqa: E402
from .member_gallery_api import router as member_gallery_router  # noqa: E402
member_gallery_api.require_member_in_chat = _require_member_in_chat
app.include_router(member_gallery_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
