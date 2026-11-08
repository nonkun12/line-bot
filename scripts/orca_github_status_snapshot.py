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


def build_snapshot(results: list[dict], run_id: str, outcome: str, captured_at: str | None = None) -> dict:
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="/tmp/minimal-autonomous-loop.jsonl")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--outcome", required=True)
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
        print(json.dumps(build_snapshot(rows, args.run_id, args.outcome), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ORCA_CLOUD_SNAPSHOT_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
