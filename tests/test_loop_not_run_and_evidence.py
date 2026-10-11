"""Regression tests for NOT_RUN empty queues and consistent task evidence."""
import json
from pathlib import Path

import pytest

from scripts import run_minimal_autonomous_loop as loop


def _task(task_id="task-1"):
    return {"id": task_id, "instruction": "test", "allowed_paths": ["tests/test_loop_not_run_and_evidence.py"]}


def test_empty_queue_records_not_run_and_returns_78(monkeypatch, tmp_path, capsys):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": ["task-1"]}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [_task()])
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state), "--stop-file", str(tmp_path / "stop")])
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 78
    assert "NOT_RUN" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "NOT_RUN"
    assert row["failure_reason"] == "queue_empty"
    assert row["task_count"] == 0
    assert row["queue_total"] == 1
    assert row["queue_completed"] == 1
    # Empty-queue reporting must not mutate durable completion state.
    assert json.loads(state.read_text(encoding="utf-8")) == {"version": 1, "completed": ["task-1"]}


def test_empty_task_list_records_not_run(monkeypatch, tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": []}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [])
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state), "--stop-file", str(tmp_path / "stop")])
    assert loop.main() == 78
    assert json.loads(results.read_text(encoding="utf-8").splitlines()[0])["status"] == "NOT_RUN"


def test_workflow_maps_only_exit_78_to_not_run():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'if [ "$loop_rc" -eq 78 ]' in workflow
    assert 'rm -f /tmp/minimal-autonomous-loop.jsonl' in workflow
    assert 'exit "$loop_rc"' in workflow
    assert "AUTO_APPLY_PATCH: 'false'" in workflow
    assert "AUTO_DEPLOY: 'false'" in workflow
    assert ".autonomous-loop.stop" in workflow


def test_workflow_never_completes_zero_task_empty_queue():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert 'queue_exhausted_no_tasks' not in workflow
    assert "classify_final_outcome" in workflow
    assert "final_outcome_classifier_failed" in workflow
    assert 'result="NOT_RUN"' in workflow


def test_workflow_state_is_not_advanced_for_empty_queue():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    persist = workflow[workflow.index("- name: Persist completed task state"):workflow.index("- name: Record distributed run result to Google Sheets")]
    assert "autonomous-loop-not-run" in persist
    assert "state unchanged" in persist


# Summary-evidence regression tests: exit code 0 alone must never manufacture PASS.
from datetime import datetime, timezone


class _FakeProcess:
    def __init__(self, returncode=0):
        self.pid = 4242
        self.returncode = None
        self._final = returncode

    def poll(self):
        self.returncode = self._final
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self._final
        return self.returncode


def _run_with_summary(monkeypatch, tmp_path, summary_factory, *, exit_code=0, heads=("a" * 40, "c" * 40)):
    task = _task("evidence-task")
    sequence = list(heads)

    def fake_head():
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]

    monkeypatch.setattr(loop, "_git_head", fake_head)
    monkeypatch.setattr(loop, "_verify_produced_head", lambda *a, **k: (True, ""))

    def fake_popen(cmd, cwd, env, text, start_new_session):
        content = summary_factory(env)
        if content is not None:
            Path(env["AUTONOMOUS_SUMMARY_PATH"]).write_text(content, encoding="utf-8")
        return _FakeProcess(exit_code)

    monkeypatch.setattr(loop.subprocess, "Popen", fake_popen)
    return loop.run_task(task, 1, tmp_path / "stop", summary_dir=tmp_path)


