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

def test_successful_child_completion_rejects_any_failing_evidence_check(tmp_path, monkeypatch):
    import pytest

    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    child = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', claim_token=? WHERE id=?",
            ("claim-evidence-test", child["job_id"]),
        )

    failing_evidence = {
        "checks": [
            {"name": "pytest", "status": "PASS", "source": "CI run 123"},
            {"name": "scope", "status": "FAIL", "source": "git diff"},
        ]
    }
    with pytest.raises(ValueError, match="every evidence check to PASS"):
        goal_job_store.complete_claimed_child_job(
            child["job_id"],
            "claim-evidence-test",
            success=True,
            result="work completed",
            evidence=failing_evidence,
        )

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT status, claim_token FROM jobs WHERE id=?",
            (child["job_id"],),
        ).fetchone()
    assert row == ("running", "claim-evidence-test")

    passing_evidence = {
        "checks": [
            {"name": "pytest", "status": "PASS", "source": "CI run 123"},
            {"name": "scope", "status": "PASS", "source": "git diff"},
        ]
    }
    assert goal_job_store.complete_claimed_child_job(
        child["job_id"],
        "claim-evidence-test",
        success=True,
        result="verified work",
        evidence=passing_evidence,
    ) is True


def test_completed_criterion_requires_every_declared_job_and_passing_evidence(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    first = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    assert goal_job_store.evaluate_completed_goal_criteria("goal-autonomy-demo") == {
        "routing-tests": "FAIL",
        "evidence-review": "FAIL",
    }
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (first["job_id"],))
    goal_job_store.save_child_evidence(
        first["job_id"],
        {"checks": [{"name": "pytest", "status": "PASS", "source": "verified CI"}]},
    )
    assert goal_job_store.evaluate_completed_goal_criteria("goal-autonomy-demo") == {
        "routing-tests": "PASS",
        "evidence-review": "FAIL",
    }


def test_goal_id_can_be_resolved_from_registered_child(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    child = goal_job_store.persist_child_job("goal-autonomy-demo", _job())
    assert goal_job_store.get_goal_id_for_child_job(child["job_id"]) == "goal-autonomy-demo"
    assert goal_job_store.get_goal_id_for_child_job(999999) is None


def test_verified_followup_can_resolve_a_failed_attempt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = {
        "goal_id": "goal-followup-evidence",
        "objective": "Complete a scoped planning goal",
        "success_criteria": [{"id": "criterion", "description": "The plan is verified"}],
        "jobs": [{
            "id": "initial",
            "criterion_id": "criterion",
            "stage": "design",
            "instruction": "Create the initial plan.",
            "allowed_paths": ["docs/initial-plan.md"],
            "depends_on": [],
        }],
    }
    grant = _grant()
    grant.update({
        "goal_id": "goal-followup-evidence",
        "grant_id": "grant-followup-evidence",
        "max_jobs": 4,
        "allowed_stages": ["design"],
        "allowed_path_prefixes": ["docs/"],
    })
    goal_job_store.create_goal(goal, "U-test", grant)
    first = goal_job_store.persist_child_job("goal-followup-evidence", goal["jobs"][0])
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='failed' WHERE id=?", (first["job_id"],))
    assert goal_job_store.evaluate_completed_goal_criteria("goal-followup-evidence") == {"criterion": "FAIL"}

    followup = {
        "id": "goal-followup-002",
        "criterion_id": "criterion",
        "stage": "design",
        "instruction": "Create a focused follow-up plan.",
        "allowed_paths": ["docs/followup-plan.md"],
        "depends_on": [],
    }
    assert goal_job_store.register_child_job_definition("goal-followup-evidence", followup) is True
    child = goal_job_store.persist_child_job("goal-followup-evidence", followup)
    assert goal_job_store.evaluate_completed_goal_criteria("goal-followup-evidence") == {"criterion": "FAIL"}
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (child["job_id"],))
    goal_job_store.save_child_evidence(
        child["job_id"],
        {"checks": [{"name": "review", "status": "PASS", "source": "independent evidence"}]},
    )
    assert goal_job_store.evaluate_completed_goal_criteria("goal-followup-evidence") == {"criterion": "PASS"}
