import assert from "node:assert/strict";
import test from "node:test";
import { parseDay } from "../../site/js/calendar.js";
import { clampPercent, displayScore, elementName, gaugeArc, gaugePoint, shortDay, symmetricAxis,
  timeTicks, valueAxis, ZONES, zoneDescription, zoneOf } from "../../site/js/visual.js";

test("画面に出す整数のスコアは、区分の下限と食い違わない", () => {
  assert.deepEqual([79.6, 79.99, 80, 82.69, 19.5, 0, 100, 101, -3].map(displayScore),
    ["79", "79", "80", "82", "19", "0", "100", "100", "0"]);
  for (const value of [0, 19.99, 20, 39.5, 59.99, 60, 79.99, 80, 100]) {
    assert.equal(zoneOf(Number(displayScore(value))), zoneOf(value));
  }
  for (const value of [null, undefined, NaN, "80"]) assert.equal(displayScore(value), "—");
});

test("5区分を0から100まで隙間なく定義する", () => {
  assert.deepEqual(ZONES.map(({ min, max }) => [min, max]), [
    [0, 20], [20, 40], [40, 60], [60, 80], [80, 100],
  ]);
});

test("各境界はスコアの高い方の区分に入る", () => {
  const boundaries = [[0, "very_expensive"], [20, "expensive"], [40, "neutral"],
    [60, "cheap"], [80, "very_cheap"], [100, "very_cheap"]];
  for (const [value, key] of boundaries) assert.equal(zoneOf(value).key, key);
  for (const zone of ZONES) assert.equal(zoneOf(zone.max - 0.01), zone);
});

test("範囲を外れた有限スコアは端の区分で扱う", () => {
  assert.equal(zoneOf(-1), ZONES[0]);
  assert.equal(zoneOf(101), ZONES.at(-1));
  assert.deepEqual([-1, 20, 101].map(clampPercent), [0, 20, 100]);
});

test("スコアが有限の数でなければ算出不能", () => {
  for (const value of [null, undefined, "80", NaN, Infinity, false]) assert.equal(zoneOf(value), null);
});

test("半円上の0・50・100は左・上・右に対応する", () => {
  assert.deepEqual(gaugePoint(0, 20, 20, 10), { x: 10, y: 20 });
  assert.deepEqual(gaugePoint(50, 20, 20, 10), { x: 20, y: 10 });
  assert.deepEqual(gaugePoint(100, 20, 20, 10), { x: 30, y: 20 });
});

test("半円の範囲を外れる値を端に丸め、無効な座標は除外する", () => {
  assert.deepEqual(gaugePoint(-9, 20, 20, 10), gaugePoint(0, 20, 20, 10));
  assert.deepEqual(gaugePoint(109, 20, 20, 10), gaugePoint(100, 20, 20, 10));
  assert.equal(gaugePoint(null, 20, 20, 10), null);
  assert.equal(gaugePoint(50, 20, 20, -1), null);
  assert.equal(gaugePoint(50, 20, NaN, 10), null);
});

test("弧の始点と終点を丸め、不正な弧を描かない", () => {
  assert.equal(gaugeArc(-10, 120, 20, 20, 10), "M 10 20 A 10 10 0 0 1 30 20");
  assert.match(gaugeArc(20, 40, 20, 20, 10), /^M .+ A 10 10 0 0 1 /);
  assert.equal(gaugeArc(80, 60, 20, 20, 10), "");
  assert.equal(gaugeArc(100, 101, 20, 20, 10), "");
  assert.equal(gaugeArc(0, 10, 20, 20, 0), "");
  assert.equal(gaugeArc(null, 40, 20, 20, 10), "");
});

test("短い日付の曜日をUTCで数える", () => {
  assert.equal(shortDay("2026-12-23"), "12/23(水)");
  assert.equal(shortDay("2024-02-29"), "2/29(木)");
  assert.equal(shortDay("1970-01-01"), "1/1(木)");
});

test("不正な日付をダッシュで表示する", () => {
  for (const value of [null, "", "2026-02-29", "2026-2-01", "2026-01-01T00:00:00Z", 0]) {
    assert.equal(shortDay(value), "—");
  }
});

