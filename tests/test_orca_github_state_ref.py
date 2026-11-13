import unittest

from scripts.orca_github_state_ref import (
    RefWriteRejected, prepare_write, verify_before_ref_update,
)

SHA = "a" * 40


class GitRefPersistenceContractTests(unittest.TestCase):
    def setUp(self):
        self.current = {"schema_version": 1, "revision": 4, "global_hold": True, "tasks": []}
        self.next = {"schema_version": 1, "revision": 5, "global_hold": True, "tasks": [{"id": "t1"}]}

    def test_prepares_non_force_fast_forward_intent(self):
        intent = prepare_write(expected_ref_sha=SHA, current_state=self.current,
                               next_state=self.next, expected_revision=4)
        self.assertEqual(intent["parent_commit_sha"], SHA)
        self.assertFalse(intent["force"])
        verify_before_ref_update(intent=intent, observed_ref_sha=SHA,
                                 observed_state=self.current)

    def test_rejects_stale_revision(self):
        with self.assertRaisesRegex(RefWriteRejected, "stale_state_revision"):
            prepare_write(expected_ref_sha=SHA, current_state=self.current,
                          next_state=self.next, expected_revision=3)

    def test_rejects_force(self):
        with self.assertRaisesRegex(RefWriteRejected, "force_update_forbidden"):
            prepare_write(expected_ref_sha=SHA, current_state=self.current,
                          next_state=self.next, expected_revision=4, force=True)

    def test_rejects_skipped_revision(self):
        bad = dict(self.next, revision=6)
        with self.assertRaisesRegex(RefWriteRejected, "revision_must_increment_once"):
            prepare_write(expected_ref_sha=SHA, current_state=self.current,
                          next_state=bad, expected_revision=4)

    def test_detects_ref_race(self):
        intent = prepare_write(expected_ref_sha=SHA, current_state=self.current,
                               next_state=self.next, expected_revision=4)
        with self.assertRaisesRegex(RefWriteRejected, "ref_moved_retry_from_fresh_state"):
            verify_before_ref_update(intent=intent, observed_ref_sha="b" * 40,
                                     observed_state=self.current)

    def test_detects_state_tampering(self):
        intent = prepare_write(expected_ref_sha=SHA, current_state=self.current,
                               next_state=self.next, expected_revision=4)
        changed = dict(self.current, global_hold=False)
        with self.assertRaisesRegex(RefWriteRejected, "persisted_state_changed"):
            verify_before_ref_update(intent=intent, observed_ref_sha=SHA,
                                     observed_state=changed)

    def test_rejects_invalid_sha(self):
        with self.assertRaisesRegex(RefWriteRejected, "expected_ref_sha_invalid"):
            prepare_write(expected_ref_sha="main", current_state=self.current,
                          next_state=self.next, expected_revision=4)


if __name__ == "__main__":
    unittest.main()
