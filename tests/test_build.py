from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

from nbt import ledger, macro, ml
from nbt.build import JST, build, clean
from nbt.indicators import indicators
from nbt.score import score_series, score_summary
from nbt.series import price_series
from nbt.validation import load_registration


class FakeSource:
    def __init__(self, fail_nav=False, fail_index=False, estimate=True, fail_fx=False, fail_macro=False, market_end=None):
        self.fail_nav = fail_nav
        self.fail_index = fail_index
        self.fail_fx = fail_fx
        self.fail_macro = fail_macro
        end = market_end or ("2026-11-20" if estimate else "2026-11-19")
        self.dates = pd.bdate_range("2025-04-01", end)

    def nav(self, fund):
        if self.fail_nav:
            raise OSError
        dates = pd.bdate_range("2025-08-01", "2026-11-20")
        return pd.DataFrame({"nav": np.arange(1000.0, 1000.0 + len(dates)), "distribution": 0.0}, index=dates)

    def close(self, ticker):
        if self.fail_index and ticker == "^NYFANG":
            raise OSError
        if ticker in {item["ticker"] for item in macro.SERIES.values()}:
            if self.fail_macro and ticker == "DX-Y.NYB":
                raise OSError
            dates = pd.bdate_range("2024-01-04", self.dates[-1])
            pattern = np.sin(np.arange(len(dates)) / 40)
            return pd.Series({"^TNX": 4.2, "^IRX": -0.1, "DX-Y.NYB": 100.0}[ticker] + 0.05 * pattern, index=dates)
        assert ticker != "USDJPY=X"
        values = pd.Series(np.arange(100.0, 100.0 + len(self.dates)), index=self.dates)
        values.iloc[-2] *= 1.2
        return values

    def fx(self, ticker):
        if self.fail_fx:
            raise OSError
        assert ticker == "USDJPY=X"
        opening = 120.0 + np.arange(len(self.dates)) / 10
        closing = opening + 1.5
        opening[-3] *= 1.2
        closing[-2] *= 1.2
        return pd.DataFrame({"open": opening, "close": closing}, index=self.dates)


class DecisionSource(FakeSource):
    def nav(self, fund):
        frame = super().nav(fund)
        frame["nav"] = 1000 + 100 * np.sin(np.arange(len(frame)) / 12)
        return frame


