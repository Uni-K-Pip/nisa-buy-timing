import { businessDaysBetween, lastOrderDay, orderSchedule, parseDay } from "./calendar.js";
import { checkPlan } from "./plan.js";
import { bar, button, card, chip, details, el, emptyState, icon, installmentDots, issueList,
  MODEL_VALID_NOTE, movementChip, number, paragraph, percent, probability, svg, table, zoneLegend, zonePill } from "./ui.js";
import { displayScore, elementName, gaugeArc, gaugePoint, shortDay, ZONES, zoneDescription, zoneOf } from "./visual.js";

export { renderChart } from "./chart.js";
export { renderVerify } from "./verify.js";

const INVALID_MODEL = "過去の検証では偶然と区別できません。参考にしないでください";

function guide(context) {
  const step = (symbol, text) => el("li", {}, icon(symbol), el("span", {}, text));
  return card(el("div", { class: "section-heading" }, el("h2", {}, "はじめての方への案内"),
    button("閉じる", () => {
      context.state.guide_closed = true;
      context.persist();
      context.render();
      document.querySelector("#view-title")?.focus();
    })),
    el("ol", { class: "guide-steps" },
      el("li", {}, icon("gauge"),
        el("div", {}, paragraph("スコアは0〜100。高いほど、過去5年のこの投信の中で安い水準です。"),
          paragraph("朝の更新では、その日の基準価額の見込みを含めて計算します。"), zoneLegend())),
      step("clock", "スコアは過去との比較です。将来の値動きを当てるものではありません。"),
      step("calendar", "「計画」で買う日と金額を決め、「設定」で通知を受け取れます。")));
}

function gauge(value, zone) {
  const point = gaugePoint(value, 140, 132, 106);
  const rounded = displayScore(value);
  const label = zone ? "買い時スコア " + rounded + "、" + zone.name : "買い時スコアは算出できません";
  return el("div", { class: "gauge-block" },
    svg("svg", { viewBox: "0 0 280 170", class: "gauge", role: "img", "aria-label": label },
      ...ZONES.map(item => svg("path", {
        d: gaugeArc(item.min + 0.8, item.max - 0.8, 140, 132, 106),
        class: "gauge-arc " + (zone ? item.key : "no-zone") + (item === zone ? " is-current" : ""),
      })),
      point ? svg("circle", { cx: point.x, cy: point.y, r: 6.5, class: "gauge-marker" }) : null,
      svg("text", { x: 140, y: 116, "text-anchor": "middle", class: "gauge-value" }, rounded),
      svg("text", { x: 140, y: 140, "text-anchor": "middle", class: "gauge-label" }, "/100"),
      svg("text", { x: 36, y: 162, "text-anchor": "middle", class: "gauge-label" }, "割高"),
      svg("text", { x: 244, y: 162, "text-anchor": "middle", class: "gauge-label" }, "割安")),
    zonePill(zone));
}

function scoreChange(score) {
  if (![score.value, score.previous_value].every(Number.isFinite)) return null;
  const delta = score.value - score.previous_value;
  return paragraph(delta === 0 ? "前回と同じスコアです。" : "前回より " +
    (delta > 0 ? "▲" : "▼") + number(Math.abs(delta), 1) + " ポイント（" +
    (delta > 0 ? "割安方向" : "割高方向") + "）", "score-change");
}

function deadlineTiming(deadline, context) {
  if (parseDay(deadline) === null) return null;
  if (deadline < context.today) return { text: "期限経過", urgent: true };
  // 休日の一覧がないときは日数を出さない(ビルド時点の残り日数は、日がたつと多めに出る)。
  const count = context.calendar ? businessDaysBetween(context.today, deadline, context.calendar) : null;
  return Number.isFinite(count) ? { text: "あと " + count + " 営業日", urgent: count <= 5 } : null;
}

function planSummary(plan, context, fund) {
  const next = plan.installments.filter(row => row.status === "planned")
    .sort((a, b) => (a.planned_date ?? "9999").localeCompare(b.planned_date ?? "9999"))[0];
  const official = plan.official_last_order_date;
  const timing = deadlineTiming(official, context);
  return el("section", { class: "inset-panel" }, el("h4", {}, plan.title || "購入計画"),
    paragraph(next ? "次の回 " + (next.planned_date ? shortDay(next.planned_date) : "予定日未入力")
      : "未注文の回はありません。"),
    installmentDots(plan.installments),
    issueList(checkPlan(plan, { ...context, fund })),
    official ? paragraph("入力した公式の最終注文日 " + shortDay(official) +
      (timing ? "（" + timing.text + "）" : ""), "secondary") : null);
}

