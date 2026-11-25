from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
import subprocess

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import backtest, ml, stats

NOTE = "探索の結果です。購入判定には使いません。"
WINDOW, COUNT, PROBABILITY = 40, 3, 0.4
PERIODS = ("all", "nav")
REFERENCE = ("A", "down20", "registered")
NEUTRAL = {"auc": 0.5}
TARGETS = {
    "down20": ("binary", 20, None),
    **{f"ret{h}": ("continuous", h, None) for h in (5, 10, 20)},
    **{f"drop{x}_{h}": ("binary", h, -x / 100) for h in (10, 20) for x in (3, 5)},
    "low20": ("continuous", 20, None), "vol20": ("continuous", 20, None),
}


def targets(price, lag):
    outcome = pd.DataFrame(index=price.index)
    initial = price.shift(-lag)
    for target, (_, horizon, threshold) in TARGETS.items():
        # 両端の価格だけで決まる対象は両端だけ、期間内の価格を使う対象は期間内のすべてがそろった行に限る。
        complete = price.rolling(horizon + 1).count().shift(-lag - horizon).eq(horizon + 1)
        if target == "down20":
            values = ml.targets(price, lag)
        elif target.startswith("ret"):
            values = price.shift(-lag - horizon) / initial - 1
        elif target == "vol20":
            volatility = np.log(price).diff().rolling(horizon).std().shift(-lag - horizon) * np.sqrt(252)
            values = np.log(volatility.where(volatility > 0)).where(complete)
        else:
            minimum = price.rolling(horizon).min().shift(-lag - horizon)
            values = minimum / initial - 1 if threshold is None else minimum.le(initial * (1 + threshold)).astype(float)
            values = values.where(complete)
        outcome[target] = values
    return outcome.replace([np.inf, -np.inf], np.nan)


def _ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


def _model_predictions(outcomes, training, decision, complete, predictable, lag):
    values = training.to_numpy(dtype=float)
    inputs = decision.reindex(outcomes.index).to_numpy(dtype=float)
    predictions = {}
    for target, (kind, horizon, _) in TARGETS.items():
        binary = kind == "binary"
        predictions[target] = ml.walk_forward(
            outcomes[target].to_numpy(), values, inputs, complete, predictable, lag, horizon,
            ml.make_model if binary else _ridge, binary=binary,
        )
    return predictions


def _skill(actual, predicted, baseline):
    errors = (actual - predicted) ** 2
    reference = (actual - baseline) ** 2

    def statistic(rows):
        denominator = reference[rows].sum()
        return 1 - errors[rows].sum() / denominator if denominator else np.nan

    return statistic


def _rank_corr(actual, predicted):
    ranks = rankdata(actual), rankdata(predicted)

    def statistic(rows):
        if len(rows) < 2:
            return np.nan
        a, b = (values[rows] - values[rows].mean() for values in ranks)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        return np.dot(a, b) / norm if norm else np.nan

    return statistic