@pytest.mark.parametrize("estimate", [True, False])
def test_fake_build_file_contract(tmp_path, monkeypatch, estimate):
    def blocked(*args, **kwargs):
        pytest.fail("network access")

    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "synthetic-public-key")
    source = FakeSource(estimate=estimate)
    build(tmp_path, source, datetime(2026, 11, 22, 9, tzinfo=JST), run_kind="morning")

    def read(name):
        return json.loads((tmp_path / name).read_text(encoding="utf-8"))

    latest = read("latest.json")
    assert {"schema", "generated_at", "run_kind", "disclaimer", "sources", "funds"} <= latest.keys()
    assert latest["generated_at"] == "2026-11-22T09:00:00+09:00"
    assert latest["run_kind"] == "morning"
    assert len(latest["funds"]) == 3
    assert all({"name", "url"} <= source.keys() for source in latest["sources"])
    assert read("push.json") == {"vapid_public_key": "synthetic-public-key"}
    assert {"years", "JP", "NYSE"} == read("calendar.json").keys()
    assert read("calendar.json")["years"] == [2026, 2027]
    meta = read("meta.json")
    assert {"generated_at", "funds", "market_dates"} <= meta.keys()
    assert meta["market_dates"]["USDJPY=X"] == source.dates[-1].date().isoformat()
    expected = {"latest.json", "meta.json", "push.json", "calendar.json"}
    for fund in latest["funds"]:
        assert {
            "id", "name", "short_name", "series_kind", "nav", "nowcast", "proxy", "score",
            "ml", "settlement", "status",
        } == fund.keys()
        assert {"date", "value", "change_pct"} <= fund["nav"].keys()
        if estimate:
            assert {"us_date", "value", "change_pct", "error_pct"} == fund["nowcast"].keys()
        else:
            assert fund["nowcast"] is None
        assert {"index_ticker", "index_label", "index", "fx"} == fund["proxy"].keys()
        assert {"value", "category", "category_name", "elements", "date", "comparison",
                "previous_value", "basis"} <= fund["score"].keys()
        assert {"probability", "date", "valid", "metrics", "note"} <= fund["ml"].keys()
        assert fund["nav"]["date"] == "2026-11-20"
        assert fund["ml"]["basis"] == ("estimate" if estimate else "confirmed")
        assert fund["ml"]["date"] == ("2026-11-24" if estimate else "2026-11-20")
        assert {"last_order_date", "last_settle_date", "remaining_business_days", "upcoming_orders",
                "verified", "trade_lag_bd", "settle_bd_from_order", "order_cutoff_jst"} <= fund["settlement"].keys()
        assert {"nav", "index", "fx", "proxy", "vix", "warnings"} == fund["status"].keys()
        assert fund["series_kind"] == "nav"
        assert fund["settlement"]["verified"] is False
        fund_id = fund["id"]
        names = [f"{kind}/{fund_id}.json" for kind in ("series", "backtest", "ml")]
        expected.update(names)
        series, backtest, ml = (read(name) for name in names)
        assert {"dates", "value", "nav", "proxy_jp", "index", "score", "ml_prob"} == series.keys()
        assert len({len(values) for values in series.values()}) == 1
        assert series["dates"][0] == "2025-08-01"
        assert series["dates"][-1] == "2026-11-20"
        assert None in series["ml_prob"]
        assert set(backtest) == {
            "schema", "description", "ml_probability_at_most", "periods", "grid",
            "grid_summary", "evidence", "estimate_impact",
        }
        assert backtest["schema"] == 2
        assert backtest["periods"]["nav"] == {"from": series["dates"][0], "to": series["dates"][-1]}
        assert len(backtest["grid"]) == 60
        assert {"auc", "brier", "baseline_brier", "brier_skill", "count", "valid", "calibration",
                "auc_ci", "brier_skill_ci", "independent", "forward", "estimate_impact"} == ml.keys()
        assert set(ml["forward"]) == {"count", "auc", "brier_skill", "auc_ci", "brier_skill_ci"}
        assert set(ml["estimate_impact"]) == {
            "prob_abs_diff_mean", "prob_abs_diff_p95", "auc_confirmed", "brier_skill_confirmed",
            "auc_estimate", "brier_skill_estimate",
        }
        assert set(backtest["estimate_impact"]) == {
            "score_abs_diff_mean", "score_abs_diff_p95", "category_mismatch_rate", "threshold_mismatch_rate", "days", "primary",
        }
        basic = {"count", "independent", "mean", "median", "win_rate", "p05", "p95", "ci"}
        strategy_keys = basic | {"delay", "vs_lump", "vs_placebo"}
        for item in backtest["grid"]:
            for strategy, keys in (("score", strategy_keys), ("ml", strategy_keys), ("lump", basic)):
                assert item[strategy].keys() == {"all", "nav", "recent_3y"}
                assert all(set(period) == keys for period in item[strategy].values())
        evidence = backtest["evidence"]
        assert evidence["protocol"]["level"] == 0.998
        assert evidence["strategies"].keys() == {"score", "ml", "ml-macro"}
        for strategy in evidence["strategies"].values():
            assert strategy["looks"]["last"] is None
            assert strategy["comparisons"].keys() == {"regular", "lump", "placebo"}
            for comparison in strategy["comparisons"].values():
                assert comparison.keys() == {"status", "history", "history_nav", "forward", "judgment"}
                assert comparison["history"].keys() == basic | {"t_ci"}
                assert comparison["forward"].keys() == basic | {"years"}
                assert comparison["judgment"] is None

        name = f"registered/{fund['id']}.json"
        expected.add(name)
        registered = read(name)
        assert registered["schema"] == 1
        assert registered["strategies"].keys() == evidence["strategies"].keys()
        assert all(entry["available"] and entry["ledger"] is None and entry["decision"] is None
                   for entry in registered["strategies"].values())
        model = registered["strategies"]["ml-macro"]
        assert model["features"] == ["base", "rates_dollar"]
        assert model["feature_names"][-5:] == list(macro.RATES_DOLLAR_NAMES)
        assert model["metrics"].keys() == ml.keys()
        assert model["coverage"]["complete"] > 0
        assert model["macro"]["us3m"]["last"] == source.dates[-1].date().isoformat()

        index = source.close(fund["proxy"]["index_ticker"])
        fx = source.fx("USDJPY=X")
        fx.loc[fx.index[-3], "open"] = np.nan
        fx.loc[fx.index[-2], "close"] = np.nan
        assert fund["proxy"]["index"]["previous_value"] == clean(index.iloc[-2])
        assert fund["proxy"]["fx"]["value"] == clean(fx["close"].iloc[-1])
        assert fund["proxy"]["fx"]["previous_value"] == clean(fx["close"].iloc[-3])
        price, _, proxy, daily_fx, nav_start = price_series(source.nav(fund), index, fx)
        assert price.index[0] < nav_start
        assert series["proxy_jp"] == clean(proxy.reindex(pd.to_datetime(series["dates"])).tolist())
        vix = source.close("^VIX")
        confirmed = indicators(price, daily_fx, vix)
        scores, pct = score_series(confirmed)
        confirmed_score = score_summary(scores, pct, confirmed)
        assert series["value"][-1] == clean(price.iloc[-1])
        assert series["score"][-1] == clean(scores.iloc[-1])
        if not estimate:
            expected_score = dict(confirmed_score, basis="confirmed", previous_value=scores.iloc[-2])
        else:
            day = pd.Timestamp("2026-11-24")
            latest_price = price.iloc[-1] * proxy.loc[day] / proxy.asof(price.index[-1])
            assert daily_fx.loc[day] == fx["close"].iloc[-1]
            assert fund["nowcast"]["us_date"] == index.index[-1].date().isoformat()
            assert fund["nowcast"]["value"] == clean(latest_price)
            extended = pd.concat([price, pd.Series([latest_price], index=[day])])
            latest_features = indicators(extended, daily_fx, vix)
            latest_scores, latest_pct = score_series(latest_features)
            expected_score = score_summary(latest_scores, latest_pct, latest_features)

            replaced = price.copy()
            replaced.iloc[-1] = price.iloc[-2] * proxy.asof(price.index[-1]) / proxy.asof(price.index[-2])
            previous_scores, _ = score_series(indicators(replaced, daily_fx, vix))
            assert clean(previous_scores.iloc[-1]) != clean(scores.iloc[-1])
            expected_score.update(
                basis="estimate", previous_value=previous_scores.iloc[-1],
                confirmed={key: confirmed_score[key] for key in ("value", "category", "category_name", "date")},
            )
        assert fund["score"] == clean(expected_score)
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.json")} == expected


