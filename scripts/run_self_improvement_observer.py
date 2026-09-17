"""Run a read-only distributed self-improvement observation.

This command consumes a completed RuntimeReport, asks bounded advisory agents to
analyze it, and writes only a JSON artifact. It never edits the repository or
creates commits, branches, pull requests, or deployments.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Mapping

from core.control_tower import ControlTower
from core.creator_critic_runtime import build_creator_critic_loop
from core.distributed_executor import DistributedAIExecutor
from core.self_improvement_distributed import DistributedSelfImprovementLoop
from core.agent_runtime import RuntimeReport


def build_report(payload: Mapping[str, object]) -> RuntimeReport:
    failed_task_id = payload.get("failed_task_id")
    error = payload.get("error")
    rounds = int(payload.get("rounds", 1) or 1)
    repair_attempts = int(payload.get("repair_attempts", 0) or 0)
    integration_ready = bool(payload.get("integration_ready", False))
    return RuntimeReport(
        (),
        failed_task_id=str(failed_task_id).strip() if failed_task_id else None,
        error=str(error).strip() if error else None,
        rounds=max(0, rounds),
        repair_attempts=max(0, repair_attempts),
        integration_ready=integration_ready,
    )


def run_observer(
    payload: Mapping[str, object],
    *,
    output_path: str | Path = "self-improvement-observer.json",
    model_call=None,
) -> dict[str, object]:
    report = build_report(payload)
    tower = ControlTower(
        creator_critic=build_creator_critic_loop(model_call=model_call, max_iterations=1)
    )
    loop = DistributedSelfImprovementLoop(
        executor=DistributedAIExecutor(model_call=model_call) if model_call else None,
        control_tower=tower,
    )
    objective = str(payload.get("objective", "")).strip() or None
    result = loop.run(report, objective=objective)

    decision = result.decision
    output: dict[str, object] = {
        "analysis_success": result.analysis_success,
        "analysis_agent_count": len(result.analysis_results),
        "analysis_results": [
            {
                "task_id": item.task_id,
                "success": item.success,
                "summary": item.summary[:2000],
            }
            for item in result.analysis_results
        ],
        "evidence": dict(result.evidence),
        "proposal": {
            "title": decision.proposal.title,
            "rationale": decision.proposal.rationale,
            "task_id": decision.proposal.task.task_id if decision.proposal.task else None,
        } if decision and decision.proposal else None,
        "approved_for_pipeline": bool(decision and decision.approved_for_pipeline),
        "approved_task_id": decision.approved_task.task_id if decision and decision.approved_task else None,
        "evaluation_error": decision.evaluation_error if decision else None,
    }
    Path(output_path).write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output


def main() -> int:
    raw = os.environ.get("SELF_IMPROVEMENT_REPORT_JSON", "").strip()
    if not raw:
        print("SELF_IMPROVEMENT_REPORT_JSON is required", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid SELF_IMPROVEMENT_REPORT_JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("SELF_IMPROVEMENT_REPORT_JSON must be a JSON object", file=sys.stderr)
        return 2
    run_observer(payload)
    print("self-improvement observer completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
