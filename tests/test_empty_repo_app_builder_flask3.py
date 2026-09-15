from pathlib import Path

from scripts.empty_repo_app_builder import repair_known_flask3_issues


def test_repair_known_flask3_issue_removes_before_first_request_and_runs_once(tmp_path: Path):
    target = tmp_path / "app.py"
    target.write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "calls = []\n"
        "def init_db():\n"
        "    calls.append('init')\n"
        "@app.before_first_request\n"
        "def initialize():\n"
        "    init_db()\n",
        encoding="utf-8",
    )

    changed = repair_known_flask3_issues(
        tmp_path,
        {"app.py"},
        "AttributeError: 'Flask' object has no attribute 'before_first_request'",
    )

    assert changed is True
    content = target.read_text(encoding="utf-8")
    assert "before_first_request" not in content
    assert "with app.app_context():" in content
    assert "initialize()" in content


def test_repair_known_flask3_issue_is_noop_for_unrelated_failures(tmp_path: Path):
    target = tmp_path / "app.py"
    original = "from flask import Flask\napp = Flask(__name__)\n"
    target.write_text(original, encoding="utf-8")

    changed = repair_known_flask3_issues(tmp_path, {"app.py"}, "AssertionError: expected 1, got 2")

    assert changed is False
    assert target.read_text(encoding="utf-8") == original
