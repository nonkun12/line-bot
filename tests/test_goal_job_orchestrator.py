import db
import goal_job_orchestrator
import goal_job_store


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-orchestrator.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()


def _grant(goal_id, max_jobs=8):
    return {
        "grant_id": f"grant-{goal_id}",
        "goal_id": goal_id,
        "active": True,
        "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": max_jobs,
        "allowed_stages": ["test", "review", "fix"],
        "allowed_path_prefixes": ["tests/", "docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }


def _goal(goal_id="goal-orchestrator"):
    return {
        "goal_id": goal_id,
        "objective": "Complete a bounded Goal child chain",
        "success_criteria": [{"id": "criterion", "description": "Required checks pass"}],
        "jobs": [
            {
                "id": "first-test",
                "criterion_id": "criterion",
                "stage": "test",
                "instruction": "Run the first focused regression test.",
                "allowed_paths": ["tests/test_goal_job_orchestrator.py"],
                "depends_on": [],
            },
            {
                "id": "second-review",
                "criterion_id": "criterion",
                "stage": "review",
                "instruction": "Review the first test evidence.",
                "allowed_paths": ["docs/goal-review.md"],
                "depends_on": ["first-test"],
            },
        ],
    }


def test_advance_goal_persists_one_child_and_never_executes_inline(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator"))
    result = goal_job_orchestrator.advance_goal("goal-orchestrator")
    assert result["decision"] == "CHILD_JOB_QUEUED"
    assert result["job_record"]["created"] is True
    assert result["execute_job"] is False
    again = goal_job_orchestrator.advance_goal("goal-orchestrator")
    assert again["decision"] == "HOLD"


def test_run_until_blocked_reaches_goal_after_independent_evidence_passes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator"))
    executed = []

    def executor(job, payload):
        executed.append(payload["goal_job_key"])
        return {
            "result": f"completed {payload['goal_job_key']}",
            "evidence": {
                "checks": [{"name": "pytest", "status": "PASS", "source": "CI run 456"}]
            },
        }

    def evaluator(_goal_record, job):
        if job["status"] != "completed":
            return {"criterion": "FAIL"}
        key = __import__("json").loads(job["message"])["goal_job_key"]
        return {"criterion": "FAIL" if key == "first-test" else "PASS"}

    result = goal_job_orchestrator.run_until_blocked(
        "goal-orchestrator",
        executor=executor,
        evidence_evaluator=evaluator,
        max_steps=4,
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert executed == ["first-test", "second-review"]
    assert result["steps_executed"] == 2


def test_run_until_blocked_requires_executor_and_independent_evaluator(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator"))
    result = goal_job_orchestrator.run_until_blocked(
        "goal-orchestrator", executor=None, evidence_evaluator=lambda *_: {}
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "executor_and_independent_evaluator_required"


def test_run_until_blocked_rejects_budget_above_goal_grant(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator", max_jobs=2))
    result = goal_job_orchestrator.run_until_blocked(
        "goal-orchestrator",
        executor=lambda *_: {"result": "ok", "evidence": {"checks": [{"name": "test", "status": "PASS", "source": "CI"}]}},
        evidence_evaluator=lambda *_: {"criterion": "PASS"},
        max_steps=3,
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "step_budget_invalid"
