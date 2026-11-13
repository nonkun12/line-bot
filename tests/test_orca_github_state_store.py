import base64
import json
import unittest
from unittest.mock import Mock

from scripts.orca_github_state_store import (
    GitHubStateStore, StateConflict, StateSnapshot, StateStoreError,
)


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=-1): return self.payload[:limit]


class GitHubStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.current = {"schema_version": 1, "revision": 2, "global_hold": True,
                        "tasks": [], "active_lease": None}
        self.next_state = dict(self.current, revision=3)
        self.ref = "a" * 40
        self.tree = "b" * 40
        self.blob = "c" * 40
        self.commit = "d" * 40

    def test_read_pins_state_document_to_observed_commit_sha(self):
        encoded = base64.b64encode(json.dumps(self.current).encode()).decode()
        responses = [
            {"object": {"sha": self.ref}},
            {"tree": {"sha": self.tree}},
            {"encoding": "base64", "content": encoded, "sha": self.blob},
        ]
        calls = []
        def opener(request, timeout=15):
            calls.append(request)
            return Response(responses.pop(0))
        store = GitHubStateStore(token="token", repository="o/r", branch="state",
                                 path="state/queue.json", opener=opener)

        snapshot = store.read()

        self.assertEqual(snapshot.ref_sha, self.ref)
        self.assertEqual(snapshot.state, self.current)
        self.assertIn(f"?ref={self.ref}", calls[2].full_url)
        self.assertNotIn("?ref=state", calls[2].full_url)

    def test_missing_configuration_fails_closed(self):
        with self.assertRaises(StateStoreError):
            GitHubStateStore(token="", repository="owner/repo", branch="state",
                             path="state.json")

    def test_write_uses_non_force_patch_and_verifies_readback(self):
        encoded = base64.b64encode(json.dumps(self.next_state).encode()).decode()
        responses = [
            {"sha": self.blob},                 # create blob
            {"tree": {"sha": self.tree}},      # read parent commit
            {"sha": self.tree},                # create tree
            {"sha": self.commit},              # create commit
            {"object": {"sha": self.commit}},  # update ref response
            {"object": {"sha": self.commit}},  # read-after-write ref
            {"tree": {"sha": self.tree}},      # read-after-write commit
            {"encoding": "base64", "content": encoded, "sha": self.blob},
        ]
        calls = []
        def opener(request, timeout=15):
            calls.append(request)
            return Response(responses.pop(0))
        store = GitHubStateStore(token="token", repository="o/r", branch="state",
                                 path="state/queue.json", opener=opener)
        # Initial snapshot read is intentionally mocked as a known, exact revision.
        snapshot = StateSnapshot(self.ref, self.current, self.blob)
        result = store.write(snapshot=snapshot, next_state=self.next_state, expected_revision=2)
        self.assertEqual(result.ref_sha, self.commit)
        patch = next(x for x in calls if x.get_method() == "PATCH")
        self.assertFalse(json.loads(patch.data)["force"])

    def test_stale_revision_rejected_before_api_calls(self):
        opener = Mock()
        store = GitHubStateStore(token="token", repository="o/r", branch="state",
                                 path="state.json", opener=opener)
        snapshot = StateSnapshot(self.ref, self.current, self.blob)
        with self.assertRaises(StateConflict):
            store.write(snapshot=snapshot, next_state=self.next_state, expected_revision=1)
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
