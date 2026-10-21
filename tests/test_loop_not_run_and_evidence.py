"""Regression tests for NOT_RUN empty queues and consistent task evidence."""
import json
from pathlib import Path

import pytest

from scripts import run_minimal_autonomous_loop as loop


def _task(task_id="task-1"):
    return {"id": task_id, "instruction": "test", "allowed_paths": ["tests/test_loop_not_run_and_evidence.py"]}


def test_completed_only_queue_records_no_eligible_task_and_returns_78(monkeypatch, tmp_path, capsys):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": ["task-1"]}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: [_task()])
    # The test queue is synthetic; explicitly provide its reviewed test catalog.
    monkeypatch.setattr(loop, "_load_registered_catalog", lambda _sha: [_task()])
    monkeypatch.setattr(loop.sys, "argv", ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state), "--stop-file", str(tmp_path / "stop")])
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 78
    assert "NOT_RUN" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "NOT_RUN"
    assert row["failure_reason"] == "no_eligible_task"
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
    assert 'queue_empty' in workflow
    assert 'QUEUE_EMPTY' not in workflow
    assert 'Path("/tmp/autonomous-loop-not-run").exists()' in workflow


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

@pytest.mark.parametrize(
    ("gate", "outcome"),
    [("publish", "failure"), ("state", "failure"), ("sheets", "failure")],
)
def test_final_outcome_empty_queue_blocks_when_required_gate_fails(gate, outcome):
    outcomes = {
        "loop_outcome": "success",
        "publish_outcome": "success",
        "state_outcome": "success",
        "sheets_outcome": "success",
        "queue_empty": True,
    }
    outcomes[{"loop": "loop_outcome", "publish": "publish_outcome", "state": "state_outcome", "sheets": "sheets_outcome"}.get(gate, gate)] = outcome
    assert loop.classify_final_outcome(["NOT_RUN"], **outcomes) == (
        "BLOCKED",
        f"queue_empty_post_run_gate_failed:{gate}",
    )



def _prepare_selector_main(monkeypatch, tmp_path, tasks, head_reader=None):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"max_tasks_per_run": 4}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": []}), encoding="utf-8")
    results = tmp_path / "results.jsonl"
    monkeypatch.setattr(loop, "QUEUE", queue)
    monkeypatch.setattr(loop, "load_tasks", lambda: tasks)
    monkeypatch.setattr(
        loop,
        "_load_registered_catalog",
        lambda _sha: [
            {**task, "allowed_paths": list(task["allowed_paths"])}
            for task in tasks
        ],
    )
    monkeypatch.setattr(loop, "_git_head", head_reader or (lambda: "a" * 40))

    class _RecoveryStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def _read(self):
            return {"schema_version": 1, "tasks": {}, "checkpoint": None}

        def task_status(self, _task_id):
            return {"held": False}

    monkeypatch.setattr("scripts.recovery_ai.RecoveryStore", _RecoveryStore)
    monkeypatch.setattr(
        loop.sys,
        "argv",
        ["loop", "--max-tasks", "1", "--results", str(results), "--state", str(state),
         "--stop-file", str(tmp_path / "stop")],
    )
    return results


