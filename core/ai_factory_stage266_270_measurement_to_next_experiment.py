"""Stages 266-270: evidence custody, runtime fingerprinting and proposal-only iteration.

The module verifies supplied bytes and append-only structures, captures selected
facts of the current Python process, aggregates per-domain evidence, and ranks
replication-backed proposals. It never executes experiments or changes models.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
import os
import platform
import sys
from collections.abc import Mapping, Sequence

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
    return isinstance(value, str) and len(value) == 64 and all(ch in _HEX for ch in value)


def _json_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _json_digest(result)
    return result


def _valid_seal(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(key) is not value for key, value in _FALSE.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    body = {key: value for key, value in result.items() if key != "result_digest"}
    try:
        return claimed == _json_digest(body)
    except (TypeError, ValueError):
        return False


def stage266_build_task_bank_manifest(*, tasks: Sequence[Mapping],
                                      minimum_per_domain: int = 5,
                                      held: bool = False):
    """Hash actual task payload bytes and build a deterministic task-bank manifest."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)) or not tasks
            or isinstance(minimum_per_domain, bool) or not isinstance(minimum_per_domain, int)
            or minimum_per_domain < 1):
        return _blocked("non-empty tasks and positive per-domain minimum are required")
    seen, entries, counts = set(), [], {}
    for task in tasks:
        if not isinstance(task, Mapping):
            return _blocked("each task must be a mapping")
        task_id, domain, payload = task.get("task_id"), task.get("domain"), task.get("payload")
        if (not isinstance(task_id, str) or not task_id.strip() or task_id in seen
                or not isinstance(domain, str) or not domain.strip()
                or not isinstance(payload, bytes) or not payload):
            return _blocked("task IDs, domains and non-empty raw payload bytes are required")
        seen.add(task_id)
        counts[domain] = counts.get(domain, 0) + 1
        entries.append({
            "task_id": task_id, "domain": domain,
            "payload_sha256": sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
        })
    if any(count < minimum_per_domain for count in counts.values()):
        return _blocked("one or more domains fail the minimum task count")
    entries.sort(key=lambda item: item["task_id"])
    manifest = {
        "format": "ai-factory-task-bank-v1",
        "task_count": len(entries),
        "domain_counts": dict(sorted(counts.items())),
        "entries": entries,
    }
    return _seal({
        "status": "TASK_BANK_MANIFEST_BUILT",
        "manifest": manifest,
        "task_bank_digest": _json_digest(manifest),
    })


def stage267_validate_preregistration_ledger(*, events: Sequence[Mapping],
                                              held: bool = False):
    """Verify a contiguous, hash-linked event ledger with timezone-aware timestamps."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
        return _blocked("a non-empty event ledger is required")
    previous = "0" * 64
    normalized = []
    for index, event in enumerate(events, start=1):
        if not isinstance(event, Mapping):
            return _blocked("each ledger event must be a mapping")
        sequence = event.get("sequence")
        event_type = event.get("event_type")
        payload_digest = event.get("payload_digest")
        actor_id = event.get("actor_id")
        timestamp = event.get("timestamp")
        previous_digest = event.get("previous_digest")
        claimed_digest = event.get("event_digest")
        if (isinstance(sequence, bool) or sequence != index
                or not isinstance(event_type, str) or not event_type.strip()
                or not _digest(payload_digest)
                or not isinstance(actor_id, str) or not actor_id.strip()
                or not isinstance(timestamp, str) or not _digest(previous_digest)
                or previous_digest != previous):
            return _blocked("ledger sequence, identity, payload, timestamp or chain link is invalid")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return _blocked("ledger timestamp must be ISO-8601")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return _blocked("ledger timestamp must include timezone")
        body = {
            "sequence": sequence, "event_type": event_type,
            "payload_digest": payload_digest, "actor_id": actor_id,
            "timestamp": timestamp, "previous_digest": previous_digest,
        }
        actual = _json_digest(body)
        if claimed_digest != actual:
            return _blocked("event digest mismatch")
        normalized.append({**body, "event_digest": actual})
        previous = actual
    return _seal({
        "status": "PREREGISTRATION_LEDGER_VALIDATED",
        "event_count": len(normalized),
        "ledger_head_digest": previous,
        "events": normalized,
        "trusted_timestamping": False,
    })


def stage268_capture_runtime_fingerprint(*, runtime_config: Mapping,
                                         held: bool = False):
    """Capture selected live Python/runtime facts and bind them to a config digest."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(runtime_config, Mapping) or not runtime_config:
        return _blocked("non-empty runtime configuration is required")
    try:
        config_digest = _json_digest(runtime_config)
    except (TypeError, ValueError):
        return _blocked("runtime configuration must be canonical JSON data")
    facts = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_cache_tag": getattr(sys.implementation, "cache_tag", None),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "byteorder": sys.byteorder,
        "float_mantissa_bits": sys.float_info.mant_dig,
        "runtime_config_digest": config_digest,
    }
    return _seal({
        "status": "RUNTIME_FINGERPRINT_CAPTURED",
        "runtime_facts": facts,
        "runtime_fingerprint_digest": _json_digest(facts),
        "capture_scope": "current Python process; model/runtime internals not introspected",
    })


