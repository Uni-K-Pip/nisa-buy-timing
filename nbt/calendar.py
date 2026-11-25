from datetime import date, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

import holidays

DAY = timedelta(days=1)


@cache
def holidays_for(year):
    jp = set(holidays.country_holidays("JP", years=year))
    jp.update(date(year, 1, day) for day in range(1, 4))
    jp.add(date(year, 12, 31))
    nyse = set(holidays.financial_holidays("NYSE", years=year))
    return {"JP": frozenset(jp), "NYSE": frozenset(nyse)}


def is_business_day(day, market="JP"):
    return day.weekday() < 5 and day not in holidays_for(day.year)[market]


def is_order_day(day, closed_calendars=()):
    return is_business_day(day) and all(
        is_business_day(day, market) for market in closed_calendars
    )


def add_business_days(day, count, market="JP"):
    step = DAY if count > 0 else -DAY
    for _ in range(abs(count)):
        day += step
        while not is_business_day(day, market):
            day += step
    return day


def latest_us_session(now):
    """通常取引が終わっている最後の NYSE の営業日(3.3)。"""
    local = now.astimezone(ZoneInfo("America/New_York"))
    day = local.date()
    if is_business_day(day, "NYSE") and local.time() >= time(16):
        return day
    return add_business_days(day, -1, "NYSE")


def business_days_between(start, end):
    """Count domestic business days in (start, end]."""
    if start > end:
        return -business_days_between(end, start)
    return sum(is_business_day(start + DAY * offset) for offset in range(1, (end - start).days + 1))


def export_calendar(year):
    return {
        "years": [year, year + 1],
        **{
            market: sorted(day.isoformat() for y in (year, year + 1) for day in holidays_for(y)[market])
            for market in ("JP", "NYSE")
        },
    }
