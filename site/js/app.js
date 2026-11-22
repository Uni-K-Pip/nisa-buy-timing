import { calendarDays, jstToday } from "./calendar.js";
import { renderChart, renderToday, renderVerify } from "./dashboard.js";
import { renderPlans } from "./plan-view.js";
import { renderSettings } from "./settings.js";
import { loadState, saveState } from "./storage.js";
import { getJSON, heading } from "./ui.js";

const view = document.querySelector("#view");
const warning = document.querySelector("#storage-status");
const tabs = [...document.querySelectorAll("[data-tab]")];
const disclaimer = document.querySelector("#disclaimer");
const titles = { today: "今日", chart: "チャート", plan: "計画", verify: "検証", settings: "設定" };
const views = { today: renderToday, chart: renderChart, plan: renderPlans, verify: renderVerify, settings: renderSettings };
let tab = "today";

function showDisclaimer() {
  if (!disclaimer.open) disclaimer.showModal();
}

function storageStatus(available) {
  warning.hidden = available;
  warning.textContent = available ? "" : "端末の保存領域を使えません。変更を保持するには、設定から書き出してください。";
}

function load(path) {
  return getJSON(path).catch(() => null);
}

const serviceWorker = navigator.serviceWorker?.register("./sw.js").catch(() => null) ?? Promise.resolve(null);
const [latest, calendar, push, appConfig] = await Promise.all([
  load("./data/latest.json"), load("./data/calendar.json"), load("./data/push.json"), load("./app-config.json"),
]);
const saved = loadState(latest?.default_watch);
const context = {
  latest, funds: latest?.funds ?? [], calendar: calendar ? calendarDays(calendar) : null,
  calendarYears: calendar?.years, push, appConfig, serviceWorker, state: saved.state, today: jstToday(),
  selection: { years: 1 }, render, showDisclaimer,
  persist() {
    storageStatus(saveState(this.state));
  },
  replaceState(state, alreadyCleared) {
    this.state = state;
    this.selection = { years: 1 };
    if (alreadyCleared === undefined) this.persist();
    else storageStatus(alreadyCleared);
  },
};

function render() {
  context.today = jstToday();
  view.replaceChildren(heading(titles[tab]), ...views[tab](context).filter(Boolean));
}

for (const control of tabs) {
  control.addEventListener("click", () => {
    tab = control.dataset.tab;
    tabs.forEach(item => {
      if (item === control) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    render();
    view.querySelector("h1").focus();
    window.scrollTo(0, 0);
  });
}
disclaimer.addEventListener("cancel", event => event.preventDefault());
document.querySelector("#agree").addEventListener("click", () => {
  context.state.agreed = true;
  context.persist();
  disclaimer.close();
});

storageStatus(saved.available);
render();
if (!context.state.agreed) showDisclaimer();