def stage269_aggregate_domain_evidence(*, domain_results: Sequence[Mapping],
                                       minimum_pairs_per_domain: int = 30,
                                       held: bool = False):
    """Require each domain to pass its own paired lower-bound gate; do not hide regressions."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_results, Sequence) or isinstance(domain_results, (str, bytes))
            or not domain_results
            or isinstance(minimum_pairs_per_domain, bool)
            or not isinstance(minimum_pairs_per_domain, int) or minimum_pairs_per_domain < 1):
        return _blocked("domain results and a positive per-domain sample minimum are required")
    seen, rows = set(), []
    for row in domain_results:
        if not isinstance(row, Mapping):
            return _blocked("each domain result must be a mapping")
        domain, count = row.get("domain"), row.get("sample_count")
        lower, threshold = row.get("adjusted_lower_bound"), row.get("minimum_gain")
        observations_digest = row.get("observations_digest")
        protocol_family_digest = row.get("protocol_family_digest")
        if (not isinstance(domain, str) or not domain.strip() or domain in seen
                or isinstance(count, bool) or not isinstance(count, int) or count < minimum_pairs_per_domain
                or not isinstance(lower, (int, float)) or isinstance(lower, bool) or not math.isfinite(lower)
                or not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(threshold)
                or threshold < 0 or not _digest(observations_digest) or not _digest(protocol_family_digest)):
            return _blocked("malformed domain evidence or insufficient sample count")
        if lower <= threshold:
            return _blocked("at least one domain does not exceed its practical gain threshold")
        seen.add(domain)
        rows.append({
            "domain": domain, "sample_count": count,
            "adjusted_lower_bound": float(lower), "minimum_gain": float(threshold),
            "observations_digest": observations_digest, "protocol_family_digest": protocol_family_digest,
        })
    rows.sort(key=lambda item: item["domain"])
    protocol_digests = {row["protocol_family_digest"] for row in rows}
    if len(protocol_digests) != 1:
        return _blocked("domain evidence must share one preregistered protocol digest")
    return _seal({
        "status": "MULTI_DOMAIN_CAPABILITY_GAIN_SUPPORTED",
        "domain_count": len(rows),
        "domains": rows,
        "macro_mean_lower_bound": sum(row["adjusted_lower_bound"] for row in rows) / len(rows),
        "worst_domain_lower_bound": min(row["adjusted_lower_bound"] for row in rows),
        "all_domains_passed": True,
        "protocol_family_digest": next(iter(protocol_digests)),
    })


def stage270_rank_next_experiment_proposals(*, candidates: Sequence[Mapping],
                                            held: bool = False):
    """Rank only replication-backed, all-domain-positive proposals; never execute them."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates:
        return _blocked("non-empty candidate list is required")
    seen, eligible = set(), []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return _blocked("each candidate must be a mapping")
        candidate_id = candidate.get("candidate_id")
        multidomain = candidate.get("multi_domain_evidence")
        replication = candidate.get("replication_evidence")
        if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in seen:
            return _blocked("candidate IDs must be unique non-empty strings")
        seen.add(candidate_id)
        if (not _valid_seal(multidomain, "MULTI_DOMAIN_CAPABILITY_GAIN_SUPPORTED")
                or not _valid_seal(replication, "INDEPENDENT_REPLICATION_DECLARED")
                or replication.get("rsi_or_asi_demonstrated") is not False
                or multidomain.get("protocol_family_digest") != replication.get("protocol_family_digest")):
            continue
        eligible.append({
            "candidate_id": candidate_id,
            "macro_mean_lower_bound": multidomain["macro_mean_lower_bound"],
            "worst_domain_lower_bound": multidomain["worst_domain_lower_bound"],
            "replication_digest": replication["result_digest"],
            "multi_domain_digest": multidomain["result_digest"],
            "next_step": "PROPOSAL_FOR_SEPARATE_REVIEW",
        })
    eligible.sort(key=lambda item: (-item["worst_domain_lower_bound"],
                                    -item["macro_mean_lower_bound"], item["candidate_id"]))
    return _seal({
        "status": "NEXT_EXPERIMENT_PROPOSALS_RANKED",
        "eligible_count": len(eligible),
        "proposals": eligible,
        "execution_authorized": False,
        "selection_rule": "replicated evidence first; rank by worst-domain then macro-mean lower bound",
    })
