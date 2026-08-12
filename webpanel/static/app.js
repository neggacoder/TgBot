"use strict";
// app.js
// Одностраничный интерфейс панели. Никаких внешних библиотек — политика
// безопасности страницы запрещает подгружать что-либо со сторонних адресов.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
// На /member/... в DOM нет админки, а на /admin/... — кабинета участника.
// Общий скрипт обслуживает обе облегчённые оболочки, поэтому статичные
// слушатели вешаем только если их элемент действительно отдан сервером.
function on(sel, event, handler) {
  const element = $(sel);
  if (element) element.addEventListener(event, handler);
}

let me = null;      // {username, role}
let chats = [];     // кэш списка чатов
let roleCatalog = []; // [{key, level, name}] — роли бота для фильтров

// --- helpers --------------------------------------------------------------

function csrfToken() {
  const found = document.cookie.split("; ").find((c) => c.startsWith("botpanel_csrf="));
  return found ? decodeURIComponent(found.split("=")[1]) : "";
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") opts.headers["X-CSRF-Token"] = csrfToken();
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { /* пустой ответ — не беда */ }
  if (!res.ok) throw new Error((data && data.detail) || `Ошибка ${res.status}`);
  return data;
}

function icon(name) {
  return `<svg class="ic"><use href="#ic-${name}"/></svg>`;
}

// Короткое превью значения (для свёрнутых карточек настроек): схлопывает
// переносы, обрезает и экранирует.
function previewText(v, n = 90) {
  if (v === null || v === undefined || v === "") return "— пусто —";
  const flat = String(v).replace(/\s+/g, " ").trim();
  return escapeHtml(flat.length > n ? flat.slice(0, n).trimEnd() + "…" : flat);
}

function say(where, text, kind = "ok") {
  const box = $(where);
  // Серверные строки приходят с эмодзи («🧊 Ваш счёт заморожен…») — панель
  // их не показывает, у сообщения и так есть своя иконка.
  box.innerHTML = `<div class="msg ${kind}">${icon(kind === "ok" ? "check" : "alert")}<span>${escapeHtml(безЭмодзи(text))}</span></div>`;
  if (kind === "ok") setTimeout(() => { box.innerHTML = ""; }, 4000);
}

function empty(cols, text) {
  return `<tr><td colspan="${cols}"><div class="empty">${icon("empty")}<span>${escapeHtml(text)}</span></div></td></tr>`;
}

// Цвет аватарки берём из имени — так у одного человека он всегда один и тот
// же, а список не выглядит одинаково-серым.
const PALETTE = ["#e8735a", "#e0a13a", "#8f7ae0", "#3fb894", "#3f9fd6", "#d668a8", "#5f8de0"];

function avatar(name, id) {
  const label = String(name || id || "?").trim();
  const initials = label.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
  const key = Math.abs(Number(id) || label.length) % PALETTE.length;
  return `<span class="avatar" style="background:${PALETTE[key]}">${escapeHtml(initials)}</span>`;
}

// Приписка с ролью участника. Показываем её у каждого человека в панели, а не
// только у админов: пустое место рядом с именем читается как «панель не знает»,
// а не как «обычный участник».
function roleBadge(row) {
  if (!row || row.role == null) return "";
  return `<span class="badge role ${row.role_key || "member"}">${escapeHtml(row.role)}</span>`;
}

// Тип вложения из ленты. Бот описывает его строкой, где перед словом стоит
// эмодзи: в Telegram это уместно, в панели всё рисуется SVG-иконками, поэтому
// распознаём тип по слову, а эмодзи из подписи убираем.
const MEDIA_KINDS = [
  { match: /голосов/i, icon: "mic", label: "Голосовое сообщение" },
  { match: /видеосообщ|кружок/i, icon: "video", label: "Видеосообщение" },
  { match: /фото|картинк/i, icon: "image", label: "Фото" },
  { match: /видео/i, icon: "video", label: "Видео" },
  { match: /стикер/i, icon: "sticker", label: "Стикер" },
  { match: /файл|документ/i, icon: "file", label: "Файл" },
];

const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}\u{FE0F}\u{FE0E}\u{200D}\u{20E3}]/gu;

// Для части экранов имена и серверные строки приходят с декоративными
// эмодзи, которые там заменяются собственными иконками. Товары и питомцы —
// исключение: их emoji является частью каталога в БД и выводится как есть.
// Заодно вырезаем чатовые теги <tg-emoji> из РП-фраз.
function безЭмодзи(s) {
  return String(s ?? "")
    .replace(/<\/?tg-emoji[^>]*>/g, "")
    .replace(EMOJI_RE, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// Иконка предмета игры из реестра GAME_ICONS (game_icons.js). Домен без
// иконки падает на штриховой символ спрайта — пусто не бывает никогда.
const GICON_FALLBACK = {
  crop: "sprout", animal: "paw", product: "basket", fish: "fish",
  game: "casino", biz: "building", bizup: "wrench", coll: "gift",
  house: "barn", rar: "spark", prof: "work", petfam: "paw",
  cat: "gift", weather: "sun", misc: "spark",
};

function gicon(domain, key, cls = "") {
  const inner = typeof GAME_ICONS !== "undefined" && GAME_ICONS[`${domain}:${key}`];
  if (inner) {
    return `<svg class="gicon${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true">${inner}</svg>`;
  }
  return icon(GICON_FALLBACK[domain] || "gift");
}

// Товары магазина — открытый набор (админ заводит любые), поэтому иконка
// выбирается КАТЕГОРИЕЙ по ключу товара. Неизвестный ключ падает на подарок:
// имя всё равно написано рядом, категория — только настроение.
const SHOP_CATS = {
  food: ["pizza", "burger", "sushi", "blin", "vilka", "kartoshka", "yabloko", "syr", "pirog"],
  drink: ["coffee", "chay", "kofe", "probka", "energetik", "termos", "kofemashina", "chek"],
  sweet: ["pechenka", "tort", "chocolate", "morojenoe", "fantik", "zhvachka"],
  jewel: ["ring", "diamond", "kolco", "gem", "slitok", "treasure", "monetka", "fishka", "lucky_coin"],
  medal: ["medal", "kubok", "trophy", "korona", "crown_gold", "vip_badge", "medal_bronze",
          "medal_iron", "medal_silver", "medal_gold", "order_leaf", "order_shield",
          "order_star", "order_crown", "korona_mastera", "bilet_star", "klubnaya_karta",
          "torgovyy_znak", "zvezda"],
  tool: ["remkomplekt", "aptechka", "skrepka", "gvozd", "provod", "shesterenka", "lampochka",
         "magnit", "podshipnik", "pruzhina", "doska", "provoloka", "steklo", "otmychka",
         "master_otmychka", "medvezhatnik", "lopata_master", "ledobur", "nosok", "nitka",
         "perchatka", "zont", "strahovka", "kirpich"],
  weapon: ["sword", "shield", "bronik", "bdsm_pletka", "sabotazh", "kompromat", "dymovushka"],
  tech: ["robot", "nautbuk", "teleskop", "mototsikl", "rocket", "echolot", "metalloiskatel",
         "binokl", "survilence_pass", "getaway_car", "vezdehod", "traktor", "robot_worker",
         "kamera", "signalizaciya", "slepok", "kryshka"],
  nature: ["cvetok", "kaktus", "ostrov", "kamen", "pyl", "banan_kozhura", "puzyr",
           "yashchik", "pugalo", "teplica", "gold_pig", "rabbit_paw", "korm"],
  party: ["sharik", "firework", "gift", "bilet", "gitara", "shchedrost", "megafon", "ringbell",
          "mayak", "yahta", "sharf", "tulup", "kombinezon", "portfel"],
  mystic: ["wand", "magicbook", "magicwand", "skull", "ghost", "pumpkin", "phoenix", "dragon",
           "zerkalo", "obereg", "amulet_serii", "elixir", "talisman", "kometa", "planeta",
           "zamok", "book", "dosye", "vabank", "lyod", "biznesplan", "ogon", "kompas",
           "karta", "snasti", "set_rybaka", "almaznaya_kirka"],
};
const SHOP_CAT_BY_KEY = {};
Object.entries(SHOP_CATS).forEach(([cat, keys]) => keys.forEach((k) => { SHOP_CAT_BY_KEY[k] = cat; }));

function shopIcon(key, cls = "") {
  const cat = SHOP_CAT_BY_KEY[key];
  return cat ? gicon("cat", cat, cls) : gicon("cat", "gift", cls);
}

// Ачивки: полсотни штук, и рисовать каждой свой арт — дорого и незачем;
// иконка берётся по СМЫСЛУ ключа из штрихового спрайта.
const ACH_ICONS = [
  [/^msg_|^quotes_/, "message"], [/^streak_/, "spark"], [/^days_/, "clock"],
  [/^rewarded_|^season_/, "medal"], [/night_owl/, "moon"], [/early_bird/, "sun"],
  [/^duel_/, "shield-x"], [/married|matchmaker/, "ring"], [/role_taken/, "mask"],
  [/^clan_/, "shield"], [/popular/, "star"], [/investor/, "xp"],
  [/lootbox|generous/, "gift"], [/^coins_/, "coins"], [/^casino_/, "casino"],
  [/robber/, "eye-off"], [/club_founder/, "chats"], [/bookmarks/, "pin"],
  [/^prof_|^work_|^sidejob_/, "work"], [/family/, "user"], [/^pets_/, "paw"],
  [/house_built/, "barn"], [/^race_/, "walk"], [/^farm_/, "sprout"],
  [/^fish_/, "fish"], [/treasure/, "key"], [/^collection_/, "gift"],
];
function achIcon(key) {
  const метка = ACH_ICONS.find(([re]) => re.test(key));
  return icon(метка ? метка[1] : "trophy");
}

// Питомцы: видов уже 25 и админ может добавить новых — рисуем семейство,
// а не каждого зверя. Неизвестный вид — просто лапа.
const PET_FAMILIES = {
  homyak: "rodent", mysh: "rodent", ulitka: "rodent", svinka: "rodent",
  popugay: "bird", volnistiy: "bird", sova: "bird", lebed: "bird",
  kot: "cat", pes: "dog",
  lisa: "wild", enot: "wild", panda: "wild", martyshka: "wild",
  olenenok: "wild", vydra: "wild",
  yashcherka: "reptile", cherepaha: "reptile",
  osminog: "aqua", akula: "aqua",
  muravey: "insect", pchela: "insect",
  drakon: "mythic", edinorog: "mythic", tirex: "mythic",
};
function petIcon(speciesKey, cls = "") {
  const fam = PET_FAMILIES[speciesKey];
  return fam ? gicon("petfam", fam, cls) : icon("paw");
}

// Топы: эмодзи вида с сервера меняем на штрих по ключу вида.
const TOP_ICONS = {
  messages: "message", week: "clock", coins: "coins",
  fishing: "fish", work: "work", achievements: "trophy",
};

// События смены приходят СТРОКОЙ с эмодзи в начале («🎉 Премия…») —
// эмодзи срезается, иконка подбирается по слову.
const WORK_EVENT_ICONS = [
  [/премия/i, "gift"], [/несчастный/i, "alert"], [/озарение/i, "spark"],
  [/краж/i, "eye-off"], [/коллега/i, "coffee"], [/курс/i, "xp"],
];
function workEventHtml(text) {
  const чистый = безЭмодзи(text);
  const метка = WORK_EVENT_ICONS.find(([re]) => re.test(чистый));
  return `${icon(метка ? метка[1] : "spark")}${escapeHtml(чистый)}`;
}

// Состояния питомца («🍽 проголодался») — тем же приёмом.
const PET_STATE_ICONS = [
  [/голодает|проголодался/i, "bowl"], [/скучает/i, "alert"], [/хорошо/i, "smile"],
];
function petStateHtml(text) {
  const чистый = безЭмодзи(text);
  const метка = PET_STATE_ICONS.find(([re]) => re.test(чистый));
  return `${icon(метка ? метка[1] : "smile")}${escapeHtml(чистый)}`;
}

function mediaKind(kind) {
  const raw = String(kind || "").trim();
  const known = MEDIA_KINDS.find((k) => k.match.test(raw));
  if (known) return known;
  // Неизвестный тип показываем как есть, но без эмодзи: бот мог добавить
  // новый вид вложения, а панель не должна ни падать, ни рисовать картинку
  // системным шрифтом.
  const label = raw.replace(EMOJI_RE, "").trim();
  return { icon: "message", label: label || "Сообщение без текста" };
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value.replace(" ", "T") + (value.includes("Z") ? "" : "Z"));
  return isNaN(d) ? value : d.toLocaleString("ru-RU");
}

// Скелет на время загрузки: место занято ровно тем, что сейчас появится, и
// переход не читается как зависшая страница.
function skeleton(rows = 3) {
  return `<div class="skeleton">${'<div class="skeleton-row"></div>'.repeat(rows)}</div>`;
}

function skeletonRows(cols, rows = 3) {
  return `<tr><td colspan="${cols}">${skeleton(rows)}</td></tr>`;
}

// --- тема -----------------------------------------------------------------
// Выбор темы руками сильнее системной: если человек нажал кнопку, панель
// обязана остаться такой при следующем заходе. Пусто в хранилище — идём за
// системной настройкой, как и раньше.

const THEME_KEY = "botpanel_theme";

function systemTheme() {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function currentTheme() {
  return document.documentElement.dataset.theme || systemTheme();
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const label = $("#theme-label");
  if (label) label.textContent = currentTheme() === "light" ? "Тёмная" : "Светлая";
}

function toggleTheme() {
  const next = currentTheme() === "light" ? "dark" : "light";
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

// Маршруты — настоящие адреса, а не состояние, спрятанное в ?panel=&tab=.
// Сервер отдаёт одну оболочку для /member/... и /admin/..., а клиент лениво
// рисует нужный экран. Так прямой ссылкой можно поделиться, F5 не сбрасывает
// человека на главную, и после повторного входа остаётся именно тот раздел,
// на котором протухла сессия.
const MEMBER_TAB_TO_ROUTE = {
  prof: "profile", tops: "tops", caps: "capabilities", suggest: "suggestions",
  rel: "relationships", family: "family", clans: "clans", farm: "farm",
  casino: "casino", biz: "businesses", fish: "fishing", work: "work",
  pets: "pets", shop: "shop", stock: "stock", bank: "bank",
};
const MEMBER_ROUTE_TO_TAB = Object.fromEntries(
  Object.entries(MEMBER_TAB_TO_ROUTE).map(([tab, route]) => [route, tab])
);

function navFromUrl() {
  const parts = location.pathname.split("/").filter(Boolean);
  if (parts[0] === "member") {
    return { panel: "member", tab: MEMBER_ROUTE_TO_TAB[parts[1]] || null };
  }
  if (parts[0] === "admin") {
    return { panel: "admin", tab: parts[1] || null };
  }
  // Старые ссылки с query-параметрами не ломаем: при первом переходе они
  // автоматически станут каноническим адресом.
  const params = new URLSearchParams(location.search);
  return { panel: params.get("panel"), tab: params.get("tab") };
}

function writeNavUrl(panel, tab, push = true) {
  const url = new URL(location.href);
  url.searchParams.delete("token");
  url.searchParams.delete("panel");
  url.searchParams.delete("tab");
  const route = panel === "member" ? MEMBER_TAB_TO_ROUTE[tab] : tab;
  url.pathname = `/${panel}/${route || (panel === "member" ? "profile" : "send")}`;
  history[push ? "pushState" : "replaceState"]({ panel, tab }, "", url);
}

function postLoginUrl() {
  const nav = navFromUrl();
  if (nav.panel === "member" || nav.panel === "admin") {
    return `${location.pathname}${location.search}${location.hash}`;
  }
  return "/";
}

// Тему ставим до первой отрисовки — иначе панель мигнёт чужим цветом.
applyTheme(localStorage.getItem(THEME_KEY));

// --- вход -----------------------------------------------------------------

async function boot() {
  const state = await api("/api/me");
  if (state.authenticated) {
    me = state;
    const nav = navFromUrl();
    // Сам URL выбирает оболочку. Роль ограничивает данные и действия через
    // API, но не имеет права молча превратить /member/profile в /admin/send:
    // иначе прямые ссылки и возврат после входа теряют весь смысл.
    if (nav.panel === "member") showMember();
    else if (nav.panel === "admin") showApp();
    else if (me.role === "member") location.replace("/member/profile");
    else showApp();
    return;
  }
  const setupToken = new URLSearchParams(location.search).get("token");
  if (state.setup_required && setupToken) {
    $("#auth-title").textContent = "Создание владельца";
    $("#auth-hint").textContent = "Это первый вход. Задайте логин и пароль владельца панели.";
    $("#auth-form").dataset.mode = "setup";
  } else if (state.setup_required) {
    $("#auth-title").textContent = "Панель не настроена";
    $("#auth-hint").textContent =
      "Откройте одноразовую ссылку из логов запуска панели, чтобы создать владельца.";
    $("#auth-form").querySelectorAll("label, button").forEach((el) => el.classList.add("hidden"));
  }
  $("#auth").classList.remove("hidden");
}

on("#auth-form", "submit", async (e) => {
  e.preventDefault();
  const username = $("#auth-user").value.trim();
  const password = $("#auth-pass").value;
  const isSetup = $("#auth-form").dataset.mode === "setup";
  try {
    if (isSetup) {
      const token = new URLSearchParams(location.search).get("token");
      await api("/api/setup", { method: "POST", body: { token, username, password } });
    } else {
      await api("/api/login", { method: "POST", body: { username, password } });
    }
    location.assign(postLoginUrl());
  } catch (err) {
    say("#auth-msg", err.message, "err");
  }
});

on("#logout", "click", async () => {
  await api("/api/logout", { method: "POST" });
  location.href = "/";
});

on("#theme-toggle", "click", toggleTheme);

// --- экран участника ------------------------------------------------------
// Вход у участников и персонала общий — /api/login по логину и паролю.
// После проверки роли boot() открывает отдельный интерфейс участника.
on("#member-logout", "click", async () => {
  await api("/api/logout", { method: "POST" });
  location.href = "/";
});

on("#member-theme", "click", toggleTheme);

// Какие вкладки участника уже загружены (ленивая загрузка при первом открытии).
// Рабочий чат для старых вкладок (отношения, семья, кланы). Раньше он
// читался из выпадающего списка; список убран — чат один, и сервер отдаёт
// именно его.
const _членство = { rel: null, family: null, clans: null };

const _memberLoaded = { prof: false, tops: false, shop: false, pets: false, rel: false, family: false, clans: false, caps: false, suggest: false, farm: false, casino: false, biz: false, fish: false, work: false, stock: false, bank: false };

function showMember() {
  if (!$("#member")) {
    location.replace("/member/profile");
    return;
  }
  $("#auth").classList.add("hidden");
  $("#app")?.classList.add("hidden");
  $("#member").classList.remove("hidden");
  // Кнопка возврата — только у персонала (admin/owner), заглянувшего сюда из
  // своей панели. Обычный участник (role === "member") сюда попадает
  // напрямую при входе и возвращаться ему некуда.
  $("#member-back-to-panel").classList.toggle("hidden", !me || me.role === "member");
  _memberLoaded.rel = _memberLoaded.family = _memberLoaded.clans = _memberLoaded.caps = false;
  _memberLoaded.farm = _memberLoaded.casino = _memberLoaded.biz = false;
  _memberLoaded.fish = _memberLoaded.work = false;
  _memberLoaded.prof = _memberLoaded.tops = false;
  _memberLoaded.shop = _memberLoaded.pets = false;
  const nav = navFromUrl();
  const requested = nav.panel === "member" ? nav.tab : null;
  const exists = $$(".member-tab").some((b) => b.dataset.mtab === requested);
  switchMemberTab(exists ? requested : "prof", false);
}

on("#member-back-to-panel", "click", () => {
  $("#member").classList.add("hidden");
  writeNavUrl("admin", "send");
  if ($("#app")) showApp(); else location.assign("/admin/send");
});

// На телефоне навигация — выезжающий слева сайдбар. Открывается одной кнопкой,
// а группы внутри него сразу развёрнуты: второго «бургера в бургере» нет.
const _burger = $("#member-burger");

function setBurger(open) {
  const tabs = $("#member-tabs");
  if (!tabs || !_burger) return;
  tabs.classList.toggle("open", open);
  $("#member")?.classList.toggle("member-nav-open", open);
  _burger.setAttribute("aria-expanded", open ? "true" : "false");
  if (open && !_memberNavDesktop.matches) {
    _memberNavGroups.forEach((group) => { group.open = true; });
  }
}

if (_burger) {
  _burger.addEventListener("click", (e) => {
    e.stopPropagation();
    setBurger(_burger.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#member-tabs") && !e.target.closest("#member-burger")) {
      setBurger(false);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setBurger(false);
  });
}

// На компьютере это hover-витрина: кнопки появляются, только пока курсор над
// карточкой. Клик по заголовку там не нужен и не должен оставлять её открытой.
// На телефоне hover отсутствует, поэтому остаётся обычный details по нажатию.
const _memberNavDesktop = window.matchMedia('(min-width: 761px)');
const _memberNavGroups = $$('details.member-nav-group');

_memberNavGroups.forEach((group) => {
  const summary = group.querySelector('summary');
  let closeTimer = null;
  const openOnDesktop = () => {
    if (!_memberNavDesktop.matches) return;
    if (closeTimer) clearTimeout(closeTimer);
    group.open = true;
  };
  const closeOnDesktop = () => {
    if (!_memberNavDesktop.matches) return;
    closeTimer = setTimeout(() => { group.open = false; }, 90);
  };

  group.addEventListener('pointerenter', openOnDesktop);
  group.addEventListener('pointerleave', closeOnDesktop);
  group.addEventListener('focusin', openOnDesktop);
  group.addEventListener('focusout', () => {
    setTimeout(() => {
      if (!group.contains(document.activeElement)) closeOnDesktop();
    }, 0);
  });
  summary.addEventListener('click', (event) => {
    if (!_memberNavDesktop.matches) {
      event.preventDefault();
      return;
    }
    if (_memberNavDesktop.matches && event.detail !== 0) event.preventDefault();
  });

  // На большом экране две открытые витрины перекрывали бы друг друга. В
  // мобильном сайдбаре, наоборот, все группы видны сразу.
  group.addEventListener('toggle', () => {
    if (!_memberNavDesktop.matches) return;
    if (!group.open) return;
    _memberNavGroups.forEach((other) => {
      if (other !== group) other.open = false;
    });
  });
});

_memberNavDesktop.addEventListener('change', (event) => {
  if (event.matches) _memberNavGroups.forEach((group) => { group.open = false; });
});

function switchMemberTab(name, push = true) {
  const выбранная = $$(".member-tab").find((b) => b.dataset.mtab === name);
  if (!выбранная) return;
  writeNavUrl("member", name, push);
  $$(".member-tab").forEach((b) => b.classList.toggle("active", b.dataset.mtab === name));
  // Вложенные группы держат меню коротким. При переходе по URL или ссылке
  // раскрываем группу активного раздела только на телефоне: на десктопе
  // кнопки намеренно появляются лишь при наведении.
  const группа = выбранная.closest("details.member-nav-group");
  if (группа && !_memberNavDesktop.matches) группа.open = true;
  // Название текущего раздела на кнопке: свёрнутый список иначе не говорит,
  // где ты находишься.
  const подпись = $("#member-burger-label");
  if (подпись && выбранная) подпись.textContent = выбранная.textContent.trim();
  setBurger(false);
  $$(".member-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
  if (name === "prof" && !_memberLoaded.prof) { _memberLoaded.prof = true; loadMemberProf(); }
  else if (name === "tops" && !_memberLoaded.tops) { _memberLoaded.tops = true; loadMemberTops(); }
  else if (name === "rel" && !_memberLoaded.rel) { _memberLoaded.rel = true; loadMemberRelationship(); }
  else if (name === "family" && !_memberLoaded.family) { _memberLoaded.family = true; loadMemberFamily(); }
  else if (name === "clans" && !_memberLoaded.clans) { _memberLoaded.clans = true; loadMemberClans(); }
  else if (name === "caps" && !_memberLoaded.caps) { _memberLoaded.caps = true; loadMemberCapabilities(); }
  else if (name === "suggest" && !_memberLoaded.suggest) { _memberLoaded.suggest = true; loadMemberSuggestion(); }
  else if (name === "farm" && !_memberLoaded.farm) { _memberLoaded.farm = true; loadMemberFarm(); }
  else if (name === "casino" && !_memberLoaded.casino) { _memberLoaded.casino = true; loadMemberCasino(); }
  else if (name === "biz" && !_memberLoaded.biz) { _memberLoaded.biz = true; loadMemberBiz(); }
  else if (name === "fish" && !_memberLoaded.fish) { _memberLoaded.fish = true; loadMemberFish(); }
  else if (name === "work" && !_memberLoaded.work) { _memberLoaded.work = true; loadMemberWork(); }
  else if (name === "shop" && !_memberLoaded.shop) { _memberLoaded.shop = true; loadMemberShop(); }
  else if (name === "stock" && !_memberLoaded.stock) { _memberLoaded.stock = true; loadMemberStock(); }
  else if (name === "bank" && !_memberLoaded.bank) { _memberLoaded.bank = true; loadMemberBank(); }
  else if (name === "pets" && !_memberLoaded.pets) { _memberLoaded.pets = true; loadMemberPets(); }
  if (name !== "biz") { if (typeof stopBizTick === "function") stopBizTick(); }
  if (name !== "fish" && name !== "work") {
    if (typeof stopActivityTick === "function") stopActivityTick();
  }
  // Таймеры фермы тикают раз в секунду. Уходя с вкладки, их надо гасить:
  // невидимый экран не должен жечь батарею и дёргать сервер, когда грядка
  // поспеет.
  if (name !== "farm") { if (typeof stopFarmTick === "function") stopFarmTick(); }
  else if (_memberLoaded.farm && _farm.state) startFarmTick();
}

// ===== Вкладка «Кланы» =====================================================
const CLAN_ROLE = { leader: "Лидер", deputy: "Зам", member: "Участник" };

function memberClansChat() {
  return _членство.clans;
}

function clansBlock(inner) {
  return `<section class="member-block"><h2>${icon("shield")}Кланы</h2><div class="card">${inner}</div></section>`;
}

async function loadMemberClans() {
  const box = $("#member-clans");
  box.innerHTML = clansBlock(`<div class="muted">Загрузка…</div>`);
  try {
    const data = await api("/api/member/chats");
    const chats = data.chats || [];
    if (!chats.length) {
      box.innerHTML = clansBlock(`<div class="empty">${icon("empty")}<span>Бот пока не видел вас ни в одном чате.</span></div>`);
      return;
    }
    const options = chats.map((c) => `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`).join("");
    box.innerHTML = clansBlock(
      `
       <div id="member-clans-status"></div>`
    );
    _членство.clans = Number(chats[0].chat_id);
    loadMemberClanStatus();
  } catch (err) {
    box.innerHTML = clansBlock(`<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`);
  }
}

async function loadMemberClanStatus() {
  const el = $("#member-clans-status");
  if (!el) return;
  el.innerHTML = `<div class="muted">Загрузка…</div>`;
  try {
    const data = await api(`/api/member/clans?chat_id=${memberClansChat()}`);
    let out = "";
    if (data.my) {
      out += renderMyClan(data.my);
    } else {
      out += `<div class="rel-row"><span class="muted">Вы не состоите в клане.</span></div>
        <div class="rel-propose"><label><span>Создать свой клан</span>
          <input type="text" id="clan-new-name" placeholder="Название (до 64 символов)" autocomplete="off"></label>
          <textarea id="clan-new-desc" rows="2" placeholder="Описание (необязательно)"></textarea>
          <button class="ghost small act-ready" id="clan-create-btn">${icon("plus")}Создать клан</button></div>`;
    }
    out += renderClanList(data.clans, data.my);
    el.innerHTML = out;
    wireClanHandlers();
  } catch (err) {
    el.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderMyClan(c) {
  const isLeader = c.role === "leader";
  const canManage = isLeader || c.role === "deputy";
  let h = `<div class="clan-card">
    <div class="clan-head"><h3>${icon("shield")}${escapeHtml(c.name)}</h3>
      <span class="chip">${escapeHtml(CLAN_ROLE[c.role] || c.role)}</span></div>`;
  if (c.title) h += `<div class="clan-meta">${icon("tag")}${escapeHtml(c.title)}</div>`;
  if (c.motto) h += `<div class="clan-meta muted">«${escapeHtml(c.motto)}»</div>`;
  if (c.description) h += `<div class="clan-desc">${escapeHtml(c.description)}</div>`;
  h += `<div class="clan-stats">
    <span>${icon("medal")}Очки войн: <b>${c.war_points}</b></span>
    <span class="muted">Побед ${c.wars_won} · ничьих ${c.wars_drawn} · поражений ${c.wars_lost}</span>
    <span>${icon("spark")}Казна: <b>${c.coins}</b></span></div>`;
  h += `<div class="clan-members">`;
  for (const m of c.members) {
    const roleLbl = CLAN_ROLE[m.role] || m.role;
    let ops = "";
    if (canManage && m.role !== "leader") {
      if (m.role === "member" || isLeader) ops += `<button class="ghost small danger" data-clan-kick="${m.user_id}">Кик</button>`;
      if (isLeader && m.role === "member") ops += `<button class="ghost small" data-clan-deputy="${m.user_id}" data-on="1">+Зам</button>`;
      if (isLeader && m.role === "deputy") ops += `<button class="ghost small" data-clan-deputy="${m.user_id}" data-on="0">−Зам</button>`;
      if (isLeader) ops += `<button class="ghost small" data-clan-transfer="${m.user_id}">Передать</button>`;
    }
    h += `<div class="clan-member-row"><span>${m.role === "leader" ? icon("crown") : ""}${escapeHtml(m.name)} <span class="muted">· ${roleLbl}</span></span><span class="clan-ops">${ops}</span></div>`;
  }
  h += `</div>`;
  if (canManage) {
    h += `<div class="clan-manage">
      <label><span>Название</span><input type="text" id="clan-edit-name" value="${escapeHtml(c.name)}" autocomplete="off"></label>
      <textarea id="clan-edit-desc" rows="2" placeholder="Описание">${escapeHtml(c.description || "")}</textarea>
      <button class="ghost small" id="clan-edit-btn">${icon("edit")}Сохранить описание</button>
      <div class="clan-inline"><input type="text" id="clan-title" value="${escapeHtml(c.title || "")}" placeholder="Звание (пусто — снять)" autocomplete="off">
        <button class="ghost small" id="clan-title-btn">${icon("tag")}Звание</button></div>
      <div class="clan-inline"><input type="text" id="clan-motto" value="${escapeHtml(c.motto || "")}" placeholder="Девиз (пусто — снять)" autocomplete="off">
        <button class="ghost small" id="clan-motto-btn">${icon("edit")}Девиз</button></div></div>`;
  }
  h += `<div class="clan-foot">`;
  h += isLeader
    ? `<button class="ghost small danger" id="clan-delete-btn">${icon("trash")}Удалить клан</button>`
    : `<button class="ghost small danger" id="clan-leave-btn">${icon("logout")}Выйти из клана</button>`;
  h += `</div></div>`;
  return h;
}

function renderClanList(clans, my) {
  if (!clans || !clans.length) {
    return `<div class="hint">В этом чате пока нет кланов${my ? "" : " — создайте первый"}.</div>`;
  }
  const myId = my ? my.id : null;
  let h = `<div class="clan-list"><h4>${icon("chart")}Кланы чата</h4>`;
  for (const c of clans) {
    const right = c.id !== myId
      ? `<button class="ghost small" data-clan-join="${c.id}">Вступить</button>`
      : `<span class="chip">вы здесь</span>`;
    h += `<div class="clan-list-row"><span>${icon("shield")}<b>${escapeHtml(c.name)}</b>${
      c.title ? ` <span class="muted">${escapeHtml(c.title)}</span>` : ""} <span class="muted">· ${c.members_count} уч. · ${icon("medal")}${c.war_points}</span></span>${right}</div>`;
  }
  return h + `</div>`;
}

function wireClanHandlers() {
  const on = (id, fn) => { const e = $("#" + id); if (e) e.addEventListener("click", fn); };
  on("clan-create-btn", memberClanCreate);
  on("clan-leave-btn", memberClanLeave);
  on("clan-delete-btn", memberClanDelete);
  on("clan-edit-btn", memberClanEdit);
  on("clan-title-btn", memberClanTitle);
  on("clan-motto-btn", memberClanMotto);
  $$("[data-clan-join]").forEach((b) => b.addEventListener("click", () => memberClanJoin(Number(b.dataset.clanJoin))));
  $$("[data-clan-kick]").forEach((b) => b.addEventListener("click", () => memberClanKick(Number(b.dataset.clanKick))));
  $$("[data-clan-deputy]").forEach((b) => b.addEventListener("click", () => memberClanDeputy(Number(b.dataset.clanDeputy), b.dataset.on === "1")));
  $$("[data-clan-transfer]").forEach((b) => b.addEventListener("click", () => memberClanTransfer(Number(b.dataset.clanTransfer))));
}

async function _clanPost(path, body, okMsg) {
  try {
    await api(path, { method: "POST", body: { chat_id: memberClansChat(), ...body } });
    if (okMsg) say("#member-toast", okMsg);
    loadMemberClanStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

function memberClanCreate() {
  const name = ($("#clan-new-name").value || "").trim();
  if (!name) { say("#member-toast", "Введите название клана", "err"); return; }
  _clanPost("/api/member/clan/create", { name, description: ($("#clan-new-desc").value || "").trim() }, "Клан создан");
}
function memberClanJoin(id) {
  if (!confirm("Вступить в этот клан? Из текущего клана вы выйдете.")) return;
  _clanPost("/api/member/clan/join", { clan_id: id }, "Вы вступили в клан");
}
function memberClanLeave() {
  if (!confirm("Выйти из клана?")) return;
  _clanPost("/api/member/clan/leave", {}, "Вы вышли из клана");
}
function memberClanDelete() {
  if (!confirm("Удалить клан безвозвратно? Все участники будут распущены.")) return;
  _clanPost("/api/member/clan/delete", {}, "Клан удалён");
}
function memberClanEdit() {
  _clanPost("/api/member/clan/edit", { name: ($("#clan-edit-name").value || "").trim(), description: ($("#clan-edit-desc").value || "").trim() }, "Сохранено");
}
function memberClanTitle() {
  _clanPost("/api/member/clan/title", { value: ($("#clan-title").value || "").trim() }, "Звание обновлено");
}
function memberClanMotto() {
  _clanPost("/api/member/clan/motto", { value: ($("#clan-motto").value || "").trim() }, "Девиз обновлён");
}
function memberClanKick(uid) {
  if (!confirm("Исключить участника из клана?")) return;
  _clanPost("/api/member/clan/kick", { user_id: uid }, "Участник исключён");
}
function memberClanDeputy(uid, on) {
  _clanPost("/api/member/clan/deputy", { user_id: uid, on }, on ? "Назначен зам" : "Зам снят");
}
function memberClanTransfer(uid) {
  if (!confirm("Передать лидерство этому участнику? Вы станете замом.")) return;
  _clanPost("/api/member/clan/transfer", { user_id: uid }, "Лидерство передано");
}

// ===== Вкладка «Семья»: дом, питомцы, дети =================================
function memberFamilyChat() {
  return _членство.family;
}

function familyBlock(inner) {
  return `<section class="member-block"><h2>${icon("crown")}Семья</h2><div class="card">${inner}</div></section>`;
}

async function loadMemberFamily() {
  const box = $("#member-family");
  box.innerHTML = familyBlock(`<div class="muted">Загрузка…</div>`);
  try {
    const data = await api("/api/member/chats");
    const chats = data.chats || [];
    if (!chats.length) {
      box.innerHTML = familyBlock(`<div class="empty">${icon("empty")}<span>Бот пока не видел вас ни в одном чате.</span></div>`);
      return;
    }
    const options = chats.map((c) => `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`).join("");
    box.innerHTML = familyBlock(
      `
       <div id="member-family-status"></div>`
    );
    _членство.family = Number(chats[0].chat_id);
    loadMemberFamilyStatus();
  } catch (err) {
    box.innerHTML = familyBlock(`<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`);
  }
}

async function loadMemberFamilyStatus() {
  const el = $("#member-family-status");
  if (!el) return;
  el.innerHTML = `<div class="muted">Загрузка…</div>`;
  try {
    const d = await api(`/api/member/family?chat_id=${memberFamilyChat()}`);
    if (!d.pair) {
      el.innerHTML = `<div class="rel-row"><span class="muted">Вы ни с кем не в отношениях — дом, питомцы и дети есть только у пары.</span></div>`;
      return;
    }
    let out = `<div class="fam-sparks">${icon("spark")}Искр у пары: <b>${d.sparks}</b></div>`;
    // Дом
    out += `<div class="fam-sec"><h4>${icon("crown")}Дом</h4>`;
    if (d.house) {
      out += `<div class="fam-row"><b>${escapeHtml(безЭмодзи(d.house.name))}</b> <span class="muted">· ${d.house.status === "building" ? "строится" : "готов"}</span></div>`;
      if (d.house.rooms.length) out += `<div class="fam-tags">${d.house.rooms.map((r) => `<span class="chip">${escapeHtml(r.key)} ур.${r.level}</span>`).join("")}</div>`;
      if (d.house.upgrades.length) out += `<div class="fam-tags">${d.house.upgrades.map((u) => `<span class="chip">${escapeHtml(u.key)} ур.${u.level}</span>`).join("")}</div>`;
    } else {
      out += `<div class="muted">Дома пока нет. Купить — в чате: <code>дом купить hut</code>.</div>`;
    }
    out += `</div>`;
    // Питомцы
    out += `<div class="fam-sec"><h4>${icon("bot")}Питомцы <span class="muted">${d.pets.length}</span></h4>`;
    if (d.pets.length) {
      for (const p of d.pets) {
        out += `<div class="fam-item">
          <div class="fam-item-head"><b>${escapeHtml(p.name)}</b> <span class="muted">${escapeHtml(p.species)} · ${escapeHtml(p.rarity)} · ур.${p.level}${p.active ? " · активный" : ""}</span></div>
          <div class="fam-bars"><span>HP ${p.hp}</span><span>Настроение ${p.mood}</span></div>
          <div class="fam-ops">
            ${p.active ? "" : `<button class="ghost small" data-pet-active="${p.id}">Сделать активным</button>`}
            <button class="ghost small" data-pet-rename="${p.id}" data-name="${escapeHtml(p.name)}">${icon("edit")}Имя</button></div></div>`;
      }
    } else {
      out += `<div class="muted">Питомцев нет. Купить яйцо — в чате: <code>отн пт яйцо …</code>.</div>`;
    }
    out += `</div>`;
    // Дети
    out += `<div class="fam-sec"><h4>${icon("user")}Дети <span class="muted">${d.children.length}</span></h4>`;
    if (d.children.length) {
      for (const c of d.children) {
        out += `<div class="fam-item">
          <div class="fam-item-head"><b>${escapeHtml(c.name)}</b> <span class="muted">ур.${c.level}${c.section ? " · " + escapeHtml(c.section) : ""}</span></div>
          <div class="fam-bars"><span>Здоровье ${c.health}</span><span>Интеллект ${c.intellect}</span><span>Обаяние ${c.charisma}</span></div>
          <div class="fam-ops"><button class="ghost small" data-child-rename="${c.id}" data-name="${escapeHtml(c.name)}">${icon("edit")}Имя</button></div></div>`;
      }
    } else {
      out += `<div class="muted">Детей нет. Завести — в чате ответом на сообщение партнёра: <code>отн родить Имя</code>.</div>`;
    }
    out += `</div>`;
    el.innerHTML = out;
    wireFamilyHandlers();
  } catch (err) {
    el.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function wireFamilyHandlers() {
  $$("[data-pet-active]").forEach((b) => b.addEventListener("click", () => memberPetActive(Number(b.dataset.petActive))));
  $$("[data-pet-rename]").forEach((b) => b.addEventListener("click", () => memberPetRename(Number(b.dataset.petRename), b.dataset.name)));
  $$("[data-child-rename]").forEach((b) => b.addEventListener("click", () => memberChildRename(Number(b.dataset.childRename), b.dataset.name)));
}

async function memberPetActive(petId) {
  try {
    await api("/api/member/pet/active", { method: "POST", body: { chat_id: memberFamilyChat(), pet_id: petId } });
    say("#member-toast", "Питомец теперь активный");
    loadMemberFamilyStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberPetRename(petId, cur) {
  const name = prompt("Новое имя питомца:", cur || "");
  if (name == null) return;
  try {
    await api("/api/member/pet/rename", { method: "POST", body: { chat_id: memberFamilyChat(), pet_id: petId, name: name.trim() } });
    say("#member-toast", "Имя изменено");
    loadMemberFamilyStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberChildRename(childId, cur) {
  const name = prompt("Новое имя ребёнка:", cur || "");
  if (name == null) return;
  try {
    await api("/api/member/child/rename", { method: "POST", body: { chat_id: memberFamilyChat(), child_id: childId, name: name.trim() } });
    say("#member-toast", "Имя изменено");
    loadMemberFamilyStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function loadMemberCapabilities() {
  const el = $("#member-caps");
  el.innerHTML = skeleton(4);
  try {
    const data = await api("/api/member/capabilities");
    $("#member-who").textContent = data.name || "участник";
    el.innerHTML =
      memberSection(`${icon("message")}РП-действия`, data.rp) +
      memberSection(`${icon("user")}Себяшки`, data.self);
    $$("[data-member-expand]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = btn.closest(".action-card").querySelector(".action-body");
        const nowCollapsed = body.classList.toggle("collapsed");
        btn.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
      });
    });
  } catch (err) {
    el.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function loadMemberSuggestion() {
  const el = $("#member-suggest");
  el.innerHTML = `<section class="member-block"><h2>${icon("message")}Предложить улучшение</h2>
    <div class="card">
      <p class="muted">Расскажите, что стоит добавить, изменить или исправить. Сообщение попадёт администраторам.</p>
      <label><span>Ваше предложение</span>
        <textarea id="member-suggestion-text" maxlength="2000" rows="7"
          placeholder="Например: добавить новое событие для всего чата…"></textarea>
      </label>
      <div id="member-suggestion-msg"></div>
      <div class="form-foot"><button class="primary" id="member-suggestion-send">${icon("send")}Отправить</button></div>
    </div></section>`;
  $("#member-suggestion-send").addEventListener("click", sendMemberSuggestion);
}

async function sendMemberSuggestion() {
  const input = $("#member-suggestion-text");
  const text = input.value.trim();
  if (!text) { say("#member-suggestion-msg", "Напишите предложение", "err"); return; }
  const btn = $("#member-suggestion-send");
  btn.disabled = true;
  try {
    await api("/api/member/suggestion", { method: "POST", body: { text } });
    input.value = "";
    say("#member-suggestion-msg", "Предложение отправлено. Спасибо!");
  } catch (err) {
    say("#member-suggestion-msg", err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

// Одна read-only секция обзора: действия (сворачиваемые, как в админке, но без
// кнопок правки) + синонимы. Фразы — данные бота; эмодзи в них панель
// срезает, как и везде в кабинете.
function memberSection(title, set) {
  const actions = (set && set.actions) || [];
  if (!actions.length) {
    return `<section class="member-block"><h2>${title}</h2>
      <div class="card"><div class="empty">${icon("empty")}<span>Пока ничего</span></div></div></section>`;
  }
  const cards = actions.map((a) => `
    <div class="card action-card">
      <div class="action-head">
        <h3>${escapeHtml(a.key)} <span class="muted">${a.phrases.length}</span></h3>
        <button class="disclosure ghost small" data-member-expand aria-expanded="false" title="Показать фразы">${icon("chevron")}</button>
      </div>
      <div class="action-body collapsed">
        <div class="action-phrases">
          ${a.phrases.map((p) => `<div class="phrase-row"><span class="phrase-text">${escapeHtml(безЭмодзи(p))}</span></div>`).join("")}
        </div>
      </div>
    </div>`).join("");
  let synonyms = "";
  const entries = Object.entries((set && set.synonyms) || {});
  if (entries.length) {
    synonyms = `<div class="card"><h3>${icon("tag")}Синонимы</h3>
      ${entries.map(([syn, key]) => `
        <div class="phrase-row"><span class="phrase-text"><b>${escapeHtml(syn)}</b> <span class="muted">→</span> ${escapeHtml(key)}</span></div>`).join("")}</div>`;
  }
  return `<section class="member-block"><h2>${title}</h2>${cards}${synonyms}</section>`;
}

// --- участник: свой брак и отношения --------------------------------------

function relBlock(inner) {
  return `<section class="member-block"><h2>${icon("ring")}Брак и отношения</h2><div class="card">${inner}</div></section>`;
}

async function loadMemberRelationship() {
  const box = $("#member-rel");
  box.innerHTML = relBlock(`<div class="muted">Загрузка…</div>`);
  try {
    const data = await api("/api/member/chats");
    const chats = data.chats || [];
    if (!chats.length) {
      box.innerHTML = relBlock(`<div class="empty">${icon("empty")}<span>Бот пока не видел вас ни в одном чате.</span></div>`);
      return;
    }
    const options = chats.map((c) => `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`).join("");
    box.innerHTML = relBlock(
      `
       <div id="member-rel-status"></div>`
    );
    _членство.rel = Number(chats[0].chat_id);
    loadMemberRelStatus();
  } catch (err) {
    box.innerHTML = relBlock(`<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`);
  }
}

function memberCurrentChat() {
  return _членство.rel;
}

async function loadMemberRelStatus() {
  const el = $("#member-rel-status");
  el.innerHTML = `<div class="muted">Загрузка…</div>`;
  try {
    const chatId = memberCurrentChat();
    const [info, data] = await Promise.all([
      api(`/api/member/info?chat_id=${chatId}`),
      api(`/api/member/relationship?chat_id=${chatId}`),
    ]);
    let out = `<div class="member-info-box">${userInfoHtml(info)}</div>`;
    out += `<div class="rel-propose"><label><span>Мой ник в этом чате</span>
      <div class="row"><input type="text" id="member-nick" maxlength="32" value="${escapeHtml(info.nickname || "")}" placeholder="Без ника" autocomplete="off">
        <button class="ghost small" id="member-nick-save">${icon("check")}Сохранить</button></div></label></div>`;
    out += `<div class="member-target-list mb-2">
      <button class="ghost small" id="member-top-btn">${icon("chart")}Топ чата</button>
      <button class="ghost small" id="member-warns-btn">${icon("alert")}Мои варны</button>
      <button class="ghost small" id="member-rewards-btn">${icon("medal")}Мои награды</button></div>`;
    if (data.marriage) {
      const when = data.marriage.married_at ? ` <span class="muted">· с ${escapeHtml(data.marriage.married_at.slice(0, 10))}</span>` : "";
      out += `<div class="rel-row"><span>${icon("ring")}В браке с <b>${escapeHtml(data.marriage.partner_name)}</b>${when}</span>
        <button class="ghost small danger" id="member-divorce">Развестись</button></div>`;
    } else {
      out += `<div class="rel-row"><span class="muted">Вы ни с кем не в браке.</span>${
        data.can_restore_marriage ? `<button class="ghost small" id="member-restore-marriage">${icon("undo")}Вернуть брак (72ч)</button>` : ""}</div>`;
    }
    if (data.relationship) {
      const r = data.relationship;
      const lvl = escapeHtml(r.level_name || `ур. ${r.level}`);
      out += `<div class="rel-row"><span>${icon("heart")}Отношения с <b>${escapeHtml(r.partner_name)}</b> <span class="muted">· ${lvl} · ${icon("spark")}${r.sparks}</span></span>
        <button class="ghost small danger" id="member-relbreak">Расторгнуть</button></div>`;
      out += `<div class="rel-row"><span>${icon("shield")}Презик (защита от беременности): <b>${r.contraception ? "вкл" : "выкл"}</b></span>
        <button class="ghost small" id="member-contra" data-on="${r.contraception ? 1 : 0}">${r.contraception ? "Снять" : "Надеть"}</button></div>`;
      out += `<div class="rel-propose"><label><span>Действие с партнёром</span></label>
        <div class="member-target-list" id="member-gestures"><span class="muted">загрузка…</span></div></div>`;
      // Фарм искр — сворачиваемая секция со стрелкой, как у РП-действий.
      out += `<div class="card farm-card">
        <div class="action-head">
          <h4>${icon("spark")}Фарм искр</h4>
          <button class="disclosure ghost small" data-farm-expand aria-expanded="${memberFarmExpanded ? "true" : "false"}" title="Раскрыть">${icon("chevron")}</button>
        </div>
        <div class="action-body${memberFarmExpanded ? "" : " collapsed"}">
          <button class="member-farm-btn ${r.bonus_available ? "act-ready" : "act-dim"}" id="member-bonus" ${r.bonus_available ? "" : "disabled"}>
            ${r.bonus_available ? `${icon("spark")}Забрать бонус искр` : `${icon("clock")}Бонус через ${escapeHtml(r.bonus_wait || "")}`}
          </button>
          <div class="farm-actions-head">
            <span class="muted">Действия отношений — открываются по уровню пары</span>
            <label class="check quiet-toggle push">
              <input type="checkbox" id="member-quiet-toggle" ${memberQuietMode ? "checked" : ""}>
              <span class="muted">Тихо (не публиковать в чат)</span>
            </label>
          </div>
          <div class="farm-actions" id="member-rp-actions"><span class="muted">загрузка…</span></div>
        </div>
      </div>`;
    } else {
      out += `<div class="rel-row"><span class="muted">Вы ни с кем не в отношениях.</span>${
        data.can_restore_rel ? `<button class="ghost small" id="member-restore-rel">${icon("undo")}Вернуть отношения (72ч)</button>` : ""}</div>`;
    }
    // Пол — «профиль для отнов»: влияет на подбор фото-реакции в паре.
    const genders = [["м", `${icon("mars")} М`], ["ж", `${icon("venus")} Ж`], ["др", `${icon("gender-x")} Др`]];
    out += `<div class="rel-propose"><label><span>Мой пол <span class="muted">(для фото-реакций в паре)</span></span></label>
      <div class="member-target-list">${genders.map(([g, lbl]) =>
        `<button class="ghost small member-gender${data.gender === g ? " active" : ""}" data-gender="${g}">${lbl}</button>`).join("")}</div></div>`;
    if (!data.marriage) {
      out += `<div class="rel-propose">
        <label><span>Сделать предложение брака</span>
          <input type="text" id="member-target-q" placeholder="Имя или @username участника" autocomplete="off"></label>
        <div id="member-target-list" class="member-target-list"></div>
      </div>`;
    }
    el.innerHTML = out;
    $("#member-nick-save").addEventListener("click", memberSetNick);
    $("#member-top-btn").addEventListener("click", openMemberTop);
    $("#member-warns-btn").addEventListener("click", openMemberWarns);
    $("#member-rewards-btn").addEventListener("click", openMemberRewards);
    if (data.marriage) $("#member-divorce").addEventListener("click", memberDivorce);
    if (data.relationship) {
      $("#member-relbreak").addEventListener("click", memberRelBreak);
      $("#member-contra").addEventListener("click", () =>
        memberSetContra($("#member-contra").dataset.on !== "1"));
      loadMemberGestures();
      loadMemberRpActions();
      $("[data-farm-expand]").addEventListener("click", (e) => {
        const btn = e.currentTarget;
        const body = btn.closest(".farm-card").querySelector(".action-body");
        const collapsed = body.classList.toggle("collapsed");
        btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
        memberFarmExpanded = !collapsed;
      });
      const bonusBtn = $("#member-bonus");
      if (bonusBtn && !bonusBtn.disabled) bonusBtn.addEventListener("click", memberFarmBonus);
      const quietToggle = $("#member-quiet-toggle");
      if (quietToggle) quietToggle.addEventListener("change", () => {
        memberQuietMode = quietToggle.checked;
      });
    }
    $$(".member-gender").forEach((btn) =>
      btn.addEventListener("click", () => memberSetGender(btn.dataset.gender)));
    if (!data.marriage && data.can_restore_marriage)
      $("#member-restore-marriage").addEventListener("click", () => memberRestore("marriage"));
    if (!data.relationship && data.can_restore_rel)
      $("#member-restore-rel").addEventListener("click", () => memberRestore("rel2"));
    if (!data.marriage) wireMemberTargetSearch();
  } catch (err) {
    el.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

async function memberDivorce() {
  if (!confirm("Развестись? Вернуть брак можно будет в течение 72 часов.")) return;
  try {
    await api("/api/member/divorce", { method: "POST", body: { chat_id: memberCurrentChat() } });
    say("#member-toast", "Развод оформлен");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberRelBreak() {
  if (!confirm("Расторгнуть отношения? Вернуть можно будет в течение 72 часов.")) return;
  try {
    await api("/api/member/rel-break", { method: "POST", body: { chat_id: memberCurrentChat() } });
    say("#member-toast", "Отношения расторгнуты");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberRestore(kind) {
  try {
    await api("/api/member/restore", { method: "POST", body: { chat_id: memberCurrentChat(), kind } });
    say("#member-toast", kind === "marriage" ? "Брак восстановлен" : "Отношения восстановлены");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberSetContra(on) {
  try {
    await api("/api/member/rel-contraception", { method: "POST", body: { chat_id: memberCurrentChat(), on } });
    say("#member-toast", on ? "Презик надет" : "Презик снят");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberSetGender(gender) {
  try {
    await api("/api/member/gender", { method: "POST", body: { chat_id: memberCurrentChat(), gender } });
    say("#member-toast", "Пол обновлён");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberSetNick() {
  const nickname = $("#member-nick").value.trim();
  try {
    await api("/api/member/nickname", { method: "POST", body: { chat_id: memberCurrentChat(), nickname } });
    say("#member-toast", nickname ? "Ник обновлён" : "Ник снят");
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

function memberModal(title, innerHtml) {
  const overlay = document.createElement("div");
  overlay.className = "keys-overlay";
  overlay.innerHTML = `<div class="card user-info-card"><h3>${title}</h3>${innerHtml}
    <div class="form-foot"><button class="ghost" data-close>Закрыть</button></div></div>`;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector("[data-close]").addEventListener("click", () => overlay.remove());
  document.body.appendChild(overlay);
}

async function openMemberTop() {
  try {
    const d = await api(`/api/member/top?chat_id=${memberCurrentChat()}`);
    const rows = (d.top || []).map((t) =>
      `<div class="info-row"><span>${t.rank}. ${escapeHtml(t.name)}${t.me ? " <span class='muted'>(вы)</span>" : ""}</span><b>${t.messages}</b></div>`
    ).join("") || `<div class="muted">Пусто</div>`;
    memberModal(`${icon("chart")}Топ по сообщениям`, rows + (d.my_rank ? `<div class="muted mt-1">Ваше место: #${d.my_rank}</div>` : ""));
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function openMemberWarns() {
  try {
    const d = await api(`/api/member/warns?chat_id=${memberCurrentChat()}`);
    const rows = (d.warns || []).map((w) =>
      `<div class="info-row"><span>${w.reason ? escapeHtml(w.reason) : "без причины"}</span><b class="muted">${w.created_at ? escapeHtml(w.created_at.slice(0, 10)) : ""}</b></div>`
    ).join("") || `<div class="muted">${icon("check")}Варнов нет</div>`;
    memberModal(`${icon("alert")}Мои варны`, rows);
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function openMemberRewards() {
  try {
    const d = await api(`/api/member/rewards?chat_id=${memberCurrentChat()}`);
    const rows = (d.rewards || []).map((r) =>
      `<div class="info-row"><span>${icon("medal")}${r.degree} · ${r.reason ? escapeHtml(r.reason) : "без причины"}</span><b class="muted">${r.created_at ? escapeHtml(r.created_at.slice(0, 10)) : ""}</b></div>`
    ).join("") || `<div class="muted">Наград пока нет</div>`;
    memberModal(`${icon("medal")}Мои награды`, rows);
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function loadMemberGestures() {
  const box = $("#member-gestures");
  if (!box) return;
  try {
    const d = await api("/api/member/gestures");
    box.innerHTML = (d.gestures || []).map((g) =>
      `<button class="ghost small member-gesture" data-key="${escapeHtml(g.key)}">${escapeHtml(g.name)}</button>`
    ).join("") || `<span class="muted">нет</span>`;
    $$(".member-gesture").forEach((btn) => btn.addEventListener("click", () => memberDoGesture(btn.dataset.key)));
  } catch (err) { box.innerHTML = `<span class="muted">${escapeHtml(err.message)}</span>`; }
}

async function memberDoGesture(key) {
  try {
    await api("/api/member/gesture", { method: "POST", body: { chat_id: memberCurrentChat(), key } });
    say("#member-toast", "Отправлено в чат");
  } catch (err) { say("#member-toast", err.message, "err"); }
}

async function memberFarmBonus() {
  try {
    const d = await api("/api/member/farm-bonus", { method: "POST", body: { chat_id: memberCurrentChat() } });
    say("#member-toast", `+${d.amount} искр (баланс: ${d.balance})`);
    loadMemberRelStatus();
  } catch (err) { say("#member-toast", err.message, "err"); }
}

// Раскрыт ли блок «Фарм искр» — чтобы после действия перерисовка не схлопывала его.
let memberFarmExpanded = false;
// Тихий режим фарма: если включён, действие не публикуется в чат (искры всё равно начисляются).
let memberQuietMode = false;

async function loadMemberRpActions() {
  const box = $("#member-rp-actions");
  if (!box) return;
  try {
    const d = await api(`/api/member/rp-actions?chat_id=${memberCurrentChat()}`);
    box.innerHTML = (d.actions || []).map((a) => {
      let meta;
      if (a.locked) meta = `${icon("crown")}ур. ${a.level}`;
      else if (a.on_cooldown) meta = `${icon("clock")}${escapeHtml(a.wait || "")}`;
      else meta = `${icon("spark")}+${a.reward}`;
      return `<button class="farm-action ${a.available ? "act-ready" : "act-dim"}" data-key="${escapeHtml(a.key)}" ${a.available ? "" : "disabled"}>
        <span class="farm-action-name">${escapeHtml(a.name)}</span>
        <span class="farm-action-meta">${meta}</span></button>`;
    }).join("") || `<span class="muted">нет</span>`;
    $$(".farm-action:not([disabled])").forEach((btn) =>
      btn.addEventListener("click", () => memberDoRpAction(btn.dataset.key)));
  } catch (err) { box.innerHTML = `<span class="muted">${escapeHtml(err.message)}</span>`; }
}

async function memberDoRpAction(key) {
  try {
    const d = await api("/api/member/rp-action", {
      method: "POST",
      body: { chat_id: memberCurrentChat(), key, quiet: memberQuietMode },
    });
    say("#member-toast", `+${d.amount} искр · баланс ${d.balance} · ур. ${d.level} (${d.level_name})`);
    loadMemberRelStatus();  // обновит баланс/уровень; секция фарма останется раскрытой
  } catch (err) { say("#member-toast", err.message, "err"); }
}

function wireMemberTargetSearch() {
  const input = $("#member-target-q");
  const list = $("#member-target-list");
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { list.innerHTML = ""; return; }
      try {
        const data = await api(`/api/member/chat-members?q=${encodeURIComponent(q)}`);
        const members = data.members || [];
        list.innerHTML = members.length
          ? members.map((m) => `<button class="ghost small member-target" data-id="${m.user_id}">${
              escapeHtml(m.full_name || (m.username ? "@" + m.username : String(m.user_id)))}</button>`).join("")
          : `<span class="muted">Никого не найдено</span>`;
        $$(".member-target").forEach((btn) =>
          btn.addEventListener("click", () => memberPropose(Number(btn.dataset.id), btn.textContent.trim())));
      } catch (err) {
        list.innerHTML = `<span class="muted">${escapeHtml(err.message)}</span>`;
      }
    }, 300);
  });
}

async function memberPropose(targetId, name) {
  if (!confirm(`Отправить «${name}» предложение брака? Оно появится в чате — партнёр подтвердит его там.`)) return;
  try {
    await api("/api/member/propose-marriage", { method: "POST", body: { chat_id: memberCurrentChat(), target_id: targetId } });
    say("#member-toast", "Предложение отправлено в чат");
    $("#member-target-q").value = "";
    $("#member-target-list").innerHTML = "";
  } catch (err) { say("#member-toast", err.message, "err"); }
}

// --- горячие клавиши ------------------------------------------------------
// Панель — рабочий инструмент: модератор ищет человека десятки раз за смену, и
// каждый раз тянуться к полю мышью долго. Клавиши не перехватываются, пока
// человек печатает, иначе «/» в тексте сообщения увело бы фокус.

const KEY_HINTS = [
  ["/", "перейти к поиску на текущей вкладке"],
  ["Esc", "очистить поиск, закрыть окно"],
  ["T", "сменить тему"],
  ["1…8", "переключить раздел"],
  ["?", "эта шпаргалка"],
];

function isTyping(el) {
  return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function activeSearchInput() {
  const view = $$(".view").find((v) => !v.classList.contains("hidden"));
  return view ? view.querySelector('input[type="text"][id$="-q"]') : null;
}

function toggleKeysHelp(force) {
  const existing = $(".keys-overlay");
  if (existing && force !== true) { existing.remove(); return; }
  if (existing) return;
  const rows = KEY_HINTS
    .map(([key, what]) => `<dt><kbd>${escapeHtml(key)}</kbd></dt><dd>${escapeHtml(what)}</dd>`)
    .join("");
  const overlay = document.createElement("div");
  overlay.className = "keys-overlay";
  overlay.innerHTML = `
    <div class="keys-card" role="dialog" aria-label="Горячие клавиши">
      <h3>${icon("keyboard")}Горячие клавиши</h3>
      <dl>${rows}</dl>
    </div>`;
  overlay.addEventListener("click", () => overlay.remove());
  document.body.appendChild(overlay);
}

on("#keys-help", "click", () => toggleKeysHelp());

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  // На страницах кабинета админская оболочка вообще не отдана сервером.
  // Горячие клавиши тогда не нужны, но отсутствие #app не должно ронять JS.
  const adminShell = $("#app");
  if (!adminShell || adminShell.classList.contains("hidden")) return;

  if (e.key === "Escape") {
    const overlay = $(".keys-overlay");
    if (overlay) { overlay.remove(); return; }
    const search = activeSearchInput();
    if (search && search.value) {
      search.value = "";
      search.dispatchEvent(new Event("input"));
    } else if (isTyping(document.activeElement)) {
      document.activeElement.blur();
    }
    return;
  }

  if (isTyping(document.activeElement)) return;

  if (e.key === "/") {
    const search = activeSearchInput();
    if (search) { e.preventDefault(); search.focus(); search.select(); }
  } else if (e.key === "?") {
    toggleKeysHelp();
  } else if (e.key === "t" || e.key === "е") {  // «е» — та же клавиша в русской раскладке
    toggleTheme();
  } else if (/^[1-8]$/.test(e.key)) {
    const buttons = $$(".nav-btn").filter((b) => !b.classList.contains("hidden"));
    const target = buttons[Number(e.key) - 1];
    if (target) target.click();
  }
});

// --- каркас ---------------------------------------------------------------

function showApp() {
  if (!$("#app")) {
    location.replace("/admin/send");
    return;
  }
  $("#auth").classList.add("hidden");
  $("#member")?.classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#who").textContent = `${me.username} · ${me.role === "owner" ? "владелец" : "администратор"}`;
  if (me.role === "owner") $$(".owner-only").forEach((el) => el.classList.remove("hidden"));
  renderTgLink();
  loadRoles();
  loadChats();
  const nav = navFromUrl();
  const requested = nav.panel === "admin" ? nav.tab : null;
  const button = $$(".nav-btn").find((b) =>
    b.dataset.view === requested && !b.classList.contains("hidden"));
  switchAdminView(button ? requested : "send", false);
}

// --- привязка персонала к Telegram (доступ к экрану участника) ------------
// Персонал (admin/owner) видит либо форму привязки (код из бота), либо,
// если уже привязан, кнопку перехода на тот же read-only экран, что видят
// обычные участники — под своим собственным tg-аккаунтом.

function renderTgLink() {
  const linked = !!(me && me.tg_user_id);
  $("#tg-link-unlinked").classList.toggle("hidden", linked);
  $("#tg-link-linked").classList.toggle("hidden", !linked);
  if (linked) {
    $("#tg-link-status").innerHTML =
      `${icon("check")}<span>Привязан к Telegram: ${escapeHtml(me.tg_full_name || "без имени")}</span>`;
  }
}

async function refreshMe() {
  try {
    const state = await api("/api/me");
    if (state.authenticated) me = state;
  } catch (err) {
    // тихо — блок привязки просто не обновится сразу, следующая
    // перезагрузка страницы всё равно подхватит актуальное состояние
  }
}

// Слушатель вешаем один раз при загрузке страницы, как у соседних кнопок
// этого экрана: настройки перерисовывают только свой список, а карточка
// рубильника живёт в разметке и никуда не девается.
on("#infinite-toggle", "change", saveInfiniteMoney);

on("#tg-link-save", "click", async () => {
  const code = $("#tg-link-code").value.trim();
  if (!code) return;
  try {
    const result = await api("/api/link-telegram", { method: "POST", body: { code } });
    $("#tg-link-code").value = "";
    await refreshMe();
    renderTgLink();
    say("#global-msg", result.merged ? "Аккаунты объединены, Telegram привязан" : "Telegram привязан");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

on("#tg-link-open-member", "click", () => {
  writeNavUrl("member", "prof");
  showMember();
});

// Роли берём с сервера, а не хардкодим: их могли переименовать командой в чате,
// и список в панели должен совпадать с тем, что люди видят в Telegram.
async function loadRoles() {
  try {
    const data = await api("/api/roles");
    roleCatalog = data.roles || [];
    const options = `<option value="">Любая</option>` + roleCatalog
      .map((r) => `<option value="${r.key}">${escapeHtml(r.name)}</option>`)
      .join("");
    ["#members-role", "#mod-role"].forEach((sel) => { $(sel).innerHTML = options; });
  } catch (err) {
    // без справочника фильтр просто останется пустым — остальная панель работает
  }
}

// Мобильный бургер админки: раскрывает список разделов. На широком экране
// кнопки не видно, обработчик просто не срабатывает.
function навБургер() { return $("#nav-burger"); }

function закрытьНавМеню() {
  const бургер = навБургер();
  if (!бургер) return;
  бургер.closest(".sidebar").classList.remove("open");
  бургер.setAttribute("aria-expanded", "false");
}

// Подпись на бургере — название текущего раздела, без цифры-бейджа жалоб:
// текст берём только из текстовых узлов кнопки.
function подписьРаздела(btn) {
  return [...btn.childNodes]
    .filter((n) => n.nodeType === Node.TEXT_NODE)
    .map((n) => n.textContent).join("").trim();
}

if (навБургер()) {
  навБургер().addEventListener("click", () => {
    const открыт = навБургер().closest(".sidebar").classList.toggle("open");
    навБургер().setAttribute("aria-expanded", открыт ? "true" : "false");
  });
}

function switchAdminView(view, push = true) {
  const btn = $$(".nav-btn").find((b) =>
    b.dataset.view === view && !b.classList.contains("hidden"));
  if (!btn) return;
  writeNavUrl("admin", view, push);
    $$(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const группа = btn.closest("details.nav-group");
    if (группа) группа.open = true;
    const метка = $("#nav-burger-label");
    if (метка) метка.textContent = подписьРаздела(btn);
    закрытьНавМеню();
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${view}`).classList.remove("hidden");
    if (view === "settings") loadSettings();
    if (view === "users") loadUsers();
    if (view === "stats") loadStatsData();
    if (view === "logs") loadLogs();
    if (view === "stock") { loadStockData(); loadChatEvents(); }
    if (view === "tgadmins") loadTgAdmins();
    if (view === "chatroles") loadChatRoles();
    if (view === "moderation") { loadRestRequests(); loadWordFilter(); }
    if (view === "confirmations") loadMarketRequests();
    if (view === "complaints") loadComplaintTargets();
    if (view === "actions") { loadActions(); loadGestures(); loadProposeActions(); }
    if (view === "cmdtree") { loadCommandTree(); loadRewardLevels(); }
    if (view === "chatsettings") loadChatSettings();
    // Лента живёт только на своей вкладке: иначе SSE-соединение и опрос БД
    // продолжались бы всё время, пока панель просто открыта.
    if (view === "send") loadFeed(); else closeFeedStream();
}

$$(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchAdminView(btn.dataset.view));
});

// Вкладки экрана участника — привязываем один раз (кнопки статичны в разметке).
$$(".member-tab").forEach((btn) =>
  btn.addEventListener("click", () => switchMemberTab(btn.dataset.mtab)));

window.addEventListener("popstate", () => {
  if (!me) return;
  const nav = navFromUrl();
  if (me.role === "member") {
    showMember();
  } else if (nav.panel === "member" && me.tg_user_id) {
    showMember();
  } else {
    showApp();
  }
});

// ===== Дерево команд (админ) ===============================================
let _cmdTree = null;  // кэш ответа для клиентского поиска/локального обновления
// Раскрытые категории — по названию. Живут отдельно от DOM, потому что
// renderCommandTree() пересобирает разметку целиком.
const _cmdtreeOpen = new Set();

async function loadCommandTree() {
  const body = $("#cmdtree-body");
  body.innerHTML = skeleton(4);
  try {
    _cmdTree = await api("/api/command-tree");
    renderCommandTree();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderCommandTree() {
  const body = $("#cmdtree-body");
  if (!body || !_cmdTree) return;
  const q = ($("#cmdtree-q").value || "").trim().toLowerCase();
  const names = _cmdTree.level_names || {};
  const canEdit = _cmdTree.can_edit;
  const lvlName = (l) => escapeHtml(names[String(l)] || ("ур. " + l));
  const options = (sel) => [0, 1, 2, 3].map((l) =>
    `<option value="${l}"${l === sel ? " selected" : ""}>${lvlName(l)}</option>`).join("");
  // Свой срок автоочистки. Пусто в поле = «как у всех»: показываем общий срок
  // подсказкой в placeholder, чтобы не приходилось искать его в настройках.
  const dflt = _cmdTree.cleanup_default;
  const cleanupCtl = (c) => {
    // Команду, которую бот не отличает в чате от соседней с такой же фразой,
    // своим сроком не настроить — поле для неё было бы обманом.
    if (!c.cleanup_targetable) {
      return `<span class="muted cmd-cleanup-na"
        title="Эту команду бот не отличает в чате от соседней с такой же фразой — свой срок ей не задать.">—</span>`;
    }
    if (!canEdit) {
      return `<span class="chip${c.cleanup_minutes != null ? " chip-accent" : ""}">${c.cleanup_minutes != null ? c.cleanup_minutes : dflt} мин</span>`;
    }
    return `<span class="cmd-cleanup-wrap">
      <input type="number" class="cmd-cleanup" data-key="${escapeHtml(c.key)}" min="0"
        max="${_cmdTree.cleanup_max}" step="1" placeholder="${dflt}"
        title="Через сколько минут убирать эту команду из чата жалоб. Пусто — общий срок (${dflt} мин.), 0 — не убирать."
        value="${c.cleanup_minutes === null || c.cleanup_minutes === undefined ? "" : c.cleanup_minutes}" autocomplete="off">
      <span class="muted">мин</span></span>`;
  };
  let out = "";
  let shown = 0;
  for (const cat of _cmdTree.categories) {
    const cmds = cat.commands.filter((c) =>
      !q || c.key.toLowerCase().includes(q) || c.phrase.toLowerCase().includes(q));
    if (!cmds.length) continue;
    shown += cmds.length;
    // Во время поиска категории с совпадениями раскрыты принудительно, иначе
    // результат поиска был бы списком закрытых заголовков. Ручные раскрытия
    // при этом не теряются: они живут в _cmdtreeOpen и вернутся, когда строку
    // поиска очистят.
    const open = q || _cmdtreeOpen.has(cat.category);
    out += `<details class="cmdtree-cat fold" data-cat="${escapeHtml(cat.category)}"${open ? " open" : ""}>
      <summary><h3>${escapeHtml(cat.category)}</h3><span class="fold-note">${cmds.length}</span></summary>`;
    for (const c of cmds) {
      const ctl = (canEdit && c.overridable)
        ? `<select class="cmd-level" data-key="${escapeHtml(c.key)}">${options(c.level)}</select>`
        : `<span class="chip${c.overridden ? " chip-accent" : ""}">${lvlName(c.level)}</span>`;
      const reset = (canEdit && c.overridable && c.overridden)
        ? `<button class="ghost small cmd-reset" data-key="${escapeHtml(c.key)}" title="Сбросить к умолчанию">${icon("undo")}</button>` : "";
      out += `<div class="cmdtree-row">
        <div class="cmdtree-cmd"><code>${escapeHtml(c.key)}</code><span class="cmdtree-phrase">${escapeHtml(c.phrase)}</span></div>
        <div class="cmdtree-ctl">${cleanupCtl(c)}${ctl}${reset}</div></div>`;
    }
    out += `</details>`;
  }
  body.innerHTML = out || `<div class="empty">${icon("empty")}<span>Ничего не найдено</span></div>`;
  if (canEdit) {
    $$(".cmd-level").forEach((sel) => sel.addEventListener("change", () => cmdSetLevel(sel.dataset.key, Number(sel.value))));
    $$(".cmd-reset").forEach((btn) => btn.addEventListener("click", () => cmdSetLevel(btn.dataset.key, null)));
    // change, а не input: сохранять на каждую нажатую цифру — это запрос на
    // «1», потом на «15», потом на «150».
    $$(".cmd-cleanup").forEach((inp) => inp.addEventListener("change", () => {
      const raw = inp.value.trim();
      cmdSetCleanup(inp.dataset.key, raw === "" ? null : Number(raw));
    }));
  }
  // Запоминаем раскрытые категории: renderCommandTree() пересобирает разметку
  // целиком (после правки уровня, при поиске), и без этого блок захлопывался
  // бы прямо под руками.
  $$("#cmdtree-body .cmdtree-cat").forEach((el) => {
    el.addEventListener("toggle", () => {
      if (el.open) _cmdtreeOpen.add(el.dataset.cat);
      else _cmdtreeOpen.delete(el.dataset.cat);
      syncCmdtreeToggleAll();
    });
  });
  $("#cmdtree-count").textContent = q
    ? `Найдено команд: ${shown}`
    : `Команд всего: ${shown}`;
  syncCmdtreeToggleAll();
}

// Кнопка «Раскрыть все» / «Свернуть все» — её надпись должна отражать то, что
// произойдёт по нажатию, поэтому считаем текущее состояние после каждой смены.
function syncCmdtreeToggleAll() {
  const btn = $("#cmdtree-toggle-all");
  if (!btn) return;
  const cats = $$("#cmdtree-body .cmdtree-cat");
  const allOpen = cats.length > 0 && cats.every((el) => el.open);
  btn.dataset.open = allOpen ? "1" : "0";
  btn.textContent = allOpen ? "Свернуть все" : "Раскрыть все";
  btn.disabled = !cats.length;
}

async function cmdSetLevel(key, level) {
  try {
    const d = await api("/api/command-tree/level", { method: "POST", body: { command_key: key, level } });
    for (const cat of _cmdTree.categories) {
      const c = cat.commands.find((x) => x.key === key);
      if (c) { c.level = d.level; c.overridden = d.overridden; }
    }
    renderCommandTree();
    say("#global-msg", "Уровень команды обновлён");
  } catch (err) { say("#global-msg", err.message, "err"); renderCommandTree(); }
}

async function cmdSetCleanup(key, minutes) {
  try {
    const d = await api("/api/command-tree/cleanup", { method: "POST", body: { command_key: key, minutes } });
    for (const cat of _cmdTree.categories) {
      const c = cat.commands.find((x) => x.key === key);
      if (c) c.cleanup_minutes = d.cleanup_minutes;
    }
    say("#global-msg", d.cleanup_minutes === null
      ? "Команда снова чистится по общему сроку"
      : (d.cleanup_minutes === 0 ? "Эта команда больше не удаляется" : `Очистка команды: ${d.cleanup_minutes} мин.`));
  } catch (err) { say("#global-msg", err.message, "err"); renderCommandTree(); }
}

const _cmdtreeSearch = $("#cmdtree-q");
if (_cmdtreeSearch) _cmdtreeSearch.addEventListener("input", renderCommandTree);

const _cmdtreeToggleAll = $("#cmdtree-toggle-all");
if (_cmdtreeToggleAll) {
  _cmdtreeToggleAll.addEventListener("click", () => {
    const open = _cmdtreeToggleAll.dataset.open !== "1";
    _cmdtreeOpen.clear();
    if (open) for (const cat of (_cmdTree?.categories || [])) _cmdtreeOpen.add(cat.category);
    // Переключаем прямо в DOM, не перерисовывая: перерисовка сбросила бы
    // позицию прокрутки и открытые <select> с уровнями.
    $$("#cmdtree-body .cmdtree-cat").forEach((el) => { el.open = open; });
    syncCmdtreeToggleAll();
  });
}

// ===== Пороги наград (владелец) ============================================
let _rewardLevels = null;

async function loadRewardLevels() {
  const body = $("#reward-levels-body");
  body.innerHTML = skeleton(2);
  try {
    _rewardLevels = await api("/api/reward-levels");
    renderRewardLevels();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderRewardLevels() {
  const body = $("#reward-levels-body");
  if (!body || !_rewardLevels) return;
  const names = _rewardLevels.level_names || {};
  const canEdit = _rewardLevels.can_edit;
  const lvlName = (l) => escapeHtml(names[String(l)] || ("ур. " + l));
  const levels = [0, 1, 2, 3, 99];
  const options = (sel) => levels.map((l) =>
    `<option value="${l}"${l === sel ? " selected" : ""}>${lvlName(l)}</option>`).join("");
  let out = `<div class="cmdtree-cat">`;
  for (const d of _rewardLevels.degrees) {
    const ctl = canEdit
      ? `<select class="reward-level" data-degree="${d.degree}">${options(d.level)}</select>`
      : `<span class="chip${d.overridden ? " chip-accent" : ""}">${lvlName(d.level)}</span>`;
    const reset = (canEdit && d.overridden)
      ? `<button class="ghost small reward-reset" data-degree="${d.degree}" title="Сбросить к умолчанию">${icon("undo")}</button>` : "";
    out += `<div class="cmdtree-row">
      <div class="cmdtree-cmd"><code>${d.emoji} степень ${d.degree}</code></div>
      <div class="cmdtree-ctl">${ctl}${reset}</div></div>`;
  }
  out += `</div>`;
  body.innerHTML = out;
  if (canEdit) {
    $$(".reward-level").forEach((sel) => sel.addEventListener("change",
      () => rewardSetLevel(Number(sel.dataset.degree), Number(sel.value))));
    $$(".reward-reset").forEach((btn) => btn.addEventListener("click",
      () => rewardSetLevel(Number(btn.dataset.degree), null)));
  }
}

async function rewardSetLevel(degree, level) {
  try {
    const d = await api("/api/reward-levels/level", { method: "POST", body: { degree, level } });
    const row = _rewardLevels.degrees.find((x) => x.degree === degree);
    if (row) { row.level = d.level; row.overridden = d.overridden; }
    renderRewardLevels();
    say("#global-msg", "Порог награды обновлён");
  } catch (err) { say("#global-msg", err.message, "err"); renderRewardLevels(); }
}

// --- чаты -----------------------------------------------------------------

// Чат у панели один — рабочий. Раньше в каждом разделе висел выбор чата, и
// это был обман: бот работает только в рабочем, а остальные строки — остаток
// от прежнего использования. Админ выбирал чат и смотрел данные, которых нет.
let рабочийЧат = null;

function чат() {
  return рабочийЧат;
}

async function loadChats() {
  try {
    const data = await api("/api/chats");
    chats = data.chats;
    рабочийЧат = chats.length ? Number(chats[0].chat_id) : null;
    $("#chats-table").innerHTML = chats.map((c) => `
      <tr><td class="tc-head"><div class="person">${avatar(c.title, c.chat_id)}<span>${escapeHtml(c.title)}</span></div></td>
          <td class="mono" data-label="ID">${c.chat_id}</td>
          <td class="num" data-label="Людей">${c.members}</td></tr>`).join("")
      || empty(3, "Бот пока не видел ни одного чата");
    if (chats.length) {
      loadMembers();
      loadFeed();
      // При прямом входе на /admin/confirmations вкладка открывается раньше,
      // чем доезжает рабочий чат. Повторяем загрузку, когда chat_id уже есть.
      if (!$("#view-confirmations").classList.contains("hidden")) loadMarketRequests();
    }
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

async function loadMembers() {
  const chatId = чат();
  if (!chatId) return;
  $("#members-table").innerHTML = skeletonRows(5);
  try {
    const params = new URLSearchParams({
      chat_id: chatId,
      q: $("#members-q").value,
      role: $("#members-role").value,
      sort: $("#members-sort").value,
    });
    const data = await api(`/api/members?${params}`);
    $("#members-table").innerHTML = data.members.map((m) => `
      <tr><td class="tc-head"><div class="person">${avatar(m.full_name, m.user_id)}<span>${escapeHtml(m.full_name)}</span>${roleBadge(m) ? `<span class="tc-only">${roleBadge(m)}</span>` : ""}</div></td>
          <td class="tc-skip">${roleBadge(m)}</td>
          <td class="muted" data-label="Ник">${m.username ? "@" + escapeHtml(m.username) : ""}</td>
          <td class="mono" data-label="Сообщений">${m.message_count ?? 0}</td>
          <td class="mono" data-label="ID">${m.user_id}</td>
          <td class="right nowrap tc-actions">
            <button class="ghost small" data-userinfo="${m.user_id}" title="Информация о пользователе">${icon("id")}Инфо</button>
            <button class="ghost small" data-moderate="${m.user_id}"
              data-name="${escapeHtml(m.full_name)}" data-username="${escapeHtml(m.username || "")}"
              data-role="${escapeHtml(m.role || "")}" data-role-key="${escapeHtml(m.role_key || "")}"
              title="Открыть модерацию по этому участнику">${icon("shield")}Модерация</button>
          </td></tr>`).join("")
      || empty(6, "Никого не нашлось");

    $$("[data-userinfo]").forEach((btn) =>
      btn.addEventListener("click", () => openUserInfo(chatId, Number(btn.dataset.userinfo))));

    // Клик по кнопке в строке — сразу переносит человека в модерацию,
    // чтобы не приходилось переписывать ID руками.
    $$("[data-moderate]").forEach((btn) => {
      btn.addEventListener("click", () => {
        pickMember({
          user_id: Number(btn.dataset.moderate),
          full_name: btn.dataset.name,
          username: btn.dataset.username || null,
          role: btn.dataset.role || null,
          role_key: btn.dataset.roleKey || null,
        }, чат());
      });
    });
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

on("#members-role", "change", loadMembers);
on("#members-q", "input", () => {
  clearTimeout(window._memberSearch);
  window._memberSearch = setTimeout(loadMembers, 300);
});
on("#members-sort", "change", loadMembers);

// Карточка инфо о пользователе — общий рендер для админской модалки и экрана
// участника (своя инфа).
function userInfoHtml(info) {
  const line = (label, val) => `<div class="info-row"><span class="muted">${label}</span><b>${val}</b></div>`;
  const when = (s) => (s ? escapeHtml(String(s).slice(0, 16).replace("T", " ")) : "—");
  return `
    <h3>${icon("id")}${escapeHtml(info.name)}${info.username ? ` <span class="muted">@${escapeHtml(info.username)}</span>` : ""}</h3>
    ${line("Сообщений всего", info.messages)}
    ${line("За сутки / неделю / месяц", `${info.today} / ${info.week} / ${info.month}`)}
    ${info.rank ? line("Место в топе", "#" + info.rank) : ""}
    ${line("Первое появление", when(info.first_seen))}
    ${line("Последняя активность", when(info.last_active))}
    ${info.role ? line("Роль", escapeHtml(info.role)) : ""}
    ${line("Награды / варны", `${icon("medal")}${info.rewards} · ${icon("alert")}${info.warns}`)}
    ${line("Репутация", info.reputation)}
    <div class="mono muted mt-1">ID: ${info.user_id}</div>`;
}

async function openUserInfo(chatId, userId) {
  const overlay = document.createElement("div");
  overlay.className = "keys-overlay";
  overlay.innerHTML = `<div class="card user-info-card"><div class="muted">Загрузка…</div></div>`;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
  try {
    const info = await api(`/api/user-info?chat_id=${encodeURIComponent(chatId)}&user_id=${userId}`);
    overlay.querySelector(".user-info-card").innerHTML =
      userInfoHtml(info) + `<div class="form-foot"><button class="ghost" data-close>Закрыть</button></div>`;
    overlay.querySelector("[data-close]").addEventListener("click", () => overlay.remove());
  } catch (err) {
    overlay.querySelector(".user-info-card").innerHTML =
      `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// --- роли чата ------------------------------------------------------------
// Именные роли участников (chat_roles): их занимают, бронируют и освобождают в
// боте, панель только показывает. Не путать с ролями на вкладке «Чаты и люди» —
// там уровни прав, и приходят они из другого эндпоинта (/api/roles).

let chatRoleStatus = "";  // активный чип-фильтр; пусто — все роли

const CHAT_ROLE_STATUSES = [
  { key: "", label: "Все" },
  { key: "free", label: "Свободные" },
  { key: "taken", label: "Занятые" },
  { key: "reserved", label: "Забронированные" },
  { key: "pending", label: "На модерации" },
];

// Дата брони в местном формате. Сервер присылает ISO, но человеку нужен день и
// час, а не машинная строка.
function roleDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function rolePerson(person) {
  const name = person.full_name || `ID ${person.user_id}`;
  const nick = person.username ? ` <span class="muted">@${escapeHtml(person.username)}</span>` : "";
  return `<div class="person">${avatar(person.full_name, person.user_id)}
    <span>${escapeHtml(name)}${nick}</span></div>`;
}

// Строка состояния роли: у каждого статуса свой смысл, поэтому и текст разный —
// «свободна» это приглашение занять, а «забронирована» требует знать, до когда.
function roleState(role) {
  if (!role.approved) {
    return `<span class="role-state pending">${icon("alert")}Заявка на модерации</span>`;
  }
  if (role.status === "taken" && role.holder) {
    return `<span class="role-state taken">${icon("user")}Занята</span>${rolePerson(role.holder)}`;
  }
  if (role.status === "reserved" && role.reserved_by) {
    const till = roleDate(role.reserve_expires_at);
    const note = till ? `<span class="muted">бронь до ${escapeHtml(till)}</span>` : "";
    return `<span class="role-state reserved">${icon("clock")}Забронирована</span>
      ${rolePerson(role.reserved_by)}${note}`;
  }
  return `<span class="role-state free">${icon("check")}Свободна</span>`;
}

// --- РП-действия и себяшки ------------------------------------------------
// Правки пишутся в БД и поднимают флаг перечитки; бот подхватывает их в чатах
// за несколько секунд (см. /api/action-sets и panel_action_reload_loop в боте).
// Фразы содержат эмодзи — это данные (их шлёт бот в чат), а не оформление
// панели, поэтому показываем как есть.

let actionKind = "rp";

async function loadActions() {
  $("#synonyms-card").classList.toggle("hidden", actionKind !== "rp");
  $$("#actions-kind .chip").forEach((c) => c.classList.toggle("active", c.dataset.kind === actionKind));
  $("#actions-list").innerHTML = skeleton(4);
  try {
    const data = await api(`/api/action-sets/${actionKind}`);
    renderActions(data.actions);
    if (actionKind === "rp") renderSynonyms(data.synonyms || {});
  } catch (err) {
    $("#actions-list").innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderActions(actions) {
  if (!actions.length) {
    $("#actions-list").innerHTML = `<div class="card"><div class="empty">${icon("empty")}<span>Действий пока нет</span></div></div>`;
    return;
  }
  $("#actions-list").innerHTML = actions.map((a) => `
    <div class="card action-card${a.active ? "" : " off"}" data-action="${escapeHtml(a.key)}">
      <div class="action-head">
        <h3>${escapeHtml(a.key)} <span class="muted">${a.phrases.length}</span></h3>
        <div class="action-head-controls">
          <button class="ghost small ${a.active ? "" : "danger"}" data-toggle="${escapeHtml(a.key)}" data-active="${a.active ? 1 : 0}">
            ${icon("power")}${a.active ? "Включено" : "Выключено"}
          </button>
          <button class="disclosure ghost small" data-expand aria-expanded="false" title="Показать фразы">${icon("chevron")}</button>
        </div>
      </div>
      <div class="action-body collapsed">
        <div class="action-phrases">
          ${a.phrases.map((p) => `
            <div class="phrase-row" data-phrase="${p.id}">
              <span class="phrase-text">${escapeHtml(p.phrase)}</span>
              <button class="ghost small" data-edit-phrase="${p.id}" title="Изменить">${icon("edit")}</button>
              <button class="ghost small danger" data-del-phrase="${p.id}" title="Удалить">${icon("trash")}</button>
            </div>`).join("")}
        </div>
        <form class="row phrase-add" data-add-to="${escapeHtml(a.key)}">
          <input type="text" maxlength="512" placeholder="Новая фраза…" required autocomplete="off">
          <button class="ghost small" type="submit">${icon("plus")}Фраза</button>
        </form>
      </div>
    </div>`).join("");

  bindActionControls();
}

function bindActionControls() {
  $$("[data-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const body = btn.closest(".action-card").querySelector(".action-body");
      const nowCollapsed = body.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
    });
  });

  $$("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const active = btn.dataset.active !== "1";  // переключаем
      try {
        await api(`/api/action-sets/${actionKind}/actions/${encodeURIComponent(btn.dataset.toggle)}/active`,
                  { method: "POST", body: { active } });
        say("#global-msg", active ? "Действие включено" : "Действие выключено");
        loadActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-del-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Удалить эту фразу?")) return;
      try {
        await api(`/api/action-sets/${actionKind}/phrases/${btn.dataset.delPhrase}`, { method: "DELETE" });
        loadActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-edit-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".phrase-row");
      const current = row.querySelector(".phrase-text").textContent;
      const next = prompt("Новый текст фразы:", current);
      if (next === null || !next.trim()) return;
      try {
        await api(`/api/action-sets/${actionKind}/phrases/${btn.dataset.editPhrase}`,
                  { method: "PATCH", body: { phrase: next.trim() } });
        loadActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$(".phrase-add").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      const phrase = input.value.trim();
      if (!phrase) return;
      try {
        await api(`/api/action-sets/${actionKind}/phrases`,
                  { method: "POST", body: { key: form.dataset.addTo, phrase } });
        input.value = "";
        loadActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });
}

function renderSynonyms(synonyms) {
  const entries = Object.entries(synonyms);
  $("#synonyms-list").innerHTML = entries.length
    ? entries.map(([syn, key]) => `
      <div class="phrase-row" data-synonym="${escapeHtml(syn)}">
        <span class="phrase-text"><b>${escapeHtml(syn)}</b> <span class="muted">→</span> ${escapeHtml(key)}</span>
        <button class="ghost small danger" data-del-synonym="${escapeHtml(syn)}" title="Удалить">${icon("trash")}</button>
      </div>`).join("")
    : `<div class="empty"><span class="muted">Синонимов пока нет</span></div>`;

  $$("[data-del-synonym]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/action-sets/rp/synonyms/${encodeURIComponent(btn.dataset.delSynonym)}`, { method: "DELETE" });
        loadActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });
}

$$("#actions-kind .chip").forEach((chip) => {
  chip.addEventListener("click", () => { actionKind = chip.dataset.kind; loadActions(); });
});

on("#action-add", "submit", async (e) => {
  e.preventDefault();
  const key = $("#action-key").value.trim();
  const phrase = $("#action-phrase").value.trim();
  if (!key || !phrase) return;
  try {
    await api(`/api/action-sets/${actionKind}/phrases`, { method: "POST", body: { key, phrase } });
    say("#global-msg", `Действие «${key}» добавлено`);
    $("#action-key").value = "";
    $("#action-phrase").value = "";
    loadActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

on("#synonym-add", "submit", async (e) => {
  e.preventDefault();
  const synonym = $("#synonym-word").value.trim();
  const key = $("#synonym-key").value.trim();
  if (!synonym || !key) return;
  try {
    await api("/api/action-sets/rp/synonyms", { method: "POST", body: { synonym, key } });
    say("#global-msg", "Синоним добавлен");
    $("#synonym-word").value = "";
    $("#synonym-key").value = "";
    loadActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

// --- «Предложить действие» --------------------------------------------------
const PROPOSE_KIND_LABELS = { propose: "Предложение", agree: "Согласие", decline: "Отказ" };

async function loadProposeActions() {
  $("#propose-actions-list").innerHTML = skeleton(3);
  try {
    const data = await api("/api/propose-actions");
    renderProposeActions(data.actions, data.can_edit);
  } catch (err) {
    $("#propose-actions-list").innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderProposeActions(actions, canEdit) {
  if (!actions.length) {
    $("#propose-actions-list").innerHTML = `<div class="card"><div class="empty">${icon("empty")}<span>Действий пока нет</span></div></div>`;
    bindProposeActionControls(canEdit);
    return;
  }
  $("#propose-actions-list").innerHTML = actions.map((a) => `
    <div class="card action-card${a.active ? "" : " off"}" data-propose-action="${escapeHtml(a.key)}">
      <div class="action-head">
        <h3>${escapeHtml(a.key)}</h3>
        <div class="action-head-controls">
          ${canEdit ? `
            <button class="ghost small ${a.active ? "" : "danger"}" data-propose-toggle="${escapeHtml(a.key)}" data-active="${a.active ? 1 : 0}">
              ${icon("power")}${a.active ? "Включено" : "Выключено"}
            </button>` : `<span class="chip${a.active ? "" : " chip-muted"}">${a.active ? "Включено" : "Выключено"}</span>`}
          <button class="disclosure ghost small" data-propose-expand aria-expanded="false" title="Показать">${icon("chevron")}</button>
        </div>
      </div>
      <div class="action-body collapsed">
        ${["propose", "agree", "decline"].map((kind) => `
          <h4>${PROPOSE_KIND_LABELS[kind]}</h4>
          <div class="action-phrases">
            ${a.phrases[kind].map((p) => `
              <div class="phrase-row" data-phrase="${p.id}">
                <span class="phrase-text">${escapeHtml(p.phrase)}</span>
                ${canEdit ? `
                  <button class="ghost small" data-propose-edit-phrase="${p.id}" title="Изменить">${icon("edit")}</button>
                  <button class="ghost small danger" data-propose-del-phrase="${p.id}" title="Удалить">${icon("trash")}</button>` : ""}
              </div>`).join("") || `<div class="empty"><span class="muted">Фраз пока нет</span></div>`}
          </div>
          ${canEdit ? `
            <form class="row propose-phrase-add" data-propose-add-to="${escapeHtml(a.key)}" data-propose-kind="${kind}">
              <input type="text" maxlength="512" placeholder="Новая фраза…" required autocomplete="off">
              <button class="ghost small" type="submit">${icon("plus")}Фраза</button>
            </form>` : ""}
        `).join("")}
        <h4>Синонимы</h4>
        <div class="action-phrases">
          ${a.synonyms.map((s) => `
            <div class="phrase-row" data-propose-synonym="${escapeHtml(s)}">
              <span class="phrase-text">${escapeHtml(s)}</span>
              ${canEdit ? `<button class="ghost small danger" data-propose-del-synonym="${escapeHtml(s)}" title="Удалить">${icon("trash")}</button>` : ""}
            </div>`).join("") || `<div class="empty"><span class="muted">Синонимов пока нет</span></div>`}
        </div>
        ${canEdit ? `
          <form class="row" data-propose-synonym-add-to="${escapeHtml(a.key)}">
            <input type="text" maxlength="64" placeholder="новый синоним…" required autocomplete="off">
            <button class="ghost small" type="submit">${icon("plus")}Синоним</button>
          </form>
          <form class="row propose-settings" data-propose-settings-for="${escapeHtml(a.key)}">
            <label class="narrow"><span>Кулдаун, сек</span>
              <input type="number" min="1" max="86400" value="${a.cooldown_seconds}" data-field="cooldown_seconds" required autocomplete="off">
            </label>
            <label class="narrow"><span>Таймаут, сек</span>
              <input type="number" min="1" max="86400" value="${a.timeout_seconds}" data-field="timeout_seconds" required autocomplete="off">
            </label>
            <button class="ghost small" type="submit">${icon("check")}Сохранить</button>
          </form>` : `<p class="sub">Кулдаун ${a.cooldown_seconds}с, таймаут ${a.timeout_seconds}с</p>`}
      </div>
    </div>`).join("");
  bindProposeActionControls(canEdit);
}

function bindProposeActionControls(canEdit) {
  $$("[data-propose-expand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const body = btn.closest(".action-card").querySelector(".action-body");
      const nowCollapsed = body.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
    });
  });
  if (!canEdit) return;

  $$("[data-propose-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const active = btn.dataset.active !== "1";
      try {
        await api(`/api/propose-actions/${encodeURIComponent(btn.dataset.proposeToggle)}/active`,
                  { method: "POST", body: { active } });
        say("#global-msg", active ? "Действие включено" : "Действие выключено");
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-del-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Удалить эту фразу?")) return;
      try {
        await api(`/api/propose-actions/phrases/${btn.dataset.proposeDelPhrase}`, { method: "DELETE" });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-edit-phrase]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".phrase-row");
      const current = row.querySelector(".phrase-text").textContent;
      const next = prompt("Новый текст фразы:", current);
      if (next === null || !next.trim()) return;
      try {
        await api(`/api/propose-actions/phrases/${btn.dataset.proposeEditPhrase}`,
                  { method: "PUT", body: { phrase: next.trim() } });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-add-to]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      const phrase = input.value.trim();
      if (!phrase) return;
      try {
        await api("/api/propose-actions/phrases", {
          method: "POST",
          body: { action_key: form.dataset.proposeAddTo, kind: form.dataset.proposeKind, phrase },
        });
        input.value = "";
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-del-synonym]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/propose-actions/synonyms/${encodeURIComponent(btn.dataset.proposeDelSynonym)}`, { method: "DELETE" });
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$("[data-propose-synonym-add-to]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      const synonym = input.value.trim().toLowerCase();
      if (!synonym) return;
      try {
        await api("/api/propose-actions/synonyms", {
          method: "POST", body: { synonym, action_key: form.dataset.proposeSynonymAddTo },
        });
        input.value = "";
        loadProposeActions();
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });

  $$(".propose-settings").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const cooldown = Number(form.querySelector('[data-field="cooldown_seconds"]').value);
      const timeout = Number(form.querySelector('[data-field="timeout_seconds"]').value);
      try {
        await api(`/api/propose-actions/${encodeURIComponent(form.dataset.proposeSettingsFor)}/settings`, {
          method: "POST", body: { cooldown_seconds: cooldown, timeout_seconds: timeout },
        });
        say("#global-msg", "Кулдаун/таймаут сохранены");
      } catch (err) { say("#global-msg", err.message, "err"); }
    });
  });
}

on("#propose-action-add", "submit", async (e) => {
  e.preventDefault();
  const action_key = $("#propose-action-key").value.trim();
  const phrase = $("#propose-action-phrase").value.trim();
  if (!action_key || !phrase) return;
  try {
    await api("/api/propose-actions/phrases", { method: "POST", body: { action_key, kind: "propose", phrase } });
    say("#global-msg", `Действие «${action_key}» добавлено`);
    $("#propose-action-key").value = "";
    $("#propose-action-phrase").value = "";
    loadProposeActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

on("#propose-synonym-add", "submit", async (e) => {
  e.preventDefault();
  const synonym = $("#propose-synonym-word").value.trim().toLowerCase();
  const action_key = $("#propose-synonym-key").value.trim();
  if (!synonym || !action_key) return;
  try {
    await api("/api/propose-actions/synonyms", { method: "POST", body: { synonym, action_key } });
    say("#global-msg", "Синоним добавлен");
    $("#propose-synonym-word").value = "";
    $("#propose-synonym-key").value = "";
    loadProposeActions();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

// --- Отн-жесты (админ): жест + фразы + слова-триггеры + фото ---------------

const GESTURE_PAIR_LABELS = { mf: "М + Ж", mm: "М + М", ff: "Ж + Ж", all: "Общие (любая пара)" };

on("#gesture-add", "submit", async (e) => {
  e.preventDefault();
  const key = $("#gesture-key").value.trim();
  const name = $("#gesture-name").value.trim();
  if (!key || !name) return;
  try {
    await api("/api/rel-gestures", { method: "POST", body: { key, name } });
    say("#global-msg", `Жест «${name}» добавлен`);
    $("#gesture-key").value = "";
    $("#gesture-name").value = "";
    loadGestures();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

async function loadGestures() {
  const box = $("#gestures-list");
  box.innerHTML = skeleton(3);
  try {
    const data = await api("/api/rel-gestures");
    const gestures = data.gestures || [];
    box.innerHTML = gestures.length
      ? gestures.map(gestureCard).join("")
      : `<div class="card"><div class="empty">${icon("empty")}<span>Жестов пока нет</span></div></div>`;
    bindGestureControls();
  } catch (err) {
    box.innerHTML = `<div class="card"><div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div>`;
  }
}

function gestureCard(g) {
  const k = escapeHtml(g.gesture_key);
  const kEnc = encodeURIComponent(g.gesture_key);
  const phrases = g.phrases.map((p) => `
    <div class="phrase-row"><span class="phrase-text">${escapeHtml(p.phrase)}</span>
      <button class="ghost small danger" data-gph-del="${p.id}" title="Удалить">${icon("trash")}</button></div>`).join("");
  const aliases = g.aliases.map((a) => `
    <span class="alias-chip">${escapeHtml(a)}<button data-gal-del="${escapeHtml(a)}" data-gkey="${k}" title="Убрать">×</button></span>`).join("");
  const photos = Object.entries(g.photos).map(([pairing, files]) => `
    <div class="gphotos">
      <div class="gphotos-head"><b>${GESTURE_PAIR_LABELS[pairing] || pairing}</b> <span class="muted">${files.length}</span>
        <label class="ghost small gphoto-up">${icon("image")}Загрузить
          <input type="file" accept="image/*" hidden data-gphoto-up="${k}" data-pairing="${pairing}"></label></div>
      <div class="gphoto-thumbs">${files.map((f) => `<span class="gthumb">
        <img loading="lazy" src="/api/rel-gestures/${kEnc}/photos/${pairing}/${encodeURIComponent(f)}" alt="">
        <button data-gphoto-del="${escapeHtml(f)}" data-gkey="${k}" data-pairing="${pairing}" title="Удалить">×</button></span>`).join("")}</div>
    </div>`).join("");
  return `
    <div class="card action-card${g.is_active ? "" : " off"}">
      <div class="action-head">
        <h3>${escapeHtml(g.name)} <span class="muted">${k}</span></h3>
        <div class="action-head-controls">
          <button class="ghost small ${g.is_active ? "" : "danger"}" data-gact="${k}" data-active="${g.is_active ? 1 : 0}">${icon("power")}${g.is_active ? "Включен" : "Выключен"}</button>
          <button class="ghost small danger" data-gdel="${k}" title="Удалить жест">${icon("trash")}</button>
          <button class="disclosure ghost small" data-gexpand aria-expanded="false" title="Раскрыть">${icon("chevron")}</button>
        </div>
      </div>
      <div class="action-body collapsed">
        <label><span>Ответная реакция снизу (моноблоком; <code>{actor}</code>/<code>{target}</code>)</span>
          <div class="row"><input type="text" maxlength="255" value="${escapeHtml(g.reply_template || "")}" data-greply-input="${k}" placeholder="{target} подмигивает {actor} в ответ." autocomplete="off">
            <button class="ghost small" data-greply="${k}">${icon("check")}Сохранить</button></div></label>
        <div class="gsub"><b>Слова-триггеры</b> <span class="muted">(что писать в чате: «отн подмигнуть»)</span>
          <div class="alias-list">${aliases || `<span class="muted">нет</span>`}</div>
          <form class="row alias-add" data-gkey="${k}"><input type="text" maxlength="64" placeholder="подмигнуть" required autocomplete="off">
            <button class="ghost small" type="submit">${icon("plus")}Слово</button></form></div>
        <div class="gsub"><b>Фразы</b> <span class="muted">(<code>{actor}</code>/<code>{target}</code>)</span>
          <div class="action-phrases">${phrases || `<span class="muted">нет</span>`}</div>
          <form class="row gphrase-add" data-gkey="${k}"><input type="text" maxlength="512" placeholder="{actor} подмигивает {target}." required autocomplete="off">
            <button class="ghost small" type="submit">${icon("plus")}Фраза</button></form></div>
        <div class="gsub"><b>Фото по полу пары</b>${photos}</div>
      </div>
    </div>`;
}

function bindGestureControls() {
  const reloadOr = async (fn) => { try { await fn(); loadGestures(); } catch (err) { say("#global-msg", err.message, "err"); } };

  $$("[data-gexpand]").forEach((btn) => btn.addEventListener("click", () => {
    const body = btn.closest(".action-card").querySelector(".action-body");
    const collapsed = body.classList.toggle("collapsed");
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }));
  $$("[data-gact]").forEach((btn) => btn.addEventListener("click", () => reloadOr(() =>
    api(`/api/rel-gestures/${encodeURIComponent(btn.dataset.gact)}/active`, { method: "POST", body: { active: btn.dataset.active !== "1" } }))));
  $$("[data-gdel]").forEach((btn) => btn.addEventListener("click", () => {
    if (!confirm("Удалить жест целиком (фразы и триггеры)? Фото останутся в папке.")) return;
    reloadOr(() => api(`/api/rel-gestures/${encodeURIComponent(btn.dataset.gdel)}`, { method: "DELETE" }));
  }));
  $$("[data-greply]").forEach((btn) => btn.addEventListener("click", () => {
    const val = btn.closest(".row").querySelector("[data-greply-input]").value;
    reloadOr(() => api(`/api/rel-gestures/${encodeURIComponent(btn.dataset.greply)}/reply`, { method: "POST", body: { reply: val } }));
  }));
  $$(".alias-add").forEach((form) => form.addEventListener("submit", (e) => {
    e.preventDefault();
    const alias = form.querySelector("input").value.trim();
    if (alias) reloadOr(() => api(`/api/rel-gestures/${encodeURIComponent(form.dataset.gkey)}/aliases`, { method: "POST", body: { alias } }));
  }));
  $$("[data-gal-del]").forEach((btn) => btn.addEventListener("click", () => reloadOr(() =>
    api(`/api/rel-gestures/${encodeURIComponent(btn.dataset.gkey)}/aliases/${encodeURIComponent(btn.dataset.galDel)}`, { method: "DELETE" }))));
  $$(".gphrase-add").forEach((form) => form.addEventListener("submit", (e) => {
    e.preventDefault();
    const phrase = form.querySelector("input").value.trim();
    if (phrase) reloadOr(() => api(`/api/rel-gestures/${encodeURIComponent(form.dataset.gkey)}/phrases`, { method: "POST", body: { phrase } }));
  }));
  $$("[data-gph-del]").forEach((btn) => btn.addEventListener("click", () => reloadOr(() =>
    api(`/api/rel-gestures/phrases/${btn.dataset.gphDel}`, { method: "DELETE" }))));
  $$("[data-gphoto-up]").forEach((inp) => inp.addEventListener("change", () => {
    if (!inp.files || !inp.files[0]) return;
    const fd = new FormData();
    fd.append("pairing", inp.dataset.pairing);
    fd.append("file", inp.files[0]);
    reloadOr(() => api(`/api/rel-gestures/${encodeURIComponent(inp.dataset.gphotoUp)}/photos`, { method: "POST", form: fd }));
  }));
  $$("[data-gphoto-del]").forEach((btn) => btn.addEventListener("click", () => reloadOr(() =>
    api(`/api/rel-gestures/${encodeURIComponent(btn.dataset.gkey)}/photos/${btn.dataset.pairing}/${encodeURIComponent(btn.dataset.gphotoDel)}`, { method: "DELETE" }))));
}

// --- жалобы ---------------------------------------------------------------
// Анонимность держит сервер: для анонимной жалобы он не отдаёт автора вовсе,
// поэтому показывать тут нечего и подменить нечем.

const COMPLAINT_STATES = {
  pending:  { icon: "clock", label: "на рассмотрении", cls: "reserved" },
  accepted: { icon: "check", label: "принята",         cls: "taken" },
  declined: { icon: "ban",   label: "отклонена",       cls: "free" },
};

let complaintTarget = null;

async function loadComplaintTargets() {
  try {
    const data = await api("/api/complaints");
    const badge = $("#complaints-badge");
    badge.textContent = data.pending_total;
    badge.classList.toggle("hidden", !data.pending_total);

    $("#complaints-targets").innerHTML = data.targets.length
      ? data.targets.map((t) => `
        <button class="picker-row${complaintTarget === t.target_id ? " picked" : ""}"
                data-complaint-target="${t.target_id}">
          ${avatar(t.full_name, t.target_id)}
          <span class="picker-name">${escapeHtml(t.full_name || `ID ${t.target_id}`)}
            ${t.username ? `<span class="muted">@${escapeHtml(t.username)}</span>` : ""}</span>
          ${t.pending ? `<span class="rights-count">${t.pending}</span>` : ""}
          <span class="muted">${t.total}</span>
        </button>`).join("")
      : `<div class="empty">${icon("check")}<span>Жалоб пока нет</span></div>`;

    $$("[data-complaint-target]").forEach((btn) => {
      btn.addEventListener("click", () => {
        complaintTarget = Number(btn.dataset.complaintTarget);
        loadComplaintTargets();
        loadComplaints();
      });
    });
    if (complaintTarget) loadComplaints();
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

async function loadComplaints() {
  if (!complaintTarget) return;
  $("#complaints-list").innerHTML = skeleton(3);
  try {
    const data = await api(`/api/complaints/${complaintTarget}`);
    const who = data.target?.full_name || `ID ${complaintTarget}`;
    $("#complaints-title").textContent = `Жалобы на ${who}`;

    $("#complaints-list").innerHTML = data.complaints.map((c) => {
      const state = COMPLAINT_STATES[c.status] || COMPLAINT_STATES.pending;
      const from = c.anonymous
        ? `<span class="right-chip" title="Автор скрыл себя — панель его не знает">${icon("eye-off")}анонимно</span>`
        : `<span class="right-chip">${icon("user")}${escapeHtml(c.reporter?.full_name || `ID ${c.reporter?.user_id}`)}</span>`;
      return `
        <div class="role-row" data-complaint="${c.id}">
          <div class="grow">
            <div class="role-name">${escapeHtml(c.reason || "без текста")}</div>
            <div class="role-info mt-1">
              ${from}
              <span class="muted">${escapeHtml(roleDate(c.created_at) || "")}</span>
              <span class="role-state ${state.cls}">${icon(state.icon)}${state.label}</span>
            </div>
          </div>
          <span class="role-actions">
            ${c.status !== "accepted" ? `<button class="ghost small ok" data-complaint-yes="${c.id}">${icon("check")}Принять</button>` : ""}
            ${c.status !== "declined" ? `<button class="ghost small" data-complaint-no="${c.id}">${icon("ban")}Отклонить</button>` : ""}
            <button class="ghost small danger" data-complaint-del="${c.id}" title="Удалить жалобу">${icon("trash")}</button>
          </span>
        </div>`;
    }).join("") || `<div class="empty">${icon("empty")}<span>Жалоб на этого человека нет</span></div>`;

    const act = async (id, fn, row) => {
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await fn(id);
        loadComplaintTargets();
        loadComplaints();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    };
    const setStatus = (status) => (id) =>
      api(`/api/complaints/${id}/status`, { method: "POST", body: { status } })
        .then(() => say("#global-msg", status === "accepted" ? "Жалоба принята" : "Жалоба отклонена"));

    $$("[data-complaint-yes]").forEach((b) =>
      b.addEventListener("click", () => act(b.dataset.complaintYes, setStatus("accepted"), b.closest("[data-complaint]"))));
    $$("[data-complaint-no]").forEach((b) =>
      b.addEventListener("click", () => act(b.dataset.complaintNo, setStatus("declined"), b.closest("[data-complaint]"))));
    $$("[data-complaint-del]").forEach((b) =>
      b.addEventListener("click", () => {
        if (!confirm("Удалить эту жалобу? Отменить будет нельзя.")) return;
        act(b.dataset.complaintDel,
            (id) => api(`/api/complaints/${id}`, { method: "DELETE" }).then(() => say("#global-msg", "Жалоба удалена")),
            b.closest("[data-complaint]"));
      }));
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

// --- фильтр слов ----------------------------------------------------------
// Сообщения с этими словами бот удаляет. Правки поднимают флаг перечитки —
// бот подхватывает список в чатах за несколько секунд.

async function loadWordFilter() {
  try {
    const data = await api("/api/word-filter");
    const words = data.words || [];
    $("#word-filter-count").textContent = words.length;
    $("#word-filter-list").innerHTML = words.length
      ? words.map((w) => `
        <span class="chip word-chip">${escapeHtml(w)}
          <button class="word-del" data-word="${escapeHtml(w)}" title="Убрать из фильтра" aria-label="Убрать">${icon("trash")}</button>
        </span>`).join("")
      : `<span class="muted">Список пуст — фильтр не действует</span>`;

    $$("[data-word]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/word-filter/${encodeURIComponent(btn.dataset.word)}`, { method: "DELETE" });
          loadWordFilter();
        } catch (err) { say("#global-msg", err.message, "err"); }
      });
    });
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

on("#word-filter-add", "submit", async (e) => {
  e.preventDefault();
  const word = $("#word-filter-input").value.trim();
  if (!word) return;
  try {
    await api("/api/word-filter", { method: "POST", body: { word } });
    say("#global-msg", `«${word}» добавлено в фильтр`);
    $("#word-filter-input").value = "";
    loadWordFilter();
  } catch (err) { say("#global-msg", err.message, "err"); }
});

// --- заявки на рест -------------------------------------------------------
// Решение доезжает до чата: бот правит свою карточку с кнопками, чтобы второй
// админ не нажал «Одобрить» по уже закрытой заявке.

function restDuration(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const parts = [];
  if (days) parts.push(`${days} дн.`);
  if (hours) parts.push(`${hours} ч.`);
  return parts.join(" ") || `${Math.max(1, Math.round(seconds / 60))} мин.`;
}

async function loadRestRequests() {
  const chatId = чат();
  if (!chatId) return;
  try {
    const data = await api(`/api/rest-requests?chat_id=${chatId}`);
    const list = data.requests || [];
    $("#rest-requests-card").classList.toggle("hidden", !list.length);
    $("#rest-requests-count").textContent = list.length;
    if (!list.length) return;

    $("#rest-requests-list").innerHTML = list.map((r) => `
      <div class="role-row" data-rest="${r.id}">
        <div class="person">
          ${avatar(r.full_name, r.user_id)}
          <span class="picker-name">
            <b>${escapeHtml(r.full_name || `ID ${r.user_id}`)}</b>
            ${r.username ? `<span class="muted">@${escapeHtml(r.username)}</span>` : ""}
          </span>
        </div>
        <div class="role-info">
          <span class="right-chip">${icon("clock")}${escapeHtml(restDuration(r.duration_seconds))}</span>
          ${r.reason ? `<span class="muted">${escapeHtml(r.reason)}</span>` : `<span class="muted">без причины</span>`}
          <span class="role-actions">
            <button class="ghost small ok" data-rest-yes="${r.id}">${icon("check")}Одобрить</button>
            <button class="ghost small danger" data-rest-no="${r.id}">${icon("ban")}Отклонить</button>
          </span>
        </div>
      </div>`).join("");

    const decide = async (id, approve, row) => {
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await api(`/api/rest-requests/${id}/decision`, { method: "POST", body: { approve } });
        say("#global-msg", approve ? "Рест одобрен" : "Заявка на рест отклонена");
        loadRestRequests();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    };
    $$("[data-rest-yes]").forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.restYes, true, b.closest("[data-rest]"))));
    $$("[data-rest-no]").forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.restNo, false, b.closest("[data-rest]"))));
  } catch (err) {
    $("#rest-requests-card").classList.add("hidden");
  }
}

// --- подтверждения рынка ---------------------------------------------------

async function loadMarketRequests() {
  const chatId = чат();
  const listNode = $("#market-requests-list");
  if (!chatId || !listNode) return;
  try {
    const data = await api(`/api/market-requests?chat_id=${chatId}`);
    const list = data.requests || [];
    $("#market-requests-count").textContent = list.length;
    listNode.innerHTML = list.length ? list.map((r) => `
      <div class="role-row" data-market-request="${r.id}">
        <div class="person">
          ${avatar(r.full_name, r.seller_id)}
          <span class="picker-name">
            <b>${escapeHtml(r.full_name || `ID ${r.seller_id}`)}</b>
            ${r.username ? `<span class="muted">@${escapeHtml(r.username)}</span>` : ""}
          </span>
        </div>
        <div class="role-info">
          <span><b>${escapeHtml(r.name)}</b> <code>${escapeHtml(r.key)}</code> · ${Number(r.price).toLocaleString("ru")} i¢</span>
          <span class="role-actions">
            <button class="ghost small ok" data-market-request-yes="${r.id}">${icon("check")}Принять</button>
            <button class="ghost small danger" data-market-request-no="${r.id}">${icon("ban")}Отклонить</button>
          </span>
        </div>
      </div>`).join("") : `<p class="muted">Заявок на рынок нет.</p>`;

    const decide = async (id, approve, row) => {
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await api(`/api/market-requests/${id}/decision`, {
          method: "POST", body: { chat_id: chatId, approve },
        });
        say("#global-msg", approve ? "Заявка рынка принята" : "Заявка рынка отклонена");
        loadMarketRequests();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    };
    $$('[data-market-request-yes]').forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.marketRequestYes, true,
        b.closest("[data-market-request]"))));
    $$('[data-market-request-no]').forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.marketRequestNo, false,
        b.closest("[data-market-request]"))));
  } catch (err) {
    $("#market-requests-count").textContent = "0";
    listNode.innerHTML = `<p class="muted">Не удалось загрузить заявки: ${escapeHtml(err.message)}</p>`;
  }
}


// Выбор участника — общий диалог: поиск тот же, что на вкладке «Чаты и люди»,
// поэтому и здесь ищется по имени, @нику и ID. Возвращает выбранного человека
// либо null, если окно закрыли.
function pickMemberDialog(chatId, title) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "keys-overlay";
    overlay.innerHTML = `
      <div class="keys-card picker" role="dialog" aria-label="${escapeHtml(title)}">
        <h3>${icon("user")}${escapeHtml(title)}</h3>
        <span class="input-icon">
          <svg class="ic"><use href="#ic-search"/></svg>
          <input type="text" id="picker-q" placeholder="Имя, @ник или ID" autocomplete="off">
        </span>
        <div class="picker-list">${skeleton(4)}</div>
      </div>`;

    const close = (value) => { overlay.remove(); document.removeEventListener("keydown", onKey); resolve(value); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(null); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(overlay);

    const list = overlay.querySelector(".picker-list");
    const search = overlay.querySelector("#picker-q");

    async function render() {
      try {
        const params = new URLSearchParams({ chat_id: chatId, q: search.value });
        const data = await api(`/api/members?${params}`);
        list.innerHTML = data.members.slice(0, 40).map((m) => `
          <button class="picker-row" data-pick="${m.user_id}"
                  data-name="${escapeHtml(m.full_name || "")}">
            ${avatar(m.full_name, m.user_id)}
            <span class="picker-name">${escapeHtml(m.full_name || "Без имени")}
              ${m.username ? `<span class="muted">@${escapeHtml(m.username)}</span>` : ""}</span>
            ${roleBadge(m)}
          </button>`).join("")
          || `<div class="empty">${icon("empty")}<span>Никого не нашлось</span></div>`;
        list.querySelectorAll("[data-pick]").forEach((row) => {
          row.addEventListener("click", () =>
            close({ user_id: Number(row.dataset.pick), full_name: row.dataset.name }));
        });
      } catch (err) {
        list.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
      }
    }

    search.addEventListener("input", () => {
      clearTimeout(window._pickerSearch);
      window._pickerSearch = setTimeout(render, 250);
    });
    search.focus();
    render();
  });
}

// Действия над ролью: выдать держателя, освободить, закрыть заявку. Всё в той
// же строке, где роль и так видна.
function roleActionButtons(role) {
  if (!role.approved) return "";
  const give = `<button class="ghost small" data-role-give="${role.id}"
      title="Закрепить роль за участником">${icon("user")}${role.status === "free" ? "Выдать" : "Передать"}</button>`;
  const rename = `<button class="ghost small" data-role-rename="${role.id}"
      data-name="${escapeHtml(role.name)}" data-category="${escapeHtml(role.category || "")}"
      title="Переименовать роль или сменить категорию">${icon("edit")}</button>`;
  // Удалять можно только свободную — занятую сначала освобождают, иначе
  // человек лишится роли молча. Ровно так же ведёт себя бот.
  const extra = role.status === "free"
    ? `<button class="ghost small danger" data-role-delete="${role.id}"
         title="Удалить роль из списка">${icon("trash")}Удалить</button>`
    : `<button class="ghost small danger" data-role-free="${role.id}"
         title="Снять роль с участника">${icon("undo")}Освободить</button>`;
  return `<span class="role-actions">${rename}${give}${extra}</span>`;
}

function bindRoleActions() {
  const chatId = () => чат();

  $$("[data-role-give]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".role-row");
      const roleName = row.querySelector(".role-name")?.textContent.trim() || "роль";
      const person = await pickMemberDialog(chatId(), `Кому выдать: ${roleName}`);
      if (!person) return;
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        const res = await api(`/api/chat-roles/${btn.dataset.roleGive}/assign`, {
          method: "POST",
          body: { chat_id: chatId(), user_id: person.user_id },
        });
        say("#global-msg", res.reserved
          ? `Роль забронирована за ${person.full_name} — его пока нет в чате`
          : `Роль выдана: ${person.full_name}`);
        loadChatRoles();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
  });

  $$("[data-role-rename]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      // Переименование сохраняет держателя и бронь — в отличие от «удалить и
      // завести заново», которым это приходилось делать раньше.
      const name = prompt("Новое название роли:", btn.dataset.name);
      if (name === null || !name.trim()) return;
      const category = prompt("Категория (пусто — без категории):", btn.dataset.category);
      if (category === null) return;
      try {
        await api(`/api/chat-roles/${btn.dataset.roleRename}`, {
          method: "PATCH",
          body: { chat_id: chatId(), name: name.trim(), category: category.trim() || null },
        });
        say("#global-msg", `Роль переименована: ${name.trim()}`);
        loadChatRoles();
      } catch (err) {
        say("#global-msg", err.message, "err");
      }
    });
  });

  $$("[data-role-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".role-row");
      const name = row.querySelector(".role-name")?.textContent.trim() || "роль";
      if (!confirm(`Удалить ${name} из списка ролей?`)) return;
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        const res = await api(`/api/chat-roles/${btn.dataset.roleDelete}`, {
          method: "DELETE",
          body: { chat_id: chatId() },
        });
        say("#global-msg", `Роль «${res.name}» удалена`);
        loadChatRoles();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
  });

  $$("[data-role-free]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".role-row");
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        const res = await api(`/api/chat-roles/${btn.dataset.roleFree}/release`, {
          method: "POST",
          body: { chat_id: chatId() },
        });
        say("#global-msg", `Роль «${res.name}» освобождена`);
        loadChatRoles();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
  });
}

// Заявку на роль можно закрыть прямо здесь — там же, где она видна. Решение
// уходит в чат: бот правит свою карточку с кнопками (см. /api/chat-roles/…/decision).
function roleDecisionButtons(role) {
  if (role.approved) return "";
  return `
    <span class="role-actions">
      <button class="ghost small ok" data-role-decide="${role.id}" data-approve="1"
        title="Принять заявку — роль появится в списке">${icon("check")}Принять</button>
      <button class="ghost small danger" data-role-decide="${role.id}" data-approve="0"
        title="Отклонить заявку">${icon("ban")}Отклонить</button>
    </span>`;
}

function bindRoleDecisions() {
  $$("[data-role-decide]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const approve = btn.dataset.approve === "1";
      // Блокируем обе кнопки строки: запрос идёт в Telegram и занимает
      // заметное время, а второй клик закрыл бы уже закрытую заявку.
      const row = btn.closest(".role-row");
      row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        const res = await api(`/api/chat-roles/${btn.dataset.roleDecide}/decision`, {
          method: "POST",
          body: { chat_id: чат(), approve },
        });
        say("#global-msg", approve
          ? (res.reserved ? "Заявка принята, роль забронирована за автором" : "Заявка принята")
          : "Заявка отклонена");
        loadChatRoles();
      } catch (err) {
        say("#global-msg", err.message, "err");
        row.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
  });
}

async function loadChatRoles() {
  const chatId = чат();
  if (!chatId) return;
  if (!$("#chatroles-list").children.length) $("#chatroles-list").innerHTML = skeleton(4);
  try {
    const params = new URLSearchParams({
      chat_id: chatId,
      q: $("#chatroles-q").value,
      status: chatRoleStatus,
      category: $("#chatroles-category").value,
    });
    const data = await api(`/api/chat-roles?${params}`);

    // Изменившиеся счётчики коротко подсвечиваются: иначе цифра меняется
    // незаметно и кажется, что фильтр не сработал.
    const before = {};
    $$("#chatroles-filters .chip").forEach((c) => {
      before[c.dataset.status] = c.querySelector(".chip-count")?.textContent;
    });
    $("#chatroles-filters").innerHTML = CHAT_ROLE_STATUSES.map((s) => {
      const count = s.key ? (data.counts[s.key] ?? 0) : Object.values(data.counts).reduce((a, b) => a + b, 0);
      const active = s.key === chatRoleStatus ? " active" : "";
      const bump = before[s.key] !== undefined && before[s.key] !== String(count) ? " bump" : "";
      return `<button class="chip${active}" data-status="${s.key}">${escapeHtml(s.label)}
        <span class="chip-count${bump}">${count}</span></button>`;
    }).join("");

    // Категории приходят те же, что у бота; выбранную сохраняем, иначе фильтр
    // сбрасывался бы при каждом вводе символа в поиск.
    const chosen = $("#chatroles-category").value;
    $("#chatroles-category").innerHTML = `<option value="">Любая</option>`
      + data.categories.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    $("#chatroles-category").value = chosen;

    // Группируем по категориям — так же, как список ролей выглядит в чате.
    const groups = new Map();
    data.roles.forEach((role) => {
      const key = role.category || "Без категории";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(role);
    });

    $("#chatroles-list").innerHTML = groups.size
      ? [...groups].map(([category, list]) => `
        <div class="role-group">
          <h4>${escapeHtml(category)} <span class="muted">${list.length}</span></h4>
          ${list.map((role) => `
            <div class="role-row">
              <div class="role-name">${escapeHtml(role.name)}<span class="mono muted">#${role.id}</span></div>
              <div class="role-info">${roleState(role)}${roleDecisionButtons(role)}${roleActionButtons(role)}</div>
            </div>`).join("")}
        </div>`).join("")
      : `<div class="empty">${icon("empty")}<span>Ролей не нашлось</span></div>`;

    bindRoleDecisions();
    bindRoleActions();

    $$("#chatroles-filters .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        chatRoleStatus = chip.dataset.status;
        loadChatRoles();
      });
    });
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

on("#chatrole-add", "submit", async (e) => {
  e.preventDefault();
  const name = $("#chatrole-name").value.trim();
  if (!name) return;
  const submit = $("#chatrole-add button[type=submit]");
  submit.disabled = true;
  try {
    await api("/api/chat-roles", {
      method: "POST",
      body: {
        chat_id: чат(),
        name,
        category: $("#chatrole-category").value.trim() || null,
      },
    });
    say("#global-msg", `Роль «${name}» добавлена`);
    $("#chatrole-name").value = "";
    // Категорию намеренно не чистим: роли обычно заводят пачкой в одной и той
    // же категории, и перепечатывать её каждый раз — лишняя работа.
    $("#chatrole-name").focus();
    loadChatRoles();
  } catch (err) {
    say("#global-msg", err.message, "err");
  } finally {
    submit.disabled = false;
  }
});

on("#chatroles-category", "change", loadChatRoles);
on("#chatroles-q", "input", () => {
  clearTimeout(window._chatRoleSearch);
  window._chatRoleSearch = setTimeout(loadChatRoles, 300);
});

// --- лента последних сообщений --------------------------------------------
//
// Плашка на вкладке «Написать»: последние сообщения чата, клик по строке
// подставляет её id в «Ответ на сообщение». Первую порцию берём обычным
// запросом, дальше сервер сам досылает новые через SSE.

const FEED_VISIBLE = 10;      // столько строк держим в плашке
let feedSource = null;        // текущий EventSource
let feedItems = [];           // [{...сообщение}] от старых к новым
let feedChatId = null;        // чат, на который сейчас подписаны
let replyTo = null;           // выбранное сообщение

function feedStatus(text, kind = "") {
  const el = $("#feed-status");
  // Точка показывает состояние потока: «тихо, но на связи» и «связи нет» —
  // разные вещи, а текстом они читались одинаково.
  const live = kind === "err" ? "off" : "on";
  el.innerHTML = `<span class="live-dot ${live}"></span>${escapeHtml(text)}`;
  el.className = `feed-status ${kind}`;
}

function renderFeed() {
  const list = $("#feed-list");
  if (!feedItems.length) {
    list.innerHTML = `<div class="feed-empty">Пока пусто. Сообщения появятся здесь, как только их напишут в чат.</div>`;
    return;
  }
  list.innerHTML = feedItems.map((m) => {
    // Вложение без подписи описываем типом — своей иконкой, а не эмодзи из
    // строки бота (см. mediaKind).
    const body = m.text
      ? `<span class="feed-text">${escapeHtml(m.text)}</span>`
      : (() => {
          const media = mediaKind(m.kind);
          return `<span class="feed-text muted">${icon(media.icon)}${escapeHtml(media.label)}</span>`;
        })();
    return `
      <button class="feed-item${replyTo && replyTo.message_id === m.message_id ? " picked" : ""}"
              data-msg="${m.message_id}" title="Ответить на это сообщение">
        ${avatar(m.full_name, m.user_id)}
        <span class="feed-body">
          <span class="feed-meta">
            <b>${escapeHtml(m.full_name)}</b>
            ${roleBadge(m)}
            <span class="mono muted">${m.message_id}</span>
          </span>
          ${body}
        </span>
      </button>`;
  }).join("");

  $$("[data-msg]").forEach((el) => {
    el.addEventListener("click", () => {
      const id = Number(el.dataset.msg);
      setReplyTo(feedItems.find((m) => m.message_id === id) || null);
    });
  });
}

function setReplyTo(message) {
  replyTo = message;
  $("#send-reply").value = message ? message.message_id : "";
  renderReplyChip();
  renderFeed();
}

function renderReplyChip() {
  const chip = $("#reply-chip");
  if (!replyTo) {
    chip.classList.add("hidden");
    chip.innerHTML = "";
    return;
  }
  const preview = replyTo.text || replyTo.kind || "сообщение без текста";
  chip.classList.remove("hidden");
  chip.innerHTML = `
    <span class="reply-mark"></span>
    <span class="reply-info">
      <b>Отвечаете: ${escapeHtml(replyTo.full_name)}</b>
      <span class="muted">${escapeHtml(preview)}</span>
    </span>
    <button class="ghost small" id="reply-clear" title="Не отвечать">Отменить</button>`;
  $("#reply-clear").addEventListener("click", () => setReplyTo(null));
}

function pushFeedMessage(message) {
  // Сообщение может прийти повторно: браузер переподключает SSE сам, и на
  // стыке одна-две строки способны продублироваться.
  if (feedItems.some((m) => m.message_id === message.message_id)) return;
  feedItems.push(message);
  if (feedItems.length > FEED_VISIBLE) feedItems = feedItems.slice(-FEED_VISIBLE);
  renderFeed();
}

function closeFeedStream() {
  if (feedSource) {
    feedSource.close();
    feedSource = null;
  }
}

async function loadFeed() {
  const chatId = чат();
  if (!chatId) return;

  closeFeedStream();
  feedChatId = chatId;
  // Ответ относился к прежнему чату — в новом этот id указывает в никуда.
  if (replyTo) setReplyTo(null);
  feedStatus("подключение…");

  let lastId = 0;
  try {
    const data = await api(`/api/messages?chat_id=${chatId}&limit=${FEED_VISIBLE}`);
    feedItems = data.messages || [];
    lastId = data.last_id || 0;
    renderFeed();
  } catch (err) {
    feedItems = [];
    renderFeed();
    feedStatus("лента недоступна", "err");
    return;
  }

  // Чат могли переключить, пока грузилась первая порция.
  if (feedChatId !== chatId) return;

  const source = new EventSource(`/api/messages/stream?chat_id=${chatId}&after_id=${lastId}`);
  feedSource = source;
  source.onopen = () => { if (feedSource === source) feedStatus("в реальном времени", "live"); };
  source.onmessage = (e) => {
    if (feedSource !== source) return;
    try {
      pushFeedMessage(JSON.parse(e.data));
    } catch (_) { /* битую строку просто пропускаем */ }
  };
  // EventSource переподключается сам, поэтому это не ошибка, а «связь рвётся».
  source.onerror = () => { if (feedSource === source) feedStatus("переподключение…", "warn"); };
}


// В фоновой вкладке лента никому не нужна, а соединение висит и опрашивает БД.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    closeFeedStream();
    feedStatus("пауза (вкладка неактивна)");
  } else if ($("#view-send") && !$("#view-send").classList.contains("hidden")) {
    loadFeed();
  }
});

// --- отправка -------------------------------------------------------------

// Счётчик длины: лимит Telegram — 4096 символов, и упереться в него легко,
// когда текст пишут прямо в панели.
on("#send-text", "input", () => {
  const len = $("#send-text").value.length;
  const counter = $("#send-counter");
  counter.textContent = `${len} / 4096`;
  counter.style.color = len > 4096 ? "var(--danger)" : "";
});

// Ctrl+Enter (на маке — ⌘+Enter) отправляет. Жмём саму кнопку, а не дублируем
// отправку: иначе горячая клавиша прошла бы мимо блокировки кнопки и с зажатым
// Ctrl+Enter можно было бы наплодить дублей.
on("#send-text", "keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (!$("#send-btn").disabled) $("#send-btn").click();
  }
});

on("#send-btn", "click", async () => {
  const text = $("#send-text").value.trim();
  if (!text) return say("#global-msg", "Сначала напишите текст", "err");
  const btn = $("#send-btn");
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Отправляю…";
  try {
    const res = await api("/api/send", {
      method: "POST",
      body: {
        chat_id: чат(),
        text,
        reply_to: Number($("#send-reply").value) || null,
        topic_id: Number($("#send-topic").value) || null,
      },
    });
    $("#send-text").value = "";
    $("#send-counter").textContent = "0 / 4096";
    setReplyTo(null);   // ответ отправлен — следующее сообщение уже само по себе
    say("#global-msg", `Отправлено (id ${res.message_id})`);
  } catch (err) {
    say("#global-msg", err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = label;
  }
});

on("#send-photo-btn", "click", async () => {
  const file = $("#send-photo").files[0];
  if (!file) return say("#global-msg", "Выберите файл", "err");
  const form = new FormData();
  form.append("chat_id", чат());
  form.append("caption", $("#send-caption").value);
  form.append("photo", file);
  try {
    await api("/api/send_photo", { method: "POST", form });
    $("#send-photo").value = "";
    say("#global-msg", "Картинка отправлена");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

// --- модерация ------------------------------------------------------------
//
// Участника выбирают из списка known_users, а не вводят ID руками: ID нигде
// не виден обычному человеку, а ошибка в одной цифре означает наказание не
// того. Ручной ввод остался, но спрятан — для тех, кого бот ещё не видел.

let modPicked = null;   // {user_id, full_name, username}

// --- варны выбранного участника -------------------------------------------
// Панель повторяет поведение бота целиком: на лимите — автобан со сбросом
// счётчика. Логика на сервере (см. /api/warns), здесь только показ.

async function loadWarns() {
  const card = $("#mod-warns-card");
  if (!modPicked) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  try {
    const params = new URLSearchParams({ chat_id: чат(), user_id: modPicked.user_id });
    const data = await api(`/api/warns?${params}`);
    $("#mod-warns-count").textContent = `${data.count} из ${data.limit}`;
    $("#mod-warns-hint").textContent = data.count >= data.limit - 1 && data.count < data.limit
      ? `Ещё один варн — и бот забанит участника (лимит ${data.limit}).`
      : `При достижении лимита (${data.limit}) бот банит участника и обнуляет счётчик.`;
    $("#mod-warns-list").innerHTML = data.warns.length
      ? data.warns.map((w) => `
        <div class="role-row">
          <div class="role-name">${escapeHtml(w.reason || "без причины")}</div>
          <div class="role-info">
            <span class="muted">${escapeHtml(roleDate(w.created_at) || "")}</span>
            ${w.expires_at ? `<span class="right-chip">${icon("clock")}до ${escapeHtml(roleDate(w.expires_at))}</span>` : ""}
            ${w.by_panel ? `<span class="right-chip">${icon("id")}из панели</span>` : ""}
          </div>
        </div>`).join("")
      : `<div class="empty">${icon("check")}<span>Активных предупреждений нет</span></div>`;
  } catch (err) {
    $("#mod-warns-list").innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

on("#mod-warn", "click", async () => {
  if (!modPicked) { say("#global-msg", "Сначала выберите участника", "err"); return; }
  const days = Number($("#mod-warn-days").value) || null;
  try {
    const res = await api("/api/warns", {
      method: "POST",
      body: {
        chat_id: чат(),
        user_id: modPicked.user_id,
        days,
        reason: $("#mod-warn-reason").value.trim() || null,
      },
    });
    if (res.ban_error) {
      // Варн выдан, счётчик сброшен, а бан не прошёл — молчать об этом нельзя.
      say("#global-msg", `Лимит достигнут, но забанить не вышло: ${res.ban_error}`, "err");
    } else {
      say("#global-msg", res.banned
        ? `Лимит варнов достигнут — ${modPicked.full_name} забанен(а)`
        : `Варн выдан: ${res.count} из ${res.limit}`);
    }
    $("#mod-warn-reason").value = "";
    loadWarns();
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

on("#mod-unwarn", "click", async () => {
  if (!modPicked) return;
  try {
    const res = await api("/api/warns/remove", {
      method: "POST",
      body: { chat_id: чат(), user_id: modPicked.user_id },
    });
    say("#global-msg", `Варн снят. Осталось: ${res.count}`);
    loadWarns();
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

function renderPicked() {
  const box = $("#mod-picked");
  if (!modPicked) {
    box.classList.add("hidden");
    box.innerHTML = "";
    $("#mod-warns-card").classList.add("hidden");
    return;
  }
  loadWarns();
  box.classList.remove("hidden");
  box.innerHTML = `
    ${avatar(modPicked.full_name, modPicked.user_id)}
    <div class="picked-info">
      <b>${escapeHtml(modPicked.full_name || modPicked.user_id)}</b>
      <span class="muted">${modPicked.username ? "@" + escapeHtml(modPicked.username) + " · " : ""}<span class="mono">${modPicked.user_id}</span></span>
    </div>
    ${roleBadge(modPicked)}
    <button class="ghost small" id="mod-clear">Сбросить</button>`;
  $("#mod-clear").addEventListener("click", () => {
    modPicked = null;
    $("#mod-user").value = "";
    $("#mod-search").value = "";
    renderPicked();
  });
}

function pickMember(member, chatId) {
  modPicked = member;
  $("#mod-user").value = member.user_id;
  $("#mod-search").value = "";
  $("#mod-suggest").classList.add("hidden");

  if (chatId) чат() = chatId;
  // переключаемся на вкладку модерации, если пришли из списка участников
  switchAdminView("moderation");

  renderPicked();
}

async function suggestMembers() {
  const q = $("#mod-search").value.trim();
  const role = $("#mod-role").value;
  const box = $("#mod-suggest");
  // Раньше подсказки требовали хотя бы одну букву. Теперь, когда выбрана роль,
  // пустой запрос осмыслен: «покажи всех модераторов этого чата».
  if (q.length < 1 && !role) { box.classList.add("hidden"); return; }
  try {
    const params = new URLSearchParams({ chat_id: чат(), q, role });
    const data = await api(`/api/members?${params}`);
    const list = data.members.slice(0, 8);
    if (!list.length) {
      box.classList.remove("hidden");
      box.innerHTML = `<div class="suggest-empty">Никого не нашлось. Возможно, бот его ещё не видел — тогда укажите ID вручную.</div>`;
      return;
    }
    box.classList.remove("hidden");
    box.innerHTML = list.map((m) => `
      <button class="suggest-item" data-pick="${m.user_id}"
        data-name="${escapeHtml(m.full_name)}" data-username="${escapeHtml(m.username || "")}"
        data-role="${escapeHtml(m.role || "")}" data-role-key="${escapeHtml(m.role_key || "")}">
        ${avatar(m.full_name, m.user_id)}
        <span class="suggest-name">${escapeHtml(m.full_name)}</span>
        ${roleBadge(m)}
        <span class="muted">${m.username ? "@" + escapeHtml(m.username) : ""}</span>
        <span class="mono muted">${m.user_id}</span>
      </button>`).join("");

    $$("[data-pick]").forEach((el) => {
      el.addEventListener("click", () => pickMember({
        user_id: Number(el.dataset.pick),
        full_name: el.dataset.name,
        username: el.dataset.username || null,
        role: el.dataset.role || null,
        role_key: el.dataset.roleKey || null,
      }));
    });
  } catch (err) {
    box.classList.add("hidden");
  }
}

on("#mod-search", "input", () => {
  clearTimeout(window._modSearch);
  window._modSearch = setTimeout(suggestMembers, 250);
});
on("#mod-search", "focus", suggestMembers);
on("#mod-role", "change", suggestMembers);
// клик мимо подсказок — закрыть их
document.addEventListener("click", (e) => {
  if (!e.target.closest("#mod-suggest") && e.target !== $("#mod-search") && e.target !== $("#mod-role")) {
    $("#mod-suggest").classList.add("hidden");
  }
});

$$("[data-mod]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const action = btn.dataset.mod;
    const userId = Number($("#mod-user").value);
    if (!userId) return say("#global-msg", "Сначала выберите участника", "err");

    const who = modPicked ? (modPicked.full_name || userId) : userId;
    const labels = { ban: "забанить", kick: "кикнуть", mute: "замутить" };
    if (labels[action] && !confirm(`Точно ${labels[action]}: ${who}?`)) return;
    try {
      const res = await api(`/api/moderation/${action}`, {
        method: "POST",
        body: {
          chat_id: чат(),
          user_id: userId,
          minutes: Number($("#mod-minutes").value) || null,
          reason: $("#mod-reason").value,
        },
      });
      // Про возврат прав говорим явно: раньше панель молчала, и было не понять,
      // вернулись они вообще или нет.
      const note = res && res.admin_rights_restored ? " · права администратора возвращены" : "";
      say("#global-msg", `Готово: ${who}${note}`);
    } catch (err) {
      say("#global-msg", err.message, "err");
    }
  });
});

// --- админы чата (Telegram) -----------------------------------------------
//
// Настоящий статус администратора в Telegram — то же, что «+тг админ» / «тг
// права» в чате. Права выставляются ТОЛЬКО полным набором: Telegram сбрасывает
// в False всё, что не передали, поэтому «отправить одну галочку» нельзя.

let tgRightsFields = [];   // [{key, label}]
let tgRightsDefaults = {};
let tgPicked = null;       // кого назначаем

// Права администратора Telegram. Бот подписывает их эмодзи — в чате это
// уместно, в панели всё рисуется иконками, поэтому эмодзи из подписи убираем,
// а иконку подбираем по ключу права (он стабильный, в отличие от текста).
const RIGHT_ICONS = {
  can_delete_messages: "trash",
  can_restrict_members: "mute",
  can_pin_messages: "pin",
  can_invite_users: "plus",
  can_manage_video_chats: "video",
  can_change_info: "edit",
  can_manage_chat: "sliders",
  can_promote_members: "crown",
  can_manage_tags: "tag",
  is_anonymous: "eye-off",
};

// Права, которыми пользуются чаще всего: их набор предлагается кнопкой
// «Только модерация» — она закрывает типовой случай в одно нажатие.
const MODERATION_RIGHTS = ["can_delete_messages", "can_restrict_members", "can_pin_messages"];

function rightIcon(key) {
  return icon(RIGHT_ICONS[key] || "check");
}

function rightLabel(field) {
  return String(field.label || field.key).replace(EMOJI_RE, "").trim();
}

function rightsGrid(containerSel, values, namePrefix) {
  $(containerSel).innerHTML = `
    <div class="rights-presets">
      <button type="button" class="chip" data-preset="default">Обычный админ</button>
      <button type="button" class="chip" data-preset="moderation">Только модерация</button>
      <button type="button" class="chip" data-preset="all">Все права</button>
      <button type="button" class="chip" data-preset="none">Снять все</button>
    </div>
    <div class="rights-list">
      ${tgRightsFields.map((f) => `
        <label class="check right-item">
          <input type="checkbox" data-${namePrefix}="${f.key}" ${values[f.key] ? "checked" : ""}>
          <span class="right-label">${rightIcon(f.key)}${escapeHtml(rightLabel(f))}</span>
        </label>`).join("")}
    </div>`;

  // Пресеты меняют галочки, но ничего не сохраняют: человек видит набор до
  // того, как нажмёт «Назначить».
  $(containerSel).querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = btn.dataset.preset;
      $(containerSel).querySelectorAll(`[data-${namePrefix}]`).forEach((el) => {
        const key = el.dataset[namePrefix];
        el.checked =
          preset === "all" ? true :
          preset === "none" ? false :
          preset === "moderation" ? MODERATION_RIGHTS.includes(key) :
          Boolean(tgRightsDefaults[key]);
      });
    });
  });
}

function readRights(containerSel, namePrefix) {
  const out = {};
  $$(`${containerSel} [data-${namePrefix}]`).forEach((el) => {
    out[el.dataset[namePrefix]] = el.checked;
  });
  return out;
}

async function loadTgRights() {
  if (tgRightsFields.length) return;
  const data = await api("/api/tg_rights");
  tgRightsFields = data.fields || [];
  tgRightsDefaults = data.defaults || {};
}

async function loadTgAdmins() {
  const chatId = чат();
  if (!chatId) return;
  $("#tga-list").innerHTML = skeleton(4);
  try {
    await loadTgRights();
    rightsGrid("#tga-rights", tgRightsDefaults, "newright");

    const data = await api(`/api/tg_admins?chat_id=${chatId}`);
    $("#tga-list").innerHTML = data.admins.map((a) => {
      const granted = tgRightsFields.filter((f) => a.rights[f.key]);
      // Полный список прав в строке нечитаем, а голое число ничего не говорит.
      // Показываем счёт и сами права — иконками с подписью-подсказкой.
      const chips = granted.length
        ? `<span class="rights-count">${granted.length} из ${tgRightsFields.length}</span>`
          + granted.map((f) => `
            <span class="right-chip" title="${escapeHtml(rightLabel(f))}">
              ${rightIcon(f.key)}<span>${escapeHtml(rightLabel(f))}</span>
            </span>`).join("")
        : `<span class="muted">без отдельных прав</span>`;

      // Почему кнопок нет: создателя чата снять нельзя никому, а обычного
      // админа — только если его назначал бот. Молча спрятанные кнопки
      // читаются как поломка, поэтому причину пишем прямо здесь.
      const why = a.is_creator
        ? "Создателя чата снять нельзя"
        : "Назначен не ботом — Telegram не даёт им управлять";
      const actions = a.editable ? `
        <button class="ghost small" data-edit="${a.user_id}">${icon("sliders")}Права</button>
        <button class="ghost small danger" data-demote="${a.user_id}">${icon("ban")}Снять админку</button>`
        : `<span class="muted tip-inline">${escapeHtml(why)}</span>`;

      return `
        <div class="admin-row" data-admin="${a.user_id}">
          <div class="admin-head">
            ${avatar(a.full_name, a.user_id)}
            <div class="picked-info">
              <b>${escapeHtml(a.full_name)}</b>
              <span class="muted">${a.username ? "@" + escapeHtml(a.username) + " · " : ""}<span class="mono">${a.user_id}</span></span>
            </div>
            <span class="admin-tags">
              ${a.is_creator ? `<span class="badge owner">${icon("crown")}создатель</span>` : ""}
              ${a.is_bot ? `<span class="badge">${icon("bot")}бот</span>` : ""}
              ${a.custom_title ? `<span class="badge">${escapeHtml(a.custom_title)}</span>` : ""}
            </span>
            <span class="admin-actions">${actions}</span>
          </div>
          <div class="admin-chips">${chips}</div>
          <div class="admin-editor hidden" data-editor="${a.user_id}"></div>
        </div>`;
    }).join("") || `<div class="empty">${icon("empty")}<span>В этом чате нет администраторов, либо бот их не видит</span></div>`;

    bindTgAdminActions(data.admins, chatId);
  } catch (err) {
    $("#tga-list").innerHTML = "";
    say("#global-msg", err.message, "err");
  }
}

function bindTgAdminActions(admins, chatId) {
  const find = (id) => admins.find((a) => a.user_id === Number(id));

  $$("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const admin = find(btn.dataset.edit);
      const box = $(`[data-editor="${btn.dataset.edit}"]`);
      if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }

      box.classList.remove("hidden");
      box.innerHTML = `
        <label class="narrow"><span>Должность</span>
          <input type="text" maxlength="16" data-title value="${escapeHtml(admin.custom_title || "")}" autocomplete="off">
        </label>
        <div data-grid></div>
        <button class="primary small" data-save-rights>${icon("check")}Сохранить права</button>`;
      box.querySelector("[data-grid]").innerHTML = `<div class="rights-list">${
        tgRightsFields.map((f) => `
          <label class="check right-item">
            <input type="checkbox" data-right="${f.key}" ${admin.rights[f.key] ? "checked" : ""}>
            <span class="right-label">${rightIcon(f.key)}${escapeHtml(rightLabel(f))}</span>
          </label>`).join("")
      }</div>`;

      box.querySelector("[data-save-rights]").addEventListener("click", async () => {
        const rights = {};
        box.querySelectorAll("[data-right]").forEach((el) => { rights[el.dataset.right] = el.checked; });
        try {
          await api("/api/tg_admins/rights", {
            method: "POST",
            body: {
              chat_id: Number(chatId),
              user_id: admin.user_id,
              rights,
              custom_title: box.querySelector("[data-title]").value,
            },
          });
          say("#global-msg", `Права обновлены: ${admin.full_name}`);
          loadTgAdmins();
        } catch (err) {
          say("#global-msg", err.message, "err");
        }
      });
    });
  });

  $$("[data-demote]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const admin = find(btn.dataset.demote);
      if (!confirm(`Снять права администратора Telegram: ${admin.full_name}?`)) return;
      try {
        await api("/api/tg_admins/demote", {
          method: "POST",
          body: { chat_id: Number(chatId), user_id: admin.user_id },
        });
        say("#global-msg", `Админка снята: ${admin.full_name}`);
        loadTgAdmins();
      } catch (err) {
        say("#global-msg", err.message, "err");
      }
    });
  });
}

// Выбор человека для назначения — тот же поиск, что и в модерации.
async function suggestTgCandidates() {
  const q = $("#tga-search").value.trim();
  const box = $("#tga-suggest");
  if (q.length < 1) { box.classList.add("hidden"); return; }
  try {
    const params = new URLSearchParams({ chat_id: чат(), q });
    const data = await api(`/api/members?${params}`);
    const list = data.members.slice(0, 8);
    box.classList.remove("hidden");
    if (!list.length) {
      box.innerHTML = `<div class="suggest-empty">Никого не нашлось — бот мог его ещё не видеть в этом чате.</div>`;
      return;
    }
    box.innerHTML = list.map((m) => `
      <button class="suggest-item" data-tgpick="${m.user_id}"
        data-name="${escapeHtml(m.full_name)}" data-username="${escapeHtml(m.username || "")}">
        ${avatar(m.full_name, m.user_id)}
        <span class="suggest-name">${escapeHtml(m.full_name)}</span>
        ${roleBadge(m)}
        <span class="mono muted">${m.user_id}</span>
      </button>`).join("");

    $$("[data-tgpick]").forEach((el) => {
      el.addEventListener("click", () => {
        tgPicked = {
          user_id: Number(el.dataset.tgpick),
          full_name: el.dataset.name,
          username: el.dataset.username || null,
        };
        $("#tga-search").value = "";
        box.classList.add("hidden");
        renderTgPicked();
      });
    });
  } catch (err) {
    box.classList.add("hidden");
  }
}

function renderTgPicked() {
  const box = $("#tga-picked");
  if (!tgPicked) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = `
    ${avatar(tgPicked.full_name, tgPicked.user_id)}
    <div class="picked-info">
      <b>${escapeHtml(tgPicked.full_name)}</b>
      <span class="muted">${tgPicked.username ? "@" + escapeHtml(tgPicked.username) + " · " : ""}<span class="mono">${tgPicked.user_id}</span></span>
    </div>
    <button class="ghost small" id="tga-clear">Сбросить</button>`;
  $("#tga-clear").addEventListener("click", () => { tgPicked = null; renderTgPicked(); });
}

on("#tga-search", "input", () => {
  clearTimeout(window._tgSearch);
  window._tgSearch = setTimeout(suggestTgCandidates, 250);
});

on("#tga-promote", "click", async () => {
  if (!tgPicked) return say("#global-msg", "Сначала выберите, кого назначаем", "err");
  const rights = readRights("#tga-rights", "newright");
  try {
    await api("/api/tg_admins/promote", {
      method: "POST",
      body: {
        chat_id: чат(),
        user_id: tgPicked.user_id,
        rights,
        custom_title: $("#tga-title").value,
      },
    });
    say("#global-msg", `Назначен администратором: ${tgPicked.full_name}`);
    tgPicked = null;
    $("#tga-title").value = "";
    renderTgPicked();
    loadTgAdmins();
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

// --- биржа ----------------------------------------------------------------

// Линейный график курса: одна серия, поэтому один цвет. Рисуем инлайновым SVG
// в viewBox 0..100 x 0..100 с preserveAspectRatio="none" — тогда график тянется
// по ширине карточки без пересчёта на resize и без единого обработчика.
// Толщину линии компенсируем vector-effect, иначе растяжение размажет её.
function lineChart(title, subtitle, points) {
  if (points.length < 2) {
    return `<div class="chart-block"><h3>${escapeHtml(title)}</h3>
      <div class="chart-empty">${icon("chart")}Точек пока мало — график появится
      после нескольких изменений курса</div></div>`;
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Плоскую линию (min === max) иначе поделили бы на ноль — рисуем по центру.
  const span = max - min || 1;
  const x = (i) => (i / (points.length - 1)) * 100;
  const y = (v) => 100 - ((v - min) / span) * 100;

  const line = points.map((p, i) => `${x(i).toFixed(2)},${y(p.value).toFixed(2)}`).join(" ");
  const area = `0,100 ${line} 100,100`;
  const last = points[points.length - 1];
  const first = points[0];
  const growth = first.value ? ((last.value / first.value - 1) * 100) : 0;
  const trend = growth >= 0 ? "up" : "down";

  // Подписи оси Y — только три (низ/середина/верх): больше на узкой карточке
  // не читается, а точное значение точки видно в нативном title при наведении.
  const fmt = (v) => (v >= 1000 ? Math.round(v).toLocaleString("ru-RU") : v.toFixed(2));
  const dots = points.map((p, i) => `<circle class="spark-dot" cx="${x(i).toFixed(2)}"
    cy="${y(p.value).toFixed(2)}" r="1.4"><title>${escapeHtml(p.title)}</title></circle>`).join("");

  return `<div class="chart-block">
    <h3>${escapeHtml(title)}</h3>
    <p class="chart-sub">${escapeHtml(subtitle)}</p>
    <div class="spark-wrap">
      <div class="spark-y"><span>${fmt(max)}</span><span>${fmt((max + min) / 2)}</span><span>${fmt(min)}</span></div>
      <svg class="spark ${trend}" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <polygon class="spark-area" points="${area}"/>
        <polyline class="spark-line" points="${line}"/>
        ${dots}
      </svg>
    </div>
    <div class="bar-axis"><span>${escapeHtml(first.axis)}</span><span class="right">${escapeHtml(last.axis)}</span></div>
    <div class="stat-grid mt-3">
      ${statCell(fmt(last.value), "курс сейчас")}
      ${statCell(`${growth >= 0 ? "+" : ""}${growth.toFixed(1)}%`, "за период")}
      ${statCell(fmt(min), "минимум")}
      ${statCell(fmt(max), "максимум")}
    </div>
  </div>`;
}

// Средний процент за шаг — то самое число, из-за которого «биржа печатает
// деньги»: если оно заметно больше нуля, курс растёт экспоненциально.
function stockForecast(lo, hi, div) {
  if (![lo, hi, div].every(Number.isFinite)) return "";
  const avg = (lo + hi) / 2;
  const perDay = (Math.pow(1 + avg / 100, 24) - 1) * 100;
  let verdict;
  if (Math.abs(avg) < 0.5) verdict = "ok";
  else if (avg > 0) verdict = "warn";
  else verdict = "warn";
  const dayText = Math.abs(perDay) > 100000
    ? `${(perDay / 100).toExponential(1)}×`
    : `${perDay >= 0 ? "+" : ""}${perDay.toFixed(0)}%`;
  const note = verdict === "ok"
    ? "курс в среднем стоит на месте — деньги не печатаются"
    : (avg > 0 ? "курс в среднем растёт — со временем это разгонит инфляцию"
               : "курс в среднем падает — вложения будут таять");
  return `<p class="msg mt-1 ${verdict === "ok" ? "ok" : "err"}">
    Средний шаг: <b>${avg >= 0 ? "+" : ""}${avg.toFixed(2)}%</b> в час → примерно
    <b>${dayText}</b> в сутки. ${escapeHtml(note)}.
    Дивиденды добавляют держателям ещё <b>${div.toFixed(1)}%</b> от вложенного в сутки.</p>`;
}

// Пресеты — те же числа, что у «биржа настройки {режим}» в боте (STOCK_PRESETS).
const STOCK_PRESETS = {
  "спокойная": [-5, 5, 2],
  "обычная": [-15, 15, 5],
  "азартная": [-30, 30, 10],
};

function refreshStockForecast() {
  const lo = Number($("#stock-min").value);
  const hi = Number($("#stock-max").value);
  const div = Number($("#stock-div").value);
  $("#stock-forecast").innerHTML = stockForecast(lo, hi, div);
  // Подсвечиваем режим, если текущие числа в точности совпали с ним.
  $$("#stock-presets .preset").forEach((b) => {
    const p = STOCK_PRESETS[b.dataset.preset];
    b.classList.toggle("on", p && p[0] === lo && p[1] === hi && p[2] === div);
  });
}

function applyStockPreset(name) {
  const p = STOCK_PRESETS[name];
  if (!p) return;
  $("#stock-min").value = p[0];
  $("#stock-max").value = p[1];
  $("#stock-div").value = p[2];
  refreshStockForecast();
}

async function loadStockData() {
  const chatId = чат();
  if (!chatId) return;
  const period = $("#stock-period").value;
  $("#stock-out").innerHTML = skeleton(3);
  try {
    const d = await api(`/api/stock?chat_id=${chatId}&period=${encodeURIComponent(period)}`);
    const withTime = period === "24h";
    const points = d.points.map((p) => {
      const dt = new Date(p.t + "Z");
      const stamp = withTime
        ? dt.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
        : dt.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
      const change = p.change == null ? "" : ` (${p.change >= 0 ? "+" : ""}${p.change.toFixed(1)}%)`;
      const manual = { manual: ", вручную", seed: ", на момент запуска", now: ", сейчас" }[p.source] || "";
      return {
        value: p.price,
        axis: stamp,
        title: `${dt.toLocaleString("ru-RU")}: ${p.price.toFixed(2)} i¢${change}${manual}`,
      };
    });
    const periodName = { "24h": "за сутки", "7d": "за неделю", "30d": "за месяц" }[period];
    $("#stock-out").innerHTML =
      lineChart("Курс акций", `Каждая точка — изменение курса ${periodName}.`, points);

    $("#stock-min").value = d.settings.min_change_percent;
    $("#stock-max").value = d.settings.max_change_percent;
    $("#stock-div").value = d.settings.dividend_percent;
    refreshStockForecast();
    // Ручные поля раскрываем только если настройки не совпали ни с одним
    // режимом — иначе три кнопки и есть весь нужный интерфейс.
    $("#stock-tune").open = !$("#stock-presets .preset.on");
  } catch (err) {
    $("#stock-out").innerHTML = "";
    say("#stock-msg", err.message, "err");
  }
}

async function saveStockSettings() {
  const chatId = чат();
  if (!chatId) return;
  try {
    await api("/api/stock/settings", {
      method: "POST",
      body: {
        chat_id: Number(chatId),
        min_change_percent: Number($("#stock-min").value),
        max_change_percent: Number($("#stock-max").value),
        dividend_percent: Number($("#stock-div").value),
      },
    });
    say("#stock-msg", "Настройки биржи сохранены.");
  } catch (err) {
    say("#stock-msg", err.message, "err");
  }
}

$$("#stock-presets .preset").forEach((btn) => {
  btn.addEventListener("click", () => applyStockPreset(btn.dataset.preset));
});
on("#stock-load", "click", loadStockData);
on("#stock-period", "change", loadStockData);
on("#stock-save", "click", saveStockSettings);
["#stock-min", "#stock-max", "#stock-div"].forEach((sel) => {
  on(sel, "input", refreshStockForecast);
});

// --- случайные события чата -----------------------------------------------
// Тумблер на одну настройку, поэтому без формы: кнопка сразу и показывает
// текущее состояние, и переключает его.
let _eventsEnabled = null;

function renderEventsToggle() {
  const btn = $("#events-toggle");
  if (!btn) return;
  if (_eventsEnabled === null) {
    btn.textContent = "Загрузка…";
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  btn.textContent = _eventsEnabled ? "Выключить события" : "Включить события";
  btn.classList.toggle("primary", !_eventsEnabled);
  btn.classList.toggle("ghost", _eventsEnabled);
}

async function loadChatEvents() {
  const chatId = чат();
  if (!chatId) return;
  _eventsEnabled = null;
  renderEventsToggle();
  try {
    const d = await api(`/api/chat-events?chat_id=${chatId}`);
    _eventsEnabled = d.enabled;
    renderEventsToggle();
    say("#events-msg", _eventsEnabled
      ? "Сейчас события включены — бот сам объявляет их в чате."
      : "Сейчас события выключены — бот не объявляет их в этом чате.");
  } catch (err) {
    say("#events-msg", err.message, "err");
  }
}

async function toggleChatEvents() {
  const chatId = чат();
  if (!chatId || _eventsEnabled === null) return;
  try {
    const d = await api("/api/chat-events", {
      method: "POST", body: { chat_id: Number(chatId), enabled: !_eventsEnabled },
    });
    _eventsEnabled = d.enabled;
    renderEventsToggle();
    say("#events-msg", _eventsEnabled ? "События включены." : "События выключены.");
  } catch (err) {
    say("#events-msg", err.message, "err");
  }
}

if ($("#events-toggle")) $("#events-toggle").addEventListener("click", toggleChatEvents);

// --- статистика -----------------------------------------------------------

// Столбчатый график из массива {label, value}: одна серия, поэтому один цвет.
// Высота столбца — доля от максимума; пик выделен и подписан значением (только
// он — правило «selective direct labels»). Ховер — нативный title с точным
// числом (CSP-safe, без JS). subtitle — что за график.
function barChart(title, subtitle, points, { peakLabel } = {}) {
  if (!points.length || points.every((p) => p.value === 0)) {
    return `<div class="chart-block"><h3>${escapeHtml(title)}</h3>
      <div class="chart-empty">${icon("chart")}Пока нет данных за этот период</div></div>`;
  }
  const max = Math.max(...points.map((p) => p.value), 1);
  const peakIdx = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);
  const bars = points.map((p, i) => {
    const h = Math.round((p.value / max) * 100);
    const isPeak = i === peakIdx && p.value > 0;
    const label = isPeak ? `<span class="bar-peak-label">${p.value}</span>` : "";
    return `<div class="bar-col" title="${escapeHtml(p.title)}">
      ${label}<div class="bar${isPeak ? " peak" : ""}" style="height:${h}%"></div>
    </div>`;
  }).join("");
  const axis = points.map((p) => `<span>${escapeHtml(p.axis ?? "")}</span>`).join("");
  return `<div class="chart-block">
    <h3>${escapeHtml(title)}</h3>
    <p class="chart-sub">${escapeHtml(subtitle)}</p>
    <div class="bars">${bars}</div>
    <div class="bar-axis">${axis}</div>
  </div>`;
}

function statCell(value, label) {
  return `<div class="stat-cell"><b>${value}</b><span>${escapeHtml(label)}</span></div>`;
}

async function loadStatsData() {
  const chatId = чат();
  if (!chatId) return;
  const days = Math.max(1, Number($("#stats-days").value) || 7);
  $("#stats-out").innerHTML = skeleton(5);
  try {
    const s = await api(`/api/stats?chat_id=${chatId}&days=${days}`);
    const sum = s.summary || {};

    const table = (title, rows, valueKey, unit = "") => {
      if (!rows || !rows.length) return "";
      return `<h3>${escapeHtml(title)}</h3><div class="table-wrap"><table><tbody>` +
        rows.map((r, i) => `<tr>
            <td style="width:1%" class="muted">${i + 1}</td>
            <td><div class="person">${avatar(r.full_name, r.user_id)}<span>${escapeHtml(r.full_name || r.user_id)}</span></div></td>
            <td style="width:1%">${roleBadge(r)}</td>
            <td class="num mono">${r[valueKey] ?? ""}${unit}</td>
          </tr>`).join("") + "</tbody></table></div>";
    };

    // Ряд по дням: подпись оси — день/месяц, но первую точку каждого месяца и
    // концы показываем, остальное прорежаем, чтобы подписи не наезжали.
    const dailyPoints = s.daily.map((d, i, arr) => {
      const dt = new Date(d.day + "T00:00:00");
      const dd = String(dt.getDate());
      const show = arr.length <= 14 || i === 0 || i === arr.length - 1 || dt.getDate() === 1;
      return {
        value: d.count,
        axis: show ? dd : "",
        title: `${dt.toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}: ${d.count} сообщ.`,
      };
    });

    const hourlyPoints = s.hourly.map((h) => ({
      value: h.count,
      axis: h.hour % 6 === 0 ? String(h.hour) : "",
      title: `${String(h.hour).padStart(2, "0")}:00 — ${h.count} сообщ.`,
    }));

    const peakHourLabel = sum.peak_hour && sum.peak_hour.hour != null
      ? `${String(sum.peak_hour.hour).padStart(2, "0")}:00` : "—";

    $("#stats-out").innerHTML =
      `<div class="stat-grid">
         ${statCell(s.messages, `сообщений за ${days} дн.`)}
         ${statCell(sum.avg_per_day ?? "—", "в среднем за день")}
         ${statCell(sum.active_users ?? 0, "активных участников")}
         ${statCell(sum.newcomers ?? 0, "новичков")}
         ${statCell(peakHourLabel, "самый активный час")}
       </div>` +
      barChart("Активность по дням", `Сообщений в день за последние ${days} дн.`, dailyPoints) +
      barChart("Активность по часам", "Сообщений по часам за последние сутки (UTC)", hourlyPoints) +
      table("Самые активные", s.top_active, "total") +
      table("Репутация", s.reputation, "points") +
      table("Ачивки", s.achievements, "total") +
      table("Новички", s.newcomers, "user_id");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

on("#stats-load", "click", loadStatsData);

// Журнал: поиск + фильтры + постраничная выдача.
const LOGS_PAGE = 50;
let _logsOffset = 0;
let _logsTotal = 0;
// Типы событий приходят с сервера вместе с первой страницей; заполняем
// выпадающий список один раз, иначе он сбрасывал бы выбор на каждый ввод.
let _logsTypesFilled = false;
let _logsTimer = null;

function logsQueryString() {
  const p = new URLSearchParams();
  const q = $("#logs-q").value.trim();
  if (q) p.set("q", q);
  const type = $("#logs-type").value;
  if (type) p.set("event_type", type);
  const days = $("#logs-days").value;
  if (days && days !== "0") p.set("days", days);
  const chat = чат();
  if (chat) p.set("chat_id", chat);
  const uid = $("#logs-user").value.trim();
  if (uid) p.set("user_id", uid);
  p.set("limit", LOGS_PAGE);
  p.set("offset", _logsOffset);
  return p.toString();
}

async function loadLogs() {
  const table = $("#logs-table");
  if (!table) return;
  try {
    const data = await api(`/api/logs/search?${logsQueryString()}`);
    _logsTotal = data.total;

    if (!_logsTypesFilled && data.event_types) {
      $("#logs-type").innerHTML = `<option value="">Все события</option>` +
        data.event_types.map((t) =>
          `<option value="${escapeHtml(t.event_type)}">${escapeHtml(t.event_type)} (${t.n})</option>`).join("");
      _logsTypesFilled = true;
    }

    table.innerHTML = data.logs.map((l) => {
      // Время приходит в UTC — показываем в зоне того, кто смотрит панель.
      const dt = new Date(l.created_at + "Z");
      const who = [
        l.actor_id ? `<span class="mono">${l.actor_id}</span>` : "",
        l.target_id ? `→ <span class="mono">${l.target_id}</span>` : "",
      ].filter(Boolean).join(" ");
      return `<tr>
        <td class="muted mono nowrap" title="${escapeHtml(dt.toLocaleString("ru-RU"))}">${escapeHtml(dt.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}</td>
        <td><span class="badge">${escapeHtml(l.event_type)}</span></td>
        <td class="muted" data-label="Кто / кому">${who || ""}</td>
        <td class="muted tc-details">${escapeHtml(l.details || "")}</td></tr>`;
    }).join("") || empty(4, "Ничего не найдено — попробуйте ослабить фильтры");

    const from = _logsTotal ? _logsOffset + 1 : 0;
    const to = Math.min(_logsOffset + LOGS_PAGE, _logsTotal);
    $("#logs-count").textContent = _logsTotal
      ? `Показаны ${from}–${to} из ${_logsTotal}`
      : "Записей нет";
    $("#logs-prev").disabled = _logsOffset <= 0;
    $("#logs-next").disabled = _logsOffset + LOGS_PAGE >= _logsTotal;
  } catch (err) {
    table.innerHTML = empty(4, err.message);
  }
}

// Ввод в поиске не дёргает сервер на каждую букву.
function scheduleLogsReload() {
  clearTimeout(_logsTimer);
  _logsTimer = setTimeout(() => { _logsOffset = 0; loadLogs(); }, 300);
}

if ($("#logs-q")) {
  $("#logs-q").addEventListener("input", scheduleLogsReload);
  ["#logs-type", "#logs-days"].forEach((sel) =>
    $(sel).addEventListener("change", () => { _logsOffset = 0; loadLogs(); }));
  $("#logs-user").addEventListener("input", scheduleLogsReload);
  $("#logs-prev").addEventListener("click", () => {
    _logsOffset = Math.max(0, _logsOffset - LOGS_PAGE);
    loadLogs();
  });
  $("#logs-next").addEventListener("click", () => {
    if (_logsOffset + LOGS_PAGE < _logsTotal) { _logsOffset += LOGS_PAGE; loadLogs(); }
  });
  $("#logs-reset").addEventListener("click", () => {
    $("#logs-q").value = "";
    $("#logs-type").value = "";
    $("#logs-days").value = "7";
    чат() = "";
    $("#logs-user").value = "";
    _logsOffset = 0;
    loadLogs();
  });
}

// --- настройки ------------------------------------------------------------

// Одна карточка настройки. Булеву настройку рисуем кнопкой-переключателем
// (не заставляем писать 0/1 руками), остальные — сворачиваемым полем с превью.
function settingCard(key, item, canEdit) {
  if (item.kind === "bool") {
    const on = String(item.value ?? "").trim() === "1";
    const control = canEdit
      ? `<button class="ghost small ${on ? "" : "danger"}" data-bool-setting="${key}" data-value="${on ? 1 : 0}">${icon("power")}${on ? "Включено" : "Выключено"}</button>`
      : `<span class="badge ${on ? "ok" : ""}">${on ? "Включено" : "Выключено"}</span>`;
    return `
      <div class="card setting-card">
        <div class="action-head">
          <h3>${icon("settings")}${escapeHtml(item.title)}</h3>
          ${control}
        </div>
      </div>`;
  }
  if (item.kind === "timezone") {
    // Выпадающий список вместо свободного ввода: пояс — это выбор из конечного
    // набора, и опечатка «Europe/Moskow» иначе всплыла бы только при сохранении.
    // Поле ручного ввода оставляем: там принимаются и «мск», и «+3», и любая
    // зона IANA, которой нет в списке.
    const cur = String(item.value || "");
    const known = _timezones.some((t) => t.value === cur);
    const opts = [`<option value=""${cur ? "" : " selected"}>GMT+0 (UTC) — по умолчанию</option>`]
      .concat(_timezones.map((t) =>
        `<option value="${escapeHtml(t.value)}"${t.value === cur ? " selected" : ""}>${escapeHtml(t.label)}</option>`))
      .join("");
    return `
      <div class="card setting-card">
        <div class="action-head">
          <h3>${icon("clock")}${escapeHtml(item.title)}</h3>
        </div>
        <div class="row">
          <label><span>Часовой пояс</span>
            <select data-tz-select ${canEdit ? "" : "disabled"}>${opts}</select>
          </label>
          <label><span>Или впишите свой</span>
            <input type="text" data-setting="${key}" ${canEdit ? "" : "disabled"}
              value="${escapeHtml(cur)}" placeholder="мск / GMT+3 / Europe/Moscow" autocomplete="off">
          </label>
          ${canEdit ? `<div class="grow-0"><button class="ghost" data-save="${key}">${icon("check")}Сохранить</button></div>` : ""}
        </div>
        ${cur && !known ? `<div class="muted tiny">Своё значение: <code>${escapeHtml(cur)}</code></div>` : ""}
      </div>`;
  }
  const placeholder = item.kind === "number"
    ? "Число (0 — выключить правило)"
    : "Пусто — бот использует текст по умолчанию";
  return `
    <div class="card setting-card">
      <div class="action-head">
        <h3>${icon("settings")}${escapeHtml(item.title)}</h3>
        <button class="disclosure ghost small" data-expand-setting aria-expanded="false" title="Открыть/закрыть">${icon("chevron")}</button>
      </div>
      <div class="setting-preview muted">${previewText(item.value)}</div>
      <div class="setting-body collapsed">
        <label>
          <textarea data-setting="${key}" ${canEdit ? "" : "disabled"}
            placeholder="${placeholder}">${escapeHtml(item.value || "")}</textarea>
        </label>
        ${canEdit ? `<button class="ghost" data-save="${key}">${icon("check")}Сохранить</button>` : ""}
      </div>
    </div>`;
}

// Список зон приходит с сервера (общий модуль tz_settings), а не хранится
// в панели: свой список рано или поздно разошёлся бы с тем, что принимает бот.
let _timezones = [];

// Бесконечные деньги — рубильник владельца, он же «+бесконечность» в чате.
// Список один на всех владельцев, поэтому экран показывает и чужие включения:
// иначе выглядело бы, что рубильник только твой.
async function loadInfiniteMoney() {
  const карточка = $("#infinite-card");
  if (!карточка || me.role !== "owner") return;
  const флажок = $("#infinite-toggle"), подпись = $("#infinite-label"),
        заметка = $("#infinite-note");
  try {
    const d = await api("/api/owner/infinite-money");
    флажок.checked = !!d.enabled;
    // Не привязан телеграм — бот не знает, кому включать. Говорим это ДО
    // нажатия и называем, что делать: отказ по факту читается как поломка.
    флажок.disabled = !d.linked;
    подпись.textContent = d.enabled
      ? "Включены — ваши покупки не списывают i¢"
      : "Включить бесконечные деньги";
    заметка.innerHTML = !d.linked
      ? `${icon("alert")}Сначала привяжите телеграм выше — бот узнаёт вас по нему.`
      : (d.others.length
         ? `Включены ещё у ${d.others.length} ${d.others.length === 1 ? "владельца" : "владельцев"}. Выключить чужой отсюда нельзя.`
         : "");
  } catch (err) {
    заметка.textContent = err.message;
  }
}

async function saveInfiniteMoney() {
  const флажок = $("#infinite-toggle");
  if (!флажок) return;
  const нужно = флажок.checked;
  флажок.disabled = true;
  try {
    await api("/api/owner/infinite-money", { method: "POST", body: { enabled: нужно } });
    say("#infinite-msg", нужно
      ? "Бесконечные деньги включены — покупки больше не списывают i¢."
      : "Бесконечные деньги выключены — траты снова списываются.");
  } catch (err) {
    флажок.checked = !нужно;      // сервер не согласился — возвращаем как было
    say("#infinite-msg", err.message, "err");
  }
  флажок.disabled = false;
  await loadInfiniteMoney();
}

async function loadSettings() {
  loadInfiniteMoney();
  try {
    const data = await api("/api/settings");
    _timezones = data.timezones || [];
    const canEdit = me.role === "owner";
    $("#settings-list").innerHTML =
      Object.entries(data.settings).map(([key, item]) => settingCard(key, item, canEdit)).join("")
      + (canEdit ? "" : `<div class="card"><div class="empty">${icon("alert")}
          <span>Менять настройки может только владелец.</span></div></div>`);

    $$("[data-expand-setting]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = btn.closest(".setting-card").querySelector(".setting-body");
        const nowCollapsed = body.classList.toggle("collapsed");
        btn.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
      });
    });

    // Выбор в списке подставляем в поле ручного ввода — сохраняет всегда
    // одна кнопка, читающая именно это поле.
    $$("[data-tz-select]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const input = sel.closest(".setting-card").querySelector('[data-setting="timezone"]');
        if (input) input.value = sel.value;
      });
    });

    $$("[data-bool-setting]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const next = btn.dataset.value === "1" ? "0" : "1";
        try {
          await api("/api/settings", { method: "POST", body: { key: btn.dataset.boolSetting, value: next } });
          say("#global-msg", next === "1" ? "Включено" : "Выключено");
          loadSettings();
        } catch (err) { say("#global-msg", err.message, "err"); }
      });
    });

    $$("[data-save]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const key = btn.dataset.save;
        try {
          await api("/api/settings", {
            method: "POST",
            body: { key, value: $(`[data-setting="${key}"]`).value },
          });
          say("#global-msg", "Сохранено");
        } catch (err) {
          say("#global-msg", err.message, "err");
        }
      });
    });
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

// --- аккаунты -------------------------------------------------------------

async function loadUsers() {
  try {
    const data = await api("/api/users");
    $("#users-table").innerHTML = data.users.map((u) => `
      <tr>
        <td class="tc-head"><div class="person">${avatar(u.username, u.id)}<span>${escapeHtml(u.username)}${
          u.username === me.username ? ' <em class="tip">— это вы</em>' : ""}</span></div></td>
        <td data-label="Роль"><span class="badge ${u.role === "owner" ? "owner" : ""}">${
          u.role === "owner" ? icon("key") + "владелец" : "администратор"}</span></td>
        <td class="muted nowrap" data-label="Последний вход">${fmtDate(u.last_login_at)}</td>
        <td class="right ${u.username === me.username ? "" : "tc-actions"}">${u.username === me.username ? "" :
          `<button class="danger" data-del="${u.id}">${icon("trash")}Удалить</button>`}</td>
      </tr>`).join("");

    $$("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Удалить аккаунт?")) return;
        try {
          await api(`/api/users/${btn.dataset.del}`, { method: "DELETE" });
          loadUsers();
        } catch (err) {
          say("#global-msg", err.message, "err");
        }
      });
    });

    const logins = await api("/api/logins");
    $("#logins-table").innerHTML = logins.logins.map((l) => `
      <tr><td class="muted nowrap" data-label="Когда">${fmtDate(l.created_at)}</td>
          <td data-label="Логин">${escapeHtml(l.username)}</td>
          <td class="mono" data-label="Адрес">${escapeHtml(l.ip || "—")}</td>
          <td><span class="badge ${l.success ? "ok" : "err"}">${
            icon(l.success ? "check" : "alert")}${l.success ? "успех" : "отказ"}</span></td></tr>`).join("")
      || empty(4, "Входов пока не было");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

on("#nu-create", "click", async () => {
  try {
    await api("/api/users", {
      method: "POST",
      body: {
        username: $("#nu-name").value.trim(),
        password: $("#nu-pass").value,
        role: $("#nu-role").value,
      },
    });
    $("#nu-name").value = ""; $("#nu-pass").value = "";
    say("#global-msg", "Аккаунт создан");
    loadUsers();
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

on("#pw-save", "click", async () => {
  try {
    await api("/api/password", { method: "POST", body: { password: $("#pw-new").value } });
    $("#pw-new").value = "";
    say("#global-msg", "Пароль изменён");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

// --- пасхалка -------------------------------------------------------------
// Konami-код заставляет логотип сделать кувырок. Ничего не включает и не
// меняет — просто привет тому, кто попробовал.

const KONAMI = ["ArrowUp","ArrowUp","ArrowDown","ArrowDown","ArrowLeft","ArrowRight","ArrowLeft","ArrowRight","b","a"];
let konamiPos = 0;

document.addEventListener("keydown", (e) => {
  if (isTyping(document.activeElement)) return;
  const expected = KONAMI[konamiPos];
  const pressed = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  konamiPos = pressed === expected ? konamiPos + 1 : (pressed === KONAMI[0] ? 1 : 0);
  if (konamiPos < KONAMI.length) return;

  konamiPos = 0;
  const logo = $(".brand-ic");
  if (!logo) return;
  logo.classList.remove("tumble");
  void logo.offsetWidth;  // перезапуск анимации: без этого второй раз не сработает
  logo.classList.add("tumble");
  say("#global-msg", "Бот сделал сальто. Больше он ничего не умеет.");
});

// ===== Настройки чата ======================================================
// Форма собирается из ответа API: панель не знает ни про банк, ни про рынок.
// Появилась настройка в chat_settings.py — появилась и здесь, править нечего.

async function loadChatSettings() {
  // Чат один, выбирать нечего. Но раздел могли открыть первым — тогда
  // рабочий чат ещё не загружен, и без этого запроса форма осталась бы пустой.
  if (!чат()) await loadChats();
  await renderChatSettings();
}

async function renderChatSettings() {
  const chatId = чат();
  const out = $("#chatsettings-out");
  if (!chatId) { out.innerHTML = ""; return; }
  out.innerHTML = skeleton(3);
  try {
    const { groups } = await api(`/api/chat-settings?chat_id=${chatId}`);
    // Секций девять, и раньше до «Дуэлей» можно было добраться только
    // прокруткой через всё. Лента-оглавление сверху прыгает к секции.
    const якоря = groups.length > 1
      ? `<nav class="cs-anchors chips">${groups.map((g, i) =>
          `<button type="button" class="chip" data-cs-anchor="cs-${i}">${escapeHtml(g.group)}</button>`).join("")}</nav>`
      : "";
    out.innerHTML = якоря + groups.map(chatSettingsGroup).join("");
    $$("#chatsettings-out [data-cs-anchor]").forEach((b) =>
      b.addEventListener("click", () => {
        const цель = document.getElementById(b.dataset.csAnchor);
        if (цель) цель.scrollIntoView({ behavior: "smooth", block: "start" });
      }));
    $$("#chatsettings-out [data-setting]").forEach((el) =>
      el.addEventListener("change", () => saveChatSetting(el)));
  } catch (e) {
    out.innerHTML = `<div class="card error">${escapeHtml(e.message)}</div>`;
  }
}

function chatSettingsGroup(group, i) {
  const rows = group.settings.map(chatSettingField).join("");
  return `<section class="card cs-card" id="cs-${i}">
    <h2>${escapeHtml(group.group)}</h2><div class="cs-grid">${rows}</div></section>`;
}

function chatSettingField(s) {
  const off = s.can_edit ? "" : " disabled";
  let input;
  if (s.kind === "bool") {
    const checked = s.value ? " checked" : "";
    input = `<input type="checkbox" data-setting="${s.key}"${checked}${off}>`;
  } else if (s.kind === "choice") {
    const options = s.choices
      .map((c) => `<option value="${escapeHtml(c.value)}"${c.value === s.value ? " selected" : ""}>${escapeHtml(c.label)}</option>`)
      .join("");
    input = `<select data-setting="${s.key}"${off}>${options}</select>`;
  } else {
    input = `<input type="number" step="any" data-setting="${s.key}" value="${s.value}"${off}
      min="${s.minimum}" max="${s.maximum}" autocomplete="off">`;
  }
  const notes = [];
  if (s.hint) notes.push(escapeHtml(s.hint));
  if (s.global) notes.push("Действует во ВСЕХ чатах.");
  if (!s.can_edit) notes.push(`Нужен уровень «${escapeHtml(s.level_name)}».`);
  const note = notes.length ? `<div class="muted">${notes.join(" ")}</div>` : "";
  return `<div class="setting-row"><label>${escapeHtml(s.title)}${input}</label>${note}</div>`;
}

async function saveChatSetting(el) {
  const chatId = чат();
  const value = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
  try {
    await api("/api/chat-settings", {
      method: "POST",
      body: { chat_id: Number(chatId), key: el.dataset.setting, value: String(value) },
    });
    // В app.js нет глобального toast() — есть say(селектор, текст, kind),
    // который пишет в конкретный элемент на странице. Свой toast заводить
    // не стали: молча несуществующая функция уронила бы вкладку только в
    // браузере, тесты этого не видят.
    say("#chatsettings-msg", "Сохранено");
  } catch (e) {
    say("#chatsettings-msg", e.message, "err");
    // Значение не доехало — перерисовываем, чтобы в поле не осталось то,
    // чего в базе нет: иначе человек уверен, что настроил, а бот работает
    // по-старому.
    await renderChatSettings();
  }
}

// ===== Вкладка «Ферма» =====================================================
// Экран живёт по своему времени: сервер присылает сроки абсолютным UTC, а
// таймеры тикают здесь. Иначе каждая секунда обратного отсчёта стоила бы
// запроса, а вкладка, полежавшая в фоне, показывала бы прошлое.
const _farm = { state: null, skew: 0, tick: null, count: 1, slot: null, bound: false };

// Питон отдаёт время без пометки зоны («2026-08-02T12:00:00»), а JS такую
// строку читает как МЕСТНУЮ. Без этой буквы Z у человека в UTC+3 всё
// поспевало бы на три часа раньше, чем на самом деле.
function farmTime(iso) {
  if (!iso) return null;
  return Date.parse(/[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
}

// Часы браузера могут отставать или спешить. Разницу с сервером запоминаем
// один раз на ответ и дальше считаем по ней — иначе сбитые часы показали бы
// «готово» на грядке, которая ещё растёт.
function farmNow() { return Date.now() + _farm.skew; }

function farmLeft(ms) {
  if (ms <= 0) return "готово";
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `${h} ч ${String(m).padStart(2, "0")} м`;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function farmSay(text, kind = "ok") {
  const box = $("#member-farm-msg");
  if (box) say("#member-farm-msg", text, kind);
}

async function loadMemberFarm() {
  const box = $("#member-farm");
  box.innerHTML = `<section class="member-block"><h2>${icon("sprout")}Ферма</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${icon("sprout")}Ферма</h2>
      <div class="card">
        <div id="member-farm-msg"></div>
        <div id="member-farm-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!_farm.bound) { $("#member-farm").addEventListener("click", onFarmClick); _farm.bound = true; }
    loadFarmState();
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${icon("sprout")}Ферма</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

async function loadFarmState() {
  try {
    applyFarmState(await api(`/api/member/game/farm`));
  } catch (err) {
    const body = $("#member-farm-body");
    if (body) body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function applyFarmState(state) {
  _farm.state = state;
  _farm.skew = farmTime(state.now) - Date.now();
  renderFarm();
}

// Погодная строка: что погода ДЕЛАЕТ, а не только как называется. Без этого
// «Дождь» — картинка, а не правило, по которому человек выбирает культуру.
function weatherNote(w) {
  const части = [];
  if (w.grow_percent > 0) части.push(`растёт быстрее на ${w.grow_percent}%`);
  if (w.grow_percent < 0) части.push(`растёт медленнее на ${-w.grow_percent}%`);
  if (w.yield_percent) части.push(`урожай ${w.yield_percent > 0 ? "+" : ""}${w.yield_percent}%`);
  if (w.pest_percent > 0) части.push("вредители злее");
  if (w.pest_percent < 0) части.push("вредителей меньше");
  return части.length ? части.join(" · ") : "обычный день";
}

function plotHtml(p) {
  if (!p.crop) {
    return `<button type="button" class="plot free" data-act="plant" data-slot="${p.slot}">
      <span class="plot-plus">+</span><small>посадить</small></button>`;
  }
  const ready = p.ready;
  const классы = ["plot"];
  if (ready) классы.push("ready");
  if (p.pests) классы.push("pests");
  if (p.perished) классы.push("perished");
  const значок = p.perished ? `<span class="plot-badge warn">${icon("wilt")} сгнила</span>`
    : p.pests ? `<span class="plot-badge">${icon("bug")} ${p.pest_loss}%</span>` : "";
  const подпись = p.perished ? "сгнила" : ready ? "готово" : farmLeft(farmTime(p.ready_at) - farmNow());
  return `<button type="button" class="${классы.join(" ")}" data-act="plot" data-slot="${p.slot}"
      data-ready="${escapeHtml(p.ready_at)}" data-planted="${escapeHtml(p.planted_at)}"
      style="--grown:${ready ? 100 : p.progress}">
    <span class="plot-ring"></span>${значок}
    <span class="plot-plant game-emoji xl">${escapeHtml(p.emoji || "🌱")}</span>
    <span class="plot-label">${escapeHtml(подпись)}</span>
    <span class="plot-crop">${escapeHtml(p.name)}</span>
  </button>`;
}

function barnHtml(a) {
  const есть = a.quantity > 0;
  const продукт = `<span class="game-emoji">${escapeHtml(a.item_emoji || "📦")}</span>`;
  const строка = есть
    ? (a.ready > 0
        ? `${продукт} <b>${a.ready} ${escapeHtml(a.item_name.toLowerCase())}</b> готово`
        : a.next_at
          ? `${продукт} следующая порция через <span data-next="${escapeHtml(a.next_at)}">${farmLeft(farmTime(a.next_at) - farmNow())}</span>`
          : "хлев полон — заберите продукт")
    : `${продукт} ${escapeHtml(a.item_name.toLowerCase())} · ${a.price} i¢ за голову`;
  const кнопки = есть
    ? `<button type="button" class="btn" data-act="barn_buy" data-animal="${a.key}">Купить ещё</button>
       <button type="button" class="btn ghost" data-act="barn_sell" data-animal="${a.key}">Продать (${a.sell_back} i¢)</button>`
    : `<button type="button" class="btn" data-act="barn_buy" data-animal="${a.key}">Купить · ${a.price} i¢</button>`;
  return `<div class="barn-card${есть ? " has" : ""}">
    <div class="barn-head">
      <span class="barn-emoji game-emoji lg">${escapeHtml(a.emoji || "🐾")}</span>
      <span class="barn-name">${escapeHtml(a.name)}</span>
      <span class="barn-qty">${есть ? `×${a.quantity}` : ""}</span>
    </div>
    <div class="barn-note">${строка}</div>
    <div class="barn-buttons">${кнопки}</div>
  </div>`;
}

function renderFarm() {
  const s = _farm.state, body = $("#member-farm-body");
  if (!s || !body) return;
  const спелых = s.plots.filter((p) => p.crop && p.ready).length;
  const вхлеву = s.barn.reduce((n, a) => n + a.ready, 0);
  const бонусы = [];
  if (s.aura.speed) бонусы.push(`${icon("clock")} рост +${s.aura.speed}%`);
  if (s.aura.harvest) бонусы.push(`${icon("bee")} урожай +${s.aura.harvest}%`);
  if (s.aura.truffle) бонусы.push(`${icon("star")} трюфели ${s.aura.truffle}%`);
  if (s.pests_off) бонусы.push(`${icon("mask")} пугало на месте`);

  // Сцена рисует погоду сама (солнце, тучи, ливень — по data-weather), эмодзи
  // ей не нужен; грядки и действия стоят на почве той же сцены.
  body.innerHTML = `
    <div class="farm-scene" data-weather="${escapeHtml(s.weather.key || "sun")}">
      <div class="farm-rain"></div>
      <div class="farm-sky">
        <span>
          <span class="farm-sky-name">${escapeHtml(s.weather.name)}</span>
          <span class="farm-sky-note">${escapeHtml(weatherNote(s.weather))}</span>
        </span>
        <span class="farm-sky-coins"><b>${s.coins.toLocaleString("ru")} i¢</b>
          <span>${s.plot_total} грядок · свободно ${s.plot_free}</span></span>
      </div>
      <div class="farm-field">
        <div class="farm-plots">
          ${s.plots.map(plotHtml).join("")}
          ${s.plot_room > 0
            ? `<button type="button" class="plot buy" data-act="expand">
                 <span class="plot-plus">+</span><small>грядка<br>${s.plot_next_price} i¢</small></button>`
            : ""}
        </div>
        <div class="farm-actions">
          <button type="button" class="btn btn-harvest" data-act="harvest" ${спелых ? "" : "disabled"}>
            ${icon("basket")}Собрать урожай${спелых ? ` · ${спелых}` : ""}</button>
          ${вхлеву ? `<button type="button" class="btn" data-act="barn_collect">${icon("barn")}Забрать из хлева · ${вхлеву}</button>` : ""}
        </div>
      </div>
    </div>
    ${бонусы.length ? `<div class="farm-bonuses muted">${бонусы.join(" · ")}</div>` : ""}
    <h3 class="block-head">${icon("barn")}Хлев</h3>
    <div class="barn">${s.barn.map(barnHtml).join("")}</div>`;

  startFarmTick();
}

// Тикаем по узлам, а не перерисовкой: перерисовка каждую секунду сбрасывала бы
// нажатие, прокрутку и открытую шторку.
function startFarmTick() {
  if (_farm.tick) clearInterval(_farm.tick);
  _farm.tick = setInterval(() => {
    const узлы = $$("#member-farm-body .plot[data-ready]");
    if (!узлы.length && !$$("#member-farm-body [data-next]").length) return;
    let поспело = false;
    узлы.forEach((el) => {
      const ready = farmTime(el.dataset.ready), planted = farmTime(el.dataset.planted);
      const всего = Math.max(1, ready - planted), прошло = farmNow() - planted;
      const процент = Math.max(0, Math.min(100, Math.round((прошло / всего) * 100)));
      el.style.setProperty("--grown", процент);
      const label = el.querySelector(".plot-label");
      if (el.classList.contains("perished")) return;
      if (ready <= farmNow()) {
        if (!el.classList.contains("ready")) { el.classList.add("ready"); поспело = true; }
        if (label) label.textContent = "готово";
      } else if (label) {
        label.textContent = farmLeft(ready - farmNow());
      }
    });
    $$("#member-farm-body [data-next]").forEach((el) => {
      const срок = farmTime(el.dataset.next) - farmNow();
      el.textContent = farmLeft(срок);
      if (срок <= 0) loadFarmState();
    });
    // Грядка поспела прямо на глазах — кнопку сбора надо включить, а её
    // счётчик обновить. Полная перерисовка тут уместна: событие редкое.
    if (поспело) loadFarmState();
  }, 1000);
}

function stopFarmTick() {
  if (_farm.tick) { clearInterval(_farm.tick); _farm.tick = null; }
}

async function farmDo(action, body, успех) {
  try {
    const res = await api(`/api/member/game/farm/${action}`, {
      method: "POST", body: { ...body },
    });
    applyFarmState(res.state);
    farmSay(успех(res));
  } catch (err) {
    farmSay(err.message, "err");
  }
}

function farmItemsText(items) {
  const s = _farm.state;
  const имена = {};
  (s.crops || []).forEach((c) => { имена[c.key] = c.item_name; });
  const части = Object.entries(items || {}).map(([k, n]) => `${имена[k] || k} ×${n}`);
  return части.join(", ");
}

async function onFarmClick(e) {
  const el = e.target.closest("[data-act]");
  // Шторка выбора культуры живёт в document.body, а не внутри экрана: иначе
  // её перекрывали бы соседние карточки. Поэтому проверка «внутри экрана»
  // обязана пускать и её — без этого клик по культуре никуда не доходил, и
  // посадка с сайта не работала вовсе.
  if (!el) return;
  const свой = $("#member-farm")?.contains(el) || el.closest("#farm-sheet");
  if (!свой) return;
  const act = el.dataset.act;
  const s = _farm.state;
  if (act === "plant") {
    openCropSheet(Number(el.dataset.slot));
  } else if (act === "plot") {
    const p = s.plots.find((x) => String(x.slot) === el.dataset.slot);
    if (!p) return;
    if (p.perished || p.ready) {
      farmDo("harvest", {}, (r) => {
        const части = [];
        if (r.harvested) части.push(`Собрано: ${farmItemsText(r.items)}`);
        if (r.truffles) части.push(`трюфель ×${r.truffles}: +${r.coins_gained} i¢`);
        if (r.perished) части.push(`${r.perished} сгнило`);
        if (r.pest_loss) части.push(`саранча съела до ${r.pest_loss}%`);
        return части.join(" · ") || "Грядки освобождены";
      });
    } else if (p.pests) {
      farmSay("Саранчу со своих грядок прогнать нельзя — попросите соседа в чате: «ферма помочь @вы».", "err");
    } else {
      farmSay(`${p.name} поспеет через ${farmLeft(farmTime(p.ready_at) - farmNow())}.`);
    }
  } else if (act === "harvest") {
    farmDo("harvest", {}, (r) => {
      const части = [];
      if (r.harvested) части.push(`Собрано: ${farmItemsText(r.items)}`);
      if (r.truffles) части.push(`трюфель ×${r.truffles}: +${r.coins_gained} i¢`);
      if (r.perished) части.push(`${r.perished} сгнило`);
      return части.join(" · ") || "Собирать было нечего";
    });
  } else if (act === "expand") {
    farmDo("expand", { count: 1 }, (r) => `Грядка куплена за ${r.coins_spent} i¢`);
  } else if (act === "barn_collect") {
    farmDo("barn_collect", {}, (r) => `Забрано из хлева: ${farmItemsText(r.items) || r.harvested}`);
  } else if (act === "barn_buy") {
    farmDo("barn_buy", { animal: el.dataset.animal, count: 1 },
      (r) => `Куплено голов: ${r.planted} за ${r.coins_spent} i¢`);
  } else if (act === "barn_sell") {
    farmDo("barn_sell", { animal: el.dataset.animal, count: 1 },
      (r) => `Продано голов: ${r.harvested}, +${r.coins_gained} i¢`);
  } else if (act === "sow") {
    closeCropSheet();
    farmDo("plant", { crop: el.dataset.crop, count: _farm.count, slot: _farm.slot },
      (r) => `Посажено грядок: ${r.planted} (−${r.coins_spent} i¢)`);
  } else if (act === "count") {
    _farm.count = el.dataset.count === "все" ? "все" : 1;
    openCropSheet(_farm.slot);
  } else if (act === "sheet-close") {
    closeCropSheet();
  }
}

function closeCropSheet() {
  const el = $("#farm-sheet");
  if (el) el.remove();
  document.removeEventListener("keydown", onSheetKey);
}

function onSheetKey(e) { if (e.key === "Escape") closeCropSheet(); }

// Шторка выбора культуры. Цена, срок и «сколько хватит монет» стоят на самой
// строке: выбор делается здесь, и уходить за этими цифрами в чат человек не
// должен.
function openCropSheet(slot) {
  closeCropSheet();
  // Запоминаем, по какой грядке нажали: сажать надо туда, куда попал палец, а
  // не в первую свободную — иначе росток всходит в другом углу экрана.
  _farm.slot = Number.isFinite(slot) ? slot : null;
  const s = _farm.state;
  const строки = s.crops.map((c) => {
    const срок = farmLeft(c.grow_seconds * 1000);
    const хватит = Math.min(c.affordable, s.plot_free);
    const мало = c.locked || хватит < 1;
    // Причины «нельзя» разные, и валить их в «не хватает монет» нечестно:
    // с полным кошельком и занятым полем подпись обвиняла кошелёк.
    const пометка = c.locked ? "только во время ивента"
      : s.plot_free < 1 ? "нет свободных грядок"
      : c.affordable < 1 ? "не хватает монет"
      : `${срок} · ${c.yield_min}–${c.yield_max} шт${c.perish_hours ? ` · сгниёт через ${c.perish_hours} ч` : ""}`;
    return `<button type="button" class="crop-row" data-act="sow" data-crop="${c.key}" ${мало ? "disabled" : ""}>
      <span class="crop-emoji game-emoji lg">${escapeHtml(c.emoji || "🌱")}</span>
      <span><span class="crop-name">${escapeHtml(c.name)}</span>
        <span class="crop-meta">${escapeHtml(пометка)}</span></span>
      <span class="crop-price">${c.price} i¢<small>хватит на ${хватит}</small></span>
    </button>`;
  }).join("");
  const одна = _farm.count === 1;
  const sheet = document.createElement("div");
  sheet.className = "sheet-back";
  sheet.id = "farm-sheet";
  sheet.innerHTML = `<div class="sheet" role="dialog" aria-label="Что посадить">
    <div class="sheet-head"><h3>Что посадить</h3>
      <button type="button" class="sheet-close" data-act="sheet-close" aria-label="Закрыть">×</button></div>
    <div class="farm-actions mb-3">
      <button type="button" class="btn ${одна ? "" : "ghost"}" data-act="count" data-count="1">Одну грядку</button>
      <button type="button" class="btn ${одна ? "ghost" : ""}" data-act="count" data-count="все">Всё поле · ${s.plot_free}</button>
    </div>
    ${строки}</div>`;
  // Клик по подложке закрывает шторку, клик по культуре идёт в общий
  // обработчик экрана — он же разбирает и «сажать одну / всё поле».
  sheet.addEventListener("click", (e) => {
    if (e.target === sheet) closeCropSheet();
    else onFarmClick(e);
  });
  document.body.appendChild(sheet);
  document.addEventListener("keydown", onSheetKey);
}

// ===== Вкладка «Казино» ====================================================
// Экран играет ставками, поэтому правило здесь одно: всё, что про деньги,
// решает сервер. Браузер рисует ленту и карты, но исход приходит готовым — и
// в чат уходит не то, что нарисовано, а то, что сервер у себя записал.
const _casino = { state: null, game: "roulette", bet: 100,
                  color: "red", guess: 1, side: "орёл", last: null, bound: false,
                  // Накопленные углы колеса и шарика. Именно накопленные, а не
                  // остаток от 360: колесо должно всегда доворачиваться
                  // вперёд, а не отматываться назад к ближайшему совпадению.
                  angle: 0, ball: 0, dieX: 0, dieY: 0, coin: 0,
                  // Предмет игры в движении. Пока true, итог не показывают
                  // нигде: ни на самом предмете, ни текстом, ни балансом.
                  spinning: false };

// Порядок чисел по кругу — как на настоящем европейском колесе. Он не
// случайный и не по возрастанию: красные и чёрные чередуются, а соседи по
// кругу далеки по значению — так на колесе не остаётся «удачной» четверти.
// Здесь он ещё и рабочий: по месту числа в этом списке считается, куда
// довернуть колесо.
const WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11,
                     30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
                     29, 7, 28, 12, 35, 3, 26];
const WHEEL_STEP = 360 / WHEEL_ORDER.length;
const WHEEL_SPIN_MS = 4200;
const WHEEL_TURNS = 6;
const SPIN_SKIP_KEY = "casino-skip-spin";

// Крутить или показать сразу. Выбор человека, а не наш: одному вращение —
// половина игры, другому оно каждый раз стоит четырёх секунд.
//
// Пока не выбрали — спрашиваем систему. «Убрать анимации» в настройках
// телефона включают ровно из этих соображений, и переспрашивать то же самое
// ещё раз невежливо. Но выбор в панели всегда сильнее: настройка системы —
// это умолчание, а не запрет.
function spinSkipped() {
  let свой = null;
  try { свой = localStorage.getItem(SPIN_SKIP_KEY); } catch (e) { свой = null; }
  if (свой !== null) return свой === "1";
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
// Шарик катится навстречу колесу — как на настоящем. Оборотов целое число,
// поэтому он всегда возвращается наверх, к стрелке: там же, где встанет
// выпавшее число.
const BALL_TURNS = 10;

// Ближайшее положение с нужным остатком, но не ближе чем через столько-то
// оборотов вперёд.
//
// Углы копятся, а не сбрасываются к остатку от 360: иначе предмет то дёргался
// бы на месте (когда нужное положение совпало с текущим), то отматывался бы
// назад — и то и другое выглядит поломкой, а не броском.
function nextAngle(было, нужен, оборотов) {
  const цель = ((нужен % 360) + 360) % 360;
  let угол = Math.floor(было / 360) * 360 + цель;
  while (угол < было + 360 * оборотов) угол += 360;
  return угол;
}

// Куда довернуть колесо, чтобы выпавшее число встало под стрелкой.
//
// Вынесено отдельной функцией не для красоты: ошибка здесь не видна. Колесо
// будет так же красиво крутиться и так же плавно останавливаться — просто не
// на том числе, и заметить это можно только сверив с текстом итога. Поэтому
// функция чистая и проверяется отдельно, на всех тридцати семи числах.
function wheelAngle(было, number, оборотов = WHEEL_TURNS) {
  const место = WHEEL_ORDER.indexOf(number);
  if (место < 0) return было;
  // Сектор с местом i стоит под углом i * шаг по часовой от верха. Чтобы он
  // оказался под стрелкой, колесо надо повернуть ровно на минус этот угол.
  return nextAngle(было, -место * WHEEL_STEP, оборотов);
}

// --- кость -----------------------------------------------------------------
// Настоящий куб: шесть граней, каждая на своём месте, и кость приземляется
// выпавшей гранью к зрителю. Точки, а не символы ⚀⚁⚂⚃⚄⚅: те рисуются шрифтом
// системы и на разных телефонах выглядят по-разному, а на части — квадратами.

// Где какая грань стоит в покое. Противоположные в сумме дают семь, как на
// настоящей кости.
const DIE_SIDES = [
  { n: 1, t: "translateZ(var(--die-half))" },
  { n: 6, t: "rotateY(180deg) translateZ(var(--die-half))" },
  { n: 3, t: "rotateY(90deg) translateZ(var(--die-half))" },
  { n: 4, t: "rotateY(-90deg) translateZ(var(--die-half))" },
  { n: 5, t: "rotateX(90deg) translateZ(var(--die-half))" },
  { n: 2, t: "rotateX(-90deg) translateZ(var(--die-half))" },
];

// Куда повернуть КУБ, чтобы нужная грань смотрела на зрителя, — обратный
// поворот к тому, которым грань поставлена на место.
//
// Каждый поворот здесь вокруг ОДНОЙ оси, и это не случайность: полный оборот
// есть тождество, поэтому rotateX(360a + X) rotateY(360b + Y) сводится ровно
// к rotateX(X) rotateY(Y) при любом порядке сомножителей. Понадобись какой-то
// грани оба угла сразу — порядок начал бы значить, и промахнулась бы она
// одна: самый трудный для поимки случай.
const DIE_FACE = {
  1: { x: 0, y: 0 },
  6: { x: 0, y: 180 },
  3: { x: 0, y: -90 },
  4: { x: 0, y: 90 },
  5: { x: -90, y: 0 },
  2: { x: 90, y: 0 },
};
const DIE_TURNS_X = 3;
const DIE_TURNS_Y = 4;   // разное число оборотов по осям: кость кувыркается,
                         // а не вращается вокруг одной оси, как волчок

function dieAngles(былоX, былоY, roll) {
  const грань = DIE_FACE[roll];
  if (!грань) return { x: былоX, y: былоY };
  return { x: nextAngle(былоX, грань.x, DIE_TURNS_X),
           y: nextAngle(былоY, грань.y, DIE_TURNS_Y) };
}

// --- монета ----------------------------------------------------------------
// Орёл смотрит на зрителя в покое, решка — с обратной стороны.
const COIN_FACE = { "орёл": 0, "решка": 180 };
const COIN_TURNS = 5;

// Сколько длится бросок. Колесо крутится долго — на него и смотрят; кость и
// монета в жизни падают быстро, и растянутое падение читается как задержка,
// а не как игра.
const DIE_ROLL_MS = 1500;
const COIN_FLIP_MS = 1300;

// Игры, у которых есть что пропускать: там итог ждёт конца броска.
const ANIMATED_GAMES = new Set(["roulette", "dice", "coin"]);

function coinAngle(было, side) {
  const грань = COIN_FACE[side];
  if (грань === undefined) return было;
  return nextAngle(было, грань, COIN_TURNS);
}

function casinoSay(text, kind = "ok") {
  if ($("#member-casino-msg")) say("#member-casino-msg", text, kind);
}

async function loadMemberCasino() {
  const box = $("#member-casino");
  box.innerHTML = `<section class="member-block"><h2>${icon("casino")}Казино</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${icon("casino")}Казино</h2>
      <div class="card">
        <div id="member-casino-msg"></div>
        <div id="member-casino-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!_casino.bound) {
      $("#member-casino").addEventListener("click", onCasinoClick);
      $("#member-casino").addEventListener("input", onCasinoInput);
      _casino.bound = true;
    }
    loadCasinoState();
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${icon("casino")}Казино</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

async function loadCasinoState() {
  try {
    _casino.state = await api(`/api/member/game/casino`);
    renderCasino();
  } catch (err) {
    const body = $("#member-casino-body");
    if (body) body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// Колесо рисуется разметкой SVG, а не картинкой: страница запрещает грузить
// что-либо со стороны, а нарисованное здесь одинаково чётко и на телефоне, и
// на большом экране.
//
// Ширина колеса задаётся стилем (min(100%, …)), поэтому оно физически не
// может стать шире экрана. Прежняя лента могла и была: сорок одна клетка по
// 56 пикселей — больше двух тысяч, пять экранов телефона.
function wheelHtml() {
  const красные = new Set(_casino.state.reds || []);
  const Ц = 100, R = 96, r = 56;                 // центр, внешний и внутренний радиус
  const точка = (ρ, φ) => {
    const рад = φ * Math.PI / 180;
    return [(Ц + ρ * Math.sin(рад)).toFixed(2), (Ц - ρ * Math.cos(рад)).toFixed(2)];
  };
  const секторы = WHEEL_ORDER.map((n, i) => {
    const от = i * WHEEL_STEP - WHEEL_STEP / 2, до = от + WHEEL_STEP;
    const [x1, y1] = точка(R, от), [x2, y2] = точка(R, до);
    const [x3, y3] = точка(r, до), [x4, y4] = точка(r, от);
    const цвет = n === 0 ? "green" : красные.has(n) ? "red" : "black";
    return `<path class="wheel-slot ${цвет}" `
         + `d="M${x1} ${y1}A${R} ${R} 0 0 1 ${x2} ${y2}L${x3} ${y3}A${r} ${r} 0 0 0 ${x4} ${y4}Z"/>`;
  }).join("");
  // Числа поворачиваются вместе с колесом — как на настоящем. Считать это
  // ошибкой не надо: выпавшее число останавливается под стрелкой ровно
  // прямым, потому что колесо доворачивается на минус его угол.
  const числа = WHEEL_ORDER.map((n, i) =>
    `<text class="wheel-num" x="${Ц}" y="${Ц - (R + r) / 2}" dy=".35em" `
    + `transform="rotate(${(i * WHEEL_STEP).toFixed(2)} ${Ц} ${Ц})">${n}</text>`).join("");
  const угол = _casino.angle || 0;
  // Пока колесо крутится, середина пустая. Число, показанное раньше
  // остановки, отменяет смысл вращения: смотреть уже не на что.
  const итог = !_casino.spinning && _casino.last && _casino.last.detail
    && typeof _casino.last.detail.number === "number" ? _casino.last.detail.number : null;
  return `<div class="wheel-wrap">
      <svg class="wheel" id="casino-wheel" viewBox="0 0 200 200" aria-hidden="true"
           style="transform: rotate(${угол}deg)">
        <circle class="wheel-rim" cx="${Ц}" cy="${Ц}" r="99"/>
        ${секторы}
        <circle class="wheel-hub" cx="${Ц}" cy="${Ц}" r="${r}"/>
        ${числа}
      </svg>
      <div class="wheel-pin" aria-hidden="true"></div>
      <div class="wheel-ball-orbit" id="casino-ball" aria-hidden="true"
           style="transform: rotate(${_casino.ball || 0}deg)"><i class="wheel-ball"></i></div>
      <div class="wheel-face" id="casino-wheel-face" aria-hidden="true">${итог === null ? "" : итог}</div>
    </div>`;
}

// Точки на грани. Раскладка настоящая: 1 в центре, 2 и 3 по диагонали, 4 по
// углам, 5 — углы и центр, 6 — два столбца по три.
const DIE_PIPS = {
  1: [[2, 2]],
  2: [[1, 1], [3, 3]],
  3: [[1, 1], [2, 2], [3, 3]],
  4: [[1, 1], [1, 3], [3, 1], [3, 3]],
  5: [[1, 1], [1, 3], [2, 2], [3, 1], [3, 3]],
  6: [[1, 1], [2, 1], [3, 1], [1, 3], [2, 3], [3, 3]],
};

// Грань кости. Одна и та же и в броске, и в строке итога: предмет игры обязан
// выглядеть одинаково там, где он катится, и там, где записан результат.
function dieFaceHtml(n, добавка = "") {
  const точки = (DIE_PIPS[n] || []).map(([ряд, кол]) =>
    `<i class="pip" style="grid-area:${ряд}/${кол}"></i>`).join("");
  // Единица — «туз» с красным пипом, как у настоящих казино-костей; класс
  // работает и на кубе, и на кнопках выбора, и в строке итога.
  return `<span class="die-face ${добавка}${n === 1 ? " ace" : ""}" role="img" aria-label="${n}">${точки}</span>`;
}

function die3dHtml() {
  const грани = DIE_SIDES.map((с) =>
    `<span class="die-side" style="transform:${с.t}">${dieFaceHtml(с.n)}</span>`).join("");
  const x = _casino.dieX || 0, y = _casino.dieY || 0;
  return `<div class="casino-stage die3d">
      <div class="die3d-cube" id="casino-die"
           style="transform: rotateX(${x}deg) rotateY(${y}deg)">${грани}</div>
    </div>`;
}

// Масти карт — inline-SVG, а не символы ♥♦♠♣: на части телефонов шрифт
// подменяет их эмодзи (тот же класс бага, что 🂠, с которого покер и
// рисовал десять битых рубашек вместо пяти).
const SUIT_PATHS = {
  "♥": "M12 21C7 16.5 3 13 3 8.8 3 6 5.2 4 7.6 4c1.8 0 3.3.9 4.4 2.6C13.1 4.9 14.6 4 16.4 4 18.8 4 21 6 21 8.8c0 4.2-4 7.7-9 12.2z",
  "♦": "M12 2l8 10-8 10-8-10z",
  "♠": "M12 2C8.5 6.8 4 9.3 4 13.2 4 15.8 6 17.5 8.3 17.5c1 0 1.9-.3 2.7-1-.3 1.9-1 3.3-2.3 4.5h6.6c-1.3-1.2-2-2.6-2.3-4.5.8.7 1.7 1 2.7 1C18 17.5 20 15.8 20 13.2 20 9.3 15.5 6.8 12 2z",
  "♣": "M12 2a4 4 0 0 0-3.2 6.4A4 4 0 1 0 10.9 15c-.2 2-.9 3.5-2.2 4.7h6.6c-1.3-1.2-2-2.7-2.2-4.7a4 4 0 1 0 2.1-6.6A4 4 0 0 0 12 2z",
};

function suitSvg(suit, cls = "") {
  return `<svg class="pc-s${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true"><path d="${SUIT_PATHS[suit]}"/></svg>`;
}

// Сторона монеты. Слово, а не картинка: «орёл» и «решка» — это и есть их
// имена, и в строке итога написано ровно то же слово. Символы 🦅 и 🪙 рисуются
// шрифтом системы и на разных телефонах выглядят по-разному.
function coinHtml() {
  const угол = _casino.coin || 0;
  // Пять дисков между лицом (+4px) и изнанкой (−4px): в профиль их рёбра
  // складываются в толщину — без них rotateY схлопывает монету в линию.
  const сердцевина = [-3, -1.5, 0, 1.5, 3].map((z) =>
    `<span class="coin-core" style="transform: translateZ(${z}px)"></span>`).join("");
  return `<div class="casino-stage coin-scene">
      <div class="coin-shadow" id="casino-coin-shadow"></div>
      <div class="coin3d">
        <div class="coin3d-inner" id="casino-coin" style="transform: rotateY(${угол}deg)">
          ${сердцевина}
          <span class="coin-side coin-head">орёл</span>
          <span class="coin-side coin-tail">решка</span>
        </div>
      </div>
    </div>`;
}

// Переключатель показывается у всех игр, где есть что пропускать. Отдельной
// функцией, чтобы у трёх игр он был один и тот же, а не три похожих.
function skipToggleHtml() {
  return `<label class="check spin-skip">
      <input type="checkbox" id="casino-skip" autocomplete="off"
             ${spinSkipped() ? "checked" : ""}>
      <span class="muted">Без анимации — сразу результат</span>
    </label>`;
}

function casinoTableHtml() {
  const s = _casino.state;
  if (_casino.game === "roulette") {
    const фишки = s.colors.map((c) => `
      <button type="button" class="chip ${c.key} ${_casino.color === c.key ? "active" : ""}"
              data-cact="color" data-color="${c.key}">
        ${escapeHtml(c.label)}<small>x${c.payout}</small></button>`).join("");
    return `${wheelHtml()}${skipToggleHtml()}
            <div class="chips">${фишки}</div>`;
  }
  if (_casino.game === "dice") {
    // Кнопка выбора показывает ту же грань, что упадёт: цифра рядом с точками
    // нужна тем, кому точки считать долго.
    const грани = [1, 2, 3, 4, 5, 6].map((n) =>
      `<button type="button" class="btn die-pick ${_casino.guess === n ? "active" : ""}"
               data-cact="guess" data-guess="${n}">${dieFaceHtml(n, "die-face-sm")}</button>`).join("");
    return `${die3dHtml()}${skipToggleHtml()}
            <div class="faces">${грани}</div>
            <div class="hint">Угадали грань — ставка ×6.</div>`;
  }
  if (_casino.game === "coin") {
    // Кнопки — жетоны с тем же металлом, что у большой монеты: золотой орёл,
    // серебряная решка. Исход и выбор связываются цветом, не только словом.
    const стороны = [["орёл", "head"], ["решка", "tail"]].map(([x, k]) =>
      `<button type="button" class="side-pick ${_casino.side === x ? "active" : ""}"
               data-cact="side" data-side="${x}">
         <span class="coin-mini ${k}"></span>${x}<small>×2</small></button>`).join("");
    return `${coinHtml()}${skipToggleHtml()}
            <div class="sides">${стороны}</div>
            <div class="hint">Угадали сторону — ставка ×2.</div>`;
  }
  // Покер. Рубашки — циклом по пяти, а не "🂠".repeat(5).split(""): эмодзи
  // рвался на половины суррогатной пары, и на столе лежали ДЕСЯТЬ битых
  // карт. Рубашка рисуется CSS-ом, выплаты — пилюлями (комбинация-победитель
  // подсвечивается после раздачи).
  const пять = [0, 1, 2, 3, 4].map((i) =>
    `<div class="playing-card back" style="animation-delay:${i * 60}ms"></div>`).join("");
  const выплаты = [["две пары", 2], ["тройка", 3], ["стрит", 5], ["флеш", 6],
                   ["фулл-хаус", 8], ["каре", 10], ["стрит-флеш", 10]]
    .map(([имя, x]) => `<span class="pay-pill" data-combo="${имя}">${имя} <b>×${x}</b></span>`).join("");
  return `<div class="casino-stage poker-felt"><div class="hand" id="casino-hand">${пять}</div></div>
          <div class="poker-pays" id="poker-pays">${выплаты}</div>`;
}

function casinoResultHtml() {
  const r = _casino.last;
  if (!r) return "";
  // Предмет игры ещё в движении — итога нет. Написать его сейчас значило бы
  // отдать ответ раньше, чем закончится вопрос.
  if (_casino.spinning) {
    const что = { roulette: "Колесо крутится", dice: "Кость катится",
                  coin: "Монета в воздухе" }[r.game] || "Ещё немного";
    return `<div class="casino-result waiting">${icon("clock")}${что}…</div>`;
  }
  const выиграл = r.won;
  const сумма = выиграл ? `+${r.delta.toLocaleString("ru")} i¢` : `${r.delta.toLocaleString("ru")} i¢`;
  // Предмет игры в итоге показан ТЕМ ЖЕ, что и в анимации: кость — теми же
  // точками, монета — тем же словом. Раньше тут стояли символы шрифта
  // (⚀⚁⚂⚃⚄⚅, 🦅, 🪙), и они же рисовались в самой игре; теперь и то и другое
  // нарисовано нами и совпадает на любом телефоне.
  const строка = r.game === "roulette"
      ? `Выпало <span class="rdot ${r.detail.number === 0 ? "green" : (_casino.state.reds || []).includes(r.detail.number) ? "red" : "black"}"></span> <b>${r.detail.number}</b>`
    : r.game === "dice" ? `Выпало ${dieFaceHtml(r.detail.roll, "die-face-sm")} <b>${r.detail.roll}</b> (ставили на ${r.detail.guess})`
    // В итоге монеты — тот же жетон, что на кнопке: исход совпадает с
    // выбором и цветом металла, а не только словом.
    : r.game === "coin" ? `Выпало <span class="coin-mini ${r.detail.side === "орёл" ? "head" : "tail"}"></span> <b>${escapeHtml(r.detail.side)}</b>`
    // hand_text с бэкенда набран шрифтовыми ♥♦ — те же битые глифы, что 🂠;
    // карты и так лежат на столе, в итоге достаточно названия комбинации.
    : `<b>${escapeHtml(r.detail.combo)}</b>`;
  return `<div class="casino-result ${выиграл ? "win" : "lose"}">
    <div>${строка}</div>
    <div class="sum">${выиграл ? `${сумма} (x${r.multiplier})` : сумма}</div>
    <div class="share">
      ${r.can_share
        ? `<button type="button" class="btn" data-cact="share">${icon("megaphone")}Показать в чате</button>`
        : `<span class="muted">Показано в чате.</span>`}
    </div></div>`;
}

function renderCasino() {
  const s = _casino.state, body = $("#member-casino-body");
  if (!s || !body) return;
  const игры = s.games.map((g) => `
    <button type="button" class="casino-game ${_casino.game === g.key ? "active" : ""}"
            data-cact="game" data-game="${g.key}">${gicon("game", g.key)} ${escapeHtml(g.title)}</button>`).join("");
  const множитель = s.event_multiplier && s.event_multiplier !== 1
    ? `<div class="casino-event">${icon("spark")} Событие чата: выигрыш ×${s.event_multiplier}. Ставка не меняется.</div>` : "";

  body.innerHTML = `
    <div class="casino-top">
      <div class="casino-balance"><b>${s.balance.toLocaleString("ru")} i¢</b>
        <span>в казино · в кошельке ${s.coins.toLocaleString("ru")} i¢</span></div>
      <div class="casino-money">
        ${s.bonus_ready
          ? `<button type="button" class="btn gold" data-cact="bonus" title="Ежедневный бонус">${icon("gift")}<span class="btn-label"> Бонус ${s.bonus_amount} i¢</span></button>`
          : `<button type="button" class="btn" disabled title="Бонус уже получен">${icon("gift")}<span class="btn-label"> Бонус завтра</span></button>`}
        <button type="button" class="btn" data-cact="topup" title="Пополнить из кошелька">${icon("in")}<span class="btn-label"> Пополнить</span></button>
        <button type="button" class="btn" data-cact="withdraw" title="Вывести в кошелёк">${icon("out")}<span class="btn-label"> Вывести</span></button>
      </div>
      ${множитель}
    </div>
    <div class="casino-games" id="casino-games">${игры}</div>
    <div class="casino-table">
      ${casinoTableHtml()}
      <label class="bet-field">
        <span>Ставка · не больше ${s.max_bet.toLocaleString("ru")} i¢</span>
        <input type="number" id="casino-bet" min="1" max="${s.max_bet}" value="${_casino.bet}"
               inputmode="numeric" autocomplete="off">
      </label>
      <div class="bet-quick">
        <button type="button" class="btn ghost" data-cact="bet" data-bet="100">100</button>
        <button type="button" class="btn ghost" data-cact="bet" data-bet="1000">1 000</button>
        <button type="button" class="btn ghost" data-cact="bet" data-bet="10000">10 000</button>
        <button type="button" class="btn ghost" data-cact="bet" data-bet="x2">×2</button>
        <button type="button" class="btn ghost" data-cact="bet" data-bet="все">Всё</button>
      </div>
      <button type="button" class="btn casino-play" data-cact="play"
              ${_casino.spinning ? "disabled" : ""}>${_casino.spinning ? "Крутится…" : "Играть"}</button>
      ${casinoResultHtml()}
    </div>`;

  // На телефоне лента игр листается, и выбранная вкладка могла остаться за
  // краем: без этого на открытом покере лента показывала «Рулетка, Кости…»
  // и никак не выдавала, что открыт покер. nearest — если вкладка и так
  // видна, ничего не прокручивается и страница не дёргается.
  const активная = body.querySelector(".casino-game.active");
  if (активная && активная.scrollIntoView) {
    активная.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

function onCasinoInput(e) {
  if (e.target.id === "casino-bet") _casino.bet = Number(e.target.value) || 0;
  if (e.target.id === "casino-skip") {
    try { localStorage.setItem(SPIN_SKIP_KEY, e.target.checked ? "1" : "0"); } catch (err) { /* приватный режим */ }
  }
}

// Повернуть узел от одного угла к другому.
//
// Ключевыми кадрами, а НЕ переходом между двумя стилями, и это не вкусовщина.
// Переход браузер запускает только между двумя ПОСЧИТАННЫМИ состояниями, а
// разметку перед вращением перерисовывают целиком: колесо — новый элемент,
// стиль ему ещё ни разу не считали, начальный и конечный угол попадают в один
// пересчёт — и перехода не возникает вовсе. Колесо просто оказывается в новом
// положении. Ровно так это и выглядело: «телепортируется».
//
// Лечить это принудительным пересчётом (чтением offsetWidth) можно, но
// лекарство держится на строке, которая выглядит бессмысленной и потому
// однажды будет убрана. Ключевые кадры знают начало и конец сами и ни от
// какого предыдущего состояния не зависят.
function крутить(узел, от, до, мс, плавность, ось = "rotate") {
  if (!узел) return;
  // Куда встать, когда всё кончится: анимация перекрывает стиль, пока идёт, и
  // отдаёт ему управление на выходе — без «повисания» на последнем кадре.
  узел.style.transform = `${ось}(${до}deg)`;
  if (typeof узел.animate !== "function") return;
  узел.animate([{ transform: `${ось}(${от}deg)` }, { transform: `${ось}(${до}deg)` }],
               { duration: мс, easing: плавность });
}

// То же для кости: две оси сразу. Порядок сомножителей одинаков в кадрах и в
// стиле — иначе кость приземлилась бы не туда, куда её посчитали.
function кувыркать(узел, отX, отY, доX, доY, мс) {
  if (!узел) return;
  const вид = (x, y) => `rotateX(${x}deg) rotateY(${y}deg)`;
  узел.style.transform = вид(доX, доY);
  if (typeof узел.animate !== "function") return;
  узел.animate([{ transform: вид(отX, отY) }, { transform: вид(доX, доY) }],
               // Кость бросают, а не раскручивают: резкий старт, короткий
               // выкат и лёгкая осадка в конце.
               { duration: мс, easing: "cubic-bezier(.2,.75,.25,1)" });
}

// Колесо останавливается на выпавшем числе. Анимация — ПОСЛЕ ответа сервера:
// крутить заранее и подгонять под результат значило бы показывать заход,
// которого ещё не было, и врать при ошибке сети.
//
// Колесо здесь — картинка происходящего, а не источник правды: что выпало,
// написано текстом в итоге, и текст не ждёт окончания вращения.
function spinWheel(number, мгновенно, кончилось) {
  const колесо = $("#casino-wheel");
  if (!колесо) { кончилось(); return; }
  const было = _casino.angle || 0;
  const стало = wheelAngle(было, number);
  _casino.angle = стало;
  const шарик = $("#casino-ball");
  const шарик_было = _casino.ball || 0;
  const шарик_стало = шарик_было - 360 * BALL_TURNS;
  _casino.ball = шарик_стало;

  const мс = мгновенно ? 0 : WHEEL_SPIN_MS;
  // Резкий старт и долгий выкат: так крутится настоящее колесо — сначала не
  // уследить за числами, потом последние полоборота ползёт.
  крутить(колесо, было, стало, мс, "cubic-bezier(.08,.62,.16,1)");
  // Шарик останавливается чуть раньше колеса: он падает в лунку, а колесо
  // после этого ещё доезжает.
  крутить(шарик, шарик_было, шарик_стало, Math.round(мс * 0.82),
          "cubic-bezier(.1,.55,.2,1)");
  // Число, баланс и итог показывает уже вызвавший — вместе с остановкой.
  setTimeout(кончилось, мс);
}

// Кость кувыркается по двум осям и падает выпавшей гранью к зрителю.
function rollDie(roll, мгновенно, кончилось) {
  const куб = $("#casino-die");
  if (!куб) { кончилось(); return; }
  const былоX = _casino.dieX || 0, былоY = _casino.dieY || 0;
  const { x, y } = dieAngles(былоX, былоY, roll);
  _casino.dieX = x;
  _casino.dieY = y;
  const мс = мгновенно ? 0 : DIE_ROLL_MS;
  кувыркать(куб, былоX, былоY, x, y, мс);
  setTimeout(кончилось, мс);
}

// Монета подлетает и переворачивается, приземляясь нужной стороной.
function flipCoin(side, мгновенно, кончилось) {
  const монета = $("#casino-coin");
  if (!монета) { кончилось(); return; }
  const было = _casino.coin || 0;
  const стало = coinAngle(было, side);
  _casino.coin = стало;
  const мс = мгновенно ? 0 : COIN_FLIP_MS;
  крутить(монета, было, стало, мс, "cubic-bezier(.25,.5,.3,1)", "rotateY");
  // Подброс — на внешней обёртке: она не участвует в трёхмерном повороте, и
  // взлёт не мешает вращению, а складывается с ним.
  const подброс = монета.parentElement;
  if (подброс && typeof подброс.animate === "function" && мс) {
    подброс.animate([
      { transform: "translateY(0)" },
      { transform: "translateY(-38%)", offset: .32 },
      { transform: "translateY(0)" },
    ], { duration: мс, easing: "cubic-bezier(.35,0,.35,1)" });
  }
  // Тень на сукне сжимается синхронно с верхней точкой подброса (offset .32):
  // именно она продаёт высоту полёта.
  const тень = $("#casino-coin-shadow");
  if (тень && typeof тень.animate === "function" && мс) {
    тень.animate([
      { transform: "translateX(-50%) scale(1)", opacity: .5 },
      { transform: "translateX(-50%) scale(.55)", opacity: .18, offset: .32 },
      { transform: "translateX(-50%) scale(1)", opacity: .5 },
    ], { duration: мс, easing: "cubic-bezier(.35,0,.35,1)" });
  }
  // Итог, баланс и кнопку возвращает вызвавший — вместе с приземлением.
  // Без этой строки монета «крутится вечно»: сама она садится, а экран
  // остаётся в полёте — итога нет, «Играть» не нажать. Ровно так и было.
  setTimeout(кончилось, мс);
}

async function casinoPlay() {
  const s = _casino.state;
  const тело = { bet: _casino.bet };
  if (_casino.game === "roulette") тело.color = _casino.color;
  if (_casino.game === "dice") тело.guess = _casino.guess;
  if (_casino.game === "coin") тело.side = _casino.side;
  const кнопка = $(".casino-play");
  if (кнопка) кнопка.disabled = true;
  try {
    const r = await api(`/api/member/game/casino/play/${_casino.game}`,
                        { method: "POST", body: тело });
    _casino.last = r;
    const мгновенно = spinSkipped();
    const оживает = ANIMATED_GAMES.has(_casino.game) && !мгновенно;
    // Баланс ждёт вместе с предметом игры. Иначе исход виден по нему —
    // подскочил, значит выиграл, — и бросок происходит уже впустую.
    _casino.spinning = оживает;
    if (!оживает) s.balance = r.balance;
    renderCasino();

    const показать = () => {
      _casino.spinning = false;
      s.balance = r.balance;
      renderCasino();
    };

    if (_casino.game === "roulette") {
      spinWheel(r.detail.number, мгновенно, показать);
    } else if (_casino.game === "dice") {
      rollDie(r.detail.roll, мгновенно, показать);
    } else if (_casino.game === "coin") {
      flipCoin(r.detail.side, мгновенно, показать);
    } else if (_casino.game === "poker") {
      // Карты раскрываются по одной — задержка считается на месте, поэтому
      // разметка строится здесь, а не в общей отрисовке.
      const рука = $("#casino-hand");
      if (рука) {
        рука.classList.toggle("win", r.won);
        рука.innerHTML = r.detail.hand.map(([rank, suit], i) => {
          const имя = { 11: "J", 12: "Q", 13: "K", 14: "A" }[rank] || rank;
          const красная = suit === "♥" || suit === "♦";
          return `<div class="playing-card${красная ? " red" : ""}" style="animation-delay:${i * 110}ms">
            <span class="pc-corner">${имя}${suitSvg(suit)}</span>
            ${suitSvg(suit, "pc-pip")}
            <span class="pc-corner pc-corner-b">${имя}${suitSvg(suit)}</span>
          </div>`;
        }).join("");
        // Подсветить пилюлю выигравшей комбинации. Совпадение берём самое
        // ДЛИННОЕ: иначе «стрит-флеш» зажёг бы заодно «стрит» и «флеш».
        const комбо = (r.detail.combo || "").toLowerCase();
        let лучшая = null;
        $$("#poker-pays .pay-pill").forEach((p) => {
          p.classList.remove("hit");
          if (r.won && комбо.includes(p.dataset.combo)
              && (!лучшая || p.dataset.combo.length > лучшая.dataset.combo.length)) лучшая = p;
        });
        if (лучшая) лучшая.classList.add("hit");
      }
    }
  } catch (err) {
    casinoSay(err.message, "err");
  } finally {
    // Пока предмет игры в движении, кнопку не возвращаем: второй заход
    // поверх первого показал бы итоги вперемешку. Её включит отрисовка после
    // остановки — она же знает, что движение кончилось.
    const b = $(".casino-play");
    if (b && !_casino.spinning) b.disabled = false;
  }
}

async function casinoMoney(action) {
  let сумма = null;
  if (action === "topup" || action === "withdraw") {
    const ответ = prompt(action === "topup"
      ? "Сколько перевести в казино? Можно слово «все»."
      : "Сколько вывести в кошелёк? Можно слово «все».", "1000");
    if (ответ === null) return;
    сумма = /^\s*(все|всё|all)\s*$/i.test(ответ) ? "все" : Number(ответ);
  }
  try {
    const r = await api(`/api/member/game/casino/${action}`,
                        { method: "POST", body: { amount: сумма } });
    if (r.state) _casino.state = { ..._casino.state, ...r.state };
    renderCasino();
    casinoSay(action === "bonus" ? `Бонус получен: +${r.delta} i¢`
      : action === "topup" ? `Переведено в казино: ${r.delta} i¢`
      : `Выведено в кошелёк: ${r.delta} i¢`);
  } catch (err) {
    casinoSay(err.message, "err");
  }
}

async function onCasinoClick(e) {
  const el = e.target.closest("[data-cact]");
  if (!el) return;
  const act = el.dataset.cact;
  if (act === "game") { _casino.game = el.dataset.game; _casino.last = null; renderCasino(); }
  else if (act === "color") { _casino.color = el.dataset.color; renderCasino(); }
  else if (act === "guess") { _casino.guess = Number(el.dataset.guess); renderCasino(); }
  else if (act === "side") { _casino.side = el.dataset.side; renderCasino(); }
  else if (act === "bet") {
    const v = el.dataset.bet;
    _casino.bet = v === "все" ? (_casino.state.balance || 0)
      : v === "x2" ? Math.max(1, _casino.bet * 2) : Number(v);
    renderCasino();
  }
  else if (act === "play") casinoPlay();
  else if (act === "bonus" || act === "topup" || act === "withdraw") casinoMoney(act);
  else if (act === "share") {
    try {
      await api("/api/member/game/casino/share",
                { method: "POST", body: {} });
      if (_casino.last) _casino.last.can_share = false;
      renderCasino();
      casinoSay("Отправлено в чат.");
    } catch (err) {
      casinoSay(err.message, "err");
    }
  }
}

// ===== Вкладка «Бизнесы» ===================================================
// Копилка считается лениво (на сервере, от времени последнего обращения),
// поэтому экран её не «тикает», а перечитывает: рисовать растущее число самому
// значило бы разойтись с тем, что реально начислится при сборе.
const _biz = { state: null, bound: false, timer: null };

function bizSay(text, kind = "ok") {
  if ($("#member-biz-msg")) say("#member-biz-msg", text, kind);
}

async function loadMemberBiz() {
  const box = $("#member-biz");
  box.innerHTML = `<section class="member-block"><h2>${icon("building")}Бизнесы</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${icon("building")}Бизнесы</h2>
      <div class="card">
        <div id="member-biz-msg"></div>
        <div id="member-biz-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!_biz.bound) { $("#member-biz").addEventListener("click", onBizClick); _biz.bound = true; }
    loadBizState();
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${icon("building")}Бизнесы</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

async function loadBizState() {
  try {
    _biz.state = await api(`/api/member/game/business`);
    renderBiz();
  } catch (err) {
    const body = $("#member-biz-body");
    if (body) body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// Копилка перечитывается раз в полминуты: доход капает часами, и чаще
// спрашивать не о чем.
function startBizTick() {
  if (_biz.timer) clearInterval(_biz.timer);
  _biz.timer = setInterval(() => { if (_biz.state) loadBizState(); }, 30000);
}

function stopBizTick() {
  if (_biz.timer) { clearInterval(_biz.timer); _biz.timer = null; }
}

function bizCardHtml(b, gear) {
  const процент = b.full_percent;
  const полная = процент >= 100;
  const оснащение = gear.map((g) => {
    const стоит = b.upgrades.includes(g.key);
    const цена = (b.gear_prices || {})[g.key] || 0;
    return `<button type="button" class="${стоит ? "on" : ""}" ${стоит ? "disabled" : ""}
      data-bact="equip" data-key="${b.key}" data-gear="${g.key}"
      title="${escapeHtml(g.hint)}"><span class="game-emoji">${escapeHtml(g.emoji || "🔧")}</span> ${escapeHtml(g.name)}${стоит ? "" : ` · ${цена} i¢`}</button>`;
  }).join("");
  return `<div class="biz-card ${b.broken ? "broken" : ""}">
    <div class="biz-head">
      <span class="biz-name">${escapeHtml(b.name)}</span>
      <span class="biz-level">${b.level}/${b.max_level} ур.</span>
      <span class="biz-income">${b.income.toLocaleString("ru")} i¢/час</span>
    </div>
    ${b.broken
      ? `<div class="biz-broken">${icon("wrench")} Сломан (${escapeHtml(b.broken)}) — доход не капает.</div>`
      : ""}
    <div class="vault ${полная ? "full" : ""} ${b.accrued ? "" : "empty"}">
      <div class="vault-fill" style="width:${процент}%"></div>
      <div class="vault-text">${b.accrued.toLocaleString("ru")} / ${b.cap.toLocaleString("ru")} i¢${
        полная ? " · полная" : b.hours_to_full ? ` · полная через ${b.hours_to_full} ч` : ""}</div>
    </div>
    <div class="biz-gear">${оснащение}</div>
    <div class="biz-buttons">
      <button type="button" class="btn" data-bact="collect" data-key="${b.key}"
              ${b.accrued ? "" : "disabled"}>Забрать</button>
      ${b.broken
        ? `<button type="button" class="btn" data-bact="repair" data-key="${b.key}">Починить · ${b.repair_cost} i¢</button>`
        : b.upgrade_cost
          ? `<button type="button" class="btn" data-bact="upgrade" data-key="${b.key}">Улучшить · ${b.upgrade_cost.toLocaleString("ru")} i¢</button>`
          : `<button type="button" class="btn" disabled>Максимум</button>`}
      <button type="button" class="btn ghost" data-bact="sell" data-key="${b.key}">Боту · ${b.sell_price.toLocaleString("ru")} i¢</button>
      <button type="button" class="btn ghost" data-bact="offer" data-key="${b.key}">Игроку…</button>
    </div>
  </div>`;
}

function renderBiz() {
  const s = _biz.state, body = $("#member-biz-body");
  if (!s || !body) return;
  const карточки = s.mine.map((b) => bizCardHtml(b, s.gear)).join("");
  const витрина = s.catalog.map((c) => `
    <div class="biz-offer ${c.owned ? "owned" : ""}">
      <span><span class="name">${escapeHtml(c.name)}</span>
        <span class="meta">${c.income.toLocaleString("ru")} i¢/час · копилка ${c.cap.toLocaleString("ru")}</span></span>
      ${c.owned
        ? `<span class="meta">уже ваш</span>`
        : `<button type="button" class="btn" data-bact="buy" data-key="${c.key}"
                   ${c.affordable ? "" : "disabled"}>${c.price.toLocaleString("ru")} i¢</button>`}
    </div>`).join("");

  body.innerHTML = `
    <div class="biz-summary">
      <div><span class="total">${s.pending_total.toLocaleString("ru")} i¢</span>
        <span class="muted">в копилках<small>налог при сборе: ${s.tax_now.toLocaleString("ru")} i¢ · в кошельке ${s.coins.toLocaleString("ru")} i¢</small></span></div>
      <button type="button" class="btn btn-collect" data-bact="collect"
              ${s.pending_total ? "" : "disabled"}>${icon("coins")}Забрать со всех</button>
    </div>
    ${s.mine.length
      ? `<div class="biz-list">${карточки}</div>`
      : `<div class="empty">${icon("empty")}<span>Бизнесов пока нет — купите первый ниже.</span></div>`}
    <h3 class="block-head">${icon("store")}Купить</h3>
    <div class="biz-shop">${витрина}</div>`;
  startBizTick();
}

async function bizDo(action, тело, успех) {
  try {
    const r = await api(`/api/member/game/business/${action}`,
                        { method: "POST", body: { ...тело } });
    _biz.state = r.state;
    renderBiz();
    bizSay(успех(r));
  } catch (err) {
    bizSay(err.message, "err");
  }
}

async function onBizClick(e) {
  const el = e.target.closest("[data-bact]");
  if (!el) return;
  const act = el.dataset.bact, key = el.dataset.key || null;
  if (act === "collect") {
    // Налог считается от всей суммы разом, поэтому «забрать со всех» — не то
    // же самое, что несколько сборов подряд: об этом сказано в шапке.
    bizDo("collect", { key }, (r) =>
      `Забрали ${r.gross.toLocaleString("ru")} i¢ с ${r.count} бизнес(-ов) · налог ${r.tax.toLocaleString("ru")} · на руки ${r.net.toLocaleString("ru")}`);
  } else if (act === "buy") {
    bizDo("buy", { key }, (r) => `Куплено за ${r.spent.toLocaleString("ru")} i¢`);
  } else if (act === "upgrade") {
    bizDo("upgrade", { key }, (r) =>
      r.free ? `Улучшено до ${r.level} ур. по «бизнес-плану» — бесплатно`
             : `Улучшено до ${r.level} ур. за ${r.spent.toLocaleString("ru")} i¢`);
  } else if (act === "repair") {
    bizDo("repair", { key }, (r) => `Починено за ${r.spent.toLocaleString("ru")} i¢`);
  } else if (act === "equip") {
    bizDo("equip", { key, gear: el.dataset.gear }, (r) => `Оснащение поставлено за ${r.spent.toLocaleString("ru")} i¢`);
  } else if (act === "sell") {
    if (!confirm("Продать бизнес боту? Оснащение снимется, копилка вернётся вместе с ценой.")) return;
    bizDo("sell", { key }, (r) => `Продано, получено ${r.net.toLocaleString("ru")} i¢`);
  } else if (act === "offer") {
    // Сделка с человеком: сайт только ПРЕДЛАГАЕТ. Согласие второй стороны
    // приходит кнопкой в чате — иначе бизнес переходил бы без спроса.
    const кому = prompt("Кому? Укажите @ник (бот должен был видеть его в этом чате).", "@");
    if (!кому) return;
    const цена = prompt("За сколько i¢? Оставьте 0 или пусто — передать в дар.", "0");
    if (цена === null) return;
    const сумма = Number(цена) || 0;
    bizDo(сумма > 0 ? "offer" : "give", { key, target: кому, price: сумма },
      () => сумма > 0
        ? "Предложение отправлено в чат — ждём согласия покупателя."
        : "Предложение отправлено в чат — ждём согласия получателя.");
  }
}

// ===== Вкладки «Рыбалка» и «Работа» ========================================
// Общий каркас на два занятия: выбрать чат, показать состояние, нажать —
// перерисовать. Разное у них только внутри карточки, поэтому и код общий:
// две почти одинаковые копии разъезжаются на первой же правке.
const _act = { fish: { state: null }, work: { state: null },
               bound: false, timer: null };

function actSay(вид, text, kind = "ok") {
  if ($(`#member-${вид}-msg`)) say(`#member-${вид}-msg`, text, kind);
}

function actLeft(iso) {
  const мс = farmTime(iso) - Date.now();
  return мс > 0 ? farmLeft(мс) : "";
}

async function loadActivity(вид, заголовок) {
  const box = $(`#member-${вид}`);
  box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
      <div class="card">
        <div id="member-${вид}-msg"></div>
        <div id="member-${вид}-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!_act.bound) {
      $("#member-fish").addEventListener("click", (e) => onActivityClick("fish", e));
      $("#member-work").addEventListener("click", (e) => onActivityClick("work", e));
      _act.bound = true;
    }
    loadActivityState(вид);
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

const loadMemberFish = () => loadActivity("fish", `${icon("fish")}Рыбалка`);
const loadMemberWork = () => loadActivity("work", `${icon("work")}Работа`);

async function loadActivityState(вид) {
  const адрес = вид === "fish" ? "fishing" : "work";
  try {
    _act[вид].state = await api(`/api/member/game/${адрес}`);
    if (вид === "fish") renderFish(); else renderWork();
    startActivityTick();
  } catch (err) {
    const body = $(`#member-${вид}-body`);
    if (body) body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// Один тикер на оба занятия: они показывают одно и то же — сколько ждать.
function startActivityTick() {
  if (_act.timer) clearInterval(_act.timer);
  _act.timer = setInterval(() => {
    let живо = false;
    $$("[data-until]").forEach((el) => {
      const осталось = farmTime(el.dataset.until) - Date.now();
      if (осталось > 0) { el.textContent = farmLeft(осталось); живо = true; }
      else { el.textContent = "готово"; }
    });
    if (!живо && _act.timer) { clearInterval(_act.timer); _act.timer = null; }
  }, 1000);
}

function stopActivityTick() {
  if (_act.timer) { clearInterval(_act.timer); _act.timer = null; }
}

// --- рыбалка ---------------------------------------------------------------
function fishCardHtml(f) {
  // Свежесть цветом, а не подписью: решение «продать или ждать Клёва»
  // принимается взглядом.
  const класс = f.hours >= 48 ? "rot" : f.hours >= 24 ? "stale" : "";
  return `<div class="fish-card ${класс} ${f.pinned ? "pinned" : ""}">
    <div class="fish-card-head"><span class="game-emoji lg">${escapeHtml(f.emoji || "🐟")}</span>
      <span class="rarity ${f.rarity}">${escapeHtml(f.rarity_label)}</span></div>
    <div class="fish-name">${escapeHtml(f.name)}${f.pinned ? ` ${icon("pin")}` : ""}</div>
    <div class="fish-meta">${escapeHtml(f.weight)} · ${escapeHtml(f.freshness)}</div>
    <div class="fish-price">${f.price.toLocaleString("ru")} i¢</div>
    <div class="row-btns">
      <button type="button" class="btn" data-aact="sell" data-id="${f.id}"
              ${f.pinned ? "disabled" : ""}>Продать</button>
      <button type="button" class="btn ghost btn-ic" data-aact="${f.pinned ? "unpin" : "pin"}" data-id="${f.id}"
              title="${f.pinned ? "Открепить" : "Закрепить — не продастся и не выпустится"}">
        ${icon(f.pinned ? "undo" : "pin")}</button>
      <button type="button" class="btn ghost btn-ic" data-aact="release" data-id="${f.id}"
              ${f.pinned ? "disabled" : ""} title="Выпустить обратно в воду">${icon("out")}</button>
    </div>
  </div>`;
}

function renderFish() {
  const s = _act.fish.state, body = $("#member-fish-body");
  if (!s || !body) return;
  const ждать = s.next_at ? actLeft(s.next_at) : "";
  // Вода — сцена: глубина градиентом, гребешки волн, поплавок у поверхности.
  body.innerHTML = `
    <div class="fish-scene">
      <div class="fish-waves"></div>
      <div class="fish-bobber"></div>
      <div class="fish-top">
        <div><span class="value">${s.net_value.toLocaleString("ru")} i¢</span>
          <small>в сетке ${s.net.length}/${s.capacity}${
            s.multiplier > 1 ? ` · ${icon("fish")} Клёв ×${s.multiplier}` : ""}</small></div>
        <div class="fish-actions">
          <button type="button" class="btn primary" data-aact="cast" ${ждать ? "disabled" : ""}>
            ${icon("fish")}Забросить${ждать ? ` · <span data-until="${escapeHtml(s.next_at)}">${ждать}</span>` : ""}</button>
          <button type="button" class="btn" data-aact="sell" ${s.net.length ? "" : "disabled"}>
            ${icon("coins")}Продать всё</button>
        </div>
      </div>
    </div>
    ${s.net.length
      ? `<div class="net">${s.net.map(fishCardHtml).join("")}</div>`
      : `<div class="empty">${icon("empty")}<span>Сетка пуста — забросьте удочку.</span></div>`}
    <div class="hint">
      Рекорд: ${(s.best_weight / 1000).toFixed(1)} кг · уловов всего: ${s.total_catches}.
      Рыба портится: до 24 ч свежая, после 48 ч дешевеет вдвое. Цену поднимает «Клёв» — придержать улов бывает выгодно.
    </div>`;
}

// --- работа ----------------------------------------------------------------
// Классы meters/meter, а не bars/bar: те заняты столбчатым графиком
// статистики, и общее имя уже один раз молча ломало ему масштаб.
function barHtml(вид, подпись, значение) {
  return `<div class="bar-row"><span class="bar-label">${подпись}</span>
    <span class="meter ${вид}"><i style="width:${Math.max(0, Math.min(100, значение))}%"></i></span>
    <span class="bar-value">${значение}/100</span></div>`;
}

function renderWork() {
  const s = _act.work.state, body = $("#member-work-body");
  if (!s || !body) return;
  if (!s.profession) {
    body.innerHTML = `<div class="empty">${icon("empty")}<span>Профессии пока нет.
      Выберите подходящую ниже.</span></div>
      <div class="prof-list mt-3">${s.catalog.map((p) => `
        <div class="prof-card"><div class="name"><span class="game-emoji">${escapeHtml(p.emoji || "💼")}</span> ${escapeHtml(p.name)}</div>
          <div class="meta">${p.income[0].toLocaleString("ru")}–${p.income[1].toLocaleString("ru")} i¢ · ${icon("spark")}${p.energy}
          ${p.req_days ? ` · от ${p.req_days} дн.` : ""}${p.req_coins ? ` · вход от ${p.req_coins.toLocaleString("ru")} i¢` : ""}</div>
          <button type="button" class="btn small" data-aact="join" data-key="${escapeHtml(p.key)}">Устроиться</button></div>`).join("")}</div>`;
    return;
  }
  const ждать = s.next_at ? actLeft(s.next_at) : "";
  const перерыв = s.break_at ? actLeft(s.break_at) : "";
  const доля = s.xp_next ? Math.min(100, Math.round(s.xp * 100 / s.xp_next)) : 100;
  const заметки = [];
  if (s.burnout) заметки.push(`<div class="work-note bad">${icon("alert")} Выгорание: доход урезан на ${s.burnout_penalty}%. Помогает перерыв.</div>`);
  else if (s.shifts_since_break >= s.burnout_after - 2)
    заметки.push(`<div class="work-note warn">${icon("clock")} Смен без перерыва: ${s.shifts_since_break} из ${s.burnout_after}.</div>`);
  if (s.union) заметки.push(`<div class="work-note">${icon("chats")} Профсоюз (${s.colleagues} чел.): смена даётся легче.</div>`);
  if (s.streak) заметки.push(`<div class="work-note">${icon("star")} Серия смен: ${s.streak} дн.</div>`);

  body.innerHTML = `
    <div class="work-head">
      <div><div class="work-prof"><span class="game-emoji lg">${escapeHtml(s.emoji || "💼")}</span> ${escapeHtml(s.name)}</div>
        <div class="work-level">${s.level}/${s.max_level} уровень · ${s.income[0].toLocaleString("ru")}–${s.income[1].toLocaleString("ru")} i¢ за смену</div>
        <div class="xp-bar"><i style="width:${доля}%"></i></div>
        <div class="work-level">${s.xp} / ${s.xp_next} XP</div></div>
      <button type="button" class="btn btn-shift" data-aact="shift" ${ждать ? "disabled" : ""}>
        ${icon("work")}На смену${ждать ? ` · <span data-until="${escapeHtml(s.next_at)}">${ждать}</span>` : ""}</button>
    </div>
    <div class="meters">
      ${barHtml("energy", `${icon("spark")} Энергия`, s.energy)}
      ${barHtml("mood", `${icon("smile")} Настроение`, s.mood)}
      ${barHtml("health", `${icon("heart")} Здоровье`, s.health)}
    </div>
    <div class="farm-actions">
      <button type="button" class="btn" data-aact="rest" ${перерыв ? "disabled" : ""}>
        ${icon("coffee")}Перерыв${перерыв ? ` · <span data-until="${escapeHtml(s.break_at)}">${перерыв}</span>` : ""}</button>
    </div>
    ${заметки.join("")}
    <div class="hint">
      Силы восстанавливаются сами: примерно ${s.regen_per_hour} в час.</div>`;
}

async function onActivityClick(вид, e) {
  const el = e.target.closest("[data-aact]");
  if (!el) return;
  const act = el.dataset.aact;
  const адрес = вид === "fish" ? "fishing" : "work";
  const тело = { };
  if (el.dataset.id) тело.fish_id = Number(el.dataset.id);
  if (el.dataset.key) тело.key = el.dataset.key;
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/${адрес}/${act}`, { method: "POST", body: тело });
    _act[вид].state = r.state;
    if (вид === "fish") renderFish(); else renderWork();
    startActivityTick();
    actSay(вид, activityReport(вид, act, r));
  } catch (err) {
    actSay(вид, err.message, "err");
    el.disabled = false;
  }
}

// Эмодзи в отчётах ниже — не забытые: отчёт уходит в say(), а тот экранирует
// текст (иначе любое имя с «<» ломало бы страницу). Разметку туда вставить
// нельзя, и значок остаётся единственным способом показать, о чём речь.
function activityReport(вид, act, r) {
  if (вид === "fish") {
    if (act === "cast") {
      if (r.junk) return `${r.name} — сдали в приёмку: +${r.coins} i¢`;
      if (r.released) return "Сетка полна, а улов самый скромный — отпустили.";
      const части = [`${r.name}, ${(r.grams / 1000).toFixed(2)} кг ≈ ${r.price} i¢`];
      if (r.lucky) части.push("талисман: вдвое крупнее");
      if (r.record) части.push("новый рекорд");
      if (r.evicted) части.push(`выбросили ${r.evicted}`);
      return части.join(" · ");
    }
    if (act === "sell") {
      const части = [`Продано ${r.sold} шт. на ${r.coins.toLocaleString("ru")} i¢`];
      if (r.multiplier > 1) части.push(`Клёв ×${r.multiplier}`);
      if (r.passive) части.push(`снасти +${r.passive}%`);
      return части.join(" · ");
    }
    if (act === "release") return "Рыбу выпустили — место освободилось.";
    if (act === "unpin") return "Трофей откреплён.";
    return "Готово.";
  }
  if (act === "join") return `Вы устроились: ${r.state.name}. Первая смена уже доступна.`;
  if (act === "rest") return "Отдохнули." + (r.burnout ? " Выгорание снято." : "");
  const части = [`Смена: +${r.income.toLocaleString("ru")} i¢, +${r.xp} XP`];
  if (r.level_up) части.push(`повышение до ${r.level}`);
  if (r.office) части.push("вне очереди");
  if (r.event) части.push(безЭмодзи(r.event));
  if (r.mentor_share) части.push(`наставнику ${r.mentor_share} i¢`);
  if (r.graduated) части.push("стажировка окончена");
  return части.join(" · ");
}

// ===== Вкладки «Профиль» и «Топы» ==========================================
// Только чтение, поэтому никаких «нажал — перерисовать»: загрузили и показали.
const _prof = { state: null, tops: null, kind: "messages", bound: false };

// Цвет кружка с буквой — из имени, как у аватарок в списках: у одного
// человека он всегда один и тот же, и список не выглядит серым.
function profColor(имя) {
  let сумма = 0;
  for (const c of String(имя)) сумма = (сумма + c.codePointAt(0)) % 997;
  return PALETTE[сумма % PALETTE.length];
}

async function loadMemberProf() { await loadProfScreen("prof", `${icon("user")}Профиль`); }
async function loadMemberTops() { await loadProfScreen("tops", `${icon("trophy")}Топы`); }

async function loadProfScreen(вид, заголовок) {
  const box = $(`#member-${вид}`);
  box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
      <div class="card">
        <div id="member-${вид}-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!_prof.bound) {
      $("#member-tops").addEventListener("click", onTopsClick);
      _prof.bound = true;
    }
    // Анкета и титулы живут в «Профиле». Слушатели вешаем на сам экран, а не
    // на поля: разметка перерисовывается после каждой правки, и слушатели на
    // полях пришлось бы вешать заново каждый раз.
    if (вид === "prof" && !_card.bound) {
      const экран = $("#member-prof");
      экран.addEventListener("click", onCardClick);
      экран.addEventListener("click", onGalleryClick);
      экран.addEventListener("change", onCardChange);
      экран.addEventListener("input", onCardInput);
      // focusout, а не blur: blur не всплывает, и на самом экране его не
      // поймать — правка молча терялась бы.
      экран.addEventListener("focusout", onCardBlur);
      // Запоминаем, раскрыт ли магазин титулов: toggle не всплывает,
      // ловим на фазе захвата.
      экран.addEventListener("toggle", (e) => {
        if (e.target.classList.contains("title-shop")) _card.shopOpen = e.target.open;
      }, true);
      _card.bound = true;
    }
    вид === "prof" ? loadProfile() : loadTops();
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

async function loadProfile() {
  const body = $("#member-prof-body");
  if (!body) return;
  try {
    _prof.state = await api(`/api/member/game/profile`);
    renderProfile();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function tile(значение, подпись, класс = "") {
  return `<div class="tile ${класс}"><div class="v">${значение}</div><div class="k">${подпись}</div></div>`;
}

function renderProfile() {
  const p = _prof.state, body = $("#member-prof-body");
  if (!p || !body) return;
  const буква = (p.name || "?").trim()[0] || "?";
  const звёзды = p.star_progress.need
    ? Math.round(p.star_progress.have * 100 / p.star_progress.need) : 100;
  const плитки = [
    tile(p.messages.toLocaleString("ru"), "сообщений", "accent"),
    tile(p.rank ? `#${p.rank}` : "—", "место в чате"),
    tile(p.coins.toLocaleString("ru"), "монет", "gold"),
    tile(`${p.stars} ${icon("star")}`, "звёздность", "gold"),
    tile(p.achievements, "достижений"),
    p.businesses ? tile(p.businesses, "бизнесов") : "",
    p.pets ? tile(p.pets, "питомцев") : "",
    p.clan ? tile(escapeHtml(p.clan), "клан") : "",
  ].join("");

  const занятия = [];
  if (p.work.name) {
    занятия.push(`<div class="tile"><div class="v"><span class="game-emoji">${escapeHtml(p.work.emoji || "💼")}</span> ${escapeHtml(p.work.name)}</div>
      <div class="k">${p.work.level} ур. · ${p.work.shifts} смен${p.work.streak ? ` · серия ${p.work.streak}` : ""}</div></div>`);
  }
  if (p.fishing.catches) {
    занятия.push(`<div class="tile"><div class="v">${icon("fish")} ${escapeHtml(p.fishing.best_weight_text)}</div>
      <div class="k">рекорд${p.fishing.best_species ? ` · ${escapeHtml(p.fishing.best_species)}` : ""} · уловов ${p.fishing.catches}</div></div>`);
  }

  body.innerHTML = `
    <div class="prof-card">
      <div class="prof-ava" style="background:${profColor(p.name)}">${escapeHtml(буква.toUpperCase())}</div>
      <div class="grow">
        <div class="prof-name">${escapeHtml(p.name)}</div>
        <div class="prof-sub">${p.username ? "@" + escapeHtml(p.username) : `id ${p.user_id}`}</div>
        ${p.title ? `<span class="prof-title">${escapeHtml(p.title)}</span>` : ""}
        <div class="star-line" title="До следующей звезды"><i style="width:${звёзды}%"></i></div>
      </div>
    </div>
    <div class="tiles">${плитки}</div>
    <h3 class="block-head">Быстрый доступ</h3>
    <div class="profile-shortcuts">
      <button type="button" class="btn ghost" data-member-open="farm">${icon("sprout")}Ферма</button>
      <button type="button" class="btn ghost" data-member-open="work">${icon("work")}Работа</button>
      <button type="button" class="btn ghost" data-member-open="fish">${icon("fish")}Рыбалка</button>
      <button type="button" class="btn ghost" data-member-open="shop">${icon("cart")}Магазин</button>
    </div>
    ${занятия.length ? `<h3 class="block-head">Занятия</h3>
      <div class="tiles">${занятия.join("")}</div>` : ""}
    <h3 class="block-head">Активность</h3>
    <div class="tiles">
      ${tile(p.activity.last_24h.toLocaleString("ru"), "за 24 часа")}
      ${tile(p.activity.day.toLocaleString("ru"), "за сегодня")}
      ${tile(p.activity.week.toLocaleString("ru"), "за неделю")}
      ${tile(p.activity.month.toLocaleString("ru"), "за месяц")}
    </div>
    <div id="member-gallery-block"></div>
    <div id="member-card-block"></div>`;
  loadGallery();
  loadCardBlock();
}

// --- достижения и коллекции -------------------------------------------------
// Только просмотр. Стоят в «Профиле», где уже есть счётчик достижений: до сих
// пор он показывал число, по которому нельзя было понять, что именно собрано
// и что осталось.
//
// Неполученные показываются тоже — и это половина смысла экрана: список
// одного собранного отвечает на вопрос «что у меня есть» и молчит о том, ради
// чего сюда и заходят. В чате так же: полученные списком, остальные под катом.
const _gallery = { data: null, open: false };

async function loadGallery() {
  const блок = $("#member-gallery-block");
  if (!блок) return;
  try {
    _gallery.data = await api(`/api/member/game/gallery`);
  } catch (err) {
    блок.innerHTML = "";
    return;
  }
  renderGallery();
}

function renderGallery() {
  const d = _gallery.data, блок = $("#member-gallery-block");
  if (!d || !блок) return;
  const a = d.achievements || { items: [], earned: 0, total: 0 };
  const собраны = a.items.filter((x) => x.earned);
  const остались = a.items.filter((x) => !x.earned);

  блок.innerHTML = `
    <h3 class="block-head">${icon("medal")}Достижения · ${a.earned} из ${a.total}</h3>
    ${собраны.length
      ? `<div class="ach-list">${собраны.map(achHtml).join("")}</div>`
      : `<div class="muted mb-2">Пока ни одного. Они выдаются сами — за
         активность, стаж и события в чате.</div>`}
    ${остались.length ? `
      <button type="button" class="btn ghost small" data-gallery="toggle">
        ${_gallery.open ? "Скрыть" : `Показать оставшиеся · ${остались.length}`}</button>
      ${_gallery.open ? `<div class="ach-list mt-2">${остались.map(achHtml).join("")}</div>` : ""}` : ""}

    <h3 class="block-head">${icon("basket")}Коллекции</h3>
    <div class="coll-list">${(d.collections?.items || []).map((c) => {
      const доля = c.total ? Math.round(c.done * 100 / c.total) : 0;
      return `<div class="coll-row ${c.rewarded ? "done" : ""}">
        <div class="coll-head"><span class="coll-emoji" aria-hidden="true">${escapeHtml(c.emoji)}</span> <b>${escapeHtml(c.name)}</b>
          ${c.rewarded ? `<span class="coll-mark">${icon("check")}титул получен</span>` : ""}
          <span class="push">${c.done}/${c.total}</span></div>
        <div class="coll-bar"><i style="width:${доля}%"></i></div>
        <div class="coll-desc">${escapeHtml(c.description)}</div>
      </div>`;
    }).join("")}</div>
    <div class="hint">За полный сбор — титул, который нельзя купить.</div>`;
}

function achHtml(x) {
  return `<div class="ach ${x.earned ? "got" : "left"}">
    <span class="ach-emoji">${x.earned ? achIcon(x.key) : icon("lock")}</span>
    <span class="ach-body"><b>${escapeHtml(x.title)}</b>
      <span class="muted">${escapeHtml(x.desc)}</span></span>
  </div>`;
}

function onGalleryClick(e) {
  if (!e.target.closest("[data-gallery]")) return;
  _gallery.open = !_gallery.open;
  renderGallery();
}

// --- анкета и титулы --------------------------------------------------------
// Стоят в «Профиле», под тем, что они и описывают. Правится всё на месте: поле
// сохраняется, когда из него уходят, — отдельная кнопка «сохранить» у шести
// коротких строк дала бы шесть кнопок и ни одной подсказки, какая из них ещё
// не нажата.
// shopOpen — раскрыт ли магазин титулов: после покупки блок перерисовывается,
// и без этого флага свёрнутый по умолчанию список захлопывался бы в руках.
const _card = { state: null, titles: null, bound: false, shopOpen: false };

async function loadCardBlock() {
  const блок = $("#member-card-block");
  if (!блок) return;
  try {
    const d = await api(`/api/member/game/card`);
    _card.state = d.card;
    _card.titles = d.titles;
    _card.pins = d.pins;
  } catch (err) {
    блок.innerHTML = "";
    return;
  }
  renderCardBlock();
}

function cardField(поле, подпись, значение, предел, многострочно) {
  const общее = `id="card-${поле}" data-card-field="${поле}" maxlength="${предел}"`;
  return `<label class="bet-field card-field">
    <span>${escapeHtml(подпись)} <em class="tip"><b data-card-count="${поле}">${String(значение || "").length}</b>/${предел} · пусто — убрать</em></span>
    ${многострочно
      ? `<textarea ${общее} rows="3" autocomplete="off">${escapeHtml(значение)}</textarea>`
      : `<input type="text" ${общее} value="${escapeHtml(значение)}" autocomplete="off">`}
  </label>`;
}

function renderCardBlock() {
  const c = _card.state, t = _card.titles, pins = _card.pins, блок = $("#member-card-block");
  if (!c || !t || !pins || !блок) return;

  // Списки берём с запасом: половина ответа роняла бы весь «Профиль», а он
  // тут главный — анкета внизу и приложена к нему.
  const все = (t.for_sale || []).concat(t.earned_only || []);
  const надет = все.find((x) => x.key === t.active);
  const свои = все.filter((x) => x.owned);
  const заполнено = [c.title, c.motto, c.gender, c.city, c.about].filter(Boolean).length;
  const процент = Math.round(заполнено * 100 / 5);
  const pinNames = { item: "Предмет", achievement: "Достижение", business: "Бизнес", pet: "Питомец", fish: "Трофей", doll: "Кукла" };
  const vitrina = Object.entries(pinNames).map(([key, name]) => {
    const options = pins.options[key] || [];
    const selected = pins.selected[key] == null ? "" : String(pins.selected[key]);
    return `<label class="pin-field"><span>${name}</span><select data-profile-pin="${key}" ${options.length ? "" : "disabled"}>
      <option value="">${options.length ? "Не показывать" : "Пока нечего выбрать"}</option>
      ${options.map((x) => `<option value="${escapeHtml(x.value)}" ${String(x.value) === selected ? "selected" : ""}>${escapeHtml(x.label)}</option>`).join("")}
    </select></label>`;
  }).join("");

  блок.innerHTML = `
    <h3 class="block-head">${icon("id")}Анкета</h3>
    <div class="profile-completion">
      <div><b>Заполненность анкеты · ${заполнено} из 5</b><span>${процент}%</span></div>
      <i><i style="width:${процент}%"></i></i>
      <small>Заполненная анкета делает профиль в чате узнаваемее.</small>
    </div>
    ${cardField("title", "Звание", c.title, c.limits.title, false)}
    ${cardField("motto", "Девиз", c.motto, c.limits.motto, false)}
    <label class="bet-field card-field">
      <span>Пол <em class="tip">необязательно · влияет на РП-превью</em></span>
      <select id="card-gender" data-card-gender autocomplete="off">
        <option value="" ${!c.gender ? "selected" : ""}>Не указывать</option>
        <option value="м" ${c.gender === "м" ? "selected" : ""}>♂ Мужской</option>
        <option value="ж" ${c.gender === "ж" ? "selected" : ""}>♀ Женский</option>
        <option value="др" ${c.gender === "др" ? "selected" : ""}>⚧ Другой</option>
      </select>
    </label>
    ${cardField("city", "Город", c.city, c.limits.city, false)}
    ${cardField("about", "О себе", c.about, c.limits.about, true)}
    <label class="check">
      <input type="checkbox" id="card-citizen" data-card-flag="citizen"
             ${c.citizen ? "checked" : ""} autocomplete="off">
      <span>Гражданин(ка) чата</span>
    </label>
    <label class="check">
      <input type="checkbox" id="card-visible" data-card-flag="visible"
             ${c.visible ? "checked" : ""} autocomplete="off">
      <span>Анкету видно другим</span>
    </label>

    <h3 class="block-head">${icon("pin")}Витрина профиля</h3>
    <div class="profile-pins">${vitrina}</div>
    <div class="hint">Выбранные вещи показываются в вашей карточке в чате. Закреп не расходует предмет и не меняет его свойства.</div>

    <h3 class="block-head">${icon("medal")}Титулы</h3>
    <div class="card-title-now">
      ${надет ? `Надет: <b>${escapeHtml(безЭмодзи(надет.name))}</b>` : `<span class="muted">Титул не надет</span>`}
      ${t.active ? `<button type="button" class="btn ghost small" data-title-act="unequip">Снять</button>` : ""}
    </div>
    ${свои.length ? `<div class="card-titles">${свои.map((x) => `
      <button type="button" class="btn ghost small ${x.key === t.active ? "active" : ""}"
              data-title-act="equip" data-key="${escapeHtml(x.key)}">${escapeHtml(безЭмодзи(x.name))}</button>`).join("")}</div>`
      : `<div class="muted mb-2">Своих титулов пока нет.</div>`}

    ${(t.for_sale || []).filter((x) => !x.owned).length ? `
      <details class="fold fold-quiet title-shop"${_card.shopOpen ? " open" : ""}>
        <summary>В продаже · ${(t.for_sale || []).filter((x) => !x.owned).length} титулов
          <span class="muted">· в кошельке ${t.coins.toLocaleString("ru")} i¢</span></summary>
        <div class="card-titles">${(t.for_sale || []).filter((x) => !x.owned).map((x) => `
          <button type="button" class="btn ${t.coins >= x.price ? "" : "ghost"}"
                  data-title-act="buy" data-key="${escapeHtml(x.key)}"
                  ${t.coins >= x.price ? "" : "disabled"}>
            ${escapeHtml(безЭмодзи(x.name))} · ${x.price.toLocaleString("ru")} i¢</button>`).join("")}</div>
      </details>` : ""}

    ${(t.earned_only || []).filter((x) => !x.owned).length ? `
      <div class="muted mt-2">За достижения, не продаются:
        ${(t.earned_only || []).filter((x) => !x.owned).map((x) => escapeHtml(безЭмодзи(x.name))).join(" · ")}</div>` : ""}
    <div id="member-card-msg"></div>`;
}

async function saveCardField(поле, значение) {
  try {
    const r = await api(`/api/member/game/card/field`, {
      method: "POST", body: { field: поле, value: значение },
    });
    _card.state = r.card;
    say("#member-card-msg", r.cleared ? "Убрано." : "Сохранено.");
  } catch (err) {
    say("#member-card-msg", err.message, "err");
  }
}

async function saveCardFlag(поле, включено) {
  try {
    const r = await api(`/api/member/game/card/field`, {
      method: "POST", body: { field: поле, on: включено },
    });
    _card.state = r.card;
    say("#member-card-msg", "Сохранено.");
  } catch (err) {
    say("#member-card-msg", err.message, "err");
  }
}

async function onCardClick(e) {
  const переход = e.target.closest("[data-member-open]");
  if (переход) {
    switchMemberTab(переход.dataset.memberOpen);
    return;
  }
  const el = e.target.closest("[data-title-act]");
  if (!el || el.disabled) return;
  const act = el.dataset.titleAct;
  const путь = act === "buy" ? "buy" : "equip";
  const тело = act === "unequip" ? { key: null } : { key: el.dataset.key };
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/card/title/${путь}`, { method: "POST", body: тело });
    _card.titles = r.titles;
    say("#member-card-msg",
        r.action === "buy" ? `Куплено: ${безЭмодзи(r.name)} за ${r.price.toLocaleString("ru")} i¢.`
        : r.action === "equip" ? `Надет титул: ${безЭмодзи(r.name)}.` : "Титул снят.");
    renderCardBlock();
  } catch (err) {
    say("#member-card-msg", err.message, "err");
    el.disabled = false;
  }
}

// Поле сохраняется, когда из него уходят: набирать и жать «сохранить» на
// каждой из шести строк — работа, которой здесь взяться неоткуда.
function onCardBlur(e) {
  const поле = e.target.closest("[data-card-field]");
  if (поле) { saveCardField(поле.dataset.cardField, поле.value); return; }
}

function onCardChange(e) {
  const пол = e.target.closest("[data-card-gender]");
  if (пол) { saveCardField("gender", пол.value); return; }
  const витрина = e.target.closest("[data-profile-pin]");
  if (витрина) { saveProfilePin(витрина.dataset.profilePin, витрина.value); return; }
  const флаг = e.target.closest("[data-card-flag]");
  if (флаг) saveCardFlag(флаг.dataset.cardFlag, флаг.checked);
}

async function saveProfilePin(поле, значение) {
  try {
    const r = await api(`/api/member/game/card/pin`, { method: "POST", body: { field: поле, value: значение || null } });
    _card.pins = r.pins;
    say("#member-card-msg", значение ? "Закреплено в профиле." : "Закреп снят.");
    renderCardBlock();
  } catch (err) {
    say("#member-card-msg", err.message, "err");
  }
}

function onCardInput(e) {
  const поле = e.target.closest("[data-card-field]");
  if (!поле) return;
  const счётчик = $(`[data-card-count="${поле.dataset.cardField}"]`);
  if (счётчик) счётчик.textContent = String(поле.value || "").length;
}

async function loadTops() {
  const body = $("#member-tops-body");
  if (!body) return;
  try {
    _prof.tops = await api(`/api/member/game/tops`);
    renderTops();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderTops() {
  const t = _prof.tops, body = $("#member-tops-body");
  if (!t || !body) return;
  const выбор = t.kinds.map((k) => `
    <button type="button" class="top-kind ${_prof.kind === k.key ? "active" : ""}"
            data-top="${k.key}">${icon(TOP_ICONS[k.key] || "trophy")} ${escapeHtml(k.title)}</button>`).join("");
  const таблица = t.tables[_prof.kind] || { rows: [], unit: "" };
  const мой = _prof.state ? _prof.state.user_id : null;
  const строки = таблица.rows.map((r) => `
    <div class="top-row ${r.user_id === мой ? "me" : ""}">
      <span class="top-place">${r.place}</span>
      <span class="top-who">${escapeHtml(r.name)}${
        r.note ? `<small>${escapeHtml(безЭмодзи(r.note))}</small>` : ""}</span>
      <span class="top-value">${escapeHtml(r.text || r.value.toLocaleString("ru"))}
        ${таблица.unit ? `<small>${escapeHtml(таблица.unit)}</small>` : ""}</span>
    </div>`).join("");

  body.innerHTML = `<div class="top-kinds">${выбор}</div>
    ${строки
      ? `<div class="top-list">${строки}</div>`
      : `<div class="empty">${icon("empty")}<span>Здесь пока пусто.</span></div>`}`;
}

function onTopsClick(e) {
  const el = e.target.closest("[data-top]");
  if (!el) return;
  _prof.kind = el.dataset.top;
  renderTops();
}

// ===== Вкладки «Магазин» и «Питомцы» =======================================
const _shop = { state: null, bound: false, tab: "shop" };
const _pets = { data: null, bound: false };

async function loadMemberShop() {
  await loadSimpleScreen("shop", `${icon("cart")}Магазин`, _shop, loadShopState, onShopClick);
}
async function loadMemberPets() {
  await loadSimpleScreen("pets", `${icon("paw")}Питомцы`, _pets, loadPetsState, onPetsClick);
}

// Общий каркас «выбрать чат → показать → нажать»: третий экран подряд с одним
// и тем же началом — повод не копировать его в третий раз.
async function loadSimpleScreen(вид, заголовок, состояние, загрузка, нажатие) {
  const box = $(`#member-${вид}`);
  box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
    <div class="card"><div class="muted">Загрузка…</div></div></section>`;
  try {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2>
      <div class="card">
        <div id="member-${вид}-msg"></div>
        <div id="member-${вид}-body"><div class="muted">Загрузка…</div></div>
      </div></section>`;
    if (!состояние.bound) { box.addEventListener("click", нажатие); состояние.bound = true; }
    загрузка();
  } catch (err) {
    box.innerHTML = `<section class="member-block"><h2>${заголовок}</h2><div class="card">
      <div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div></div></section>`;
  }
}

// --- магазин ---------------------------------------------------------------
async function loadShopState() {
  const body = $("#member-shop-body");
  if (!body) return;
  try {
    _shop.state = await api(`/api/member/game/shop`);
    renderShop();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function goodHtml(g) {
  const остаток = g.stock === null || g.stock === undefined
    ? "" : `<div class="good-stock">на полке: ${g.stock}</div>`;
  return `<div class="good ${g.sale ? "sale" : ""} ${g.affordable ? "" : "dear"}">
    <div class="good-head"><span class="good-emoji">${escapeHtml(g.emoji || "🎁")}</span>
      <span class="good-name">${escapeHtml(g.name)}</span></div>
    ${g.description ? `<div class="good-desc">${escapeHtml(g.description)}</div>` : ""}
    <div class="good-price"><b>${g.price.toLocaleString("ru")} i¢</b>
      ${g.sale ? `<s>${g.base_price.toLocaleString("ru")}</s>` : ""}
      ${g.discount && !g.sale ? `<s>${g.base_price.toLocaleString("ru")}</s>` : ""}</div>
    ${остаток}
    <div class="good-buy">
      <label class="sr-only" for="shop-qty-${escapeHtml(g.key)}">Количество «${escapeHtml(g.name)}»</label>
      <input id="shop-qty-${escapeHtml(g.key)}" class="good-qty" data-shop-qty
             type="text" inputmode="numeric" value="1" maxlength="4"
             aria-label="Количество" title="Количество или «все»" autocomplete="off">
      <button type="button" class="btn" data-sact="buy" data-key="${escapeHtml(g.key)}"
              data-bm="${g.black_market ? "1" : ""}" ${g.affordable ? "" : "disabled"}>Купить</button>
    </div>
  </div>`;
}

function invHtml(i) {
  return `<div class="inv-card ${i.reward ? "reward" : ""}">
    <div class="good-head"><span class="good-emoji">${escapeHtml(i.emoji || "🎁")}</span>
      <span class="good-name">${escapeHtml(i.name)}</span>
      <span class="inv-qty">×${i.quantity}</span></div>
    ${i.sellable
      ? `<div class="good-price"><b>${i.sell_price.toLocaleString("ru")} i¢</b>
           <span class="good-stock">за штуку</span></div>
         <div class="inv-actions">
           <button type="button" class="btn" data-sact="sell" data-key="${escapeHtml(i.key)}">Продать</button>
           <button type="button" class="btn ghost" data-sact="sellall" data-key="${escapeHtml(i.key)}">Всё</button>
         </div>`
      : `<div class="good-stock">${i.reward ? `${icon("medal")} награда — не продаётся` : "продать нельзя"}</div>`}
  </div>`;
}

function renderShop() {
  const s = _shop.state, body = $("#member-shop-body");
  if (!s || !body) return;
  const доступныеВкладки = new Set(["shop", "black_market", "inventory", "market"]);
  if (!доступныеВкладки.has(_shop.tab)) _shop.tab = "shop";
  const вкладка = _shop.tab;
  const tabs = [
    ["shop", "Витрина", "store"], ["black_market", "Лавка", "mask"],
    ["inventory", "Инвентарь", "bag"], ["market", "Рынок", "basket"],
  ];
  const вкладки = `<div class="shop-tabs" role="tablist" aria-label="Разделы магазина">${tabs.map(([key, label, ico]) =>
    `<button type="button" class="shop-tab ${вкладка === key ? "active" : ""}" role="tab"
      aria-selected="${вкладка === key}" data-shop-tab="${key}">${icon(ico)}${label}</button>`).join("")}</div>`;
  let содержание = "";
  if (вкладка === "shop") {
    содержание = `<h3 class="mb-2">${icon("store")}Витрина</h3>${s.items.length
      ? `<div class="shop-goods">${s.items.map(goodHtml).join("")}</div>`
      : `<div class="empty">${icon("empty")}<span>На витрине пока нет товаров.</span></div>`}`;
  } else if (вкладка === "black_market") {
    const лавка = s.black_market || [];
    содержание = `<h3 class="mb-2">${icon("mask")}Лавка · завоз на сегодня</h3>${лавка.length
      ? `<div class="shop-goods">${лавка.map(goodHtml).join("")}</div>`
      : `<div class="empty">${icon("empty")}<span>Сегодня лавка без завоза.</span></div>`}`;
  } else if (вкладка === "inventory") {
    содержание = `<h3 class="mb-2">${icon("bag")}Инвентарь</h3>${s.inventory.length
      ? `<div class="inv-list">${s.inventory.map(invHtml).join("")}</div>`
      : `<div class="empty">${icon("empty")}<span>Инвентарь пуст.</span></div>`}
      <div id="lootbox-block"></div>`;
  } else {
    содержание = `<div id="market-block"><div class="muted">Загрузка рынка…</div></div>
      <div id="steal-block"></div>`;
  }
  body.innerHTML = `
    <div class="biz-summary">
      <div><span class="total">${s.coins.toLocaleString("ru")} i¢</span>
        <span class="muted">в кошельке<small>магазин принимает предметы обратно за ${s.sell_percent}%</small></span></div>
    </div>
    ${вкладки}
    <div class="shop-pane" role="tabpanel">${содержание}</div>`;
  if (вкладка === "inventory") loadLootboxes();
  if (вкладка === "market") { loadMarket(); loadStealState(); }
}

// --- рынок участников -------------------------------------------------------
// Товары людей, а не бота: цену назначает сам продавец, и с каждой сделки в
// казну чата уходит комиссия. Заявку на свой товар одобряет администрация —
// экран говорит об этом до подачи, а не после.
const _market = { state: null };

async function loadMarket() {
  const блок = $("#market-block");
  if (!блок) return;
  try {
    _market.state = await api(`/api/member/game/market`);
  } catch (err) {
    блок.innerHTML = "";
    return;
  }
  renderMarket();
}

function renderMarket() {
  const s = _market.state, блок = $("#market-block");
  if (!s || !блок) return;
  const чужие = (s.goods || []).filter((g) => !g.mine);

  блок.innerHTML = `
    <h3 class="block-head">${icon("basket")}Рынок участников</h3>
    <div class="bank-meta">Товары людей, а не бота. С каждой покупки
      ${s.commission_percent}% уходит в казну чата. Свой товар: до
      ${s.max_goods} шт., цена до ${s.max_price.toLocaleString("ru")} i¢.</div>

    ${чужие.length ? `<div class="market-list">${чужие.map((g) => `
      <div class="market-row">
        <div class="market-name"><span class="good-emoji">${escapeHtml(g.emoji || "🧺")}</span> <b>${escapeHtml(безЭмодзи(g.name))}</b>
          <code class="steal-item-key">${escapeHtml(g.key)}</code>
          <span class="muted">${g.price.toLocaleString("ru")} i¢${g.sold ? ` · продано ${g.sold}` : ""}</span></div>
        <div class="market-acts">
          <input type="number" class="market-qty" data-key="${escapeHtml(g.key)}"
                 min="1" max="${s.max_qty}" value="1" inputmode="numeric" autocomplete="off">
          <button type="button" class="btn small" data-market="buy" data-key="${escapeHtml(g.key)}"
                  ${s.coins >= g.price ? "" : "disabled"}>Купить</button>
        </div>
      </div>`).join("")}</div>`
      : `<div class="muted mb-2">На рынке пока пусто.</div>`}

    ${(s.mine || []).length ? `
      <div class="muted mt-2 mb-2">Мои товары</div>
      <div class="market-list">${s.mine.map((g) => `
        <div class="market-row">
          <div class="market-name"><b>${escapeHtml(g.name)}</b>
            <code class="steal-item-key">${escapeHtml(g.key)}</code>
            <span class="muted">${g.price.toLocaleString("ru")} i¢ · ${marketStatus(g.status)}${
              g.sold ? ` · продано ${g.sold}` : ""}</span></div>
          <div class="market-acts">
            ${g.status !== "withdrawn"
              ? `<button type="button" class="btn ghost small" data-market="withdraw"
                         data-key="${escapeHtml(g.key)}">Снять</button>` : ""}
          </div>
        </div>`).join("")}</div>` : ""}

    ${s.accepts_requests ? `
      <div class="muted mt-2 mb-2">Выйти на рынок${s.auto_accept
        ? " · заявки принимаются сразу"
        : " · заявку одобряет администрация"}</div>
      <div class="market-apply">
        <input type="text" id="market-new-key" placeholder="ключ: ogurcy" autocomplete="off">
        <input type="text" id="market-new-name" placeholder="Название" maxlength="${s.name_max}" autocomplete="off">
        <input type="number" id="market-new-price" placeholder="Цена" min="1" max="${s.max_price}"
               inputmode="numeric" autocomplete="off">
        <button type="button" class="btn" data-market="apply">Подать заявку</button>
      </div>`
      : `<div class="bank-blocked mt-2">${icon("alert")}Приём заявок в чате сейчас закрыт.</div>`}
    <div id="market-msg"></div>`;
}

function marketStatus(s) {
  return { approved: "на витрине", pending: "ждёт одобрения",
           withdrawn: "снят", rejected: "отклонён" }[s] || s;
}

async function onMarketClick(e) {
  const el = e.target.closest("[data-market]");
  if (!el || el.disabled) return;
  const act = el.dataset.market;
  const тело = { key: el.dataset.key || "" };
  if (act === "buy") {
    const поле = $$(".market-qty").find((i) => i.dataset.key === el.dataset.key);
    тело.quantity = Number(поле && поле.value) || 1;
  }
  if (act === "apply") {
    тело.key = ($("#market-new-key") || {}).value || "";
    тело.name = ($("#market-new-name") || {}).value || "";
    тело.price = Number(($("#market-new-price") || {}).value) || 0;
  }
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/market/${act === "apply" ? "apply" : act}`,
                        { method: "POST", body: тело });
    _market.state = r.state;
    renderMarket();
    say("#market-msg", marketSaid(r), "ok");
  } catch (err) {
    say("#market-msg", err.message, "err");
    el.disabled = false;
  }
}

function marketSaid(r) {
  if (r.action === "buy") {
    const сбор = r.fee ? ` Комиссия чата: ${r.fee} i¢.` : "";
    return `Куплено «${r.name}» × ${r.quantity} за ${r.total.toLocaleString("ru")} i¢.${сбор}`;
  }
  if (r.action === "withdraw") return `Товар «${r.key}» снят с витрины.`;
  return r.pending
    ? `Заявка отправлена администрации. Товар появится на витрине после одобрения.`
    : `Товар «${r.name}» на витрине.`;
}

// --- лутбоксы ---------------------------------------------------------------
// В «Магазине», над медвежатником: это тоже покупка, только с неизвестным
// содержимым. Открытие показывает выпавшее списком — и отдельно помечает
// редкое, потому что ради него коробку и берут.
const _loot = { state: null };

async function loadLootboxes() {
  const блок = $("#lootbox-block");
  if (!блок) return;
  try {
    _loot.state = await api(`/api/member/game/lootbox`);
  } catch (err) {
    блок.innerHTML = "";
    return;
  }
  renderLootboxes();
}

function renderLootboxes() {
  const s = _loot.state, блок = $("#lootbox-block");
  if (!s || !блок) return;
  блок.innerHTML = `
    <h3 class="block-head">${icon("gift")}Лутбоксы</h3>
    <div class="loot-list">${s.kinds.map((k) => `
      <div class="loot-row">
        <div class="loot-name">${gicon("rar", k.key, "lg")} <b>${escapeHtml(k.name)}</b>
          <span class="muted">${k.price.toLocaleString("ru")} i¢ · редкое ${k.rare_chance}%</span></div>
        <div class="loot-have">${k.owned ? `${k.owned} шт.` : ""}</div>
        <div class="loot-acts">
          <button type="button" class="btn ghost small" data-loot="buy" data-key="${k.key}"
                  ${s.coins >= k.price ? "" : "disabled"}>Купить</button>
          <button type="button" class="btn small" data-loot="open" data-key="${k.key}"
                  ${k.owned ? "" : "disabled"}>Открыть</button>
        </div>
      </div>`).join("")}</div>
    <div id="loot-result"></div>`;
}

async function onLootboxClick(e) {
  const el = e.target.closest("[data-loot]");
  if (!el || el.disabled) return;
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/lootbox/${el.dataset.loot}`, {
      method: "POST", body: { rarity: el.dataset.key, count: 1 },
    });
    _loot.state = r.state;
    renderLootboxes();
    const место = $("#loot-result");
    if (место) место.innerHTML = r.action === "buy"
      ? `<div class="msg ok">Куплено за ${r.total_price.toLocaleString("ru")} i¢.</div>`
      : lootRewardsHtml(r);
  } catch (err) {
    say("#member-shop-msg", err.message, "err");
    el.disabled = false;
  }
}

function lootRewardsHtml(r) {
  return `<div class="loot-open">
    ${r.rewards.map((n) => `
      <div class="loot-prize ${n.rare ? "rare" : ""}">
        ${n.rare ? `<span class="loot-rare">${icon("spark")}редкое</span>` : ""}
        <b>${escapeHtml(безЭмодзи(n.name))}</b>
        <span class="muted">ценность ${n.price.toLocaleString("ru")} i¢</span>
        ${n.note ? `<span class="muted">· ${escapeHtml(n.note)}</span>` : ""}
      </div>`).join("")}
  </div>`;
}

// --- медвежатник -----------------------------------------------------------
// Живёт в «Магазине», под инвентарём, и появляется только когда инструмент
// есть на руках — ровно как команда в чате, которая без него не работает.
//
// Чужой инвентарь здесь НЕ показывается. Ключ предмета вводят руками, как и в
// чате: список чужих вещей выдал бы даром то, за чем существует отдельный
// платный предмет «Досье», и превратил бы медвежатник из риска в выбор из
// меню. Кража остаётся ставкой вслепую.
const _steal = { state: null, target: null, targetName: "", loot: null };

async function loadStealState() {
  const блок = $("#steal-block");
  if (!блок) return;
  try {
    _steal.state = await api(`/api/member/game/steal`);
  } catch (err) {
    блок.innerHTML = "";
    return;
  }
  renderSteal();
}

function renderSteal() {
  const s = _steal.state, блок = $("#steal-block");
  if (!s || !блок) return;
  if (!s.has_tool) { блок.innerHTML = ""; return; }

  const ждать = s.wait_seconds > 0
    ? `Замки ещё не остыли — ${Math.ceil(s.wait_seconds / 3600)} ч. до следующего дела.`
    : "";
  const мешает = s.curfew ? "Комендантский час — на улицах патрули." : ждать;

  блок.innerHTML = `
    <h3 class="block-head">${icon("key")}Медвежатник</h3>
    <div class="steal-card">
      <div class="bank-meta">Одна вещь из чужих закромов, раз в ${s.cooldown_hours} ч.
        Ключ предмета нужно знать заранее — здесь его не подскажут.
        У жертвы может стоять «Сигнализация»: глушит кражу с шансом
        ${s.signal_chance}%, и тогда инструмент сгорает впустую.
        ${s.has_slepok ? `Слепок ключа на руках — сократит откат на ${Math.round(s.slepok_cut * 100)}%.` : ""}</div>
      ${мешает ? `<div class="bank-blocked">${icon("alert")}${escapeHtml(мешает)}</div>` : `
      <label class="bet-field">
        <span>Кого вскрываем</span>
        <input type="text" id="steal-q" placeholder="Имя или @username" autocomplete="off">
      </label>
      <div class="member-target-list" id="steal-targets"></div>
      <div class="steal-chosen" id="steal-chosen">${
        _steal.target ? `Цель: <b>${escapeHtml(_steal.targetName)}</b>` : ""}</div>
      <div id="steal-loot">${stealLootHtml()}</div>
      <label class="bet-field">
        <span>Ключ предмета — тот, что виден в инвентаре</span>
        <input type="text" id="steal-key" placeholder="например, diamond" autocomplete="off">
      </label>
      <button type="button" class="btn steal-go" data-steal="go"
              ${_steal.target ? "" : "disabled"}>${icon("key")}Вскрыть закрома</button>`}
    </div>`;
  wireStealSearch();
}

// Что лежит у цели. Список приходит с сервера и уже без двух вещей: наград
// (их не украсть) и сигнализации — защита не должна выдавать сама себя, иначе
// вор просто обходил бы тех, у кого она есть.
function stealLootHtml() {
  if (!_steal.target) return "";
  const добыча = _steal.loot;
  if (добыча === null) return `<span class="muted">Смотрим, что там…</span>`;
  if (!добыча.length) {
    return `<span class="muted">Взять нечего — карманы пусты.</span>`;
  }
  return `<div class="steal-loot">${добыча.map((и) => `
    <button type="button" class="btn ghost small steal-item" data-key="${escapeHtml(и.key)}">
      <span class="steal-item-name"><span class="good-emoji">${escapeHtml(и.emoji || "🎁")}</span> ${escapeHtml(безЭмодзи(и.name))}${
        и.quantity > 1 ? ` ×${и.quantity}` : ""}</span>
      <code class="steal-item-key">${escapeHtml(и.key)}</code>
    </button>`).join("")}</div>`;
}

async function loadStealLoot() {
  if (!_steal.target) return;
  _steal.loot = null;
  const место = $("#steal-loot");
  if (место) место.innerHTML = stealLootHtml();
  try {
    const d = await api(`/api/member/game/steal/loot?target_id=${_steal.target}`);
    _steal.loot = d.items || [];
  } catch (err) {
    _steal.loot = [];
  }
  const снова = $("#steal-loot");
  if (снова) снова.innerHTML = stealLootHtml();
}

function wireStealSearch() {
  const поле = $("#steal-q"), список = $("#steal-targets");
  if (!поле || !список) return;
  let таймер = null;
  поле.addEventListener("input", () => {
    clearTimeout(таймер);
    таймер = setTimeout(async () => {
      const q = поле.value.trim();
      if (!q) { список.innerHTML = ""; return; }
      try {
        const d = await api(`/api/member/chat-members?q=${encodeURIComponent(q)}`);
        const люди = d.members || [];
        список.innerHTML = люди.length
          ? люди.map((m) => `<button type="button" class="btn ghost small steal-pick" data-id="${m.user_id}">${
              escapeHtml(m.full_name || (m.username ? "@" + m.username : String(m.user_id)))}</button>`).join("")
          : `<span class="muted">Никого не найдено</span>`;
      } catch (err) {
        список.innerHTML = `<span class="muted">${escapeHtml(err.message)}</span>`;
      }
    }, 300);
  });
}

async function onStealClick(e) {
  const выбор = e.target.closest(".steal-pick");
  if (выбор) {
    _steal.target = Number(выбор.dataset.id);
    _steal.targetName = выбор.textContent.trim();
    const строка = $("#steal-chosen");
    if (строка) строка.innerHTML = `Цель: <b>${escapeHtml(_steal.targetName)}</b>`;
    const кнопка = $(".steal-go");
    if (кнопка) кнопка.disabled = false;
    loadStealLoot();
    return;
  }
  // Нажали по вещи из списка — подставляем её ключ в поле. Поле остаётся
  // доступным для ручного ввода: список показывает не всё, что у человека
  // есть, и знающий ключ не должен упираться в меню.
  const вещь = e.target.closest(".steal-item");
  if (вещь) {
    const поле = $("#steal-key");
    if (поле) поле.value = вещь.dataset.key;
    return;
  }
  const el = e.target.closest("[data-steal]");
  if (!el || el.disabled) return;
  const ключ = ($("#steal-key") || {}).value || "";
  if (!_steal.target) { say("#member-shop-msg", "Не выбрана цель.", "err"); return; }
  if (!ключ.trim()) { say("#member-shop-msg", "Не сказано, что красть.", "err"); return; }
  // Кража громкая: о ней узнают все в чате и сама жертва. Предупреждаем — с
  // сайта это не так очевидно, как из чата, где сообщение видно сразу.
  if (!confirm(`Вскрыть закрома «${_steal.targetName}»? О краже узнает весь чат, `
               + `а жертве придёт личное сообщение.`)) return;
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/steal`, {
      method: "POST", body: { target_id: _steal.target, item_key: ключ.trim() },
    });
    _steal.state = r.state;
    say("#member-shop-msg", stealSaid(r), r.outcome === "stolen" ? "ok" : "err");
    _steal.target = null;
    _steal.targetName = "";
    _steal.loot = null;
    renderSteal();
    await loadShopState();
  } catch (err) {
    say("#member-shop-msg", err.message, "err");
    el.disabled = false;
  }
}

function stealSaid(r) {
  if (r.outcome === "blocked") {
    return "Взвыла сигнализация — ушли с пустыми руками. Медвежатник потрачен.";
  }
  if (r.outcome === "gone") {
    return "Предмет успели потратить — вскрывать оказалось нечего.";
  }
  const промах = r.signal_missed ? " Сигнализация не сработала." : "";
  const слепок = r.slepok_used ? " Слепок ключа сократил откат." : "";
  return `Унесли «${r.item_name || r.item_key}».${промах}${слепок}`;
}

async function onShopClick(e) {
  // Медвежатник живёт на этом же экране, поэтому его нажатия разбираются
  // здесь же: второй слушатель на тот же узел означал бы два места, где
  // решают, что делать с одним и тем же кликом.
  const tab = e.target.closest("[data-shop-tab]");
  if (tab) {
    _shop.tab = tab.dataset.shopTab;
    renderShop();
    return;
  }
  if (e.target.closest("[data-market]")) return onMarketClick(e);
  if (e.target.closest("[data-loot]")) return onLootboxClick(e);
  if (e.target.closest("[data-steal]") || e.target.closest(".steal-pick")
      || e.target.closest(".steal-item")) {
    return onStealClick(e);
  }
  const el = e.target.closest("[data-sact]");
  if (!el) return;
  const act = el.dataset.sact, key = el.dataset.key;
  let тело = { key };
  let адрес = "buy";
  if (act === "buy") {
    тело.black_market = el.dataset.bm === "1";
    const полеКоличества = el.closest(".good")?.querySelector("[data-shop-qty]");
    const сколько = полеКоличества?.value.trim() || "1";
    тело.qty = /^\s*(все|всё|all)\s*$/i.test(сколько) ? "все" : Number(сколько) || 1;
  } else {
    адрес = "sell";
    тело.qty = act === "sellall" ? "все" : 1;
  }
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/shop/${адрес}`, { method: "POST", body: тело });
    _shop.state = r.state;
    renderShop();
    say("#member-shop-msg", адрес === "buy"
      ? `Куплено: ${r.name} ×${r.qty} за ${r.total.toLocaleString("ru")} i¢${r.sale ? " (распродажа)" : ""}`
      : `Продано: ${r.name} ×${r.qty} за ${r.total.toLocaleString("ru")} i¢`);
  } catch (err) {
    say("#member-shop-msg", err.message, "err");
    el.disabled = false;
  }
}

// --- питомцы ---------------------------------------------------------------
async function loadPetsState() {
  const body = $("#member-pets-body");
  if (!body) return;
  try {
    _pets.data = await api(`/api/member/game/pets`);
    renderPets();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

function petStat(вид, иконка, значение, максимум, подпись) {
  const доля = максимум ? Math.max(0, Math.min(100, Math.round(значение * 100 / максимум))) : 0;
  // Ниже трети — предупреждение: пока значение низкое, способности не
  // работают, и понять это надо не читая подпись.
  const тревога = вид !== "xp" && доля < 34 ? " low" : "";
  return `<div class="pet-stat ${вид}${тревога}">
    ${icon(иконка)}<span class="bar"><i style="width:${доля}%"></i></span>
    <span class="val">${подпись}</span></div>`;
}

function petCardHtml(p) {
  const классы = ["pet-card"];
  if (p.evolved) классы.push("evolved");
  if (p.pinned) классы.push("pinned");
  if (!p.active) классы.push("sleepy");
  const способности = p.abilities.map((a) => `
    <div class="pet-ability ${a.works ? "" : "sleeping"}">
      ${icon(a.works ? "spark" : "sleep")}
      <span>${escapeHtml(безЭмодзи(a.text))}${a.works ? "" : " — спит"}</span>
    </div>`).join("");
  return `<div class="${классы.join(" ")}">
    <div class="pet-head">
      <span class="pet-emoji">${escapeHtml(p.emoji || "🐾")}</span>
      <span class="grow">
        <span class="pet-name">${escapeHtml(p.name)}</span>
        <span class="pet-key">${escapeHtml(p.key)}${
          p.species && p.species !== p.name ? ` · ${escapeHtml(p.species)}` : ""}</span>
      </span>
      <span class="pet-lvl-badge">${icon("star")} ${p.is_max ? "MAX" : `${p.level}/${p.max_level}`}</span>
    </div>
    ${petStat("hunger", "bowl", p.hunger, 100, p.hunger)}
    ${petStat("mood", "smile", p.mood, 100, p.mood)}
    ${p.is_max ? "" : petStat("xp", "xp", p.xp, p.xp_need, `${p.xp}/${p.xp_need}`)}
    <div class="pet-state">${petStateHtml(p.state)}${p.evolved ? " · эволюционировал(а)" : ""}</div>
    ${способности}
    <div class="inv-actions">
      <button type="button" class="btn" data-pact="feed" data-key="${escapeHtml(p.key)}">${icon("bowl")} Покормить</button>
      <button type="button" class="btn ghost" data-pact="pet" data-key="${escapeHtml(p.key)}">${icon("heart")} Приласкать</button>
    </div>
    <div class="inv-actions">
      <button type="button" class="btn ghost" data-pact="walk" data-key="${escapeHtml(p.key)}">${icon("walk")} Погулять</button>
      <button type="button" class="btn ghost" data-pact="${p.pinned ? "unpin" : "pin"}" data-key="${escapeHtml(p.key)}">
        ${icon("pin")} ${p.pinned ? "Открепить" : "Закрепить"}</button>
    </div>
  </div>`;
}

function renderPets() {
  const d = _pets.data, body = $("#member-pets-body");
  if (!d || !body) return;
  // Карточки строятся из ЧИСЕЛ (cards), а не из текста бота: тот собран для
  // чата, с полосками из ▰▱, и на сайте читается как стена. Текст оставлен
  // запасным путём — если сервер старый и чисел не прислал.
  const карточки = d.cards || [];
  const каталог = d.catalog || [];
  const витрина = каталог.length ? `<section class="pet-catalog">
    <h3 class="block-head">${icon("paw")}Завести питомца</h3>
    <div class="pet-list">${каталог.map((p) => `<div class="pet-card pet-store-card">
      <div class="good-head"><span class="good-emoji">${escapeHtml(p.emoji || "🐾")}</span>
        <span class="good-name">${escapeHtml(p.name)}</span></div>
      ${p.ability ? `<div class="pet-note">${escapeHtml(безЭмодзи(p.ability))}</div>` : ""}
      ${p.limit !== null && p.limit !== undefined ? `<div class="pet-note">Хозяев: ${p.taken}/${p.limit}</div>` : ""}
      ${p.available ? `<div class="good-price"><b>${p.price.toLocaleString("ru")} i¢</b></div>
        <button type="button" class="btn" data-pact="buy" data-key="${escapeHtml(p.key)}">Завести</button>`
        : `<div class="good-stock">${escapeHtml(p.reason || "Недоступен")}</div>`}
    </div>`).join("")}</div>
  </section>` : "";
  if (!карточки.length) {
    body.innerHTML = `<div class="empty">${icon("empty")}<span>Питомцев пока нет — выберите друга в каталоге ниже.</span></div>${витрина}`;
    return;
  }
  body.innerHTML = `
    <div class="pet-food">${icon("bowl")}
      <span>Корма у вас: <b>${d.food ?? 0}</b> шт.</span>
      <span class="muted push">питомцев: ${карточки.length}</span></div>
    <div class="pet-list">${карточки.map(petCardHtml).join("")}</div>
    <div class="farm-actions">
      <button type="button" class="btn" data-pact="feed_all">${icon("bowl")} Покормить всех</button>
      <button type="button" class="btn" data-pact="care_all" data-verb="pet">${icon("heart")} Приласкать всех</button>
      <button type="button" class="btn" data-pact="walk_all">${icon("walk")} Погулять со всеми</button>
    </div>
    ${витрина}`;
}

async function onPetsClick(e) {
  const el = e.target.closest("[data-pact]");
  if (!el) return;
  const act = el.dataset.pact;
  const тело = {};
  if (el.dataset.key) тело.key = el.dataset.key;
  if (el.dataset.verb) тело.verb = el.dataset.verb;
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/pets/${act}`, { method: "POST", body: тело });
    say("#member-pets-msg", String(r.text || "Готово.").replace(/<[^>]+>/g, ""), r.ok ? "ok" : "err");
    await loadPetsState();
  } catch (err) {
    say("#member-pets-msg", err.message, "err");
    el.disabled = false;
  }
}

// ===== Вкладка «Биржа» =====================================================
// Курс, свои акции, дивиденды и график. График рисует lineChart — тот же, что
// в админской панели: две реализации одного графика по одним и тем же данным
// разъедутся, и разъедутся молча.
const _stock = { state: null, bound: false };

async function loadMemberStock() {
  await loadSimpleScreen("stock", `${icon("chart")}Биржа`, _stock, loadStockState, onStockClick);
}

async function loadStockState() {
  const body = $("#member-stock-body");
  if (!body) return;
  try {
    _stock.state = await api(`/api/member/game/stock`);
    renderStock();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// Точки истории → то, что понимает lineChart. Подписи считаются здесь, а не на
// сервере: сервер отдаёт цену и время, а как их назвать — дело экрана.
function stockPoints(история) {
  const когда = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString("ru-RU",
      { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  return (история || []).map((т) => ({
    value: т.price,
    title: `${когда(т.at)} — ${т.price} i¢`,
    axis: когда(т.at),
  }));
}

function renderStock() {
  const s = _stock.state, body = $("#member-stock-body");
  if (!s || !body) return;

  // Выключенная биржа заморожена целиком: смотреть можно, торговать нельзя.
  // Кнопки не прячем, а объясняем — исчезнувшие кнопки читаются как поломка.
  const заморожена = !s.enabled
    ? `<div class="stock-frozen">${icon("alert")}${escapeHtml(s.disabled_text)}</div>` : "";
  const выкл = s.enabled ? "" : "disabled";

  const прибыль = s.value - s.invested;
  const знак = прибыль > 0 ? "+" : "";
  const цвет = прибыль > 0 ? "up" : (прибыль < 0 ? "down" : "");

  body.innerHTML = `
    <div class="stock-top">
      <div class="stock-price"><b>${s.price.toLocaleString("ru")} i¢</b>
        <span>за акцию · в кошельке ${s.coins.toLocaleString("ru")} i¢</span></div>
      <div class="stock-mine ${цвет}">
        <b>${s.value.toLocaleString("ru")} i¢</b>
        <span>${s.shares} шт.${s.invested ? ` · ${знак}${прибыль.toLocaleString("ru")} i¢` : ""}</span>
      </div>
    </div>
    ${заморожена}
    ${lineChart("Курс акций", `За последние ${s.chart_days} дней · дивиденды ${s.dividend_percent}% в сутки от вложенного`,
                stockPoints(s.history))}

    <div class="stat-grid mt-3">
      ${statCell(`${s.invested.toLocaleString("ru")}`, "вложено i¢")}
      ${statCell(`${s.room.toLocaleString("ru")}`, "можно ещё i¢")}
      ${statCell(`${Math.round(s.pending_dividends).toLocaleString("ru")}`, "дивиденды ждут")}
      ${statCell(`${s.total_profit.toLocaleString("ru")}`, "заработано всего")}
    </div>

    <label class="bet-field">
      <span>Сумма сделки · в кошельке ${s.coins.toLocaleString("ru")} i¢</span>
      <input type="number" id="stock-amount" min="1" step="1" value="${Math.min(1000, s.coins) || 1}"
             inputmode="numeric" autocomplete="off" ${выкл}>
    </label>
    <div class="bet-quick">
      <button type="button" class="btn ghost" data-sact="set" data-amount="1000" ${выкл}>1 000</button>
      <button type="button" class="btn ghost" data-sact="set" data-amount="10000" ${выкл}>10 000</button>
      <button type="button" class="btn ghost" data-sact="set" data-amount="100000" ${выкл}>100 000</button>
      <button type="button" class="btn ghost" data-sact="set" data-amount="wallet" ${выкл}>Весь кошелёк</button>
    </div>
    <div class="stock-ops">
      <button type="button" class="btn stock-buy" data-sact="buy" ${выкл}>${icon("in")}Купить</button>
      <button type="button" class="btn stock-sell" data-sact="sell" ${выкл}>${icon("out")}Продать</button>
      <button type="button" class="btn stock-all" data-sact="sell-all" ${выкл}>Продать всё</button>
    </div>
    <button type="button" class="btn stock-div" data-sact="dividends"
            ${s.enabled && s.pending_dividends >= 1 ? "" : "disabled"}>
      ${icon("coins")}Забрать дивиденды${s.pending_dividends >= 1
        ? ` · ${Math.round(s.pending_dividends).toLocaleString("ru")} i¢` : ""}
    </button>
    <div class="hint">Дивиденды капают раз в сутки от вложенной суммы. Максимум
      вложений на человека — ${s.max_invest.toLocaleString("ru")} i¢.</div>`;
}

async function onStockClick(e) {
  const el = e.target.closest("[data-sact]");
  if (!el || el.disabled) return;
  const act = el.dataset.sact;
  const поле = $("#stock-amount");

  if (act === "set") {
    if (!поле) return;
    поле.value = el.dataset.amount === "wallet"
      ? (_stock.state ? _stock.state.coins : 0) : el.dataset.amount;
    return;
  }

  const тело = {};
  if (act === "buy" || act === "sell") {
    const сумма = Number(поле && поле.value) || 0;
    if (сумма <= 0) { say("#member-stock-msg", "Сколько монет?", "err"); return; }
    тело.amount = сумма;
  }
  // «Всё» уходит на сервер словом: во сколько монет оно разворачивается,
  // знают только доли и курс, а посчитанное здесь после округления стабильно
  // промахивается мимо предела продажи на копейку.
  if (act === "sell-all") тело.amount = "все";
  const путь = act === "dividends" ? "dividends" : (act === "buy" ? "buy" : "sell");

  el.disabled = true;
  try {
    const r = await api(`/api/member/game/stock/${путь}`, { method: "POST", body: тело });
    _stock.state = r.state;
    say("#member-stock-msg", stockSaid(r), "ok");
    renderStock();
  } catch (err) {
    say("#member-stock-msg", err.message, "err");
    el.disabled = false;
  }
}

function stockSaid(r) {
  if (r.action === "buy") {
    return `Куплено ${r.shares} акций по ${r.price} i¢ на сумму ${r.amount.toLocaleString("ru")} i¢.`;
  }
  if (r.action === "sell") {
    const итог = r.profit > 0 ? `прибыль +${Math.round(r.profit)} i¢`
      : (r.profit < 0 ? `убыток ${Math.round(r.profit)} i¢` : "без прибыли и убытка");
    return `Продано на ${r.amount.toLocaleString("ru")} i¢ по курсу ${r.price} (${итог}).`;
  }
  return `Получены дивиденды: +${r.amount.toLocaleString("ru")} i¢`;
}

// ===== Вкладка «Банк» ======================================================
// Вклад, кредит и погашение. Главное отличие от остальных экранов: кредит НЕ
// выдаётся по нажатию — заявку одобряет админ кнопкой в телеграме. Поэтому
// экран заранее говорит, почему кредит недоступен (чёрный список, автоотказ,
// минус на балансе, уже поданная заявка), а не сообщает об этом после
// нажатия: отказ по факту читается как поломка, а не как правило.
const _bank = { state: null, bound: false, days: 1 };

async function loadMemberBank() {
  await loadSimpleScreen("bank", `${icon("coins")}Банк`, _bank, loadBankState, onBankClick);
  // Общий каркас вешает только нажатия, а здесь считается ещё и на ввод:
  // сколько получишь и сколько вернёшь, пока набираешь сумму.
  const box = $("#member-bank");
  if (box && !_bank.boundInput) {
    box.addEventListener("input", onBankInput);
    _bank.boundInput = true;
  }
}

async function loadBankState() {
  const body = $("#member-bank-body");
  if (!body) return;
  try {
    _bank.state = await api(`/api/member/game/bank`);
    renderBank();
  } catch (err) {
    body.innerHTML = `<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`;
  }
}

// Когда созреет вклад или когда истекает кредит — словами. Точное время в
// подсказке: «через 2 дня» отвечает на вопрос, а дата и час нужны редко.
function bankWhen(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const осталось = d - new Date();
  if (осталось <= 0) return "уже";
  const часы = Math.floor(осталось / 3600000);
  const дни = Math.floor(часы / 24);
  if (дни >= 1) return `через ${дни} дн. ${часы % 24} ч.`;
  if (часы >= 1) return `через ${часы} ч.`;
  return `через ${Math.max(1, Math.round(осталось / 60000))} мин.`;
}

function bankWhenTitle(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("ru-RU");
}

// Почему кредит недоступен. Причина одна и первая по важности: перечислять
// все сразу незачем, человеку нужно знать, что делать дальше.
function bankCreditBlocker(s) {
  if (s.credit) return "Сначала погасите текущий кредит.";
  if (s.pending) return "Заявка уже подана и ждёт решения администраторов.";
  if (s.blacklisted) return "Вам закрыт доступ к кредитам — вы в чёрном списке.";
  if (s.in_the_red) return "Баланс отрицательный после взыскания. Кредит дадут, когда выйдете в ноль.";
  if (s.auto_reject) return "Кредиты в чате временно не выдаются.";
  if (!s.gate_ready) return "Кредиты пока некому одобрять — админы не настроили чат заявок.";
  return "";
}

function renderBank() {
  const s = _bank.state, body = $("#member-bank-body");
  if (!s || !body) return;

  const вклад = s.deposit
    ? `<div class="bank-card ${s.deposit.ready ? "ready" : ""}">
         <div class="bank-card-head">${icon("coins")}Вклад</div>
         <div class="bank-sum">${s.deposit.amount.toLocaleString("ru")} i¢</div>
         <div class="bank-meta">${s.deposit.days} дн. под ${s.deposit.rate}%/день ·
           выплата <b>${s.deposit.payout.toLocaleString("ru")} i¢</b></div>
         <div class="bank-meta" title="${escapeHtml(bankWhenTitle(s.deposit.matures_at))}">
           ${s.deposit.ready ? "созрел — можно снимать"
             : `созреет ${escapeHtml(bankWhen(s.deposit.matures_at))}`}</div>
         <button type="button" class="btn bank-take" data-bact="withdraw"
                 ${s.deposit.ready ? "" : "disabled"}>
           ${s.deposit.ready ? "Снять вклад" : "Досрочно снять нельзя"}</button>
       </div>`
    : `<div class="bank-card">
         <div class="bank-card-head">${icon("coins")}Вклад</div>
         <div class="bank-meta">Вклада нет. Проценты простые: ставка фиксируется
           в момент открытия и не меняется до конца срока.</div>
         <div class="bank-terms">
           ${s.terms.map((t) => `
             <button type="button" class="btn bank-term ${_bank.days === t.days ? "active" : ""}"
                     data-bact="term" data-days="${t.days}">
               <b>${t.days} дн.</b><span>${t.rate}%/день</span></button>`).join("")}
         </div>
         <label class="bet-field">
           <span>Сумма вклада · минимум ${s.min_deposit.toLocaleString("ru")} i¢</span>
           <input type="number" id="bank-amount" min="1" step="1"
                  value="${Math.max(s.min_deposit, 0) || 1}" inputmode="numeric" autocomplete="off">
         </label>
         <div class="bank-payout" id="bank-payout"></div>
         <button type="button" class="btn bank-open" data-bact="deposit">Открыть вклад</button>
       </div>`;

  const мешает = bankCreditBlocker(s);
  const кредит = s.credit
    ? `<div class="bank-card ${s.credit.overdue ? "overdue" : ""}">
         <div class="bank-card-head">${icon("alert")}Кредит</div>
         <div class="bank-sum">${s.credit.debt.toLocaleString("ru")} i¢</div>
         <div class="bank-meta" title="${escapeHtml(bankWhenTitle(s.credit.due_at))}">
           ${s.credit.overdue
             ? `просрочен — капает пеня ${s.credit_penalty_percent}%/день`
             : `вернуть ${escapeHtml(bankWhen(s.credit.due_at))}`}</div>
         <label class="bet-field">
           <span>Сколько погасить · в кошельке ${s.coins.toLocaleString("ru")} i¢</span>
           <input type="number" id="bank-repay-amount" min="1" step="1"
                  value="${Math.min(s.credit.debt, Math.max(s.coins, 1))}"
                  inputmode="numeric" autocomplete="off">
         </label>
         <div class="stock-ops">
           <button type="button" class="btn bank-pay" data-bact="repay">Погасить</button>
           <button type="button" class="btn ghost" data-bact="repay-all">Погасить весь долг</button>
         </div>
       </div>`
    : `<div class="bank-card">
         <div class="bank-card-head">${icon("alert")}Кредит</div>
         <div class="bank-meta">Комиссия ${s.credit_fee_percent}% · срок
           ${s.credit_term_days} дн. · пеня за просрочку ${s.credit_penalty_percent}%/день.
           Выдаётся не сразу: заявку одобряет администратор.</div>
         ${мешает ? `<div class="bank-blocked">${icon("alert")}${escapeHtml(мешает)}</div>` : `
         <label class="bet-field">
           <span>Сумма кредита</span>
           <input type="number" id="bank-credit-amount" min="1" step="1" value="1000"
                  inputmode="numeric" autocomplete="off">
         </label>
         <div class="bank-payout" id="bank-debt"></div>
         <button type="button" class="btn bank-ask" data-bact="credit">Подать заявку</button>`}
       </div>`;

  body.innerHTML = `
    <div class="bank-top">
      <div class="bank-wallet"><b>${s.coins.toLocaleString("ru")} i¢</b>
        <span>в кошельке</span></div>
    </div>
    <div class="bank-grid">${вклад}${кредит}</div>
    <h3 class="block-head">${icon("coins")}Переводы</h3>
    ${s.transfers?.length ? `<div class="money-history">
      ${s.transfers.map((t) => {
        const отправлен = t.direction === "sent";
        const дата = t.created_at ? new Date(t.created_at).toLocaleString("ru-RU", {
          day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
        }) : "";
        return `<div class="money-row ${отправлен ? "out" : "in"}">
          <span class="money-sign">${отправлен ? "↑" : "↓"}</span>
          <span class="grow"><b>${отправлен ? "Перевод" : "Получено"}</b>
            <small>${отправлен ? "для" : "от"} ${escapeHtml(t.counterparty)}${дата ? ` · ${escapeHtml(дата)}` : ""}</small></span>
          <b>${отправлен ? "−" : "+"}${Number(t.amount).toLocaleString("ru")} i¢</b>
        </div>`;
      }).join("")}
    </div>` : `<div class="empty bank-history-empty">${icon("coins")}<span>Переводов пока нет. Здесь появятся отправленные и полученные i¢.</span></div>`}
    <h3 class="block-head">${icon("coins")}Заработки</h3>
    ${s.earnings?.length ? `<div class="money-history">
      ${s.earnings.map((e) => {
        const дата = e.created_at ? new Date(e.created_at).toLocaleString("ru-RU", {
          day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
        }) : "";
        return `<div class="money-row in">
          <span class="money-sign">+</span>
          <span class="grow"><b>${escapeHtml(e.source)}</b>
            <small>${дата ? escapeHtml(дата) : ""}</small></span>
          <b>+${Number(e.amount).toLocaleString("ru")} i¢</b>
        </div>`;
      }).join("")}
    </div>` : `<div class="empty bank-history-empty">${icon("coins")}<span>Заработков пока нет. История записывается после обновления бота.</span></div>`}`;
  bankRefreshHints();
}

// Сколько получишь и сколько вернёшь — считаем сразу, теми же формулами, что
// на сервере. Число, которое видно ДО нажатия, и есть главная часть этого
// экрана: без него «7% в день» ничего не говорит.
function bankRefreshHints() {
  const s = _bank.state;
  if (!s) return;
  const вклад = $("#bank-amount"), итог = $("#bank-payout");
  if (вклад && итог) {
    const сумма = Number(вклад.value) || 0;
    const срок = s.terms.find((t) => t.days === _bank.days) || s.terms[0];
    const выплата = срок ? Math.floor(сумма + сумма * срок.rate / 100 * срок.days) : сумма;
    итог.innerHTML = сумма >= s.min_deposit && срок
      ? `Через ${срок.days} дн. получите <b>${выплата.toLocaleString("ru")} i¢</b>
         <span class="muted">(+${(выплата - сумма).toLocaleString("ru")})</span>`
      : `<span class="muted">Минимум ${s.min_deposit.toLocaleString("ru")} i¢</span>`;
  }
  const кредит = $("#bank-credit-amount"), долг = $("#bank-debt");
  if (кредит && долг) {
    const сумма = Number(кредит.value) || 0;
    const вернуть = Math.round(сумма * (1 + s.credit_fee_percent / 100));
    долг.innerHTML = сумма > 0
      ? `Вернуть придётся <b>${вернуть.toLocaleString("ru")} i¢</b>
         <span class="muted">за ${s.credit_term_days} дн.</span>`
      : "";
  }
}

function onBankInput(e) {
  if (["bank-amount", "bank-credit-amount"].includes(e.target.id)) bankRefreshHints();
}

async function onBankClick(e) {
  const el = e.target.closest("[data-bact]");
  if (!el || el.disabled) return;
  const act = el.dataset.bact;

  if (act === "term") {
    _bank.days = Number(el.dataset.days);
    renderBank();
    return;
  }

  const тело = {};
  if (act === "deposit") {
    тело.amount = Number(($("#bank-amount") || {}).value) || 0;
    тело.days = _bank.days;
  }
  if (act === "repay") тело.amount = Number(($("#bank-repay-amount") || {}).value) || 0;
  if (act === "repay-all") тело.amount = "всё";
  if (act === "credit") тело.amount = Number(($("#bank-credit-amount") || {}).value) || 0;

  const путь = act === "repay-all" ? "repay" : act;
  el.disabled = true;
  try {
    const r = await api(`/api/member/game/bank/${путь}`, { method: "POST", body: тело });
    _bank.state = r.state;
    say("#member-bank-msg", bankSaid(r), "ok");
    renderBank();
  } catch (err) {
    say("#member-bank-msg", err.message, "err");
    el.disabled = false;
  }
}

function bankSaid(r) {
  if (r.action === "deposit") {
    return `Вклад открыт: ${r.amount.toLocaleString("ru")} i¢ на ${r.days} дн. под ${r.rate}%/день. Получите ${r.payout.toLocaleString("ru")} i¢.`;
  }
  if (r.action === "withdraw") {
    return `Вклад закрыт, получено ${r.payout.toLocaleString("ru")} i¢.`;
  }
  if (r.action === "repay") {
    return r.closed
      ? `Погашено ${r.amount.toLocaleString("ru")} i¢. Кредит полностью закрыт.`
      : `Погашено ${r.amount.toLocaleString("ru")} i¢. Остаток долга: ${r.debt.toLocaleString("ru")} i¢.`;
  }
  return `Заявка на ${r.amount.toLocaleString("ru")} i¢ отправлена администраторам. К возврату ${r.debt.toLocaleString("ru")} i¢ за ${r.term_days} дн.`;
}

// Запуск только после объявления состояния всех экранов. Раньше boot стоял
// посередине файла: на быстром ответе /api/me профиль мог обратиться к _prof
// в его temporal dead zone и оставлял /member/profile пустым.
boot().catch((err) => {
  $("#auth")?.classList.remove("hidden");
  say("#auth-msg", err.message || "Не удалось открыть панель", "err");
});
