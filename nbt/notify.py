import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
import logging
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .calendar import business_days_between, is_business_day

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9), "JST")


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def crossed(previous, current, threshold, *, above=False):
    if not all(number(value) for value in (previous, current, threshold)):
        return False
    return previous < threshold <= current if above else previous > threshold >= current


def price_quote(fund, kind):
    if kind == "index":
        return fund["proxy"].get("index") or {}
    if kind == "nav":
        return fund.get("nav") or {}
    return {}


def notifications(rules, latest, today):
    funds = {fund["id"]: fund for fund in latest["funds"]}
    messages = []
    count = 0

    def add(fund, heading, body):
        messages.append({"title": f"{heading}: {fund['short_name']}", "body": body, "url": "./"})

    for fund_id in dict.fromkeys(rules.get("funds", [])):
        fund = funds.get(fund_id)
        if fund is None:
            continue
        score = fund["score"]
        limit = rules.get("score_at_least")
        if number(limit):
            count += 1
            if crossed(score.get("previous_value"), score.get("value"), limit, above=True):
                reason = next((item for item in score.get("elements", []) if item["key"] == "dd252"), None)
                detail = f"{reason['description']}。" if reason else ""
                add(fund, "買い時シグナル",
                    f"スコア {score['value']:g}（{score['category_name']}）。{detail}判断と注文はご自身で。")
        ml = rules.get("ml", {})
        if ml.get("enabled"):
            count += 1
            experiment = fund.get("ml", {})
            if experiment.get("valid") and crossed(
                experiment.get("previous_probability"), experiment.get("probability"), ml.get("prob_at_most")
            ):
                add(fund, "実験モデルの参考情報",
                    f"20営業日待てば安く買えた確率 {experiment['probability']:.1%}。判断と注文はご自身で。")

    for kind in ("levels", "drops"):
        for rule in rules.get(kind, []):
            count += 1
            fund = funds.get(rule.get("fund_id"))
            if fund is None:
                continue
            quote = price_quote(fund, rule.get("kind"))
            if kind == "levels":
                limit = rule.get("value") if rule.get("op") == "<=" else None
            else:
                reference, pct = rule.get("reference_value"), rule.get("pct")
                limit = reference * (1 - pct / 100) if number(reference) and number(pct) else None
            if crossed(quote.get("previous_value"), quote.get("value"), limit):
                name = "指数" if rule["kind"] == "index" else "基準価額"
                add(fund, "価格の条件", f"{name}が設定した条件に達しました。判断と注文はご自身で。")

    for rule in rules.get("dates", []):
        count += 1
        fund = funds.get(rule.get("fund_id"))
        if fund is None:
            continue
        planned = date.fromisoformat(rule["date"])
        if (planned - today).days in rule.get("days_before", []):
            add(fund, "予定日の確認", f"{rule['label']}の購入予定日 {planned}。注文済みなら不要です。")

    year_end = rules.get("year_end", {})
    for fund_id in dict.fromkeys(year_end.get("fund_ids", [])):
        count += 1
        fund = funds.get(fund_id)
        last = (fund or {}).get("settlement", {}).get("last_order_date")
        if last and is_business_day(today):
            remaining = business_days_between(today, date.fromisoformat(last))
            if remaining in year_end.get("days_before", []):
                add(fund, "年内受渡の確認",
                    f"最終注文日（推定）まで残り {remaining} 国内営業日です。公式画面で確認してください。")
    return count, messages


def signing_key(private_key, subject):
    from py_vapid import Vapid

    url = urlsplit(subject)
    if url.scheme != "https" or not url.hostname or url.username is not None or url.fragment:
        raise ValueError
    # py-vapid's strict subject check excludes HTTPS URLs that have a path.
    return Vapid(Vapid.from_string(private_key).private_key, conf={"no-strict": True})


def main(argv=None, *, sender=None, today=None):
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--send", action="store_true")
    actions.add_argument("--dry-run", type=Path)
    parser.add_argument("--data", type=Path, default=ROOT / "site/data")
    args = parser.parse_args(argv)
    counts = dict.fromkeys(("rules", "triggered", "sent", "failed", "expired"), 0)
    result = 0
    try:
        if args.dry_run and os.getenv("GITHUB_ACTIONS", "").lower() == "true":
            raise PermissionError
        raw_config = os.getenv("PUSH_CONFIG")
        private_key = os.getenv("VAPID_PRIVATE_KEY")
        if not raw_config or (args.send and not private_key):
            return 0
        config = json.loads(raw_config)
        if config.get("v") != 1:
            raise ValueError
        subscriptions = config["subscriptions"]
        latest = json.loads((args.data / "latest.json").read_text(encoding="utf-8"))
        if args.send and latest.get("run_kind") != "morning":
            return 0
        counts["rules"], messages = notifications(config["rules"], latest, today or datetime.now(JST).date())
        counts["triggered"] = len(messages)
        if args.dry_run:
            with args.dry_run.open("x", encoding="utf-8") as output:
                json.dump(messages, output, ensure_ascii=False, indent=2)
                output.write("\n")
        elif messages:
            app_config = json.loads((ROOT / "site/app-config.json").read_text(encoding="utf-8"))
            subject = os.getenv("VAPID_SUBJECT") or app_config["site_url"]
            if sender is None:
                from pywebpush import webpush

                private_key = signing_key(private_key, subject)
                sender = webpush
            for subscription in subscriptions:
                for message in messages:
                    try:
                        # Third-party diagnostics can contain endpoints and credentials.
                        previous_log_level = logging.root.manager.disable
                        try:
                            logging.disable(sys.maxsize)
                            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                                sender(subscription_info=subscription, data=json.dumps(message, ensure_ascii=False),
                                       vapid_private_key=private_key, vapid_claims={"sub": subject},
                                       ttl=12 * 60 * 60, timeout=30)
                        finally:
                            logging.disable(previous_log_level)
                        counts["sent"] += 1
                    except Exception as error:
                        if getattr(getattr(error, "response", None), "status_code", None) in (404, 410):
                            counts["expired"] += 1
                        else:
                            counts["failed"] += 1
                        print(type(error).__name__, file=sys.stderr)
            result = int(counts["failed"] > 0)
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        result = 1
    finally:
        print("notify: " + " ".join(f"{key}={value}" for key, value in counts.items()))
    return result


if __name__ == "__main__":
    sys.exit(main())
