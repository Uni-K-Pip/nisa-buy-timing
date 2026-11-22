import { addDays, businessDaysBetween, lastOrderDay, orderSchedule, parseDay } from "./calendar.js";
import { checkPlan, planOrderDeadline } from "./plan.js";
import { button, card, el, facts, fundPicker, getJSON, issueList, number, paragraph,
  percent, probability, selectedFund, table } from "./ui.js";

function quote(value, unit = "") {
  return value ? number(value.value) + unit + "（" + value.date + "／前日比 " + percent(value.change_pct, true) + "）" : "—";
}

function deadlineCopy(deadline, context) {
  if (!deadline) return "算出できません";
  const count = context.calendar ? businessDaysBetween(context.today, deadline, context.calendar) : null;
  const note = count === null ? "" : count < 0 ? "（期限経過）" : "（残り " + count + " 国内営業日）";
  return deadline + note;
}

function todayCard(fund, context) {
  const { score, ml, settlement: params, proxy, nowcast } = fund;
  const meter = Number.isFinite(score.value) ? el("meter", {
    min: 0, max: 100, value: score.value, "aria-label": "買い時スコア",
  }) : null;
  const plans = context.state.plans.filter(plan => plan.fund_id === fund.id);
  const outdated = score.date && context.calendar && businessDaysBetween(score.date, context.today, context.calendar) > 2;
  const year = Number(context.today.slice(0, 4));
  const knownYear = context.calendar && context.calendarYears.includes(year);
  const deadline = knownYear ? lastOrderDay(year, params.settle_bd_from_order, context.calendar,
    params.order_closed_calendars) : params.last_order_date;
  const upcoming = knownYear ? orderSchedule(params, context.calendar) : params.upcoming_orders;
  const estimate = nowcast ? number(nowcast.value) + " 円（米国 " + nowcast.us_date + "／変化 "
    + percent(nowcast.change_pct, true) + "／過去1年の誤差の目安 " + percent(nowcast.error_pct) + "）" : "—";
  return card(
    el("h2", {}, fund.name),
    el("div", { class: "score" }, el("strong", {}, number(score.value)), el("span", {}, score.category_name)),
    meter,
    paragraph(score.comparison + " · 基準日 " + score.date, "secondary"),
    fund.series_kind === "proxy" ? paragraph("円換算した代理系列の過去価格で算出しています。", "notice") : null,
    outdated ? paragraph("価格データの更新が遅れています。基準日を確認してください。", "notice warning") : null,
    score.elements.length ? el("ul", { class: "reasons" },
      ...score.elements.slice(0, 3).map(reason => el("li", {}, reason.description))) : null,
    facts([
      ["公表基準価額", quote(fund.nav, " 円")],
      ["推定基準価額", estimate],
      [proxy.index_label ?? "指数", quote(proxy.index)],
      ["米ドル／円", quote(proxy.fx, " 円")],
      ["年内受渡の最終注文日（推定）", deadlineCopy(deadline, context)],
      ["注文締切（推定）", params.order_cutoff_jst + " JST"],
    ]),
    el("details", {}, el("summary", {}, "今後5回の注文可能日と受渡日（推定）"),
      table(["注文日", "約定日", "受渡日"], upcoming.map(row =>
        [row.order_date, row.trade_date, row.settle_date]))),
    paragraph("締切、約定日、受渡日は公式画面で確認してください。", "secondary"),
    el("h3", {}, "20営業日待てば安く買えた確率 " + probability(ml.probability)),
    ml.valid ? paragraph("有効（過去の検証基準を満たした実験モデル）", "notice")
      : el("h3", { class: "notice warning" }, "無効。 " + ml.note),
    ...fund.status.warnings.map(warning => paragraph(warning, "secondary")),
    ...plans.map(plan => {
      const next = plan.installments.filter(row => row.status === "planned")
        .sort((a, b) => (a.planned_date ?? "9999").localeCompare(b.planned_date ?? "9999"))[0];
      return el("div", {}, el("h3", {}, plan.title || "購入計画"),
        paragraph(next ? "次の回は " + (next.planned_date ?? "予定日未入力") : "未注文の回はありません。"),
        plan.official_last_order_date ? paragraph("入力した公式の最終注文日 " +
          deadlineCopy(planOrderDeadline(plan, params, context.calendar), context)) : null,
        issueList(checkPlan(plan, { ...context, fund })));
    }),
  );
}

export function renderToday(context) {
  const watch = context.funds.filter(fund => context.state.watch.includes(fund.id));
  return [
    context.latest ? paragraph("データ更新 " + context.latest.generated_at.replace("T", " ").slice(0, 16) + " JST", "secondary")
      : paragraph("データを取得できませんでした。通信を確認して開き直してください。", "notice warning"),
    context.latest && !watch.length ? paragraph("設定でウォッチする銘柄を選択できます。") : null,
    ...watch.map(fund => todayCard(fund, context)),
  ];
}

