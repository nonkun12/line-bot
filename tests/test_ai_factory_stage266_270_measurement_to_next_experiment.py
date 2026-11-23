import hashlib
import json

from core.ai_factory_stage266_270_measurement_to_next_experiment import (
    stage266_build_task_bank_manifest,
    stage267_validate_preregistration_ledger,
    stage268_capture_runtime_fingerprint,
    stage269_aggregate_domain_evidence,
    stage270_rank_next_experiment_proposals,
    _json_digest,
    _seal,
)


def test_266_hashes_actual_task_bytes_and_rejects_duplicate_ids():
    tasks = [
        {"task_id": "d1", "domain": "reasoning", "payload": b"task payload 1"},
        {"task_id": "d2", "domain": "reasoning", "payload": b"task payload 2"},
        {"task_id": "d3", "domain": "coding", "payload": b"task payload 3"},
        {"task_id": "d4", "domain": "coding", "payload": b"task payload 4"},
    ]
    result = stage266_build_task_bank_manifest(tasks=tasks, minimum_per_domain=2)
    assert result["status"] == "TASK_BANK_MANIFEST_BUILT"
    entry = next(x for x in result["manifest"]["entries"] if x["task_id"] == "d1")
    assert entry["payload_sha256"] == hashlib.sha256(b"task payload 1").hexdigest()
    assert result["manifest"]["domain_counts"] == {"coding": 2, "reasoning": 2}
    duplicate = [*tasks, dict(tasks[0])]
    assert stage266_build_task_bank_manifest(
        tasks=duplicate, minimum_per_domain=2
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_267_checks_hash_chain_sequence_and_timezone():
    payload = hashlib.sha256(b"preregistration").hexdigest()
    body = {
        "sequence": 1, "event_type": "preregister",
        "payload_digest": payload, "actor_id": "reviewer-a",
        "timestamp": "2026-11-23T08:00:00+00:00",
        "previous_digest": "0" * 64,
    }
    events = [{**body, "event_digest": _json_digest(body)}]
    result = stage267_validate_preregistration_ledger(events=events)
    assert result["status"] == "PREREGISTRATION_LEDGER_VALIDATED"
    assert result["trusted_timestamping"] is False
    broken = [{**events[0], "sequence": 2}]
    assert stage267_validate_preregistration_ledger(
        events=broken
    )["status"] == "INSUFFICIENT_EVIDENCE"
    naive = [{**body, "timestamp": "2026-11-23T08:00:00"}]
    naive[0]["event_digest"] = _json_digest(naive[0])
    assert stage267_validate_preregistration_ledger(
        events=naive
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_268_captures_runtime_facts_and_binds_config():
    result = stage268_capture_runtime_fingerprint(runtime_config={"precision": "fp32", "seed": 7})
    assert result["status"] == "RUNTIME_FINGERPRINT_CAPTURED"
    assert result["runtime_facts"]["python_version"]
    assert len(result["runtime_fingerprint_digest"]) == 64
    assert stage268_capture_runtime_fingerprint(
        runtime_config={"seed": object()}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_269_requires_each_domain_to_pass_individually():
    digest = hashlib.sha256(b"protocol family").hexdigest()
    domains = [{
        "domain": domain, "sample_count": 40, "adjusted_lower_bound": 0.12,
        "minimum_gain": 0.05,
        "observations_digest": hashlib.sha256(domain.encode()).hexdigest(),
        "protocol_family_digest": digest,
    } for domain in ("reasoning", "coding", "planning")]
    result = stage269_aggregate_domain_evidence(domain_results=domains)
    assert result["status"] == "MULTI_DOMAIN_CAPABILITY_GAIN_SUPPORTED"
    assert result["domain_count"] == 3
    assert result["worst_domain_lower_bound"] == 0.12
    regressed = [{**domains[0], "adjusted_lower_bound": 0.01}, *domains[1:]]
    assert stage269_aggregate_domain_evidence(
        domain_results=regressed
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_270_ranks_only_replication_backed_proposals_without_execution():
    family_digest = hashlib.sha256(b"protocol family").hexdigest()
    multi = stage269_aggregate_domain_evidence(domain_results=[{
        "domain": "reasoning", "sample_count": 40, "adjusted_lower_bound": 0.12,
        "minimum_gain": 0.05,
        "observations_digest": hashlib.sha256(b"observations").hexdigest(),
        "protocol_family_digest": family_digest,
    }])
    replication = _seal({
        "status": "INDEPENDENT_REPLICATION_DECLARED",
        "protocol_family_digest": family_digest,
        "rsi_or_asi_demonstrated": False,
    })
    ranked = stage270_rank_next_experiment_proposals(candidates=[
        {"candidate_id": "candidate-a", "multi_domain_evidence": multi,
         "replication_evidence": replication},
        {"candidate_id": "candidate-b", "multi_domain_evidence": multi,
         "replication_evidence": {"status": "INSUFFICIENT_EVIDENCE"}},
    ])
    assert ranked["status"] == "NEXT_EXPERIMENT_PROPOSALS_RANKED"
    assert ranked["eligible_count"] == 1
    assert ranked["proposals"][0]["candidate_id"] == "candidate-a"
    assert ranked["execution_authorized"] is False
    assert ranked["experiment_execution_authorized"] is False
