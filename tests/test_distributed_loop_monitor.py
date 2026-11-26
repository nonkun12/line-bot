import base64
import hashlib
import json
import unittest
import os
import sys
import tempfile
from unittest.mock import patch

from scripts.distributed_loop_monitor import evaluate


def valid_state():
    return {
        "version": 1,
        "completed": [],
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {},
            "checkpoint": None,
            "state_updated_at": "2026-11-13T23:30:00Z",
        },
    }


def contents_response(state=None):
    raw = json.dumps(valid_state() if state is None else state, separators=(",", ":")).encode()
    blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return {
        "encoding": "base64",
        "content": base64.b64encode(raw).decode(),
        "sha": blob_sha,
    }


def valid_meta(response=None):
    response = contents_response() if response is None else response
    return {
        "branch_tip_sha": "b" * 40,
        "state_commit_sha": "b" * 40,
        "state_commit_timestamp": "2026-11-13T23:30:00Z",
        "contents_blob_sha": response["sha"],
    }


def valid_runs():
    return {"workflow_runs": []}

def main_run(**overrides):
    run = {
        "id": 9001,
        "run_number": 10,
        "run_attempt": 1,
        "workflow_id": 357086091,
        "event": "workflow_dispatch",
        "status": "in_progress",
        "conclusion": None,
        "created_at": "2026-11-13T23:59:00Z",
        "run_started_at": "2026-11-13T23:59:00Z",
    }
    run.update(overrides)
    return run


