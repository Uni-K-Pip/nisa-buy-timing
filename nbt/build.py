import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest, indicators, ledger as forward_log, macro, ml, score, validation
from .calendar import export_calendar, latest_us_session
from .fetch import DataSource
from .ledger import JST
from .series import _domestic_range, domestic_dates, estimated_series, latest_estimate, nowcast, price_series, remove_fx_outliers
from .settlement import settlement_summary

ROOT = Path(__file__).resolve().parents[1]
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
    "auc_ci", "brier_skill_ci", "auc_confirmed", "auc_estimate", "brier_skill_confirmed",
    "brier_skill_estimate", "prob_abs_diff_mean", "prob_abs_diff_p95", "probability_at_most", "level", "signal", "close",
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


def write_json(path, value, *, prepared=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    try:
        data = value if prepared else clean(value)
        temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
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


def _last_date(values):
    return values.index[-1].date().isoformat() if len(values) else None


def _coverage(base, features, signal):
    base_complete = np.isfinite(base.to_numpy()).all(axis=1)
    complete = np.isfinite(features.to_numpy()).all(axis=1) if features is not None else np.zeros(len(base), dtype=bool)
    predicted = signal.dropna()
    return clean({
        "days": len(base), "base_complete": base_complete.sum(), "complete": complete.sum(),
        "excluded_by_macro": (base_complete & ~complete).sum(), "predicted": len(predicted),
        "first_prediction": predicted.index[0].date().isoformat() if len(predicted) else None,
    })


def _registered_ml(entry, price, base, decision, macro_series, lag, nav_start, basis):
    groups = entry["features"][1:]
    features = inputs = None
    signal = pd.Series(np.nan, index=price.index)
    metrics = None
    reason = None
    try:
        extra = macro.features(macro_series, price.index.union(decision.index), groups)
        if extra is None:
            reason = macro.UNAVAILABLE
        else:
            features, inputs = base.join(extra), decision.join(extra)
            signal, _, _, metrics = ml.experiment(
                price, features, inputs, lag=lag, registered=entry["registered"], nav_start=nav_start, latest_basis=basis,
            )
    except Exception as error:
        reason = type(error).__name__
    fields = {
        "features": entry["features"], "feature_names": list(base.columns) + macro.feature_names(groups),
        "metrics": clean(metrics), "coverage": _coverage(base, features, signal), "macro": macro.metadata(macro_series),
    }
    return signal, features, inputs, fields, reason


def _decision(now, run_kind, fund, entry, price, features, inputs, point, signals, percentiles, input_dates, reason):
    if not forward_log.is_decision_time(now, fund):
        return None
    day = pd.Timestamp(now.date())
    basis = "estimate" if point is not None and point[0] == day else None
    signal = values = train = None
    if reason is None and basis is None:
        reason = "no_estimate"
    if reason is None:
        if entry["kind"] == "score":
            columns = percentiles.loc[day].dropna().index
            values = inputs.loc[day, columns].to_dict()
            signal = signals.loc[day]
            if not np.isfinite(signal):
                signal, reason = None, "features_incomplete"
        else:
            values = inputs.loc[day].to_dict()
            signal, count, last, reason = ml.decision_probability(
                price, features, inputs, day, lag=fund["settlement"]["trade_lag_bd"],
            )
            train = {"count": count, "last": last}
    return forward_log.make_row(
        now, run_kind, entry, fund, basis=basis, signal=signal, reason=reason, features=values, inputs=input_dates, train=train,
    )


def _save_ledger(folder, records):
    appended = 0
    errors = {}
    for fund, entry, artifact, row, signal in records:
        path = forward_log.path_for(folder, entry, fund)
        try:
            if row is not None:
                appended += forward_log.append(path, row)
            artifact["ledger"] = forward_log.reconcile(forward_log.read(path), signal, entry)
        except Exception as error:
            errors.setdefault(fund["id"], {})[entry["id"]] = type(error).__name__
    return {"appended": appended, "ok": not errors, "errors": errors}


def _write_exploration(folder, datasets, macro_series, run, draws):
    from . import explore

    results = []
    macro_data = macro.metadata(macro_series, include_first=True)
    for fund, price, base, decision, nav_start, probabilities in datasets:
        extra = macro.features(macro_series, price.index.union(decision.index), ["rates_dollar"])
        if extra is None:
            raise ValueError(macro.UNAVAILABLE)
        results.append(explore.evaluate(fund, price, base, decision, extra, nav_start, probabilities, macro_data, run, draws))
    folder.mkdir(parents=True, exist_ok=True)
    for result in results:
        write_json(folder / f"{result['fund']['id']}.json", result, prepared=True)
    (folder / "report.md").write_text(explore.report(results), encoding="utf-8", newline="\n")


def build(out, source=None, now=None, run_kind="manual", config=None, registration=None, ledger=None, explore=None):
    source = DataSource() if source is None else source
    now = datetime.now(JST) if now is None else now.astimezone(JST)
    expected_us_date = latest_us_session(now).isoformat()
    latest_close = {"expected_us_date": expected_us_date, "filled": {}, "unfilled": {}, "stale": {}}
    if config is None:
        config = json.loads((ROOT / "config/funds.json").read_text(encoding="utf-8"))
    registration = validation.load_registration(registration)
    ml_registered = next((entry["registered"] for entry in registration["strategies"] if entry["id"] == "ml"), None)
    out = Path(out)
    stamp = now.isoformat(timespec="seconds")
    explore_run = None
    if explore is not None:
        from .explore import run_info

        explore = Path(explore)
        explore_run = run_info(stamp, registration)
    market = {}
    fx_market = {}
    empty_fx = pd.DataFrame(columns=["open", "close"], index=pd.DatetimeIndex([]), dtype=float)
    files = {}
    registered_files = {}
    ledger_records = []
    explore_datasets = []
    macro_errors = {}

    def close(ticker, *, allow_nonpositive=False):
        if not ticker:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        if ticker not in market:
            try:
                values = source.close(ticker).dropna().sort_index()
                values = values.loc[~values.index.duplicated(keep="last")]
                if not allow_nonpositive:
                    values = values.loc[values.gt(0)]
                market[ticker] = values
            except Exception:
                market[ticker] = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
            note = getattr(source, "close_notes", {}).get(ticker)
            if note is not None:
                latest_close[note["status"]][ticker] = {key: value for key, value in note.items() if key != "status"}
        return market[ticker]

    def fx_quotes(ticker):
        if ticker and ticker not in fx_market:
            try:
                values = source.fx(ticker)[["open", "close"]].dropna().sort_index()
                values = values.loc[~values.index.duplicated(keep="last") & values.gt(0).all(axis=1)]
                fx_market[ticker] = pd.concat(
                    {key: remove_fx_outliers(values[key]) for key in values.columns}, axis=1, sort=True,
                )
            except Exception:
                fx_market[ticker] = empty_fx
        return fx_market.get(ticker, empty_fx)

    latest = []
    vix = close("^VIX")
    macro_series = {name: close(info["ticker"], allow_nonpositive=info.get("allow_nonpositive", False))
                    for name, info in macro.SERIES.items()}
    shared_tickers = ("^VIX", *(info["ticker"] for info in macro.SERIES.values()))
    for fund in config["funds"]:
        fund_id = fund["id"]
        nav = pd.DataFrame(columns=["nav", "distribution"], index=pd.DatetimeIndex([]), dtype=float)
        if fund.get("isin") and fund.get("association_code"):
            try:
                nav = source.nav(fund).sort_index()
            except Exception:
                pass
        proxy_cfg = fund.get("proxy", {})
        index_ticker = proxy_cfg.get("index_ticker")
        index = close(index_ticker)
        fx = fx_quotes(proxy_cfg.get("fx_ticker"))
        price, nav, proxy_jp, daily_fx, nav_start = price_series(nav, index, fx)
        if price.empty:
            raise ValueError(f"利用できる価格系列がありません: {fund_id}")
        has_nav = nav_start is not None
        if not has_nav:
            # 代理系列だけの銘柄は、極端に古い指数の履歴(例: 1928 年からの S&P 500)を使わない。
            price = price.loc[price.index >= pd.Timestamp(now.date()) - pd.DateOffset(years=PROXY_ONLY_YEARS)]
        score_fx = daily_fx if fund.get("fx_component") else None
        features = indicators.indicators(price, score_fx, vix)
        scores, percentiles = score.score_series(features)
        score_info = score.score_summary(scores, percentiles, features)
        point = latest_estimate(price, proxy_jp)
        estimated = estimated_series(price, proxy_jp, nav_start)
        extended_price = price
        extended_estimate = estimated
        if point is not None:
            day, value = point
            latest_price = pd.Series([value], index=[day])
            extended_price = pd.concat([price, latest_price])
            extended_estimate = pd.concat([estimated, latest_price])
        decision = indicators.decision_indicators(extended_price, extended_estimate, score_fx, vix)
        decision_scores, decision_pct = score.decision_score_series(features, decision)
        if point is None:
            score_info["basis"] = "confirmed"
            score_info["previous_value"] = scores.iloc[-2] if len(scores) >= 2 else None
        else:
            confirmed = {key: score_info[key] for key in ("value", "category", "category_name", "date")}
            score_info = score.score_summary(decision_scores, decision_pct, decision)
            score_info.update(basis="estimate", previous_value=decision_scores.loc[price.index[-1]], confirmed=confirmed)
        # NAV が欠けた国内営業日も、ML の約定日と予測期間の日数に数える。
        ml_days = _domestic_range(price.index[0], price.index[-1])
        ml_basis = "estimate" if point is not None else "confirmed"
        ml_price = price.reindex(ml_days)
        ml_features = features.reindex(ml_days)
        lag = fund["settlement"]["trade_lag_bd"]
        probabilities, latest_prob, previous_prob, metrics = ml.experiment(
            ml_price, ml_features, decision, lag=lag, registered=ml_registered, nav_start=nav_start, latest_basis=ml_basis,
        )
        if explore is not None:
            explore_datasets.append((fund, ml_price, ml_features, decision, nav_start, probabilities))
        probabilities = probabilities.reindex(price.index)
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
        if index_quote is not None and index_quote["date"] < expected_us_date:
            index_date = index_quote["date"]
            status["warnings"].append(
                f"指数の直近の終値({expected_us_date})を取得できませんでした。{index_date} までの値で計算しています。"
            )
            latest_close["stale"][index_ticker] = index_date
        fx_quote = quote(fx["close"].dropna())
        latest.append({
            **{key: fund[key] for key in ("id", "name", "short_name")},
            "series_kind": "nav" if has_nav else "proxy", "nav": nav_quote,
            "nowcast": nowcast(nav, proxy_jp, index),
            "proxy": {
                "index_ticker": index_ticker, "index_label": proxy_cfg.get("index_label"),
                "index": index_quote, "fx": fx_quote,
            },
            "score": score_info,
            "ml": {
                "probability": latest_prob, "previous_probability": previous_prob,
                "date": decision.index[-1].date().isoformat(), "valid": metrics["valid"],
                "basis": ml_basis,
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
        chart = chart.loc[nav_start:price.index[-1]] if has_nav else chart.loc[price.index[0]:]
        files[f"series/{fund_id}.json"] = {
            "dates": chart.index.strftime("%Y-%m-%d").tolist(), **chart.to_dict(orient="list"),
        }
        input_dates = {"nav": _last_date(nav), "index": _last_date(index), "fx": _last_date(fx), "vix": _last_date(vix),
                       **{name: _last_date(values) for name, values in macro_series.items()}}
        filled_tickers = [ticker for ticker in (index_ticker, *shared_tickers) if ticker in latest_close["filled"]]
        if filled_tickers:
            input_dates["filled"] = filled_tickers
        variants = {}
        signals, unavailable = {}, {}
        for entry in registration["strategies"]:
            name = entry["id"]
            extra_fields, reason = {}, None
            decision_features, training = decision, ml_features
            if entry["kind"] == "score":
                signal = decision_scores
            elif name == "ml" and entry["features"] == ["base"]:
                signal = probabilities
            else:
                signal, training, decision_features, extra_fields, reason = _registered_ml(
                    entry, ml_price, ml_features, decision, macro_series, lag, nav_start, ml_basis,
                )
            try:
                row = _decision(now, run_kind, fund, entry, ml_price, training, decision_features, point,
                                signal, decision_pct, input_dates, reason)
            except Exception as error:
                if extra_fields:
                    reason = type(error).__name__
                row = _decision(now, run_kind, fund, entry, ml_price, training, decision_features, point,
                                signal, decision_pct, input_dates, reason or "model_unavailable")
            if reason is not None:
                unavailable[name] = reason
            signals[name] = signal
            variants[name] = (entry, extra_fields, row)

        files[f"backtest/{fund_id}.json"] = backtest.compare(
            price, decision_scores, probabilities, fund=fund, confirmed_scores=scores, nav_start=nav_start,
            registration=registration, today=now.date(), registered_signals=signals, unavailable=unavailable,
        )
        files[f"ml/{fund_id}.json"] = metrics
        registered = {}
        for name, (entry, extra_fields, row) in variants.items():
            evidence = files[f"backtest/{fund_id}.json"]["evidence"]["strategies"][name]
            reason = evidence.get("unavailable")
            if reason is not None and extra_fields:
                macro_errors.setdefault(fund_id, {})[name] = reason
                if row is not None:
                    row = forward_log.make_row(now, run_kind, entry, fund, basis=row["basis"], reason=reason, inputs=input_dates)
            artifact = {key: entry[key] for key in ("kind", "version", "registered", "fingerprint")} | {
                "available": reason is None, "reason": reason,
                "decision": {key: value for key, value in row.items() if key not in ("features", "inputs", "train")} if row else None,
                "ledger": None, **extra_fields,
            }
            registered[name] = artifact
            if ledger is not None:
                ledger_records.append((fund, entry, artifact, row, signals[name] if reason is None else pd.Series(dtype=float)))
        registered_files[f"registered/{fund_id}.json"] = {"schema": 1, "strategies": registered}

    market_quotes = market | {ticker: values["close"].dropna() for ticker, values in fx_market.items()}
    macro_available = all(not values.empty for values in macro_series.values())
    files.update({
        "latest.json": {
            "schema": 1, "generated_at": stamp, "run_kind": run_kind, "disclaimer": DISCLAIMER,
            "sources": SOURCES, "default_watch": config["default_watch"], "funds": latest,
        },
        "meta.json": {
            "generated_at": stamp, "run_kind": run_kind,
            "market_dates": {ticker: _last_date(values) for ticker, values in market_quotes.items()},
            "latest_close": latest_close,
            "macro": {"available": macro_available, "series": macro.metadata(macro_series),
                      "unavailable": macro_errors},
            "funds": [{
                "id": fund["id"], "nav_date": (fund["nav"] or {}).get("date"),
                "index_date": (fund["proxy"]["index"] or {}).get("date"),
                "fx_date": (fund["proxy"]["fx"] or {}).get("date"), "status": fund["status"],
            } for fund in latest],
        },
        "calendar.json": export_calendar(now.year),
        "push.json": {"vapid_public_key": os.getenv("VAPID_PUBLIC_KEY") or None},
    })
    if ledger is not None:
        files["meta.json"]["ledger"] = _save_ledger(ledger, ledger_records)
    for name, value in files.items():
        write_json(out / name, value)
    for name, value in registered_files.items():
        write_json(out / name, value, prepared=True)
    if explore is not None:
        if not macro_available:
            raise ValueError(macro.UNAVAILABLE)
        roots = [out.resolve()] + ([Path(ledger).resolve()] if ledger is not None else [])
        if any(explore.resolve().is_relative_to(root) for root in roots):
            raise ValueError("探索の出力先は通常の出力先と台帳の外に指定してください")
        _write_exploration(explore, explore_datasets, macro_series, explore_run, registration["protocol"]["bootstrap_draws"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "site/data")
    parser.add_argument("--run-kind", choices=("morning", "evening", "manual", "push"), default="manual")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--explore", type=Path)
    args = parser.parse_args()
    build(args.out, run_kind=args.run_kind, ledger=args.ledger, explore=args.explore)


if __name__ == "__main__":
    main()
