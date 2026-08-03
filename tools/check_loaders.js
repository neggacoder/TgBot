// Прогон ЗАГРУЗЧИКОВ вкладок кабинета.
//
// Зачем. Экраны падали на `options is not defined`: правка убрала вычисление
// переменной, а ссылка на неё осталась в трёх шаблонах. Прошлые проверки
// дёргали только ОТРИСОВКУ (renderFarm и родню), а до неё дело не доходило —
// падал загрузчик. Здесь вызывается именно он, с заглушками вместо браузера и
// сервера.
//
// Запуск: node tools/check_loaders.js   (из корня проекта)
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(
  path.join(__dirname, "..", "webpanel", "static", "app.js"), "utf8");

// Берём весь кабинет: загрузчики ссылаются друг на друга и на общий каркас.
const кусок = src.slice(src.indexOf("// ===== Вкладка «Ферма»"));

// Идентификаторы, которые есть в самой странице: их браузер найдёт всегда.
const РАЗМЕТКА = fs.readFileSync(
  path.join(__dirname, "..", "webpanel", "static", "index.html"), "utf8");
const ЕСТЬ_В_СТРАНИЦЕ = new Set(
  [...РАЗМЕТКА.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]));

const узлы = {};

// Главная тонкость проверки: браузер отдаёт NULL, если узла нет. Заглушка,
// которая отдаёт объект на любой селектор, пропустит ровно ту поломку, ради
// которой всё это писалось, — обращение к удалённому элементу.
const существует = (сел) => {
  if (!сел.startsWith("#")) return true;         // селекторы по классу не проверяем
  const имя = сел.slice(1);
  if (ЕСТЬ_В_СТРАНИЦЕ.has(имя)) return true;
  const нарисовано = Object.values(узлы).map((у) => у.innerHTML).join("");
  return нарисовано.includes(`id="${имя}"`);
};

// Значения полей, по которым экран ВЕТВИТСЯ. По умолчанию заглушка отдаёт
// "-100" — оно сходит за номер чата и годится почти всюду. Но выбор периода на
// бирже так не работает: подпись графика собиралась из словаря по этому
// значению и выходила «изменение курса undefined».
const ЗНАЧЕНИЯ = { "#stock-period": "30d" };