@pytest.mark.parametrize(("missing", "expected"), [("nav", "proxy"), ("index", "nav"), ("fx", "nav")])
def test_build_degrades_and_records_warnings(tmp_path, missing, expected):
    source = FakeSource(fail_nav=missing == "nav", fail_index=missing == "index", fail_fx=missing == "fx")
    build(tmp_path, source, datetime(2026, 11, 22, 9, tzinfo=JST))
    first = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["funds"][0]
    assert first["series_kind"] == expected
    assert not first["status"][missing]
    assert first["status"]["proxy"] == (missing == "nav")
    assert first["status"]["warnings"]
    if missing == "nav":
        backtest = json.loads((tmp_path / "backtest" / f"{first['id']}.json").read_text(encoding="utf-8"))
        ml = json.loads((tmp_path / "ml" / f"{first['id']}.json").read_text(encoding="utf-8"))
        assert backtest["periods"]["nav"] is None
        assert backtest["estimate_impact"] is None
        assert ml["estimate_impact"] is None
    if missing == "fx":
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
        assert meta["market_dates"]["USDJPY=X"] is None
        assert first["proxy"]["fx"] is None


def test_no_price_does_not_replace_published_data(tmp_path):
    previous = tmp_path / "latest.json"
    previous.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="価格系列"):
        build(tmp_path, FakeSource(fail_nav=True, fail_index=True))
    assert previous.read_text(encoding="utf-8") == "{}"


