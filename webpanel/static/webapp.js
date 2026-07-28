"use strict";
// Мини-приложение Telegram: тот же бот, но экраном вместо команд.
//
// Вход не спрашиваем вообще. Telegram сам передаёт подписанную initData —
// строку, где уже лежит, кто открыл приложение; подпись считается на секрете
// бота, поэтому подделать её нельзя (проверка — webapp_auth.py на сервере).
// Мы просто прикладываем эту строку заголовком к каждому запросу.

const tg = window.Telegram && window.Telegram.WebApp;

// Если SDK не загрузился (например, страницу открыли обычным браузером),
// пробуем достать initData из адреса — Telegram кладёт её и туда.
function initData() {
  if (tg && tg.initData) return tg.initData;
  const m = /[#&]tgWebAppData=([^&]*)/.exec(location.hash || "");
  return m ? decodeURIComponent(m[1]) : "";
}

const $ = (sel) => document.querySelector(sel);

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let chats = [];
let currentChat = null;
let currentTab = "me";

// --- сеть ------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const headers = { "X-Telegram-Init-Data": initData() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* пустой ответ — не беда */ }
  if (!res.ok) throw new Error((data && data.detail) || `Ошибка ${res.status}`);
  return data;
}

let toastTimer = null;
function toast(text, kind) {
  const el = $("#toast");
  el.textContent = text;
  el.className = "toast" + (kind === "err" ? " err" : "");
  el.hidden = false;
  if (tg && tg.HapticFeedback) {
    tg.HapticFeedback.notificationOccurred(kind === "err" ? "error" : "success");
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

// --- разметка --------------------------------------------------------------

const row = (k, v) => `<div class="row"><span class="k">${escapeHtml(k)}</span><span class="v">${v}</span></div>`;
const card = (title, inner) =>
  `<div class="card">${title ? `<h3>${escapeHtml(title)}</h3>` : ""}${inner}</div>`;
const empty = (text) => `<div class="card"><div class="empty">${escapeHtml(text)}</div></div>`;

function render(html) { $("#view").innerHTML = html; }
function loading() { render('<div class="skeleton"></div>'); }

// --- вкладка «Профиль» -----------------------------------------------------

async function tabMe() {
  loading();
  const [info, top] = await Promise.all([
    api(`/api/member/info?chat_id=${currentChat}`),
    api(`/api/member/top?chat_id=${currentChat}`).catch(() => null),
  ]);

  let html = `<div class="big">
    <div><b>${info.messages}</b><span>сообщений</span></div>
    <div><b>${info.rank ? "#" + info.rank : "—"}</b><span>место</span></div>
    <div><b>${info.reputation ?? 0}</b><span>репутация</span></div>
  </div>`;

  html += card("Активность", [
    row("Сегодня", info.today ?? 0),
    row("За неделю", info.week ?? 0),
    row("За месяц", info.month ?? 0),
  ].join(""));

  const about = [];
  if (info.nickname) about.push(row("Ник", escapeHtml(info.nickname)));
  if (info.role) about.push(row("Роль", escapeHtml(info.role)));
  about.push(row("Награды", info.rewards ?? 0));
  about.push(row("Предупреждения", info.warns ?? 0));
  html += card("О вас", about.join(""));

  if (top && top.top && top.top.length) {
    const rows = top.top.slice(0, 10).map((t, i) =>
      row(`${i + 1}. ${t.name}`, `${t.messages}`)).join("");
    html += card("Топ чата", rows);
  }
  render(html);
}

// --- вкладка «Пара» --------------------------------------------------------

async function tabLove() {
  loading();
  const data = await api(`/api/member/relationship?chat_id=${currentChat}`);
  let html = "";

  if (data.marriage) {
    html += card("Брак 💍", [
      row("Партнёр", escapeHtml(data.marriage.partner_name)),
      row("В браке с", escapeHtml((data.marriage.married_at || "—").slice(0, 10))),
    ].join("") + `<button class="act ghost" id="divorce">Развестись</button>`);
  } else if (data.can_restore_marriage) {
    html += card("Брак 💍",
      `<div class="empty">Вы недавно развелись. Вернуть брак можно в течение 72 часов.</div>
       <button class="act" id="restore">Вернуть брак</button>`);
  } else {
    html += empty("Вы пока ни с кем не в браке. Предложение делается в чате словом «Брак».");
  }

  if (data.relationship) {
    const r = data.relationship;
    html += card("Отношения 💞", [
      row("Партнёр", escapeHtml(r.partner_name)),
      row("Уровень", escapeHtml(r.level_name || `ур. ${r.level}`)),
      row("Искры", r.sparks),
    ].join("") +
      `<button class="act" id="bonus" ${r.bonus_available ? "" : "disabled"}>
         ${r.bonus_available ? "Забрать бонус искр" : `Бонус через ${escapeHtml(r.bonus_wait || "")}`}
       </button>`);

    html += `<div id="actions"><div class="skeleton"></div></div>`;
  }

  render(html);

  const divorce = $("#divorce");
  if (divorce) divorce.onclick = () => confirmAnd("Развестись?", async () => {
    await api("/api/member/divorce", { method: "POST", body: { chat_id: currentChat } });
    toast("Брак расторгнут");
    tabLove();
  });

  const restore = $("#restore");
  if (restore) restore.onclick = async () => {
    try {
      await api("/api/member/restore", { method: "POST", body: { chat_id: currentChat, kind: "marriage" } });
      toast("Брак возвращён 💞");
      tabLove();
    } catch (e) { toast(e.message, "err"); }
  };

  const bonus = $("#bonus");
  if (bonus && !bonus.disabled) bonus.onclick = async () => {
    bonus.disabled = true;
    try {
      const d = await api("/api/member/farm-bonus", { method: "POST", body: { chat_id: currentChat } });
      toast(`+${d.amount} искр`);
      tabLove();
    } catch (e) { toast(e.message, "err"); bonus.disabled = false; }
  };

  if (data.relationship) loadActions();
}

async function loadActions() {
  const box = $("#actions");
  if (!box) return;
  let data;
  try {
    data = await api(`/api/member/rp-actions?chat_id=${currentChat}`);
  } catch (_) { box.innerHTML = ""; return; }

  const buttons = data.actions.map((a) => {
    const note = a.locked ? `нужен ур. ${a.level}`
      : a.on_cooldown ? `через ${a.wait}`
      : `+${a.reward} искр`;
    return `<button data-action="${escapeHtml(a.key)}" ${a.available ? "" : "disabled"}>
      ${escapeHtml(a.name)}<small>${escapeHtml(note)}</small></button>`;
  }).join("");

  box.innerHTML = card("Действия с партнёром", `<div class="grid">${buttons}</div>`);
  box.querySelectorAll("[data-action]").forEach((btn) => {
    if (btn.disabled) return;
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const d = await api("/api/member/rp-action", {
          method: "POST", body: { chat_id: currentChat, key: btn.dataset.action },
        });
        toast(`+${d.amount} искр · баланс ${d.balance}`);
        loadActions();
      } catch (e) { toast(e.message, "err"); btn.disabled = false; }
    };
  });
}

