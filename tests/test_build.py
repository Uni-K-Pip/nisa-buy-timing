from datetime import datetime
import json

import numpy as np
import pandas as pd
import pytest
import requests

from nbt.build import JST, build, clean
from nbt.indicators import indicators
from nbt.score import score_series, score_summary
from nbt.series import price_series


class FakeSource:
    def __init__(self, fail_nav=False, fail_index=False, estimate=True, fail_fx=False):
        self.fail_nav = fail_nav
        self.fail_index = fail_index
        self.fail_fx = fail_fx
        end = "2026-11-20" if estimate else "2026-11-19"
        self.dates = pd.bdate_range("2025-04-01", end)

    def nav(self, fund):
        if self.fail_nav:
            raise OSError
        dates = pd.bdate_range("2025-08-01", "2026-11-20")
        return pd.DataFrame({"nav": np.arange(1000.0, 1000.0 + len(dates)), "distribution": 0.0}, index=dates)

    def close(self, ticker):
        if self.fail_index and ticker == "^NYFANG":
            raise OSError
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
        assert fund["ml"]["basis"] == "confirmed"
        assert fund["ml"]["date"] == fund["nav"]["date"] == "2026-11-20"
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
        assert {"description", "grid"} <= backtest.keys()
        assert len(backtest["grid"]) == 60
        assert {"auc", "brier", "baseline_brier", "brier_skill", "count", "valid", "calibration"} == ml.keys()

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
