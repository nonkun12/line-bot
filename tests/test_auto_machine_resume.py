import json

from scripts import auto_machine_resume as module


def test_no_change_when_catalog_has_no_machine_policy(tmp_path, monkeypatch):
    recovery = {"schema_version": 1, "checkpoint": None, "tasks": {}}
    state = {"version": 1, "completed": [], "recovery_ai": recovery}
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "recovery.json").write_text(json.dumps(recovery))
    (tmp_path / "catalog.json").write_text(json.dumps({"tasks": []}))
    result = module.run_one_machine_resume(
        repo_root=tmp_path,
        state_file=tmp_path / "state.json",
        recovery_state_file=tmp_path / "recovery.json",
        catalog_file=tmp_path / "catalog.json",
        base_sha="a" * 40,
        workflow_run_id="123456789",
        run_attempt=1,
        nonce="d" * 32,
    )
    assert result == {
        "status": "NO_CHANGE",
        "reason_code": "no_machine_resume_candidate",
    }


def test_does_not_attempt_unknown_or_nonrepairable_failure(tmp_path, monkeypatch):
    task = {
        "id": "machine-test-1",
        "instruction": "Run a safe regression test.",
        "allowed_paths": ["tests/test_safe.py"],
        "execution_approved": True,
        "resume_policy": "machine_evidence",
    }
    recovery = {
        "schema_version": 1,
        "checkpoint": None,
        "tasks": {
            task["id"]: {
                "held": True,
                "resume_requires_review": False,
                "last_category": "unknown",
            }
        },
    }
    state = {"version": 1, "completed": [], "recovery_ai": recovery}
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "recovery.json").write_text(json.dumps(recovery))
    (tmp_path / "catalog.json").write_text(json.dumps({"tasks": [task]}))
    def forbidden(*args, **kwargs):
        raise AssertionError("REA must not run for unknown failure category")
    monkeypatch.setattr(module, "run_pre_repair_rea", forbidden)
    result = module.run_one_machine_resume(
        repo_root=tmp_path,
        state_file=tmp_path / "state.json",
        recovery_state_file=tmp_path / "recovery.json",
        catalog_file=tmp_path / "catalog.json",
        base_sha="a" * 40,
        workflow_run_id="123456789",
        run_attempt=1,
        nonce="d" * 32,
    )
    assert result["status"] == "NO_CHANGE"


def test_rejects_state_recovery_mismatch(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"recovery_ai": {}}))
    (tmp_path / "recovery.json").write_text(json.dumps({"schema_version": 1, "tasks": {}}))
    (tmp_path / "catalog.json").write_text(json.dumps({"tasks": []}))
    result = module.run_one_machine_resume(
        repo_root=tmp_path,
        state_file=tmp_path / "state.json",
        recovery_state_file=tmp_path / "recovery.json",
        catalog_file=tmp_path / "catalog.json",
        base_sha="a" * 40,
        workflow_run_id="123456789",
        run_attempt=1,
        nonce="d" * 32,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "machine_resume_state_mismatch"
