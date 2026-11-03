from scripts.goal_job_runtime_adapter import execute_goal_child


def test_goal_runtime_adapter_passes_exact_granted_paths_and_records_provenance():
    calls = []
    git_values = {
        ("rev-parse", "HEAD"): ["base-sha", "produced-sha"],
        ("branch", "--show-current"): ["goal-child/42"],
        ("diff", "--name-only", "base-sha..produced-sha"): ["tests/test_goal_job_runtime_adapter.py"],
    }

    def fake_git(*args):
        value = git_values[args].pop(0)
        return value

    def fake_execute(instruction, *, allowed_paths):
        calls.append((instruction, allowed_paths))
        return 0

    payload = {
        "goal_job_key": "job-42",
        "instruction": "Add one focused regression test",
        "allowed_paths": ["tests/test_goal_job_runtime_adapter.py"],
    }
    output = execute_goal_child(
        {"id": 42, "job_type": "goal_child"},
        payload,
        runtime_execute=fake_execute,
        git=fake_git,
    )

    assert calls == [("Add one focused regression test", ["tests/test_goal_job_runtime_adapter.py"])]
    assert output["evidence"]["base_sha"] == "base-sha"
    assert output["evidence"]["produced_sha"] == "produced-sha"
    assert output["evidence"]["changed_paths"] == ["tests/test_goal_job_runtime_adapter.py"]
    assert all(item["status"] == "PASS" for item in output["evidence"]["checks"])


def test_goal_runtime_adapter_marks_out_of_grant_changes_as_failure():
    git_values = {
        ("rev-parse", "HEAD"): ["base-sha", "produced-sha"],
        ("branch", "--show-current"): ["goal-child/42"],
        ("diff", "--name-only", "base-sha..produced-sha"): [
            "tests/test_goal_job_runtime_adapter.py\ncore/protected.py"
        ],
    }

    def fake_git(*args):
        return git_values[args].pop(0)

    output = execute_goal_child(
        {"id": 42, "job_type": "goal_child"},
        {
            "goal_job_key": "job-42",
            "instruction": "Add one focused regression test",
            "allowed_paths": ["tests/test_goal_job_runtime_adapter.py"],
        },
        runtime_execute=lambda *args, **kwargs: 0,
        git=fake_git,
    )

    assert output["evidence"]["outside_scope_paths"] == ["core/protected.py"]
    assert output["evidence"]["checks"][1]["status"] == "FAIL"


def test_goal_runtime_adapter_rejects_non_goal_jobs_before_execution():
    called = []
    try:
        execute_goal_child(
            {"id": 1, "job_type": "normal"},
            {"instruction": "do work", "allowed_paths": ["tests/test_x.py"]},
            runtime_execute=lambda *args, **kwargs: called.append(True) or 0,
            git=lambda *args: "sha",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("non-Goal job must be rejected")
    assert called == []


def test_goal_runtime_adapter_rejects_duplicate_allowed_paths():
    try:
        execute_goal_child(
            {"id": 1, "job_type": "goal_child"},
            {
                "instruction": "do work",
                "allowed_paths": ["tests/test_x.py", "tests/test_x.py"],
            },
            runtime_execute=lambda *args, **kwargs: 0,
            git=lambda *args: "sha",
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate grant paths must be rejected")


def test_run_goal_child_once_delegates_to_typed_worker(monkeypatch):
    from scripts import goal_job_runtime_adapter as adapter

    captured = {}

    def fake_run_once(executor, *, job_id=None):
        captured["executor"] = executor
        captured["job_id"] = job_id
        return {"id": job_id, "status": "completed"}

    monkeypatch.setattr(adapter.goal_job_worker, "run_once", fake_run_once)
    result = adapter.run_goal_child_once(job_id=77)

    assert result == {"id": 77, "status": "completed"}
    assert captured == {"executor": adapter.execute_goal_child, "job_id": 77}


def test_goal_runtime_adapter_sets_and_restores_child_audit_identity(monkeypatch):
    import os

    from scripts.goal_job_runtime_adapter import execute_goal_child

    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "previous-task")
    monkeypatch.setenv("AUTONOMOUS_RUN_SOURCE", "previous-source")
    git_values = {
        ("rev-parse", "HEAD"): ["base-sha", "produced-sha"],
        ("branch", "--show-current"): ["goal-child/42"],
        ("diff", "--name-only", "base-sha..produced-sha"): ["tests/test_goal_job_runtime_adapter.py"],
    }
    observed = {}

    def fake_git(*args):
        return git_values[args].pop(0)

    def fake_execute(instruction, *, allowed_paths):
        observed["task_id"] = os.environ.get("AUTONOMOUS_TASK_ID")
        observed["source"] = os.environ.get("AUTONOMOUS_RUN_SOURCE")
        return 0

    execute_goal_child(
        {"id": 42, "job_type": "goal_child"},
        {
            "goal_job_key": "goal-child-42",
            "instruction": "Add a regression test",
            "allowed_paths": ["tests/test_goal_job_runtime_adapter.py"],
        },
        runtime_execute=fake_execute,
        git=fake_git,
    )

    assert observed == {
        "task_id": "goal-child-42",
        "source": "goal-child",
    }
    assert os.environ["AUTONOMOUS_TASK_ID"] == "previous-task"
    assert os.environ["AUTONOMOUS_RUN_SOURCE"] == "previous-source"