// --- вкладка «Семья» -------------------------------------------------------

async function tabFamily() {
  loading();
  const d = await api(`/api/member/family?chat_id=${currentChat}`);
  if (!d.pair) return render(empty("Семья появляется у пары. Начните отношения в чате: «отн запрос»."));

  let html = card("Казна пары", row("Искры", d.sparks));

  if (d.house) {
    const rooms = d.house.rooms.length
      ? d.house.rooms.map((r) => `${escapeHtml(r.key)} ур.${r.level}`).join(", ")
      : "комнат пока нет";
    html += card(`Дом · ${d.house.name}`, [
      row("Статус", escapeHtml(d.house.status)),
      row("Комнаты", escapeHtml(rooms)),
    ].join(""));
  }

  if (d.pets.length) {
    html += card("Питомцы", d.pets.map((p) =>
      row(`${p.active ? "⭐ " : ""}${p.name} · ${p.species}`,
          `ур.${p.level} · ❤️${p.hp} · 🙂${p.mood}`)).join(""));
  }

  if (d.children.length) {
    html += card("Дети", d.children.map((c) =>
      row(`${c.name}${c.section ? " · " + escapeHtml(c.section) : ""}`,
          `ур.${c.level} · 💪${c.health} · 🧠${c.intellect}`)).join(""));
  }

  if (!d.house && !d.pets.length && !d.children.length) {
    html += empty("Дома, питомцев и детей ещё нет — всё это заводится командами «дом», «отн питомец», «отн родить».");
  }
  render(html);
}

// --- вкладка «Клан» --------------------------------------------------------

