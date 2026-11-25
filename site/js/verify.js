import { businessDaysBetween } from "./calendar.js";
import { cachedJSON, card, chip, details, el, facts, field, fundPicker, MODEL_VALID_NOTE, number, paragraph, percent,
  probability, responsiveFigure, segmented, selectedFund, svg, table } from "./ui.js";
import { clampPercent, evidenceHeading, evidenceStatus, intervalText, isPrimaryCondition, modelMetric, percentagePoints,
  signedPercent, signedPoints, symmetricAxis } from "./visual.js";

const PERIODS = [["all", "全期間"], ["nav", "基準価額のある期間"], ["recent_3y", "直近3年"]];
const COMPARISONS = [
  { id: "regular", short: "対定期", label: "決めた日に分けて買う（定期購入）", format: signedPercent },
  { id: "lump", short: "対一括", label: "初日に一括で買う", stat: "vs_lump", format: signedPercent },
  { id: "placebo", short: "対偽シグナル", label: "待ち方だけをまねた買い方（偽シグナル）", stat: "vs_placebo",
    format: signedPoints },
];
const NO_FORWARD = "まだ集計できる期間がありません（最初の期間が終わるのは、基準日のおよそ 2 か月後です）。";

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
  if (!stats?.count) return "比較できる期間がありません。";
  if (!Number.isFinite(stats.mean)) return "平均差は算出できません。";
  const change = stats.mean < 0 ? "平均 " + percent(-stats.mean) + " 安く"
    : stats.mean > 0 ? "平均 " + percent(stats.mean) + " 高く" : "平均差は 0% で";
  return "過去 " + number(stats.count) + " 回の期間で、定期購入より " + change
    + "、安く買えたのは " + percent(stats.win_rate) + " でした。";
}

function evidenceLabel(heading, comparison, status) {
  return el(heading, { class: "evidence-label" }, comparison.label,
    status ? chip(status.label, "evidence-chip " + status.tone) : null);
}

function averageInterval(stats, format) {
  return paragraph("平均 " + format(stats?.mean) + " ／ 95% 区間 " + intervalText(stats?.ci, format));
}

function verdictCard(row, strategy, period) {
  const primary = strategy?.primary;
  if (!primary) return null;
  const active = isPrimaryCondition(row, primary);
  const comparisons = strategy.comparisons;
  const stats = row.score?.[period];
  return card(el("div", { class: "notice verdict" },
    el("h2", {}, active ? evidenceHeading(comparisons) : "参考（判定には使いません）"),
    paragraph(active ? "状態は、対象期間を切り替えても変わりません。"
      : "判定は主条件（期間 " + number(primary.window, 0) + " 日・" + number(primary.count, 0)
        + " 回・閾値 " + number(primary.threshold, 0) + "）だけで行います。", "secondary"),
    paragraph(active ? "基準日までに約定が終わった、探索に使った過去データでのスコア戦略の結果です。"
      : "表示中の期間には、探索に使った過去データを含みます。", "secondary"),
    ...COMPARISONS.map(item => {
      const result = comparisons?.[item.id];
      const status = evidenceStatus(result?.status);
      const values = active ? result?.history : item.stat ? stats?.[item.stat] : stats;
      return el("section", { class: "evidence-comparison" }, evidenceLabel("h3", item, active ? status : null),
        active && status ? paragraph(status.description) : null, averageInterval(values, item.format));
    }),
    paragraph("過去の結果であり、将来も同じとは限りません。", "secondary")));
}

