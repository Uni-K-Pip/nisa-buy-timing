import numpy as np
import pandas as pd

from .series import domestic_dates


def _wilder_average(moves, period):
    seeded = moves.iloc[period:].copy()
    if not seeded.empty:
        seeded.iloc[0] = moves.iloc[1:period + 1].mean()
    return seeded.ewm(alpha=1 / period, adjust=False).mean().reindex(moves.index)


def _rsi(gain, loss):
    value = 100 * gain / (gain + loss)
    return value.mask(gain.eq(0) & loss.eq(0), 50)


def wilder_rsi(price, period=14):
    delta = price.diff()
    return _rsi(_wilder_average(delta.clip(lower=0), period),
                _wilder_average(-delta.clip(upper=0), period))


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
        result["fx_dev"] = deviation.reindex(price.index)
    if vix is not None and not vix.empty:
        result["vix"] = domestic_dates(vix).reindex(price.index, method="ffill")
        result["vix_chg20"] = domestic_dates(vix.pct_change(20)).reindex(price.index, method="ffill")
    return result.replace([np.inf, -np.inf], np.nan)


def _decision_wilder_average(moves, estimated_move, period):
    previous = _wilder_average(moves, period).shift()
    alpha = 1 / period
    average = (1 - alpha) * previous + alpha * estimated_move
    if len(moves) > period:
        seed = pd.concat([moves.iloc[1:period], estimated_move.iloc[period:period + 1]])
        average.iloc[period] = seed.mean()
    return average


def _decision_volatility(daily_return, estimated_return, period):
    count = period - 1
    prior = daily_return.shift().rolling(count)
    # 直前の標本に推定した対数収益率を 1 件加える。
    squared = prior.var() * (count - 1) + (estimated_return - prior.mean()).pow(2) * (count / period)
    return (squared / count).pow(0.5) * np.sqrt(252)


def decision_indicators(price, estimated, fx=None, vix=None):
    result = indicators(price, fx, vix)
    decision = pd.DataFrame(index=price.index)
    highest = np.maximum(price.shift().rolling(251).max(), estimated)
    decision["dd252"] = estimated / highest - 1
    for period in (200, 25):
        average = (price.shift().rolling(period - 1).sum() + estimated) / period
        decision[f"ma{period}_dev"] = estimated / average - 1
    delta, estimated_delta = price.diff(), estimated - price.shift()
    decision["rsi14"] = _rsi(
        _decision_wilder_average(delta.clip(lower=0), estimated_delta.clip(lower=0), 14),
        _decision_wilder_average(-delta.clip(upper=0), -estimated_delta.clip(upper=0), 14),
    )
    for period in (5, 20, 60):
        decision[f"ret{period}"] = estimated / price.shift(period) - 1
    log_price = np.log(price)
    daily_return, estimated_return = log_price.diff(), np.log(estimated) - log_price.shift()
    decision["vol20"] = _decision_volatility(daily_return, estimated_return, 20)
    decision["vol_ratio"] = decision["vol20"] / _decision_volatility(daily_return, estimated_return, 252)
    decision = decision.replace([np.inf, -np.inf], np.nan)
    # 同じ価格の行は、丸め誤差で百分位の同順位が崩れないよう確定値を使う。
    changed = estimated.ne(price) & (estimated.notna() | price.notna())
    result[decision.columns] = decision.where(changed, result[decision.columns], axis=0)
    return result
