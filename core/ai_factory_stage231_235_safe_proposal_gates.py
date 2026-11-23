"""Stages 231-235: freshness, revalidation, safety policy, deduplication and review gates.

Deterministic proposal governance only. No work is scheduled or executed.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Mapping, Sequence


def _blocked(reason: str) -> dict:
    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": reason,
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }


def _parse_aware(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def stage231_evidence_freshness(*, evidence: Sequence[Mapping], evaluated_at: str,
                                max_age_seconds: int, held: bool = False):
    """Check evidence timestamps against an explicit evaluation time and age bound."""
    if held:
        return _blocked("HOLD is active")
    now = _parse_aware(evaluated_at)
    if now is None or not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds < 0:
        return _blocked("invalid evaluation time or maximum age")
    if not evidence:
        return _blocked("no evidence supplied")
    ages = []
    ids = set()
    for item in evidence:
        eid = item.get("evidence_id")
        observed = _parse_aware(item.get("observed_at"))
        if not eid or eid in ids or observed is None:
            return _blocked("missing/duplicate evidence ID or timezone-aware timestamp")
        ids.add(eid)
        age = (now - observed).total_seconds()
        if age < 0:
            return _blocked("evidence timestamp is in the future")
        ages.append(age)
    stale = [eid for eid, age in zip((x.get("evidence_id") for x in evidence), ages) if age > max_age_seconds]
    return {
        "status": "EVIDENCE_STALE" if stale else "EVIDENCE_FRESH",
        "evidence_count": len(evidence),
        "max_observed_age_seconds": max(ages),
        "stale_evidence_ids": stale,
        "evaluated_at": now.isoformat(),
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }


def stage232_revalidate_evidence(*, expected_digests: Mapping, actual_digests: Mapping,
                                 signature_verified: bool, held: bool = False):
    """Compare caller-supplied digest maps; cryptographic verification is external."""
    if held:
        return _blocked("HOLD is active")
    if not isinstance(expected_digests, Mapping) or not expected_digests:
        return _blocked("expected digest manifest is empty or invalid")
    if not isinstance(actual_digests, Mapping) or set(expected_digests) != set(actual_digests):
        return _blocked("evidence reference set mismatch")
    if any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
           for k, v in expected_digests.items()):
        return _blocked("invalid expected digest manifest")
    if any(expected_digests[k] != actual_digests[k] for k in expected_digests):
        return _blocked("evidence digest mismatch")
    if signature_verified is not True:
        return _blocked("independent signature verification not confirmed")
    return {
        "status": "EVIDENCE_REVALIDATED",
        "reference_count": len(expected_digests),
        "digest_match": True,
        "signature_scope": "caller-asserted; cryptographic verification not performed here",
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }


def stage233_validate_safety_policy(*, policy: Mapping, held: bool = False):
    """Require explicit restrictive policy settings; missing values fail closed."""
    if held:
        return _blocked("HOLD is active")
    required = {
        "safety_gate": True,
        "approval_required": True,
        "auto_execute": False,
        "auto_train": False,
        "auto_model_mutation": False,
        "auto_merge": False,
        "auto_deploy": False,
        "hold_release_allowed": False,
    }
    if not isinstance(policy, Mapping):
        return _blocked("safety policy is missing or invalid")
    mismatches = [key for key, expected in required.items() if policy.get(key) is not expected]
    if mismatches:
        return _blocked("missing or permissive safety settings: " + ",".join(mismatches))
    return {
        "status": "RESTRICTIVE_SAFETY_POLICY_VALID",
        "validated_controls": sorted(required),
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }


def stage234_deduplicate_candidates(*, candidates: Sequence[Mapping], held: bool = False):
    """Create stable proposal fingerprints and retain one representative per identity."""
    if held:
        return _blocked("HOLD is active")
    if not candidates:
        return _blocked("no candidates supplied")
    seen, unique, duplicates = set(), [], []
    for candidate in candidates:
        category = candidate.get("category")
        action = candidate.get("proposed_action")
        target = candidate.get("target")
        if not all(isinstance(x, str) and x.strip() for x in (category, action, target)):
            return _blocked("candidate identity fields are required")
        canonical = json.dumps(
            {"category": category.strip().casefold(),
             "proposed_action": action.strip().casefold(),
             "target": target.strip().casefold()},
            sort_keys=True, separators=(",", ":"),
        )
        fingerprint = sha256(canonical.encode("utf-8")).hexdigest()
        if fingerprint in seen:
            duplicates.append(fingerprint)
            continue
        seen.add(fingerprint)
        unique.append({**dict(candidate), "proposal_fingerprint": fingerprint})
    return {
        "status": "CANDIDATES_DEDUPLICATED",
        "unique_candidates": unique,
        "duplicate_fingerprints": duplicates,
        "input_count": len(candidates),
        "unique_count": len(unique),
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }


def stage235_prepare_review_gate(*, freshness: Mapping, revalidation: Mapping,
                                 safety: Mapping, deduplication: Mapping,
                                 held: bool = False):
    """Assemble a human-review package; never grants execution authority."""
    if held:
        return _blocked("HOLD is active")
    expected = {
        "freshness": (freshness, {"EVIDENCE_FRESH"}),
        "revalidation": (revalidation, {"EVIDENCE_REVALIDATED"}),
        "safety": (safety, {"RESTRICTIVE_SAFETY_POLICY_VALID"}),
        "deduplication": (deduplication, {"CANDIDATES_DEDUPLICATED"}),
    }
    failed = [name for name, (result, statuses) in expected.items()
              if not isinstance(result, Mapping) or result.get("status") not in statuses]
    if failed:
        return _blocked("review gate prerequisites failed: " + ",".join(failed))
    candidates = deduplication.get("unique_candidates")
    if not isinstance(candidates, list):
        return _blocked("deduplicated candidate list is invalid")
    return {
        "status": "READY_FOR_SEPARATE_HUMAN_REVIEW" if candidates else "NO_REVIEWABLE_CANDIDATES",
        "candidate_count": len(candidates),
        "candidate_fingerprints": [c.get("proposal_fingerprint") for c in candidates],
        "required_next_step": "separate explicit approval outside this module",
        "authority": "review package only; no execution or state transition authority",
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }
