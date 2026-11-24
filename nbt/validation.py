from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .stats import mean_interval, non_overlapping, stable_seed, summarize, t_interval

REGISTRATION_PATH = Path(__file__).resolve().parents[1] / "config" / "validation.json"


def load_registration(registration=None):
    if registration is None:
        registration = json.loads(REGISTRATION_PATH.read_text(encoding="utf-8"))
    protocol = registration["protocol"]
    strategies = registration["strategies"]
    if registration["schema"] != 1:
        raise ValueError("検証登録の schema が不明です")
    if len(strategies) > protocol["max_concurrent_versions"]:
        raise ValueError("前向き検証の同時登録数が上限を超えています")
    ids = [entry["id"] for entry in strategies]
    if set(ids) - {"score", "ml"} or len(ids) != len(set(ids)):
        raise ValueError("有効な登録はスコアとMLの各1版までです")
    years = protocol["looks_years"]
    if not years or years != sorted(set(years)) or years[0] < protocol["min_forward_years"]:
        raise ValueError("検証登録の判定年が不正です")
    for entry in strategies:
        date.fromisoformat(entry["registered"])
        primary = entry["primary"]
        if not 1 <= primary["count"] <= primary["window"]:
            raise ValueError("検証登録の購入回数が不正です")
    return registration


def judgment_level(protocol):
    return 1 - protocol["alpha"] / (len(protocol["looks_years"]) * protocol["max_concurrent_versions"])


def public_protocol(protocol):
    return {
        key: protocol[key] for key in (
            "alpha", "looks_years", "max_concurrent_versions", "practical_margin_pct",
            "min_forward_years", "min_independent_windows",
        )
    } | {"level": judgment_level(protocol)}


def anniversary(registered, years):
    try:
        return registered.replace(year=registered.year + years)
    except ValueError:
        return registered.replace(year=registered.year + years, day=28)


def look_schedule(registered, years, today, *, confirmed=False):
    dates = [anniversary(registered, year) for year in years]
    last = max((day for day in dates if day <= today), default=None)
    following = next((day for day in dates if day > today), None)
    return {
        "dates": [day.isoformat() for day in dates], "last": last.isoformat() if last else None,
        "next": following.isoformat() if following else None, "closed": last == dates[-1] and not confirmed,
    }


def period_masks(rows, registered):
    registered = pd.Timestamp(registered)
    return rows["last_fill"] <= registered, rows["date"] > registered


def _meets_margin(mean, ci, t_ci, margin):
    return mean is not None and mean <= -margin and ci is not None and ci[1] < 0 and t_ci is not None and t_ci[1] < 0


def status(mean, ci, t_ci, nav_mean, has_nav, margin, passed=False, closed=False):
    if ci is not None and ci[0] > 0:
        return "unfavorable"
    if _meets_margin(mean, ci, t_ci, margin) and (not has_nav or nav_mean is not None and nav_mean < 0):
        if passed:
            return "confirmed"
        if not closed:
            return "candidate"
    return "unconfirmed"


def _independent(values, window):
    return values.loc[non_overlapping(values.index, window)]