function svgElement(tag, attributes, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text != null) node.textContent = text;
  return node;
}

function priceChart(series, years, plans, kind) {
  const final = series.dates.at(-1);
  if (!final) return paragraph("表示できる価格がありません。");
  const end = parseDay(final);
  const cutoff = years ? parseDay(addDays(final, -Math.round(365.25 * years))) : -Infinity;
  const rows = series.dates.map((day, i) => ({ day, date: parseDay(day), value: series.value[i], score: series.score[i] }))
    .filter(row => row.date >= cutoff);
  const prices = rows.map(row => row.value).filter(Number.isFinite);
  if (!prices.length) return paragraph("表示できる価格がありません。");
  const min = Math.min(...prices), max = Math.max(...prices);
  const x = stamp => 66 + 550 * ((stamp - rows[0].date) / (end - rows[0].date || 1));
  const y = price => 172 - 155 * (max === min ? 0.5 : (price - min) / (max - min));
  const svg = svgElement("svg", { viewBox: "0 0 636 263", class: "chart", role: "img",
    "aria-label": "価格の線、スコアの帯と購入記録" });
  for (const ratio of [0, 0.5, 1]) {
    const top = 172 - 155 * ratio;
    svg.append(svgElement("line", { x1: 66, x2: 616, y1: top, y2: top, class: "grid" }),
      svgElement("text", { x: 60, y: top + 4, "text-anchor": "end" }, number(min + (max - min) * ratio, 0)));
  }
  const path = [];
  let connects = false;
  rows.forEach((row, i) => {
    const cx = x(row.date);
    const nextX = i + 1 < rows.length ? x(rows[i + 1].date) : cx + 1;
    if (Number.isFinite(row.score)) {
      svg.append(svgElement("rect", { x: cx, y: 188, height: 16, width: Math.max(nextX - cx, 0.25),
        class: "band", opacity: 0.14 + 0.86 * row.score / 100 }));
    }
    if (Number.isFinite(row.value)) path.push((connects ? "L" : "M") + cx.toFixed(2) + "," + y(row.value).toFixed(2));
    connects = Number.isFinite(row.value);
  });
  svg.append(svgElement("path", { d: path.join(" "), class: "price" }));
  if (prices.length === 1) {
    const row = rows.find(point => Number.isFinite(point.value));
    svg.append(svgElement("circle", { cx: x(row.date), cy: y(row.value), r: 3, class: "band" }));
  }
  const purchases = plans.flatMap(plan => plan.installments)
    .filter(row => ["ordered", "executed"].includes(row.status))
    .map(row => row.trade_date || row.order_date);
  for (const day of new Set(purchases)) {
    const stamp = parseDay(day);
    if (stamp === null || stamp < rows[0].date || stamp > end) continue;
    const mark = svgElement("line", { x1: x(stamp), x2: x(stamp), y1: 16, y2: 172, class: "purchase" });
    mark.append(svgElement("title", {}, "購入記録 " + day));
    svg.append(mark);
  }
  svg.append(svgElement("text", { x: 66, y: 230 }, rows[0].day),
    svgElement("text", { x: 616, y: 230, "text-anchor": "end" }, final));
  return el("div", {}, svg, paragraph(
    (kind === "nav" ? "価格線は分配金再投資後の基準価額。" : "価格線は円換算の代理系列。")
    + " 帯が濃いほどスコアが高く、破線は端末の購入記録です。", "secondary chart-key"));
}

export function renderChart(context) {
  const fund = selectedFund(context, context.selection.chart);
  if (!fund) return [paragraph("銘柄データがありません。")];
  const { years } = context.selection;
  const chart = el("div", {}, paragraph("系列を読み込んでいます。"));
  getJSON("./data/series/" + encodeURIComponent(fund.id) + ".json").then(series => {
    chart.replaceChildren(priceChart(series, years, context.state.plans.filter(plan => plan.fund_id === fund.id),
      fund.series_kind));
  }).catch(() => chart.replaceChildren(paragraph("系列を取得できませんでした。", "notice warning")));
  return [card(fundPicker(context.funds, fund.id, id => { context.selection.chart = id; context.render(); }),
    el("div", { class: "actions", "aria-label": "表示期間" }, ...[[1, "1年"], [3, "3年"], [0, "全期間"]].map(([span, label]) => {
      const control = button(label, () => { context.selection.years = span; context.render(); });
      control.setAttribute("aria-pressed", String(span === years));
      return control;
    })),
    chart)];
}

function nearestGrid(grid, plan, calendar) {
  const rows = plan?.installments.filter(row => row.status !== "cancelled") ?? [];
  const dates = rows.map(row => row.planned_date).filter(Boolean).sort();
  const window = dates.length && calendar ? businessDaysBetween(dates[0], dates.at(-1), calendar) + 1 : 40;
  const params = { window, count: rows.length || 3, threshold: plan?.threshold_score ?? 70 };
  return grid.reduce((best, row) => {
    const distances = ["window", "count", "threshold"];
    for (const key of distances) {
      const delta = Math.abs(row[key] - params[key]) - Math.abs(best[key] - params[key]);
      if (delta) return delta < 0 ? row : best;
    }
    return best;
  }, grid[0]);
}

