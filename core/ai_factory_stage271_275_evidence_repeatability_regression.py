"""Stages 271-275: evidence provenance, repeated replication and regression guards.

Receipts and identities remain caller-supplied declarations unless a separately
trusted signature/transparency service is integrated. These stages never execute
experiments, mutate models, release HOLD, merge, or deploy.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
import json
import math

_FALSE = {
    "proposal_only": True,
    "task_execution_authorized": False,
    "experiment_execution_authorized": False,
    "model_change_authorized": False,
    "merge_deploy_authorized": False,
    "hold_release_authorized": False,
}
_HEX = set("0123456789abcdef")


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX for c in value)


def _canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _canonical_digest(result)
    return result


def _valid_seal(result, expected_status):
    if not isinstance(result, Mapping) or result.get("status") != expected_status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    try:
        return claimed == _canonical_digest({k: v for k, v in result.items() if k != "result_digest"})
    except (TypeError, ValueError):
        return False


def _aware_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def stage271_validate_task_bank_custody_receipt(*, receipt: Mapping, expected_manifest_digest: str,
                                                 held: bool = False):
    """Check receipt structure/linkage; deliberately do not claim external authentication."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(receipt, Mapping) or not _digest(expected_manifest_digest):
        return _blocked("receipt and expected task-bank digest are required")
    receipt_id = receipt.get("receipt_id")
    authority_id = receipt.get("custody_authority_id")
    manifest_digest = receipt.get("task_bank_digest")
    received_at = receipt.get("received_at")
    receipt_digest = receipt.get("receipt_digest")
    if (not isinstance(receipt_id, str) or not receipt_id.strip()
            or not isinstance(authority_id, str) or not authority_id.strip()
            or manifest_digest != expected_manifest_digest
            or not _aware_timestamp(received_at)):
        return _blocked("receipt identity, manifest linkage or timezone-aware receipt time is invalid")
    body = {
        "receipt_id": receipt_id, "custody_authority_id": authority_id,
        "task_bank_digest": manifest_digest, "received_at": received_at,
    }
    try:
        actual = _canonical_digest(body)
    except (TypeError, ValueError):
        return _blocked("receipt fields are not canonical JSON")
    if receipt_digest != actual:
        return _blocked("receipt digest mismatch")
    return _seal({
        "status": "TASK_BANK_CUSTODY_RECEIPT_STRUCTURALLY_VALIDATED",
        **body, "receipt_digest": actual,
        "external_authentication_verified": False,
        "trusted_timestamping_verified": False,
        "verification_scope": "structure and content linkage only",
    })


