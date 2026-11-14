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
        snapshot = StateSnapshot(self.ref, self.current, self.blob)
        result = store.write(snapshot=snapshot, next_state=self.next_state, expected_revision=2)
        self.assertEqual(result.ref_sha, self.commit)
        patch = next(x for x in calls if x.get_method() == "PATCH")
        self.assertFalse(json.loads(patch.data)["force"])

    def test_concurrent_ref_advance_rejects_non_force_write(self):
        responses = [
            {"sha": self.blob},
            {"tree": {"sha": self.tree}},
            {"sha": self.tree},
            {"sha": self.commit},
        ]
        methods = []
        def opener(request, timeout=15):
            methods.append(request.get_method())
            if request.get_method() == "PATCH":
                raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
                    request.full_url, 422, "non-fast-forward", {}, None
                )
            return Response(responses.pop(0))
        store = GitHubStateStore(token="token", repository="o/r", branch="state",
                                 path="state/queue.json", opener=opener)
        snapshot = StateSnapshot(self.ref, self.current, self.blob)
        with self.assertRaisesRegex(StateConflict, "github_ref_fast_forward_conflict"):
            store.write(snapshot=snapshot, next_state=self.next_state, expected_revision=2)
        self.assertEqual(methods[-1], "PATCH")
        self.assertEqual(methods.count("PATCH"), 1)

    def test_stale_revision_rejected_before_api_calls(self):
        opener = Mock()
        store = GitHubStateStore(token="token", repository="o/r", branch="state",
                                 path="state.json", opener=opener)
        snapshot = StateSnapshot(self.ref, self.current, self.blob)
        with self.assertRaises(StateConflict):
            store.write(snapshot=snapshot, next_state=self.next_state, expected_revision=1)
        opener.assert_not_called()


class GitHubStateInitializerTests(unittest.TestCase):
    def setUp(self):
        self.ref = "a" * 40
        self.tree = "b" * 40
        self.blob = "c" * 40
        self.commit = "d" * 40
        self.path = "state/queue.json"

    def _store(self, opener):
        return GitHubStateStore(token="token", repository="o/r", branch="state",
                                path=self.path, opener=opener)

    def _missing_document(self, request):
        import urllib.error
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    def test_initializes_missing_document_hold_latched_and_non_force(self):
        from scripts.orca_github_task_queue import empty_state
        encoded = base64.b64encode(
            json.dumps(empty_state(), sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        responses = [
            {"object": {"sha": self.ref}},  # observed ref
            None,                            # missing document (404)
            {"tree": {"sha": self.tree}},   # parent commit
            {"sha": self.blob},              # create blob
            {"sha": self.tree},              # create tree
            {"sha": self.commit},             # create commit
            {"object": {"sha": self.commit}},# update ref
            {"object": {"sha": self.commit}},# readback ref
            {"tree": {"sha": self.tree}},    # readback commit
            {"encoding": "base64", "content": encoded, "sha": self.blob},
        ]
        calls = []
        def opener(request, timeout=15):
            calls.append(request)
            item = responses.pop(0)
            if item is None:
                self._missing_document(request)
            return Response(item)
        snapshot = self._store(opener).initialize_hold_latched()
        self.assertEqual(snapshot.ref_sha, self.commit)
        self.assertIs(snapshot.state["global_hold"], True)
        self.assertEqual(snapshot.state["revision"], 0)
        patch = next(x for x in calls if x.get_method() == "PATCH")
        self.assertFalse(json.loads(patch.data)["force"])
        commit_payload = json.loads(next(
            x.data for x in calls if x.get_method() == "POST"
            and x.full_url.endswith("/git/commits")
        ))
        self.assertEqual(commit_payload["parents"], [self.ref])

    def test_existing_document_is_never_overwritten(self):
        calls = []
        def opener(request, timeout=15):
            calls.append(request)
            if len(calls) == 1:
                return Response({"object": {"sha": self.ref}})
            return Response({"sha": self.blob})
        with self.assertRaisesRegex(StateConflict, "state_document_already_exists"):
            self._store(opener).initialize_hold_latched()
        self.assertEqual([x.get_method() for x in calls], ["GET", "GET"])

    def test_concurrent_initializer_cannot_force_ref_update(self):
        responses = [
            {"object": {"sha": self.ref}}, None,
            {"tree": {"sha": self.tree}}, {"sha": self.blob},
            {"sha": self.tree}, {"sha": self.commit},
        ]
        methods = []
        def opener(request, timeout=15):
            methods.append(request.get_method())
            if len(methods) == 2:
                self._missing_document(request)
            if request.get_method() == "PATCH":
                import urllib.error
                raise urllib.error.HTTPError(
                    request.full_url, 422, "non-fast-forward", {}, None
                )
            return Response(responses.pop(0))
        with self.assertRaisesRegex(StateConflict, "github_ref_fast_forward_conflict"):
            self._store(opener).initialize_hold_latched()
        self.assertEqual(methods[-1], "PATCH")
        self.assertEqual(methods.count("PATCH"), 1)


if __name__ == "__main__":
    unittest.main()