def test_json_precision():
    assert clean({"probability": np.float64(0.412345), "price": 200.123, "error": np.nan}) == {
        "probability": 0.4123, "price": 200.12, "error": None,
    }


def test_build_uses_injected_registration_and_now(tmp_path):
    registration = load_registration()
    for entry in registration["strategies"]:
        entry["registered"] = "2024-11-24"
    source = FakeSource()
    name = "backtest/ifree-next-fang-plus.json"
    for day in (23, 24):
        build(tmp_path, source, datetime(2026, 11, day, 9, tzinfo=JST), registration=registration)
        artifact = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        strategy = artifact["evidence"]["strategies"]["score"]
        assert strategy["registered"] == "2024-11-24"
        result = strategy["comparisons"]["regular"]["judgment"]
        if day == 23:
            assert result is None
        else:
            assert result["look"] == "2026-11-24"
            assert result["level"] == 0.998


def _small_build(fund_indices=(0,)):
    config = json.loads((Path("config") / "funds.json").read_text(encoding="utf-8"))
    config["funds"] = [config["funds"][index] for index in fund_indices]
    registration = load_registration()
    registration["protocol"]["bootstrap_draws"] = 8
    return config, registration, config["funds"][0]["id"]


def _outputs(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*.json")}


def _existing_outputs(files, fund_id):
    backtest_name = f"backtest/{fund_id}.json"
    backtest = json.loads(files[backtest_name])
    backtest["evidence"]["strategies"].pop("ml-macro")
    return {name: value for name, value in files.items() if name not in ("meta.json", backtest_name)
            and not name.startswith("registered/")} | {backtest_name: backtest}


def test_missing_macro_and_macro_exception_preserve_existing_outputs(tmp_path, monkeypatch):
    config, registration, fund_id = _small_build()
    now = datetime(2026, 11, 24, 9, tzinfo=JST)
    out = tmp_path / "out"
    build(out, FakeSource(), now, config=config, registration=registration)
    reference = _existing_outputs(_outputs(out), fund_id)
    assert json.loads((out / "meta.json").read_bytes())["macro"]["available"]

    def check(reason):
        files = _outputs(out)
        assert _existing_outputs(files, fund_id) == reference
        info = json.loads(files[f"registered/{fund_id}.json"])["strategies"]["ml-macro"]
        assert not info["available"] and info["reason"] == reason
        evidence = json.loads(files[f"backtest/{fund_id}.json"])["evidence"]["strategies"]["ml-macro"]
        assert evidence["comparisons"] is None and evidence["unavailable"] == reason
        assert json.loads(files["meta.json"])["macro"]["unavailable"][fund_id]["ml-macro"] == reason

    with pytest.raises(ValueError, match="macro_unavailable"):
        build(out, FakeSource(fail_macro=True), now, config=config, registration=registration, explore=tmp_path / "explore")
    assert not (tmp_path / "explore").exists()
    check("macro_unavailable")

    def fail(*args, **kwargs):
        raise RuntimeError

    monkeypatch.setattr(macro, "features", fail)
    build(out, FakeSource(), now, config=config, registration=registration)
    check("RuntimeError")


def test_ledger_opt_in_io_failure_and_exploration_isolation(tmp_path, monkeypatch):
    config, registration, fund_id = _small_build()
    monkeypatch.setattr(ml, "MIN_TRAIN", 20)
    out, log, exploration = (tmp_path / name for name in ("out", "log", "explore"))
    now = datetime(2026, 11, 24, 9, tzinfo=JST)

    def unexpected(*args, **kwargs):
        pytest.fail("ledger I/O without --ledger")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "read", unexpected)
        patch.setattr(ledger, "append", unexpected)
        build(out, FakeSource(), now, config=config, registration=registration)
        assert not log.exists()
    base = _outputs(out)
    assert "ledger" not in json.loads(base["meta.json"])
    score = json.loads(base[f"registered/{fund_id}.json"])["strategies"]["score"]["decision"]
    assert score["date"] == "2026-11-24" and score["status"] == "ok"
    assert {"features", "inputs", "train"}.isdisjoint(score)

    build(out, FakeSource(), now, config=config, registration=registration, ledger=log)
    assert json.loads((out / "meta.json").read_bytes())["ledger"]["appended"] == 3
    paths = sorted(log.rglob("*.jsonl"))
    before_log = [path.read_bytes() for path in paths]
    assert len(paths) == 3 and all(len(data.splitlines()) == 1 for data in before_log)
    assert json.loads((out / f"registered/{fund_id}.json").read_bytes())["strategies"]["score"]["ledger"]["ok_days"] == 1

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "read", unexpected)
        patch.setattr(ledger, "append", unexpected)
        build(out, FakeSource(), now, config=config, registration=registration, explore=exploration)
    assert _outputs(out) == base
    assert [path.read_bytes() for path in paths] == before_log
    assert {path.name for path in exploration.iterdir()} == {f"{fund_id}.json", "report.md"}
    result = json.loads((exploration / f"{fund_id}.json").read_bytes())
    assert result["kind"] == "exploration"
    assert "探索の結果" in (exploration / "report.md").read_text(encoding="utf-8")

    log_is_file = tmp_path / "unwritable-log"
    log_is_file.touch()
    build(out, FakeSource(), now, config=config, registration=registration, ledger=log_is_file)
    files = _outputs(out)
    assert _existing_outputs(files, fund_id) == _existing_outputs(base, fund_id)
    state = json.loads(files["meta.json"])["ledger"]
    assert not state["ok"] and state["appended"] == 0
    assert state["errors"][fund_id].keys() == {"score", "ml", "ml-macro"}