const создать = (сел) => (узлы[сел] ||= {
  innerHTML: "", value: ЗНАЧЕНИЯ[сел] || "-100", dataset: {}, textContent: "", disabled: false,
  offsetWidth: 320, parentElement: { offsetWidth: 320 },
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  style: { setProperty() {} }, addEventListener() {}, removeEventListener() {},
  remove() {}, querySelector: () => узел("любой"), querySelectorAll: () => [],
  appendChild() {}, insertAdjacentHTML() {}, focus() {}, scrollIntoView() {},
  // Свойства, которые экраны читают ДО отрисовки: список детей, набор опций,
  // состояние галочки. Без них падает не код, а бедность заглушки.
  children: [], options: [], selectedIndex: 0, checked: false, files: [],
  closest: () => null,
});
const узел = (сел) => (существует(сел) ? создать(сел) : null);
global.$ = узел;
global.$$ = () => [];
global.escapeHtml = (s) => String(s);
global.icon = (n) => `<svg><use href="#ic-${n}"/></svg>`;
global.say = () => {};
global.PALETTE = ["#111"];
global.setInterval = () => 0;
global.clearInterval = () => {};
global.requestAnimationFrame = (fn) => fn();
global.prompt = () => null;
global.confirm = () => false;
global.document = {
  createElement: () => узел("новый"), body: { appendChild() {} },
  documentElement: { setAttribute() {}, removeAttribute() {}, dataset: {},
                     classList: { add() {}, remove() {}, toggle() {} } },
  addEventListener() {}, removeEventListener() {},
  // Через него ходит $ из самого app.js — значит и он обязан отдавать null
  // на отсутствующий узел, иначе проверка снова ничего не поймает.
  querySelector: (сел) => узел(сел), querySelectorAll: () => [],
  cookie: "",
};
global.window = { addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.location = { href: "", search: "", hash: "" };
global.navigator = { userAgent: "проверка" };
global.URLSearchParams = class {
  get() { return null; }
  set() {}
  append() {}
  toString() { return ""; }
};
// Лента событий держит открытое соединение; в прогоне её просто нет.
global.EventSource = class {
  constructor() { this.close = () => {}; }
  addEventListener() {}
};

// Сервер отвечает пустыми, но правдоподобными данными: задача прогона —
// поймать обращение к несуществующей переменной, а не проверить содержимое.
const ответы = {
  farm: { now: new Date().toISOString(), coins: 0, weather: { emoji: "☀", name: "Ясно", yield_percent: 0, grow_percent: 0, pest_percent: 0 }, plots: [], plot_total: 0, plot_free: 0, plot_sources: {}, plot_next_price: null, plot_room: 0, crops: [], barn: [], reds: [],
    // Аура и пугало заполнены намеренно: с пустыми экран не рисует строку
    // бонусов вовсе, и проверка не увидела бы, что она экранирована.
    aura: { speed: 17, harvest: 17, truffle: 17 }, pests_off: true },
  casino: { balance: 0, coins: 0, bonus_ready: false, bonus_amount: 1000, max_bet: 100, games_played: 0, event_multiplier: 1, colors: [], games: [], reds: [], can_share: false },
  business: { now: new Date().toISOString(), coins: 0, mine: [], pending_total: 0, tax_now: 0, catalog: [], gear: [], max_level: 3 },
  fishing: { now: new Date().toISOString(), net: [], capacity: 20, net_value: 0, multiplier: 1, next_at: null, cooldown_seconds: 0, best_weight: 0, total_catches: 0, species: [] },
  work: { now: new Date().toISOString(), profession: null, catalog: [], upgrades: {}, upgrade_catalog: [] },
  shop: { now: new Date().toISOString(), coins: 0, items: [], black_market: [], inventory: [], sell_percent: 80, max_qty: 100 },
  pets: { ok: true, text: "", pets: [], cards: [], food: 0 },
  // Лутбоксы: коробки на руках заданы, иначе кнопка «Открыть» везде выключена
  // и половина разметки осталась бы непроверенной.
  lootbox: { coins: 30000, max_per_command: 20, kinds: [
    { key: "common", name: "Обычный", emoji: "🟢", price: 500, rare_chance: 5, owned: 3 },
    { key: "rare", name: "Редкий", emoji: "🟣", price: 5000, rare_chance: 35, owned: 0 },
  ] },
  // Рынок: и чужой товар, и свой — иначе половина разметки (покупка, снятие)
  // осталась бы непроверенной.
  market: { coins: 50000, commission_percent: 10, max_price: 50000, max_goods: 3,
            max_qty: 100, name_max: 48, mode: "manual",
            mode_label: "вручную", accepts_requests: true, auto_accept: false,
            goods: [{ key: "ogurcy", name: "Огурцы", price: 500, emoji: "🥒",
                      seller_id: 999, mine: false, sold: 2 }],
            mine: [{ key: "med", name: "Мёд", price: 900, status: "pending", sold: 0 }] },
  // Медвежатник: инструмента нет — так экран рисует пусто и не мешает магазину.
  steal: { has_tool: false, tool_name: "Медвежатник", tool_emoji: "🗝", tool_price: 75000,
           cooldown_hours: 10, wait_seconds: 0, curfew: false, signal_chance: 40,
           slepok_cut: 0.25, has_slepok: false },
  // Один и тот же адрес отвечает и кабинету, и админской таблице чатов —
  // поэтому в строке есть поля обеих: без members таблица рисует «undefined».
  chats: { chats: [{ chat_id: -100, title: "Рабочий", members: 0,
                     is_current: true, last_seen_at: null }] },
  // Отношения и семья описаны подробнее прочих: их экраны читают вложенные
  // поля, а плоская пустышка отдаёт на них undefined — и проверка ругалась бы
  // на бедность заглушки, а не на код.
  relationship: { status: null, partner: null, level: 0, spark: 0,
                  contraception: false, children: [], pets: [] },
  family: { status: null, partner: null, children: [], pets: [],
            level: 0, spark: 0 },
  // Карточка «моя инфа» показывает счётчики: без них в разметке появляется
  // undefined, и это ровно тот признак, по которому проверка ищет поломку.
  // Карточка «моя инфа» показывает счётчики; имена полей взяты из самой
  // карточки (info.today / week / month), а не выдуманы: выдуманные дали бы
  // undefined в разметке — тот самый признак поломки.
  // Поля карточки «моя инфа» — ровно те, что она читает (собраны из её же
  // разметки, а не выдуманы): выдуманное имя даёт undefined на экране, и это
  // тот самый признак, по которому проверка ищет поломку.
  info: { user_id: 7, name: "Тест", username: null, role: null,
          messages: 0, today: 0, week: 0, month: 0, rank: 0,
          reputation: 0, rewards: 0, warns: 0,
          first_seen: null, last_active: null },
  profile: { user_id: 7, name: "Тест", username: null, messages: 0, rank: null, activity: { day: 0, week: 0, month: 0, all: 0 }, coins: 0, stars: 0, star_progress: { have: 0, need: 5 }, title: null, achievements: 0, clan: null, fishing: { catches: 0, best_weight: 0, best_weight_text: "0 г", best_species: null }, work: { profession: null }, businesses: 0, pets: 0 },
  tops: { now: new Date().toISOString(), kinds: [], tables: {} },
  // Витрина: и полученные достижения, и оставшиеся, и коллекции — иначе
  // половина разметки (кнопка «показать оставшиеся», полосы) не рисуется.
  gallery: {
    achievements: { total: 3, earned: 1, items: [
      { code: "msg_1", emoji: "👶", title: "Первое слово", desc: "первое сообщение", earned: true },
      { code: "msg_100", emoji: "💬", title: "Разговорился", desc: "100 сообщений", earned: false },
      { code: "msg_1000", emoji: "🗣", title: "Голос чата", desc: "1000 сообщений", earned: false },
    ] },
    collections: { items: [
      { key: "zoo", name: "Зоопарк", emoji: "🐾", description: "Собрать всех питомцев",
        done: 2, total: 8, rewarded: false, title_name: "🐾 Зоопарк" },
      { key: "junk", name: "Барахольщик", emoji: "🧦", description: "Собрать весь хлам",
        done: 5, total: 5, rewarded: true, title_name: "🧦 Барахольщик" },
    ] },
  },
  // Анкета и титулы. Списки заданы непустыми: с пустыми экран рисует только
  // «своих титулов нет», и половина разметки (витрина, надетый титул) осталась
  // бы непроверенной.
  card: {
    card: { title: "Смотритель", motto: "", city: "Алматы", about: "", gender: "",
            citizen: true, visible: true,
            limits: { title: 30, motto: 100, city: 64, about: 1000 } },
    titles: { coins: 9000, active: "hero",
              for_sale: [{ key: "hero", name: "Герой", price: 5000, owned: true },
                         { key: "star", name: "Звезда", price: 12000, owned: false }],
              earned_only: [{ key: "legend", name: "Живая легенда", price: null, owned: false }],
              owned: ["hero"] },
  },
  // История из двух точек намеренно: с одной график рисует «точек мало», и
  // сама рисовалка осталась бы непроверенной.
  stock: { now: new Date().toISOString(), enabled: true, disabled_text: "выключена",
           price: 12.5, shares: 0, value: 0, invested: 0, max_invest: 10000000,
           room: 10000000, pending_dividends: 0, total_profit: 0, coins: 500,
           dividend_percent: 1.5, chart_days: 30,
           history: [{ price: 10, at: "2026-07-01T10:00:00" },
                     { price: 12.5, at: "2026-07-02T10:00:00" }] },
  // Банк без вклада и без кредита: так экран рисует формы открытия, а их
  // тут больше. Вторую половину (созревший вклад, погашение долга, отказы)
  // проверяет отдельный прогон — check_bank_screen.js: один загрузчик не
  // может нарисовать оба состояния разом.
  bank: { now: new Date().toISOString(), coins: 5000,
          deposit: null, credit: null,
          pending: false, gate_ready: true,
          terms: [{ days: 1, rate: 5 }, { days: 3, rate: 7 }, { days: 7, rate: 10 }],
          min_deposit: 1000, credit_fee_percent: 20, credit_term_days: 7,
          credit_penalty_percent: 10, blacklisted: false, auto_reject: false,
          in_the_red: false },
};

// Ответы по ТОЧНОМУ адресу — для тех, чей путь кончается так же, как у
// другого экрана.
const АДРЕСА = {
  "/api/stock": {
    points: [{ t: "2026-07-01T10:00:00", price: 10, change: null, source: "auto" },
             { t: "2026-07-02T10:00:00", price: 12.5, change: 25, source: "auto" }],
    settings: { min_change_percent: -3, max_change_percent: 3, dividend_percent: 1.5 },
  },
};

// Подменяем именно fetch, а не api(): api объявлен в самом app.js и
// перекрывает любую глобальную заглушку — экраны шли бы через настоящий
// fetch и получали пустоту, а падение выглядело бы как поломка экрана.
global.fetch = async (путь) => {
  if (process.env.TRACE) console.log("      запрос:", путь);
  // Ответ для адресов, которых нет в списке: любое поле — пустой массив.
  // У массива есть и map, и length, и filter, и toLocaleString, поэтому
  // экран, который просто перебирает список, отрисуется пустым, а не упадёт.
  // Без этого проверка ругалась бы не на код, а на бедность заглушки.
  // Пустышка ПЛОСКАЯ: любое поле — пустой массив (у него есть map, length,
  // filter, toLocaleString). Рекурсивную пробовал — она ломается там, где
  // поле вызывают как функцию, и валит приложение целиком.
  let тело = new Proxy({}, { get: (ц, к) => (к in ц ? ц[к] : []) });
  // Хвост запроса отрезаем: адрес приходит с «?chat_id=…», и сравнение с
  // концом строки не срабатывало — заглушка молча подменялась пустышкой, а
  // экран рисовал undefined там, где ждал вложенное поле.
  const адрес = путь.split("?")[0];
  // Точный адрес важнее имени. И админская таблица (/api/stock), и биржа
  // кабинета (/api/member/game/stock) кончаются одним словом, а отвечают им
  // РАЗНОЕ: совпадение по концу строки отдало бы админскому экрану ответ
  // кабинета — и падал бы он, а не биржа. Поймано ровно так.
  if (адрес in АДРЕСА) return { ok: true, status: 200, json: async () => АДРЕСА[адрес] };
  for (const [ключ, ответ] of Object.entries(ответы)) {
    if (адрес.includes(`/game/${ключ}`) || адрес.endsWith(`/${ключ}`)) {
      тело = ответ;
      break;
    }
  }
  return { ok: true, status: 200, json: async () => тело };
};

// Берём ВЕСЬ кабинет, а не только игровые экраны: поломка пришла из старых
// вкладок (отношения, семья, кланы), которых в прошлом прогоне не было.
// Берём файл ЦЕЛИКОМ. Резать нельзя ни с какого места: загрузчики опираются
// на помощников выше (relBlock, skeleton, memberSection), а игровые экраны
// дописаны ниже вызова boot(). Отключаем только сам запуск приложения — он
// лезет в сеть и в хранилище браузера, а нам нужны загрузчики вкладок.
const весь = src.replace(/\nboot\(\);\s*$/, "\n");
// Кабинет участника И админская панель: правки задели обе (стили кнопок,
// обрезка переполнения, список чатов), а падают они одинаково молча.
const ИМЕНА = [
  // кабинет участника
  "loadMemberRelationship", "loadMemberFamily", "loadMemberClans",
  "loadMemberCapabilities", "loadMemberFarm", "loadMemberCasino",
  "loadMemberBiz", "loadMemberFish", "loadMemberWork", "loadMemberShop",
  "loadMemberPets", "loadMemberProf", "loadMemberTops", "loadMemberStock",
  "loadMemberBank",
  // админская панель
  "loadRoles", "loadCommandTree", "loadRewardLevels", "loadChats",
  "loadMembers", "loadActions", "loadProposeActions", "loadGestures",
  "loadComplaintTargets", "loadComplaints", "loadWordFilter",
  "loadRestRequests", "loadChatRoles", "loadFeed", "loadWarns",
  "loadTgRights", "loadTgAdmins", "loadStockData", "loadChatEvents",
  "loadStatsData", "loadLogs", "loadSettings", "loadUsers",
  "loadChatSettings",
];
const хвост = "\n;return {" + ИМЕНА.join(",") + "};";
const загрузчики = new Function(весь + хвост)();

(async () => {
  let упало = 0;
  for (const [имя, fn] of Object.entries(загрузчики)) {
    try {
      // Узлы общие на весь прогон: не обнулив их, ошибку одного экрана
      // увидел бы следующий — и падали бы все подряд после первого.
      for (const ключ of Object.keys(узлы)) delete узлы[ключ];
      await fn();
      // Загрузчик запускает получение состояния и НЕ ждёт его — так же, как в
      // браузере. Без паузы проверка смотрела бы на «Загрузка…» и хвалила
      // экран, который потом падает при отрисовке.
      await new Promise((r) => setTimeout(r, 25));
      // Загрузчик ловит свои ошибки САМ и рисует их в блок — наружу ничего не
      // летит. Ровно так поломка и выглядела у человека: не пустой экран с
      // ошибкой в консоли, а текст «options is not defined» вместо кабинета.
      // Поэтому смотрим не на исключение, а на то, что нарисовано.
      const разметка = Object.values(узлы).map((у) => у.innerHTML).join("");
      const беда = разметка.match(
        /is not defined|is not a function|Cannot read|undefined|NaN/) ||
        // Экранированная разметка: строку с иконками прогнали через
        // escapeHtml, и вместо значков человек видит «<svg class=…».
        разметка.match(/&lt;svg|&lt;div|&lt;span/);
      if (беда) {
        const где = разметка.slice(Math.max(0, разметка.indexOf(беда[0]) - 90),
                                   разметка.indexOf(беда[0]) + 60);
        throw new Error(`в разметке «${беда[0]}» → …${где.replace(/\s+/g, " ")}…`);
      }
      console.log(`  ✓ ${имя}`);
    } catch (e) {
      упало++;
      console.log(`  ✗ ${имя}: ${e.message}`);
    }
  }
  console.log(упало ? `\nупало загрузчиков: ${упало}` : "\nвсе загрузчики отработали");
  process.exit(упало ? 1 : 0);
})();
