import json

import pytest

import db
import job_store
import job_worker
from goal_job_runtime import advance_goal, load_goal_job_states, normalize_job_status, _persist_next_job


def setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-jobs.sqlite"))
    db.init_db()


def proposal(job_id="child-1", *, depends_on=None):
    return {
        "decision": "PROPOSE_CHILD_JOB",
        "goal_id": "goal-demo",
        "criterion_id": "criterion-demo",
        "human_approval_required": False,
        "autonomy_grant_id": "grant-demo",
        "autonomy_policy": {"decision": "AUTO_APPROVE", "risk": "low"},
        "permissions": {"merge": False, "deploy": False},
        "job": {
            "id": job_id,
            "stage": "test",
            "instruction": "Run focused tests for the Goal child.",
            "allowed_paths": ["tests/test_goal_job_runtime.py"],
            "depends_on": depends_on or [],
        },
    }


def test_goal_child_persistence_is_idempotent_and_state_is_normalized(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    first = __persist_next_job(proposal(), user_id="U-test")
    second = _persist_next_job(proposal(), user_id="U-test")

    assert first["created"] is True
    assert second["created"] is False
    assert first["job_id"] == second["job_id"]
    assert len(job_store.list_goal_child_jobs("goal-demo")) == 1
    assert load_goal_job_states("goal-demo") == {"child-1": "pending"}
    assert normalize_job_status("completed") == "done"
    assert normalize_job_status("done") == "done"


def test_goal_child_key_cannot_be_reused_for_different_payload(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    _persist_next_job(proposal(), user_id="U-test")
    changed = proposal()
    changed["job"]["instruction"] = "A different instruction"
    with pytest.raises(ValueError, match="different payload"):
        _persist_next_job(changed, user_id="U-test")


def test_dependent_child_requires_completed_parent(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    parent_id = job_store.create_job("U-test", "parent")
    with pytest.raises(ValueError, match="completed"):
        _persist_next_job(
            proposal("child-2", depends_on=["child-1"]),
            user_id="U-test", parent_job_id=parent_id,
        )
    job_store.update_job(parent_id, status="completed")
    result = _persist_next_job(
        proposal("child-2", depends_on=["child-1"]),
        user_id="U-test", parent_job_id=parent_id,
    )
    child = job_store.get_job(result["job_id"])
    assert child["parent_job_id"] == parent_id
    assert child["job_type"] == "goal_child"


def test_persist_adapter_rejects_unapproved_or_unbounded_proposals(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    plan = proposal()
    plan["human_approval_required"] = True
    with pytest.raises(ValueError):
        _persist_next_job(plan, user_id="U-test")
    plan = proposal()
    plan["permissions"]["merge"] = True
    with pytest.raises(ValueError):
        _persist_next_job(plan, user_id="U-test")


def test_goal_worker_only_claims_typed_jobs_and_requires_executor(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    normal_id = job_store.create_job("U-test", "normal")
    goal = _persist_next_job(proposal(), user_id="U-test")
    with pytest.raises(ValueError, match="executor"):
        job_worker.run_goal_child_once()
    assert job_store.get_job(goal["job_id"])["status"] == "pending"
    assert job_store.get_job(normal_id)["status"] == "pending"


def test_goal_worker_completes_only_with_explicit_pass_evidence(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    goal = _persist_next_job(proposal(), user_id="U-test")

    def executor(job, payload):
        assert job["id"] == goal["job_id"]
        assert payload["goal_id"] == "goal-demo"
        return {"outcome": "PASS", "summary": "All focused tests passed", "evidence": ["pytest: 12 passed"]}

    result = job_worker.run_goal_child_once(executor=executor)
    assert result["id"] == goal["job_id"]
    assert result["status"] == "done"
    saved = json.loads(result["result"])
    assert saved["outcome"] == "PASS"
    assert saved["evidence"] == ["pytest: 12 passed"]
    assert load_goal_job_states("goal-demo") == {"child-1": "done"}


def test_goal_worker_records_fail_and_rejects_missing_evidence(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    goal = _persist_next_job(proposal(), user_id="U-test")

    result = job_worker.run_goal_child_once(
        executor=lambda _job, _payload: {"outcome": "PASS", "evidence": []}
    )
    assert result["id"] == goal["job_id"]
    assert result["status"] == "failed"
    assert "evidence" in result["last_error"]
    assert load_goal_job_states("goal-demo") == {"child-1": "failed"}


def test_goal_worker_records_explicit_failure_with_evidence(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    goal = _persist_next_job(proposal(), user_id="U-test")
    result = job_worker.run_goal_child_once(
        executor=lambda _job, _payload: {
            "outcome": "FAIL", "summary": "One assertion failed",
            "evidence": ["pytest: 1 failed, 11 passed"],
        }
    )
    assert result["id"] == goal["job_id"]
    assert result["status"] == "failed"
    assert json.loads(result["result"])["outcome"] == "FAIL"


def trusted_grant():
    return {
        "grant_id": "grant-demo",
        "goal_id": "goal-demo",
        "active": True,
        "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 10,
        "allowed_stages": ["requirements", "design", "implementation", "test", "review", "fix", "verify"],
        "allowed_path_prefixes": ["tests/", "docs/", "agents/", "core/", "scripts/"],
        "auto_merge": False,
        "auto_deploy": False,
    }


def chained_goal():
    return {
        "goal_id": "goal-demo",
        "objective": "Verify a two-stage child JOB chain",
        "success_criteria": [
            {"id": "criterion-demo", "description": "Both stages pass with evidence"},
        ],
        "jobs": [
            {
                "id": "child-1", "criterion_id": "criterion-demo",
                "stage": "test", "instruction": "Run stage one tests.",
                "allowed_paths": ["tests/test_goal_job_runtime.py"],
                "depends_on": [],
            },
            {
                "id": "child-2", "criterion_id": "criterion-demo",
                "stage": "test", "instruction": "Run stage two tests.",
                "allowed_paths": ["tests/test_goal_job_runtime.py"],
                "depends_on": ["child-1"],
            },
        ],
    }


def test_advance_goal_persists_executes_and_chains_until_verified_goal(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    goal = chained_goal()
    grant = trusted_grant()

    first = advance_goal(goal, user_id="U-test", autonomy_grant=grant)
    assert first["plan"]["decision"] == "PROPOSE_CHILD_JOB"
    assert first["persisted_job"]["job_key"] == "child-1"

    waiting = advance_goal(goal, user_id="U-test", autonomy_grant=grant)
    assert waiting["plan"]["decision"] == "HOLD"
    assert waiting["criterion_results"]["criterion-demo"] == "UNKNOWN"

    first_result = job_worker.run_goal_child_once(
        executor=lambda _job, _payload: {
            "outcome": "PASS", "summary": "stage one complete",
            "evidence": ["stage one test report: PASS"],
        }
    )
    assert first_result["status"] == "done"

    second = advance_goal(goal, user_id="U-test", autonomy_grant=grant)
    assert second["plan"]["decision"] == "PROPOSE_CHILD_JOB"
    assert second["persisted_job"]["job_key"] == "child-2"
    second_job = job_store.get_job(second["persisted_job"]["job_id"])
    assert second_job["parent_job_id"] == first_result["id"]

    second_result = job_worker.run_goal_child_once(
        executor=lambda _job, _payload: {
            "outcome": "PASS", "summary": "stage two complete",
            "evidence": ["stage two test report: PASS"],
        }
    )
    assert second_result["status"] == "done"

    completed = advance_goal(goal, user_id="U-test", autonomy_grant=grant)
    assert completed["plan"]["decision"] == "GOAL_ACHIEVED"
    assert completed["criterion_results"]["criterion-demo"] == "PASS"
    assert completed["persisted_job"] is None


def test_advance_goal_never_reports_pass_without_evidence(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    goal = chained_goal()
    first = advance_goal(goal, user_id="U-test", autonomy_grant=trusted_grant())
    job_id = first["persisted_job"]["job_id"]
    # A legacy/direct DB status change without an evidence payload is not enough.
    job_store.update_job(job_id, status="completed", result="completed")
    result = advance_goal(goal, user_id="U-test", autonomy_grant=trusted_grant())
    assert result["criterion_results"]["criterion-demo"] == "FAIL"
    assert result["plan"]["decision"] == "PROPOSE_CHILD_JOB"
