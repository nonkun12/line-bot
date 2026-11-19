from __future__ import annotations

import json

from scripts import rea_artifact_runtime


BASE = "a" * 40
HEAD = "b" * 40


def _summary():
    return {
        "task_id": "task-001",
        "base_sha": BASE,
        "produced_sha": HEAD,
        "post_generation_rea": {
            "status": "PASS",
            "base_sha": BASE,
            "target_sha": HEAD,
        },
    }


def _scan(monkeypatch):
    monkeypatch.setattr(
        rea_artifact_runtime,
        "scan_commit_diff",
        lambda *args, **kwargs: {
            "status": "PASS",
            "changed_paths": ["core/example.py"],
            "diff_sha256": "c" * 64,
        },
    )


def _trusted_receipt_and_run():
    from core.rea_independent_verification import WORKFLOW_PATH

    receipt = {
        "schema_version": 1,
        "verified_sha": HEAD,
        "base_sha": BASE,
        "test_outcome": "SUCCESS",
        "identity_outcome": "SUCCESS",
        "risk": "UNKNOWN",
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    run_metadata = {
        "id": 987,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "nonkun12/line-bot"},
        "path": WORKFLOW_PATH,
        "event": "push",
        "head_branch": "line-dev/987",
        "head_sha": HEAD,
    }
    return receipt, run_metadata


def test_runtime_artifact_defaults_missing_tests_and_risk_to_hold(tmp_path, monkeypatch):
    _scan(monkeypatch)
    output = tmp_path / "rea.jsonl"
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        _summary(),
        repo_root=tmp_path,
        output_path=output,
        stop_state="INACTIVE",
        hold_state="CLEAR",
    )

    assert result["status"] == "HOLD"
    assert result["reason_code"] == "risk_unknown"
    assert result["tests"] == "UNKNOWN"
    assert result["risk"] == "UNKNOWN"
    assert result["execution_authorized"] is False
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["evidence_sha256"] == result["evidence_sha256"]


def test_runtime_artifact_ignores_self_reported_test_and_risk_evidence(tmp_path, monkeypatch):
    _scan(monkeypatch)
    summary = {**_summary(), "tests": "PASS", "risk": "LOW"}
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        summary,
        repo_root=tmp_path,
        output_path=tmp_path / "rea.jsonl",
        stop_state="INACTIVE",
        hold_state="CLEAR",
    )

    assert result["status"] == "HOLD"
    assert result["tests"] == "UNKNOWN"
    assert result["risk"] == "UNKNOWN"
    assert result["reason_code"] == "risk_unknown"
    assert result["merge_deploy_authorized"] is False


def test_runtime_artifact_scan_failure_is_persisted_as_hold(tmp_path, monkeypatch):
    def fail_scan(*args, **kwargs):
        raise rea_artifact_runtime.ScanBlocked("test_failure")

    monkeypatch.setattr(rea_artifact_runtime, "scan_commit_diff", fail_scan)
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        _summary(),
        repo_root=tmp_path,
        output_path=tmp_path / "rea.jsonl",
        stop_state="INACTIVE",
        hold_state="CLEAR",
    )

    assert result["status"] == "HOLD"
    assert result["reason_code"] == "artifact_evidence_collection_failed"
    assert result["patch_authorized"] is False


def test_runtime_artifact_records_sanitized_rea_history_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOVERY_RAG_DB_PATH", str(tmp_path / "recovery-rag.sqlite3"))
    monkeypatch.setenv("RECOVERY_RAG_NAMESPACE", "distributed-loop")
    _scan(monkeypatch)
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        _summary(),
        repo_root=tmp_path,
        output_path=tmp_path / "rea.jsonl",
        stop_state="INACTIVE",
        hold_state="CLEAR",
    )
    assert result["status"] == "HOLD"
    assert result["rea_rag_recorded"] is True
    from scripts.rea_rag import build_rea_context
    context = build_rea_context(
        tmp_path / "recovery-rag.sqlite3",
        namespace="distributed-loop",
        task_id="next-task",
        instruction="Review tests and unknown risk evidence",
    )
    assert "status=HOLD" in context
    assert "risk_unknown" in context


def test_runtime_consumes_trusted_independent_receipt_but_risk_stays_unknown(tmp_path, monkeypatch):
    _scan(monkeypatch)
    receipt, run_metadata = _trusted_receipt_and_run()
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        _summary(),
        repo_root=tmp_path,
        output_path=tmp_path / "rea.jsonl",
        stop_state="INACTIVE",
        hold_state="CLEAR",
        independent_receipt=receipt,
        independent_run_metadata=run_metadata,
    )

    assert result["status"] == "HOLD"
    assert result["reason_code"] == "risk_unknown"
    assert result["tests"] == "PASS"
    assert result["risk"] == "UNKNOWN"
    assert result["independent_verification"]["verified_sha"] == HEAD
    assert result["independent_verification"]["verification_run_id"] == 987
    assert result["execution_authorized"] is False
    assert result["merge_deploy_authorized"] is False
    row = json.loads((tmp_path / "rea.jsonl").read_text().splitlines()[0])
    assert row["tests"] == "PASS"
    assert row["risk"] == "UNKNOWN"


def test_runtime_rejects_receipt_without_trusted_run_metadata(tmp_path, monkeypatch):
    _scan(monkeypatch)
    receipt, _ = _trusted_receipt_and_run()
    result = rea_artifact_runtime.evaluate_and_record_runtime_artifact(
        _summary(),
        repo_root=tmp_path,
        output_path=tmp_path / "rea.jsonl",
        stop_state="INACTIVE",
        hold_state="CLEAR",
        independent_receipt=receipt,
    )

    assert result["status"] == "HOLD"
    assert result["tests"] == "UNKNOWN"
    assert result["independent_verification"]["reason_code"] == "trusted_run_metadata_missing"
    assert result["execution_authorized"] is False