@pytest.mark.parametrize(("jst_day", "market_end", "expected", "warnings"), [
    (25, "2026-11-23", "2026-11-24",
     ["指数の直近の終値(2026-11-24)を取得できませんでした。2026-11-23 までの値で計算しています。"]),
    (25, "2026-11-24", "2026-11-24", []),
    (27, "2026-11-25", "2026-11-25", []),
])
def test_build_stale_index_warning(tmp_path, monkeypatch, jst_day, market_end, expected, warnings):
    config, registration, _ = _small_build()
    ticker = config["funds"][0]["proxy"]["index_ticker"]
    monkeypatch.setattr(ml, "MIN_TRAIN", 20)
    build(tmp_path, FakeSource(market_end=market_end), datetime(2026, 11, jst_day, 9, tzinfo=JST),
          config=config, registration=registration)

    latest = json.loads((tmp_path / "latest.json").read_bytes())
    assert latest["funds"][0]["status"]["warnings"] == warnings
    meta = json.loads((tmp_path / "meta.json").read_bytes())
    assert meta["latest_close"] == {
        "expected_us_date": expected, "filled": {}, "unfilled": {}, "stale": {ticker: market_end} if warnings else {},
    }


def test_one_stale_index_preserves_other_fund_outputs(tmp_path, monkeypatch):
    config, registration, stale_id = _small_build((0, 1))
    stale_fund, fresh_fund = config["funds"]
    stale_ticker = stale_fund["proxy"]["index_ticker"]
    fresh_id = fresh_fund["id"]
    fresh_ticker = fresh_fund["proxy"]["index_ticker"]
    now = datetime(2026, 11, 25, 9, tzinfo=JST)
    monkeypatch.setattr(ml, "MIN_TRAIN", 20)
    out, logs = tmp_path / "out", tmp_path / "logs"

    class OneStaleIndex(DecisionSource):
        def close(self, ticker):
            values = super().close(ticker)
            return values.iloc[:-1] if ticker == stale_ticker else values

    def with_shared_notes(source):
        source.close_notes = {
            ticker: {
                "status": "filled", "date": "2026-11-24", "close": source.close(ticker).iloc[-1],
                "source": "regularMarketPrice", "price_time": "2026-11-24T16:00:01-05:00",
                "fetched_at": now.isoformat(timespec="seconds"),
            }
            for ticker in ("DX-Y.NYB", "^TNX", "^VIX", fresh_ticker)
        }
        return source

    build(out, with_shared_notes(DecisionSource(market_end="2026-11-24")), now,
          config=config, registration=registration)
    reference = _outputs(out)
    build(out, with_shared_notes(OneStaleIndex(market_end="2026-11-24")), now,
          config=config, registration=registration, ledger=logs)
    files = _outputs(out)

    stale, fresh = json.loads(files["latest.json"])["funds"]
    assert stale["id"] == stale_id
    assert stale["status"]["warnings"] == [
        "指数の直近の終値(2026-11-24)を取得できませんでした。2026-11-23 までの値で計算しています。",
    ]
    assert fresh == json.loads(reference["latest.json"])["funds"][1]
    for kind in ("series", "backtest", "ml"):
        name = f"{kind}/{fresh_id}.json"
        assert files[name] == reference[name]
    for entry in registration["strategies"]:
        stale_row = json.loads(ledger.path_for(logs, entry, stale_fund).read_bytes())
        assert (stale_row["status"], stale_row["reason"]) == ("missing", "no_estimate")
        assert stale_row["inputs"]["index"] == "2026-11-23"
        fresh_row = json.loads(ledger.path_for(logs, entry, fresh_fund).read_bytes())
        assert (fresh_row["status"], fresh_row["reason"]) == ("ok", None)
        assert fresh_row["inputs"]["filled"] == [fresh_ticker, "^VIX", "^TNX", "DX-Y.NYB"]


