import base64
import json
import unittest
import urllib.error

from scripts.orca_github_phase1_observer import (
    ObservationError,
    observe,
    read_state_snapshot,
    summarize_state,
)


class _Response:
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.value


class Phase1ObserverTests(unittest.TestCase):
    def test_missing_global_hold_fails_closed(self):
        state = {"schema_version": 1, "revision": 0, "tasks": [], "active_lease": None}
        with self.assertRaisesRegex(ObservationError, "global_hold_missing_or_invalid"):
            summarize_state(state)

    def test_missing_active_lease_fails_closed(self):
        state = {"schema_version": 1, "revision": 0, "global_hold": True, "tasks": []}
        with self.assertRaisesRegex(ObservationError, "active_lease_missing"):
            summarize_state(state)

    def test_multiple_claimed_tasks_fail_closed(self):
        state = {
            "schema_version": 1, "revision": 2, "global_hold": True,
            "tasks": [
                {"task_id": "a", "status": "claimed"},
                {"task_id": "b", "status": "claimed"},
            ],
            "active_lease": {"task_id": "a", "owner": "w", "run_id": "r", "expires_at": "2030-01-01T00:00:00Z"},
        }
        with self.assertRaisesRegex(ObservationError, "multiple_claimed_tasks"):
            summarize_state(state)

    def test_valid_state_summary_is_read_only(self):
        state = {
            "schema_version": 1, "revision": 4, "global_hold": False,
            "tasks": [{"task_id": "task-1", "status": "queued"}],
            "active_lease": None,
        }
        summary = summarize_state(state)
        self.assertEqual(summary["task_counts"]["queued"], 1)
        def missing_ref(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

        result = observe(token="token", repository="owner/repo", opener=missing_ref)
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["observation_status"], "BLOCKED")
        self.assertEqual(result["execution_gate"], "BLOCKED")
        self.assertEqual(result["reason"], "github_resource_not_found")


    def test_valid_snapshot_is_observed_but_execution_stays_blocked(self):
        state = {
            "schema_version": 1, "revision": 1, "global_hold": True,
            "tasks": [], "active_lease": None,
        }
        encoded = base64.b64encode(json.dumps(state).encode()).decode()
        responses = [
            _Response({"object": {"sha": "b" * 40}}),
            _Response({"encoding": "base64", "content": encoded}),
        ]

        def opener(_request, timeout):
            return responses.pop(0)

        result = observe(token="token", repository="owner/repo", opener=opener)
        self.assertEqual(result["observation_status"], "OBSERVED")
        self.assertEqual(result["execution_gate"], "BLOCKED")
        self.assertEqual(result["reason"], "global_hold_active;budget_evidence_missing")
        self.assertFalse(result["execution_enabled"])

    def test_state_document_read_is_pinned_to_observed_commit(self):
        state = {
            "schema_version": 1, "revision": 0, "global_hold": True,
            "tasks": [], "active_lease": None,
        }
        encoded = base64.b64encode(json.dumps(state).encode()).decode()
        responses = [
            _Response({"object": {"sha": "a" * 40}}),
            _Response({"encoding": "base64", "content": encoded}),
        ]
        seen = []

        def opener(request, *, timeout):
            seen.append(request.full_url)
            self.assertEqual(timeout, 10)
            return responses.pop(0)

        sha, loaded = read_state_snapshot(
            token="token", repository="owner/repo", opener=opener,
        )
        self.assertEqual(sha, "a" * 40)
        self.assertEqual(loaded, state)
        self.assertIn("?ref=" + "a" * 40, seen[1])
        self.assertNotIn("?ref=orca-state", seen[1])


if __name__ == "__main__":
    unittest.main()
