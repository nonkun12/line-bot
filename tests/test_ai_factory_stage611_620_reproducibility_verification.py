import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage611", Path(__file__).parents[1] /
    "core/ai_factory_stage611_620_reproducibility_verification.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "experiment_ref": "experiment-1",
        "protocol_ref": "protocol-1",
        "primary_actor_ref": "actor-primary",
        "environment_ref": "env-locked-1",
        "dependency_lock_ref": "lockfile-1",
        "input_refs": ["input-a"],
        "command_refs": ["command-a"],
        "run_records": [
            {"run_ref": "run-1", "actor_ref": "actor-primary",
             "environment_ref": "env-locked-1", "input_refs": ["input-a"],
             "command_refs": ["command-a"], "result_ref": "result-1",
             "started_at": "2026-11-23T10:00:00Z", "finished_at": "2026-11-23T10:01:00Z"},
            {"run_ref": "run-2", "actor_ref": "actor-primary",
             "environment_ref": "env-locked-1", "input_refs": ["input-a"],
             "command_refs": ["command-a"], "result_ref": "result-2",
             "started_at": "2026-11-23T10:02:00Z", "finished_at": "2026-11-23T10:03:00Z"},
        ],
        "determinism_claim": "DETERMINISTIC_DECLARED",
        "metric_name": "accuracy",
        "expected_value": 0.9,
        "observed_value": 0.91,
        "tolerance": 0.02,
        "independent_replication": {
            "replication_run_ref": "replication-1",
            "independent_actor_ref": "actor-independent",
            "environment_ref": "env-locked-1",
            "input_refs": ["input-a"], "command_refs": ["command-a"],
            "result_ref": "replication-result-1",
        },
        "replication_review_ref": "review-1",
        "reviewer_ref": "reviewer-1",
        "review_status": "INDEPENDENT_REVIEW_DECLARED_PASS",
        "created_at": "2026-11-23T10:10:00Z",
        "automatic_rerun": False,
    }


def test_complete_declarations_are_review_only_not_verified():
    result = m.stage_620_reproducibility_gate(good())
    assert result["status"] == "DECLARATIONS_COMPLETE"
    assert result["gate"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert result["execution_performed"] is False
    assert result["results_independently_reproduced"] is False
    assert result["capability_gain_verified"] is False
    assert result["automatic_rerun"] is False


def test_missing_and_incomplete_run_records_block():
    record = good()
    del record["dependency_lock_ref"]
    assert "dependency_lock_ref" in m.validate_reproducibility(record)["missing"]
    record = good()
    record["run_records"] = record["run_records"][:1]
    assert "run_records_invalid" in m.validate_reproducibility(record)["issues"]


def test_run_environment_inputs_commands_and_time_must_match():
    for field, value in (
        ("environment_ref", "different-env"),
        ("input_refs", ["other-input"]),
        ("command_refs", ["other-command"]),
        ("finished_at", "2026-11-23T09:59:00Z"),
    ):
        record = good()
        record["run_records"][0][field] = value
        assert m.validate_reproducibility(record)["status"] == "BLOCKED"


def test_independent_replication_requires_distinct_actor_and_same_protocol():
    record = good()
    record["independent_replication"]["independent_actor_ref"] = "actor-primary"
    assert "replication_actor_not_independent" in m.validate_reproducibility(record)["issues"]
    record = good()
    record["independent_replication"]["input_refs"] = ["different"]
    assert "replication_protocol_mismatch" in m.validate_reproducibility(record)["issues"]


def test_metric_tolerance_and_finite_numbers_are_enforced():
    record = good()
    record["observed_value"] = 1.0
    assert "observed_value_outside_tolerance" in m.validate_reproducibility(record)["issues"]
    record = good()
    record["expected_value"] = float("nan")
    assert "expected_value_invalid" in m.validate_reproducibility(record)["issues"]
    record = good()
    record["tolerance"] = -0.1
    assert "tolerance_invalid" in m.validate_reproducibility(record)["issues"]


def test_review_timestamp_and_rerun_policy_fail_closed():
    for field, value in (
        ("review_status", "PENDING"),
        ("created_at", "2026-11-23"),
        ("automatic_rerun", True),
    ):
        record = good()
        record[field] = value
        assert m.validate_reproducibility(record)["status"] == "BLOCKED"
