#!/usr/bin/env python3
"""Fail-closed 30-minute distributed-loop safety gate."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

# Schema v2 models every independently limited dimension for the current
# Workers/Pages + D1 + SQLite Durable Objects + GitHub Actions footprint.
# If the signed product inventory discovers another enabled product, fail closed
# until its complete meter set is added here.
REQUIRED_METERS = {
    "cloudflare.workers.requests.daily": ("cloudflare", "workers"),
    "cloudflare.workers_logs.events.daily": ("cloudflare", "workers_logs"),
    "cloudflare.d1.rows_read.daily": ("cloudflare", "d1"),
    "cloudflare.d1.rows_written.daily": ("cloudflare", "d1"),
    "cloudflare.d1.storage_bytes.total": ("cloudflare", "d1"),
    "cloudflare.durable_objects.requests.daily": ("cloudflare", "durable_objects"),
    "cloudflare.durable_objects.duration_gb_seconds.daily": ("cloudflare", "durable_objects"),
    "cloudflare.durable_objects.sqlite_rows_read.daily": ("cloudflare", "durable_objects"),
    "cloudflare.durable_objects.sqlite_rows_written.daily": ("cloudflare", "durable_objects"),
    "cloudflare.durable_objects.sqlite_storage_bytes.total": ("cloudflare", "durable_objects"),
    "github.actions.compute_cost_usd.monthly": ("github", "actions"),
    "github.actions.artifact_storage_bytes.monthly": ("github", "actions"),
}
REQUIRED_PRODUCTS = frozenset({
    "workers", "workers_logs", "d1", "durable_objects", "actions",
})
METER_UNITS = {
    "cloudflare.workers.requests.daily": "requests",
    "cloudflare.workers_logs.events.daily": "events",
    "cloudflare.d1.rows_read.daily": "rows",
    "cloudflare.d1.rows_written.daily": "rows",
    "cloudflare.d1.storage_bytes.total": "bytes",
    "cloudflare.durable_objects.requests.daily": "requests",
    "cloudflare.durable_objects.duration_gb_seconds.daily": "GB-seconds",
    "cloudflare.durable_objects.sqlite_rows_read.daily": "rows",
    "cloudflare.durable_objects.sqlite_rows_written.daily": "rows",
    "cloudflare.durable_objects.sqlite_storage_bytes.total": "bytes",
    "github.actions.compute_cost_usd.monthly": "USD",
    "github.actions.artifact_storage_bytes.monthly": "bytes",
}
MAX_SNAPSHOT_AGE = timedelta(minutes=10)
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_ATTESTATION_LIFETIME = timedelta(minutes=15)
MIN_SLOT_INTERVAL = timedelta(minutes=30)


class GateBlocked(RuntimeError):
    pass


def parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GateBlocked("timestamp_missing_or_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GateBlocked("timestamp_missing_or_invalid") from None
    if parsed.tzinfo is None:
        raise GateBlocked("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    unsigned = dict(payload)
    attestation = dict(unsigned.get("attestation") or {})
    attestation.pop("signature", None)
    unsigned["attestation"] = attestation
    try:
        return json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise GateBlocked("budget_attestation_payload_not_canonicalizable") from None


def verify_budget_attestation(
    payload: Any, *, now: datetime, secret: str,
    expected_account_id: str, trusted_collector_id: str,
) -> None:
    """Verify a collector HMAC and bounded freshness before trusting any limits."""
    if not isinstance(payload, dict) or not isinstance(payload.get("attestation"), dict):
        raise GateBlocked("budget_attestation_missing")
    if not secret or not expected_account_id or not trusted_collector_id:
        raise GateBlocked("budget_attestation_trust_configuration_missing")
    attestation = payload["attestation"]
    signature = attestation.get("signature")
    if (attestation.get("algorithm") != "hmac-sha256"
            or attestation.get("account_id") != expected_account_id
            or attestation.get("collector_id") != trusted_collector_id
            or not isinstance(signature, str) or len(signature) != 64):
        raise GateBlocked("budget_attestation_identity_invalid")
    try:
        int(signature, 16)
    except ValueError:
        raise GateBlocked("budget_attestation_signature_invalid") from None
    expected = hmac.new(secret.encode("utf-8"), _canonical_payload(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        raise GateBlocked("budget_attestation_signature_invalid")

    now = now.astimezone(timezone.utc)
    issued_at = parse_time(attestation.get("issued_at"))
    expires_at = parse_time(attestation.get("expires_at"))
    if (issued_at > now + MAX_FUTURE_SKEW or issued_at > expires_at
            or expires_at <= now or expires_at - issued_at > MAX_ATTESTATION_LIFETIME
            or now - issued_at > MAX_SNAPSHOT_AGE):
        raise GateBlocked("budget_attestation_stale_or_out_of_window")


def evaluate_budget_snapshot(
    payload: Any, *, now: datetime, attestation_secret: str = "",
    expected_account_id: str = "", trusted_collector_id: str = "",
    expected_github_account_id: str = "",
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("meters"), list):
        raise GateBlocked("budget_meter_inventory_v2_missing")
    verify_budget_attestation(
        payload, now=now, secret=attestation_secret,
        expected_account_id=expected_account_id,
        trusted_collector_id=trusted_collector_id,
    )
    if payload.get("schema_version") != 2:
        raise GateBlocked("budget_meter_schema_unsupported")

    attestation_issued_at = parse_time(payload["attestation"].get("issued_at"))
    now = now.astimezone(timezone.utc)
    inventory = payload.get("meter_inventory")
    if not isinstance(inventory, dict):
        raise GateBlocked("budget_product_inventory_missing")
    if (inventory.get("complete_account_coverage") is not True
            or inventory.get("unresolved_products") != []
            or inventory.get("cloudflare_account_id") != expected_account_id
            or inventory.get("github_account_id") != expected_github_account_id):
        raise GateBlocked("budget_product_inventory_incomplete")
    products = inventory.get("enabled_products")
    if (not isinstance(products, list)
            or any(not isinstance(x, str) for x in products)
            or len(products) != len(set(products))
            or set(products) != REQUIRED_PRODUCTS):
        raise GateBlocked("budget_product_inventory_unexpected_or_incomplete")
    inventory_observed = parse_time(inventory.get("observed_at"))
    inventory_watermark = parse_time(inventory.get("watermark_at"))
    if (inventory_watermark > inventory_observed
            or inventory_observed > attestation_issued_at + MAX_FUTURE_SKEW
            or inventory_observed > now + MAX_FUTURE_SKEW
            or inventory_watermark > now + MAX_FUTURE_SKEW
            or now - inventory_observed > MAX_SNAPSHOT_AGE
            or now - inventory_watermark > MAX_SNAPSHOT_AGE):
        raise GateBlocked("budget_product_inventory_stale_or_future")

    failures = payload.get("consecutive_failures")
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        raise GateBlocked("failure_counter_invalid")
    if failures >= 3:
        raise GateBlocked("consecutive_failure_limit_reached")

    by_id = {}
    for meter in payload["meters"]:
        if not isinstance(meter, dict):
            raise GateBlocked("budget_meter_invalid")
        meter_id = meter.get("meter_id")
        if not isinstance(meter_id, str) or not meter_id or meter_id in by_id:
            raise GateBlocked("budget_meter_identity_invalid")
        by_id[meter_id] = meter
    if set(by_id) != set(REQUIRED_METERS):
        raise GateBlocked("budget_meter_set_incomplete_or_unexpected")

    results = []
    for meter_id, (expected_provider, product_id) in REQUIRED_METERS.items():
        meter = by_id[meter_id]
        expected_account = expected_github_account_id if expected_provider == "github" else expected_account_id
        if (meter.get("provider") != expected_provider
                or meter.get("product_id") != product_id
                or meter.get("account_id") != expected_account
                or meter.get("enabled") is not True):
            raise GateBlocked("budget_meter_provider_product_or_account_invalid")
        if (meter.get("enforcement_eligible") is not True
                or meter.get("quality") != "exact"
                or meter.get("limit_verified") is not True
                or not isinstance(meter.get("limit_evidence_id"), str)
                or not meter["limit_evidence_id"].strip()):
            raise GateBlocked("budget_limit_not_authoritatively_verified")
        if (meter.get("unit") != METER_UNITS[meter_id]
                or not isinstance(meter.get("limit_source"), str) or not meter["limit_source"].strip()
                or not isinstance(meter.get("dataset"), str) or not meter["dataset"].strip()):
            raise GateBlocked("budget_meter_unit_dataset_or_limit_evidence_missing")
        if (meter.get("complete_account_coverage") is not True
                or meter.get("exact_counter") is not True
                or meter.get("sampling_mode") != "none"
                or meter.get("coverage_status") != "complete"):
            raise GateBlocked("budget_meter_coverage_or_exactness_unproven")
        used, limit = meter.get("used"), meter.get("limit")
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or isinstance(limit, bool) or not isinstance(limit, (int, float))
                or not math.isfinite(float(used)) or not math.isfinite(float(limit))
                or used < 0 or limit <= 0):
            raise GateBlocked("budget_values_invalid")
        observed = parse_time(meter.get("observed_at"))
        watermark = parse_time(meter.get("watermark_at"))
        if watermark > observed:
            raise GateBlocked("budget_watermark_after_observation")
        if observed > attestation_issued_at + MAX_FUTURE_SKEW:
            raise GateBlocked("budget_observation_after_attestation")
        period_start = parse_time(meter.get("period_start"))
        period_end = parse_time(meter.get("period_end"))
        if (observed > now + MAX_FUTURE_SKEW or now - observed > MAX_SNAPSHOT_AGE
                or watermark > now + MAX_FUTURE_SKEW or now - watermark > MAX_SNAPSHOT_AGE):
            raise GateBlocked("budget_snapshot_stale_or_future")
        if period_start >= period_end or not (period_start <= now < period_end):
            raise GateBlocked("budget_period_not_current")
        percent = float(used) / float(limit) * 100.0
        state = ("STOP" if percent >= 90 else "SUPPRESS" if percent >= 80
                 else "WARN" if percent >= 70 else "CLEAR")
        results.append({"meter_id": meter_id, "unit": meter["unit"],
                        "percent": percent, "status": state})
    rank = {"CLEAR": 0, "WARN": 1, "SUPPRESS": 2, "STOP": 3}
    worst = max(results, key=lambda row: rank[row["status"]])["status"]
    if worst in {"SUPPRESS", "STOP"}:
        raise GateBlocked("budget_" + worst.lower())
    return {"status": worst, "meters": results}

def attestation_account_id(payload: dict[str, Any]) -> str:
    return str(payload.get("attestation", {}).get("account_id", ""))


def decide_slot(runs: Any, *, current_run_id: str, now: datetime,
                minimum_interval: timedelta = MIN_SLOT_INTERVAL) -> tuple[bool, str]:
    if not isinstance(runs, list):
        return False, "workflow_run_history_invalid"
    previous = []
    for run in runs:
        if not isinstance(run, dict):
            return False, "workflow_run_history_invalid"
        if str(run.get("id", "")) == current_run_id:
            continue
        try:
            previous.append(parse_time(run.get("run_started_at") or run.get("created_at")))
        except GateBlocked:
            return False, "previous_run_timestamp_invalid"
    if not previous:
        return True, "first_slot"
    latest = max(previous)
    now = now.astimezone(timezone.utc)
    if latest > now + MAX_FUTURE_SKEW:
        return False, "previous_run_timestamp_in_future"
    if now - latest < minimum_interval:
        return False, "minimum_30_minute_interval_not_elapsed"
    return True, "slot_available"


def requires_slot_gate(event_name: str, continuation_depth: str) -> bool:
    return event_name == "schedule" or (
        event_name == "workflow_dispatch"
        and continuation_depth.isdigit()
        and int(continuation_depth) > 0
    )


def request_json(url: str, token: str, *, github: bool = False) -> Any:
    if not isinstance(url, str) or not url.startswith("https://") or not token:
        raise GateBlocked("required_endpoint_or_token_missing")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if github:
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read(1_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        raise GateBlocked("safety_endpoint_unavailable_or_invalid") from None


def check_global_hold() -> None:
    base = os.environ.get("ORCA_TASK_API_URL", "").rstrip("/")
    state = request_json(base + "/control/global-hold", os.environ.get("ORCA_TASK_API_TOKEN", ""))
    if (not isinstance(state, dict) or state.get("clear") is not True
            or state.get("value") != "off" or state.get("blocked") is not False):
        raise GateBlocked("global_hold_active_or_unknown")


def check_budget(now: datetime) -> dict[str, Any]:
    return evaluate_budget_snapshot(
        request_json(os.environ.get("ORCA_BUDGET_GATE_URL", ""),
                     os.environ.get("ORCA_BUDGET_GATE_TOKEN", "")),
        now=now,
        attestation_secret=os.environ.get("ORCA_BUDGET_EVIDENCE_HMAC_SECRET", ""),
        expected_account_id=os.environ.get("ORCA_BUDGET_EXPECTED_ACCOUNT_ID", ""),
        trusted_collector_id=os.environ.get("ORCA_BUDGET_TRUSTED_COLLECTOR_ID", ""),
        expected_github_account_id=os.environ.get("ORCA_GITHUB_BILLING_ACCOUNT_ID", ""),
    )


def check_slot(now: datetime) -> tuple[bool, str]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    current_run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not repo or "/" not in repo or not token or not current_run_id:
        return False, "github_run_context_missing"
    repo = urllib.parse.quote(repo, safe="/")
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
           "distributed-autonomous-loop.yml/runs?branch=main&per_page=100&exclude_pull_requests=true")
    payload = request_json(url, token, github=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        return False, "workflow_run_history_invalid"
    return decide_slot(payload["workflow_runs"], current_run_id=current_run_id, now=now)


def write_outputs(allow: bool, reason: str, detail: str = "") -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"allow={'true' if allow else 'false'}\nreason={reason}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Distributed Loop 30-minute safety gate\n\n")
            handle.write(f"- Decision: {'ALLOW' if allow else 'BLOCKED'}\n- Reason: {reason}\n")
            if detail:
                handle.write(f"- Budget: {detail}\n")
            handle.write("- No task was dispatched or executed by this gate.\n")


def main() -> int:
    now = datetime.now(timezone.utc)
    try:
        check_global_hold()
        budget = check_budget(now)
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        continuation_depth = os.environ.get("CONTINUATION_DEPTH", "0")
        if requires_slot_gate(event_name, continuation_depth):
            allow, reason = check_slot(now)
            if not allow:
                raise GateBlocked(reason)
        else:
            reason = "manual_trigger_passed_safety_gates"
        detail = ", ".join(f"{x['name']}={x['percent']:.1f}%/{x['status']}" for x in budget["sources"])
        write_outputs(True, reason, detail)
        print("ORCA_30M_GATE_ALLOW: " + reason)
    except GateBlocked as exc:
        write_outputs(False, str(exc))
        print("ORCA_30M_GATE_BLOCKED: " + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
