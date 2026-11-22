from base64 import urlsafe_b64decode
from datetime import date
import json
from pathlib import Path
import subprocess

import pytest

from nbt.notify import crossed, main, notifications, signing_key
from scripts import privacy_check
from scripts.setup_push import encoded


@pytest.fixture
def sample():
    fund = {
        "id": "demo", "short_name": "試験用",
        "score": {"previous_value": 69, "value": 70, "category_name": "割安寄り"},
        "proxy": {"index": {"previous_value": 112, "value": 88}},
        "nav": {"previous_value": 101, "value": 99},
        "ml": {"valid": True, "previous_probability": 0.45, "probability": 0.4},
        "settlement": {"last_order_date": "2026-12-23"},
    }
    latest = {"funds": [fund], "run_kind": "morning"}
    rules = {
        "funds": ["demo"], "score_at_least": 70,
        "levels": [{"fund_id": "demo", "kind": "nav", "op": "<=", "value": 100}],
        "drops": [{"fund_id": "demo", "kind": "index", "reference_value": 100, "pct": 10}],
        "dates": [{"fund_id": "demo", "date": "2026-12-23", "label": "非公開テスト用ラベル", "days_before": [0, 1]}],
        "year_end": {"fund_ids": ["demo"], "days_before": [5, 1]},
        "ml": {"enabled": True, "prob_at_most": 0.4, "valid_only": True},
    }
    config = {"v": 1, "subscriptions": [{"endpoint": "https://push.example.com/test-endpoint"}], "rules": rules}
    return latest, config


def test_crossing_and_date_rules(sample):
    latest, config = sample
    count, messages = notifications(config["rules"], latest, date(2026, 12, 22))
    assert count == 6
    assert len(messages) == 6
    assert any("注文済みなら不要です" in message["body"] for message in messages)
    assert any("残り 1 国内営業日" in message["body"] for message in messages)
    assert all(message["url"] == "./" for message in messages)
    assert [message for message in notifications(config["rules"], latest, date(2026, 12, 23))[1]
            if message["title"].startswith("予定日")]
    assert not [message for message in notifications(config["rules"], latest, date(2026, 12, 24))[1]
                if message["title"].startswith("予定日")]
    assert not crossed(70, 80, 70, above=True)
    assert not crossed(90, 89, 90)
    assert not crossed(None, 70, 70, above=True)
    latest["funds"][0]["ml"]["valid"] = False
    assert len(notifications(config["rules"], latest, date(2026, 12, 22))[1]) == 5


def test_notify_only_logs_counts_and_exception_types(sample, tmp_path, monkeypatch, capsys):
    latest, config = sample
    (tmp_path / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    monkeypatch.setenv("PUSH_CONFIG", json.dumps(config))
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-test-secret")
    sent = []

    class Gone(Exception):
        response = type("Response", (), {"status_code": 410})()

    def sender(**request):
        sent.append(request)
        assert request["ttl"] == 43_200
        assert request["vapid_claims"]["sub"].startswith("https://")
        print(request["subscription_info"], request["data"])
        if len(sent) == 1:
            raise Gone(str(request))
        if len(sent) == 2:
            raise OSError(str(request))

    assert main(["--send", "--data", str(tmp_path)], sender=sender, today=date(2026, 12, 22)) == 1
    result = capsys.readouterr()
    assert result.out == "notify: rules=6 triggered=6 sent=4 failed=1 expired=1\n"
    assert result.err.splitlines() == ["Gone", "OSError"]
    for value in ("test-endpoint", "非公開テスト用ラベル", "synthetic-test-secret"):
        assert value not in result.out + result.err

    latest["run_kind"] = "evening"
    (tmp_path / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    assert main(["--send", "--data", str(tmp_path)], sender=sender) == 0
    assert len(sent) == 6


def test_dry_run_writes_only_to_file_and_refuses_actions(sample, tmp_path, monkeypatch, capsys):
    latest, config = sample
    (tmp_path / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    monkeypatch.setenv("PUSH_CONFIG", json.dumps(config))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    output = tmp_path / "push-config-test.json"
    args = ["--dry-run", str(output), "--data", str(tmp_path)]
    assert main(args, today=date(2026, 12, 22)) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 6
    assert "非公開テスト用ラベル" not in capsys.readouterr().out
    output.unlink()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert main(args) == 1
    assert not output.exists()
    result = capsys.readouterr()
    assert result.err == "PermissionError\n"


def test_vapid_signs_with_a_project_site_url():
    from py_vapid import Vapid

    generated = Vapid()
    generated.generate_keys()
    private = generated.private_key.private_numbers().private_value.to_bytes(32, "big")
    subject = "https://site.example.com/example-project/"
    signer = signing_key(encoded(private).decode("ascii"), subject)
    headers = signer.sign({"sub": subject, "aud": "https://push.example.com"})
    token = headers["Authorization"].split("t=", 1)[1].split(",", 1)[0]
    claims = token.split(".")[1]
    assert json.loads(urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))["sub"] == subject


def test_privacy_scanner_checks_tracked_and_untracked(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(privacy_check, "ROOT", tmp_path)
    (tmp_path / ".gitignore").write_text("ignored.json\n", encoding="utf-8")
    (tmp_path / "ignored.json").write_text(json.dumps({"budget": 42}), encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("holder" + "@" + "invalid.test", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "untracked.json").write_text(json.dumps({"plans": []}), encoding="utf-16")
    assert privacy_check.main() == 1
    captured = capsys.readouterr()
    assert "issues=2" in captured.out
    assert "holder" not in captured.out + captured.err
    assert "tracked.txt" not in captured.err


@pytest.mark.parametrize(("file", "data", "violation"), [
    ("README.md", "Contact test" + "@" + "example.com", False),
    ("README.md", "user" + "@" + "users.noreply.github.com", False),
    ("README.md", "C:" + chr(92) + "Users" + chr(92) + "sample", True),
    ("local.json", json.dumps({"full_" + "name": "非公開"}), True),
    ("example.txt", "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5, True),
    ("example.txt", "VAPID_" + "PRIVATE_KEY=" + "synthetic", True),
    ("site/index.html", '<script src="' + 'https:' + '//assets.example.com/app.js"></script>', True),
    ("site/index.html", "<script>console.log(1)</script>", True),
    ("site/styles.css", '@' + 'import "https:' + '//assets.example.com/style.css";', True),
    ("site/js/test.js", 'fetch("' + 'https:' + '//data.example.com/api")', True),
])
def test_privacy_patterns(file, data, violation):
    assert bool(privacy_check.violations_for(Path(file), data)) is violation
