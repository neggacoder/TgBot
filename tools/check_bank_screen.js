// Прогон ЭКРАНА БАНКА во всех его состояниях.
//
// Зачем отдельно от check_loaders. Загрузчик рисует экран ОДИН раз, а у банка
// состояний шесть, и они взаимоисключающие: есть вклад — нет формы открытия;
// есть кредит — нет формы заявки. То есть какой стороной ни поверни заглушку,
// половина разметки остаётся ненарисованной, и поломка в ней ждёт человека, а
// не проверку.
//
// Второе, что здесь проверяется, — ЧИСЛА до нажатия. «7% в день» ничего не
// говорит; говорит «через 3 дня получите 1210». Это число экран считает сам,
// теми же простыми процентами, что и сервер, и разойтись они не имеют права:
// расхождение человек читает как обман, а не как округление.
//
// Запуск: node tools/check_bank_screen.js   (из корня проекта)
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(
  path.join(__dirname, "..", "webpanel", "static", "app.js"), "utf8");

const узлы = {};
const создать = (сел) => (узлы[сел] ||= {
  innerHTML: "", value: "1000", dataset: {}, textContent: "", disabled: false,
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  style: { setProperty() {} }, addEventListener() {}, removeEventListener() {},
  remove() {}, querySelector: () => создать("любой"), querySelectorAll: () => [],
  appendChild() {}, children: [], options: [], closest: () => null,
});
global.$ = создать;
global.$$ = () => [];
global.escapeHtml = (s) => String(s);
global.icon = (n) => `<svg class="ic"><use href="#ic-${n}"/></svg>`;
global.say = () => {};
global.setInterval = () => 0;
global.clearInterval = () => {};
global.requestAnimationFrame = (fn) => fn();
global.document = {
  createElement: () => создать("новый"), body: { appendChild() {} },
  documentElement: { setAttribute() {}, removeAttribute() {}, dataset: {},
                     classList: { add() {}, remove() {}, toggle() {} } },
  addEventListener() {}, removeEventListener() {},
  querySelector: (сел) => создать(сел), querySelectorAll: () => [], cookie: "",
};
global.window = { addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.location = { href: "", search: "", hash: "" };
global.navigator = { userAgent: "проверка" };
global.EventSource = class { constructor() { this.close = () => {}; } addEventListener() {} };
global.URLSearchParams = class { get() { return null; } set() {} append() {} toString() { return ""; } };
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });

const кусок = src.slice(src.indexOf("// ===== Вкладка «Банк»"));
const { renderBank, bankRefreshHints, bankCreditBlocker, _bank } = new Function(
  кусок + "\n;return {renderBank, bankRefreshHints, bankCreditBlocker, _bank};")();

let ошибок = 0;
const плохо = (текст) => { console.log("✗ " + текст); ошибок++; };

const БАЗА = {
  now: new Date().toISOString(), coins: 5000, deposit: null, credit: null,
  pending: false, gate_ready: true,
  terms: [{ days: 1, rate: 5 }, { days: 3, rate: 7 }, { days: 7, rate: 10 }],
  min_deposit: 1000, credit_fee_percent: 20, credit_term_days: 7,
  credit_penalty_percent: 10, blacklisted: false, auto_reject: false,
  in_the_red: false,
};

const нарисовать = (состояние) => {
  for (const ключ of Object.keys(узлы)) delete узлы[ключ];
  _bank.state = { ...БАЗА, ...состояние };
  renderBank();
  const html = Object.values(узлы).map((у) => у.innerHTML).join("");
  if (/undefined|NaN/.test(html)) плохо("в разметке undefined или NaN");
  return html;
};

// --- пустой банк: обе формы открытия ---------------------------------------
{
  const html = нарисовать({});
  for (const что of ['data-bact="deposit"', 'data-bact="credit"', 'data-bact="term"',
                     'id="bank-amount"', 'id="bank-credit-amount"']) {
    if (!html.includes(что)) плохо(`в пустом банке нет ${что}`);
  }
  const сроков = (html.match(/data-bact="term"/g) || []).length;
  if (сроков !== 3) плохо(`сроков вклада ${сроков}, а должно быть три`);
}

