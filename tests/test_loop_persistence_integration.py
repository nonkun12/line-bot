"""Synthetic integration coverage for durable loop outcome adapters.

This test uses a dummy outcome and temporary files; it does not launch a task,
call external services, or exercise the production task subprocess.
"""
import json

from scripts.control_tower_loop_observer import record_loop_observation
from scripts.recovery_ai import RecoveryStore
from scripts.recovery_ai_loop_adapter import record_loop_outcome
from scripts.run_minimal_autonomous_loop import classify_final_outcome


def test_synthetic_success_persists_both_adapters_before_final_classification(tmp_path):
    recovery_path = tmp_path / "recovery.json"
    observation_path = tmp_path / "control-tower.jsonl"
    outcome = {
        "task_id": "synthetic-integration-task",
        "status": "PASS",
        "exit_code": 0,
        "failure_reason": "",
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "run_nonce": "c" * 32,
    }

    recovery = record_loop_outcome(recovery_path, outcome)
    observation = record_loop_observation(observation_path, outcome)

    # Reload persisted evidence from disk rather than trusting return values alone.
    persisted_evidence = RecoveryStore(recovery_path).task_status(
        "synthetic-integration-task"
    )["last_success_evidence"]
    observation_rows = [
        json.loads(line)
        for line in observation_path.read_text(encoding="utf-8").splitlines()
    ]

    assert recovery["recorded"] is True
    assert recovery["verified"] is True
    assert persisted_evidence == {
        "task_id": "synthetic-integration-task",
        "base_sha": "a" * 40,
        "produced_sha": "b" * 40,
        "run_nonce": "c" * 32,
    }
    assert observation["recorded"] is True
    assert len(observation_rows) == 1
    assert observation_rows[0]["task_id"] == "synthetic-integration-task"
    assert observation_rows[0]["status"] == "PASS"

    final_status = classify_final_outcome(
        [outcome["status"]],
        loop_outcome="success",
        publish_outcome="success",
        state_outcome="success" if observation["recorded"] else "failure",
        sheets_outcome="success",
        recovery_outcome="success" if recovery["verified"] else "failure",
    )
    assert final_status == ("COMPLETED", "required_gates_passed")