def test_control_tower_reselects_second_task_against_new_head(monkeypatch, tmp_path, capsys):
    tasks = [_task("task-1"), _task("task-2")]
    head = {"sha": "a" * 40}
    results = _prepare_selector_main(monkeypatch, tmp_path, tasks, head_reader=lambda: head["sha"])
    monkeypatch.setattr(
        loop.sys,
        "argv",
        ["loop", "--max-tasks", "2", "--results", str(results),
         "--state", str(tmp_path / "state.json"), "--stop-file", str(tmp_path / "stop")],
    )
    monkeypatch.setattr(
        "scripts.control_tower_loop_adapter.authorize_registered_task",
        lambda task, catalog, sha: (True, "authorized"),
    )
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda _root, expected_sha: {"gate": "PASS", "target_sha": expected_sha},
    )
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.rea_evidence_is_valid_pass",
        lambda evidence, expected_sha: evidence.get("gate") == "PASS" and evidence.get("target_sha") == expected_sha,
    )
    monkeypatch.setattr(
        "scripts.recovery_ai_loop_adapter.record_loop_outcome",
        lambda _path, result: {"recorded": True, "task_id": result["task_id"]},
    )
    monkeypatch.setattr(
        "scripts.control_tower_loop_observer.record_loop_observation",
        lambda _path, result: {"recorded": True, "task_id": result["task_id"], "proposal_executable": False},
    )
    monkeypatch.setattr(
        "scripts.control_tower_orchestrator.coordinate_outcome",
        lambda _result: {"phase": "CONTINUE", "next_action": "CONTINUE", "reason_code": "test_pass", "allow_continue": True, "repair_executed": False},
    )

    def fake_run_task(task, index, _stop_file, *, expected_base_sha=None):
        if index == 1:
            head["sha"] = "b" * 40
            return {
                "timestamp": "2026-10-21T00:00:00+00:00",
                "run_index": index, "task_id": task["id"], "status": "PASS", "exit_code": 0,
                "base_sha": expected_base_sha, "produced_sha": head["sha"], "failure_reason": "",
            }
        return {
            "timestamp": "2026-10-21T00:00:01+00:00",
            "run_index": index, "task_id": task["id"], "status": "NO_CHANGE", "exit_code": 0,
            "base_sha": expected_base_sha, "produced_sha": head["sha"], "failure_reason": "no_change",
        }

    monkeypatch.setattr(loop, "run_task", fake_run_task)
    assert loop.main() == 0
    assert "MINIMAL_LOOP=COMPLETE" in capsys.readouterr().out
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert [row["task_id"] for row in rows] == ["task-1", "task-2"]
    assert [row["base_sha"] for row in rows] == ["a" * 40, "b" * 40]
    assert [row["produced_sha"] for row in rows] == ["b" * 40, "b" * 40]
    assert [row["rea"]["target_sha"] for row in rows] == ["a" * 40, "b" * 40]


def test_control_tower_duplicate_queue_ids_block_before_execution(monkeypatch, tmp_path, capsys):
    task = _task("duplicate-task")
    results = _prepare_selector_main(monkeypatch, tmp_path, [task, dict(task)])
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 80
    assert "control_tower_selector:duplicate_task" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "control_tower_selector:duplicate_task"
    assert row["task_count"] == 0


def test_control_tower_head_change_during_selection_blocks_before_execution(monkeypatch, tmp_path, capsys):
    task = _task("head-change-task")
    heads = iter(["a" * 40, "b" * 40])
    results = _prepare_selector_main(monkeypatch, tmp_path, [task], lambda: next(heads))
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 80
    assert "control_tower_selector:policy_blocked" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "control_tower_selector:policy_blocked"
    assert row["task_count"] == 0


def test_registered_catalog_is_loaded_from_versioned_catalogs_not_runtime_queue(monkeypatch):
    queue_task = _task("queue-only-injected-task")
    trusted_task = {
        "id": "catalog-task",
        "instruction": "reviewed instruction",
        "allowed_paths": ["tests/test_loop_not_run_and_evidence.py"],
    }
    payloads = {
        ".github/autonomous-loop-tasks.json": json.dumps({"tasks": [queue_task]}),
        ".github/autonomous-loop-task-catalog.json": json.dumps({"tasks": [trusted_task]}),
    }
    requested_paths = []

    def fake_git_checked(*args):
        assert args[0] == "show"
        revision, path = args[1].split(":", 1)
        assert revision == "a" * 40
        requested_paths.append(path)
        return (0, payloads[path])

    monkeypatch.setattr(loop, "_git_checked", fake_git_checked)
    catalog = loop._load_registered_catalog("a" * 40)
    assert catalog == [trusted_task]
    assert queue_task["id"] not in {entry["id"] for entry in catalog}
    assert requested_paths == [".github/autonomous-loop-task-catalog.json"]


def test_registered_catalog_fails_closed_when_versioned_catalog_is_unavailable(monkeypatch):
    monkeypatch.setattr(loop, "_git_checked", lambda *args: (1, ""))
    with pytest.raises(ValueError, match="catalog unavailable"):
        loop._load_registered_catalog("a" * 40)