function strategyDetails(strategy, period, selection, key, hasComparisons) {
  const { title, result, lump } = strategy;
  const stats = result?.[period];
  return el("section", { class: "strategy-details" }, el("h3", {}, title),
    hasComparisons ? el("div", { class: "comparison-table" },
      table(["比較相手", "平均", "95% 区間", "安く買えた割合", "件数"],
        (lump ? COMPARISONS.slice(0, 1) : COMPARISONS).map(({ short, id, stat, format }) => {
          const values = stat ? stats?.[stat] : stats;
          // 全期間に重ならない3期間があれば、どの期間にも重ならない比較先がある。
          // それより少ない場合、偽シグナル固有の件数はグリッドの集計からは分からない。
          const counts = id === "placebo" && !(result?.all?.independent >= 3) && stats?.count !== 0 ? values : stats;
          return [short, format(values?.mean), intervalText(values?.ci, format), percent(values?.win_rate),
            values && counts?.count != null ? number(counts.count, 0) + "（" + number(counts.independent, 0) + "）" : "—"];
        }))) : null,
    Number.isFinite(stats?.delay) ? paragraph(stats.delay === 0 ? "定期購入との購入日の差は平均 0 日でした。"
      : "定期購入より平均 " + number(Math.abs(stats.delay)) + " 日"
        + (stats.delay < 0 ? "早く" : "遅く") + "買った結果です。", "secondary") : null,
    details("詳しい数値", [table(["対象", "件数", "平均", "中央値", "勝率", "5%点", "95%点"],
      PERIODS.filter(([id]) => result?.[id]).map(([id, label]) => {
        const row = result[id];
        return [label, row.count, percent(row.mean, true), percent(row.median, true), percent(row.win_rate),
          percent(row.p05, true), percent(row.p95, true)];
      }))], selection, key));
}

function winCopy(stats) {
  return "安く買えたのは " + percent(stats.win_rate) + "（" + number(stats.count, 0) + " 回中）";
}

function strategyFigure(strategies, period, width) {
  const rows = strategies.map(item => item.result?.[period] ?? {});
  const { max, ticks } = symmetricAxis(rows.flatMap(stats => [stats.p05, stats.p95, stats.mean, stats.median]));
  const padding = 24;
  const inner = width - 2 * padding;
  const x = value => padding + inner * (0.5 + (value / max) / 2);
  const height = 398;
  const chart = svg("svg", { class: "diagram", viewBox: "0 0 " + width + " " + height, width, height,
    role: "img", "aria-label": "定期購入を0%とした平均取得単価の比較。 " + strategies.map(({ title }, i) => {
      const stats = rows[i];
      return title + "。 " + comparison(stats) + (stats.count ? " 中央値 " + percent(stats.median, true) +
        "、5%点から95%点 " + percent(stats.p05, true) + "〜" + percent(stats.p95, true) + "。" : "");
    }).join(" ") });
  chart.append(svg("text", { x: padding, y: 13 }, "安く買えた"),
    svg("text", { x: width - padding, y: 13, "text-anchor": "end" }, "高く買った"),
    svg("line", { x1: padding, x2: width - padding, y1: 23, y2: 23, class: "grid" }));
  for (const tick of ticks) {
    chart.append(svg("line", { x1: x(tick), x2: x(tick), y1: 20, y2: 26, class: tick ? "grid" : "zero-line" }),
      svg("text", { x: x(tick), y: 39, "text-anchor": "middle" }, percent(tick, true)));
  }

  strategies.forEach(({ label, subtitle }, i) => {
    const stats = rows[i];
    const top = 66 + i * 114;
    const caption = svg("text", { x: padding, y: top, class: "figure-title" }, label);
    if (subtitle) caption.append(svg("tspan", { x: padding, dy: 15 }, subtitle));
    chart.append(caption);
    if (Number.isFinite(stats.mean) && stats.count) {
      chart.append(svg("text", { x: width - padding, y: top, "text-anchor": "end", class: "figure-title" },
        "平均 " + percent(stats.mean, true)));
    }
    const y = top + 37;
    if (!stats.count) {
      chart.append(svg("text", { x: padding, y: y + 5 }, "比較できる期間がありません"));
      return;
    }
    chart.append(
      svg("line", { x1: padding, x2: width - padding, y1: y, y2: y, class: "grid" }),
      svg("line", { x1: x(0), x2: x(0), y1: y - 14, y2: y + 14, class: "zero-line" }));
    const color = stats.mean < 0 ? "cheap" : stats.mean > 0 ? "expensive" : "neutral";
    const markers = svg("g", { class: "interval " + color });
    if ([stats.p05, stats.p95].every(Number.isFinite)) {
      markers.append(svg("line", { x1: x(stats.p05), x2: x(stats.p95), y1: y, y2: y, class: "interval-range" }));
    }
    if (Number.isFinite(stats.mean)) markers.append(svg("circle", { cx: x(stats.mean), cy: y, r: 6.5, class: "interval-mean" }));
    if (Number.isFinite(stats.median)) markers.append(svg("line", {
      x1: x(stats.median), x2: x(stats.median), y1: y - 10, y2: y + 10, class: "interval-median",
    }));
    chart.append(markers);
    const barY = top + 73;
    const middle = { x1: x(0), x2: x(0), y1: barY - 2, y2: barY + 10 };
    chart.append(svg("text", { x: padding, y: barY - 5 }, winCopy(stats)),
      svg("rect", { x: padding, y: barY, width: inner, height: 8, rx: 4, class: "win-track" }),
      svg("rect", { x: padding, y: barY, width: inner * (Number.isFinite(stats.win_rate) ?
        clampPercent(stats.win_rate) / 100 : 0), height: 8, rx: 4, class: "win-fill" }),
      svg("line", { ...middle, class: "win-midpoint-edge" }),
      svg("line", { ...middle, class: "win-midpoint" }));
  });
  return chart;
}

