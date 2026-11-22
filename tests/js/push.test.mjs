import { test } from "node:test";
import assert from "node:assert/strict";
import { copyPayload, payloadHash } from "../../site/js/push.js";
import { defaults, parseBackup } from "../../site/js/storage.js";

test("通知用JSONに計画名、予算、金額、購入メモが入らない", async () => {
  const state = defaults(["example-fund"]);
  state.plans.push({
    title: "SYNTHETIC-TITLE", budget: 123457, nisa_used_this_year: 127123, fund_id: "example-fund",
    levels: [{ kind: "nav", op: "<=", value: 777 }],
    drop_rule: { kind: "index", reference_value: 100, pct: 10 },
    installments: [
      { planned_date: "2026-12-22", status: "ordered", amount: 99991 },
      { planned_date: "2026-12-23", status: "planned", amount: 99992, note: "SYNTHETIC-NOTE" },
    ],
  });
  const subscription = { toJSON: () => ({ endpoint: "https://push.example.com/subscription" }) };
  const copied = copyPayload(subscription, state);
  for (const forbidden of ["title", "budget", "amount", "123457", "127123", "99991", "99992", "SYNTHETIC"]) {
    assert.ok(!copied.includes(forbidden));
  }
  const parsed = JSON.parse(copied);
  assert.equal(parsed.rules.levels[0].value, 777);
  assert.equal(parsed.rules.drops[0].pct, 10);
  assert.deepEqual(parsed.rules.dates, [
    { fund_id: "example-fund", date: "2026-12-23", label: "2回目", days_before: [1, 0] },
  ]);
  assert.deepEqual(parsed.rules.year_end, { fund_ids: ["example-fund"], days_before: [5, 1] });
  assert.deepEqual(parsed.rules.ml, { enabled: false, prob_at_most: 0.4, valid_only: true });
  const original = await payloadHash(copied);
  state.plans[0].installments[1].amount = 53;
  assert.equal(await payloadHash(copyPayload(subscription, state)), original);
  state.plans[0].installments[1].planned_date = "2026-12-24";
  assert.notEqual(await payloadHash(copyPayload(subscription, state)), original);
});

test("設定の書き出しと読み込みの形を検証する", () => {
  const state = defaults(["example-fund"]);
  assert.deepEqual(parseBackup(JSON.stringify(state)), state);
  assert.throws(() => parseBackup('{"v": 2}'));
});
