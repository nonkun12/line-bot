"""Decide whether a completed distributed-loop run may safely continue.

Fail closed: continuation requires successful run conclusion and explicit PASS
evidence from the uploaded task result. Missing artifacts, unknown depth, failed
gates, or queue-empty runs never dispatch another cycle.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEPTH_RE = re.compile(r"continuation_depth=(\d+)")
ALLOWED_SUCCESS = {"PASS"}


def decide(artifact_dir: Path, run_name: str, conclusion: str) -> dict:
    match = DEPTH_RE.search(run_name)
    if match is None:
        return {"continue": False, "reason": "continuation_depth_missing"}
    depth = int(match.group(1))
    if depth < 0:
        return {"continue": False, "reason": "continuation_depth_invalid"}
    if conclusion != "success":
        return {"continue": False, "reason": "source_run_not_success", "depth": depth}

    candidates = sorted(artifact_dir.rglob("minimal-autonomous-loop.jsonl"))
    if not candidates:
        return {"continue": False, "reason": "task_evidence_missing", "depth": depth}
    rows = []
    try:
        for path in candidates:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("result row is not an object")
                    rows.append(row)
    except (OSError, UnicodeError, ValueError):
        return {"continue": False, "reason": "task_evidence_invalid", "depth": depth}
    if not rows:
        return {"continue": False, "reason": "task_evidence_empty", "depth": depth}

    # Every row must be a verified PASS. NO_CHANGE, HOLD, NOT_RUN, BLOCKED,
    # missing orchestrator evidence, and unknown status all stop the chain.
    for row in rows:
        if row.get("status") not in ALLOWED_SUCCESS or row.get("exit_code") != 0:
            return {"continue": False, "reason": "task_not_pass", "depth": depth}
        tower = row.get("control_tower")
        if not isinstance(tower, dict) or tower.get("recorded") is not True:
            return {"continue": False, "reason": "control_tower_evidence_missing", "depth": depth}
        orchestration = tower.get("orchestration")
        if not isinstance(orchestration, dict) or orchestration.get("allow_continue") is not True:
            return {"continue": False, "reason": "control_tower_denied_continue", "depth": depth}
        if row.get("failure_reason"):
            return {"continue": False, "reason": "failure_reason_present", "depth": depth}

    return {"continue": True, "reason": "verified_pass", "depth": depth, "next_depth": depth + 1}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = decide(args.artifact_dir, args.run_name, args.conclusion)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if result["continue"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
