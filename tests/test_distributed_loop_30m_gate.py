import unittest
from datetime import datetime, timedelta, timezone
from scripts.distributed_loop_30m_gate import GateBlocked, decide_slot, evaluate_budget_snapshot

NOW = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
START, END, OBSERVED = "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "2026-11-13T00:00:00Z"

def snapshots(overrides=None):
    overrides = overrides or {}
    return [{"name": name, "enabled": True, "used": 10, "limit": 100,
             "observed_at": OBSERVED, "period_start": START, "period_end": END,
             **overrides.get(name, {})}
            for name in ("cloudflare_workers", "cloudflare_d1", "github_actions")]

class BudgetGateTests(unittest.TestCase):
    def test_clear_and_warn_allow(self):
        self.assertEqual(evaluate_budget_snapshot({"sources": snapshots()}, now=NOW)["status"], "CLEAR")
        self.assertEqual(evaluate_budget_snapshot({"sources": snapshots({"cloudflare_d1": {"used": 70}})}, now=NOW)["status"], "WARN")
    def test_80_and_90_percent_block(self):
        for used, reason in ((80, "budget_suppress"), (90, "budget_stop")):
            with self.assertRaisesRegex(GateBlocked, reason):
                evaluate_budget_snapshot({"sources": snapshots({"cloudflare_d1": {"used": used}})}, now=NOW)
    def test_non_finite_budget_values_block(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaisesRegex(GateBlocked, "budget_values_invalid"):
                evaluate_budget_snapshot(
                    {"sources": snapshots({"cloudflare_d1": {"used": value}})}, now=NOW
                )

    def test_missing_disabled_stale_and_out_of_period_block(self):
        cases = [
            (snapshots()[:2], "budget_source_missing"),
            (snapshots({"cloudflare_d1": {"enabled": None}}), "budget_source_not_confirmed_enabled"),
            (snapshots({"cloudflare_d1": {"observed_at": (NOW-timedelta(hours=2)).isoformat()}}), "budget_snapshot_stale_or_future"),
            (snapshots({"cloudflare_d1": {"period_end": "2026-11-12T00:00:00Z"}}), "budget_period_not_current"),
        ]
        for source_rows, reason in cases:
            with self.assertRaisesRegex(GateBlocked, reason):
                evaluate_budget_snapshot({"sources": source_rows}, now=NOW)

class SlotGateTests(unittest.TestCase):
    def test_first_slot_and_old_run_allow(self):
        self.assertTrue(decide_slot([], current_run_id="2", now=NOW)[0])
        old = [{"id": 1, "run_started_at": (NOW-timedelta(minutes=31)).isoformat()}]
        self.assertEqual(decide_slot(old, current_run_id="2", now=NOW), (True, "slot_available"))
    def test_recent_future_and_invalid_runs_block(self):
        for runs in (
            [{"id": 1, "run_started_at": (NOW-timedelta(minutes=20)).isoformat()}],
            [{"id": 1, "run_started_at": (NOW+timedelta(minutes=10)).isoformat()}],
            [{}],
        ):
            self.assertFalse(decide_slot(runs, current_run_id="2", now=NOW)[0])

if __name__ == "__main__":
    unittest.main()
