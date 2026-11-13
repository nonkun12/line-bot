import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from scripts.orca_github_native_budget_evidence import EvidenceRejected, verify_github_actions_budget

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
KEY = "test-key-that-is-long-enough-for-hmac-signing"
REPO = "nonkun12/line-bot"
ACCOUNT = "github-billing-account-123"


def evidence(*, used=100, limit=2000, changes=None):
    source = {
        "name": "github_actions", "enabled": True, "used": used, "limit": limit,
        "unit": "minutes", "source_api": "trusted-account-usage-collector",
        "limit_source": "verified_plan_included_minutes",
        "limit_evidence_id": "plan-evidence-2026-11", "quality": "exact",
        "coverage_complete": True, "exact_counter": True, "sampling_mode": "none",
        "resource_count": 1,
        "resource_digest": hashlib.sha256(b"all-account-runners").hexdigest(),
        "source_watermark_at": "2026-11-13T09:00:00Z",
    }
    if changes:
        source.update(changes)
    payload = {
        "schema_version": 1, "collector_id": "orca-github-actions-budget-collector",
        "repository": REPO, "billing_account_id": ACCOUNT,
        "observed_at": "2026-11-13T09:00:00Z",
        "period_start": "2026-11-01T00:00:00Z",
        "period_end": "2026-12-01T00:00:00Z",
        "consecutive_failures": 0, "sources": [source],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    payload["signature"] = hmac.new(KEY.encode(), raw, hashlib.sha256).hexdigest()
    return payload


def resign(payload):
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    unsigned["signature"] = hmac.new(KEY.encode(), raw, hashlib.sha256).hexdigest()
    return unsigned


class GitHubNativeBudgetEvidenceTests(unittest.TestCase):
    def verify(self, payload=None, **kwargs):
        return verify_github_actions_budget(
            payload or evidence(), KEY, NOW, expected_repository=REPO,
            expected_billing_account_id=ACCOUNT, **kwargs,
        )

    def test_exact_github_only_evidence_passes(self):
        result = self.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source"], "github_actions")
        self.assertEqual(result["remaining_minutes"], 1900)

    def test_cloudflare_sources_are_rejected(self):
        payload = evidence()
        payload["sources"][0]["name"] = "cloudflare_d1"
        with self.assertRaisesRegex(EvidenceRejected, "source_set"):
            self.verify(resign(payload))

    def test_signature_tampering_is_rejected(self):
        payload = evidence()
        payload["sources"][0]["used"] = 999
        with self.assertRaisesRegex(EvidenceRejected, "signature_invalid"):
            self.verify(payload)

    def test_repository_and_billing_account_are_bound(self):
        with self.assertRaisesRegex(EvidenceRejected, "repository_mismatch"):
            verify_github_actions_budget(
                evidence(), KEY, NOW, expected_repository="someone/else",
                expected_billing_account_id=ACCOUNT,
            )
        payload = evidence()
        payload["billing_account_id"] = "other"
        with self.assertRaisesRegex(EvidenceRejected, "billing_account_mismatch"):
            verify_github_actions_budget(
                resign(payload), KEY, NOW, expected_repository=REPO,
                expected_billing_account_id=ACCOUNT,
            )

    def test_stale_snapshot_is_rejected(self):
        payload = evidence()
        payload["observed_at"] = "2026-11-13T08:00:00Z"
        payload["sources"][0]["source_watermark_at"] = "2026-11-13T08:00:00Z"
        with self.assertRaisesRegex(EvidenceRejected, "stale_or_future"):
            self.verify(resign(payload))

    def test_insufficient_reserve_is_rejected(self):
        with self.assertRaisesRegex(EvidenceRejected, "reserve_insufficient"):
            self.verify(evidence(used=1980, limit=2000))

    def test_reserve_must_exceed_the_30_minute_worker_ceiling_with_headroom(self):
        with self.assertRaisesRegex(EvidenceRejected, "reserve_insufficient"):
            self.verify(evidence(used=156, limit=200))  # 44 minutes remaining

        result = self.verify(evidence(used=155, limit=200))  # 45 minutes remaining
        self.assertEqual(result["remaining_minutes"], 45)

    def test_80_percent_threshold_blocks(self):
        with self.assertRaisesRegex(EvidenceRejected, "threshold_blocked"):
            self.verify(evidence(used=1600, limit=2000))

    def test_70_percent_threshold_warns(self):
        result = self.verify(evidence(used=1400, limit=2000))
        self.assertEqual(result["status"], "WARN")

    def test_missing_exact_coverage_is_rejected(self):
        payload = evidence(changes={"coverage_complete": False})
        with self.assertRaisesRegex(EvidenceRejected, "coverage_not_exact"):
            self.verify(resign(payload))

    def test_missing_key_is_rejected(self):
        with self.assertRaisesRegex(EvidenceRejected, "key_missing"):
            verify_github_actions_budget(
                evidence(), "short", NOW, expected_repository=REPO,
                expected_billing_account_id=ACCOUNT,
            )


if __name__ == "__main__":
    unittest.main()