function comparison(stats) {
  if (!stats.count) return "比較できる期間がありません。";
  const change = stats.mean < 0 ? "平均 " + percent(-stats.mean) + " 安く"
    : stats.mean > 0 ? "平均 " + percent(stats.mean) + " 高く" : "平均差は 0% で";
  return "過去 " + number(stats.count) + " 回の期間で、定期購入より " + change
    + "、安く買えたのは " + percent(stats.win_rate) + " でした。";
}

function verdict(row) {
  const score = row.score.all;
  const lump = row.lump.all;
  if (!score.count) return "この条件で比べられる過去の期間がありません。";
  const lines = [];
  if (score.mean < 0 && score.win_rate >= 50) {
    lines.push("この条件では、過去はスコアを見て買う方法のほうが定期購入より安く買えた期間が多めでした（平均 "
      + percent(-score.mean) + " 安い）。差は小さく、将来も同じとは限りません。");
  } else {
    lines.push("この条件では、スコアを見て待つ方法が定期購入より有利だったとは言えません（平均 "
      + percent(Math.abs(score.mean)) + (score.mean > 0 ? " 高い" : " 安い") + "、安く買えたのは "
      + percent(score.win_rate) + "）。待つあいだに値上がりすると、かえって高く買うことになります。");
  }
  if (lump.count && lump.mean < 0 && lump.mean < score.mean) {
    lines.push("同じ期間では、初日にまとめて買う方法が平均では最も安くなりました（上昇した期間が多かったため）。");
  }
  return lines.join("");
}

function comparisonBlock(title, result) {
  return card(el("h2", {}, title), paragraph(comparison(result.all)),
    table(["対象", "件数", "平均", "中央値", "勝率", "5%点", "95%点"],
      [["全期間", result.all], ["直近3年", result.recent_3y]].map(([label, row]) =>
        [label, row.count, percent(row.mean, true), percent(row.median, true), percent(row.win_rate),
          percent(row.p05, true), percent(row.p95, true)])));
}

export function renderVerify(context) {
  const fund = selectedFund(context, context.selection.verify);
  if (!fund) return [paragraph("銘柄データがありません。")];
  const plans = context.state.plans.filter(plan => plan.fund_id === fund.id);
  const plan = plans.find(plan => plan.id === context.selection.verifyPlan) ?? plans[0];
  const body = el("div", {}, paragraph("検証結果を読み込んでいます。"));
  const root = "./data/";
  const file = encodeURIComponent(fund.id) + ".json";
  Promise.all([getJSON(root + "backtest/" + file), getJSON(root + "ml/" + file)]).then(([results, model]) => {
    const row = nearestGrid(results.grid, plan, context.calendar);
    body.replaceChildren(
      card(el("h2", {}, row.window + " 営業日 · " + row.count + " 回 · スコア " + row.threshold + " 以上"),
        paragraph(verdict(row), "notice"),
        paragraph(results.description, "secondary")),
      comparisonBlock("スコアを見て買う", row.score),
      comparisonBlock("初日に一括で買う", row.lump),
      comparisonBlock("実験モデルを見て買う（確率 " + probability(results.ml_probability_at_most) + " 以下）", row.ml),
      card(el("h2", {}, "機械学習の検証"),
        model.valid ? paragraph("有効（過去の検証基準を満たしています）", "notice")
          : el("h3", { class: "notice warning" }, fund.ml.note),
        facts([["予測の検証件数", model.count], ["AUC", number(model.auc)], ["Brier", number(model.brier, 4)],
          ["基準 Brier", number(model.baseline_brier, 4)], ["Brier スキル", number(model.brier_skill, 4)]]),
        el("h3", {}, "予測確率と実際の割合（10分位）"),
        table(["確率範囲", "件数", "平均予測", "実際"], model.calibration.map(group =>
          [group.count ? probability(group.lower) + " ～ " + probability(group.upper) : "—", group.count,
            probability(group.mean_probability), probability(group.observed_rate)]))),
    );
  }).catch(() => body.replaceChildren(paragraph("検証結果を取得できませんでした。", "notice warning")));
  const planPicker = plans.length > 1 ? el("select", {}, ...plans.map(item =>
    el("option", { value: item.id, selected: item.id === plan.id }, item.title || "購入計画"))) : null;
  planPicker?.addEventListener("change", () => { context.selection.verifyPlan = planPicker.value; context.render(); });
  return [card(fundPicker(context.funds, fund.id, id => { context.selection.verify = id; context.render(); }),
    planPicker ? el("label", {}, "比較する計画", planPicker) : null,
    paragraph(plan ? "計画の条件に最も近い検証を表示します。" : "既定の条件を表示します。", "secondary")), body];
}
