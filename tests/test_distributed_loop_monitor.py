import base64
import hashlib
import json
import unittest

from scripts.distributed_loop_monitor import evaluate


def valid_state():
    return {
        "version": 1,
        "completed": [],
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {},
            "checkpoint": None,
        },
    }


def contents_response(state=None):
    raw = json.dumps(valid_state() if state is None else state, separators=(",", ":")).encode()
    blob_sha = hashlib.sha1(f"blob {len(raw)}\\0".encode() + raw).hexdigest()
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

    def test_valid_state_provenance_passes_but_never_dispatches(self):
        report = self.evaluate()
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["dispatch_allowed"], False)
        self.assertEqual(report["checks"]["state_provenance"]["status"], "PASS")
        self.assertEqual(report["checks"]["queue_and_approval"]["status"], "NOT_EVALUATED")

    def test_missing_actions_evidence_blocks(self):
        report = self.evaluate(runs={})
        self.assertEqual(report["status"], "BLOCKED")

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

    def test_active_main_run_is_reported_but_not_dispatched(self):
        runs = {"workflow_runs": [{
            "name": "Distributed Autonomous Development Loop",
            "status": "in_progress",
        }]}
        report = self.evaluate(runs=runs)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["main_loop_activity"]["active_run_count"], 1)
        self.assertFalse(report["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