def _prediction_metrics(actual, predicted, baseline, binary, delay, draws, seed_parts, model):
    n = len(actual)
    rows = np.arange(n)
    result = {"count": n, "independent": n // delay}
    skill = _skill(actual, predicted, baseline)
    if binary:
        positives = int(actual.sum())
        result.update(
            positives=positives, negatives=n - positives, positive_rate=positives / n if n else None,
            brier=np.mean((actual - predicted) ** 2) if n else None,
            baseline_brier=np.mean((actual - baseline) ** 2) if n else None,
        )
        metrics = {"auc": ml._sample_auc(actual, predicted), "brier_skill": skill}
    else:
        result.update(mean=actual.mean() if n else None, std=actual.std() if n else None)
        metrics = {"skill": skill, "rank_corr": _rank_corr(actual, predicted)}
    for key, statistic in metrics.items():
        value = statistic(rows)
        result[key] = value
        result[f"{key}_ci"] = stats.statistic_interval(
            n, 2 * delay, statistic, draws=draws, seed=stats.stable_seed(*seed_parts, model, key),
        ) if np.isfinite(value) else None
    return result, metrics


def _prediction_evaluation(fund_id, outcomes, predictions, nav_start, lag, draws):
    day = outcomes.index
    nav = day >= nav_start if nav_start is not None else np.zeros(len(day), dtype=bool)
    evaluation = {}
    for target, (kind, horizon, _) in TARGETS.items():
        outcome = outcomes[target].to_numpy()
        a, b = (predictions[model][target][0] for model in ("A", "B"))
        common = np.isfinite(outcome) & np.isfinite(a) & np.isfinite(b)
        result = {"A": {}, "B": {}, "difference": {}}
        for period, mask in (("all", common), ("nav", common & nav)):
            seed = ("explore", fund_id, target, period)
            metrics = {}
            for model in ("A", "B"):
                predicted, baseline = predictions[model][target]
                result[model][period], metrics[model] = _prediction_metrics(
                    outcome[mask], predicted[mask], baseline[mask], kind == "binary", lag + horizon, draws, seed, model,
                )
            result["difference"][period] = _prediction_difference(result, metrics, period, lag + horizon, draws, seed)
        evaluation[target] = result
    return evaluation


def _prediction_difference(result, metrics, period, delay, draws, seed):
    differences = {}
    n = result["A"][period]["count"]
    for key, a in metrics["A"].items():
        b = metrics["B"][key]

        def difference(rows):
            return b(rows) - a(rows)

        value = result["B"][period][key] - result["A"][period][key]
        differences[key] = {
            "value": value,
            "ci": stats.statistic_interval(
                n, 2 * delay, difference, draws=draws, seed=stats.stable_seed(*seed, "difference", key),
            ) if np.isfinite(value) else None,
        }
    return differences


def strategy_signals(days, predictions):
    common = np.ones(len(days), dtype=bool)
    signals = {}
    for model, forecasts in predictions.items():
        for target, (predicted, baseline) in forecasts.items():
            if target == "vol20":
                continue
            common &= np.isfinite(predicted)
            values = predicted - baseline if TARGETS[target][0] == "binary" else baseline - predicted
            signals[(model, target, "baseline")] = (values, 0.0)
            if target == "down20":
                signals[(model, target, "registered")] = (predicted, PROBABILITY)
    return common, {key: (pd.Series(values, index=days).where(common), threshold) for key, (values, threshold) in signals.items()}


def _date(day):
    return day.date().isoformat() if day is not None else None


def _period_rows(rows, expected, nav_start):
    if not rows[["date", "last_fill"]].equals(expected[["date", "last_fill"]]):
        raise ValueError("買い方の検証期間が一致しません")
    return {"all": rows, "nav": rows.loc[rows["date"] >= nav_start] if nav_start is not None else rows.iloc[:0]}


def _cost_differences(rows, reference, draws, seed):
    if rows.empty:
        return None
    differences = {}
    for comparison in backtest.COMPARISONS:
        values = (rows[comparison] - reference[comparison]).dropna()
        differences[comparison] = {
            "mean": values.mean() if len(values) else None,
            "ci": stats.mean_interval(values, (2 * WINDOW + 4) // 5, draws=draws, seed=stats.stable_seed(*seed, comparison)),
        }
    return differences


def _cost_summary(rows, reference, draws, seed):
    if rows.empty:
        return None
    summaries = {
        name: stats.summarize(rows[name], WINDOW, stats.stable_seed(*seed, name), draws)
        for name in backtest.COMPARISONS
    }
    regular = summaries["regular"]
    return {
        "count": regular["count"], "independent": regular["independent"], "delay": rows["delay"].mean(),
        **{name: {key: value for key, value in summary.items() if key not in ("count", "independent")}
           for name, summary in summaries.items()},
        "vs_reference": None if reference is None else _cost_differences(rows, reference, draws, (*seed, "vs_reference")),
    }


def _strategy_evaluation(price, fund, predictions, nav_start, draws):
    common, signals = strategy_signals(price.index, predictions)
    fills = backtest.execution_prices(price, fund)
    windows = {key: backtest.window_results(fills, values, WINDOW, COUNT, threshold, strategy="ml").comparisons()
               for key, (values, threshold) in signals.items()}
    reference = windows[REFERENCE]
    subsets = {key: _period_rows(rows, reference, nav_start) for key, rows in windows.items()}
    base = _period_rows(reference, reference, nav_start)
    results, differences = {}, {}
    for (model, target, rule), periods in subsets.items():
        strategy = f"{model}:{target}:{rule}"
        seed = ("explore", fund["id"], f"{target}:{rule}")
        # 基準の買い方そのものには、基準との差を出さない。
        compared = {period: None if (model, target, rule) == REFERENCE else base[period] for period in periods}
        results[strategy] = {"model": model, "target": target, "rule": rule} | {
            period: _cost_summary(rows, compared[period], draws, (*seed, model, period)) for period, rows in periods.items()
        }
        if model == "B":
            differences[f"{target}:{rule}"] = {
                period: _cost_differences(rows, subsets[("A", target, rule)][period], draws, (*seed, "difference", period))
                for period, rows in periods.items()
            }
    periods = {period: {"from": _date(rows["date"].iloc[0]), "to": _date(rows["date"].iloc[-1])}
               if len(rows) else None for period, rows in base.items()}
    periods["all"] = periods["all"] or {"from": None, "to": None}
    return {"common_days": int(common.sum()), "periods": periods, "results": results, "model_difference": differences}


def _interval_counts(intervals, positive, negative):
    available = [ci for ci in intervals if ci is not None]
    return {positive: sum(ci[0] > 0 for ci in available), negative: sum(ci[1] < 0 for ci in available), "total": len(available)}


def _tried(prediction, strategy):
    # 予測の指標そのものの区間は、基準(AUC は 0.5、ほかは 0)からのずれで数える。
    metrics = [[bound - NEUTRAL.get(key[:-3], 0) for bound in ci] if ci is not None else None
               for entry in prediction.values() for model in ("A", "B") for summary in entry[model].values()
               for key, ci in summary.items() if key.endswith("_ci")]
    prediction_differences = [metric for entry in prediction.values() for period in entry["difference"].values()
                              for metric in period.values()]
    periods = [entry[period] for entry in strategy["results"].values() for period in PERIODS if entry[period] is not None]
    compared = [row["vs_reference"] for row in periods if row["vs_reference"] is not None]
    model_differences = [metric for entry in strategy["model_difference"].values() for period in entry.values() if period
                         for metric in period.values()]
    strategies = len(strategy["results"])
    # 比較の数は、出そうとした区間の数(データが足りず出せなかったものを含む)。
    costs = (2 * strategies - 1 + len(strategy["model_difference"])) * len(PERIODS) * len(backtest.COMPARISONS)
    return {
        "targets": len(prediction), "models": 2, "prediction_cells": len(prediction) * 2 * len(PERIODS),
        "strategies": strategies, "comparisons": len(metrics) + len(prediction_differences) + costs,
        "intervals": {
            "prediction": _interval_counts(metrics, "positive", "negative"),
            "prediction_difference": _interval_counts((row["ci"] for row in prediction_differences), "positive", "negative"),
            "strategy": _interval_counts((row[name]["ci"] for row in periods for name in backtest.COMPARISONS), "unfavorable", "favorable"),
            "strategy_vs_reference": _interval_counts((row[name]["ci"] for row in compared
                                                       for name in backtest.COMPARISONS), "unfavorable", "favorable"),
            "model_difference": _interval_counts((row["ci"] for row in model_differences), "unfavorable", "favorable"),
        },
    }


def _git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=Path(__file__).resolve().parents[1], stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_info(generated_at, registration):
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    packages = {}
    for name in ("numpy", "pandas", "scikit-learn", "scipy", "yfinance"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "generated_at": generated_at, "git_commit": commit.decode("ascii") if commit else None,
        "git_dirty": bool(status) if status is not None else None, "python": platform.python_version(), "packages": packages,
        "registration": {entry["id"]: {key: entry[key] for key in ("version", "fingerprint")}
                         for entry in registration["strategies"]},
    }


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), 6) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _reference_check(estimate, ml_v1):
    reference = ml_v1.reindex(estimate.index)
    both = np.isfinite(estimate) & np.isfinite(reference)
    return {
        "rows_explore": int(np.isfinite(estimate).sum()), "rows_ml_v1": int(np.isfinite(reference).sum()),
        "rows_common": int(both.sum()), "probability_abs_diff_max": (estimate[both] - reference[both]).abs().max(),
    }


