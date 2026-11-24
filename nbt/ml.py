import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .calendar import add_business_days
from .stats import stable_seed, statistic_interval

HORIZON = 21  # 約定ラグ1日と約定後20日
MIN_TRAIN = 750
STEP = 21
MODEL_SETTINGS = {"C": 0.5, "max_iter": 1000}
METRIC_BLOCK = 42
METRIC_SEED = stable_seed("ml", "metrics")
INVALID_NOTE = "過去の検証では偶然と区別できません。参考にしないでください"


def _label_delay(lag):
    return lag + HORIZON - 1


def targets(price, lag=1):
    immediate = price.shift(-lag)
    delayed = price.shift(-_label_delay(lag))
    return delayed.lt(immediate).astype(float).where(delayed.notna() & immediate.notna())


def training_rows(complete, outcome, as_of, lag=1):
    # as_of の朝には as_of の価格がまだ出ていない。答えが as_of より前の価格だけで決まる行に限る。
    stop = max(0, as_of - _label_delay(lag))
    return np.flatnonzero(complete[:stop] & np.isfinite(outcome[:stop]))


def training_schedule(complete, outcome, lag=1):
    end = len(complete)
    first = next((
        as_of for as_of in range(MIN_TRAIN + _label_delay(lag), end)
        if len(training_rows(complete, outcome, as_of, lag)) >= MIN_TRAIN
    ), end)
    return range(first, end, STEP)


def make_model():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(**MODEL_SETTINGS))


def fit(features, outcome, rows):
    if np.unique(outcome[rows]).size < 2:
        return None
    return make_model().fit(features[rows], outcome[rows])


def _calibration(actual, probability):
    calibration = []
    ranked = np.argsort(probability, kind="stable")
    for group, selected in enumerate(np.array_split(ranked, 10), start=1):
        count = len(selected)
        calibration.append({
            "decile": group, "count": count,
            "lower": probability[selected[0]] if count else None,
            "upper": probability[selected[-1]] if count else None,
            "mean_probability": probability[selected].mean() if count else None,
            "observed_rate": actual[selected].mean() if count else None,
        })
    return calibration


def _performance(actual, probability, baseline, with_intervals=False):
    n = len(actual)
    auc = roc_auc_score(actual, probability) if np.unique(actual).size == 2 else None
    errors = (actual - probability) ** 2
    base_errors = (actual - baseline) ** 2
    brier = errors.mean() if n else None
    base_brier = base_errors.mean() if n else None
    skill = 1 - brier / base_brier if base_brier else None
    auc_ci = skill_ci = None
    if with_intervals and auc is not None:
        auc_ci = statistic_interval(n, METRIC_BLOCK, _sample_auc(actual, probability), seed=METRIC_SEED)
    if with_intervals and skill is not None:
        def sample_skill(rows):
            denominator = base_errors[rows].sum()
            return 1 - errors[rows].sum() / denominator if denominator else np.nan

        skill_ci = statistic_interval(n, METRIC_BLOCK, sample_skill, seed=METRIC_SEED)
    return {
        "count": n, "auc": auc, "brier": brier, "baseline_brier": base_brier, "brier_skill": skill,
        "auc_ci": auc_ci, "brier_skill_ci": skill_ci,
    }


def _sample_auc(actual, probability):
    # 確率の順位は全抽出で共通。同順位の正例・負例の組は 0.5 と数える。
    unique, ranks = np.unique(probability, return_inverse=True)
    n = len(unique)

    def auc(rows):
        groups = ranks[rows]
        positive = np.bincount(groups, weights=actual[rows], minlength=n)
        negative = np.bincount(groups, minlength=n) - positive
        pairs = positive.sum() * negative.sum()
        if not pairs:
            return np.nan
        return (positive * (negative.cumsum() - negative / 2)).sum() / pairs

    return auc


def is_valid(count, auc, skill, auc_ci, skill_ci):
    return bool(
        count >= 250 and auc is not None and auc > 0.55 and skill is not None and skill > 0.01
        and auc_ci is not None and auc_ci[0] > 0.5 and skill_ci is not None and skill_ci[0] > 0
    )