def test_control_tower_head_change_immediately_before_launch_blocks(monkeypatch, tmp_path, capsys):
    task = _task("launch-head-race")
    heads = iter(["a" * 40, "a" * 40, "b" * 40])
    results = _prepare_selector_main(monkeypatch, tmp_path, [task], lambda: next(heads))
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run after HEAD changes"))
    assert loop.main() == 80
    assert "selection_head_changed" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "control_tower_gate:selection_head_changed"


def test_recovery_ai_hold_appearing_before_launch_blocks(monkeypatch, tmp_path, capsys):
    task = _task("hold-race-task")
    results = _prepare_selector_main(monkeypatch, tmp_path, [task])

    class _ChangingRecoveryStore:
        calls = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def _read(self):
            return {"schema_version": 1, "tasks": {}, "checkpoint": None}

        def task_status(self, _task_id):
            type(self).calls += 1
            # Initial selection sees no hold; launch-time recheck sees HOLD.
            return {"held": type(self).calls >= 2}

    monkeypatch.setattr("scripts.recovery_ai.RecoveryStore", _ChangingRecoveryStore)
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run while held"))
    assert loop.main() == 80
    assert "recovery_ai_hold_or_status_uncertain" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "recovery_ai_hold_or_status_uncertain"


@pytest.mark.parametrize("recovery_record", [{"consecutive_failures": 1}, {"held": "false"}])
def test_malformed_recovery_state_blocks_before_execution(monkeypatch, tmp_path, recovery_record, capsys):
    task = _task("malformed-recovery-state")
    results = _prepare_selector_main(monkeypatch, tmp_path, [task])

    class _MalformedRecoveryStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def _read(self):
            return {"schema_version": 1, "tasks": {}, "checkpoint": None}

        def task_status(self, _task_id):
            return dict(recovery_record)

    monkeypatch.setattr("scripts.recovery_ai.RecoveryStore", _MalformedRecoveryStore)
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run with ambiguous recovery state"))
    assert loop.main() == 80
    assert "control_tower_recovery_state:unavailable_or_invalid" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    assert row["failure_reason"] == "control_tower_recovery_state:unavailable_or_invalid"


def test_recovery_state_error_records_blocked_evidence_before_execution(monkeypatch, tmp_path, capsys):
    task = _task("recovery-store-error")
    results = _prepare_selector_main(monkeypatch, tmp_path, [task])

    class _BrokenRecoveryStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def _read(self):
            return {"schema_version": 1, "tasks": {}, "checkpoint": None}

        def task_status(self, _task_id):
            raise ValueError("malformed recovery state")

    monkeypatch.setattr("scripts.recovery_ai.RecoveryStore", _BrokenRecoveryStore)
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run"))
    assert loop.main() == 80
    assert "control_tower_recovery_state:unavailable_or_invalid" in capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    assert row["task_count"] == 0
    assert row["failure_reason"] == "control_tower_recovery_state:unavailable_or_invalid"


@pytest.mark.parametrize("action", ["NOT_RUN", "HOLD"])
def test_control_tower_nonselect_action_with_executable_task_blocks(monkeypatch, tmp_path, action, capsys):
    task = _task("unexpected-nonselect-task")
    results = _prepare_selector_main(monkeypatch, tmp_path, [task])

    from core.control_tower_decision import ControlTowerDecisionRecord
    monkeypatch.setattr(
        "core.control_tower_selector.select_next_task",
        lambda *a, **k: ControlTowerDecisionRecord(
            reason_code="no_eligible_task",
            confidence=1.0,
            priority=0,
            next_action=action,
            gate_status="NOT_RUN" if action == "NOT_RUN" else "BLOCKED",
            evidence_sha="a" * 40,
        ),
    )
    monkeypatch.setattr(loop, "run_task", lambda *a, **k: pytest.fail("must not run for nonselect action"))
    assert loop.main() == 80
    output = capsys.readouterr().out
    row = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert row["status"] == "BLOCKED"
    if action == "NOT_RUN":
        assert "action_task_mismatch" in output
        assert row["failure_reason"] == "control_tower_selector:action_task_mismatch"
    else:
        # A BLOCKED gate is rejected earlier than action/task consistency checks.
        assert "control_tower_selector:no_eligible_task" in output
        assert row["failure_reason"] == "control_tower_selector:no_eligible_task"
