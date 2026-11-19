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

    def test_valid_state_provenance_passes_but_never_dispatches(self):
        report = self.evaluate()
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["dispatch_allowed"], False)
        self.assertEqual(report["checks"]["state_provenance"]["status"], "PASS")
        self.assertEqual(report["checks"]["queue_and_approval"]["status"], "NOT_EVALUATED")

    def test_missing_actions_evidence_blocks(self):
        report = self.evaluate(runs={})
        self.assertEqual(report["status"], "BLOCKED")

    def test_paginated_actions_pages_are_flattened(self):
        pages = [
            {"workflow_runs": [
                {"workflow_id": 357086091, "status": "in_progress"},
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

    def test_null_checkpoint_is_valid_initial_state(self):
        self.assertEqual(self.evaluate()["status"], "PASS")

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
        runs = {"workflow_runs": [{
            "workflow_id": 357086091,
            "name": "Renamed workflow must still be identified by ID",
            "status": "in_progress",
        }]}
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
        self.assertIs(report["dispatch_allowed"], False)

    def test_completed_main_run_is_not_reported_as_active(self):
        runs = {"workflow_runs": [{
            "workflow_id": 357086091,
            "status": "completed",
            "conclusion": "success",
        }]}
        activity = self.evaluate(runs=runs)["checks"]["main_loop_activity"]
        self.assertEqual(activity["status"], "INFO")
        self.assertEqual(activity["outcome"], "NO_CHANGE")
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


if __name__ == "__main__":
    unittest.main()