// --- вклад открыт -----------------------------------------------------------
{
  const html = нарисовать({
    deposit: { amount: 1000, days: 3, rate: 7, payout: 1210,
               matures_at: "2030-01-01T00:00:00", ready: false },
  });
  if (html.includes('data-bact="deposit"')) плохо("при открытом вкладе предлагают открыть второй");
  if (!/data-bact="withdraw"[^>]*disabled/.test(html)) {
    плохо("незрелый вклад можно снять — досрочного снятия быть не должно");
  }
  // Разделитель разрядов у toLocaleString — НЕРАЗРЫВНЫЙ пробел. Сравнение с
  // обычным молча не совпадает, и проверка ругалась бы на верный экран.
  if (!html.includes((1210).toLocaleString("ru"))) плохо("не показана выплата по вкладу");
}

{
  const html = нарисовать({
    deposit: { amount: 1000, days: 3, rate: 7, payout: 1210,
               matures_at: "2020-01-01T00:00:00", ready: true },
  });
  if (/data-bact="withdraw"[^>]*disabled/.test(html)) плохо("созревший вклад не снять");
  if (!html.includes("bank-card ready")) плохо("созревший вклад ничем не выделен");
}

// --- кредит -----------------------------------------------------------------
{
  const html = нарисовать({
    credit: { debt: 1200, amount: 1000, due_at: "2020-01-01T00:00:00", overdue: true },
  });
  if (html.includes('data-bact="credit"')) плохо("при активном кредите предлагают взять второй");
  for (const что of ['data-bact="repay"', 'data-bact="repay-all"']) {
    if (!html.includes(что)) плохо(`нечем погасить: нет ${что}`);
  }
  if (!html.includes("bank-card overdue")) плохо("просроченный кредит ничем не выделен");
  if (!html.includes("пеня")) плохо("про пеню за просрочку не сказано");
}

// --- почему кредит недоступен ----------------------------------------------
// Причину экран обязан назвать ДО нажатия: отказ по факту читается как
// поломка, а не как правило.
// Активный кредит в этот список не входит: при нём экран показывает не
// причину отказа, а сам долг и чем его гасить — это и есть ответ.
const преграды = [
  ["заявка подана", { pending: true }, "ждёт решения"],
  ["чёрный список", { blacklisted: true }, "чёрном списке"],
  ["минус после взыскания", { in_the_red: true }, "отрицательный"],
  ["автоотказ", { auto_reject: true }, "не выдаются"],
  ["нет чата заявок", { gate_ready: false }, "некому одобрять"],
];
for (const [имя, состояние, слово] of преграды) {
  const html = нарисовать(состояние);
  if (html.includes('data-bact="credit"')) {
    плохо(`${имя}: кнопка заявки на месте, отказ придёт только после нажатия`);
  }
  if (!html.includes(слово)) плохо(`${имя}: не сказано почему («${слово}»)`);
}

// Порядок причин: сначала та, с которой человеку что-то делать. Долг важнее
// чёрного списка — гасить всё равно придётся.
_bank.state = { ...БАЗА, credit: { debt: 1, amount: 1, due_at: null, overdue: false },
                blacklisted: true, pending: true };
if (!bankCreditBlocker(_bank.state).includes("погасите")) {
  плохо("причины перечислены не по важности");
}

// --- числа до нажатия -------------------------------------------------------
// Те же простые проценты, что на сервере: сумма + сумма × ставка/100 × дни.
{
  нарисовать({});
  const поле = создать("#bank-amount"), итог = создать("#bank-payout");
  for (const [сумма, дни, ставка, ждём] of [[1000, 3, 7, 1210], [5000, 7, 10, 8500],
                                            [2000, 1, 5, 2100]]) {
    поле.value = String(сумма);
    _bank.days = дни;
    bankRefreshHints();
    const ожидание = ждём.toLocaleString("ru");
    if (!итог.innerHTML.includes(ожидание)) {
      плохо(`выплата ${сумма}×${ставка}%×${дни}д посчитана не как на сервере: `
            + `ждали ${ожидание}, показано «${итог.innerHTML.replace(/<[^>]+>/g, " ").trim()}»`);
    }
  }
  // Ниже минимума — вместо числа предупреждение, а не выплата, которой не будет.
  поле.value = "10";
  bankRefreshHints();
  if (!итог.innerHTML.includes("Минимум")) плохо("сумма ниже минимума не помечена");
}

{
  нарисовать({});
  const поле = создать("#bank-credit-amount"), долг = создать("#bank-debt");
  поле.value = "1000";
  bankRefreshHints();
  if (!долг.innerHTML.includes((1200).toLocaleString("ru"))) плохо("к возврату посчитано не по комиссии");
}

console.log(ошибок ? `\nошибок: ${ошибок}`
  : "✓ банк: обе формы, оба состояния, шесть причин отказа и числа до нажатия");
process.exit(ошибок ? 1 : 0);
