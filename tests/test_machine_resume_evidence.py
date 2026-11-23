from datetime import datetime, timezone
import hashlib

from scripts.machine_resume_evidence import validate_machine_resume_evidence


NOW = datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc)
BASE = "a" * 40
TARGET = "b" * 40
RUN_ID = "45000000000"
ATTEMPT = 1
INSTRUCTION = "Add one bounded regression test and verify it with REA."
TASK = {
    "id": "machine-safe-test-001",
    "instruction": INSTRUCTION,
    "allowed_paths": ["tests/test_safe_boundary.py"],
    "execution_approved": True,
    "resume_policy": "machine_evidence",
}


def _evidence(**overrides):
    paths = ["tests/test_safe_boundary.py"]
    value = {
        "schema_version": 1,
        "task_id": TASK["id"],
        "instruction_sha256": hashlib.sha256(INSTRUCTION.encode()).hexdigest(),
        "allowed_paths_sha256": hashlib.sha256(
            b'["tests/test_safe_boundary.py"]'
        ).hexdigest(),
        "base_sha": BASE,
        "target_sha": TARGET,
        "evaluated_paths": paths,
        "scanner_complete": True,
        "scanner_status": "PASS",
        "tests_status": "PASS",
        "tests_exit_code": 0,
        "cause_status": "FIXED",
        "cause_evidence_sha256": "c" * 64,
        "workflow_run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "created_at": NOW.isoformat(),
        "nonce": "d" * 32,
    }
    value.update(overrides)
    return value


def _validate(task=TASK, evidence=None):
    return validate_machine_resume_evidence(
        task, _evidence() if evidence is None else evidence,
        expected_base_sha=BASE,
        expected_workflow_run_id=RUN_ID,
        expected_run_attempt=ATTEMPT,
        expected_nonce="d" * 32,
        now=NOW,
    )


def test_accepts_fresh_task_bound_machine_evidence():
    result = _validate()
    assert result["status"] == "PASS"
    assert result["eligible"] is True
    assert result["task_id"] == TASK["id"]


def test_rejects_task_without_machine_review_policy():
    task = {**TASK, "resume_policy": "human_review"}
    assert _validate(task=task)["reason_code"] == "resume_task_contract_invalid"


def test_rejects_legacy_instruction_requiring_human_review():
    task = {**TASK, "instruction": "人手レビュー後に実行する"}
    assert _validate(task=task)["reason_code"] == "resume_task_requires_human_review"


def test_rejects_wrong_task_or_instruction_binding():
    assert _validate(evidence=_evidence(task_id="other-task"))["eligible"] is False
    changed = {**TASK, "instruction": INSTRUCTION + " Change code."}
    assert _validate(task=changed)["eligible"] is False


def test_rejects_path_scope_mismatch():
    assert _validate(evidence=_evidence(evaluated_paths=["tests/other.py"]))["eligible"] is False
    assert _validate(evidence=_evidence(allowed_paths_sha256="e" * 64))["eligible"] is False


def test_rejects_wrong_base_or_invalid_target_sha():
    assert _validate(evidence=_evidence(base_sha="f" * 40))["eligible"] is False
    assert _validate(evidence=_evidence(target_sha="not-a-sha"))["eligible"] is False


def test_rejects_incomplete_scanner_or_failed_tests():
    assert _validate(evidence=_evidence(scanner_complete=False))["eligible"] is False
    assert _validate(evidence=_evidence(scanner_status="BLOCKED"))["eligible"] is False
    assert _validate(evidence=_evidence(tests_status="FAIL", tests_exit_code=1))["eligible"] is False
    assert _validate(evidence=_evidence(tests_exit_code=True))["eligible"] is False


def test_rejects_unfixed_or_unproven_cause():
    assert _validate(evidence=_evidence(cause_status="UNKNOWN"))["eligible"] is False
    assert _validate(evidence=_evidence(cause_evidence_sha256="invalid"))["eligible"] is False


def test_rejects_wrong_or_replayed_workflow_context():
    assert _validate(evidence=_evidence(workflow_run_id="44999999999"))["eligible"] is False
    assert _validate(evidence=_evidence(run_attempt=2))["eligible"] is False


def test_rejects_stale_or_future_evidence():
    assert _validate(evidence=_evidence(created_at="2026-11-23T00:00:00+00:00"))["eligible"] is False
    assert _validate(evidence=_evidence(created_at="2026-11-23T03:02:00+00:00"))["eligible"] is False


def test_rejects_unknown_manifest_fields():
    assert _validate(evidence={**_evidence(), "human_approved": True})["eligible"] is False


def test_rejects_nonce_not_bound_to_current_workflow_context():
    result = validate_machine_resume_evidence(
        TASK, _evidence(),
        expected_base_sha=BASE,
        expected_workflow_run_id=RUN_ID,
        expected_run_attempt=ATTEMPT,
        expected_nonce="e" * 32,
        now=NOW,
    )
    assert result["eligible"] is False
