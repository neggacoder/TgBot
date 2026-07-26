"use strict";
// app.js
// Одностраничный интерфейс панели. Никаких внешних библиотек — политика
// безопасности страницы запрещает подгружать что-либо со сторонних адресов.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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
  box.innerHTML = `<div class="msg ${kind}">${icon(kind === "ok" ? "check" : "alert")}<span>${escapeHtml(text)}</span></div>`;
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

const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{20E3}]/gu;

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

// Тему ставим до первой отрисовки — иначе панель мигнёт чужим цветом.
applyTheme(localStorage.getItem(THEME_KEY));

// --- вход -----------------------------------------------------------------

async function boot() {
  const state = await api("/api/me");
  if (state.authenticated) {
    me = state;
    if (me.role === "member") showMember(); else showApp();
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

$("#auth-form").addEventListener("submit", async (e) => {
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
    location.href = "/";
  } catch (err) {
    say("#auth-msg", err.message, "err");
  }
});

$("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.href = "/";
});

$("#theme-toggle").addEventListener("click", toggleTheme);

// --- вход и экран участника (read-only) -----------------------------------

$("#member-toggle").addEventListener("click", () => {
  $("#auth-form").classList.add("hidden");
  $("#member-form").classList.remove("hidden");
  $("#member-code").focus();
});

$("#member-back").addEventListener("click", () => {
  $("#member-form").classList.add("hidden");
  $("#auth-form").classList.remove("hidden");
});

$("#member-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("#member-code").value.trim();
  if (!code) return;
  try {
    await api("/api/member/login", { method: "POST", body: { code } });
    location.href = "/";
  } catch (err) {
    say("#member-msg", err.message, "err");
  }
});

$("#member-logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.href = "/";
});

$("#member-theme").addEventListener("click", toggleTheme);

// Какие вкладки участника уже загружены (ленивая загрузка при первом открытии).
const _memberLoaded = { rel: false, family: false, clans: false, caps: false };

function showMember() {
  $("#auth").classList.add("hidden");
  $("#app").classList.add("hidden");
  $("#member").classList.remove("hidden");
  // Кнопка возврата — только у персонала (admin/owner), заглянувшего сюда из
  // своей панели. Обычный участник (role === "member") сюда попадает
  // напрямую при входе и возвращаться ему некуда.
  $("#member-back-to-panel").classList.toggle("hidden", !me || me.role === "member");
  _memberLoaded.rel = _memberLoaded.family = _memberLoaded.clans = _memberLoaded.caps = false;
  switchMemberTab("rel");
}

$("#member-back-to-panel").addEventListener("click", () => {
  $("#member").classList.add("hidden");
  showApp();
});

function switchMemberTab(name) {
  $$(".member-tab").forEach((b) => b.classList.toggle("active", b.dataset.mtab === name));
  $$(".member-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
  if (name === "rel" && !_memberLoaded.rel) { _memberLoaded.rel = true; loadMemberRelationship(); }
  else if (name === "family" && !_memberLoaded.family) { _memberLoaded.family = true; loadMemberFamily(); }
  else if (name === "clans" && !_memberLoaded.clans) { _memberLoaded.clans = true; loadMemberClans(); }
  else if (name === "caps" && !_memberLoaded.caps) { _memberLoaded.caps = true; loadMemberCapabilities(); }
}

// ===== Вкладка «Кланы» =====================================================
const CLAN_ROLE = { leader: "Лидер", deputy: "Зам", member: "Участник" };

function memberClansChat() {
  const sel = $("#member-clans-chat");
  return sel ? Number(sel.value) : NaN;
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
      `<label><span>Чат</span><select id="member-clans-chat">${options}</select></label>
       <div id="member-clans-status"></div>`
    );
    $("#member-clans-chat").addEventListener("change", loadMemberClanStatus);
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
      <label><span>Название</span><input type="text" id="clan-edit-name" value="${escapeHtml(c.name)}"></label>
      <textarea id="clan-edit-desc" rows="2" placeholder="Описание">${escapeHtml(c.description || "")}</textarea>
      <button class="ghost small" id="clan-edit-btn">${icon("edit")}Сохранить описание</button>
      <div class="clan-inline"><input type="text" id="clan-title" value="${escapeHtml(c.title || "")}" placeholder="Звание (пусто — снять)">
        <button class="ghost small" id="clan-title-btn">${icon("tag")}Звание</button></div>
      <div class="clan-inline"><input type="text" id="clan-motto" value="${escapeHtml(c.motto || "")}" placeholder="Девиз (пусто — снять)">
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
    return `<div class="muted" style="margin-top:var(--gap-3)">В этом чате пока нет кланов${my ? "" : " — создайте первый"}.</div>`;
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
  const sel = $("#member-family-chat");
  return sel ? Number(sel.value) : NaN;
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
      `<label><span>Чат</span><select id="member-family-chat">${options}</select></label>
       <div id="member-family-status"></div>`
    );
    $("#member-family-chat").addEventListener("change", loadMemberFamilyStatus);
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
      out += `<div class="fam-row"><b>${escapeHtml(d.house.name)}</b> <span class="muted">· ${d.house.status === "building" ? "строится" : "готов"}</span></div>`;
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