def stage272_validate_execution_evidence_receipt(*, receipt: Mapping,
                                                  expected_task_bank_digest: str,
                                                  expected_runtime_digest: str,
                                                  held: bool = False):
    """Bind execution evidence to task bank/runtime while separating observed and declared fields."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(receipt, Mapping) or not _digest(expected_task_bank_digest) or not _digest(expected_runtime_digest):
        return _blocked("receipt and expected task-bank/runtime digests are required")
    required_digests = {
        "input_digest": receipt.get("input_digest"),
        "output_digest": receipt.get("output_digest"),
        "model_config_digest": receipt.get("model_config_digest"),
        "task_bank_digest": receipt.get("task_bank_digest"),
        "runtime_fingerprint_digest": receipt.get("runtime_fingerprint_digest"),
    }
    if any(not _digest(v) for v in required_digests.values()):
        return _blocked("all execution evidence digests must be lowercase SHA-256")
    if (required_digests["task_bank_digest"] != expected_task_bank_digest
            or required_digests["runtime_fingerprint_digest"] != expected_runtime_digest):
        return _blocked("execution evidence does not match expected task bank/runtime")
    run_id = receipt.get("run_id")
    observed = receipt.get("observed_fields")
    declared = receipt.get("declared_fields")
    if (not isinstance(run_id, str) or not run_id.strip()
            or not isinstance(observed, Sequence) or isinstance(observed, (str, bytes))
            or not isinstance(declared, Sequence) or isinstance(declared, (str, bytes))):
        return _blocked("run ID and explicit observed/declared field lists are required")
    if (any(not isinstance(x, str) or not x.strip() for x in [*observed, *declared])
            or set(observed) & set(declared)):
        return _blocked("observed and declared fields must be valid and disjoint")
    if not observed:
        return _blocked("at least one observed field is required")
    normalized = {
        "run_id": run_id, **required_digests,
        "observed_fields": sorted(set(observed)),
        "declared_fields": sorted(set(declared)),
    }
    return _seal({
        "status": "EXECUTION_EVIDENCE_RECEIPT_LINKED",
        **normalized,
        "observed_field_count": len(normalized["observed_fields"]),
        "declared_field_count": len(normalized["declared_fields"]),
        "external_authentication_verified": False,
        "execution_independently_attested": False,
    })


def stage273_validate_multi_round_replication(*, rounds: Sequence[Mapping],
                                               minimum_rounds: int = 3,
                                               held: bool = False):
    """Require repeated positive rounds with distinct task sets and evaluator declarations."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(rounds, Sequence) or isinstance(rounds, (str, bytes))
            or isinstance(minimum_rounds, bool) or not isinstance(minimum_rounds, int)
            or minimum_rounds < 3 or len(rounds) < minimum_rounds):
        return _blocked("at least three declared replication rounds are required")
    seen_rounds, task_sets, evaluators, normalized = set(), set(), set(), []
    protocol = None
    for item in rounds:
        if not isinstance(item, Mapping):
            return _blocked("each replication round must be a mapping")
        round_id, task_digest, evaluator_id = item.get("round_id"), item.get("task_set_digest"), item.get("evaluator_id")
        protocol_digest, evidence_digest = item.get("protocol_digest"), item.get("evidence_digest")
        if (not isinstance(round_id, str) or not round_id.strip() or round_id in seen_rounds
                or not isinstance(evaluator_id, str) or not evaluator_id.strip()
                or not _digest(task_digest) or not _digest(protocol_digest) or not _digest(evidence_digest)
                or item.get("positive_gate") is not True):
            return _blocked("round identity, digests or positive gate are invalid")
        if protocol is None:
            protocol = protocol_digest
        if protocol_digest != protocol:
            return _blocked("all rounds must use the same preregistered protocol")
        if task_digest in task_sets or evaluator_id in evaluators:
            return _blocked("task sets and evaluator declarations must be distinct across rounds")
        seen_rounds.add(round_id)
        task_sets.add(task_digest)
        evaluators.add(evaluator_id)
        normalized.append({
            "round_id": round_id, "task_set_digest": task_digest,
            "evaluator_id": evaluator_id, "protocol_digest": protocol_digest,
            "evidence_digest": evidence_digest,
        })
    normalized.sort(key=lambda x: x["round_id"])
    return _seal({
        "status": "MULTI_ROUND_REPLICATION_DECLARED",
        "round_count": len(normalized), "rounds": normalized,
        "protocol_digest": protocol, "all_rounds_positive": True,
        "independent_institution_verified": False,
        "rsi_or_asi_demonstrated": False,
    })


