import { test } from "node:test";
import assert from "node:assert/strict";
import { calendarDays } from "../../site/js/calendar.js";
import { allocateBudget, checkPlan } from "../../site/js/plan.js";

const calendar = calendarDays({ JP: ["2026-12-31"], NYSE: ["2026-12-25"] });
const fund = {
  id: "example-fund",
  nav: { value: 900 },
  proxy: { index: { value: 85 } },
  score: { value: 87 },
  settlement: { settle_bd_from_order: 6, order_closed_calendars: ["NYSE"] },
};

function row(id, planned_date, attrs = {}) {
  return { id, planned_date, amount: 10, status: "planned", order_date: null,
    trade_date: null, settle_date: null, note: "", ...attrs };
}

function plan(attrs = {}) {
  return {
    id: "example-plan", fund_id: fund.id, title: "", year: 2026,
    budget: 100, threshold_score: 70, pull_forward_score: 85, levels: [],
    drop_rule: null, installments: [], official_last_order_date: null,
    nisa_used_this_year: null, ...attrs,
  };
}

const check = (value, today = "2026-12-22") => checkPlan(value, { fund, today, calendar });

test("端数を最後に寄せて予算を割り振る", () => {
  assert.deepEqual(allocateBudget(101, 3), [33, 33, 35]);
  assert.deepEqual(allocateBudget(101, 0), []);
  assert.deepEqual(allocateBudget(null, 4), []);
});

test("取消を除いた予算超過と受渡年ごとの上限", () => {
  const installments = [
    row("a", "2026-12-21", { status: "executed", settle_date: "2026-12-21" }),
    row("b", "2026-12-22"),
    row("c", "2026-12-22", { status: "cancelled", amount: 50 }),
    row("d", "2026-12-24", { status: "ordered", settle_date: "2027-01-04" }),
    row("e", "2025-12-24", { status: "executed", settle_date: "2026-12-23" }),
  ];
  const errors = value => check(value).filter(issue => issue.type === "error").map(issue => issue.text);
  assert.deepEqual(errors(plan({ installments, budget: 40, nisa_used_this_year: 2_399_980 })), []);
  assert.deepEqual(errors(plan({ installments, budget: 39, nisa_used_this_year: 2_399_981 })),
    ["取消を除いた合計金額が予算を超えています。", "成長投資枠の年間上限を超えます"]);
});

test("予定日超過、注文休業、受渡年、二重注文を表示", () => {
  const installments = [
    row("a", "2026-12-21"),
    row("b", "2026-12-25"),
    row("c", "2026-12-22", { status: "ordered", order_date: "2026-12-22" }),
    row("d", "2026-12-22", { status: "executed", order_date: "2026-12-22" }),
  ];
  const warnings = check(plan({ installments })).filter(issue => issue.type === "warning");
  assert.ok(warnings.some(issue => issue.id === "a" && issue.text.includes("二重注文に注意")));
  assert.ok(warnings.some(issue => issue.id === "b" && issue.text.includes("2026-12-28")));
  assert.ok(warnings.some(issue => issue.id === "b" && issue.text.includes("翌年の枠")));
  assert.ok(warnings.some(issue => issue.text.includes("注文済みの回が複数")));
  const official = plan({ installments: [row("b", "2026-12-23")], official_last_order_date: "2026-12-22" });
  assert.ok(check(official).some(issue => issue.text.includes("翌年の枠")));
});

test("前倒しと価格・下落率条件の到達、未注文の回がない場合", () => {
  const value = plan({
    installments: [row("a", "2026-12-23")],
    levels: [{ kind: "nav", op: "<=", value: 900 }],
    drop_rule: { kind: "index", reference_value: 100, pct: 15 },
  });
  const messages = check(value).filter(issue => issue.type === "info").map(issue => issue.text);
  assert.equal(messages.length, 3);
  assert.ok(messages.some(text => text.includes("前倒し")));
  assert.ok(messages.some(text => text.includes("価格以下")));
  assert.ok(messages.some(text => text.includes("下落率")));
  value.installments[0].status = "ordered";
  assert.ok(!check(value).some(issue => issue.text.includes("前倒し")));
});
