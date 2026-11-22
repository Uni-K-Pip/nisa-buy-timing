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

export function button(text, action, className) {
  const node = el("button", { type: "button", class: className }, text);
  node.addEventListener("click", action);
  return node;
}

export function input(name, value, attributes = {}) {
  return el("input", { name, value: value ?? "", ...attributes });
}

export function field(label, control) {
  return el("label", {}, label, control);
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

export function issueList(issues) {
  return el("div", {}, ...issues.map(issue => paragraph(issue.text, "notice " + issue.type)));
}

export const number = (value, digits = 2) => Number.isFinite(value)
  ? value.toLocaleString("ja-JP", { maximumFractionDigits: digits }) : "—";
export const percent = (value, signed = false) => Number.isFinite(value)
  ? (signed && value > 0 ? "+" : "") + number(value) + "%" : "—";
export const probability = value => Number.isFinite(value) ? percent(value * 100) : "—";

export async function getJSON(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error("data unavailable");
  return response.json();
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
