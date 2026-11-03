import json

import db
import goal_job_store


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-chain.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()


def _goal():
    return {
        "goal_id": "goal-autonomy-demo",
        "objective": "LINE開発指示をGoal達成まで安全に連鎖実行する",
        "success_criteria": [
            {"id": "routing-tests", "description": "Routing regression tests pass"},
            {"id": "evidence-review", "description": "Evidence review passes"},
        ],
        "jobs": [{
            "id": "routing-tests",
            "criterion_id": "routing-tests",
            "stage": "test",
            "instruction": "Add focused routing regression tests.",
            "allowed_paths": ["tests/test_line_development_routing.py"],
            "depends_on": [],
        }, {
            "id": "review", "criterion_id": "evidence-review",
            "stage": "review", "instruction": "Review the regression evidence.",
            "allowed_paths": ["docs/review.md"], "depends_on": ["routing-tests"],
        }],
    }


def _grant():
    return {
        "grant_id": "grant-demo-001",
        "goal_id": "goal-autonomy-demo",
        "active": True,
        "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 8,
        "allowed_stages": ["requirements", "design", "implementation", "test", "review", "fix", "verify"],
        "allowed_path_prefixes": ["tests/", "docs/", "agents/", "core/", "scripts/"],
        "auto_merge": False,
        "auto_deploy": False,
    }


def _job():
    return {
        "id": "routing-tests",
        "criterion_id": "routing-tests",
        "stage": "test",
        "instruction": "Add focused routing regression tests.",
        "allowed_paths": ["tests/test_line_development_routing.py"],
        "depends_on": [],
    }


def test_create_goal_persists_one_time_grant_idempotently(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = goal_job_store.create_goal(_goal(), "U-test", _grant())
    second = goal_job_store.create_goal(_goal(), "U-test", _grant())
    assert first["goal_id"] == second["goal_id"]
    assert first["autonomy_grant"]["grant_id"] == "grant-demo-001"
    assert first["status"] == "active"


def test_goal_id_cannot_be_reused_with_changed_goal_or_grant(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    changed = _goal()
    changed["objective"] = "different objective"
    import pytest
    with pytest.raises(ValueError):
        goal_job_store.create_goal(changed, "U-test", _grant())


def test_persist_child_job_is_idempotent_and_keeps_parent_relation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    first = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    second = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    assert first["created"] is True
    assert second["created"] is False
    assert first["job_id"] == second["job_id"]
    assert goal_job_store.get_goal_job_states("goal-autonomy-demo") == {"routing-tests": "pending"}

    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (first["job_id"],))
    child = goal_job_store.persist_child_job(
        "goal-autonomy-demo",
        {
            "id": "review",
            "criterion_id": "evidence-review",
            "stage": "review",
            "instruction": "Review the regression evidence.",
            "allowed_paths": ["docs/review.md"],
            "depends_on": ["routing-tests"],
        },
        parent_job_key="routing-tests",
    )
    assert child["parent_job_id"] == first["job_id"]


def test_persist_child_job_rejects_scope_and_budget_violations(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    unsafe = _job()
    unsafe["allowed_paths"] = ["app.py"]
    import pytest
    with pytest.raises(PermissionError):
        goal_job_store.persist_child_job("goal-autonomy-demo", unsafe)

    budget_goal = _goal()
    budget_goal["goal_id"] = "goal-autonomy-budget"
    budget_goal["jobs"].append({
        "id": "second", "criterion_id": "evidence-review", "stage": "review",
        "instruction": "Review the evidence.", "allowed_paths": ["docs/review.md"], "depends_on": [],
    })
    grant = _grant()
    grant["goal_id"] = "goal-autonomy-budget"
    grant["grant_id"] = "grant-autonomy-budget"
    grant["max_jobs"] = 1
    goal_job_store.create_goal(budget_goal, "U-test-2", grant)
    goal_job_store.persist_child_job("goal-autonomy-budget", _job())
    with pytest.raises(PermissionError):
        goal_job_store.persist_child_job(
            "goal-autonomy-budget",
            {
                "id": "second",
                "criterion_id": "evidence-review",
                "stage": "review",
                "instruction": "Review the evidence.",
                "allowed_paths": ["docs/review.md"],
                "depends_on": [],
            },
        )


def test_status_normalizes_completed_and_done_and_evidence_closes_goal(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    first = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (first["job_id"],))
    passing_evidence = {"checks": [{"name": "pytest", "status": "PASS", "source": "CI run 123"}]}
    assert goal_job_store.save_child_evidence(first["job_id"], passing_evidence) is True
    review = goal_job_store.persist_child_job(
        "goal-autonomy-demo",
        {
            "id": "review", "criterion_id": "evidence-review", "stage": "review",
            "instruction": "Review the regression evidence.",
            "allowed_paths": ["docs/review.md"], "depends_on": ["routing-tests"],
        },
        parent_job_key="routing-tests",
    )
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (review["job_id"],))
    assert goal_job_store.save_child_evidence(review["job_id"], passing_evidence) is True
    assert goal_job_store.get_goal_job_states("goal-autonomy-demo") == {
        "routing-tests": "done", "review": "done"
    }
    result = goal_job_store.update_goal_evidence(
        "goal-autonomy-demo",
        {"routing-tests": "PASS", "evidence-review": "PASS"},
    )
    assert result["status"] == "achieved"


def test_grant_must_be_valid_and_goal_scoped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    bad = _grant()
    bad["goal_id"] = "another-goal"
    import pytest
    with pytest.raises(ValueError):
        goal_job_store.create_goal(_goal(), "U-test", bad)