function calibrationFigure(groups, width) {
  const height = 221;
  const left = 45, right = width - 24, top = 35, bottom = 178;
  const x = value => left + (right - left) * value;
  const y = value => bottom - (bottom - top) * value;
  const chart = svg("svg", { class: "diagram", viewBox: "0 0 " + width + " " + height, width, height,
    role: "img", "aria-label": "予測した確率と実際の割合の較正図。点が対角線に近いほど予測が当たっていました。数値は詳しい数値で確認できます。" });
  for (const tick of [0, 0.5, 1]) {
    chart.append(svg("line", { x1: left, x2: right, y1: y(tick), y2: y(tick), class: "grid" }),
      svg("line", { x1: x(tick), x2: x(tick), y1: top, y2: bottom, class: "grid" }),
      svg("text", { x: left - 5, y: y(tick) + 4, "text-anchor": "end" }, probability(tick)),
      svg("text", { x: x(tick), y: bottom + 17, "text-anchor": "middle" }, probability(tick)));
  }
  chart.append(svg("text", { x: left, y: 16 }, "実際の割合"),
    svg("text", { x: (left + right) / 2, y: height - 4, "text-anchor": "middle" }, "予測した確率"),
    svg("line", { x1: left, x2: right, y1: bottom, y2: top, class: "ideal" }),
    svg("text", { x: right - 2, y: top - 8, "text-anchor": "end" }, "理想"));
  const points = groups.filter(group => [group.mean_probability, group.observed_rate].every(Number.isFinite))
    .map(group => ({ x: x(group.mean_probability), y: y(group.observed_rate), group }));
  chart.append(svg("polyline", { points: points.map(point => point.x + "," + point.y).join(" "), class: "plot-line score-line" }),
    ...points.map(point => svg("circle", { cx: point.x, cy: point.y, r: 4, class: "calibration-dot" },
      svg("title", {}, "予測 " + probability(point.group.mean_probability) + "／実際 " + probability(point.group.observed_rate)))));
  return chart;
}

function forwardComparison(item, result, allEmpty, level) {
  const status = evidenceStatus(result.status);
  const { forward, judgment } = result;
  return el("section", { class: "evidence-comparison" },
    evidenceLabel("h4", item, status),
    status ? paragraph(status.description, "secondary") : null,
    forward?.count ? paragraph("件数 " + number(forward.count, 0) + "（重ならない期間 "
      + number(forward.independent, 0) + "）") : null,
    forward?.count ? averageInterval(forward, item.format) : null,
    !allEmpty && forward?.count === 0 ? paragraph(NO_FORWARD, "secondary") : null,
    judgment ? el("div", { class: "inset-panel" },
      el("p", {}, el("strong", {}, "判定日 " + (judgment.look ?? "—"))),
      facts([["件数", number(judgment.count, 0)], ["重ならない期間", number(judgment.independent, 0)],
        ["平均", item.format(judgment.mean)],
        ["補正後の区間（" + probability(judgment.level ?? level) + "）", intervalText(judgment.ci, item.format)],
        ["t 区間（同じ水準）", intervalText(judgment.t_ci, item.format)]]),
      paragraph(judgment.passed === true ? "基準を満たしました。"
        : judgment.passed === false ? "基準を満たしませんでした。" : "判定結果はありません。")) : null);
}

