import { addDays, parseDay } from "./calendar.js";
import { cachedJSON, isPurchased, card, el, number, paragraph, responsiveFigure,
  segmented, selectedFund, svg, zoneLegend } from "./ui.js";
import { clampPercent, displayScore, shortDay, timeTicks, valueAxis, ZONES, zoneOf } from "./visual.js";

const spans = [[1, "1年"], [3, "3年"], [0, "全期間"]];

function nearestRow(rows, stamp) {
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (rows[mid].stamp < stamp) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && stamp - rows[lo - 1].stamp <= rows[lo].stamp - stamp ? lo - 1 : lo;
}

function reading(row) {
  const zone = zoneOf(row.score);
  const price = Number.isFinite(row.value) ? number(row.value) + "円" : "—";
  return row.day + " · " + price + " · スコア " +
    (zone ? displayScore(row.score) + "（" + zone.name + "）" : "算出できません");
}

// latest は、価格がある最後の行の位置。系列の末尾には、指数だけが先に入った日(価格がまだない日)が付くことがある。
function chartDrawing(rows, ticks, purchases, rangeLabel, output, width, latest) {
  const start = rows[0].stamp;
  const end = rows.at(-1).stamp;
  const duration = end - start;
  const axisLabel = value => number(value, 5);
  const left = Math.max(46, Math.max(...ticks.ticks.map(value => axisLabel(value).length)) * 7 + 7);
  const right = width - 15;
  const priceTop = 27, priceBottom = 201;
  const scoreTop = 222, scoreBottom = 290;
  const height = 314;
  const x = stamp => duration ? left + (right - left) * ((stamp - start) / duration) : (left + right) / 2;
  const priceY = value => priceBottom - (priceBottom - priceTop) * ((value - ticks.min) / (ticks.max - ticks.min));
  const scoreY = value => scoreBottom - (scoreBottom - scoreTop) * (clampPercent(value) / 100);
  const label = rangeLabel + "（" + rows[0].day + "〜" + rows.at(-1).day +
    "）の価格、スコアと購入記録。最新 " + reading(rows[latest]) + "。左右キーで日付を選べます。";
  const chart = svg("svg", { viewBox: "0 0 " + width + " " + height, width, height, class: "diagram interactive-chart",
    role: "img", tabindex: "0", "aria-label": label });
  const horizontal = (y, className) => svg("line", { x1: left, x2: right, y1: y, y2: y, class: className });

  for (const tick of ticks.ticks) {
    const y = priceY(tick);
    chart.append(horizontal(y, "grid"),
      svg("text", { x: left - 5, y: y + 4, "text-anchor": "end" }, axisLabel(tick)));
  }
  for (const zone of ZONES) {
    const top = scoreY(zone.max);
    chart.append(svg("rect", { x: left, y: top, width: right - left,
      height: scoreY(zone.min) - top, class: "score-band " + zone.key }));
    if (zone.min) chart.append(horizontal(scoreY(zone.min), "grid"));
  }
  chart.append(horizontal(scoreTop, "grid"), horizontal(scoreBottom, "grid"),
    svg("text", { x: left - 5, y: scoreTop + 6, "text-anchor": "end" }, "割安"),
    svg("text", { x: left - 5, y: scoreBottom, "text-anchor": "end" }, "割高"));

  const labels = timeTicks(start, end, Math.max(2, Math.min(7, Math.floor((right - left) / 55))));
  if (!labels.length) labels.push({ stamp: end, label: shortDay(rows.at(-1).day) });
  for (const tick of labels) {
    const tickX = x(tick.stamp);
    const labelX = Math.max(22, Math.min(width - 22, tickX));
    chart.append(svg("line", { x1: tickX, x2: tickX, y1: scoreBottom, y2: scoreBottom + 4, class: "grid" }),
      svg("text", { x: labelX, y: height - 5, "text-anchor": "middle" }, tick.label));
  }

  const paths = new Map();
  const scorePath = [];
  let lastPrice;
  rows.forEach((row, i) => {
    const previous = rows[i - 1];
    const next = rows[i + 1];
    const px = x(row.stamp);
    if (Number.isFinite(row.value)) {
      lastPrice = row;
      const py = priceY(row.value);
      const zone = zoneOf(row.score);
      const connects = Number.isFinite(previous?.value);
      const isolated = !connects && !Number.isFinite(next?.value);
      if (connects || isolated) {
        const key = zone?.key ?? "no-zone";
        if (!paths.has(key)) paths.set(key, []);
        const from = connects ? x(previous.stamp) + " " + priceY(previous.value) : px + " " + py;
        paths.get(key).push("M " + from + " L " + px + " " + py);
      }
    }
    if (Number.isFinite(row.score)) {
      const command = Number.isFinite(previous?.score) ? "L " : "M ";
      scorePath.push(command + px + " " + scoreY(row.score));
      if (command === "M " && !Number.isFinite(next?.score)) scorePath.push("l 0 0");
    }
  });
  for (const [key, parts] of paths) {
    chart.append(svg("path", { d: parts.join(" "), class: "plot-line " + key }));
  }
  chart.append(svg("path", { d: scorePath.join(" "), class: "plot-line score-line" }));

  const marked = new Set(purchases);
  for (const day of marked) {
    const stamp = parseDay(day);
    if (stamp === null || stamp < start || stamp > end) continue;
    const px = x(stamp);
    chart.append(svg("g", { class: "purchase" }, svg("title", {}, "購入記録 " + day),
      svg("line", { x1: px, x2: px, y1: 20, y2: scoreBottom }),
      svg("text", { x: px, y: 14, "text-anchor": "middle" }, "買")));
  }

  const latestX = x(lastPrice.stamp);
  const latestY = priceY(lastPrice.value);
  const nearLeft = latestX < left + 65;
  chart.append(svg("circle", { cx: latestX, cy: latestY, r: 4, class: "plot-dot" }),
    svg("text", { x: latestX + (nearLeft ? 8 : -8), y: latestY - 7, "text-anchor": nearLeft ? "start" : "end",
      class: "charted-value" }, number(lastPrice.value) + "円"));

  const cursor = svg("g", { "aria-hidden": "true" });
  chart.append(cursor);
  let selected = latest;
  function choose(index, inspecting) {
    selected = index;
    const row = rows[index];
    output.textContent = reading(row);
    const px = x(row.stamp);
    cursor.replaceChildren();
    if (!inspecting) return;
    cursor.append(svg("line", { x1: px, x2: px, y1: priceTop, y2: scoreBottom, class: "crosshair" }));
    if (Number.isFinite(row.value)) cursor.append(svg("circle", { cx: px, cy: priceY(row.value), r: 4, class: "plot-dot" }));
    if (Number.isFinite(row.score)) cursor.append(svg("circle", { cx: px, cy: scoreY(row.score), r: 4, class: "plot-dot" }));
  }

  function fromPointer(event) {
    const rect = chart.getBoundingClientRect();
    if (!rect.width) return;
    const px = (event.clientX - rect.left) * width / rect.width;
    choose(nearestRow(rows, start + duration * ((px - left) / (right - left))), true);
  }

  chart.addEventListener("pointerdown", fromPointer);
  chart.addEventListener("pointermove", fromPointer);
  const reset = () => choose(latest, false);
  // タッチでは指を離すと pointerleave が来る。選んだ日を読めるように残し、マウスが外れたときだけ最新に戻す。
  chart.addEventListener("pointerleave", event => { if (event.pointerType === "mouse") reset(); });
  chart.addEventListener("blur", reset);
  chart.addEventListener("keydown", event => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    choose(Math.max(0, Math.min(rows.length - 1, selected + (event.key === "ArrowLeft" ? -1 : 1))), true);
  });
  reset();
  return chart;
}