function deadlineBanner(deadline, params, context) {
  const timing = deadlineTiming(deadline, context);
  return el("section", { class: "inset-panel deadline" + (timing?.urgent ? " warning" : "") },
    el("h3", {}, "年内受渡の最終注文日（推定）"),
    el("div", { class: "deadline-date" },
      el("strong", {}, deadline ? shortDay(deadline) : "算出できません"),
      timing ? chip(timing.text, timing.urgent ? "warning" : "") : null),
    paragraph("推定です。公式画面で確認してください。", "secondary"),
    paragraph("注文締切（推定）" + (params.order_cutoff_jst ? params.order_cutoff_jst + " JST" : "—"), "secondary"),
    paragraph("営業日は国内営業日で数えています。", "secondary"));
}

function scoreBreakdown(elements, score) {
  return el("section", { class: "fund-section" }, el("h3", {}, "なぜこのスコア？"),
    Number.isFinite(score) ? paragraph("棒が長いほど、その見方では安い水準です。スコアの正確な値は " +
      number(score) + " / 100。", "secondary") : null,
    !elements.length ? paragraph("表示できる内訳がありません。", "secondary") : null,
    ...elements.map(({ key, value, percentile, description }) => {
      const cheapness = Number.isFinite(percentile) ? 100 - percentile : null;
      const formatted = key === "rsi14" && Number.isFinite(value) ? value.toFixed(1) : percent(value, true);
      return el("div", { class: "score-element" },
        el("div", { class: "split-heading" }, el("strong", {}, elementName(key)),
          el("span", {}, formatted)),
        bar(cheapness, zoneOf(cheapness)?.key),
        el("div", { class: "bar-labels" }, el("span", {}, "高い"), el("span", {}, "安い")),
        paragraph(description, "secondary"));
    }));
}

function priceTile(label, quote, unit, { estimate = false, digits = 2 } = {}) {
  const hasValue = Number.isFinite(quote?.value);
  const date = estimate ? quote?.us_date : quote?.date;
  return el("div", { class: "inset-panel price-tile" }, el("h4", {}, label),
    el("div", { class: "price-tile-value" },
      el("strong", {}, hasValue ? (estimate ? "約 " : "") + number(quote.value, digits) + unit : "—"),
      hasValue ? movementChip(quote.change_pct) : null),
    hasValue && estimate ? paragraph(
      (date ? "米国 " + shortDay(date) + " の値動きを反映した見込み。" : "米国の値動きを反映した見込み。") +
      "過去1年の誤差の目安 " + (Number.isFinite(quote.error_pct) ? "±" + percent(quote.error_pct) : "—"), "secondary")
      : hasValue ? paragraph(shortDay(date), "secondary") : null);
}

function estimateNote(reading) {
  if (reading.basis !== "estimate") return null;
  const date = parseDay(reading.date) === null ? "" : "（" + shortDay(reading.date) + " の見込み）";
  const confirmed = reading.confirmed;
  return paragraph("推定基準価額を含みます" + date + (confirmed
    ? "。確定値では " + displayScore(confirmed.value) + "（" + shortDay(confirmed.date) + " 時点）"
    : "") + "。", "secondary");
}

function modelSummary(ml) {
  const reading = Number.isFinite(ml.probability) ? ml.probability * 100 : null;
  return el("section", { class: "fund-section" },
    el("h3", { class: "split-heading" }, "機械学習の参考値", chip("実験")),
    ml.valid ? el("div", { class: "notice" },
      paragraph(MODEL_VALID_NOTE),
      el("p", {}, "20営業日待てば安く買えた確率 ", el("strong", {}, probability(ml.probability))),
      estimateNote(ml),
      bar(reading))
      : el("div", {}, el("h3", { class: "notice warning" }, "無効。 " + (ml.note || INVALID_MODEL)),
        paragraph("20営業日待てば安く買えた確率 · 参考値 " + probability(ml.probability), "secondary"),
        estimateNote(ml)));
}

