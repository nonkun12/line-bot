"""Reproducibility and independent replication declarations (Stages 611-620).

The validator checks metadata supplied by a caller. It does not execute experiments,
inspect artifacts, attest environments, or independently reproduce results.
"""
from __future__ import annotations

import math
from datetime import datetime


REQUIRED = (
    "experiment_ref", "protocol_ref", "primary_actor_ref", "environment_ref",
    "dependency_lock_ref", "input_refs", "command_refs", "run_records",
    "determinism_claim", "metric_name", "expected_value", "observed_value",
    "tolerance", "independent_replication", "replication_review_ref",
    "reviewer_ref", "review_status", "created_at", "automatic_rerun",
)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(value):
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text_list(value):
    return (
        isinstance(value, list) and bool(value)
        and all(_text(item) for item in value)
        and len(value) == len(set(value))
    )


def _runs_valid(value, environment_ref, input_refs, command_refs):
    if not isinstance(value, list) or len(value) < 2:
        return False
    run_ids = []
    for run in value:
        if not isinstance(run, dict):
            return False
        required = ("run_ref", "actor_ref", "environment_ref", "input_refs",
                    "command_refs", "result_ref", "started_at", "finished_at")
        if any(not _text(run.get(key)) for key in required):
            return False
        start, finish = _timestamp(run["started_at"]), _timestamp(run["finished_at"])
        if start is None or finish is None or finish < start:
            return False
        if run["environment_ref"] != environment_ref:
            return False
        if run["input_refs"] != input_refs or run["command_refs"] != command_refs:
            return False
        run_ids.append(run["run_ref"])
    return len(run_ids) == len(set(run_ids))


def validate_reproducibility(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    missing = [key for key in REQUIRED if key not in record or record[key] is None]
    issues = []
    for field in ("experiment_ref", "protocol_ref", "primary_actor_ref",
                  "environment_ref", "dependency_lock_ref", "metric_name",
                  "replication_review_ref", "reviewer_ref"):
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")

    inputs, commands = record.get("input_refs"), record.get("command_refs")
    if not _text_list(inputs):
        issues.append("input_refs_invalid")
    if not _text_list(commands):
        issues.append("command_refs_invalid")
    if not _runs_valid(record.get("run_records"), record.get("environment_ref"),
                       inputs, commands):
        issues.append("run_records_invalid")

    if record.get("determinism_claim") not in ("DETERMINISTIC_DECLARED",
                                                 "NONDETERMINISTIC_DECLARED"):
        issues.append("determinism_claim_invalid")
    if not _number(record.get("expected_value")):
        issues.append("expected_value_invalid")
    if not _number(record.get("observed_value")):
        issues.append("observed_value_invalid")
    if not _number(record.get("tolerance")) or record.get("tolerance", -1) < 0:
        issues.append("tolerance_invalid")
    if all(_number(record.get(k)) for k in ("expected_value", "observed_value", "tolerance")):
        if abs(record["observed_value"] - record["expected_value"]) > record["tolerance"]:
            issues.append("observed_value_outside_tolerance")

    replication = record.get("independent_replication")
    if not isinstance(replication, dict):
        issues.append("independent_replication_invalid")
    else:
        for field in ("replication_run_ref", "independent_actor_ref",
                      "environment_ref", "input_refs", "command_refs", "result_ref"):
            if not _text(replication.get(field)):
                issues.append(f"replication_{field}_invalid")
        if _text(record.get("primary_actor_ref")) and (
            replication.get("independent_actor_ref") == record.get("primary_actor_ref")
        ):
            issues.append("replication_actor_not_independent")
        if replication.get("environment_ref") != record.get("environment_ref"):
            issues.append("replication_environment_mismatch")
        if replication.get("input_refs") != inputs or replication.get("command_refs") != commands:
            issues.append("replication_protocol_mismatch")

    if record.get("review_status") != "INDEPENDENT_REVIEW_DECLARED_PASS":
        issues.append("independent_review_not_pass_declared")
    if record.get("automatic_rerun") is not False:
        issues.append("automatic_rerun_must_be_false")
    if _timestamp(record.get("created_at")) is None:
        issues.append("created_at_invalid")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
        "execution_performed": False,
        "environment_attested": False,
        "results_independently_reproduced": False,
        "reviewer_identity_authenticated": False,
    }


def stage_620_reproducibility_gate(record):
    result = validate_reproducibility(record)
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "READY_FOR_INDEPENDENT_REVIEW",
        "capability_gain_verified": False,
        "automatic_rerun": False,
        "execution_authorized": False,
        "release_authorized": False,
    }