function priceChart(series, years, plans, kind, signal) {
  const dates = series.dates ?? [];
  const final = dates.at(-1);
  const cutoff = years && parseDay(final) !== null ? parseDay(addDays(final, -Math.round(365.25 * years))) : -Infinity;
  const rows = dates.map((day, i) => ({ day, stamp: parseDay(day), value: series.value?.[i], score: series.score?.[i] }))
    .filter(row => row.stamp !== null && row.stamp >= cutoff);
  const latest = rows.findLastIndex(row => Number.isFinite(row.value));
  const prices = rows.map(row => row.value).filter(Number.isFinite);
  const axis = valueAxis(Math.min(...prices), Math.max(...prices));
  if (!axis) return paragraph("表示できる価格がありません。");
  const purchases = plans.flatMap(plan => plan.installments.filter(isPurchased).map(row => row.trade_date || row.order_date));
  const rangeLabel = spans.find(([span]) => span === years)?.[1] ?? "全期間";
  const output = paragraph(reading(rows[latest]), "chart-reading");
  output.setAttribute("aria-live", "polite");
  return el("div", {},
    output, responsiveFigure(width => chartDrawing(rows, axis, purchases, rangeLabel, output, width, latest), signal),
    zoneLegend(),
    el("p", { class: "chart-key secondary" }, el("span", { class: "dash-key", "aria-hidden": "true" }),
      "破線 = この端末の購入記録"),
    paragraph(kind === "nav" ? "価格線は分配金再投資後の基準価額。" : "価格線は円換算の代理系列。", "secondary"));
}

export function renderChart(context) {
  const fund = selectedFund(context, context.selection.chart);
  if (!fund) return [paragraph("銘柄データがありません。")];
  const { years } = context.selection;
  const signal = context.renderSignal;
  const chart = el("div", {}, paragraph("系列を読み込んでいます。"));
  cachedJSON(context, "./data/series/" + encodeURIComponent(fund.id) + ".json").then(series => {
    if (signal?.aborted) return;
    chart.replaceChildren(priceChart(series, years, context.state.plans.filter(plan => plan.fund_id === fund.id),
      fund.series_kind, signal));
  }).catch(() => chart.replaceChildren(paragraph("系列を取得できませんでした。", "notice warning")));
  return [card(
    segmented("銘柄", context.funds.map(item => [item.id, item.short_name ?? item.name]), fund.id,
      id => { context.selection.chart = id; context.render(); }),
    paragraph(fund.name, "secondary"),
    segmented("表示期間", spans, years, span => { context.selection.years = span; context.render(); }),
    chart)];
}