async function tabClan() {
  loading();
  const d = await api(`/api/member/clans?chat_id=${currentChat}`);
  let html = "";

  if (d.my) {
    const c = d.my;
    html += card(c.name, [
      row("Ваша роль", escapeHtml({ leader: "лидер", deputy: "зам", member: "участник" }[c.role] || c.role)),
      row("Казна", c.coins),
      row("Очки войн", c.war_points),
      row("Участников", c.members.length),
    ].join("") + `<button class="act ghost" id="leave">Выйти из клана</button>`);
    html += card("Состав", c.members.map((m) =>
      row(m.name, escapeHtml({ leader: "лидер", deputy: "зам", member: "" }[m.role] || ""))).join(""));
  } else {
    html += empty("Вы не в клане. Ниже — кланы чата, можно вступить.");
  }

  if (d.clans.length) {
    html += card("Кланы чата", d.clans.map((c) => {
      const join = d.my ? "" :
        `<button class="act" data-join="${c.id}">Вступить</button>`;
      return row(`${escapeHtml(c.name)}`, `${c.members_count} чел. · ${c.war_points} оч.`) + join;
    }).join(""));
  }
  render(html);

  const leave = $("#leave");
  if (leave) leave.onclick = () => confirmAnd("Выйти из клана?", async () => {
    await api("/api/member/clan/leave", { method: "POST", body: { chat_id: currentChat } });
    toast("Вы вышли из клана");
    tabClan();
  });

  document.querySelectorAll("[data-join]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api("/api/member/clan/join", {
          method: "POST", body: { chat_id: currentChat, clan_id: Number(btn.dataset.join) },
        });
        toast("Добро пожаловать в клан!");
        tabClan();
      } catch (e) { toast(e.message, "err"); btn.disabled = false; }
    };
  });
}

// --- вкладка «Питомцы» -------------------------------------------------

// Три действия из тех, что умеет game_actions: кабинет — не замена команд
// боту, а быстрый доступ к паре самых частых («что не входит» в спеке
// подпроекта — инвентарь, торговля и т.п. остаются в чате).
//
// Кнопка рисуется на КАЖДОГО питомца и уносит его ключ. Без ключа действие
// уходит «кому-нибудь», и всякий, у кого питомцев больше одного, получал в
// ответ совет набрать команду в чате — то есть кнопки были мертвы у всех,
// кто собирает «Зоопарк».
const PET_ACTIONS = [
  { action: "feed", label: "Покормить" },
  { action: "pet", label: "Погладить" },
  { action: "walk", label: "Гулять" },
];

// Те же действия сразу на всех: при пяти питомцах жать по три кнопки на
// каждого — работа, а не игра. У ласки «всем» слово обязательно (сервер без
// него отвечает отказом): одним действием гладят, обнимают и целуют.
const PET_ALL_ACTIONS = [
  { action: "feed_all", label: "Покормить всех" },
  { action: "care_all", label: "Погладить всех", verb: "pet" },
  { action: "walk_all", label: "Выгулять всех" },
];

// key === null — кнопка «всем»: у массовых действий питомца не выбирают.
function petButtons(actions, key) {
  return actions.map((a) =>
    `<button data-pet-action="${a.action}"`
    + (key === null ? "" : ` data-pet-key="${escapeHtml(key)}"`)
    + (a.verb ? ` data-pet-verb="${a.verb}"` : "")
    + `>${a.label}</button>`).join("");
}

async function loadGamePets() {
  const list = $("#gamepets-list");
  const msg = $("#gamepets-msg");
  msg.innerHTML = "";
  list.innerHTML = '<div class="skeleton"></div>';
  try {
    // data.text уже содержит телеграмную HTML-разметку от сервера — вставляем
    // как есть (как и announcements выше), а не через escapeHtml. А вот
    // data.pets приходит обычными данными, и их экранируем сами.
    const data = await api(`/api/member/game/pets?chat_id=${currentChat}`);
    const pets = data.pets || [];
    let html = card("Питомцы", data.text);
    for (const pet of pets) {
      html += `<div class="pet-head">${escapeHtml(pet.emoji)} ${escapeHtml(pet.name)}</div>`
            + `<div class="grid">${petButtons(PET_ACTIONS, pet.key)}</div>`;
    }
    // С одним питомцем «всем» — те же три кнопки второй раз, только с другой
    // подписью: показываем, только когда их правда несколько.
    if (pets.length > 1) {
      html += `<div class="pet-head">Всем сразу</div>`
            + `<div class="grid">${petButtons(PET_ALL_ACTIONS, null)}</div>`;
    }
    list.innerHTML = html;
    list.querySelectorAll("[data-pet-action]").forEach((btn) => {
      btn.onclick = () => runGamePetAction(btn);
    });
  } catch (e) {
    list.innerHTML = empty(e.message);
  }
}

async function runGamePetAction(btn) {
  btn.disabled = true;
  const body = { chat_id: currentChat };
  // Ключ и слово ласки кладём только когда они есть: у массовых действий
  // питомца не выбирают, а лишний verb сервер у них не читает.
  if (btn.dataset.petKey) body.key = btn.dataset.petKey;
  if (btn.dataset.petVerb) body.verb = btn.dataset.petVerb;
  try {
    const d = await api(`/api/member/game/pets/${btn.dataset.petAction}`, {
      method: "POST", body,
    });
    // Отказ по правилам игры (ok:false — «не хватило корма» и т.п.) это не
    // сбой, а законный исход: текст показываем тем же местом, что и успех,
    // без отдельной ветки на ok. Список при этом НЕ перезапрашиваем: десять
    // нажатий «покормить» подряд — и десять миганий экрана раздражают
    // сильнее, чем на миг устаревшая цифра голода.
    $("#gamepets-msg").innerHTML = card("", d.text);
  } catch (e) {
    toast(e.message, "err");
  }
  btn.disabled = false;
}

