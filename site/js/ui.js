import { clampPercent, ZONES } from "./visual.js";

export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value != null && value !== false) node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.filter(child => child != null));
  return node;
}

export const paragraph = (text, className) => el("p", { class: className }, text);
export const heading = text => el("h1", { id: "view-title", tabindex: "-1" }, text);
export const card = (...children) => el("section", { class: "card" }, ...children);

export function svg(tag, attributes = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value != null) node.setAttribute(name, value);
  }
  node.append(...children.filter(child => child != null));
  return node;
}

const ICONS = {
  gauge: "M3 17a9 9 0 0 1 18 0M12 17l4-5M7 12l-1-1M12 10V8",
  clock: "M22 12a10 10 0 1 0-20 0 10 10 0 1 0 20 0ZM12 6v6l4 2",
  calendar: "M4 6h16v15H4zM8 3v6m8-6v6M4 11h16m-12 4h2m4 0h2",
  device: "M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm4 16h2",
  globe: "M22 12a10 10 0 1 0-20 0 10 10 0 1 0 20 0ZM2 12h20m-10-10c-5 5-5 15 0 20 5-5 5-15 0-20Z",
  lock: "M5 10h14v11H5zM8 10V7a4 4 0 0 1 8 0v3m-4 4v3",
};

export function icon(name) {
  return svg("svg", { viewBox: "0 0 24 24", class: "ui-icon", "aria-hidden": "true" },
    svg("path", { d: ICONS[name] }));
}

export function emptyState(symbol, title, text) {
  return card(el("div", { class: "empty-state" }, icon(symbol), el("h2", {}, title), paragraph(text)));
}

export function button(text, action, className) {
  const node = el("button", { type: "button", class: className }, text);
  node.addEventListener("click", action);
  return node;
}

export function segmented(label, items, current, onSelect) {
  return el("div", { class: "segments", role: "group", "aria-label": label },
    ...items.map(([value, title]) => {
      const control = button(title, () => {
        if (value !== current) onSelect(value);
      });
      control.setAttribute("aria-pressed", String(value === current));
      control.dataset.segment = String(value);
      return control;
    }));
}

export function details(label, children, selection, key, open = false) {
  const states = selection ? (selection.details ??= new Map()) : null;
  const node = el("details", { open: states?.get(key) ?? open, "data-details-key": states ? key : null },
    el("summary", {}, label), ...children);
  if (states) node.addEventListener("toggle", () => {
    if (node.isConnected) states.set(key, node.open);
  });
  return node;
}

export function input(name, value, attributes = {}) {
  return el("input", { name, value: value ?? "", ...attributes });
}

export function field(label, control) {
  return el("label", {}, label, control);
}

export function checkboxRow(label, control) {
  return el("label", { class: "check-row" }, control, el("span", {}, label));
}

export function select(name, items, current) {
  return el("select", { name },
    ...items.map(([value, title]) => el("option", { value, selected: String(current) === String(value) }, title)));
}

export function facts(rows) {
  return el("dl", { class: "facts" }, ...rows.map(([title, value]) =>
    el("div", {}, el("dt", {}, title), el("dd", {}, value ?? "—"))));
}

export function table(headers, rows) {
  return el("div", { class: "table-wrap", tabindex: "0" }, el("table", {},
    el("thead", {}, el("tr", {}, ...headers.map(title => el("th", { scope: "col" }, title)))),
    el("tbody", {}, ...rows.map(([label, ...cells]) => el("tr", {},
      el("th", { scope: "row" }, String(label)), ...cells.map(cell => el("td", {}, String(cell ?? "—"))))))));
}

export const ISSUE_LABELS = {
  error: ["!", "エラー"], warning: ["△", "警告"], info: ["ⓘ", "情報"],
};

export function issueList(issues) {
  return el("div", { class: "issues" }, ...issues.map(({ type, text }) => {
    const [symbol, label] = ISSUE_LABELS[type];
    return el("p", { class: "notice issue " + type },
      el("strong", {}, el("span", { "aria-hidden": "true" }, symbol + " "), label), text);
  }));
}

export const number = (value, digits = 2) => Number.isFinite(value)
  ? value.toLocaleString("ja-JP", { maximumFractionDigits: digits }) : "—";