class DistributedLoopMonitorTests(unittest.TestCase):
    def evaluate(self, runs=None, state=None, meta=None, response=None):
        state = valid_state() if state is None else state
        response = contents_response(state) if response is None else response
        return evaluate(
            valid_runs() if runs is None else runs,
            state,
            run_id="123",
            head_sha="a" * 40,
            started_at="2026-11-14T00:00:00Z",
            state_meta=valid_meta(response) if meta is None else meta,
            state_response=response,
        )

    def test_blocked_main_writes_report_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runs_path = f"{directory}/runs.json"
            state_path = f"{directory}/state.json"
            meta_path = f"{directory}/meta.json"
            output_path = f"{directory}/report.json"
            with open(runs_path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            argv = [
                "distributed_loop_monitor.py",
                "--runs-json", runs_path,
                "--state-json", state_path,
                "--state-meta-json", meta_path,
                "--output", output_path,
            ]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}):
                from scripts.distributed_loop_monitor import main
                self.assertEqual(main(), 1)
            with open(output_path, encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIs(report["dispatch_allowed"], False)

    def test_valid_state_provenance_passes_but_missing_main_loop_evidence_blocks(self):
        report = self.evaluate()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("No Main LOOP run found", report["failure_reason"])
        self.assertIs(report["dispatch_allowed"], False)
        self.assertEqual(report["checks"]["state_provenance"]["status"], "PASS")
        self.assertEqual(report["checks"]["main_loop_activity"]["outcome"], "NO_CHANGE")
        self.assertEqual(report["checks"]["queue_and_approval"]["status"], "NOT_EVALUATED")

    def test_missing_actions_evidence_blocks(self):
        report = self.evaluate(runs={})
        self.assertEqual(report["status"], "BLOCKED")

    def test_paginated_actions_pages_are_flattened(self):
        pages = [
            {"workflow_runs": [
                main_run(),
                {"workflow_id": 111111111, "status": "completed"},
            ]},
            {"workflow_runs": [
                {"workflow_id": 222222222, "status": "queued"},
            ]},
        ]
        report = self.evaluate(runs=pages)
        activity = report["checks"]["main_loop_activity"]
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(activity["status"], "PASS")
        self.assertEqual(activity["active_run_count"], 1)
        self.assertIs(report["dispatch_allowed"], False)

    def test_malformed_paginated_actions_page_blocks(self):
        pages = [
            {"workflow_runs": [{"workflow_id": 357086091, "status": "in_progress"}]},
            {"workflow_runs": "not-a-list"},
        ]
        report = self.evaluate(runs=pages)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["actions_api"]["status"], "BLOCKED")
        self.assertEqual(report["checks"]["main_loop_activity"]["outcome"], "UNVERIFIED")
        self.assertIs(report["dispatch_allowed"], False)

    def test_missing_recovery_schema_blocks(self):
        report = self.evaluate(state={"version": 1})
        self.assertEqual(report["status"], "BLOCKED")

    def test_missing_state_metadata_blocks(self):
        report = self.evaluate(meta={})
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["state_provenance"]["status"], "BLOCKED")

    def test_state_blob_sha_mismatch_blocks(self):
        response = contents_response()
        meta = valid_meta(response)
        meta["contents_blob_sha"] = "c" * 40
        self.assertEqual(self.evaluate(meta=meta, response=response)["status"], "BLOCKED")

    def test_state_branch_tip_and_pinned_commit_must_match(self):
        response = contents_response()
        meta = valid_meta(response)
        meta["state_commit_sha"] = "d" * 40
        self.assertEqual(self.evaluate(meta=meta, response=response)["status"], "BLOCKED")

    def test_stale_state_blocks(self):
        response = contents_response()
        meta = valid_meta(response)
        meta["state_commit_timestamp"] = "2026-11-12T22:00:00Z"
        self.assertEqual(self.evaluate(meta=meta, response=response)["status"], "BLOCKED")

    def test_null_checkpoint_is_valid_initial_state_but_missing_run_evidence_blocks(self):
        report = self.evaluate()
        self.assertEqual(report["checks"]["recovery_schema"]["status"], "PASS")
        self.assertIsNone(valid_state()["recovery_ai"]["checkpoint"])
        self.assertEqual(report["checks"]["main_loop_activity"]["status"], "INFO")
        self.assertEqual(report["checks"]["main_loop_activity"]["outcome"], "NO_CHANGE")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIs(report["dispatch_allowed"], False)

    def test_unverified_checkpoint_blocks(self):
        state = valid_state()
        state["recovery_ai"]["checkpoint"] = {
            "task_id": "task-1", "checkpoint_id": "cp-1",
            "verified": False, "saved_at": "2026-11-13T23:00:00Z",
        }
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_held_task_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = {"held": True}
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_pending_resume_review_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = {
            "held": False, "resume_requires_review": True
        }
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_malformed_task_flag_type_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = {"held": "false"}
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_malformed_task_record_blocks(self):
        state = valid_state()
        state["recovery_ai"]["tasks"]["task-1"] = "invalid"
        self.assertEqual(self.evaluate(state=state)["status"], "BLOCKED")

    def test_active_main_run_is_identified_by_fixed_workflow_id_not_name(self):
        runs = {"workflow_runs": [
            main_run(name="Renamed workflow must still be identified by ID")
        ]}
        report = self.evaluate(runs=runs)
        activity = report["checks"]["main_loop_activity"]
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(activity["status"], "PASS")
        self.assertEqual(activity["outcome"], "ACTIVE")
        self.assertEqual(activity["workflow_id"], 357086091)
        self.assertEqual(activity["active_run_count"], 1)
        self.assertIs(report["dispatch_allowed"], False)

    def test_zero_active_main_runs_is_info_no_change(self):
        report = self.evaluate(runs={"workflow_runs": []})
        activity = report["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "INFO")
        self.assertEqual(activity["outcome"], "NO_CHANGE")
        self.assertEqual(activity["active_run_count"], 0)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("No Main LOOP run found", report["failure_reason"])
        self.assertIs(report["dispatch_allowed"], False)

    def test_completed_main_run_is_not_reported_as_active(self):
        runs = {"workflow_runs": [
            main_run(status="completed", conclusion="success", created_at="2026-11-13T23:58:00Z")
        ]}
        activity = self.evaluate(runs=runs)["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "PASS")
        self.assertEqual(activity["outcome"], "WORKFLOW_SUCCESS")
        self.assertEqual(activity["active_run_count"], 0)

    def test_unrelated_active_workflow_is_not_counted_as_main_loop(self):
        runs = {"workflow_runs": [{
            "workflow_id": 999999999,
            "name": "Some other active workflow",
            "status": "in_progress",
        }]}
        activity = self.evaluate(runs=runs)["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "INFO")
        self.assertEqual(activity["outcome"], "NO_CHANGE")
        self.assertEqual(activity["active_run_count"], 0)

    def test_missing_or_invalid_workflow_id_blocks(self):
        invalid_records = [
            {"status": "in_progress"},
            {"workflow_id": 0, "status": "in_progress"},
            {"workflow_id": True, "status": "in_progress"},
            {"workflow_id": "357086091", "status": "in_progress"},
        ]
        for record in invalid_records:
            with self.subTest(record=record):
                report = self.evaluate(runs={"workflow_runs": [record]})
                self.assertEqual(report["status"], "BLOCKED")
                self.assertEqual(report["checks"]["actions_api"]["status"], "BLOCKED")
                self.assertEqual(report["checks"]["main_loop_activity"]["status"], "BLOCKED")
                self.assertEqual(report["checks"]["main_loop_activity"]["outcome"], "UNVERIFIED")
                self.assertIs(report["dispatch_allowed"], False)


    def test_missing_recovery_update_timestamp_blocks(self):
        state = valid_state()
        del state["recovery_ai"]["state_updated_at"]
        report = self.evaluate(state=state)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["recovery_freshness"]["status"], "BLOCKED")


    def test_stale_recovery_update_timestamp_blocks_even_if_outer_commit_is_fresh(self):
        state = valid_state()
        state["recovery_ai"]["state_updated_at"] = "2026-11-12T00:00:00Z"
        report = self.evaluate(state=state)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["recovery_freshness"]["status"], "BLOCKED")


    def test_future_recovery_update_timestamp_blocks(self):
        state = valid_state()
        state["recovery_ai"]["state_updated_at"] = "2026-11-14T00:10:00Z"
        report = self.evaluate(state=state)
        self.assertEqual(report["status"], "BLOCKED")


    def test_newer_failure_is_not_masked_by_older_success(self):
        older = main_run(id=100, run_number=1, status="completed", conclusion="success",
                         created_at="2026-11-13T22:00:00Z")
        newer = main_run(id=101, run_number=2, status="completed", conclusion="failure",
                         created_at="2026-11-13T23:00:00Z")
        report = self.evaluate(runs={"workflow_runs": [older, newer]})
        activity = report["checks"]["main_loop_activity"]
        self.assertEqual(activity["latest_run_id"], 101)
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIs(report["dispatch_allowed"], False)

    def test_latest_attempt_is_selected_for_same_run_id(self):
        first = main_run(id=200, run_attempt=1, status="completed", conclusion="success")
        retry = main_run(id=200, run_attempt=2, status="completed", conclusion="failure")
        activity = self.evaluate(runs={"workflow_runs": [first, retry]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["latest_run_attempt"], 2)
        self.assertEqual(activity["status"], "BLOCKED")

    def test_same_attempt_conflicting_created_at_blocks(self):
        first = main_run(id=250, created_at="2026-11-13T23:58:00Z")
        conflicting = main_run(id=250, created_at="2026-11-13T23:57:00Z")
        activity = self.evaluate(runs={"workflow_runs": [first, conflicting]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")
        self.assertIn("conflicting records", activity["detail"])

    def test_older_attempt_conflict_is_detected_after_newer_attempt(self):
        first_attempt = main_run(id=252, run_attempt=1, run_number=10)
        newer_attempt = main_run(id=252, run_attempt=2, run_number=10)
        conflicting_old_attempt = main_run(
            id=252, run_attempt=1, run_number=11,
        )
        activity = self.evaluate(runs={"workflow_runs": [
            first_attempt, newer_attempt, conflicting_old_attempt
        ]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")
        self.assertIn("conflicting records", activity["detail"])

    def test_same_attempt_conflicting_run_number_blocks(self):
        first = main_run(id=251, run_number=10)
        conflicting = main_run(id=251, run_number=11)
        activity = self.evaluate(runs={"workflow_runs": [first, conflicting]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")
        self.assertIn("conflicting records", activity["detail"])

    def test_multiple_active_runs_block_as_overlap(self):
        first = main_run(id=301, created_at="2026-11-13T23:57:00Z")
        second = main_run(id=302, created_at="2026-11-13T23:58:00Z", event="schedule")
        activity = self.evaluate(runs={"workflow_runs": [first, second]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["outcome"], "OVERLAP")
        self.assertEqual(activity["status"], "BLOCKED")

    def test_stale_queued_schedule_blocks(self):
        queued = main_run(status="queued", event="schedule", created_at="2026-11-13T22:00:00Z")
        activity = self.evaluate(runs={"workflow_runs": [queued]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["outcome"], "STALE_QUEUED")
        self.assertEqual(activity["status"], "BLOCKED")

    def test_skipped_run_is_not_execution_success(self):
        skipped = main_run(status="completed", conclusion="skipped")
        activity = self.evaluate(runs={"workflow_runs": [skipped]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["outcome"], "NOT_EXECUTED")
        self.assertEqual(activity["status"], "INFO")

    def test_successful_workflow_does_not_claim_task_execution_evidence(self):
        succeeded = main_run(status="completed", conclusion="success")
        report = self.evaluate(runs={"workflow_runs": [succeeded]})
        self.assertEqual(report["checks"]["task_execution_evidence"]["status"], "NOT_EVALUATED")
        self.assertIn("task-level result", report["checks"]["main_loop_activity"]["detail"])


    def test_push_event_is_valid_but_skipped_is_not_execution(self):
        skipped = main_run(status="completed", conclusion="skipped", event="push")
        activity = self.evaluate(runs={"workflow_runs": [skipped]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "INFO")
        self.assertEqual(activity["outcome"], "NOT_EXECUTED")

    def test_missing_run_attempt_metadata_blocks(self):
        incomplete = main_run()
        del incomplete["run_attempt"]
        activity = self.evaluate(runs={"workflow_runs": [incomplete]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")


    def test_stale_in_progress_run_blocks(self):
        running = main_run(status="in_progress", created_at="2026-11-13T22:00:00Z", run_started_at="2026-11-13T22:00:00Z")
        activity = self.evaluate(runs={"workflow_runs": [running]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["outcome"], "STALE_IN_PROGRESS")
        self.assertEqual(activity["status"], "BLOCKED")

    def test_future_created_at_blocks(self):
        future = main_run(created_at="2026-11-14T00:10:00Z")
        activity = self.evaluate(runs={"workflow_runs": [future]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")
        self.assertIn("created_at is too far in the future", activity["detail"])

    def test_future_run_started_at_blocks(self):
        future = main_run(run_started_at="2026-11-14T00:10:00Z")
        activity = self.evaluate(runs={"workflow_runs": [future]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertIn("run_started_at is too far in the future", activity["detail"])

    def test_run_started_before_created_at_beyond_skew_tolerance_blocks(self):
        run = main_run(
            created_at="2026-11-13T23:59:00Z",
            run_started_at="2026-11-13T23:53:59Z",
        )
        activity = self.evaluate(runs={"workflow_runs": [run]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "UNVERIFIED")
        self.assertIn("earlier than created_at", activity["detail"])

    def test_run_started_before_created_at_within_skew_tolerance_is_allowed(self):
        run = main_run(
            created_at="2026-11-13T23:59:00Z",
            run_started_at="2026-11-13T23:55:00Z",
        )
        activity = self.evaluate(runs={"workflow_runs": [run]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "PASS")
        self.assertEqual(activity["outcome"], "ACTIVE")

    def test_missing_or_invalid_run_started_at_blocks_in_progress(self):
        for value in (None, "not-a-timestamp"):
            with self.subTest(value=value):
                run = main_run(run_started_at=value)
                activity = self.evaluate(runs={"workflow_runs": [run]})["checks"]["main_loop_activity"]
                self.assertEqual(activity["status"], "BLOCKED")
                self.assertEqual(activity["outcome"], "UNVERIFIED")
                self.assertIn("run_started_at", activity["detail"])

    def test_long_queue_wait_does_not_make_recently_started_run_stale(self):
        run = main_run(
            created_at="2026-11-13T22:00:00Z",
            run_started_at="2026-11-13T23:59:00Z",
        )
        activity = self.evaluate(runs={"workflow_runs": [run]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "PASS")
        self.assertEqual(activity["outcome"], "ACTIVE")

    def test_run_started_more_than_fifty_minutes_ago_blocks(self):
        run = main_run(
            created_at="2026-11-13T23:00:00Z",
            run_started_at="2026-11-13T22:59:59Z",
        )
        activity = self.evaluate(runs={"workflow_runs": [run]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "BLOCKED")
        self.assertEqual(activity["outcome"], "STALE_IN_PROGRESS")
        self.assertIn("active for 3601s", activity["detail"])

    def test_completed_run_without_conclusion_blocks(self):
        incomplete = main_run(status="completed", conclusion=None)
        activity = self.evaluate(runs={"workflow_runs": [incomplete]})["checks"]["main_loop_activity"]
        self.assertEqual(activity["outcome"], "FAILED")
        self.assertEqual(activity["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

