from datetime import date, timedelta
from functools import cache

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
