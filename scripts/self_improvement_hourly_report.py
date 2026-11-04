"""Build an hourly, read-only self-improvement report from durable loop history.

The report is evidence and review material only. It never writes repository
state, queues tasks, changes approvals, edits source, merges, or deploys.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from core.self_improvement import ImprovementSignal
from core.self_improvement_analyzer import analyze_signals
from scripts.self_improvement_candidate_adapter import candidates_from_history
from scripts.self_improvement_state import validate_durable_history


def build_report(state: object) -> dict:
    if not isinstance(state, dict):
        raise ValueError("durable state must be an object")
    history = validate_durable_history(state.get("self_improvement_history", []))
    signals = tuple(
        ImprovementSignal(
            kind=str(row["kind"]),
            task_id=row.get("task_id"),
            detail=str(row["detail"]),
        )
        for row in history
        if row.get("record_type") != "cycle_memory"
    )
    analysis = analyze_signals(signals, min_occurrences=2, max_patterns=5)
    candidates = candidates_from_history(history)
    cycle_memory = [row for row in history if row.get("record_type") == "cycle_memory"]
    outcomes = {
        name: sum(row.get("outcome") == name for row in cycle_memory)
        for name in ("PASS", "FAIL", "BLOCKED")
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "REVIEW_REQUIRED" if candidates or analysis.recurring_patterns else "NO_RECURRING_SIGNAL",
        "evidence": {
            "history_records": len(history),
            "signal_records": len(signals),
            "failure_signals": analysis.failure_count,
            "repair_signals": analysis.repair_count,
            "cycle_outcomes": outcomes,
        },
        "recurring_patterns": [
            {
                "key": item.key,
                "count": item.count,
                "signal_kinds": list(item.signal_kinds),
                "task_ids": list(item.task_ids),
            }
            for item in analysis.recurring_patterns
        ],
        "review_candidates": candidates[-20:],
        "safety": {
            "read_only": True,
            "queue_mutated": False,
            "approval_changed": False,
            "source_modified": False,
            "merge_or_deploy": False,
            "human_review_required": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
        report = build_report(state)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"SELF_IMPROVEMENT_HOLD: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps({
        "status": report["status"],
        "history_records": report["evidence"]["history_records"],
        "candidate_count": len(report["review_candidates"]),
        "recurring_pattern_count": len(report["recurring_patterns"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
