import numpy as np
import pandas as pd

from .series import domestic_dates


def wilder_rsi(price, period=14):
    delta = price.diff().iloc[1:]
    if len(delta) < period:
        return pd.Series(np.nan, index=price.index)

    def smooth(moves):
        seeded = moves.iloc[period - 1:].copy()
        seeded.iloc[0] = moves.iloc[:period].mean()
        return seeded.ewm(alpha=1 / period, adjust=False).mean()

    gain = smooth(delta.clip(lower=0))
    loss = smooth(-delta.clip(upper=0))
    value = 100 * gain / (gain + loss)
    return value.mask(gain.eq(0) & loss.eq(0), 50).reindex(price.index)


def indicators(price, fx=None, vix=None):
    result = pd.DataFrame(index=price.index)
    result["dd252"] = price / price.rolling(252).max() - 1
    for period in (200, 25):
        result[f"ma{period}_dev"] = price / price.rolling(period).mean() - 1
    result["rsi14"] = wilder_rsi(price)
    for period in (5, 20, 60):
        result[f"ret{period}"] = price.pct_change(period)
    daily_return = np.log(price).diff()
    result["vol20"] = daily_return.rolling(20).std() * np.sqrt(252)
    result["vol_ratio"] = result["vol20"] / (daily_return.rolling(252).std() * np.sqrt(252))
    if fx is not None and not fx.empty:
        deviation = fx / fx.rolling(200).mean() - 1
        result["fx_dev"] = domestic_dates(deviation).reindex(price.index, method="ffill")
    if vix is not None and not vix.empty:
        result["vix"] = domestic_dates(vix).reindex(price.index, method="ffill")
        result["vix_chg20"] = domestic_dates(vix.pct_change(20)).reindex(price.index, method="ffill")
    return result.replace([np.inf, -np.inf], np.nan)
