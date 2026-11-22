"""Fail-closed tests for owner risk acceptance receipts."""
from __future__ import annotations

import unittest

from scripts.rea_owner_risk_acceptance import build_owner_risk_acceptance

BASE = "a" * 40
HEAD = "b" * 40
DIFF = "c" * 64


def report(findings=None):
    return {
        "complete": True, "base_sha": BASE, "target_sha": HEAD,
        "diff_sha256": DIFF, "findings": [] if findings is None else findings,
    }


def build(source=None, **overrides):
    args = {
        "actor": "nonkun12", "repository_owner": "nonkun12",
        "decision": "ACCEPT", "run_id": 1234,
        "accepted_at": "2026-11-23T00:00:00Z",
    }
    args.update(overrides)
    return build_owner_risk_acceptance(report() if source is None else source, **args)


class OwnerRiskAcceptanceTests(unittest.TestCase):
    def test_owner_acceptance_is_recorded_but_never_authorizes_merge(self):
        receipt = build()
        self.assertEqual(receipt["status"], "ACCEPTED")
        self.assertEqual(receipt["risk"], "LOW")
        self.assertFalse(receipt["independent_review_substituted"])
        self.assertFalse(receipt["merge_authorized"])
        self.assertFalse(receipt["deploy_authorized"])
        self.assertEqual(receipt["human_review_status"], "NOT_PROVIDED")

    def test_non_owner_cannot_accept(self):
        with self.assertRaisesRegex(ValueError, "actor_not_repository_owner"):
            build(actor="someone-else")

    def test_high_risk_cannot_be_accepted(self):
        source = report([{"severity": "HIGH"}])
        receipt = build(source)
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["risk"], "HIGH")
        self.assertFalse(receipt["merge_authorized"])

    def test_critical_risk_cannot_be_accepted(self):
        source = report([{"severity": "CRITICAL"}])
        self.assertEqual(build(source)["status"], "BLOCKED")

    def test_medium_risk_cannot_be_accepted(self):
        source = report([{"severity": "MEDIUM"}])
        self.assertEqual(build(source)["status"], "BLOCKED")

    def test_decline_is_recorded(self):
        self.assertEqual(build(decision="DECLINE")["status"], "DECLINED")

    def test_incomplete_scan_fails_closed(self):
        source = report()
        source["complete"] = False
        with self.assertRaisesRegex(ValueError, "scan_incomplete"):
            build(source)

    def test_sha_and_diff_identity_are_required(self):
        source = report()
        source["target_sha"] = "bad"
        with self.assertRaisesRegex(ValueError, "target_sha_invalid"):
            build(source)

    def test_malformed_findings_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "finding_severity_invalid"):
            build(report([{"severity": "UNKNOWN"}]))


if __name__ == "__main__":
    unittest.main()
