import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.run_creator_critic_loop_advisory import DEPENDENCIES, run_advisory


class CreatorCriticLoopWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root / "loop.jsonl"
        self.output = self.root / "artifacts" / "creator-critic-github" / "latest.json"
        self.runner = self.root / "fake_model_runner.py"

    def write_results(self, *rows):
        self.results.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def fake_run(self, *, inference_report=None, install_code=0, inference_code=0):
        calls = []

        def run(command, check=False, **kwargs):
            calls.append((command, check, kwargs))
            if "-m" in command and "pip" in command:
                return subprocess.CompletedProcess(command, install_code)
            if inference_report is not None:
                output_path = Path(command[command.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(inference_report) + "\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, inference_code)

        return run, calls

    def test_failure_triggers_pinned_inference_and_creates_artifact_only(self):
        self.write_results({
            "task_id": "task-123",
            "status": "FAIL",
            "failure_reason": "test failure",
            "control_tower": {"orchestration": {"repair_executed": False}},
        })
        report = {
            "status": "DISCUSSION_ONLY",
            "evidence_status": "NOT_MEASURED",
            "source_changes": False,
            "merge_or_deploy": False,
            "transcript": [
                {"role": "creator", "content": "Proposal"},
                {"role": "critic", "content": "HOLD: evidence is missing."},
            ],
        }
        run, calls = self.fake_run(inference_report=report)
        state_file = self.root / "queue-and-approval-state.json"
        state_file.write_text('{"hold": true, "approved": false}\n', encoding="utf-8")
        before_state = state_file.read_bytes()

        rc = run_advisory(
            self.results, self.output, runner_path=self.runner,
            python_executable="python-test", run=run,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2, "failure should install dependencies and invoke two-round inference")
        self.assertEqual(tuple(calls[0][0][-2:]), DEPENDENCIES)
        self.assertEqual(calls[0][2]["env"]["CMAKE_ARGS"], "-DGGML_NATIVE=OFF")
        inference = calls[1][0]
        self.assertIn("--rounds", inference)
        self.assertEqual(inference[inference.index("--rounds") + 1], "2")
        objective = inference[inference.index("--objective") + 1]
        self.assertIn("status=FAIL", objective)
        self.assertIn("<untrusted_loop_observation>", objective)
        self.assertTrue(self.output.is_file(), "mock inference should emit the transcript artifact")
        saved = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "DISCUSSION_ONLY")
        self.assertFalse(saved["source_changes"])
        self.assertFalse(saved["merge_or_deploy"])
        self.assertIn("HOLD", saved["transcript"][1]["content"])
        self.assertEqual(state_file.read_bytes(), before_state, "HOLD must never be interpreted as permission to mutate state")

    def test_success_skips_dependency_install_and_inference(self):
        self.write_results({"task_id": "task-ok", "status": "PASS", "exit_code": 0})
        self.output.parent.mkdir(parents=True)
        self.output.write_text('{"status":"stale"}\n', encoding="utf-8")
        run, calls = self.fake_run()

        rc = run_advisory(self.results, self.output, runner_path=self.runner, run=run)

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertFalse(self.output.exists(), "stale artifact must not be uploaded")

    def test_empty_queue_skips_dependency_install_and_inference(self):
        self.results.write_text("", encoding="utf-8")
        run, calls = self.fake_run()

        rc = run_advisory(self.results, self.output, runner_path=self.runner, run=run)

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertFalse(self.output.exists())

    def test_repair_signal_triggers_inference_even_when_task_passed(self):
        self.write_results({
            "task_id": "task-repaired",
            "status": "PASS",
            "control_tower": {"orchestration": {"repair_executed": True}},
        })
        run, calls = self.fake_run(inference_report={"status": "DISCUSSION_ONLY", "transcript": []})

        rc = run_advisory(self.results, self.output, runner_path=self.runner, run=run)

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("repair_executed=True", calls[1][0][calls[1][0].index("--objective") + 1])

    def test_dependency_install_failure_does_not_start_inference(self):
        self.write_results({"task_id": "task-failed", "status": "FAIL"})
        run, calls = self.fake_run(install_code=1)

        rc = run_advisory(self.results, self.output, runner_path=self.runner, run=run)

        self.assertEqual(rc, 2)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.output.exists())

    def test_inference_failure_is_reported_and_does_not_create_artifact(self):
        self.write_results({"task_id": "task-failed", "status": "FAIL"})
        run, calls = self.fake_run(inference_code=2)

        rc = run_advisory(self.results, self.output, runner_path=self.runner, run=run)

        self.assertEqual(rc, 2)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output.exists())

    def test_module_cli_import_and_empty_queue_skip_without_installing(self):
        self.results.write_text("", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_creator_critic_loop_advisory",
                "--results",
                str(self.results),
                "--output",
                str(self.output),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CREATOR_CRITIC_ADVISORY=SKIP", completed.stdout)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
