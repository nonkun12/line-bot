"""Fail-closed verifier for GitHub Actions-only budget evidence.

The verifier does not collect quota data. The HMAC key must be held by an
independent trusted collector; a workflow must never sign its own evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

COLLECTOR_ID = "orca-github-actions-budget-collector"
REQUIRED_SOURCES = ("github_actions",)
MAX_AGE = timedelta(minutes=10)
MAX_FUTURE_SKEW = timedelta(minutes=5)
WARN_PERCENT = 70
BLOCK_PERCENT = 80
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceRejected(ValueError):
    """Raised when budget evidence cannot safely authorize execution."""


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceRejected(f"{field}_missing_or_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceRejected(f"{field}_missing_or_invalid") from None
    if parsed.tzinfo is None:
        raise EvidenceRejected(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    try:
        return json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise EvidenceRejected("budget_evidence_not_canonicalizable") from None


def verify_github_actions_budget(
    payload: Any,
    key: str,
    now: datetime,
    *,
    expected_repository: str,
    expected_billing_account_id: str,
    min_remaining_minutes: int = 30,
) -> dict[str, Any]:
    """Verify a signed, repository/account-bound, exact GitHub Actions snapshot."""
    if not isinstance(payload, dict):
        raise EvidenceRejected("budget_snapshot_missing")
    if not isinstance(key, str) or len(key.encode("utf-8")) < 32:
        raise EvidenceRejected("budget_evidence_verification_key_missing")
    if not isinstance(expected_repository, str) or "/" not in expected_repository:
        raise EvidenceRejected("expected_repository_invalid")
    if not isinstance(expected_billing_account_id, str) or not expected_billing_account_id:
        raise EvidenceRejected("expected_billing_account_missing")
    if isinstance(min_remaining_minutes, bool) or not isinstance(min_remaining_minutes, int) or min_remaining_minutes < 1:
        raise EvidenceRejected("minimum_budget_reserve_invalid")
    if payload.get("schema_version") != 1 or payload.get("collector_id") != COLLECTOR_ID:
        raise EvidenceRejected("budget_evidence_collector_identity_invalid")
    if payload.get("repository") != expected_repository:
        raise EvidenceRejected("budget_evidence_repository_mismatch")
    if payload.get("billing_account_id") != expected_billing_account_id:
        raise EvidenceRejected("budget_evidence_billing_account_mismatch")

    signature = payload.get("signature")
    if not isinstance(signature, str) or not _HEX_64.fullmatch(signature):
        raise EvidenceRejected("budget_evidence_signature_missing_or_invalid")
    expected = hmac.new(key.encode("utf-8"), _canonical_payload(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise EvidenceRejected("budget_evidence_signature_invalid")

    if not isinstance(now, datetime) or now.tzinfo is None:
        raise EvidenceRejected("verification_time_timezone_missing")
    current = now.astimezone(timezone.utc)
    observed = _timestamp(payload.get("observed_at"), "observed_at")
    period_start = _timestamp(payload.get("period_start"), "period_start")
    period_end = _timestamp(payload.get("period_end"), "period_end")
    if observed > current + MAX_FUTURE_SKEW or current - observed > MAX_AGE:
        raise EvidenceRejected("budget_snapshot_stale_or_future")
    if period_start >= period_end or not period_start <= current < period_end:
        raise EvidenceRejected("budget_period_not_current")

    failures = payload.get("consecutive_failures")
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        raise EvidenceRejected("failure_counter_invalid")
    if failures >= 3:
        raise EvidenceRejected("consecutive_failure_limit_reached")

    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise EvidenceRejected("budget_sources_missing")
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceRejected("budget_source_invalid")
        name = row.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise EvidenceRejected("budget_source_identity_invalid")
        by_name[name] = row
    if set(by_name) != set(REQUIRED_SOURCES):
        raise EvidenceRejected("budget_source_set_incomplete_or_unexpected")

    source = by_name["github_actions"]
    if source.get("enabled") is not True:
        raise EvidenceRejected("github_actions_budget_source_not_enabled")
    if source.get("quality") != "exact" or source.get("coverage_complete") is not True:
        raise EvidenceRejected("github_actions_budget_coverage_not_exact")
    if source.get("exact_counter") is not True or source.get("sampling_mode") != "none":
        raise EvidenceRejected("github_actions_budget_counter_not_exact")
    if source.get("unit") != "minutes":
        raise EvidenceRejected("github_actions_budget_unit_invalid")
    if not isinstance(source.get("source_api"), str) or not source["source_api"].strip():
        raise EvidenceRejected("github_actions_budget_source_api_missing")
    if source.get("limit_source") != "verified_plan_included_minutes":
        raise EvidenceRejected("github_actions_budget_limit_not_verified")
    evidence_id = source.get("limit_evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        raise EvidenceRejected("github_actions_budget_limit_evidence_missing")
    resource_count = source.get("resource_count")
    if isinstance(resource_count, bool) or not isinstance(resource_count, int) or resource_count < 1:
        raise EvidenceRejected("github_actions_budget_resource_count_invalid")
    resource_digest = source.get("resource_digest")
    if not isinstance(resource_digest, str) or not _HEX_64.fullmatch(resource_digest):
        raise EvidenceRejected("github_actions_budget_resource_digest_invalid")

    used, limit = source.get("used"), source.get("limit")
    if isinstance(used, bool) or not isinstance(used, int) or used < 0:
        raise EvidenceRejected("github_actions_budget_used_invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or used > limit:
        raise EvidenceRejected("github_actions_budget_limit_invalid")
    watermark = _timestamp(source.get("source_watermark_at"), "source_watermark_at")
    if watermark > current + MAX_FUTURE_SKEW or current - watermark > MAX_AGE:
        raise EvidenceRejected("github_actions_budget_watermark_stale_or_future")

    remaining = limit - used
    if remaining < min_remaining_minutes:
        raise EvidenceRejected("github_actions_budget_reserve_insufficient")
    percent = (used * 100) // limit
    if percent >= BLOCK_PERCENT:
        raise EvidenceRejected("github_actions_budget_threshold_blocked")
    return {
        "status": "WARN" if percent >= WARN_PERCENT else "PASS",
        "source": "github_actions",
        "used_minutes": used,
        "limit_minutes": limit,
        "remaining_minutes": remaining,
        "used_percent": percent,
        "billing_account_id": expected_billing_account_id,
        "repository": expected_repository,
        "observed_at": observed.isoformat(),
    }
