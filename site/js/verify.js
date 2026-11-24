import { businessDaysBetween } from "./calendar.js";
import { cachedJSON, card, chip, details, el, facts, field, fundPicker, number, paragraph, percent,
  probability, responsiveFigure, segmented, selectedFund, svg, table } from "./ui.js";
import { clampPercent, symmetricAxis } from "./visual.js";

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

function strategyDetails(title, result, selection, key) {
  return el("section", { class: "strategy-details" }, el("h3", {}, title),
    details("詳しい数値", [
      paragraph(comparison(result.all)),
      table(["対象", "件数", "平均", "中央値", "勝率", "5%点", "95%点"],
        [["全期間", result.all], ["直近3年", result.recent_3y]].map(([label, row]) =>
          [label, row.count, percent(row.mean, true), percent(row.median, true), percent(row.win_rate),
            percent(row.p05, true), percent(row.p95, true)])),
    ], selection, key));
}

function winCopy(stats) {
  return "安く買えたのは " + percent(stats.win_rate) + "（" + number(stats.count, 0) + " 回中）";
}

function strategyFigure(strategies, period, width) {
  const rows = strategies.map(item => item.result[period]);
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

function modelCard(model, note, context, key, signal) {
  const groups = model.calibration ?? [];
  return card(el("h2", {}, "機械学習の検証"),
    model.valid ? paragraph("有効（過去の検証基準を満たしています）", "notice")
      : el("h3", { class: "notice warning" }, note || "過去の検証では偶然と区別できません。参考にしないでください"),
    el("h3", {}, "予測確率と実際の割合（10分位）"),
    groups.some(group => group.count) ? el("div", { class: "calibration" },
      responsiveFigure(width => calibrationFigure(groups, width), signal)) : paragraph("較正に使える検証結果がありません。"),
    paragraph("点が対角線に近いほど、予測が当たっていたことを示します。", "secondary"),
    details("詳しい数値", [
      facts([["予測の検証件数", model.count], ["AUC", number(model.auc)], ["Brier", number(model.brier, 4)],
        ["基準 Brier", number(model.baseline_brier, 4)], ["Brier スキル", number(model.brier_skill, 4)]]),
      table(["確率範囲", "件数", "平均予測", "実際"], groups.map(group =>
        [group.count ? probability(group.lower) + " ～ " + probability(group.upper) : "—", group.count,
          probability(group.mean_probability), probability(group.observed_rate)])),
    ], context.selection, key + ":model"));
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
  const file = encodeURIComponent(fund.id) + ".json";
  Promise.all([cachedJSON(context, "./data/backtest/" + file), cachedJSON(context, "./data/ml/" + file)]).then(([results, model]) => {
    if (signal?.aborted) return;
    const row = nearestGrid(results.grid ?? [], plan, context.calendar);
    if (!row) {
      body.replaceChildren(paragraph("この条件で比べられる過去の期間がありません。"));
      return;
    }
    conditions.replaceChildren(chip("期間 " + row.window + " 営業日"), chip(row.count + " 回に分ける"),
      chip("スコア " + row.threshold + " 以上で買う"));
    const key = "verify:" + fund.id + ":" + (plan?.id ?? "default");
    const score = row.score.all;
    const positive = score.count > 0 && score.mean < 0 && score.win_rate >= 50;
    const subtitle = "（確率 " + probability(results.ml_probability_at_most) + " 以下）";
    const strategies = [
      { label: "スコアを見て買う", result: row.score },
      { label: "初日に一括で買う", result: row.lump },
      { label: "実験モデルを見て買う", subtitle, result: row.ml },
    ].map(strategy => ({ ...strategy, title: strategy.label + (strategy.subtitle ?? "") }));
    body.replaceChildren(
      card(el("div", { class: "notice verdict " + (positive ? "info" : "warning") },
        el("h2", {}, positive ? "過去の結果：差は小さい" : score.count
          ? "過去の結果：有利とは言えない" : "過去の結果：比較できる期間なし"),
        paragraph(verdict(row)), paragraph("過去の結果であり、将来も同じとは限りません。"))),
      card(el("h2", {}, "3つの買い方を比べる"),
        paragraph("決めた日に分けて買う（定期購入）＝0%。平均取得単価の差を示します。"),
        paragraph("横線：5%点〜95%点　●：平均　縦の小線：中央値。割合の棒の印は50%です。", "secondary"),
        responsiveFigure(width => strategyFigure(strategies, period, width), signal),
        ...strategies.map(({ title, result }, i) =>
          strategyDetails(title, result, context.selection, key + ":strategy:" + i)),
        details("検証の方法", [paragraph(results.description, "secondary")], context.selection, key + ":method")),
      modelCard(model, fund.ml?.note, context, key, signal),
    );
  }).catch(() => body.replaceChildren(paragraph("検証結果を取得できませんでした。", "notice warning")));
  const planPicker = plans.length > 1 ? el("select", {}, ...plans.map(item =>
    el("option", { value: item.id, selected: item.id === plan.id }, item.title || "購入計画"))) : null;
  planPicker?.addEventListener("change", () => { context.selection.verifyPlan = planPicker.value; context.render(); });
  return [card(fundPicker(context.funds, fund.id, id => { context.selection.verify = id; context.render(); }),
    planPicker ? field("比較する計画", planPicker) : null,
    paragraph(plan ? "計画の条件に最も近い検証を表示します。" : "既定の条件を表示します。", "secondary"),
    conditions,
    segmented("検証の対象期間", [["all", "全期間"], ["recent_3y", "直近3年"]], period,
      value => { context.selection.verifyPeriod = value; context.render(); })), body];
}
