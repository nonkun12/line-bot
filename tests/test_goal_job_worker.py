import db
import goal_job_store
import job_store
import goal_job_worker
import job_worker


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-worker.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()


def _goal():
    return {
        "goal_id": "goal-worker-demo",
        "objective": "Run Goal children through a typed worker",
        "success_criteria": [{"id": "test", "description": "Test evidence exists"}],
        "jobs": [],
    }


def _grant():
    return {
        "grant_id": "grant-worker-001",
        "goal_id": "goal-worker-demo",
        "active": True,
        "approved_by": "repository-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 4,
        "allowed_stages": ["test", "review"],
        "allowed_path_prefixes": ["tests/", "docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }


def _job():
    return {
        "id": "test-job",
        "criterion_id": "test",
        "stage": "test",
        "instruction": "Run focused regression tests.",
        "allowed_paths": ["tests/test_goal_job_worker.py"],
        "depends_on": [],
    }


def test_goal_worker_requires_executor_and_does_not_dry_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    queued = goal_job_store.persist_child_job("goal-worker-demo", _job())
    assert goal_job_worker.run_once() is None
    assert job_store.get_job(queued["job_id"])["status"] == "pending"


def test_goal_worker_executes_only_typed_goal_child_and_records_evidence(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    queued = goal_job_store.persist_child_job("goal-worker-demo", _job())
    calls = []

    def executor(job, payload):
        calls.append((job["id"], payload["goal_id"]))
        return {
            "result": "2 tests passed",
            "evidence": {
                "checks": [
                    {"name": "pytest", "status": "PASS", "source": "CI run 123"}
                ]
            },
        }

    result = goal_job_worker.run_once(executor)
    assert result["id"] == queued["job_id"]
    assert result["status"] == "completed"
    assert calls == [(queued["job_id"], "goal-worker-demo")]
    assert goal_job_store.get_goal_job_states("goal-worker-demo") == {"test-job": "done"}


def test_generic_worker_cannot_claim_goal_child(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    queued = goal_job_store.persist_child_job("goal-worker-demo", _job())
    assert job_worker.run_once() is None
    assert job_store.get_job(queued["job_id"])["status"] == "pending"


def test_goal_worker_records_executor_failure_without_false_success(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    queued = goal_job_store.persist_child_job("goal-worker-demo", _job())

    def broken(_job, _payload):
        raise RuntimeError("executor unavailable")

    result = goal_job_worker.run_once(broken)
    assert result["id"] == queued["job_id"]
    assert result["status"] == "failed"
    assert "executor unavailable" in result["last_error"]


def test_goal_worker_revalidates_scope_before_execution(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    goal_job_store.create_goal(_goal(), "U-test", _grant())
    queued = goal_job_store.persist_child_job("goal-worker-demo", _job())
    # Tamper with the persisted message after enqueue; worker must fail closed.
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET message=? WHERE id=?", ('{"goal_id":"other"}', queued["job_id"]))
    called = []
    result = goal_job_worker.run_once(lambda *_: called.append(True))
    assert result["status"] == "failed"
    assert called == []