function forwardStrategy(title, strategy, protocol) {
  if (!strategy) return null;
  const { version, registered, primary, looks, comparisons } = strategy;
  const available = COMPARISONS.filter(item => comparisons?.[item.id]);
  const allEmpty = available.length > 0 && available.every(({ id }) => comparisons[id].forward?.count === 0);
  const years = comparisons?.regular?.forward?.years;
  return el("section", { class: "strategy-details" }, el("h3", {}, title),
    primary ? paragraph("主条件は期間 " + number(primary.window, 0) + " 日、" + number(primary.count, 0)
      + " 回、" + (Number.isFinite(primary.probability_at_most)
        ? "確率 " + probability(primary.probability_at_most) + " 以下"
        : "スコア " + number(primary.threshold, 0) + " 以上") + "です。", "secondary") : null,
    facts([["版", version], ["基準日", registered], ["次の判定日", looks?.next],
      ["判定の水準", probability(protocol?.level)], ["実用的な改善幅", percent(protocol?.practical_margin_pct)],
      ["基準日からの経過", Number.isFinite(years) ? number(years) + " 年" : "—"]]),
    looks?.closed === true ? paragraph("この版の前向き検証は終了しました。", "notice") : null,
    allEmpty ? paragraph(NO_FORWARD, "secondary") : null,
    ...available.map(item => forwardComparison(item, comparisons[item.id], allEmpty, protocol?.level)));
}

function forwardCard(evidence, selection, key) {
  const { strategies, protocol } = evidence ?? {};
  if (!strategies?.score && !strategies?.ml) return null;
  const lookYears = protocol?.looks_years?.filter(Number.isFinite) ?? [];
  return card(el("h2", {}, "条件を固定したあとのデータでの確認"),
    paragraph("条件を固定したあとの未使用データを集計しています。集計の途中経過で、判定は決められた日にだけ行います。"),
    forwardStrategy("スコア戦略", strategies.score, protocol),
    forwardStrategy("ML 戦略", strategies.ml, protocol),
    protocol ? details("判定の決まり", [
      lookYears.length ? paragraph("判定日は基準日の " + lookYears.join("、") + " 年後の "
        + number(lookYears.length, 0) + " 回だけです。") : null,
      paragraph("基準日から " + number(protocol.min_forward_years, 0) + " 年以上が経過し、重ならない期間が "
        + number(protocol.min_independent_windows, 0) + " 個以上必要です。この件数は下限です。"),
      paragraph("平均の改善が " + percent(protocol.practical_margin_pct)
        + " 以上で、補正後の水準の区間と同じ水準の t 区間がともにゼロより下なら、前向き検証の基準を満たします。"),
    ], selection, key + ":protocol") : null);
}

function scoreImpactDetails(impact, selection, key) {
  if (!impact) return null;
  const { primary } = impact;
  return details("推定誤差の影響", [
    paragraph("基準価額のある期間で、推定を含むスコアと確定値でのスコアを比べました。", "secondary"),
    facts([["比較した日数", number(impact.days, 0)], ["スコアの差の大きさ（平均）", number(impact.score_abs_diff_mean)],
      ["スコアの差の大きさ（95%点）", number(impact.score_abs_diff_p95)],
      ["区分が食い違う日の割合", percent(impact.category_mismatch_rate)],
      ["70 以上かどうかが食い違う日の割合", percent(impact.threshold_mismatch_rate)]]),
    primary ? el("h3", {}, "主条件の対定期の平均") : null,
    primary ? facts([["推定を含む場合", signedPercent(primary.with_estimate)],
      ["確定値の場合", signedPercent(primary.with_confirmed)], ["差（推定 − 確定）", signedPoints(primary.difference)]]) : null,
  ], selection, key + ":score-impact");
}

function gridSummaryDetails(summary, selection, key) {
  if (!summary?.score) return null;
  return details("グリッドの要約", [
    paragraph("スコア戦略の全期間で、95% 区間を出せた条件を数えています。区間がゼロをまたがない条件は、偶然でも 5% 前後は出ます。", "secondary"),
    ...COMPARISONS.filter(({ id }) => summary.score[id]).map(({ id, label }) => {
      const { total, favorable, unfavorable } = summary.score[id];
      return el("section", {}, el("h3", {}, label),
        paragraph(number(total, 0) + " 条件のうち、区間がゼロより下が " + number(favorable, 0)
          + "、上が " + number(unfavorable, 0) + "。"));
    }),
  ], selection, key + ":grid");
}

