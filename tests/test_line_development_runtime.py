from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


def test_explicit_comment_plan_is_deterministic():
    plan = runtime._explicit_comment_plan(
        'tests/test_line_development.py に「LINE自動開発E2E」というコメントを1行追加して、pytestを実行してください',
        'tests/test_line_development.py',
    )
    assert plan is not None
    assert plan["no_change"] is False
    change = plan["changes"][0]
    assert change["file"] == "tests/test_line_development.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    assert change["new"].endswith("# LINE自動開発E2E\n")
    assert worker.validate_plan(plan, "tests/test_line_development.py") == (
        True,
        "tests/test_line_development.py",
    )


def test_explicit_comment_plan_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "tests" / "test_line_development.py"
    target.parent.mkdir(parents=True)
    target.write_text("from example import value\n# LINE自動開発E2E\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'tests/test_line_development.py に「LINE自動開発E2E」というコメントを1行追加して',
        "tests/test_line_development.py",
    )

    assert plan == {"no_change": True}


def test_validate_plan_rejects_oversized_change():
    plan = {
        "no_change": False,
        "changes": [
            {
                "file": "tests/test_line_development.py",
                "old": "x" * 1201,
                "new": "y",
            }
        ],
    }

    assert worker.validate_plan(plan, "tests/test_line_development.py") == (
        False,
        "change_too_large",
    )