def evaluate(fund, price, features, decision, macro_features, nav_start, ml_v1, macro_data, run, draws):
    lag = fund["settlement"]["trade_lag_bd"]
    nav_start = pd.Timestamp(nav_start) if nav_start is not None else None
    training = {"A": features.reindex(price.index), "B": features.reindex(price.index).join(macro_features)}
    inputs = {"A": decision, "B": decision.join(macro_features)}
    base_complete = np.isfinite(training["A"].to_numpy()).all(axis=1)
    complete = np.isfinite(training["B"].to_numpy()).all(axis=1)
    predictable = np.isfinite(inputs["B"].reindex(price.index).to_numpy()).all(axis=1)
    outcome = targets(price, lag)
    predictions = {model: _model_predictions(outcome, values, inputs[model], complete, predictable, lag)
                   for model, values in training.items()}
    prediction = _prediction_evaluation(fund["id"], outcome, predictions, nav_start, lag, draws)
    strategy = _strategy_evaluation(price, fund, predictions, nav_start, draws)
    return _clean({
        "schema": 1, "kind": "exploration", "note": NOTE, "fund": {key: fund[key] for key in ("id", "short_name")}, "run": run,
        "data": {
            "price_from": _date(price.index[0]), "price_to": _date(price.index[-1]), "nav_start": _date(nav_start), "lag": lag,
            "rows": {"days": len(price), "base_complete": base_complete.sum(), "complete": complete.sum(),
                     "excluded_by_macro": (base_complete & ~complete).sum()}, "macro": macro_data,
        },
        "settings": {
            "min_train": ml.MIN_TRAIN, "step": ml.STEP, "draws": draws, "window": WINDOW, "count": COUNT,
            "probability_at_most": PROBABILITY, "models": {model: list(values.columns) for model, values in training.items()},
            "seed": 'stable_seed("explore", 銘柄, 対象または買い方, 対象期間・モデル・指標など)',
        },
        "targets": {key: {"kind": kind, "horizon": horizon, "threshold": threshold, "block": 2 * (lag + horizon)}
                    for key, (kind, horizon, threshold) in TARGETS.items()},
        "prediction": prediction,
        "reference_check": _reference_check(pd.Series(predictions["A"]["down20"][0], index=price.index), ml_v1),
        "strategy": strategy, "tried": _tried(prediction, strategy),
    })


