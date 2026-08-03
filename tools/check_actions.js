// Проверка ДЕЙСТВИЙ на экранах кабинета: доходит ли нажатие до сервера.
//
// Зачем отдельно от check_loaders. Тот проверяет, что экран открывается;
// здесь — что кнопка на нём что-то делает. Посадка на ферме не работала
// вовсе: шторка выбора культуры живёт в document.body, а обработчик висел на
// самом экране и проверял «внутри ли элемент» — клики по культурам не
// доходили никуда. Экран при этом открывался и выглядел рабочим.
//
// Запуск: node tools/check_actions.js   (из корня проекта)
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(
  path.join(__dirname, "..", "webpanel", "static", "app.js"), "utf8");

const РАЗМЕТКА = fs.readFileSync(
  path.join(__dirname, "..", "webpanel", "static", "index.html"), "utf8");
const ЕСТЬ_В_СТРАНИЦЕ = new Set(
  [...РАЗМЕТКА.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]));

const узлы = {};
const существует = (сел) => {
  if (!сел.startsWith("#")) return true;
  const имя = сел.slice(1);
  if (ЕСТЬ_В_СТРАНИЦЕ.has(имя)) return true;
  return Object.values(узлы).map((у) => у.innerHTML).join("").includes(`id="${имя}"`);
};
const создать = (сел) => (узлы[сел] ||= {
  innerHTML: "", value: "1", dataset: {}, textContent: "", disabled: false,
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  style: { setProperty() {} }, addEventListener() {}, removeEventListener() {},
  remove() {}, querySelector: () => узел("любой"), querySelectorAll: () => [],
  appendChild() {}, children: [], options: [], closest: () => null,
  contains: () => true,
});
const узел = (сел) => (существует(сел) ? создать(сел) : null);
global.$ = узел;
global.$$ = () => [];
global.escapeHtml = (s) => String(s);
global.icon = (n) => `<svg><use href="#ic-${n}"/></svg>`;
global.PALETTE = ["#111"];
global.setInterval = () => 0;
global.clearInterval = () => {};
global.requestAnimationFrame = (fn) => fn();
global.prompt = () => "1";
global.confirm = () => true;

// Шторка создаётся через createElement и живёт вне экрана — здесь важно
// сохранить её обработчик, чтобы «нажать» по культуре.
let шторка = null;
global.document = {
  createElement: () => {
    шторка = {
      className: "", id: "", innerHTML: "", слушатели: [],
      addEventListener(_вид, fn) { this.слушатели.push(fn); },
      classList: { add() {}, remove() {} }, remove() { шторка = null; },
    };
    return шторка;
  },
  body: { appendChild() {} },
  documentElement: { setAttribute() {}, removeAttribute() {}, dataset: {},
                     classList: { add() {}, remove() {}, toggle() {} } },
  addEventListener() {}, removeEventListener() {},
  querySelector: (сел) => узел(сел), querySelectorAll: () => [], cookie: "",
};
global.window = { addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.location = { href: "", search: "", hash: "" };
global.navigator = { userAgent: "проверка" };
global.EventSource = class { constructor() { this.close = () => {}; } addEventListener() {} };
global.URLSearchParams = class { get() { return null; } set() {} append() {} toString() { return ""; } };

const ферма = {
  now: new Date().toISOString(), coins: 100000,
  weather: { emoji: "☀", name: "Ясно", yield_percent: 0, grow_percent: 0, pest_percent: 0 },
  plots: [{ slot: 0, crop: null }], plot_total: 1, plot_free: 1,
  plot_sources: {}, plot_next_price: null, plot_room: 0,
  crops: [{ key: "kartoshka", name: "Картошка", emoji: "🥔", price: 200,
            grow_seconds: 7200, yield_min: 2, yield_max: 4, item_name: "Картошка",
            hint: "", perish_hours: 0, locked: false, affordable: 10 }],
  barn: [], aura: {}, pests_off: false, reds: [],
};

const запросы = [];
global.fetch = async (путь, настройки) => {
  запросы.push({ путь, тело: настройки && настройки.body });
  const тело = путь.includes("/game/farm") && (!настройки || настройки.method !== "POST")
    ? ферма
    : { ok: true, planted: 1, coins_spent: 200, state: ферма };
  return { ok: true, status: 200, json: async () => тело };
};

const код = src.replace(/\nboot\(\);\s*$/, "\n");
const хвост = "\n;return {loadMemberFarm,openCropSheet,onFarmClick};";
const { loadMemberFarm, openCropSheet } = new Function(код + хвост)();

(async () => {
  await loadMemberFarm();
  // Загрузчик запускает получение состояния и НЕ ждёт его — как в браузере.
  // Даём микрозадачам добежать, иначе шторка строится по пустому состоянию.
  await new Promise((r) => setTimeout(r, 20));
  openCropSheet(0);
  if (!шторка) {
    console.log("✗ шторка выбора культуры не создалась");
    process.exit(1);
  }
  if (!/data-act="sow"/.test(шторка.innerHTML)) {
    console.log("✗ в шторке нет ни одной культуры");
    process.exit(1);
  }

  // Нажимаем по культуре: событие идёт ровно так, как в браузере, — через
  // обработчик, который повесила сама шторка.
  const кнопка = {
    dataset: { act: "sow", crop: "kartoshka" },
    closest: (сел) => (сел === "[data-act]" ? кнопка : (сел === "#farm-sheet" ? шторка : null)),
    disabled: false,
  };
  запросы.length = 0;
  for (const fn of шторка.слушатели) await fn({ target: кнопка });
  await new Promise((r) => setTimeout(r, 10));

  const посадка = запросы.find((з) => з.путь.includes("/farm/plant"));
  if (!посадка) {
    console.log("✗ нажатие по культуре не дошло до посадки");
    console.log("  запросы:", запросы.map((з) => з.путь));
    process.exit(1);
  }
  const тело = JSON.parse(посадка.тело);
  if (тело.crop !== "kartoshka") {
    console.log("✗ до сервера доехала не та культура:", тело);
    process.exit(1);
  }
  console.log("✓ посадка: нажатие по культуре доходит до сервера", тело);
  process.exit(0);
})();
