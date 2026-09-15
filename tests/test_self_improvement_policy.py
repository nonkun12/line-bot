from core.self_improvement_policy import SelfImprovementDecision, assess_self_improvement


def test_normal_self_improvement_requires_review_pipeline():
    result = assess_self_improvement(["core/project_registry.py", "tests/test_project_registry.py"])
    assert result.decision == SelfImprovementDecision.AUTONOMOUS_REVIEW
    assert result.protected_paths == ()


def test_security_and_control_plane_changes_require_explicit_approval():
    result = assess_self_improvement(["core/line_development_runtime.py", ".github/workflows/line-development-dispatch.yml"])
    assert result.decision == SelfImprovementDecision.EXPLICIT_APPROVAL
    assert set(result.protected_paths) == {
        "core/line_development_runtime.py",
        ".github/workflows/line-development-dispatch.yml",
    }


def test_empty_self_improvement_scope_is_rejected():
    result = assess_self_improvement([])
    assert result.decision == SelfImprovementDecision.REJECT
