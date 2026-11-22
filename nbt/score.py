import pandas as pd

WEIGHTS = {"dd252": 0.30, "ma200_dev": 0.25, "ma25_dev": 0.15, "rsi14": 0.20, "fx_dev": 0.10}
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
    percentiles = features[weights.index].rolling(1260, min_periods=120).rank(method="max", pct=True)
    weighted = (100 * (1 - percentiles)).mul(weights)
    available = percentiles.notna().mul(weights).sum(axis=1)
    return weighted.sum(axis=1, min_count=1) / available, percentiles


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
