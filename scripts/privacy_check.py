"""Scan Git-visible files without printing any matching content."""

import codecs
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MAIL = re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
PATH = re.compile(r"(?:\b[A-Z]:[\\/]|(?:file://)?/(?:Users|home)/)[^ \t'\"<>]+", re.IGNORECASE)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
SECRET = re.compile(r"""(?m)^\s*(?:export\s+)?(?:VAPID_PRIVATE_KEY|PUSH_CONFIG)\s*=\s*['"]?[A-Za-z0-9/+\-_{]""")
PERSON = re.compile(r"""(?im)^\s*['"]?(?:full_name|real_name|account_holder|本人氏名|氏名)['"]?\s*:\s*['"]?[^'"\s{]+""")
PRIVATE_FIELDS = {
    "subscriptions", "endpoint", "p256dh", "auth", "watch", "plans", "budget",
    "installments", "planned_date", "order_date", "nisa_used_this_year",
    "official_last_order_date", "score_at_least", "PUSH_CONFIG", "VAPID_PRIVATE_KEY",
    "full_name", "real_name", "account_holder", "本人氏名", "氏名",
}
SENSITIVE_NAMES = re.compile(r"^(?:\.env(?:\.|$)|push-config|vapid|.*\.(?:pem|key)$)", re.IGNORECASE)
REMOTE = re.compile(r"^(?:[a-z][a-z\d+.-]*:|//)", re.IGNORECASE)
CSP = {
    "default-src 'self'", "img-src 'self' data:", "style-src 'self'", "script-src 'self'",
    "connect-src 'self'", "manifest-src 'self'", "worker-src 'self'", "base-uri 'none'",
    "form-action 'none'", "object-src 'none'",
}


class SiteHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.violations = set()
        self.csp = []
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "meta":
            content = props.get("content") or ""
            if (props.get("http-equiv") or "").lower() == "content-security-policy":
                self.csp.append({" ".join(rule.split()) for rule in content.split(";") if rule.strip()})
            if (props.get("name") or "").lower() == "robots":
                modes = set(content.lower().replace(",", " ").split())
                self.noindex = {"noindex", "nofollow"} <= modes
        if tag == "style" or tag == "script" and not props.get("src"):
            self.violations.add("インラインのスクリプトまたはスタイル")
        for key, value in attrs:
            if key == "style" or key.startswith("on"):
                self.violations.add("インラインのスクリプトまたはスタイル")
            asset = key in ("src", "srcset", "poster", "data") or key == "href" and tag in ("link", "base")
            if value and asset and (REMOTE.match(value) or value.startswith("/")):
                self.violations.add("外部またはルート相対のサイト資産")


def private_json(value):
    if isinstance(value, dict):
        return bool(PRIVATE_FIELDS.intersection(value)) or any(
            private_json(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(private_json(item) for item in value)
    return False


def violations_for(path, content):
    violations = set()
    for match in MAIL.finditer(content):
        host = match.group().lower().split("@")[-1]
        if host != "users.noreply.github.com" and not re.fullmatch(r"(?:[\w-]+\.)*example\.(?:com|org|net)|example", host):
            violations.add("メールアドレス")
            break
    for pattern, label in (
        (PATH, "手元の絶対パス"), (PRIVATE_KEY, "秘密鍵"), (SECRET, "Secret の値"), (PERSON, "個人名の項目"),
    ):
        if pattern.search(content):
            violations.add(label)
    if path.suffix in (".json", ".webmanifest"):
        try:
            if private_json(json.loads(content)):
                violations.add("個人設定・計画・購読のデータ")
        except ValueError:
            pass
    if path.parts[0] == "site":
        if path.suffix == ".html":
            parser = SiteHTML()
            parser.feed(content)
            violations.update(parser.violations)
            if path == Path("site/index.html"):
                if parser.csp != [CSP]:
                    violations.add("サイトのCSPが仕様と異なります")
                if not parser.noindex:
                    violations.add("検索エンジン向けの noindex または nofollow がありません")
        if path == Path("site/robots.txt") and content.split() != ["User-agent:", "*", "Disallow:", "/"]:
            violations.add("robots.txt が全拒否ではありません")
        if path.suffix == ".css" and re.search(r"""@import\b|url\(\s*['"]?(?:https?:|//|/)""", content, re.I):
            violations.add("外部またはルート相対のスタイル資産")
        if path.suffix == ".js" and re.search(r"""(?:\bfetch|\bimportScripts|\bWebSocket|\bEventSource)\s*\(\s*['"](?:https?:|//|/)""", content, re.I):
            violations.add("外部またはルート相対のサイト通信")
    return violations


def git_paths():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    return sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})


def main():
    issues = 0
    for name in git_paths():
        path = Path(name)
        target = ROOT / path
        if not target.is_file():
            continue
        labels = set()
        if target.is_symlink() or not target.resolve().is_relative_to(ROOT):
            labels.add("リポジトリ外を参照する可能性のあるファイル")
        elif SENSITIVE_NAMES.search(path.name) or path.parts[:2] == ("site", "data"):
            labels.add("個人データまたは生成物のファイル名")
        else:
            content = target.read_bytes()
            if content.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                encodings = ("utf-32",)
            elif content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                encodings = ("utf-16",)
            else:
                encodings = () if b"\0" in content else ("utf-8-sig", "cp932")
            for encoding in encodings:
                try:
                    labels.update(violations_for(path, content.decode(encoding)))
                    break
                except UnicodeDecodeError:
                    continue
        if labels:
            issues += 1
            # Avoid showing filenames too: a name can itself contain personal data.
            print("privacy_check: " + "、".join(sorted(labels)), file=sys.stderr)
    print(f"privacy_check: issues={issues}")
    return int(issues > 0)


if __name__ == "__main__":
    sys.exit(main())
