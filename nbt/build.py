import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest, indicators, ml, score
from .calendar import export_calendar
from .fetch import DataSource
from .series import domestic_dates, nowcast, price_series
from .settlement import settlement_summary

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9), "JST")
PROXY_ONLY_YEARS = 20
DISCLAIMER = "投資助言ではありません。推定値や予測は外れることがあります。締切・約定日・受渡日は公式画面で確認してください。SBI証券や運用会社とは無関係です。"
SOURCES = [
    {"name": "投資信託協会 投信総合検索ライブラリー", "url": "https://toushin-lib.fwg.ne.jp/"},
    {"name": "Yahoo Finance（指数・ETF・為替・VIX）", "url": "https://finance.yahoo.com/"},
    {"name": "holidays（日本・NYSE の休日）", "url": "https://github.com/vacanza/holidays"},
]
FRACTION_KEYS = {
    "auc", "brier", "baseline_brier", "brier_skill", "probability", "previous_probability",
    "ml_probability_at_most", "ml_prob", "lower", "upper", "mean_probability", "observed_rate",
}


def clean(value, digits=2):
    if isinstance(value, dict):
        return {key: clean(item, 4 if key in FRACTION_KEYS else 2) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item, digits) for item in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), digits) if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    try:
        temp.write_text(json.dumps(clean(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def quote(values):
    if values.empty:
        return None
    latest = values.iloc[-1]
    previous = values.iloc[-2] if len(values) > 1 else None
    return {
        "date": values.index[-1].date().isoformat(), "value": latest,
        "change_pct": (latest / previous - 1) * 100 if previous is not None else None,
        "previous_value": previous,
    }


def build(out, source=None, now=None, run_kind="manual", config=None):
    source = DataSource() if source is None else source
    now = datetime.now(JST) if now is None else now.astimezone(JST)
    if config is None:
        config = json.loads((ROOT / "config/funds.json").read_text(encoding="utf-8"))
    out = Path(out)
    market = {}
    files = {}

    def close(ticker):
        if not ticker:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        if ticker not in market:
            try:
                values = source.close(ticker).dropna().sort_index()
                values = values.loc[~values.index.duplicated(keep="last") & values.gt(0)]
                market[ticker] = values
            except Exception:
                market[ticker] = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        return market[ticker]

    latest = []
    vix = close("^VIX")
    for fund in config["funds"]:
        fund_id = fund["id"]
        nav = pd.DataFrame(columns=["nav", "distribution"], index=pd.DatetimeIndex([]), dtype=float)
        if fund.get("isin") and fund.get("association_code"):
            try:
                nav = source.nav(fund).sort_index()
            except Exception:
                pass
        proxy_cfg = fund.get("proxy", {})
        index = close(proxy_cfg.get("index_ticker"))
        fx = close(proxy_cfg.get("fx_ticker"))
        price, nav, proxy_us, proxy_jp = price_series(nav, index, fx)
        if price.empty:
            raise ValueError(f"利用できる価格系列がありません: {fund_id}")
        has_nav = not nav.empty
        if not has_nav:
            # 代理系列だけの銘柄は、極端に古い指数の履歴(例: 1928 年からの S&P 500)を使わない。
            price = price.loc[price.index >= pd.Timestamp(now.date()) - pd.DateOffset(years=PROXY_ONLY_YEARS)]
        features = indicators.indicators(price, fx if fund.get("fx_component") else None, vix)
        scores, percentiles = score.score_series(features)
        probabilities, latest_prob, previous_prob, metrics = ml.experiment(price, features)
        score_info = score.score_summary(scores, percentiles, features)
        score_info["previous_value"] = scores.iloc[-2] if len(scores) >= 2 else None
        status = {
            "nav": has_nav, "index": not index.empty, "fx": not fx.empty,
            "proxy": not proxy_jp.empty, "vix": not vix.empty, "warnings": [],
        }
        for key, warning in (
            ("nav", "基準価額を取得できなかったため、円換算の代理系列で計算しています。"),
            ("proxy", "円換算の代理系列を取得できなかったため、基準価額で計算しています。"),
            ("fx", "為替データを取得できませんでした。"),
            ("vix", "VIXを取得できなかったため、MLの特徴量から除いています。"),
        ):
            if not status[key]:
                status["warnings"].append(warning)

        nav_quote = quote(nav["nav"])
        index_quote = quote(index)
        fx_quote = quote(fx)
        latest.append({
            **{key: fund[key] for key in ("id", "name", "short_name")},
            "series_kind": "nav" if has_nav else "proxy", "nav": nav_quote,
            "nowcast": nowcast(nav, proxy_us),
            "proxy": {
                "index_ticker": proxy_cfg.get("index_ticker"), "index_label": proxy_cfg.get("index_label"),
                "index": index_quote, "fx": fx_quote,
            },
            "score": score_info,
            "ml": {
                "probability": latest_prob, "previous_probability": previous_prob,
                "date": price.index[-1].date().isoformat(), "valid": metrics["valid"],
                "metrics": {key: value for key, value in metrics.items() if key != "calibration"},
                "note": "過去データで検証した実験モデルです。" if metrics["valid"] else ml.INVALID_NOTE,
            },
            "settlement": settlement_summary(fund, now), "status": status,
        })
        chart = pd.concat({
            "value": price, "nav": nav["nav"], "proxy_jp": proxy_jp,
            "index": domestic_dates(index), "score": scores, "ml_prob": probabilities,
        }, axis=1, sort=True)
        # 画面に要るのは主系列の期間だけ。指数の長い履歴まで載せるとスマホで重くなる。
        chart = chart.loc[chart.index >= price.index[0]]
        files[f"series/{fund_id}.json"] = {
            "dates": chart.index.strftime("%Y-%m-%d").tolist(), **chart.to_dict(orient="list"),
        }
        files[f"backtest/{fund_id}.json"] = backtest.compare(price, scores, probabilities)
        files[f"ml/{fund_id}.json"] = metrics

    stamp = now.isoformat(timespec="seconds")
    files.update({
        "latest.json": {
            "schema": 1, "generated_at": stamp, "run_kind": run_kind, "disclaimer": DISCLAIMER,
            "sources": SOURCES, "default_watch": config["default_watch"], "funds": latest,
        },
        "meta.json": {
            "generated_at": stamp, "run_kind": run_kind,
            "market_dates": {ticker: quote(values)["date"] if not values.empty else None for ticker, values in market.items()},
            "funds": [{
                "id": fund["id"], "nav_date": (fund["nav"] or {}).get("date"),
                "index_date": (fund["proxy"]["index"] or {}).get("date"),
                "fx_date": (fund["proxy"]["fx"] or {}).get("date"), "status": fund["status"],
            } for fund in latest],
        },
        "calendar.json": export_calendar(now.year),
        "push.json": {"vapid_public_key": os.getenv("VAPID_PUBLIC_KEY") or None},
    })
    for name, value in files.items():
        write_json(out / name, value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "site/data")
    parser.add_argument("--run-kind", choices=("morning", "evening", "manual", "push"), default="manual")
    args = parser.parse_args()
    build(args.out, run_kind=args.run_kind)


if __name__ == "__main__":
    main()
