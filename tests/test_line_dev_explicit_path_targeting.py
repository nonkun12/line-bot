from pathlib import Path

from scripts import line_development_worker_v2 as worker


INSTRUCTION = 'line_development.py に「LINE自動開発テスト」という1行コメントを追加してください。pytestを実行し、成功したらPRを作成してください。'


def test_explicit_protected_target_wins_over_e2e_fallback(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text('_WORKFLOW_FILE = "line-development-dispatch.yml"\n', encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    chosen = worker.choose_file(None, INSTRUCTION, ["tests/test_line_development.py"])

    assert chosen == "line_development.py"


def test_deterministic_comment_plan_is_allowed_for_protected_target(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text('_WORKFLOW_FILE = "line-development-dispatch.yml"\n', encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setenv("ALLOW_SELF_TEST_COMMENT", "1")

    plan = worker.build_comment_test_plan(INSTRUCTION, "line_development.py")

    assert plan is not None
    assert plan["changes"][0]["file"] == "line_development.py"
    assert worker.validate_plan(plan, "line_development.py") == (True, "line_development.py")


def test_general_protected_plan_is_still_rejected():
    plan = {
        "no_change": False,
        "changes": [{
            "file": "line_development.py",
            "old": "print('old')\n",
            "new": "print('new')\n",
        }],
    }

    ok, detail = worker.validate_plan(plan, "line_development.py")

    assert not ok
    assert detail == "protected_file:line_development.py"


def test_explicit_comment_target_alias_is_normalized(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text('_WORKFLOW_FILE = "line-development-dispatch.yml"\n', encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    chosen = worker._extract_explicit_path(
        "./line_development.py にコメントを追加",
        ["tests/test_line_development.py"],
    )

    assert chosen == "line_development.py"