def _text(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, bool):
        return "あり" if value else "なし"
    return str(value).replace("|", r"\|").replace("\n", " ")


def _table(header, rows):
    return ["", "| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(_text(value) for value in row) + " |" for row in rows), ""]


def _reading(ci, mode, neutral=0):
    if ci is None or ci[0] <= neutral <= ci[1]:
        return "有効性未確認"
    positive = ci[0] > neutral
    if mode == "cost":
        return "過去データでは不利" if positive else "過去データでは有利"
    if mode == "difference":
        return "B が上" if positive else "B が下"
    return "基準より上" if positive else "基準より下"


def _estimate(value, ci):
    return _text(value) if ci is None else f"{_text(value)} [{_text(ci[0])}, {_text(ci[1])}]"


def _report_data(result):
    data = result["data"]
    names = {"days": "国内営業日", "base_complete": "base 完備", "complete": "全特徴量完備",
             "excluded_by_macro": "マクロ指標で除いた行"}
    rows = [("価格期間", f"{data['price_from']} ～ {data['price_to']}"), ("基準価額の開始日", data["nav_start"]),
            ("約定ラグ（国内営業日）", data["lag"])]
    rows.extend((label, data["rows"][key]) for key, label in names.items())
    rows.extend((label, result["reference_check"][key]) for key, label in (
        ("rows_explore", "探索 A の予測行数"), ("rows_ml_v1", "ML v1 の予測行数"),
        ("rows_common", "両方の予測がある行数"), ("probability_abs_diff_max", "確率の最大絶対差"),
    ))
    rows.extend((f"モデル {model} の特徴量", ", ".join(columns)) for model, columns in result["settings"]["models"].items())
    lines = _table(("項目", "値"), rows)
    lines += _table(("系列", "ティッカー", "遅れ（日）", "最初", "最後"), (
        (key, info["ticker"], info["delay_days"], info["first"], info["last"]) for key, info in data["macro"].items()
    ))
    lines += _table(("対象", "種類", "予測期間（営業日）", "閾値", "区間のブロック長"), (
        (key, item["kind"], item["horizon"], item["threshold"], item["block"]) for key, item in result["targets"].items()
    ))
    return lines


def _report_prediction(prediction):
    rows = {"binary": [], "continuous": []}
    for target, result in prediction.items():
        for model in ("A", "B"):
            for period, summary in result[model].items():
                common = (target, model, period, summary["count"], summary["independent"])
                if "auc" in summary:
                    auc_ci, skill_ci = summary["auc_ci"], summary["brier_skill_ci"]
                    rows["binary"].append((*common, summary["positives"], summary["negatives"], summary["positive_rate"],
                                           summary["brier"], summary["baseline_brier"], _estimate(summary["auc"], auc_ci),
                                           _reading(auc_ci, "metric", 0.5), _estimate(summary["brier_skill"], skill_ci),
                                           _reading(skill_ci, "metric")))
                else:
                    skill_ci, rank_ci = summary["skill_ci"], summary["rank_corr_ci"]
                    rows["continuous"].append((*common, summary["mean"], summary["std"], _estimate(summary["skill"], skill_ci),
                                               _reading(skill_ci, "metric"), _estimate(summary["rank_corr"], rank_ci),
                                               _reading(rank_ci, "metric")))
    header = ("対象", "モデル", "期間", "件数", "重ならない期間")
    return _table((*header, "正例数", "負例数", "正例率", "Brier", "基準 Brier", "AUC", "読み", "Brier スキル", "読み"),
                  rows["binary"]) + _table((*header, "平均", "標準偏差", "スキル", "読み", "順位相関", "読み"), rows["continuous"])


COST_NAMES = {"regular": "対定期", "lump": "対一括", "placebo": "対偽シグナル"}


def _report_costs(strategy):
    lines = _table(("期間", "最初の開始日", "最後の開始日"), (
        (period, (span or {}).get("from"), (span or {}).get("to")) for period, span in strategy["periods"].items()
    ))
    rows = []
    for name, result in strategy["results"].items():
        for period in PERIODS:
            summary = result[period] or {}
            for key, label in COST_NAMES.items():
                metric = summary.get(key, {})
                ref = (summary.get("vs_reference") or {}).get(key, {})
                rows.append((name, period, label, summary.get("count", 0), summary.get("independent", 0), summary.get("delay"),
                             _estimate(metric.get("mean"), metric.get("ci")), metric.get("median"), metric.get("win_rate"),
                             metric.get("p05"), metric.get("p95"), _reading(metric.get("ci"), "cost"),
                             *(("基準", "基準") if name == ":".join(REFERENCE)
                               else (_estimate(ref.get("mean"), ref.get("ci")), _reading(ref.get("ci"), "cost")))))
    return lines + _table(("買い方", "期間", "比較", "件数", "重ならない期間", "遅れ（日）", "平均", "中央値", "勝率（%）",
                           "5% 点", "95% 点", "読み", "A の登録ルールとの差", "読み"), rows)


def _report_differences(prediction, strategy):
    header = ("対象", "期間", "指標", "B − A", "読み")
    return _table(header, (
        (target, period, key, _estimate(metric["value"], metric["ci"]), _reading(metric["ci"], "difference"))
        for target, item in prediction.items() for period, metrics in item["difference"].items() for key, metric in metrics.items()
    )) + _table(("対象・ルール", "期間", "比較", "B − A", "読み"), (
        (target, period, label, _estimate(metric.get("mean"), metric.get("ci")), _reading(metric.get("ci"), "cost"))
        for target, item in strategy["model_difference"].items() for period, metrics in item.items()
        for key, label in COST_NAMES.items() for metric in [(metrics or {}).get(key, {})]
    ))


def report(results):
    lines = [
        "# 予測対象と買い方の探索", "", NOTE, "",
        "良い結果が出た条件も、結果を記録し、版の登録と前向き検証を経て確認します。",
        "結果の良否にかかわらず、この報告を `docs/experiments/<日付>-<名前>.md` に記録します。", "",
        "各区間は未補正の 95% 区間です。差がない場合でも 5% 前後はゼロをまたがないことがあります。"
        "対象や銘柄の値動きは連動するため、区間や銘柄の数を独立した確認の回数としては扱えません。", "",
        "Model B の結果が当てはまるのは、ここで使った 5 特徴量とモデルの組み合わせです。"
        "原油、金、信用スプレッド、経済統計やニュースの有効性は別途検証が必要です。"
        "共通ルールは探索用で、条件の最適性は未確認です。", "", "## 実行条件",
    ]
    if not results:
        return "\n".join(lines) + "\n"
    run, settings = results[0]["run"], results[0]["settings"]
    lines += _table(("項目", "値"), [
        ("実行時刻", run["generated_at"]), ("Git コミット", run["git_commit"]), ("未コミットの変更", run["git_dirty"]),
        ("Python", run["python"]), *run["packages"].items(),
        *((f"登録版 {key}", f"v{entry['version']} / {entry['fingerprint']}") for key, entry in run["registration"].items()),
        ("最小学習件数", settings["min_train"]), ("学習間隔（営業日）", settings["step"]), ("抽出回数", settings["draws"]),
        ("買い方の期間・回数", f"{settings['window']} 日・{settings['count']} 回"),
        ("登録ルールの確率上限", settings["probability_at_most"]), ("買い方のブロック長", (2 * settings["window"] + 4) // 5),
        ("乱数の種", settings["seed"]),
    ])
    lines += ["## 試した数", "", "比較数は、全期間と基準価額の期間それぞれで出そうとした区間の合計です"
              "(予測の指標、予測指標の B − A、買い方、A の登録ルールとの差、買い方の B − A)。"
              "予測の指標は、AUC は 0.5、ほかは 0 を基準に数えます。"]
    lines += _table(("銘柄", "対象", "モデル", "予測の評価", "買い方", "比較"), (
        (result["fund"]["short_name"], *(result["tried"][key] for key in ("targets", "models", "prediction_cells", "strategies", "comparisons")))
        for result in results
    ))
    labels = {"prediction": "予測の指標", "prediction_difference": "予測指標の B − A", "strategy": "買い方",
              "strategy_vs_reference": "A の登録ルールとの差", "model_difference": "買い方の B − A"}
    lines += ["予測の行は「基準より上」「基準より下」、買い方の行は「不利」「有利」の区間の数です。"]
    lines += _table(("銘柄", "比較", "上・不利", "下・有利", "出せた区間"), (
        (result["fund"]["short_name"], labels[key], counts.get("positive", counts.get("unfavorable")),
         counts.get("negative", counts.get("favorable")), counts["total"])
        for result in results for key, counts in result["tried"]["intervals"].items()
    ))
    for result in results:
        lines += [f"## {result['fund']['short_name']}", "", "### データ"] + _report_data(result)
        lines += ["### 予測の評価", "", "AUC の読みは 0.5 を基準とします。"] + _report_prediction(result["prediction"])
        lines += ["### 買い方の評価", "", f"全買い方の予測がそろった日数は {result['strategy']['common_days']} 日です。",
                  "価格差は %、差の差と対偽シグナルはポイントです。"] + _report_costs(result["strategy"])
        lines += ["### B と A の差"] + _report_differences(result["prediction"], result["strategy"])
    return "\n".join(lines).rstrip() + "\n"
