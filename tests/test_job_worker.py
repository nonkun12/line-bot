import pytest

import db
import job_store
import job_worker


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_run_once_moves_step_completed_back_to_pending(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "step test")

    def executor(_job):
        return {
            "status": "step_completed",
            "step_name": "supervisor",
            "next_step": "fallback_agent",
            "summary": "step complete",
        }

    result = job_worker.run_once(executor=executor)

    assert result["id"] == job_id
    assert result["status"] == "pending"
    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "supervisor"
    assert checkpoint["step_status"] == "completed"


def test_run_once_waits_for_approval(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "approval test")

    def executor(_job):
        return {
            "status": "waiting_approval",
            "step_name": "test_agent",
            "next_step": "commit_agent",
            "summary": "approval required",
        }

    result = job_worker.run_once(executor=executor)

    assert result["id"] == job_id
    assert result["status"] == "waiting_approval"
    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_status"] == "waiting_approval"


def test_run_once_retries_executor_failure(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "retry test", max_retries=2)

    def executor(_job):
        raise RuntimeError("temporary failure")

    result = job_worker.run_once(executor=executor)

    assert result["id"] == job_id
    assert result["status"] == "pending"
    assert result["retry_count"] == 1
    assert result["last_error"] == "temporary failure"


def test_run_once_fails_after_retry_limit(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "retry limit", max_retries=0)

    def executor(_job):
        raise RuntimeError("fatal failure")

    result = job_worker.run_once(executor=executor)

    assert result["id"] == job_id
    assert result["status"] == "failed"
    assert result["retry_count"] == 1


class FakeSnapshot:
    def __init__(self, values=None, next_nodes=()):
        self.values = values or {}
        self.next = next_nodes


def test_execute_one_step_uses_same_thread_id_for_resume():
    class FakeGraph:
        def __init__(self):
            self.calls = []
            self._snapshot = FakeSnapshot()
            self._invocations = 0

        def get_state(self, config):
            self.calls.append(("get_state", config))
            return self._snapshot

        def invoke(self, input_state, config):
            self.calls.append(("invoke", input_state, config))
            self._invocations += 1
            if self._invocations == 1:
                self._snapshot = FakeSnapshot(
                    values={"intent": "fallback", "request_id": "job-7"},
                    next_nodes=("fallback_agent",),
                )
            return self._snapshot.values

    fake_graph = FakeGraph()
    job = {"id": 7, "user_id": "U-test", "message": "hello"}

    result = job_worker.execute_one_step(job, graph=fake_graph)

    assert result["status"] == "step_completed"
    assert result["thread_id"] == "job-7"
    invoke_calls = [call for call in fake_graph.calls if call[0] == "invoke"]
    assert invoke_calls[0][2]["configurable"]["thread_id"] == "job-7"
