#!/usr/bin/env python3
"""Render a deterministic, read-only Orchestrator dashboard to stdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.orchestrator_core import PlanError, build_plan


def _cell(value: Any) -> str:
    """Escape untrusted values for a Markdown table cell."""
    return str(value if value is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_dashboard(document: Any) -> str:
    """Render a snapshot; never writes files or contacts external services."""
    plan = build_plan(document)
    source_tasks = {
        task["id"]: task
        for task in document["tasks"]
    }
    counts: dict[str, int] = {}
    for row in plan["tasks"]:
        state = row["planning_state"]
        counts[state] = counts.get(state, 0) + 1

    budget = plan["budget"]
    lines = [
        "# Orchestrator Dashboard",
        "",
        f"**Status:** {plan['status']}",
        "",
        "| Tasks | Count |",
        "|---|---:|",
    ]
    for state in sorted(counts):
        lines.append(f"| {_cell(state)} | {counts[state]} |")
    if not counts:
        lines.append("| (empty) | 0 |")

    lines.extend([
        "",
        "## Budget",
        "",
        "| Limit (min) | Consumed (min) | Reserved (min) | Remaining (min) |",
        "|---:|---:|---:|---:|",
        f"| {budget['limit_minutes']} | {budget['consumed_minutes']} | {budget['reserved_minutes']} | {budget['remaining_minutes']} |",
        "",
        "## Task plan",
        "",
        "| ID | Title | Priority | State | Estimate (min) | Approved | Reason |",
        "|---|---|---:|---|---:|:---:|---|",
    ])
    if plan["tasks"]:
        for row in plan["tasks"]:
            task = source_tasks[row["id"]]
            lines.append(
                "| " + " | ".join((
                    _cell(row["id"]),
                    _cell(task.get("title", "")),
                    str(row["priority"]),
                    _cell(row["planning_state"]),
                    str(row["estimated_minutes"]),
                    "yes" if row["execution_approved"] else "no",
                    _cell(row["reason"]),
                )) + " |"
            )
    else:
        lines.append("| (empty) | | | NO_TASK | 0 | no | |")

    lines.extend([
        "",
        f"**Selected candidate:** {_cell(plan['selected_candidate']) or 'none'}",
        "",
        f"**Safety:** execution={str(plan['execution_performed']).lower()}, "
        f"dispatch={str(plan['dispatch_performed']).lower()}, "
        f"repository_modified={str(plan['repository_modified']).lower()}, "
        f"push={str(plan['push_performed']).lower()}, "
        f"PR={str(plan['pull_request_created']).lower()}, "
        f"merge={str(plan['merge_performed']).lower()}, "
        f"deploy={str(plan['deployment_performed']).lower()}",
        "",
    ])
    if plan["reasons"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {_cell(reason)}" for reason in plan["reasons"])
        lines.append("")
    lines.extend([
        "> Snapshot renderer only. It does not persist a ledger, dispatch work,",
        "> update GitHub, or authorize execution. A selected candidate is not approval.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        rendered = render_dashboard(document)
        status = build_plan(document)["status"]
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        rendered = "# Orchestrator Dashboard\n\n**Status:** HOLD\n\n"
        rendered += f"**Blocker:** {_cell(str(exc)[:160])}\n\n"
        status = "HOLD"
    sys.stdout.write(rendered)
    return 0 if status in {"PLAN_READY", "NO_TASK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