function modelImpactDetails(impact, selection, key) {
  if (!impact) return null;
  return details("推定誤差の影響", [
    paragraph("基準価額のある期間で、推定を含む予測と確定値での予測を比べました。", "secondary"),
    facts([["予測確率の差の大きさ（平均）", percentagePoints((impact.prob_abs_diff_mean ?? NaN) * 100)],
      ["予測確率の差の大きさ（95%点）", percentagePoints((impact.prob_abs_diff_p95 ?? NaN) * 100)]]),
    table(["使った値", "AUC", "Brier スキル"], [
      ["推定を含む値", number(impact.auc_estimate, 4), number(impact.brier_skill_estimate, 4)],
      ["確定値", number(impact.auc_confirmed, 4), number(impact.brier_skill_confirmed, 4)],
    ]),
  ], selection, key + ":model-impact");
}

function modelCard(model, note, context, key, signal) {
  if (!model) return null;
  const groups = (model.calibration ?? []).filter(Boolean);
  const { forward } = model;
  return card(el("h2", {}, "機械学習の検証"),
    model.valid ? paragraph(MODEL_VALID_NOTE, "notice")
      : el("h3", { class: "notice warning" }, note || "過去の検証では偶然と区別できません。参考にしないでください"),
    el("h3", {}, "予測確率と実際の割合（10分位）"),
    groups.some(group => group.count) ? el("div", { class: "calibration" },
      responsiveFigure(width => calibrationFigure(groups, width), signal)) : paragraph("較正に使える検証結果がありません。"),
    paragraph("点が対角線に近いほど、予測が当たっていたことを示します。", "secondary"),
    details("詳しい数値", [
      facts([["予測の検証件数", number(model.count, 0)],
        ...("independent" in model ? [["重ならない予測期間", number(model.independent, 0)]] : []),
        ["AUC", modelMetric(model.auc)],
        ...("auc_ci" in model ? [["AUC の 95% 区間", intervalText(model.auc_ci, modelMetric)]] : []),
        ["Brier", modelMetric(model.brier)], ["基準 Brier", modelMetric(model.baseline_brier)],
        ["Brier スキル", modelMetric(model.brier_skill)],
        ...("brier_skill_ci" in model ? [["Brier スキルの 95% 区間", intervalText(model.brier_skill_ci, modelMetric)]] : [])]),
      table(["確率範囲", "件数", "平均予測", "実際"], groups.map(group =>
        [group.count ? probability(group.lower) + " ～ " + probability(group.upper) : "—", group.count,
          probability(group.mean_probability), probability(group.observed_rate)])),
    ], context.selection, key + ":model"),
    forward ? el("section", { class: "strategy-details" }, el("h3", {}, "基準日より後の予測"),
      forward.count === 0 ? paragraph("まだありません（0 件）。", "secondary") : facts([
        ["件数", number(forward.count, 0)],
        ["AUC", modelMetric(forward.auc)], ["AUC の 95% 区間", intervalText(forward.auc_ci, modelMetric)],
        ["Brier スキル", modelMetric(forward.brier_skill)],
        ["Brier スキルの 95% 区間", intervalText(forward.brier_skill_ci, modelMetric)],
      ])) : null,
    modelImpactDetails(model.estimate_impact, context.selection, key));
}

