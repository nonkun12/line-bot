import hashlib
import hmac
import json
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from scripts.distributed_loop_30m_gate import GateBlocked, check_loop_admission, decide_slot, evaluate_budget_snapshot, main

NOW = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
DAILY_START, DAILY_END = "2026-11-13T00:00:00Z", "2026-11-14T00:00:00Z"
MONTH_START, MONTH_END = "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"
OBSERVED = "2026-11-13T00:00:00Z"
SECRET, ACCOUNT, COLLECTOR = "unit-test-only-secret", "account-test-001", "orca-budget-collector-test"
GITHUB_ACCOUNT = "github-owner-test-001"
METER_SPECS = {
    "cloudflare.workers.requests.daily": ("cloudflare", "workers", "requests", "cloudflare_workers"),
    "cloudflare.workers.cpu_ms_per_invocation.max": ("cloudflare", "workers", "ms", "cloudflare_workers"),
    "cloudflare.workers_logs.events.daily": ("cloudflare", "workers_logs", "events", "cloudflare_workers_logs"),
    "cloudflare.d1.rows_read.daily": ("cloudflare", "d1", "rows", "cloudflare_d1"),
    "cloudflare.d1.rows_written.daily": ("cloudflare", "d1", "rows", "cloudflare_d1"),
    "cloudflare.d1.storage_bytes.total": ("cloudflare", "d1", "bytes", "cloudflare_d1"),
    "cloudflare.durable_objects.requests.daily": ("cloudflare", "durable_objects", "requests", "cloudflare_durable_objects"),
    "cloudflare.durable_objects.duration_gb_seconds.daily": ("cloudflare", "durable_objects", "GB-seconds", "cloudflare_durable_objects"),
    "cloudflare.durable_objects.sqlite_rows_read.daily": ("cloudflare", "durable_objects", "rows", "cloudflare_durable_objects"),
    "cloudflare.durable_objects.sqlite_rows_written.daily": ("cloudflare", "durable_objects", "rows", "cloudflare_durable_objects"),
    "cloudflare.durable_objects.sqlite_storage_bytes.total": ("cloudflare", "durable_objects", "bytes", "cloudflare_durable_objects"),
    "github.actions.compute_cost_usd.monthly": ("github", "actions", "USD", "github_actions"),
    "github.actions.artifact_storage_bytes.monthly": ("github", "actions", "bytes", "github_actions"),
}
REQUIRED_PRODUCTS = ["actions", "d1", "durable_objects", "workers", "workers_logs"]


def sign(payload):
    unsigned = dict(payload)
    attestation = dict(unsigned["attestation"])
    attestation.pop("signature", None)
    unsigned["attestation"] = attestation
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    payload["attestation"]["signature"] = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    return payload


