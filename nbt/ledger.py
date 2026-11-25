from datetime import date, time, timedelta, timezone
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import is_business_day, is_order_day
from .series import _domestic_range

JST = timezone(timedelta(hours=9), "JST")


def is_decision_time(now, fund):
    local = now.astimezone(JST)
    cutoff = time.fromisoformat(fund["settlement"]["order_cutoff_jst"])
    return is_business_day(local.date()) and local.time() < cutoff


def path_for(folder, entry, fund):
    return Path(folder) / entry["id"] / f"v{entry['version']}" / f"{fund['id']}.jsonl"


def _rounded(value):
    return round(float(value), 6) if value is not None and np.isfinite(value) else None


def _condition_met(kind, signal, condition):
    return bool(signal >= condition if kind == "score" else signal <= condition)


def make_row(now, run_kind, entry, fund, *, basis, signal=None, reason=None, features=None, inputs=None, train=None):
    local = now.astimezone(JST)
    kind = entry["kind"]
    condition = entry["primary"]["threshold" if kind == "score" else "probability_at_most"]
    row = {
        "date": local.date().isoformat(), "recorded_at": local.isoformat(timespec="seconds"), "run_kind": run_kind,
        "strategy": entry["id"], "version": entry["version"], "fingerprint": entry["fingerprint"],
        "commit": os.getenv("GITHUB_SHA") or None, "fund": fund["id"], "status": "missing" if reason else "ok",
        "reason": reason, "basis": basis,
        "orderable": is_order_day(local.date(), fund.get("order_closed_calendars", ())),
        "signal": _rounded(signal), "condition": _rounded(condition),
        "condition_met": None if reason else _condition_met(kind, signal, condition),
        "features": {key: _rounded(value) for key, value in features.items()} if features is not None else None,
        "inputs": inputs,
    }
    if kind == "ml":
        row["train"] = train
    return row


def _rows(stream):
    for line in stream:
        row = json.loads(line)
        if row["status"] not in ("ok", "missing"):
            raise ValueError("台帳の status が不明です")
        yield date.fromisoformat(row["date"]), row, line.endswith("\n")


def read(path):
    days = {}
    try:
        with path.open(encoding="utf-8") as stream:
            for day, row, _ in _rows(stream):
                first = days.get(day)
                if first is None or first["status"] == "missing" and row["status"] == "ok":
                    days[day] = row
    except FileNotFoundError:
        pass
    return days


def append(path, row):
    # 既存の行は読むだけで、足す行は必ず末尾に付く("a" は書き込みを末尾に固定する)。
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8", newline="\n") as stream:
        stream.seek(0)
        day = date.fromisoformat(row["date"])
        terminated = True
        for recorded, previous, terminated in _rows(stream):
            if recorded == day and (previous["status"] == "ok" or previous["reason"] == row["reason"]):
                return False
        if not terminated:
            stream.write("\n")
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        stream.flush()
        return True


def reconcile(days, signal, entry):
    first, last = (min(days), max(days)) if days else (None, None)
    recorded = pd.DatetimeIndex([day for day, row in days.items() if row["status"] == "ok"])
    gaps = len(_domestic_range(pd.Timestamp(first), pd.Timestamp(last)).difference(pd.DatetimeIndex(list(days)))) if days else 0
    missing = {}
    for row in days.values():
        if row["status"] == "missing":
            reason = row["reason"]
            missing[reason] = missing.get(reason, 0) + 1
    differences = []
    mismatches = 0
    recalculated = signal.reindex(recorded)
    for day, value in recalculated[np.isfinite(recalculated)].items():
        row = days[day.date()]
        differences.append(abs(row["signal"] - value))
        mismatches += row["condition_met"] != _condition_met(entry["kind"], value, row["condition"])
    return {
        "first": first.isoformat() if first else None, "last": last.isoformat() if last else None,
        "ok_days": len(recorded), "missing_days": missing, "unrecorded_days": gaps, "compared_days": len(differences),
        "signal_abs_diff_mean": _rounded(np.mean(differences)) if differences else None,
        "signal_abs_diff_max": _rounded(max(differences)) if differences else None,
        "condition_mismatch_days": mismatches,
    }
