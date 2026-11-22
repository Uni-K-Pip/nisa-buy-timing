import numpy as np
import pandas as pd
HORIZON = 21
MIN_TRAIN = 750
STEP = 21
INVALID_NOTE = "過去の検証では偶然と区別できません。参考にしないでください"


def targets(price):
    immediate = price.shift(-1)
    delayed = price.shift(-HORIZON)
    return delayed.lt(immediate).astype(float).where(delayed.notna() & immediate.notna())


def training_rows(complete, outcome, as_of):
    """Only use rows whose 21st subsequent price has already been observed."""
    stop = max(0, as_of - HORIZON + 1)
    return np.flatnonzero(complete[:stop] & np.isfinite(outcome[:stop]))


def fit(features, outcome, rows):
    if np.unique(outcome[rows]).size < 2:
        return None
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
    return model.fit(features[rows], outcome[rows])


def evaluate(actual, probability, baseline):
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
    n = len(actual)
    auc = None
    if np.unique(actual).size == 2:
        from sklearn.metrics import roc_auc_score

        auc = roc_auc_score(actual, probability)
    brier = np.mean((actual - probability) ** 2) if n else None
    base_brier = np.mean((actual - baseline) ** 2) if n else None
    skill = 1 - brier / base_brier if base_brier else None
    valid = bool(n >= 250 and skill is not None and skill > 0.01 and auc is not None and auc > 0.55)
    return {
        "valid": valid, "count": n, "auc": auc, "brier": brier,
        "baseline_brier": base_brier, "brier_skill": skill, "calibration": calibration,
    }


def experiment(price, features):
    values = features.to_numpy()
    complete = np.isfinite(values).all(axis=1)
    outcome = targets(price).to_numpy()
    forward = np.full(len(price), np.nan)
    baseline = forward.copy()
    first = next((
        i for i in range(MIN_TRAIN + HORIZON - 1, len(price))
        if len(training_rows(complete, outcome, i)) >= MIN_TRAIN
    ), len(price))
    for as_of in range(first, len(price), STEP):
        rows = training_rows(complete, outcome, as_of)
        model = fit(values, outcome, rows)
        predict = np.flatnonzero(complete[as_of:as_of + STEP]) + as_of
        if model is not None and predict.size:
            forward[predict] = model.predict_proba(values[predict])[:, 1]
            baseline[predict] = outcome[rows].mean()

    tested = np.isfinite(forward) & np.isfinite(outcome)
    metrics = evaluate(outcome[tested], forward[tested], baseline[tested])
    latest = previous = None
    # The adjacent comparisons use information available on each respective date.
    for as_of in range(max(0, len(price) - 2), len(price)):
        model = fit(values, outcome, training_rows(complete, outcome, as_of))
        if model is not None and complete[as_of]:
            prediction = model.predict_proba(values[[as_of]])[0, 1]
            if as_of == len(price) - 1:
                latest = prediction
            else:
                previous = prediction
    return pd.Series(forward, index=price.index), latest, previous, metrics
