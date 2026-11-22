from datetime import date, time

from .calendar import DAY, add_business_days, business_days_between, is_business_day, is_order_day


def settlement_date(order_day, settle_bd_from_order):
    return add_business_days(order_day, settle_bd_from_order - 1)


def last_order_day(year, settle_bd_from_order, closed_calendars=()):
    last = date(year, 12, 31)
    while not is_business_day(last):
        last -= DAY
    day = add_business_days(last, 1 - settle_bd_from_order)
    while not is_order_day(day, closed_calendars):
        day -= DAY
    return day if day.year == year else None


def settlement_summary(fund, now):
    params = fund["settlement"]
    closed = fund.get("order_closed_calendars", [])
    today = now.date()
    last = last_order_day(today.year, params["settle_bd_from_order"], closed)
    day = today
    if now.time() >= time.fromisoformat(params["order_cutoff_jst"]):
        day += DAY
    upcoming = []
    while len(upcoming) < 5:
        if is_order_day(day, closed):
            upcoming.append({
                "order_date": day.isoformat(),
                "trade_date": add_business_days(day, params["trade_lag_bd"]).isoformat(),
                "settle_date": settlement_date(day, params["settle_bd_from_order"]).isoformat(),
            })
        day += DAY
    return {
        **params,
        "order_closed_calendars": closed,
        "last_order_date": last.isoformat() if last else None,
        "last_settle_date": settlement_date(last, params["settle_bd_from_order"]).isoformat() if last else None,
        "remaining_business_days": business_days_between(today, last) if last else None,
        "upcoming_orders": upcoming,
    }
