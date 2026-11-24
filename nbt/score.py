import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

WEIGHTS = {"dd252": 0.30, "ma200_dev": 0.25, "ma25_dev": 0.15, "rsi14": 0.20, "fx_dev": 0.10}
WINDOW = 1260
MIN_PERIODS = 120
NAMES = {
    "dd252": "52週高値から",
    "ma200_dev": "200日移動平均から",
    "ma25_dev": "25日移動平均から",
    "rsi14": "RSI(14)",
    "fx_dev": "為替の200日移動平均から",
}
COMPARISON = "過去5年の同じ投信との比較（最大5年、120営業日以上）"


def score_series(features):
    weights = pd.Series(WEIGHTS).reindex(features.columns).dropna()
    percentiles = features[weights.index].rolling(WINDOW, min_periods=MIN_PERIODS).rank(method="max", pct=True)
    return _weighted_score(percentiles, weights), percentiles


def _weighted_score(percentiles, weights):
    weighted = (100 * (1 - percentiles)).mul(weights)
    available = percentiles.notna().mul(weights).sum(axis=1)
    return weighted.sum(axis=1, min_count=1) / available


def decision_score_series(confirmed, estimated):
    weights = pd.Series(WEIGHTS).reindex(estimated.columns).dropna()
    percentiles = pd.DataFrame(index=estimated.index)
    for key in weights.index:
        history = confirmed[key].reindex(estimated.index).to_numpy(dtype=float)
        history = np.where(np.isfinite(history), history, np.nan)
        # 今日の行を窓に入れず、推定値自身を分子と分母に 1 件ずつ加える。
        padded = np.pad(history, (WINDOW - 1, 0), constant_values=np.nan)
        previous = sliding_window_view(padded, WINDOW - 1)[:-1]
        value = estimated[key].to_numpy(dtype=float)
        total = (~np.isnan(previous)).sum(axis=1) + 1
        below_or_equal = (previous <= value[:, None]).sum(axis=1) + 1
        percentiles[key] = np.where(
            np.isfinite(value) & (total >= MIN_PERIODS), below_or_equal / total, np.nan,
        )
    return _weighted_score(percentiles, weights), percentiles


def category(value):
    if pd.isna(value):
        return None, "算出できません"
    for limit, key, name in (
        (80, "very_cheap", "かなり割安圏"), (60, "cheap", "割安寄り"),
        (40, "neutral", "中立"), (20, "expensive", "割高寄り"),
    ):
        if value >= limit:
            return key, name
    return "very_expensive", "かなり割高圏"


def score_summary(scores, percentiles, features):
    value = scores.iloc[-1]
    key, name = category(value)
    elements = []
    row = percentiles.iloc[-1].dropna()
    active_weight = sum(WEIGHTS[key] for key in row.index)
    for feature, pct in row.items():
        indicator = features[feature].iloc[-1]
        display = f"{indicator:.1f}" if feature == "rsi14" else f"{indicator:+.1%}"
        elements.append({
            "key": feature,
            "value": indicator if feature == "rsi14" else indicator * 100,
            "percentile": pct * 100,
            "contribution": 100 * (1 - pct) * WEIGHTS[feature] / active_weight,
            "description": f"{NAMES[feature]} {display}（過去5年で安い方から {pct:.0%}）",
        })
    return {
        "value": value, "category": key, "category_name": name,
        "date": scores.index[-1].date().isoformat(),
        "comparison": COMPARISON,
        "elements": sorted(elements, key=lambda item: item["contribution"], reverse=True),
    }
