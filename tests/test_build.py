from datetime import datetime
import json

import numpy as np
import pandas as pd
import pytest
import requests

from nbt.build import JST, build, clean


class FakeSource:
    def __init__(self, fail_nav=False, fail_index=False):
        self.fail_nav = fail_nav
        self.fail_index = fail_index

    def nav(self, fund):
        if self.fail_nav:
            raise OSError
        dates = pd.bdate_range("2025-08-01", "2026-11-20")
        return pd.DataFrame({"nav": np.arange(1000.0, 1000.0 + len(dates)), "distribution": 0.0}, index=dates)

    def close(self, ticker):
        if self.fail_index and ticker == "^NYFANG":
            raise OSError
        dates = pd.bdate_range("2025-07-31", "2026-11-20")
        return pd.Series(np.arange(100.0, 100.0 + len(dates)), index=dates)


def test_fake_build_file_contract(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("network access")

    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "synthetic-public-key")
    build(tmp_path, FakeSource(), datetime(2026, 11, 22, 9, tzinfo=JST), run_kind="morning")

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
    assert {"generated_at", "funds", "market_dates"} <= read("meta.json").keys()
    expected = {"latest.json", "meta.json", "push.json", "calendar.json"}
    for fund in latest["funds"]:
        assert {
            "id", "name", "short_name", "series_kind", "nav", "nowcast", "proxy", "score",
            "ml", "settlement", "status",
        } == fund.keys()
        assert {"date", "value", "change_pct"} <= fund["nav"].keys()
        assert {"us_date", "value", "change_pct", "error_pct"} == fund["nowcast"].keys()
        assert {"index_ticker", "index_label", "index", "fx"} == fund["proxy"].keys()
        assert {"value", "category", "category_name", "elements", "date"} <= fund["score"].keys()
        assert {"probability", "date", "valid", "metrics", "note"} <= fund["ml"].keys()
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
        assert None in series["ml_prob"]
        assert {"description", "grid"} <= backtest.keys()
        assert len(backtest["grid"]) == 60
        assert {"auc", "brier", "baseline_brier", "brier_skill", "count", "valid", "calibration"} == ml.keys()
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.json")} == expected


@pytest.mark.parametrize(("missing", "expected"), [("nav", "proxy"), ("index", "nav")])
def test_build_degrades_and_records_warnings(tmp_path, missing, expected):
    build(tmp_path, FakeSource(fail_nav=missing == "nav", fail_index=missing == "index"),
          datetime(2026, 11, 22, 9, tzinfo=JST))
    first = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["funds"][0]
    assert first["series_kind"] == expected
    assert not first["status"][missing]
    assert first["status"]["warnings"]


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
