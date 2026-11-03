"""Deterministic Goal AI planner for bounded, autonomous parent/child JOB chains.

Per-JOB human approval is replaced by a deterministic risk policy. Only
explicitly scoped, reversible repository work is auto-approved. Persistence,
execution, HOLD release, merge, and deployment remain separate capabilities.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.autonomy_policy import evaluate_job_autonomy

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_STAGES = frozenset({"requirements", "design", "implementation", "test", "review", "fix", "verify"})
_CRITERION_STATES = frozenset({"PASS", "FAIL", "UNKNOWN"})
_JOB_STATES = frozenset({"pending", "running", "done", "failed", "held"})
MAX_AUTONOMOUS_JOBS_PER_GOAL = 50


def _hold(reason: str, **details: Any) -> dict[str, Any]:
    return {
        "agent": "GoalAI",
        "decision": "HOLD",
        "reason": reason,
        **details,
        "create_job": False,
        "execute_job": False,
        "permissions": {"clear_hold": False, "merge": False, "deploy": False},
    }


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None



def _validate_autonomy_grant(grant: object, goal_id: str) -> dict[str, Any] | None:
    """Validate a grant supplied separately by the trusted approval-store adapter.

    The caller must retrieve this record from server-side durable storage; the
    goal payload and model output are never an authorization source.
    """
    if not isinstance(grant, dict):
        return None
    grant_id = grant.get("grant_id")
    allowed_stages = grant.get("allowed_stages")
    allowed_paths = grant.get("allowed_path_prefixes")
    max_jobs = grant.get("max_jobs")
    expires_at = grant.get("expires_at")
    approved_by = grant.get("approved_by")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if isinstance(expires_at, str) else None
    except ValueError:
        expiry = None
    if (
        not _valid_id(grant_id)
        or grant.get("goal_id") != goal_id
        or grant.get("active") is not True
        or not isinstance(approved_by, str) or not approved_by.strip()
        or expiry is None or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)
        or grant.get("auto_approve_registered_jobs") is not True
        or type(max_jobs) is not int
        or not 1 <= max_jobs <= MAX_AUTONOMOUS_JOBS_PER_GOAL
        or not isinstance(allowed_stages, list)
        or not allowed_stages
        or any(not isinstance(stage, str) or stage not in _STAGES for stage in allowed_stages)
        or len(allowed_stages) != len(set(allowed_stages))
        or not isinstance(allowed_paths, list)
        or not allowed_paths
        or any(not isinstance(path, str) or path not in {"tests/", "uhip/tests/", "docs/", "agents/", "core/", "scripts/"}
               for path in allowed_paths)
        or len(allowed_paths) != len(set(allowed_paths))
        or grant.get("auto_merge", False) is not False
        or grant.get("auto_deploy", False) is not False
    ):
        return None
    return {
        "grant_id": grant_id,
        "approved_by": approved_by.strip(),
        "expires_at": expires_at,
        "max_jobs": max_jobs,
        "allowed_stages": tuple(allowed_stages),
        "allowed_path_prefixes": tuple(allowed_paths),
    }


def plan_next_job(
    goal: object,
    criterion_results: object,
    job_states: object,
    *,
    autonomy_grant: object = None,
) -> dict[str, Any]:
    """Select at most one next JOB using verified goal evidence and risk policy.

    Goal schema:
      {goal_id, objective, success_criteria:[{id, description}],
       jobs:[{id, criterion_id, stage, instruction, allowed_paths, depends_on:[]}]}

    No approval/risk flag supplied by a model or goal payload is trusted.
    A one-time grant must be loaded by the trusted caller from its approval store;
    it is deliberately not accepted inside the goal contract.
    criterion_results maps criterion IDs to PASS, FAIL, or UNKNOWN.
    job_states maps job IDs to pending, running, done, failed, or held.
    """
    if not isinstance(goal, dict):
        return _hold("goal_contract_invalid")
    if "autonomy_policy" in goal:
        return _hold("autonomy_policy_must_be_server_controlled")
    goal_id = goal.get("goal_id")
    objective = goal.get("objective")
    criteria = goal.get("success_criteria")
    jobs = goal.get("jobs")
    if not _valid_id(goal_id) or not isinstance(objective, str) or not objective.strip():
        return _hold("goal_identity_or_objective_invalid")
    if not isinstance(criteria, list) or not criteria or not isinstance(jobs, list):
        return _hold("goal_contract_incomplete")
    if not isinstance(criterion_results, dict) or not isinstance(job_states, dict):
        return _hold("evidence_maps_invalid")

    grant = _validate_autonomy_grant(autonomy_grant, goal_id)
    if autonomy_grant is not None and grant is None:
        return _hold("autonomy_grant_invalid_or_mismatched")

    criterion_ids: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            return _hold("criterion_invalid")
        cid = criterion.get("id")
        description = criterion.get("description")
        if not _valid_id(cid) or cid in criterion_ids or not isinstance(description, str) or not description.strip():
            return _hold("criterion_invalid_or_duplicate")
        criterion_ids.add(cid)
    if set(criterion_results) != criterion_ids:
        return _hold("criterion_evidence_incomplete")
    if any(not isinstance(value, str) or value not in _CRITERION_STATES for value in criterion_results.values()):
        return _hold("criterion_evidence_invalid")

    normalized: list[dict[str, Any]] = []
    job_ids: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            return _hold("job_definition_invalid")
        jid = job.get("id")
        cid = job.get("criterion_id")
        stage = job.get("stage")
        instruction = job.get("instruction")
        paths = job.get("allowed_paths")
        dependencies = job.get("depends_on", [])
        # Authorization and risk claims are computed by policy code, never by
        # the LLM-generated goal contract.
        if "execution_approved" in job or "risk_level" in job:
            return _hold("untrusted_job_authorization_fields")
        if (
            not _valid_id(jid) or jid in job_ids or not _valid_id(cid) or cid not in criterion_ids
            or not isinstance(stage, str) or stage not in _STAGES
            or not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 5000
            or not isinstance(paths, list) or not paths or len(paths) > 10
            or not isinstance(dependencies, list) or not all(_valid_id(dep) for dep in dependencies)
        ):
            return _hold("job_definition_invalid_or_unsafe")
        job_ids.add(jid)
        normalized.append({
            "id": jid, "criterion_id": cid, "stage": stage,
            "instruction": instruction.strip(), "allowed_paths": list(paths),
            "depends_on": list(dependencies),
        })

    if any(dep not in job_ids for job in normalized for dep in job["depends_on"]):
        return _hold("job_dependency_unknown")
    if any(jid not in job_ids or not isinstance(state, str) or state not in _JOB_STATES
           for jid, state in job_states.items()):
        return _hold("job_state_invalid")

    # Reject dependency cycles before selecting any work.
    by_id = {job["id"]: job for job in normalized}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(jid: str) -> bool:
        if jid in visiting:
            return False
        if jid in visited:
            return True
        visiting.add(jid)
        for dep in by_id[jid]["depends_on"]:
            if not visit(dep):
                return False
        visiting.remove(jid)
        visited.add(jid)
        return True

    if not all(visit(jid) for jid in by_id):
        return _hold("job_dependency_cycle")

    if all(value == "PASS" for value in criterion_results.values()):
        return {
            "agent": "GoalAI", "decision": "GOAL_ACHIEVED",
            "reason": "all_success_criteria_verified", "goal_id": goal_id,
            "create_job": False, "execute_job": False,
            "permissions": {"clear_hold": False, "merge": False, "deploy": False},
        }
    if any(value == "UNKNOWN" for value in criterion_results.values()):
        return _hold("success_criteria_not_fully_verified")

    if grant is not None and len(job_states) >= grant["max_jobs"]:
        return _hold(
            "autonomy_job_budget_exhausted",
            goal_id=goal_id,
            job_budget=grant["max_jobs"],
            jobs_registered=len(job_states),
        )

    unmet = {cid for cid, state in criterion_results.items() if state == "FAIL"}
    relevant = [job for job in normalized if job["criterion_id"] in unmet]
    if not relevant:
        return _hold("no_registered_job_for_unmet_criteria")

    eligible: list[tuple[dict[str, Any], dict[str, Any]]] = []
    review_required: list[dict[str, str]] = []
    waiting: list[str] = []
    for job in relevant:
        if job["id"] in job_states:
            continue
        if any(job_states.get(dep) != "done" for dep in job["depends_on"]):
            waiting.append(job["id"])
            continue
        autonomy = evaluate_job_autonomy(job)
        grant_allows = (
            grant is not None
            and job["stage"] in grant["allowed_stages"]
            and all(any(path.startswith(prefix) for prefix in grant["allowed_path_prefixes"])
                    for path in job["allowed_paths"])
        )
        if autonomy.get("decision") != "AUTO_APPROVE" or not grant_allows:
            reason = str(autonomy.get("reason", "goal_autonomy_grant_required"))
            if autonomy.get("decision") == "AUTO_APPROVE" and not grant_allows:
                reason = "outside_goal_autonomy_grant_scope" if grant is not None else "goal_autonomy_grant_required"
            review_required.append({"job_id": job["id"], "reason": reason})
            continue
        eligible.append((job, autonomy))

    if eligible:
        selected, autonomy = eligible[0]
        return {
            "agent": "GoalAI",
            "decision": "PROPOSE_CHILD_JOB",
            "reason": "unmet_criterion_has_auto_approved_dependency_ready_job",
            "goal_id": goal_id,
            "criterion_id": selected["criterion_id"],
            "job": selected,
            "autonomy_policy": autonomy,
            "approval_mode": "deterministic_low_risk_auto_approval",
            "human_approval_required": False,
            "remaining_job_budget": grant["max_jobs"] - len(job_states) - 1,
            "autonomy_grant_id": grant["grant_id"],
            # Planning alone cannot write to the DB or start a worker.
            "create_job": False,
            "execute_job": False,
            "permissions": {
                "clear_hold": False, "merge": False, "deploy": False,
                "modify_secrets_or_permissions": False,
                "mutate_production_data": False,
            },
        }
    if review_required:
        return _hold(
            "human_review_required_for_high_risk_job",
            goal_id=goal_id,
            approval_required_jobs=review_required,
        )
    if waiting:
        return _hold("waiting_for_parent_jobs", goal_id=goal_id, waiting_job_ids=waiting)
    return _hold("no_safe_next_job", goal_id=goal_id)


__all__ = ["plan_next_job", "MAX_AUTONOMOUS_JOBS_PER_GOAL"]