def judgment(values, window, look, protocol, seed):
    values = values.dropna()
    independent = _independent(values, window)
    level = judgment_level(protocol)
    mean = values.mean() if len(values) else None
    ci = mean_interval(values, (2 * window + 4) // 5, level, protocol["judgment_bootstrap_draws"], seed)
    t_ci = t_interval(independent, level)
    passed = len(independent) >= protocol["min_independent_windows"] and _meets_margin(
        mean, ci, t_ci, protocol["practical_margin_pct"],
    )
    return {
        "count": len(values), "independent": len(independent), "mean": mean, "ci": ci, "t_ci": t_ci,
        "level": level, "look": look, "passed": bool(passed),
    }


def _comparison_evidence(history, history_nav, forward, at_look, window, years, looks, protocol, seed_parts):
    draws = protocol["bootstrap_draws"]
    history_summary = summarize(history, window, stable_seed(*seed_parts, "history"), draws)
    history_summary["t_ci"] = t_interval(_independent(history.dropna(), window))
    nav = history_nav.dropna() if history_nav is not None else history.iloc[:0]
    nav_mean = nav.mean() if len(nav) else None
    forward_summary = summarize(forward, window, stable_seed(*seed_parts, "forward"), draws) | {"years": years}
    look = looks["last"]
    result = judgment(at_look, window, look, protocol, stable_seed(*seed_parts, "judgment", look)) if look else None
    state = status(
        history_summary["mean"], history_summary["ci"], history_summary["t_ci"], nav_mean, history_nav is not None,
        protocol["practical_margin_pct"], passed=result is not None and result["passed"], closed=looks["closed"],
    )
    return {
        "status": state, "history": history_summary, "history_nav": {"count": len(nav), "mean": nav_mean},
        "forward": forward_summary, "judgment": result,
    }


def evidence(fund_id, entry, protocol, results, nav_start, last, today, comparisons):
    registered = date.fromisoformat(entry["registered"])
    looks = look_schedule(registered, protocol["looks_years"], today)
    history_mask, forward_mask = period_masks(results.rows, registered)
    # 偽シグナルにも、その集計時点までに使える期間だけを渡す。
    history = results.comparisons(history_mask)
    forward = results.comparisons(forward_mask)
    at_look = None
    if looks["last"] is not None:
        at_look = results.comparisons(forward_mask & (results.rows["last_fill"] <= pd.Timestamp(looks["last"])))
    history_nav = history.loc[history["date"] >= nav_start] if nav_start is not None else None
    years = max(0, round((last.date() - registered).days / 365.2425, 2))
    primary = entry["primary"]
    threshold = primary.get("threshold", primary.get("probability_at_most"))
    summaries = {}
    for comparison in comparisons:
        summaries[comparison] = _comparison_evidence(
            history[comparison], history_nav[comparison] if history_nav is not None else None, forward[comparison],
            at_look[comparison] if at_look is not None else None, results.window, years, looks, protocol,
            (fund_id, entry["id"], results.window, primary["count"], threshold, comparison),
        )
    if any(result["status"] == "confirmed" for result in summaries.values()):
        looks["closed"] = False
    return {
        "version": entry["version"], "registered": entry["registered"], "primary": primary,
        "looks": looks, "comparisons": summaries,
    }


def _synthetic_data():
    rng = np.random.default_rng(451)
    dates = pd.bdate_range("2015-01-05", periods=1500)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.012, len(dates)))), index=dates)
    proxy = price * np.exp(rng.normal(0, 0.004, len(dates)))
    fx = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(dates)))), index=dates)
    vix = pd.Series(rng.uniform(15, 35, len(dates)), index=dates)
    return price, proxy, fx, vix


def _score_fingerprint(price, proxy, fx, vix, primary):
    from . import backtest, indicators, score, series

    estimated = series.estimated_series(price, proxy, price.index[425])
    confirmed_features = indicators.indicators(price, fx, vix)
    decision_features = indicators.decision_indicators(price, estimated, fx, vix)
    confirmed, _ = score.score_series(confirmed_features)
    decision, _ = score.decision_score_series(confirmed_features, decision_features)
    window = primary["window"]
    bounds = backtest.intervals(window, primary["count"])
    return {
        "confirmed": [round(value, 4) if np.isfinite(value) else None for value in confirmed],
        "decision": [round(value, 4) if np.isfinite(value) else None for value in decision],
        "weights": score.WEIGHTS, "window": score.WINDOW, "min_periods": score.MIN_PERIODS,
        "days": [
            backtest.decision_days(bounds, decision.iloc[i:i + window].to_numpy(), primary["threshold"])
            for i in range(380, len(price) - window, 71)
        ],
        "pull_forward": [backtest.PULL_FORWARD_BONUS, backtest.PULL_FORWARD_MAX],
    }


def _ml_fingerprint(price, fx, vix, primary):
    from . import backtest, indicators, ml

    features = indicators.indicators(price, fx, vix)
    complete = np.isfinite(features.to_numpy()).all(axis=1)
    outcome = ml.targets(price).to_numpy()
    schedule = ml.training_schedule(complete, outcome)
    bounds = backtest.intervals(primary["window"], primary["count"])
    probabilities = np.random.default_rng(724).random(primary["window"])
    return {
        "features": list(features.columns),
        "targets": [int(value) if np.isfinite(value) else None for value in outcome],
        "horizon": ml.HORIZON, "min_train": ml.MIN_TRAIN, "step": ml.STEP,
        "model": [(type(step).__name__, step.get_params()) for _, step in ml.make_model().steps],
        "threshold": backtest.ML_THRESHOLD,
        "training_rows": [
            (i, ml.training_rows(complete, outcome, i).tolist()) for i in schedule[::max(1, len(schedule) // 4)]
        ],
        "days": backtest.decision_days(bounds, probabilities, primary["probability_at_most"], ml=True),
    }


def fingerprint(entry):
    price, proxy, fx, vix = _synthetic_data()
    primary = entry["primary"]
    if entry["id"] == "score":
        content = _score_fingerprint(price, proxy, fx, vix, primary)
    else:
        content = _ml_fingerprint(price, fx, vix, primary)
    payload = json.dumps({"primary": primary, **content}, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
