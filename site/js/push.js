export function notificationConfig(subscription, watch, plans, settings) {
  const funds = [...new Set(watch)].sort();
  const levels = [];
  const drops = [];
  const dates = [];
  for (const plan of plans) {
    const fundId = plan.fund_id;
    if (settings.plan_prices) {
      for (const rule of plan.levels) {
        levels.push({ fund_id: fundId, kind: rule.kind, op: "<=", value: rule.value });
      }
      if (plan.drop_rule) {
        const { kind, reference_value, pct } = plan.drop_rule;
        drops.push({ fund_id: fundId, kind, reference_value, pct });
      }
    }
    if (settings.plan_dates) {
      plan.installments.forEach((row, i) => {
        if (row.status === "planned" && row.planned_date) {
          dates.push({ fund_id: fundId, date: row.planned_date, label: (i + 1) + "回目", days_before: [1, 0] });
        }
      });
    }
  }
  return {
    v: 1,
    subscriptions: subscription ? [subscription] : [],
    rules: {
      funds,
      score_at_least: settings.score_at_least,
      levels, drops, dates,
      year_end: { fund_ids: settings.year_end ? funds : [], days_before: [5, 1] },
      ml: { enabled: settings.ml_enabled, prob_at_most: settings.ml_probability, valid_only: true },
    },
  };
}

export function copyPayload(subscription, state) {
  return JSON.stringify(notificationConfig(subscription?.toJSON(), state.watch, state.plans, state.notifications), null, 2);
}

export async function payloadHash(payload) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
  return Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, "0")).join("");
}

export function publicKeyBytes(key) {
  const base64 = key.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")), char => char.charCodeAt(0));
}
