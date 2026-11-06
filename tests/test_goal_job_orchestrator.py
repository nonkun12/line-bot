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


def test_run_until_blocked_uses_registered_fix_after_failed_child(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = _goal("goal-repair-chain")
    goal["jobs"][1]["id"] = "repair-first-test"
    goal["jobs"][1]["stage"] = "fix"
    goal["jobs"][1]["instruction"] = "Repair the failed focused test."
    goal["jobs"][1]["allowed_paths"] = ["tests/test_goal_job_orchestrator.py"]
    grant = _grant("goal-repair-chain")
    goal_job_store.create_goal(goal, "U-test", grant)
    calls = []

    def executor(_job, payload):
        key = payload["goal_job_key"]
        calls.append(key)
        if key == "first-test":
            raise RuntimeError("test command failed")
        return {
            "result": "repair applied and verified",
            "evidence": {
                "checks": [{"name": "pytest", "status": "PASS", "source": "CI run 789"}]
            },
        }

    def evaluator(_goal_record, job):
        if job["status"] != "completed":
            return {"criterion": "FAIL"}
        import json
        key = json.loads(job["message"])["goal_job_key"]
        return {"criterion": "PASS" if key == "repair-first-test" else "FAIL"}

    result = goal_job_orchestrator.run_until_blocked(
        "goal-repair-chain",
        executor=executor,
        evidence_evaluator=evaluator,
        max_steps=4,
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert calls == ["first-test", "repair-first-test"]
    assert result["steps_executed"] == 2


def test_run_until_blocked_generates_new_child_jobs_when_registered_queue_is_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = _goal("goal-dynamic-generation")
    goal["jobs"] = []
    goal_job_store.create_goal(goal, "U-test", _grant("goal-dynamic-generation"))
    generated = []

    def generator(goal_record, criterion_results, job_states):
        generated.append((goal_record["goal_id"], dict(criterion_results), dict(job_states)))
        return {
            "id": "generated-test",
            "criterion_id": "criterion",
            "stage": "test",
            "instruction": "Run the missing focused regression test.",
            "allowed_paths": ["tests/test_goal_job_orchestrator.py"],
            "depends_on": [],
        }

    def executor(_job, payload):
        return {
            "result": "generated task complete",
            "evidence": {
                "checks": [{"name": "pytest", "status": "PASS", "source": "CI run 999"}]
            },
        }

    result = goal_job_orchestrator.run_until_blocked(
        "goal-dynamic-generation",
        executor=executor,
        evidence_evaluator=lambda *_: {"criterion": "PASS"},
        job_generator=generator,
        max_steps=3,
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert len(generated) == 1
    assert generated[0][0] == "goal-dynamic-generation"


def test_generated_job_outside_goal_grant_is_held(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal = _goal("goal-reject-generated")
    goal["jobs"] = []
    goal_job_store.create_goal(goal, "U-test", _grant("goal-reject-generated"))

    def generator(*_):
        return {
            "id": "unsafe-generated",
            "criterion_id": "criterion",
            "stage": "implementation",
            "instruction": "Change production code.",
            "allowed_paths": ["app.py"],
            "depends_on": [],
        }

    result = goal_job_orchestrator.advance_goal(
        "goal-reject-generated",
        job_generator=generator,
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "generated_job_rejected"



def test_run_until_blocked_resumes_persisted_pending_child_after_interruption(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator"))
    queued = goal_job_orchestrator.advance_goal("goal-orchestrator")
    assert queued["decision"] == "CHILD_JOB_QUEUED"
    assert goal_job_store.get_goal_child_jobs("goal-orchestrator")[0]["status"] == "pending"

    executed = []

    def executor(_job, payload):
        executed.append(payload["goal_job_key"])
        return {
            "result": "resumed child completed",
            "evidence": {
                "checks": [{"name": "pytest", "status": "PASS", "source": "CI run 1001"}]
            },
        }

    def evaluator(_goal_record, job):
        import json
        key = json.loads(job["message"])["goal_job_key"]
        return {"criterion": "PASS" if key == "second-review" else "FAIL"}

    result = goal_job_orchestrator.run_until_blocked(
        "goal-orchestrator",
        executor=executor,
        evidence_evaluator=evaluator,
        max_steps=4,
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert executed == ["first-test", "second-review"]
    assert result["steps_executed"] == 2


def test_run_until_blocked_does_not_steal_running_child(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant("goal-orchestrator"))
    queued = goal_job_orchestrator.advance_goal("goal-orchestrator")
    job_id = queued["job_record"]["job_id"]
    claimed = db.claim_goal_child_job(job_id)
    assert claimed is not None

    result = goal_job_orchestrator.run_until_blocked(
        "goal-orchestrator",
        executor=lambda *_: {"result": "should not run", "evidence": {"checks": [{"name": "x", "status": "PASS", "source": "test"}]}},
        evidence_evaluator=lambda *_: {"criterion": "PASS"},
        max_steps=2,
    )
    assert result["decision"] == "HOLD"
    assert result["reason"] == "goal_child_already_running"
    assert result["job_id"] == job_id
