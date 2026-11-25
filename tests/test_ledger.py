from datetime import date, datetime, timezone
import json

import numpy as np
import pandas as pd
import pytest

from nbt import ledger, ml, validation
from nbt.series import _domestic_range

FUND = {"id": "demo", "order_closed_calendars": ["NYSE"],
        "settlement": {"order_cutoff_jst": "15:00", "trade_lag_bd": 1}}


def test_jst_decision_time_includes_domestic_days_when_us_closed():
    assert ledger.is_decision_time(datetime(2026, 11, 26, 5, 59, tzinfo=timezone.utc), FUND)
    assert not ledger.is_decision_time(datetime(2026, 11, 26, 6, tzinfo=timezone.utc), FUND)
    assert not ledger.is_decision_time(datetime(2026, 11, 23, 9, tzinfo=ledger.JST), FUND)
    assert not ledger.is_decision_time(datetime(2026, 11, 28, 9, tzinfo=ledger.JST), FUND)


def test_append_preserves_bytes_and_reconciliation_uses_first_ok(tmp_path, monkeypatch):
    entry = validation.load_registration()["strategies"][2]
    path = ledger.path_for(tmp_path, entry, FUND)
    assert path.relative_to(tmp_path).as_posix() == "ml-macro/v1/demo.jsonl"
    monkeypatch.setenv("GITHUB_SHA", "synthetic-commit")

    def row(day, **kwargs):
        now = datetime(2026, 11, day, 9, tzinfo=ledger.JST)
        return ledger.make_row(now, "morning", entry, FUND, basis="estimate", **kwargs)

    missing = row(24, reason="features_incomplete")
    assert ledger.append(path, missing)
    before = path.read_bytes()
    assert before.endswith(b"\n") and b"\r" not in before
    assert not ledger.append(path, missing)
    assert path.read_bytes() == before
    assert ledger.append(path, row(24, reason="model_unavailable"))
    assert not ledger.append(path, missing)
    assert ledger.read(path)[date(2026, 11, 24)] == missing
    first = row(24, signal=0.3999999, features={"term_spread": -0.12345678, "missing": np.nan},
                inputs={"nav": "2026-11-20"}, train={"count": 800, "last": "2026-10-01"})
    assert first == {
        "date": "2026-11-24", "recorded_at": "2026-11-24T09:00:00+09:00", "run_kind": "morning", "strategy": "ml-macro",
        "version": 1, "fingerprint": entry["fingerprint"], "commit": "synthetic-commit", "fund": "demo", "status": "ok",
        "reason": None, "basis": "estimate", "orderable": True, "signal": 0.4, "condition": 0.4, "condition_met": True,
        "features": {"term_spread": -0.123457, "missing": None}, "inputs": {"nav": "2026-11-20"},
        "train": {"count": 800, "last": "2026-10-01"},
    }
    assert ledger.append(path, first)
    assert not ledger.append(path, row(24, signal=0.2))
    assert not ledger.append(path, row(24, reason="no_estimate"))
    later = row(26, signal=0.6)
    assert not later["orderable"]
    assert ledger.append(path, later)
    assert ledger.append(path, row(27, reason="no_estimate"))
    assert path.read_bytes().startswith(before)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row(24, signal=0.9)) + "\n")
    days = ledger.read(path)
    assert days[date(2026, 11, 24)] == first
    signal = pd.Series([0.45, 0.62], index=pd.to_datetime(["2026-11-24", "2026-11-26"]))
    assert ledger.reconcile(days, signal, entry) == {
        "first": "2026-11-24", "last": "2026-11-27", "ok_days": 2, "missing_days": {"no_estimate": 1},
        "unrecorded_days": 1, "compared_days": 2, "signal_abs_diff_mean": 0.035, "signal_abs_diff_max": 0.05,
        "condition_mismatch_days": 1,
    }


@pytest.mark.parametrize("offset", [0, 1, 20, 21])
def test_morning_ml_probability_matches_later_walk_forward(monkeypatch, offset):
    monkeypatch.setattr(ml, "MIN_TRAIN", 25)
    days = _domestic_range(pd.Timestamp("2024-01-04"), pd.Timestamp("2024-08-30"))
    rng = np.random.default_rng(286)
    price = pd.Series(rng.uniform(90, 110, len(days)), index=days)
    features = pd.DataFrame({"x": rng.normal(size=len(days))}, index=days)
    decision = features * 0.8
    lag = 2
    first = ml.MIN_TRAIN + lag + 20
    n = first + offset
    as_of = first + offset // ml.STEP * ml.STEP
    probability, count, last, reason = ml.decision_probability(price.iloc[:n], features.iloc[:n], decision.iloc[:n + 1], days[n], lag)
    later = ml.experiment(price, features, decision, lag=lag)[0]
    assert reason is None
    assert count == as_of - lag - 20
    assert last == days[count - 1].date().isoformat()
    assert probability == pytest.approx(later.iloc[n], abs=1e-14)
