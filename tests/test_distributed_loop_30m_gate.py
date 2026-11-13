import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone

from scripts.distributed_loop_30m_gate import GateBlocked, decide_slot, evaluate_budget_snapshot

NOW = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
START, END, OBSERVED = "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "2026-11-13T00:00:00Z"
SECRET, ACCOUNT, COLLECTOR = "unit-test-only-secret", "account-test-001", "orca-budget-collector-test"
GITHUB_ACCOUNT = "github-owner-test-001"
NAMES = ("cloudflare_workers", "cloudflare_d1", "cloudflare_durable_objects", "github_actions")
UNITS = {"cloudflare_workers": "requests", "cloudflare_d1": "rows",
         "cloudflare_durable_objects": "requests", "github_actions": "runner_minutes"}


def sign(payload):
    unsigned = dict(payload)
    attestation = dict(unsigned["attestation"])
    attestation.pop("signature", None)
    unsigned["attestation"] = attestation
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    payload["attestation"]["signature"] = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    return payload


def signed_payload(overrides=None, *, attestation_overrides=None):
    overrides = overrides or {}
    sources = []
    for name in NAMES:
        sources.append({
            "name": name, "provider": "github" if name == "github_actions" else "cloudflare",
            "enabled": True, "used": 10, "limit": 100,
            "unit": UNITS[name], "limit_source": "vendor_verified_quota",
            "quality": "exact", "enforcement_eligible": True,
            "limit_verified": True, "limit_evidence_id": "vendor-evidence-001",
            "dataset": "authoritative-account-meter-v1",
            "account_id": GITHUB_ACCOUNT if name == "github_actions" else ACCOUNT,
            "complete_account_coverage": True, "exact_counter": True,
            "sampling_mode": "none", "coverage_status": "complete",
            "watermark_at": OBSERVED, "observed_at": OBSERVED,
            "period_start": START, "period_end": END, **overrides.get(name, {}),
        })
    payload = {"schema_version": 1, "sources": sources, "consecutive_failures": 0,
               "attestation": {
                   "algorithm": "hmac-sha256", "account_id": ACCOUNT,
                   "collector_id": COLLECTOR, "issued_at": OBSERVED,
                   "expires_at": "2026-11-13T00:10:00Z",
               }}
    payload["attestation"].update(attestation_overrides or {})
    return sign(payload)


def evaluate(payload):
    return evaluate_budget_snapshot(payload, now=NOW, attestation_secret=SECRET,
                                    expected_account_id=ACCOUNT, trusted_collector_id=COLLECTOR,
                                    expected_github_account_id=GITHUB_ACCOUNT)


