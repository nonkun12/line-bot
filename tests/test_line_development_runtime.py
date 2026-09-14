from core import line_development_runtime as runtime
from scripts import line_development_worker_v2 as worker


def test_explicit_comment_plan_is_deterministic(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text("_WORKFLOW_FILE = \".github/workflows/line-development.yml\"\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'line_development.py に「LINE自動開発E2E」というコメントを1行追加して、pytestを実行してください',
        'line_development.py',
    )
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["source"] == "deterministic_self_test"
    change = plan["changes"][0]
    assert change["file"] == "line_development.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    assert change["new"].endswith("# LINE自動開発E2E\n")
    assert worker.validate_plan(plan, "line_development.py") == (
        True,
        "line_development.py",
    )


def test_explicit_comment_plan_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "line_development.py"
    target.write_text("_WORKFLOW_FILE = \".github/workflows/line-development.yml\"\n# LINE自動開発E2E\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan = runtime._explicit_comment_plan(
        'line_development.py に「LINE自動開発E2E」というコメントを1行追加して',
        "line_development.py",
    )

    assert plan == {"no_change": True, "source": "deterministic_self_test"}


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


def test_fallback_safe_target_prefers_management_router_test():
    files = [
        "tests/test_line_development_runtime.py",
        "tests/test_management_router.py",
        "core/management_router.py",
    ]

    assert runtime._fallback_safe_target(files) == "tests/test_management_router.py"


def test_fallback_safe_target_returns_none_without_preferred_targets():
    assert runtime._fallback_safe_target(["core/example.py"]) is None
