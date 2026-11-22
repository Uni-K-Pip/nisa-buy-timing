const DAY = 86_400_000;

export function parseDay(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const stamp = Date.parse(value + "T00:00:00Z");
  return Number.isFinite(stamp) && dayString(stamp) === value ? stamp : null;
}

function dayString(stamp) {
  return new Date(stamp).toISOString().slice(0, 10);
}

export function jstToday(now = new Date()) {
  return dayString(now.getTime() + 9 * 60 * 60 * 1000);
}

export function calendarDays(calendar) {
  return Object.fromEntries(["JP", "NYSE"].map(market => [market, new Set(calendar?.[market] ?? [])]));
}

export function addDays(day, count) {
  return dayString(parseDay(day) + count * DAY);
}

export function isBusinessDay(day, calendar, market = "JP") {
  const stamp = parseDay(day);
  if (stamp === null) return false;
  const weekday = new Date(stamp).getUTCDay();
  return weekday !== 0 && weekday !== 6 && !calendar[market]?.has(day) &&
    (market !== "JP" || !["01-01", "01-02", "01-03", "12-31"].includes(day.slice(5)));
}

export function isOrderDay(day, calendar, closed = []) {
  return isBusinessDay(day, calendar) && closed.every(market => isBusinessDay(day, calendar, market));
}

export function nextOrderDay(day, calendar, closed = []) {
  while (!isOrderDay(day, calendar, closed)) day = addDays(day, 1);
  return day;
}

export function addBusinessDays(day, count, calendar) {
  const step = Math.sign(count);
  for (let remaining = Math.abs(count); remaining > 0; remaining--) {
    do {
      day = addDays(day, step);
    } while (!isBusinessDay(day, calendar));
  }
  return day;
}

export function businessDaysBetween(start, end, calendar) {
  if (start > end) return -businessDaysBetween(end, start, calendar);
  let count = 0;
  for (let day = start; day < end;) {
    day = addDays(day, 1);
    if (isBusinessDay(day, calendar)) count++;
  }
  return count;
}

export function settlementDate(orderDay, settleDays, calendar) {
  return addBusinessDays(orderDay, settleDays - 1, calendar);
}

export function lastOrderDay(year, settleDays, calendar, closed = []) {
  const lastBusinessDay = addBusinessDays(year + "-12-31", -1, calendar);
  let day = addBusinessDays(lastBusinessDay, 1 - settleDays, calendar);
  while (!isOrderDay(day, calendar, closed)) day = addDays(day, -1);
  return day.startsWith(String(year) + "-") ? day : null;
}

export function orderSchedule(settlement, calendar, now = new Date()) {
  const { order_cutoff_jst, order_closed_calendars, trade_lag_bd, settle_bd_from_order } = settlement;
  const today = jstToday(now);
  const jstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
  let day = jstTime >= order_cutoff_jst ? addDays(today, 1) : today;
  const orders = [];
  while (orders.length < 5) {
    day = nextOrderDay(day, calendar, order_closed_calendars);
    orders.push({
      order_date: day,
      trade_date: addBusinessDays(day, trade_lag_bd, calendar),
      settle_date: settlementDate(day, settle_bd_from_order, calendar),
    });
    day = addDays(day, 1);
  }
  return orders;
}
