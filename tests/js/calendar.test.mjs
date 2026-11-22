import { test } from "node:test";
import assert from "node:assert/strict";
import { addBusinessDays, calendarDays, isBusinessDay, isOrderDay, jstToday,
  lastOrderDay, orderSchedule, settlementDate } from "../../site/js/calendar.js";

const holidays = calendarDays({ JP: ["2026-11-23", "2026-12-31"], NYSE: ["2026-12-25"] });

test("2026年の年内受渡、NYSEの休場を考慮", () => {
  assert.equal(lastOrderDay(2026, 6, holidays, ["NYSE"]), "2026-12-23");
  assert.equal(lastOrderDay(2026, 5, holidays, ["NYSE"]), "2026-12-24");
  assert.equal(lastOrderDay(2026, 4, holidays, ["NYSE"]), "2026-12-24");
  assert.equal(lastOrderDay(2026, 4, holidays), "2026-12-25");
  assert.equal(addBusinessDays("2026-12-31", -1, holidays), "2026-12-30");
  assert.equal(settlementDate("2026-12-23", 6, holidays), "2026-12-30");
});

test("注文日と国内営業日、およびJSTの日付", () => {
  assert.equal(isBusinessDay("2026-12-25", holidays), true);
  assert.equal(isOrderDay("2026-12-25", holidays, ["NYSE"]), false);
  assert.equal(isBusinessDay("2026-11-23", holidays), false);
  assert.equal(isBusinessDay("2027-01-01", holidays), false);
  assert.equal(isBusinessDay("2027-02-31", holidays), false);
  assert.equal(jstToday(new Date("2026-12-23T15:00:00Z")), "2026-12-24");
});

test("JST締切後は次の注文可能日から5件を推定する", () => {
  const params = { order_cutoff_jst: "15:00", order_closed_calendars: ["NYSE"],
    trade_lag_bd: 1, settle_bd_from_order: 6 };
  const orders = orderSchedule(params, holidays, new Date("2026-12-23T06:00:00Z"));
  assert.equal(orders.length, 5);
  assert.deepEqual(orders.slice(0, 2), [
    { order_date: "2026-12-24", trade_date: "2026-12-25", settle_date: "2027-01-04" },
    { order_date: "2026-12-28", trade_date: "2026-12-29", settle_date: "2027-01-06" },
  ]);
});
