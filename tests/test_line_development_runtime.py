from core.line_development_runtime import _bounded_comment_plan


def test_bounded_comment_plan_is_deterministic():
    plan = _bounded_comment_plan(
        'tests/test_line_development.py に「LINE自動開発E2E」というコメントを1行追加して、pytestを実行してください',
        'tests/test_line_development.py',
    )
    assert plan is not None
    assert plan["no_change"] is False
    assert plan["changes"][0]["file"] == "tests/test_line_development.py"
    assert plan["changes"][0]["new"].endswith("# LINE自動開発E2E\n")
