"""Fail-closed continuation policy for chained distributed-loop jobs."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_RESULT = re.compile(r"^- 結果: \*\*(PASS|BLOCKED|NOT_RUN|FAIL)\*\*$", re.MULTILINE)
_PROGRESS = re.compile(r"^- キュー進捗: (\d+)/(\d+)$", re.MULTILINE)


def decide_chain(
    report_text: str,
    result_rows: list[dict],
    *,
    run_conclusion: str,
    continuation_depth: int,
    max_depth: int = 12,
    kill_switch: bool = False,
) -> dict:
    """Continue only after a fully successful task with verified queued work."""
    if type(continuation_depth) is not int or continuation_depth < 0:
        return {"continue": False, "reason": "invalid_continuation_depth"}
    if type(max_depth) is not int or max_depth < 1:
        return {"continue": False, "reason": "invalid_max_depth"}
    if continuation_depth >= max_depth:
        return {"continue": False, "reason": "continuation_depth_limit"}
    if kill_switch:
        return {"continue": False, "reason": "kill_switch_enabled"}
    if run_conclusion != "success":
        return {"continue": False, "reason": "workflow_not_success"}
    result_match = _RESULT.search(report_text)
    if not result_match or result_match.group(1) != "PASS":
        return {"continue": False, "reason": "task_result_not_pass"}
    progress_match = _PROGRESS.search(report_text)
    if not progress_match:
        return {"continue": False, "reason": "queue_progress_missing"}
    completed, total = map(int, progress_match.groups())
    if completed < 0 or total < 0 or completed > total:
        return {"continue": False, "reason": "queue_progress_invalid"}
    if completed >= total:
        return {
            "continue": False,
            "reason": "queue_drained",
            "queue_completed": completed,
            "queue_total": total,
        }
    if not result_rows:
        return {"continue": False, "reason": "task_evidence_missing"}
    seen: set[str] = set()
    for row in result_rows:
        if not isinstance(row, dict):
            return {"continue": False, "reason": "task_evidence_invalid"}
        task_id = row.get("task_id")
        status = row.get("status")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            return {"continue": False, "reason": "task_identity_invalid"}
        seen.add(task_id)
        if status not in {"PASS", "NO_CHANGE"}:
            return {"continue": False, "reason": "task_result_not_pass"}
    return {
        "continue": True,
        "reason": "verified_tasks_remaining",
        "next_depth": continuation_depth + 1,
        "queue_completed": completed,
        "queue_total": total,
    }


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("task result row must be an object")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--depth", type=int, required=True)
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--run-conclusion", required=True)
    parser.add_argument("--kill-switch", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        decision = decide_chain(
            args.report.read_text(encoding="utf-8"),
            read_jsonl(args.results),
            run_conclusion=args.run_conclusion,
            continuation_depth=args.depth,
            max_depth=args.max_depth,
            kill_switch=args.kill_switch,
        )
    except Exception as exc:
        decision = {"continue": False, "reason": f"decision_error_{type(exc).__name__}"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