// Одна read-only секция обзора: действия (сворачиваемые, как в админке, но без
// кнопок правки) + синонимы. Фразы — данные бота (с эмодзи), показываем как есть.
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
          ${a.phrases.map((p) => `<div class="phrase-row"><span class="phrase-text">${escapeHtml(p)}</span></div>`).join("")}
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
      `<label><span>Чат</span><select id="member-rel-chat">${options}</select></label>
       <div id="member-rel-status"></div>`
    );
    $("#member-rel-chat").addEventListener("change", loadMemberRelStatus);
    loadMemberRelStatus();
  } catch (err) {
    box.innerHTML = relBlock(`<div class="empty">${icon("alert")}<span>${escapeHtml(err.message)}</span></div>`);
  }
}

function memberCurrentChat() {
  return Number($("#member-rel-chat").value);
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
      <div class="row"><input type="text" id="member-nick" maxlength="32" value="${escapeHtml(info.nickname || "")}" placeholder="Без ника">
        <button class="ghost small" id="member-nick-save">${icon("check")}Сохранить</button></div></label></div>`;
    out += `<div class="member-target-list" style="margin-bottom: var(--gap-2)">
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
            <label class="check quiet-toggle" style="margin-left:auto">
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
    const genders = [["м", "♂ М"], ["ж", "♀ Ж"], ["др", "⚧ Др"]];
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
    memberModal(`${icon("chart")}Топ по сообщениям`, rows + (d.my_rank ? `<div class="muted" style="margin-top:8px">Ваше место: #${d.my_rank}</div>` : ""));
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
        const data = await api(`/api/member/chat-members?chat_id=${memberCurrentChat()}&q=${encodeURIComponent(q)}`);
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

$("#keys-help").addEventListener("click", () => toggleKeysHelp());

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if ($("#app").classList.contains("hidden")) return;  // на экране входа не мешаем

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
  $("#auth").classList.add("hidden");
  $("#member").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#who").textContent = `${me.username} · ${me.role === "owner" ? "владелец" : "администратор"}`;
  if (me.role === "owner") $$(".owner-only").forEach((el) => el.classList.remove("hidden"));
  renderTgLink();
  loadRoles();
  loadChats();
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

$("#tg-link-save").addEventListener("click", async () => {
  const code = $("#tg-link-code").value.trim();
  if (!code) return;
  try {
    await api("/api/link-telegram", { method: "POST", body: { code } });
    $("#tg-link-code").value = "";
    await refreshMe();
    renderTgLink();
    say("#global-msg", "Telegram привязан");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
});

$("#tg-link-open-member").addEventListener("click", () => {
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

$$(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${view}`).classList.remove("hidden");
    if (view === "settings") loadSettings();
    if (view === "users") loadUsers();
    if (view === "stats") { loadStatsData(); loadLogs(); }
    if (view === "stock") loadStockData();
    if (view === "tgadmins") loadTgAdmins();
    if (view === "chatroles") loadChatRoles();
    if (view === "moderation") { loadRestRequests(); loadWordFilter(); }
    if (view === "complaints") loadComplaintTargets();
    if (view === "actions") { loadActions(); loadGestures(); loadProposeActions(); }
    if (view === "cmdtree") { loadCommandTree(); loadRewardLevels(); }
    // Лента живёт только на своей вкладке: иначе SSE-соединение и опрос БД
    // продолжались бы всё время, пока панель просто открыта.
    if (view === "send") loadFeed(); else closeFeedStream();
  });
});

// Вкладки экрана участника — привязываем один раз (кнопки статичны в разметке).
$$(".member-tab").forEach((btn) =>
  btn.addEventListener("click", () => switchMemberTab(btn.dataset.mtab)));

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
        <div class="cmdtree-ctl">${ctl}${reset}</div></div>`;
    }
    out += `</details>`;
  }
  body.innerHTML = out || `<div class="empty">${icon("empty")}<span>Ничего не найдено</span></div>`;
  if (canEdit) {
    $$(".cmd-level").forEach((sel) => sel.addEventListener("change", () => cmdSetLevel(sel.dataset.key, Number(sel.value))));
    $$(".cmd-reset").forEach((btn) => btn.addEventListener("click", () => cmdSetLevel(btn.dataset.key, null)));
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

async function loadChats() {
  try {
    const data = await api("/api/chats");
    chats = data.chats;
    const options = chats
      .map((c) => `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`)
      .join("");
    ["#send-chat", "#members-chat", "#mod-chat", "#stats-chat", "#stock-chat", "#tga-chat", "#chatroles-chat"].forEach((sel) => {
      $(sel).innerHTML = options || `<option value="">Чатов пока нет</option>`;
    });
    $("#chats-table").innerHTML = chats.map((c) => `
      <tr><td><div class="person">${avatar(c.title, c.chat_id)}<span>${escapeHtml(c.title)}</span></div></td>
          <td class="mono">${c.chat_id}</td>
          <td class="num">${c.members}</td></tr>`).join("")
      || empty(3, "Бот пока не видел ни одного чата");
    if (chats.length) {
      loadMembers();
      loadFeed();
    }
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

async function loadMembers() {
  const chatId = $("#members-chat").value;
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
      <tr><td><div class="person">${avatar(m.full_name, m.user_id)}<span>${escapeHtml(m.full_name)}</span></div></td>
          <td>${roleBadge(m)}</td>
          <td class="muted">${m.username ? "@" + escapeHtml(m.username) : "—"}</td>
          <td class="mono">${m.message_count ?? 0}</td>
          <td class="mono">${m.user_id}</td>
          <td style="text-align:right; white-space:nowrap">
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
        }, $("#members-chat").value);
      });
    });
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

$("#members-chat").addEventListener("change", loadMembers);
$("#members-role").addEventListener("change", loadMembers);
$("#members-q").addEventListener("input", () => {
  clearTimeout(window._memberSearch);
  window._memberSearch = setTimeout(loadMembers, 300);
});
$("#members-sort").addEventListener("change", loadMembers);

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
    <div class="mono muted" style="margin-top:6px">ID: ${info.user_id}</div>`;
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
          <input type="text" maxlength="512" placeholder="Новая фраза…" required>
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

$("#action-add").addEventListener("submit", async (e) => {
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

$("#synonym-add").addEventListener("submit", async (e) => {
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
              <input type="text" maxlength="512" placeholder="Новая фраза…" required>
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
            <input type="text" maxlength="64" placeholder="новый синоним…" required>
            <button class="ghost small" type="submit">${icon("plus")}Синоним</button>
          </form>
          <form class="row propose-settings" data-propose-settings-for="${escapeHtml(a.key)}">
            <label class="narrow"><span>Кулдаун, сек</span>
              <input type="number" min="1" max="86400" value="${a.cooldown_seconds}" data-field="cooldown_seconds" required>
            </label>
            <label class="narrow"><span>Таймаут, сек</span>
              <input type="number" min="1" max="86400" value="${a.timeout_seconds}" data-field="timeout_seconds" required>
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

$("#propose-action-add").addEventListener("submit", async (e) => {
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

$("#propose-synonym-add").addEventListener("submit", async (e) => {
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

const GESTURE_PAIR_LABELS = { mf: "♂ + ♀", mm: "♂ + ♂", ff: "♀ + ♀" };

$("#gesture-add").addEventListener("submit", async (e) => {
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
          <div class="row"><input type="text" maxlength="255" value="${escapeHtml(g.reply_template || "")}" data-greply-input="${k}" placeholder="{target} подмигивает {actor} в ответ.">
            <button class="ghost small" data-greply="${k}">${icon("check")}Сохранить</button></div></label>
        <div class="gsub"><b>Слова-триггеры</b> <span class="muted">(что писать в чате: «отн подмигнуть»)</span>
          <div class="alias-list">${aliases || `<span class="muted">нет</span>`}</div>
          <form class="row alias-add" data-gkey="${k}"><input type="text" maxlength="64" placeholder="подмигнуть" required>
            <button class="ghost small" type="submit">${icon("plus")}Слово</button></form></div>
        <div class="gsub"><b>Фразы</b> <span class="muted">(<code>{actor}</code>/<code>{target}</code>)</span>
          <div class="action-phrases">${phrases || `<span class="muted">нет</span>`}</div>
          <form class="row gphrase-add" data-gkey="${k}"><input type="text" maxlength="512" placeholder="{actor} подмигивает {target}." required>
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
          <div style="flex:1; min-width:0">
            <div class="role-name">${escapeHtml(c.reason || "без текста")}</div>
            <div class="role-info" style="justify-content:flex-start; margin-top:4px">
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

$("#word-filter-add").addEventListener("submit", async (e) => {
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
  const chatId = $("#mod-chat").value;
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

$("#mod-chat").addEventListener("change", loadRestRequests);

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
  const chatId = () => Number($("#chatroles-chat").value);

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
          body: { chat_id: Number($("#chatroles-chat").value), approve },
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
  const chatId = $("#chatroles-chat").value;
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

$("#chatrole-add").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#chatrole-name").value.trim();
  if (!name) return;
  const submit = $("#chatrole-add button[type=submit]");
  submit.disabled = true;
  try {
    await api("/api/chat-roles", {
      method: "POST",
      body: {
        chat_id: Number($("#chatroles-chat").value),
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

$("#chatroles-chat").addEventListener("change", loadChatRoles);
$("#chatroles-category").addEventListener("change", loadChatRoles);
$("#chatroles-q").addEventListener("input", () => {
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
  const chatId = Number($("#send-chat").value);
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

$("#send-chat").addEventListener("change", loadFeed);

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
$("#send-text").addEventListener("input", () => {
  const len = $("#send-text").value.length;
  const counter = $("#send-counter");
  counter.textContent = `${len} / 4096`;
  counter.style.color = len > 4096 ? "var(--danger)" : "";
});

// Ctrl+Enter (на маке — ⌘+Enter) отправляет. Жмём саму кнопку, а не дублируем
// отправку: иначе горячая клавиша прошла бы мимо блокировки кнопки и с зажатым
// Ctrl+Enter можно было бы наплодить дублей.
$("#send-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (!$("#send-btn").disabled) $("#send-btn").click();
  }
});

$("#send-btn").addEventListener("click", async () => {
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
        chat_id: Number($("#send-chat").value),
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

$("#send-photo-btn").addEventListener("click", async () => {
  const file = $("#send-photo").files[0];
  if (!file) return say("#global-msg", "Выберите файл", "err");
  const form = new FormData();
  form.append("chat_id", $("#send-chat").value);
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
    const params = new URLSearchParams({ chat_id: $("#mod-chat").value, user_id: modPicked.user_id });
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

$("#mod-warn").addEventListener("click", async () => {
  if (!modPicked) { say("#global-msg", "Сначала выберите участника", "err"); return; }
  const days = Number($("#mod-warn-days").value) || null;
  try {
    const res = await api("/api/warns", {
      method: "POST",
      body: {
        chat_id: Number($("#mod-chat").value),
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

$("#mod-unwarn").addEventListener("click", async () => {
  if (!modPicked) return;
  try {
    const res = await api("/api/warns/remove", {
      method: "POST",
      body: { chat_id: Number($("#mod-chat").value), user_id: modPicked.user_id },
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

  if (chatId) $("#mod-chat").value = chatId;
  // переключаемся на вкладку модерации, если пришли из списка участников
  closeFeedStream();   // вкладку «Написать» покидаем — лента больше не нужна
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "moderation"));
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-moderation").classList.remove("hidden");

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
    const params = new URLSearchParams({ chat_id: $("#mod-chat").value, q, role });
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

$("#mod-search").addEventListener("input", () => {
  clearTimeout(window._modSearch);
  window._modSearch = setTimeout(suggestMembers, 250);
});
$("#mod-search").addEventListener("focus", suggestMembers);
$("#mod-role").addEventListener("change", suggestMembers);
$("#mod-chat").addEventListener("change", () => {
  // сменили чат — прежний выбор к нему уже не относится
  modPicked = null;
  $("#mod-user").value = "";
  renderPicked();
  $("#mod-suggest").classList.add("hidden");
});
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
          chat_id: Number($("#mod-chat").value),
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
  const chatId = $("#tga-chat").value;
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
          <input type="text" maxlength="16" data-title value="${escapeHtml(admin.custom_title || "")}">
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
    const params = new URLSearchParams({ chat_id: $("#tga-chat").value, q });
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

$("#tga-chat").addEventListener("change", () => {
  tgPicked = null;          // прежний выбор к новому чату не относится
  renderTgPicked();
  loadTgAdmins();
});
$("#tga-search").addEventListener("input", () => {
  clearTimeout(window._tgSearch);
  window._tgSearch = setTimeout(suggestTgCandidates, 250);
});

$("#tga-promote").addEventListener("click", async () => {
  if (!tgPicked) return say("#global-msg", "Сначала выберите, кого назначаем", "err");
  const rights = readRights("#tga-rights", "newright");
  try {
    await api("/api/tg_admins/promote", {
      method: "POST",
      body: {
        chat_id: Number($("#tga-chat").value),
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
    <div class="bar-axis"><span>${escapeHtml(first.axis)}</span><span style="text-align:right">${escapeHtml(last.axis)}</span></div>
    <div class="stat-grid" style="margin-top:var(--gap-3)">
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
  return `<p class="msg ${verdict === "ok" ? "ok" : "err"}" style="margin-top:8px">
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
  const chatId = $("#stock-chat").value;
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
  const chatId = $("#stock-chat").value;
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
$("#stock-load").addEventListener("click", loadStockData);
$("#stock-chat").addEventListener("change", loadStockData);
$("#stock-period").addEventListener("change", loadStockData);
$("#stock-save").addEventListener("click", saveStockSettings);
["#stock-min", "#stock-max", "#stock-div"].forEach((sel) => {
  $(sel).addEventListener("input", refreshStockForecast);
});

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
  const chatId = $("#stats-chat").value;
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

$("#stats-load").addEventListener("click", loadStatsData);

async function loadLogs() {
  try {
    const data = await api("/api/logs?limit=50");
    $("#logs-table").innerHTML = data.logs.map((l) => `
      <tr><td class="muted" style="white-space:nowrap">${fmtDate(l.created_at)}</td>
          <td><span class="badge">${escapeHtml(l.event_type)}</span></td>
          <td class="muted">${escapeHtml(l.details || "")}</td></tr>`).join("")
      || empty(3, "Журнал пока пуст");
  } catch (err) { /* журнал не критичен */ }
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
              value="${escapeHtml(cur)}" placeholder="мск / GMT+3 / Europe/Moscow">
          </label>
          ${canEdit ? `<div class="grow-0"><button class="ghost" data-save="${key}">${icon("check")}Сохранить</button></div>` : ""}
        </div>
        ${cur && !known ? `<div class="muted" style="font-size:12px">Своё значение: <code>${escapeHtml(cur)}</code></div>` : ""}
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

async function loadSettings() {
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
        <td><div class="person">${avatar(u.username, u.id)}<span>${escapeHtml(u.username)}${
          u.username === me.username ? ' <em class="tip">— это вы</em>' : ""}</span></div></td>
        <td><span class="badge ${u.role === "owner" ? "owner" : ""}">${
          u.role === "owner" ? icon("key") + "владелец" : "администратор"}</span></td>
        <td class="muted" style="white-space:nowrap">${fmtDate(u.last_login_at)}</td>
        <td style="text-align:right">${u.username === me.username ? "" :
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
      <tr><td class="muted" style="white-space:nowrap">${fmtDate(l.created_at)}</td>
          <td>${escapeHtml(l.username)}</td>
          <td class="mono">${escapeHtml(l.ip || "—")}</td>
          <td><span class="badge ${l.success ? "ok" : "err"}">${
            icon(l.success ? "check" : "alert")}${l.success ? "успех" : "отказ"}</span></td></tr>`).join("")
      || empty(4, "Входов пока не было");
  } catch (err) {
    say("#global-msg", err.message, "err");
  }
}

$("#nu-create").addEventListener("click", async () => {
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

$("#pw-save").addEventListener("click", async () => {
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

boot();