def _summary(env, **overrides):
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "exit_code": 0,
        "base_sha": "a" * 40,
        "produced_sha": "c" * 40,
        "task_id": "evidence-task",
        "run_nonce": env["AUTONOMOUS_RUN_NONCE"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_consistent_pass_summary_is_accepted(monkeypatch, tmp_path):
    result = _run_with_summary(monkeypatch, tmp_path, lambda env: _summary(env))
    assert result["status"] == "PASS"
    assert result["failure_reason"] == ""


def test_missing_summary_cannot_be_pass(monkeypatch, tmp_path):
    result = _run_with_summary(monkeypatch, tmp_path, lambda env: None)
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_missing_required_key"


def test_unknown_summary_status_cannot_be_pass(monkeypatch, tmp_path):
    result = _run_with_summary(monkeypatch, tmp_path, lambda env: _summary(env, status="SUCCESS"))
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_status_invalid"


def test_produced_sha_must_match_observed_head(monkeypatch, tmp_path):
    result = _run_with_summary(monkeypatch, tmp_path, lambda env: _summary(env, produced_sha="d" * 40))
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_produced_sha_mismatch"


def test_no_change_claim_with_moved_head_is_rejected(monkeypatch, tmp_path):
    result = _run_with_summary(monkeypatch, tmp_path, lambda env: _summary(env, status="NO_CHANGE"))
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "summary_no_change_but_head_moved"


def test_consistent_no_change_summary_is_accepted(monkeypatch, tmp_path):
    base = "a" * 40
    result = _run_with_summary(
        monkeypatch, tmp_path,
        lambda env: _summary(env, status="NO_CHANGE", produced_sha=base),
        heads=(base, base),
    )
    assert result["status"] == "NO_CHANGE"
    assert result["failure_reason"] == "no_change"

def test_not_run_does_not_fabricate_task_identity_or_instruction():
    workflow = Path(".github/workflows/distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    assert "if status == 'NOT_RUN':" in workflow
    assert "os.environ['AUTONOMOUS_TASK_ID'] = ''" in workflow
    assert "Queue exhausted; no task executed; replenish the task queue." in workflow




def test_final_outcome_empty_queue_is_not_run():
    assert loop.classify_final_outcome(
        ["NOT_RUN"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        queue_empty=True,
    ) == ("NOT_RUN", "queue_empty")


@pytest.mark.parametrize(
    ("gate", "expected_reason"),
    [
        ("publish", "post_run_gate_failed:publish"),
        ("state", "post_run_gate_failed:state"),
        ("sheets", "post_run_gate_failed:sheets"),
        ("loop", "post_run_gate_failed:loop"),
    ],
)
def test_final_outcome_pass_is_not_completed_when_post_run_gate_fails(gate, expected_reason):
    outcomes = {
        "loop_outcome": "success",
        "publish_outcome": "success",
        "state_outcome": "success",
        "sheets_outcome": "success",
    }
    outcomes[f"{gate}_outcome"] = "failure"
    assert loop.classify_final_outcome(["PASS"], **outcomes) == ("FAILED", expected_reason)


def test_final_outcome_normal_pass_requires_all_gates():
    assert loop.classify_final_outcome(
        ["PASS", "NO_CHANGE"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
    ) == ("COMPLETED", "required_gates_passed")


def test_final_outcome_missing_evidence_fails_closed():
    assert loop.classify_final_outcome(
        [],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
    ) == ("BLOCKED", "missing_task_evidence")


def test_final_outcome_empty_queue_marker_mismatch_is_blocked():
    assert loop.classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        queue_empty=True,
    ) == ("BLOCKED", "queue_empty_evidence_mismatch")



def test_final_outcome_does_not_claim_completion_before_requested_work():
    assert loop.classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        requested_tasks=4,
        queue_completed=2,
        queue_total=5,
    ) == ("INCOMPLETE", "requested_task_limit_not_met")


def test_final_outcome_allows_queue_exhaustion_after_fewer_tasks():
    assert loop.classify_final_outcome(
        ["PASS"],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        requested_tasks=4,
        queue_completed=5,
        queue_total=5,
    ) == ("COMPLETED", "required_gates_passed")



def test_final_outcome_empty_queue_without_result_row_is_blocked():
    assert loop.classify_final_outcome(
        [],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success",
        sheets_outcome="success",
        queue_empty=True,
    ) == ("BLOCKED", "queue_empty_evidence_mismatch")
