import argparse
from base64 import urlsafe_b64encode
import json
import subprocess
import sys

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

DEFAULT_REPO = "Uni-K-Pip/nisa-buy-timing"


def gh(repo, *args, stdin=None):
    return subprocess.run(
        ["gh", *args, "--repo", repo], input=stdin, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def encoded(data):
    return urlsafe_b64encode(data).rstrip(b"=")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--force", action="store_true", help="既存の購読が無効になる鍵の再発行を許可")
    args = parser.parse_args()
    try:
        secrets = json.loads(gh(args.repo, "secret", "list", "--json", "name"))
        variables = json.loads(gh(args.repo, "variable", "list", "--json", "name"))
        exists = any(item["name"] in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY") for item in secrets + variables)
        if exists and not args.force:
            print("既存のVAPID鍵があります。購読を再登録できる場合に限り --force を使ってください。", file=sys.stderr)
            return 1
        vapid = Vapid()
        vapid.generate_keys()
        private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        gh(args.repo, "secret", "set", "VAPID_PRIVATE_KEY", stdin=encoded(private))
        gh(args.repo, "variable", "set", "VAPID_PUBLIC_KEY", stdin=encoded(public))
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("鍵の登録を完了できませんでした。gh の認証と対象リポジトリの登録状況を確認してください。", file=sys.stderr)
        return 1
    print("VAPID鍵を登録しました。Pagesのデータを再生成してからアプリで購読してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