const GLOSSARY = [
  ["基準価額", "投信の1万口あたりの値段。1日1回決まります。"],
  ["推定基準価額", "直近の米国市場と為替から、このアプリが見積もった次回の値です。"],
  ["約定日", "買う値段が決まる日です。"],
  ["受渡日", "代金の受け渡しが済む日です。NISAの年間枠はこの日の年で数えます。"],
  ["国内営業日", "日本の祝日、土日、12/31と1/1〜1/3を除く日です。"],
  ["スコア", "この投信の過去5年の中での安さを0〜100で示した参考指標です。"],
];

function todayCard(fund, context) {
  const score = fund.score ?? {};
  const zone = zoneOf(score.value);
  const params = { ...fund.settlement, order_closed_calendars: fund.settlement?.order_closed_calendars ?? [] };
  const proxy = fund.proxy ?? {};
  const plans = context.state.plans.filter(plan => plan.fund_id === fund.id);
  const outdated = parseDay(score.date) !== null && context.calendar &&
    businessDaysBetween(score.date, context.today, context.calendar) > 2;
  const year = Number(context.today.slice(0, 4));
  const knownYear = context.calendar && context.calendarYears?.includes(year) &&
    Number.isFinite(params.settle_bd_from_order) && Number.isFinite(params.trade_lag_bd);
  const deadline = knownYear ? lastOrderDay(year, params.settle_bd_from_order, context.calendar,
    params.order_closed_calendars) : params.last_order_date;
  const upcoming = (knownYear ? orderSchedule(params, context.calendar) : params.upcoming_orders) ?? [];
  return card(
    el("div", { class: "section-heading" }, el("h2", {}, fund.name),
      chip(shortDay(score.date) + (score.date ? " 時点" : ""), "date-chip")),
    outdated ? paragraph("価格データの更新が遅れています。基準日を確認してください。", "notice warning") : null,
    gauge(score.value, zone),
    el("div", { class: "score-summary" }, estimateNote(score), paragraph(zoneDescription(zone)), scoreChange(score),
      paragraph((score.comparison ? score.comparison + "。 " : "") + "将来の値動きを示すものではありません。", "secondary")),
    fund.series_kind === "proxy" ? paragraph("円換算した代理系列の過去価格で算出しています。", "notice") : null,
    plans.length ? el("section", { class: "fund-section" }, el("h3", {}, "この銘柄の計画"),
      ...plans.map(plan => planSummary(plan, context, fund))) : null,
    deadlineBanner(deadline, params, context),
    scoreBreakdown(score.elements ?? [], score.value),
    el("section", { class: "fund-section" }, el("h3", {}, "いまの価格"),
      paragraph("▲／▼は前日比。推定基準価額は公表基準価額からの変化です。", "secondary"),
      el("div", { class: "price-tiles" }, priceTile("公表基準価額", fund.nav, "円"),
        priceTile("推定基準価額", fund.nowcast, "円", { estimate: true, digits: 0 }),
        priceTile(proxy.index_label ?? "指数", proxy.index, ""), priceTile("米ドル／円", proxy.fx, "円"))),
    details("今後5回の注文できる日（推定）", [
      table(["注文日", "約定日", "受渡日"], upcoming.map(row => [row.order_date, row.trade_date, row.settle_date])),
      paragraph("締切、約定日、受渡日は公式画面で確認してください。", "secondary"),
    ], context.selection, fund.id + ":orders"),
    modelSummary(fund.ml ?? {}),
    ...(fund.status?.warnings ?? []).map(warning => paragraph(warning, "secondary")),
    details("用語の説明", [el("dl", { class: "glossary" }, ...GLOSSARY.flatMap(([term, description]) =>
      [el("dt", {}, term), el("dd", {}, description)]))], context.selection, fund.id + ":glossary"));
}

export function renderToday(context) {
  const watch = context.funds.filter(fund => context.state.watch.includes(fund.id));
  const stamp = context.latest?.generated_at;
  return [
    context.latest ? paragraph("データ更新 " + (stamp ? stamp.replace("T", " ").slice(0, 16) + " JST" : "—"), "secondary")
      : paragraph("データを取得できませんでした。通信を確認して開き直してください。", "notice warning"),
    context.state.guide_closed ? null : guide(context),
    context.latest && !watch.length ? emptyState("gauge", "ウォッチ中の銘柄がありません",
      "設定でウォッチする銘柄を選ぶと、ここにスコアが出ます。") : null,
    ...watch.map(fund => todayCard(fund, context)),
  ];
}
