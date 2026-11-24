import { parseDay } from "./calendar.js";

export const ZONES = Object.freeze([
  { key: "very_expensive", min: 0, max: 20, name: "かなり割高圏", comparison: "かなり高い" },
  { key: "expensive", min: 20, max: 40, name: "割高寄り", comparison: "やや高い" },
  { key: "neutral", min: 40, max: 60, name: "中立", comparison: "ふつうの" },
  { key: "cheap", min: 60, max: 80, name: "割安寄り", comparison: "やや安い" },
  { key: "very_cheap", min: 80, max: 100, name: "かなり割安圏", comparison: "かなり安い" },
].map(Object.freeze));

export function zoneOf(score) {
  return Number.isFinite(score) ? ZONES.findLast(zone => score >= zone.min) ?? ZONES[0] : null;
}

export const clampPercent = value => Math.max(0, Math.min(100, value));

// 画面の整数は切り捨てる。四捨五入だと 79.6 が「80」と「割安寄り」になり、区分の下限(80)と食い違う。
export const displayScore = score => Number.isFinite(score) ? String(Math.floor(clampPercent(score))) : "—";

export function gaugePoint(score, cx, cy, r) {
  if (![score, cx, cy, r].every(Number.isFinite) || r < 0) return null;
  const angle = Math.PI * (clampPercent(score) / 100);
  return { x: cx - r * Math.cos(angle), y: cy - r * Math.sin(angle) };
}

export function gaugeArc(start, end, cx, cy, r) {
  const from = gaugePoint(start, cx, cy, r);
  const to = gaugePoint(end, cx, cy, r);
  if (!from || !to || clampPercent(end) <= clampPercent(start) || r === 0) return "";
  return `M ${from.x} ${from.y} A ${r} ${r} 0 0 1 ${to.x} ${to.y}`;
}

export function shortDay(value) {
  const stamp = parseDay(value);
  if (stamp === null) return "—";
  const day = new Date(stamp);
  return `${day.getUTCMonth() + 1}/${day.getUTCDate()}(${"日月火水木金土"[day.getUTCDay()]})`;
}

function monthStamp(month) {
  const date = new Date(0);
  const year = Math.floor(month / 12);
  date.setUTCFullYear(year, month - year * 12, 1);
  return date.getTime();
}

export function timeTicks(start, end, limit = 4) {
  if (![start, end].every(Number.isFinite) || end < start || !Number.isInteger(limit) || limit < 1) return [];
  const first = new Date(start);
  const last = new Date(end);
  if (![first, last].every(date => Number.isFinite(date.getTime()))) return [];
  const anniversary = new Date(start);
  anniversary.setUTCFullYear(first.getUTCFullYear() + 1);
  const short = end <= anniversary.getTime();
  const firstMonth = first.getUTCFullYear() * 12 + first.getUTCMonth();
  const lastMonth = last.getUTCFullYear() * 12 + last.getUTCMonth();
  const firstTick = firstMonth + (monthStamp(firstMonth) < start ? 1 : 0);
  const steps = short ? [1, 2, 3, 4, 6, 12] : [12, 24, 36, 48, 60, 120, 240];
  const count = step => Math.floor(lastMonth / step) - Math.ceil(firstTick / step) + 1;
  const step = steps.find(step => count(step) <= limit) ?? 12 * Math.ceil((lastMonth - firstTick + 12) / (12 * limit));
  const ticks = [];
  for (let month = Math.ceil(firstTick / step) * step; month <= lastMonth; month += step) {
    const date = new Date(monthStamp(month));
    const year = date.getUTCFullYear();
    const index = date.getUTCMonth();
    ticks.push({ stamp: date.getTime(), label: !short || index === 0 ? `${year}年` : `${index + 1}月` });
  }
  return ticks;
}

export function valueAxis(min, max) {
  if (![min, max].every(Number.isFinite) || min > max) return null;
  if (min === max) {
    const pad = Math.max(1, Math.abs(min) * 0.05);
    min -= pad;
    max += pad;
  }
  const span = max - min;
  if (!Number.isFinite(span)) return null;
  const unit = 10 ** Math.floor(Math.log10(span)) || Number.MIN_VALUE;
  const factors = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10];
  const steps = factors.map(factor => factor * unit).filter(step => step > 0 && Number.isFinite(step));
  const intervals = step => Math.ceil(max / step) - Math.floor(min / step);
  const bound = steps.find(step => intervals(step) <= 7);
  if (!bound) return null;
  const clean = value => Number(value.toPrecision(15));
  let bottom = Math.min(min, clean(Math.floor(min / bound) * bound));
  let top = Math.max(max, clean(Math.ceil(max / bound) * bound));
  const firstTick = step => Math.ceil(clean(bottom / step));
  const lastTick = step => Math.floor(clean(top / step));
  let step = steps.find(step => step >= bound && [2, 3].includes(lastTick(step) - firstTick(step)));
  if (!step) {
    step = steps.find(step => intervals(step) <= 3);
    if (!step) return null;
    const first = Math.floor(min / step);
    const last = Math.max(first + 2, Math.ceil(max / step));
    bottom = Math.min(min, clean(first * step));
    top = Math.max(max, clean(last * step));
  }
  if (![bottom, top].every(Number.isFinite) || top <= bottom) return null;
  const first = firstTick(step);
  const ticks = Array.from({ length: lastTick(step) - first + 1 }, (_, i) => clean((first + i) * step));
  return { min: bottom, max: top, ticks };
}

export function symmetricAxis(values) {
  const extent = Array.isArray(values)
    ? values.reduce((max, value) => Number.isFinite(value) ? Math.max(max, Math.abs(value)) : max, 1) : 1;
  const unit = 10 ** Math.floor(Math.log10(extent));
  const max = [1, 2, 2.5, 5, 10].map(factor => factor * unit).find(value => Number.isFinite(value) && value >= extent) ?? extent;
  return { min: -max, max, ticks: [-max, -max / 2, 0, max / 2, max] };
}

const ELEMENT_NAMES = new Map([
  ["dd252", "1年の高値からの下がり幅"],
  ["ma200_dev", "長い目で見た平均(200日)との差"],
  ["ma25_dev", "最近の平均(25日)との差"],
  ["rsi14", "売られすぎ・買われすぎ(RSI)"],
  ["fx_dev", "為替(円高・円安)"],
]);

export function elementName(key) {
  return ELEMENT_NAMES.get(key) ?? "その他の指標";
}

export function zoneDescription(zone) {
  return zone?.comparison ? `過去5年のこの投信の中で、${zone.comparison}水準です。` : "スコアを算出できません。";
}