def signed_payload(overrides=None, *, attestation_overrides=None, inventory_overrides=None):
    overrides = overrides or {}
    meters = []
    for meter_id, (provider, product_id, unit, alias) in METER_SPECS.items():
        if ".daily" in meter_id:
            period_kind, period_start, period_end = "daily", DAILY_START, DAILY_END
        elif ".monthly" in meter_id:
            period_kind, period_start, period_end = "monthly", MONTH_START, MONTH_END
        elif ".total" in meter_id:
            period_kind, period_start, period_end = "total", None, None
        else:
            period_kind, period_start, period_end = "per_invocation", None, None
        meters.append({
            "meter_id": meter_id, "provider": provider, "product_id": product_id,
            "account_id": GITHUB_ACCOUNT if provider == "github" else ACCOUNT,
            "enabled": True, "used": 10, "limit": 100, "unit": unit,
            "limit_source": "vendor_verified_quota", "quality": "exact",
            "enforcement_eligible": True, "limit_verified": True,
            "limit_evidence_id": "vendor-meter-evidence-v2",
            "dataset": "authoritative-account-meter-v2",
            "complete_account_coverage": True, "exact_counter": True,
            "sampling_mode": "none", "coverage_status": "complete",
            "watermark_at": OBSERVED, "observed_at": OBSERVED,
            "period_kind": period_kind, "period_start": period_start, "period_end": period_end,
            **overrides.get(meter_id, overrides.get(alias, {})),
        })
    inventory = {
        "complete_account_coverage": True,
        "cloudflare_account_id": ACCOUNT,
        "github_account_id": GITHUB_ACCOUNT,
        "enabled_products": list(REQUIRED_PRODUCTS),
        "unresolved_products": [],
        "observed_at": OBSERVED,
        "watermark_at": OBSERVED,
        **(inventory_overrides or {}),
    }
    payload = {
        "schema_version": 2, "meters": meters, "meter_inventory": inventory,
        "consecutive_failures": 0,
        "attestation": {
            "algorithm": "hmac-sha256", "account_id": ACCOUNT,
            "collector_id": COLLECTOR, "issued_at": OBSERVED,
            "expires_at": "2026-11-13T00:10:00Z",
        },
    }
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
        payload["meters"][0]["limit_evidence_id"] = "fixture-evidence-001"
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
        payload["meters"] = [x for x in payload["meters"]
                             if x["meter_id"] != "cloudflare.durable_objects.requests.daily"]
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "budget_meter_set_incomplete_or_unexpected"):
            evaluate(payload)

    def test_incomplete_or_unknown_product_inventory_blocks(self):
        payload = signed_payload()
        payload.pop("meter_inventory")
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "budget_product_inventory_missing"):
            evaluate(payload)
        payload = signed_payload(inventory_overrides={
            "enabled_products": REQUIRED_PRODUCTS + ["workers_kv"]
        })
        with self.assertRaisesRegex(GateBlocked, "budget_product_inventory_unexpected_or_incomplete"):
            evaluate(payload)

    def test_legacy_v1_four_row_payload_is_rejected(self):
        payload = signed_payload()
        payload["schema_version"] = 1
        payload["sources"] = [{"name": "cloudflare_workers"}]
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "budget_meter_schema_unsupported"):
            evaluate(payload)

    def test_inventory_freshness_and_account_scope_are_enforced(self):
        stale = signed_payload(inventory_overrides={
            "observed_at": "2026-11-12T23:40:00Z",
            "watermark_at": "2026-11-12T23:40:00Z",
        })
        with self.assertRaisesRegex(GateBlocked, "budget_product_inventory_stale_or_future"):
            evaluate(stale)
        wrong_account = signed_payload(inventory_overrides={
            "cloudflare_account_id": "another-account",
        })
        with self.assertRaisesRegex(GateBlocked, "budget_product_inventory_incomplete"):
            evaluate(wrong_account)

    def test_duplicate_meter_id_blocks(self):
        payload = signed_payload()
        payload["meters"].append(dict(payload["meters"][0]))
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "budget_meter_identity_invalid"):
            evaluate(payload)

    def test_partial_sampled_or_wrong_account_meter_blocks(self):
        for override in ({"complete_account_coverage": False}, {"exact_counter": False},
                         {"sampling_mode": "adaptive"}, {"coverage_status": "partial"}):
            with self.subTest(override=override):
                with self.assertRaisesRegex(GateBlocked, "budget_meter_coverage_or_exactness_unproven"):
                    evaluate(signed_payload({"cloudflare_workers": override}))
        with self.assertRaisesRegex(GateBlocked, "budget_meter_provider_product_or_account_invalid"):
            evaluate(signed_payload({"cloudflare_workers": {"account_id": "other-account"}}))

    def test_wrong_github_billing_account_blocks(self):
        with self.assertRaisesRegex(GateBlocked, "budget_meter_provider_product_or_account_invalid"):
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
            ({"cloudflare_d1": {"enabled": None}}, "budget_meter_provider_product_or_account_invalid"),
            ({"cloudflare.d1.rows_read.daily": {"period_end": "2026-11-12T00:00:00Z"}}, "budget_period_not_current"),
            ({"cloudflare_d1": {"limit_verified": False}}, "budget_limit_not_authoritatively_verified"),
        ]
        for overrides, reason in cases:
            with self.assertRaisesRegex(GateBlocked, reason):
                evaluate(signed_payload(overrides))

    def test_meter_period_kind_and_total_boundaries_are_enforced(self):
        with self.assertRaisesRegex(GateBlocked, "budget_period_kind_invalid"):
            evaluate(signed_payload({"cloudflare.workers.requests.daily": {"period_kind": "monthly"}}))
        with self.assertRaisesRegex(GateBlocked, "budget_nonreset_meter_has_period_boundary"):
            evaluate(signed_payload({"cloudflare.d1.storage_bytes.total": {
                "period_start": MONTH_START, "period_end": MONTH_END
            }}))

    def test_three_consecutive_failures_block(self):
        payload = signed_payload()
        payload["consecutive_failures"] = 3
        sign(payload)
        with self.assertRaisesRegex(GateBlocked, "consecutive_failure_limit_reached"):
            evaluate(payload)



class LoopAdmissionTests(unittest.TestCase):
    def test_loop_admission_requires_explicit_hold_and_budget_clear(self):
        good = {
            "allowed": True,
            "global_hold": {"clear": True, "value": "off", "blocked": False, "unresolved_operations": 0},
            "budget_guard": {"allowed": True, "status": "WARN"},
        }
        with patch.dict("os.environ", {
            "ORCA_CONTROL_API_URL": "https://control.example.test",
            "ORCA_LOOP_PREFLIGHT_TOKEN": "unit-test-token",
        }):
            with patch("scripts.distributed_loop_30m_gate.request_json", return_value=good):
                check_loop_admission()
            bad = dict(good)
            bad["budget_guard"] = {"allowed": False, "status": "STOP"}
            with patch("scripts.distributed_loop_30m_gate.request_json", return_value=bad):
                with self.assertRaisesRegex(GateBlocked, "orca_loop_admission_or_stop_latch_blocked"):
                    check_loop_admission()
            bad_hold = dict(good)
            bad_hold["global_hold"] = dict(good["global_hold"], unresolved_operations=1)
            with patch("scripts.distributed_loop_30m_gate.request_json", return_value=bad_hold):
                with self.assertRaisesRegex(GateBlocked, "orca_loop_admission_or_stop_latch_blocked"):
                    check_loop_admission()

class GateMainTests(unittest.TestCase):
    def test_blocked_gate_returns_nonzero_exit_status(self):
        with patch("scripts.distributed_loop_30m_gate.check_global_hold",
                   side_effect=GateBlocked("global_hold_active_or_unknown")):
            with patch("scripts.distributed_loop_30m_gate.write_outputs"):
                self.assertEqual(main(), 1)


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
        self.assertIn(".global_hold.unresolved_operations == 0", watcher)
        self.assertIn("--stop-file \"$STOP_FILE\"", workflow)


    def test_final_admission_is_rechecked_before_publish(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                    / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
        final_gate = workflow.split("id: final_admission", 1)[1].split("id: publish", 1)[0]
        self.assertIn("python scripts/distributed_loop_30m_gate.py", final_gate)
        self.assertIn("ORCA_30M_GATE_ALLOW:", final_gate)
        self.assertIn("steps.final_admission.outputs.allow == 'true'", workflow)
        self.assertIn("steps.final_admission.outputs.allow == 'true'", workflow.split("id: persist_recovery_ai", 1)[1].split("name: Advisory Creator-Critic", 1)[0])


if __name__ == "__main__":
    unittest.main()