export const percent = (value, signed = false) => Number.isFinite(value)
  ? (signed && value > 0 ? "+" : "") + number(value) + "%" : "—";
export const probability = value => Number.isFinite(value) ? percent(value * 100) : "—";

export const chip = (text, className = "") => el("span", { class: "chip " + className }, text);
export const zonePill = zone => chip(zone?.name ?? "算出できません", "zone-pill " + (zone?.key ?? "no-zone"));

// 5 列に収めるため、「かなり割高圏」は「かなり」の後ろでだけ折り返せるようにする。
const zoneName = name => name.startsWith("かなり")
  ? el("span", {}, "かなり", el("wbr"), name.slice(3)) : el("span", {}, name);

export function zoneLegend() {
  return el("ul", { class: "zone-legend", "aria-label": "スコアの区分" }, ...ZONES.map((zone, i) =>
    el("li", {}, el("span", { class: "zone-swatch " + zone.key, "aria-hidden": "true" }),
      zoneName(zone.name), el("small", {}, `${zone.min}〜${zone.max - (i === ZONES.length - 1 ? 0 : 1)}`))));
}

export function movementChip(value) {
  if (!Number.isFinite(value)) return chip("前日比 —");
  const direction = value > 0 ? "▲+" : value < 0 ? "▼-" : "＝±";
  return chip(direction + number(Math.abs(value)) + "%", value > 0 ? "up" : value < 0 ? "down" : "flat");
}

export const STATUS_LABELS = [
  ["planned", "予定"], ["ordered", "注文済み"], ["executed", "約定済み"], ["cancelled", "取消"],
];
const statusLabels = new Map(STATUS_LABELS);
export const isPurchased = row => row.status === "ordered" || row.status === "executed";
export const statusChip = status => chip(statusLabels.get(status), "status-chip " + status);

export function installmentDots(rows) {
  return el("ol", { class: "installment-dots", "aria-label": "各回の状態" }, ...rows.map((row, i) => {
    const label = (i + 1) + "回目 " + statusLabels.get(row.status);
    return el("li", { class: "installment-dot " + row.status, title: label },
      el("span", { "aria-hidden": "true" }, row.status === "cancelled" ? "×" : ""),
      el("span", { class: "sr-only" }, label));
  }));
}

export function bar(value, className = "") {
  const fill = el("span", { class: "bar-fill " + className });
  fill.style.setProperty("--bar-value", (Number.isFinite(value) ? clampPercent(value) : 0) + "%");
  return el("div", { class: "bar", "aria-hidden": "true" }, fill);
}

export async function getJSON(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error("data unavailable");
  return response.json();
}

// 期間や銘柄の切り替えのたびに同じ JSON を取り直さない。失敗は覚えず、次の描画で取り直す。
export function cachedJSON(context, path) {
  const cache = (context.dataCache ??= new Map());
  if (!cache.has(path)) {
    const request = getJSON(path);
    request.catch(() => cache.delete(path));
    cache.set(path, request);
  }
  return cache.get(path);
}

export function selectedFund(context, value) {
  return context.funds.find(fund => fund.id === value) ??
    context.funds.find(fund => context.state.watch.includes(fund.id)) ?? context.funds[0];
}

export function fundPicker(funds, current, onSelect) {
  const picker = select("fund", funds.map(fund => [fund.id, fund.name]), current);
  picker.addEventListener("change", () => onSelect(picker.value));
  return field("銘柄", picker);
}

// Redraw at CSS-pixel dimensions so SVG labels keep their size on narrow screens.
export function responsiveFigure(draw, signal) {
  const frame = el("div", { class: "figure-frame" });
  let renderedWidth = 0;
  const resize = width => {
    if (width <= 0 || width === renderedWidth || signal?.aborted) return;
    renderedWidth = width;
    frame.replaceChildren(draw(width));
  };
  if (typeof ResizeObserver === "undefined") {
    queueMicrotask(() => resize(Math.floor(frame.clientWidth)));
    return frame;
  }
  if (signal?.aborted) return frame;
  const observer = new ResizeObserver(([entry]) => resize(Math.floor(entry.contentRect.width)));
  observer.observe(frame);
  signal?.addEventListener("abort", () => observer.disconnect(), { once: true });
  return frame;
}