def test_build_records_close_notes_and_preserves_ledger_on_rerun(tmp_path, monkeypatch):
    config, registration, _ = _small_build((0, 2))
    unfilled_fund, filled_fund = config["funds"]
    ticker = filled_fund["proxy"]["index_ticker"]
    now = datetime(2026, 11, 25, 9, tzinfo=JST)
    monkeypatch.setattr(ml, "MIN_TRAIN", 20)
    out, logs = tmp_path / "out", tmp_path / "logs"
    common = {"date": "2026-11-24", "fetched_at": now.isoformat(timespec="seconds")}
    filled = dict(common, close=148.14286, source="regularMarketPrice", price_time="2026-11-24T16:00:01-05:00")
    unfilled = dict(common, reason="date_mismatch")

    class WithCloseNotes(DecisionSource):
        def __init__(self, corrected=False):
            super().__init__(market_end="2026-11-24")
            self.corrected = corrected
            self.close_notes = {"^IRX": dict(unfilled, status="unfilled")}
            if not corrected:
                self.close_notes[ticker] = dict(filled, status="filled")
            self.close_notes["OTHER"] = dict(filled, status="filled")

        def close(self, symbol):
            values = super().close(symbol)
            if symbol == ticker:
                values *= 148 / values.iloc[-1]
                values.iloc[-1] = 148.5 if self.corrected else filled["close"]
            elif symbol == "^IRX":
                values = values.iloc[:-1]
            return values

    build(out, WithCloseNotes(), now, config=config, registration=registration, ledger=logs)
    files = _outputs(out)
    meta = json.loads(files["meta.json"])
    assert meta["latest_close"] == {
        "expected_us_date": "2026-11-24", "filled": {ticker: dict(filled, close=148.1429)},
        "unfilled": {"^IRX": unfilled}, "stale": {},
    }
    before = {path.relative_to(logs): path.read_bytes() for path in logs.rglob("*.jsonl")}
    assert len(before) == meta["ledger"]["appended"] == 6
    for entry in registration["strategies"]:
        row = json.loads(before[ledger.path_for(logs, entry, filled_fund).relative_to(logs)])
        assert row["status"] == "ok"
        assert row["inputs"]["filled"] == [ticker]
        other_row = json.loads(before[ledger.path_for(logs, entry, unfilled_fund).relative_to(logs)])
        assert "filled" not in other_row["inputs"]

    build(out, WithCloseNotes(corrected=True), now, config=config, registration=registration, ledger=logs)
    after = _outputs(out)
    assert json.loads(after["latest.json"])["funds"][1]["proxy"]["index"]["value"] == 148.5
    meta = json.loads(after["meta.json"])
    assert meta["latest_close"]["filled"] == {}
    assert meta["ledger"]["appended"] == 0
    assert {path.relative_to(logs): path.read_bytes() for path in logs.rglob("*.jsonl")} == before