class BudgetGateTests(unittest.TestCase):
    def test_signed_clear_and_warn_allow(self):
        self.assertEqual(evaluate(signed_payload())["status"], "CLEAR")
        self.assertEqual(evaluate(signed_payload({"cloudflare_d1": {"used": 70}}))["status"], "WARN")

    def test_80_and_90_percent_block(self):
        for used, reason in ((80, "budget_suppress"), (90, "budget_stop")):
            with self.assertRaisesRegex(GateBlocked, reason):
                evaluate(signed_payload({"cloudflare_d1": {"used": used}}))

    def test_self_asserted_authority_without_valid_signature_blocks(self):
        payload = signed_payload()
        payload["sources"][0]["limit_evidence_id"] = "fixture-evidence-001"
        payload["attestation"]["signature"] = "0" * 64
        with self.assertRaisesRegex(GateBlocked, "budget_attestation_signature_invalid"):
            evaluate(payload)

    def test_unsigned_or_wrong_collector_blocks(self):
        payload = signed_payload()
        payload.pop("attestation")
        with self.assertRaisesRegex(GateBlocked, "budget_attestation_missing"):
            evaluate(payload)
        payload = signed_payload(attestation_overrides={"collector_id": "untrusted"})
        with self.assertRaisesRegex(GateBlocked, "budget_attestation_signature_invalid|budget_attestation_identity_invalid"):
            evaluate(payload)

    def test_attestation_expiry_and_freshness_are_signed_and_enforced(self):
        payload = signed_payload(attestation_overrides={
            "issued_at": "2026-11-12T23:00:00Z", "expires_at": "2026-11-12T23:15:00Z"
        })
        with self.assertRaisesRegex(GateBlocked, "budget_attestation_stale_or_out_of_window"):
            evaluate(payload)

    def test_missing_or_unexpected_meter_blocks(self):
        payload = signed_payload()
        payload["sources"] = [x for x in payload["sources"] if x["name"] != "cloudflare_durable_objects"]
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "budget_source_set_incomplete_or_unexpected"):
            evaluate(payload)

    def test_partial_sampled_or_wrong_account_source_blocks(self):
        for override in ({"complete_account_coverage": False}, {"exact_counter": False},
                         {"sampling_mode": "adaptive"}, {"coverage_status": "partial"},
                         {"account_id": "other-account"}):
            with self.subTest(override=override):
                with self.assertRaisesRegex(GateBlocked, "budget_source_coverage_or_exactness_unproven"):
                    evaluate(signed_payload({"cloudflare_workers": override}))

    def test_wrong_github_billing_account_blocks(self):
        with self.assertRaisesRegex(GateBlocked, "budget_source_coverage_or_exactness_unproven"):
            evaluate(signed_payload({"github_actions": {"account_id": "untrusted-gh-owner"}}))

    def test_old_watermark_blocks_even_if_poll_is_recent(self):
        with self.assertRaisesRegex(GateBlocked, "budget_snapshot_stale_or_future"):
            evaluate(signed_payload({"cloudflare_d1": {"watermark_at": "2026-11-12T23:40:00Z"}}))

    def test_watermark_must_not_be_newer_than_observation_or_attestation(self):
        with self.assertRaisesRegex(GateBlocked, "budget_watermark_after_observation"):
            evaluate(signed_payload({"cloudflare_d1": {"watermark_at": "2026-11-13T00:01:00Z"}}))
        with self.assertRaisesRegex(GateBlocked, "budget_observation_after_attestation"):
            evaluate(signed_payload({"cloudflare_d1": {"observed_at": "2026-11-13T00:06:00Z",
                                                       "watermark_at": "2026-11-13T00:05:00Z"}}))

    def test_missing_trust_configuration_blocks(self):
        from scripts.distributed_loop_30m_gate import evaluate_budget_snapshot
        with self.assertRaisesRegex(GateBlocked, "budget_attestation_trust_configuration_missing"):
            evaluate_budget_snapshot(signed_payload(), now=NOW, attestation_secret="",
                                     expected_account_id=ACCOUNT,
                                     trusted_collector_id=COLLECTOR,
                                     expected_github_account_id=GITHUB_ACCOUNT)

    def test_missing_disabled_and_out_of_period_block(self):
        cases = [
            ({"cloudflare_d1": {"enabled": None}}, "budget_source_not_confirmed_enabled"),
            ({"cloudflare_d1": {"period_end": "2026-11-12T00:00:00Z"}}, "budget_period_not_current"),
            ({"cloudflare_d1": {"limit_verified": False}}, "budget_limit_not_authoritatively_verified"),
        ]
        for overrides, reason in cases:
            with self.assertRaisesRegex(GateBlocked, reason):
                evaluate(signed_payload(overrides))

    def test_three_consecutive_failures_block(self):
        payload = signed_payload()
        payload["consecutive_failures"] = 3
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "consecutive_failure_limit_reached"):
            evaluate(payload)


class SlotGateTests(unittest.TestCase):
    def test_auto_continuation_is_subject_to_slot_gate(self):
        from scripts.distributed_loop_30m_gate import requires_slot_gate
        self.assertTrue(requires_slot_gate("schedule", "0"))
        self.assertTrue(requires_slot_gate("workflow_dispatch", "1"))
        self.assertTrue(requires_slot_gate("workflow_dispatch", "12"))
        self.assertFalse(requires_slot_gate("workflow_dispatch", "0"))
        self.assertFalse(requires_slot_gate("issue_comment", "0"))

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


class RuntimeStopWatcherTests(unittest.TestCase):
    def test_live_watcher_fails_closed_on_network_or_admission_failure(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                    / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
        watcher = workflow.split("STOP_FILE=/tmp/line-bot-autonomous-loop.stop", 1)[1].split(
            "POLLER_PID=$!", 1
        )[0]
        self.assertIn("while sleep 15", watcher)
        self.assertIn("if ! git fetch --quiet --no-tags --depth=1 origin main", watcher)
        self.assertIn('touch "$STOP_FILE"', watcher)
        self.assertIn("/control/loop-admission", watcher)
        self.assertIn('if [ "$http_code" != "200" ]', watcher)
        self.assertIn(".global_hold.clear == true", watcher)
        self.assertIn(".budget_guard.allowed == true", watcher)
        self.assertIn("--stop-file \"$STOP_FILE\"", workflow)


    def test_final_admission_is_rechecked_before_publish(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                    / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
        final_gate = workflow.split("id: final_admission", 1)[1].split("id: publish", 1)[0]
        self.assertIn("python scripts/distributed_loop_30m_gate.py", final_gate)
        self.assertIn("ORCA_30M_GATE_ALLOW:", final_gate)
        self.assertIn("steps.final_admission.outputs.allow == 'true'", workflow)


if __name__ == "__main__":
    unittest.main()