def stage274_detect_capability_regression(*, baseline: Mapping, candidate: Mapping,
                                           allowed_regression: float = 0.0,
                                           held: bool = False):
    """Fail closed on missing domains, uncertain inputs, or a material per-domain regression."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _valid_seal(baseline, "MULTI_DOMAIN_CAPABILITY_GAIN_SUPPORTED")
            or not _valid_seal(candidate, "MULTI_DOMAIN_CAPABILITY_GAIN_SUPPORTED")
            or isinstance(allowed_regression, bool)
            or not isinstance(allowed_regression, (int, float))
            or not math.isfinite(allowed_regression) or allowed_regression < 0):
        return _blocked("sealed baseline/candidate evidence and non-negative regression tolerance are required")
    base_rows = {row.get("domain"): row for row in baseline.get("domains", []) if isinstance(row, Mapping)}
    cand_rows = {row.get("domain"): row for row in candidate.get("domains", []) if isinstance(row, Mapping)}
    if not base_rows or set(base_rows) != set(cand_rows):
        return _blocked("baseline and candidate must contain the exact same non-empty domains")
    comparisons, regressions = [], []
    for domain in sorted(base_rows):
        before, after = base_rows[domain], cand_rows[domain]
        old, new = before.get("adjusted_lower_bound"), after.get("adjusted_lower_bound")
        threshold = after.get("minimum_gain")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               for x in (old, new, threshold)):
            return _blocked("domain lower bounds and practical-gain thresholds must be finite")
        delta = float(new) - float(old)
        row = {"domain": domain, "baseline_lower_bound": float(old),
               "candidate_lower_bound": float(new), "lower_bound_delta": delta,
               "minimum_gain": float(threshold)}
        comparisons.append(row)
        if new < threshold or delta < -allowed_regression:
            regressions.append(domain)
    return _seal({
        "status": "CAPABILITY_REGRESSION_DETECTED" if regressions else "CAPABILITY_REGRESSION_GUARD_PASSED",
        "domain_comparisons": comparisons, "regressed_domains": regressions,
        "regression_detected": bool(regressions),
        "allowed_regression": float(allowed_regression),
        "baseline_digest": baseline["result_digest"],
        "candidate_digest": candidate["result_digest"],
    })


def stage275_generate_research_plan(*, regression_guard: Mapping, candidates: Sequence[Mapping],
                                    maximum_cost_units: float, held: bool = False):
    """Rank proposal-only research actions by declared information value, weakness and cost."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _valid_seal(regression_guard, "CAPABILITY_REGRESSION_GUARD_PASSED")
            or not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates
            or isinstance(maximum_cost_units, bool) or not isinstance(maximum_cost_units, (int, float))
            or not math.isfinite(maximum_cost_units) or maximum_cost_units <= 0):
        return _blocked("a passed regression guard, candidates and positive cost ceiling are required")
    seen, ranked = set(), []
    weak_domains = sorted(
        regression_guard["domain_comparisons"],
        key=lambda x: (x["candidate_lower_bound"], x["domain"]),
    )
    for item in candidates:
        if not isinstance(item, Mapping):
            return _blocked("each research candidate must be a mapping")
        candidate_id, domain = item.get("candidate_id"), item.get("target_domain")
        gain, uncertainty, cost = item.get("expected_information_gain"), item.get("uncertainty"), item.get("estimated_cost_units")
        rationale = item.get("rationale")
        if (not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in seen
                or not isinstance(domain, str) or domain not in {x["domain"] for x in weak_domains}
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in (gain, uncertainty, cost))
                or gain <= 0 or not 0 <= uncertainty <= 1 or cost <= 0
                or not isinstance(rationale, str) or not rationale.strip()):
            return _blocked("candidate fields, target domain, gain, uncertainty or cost are invalid")
        seen.add(candidate_id)
        if cost > maximum_cost_units:
            continue
        weakness_rank = next(i for i, row in enumerate(weak_domains) if row["domain"] == domain)
        priority = (gain * (1.0 + weakness_rank / max(1, len(weak_domains)))) / (cost * (1.0 + uncertainty))
        ranked.append({
            "candidate_id": candidate_id, "target_domain": domain,
            "expected_information_gain": float(gain), "uncertainty": float(uncertainty),
            "estimated_cost_units": float(cost), "priority_score": priority,
            "rationale": rationale,
            "next_step": "PROPOSAL_FOR_SEPARATE_REVIEW",
        })
    ranked.sort(key=lambda x: (-x["priority_score"], x["candidate_id"]))
    return _seal({
        "status": "NEXT_RESEARCH_PLAN_PROPOSED",
        "proposal_count": len(ranked), "proposals": ranked,
        "weak_domain_order": [x["domain"] for x in weak_domains],
        "maximum_cost_units": float(maximum_cost_units),
        "plan_is_executable": False,
        "execution_authorized": False,
    })
