from agents.test.node import test_runner_node as run_test_agent


def test_test_runner_skips_when_patch_not_applied():
    state = {
        "agent_results": {},
        "patch_result": {
            "skipped": True,
            "applied": False,
        },
    }

    result = run_test_agent(state)

    assert result["test_result"]["skipped"] is True
    assert result["test_result"]["passed"] is None
    assert result["test_result"]["reason"] == "patch not applied"


def test_test_runner_skips_when_patch_failed():
    state = {
        "agent_results": {},
        "patch_result": {
            "skipped": False,
            "applied": False,
        },
    }

    result = run_test_agent(state)

    assert result["test_result"]["skipped"] is True
    assert result["test_result"]["passed"] is None


def test_test_runner_runs_tests_when_patch_applied(monkeypatch):
    expected = {
        "passed": True,
        "returncode": 0,
        "stdout": "5 passed",
        "stderr": "",
        "timed_out": False,
    }

    def fake_run_tests(cwd=None):
        return expected.copy()

    monkeypatch.setattr(
        "agents.test.node.run_tests",
        fake_run_tests,
    )

    state = {
        "agent_results": {},
        "patch_result": {
            "skipped": False,
            "applied": True,
        },
    }

    result = run_test_agent(state)

    assert result["test_result"]["skipped"] is False
    assert result["test_result"]["passed"] is True
    assert result["test_result"]["returncode"] == 0
