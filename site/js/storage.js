import { parseDay } from "./calendar.js";
import { STATUSES } from "./plan.js";

const KEY = "nbt:v1";
export const DEFAULT_NOTIFICATIONS = Object.freeze({
  score_at_least: 70, plan_prices: true, plan_dates: true, year_end: true,
  ml_enabled: false, ml_probability: 0.4,
});

export function defaults(watch = []) {
  return { v: 1, agreed: false, guide_closed: false, watch: [...watch], plans: [],
    notifications: { ...DEFAULT_NOTIFICATIONS }, push_hash: null };
}

const plain = value => value !== null && typeof value === "object" && !Array.isArray(value);
const id = value => typeof value === "string" && /^[a-zA-Z0-9-]+$/.test(value);
const optionalDay = value => value === null || parseDay(value) !== null;
const number = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
const yen = value => value === null || (Number.isSafeInteger(value) && value >= 0);
const kind = value => value === "nav" || value === "index";

function validRow(row) {
  return plain(row) && id(row.id) && optionalDay(row.planned_date) &&
    STATUSES.includes(row.status) && yen(row.amount) && optionalDay(row.order_date) &&
    optionalDay(row.trade_date) && optionalDay(row.settle_date) && typeof row.note === "string";
}

function validPlan(plan) {
  return plain(plan) && id(plan.id) && id(plan.fund_id) && typeof plan.title === "string" &&
    (plan.year === null || Number.isInteger(plan.year) && number(plan.year, 1900, 9999)) &&
    yen(plan.budget) && number(plan.threshold_score, 0, 100) && number(plan.pull_forward_score, 0, 100) &&
    optionalDay(plan.official_last_order_date) && yen(plan.nisa_used_this_year) &&
    Array.isArray(plan.installments) && plan.installments.every(validRow) &&
    new Set(plan.installments.map(row => row.id)).size === plan.installments.length &&
    Array.isArray(plan.levels) && plan.levels.every(rule =>
      plain(rule) && kind(rule.kind) && rule.op === "<=" && number(rule.value, 0, Number.MAX_VALUE)
    ) && (plan.drop_rule === null || (
      plain(plan.drop_rule) && kind(plan.drop_rule.kind) &&
      number(plan.drop_rule.reference_value, 0, Number.MAX_VALUE) && number(plan.drop_rule.pct, 0, 100)
    ));
}

export function parseBackup(raw) {
  const saved = JSON.parse(raw);
  const rules = saved?.notifications;
  if (!plain(saved) || saved.v !== 1 || typeof saved.agreed !== "boolean" ||
      (Object.hasOwn(saved, "guide_closed") && typeof saved.guide_closed !== "boolean") ||
      !Array.isArray(saved.watch) || !saved.watch.every(id) ||
      !Array.isArray(saved.plans) || !saved.plans.every(validPlan) ||
      new Set(saved.plans.map(plan => plan.id)).size !== saved.plans.length ||
      !plain(rules) || !(rules.score_at_least === null || number(rules.score_at_least, 0, 100)) ||
      !["plan_prices", "plan_dates", "year_end", "ml_enabled"].every(key => typeof rules[key] === "boolean") ||
      !number(rules.ml_probability, 0, 1) ||
      !(saved.push_hash === null || typeof saved.push_hash === "string" && /^[a-f0-9]{64}$/.test(saved.push_hash))) {
    throw new Error("設定ファイルの形式が違います。");
  }
  return saved;
}

export function loadState(watch) {
  try {
    const raw = localStorage.getItem(KEY);
    return { state: raw ? parseBackup(raw) : defaults(watch), available: true };
  } catch {
    return { state: defaults(watch), available: false };
  }
}

export function saveState(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

export function clearState() {
  try {
    localStorage.removeItem(KEY);
    return true;
  } catch {
    return false;
  }
}
