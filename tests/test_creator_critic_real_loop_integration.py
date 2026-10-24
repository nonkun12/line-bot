import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import core.control_tower_selector as selector
from scripts import (
    control_tower_loop_adapter,
    control_tower_loop_observer,
    control_tower_orchestrator,
    rea_control_tower_adapter,
    recovery_ai_loop_adapter,
    run_minimal_autonomous_loop as loop,
)
from scripts.recovery_ai import RecoveryStore
from scripts.run_creator_critic_loop_advisory import run_advisory


class CreatorCriticRealLoopIntegrationTests(unittest.TestCase):
    """Exercise the real loop result writer and advisory dispatch in a sandbox."""

    def test_real_loop_failure_row_triggers_advisory_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {
                "id": "creator-critic-failure-smoke",
                "instruction": "isolated fixture; never launched",
                "allowed_paths": ["tests/test_placeholder.py"],
            }
            queue = root / "queue.json"
            queue.write_text(
                json.dumps({"max_tasks_per_run": 1, "tasks": [task]}),
                encoding="utf-8",
            )
            results = root / "minimal-autonomous-loop.jsonl"
            state = root / "autonomous-loop-state.json"
            output = root / "artifacts" / "creator-critic-github" / "latest.json"
            base_sha = "a" * 40
            run_nonce = "b" * 32

            failed_result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_index": 1,
                "task_id": task["id"],
                "run_nonce": run_nonce,
                "status": "FAIL",
                "exit_code": 1,
                "base_sha": base_sha,
                "produced_sha": base_sha,
                "failure_reason": "task_runtime_failed",
            }
            rea = {
                "gate": "PASS",
                "mode": "OBSERVE_ONLY",
                "target_sha": base_sha,
                "critical_count": 0,
                "blocking_count": 0,
                "execution_authorized": False,
                "patch_authorized": False,
                "hold_clear_authorized": False,
                "merge_deploy_authorized": False,
                "scanner_status": "PASS",
                "finding_count": 0,
                "findings_truncated": False,
                "findings": [],
            }

            patches = [
                patch.object(loop, "QUEUE", queue),
                patch.object(loop, "load_completed", return_value=set()),
                patch.object(loop, "load_tasks", return_value=[task]),
                patch.object(loop, "_git_head", return_value=base_sha),
                patch.object(loop, "_load_registered_catalog", return_value=[task]),
                patch.object(loop, "run_task", return_value=dict(failed_result)),
                patch.object(loop.signal, "signal"),
                patch.object(
                    loop.sys,
                    "argv",
                    [
                        "run_minimal_autonomous_loop.py",
                        "--max-tasks", "1",
                        "--stop-file", str(root / "stop"),
                        "--results", str(results),
                        "--state", str(state),
                    ],
                ),
                patch.object(RecoveryStore, "task_status", return_value={}),
                patch.object(
                    selector,
                    "select_next_task",
                    return_value=SimpleNamespace(
                        next_action="SELECT_REGISTERED_TASK",
                        task_template_id=task["id"],
                        reason_code="selected",
                    ),
                ),
                patch.object(
                    control_tower_loop_adapter,
                    "authorize_registered_task",
                    return_value=(True, "authorized"),
                ),
                patch.object(
                    rea_control_tower_adapter,
                    "prepare_rea_evidence",
                    side_effect=lambda _root, expected_sha: {**rea, "target_sha": expected_sha},
                ),
                patch.object(rea_control_tower_adapter, "rea_evidence_is_valid_pass", return_value=True),
                patch.object(
                    recovery_ai_loop_adapter,
                    "record_loop_outcome",
                    side_effect=lambda _path, row: {
                        "recorded": True,
                        "verified": True,
                        "status": row["status"],
                        "evidence": {
                            "task_id": row["task_id"],
                            "base_sha": base_sha,
                            "produced_sha": base_sha,
                            "run_nonce": run_nonce,
                        },
                    },
                ),
                patch.object(
                    control_tower_loop_observer,
                    "record_loop_observation",
                    side_effect=lambda _path, row: {
                        "recorded": True,
                        "observed_status": row["status"],
                        "proposal_executable": False,
                    },
                ),
                patch.object(
                    control_tower_orchestrator,
                    "coordinate_outcome",
                    return_value={
                        "phase": "STOP",
                        "next_action": "STOP_AND_REPORT",
                        "reason_code": "task_failed",
                        "allow_continue": False,
                        "repair_executed": False,
                    },
                ),
                patch.dict(os.environ, {"CONTROL_TOWER_KILL_SWITCH": "false"}),
            ]
            entered = []
            try:
                for patcher in patches:
                    entered.append(patcher)
                    patcher.start()

                # This executes the actual distributed-loop entry point; only
                # the task launch and external persistence adapters are stubbed.
                self.assertEqual(loop.main(), 1)
            finally:
                for patcher in reversed(entered):
                    patcher.stop()

            rows = [
                json.loads(line)
                for line in results.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "FAIL")
            self.assertEqual(rows[0]["task_id"], task["id"])
            self.assertEqual(rows[0]["failure_reason"], "task_runtime_failed")
            self.assertFalse(rows[0]["control_tower"]["orchestration"]["allow_continue"])

            # Run the real advisory dispatcher while faking only pip/model
            # execution. This validates the complete result-file contract and
            # confirms the smoke test never downloads or loads a model.
            calls = []
            transcript = {
                "status": "DISCUSSION_ONLY",
                "evidence_status": "NOT_MEASURED",
                "source_changes": False,
                "merge_or_deploy": False,
                "transcript": [
                    {"role": "creator", "content": "Bounded proposal"},
                    {"role": "critic", "content": "HOLD: more evidence needed"},
                ],
            }

            def fake_run(command, check=False, **kwargs):
                calls.append((command, check, kwargs))
                if "-m" in command and "pip" in command:
                    return subprocess.CompletedProcess(command, 0)
                output_path = Path(command[command.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(transcript) + "\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            self.assertEqual(
                run_advisory(
                    results,
                    output,
                    runner_path=root / "fake-model-runner.py",
                    run=fake_run,
                ),
                0,
            )
            self.assertEqual(len(calls), 2)
            objective = calls[1][0][calls[1][0].index("--objective") + 1]
            self.assertIn(f"task_id={task['id']}", objective)
            self.assertIn("status=FAIL", objective)
            self.assertIn("<untrusted_loop_observation>", objective)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), transcript)
            self.assertFalse((root / "recovery-ai-state.json").exists())
            self.assertFalse((root / "control-tower-observations.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
