from scripts import line_development_worker_v2 as worker
from core.self_improvement_policy import SelfImprovementDecision


def test_worker_uses_shared_policy_for_normal_targets():
    assert worker._is_shared_policy_autonomous("tests/test_line_development.py") is True
    assert worker._is_shared_policy_autonomous("core/self_improvement_policy.py") is False
    assert worker._is_shared_policy_autonomous(".github/workflows/pytest.yml") is False


def test_worker_repo_files_excludes_shared_policy_protected_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    class Result:
        returncode = 0
        stdout = "tests/test_line_development.py\ncore/self_improvement_policy.py\n.github/workflows/pytest.yml\n"
        stderr = ""

    monkeypatch.setattr(worker, "run", lambda *args, **kwargs: Result())

    assert worker.repo_files() == ["tests/test_line_development.py"]


def test_worker_validate_plan_rechecks_shared_policy(monkeypatch):
    plan = {
        "no_change": False,
        "changes": [
            {
                "file": "tests/test_line_development.py",
                "old": "old",
                "new": "new",
            }
        ],
    }

    monkeypatch.setattr(worker, "_shared_policy_decision", lambda path: SelfImprovementDecision.EXPLICIT_APPROVAL)

    assert worker.validate_plan(plan, "tests/test_line_development.py") == (
        False,
        "self_improvement_policy:explicit_approval",
    )


def test_worker_preserves_explicit_deterministic_self_test_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    plan = {
        "no_change": False,
        "source": "deterministic_self_test",
        "changes": [
            {
                "file": "line_development.py",
                "old": '_WORKFLOW_FILE = "x"\n',
                "new": '_WORKFLOW_FILE = "x"\n# test\n',
            }
        ],
    }

    assert worker.validate_plan(plan, "line_development.py") == (
        True,
        "line_development.py",
    )
