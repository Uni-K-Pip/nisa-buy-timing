import pandas as pd

from .series import _domestic_range, domestic_dates


def bond_yield(discount):
    d = discount / 100
    return 100 * 365 * d / (360 - 91 * d)


SERIES = {
    "us10y": {"ticker": "^TNX", "delay_days": 0, "allow_nonpositive": True},
    "us3m": {"ticker": "^IRX", "delay_days": 0, "allow_nonpositive": True, "convert": bond_yield},
    "dxy": {"ticker": "DX-Y.NYB", "delay_days": 1},
}
UNAVAILABLE = "macro_unavailable"
RATES_DOLLAR_NAMES = ("us10y_chg20", "term_spread", "term_spread_chg20", "dxy_dev", "dxy_ret20")


def domestic_close(values, delay_days):
    values = values.dropna().sort_index(kind="stable")
    dates = pd.DatetimeIndex(values.index).tz_localize(None).normalize()
    values.index = dates + pd.Timedelta(days=delay_days)
    values = values.loc[~values.index.duplicated(keep="last")]
    return domestic_dates(values)


def rates_dollar(values):
    us10y, us3m, dxy = (values[name] for name in ("us10y", "us3m", "dxy"))
    spread = us10y - us3m
    columns = (us10y.diff(20), spread, spread.diff(20), dxy / dxy.rolling(200).mean() - 1, dxy / dxy.shift(20) - 1)
    return pd.DataFrame(dict(zip(RATES_DOLLAR_NAMES, columns)))


FEATURE_SETS = {"rates_dollar": (("us10y", "us3m", "dxy"), rates_dollar, RATES_DOLLAR_NAMES)}


def feature_names(groups):
    return [name for group in groups for name in FEATURE_SETS[group][2]]


def features(series, days, groups):
    names = dict.fromkeys(name for group in groups for name in FEATURE_SETS[group][0])
    if any(series[name].dropna().empty for name in names):
        return None
    if not names:
        return pd.DataFrame(index=days)
    mapped = {}
    for name in names:
        definition = SERIES[name]
        values = series[name]
        if "convert" in definition:
            values = definition["convert"](values)
        mapped[name] = domestic_close(values, definition["delay_days"])
    start = min(values.index[0] for values in mapped.values())
    calendar = _domestic_range(start, days.max()) if len(days) else days
    aligned = {name: values.reindex(calendar).ffill(limit=5) for name, values in mapped.items()}
    frames = [FEATURE_SETS[group][1](aligned) for group in groups]
    return pd.concat(frames, axis=1).reindex(days)


def metadata(series, *, include_first=False):
    result = {}
    for name, definition in SERIES.items():
        values = series[name]
        info = {key: definition[key] for key in ("ticker", "delay_days")}
        if include_first:
            info["first"] = values.index[0].date().isoformat() if len(values) else None
        info["last"] = values.index[-1].date().isoformat() if len(values) else None
        result[name] = info
    return result
