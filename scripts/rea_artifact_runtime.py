"""Collect and persist fail-closed post-runtime REA evidence."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from core.rea_artifact_evaluator import evaluate_runtime_summary
from core.rea_independent_verification import evaluate_independent_verification_receipt
from core.rea_independent_verification_client import load_independent_verification_for_sha
from scripts.rea_readonly_scanner import ScanBlocked, scan_commit_diff
from core.rea_risk_classifier import classify_changed_paths


def evaluate_and_record_runtime_artifact(
    summary: object,
    *,
    repo_root: str | Path,
    output_path: str | Path,
    stop_state: str,
    hold_state: str,
    independent_receipt: object = None,
    independent_run_metadata: object = None,
) -> dict[str, Any]:
    """Evaluate immutable runtime output and append a metadata-only JSONL record.

    Runtime summaries are not an independent source for tests or risk. Until a
    separate verifier supplies those facts, they remain NOT_RUN / UNKNOWN and
    changed artifacts cannot receive PASS.
    """
    verification: dict[str, Any] = {
        "tests": "NOT_RUN",
        "risk": "UNKNOWN",
        "stop_state": stop_state,
        "hold_state": hold_state,
        "changed_files": [],
        "diff_scan": "UNKNOWN",
    }
    try:
        if not isinstance(summary, dict):
            raise ScanBlocked("runtime_summary_not_object")
        base_sha = summary.get("base_sha")
        head_sha = summary.get("produced_sha")
        if not isinstance(base_sha, str) or not isinstance(head_sha, str):
            raise ScanBlocked("runtime_summary_sha_missing")
        scan = scan_commit_diff(repo_root, base_sha=base_sha, target_sha=head_sha)
        verification["changed_files"] = scan.get("changed_paths", [])
        verification["diff_scan"] = "PASS" if scan.get("status") == "PASS" else "FAIL"
        verification["diff_sha256"] = scan.get("diff_sha256")
        risk = classify_changed_paths(verification["changed_files"])
        verification["risk"] = risk["risk"] if verification["diff_scan"] == "PASS" else "UNKNOWN"
        verification["risk_reason_code"] = risk["reason_code"]
        # When running in GitHub Actions, discover the newest exact-SHA
        # verifier run and download only its run-bound artifact. Local runs and
        # API failures remain fail-closed with no independent test evidence.
        if independent_receipt is None and independent_run_metadata is None:
            independent_receipt, independent_run_metadata = (
                load_independent_verification_for_sha(head_sha)
            )

        # Child-written summary fields are untrusted. Only a receipt paired with
        # trusted GitHub Actions API run metadata can upgrade test evidence.
        independent = evaluate_independent_verification_receipt(
            independent_receipt,
            independent_run_metadata,
            expected_sha=head_sha,
        )
        verification["tests"] = independent["tests"]
        verification["independent_verification"] = {
            "reason_code": independent["reason_code"],
            "verified_sha": independent.get("verified_sha"),
            "verification_workflow_id": independent.get("verification_workflow_id"),
            "verification_run_id": independent.get("verification_run_id"),
        }

        adapted_summary = dict(summary)
        if head_sha == base_sha and not isinstance(adapted_summary.get("post_generation_rea"), dict):
            adapted_summary["post_generation_rea"] = {
                "status": "PASS",
                "base_sha": base_sha,
                "target_sha": head_sha,
            }
        result = evaluate_runtime_summary(adapted_summary, verification)
    except Exception:
        # Do not leak scanner stderr, file contents, or environment details.
        from core.rea_artifact_evaluator import evaluate_artifact_evidence

        result = evaluate_artifact_evidence({
            "task_id": summary.get("task_id") if isinstance(summary, dict) else None,
            "base_sha": summary.get("base_sha") if isinstance(summary, dict) else None,
            "head_sha": summary.get("produced_sha") if isinstance(summary, dict) else None,
            "changed_files": [],
            "tests": "UNKNOWN",
            "diff_scan": "UNKNOWN",
            "risk": "UNKNOWN",
            "stop_state": stop_state,
            "hold_state": hold_state,
        })
        result["reason_code"] = "artifact_evidence_collection_failed"

    record = {
        **result,
        "task_id": summary.get("task_id") if isinstance(summary, dict) else None,
        "base_sha": summary.get("base_sha") if isinstance(summary, dict) else None,
        "head_sha": summary.get("produced_sha") if isinstance(summary, dict) else None,
        "tests": verification.get("tests", "UNKNOWN"),
        "risk": verification.get("risk", "UNKNOWN"),
        "diff_scan": verification.get("diff_scan", "UNKNOWN"),
        "changed_file_count": len(verification.get("changed_files", [])),
        "risk_reason_code": verification.get("risk_reason_code", "risk_not_classified"),
        "independent_verification": verification.get("independent_verification", {
            "reason_code": "independent_verification_not_supplied",
            "verified_sha": None,
            "verification_workflow_id": None,
            "verification_run_id": None,
        }),
    }
    # Optional RAG memory stores only the evaluator's sanitized metadata.
    # A cache failure must never change the REA decision or block evidence output.
    rag_db_path = os.environ.get("RECOVERY_RAG_DB_PATH", "").strip()
    rag_namespace = os.environ.get("RECOVERY_RAG_NAMESPACE", "distributed-loop").strip()
    record["rea_rag_recorded"] = False
    if rag_db_path and rag_namespace:
        try:
            from scripts.rea_rag import record_rea_evaluation
            evidence_sha = record.get("evidence_sha256")
            if isinstance(evidence_sha, str):
                record_rea_evaluation(
                    rag_db_path,
                    namespace=rag_namespace,
                    task_id=str(record.get("task_id") or ""),
                    status=str(record.get("status") or ""),
                    reason_code=str(record.get("reason_code") or "unknown"),
                    evidence_sha256=evidence_sha,
                    changed_file_count=len(verification.get("changed_files", [])),
                )
                record["rea_rag_recorded"] = True
        except Exception:
            # Keep RAG optional and fail-closed as a knowledge source, not as a gate.
            record["rea_rag_recorded"] = False
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with destination.open("a", encoding="utf-8") as handle:
        # Serialize concurrent writers and force the evidence row to stable storage.
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return record
