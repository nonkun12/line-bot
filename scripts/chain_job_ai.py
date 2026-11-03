"""Independent, evidence-driven decision agent for bounded distributed-job chains.

Chain Job AI owns the continuation decision. It does not execute tasks, create
work, clear holds, or publish changes; it only authorizes the next bounded job
when runtime, Control Tower, and durable completion evidence all agree.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_DEPTH = re.compile(r"continuation_depth=(\\d+)")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_RESULTS = 4


def _stop(reason: str, depth: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "agent": "ChainJobAI",
        "schema_version": 1,
        "decision": "STOP",
        "continue": False,
        "reason": reason,
    }
    if depth is not None:
        result["depth"] = depth
    return result


def _one_file(root: Path, name: str) -> Path | None:
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    return matches[0] if len(matches) == 1 else None


def decide(
    artifact_dir: Path,
    run_name: str,
    conclusion: str,
    *,
    evidence_download_outcome: str = "success",
    kill_switch: str | bool = False,
    max_depth: int = 12,
) -> dict[str, Any]:
    """Return a fail-closed continuation decision from immutable run evidence."""
    if type(max_depth) is not int or not 1 <= max_depth <= 12:
        return _stop("invalid_depth_limit")
    if kill_switch is True or (
        isinstance(kill_switch, str) and kill_switch.strip().lower() == "true"
    ):
        return _stop("kill_switch_enabled")
    if conclusion != "success":
        return _stop("source_run_not_success")
    match = _DEPTH.search(run_name if isinstance(run_name, str) else "")
    if match is None:
        return _stop("continuation_depth_missing")
    depth = int(match.group(1))
    if depth >= max_depth:
        return _stop("bounded_depth_limit", depth)
    if evidence_download_outcome != "success":
        return _stop("missing_or_unreadable_artifact", depth)

    result_path = _one_file(artifact_dir, "minimal-autonomous-loop.jsonl")
    state_path = _one_file(artifact_dir, "autonomous-loop-state.json")
    if result_path is None or state_path is None:
        return _stop("missing_or_ambiguous_evidence", depth)
    try:
        rows = []
        for line in result_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                return _stop("invalid_task_result_row", depth)
            rows.append(row)
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _stop("invalid_evidence", depth)

    if not 1 <= len(rows) <= _MAX_RESULTS:
        return _stop("unexpected_task_result_count", depth)
    task_ids: list[str] = []
    for row in rows:
        task_id = row.get("task_id")
        if row.get("status") != "PASS":
            return _stop("task_status_not_verified_pass", depth)
        if type(row.get("exit_code")) is not int or row["exit_code"] != 0:
            return _stop("task_exit_code_not_zero", depth)
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            return _stop("missing_or_invalid_task_id", depth)
        tower = row.get("control_tower")
        orchestration = tower.get("orchestration") if isinstance(tower, dict) else None
        if not isinstance(tower, dict) or tower.get("recorded") is not True:
            return _stop("control_tower_evidence_missing", depth)
        if not isinstance(orchestration, dict) or orchestration.get("allow_continue") is not True:
            return _stop("control_tower_denied_continue", depth)
        if row.get("failure_reason"):
            return _stop("failure_reason_present", depth)
        task_ids.append(task_id)

    if len(task_ids) != len(set(task_ids)):
        return _stop("duplicate_task_ids", depth)
    completed = state.get("completed") if isinstance(state, dict) else None
    if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
        return _stop("durable_completion_state_invalid", depth)
    if any(task_id not in completed for task_id in task_ids):
        return _stop("durable_completion_not_confirmed", depth)

    return {
        "agent": "ChainJobAI",
        "schema_version": 1,
        "decision": "CONTINUE",
        "continue": True,
        "reason": "verified_pass_and_durable_completion",
        "depth": depth,
        "next_depth": depth + 1,
        "verified_task_ids": task_ids,
        "verified_task_count": len(task_ids),
        "permissions": {
            "execute_task": False,
            "create_task": False,
            "clear_hold": False,
            "modify_source": False,
            "merge": False,
            "deploy": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--evidence-download-outcome", default="success")
    parser.add_argument("--kill-switch", default="false")
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = decide(
        args.artifact_dir,
        args.run_name,
        args.conclusion,
        evidence_download_outcome=args.evidence_download_outcome,
        kill_switch=args.kill_switch,
        max_depth=args.max_depth,
    )
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"continue={'true' if report['continue'] else 'false'}\n")
        if "depth" in report:
            output.write(f"depth={report['depth']}\n")
        if report["continue"]:
            output.write(f"task_id={report['verified_task_ids'][-1]}\n")
            output.write(f"next_depth={report['next_depth']}\n")
    print("CHAIN_JOB_AI_DECISION=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
