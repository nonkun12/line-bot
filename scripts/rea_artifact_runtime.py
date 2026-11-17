"""Collect and persist fail-closed post-runtime REA evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.rea_artifact_evaluator import evaluate_runtime_summary
from scripts.rea_readonly_scanner import ScanBlocked, scan_commit_diff


def evaluate_and_record_runtime_artifact(
    summary: object,
    *,
    repo_root: str | Path,
    output_path: str | Path,
    stop_state: str,
    hold_state: str,
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
        # Deliberately ignore summary["tests"] and summary["risk"]: the runtime
        # child can write its own summary, so those fields are self-reported.
        # Independent test/risk evidence is not wired yet; remain fail-closed.

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
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    return record