test("1年以内の時間目盛りは月初で、年が変わる位置に年を表示する", () => {
  const ticks = timeTicks(parseDay("2025-10-01"), parseDay("2026-09-30"), 4);
  assert.deepEqual(ticks.map(({ label }) => label), ["10月", "2026年", "4月", "7月"]);
  assert.equal(ticks[1].stamp, parseDay("2026-01-01"));
  assert.ok(ticks.every(({ stamp }) => new Date(stamp).getUTCDate() === 1));
  assert.equal(timeTicks(parseDay("2026-02-02"), parseDay("2026-02-28")).length, 0);
});

test("長期間の時間目盛りは範囲内の年初で、指定の個数を超えない", () => {
  const start = parseDay("2017-02-02");
  const end = parseDay("2026-09-30");
  const ticks = timeTicks(start, end, 3);
  assert.ok(ticks.length > 0 && ticks.length <= 3);
  assert.ok(ticks.every(({ stamp, label }) => stamp >= start && stamp <= end &&
    new Date(stamp).toISOString().slice(5, 10) === "01-01" && /^\d{4}年$/.test(label)));
  assert.deepEqual(timeTicks(0, 0, 1), [{ stamp: 0, label: "1970年" }]);
});

test("不正な期間や個数の時間目盛りは空", () => {
  for (const args of [[null, 0], [1, 0], [0, Infinity], [0, 1, 0], [0, 1, 1.5], [0, 1e25]]) {
    assert.deepEqual(timeTicks(...args), []);
  }
});

test("価格の軸をきりのよい範囲に広げ3〜4本の目盛りを出す", () => {
  assert.deepEqual(valueAxis(71284, 104358), { min: 70000, max: 105000, ticks: [70000, 80000, 90000, 100000] });
  for (const [min, max] of [[5, 10], [10, 10], [0, 0], [-1, 0.1], [39.58, 41.499], [0.11, 0.15]]) {
    const axis = valueAxis(min, max);
    assert.ok(axis.min <= min && axis.max >= max && axis.min < axis.max);
    assert.ok(axis.ticks.length >= 3 && axis.ticks.length <= 4);
    assert.ok(axis.ticks.every((tick, i) => tick >= axis.min && tick <= axis.max && (!i || tick > axis.ticks[i - 1])));
  }
});

test("逆順や有限でない値では価格軸を作らない", () => {
  assert.equal(valueAxis(10, 9), null);
  assert.equal(valueAxis(null, 10), null);
  assert.equal(valueAxis(0, Infinity), null);
});

test("比較軸を左右対称に広げ、無効な値や0のときも目盛りを出す", () => {
  assert.deepEqual(symmetricAxis([-8.08, 8.06]), { min: -10, max: 10, ticks: [-10, -5, 0, 5, 10] });
  assert.deepEqual(symmetricAxis([0, -2, null, NaN, Infinity]), { min: -2, max: 2, ticks: [-2, -1, 0, 1, 2] });
  assert.deepEqual(symmetricAxis(null), { min: -1, max: 1, ticks: [-1, -0.5, 0, 0.5, 1] });
});

test("各指標に平易な名前を付け、未知のキーも扱う", () => {
  assert.deepEqual(["dd252", "ma200_dev", "ma25_dev", "rsi14", "fx_dev"].map(elementName), [
    "1年の高値からの下がり幅", "長い目で見た平均(200日)との差", "最近の平均(25日)との差",
    "売られすぎ・買われすぎ(RSI)", "為替(円高・円安)",
  ]);
  assert.equal(elementName("toString"), "その他の指標");
  assert.equal(elementName(null), "その他の指標");
});

test("区分の説明を過去との比較で示し、区分がなければ算出不能を示す", () => {
  assert.deepEqual(ZONES.map(zoneDescription), ["かなり高い", "やや高い", "ふつうの", "やや安い", "かなり安い"]
    .map(word => "過去5年のこの投信の中で、" + word + "水準です。"));
  assert.equal(zoneDescription(null), "スコアを算出できません。");
  assert.equal(zoneDescription({}), "スコアを算出できません。");
});
