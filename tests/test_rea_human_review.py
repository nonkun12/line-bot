"""Tests for SHA-bound REA human-review attestation validation."""
from __future__ import annotations

import unittest

from scripts.rea_human_review import apply_human_review_attestation


HEAD = "a" * 40
DIFF = "b" * 64
BASE = "c" * 40
COMMENT = (
    "REA-HUMAN-REVIEW: APPROVED\n"
    f"HEAD_SHA: {HEAD}\n"
    f"BASE_SHA: {BASE}\n"
    f"DIFF_SHA256: {DIFF}\n"
    "I reviewed the complete dispatcher diff."
)


def make_report() -> dict:
    return {
        "base_sha": BASE,
        "target_sha": HEAD,
        "diff_sha256": DIFF,
        "findings": [
            {
                "category": "manual_review_required",
                "target_sha": HEAD,
                "status": "REVIEW_REQUIRED",
                "severity": "HIGH",
                "evidence": {
                    "path": "distributed_loop_trigger.py",
                    "check": "sensitive_entrypoint_requires_human_review",
                },
            },
            {
                "category": "python_syntax",
                "target_sha": HEAD,
                "status": "REVIEW_REQUIRED",
                "severity": "HIGH",
                "evidence": {"path": "scripts/other.py", "check": "ast_parse_failed"},
            },
        ],
    }


def make_attestation() -> dict:
    return {
        "expected_head_sha": HEAD,
        "expected_base_sha": BASE,
        "expected_diff_sha256": DIFF,
        "reviewer_login": "independent-reviewer",
        "pr_author_login": "nonkun12",
        "comment_id": 123,
        "comment_url": "https://github.com/nonkun12/line-bot/pull/1576#pullrequestreview-123",
        "comment_body": COMMENT,
        "comment_created_at": "2026-11-22T10:00:00Z",
        "comment_updated_at": "2026-11-22T10:00:00Z",
        "head_commit_at": "2026-11-22T09:00:00Z",
        "repo_full_name": "nonkun12/line-bot",
        "pr_number": 1576,
    }


class HumanReviewAttestationTests(unittest.TestCase):
    def test_valid_attestation_marks_only_the_designated_finding(self) -> None:
        original = make_report()
        updated = apply_human_review_attestation(original, make_attestation())
        self.assertEqual(updated["human_review_attestation"]["status"], "VERIFIED")
        self.assertEqual(updated["findings"][0]["status"], "HUMAN_REVIEWED")
        self.assertEqual(updated["findings"][1]["status"], "REVIEW_REQUIRED")
        self.assertEqual(original["findings"][0]["status"], "REVIEW_REQUIRED")

    def test_wrong_head_sha_is_rejected(self) -> None:
        evidence = make_attestation()
        evidence["expected_head_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "review_head_sha_mismatch"):
            apply_human_review_attestation(make_report(), evidence)

    def test_wrong_diff_hash_is_rejected(self) -> None:
        evidence = make_attestation()
        evidence["expected_diff_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "review_diff_hash_mismatch"):
            apply_human_review_attestation(make_report(), evidence)

    def test_comment_must_bind_the_diff_hash(self) -> None:
        evidence = make_attestation()
        evidence["comment_body"] = evidence["comment_body"].replace(DIFF, "d" * 64)
        with self.assertRaisesRegex(ValueError, "review_comment_diff_mismatch"):
            apply_human_review_attestation(make_report(), evidence)

    def test_comment_must_bind_the_base_sha(self) -> None:
        evidence = make_attestation()
        evidence["comment_body"] = evidence["comment_body"].replace(BASE, "d" * 40)
        with self.assertRaisesRegex(ValueError, "review_comment_base_mismatch"):
            apply_human_review_attestation(make_report(), evidence)

    def test_pr_author_cannot_self_attest(self) -> None:
        evidence = make_attestation()
        evidence["reviewer_login"] = "nonkun12"
        with self.assertRaisesRegex(ValueError, "reviewer_is_pr_author"):
            apply_human_review_attestation(make_report(), evidence)

    def test_comment_must_postdate_reviewed_head(self) -> None:
        evidence = make_attestation()
        evidence["comment_created_at"] = "2026-11-22T08:59:59Z"
        evidence["comment_updated_at"] = "2026-11-22T08:59:59Z"
        with self.assertRaisesRegex(ValueError, "review_comment_predates_head"):
            apply_human_review_attestation(make_report(), evidence)

    def test_comment_must_contain_exact_head_marker(self) -> None:
        evidence = make_attestation()
        evidence["comment_body"] = "REA-HUMAN-REVIEW: APPROVED\nHEAD_SHA: " + "c" * 40
        with self.assertRaisesRegex(ValueError, "review_comment_head_mismatch"):
            apply_human_review_attestation(make_report(), evidence)

    def test_unrelated_high_finding_is_never_dismissed(self) -> None:
        evidence = make_attestation()
        source = make_report()
        source["findings"][1]["category"] = "manual_review_required"
        source["findings"][1]["evidence"]["path"] = "scripts/other.py"
        updated = apply_human_review_attestation(source, evidence)
        self.assertEqual(updated["findings"][0]["status"], "HUMAN_REVIEWED")
        self.assertEqual(updated["findings"][1]["status"], "REVIEW_REQUIRED")
        self.assertEqual(updated["findings"][1]["severity"], "HIGH")


if __name__ == "__main__":
    unittest.main()
