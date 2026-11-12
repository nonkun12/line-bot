import unittest

from scripts.distributed_loop_budget_observation import build_budget_observation


class BudgetObservationTests(unittest.TestCase):
    def test_exact_measurement_is_still_observation_only(self):
        record = build_budget_observation({
            "name": "cloudflare_d1",
            "used": 1234,
            "unit": "rows_read",
            "quality": "exact",
            "limit": 999999,
            "limit_source": "forged",
            "limit_verified": True,
            "limit_evidence_id": "forged-evidence",
            "enforcement_eligible": True,
        })
        self.assertEqual(record["used"], 1234)
        self.assertEqual(record["quality"], "exact")
        self.assertIsNone(record["limit"])
        self.assertIsNone(record["limit_source"])
        self.assertFalse(record["limit_verified"])
        self.assertIsNone(record["limit_evidence_id"])
        self.assertFalse(record["enforcement_eligible"])

    def test_unavailable_source_can_be_recorded_without_usage(self):
        record = build_budget_observation({
            "name": "cloudflare_workers",
            "quality": "unavailable",
            "note": "provider endpoint unavailable",
        })
        self.assertIsNone(record["used"])
        self.assertFalse(record["enforcement_eligible"])

    def test_invalid_source_quality_and_usage_are_rejected(self):
        cases = [
            ({"name": "unknown", "quality": "exact", "used": 1}, "source"),
            ({"name": "cloudflare_d1", "quality": "perfect", "used": 1}, "quality"),
            ({"name": "cloudflare_d1", "quality": "exact", "used": float("inf")}, "used"),
            ({"name": "cloudflare_d1", "quality": "estimated"}, "missing"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, expected):
                    build_budget_observation(raw)


if __name__ == "__main__":
    unittest.main()
