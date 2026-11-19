"""Build a truthful cloud-side Orca status snapshot from this GitHub Actions run."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STREAMS = {
    "main_star_night": ("STAR-NIGHT", "main"),
    "side_task_supply": ("タスク供給・分散Loop", "side"),
    "side_self_improvement": ("自己改善AI", "side"),
    "side_line_full_control": ("LINE AI Secretary", "side"),
    "side_media_ai": ("Muse（動画・音楽）", "side"),
    "side_core_vocabulary": ("英単語コア語彙", "side"),
}
ALLOWED_STATUS = {"PASS", "NO_CHANGE", "FAIL", "BLOCKED", "NOT_RUN"}


def build_snapshot(results: list[dict], run_id: str, outcome: str, captured_at: str | None = None, work_finder_report: dict | None = None) -> dict:
    now = captured_at or datetime.now(timezone.utc).isoformat()
    counts = {key: 0 for key in STREAMS}
    tasks = []
    for row in results[:100]:
        if not isinstance(row, dict):
            continue
        task_id = str(row.get("task_id") or "")[:100]
        status = str(row.get("status") or "NOT_RUN")
        if not task_id or status not in ALLOWED_STATUS:
            continue
        stream_key = row.get("stream_key")
        if stream_key not in STREAMS:
            stream_key = None
        else:
            counts[stream_key] += 1
        item = {"task_id": task_id, "status": status, "stage": "completed" if status in {"PASS", "NO_CHANGE"} else "reported"}
        artifact = row.get("rea_artifact")
        if isinstance(artifact, dict):
            artifact_status = artifact.get("status")
            evidence_hash = artifact.get("evidence_sha256")
            reason_code = artifact.get("reason_code")
            if artifact_status in {"PASS", "FAIL", "NO_CHANGE", "BLOCKED", "HOLD"}:
                item["rea_artifact_status"] = artifact_status
            if isinstance(reason_code, str) and reason_code and len(reason_code) <= 100:
                item["rea_artifact_reason_code"] = reason_code
            if isinstance(evidence_hash, str) and len(evidence_hash) == 64 and all(ch in "0123456789abcdef" for ch in evidence_hash):
                item["rea_artifact_evidence_sha256"] = evidence_hash
            for flag in ("execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"):
                item["rea_artifact_" + flag] = artifact.get(flag) is True
        if stream_key:
            item["stream_key"] = stream_key
        tasks.append(item)

    streams = []
    for key, (label, kind) in STREAMS.items():
        count = counts[key]
        streams.append({
            "key": key,
            "label": label,
            "kind": kind,
            "status": "observed" if count else "unknown",
            "task_count": count,
            "dispatch_count": 0,
            "worker_count": 0,
            "evidence": "matched_runtime_records" if count else "no_matching_stream_metadata",
        })

    work_finder = None
    if isinstance(work_finder_report, dict):
        source = work_finder_report.get("work_finder")
        if isinstance(source, dict):
            counts = {}
            count_keys = ("discovered_candidate_count", "review_pending_count", "completed_task_count",
                          "catalog_task_count", "runtime_queue_task_count", "held_task_count",
                          "resume_review_required_count", "scanned_target_pairs")
            for key in count_keys:
                value = source.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    counts[key] = max(0, min(value, 10000))
            eligible = source.get("execution_eligible_count")
            if isinstance(eligible, int) and not isinstance(eligible, bool):
                counts["execution_eligible_count"] = max(0, min(eligible, 10000))
            previews = []
            raw_candidates = work_finder_report.get("candidates")
            if isinstance(raw_candidates, list):
                for candidate in raw_candidates[:5]:
                    if not isinstance(candidate, dict):
                        continue
                    preview = {}
                    for key, limit in (("id", 100), ("target_test", 200), ("source_function", 120), ("evidence", 250)):
                        value = candidate.get(key)
                        if isinstance(value, str) and value.strip():
                            preview[key] = value.strip()[:limit]
                    if preview.get("id") and preview.get("target_test") and preview.get("source_function"):
                        preview["status"] = "REVIEW_REQUIRED"
                        previews.append(preview)
            safety = source.get("safety")
            work_finder = {
                "cycle_status": source.get("cycle_status") if source.get("cycle_status") in {"WORK_FOUND", "NO_SAFE_CANDIDATE"} else "BLOCKED",
                "next_action": source.get("next_action") if source.get("next_action") in {
                    "human_review_candidates", "review_catalog_runtime_plan_gaps", "expand_allowlisted_discovery_sources"
                } else "investigate_discovery_status",
                "execution_eligibility_status": "verified" if source.get("execution_eligibility_status") == "verified" and "execution_eligible_count" in counts else "not_proven",
                "candidate_policy": "review_only_no_execution_approval",
                "candidate_preview": previews,
                "safety": {"read_only": isinstance(safety, dict) and safety.get("read_only") is True,
                           "execution_approval_granted": False},
                **counts,
            }

    return {
        "captured_at": now,
        "run_id": str(run_id)[:100],
        "tasks": tasks,
        "dispatches": [{
            "dispatch_id": f"github-actions-run-{str(run_id)[:80]}",
            "status": outcome if outcome in ALLOWED_STATUS else "BLOCKED",
            "stage": "completed",
            "updated_at": now,
        }],
        "workers": [],
        "streams": streams,
        "work_finder": work_finder,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="/tmp/minimal-autonomous-loop.jsonl")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--work-finder-report", default=None)
    args = parser.parse_args(argv)
    try:
        rows = []
        path = Path(args.results)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines()[:100]:
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
        work_finder_report = None
        if args.work_finder_report:
            report_path = Path(args.work_finder_report)
            if report_path.is_file():
                report_value = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(report_value, dict):
                    work_finder_report = report_value
        print(json.dumps(build_snapshot(rows, args.run_id, args.outcome, work_finder_report=work_finder_report), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ORCA_CLOUD_SNAPSHOT_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