// Подтверждение: у Telegram оно нативное, в браузере — обычный confirm.
function confirmAnd(question, action) {
  const run = async () => {
    try { await action(); } catch (e) { toast(e.message, "err"); }
  };
  if (tg && tg.showConfirm) tg.showConfirm(question, (ok) => { if (ok) run(); });
  else if (confirm(question)) run();
}

// --- запуск ----------------------------------------------------------------

const TABS = { me: tabMe, love: tabLove, family: tabFamily, clan: tabClan, gamepets: loadGamePets };

async function showTab(name) {
  currentTab = name;
  // «Питомцы» помечен data-mtab, а не data-tab (см. webapp.html) — у него
  // свой экран #mtab-gamepets, а не общий #view, поэтому оба атрибута нужно
  // проверять при подсветке активной кнопки.
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", (b.dataset.tab || b.dataset.mtab) === name));
  $("#view").hidden = name === "gamepets";
  $("#mtab-gamepets").hidden = name !== "gamepets";
  try {
    await TABS[name]();
  } catch (e) {
    render(empty(e.message));
  }
}

async function start() {
  if (tg) { tg.ready(); tg.expand(); }

  // Имя показываем СРАЗУ, из подписанных данных, до любых запросов. Раньше
  // шапка обновлялась только после успешного ответа сервера — и при отказе
  // в ней навсегда оставалось «загружаем…», хотя ошибка уже была видна ниже.
  const tgUser = (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) || null;
  const name = tgUser
    ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(" ")
    : "Вы";
  $("#who-name").textContent = name;
  $("#avatar").textContent = (name.trim()[0] || "·").toUpperCase();

  if (!initData()) {
    $("#who-chat").textContent = "";
    render(empty("Откройте это приложение кнопкой в Telegram — там бот сам вас узнает."));
    return;
  }

  let data;
  try {
    data = await api("/api/member/chats");
  } catch (err) {
    // Не пустило. «Нужен вход» само по себе ничего не объясняет, поэтому
    // спрашиваем у сервера, что именно не сошлось, и показываем это.
    $("#who-chat").textContent = "";
    let reason = "";
    try {
      const check = await api("/api/webapp-check");
      if (!check.bot_token_configured) {
        reason = "у панели не задан BOT_TOKEN — подпись проверять нечем";
      } else if (!check.ok) {
        reason = check.reason || "";
      } else {
        // Подпись верна, а внутрь всё равно не пустили — значит дело не в
        // Telegram, а в аккаунте на стороне панели. Без этой ветки на экране
        // оставалось безадресное «Нужен вход», и понять было нечего.
        reason = "Telegram вас подтвердил, но панель не пустила — "
               + "похоже на проблему с аккаунтом. Причина записана в лог панели.";
      }
    } catch (_) {
      // Даже диагностика недоступна — чаще всего панель просто не перезапущена
      // после обновления, и новых адресов на ней ещё нет.
      reason = "панель не отвечает на проверку — возможно, её не перезапустили после обновления";
    }
    render(
      `<div class="card"><div class="empty">
         <b>Не удалось войти</b><br>${escapeHtml(reason || err.message)}
       </div></div>` +
      `<button class="act" id="retry">Попробовать снова</button>`
    );
    const retry = $("#retry");
    if (retry) retry.onclick = () => { render('<div class="skeleton"></div>'); start(); };
    return;
  }

  chats = data.chats || [];
  if (!chats.length) {
    $("#who-chat").textContent = "нет общих чатов";
    render(empty("Бот пока не видел вас ни в одном чате. Напишите что-нибудь в группе — и возвращайтесь."));
    return;
  }

  const select = $("#chat-select");
  select.innerHTML = chats.map((c) =>
    `<option value="${c.chat_id}">${escapeHtml(c.title)}</option>`).join("");
  select.hidden = chats.length < 2;
  currentChat = chats[0].chat_id;
  $("#who-chat").textContent = chats.length > 1 ? "выберите чат" : chats[0].title;
  select.onchange = () => { currentChat = Number(select.value); showTab(currentTab); };

  $("#tabs").hidden = false;
  document.querySelectorAll(".tab").forEach((b) => {
    b.onclick = () => showTab(b.dataset.tab || b.dataset.mtab);
  });

  showTab("me");
}

start();
