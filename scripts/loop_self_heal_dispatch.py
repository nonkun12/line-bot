"""Dispatch a repair only after Recovery AI requests one and catalog grants it."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


def maybe_run_repair(
    task_id: str,
    recovery_result: dict[str, Any],
    registered_catalog: list[dict[str, Any]],
    recovery_state_path: str | Path,
    *,
    env: dict[str, str] | None = None,
    repair_runner: Callable[[str, str | Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Run one local repair after a recorded REPAIR_ONCE decision; never resume."""
    if not isinstance(recovery_result, dict) or recovery_result.get("recorded") is not True:
        return None
    decision = recovery_result.get("decision")
    if not isinstance(decision, dict) or decision.get("action") != "REPAIR_ONCE":
        return None

    matches = [
        item for item in registered_catalog
        if isinstance(item, dict) and item.get("id") == task_id
    ]
    if len(matches) != 1:
        return {"status": "BLOCKED", "reason_code": "repair_catalog_identity_invalid"}
    task = matches[0]
    if task.get("repair_approved") is not True or task.get("execution_approved") is not True:
        return {"status": "BLOCKED", "reason_code": "catalog_repair_approval_missing"}

    runtime_env = os.environ if env is None else env
    if str(runtime_env.get("GITHUB_ACTIONS", "")).casefold() == "true":
        return {"status": "BLOCKED", "reason_code": "local_model_not_available_in_hosted_runner"}
    token = str(runtime_env.get("GITHUB_TOKEN") or runtime_env.get("GH_TOKEN") or "").strip()
    if not token:
        return {"status": "BLOCKED", "reason_code": "github_repair_ledger_token_missing"}

    if repair_runner is None:
        try:
            from scripts.run_loop_repair import run
            repair_runner = run
        except Exception:
            return {"status": "BLOCKED", "reason_code": "repair_orchestrator_unavailable"}
    try:
        result = repair_runner(task_id, recovery_state_path, token)
    except Exception as exc:
        return {"status": "BLOCKED", "reason_code": "repair_dispatch_error:" + type(exc).__name__}
    if not isinstance(result, dict):
        return {"status": "BLOCKED", "reason_code": "repair_result_invalid"}
    # A verified patch is not task success and does not authorize HOLD clearing
    # or resumption. A separate reviewed transition is still required.
    return {
        **result,
        "hold_clear_authorized": False,
        "resume_authorized": False,
        "merge_deploy_authorized": False,
    }
