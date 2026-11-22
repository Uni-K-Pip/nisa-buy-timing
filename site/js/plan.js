import { isOrderDay, lastOrderDay, nextOrderDay, parseDay, settlementDate } from "./calendar.js";

export const STATUSES = ["planned", "ordered", "executed", "cancelled"];
export const GROWTH_LIMIT = 2_400_000;

export function allocateBudget(budget, count) {
  if (!Number.isSafeInteger(budget) || budget < 0 || !Number.isSafeInteger(count) || count < 1) return [];
  const amount = Math.floor(budget / count);
  return Array.from({ length: count }, (_, i) => i === count - 1 ? budget - amount * (count - 1) : amount);
}

export function planOrderDeadline(plan, settlement, calendar) {
  if (parseDay(plan.official_last_order_date) !== null) return plan.official_last_order_date;
  return settlement && calendar && plan.year
    ? lastOrderDay(plan.year, settlement.settle_bd_from_order, calendar, settlement.order_closed_calendars)
    : null;
}

export function fundPrice(fund, kind) {
  return kind === "index" ? fund?.proxy?.index?.value : fund?.nav?.value;
}

export function checkPlan(plan, { fund, today, calendar, calendarYears }) {
  const issues = [];
  const add = (type, text, id = null) => issues.push({ type, text, id });
  const params = fund?.settlement;
  const closed = params?.order_closed_calendars ?? [];
  const known = day => Boolean(calendar) && (!calendarYears || calendarYears.includes(Number(day?.slice(0, 4))));
  const deadline = planOrderDeadline(plan, params, known(String(plan.year)) ? calendar : null);
  const active = plan.installments.filter(row => row.status !== "cancelled");
  const total = active.reduce((amount, row) => amount + (row.amount ?? 0), 0);
  if (Number.isFinite(plan.budget) && total > plan.budget) {
    add("error", "取消を除いた合計金額が予算を超えています。");
  }

  let unsettled = 0;
  const ordered = new Set();
  const duplicate = new Set();
  for (const row of active) {
    const planned = parseDay(row.planned_date) !== null ? row.planned_date : null;
    if (row.status === "planned" && planned && planned < today) {
      add("warning", "予定日を過ぎています。注文済みか確かめてください(二重注文に注意)", row.id);
    }
    if (planned && known(planned) && !isOrderDay(planned, calendar, closed)) {
      const next = nextOrderDay(planned, calendar, closed);
      if (known(next)) add("warning", "予定日は注文できません。次に注文できる日（推定）は " + next + " です。", row.id);
    }
    if (planned && deadline && planned > deadline) {
      add("warning", "受渡が翌年になり、翌年の枠を使う可能性があります", row.id);
    }
    if (row.status === "ordered" || row.status === "executed") {
      if (row.order_date && ordered.has(row.order_date) && !duplicate.has(row.order_date)) {
        add("warning", row.order_date + " に注文済みの回が複数あります。");
        duplicate.add(row.order_date);
      }
      if (row.order_date) ordered.add(row.order_date);
    }

    const base = row.order_date || planned;
    if (!row.settle_date && base && params && !known(base)) continue;
    let settle = row.settle_date;
    if (!settle && base && params) {
      const order = row.order_date || nextOrderDay(base, calendar, closed);
      settle = settlementDate(order, params.settle_bd_from_order, calendar);
      if (!known(settle)) settle = null;
      if (!row.order_date && deadline && order > deadline && order.startsWith(String(plan.year))) settle = null;
    }
    if (settle && settle >= today && settle.startsWith(String(plan.year) + "-")) unsettled += row.amount ?? 0;
  }
  if (Number.isFinite(plan.nisa_used_this_year) && plan.nisa_used_this_year + unsettled > GROWTH_LIMIT) {
    add("error", "成長投資枠の年間上限を超えます");
  }
  if (Number.isFinite(fund?.score?.value) && fund.score.value >= plan.pull_forward_score &&
      active.some(row => row.status === "planned")) {
    add("info", "前倒しの条件に達しています(判断はご自身で)");
  }
  for (const level of plan.levels) {
    const price = fundPrice(fund, level.kind);
    if (Number.isFinite(price) && Number.isFinite(level.value) && price <= level.value) {
      add("info", (level.kind === "index" ? "指数" : "基準価額") + "が設定した価格以下です。");
    }
  }
  const drop = plan.drop_rule;
  if (drop) {
    const price = fundPrice(fund, drop.kind);
    if (Number.isFinite(price) && Number.isFinite(drop.reference_value) && Number.isFinite(drop.pct) &&
        price <= drop.reference_value * (1 - drop.pct / 100)) {
      add("info", (drop.kind === "index" ? "指数" : "基準価額") + "が設定した下落率に達しています。");
    }
  }
  return issues;
}