function comparisonCard(results, row, period, selection, key, signal) {
  const subtitle = Number.isFinite(results?.ml_probability_at_most)
    ? "（確率 " + probability(results.ml_probability_at_most) + " 以下）" : "";
  const strategies = [
    { label: "スコアを見て買う", result: row?.score },
    { label: "初日に一括で買う", result: row?.lump, lump: true },
    { label: "実験モデルを見て買う", subtitle, result: row?.ml },
  ].map(strategy => ({ ...strategy, title: strategy.label + (strategy.subtitle ?? "") }));
  return card(el("h2", {}, "買い方を比べる"),
    row ? el("div", {},
      paragraph("表示中の期間には、探索に使った過去データを含みます。", "secondary"),
      paragraph("決めた日に分けて買う（定期購入）を 0% とした、平均取得単価の差です。"),
      paragraph("横線は5%点〜95%点、●は平均、縦の小線は中央値です。割合の棒の印は50%です。", "secondary"),
      responsiveFigure(width => strategyFigure(strategies, period, width), signal),
      results.schema === 2 ? paragraph("偽シグナルは、同じように待ちながらスコアや予測確率とは無関係な日に買い、日を選ぶ指標に情報があるかを調べるための比較相手です。", "secondary") : null,
      results.schema === 2 ? paragraph("負の差は、比較相手より安く買えたことを示します。pt はパーセントポイントです。件数の括弧内は重ならない期間の数です。", "secondary") : null,
      ...strategies.filter(({ result }) => result).map(strategy =>
        strategyDetails(strategy, period, selection, key + ":strategy:" + strategy.label, results.schema === 2)))
      : paragraph("この条件で比べられる過去の期間がありません。"),
    scoreImpactDetails(results?.estimate_impact, selection, key),
    gridSummaryDetails(results?.grid_summary, selection, key),
    results?.description ? details("検証の方法", [paragraph(results.description, "secondary")], selection, key + ":method") : null);
}

export function renderVerify(context) {
  const fund = selectedFund(context, context.selection.verify);
  if (!fund) return [paragraph("銘柄データがありません。")];
  const plans = context.state.plans.filter(plan => plan.fund_id === fund.id);
  const plan = plans.find(item => item.id === context.selection.verifyPlan) ?? plans[0];
  const period = context.selection.verifyPeriod ?? "all";
  const signal = context.renderSignal;
  const body = el("div", {}, paragraph("検証結果を読み込んでいます。"));
  const conditions = el("div", { class: "chips" });
  const dateRange = el("div", {});
  const file = encodeURIComponent(fund.id) + ".json";
  Promise.all([cachedJSON(context, "./data/backtest/" + file), cachedJSON(context, "./data/ml/" + file)]).then(([results, model]) => {
    if (signal?.aborted) return;
    const row = nearestGrid((results?.grid ?? []).filter(Boolean), plan, context.calendar);
    if (row) {
      conditions.replaceChildren(chip("期間 " + row.window + " 営業日"), chip(row.count + " 回に分ける"),
        chip("スコア " + row.threshold + " 以上で買う"));
    }
    const dates = results?.periods?.[period];
    if (dates?.from || dates?.to) dateRange.append(paragraph((dates.from ?? "—") + " 〜 " + (dates.to ?? "—")));
    if (period === "all" && results?.schema === 2) {
      dateRange.append(paragraph("全期間には、基準価額の開始より前を指数と為替でつないだ期間を含みます。", "secondary"));
    }
    const key = "verify:" + fund.id + ":" + (plan?.id ?? "default");
    body.replaceChildren(...[
      row ? verdictCard(row, results?.evidence?.strategies?.score, period) : null,
      comparisonCard(results, row, period, context.selection, key, signal),
      forwardCard(results?.evidence, context.selection, key),
      modelCard(model, fund.ml?.note, context, key, signal),
    ].filter(Boolean));
  }).catch(() => {
    if (!signal?.aborted) body.replaceChildren(paragraph("検証結果を取得できませんでした。", "notice warning"));
  });
  const planPicker = plans.length > 1 ? el("select", {}, ...plans.map(item =>
    el("option", { value: item.id, selected: item.id === plan.id }, item.title || "購入計画"))) : null;
  planPicker?.addEventListener("change", () => { context.selection.verifyPlan = planPicker.value; context.render(); });
  return [card(fundPicker(context.funds, fund.id, id => { context.selection.verify = id; context.render(); }),
    planPicker ? field("比較する計画", planPicker) : null,
    paragraph(plan ? "計画の条件に最も近い検証を表示します。" : "既定の条件を表示します。", "secondary"),
    conditions,
    segmented("検証の対象期間", PERIODS, period,
      value => { context.selection.verifyPeriod = value; context.render(); }),
    dateRange), body];
}