def evaluate(actual, probability, baseline):
    result = _performance(actual, probability, baseline, with_intervals=True)
    result["valid"] = is_valid(
        result["count"], result["auc"], result["brier_skill"], result["auc_ci"], result["brier_skill_ci"],
    )
    result["calibration"] = _calibration(actual, probability)
    result["independent"] = result["count"] // HORIZON
    return result


def _estimate_impact(outcome, predicted, confirmed, baseline, tested):
    errors = np.abs(predicted[tested] - confirmed[tested])
    estimate = _performance(outcome[tested], predicted[tested], baseline[tested])
    actual = _performance(outcome[tested], confirmed[tested], baseline[tested])
    return {
        "prob_abs_diff_mean": errors.mean() if len(errors) else None,
        "prob_abs_diff_p95": np.percentile(errors, 95) if len(errors) else None,
        "auc_confirmed": actual["auc"], "brier_skill_confirmed": actual["brier_skill"],
        "auc_estimate": estimate["auc"], "brier_skill_estimate": estimate["brier_skill"],
    }


def _latest_probabilities(price, inputs, values, outcome, complete, lag):
    if not len(inputs):
        return None, None
    latest = inputs.index[-1]
    if isinstance(inputs.index, pd.DatetimeIndex):
        previous = pd.Timestamp(add_business_days(latest.date(), -1))
    else:
        previous = inputs.index[-2] if len(inputs) > 1 else None
    probabilities = []
    for day in (previous, latest):
        if day not in inputs.index:
            probabilities.append(None)
            continue
        row = inputs.loc[[day]].to_numpy(dtype=float)
        as_of = price.index.searchsorted(day)
        model = fit(values, outcome, training_rows(complete, outcome, as_of, lag))
        probabilities.append(model.predict_proba(row)[0, 1] if model is not None and np.isfinite(row).all() else None)
    return probabilities[1], probabilities[0]


def experiment(price, features, decision=None, *, lag=1, registered=None, nav_start=None, latest_basis="confirmed"):
    decision = features if decision is None else decision
    values = features.to_numpy(dtype=float)
    inputs = decision.reindex(price.index).to_numpy(dtype=float)
    complete = np.isfinite(values).all(axis=1)
    predictable = np.isfinite(inputs).all(axis=1)
    outcome = targets(price, lag).to_numpy()
    predicted = np.full(len(price), np.nan)
    confirmed = predicted.copy()
    baseline = predicted.copy()
    for as_of in training_schedule(complete, outcome, lag):
        rows = training_rows(complete, outcome, as_of, lag)
        model = fit(values, outcome, rows)
        predict = np.flatnonzero(predictable[as_of:as_of + STEP]) + as_of
        if model is not None and predict.size:
            predicted[predict] = model.predict_proba(inputs[predict])[:, 1]
            baseline[predict] = outcome[rows].mean()
            paired = predict[complete[predict]]
            if nav_start is not None and paired.size:
                confirmed[paired] = model.predict_proba(values[paired])[:, 1]

    tested = np.isfinite(predicted) & np.isfinite(outcome)
    metrics = evaluate(outcome[tested], predicted[tested], baseline[tested])
    forward = tested & (price.index > pd.Timestamp(registered)) if registered is not None else np.zeros(len(price), dtype=bool)
    performance = _performance(outcome[forward], predicted[forward], baseline[forward], with_intervals=True)
    metrics["forward"] = {key: performance[key] for key in ("count", "auc", "brier_skill", "auc_ci", "brier_skill_ci")}
    metrics["estimate_impact"] = None
    if nav_start is not None:
        paired = tested & np.isfinite(confirmed) & (price.index >= pd.Timestamp(nav_start))
        metrics["estimate_impact"] = _estimate_impact(outcome, predicted, confirmed, baseline, paired)
    latest_inputs = decision if latest_basis == "estimate" else features
    latest, previous = _latest_probabilities(price, latest_inputs, values, outcome, complete, lag)
    return pd.Series(predicted, index=price.index), latest, previous, metrics
