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

# Cloudflare meters are aligned with Budget Guardian; GitHub Actions is a
# separate platform meter and must be attested by the same trusted collector.
REQUIRED_SOURCES = (
    "cloudflare_workers",
    "cloudflare_d1",
    "cloudflare_durable_objects",
    "github_actions",
)
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
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise GateBlocked("budget_snapshot_missing")
    verify_budget_attestation(
        payload, now=now, secret=attestation_secret,
        expected_account_id=expected_account_id,
        trusted_collector_id=trusted_collector_id,
    )
    if payload.get("schema_version") != 1:
        raise GateBlocked("budget_snapshot_schema_invalid")
    failures = payload.get("consecutive_failures")
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        raise GateBlocked("failure_counter_invalid")
    if failures >= 3:
        raise GateBlocked("consecutive_failure_limit_reached")

    now = now.astimezone(timezone.utc)
    by_name = {}
    for source in payload["sources"]:
        if not isinstance(source, dict):
            raise GateBlocked("budget_source_invalid")
        name = source.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise GateBlocked("budget_source_identity_invalid")
        by_name[name] = source
    if set(by_name) != set(REQUIRED_SOURCES):
        raise GateBlocked("budget_source_set_incomplete_or_unexpected")

    results = []
    for name in REQUIRED_SOURCES:
        source = by_name[name]
        if source.get("enabled") is not True:
            raise GateBlocked("budget_source_not_confirmed_enabled")
        if (source.get("enforcement_eligible") is not True
                or source.get("quality") != "exact"
                or source.get("limit_verified") is not True
                or not isinstance(source.get("limit_evidence_id"), str)
                or not source["limit_evidence_id"].strip()):
            raise GateBlocked("budget_limit_not_authoritatively_verified")
        if (not isinstance(source.get("unit"), str) or not source["unit"].strip()
                or not isinstance(source.get("limit_source"), str) or not source["limit_source"].strip()
                or not isinstance(source.get("dataset"), str) or not source["dataset"].strip()):
            raise GateBlocked("budget_unit_dataset_or_limit_evidence_missing")
        expected_provider = "github" if name == "github_actions" else "cloudflare"
        expected_source_account = attestation_account_id(payload) if expected_provider == "cloudflare" else expected_github_account_id
        if (not expected_source_account or source.get("provider") != expected_provider
                or source.get("account_id") != expected_source_account
                or source.get("complete_account_coverage") is not True
                or source.get("exact_counter") is not True
                or source.get("sampling_mode") != "none"
                or source.get("coverage_status") != "complete"):
            raise GateBlocked("budget_source_coverage_or_exactness_unproven")
        used, limit = source.get("used"), source.get("limit")
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or isinstance(limit, bool) or not isinstance(limit, (int, float))
                or not math.isfinite(float(used)) or not math.isfinite(float(limit))
                or used < 0 or limit <= 0):
            raise GateBlocked("budget_values_invalid")
        observed = parse_time(source.get("observed_at"))
        watermark = parse_time(source.get("watermark_at"))
        period_start = parse_time(source.get("period_start"))
        period_end = parse_time(source.get("period_end"))
        if (observed > now + MAX_FUTURE_SKEW or now - observed > MAX_SNAPSHOT_AGE
                or watermark > now + MAX_FUTURE_SKEW or now - watermark > MAX_SNAPSHOT_AGE):
            raise GateBlocked("budget_snapshot_stale_or_future")
        if period_start >= period_end or not (period_start <= now < period_end):
            raise GateBlocked("budget_period_not_current")
        percent = float(used) / float(limit) * 100.0
        state = ("STOP" if percent >= 90 else "SUPPRESS" if percent >= 80
                 else "WARN" if percent >= 70 else "CLEAR")
        results.append({"name": name, "unit": source["unit"], "percent": percent, "status": state})
    rank = {"CLEAR": 0, "WARN": 1, "SUPPRESS": 2, "STOP": 3}
    worst = max(results, key=lambda row: rank[row["status"]])["status"]
    if worst in {"SUPPRESS", "STOP"}:
        raise GateBlocked("budget_" + worst.lower())
    return {"status": worst, "sources": results}


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
