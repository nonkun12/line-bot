"""Deterministic Goal AI policy for bounded parent/child JOB chains.

This module plans one next child JOB from an explicit goal contract. It does
not call an LLM, persist jobs, execute work, clear HOLD, merge, or deploy.
Callers may persist an approved proposal with job_store.create_job and its
numeric parent_job_id only after their existing authorization checks pass.
"""
from __future__ import annotations

import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_STAGES = frozenset({"requirements", "design", "implementation", "test", "review", "fix", "verify"})
_CRITERION_STATES = frozenset({"PASS", "FAIL", "UNKNOWN"})
_JOB_STATES = frozenset({"pending", "running", "done", "failed", "held"})
_RISK_LEVELS = frozenset({"low", "medium", "high"})


def _valid_autonomy_policy(policy: object) -> bool:
    """Validate a one-time, goal-scoped grant; never grant merge/deploy rights."""
    if not isinstance(policy, dict):
        return False
    stages = policy.get("allowed_stages")
    max_jobs = policy.get("max_jobs")
    return (
        policy.get("mode") == "bounded_autonomous"
        and policy.get("auto_approve_registered_jobs") is True
        and type(max_jobs) is int and 1 <= max_jobs <= 50
        and isinstance(stages, list) and 1 <= len(stages) <= len(_STAGES)
        and all(isinstance(stage, str) and stage in _STAGES for stage in stages)
        and len(stages) == len(set(stages))
        and policy.get("auto_merge", False) is False
        and policy.get("auto_deploy", False) is False
    )


def _hold(reason: str) -> dict[str, Any]:
    return {
        "agent": "GoalAI",
        "decision": "HOLD",
        "reason": reason,
        "create_job": False,
        "execute_job": False,
        "permissions": {"clear_hold": False, "merge": False, "deploy": False},
    }


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def plan_next_job(
    goal: object,
    criterion_results: object,
    job_states: object,
) -> dict[str, Any]:
    """Assess explicit goal evidence and propose at most one eligible child JOB.

    Goal schema:
      {goal_id, objective, success_criteria:[{id, description}],
       jobs:[{id, criterion_id, stage, instruction, allowed_paths,
              depends_on:[], execution_approved:bool}]}

    criterion_results maps criterion IDs to PASS, FAIL, or UNKNOWN.
    job_states maps job IDs to pending, running, done, failed, or held.
    """
    if not isinstance(goal, dict):
        return _hold("goal_contract_invalid")
    goal_id = goal.get("goal_id")
    objective = goal.get("objective")
    criteria = goal.get("success_criteria")
    jobs = goal.get("jobs")
    autonomy_policy = goal.get("autonomy_policy")
    if autonomy_policy is not None and not _valid_autonomy_policy(autonomy_policy):
        return _hold("autonomy_policy_invalid_or_unsafe")
    if not _valid_id(goal_id) or not isinstance(objective, str) or not objective.strip():
        return _hold("goal_identity_or_objective_invalid")
    if not isinstance(criteria, list) or not criteria or not isinstance(jobs, list):
        return _hold("goal_contract_incomplete")
    if not isinstance(criterion_results, dict) or not isinstance(job_states, dict):
        return _hold("evidence_maps_invalid")

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
        approved = job.get("execution_approved")
        risk_level = job.get("risk_level", "medium")
        if (
            not _valid_id(jid) or jid in job_ids or not _valid_id(cid) or cid not in criterion_ids
            or not isinstance(stage, str) or stage not in _STAGES or not isinstance(instruction, str)
            or not instruction.strip() or len(instruction) > 5000
            or not isinstance(paths, list) or not paths or len(paths) > 10
            or not all(isinstance(p, str) and re.fullmatch(r"(tests|uhip/tests)/test_[A-Za-z0-9_]+[.]py", p) for p in paths)
            or not isinstance(dependencies, list) or not all(_valid_id(dep) for dep in dependencies)
            or type(approved) is not bool
            or not isinstance(risk_level, str) or risk_level not in _RISK_LEVELS
        ):
            return _hold("job_definition_invalid_or_unsafe")
        job_ids.add(jid)
        normalized.append({
            "id": jid, "criterion_id": cid, "stage": stage,
            "instruction": instruction.strip(), "allowed_paths": list(paths),
            "depends_on": list(dependencies), "execution_approved": approved,
            "risk_level": risk_level,
        })

    if any(dep not in job_ids for job in normalized for dep in job["depends_on"]):
        return _hold("job_dependency_unknown")
    if any(jid not in job_ids or not isinstance(state, str) or state not in _JOB_STATES
           for jid, state in job_states.items()):
        return _hold("job_state_invalid")
    # A dependency cycle can never become eligible; reject it before planning.
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

    unmet = {cid for cid, state in criterion_results.items() if state != "PASS"}
    if autonomy_policy is not None and len(job_states) >= autonomy_policy["max_jobs"]:
        return {**_hold("autonomy_job_budget_exhausted"), "goal_id": goal_id,
                "job_budget": autonomy_policy["max_jobs"], "jobs_registered": len(job_states)}
    relevant = [job for job in normalized if job["criterion_id"] in unmet]
    if not relevant:
        return _hold("no_registered_job_for_unmet_criteria")

    eligible = []
    approval_required = []
    waiting = []
    for job in relevant:
        if job["id"] in job_states:
            continue
        if any(job_states.get(dep) != "done" for dep in job["depends_on"]):
            waiting.append(job["id"])
            continue
        policy_auto_approved = (
            autonomy_policy is not None
            and autonomy_policy["auto_approve_registered_jobs"] is True
            and job["stage"] in autonomy_policy["allowed_stages"]
            and job["risk_level"] in {"low", "medium"}
        )
        if not job["execution_approved"] and not policy_auto_approved:
            approval_required.append(job["id"])
            continue
        eligible.append(job)

    if eligible:
        selected = eligible[0]  # Stable order from the reviewed goal contract.
        return {
            "agent": "GoalAI", "decision": "PROPOSE_CHILD_JOB",
            "reason": "unmet_criterion_has_approved_dependency_ready_job",
            "goal_id": goal_id, "criterion_id": selected["criterion_id"],
            "job": selected, "create_job": False, "execute_job": False,
            "approval_mode": "goal_scoped_autonomy" if autonomy_policy is not None and not selected["execution_approved"] else "explicit_job_approval",
            "human_approval_required": False,
            "remaining_job_budget": (autonomy_policy["max_jobs"] - len(job_states) - 1) if autonomy_policy is not None else None,
            "permissions": {"clear_hold": False, "merge": False, "deploy": False},
        }
    if approval_required:
        return {**_hold("human_approval_required"), "goal_id": goal_id,
                "approval_required_job_ids": approval_required}
    if waiting:
        return {**_hold("waiting_for_parent_jobs"), "goal_id": goal_id,
                "waiting_job_ids": waiting}
    return {**_hold("no_safe_next_job"), "goal_id": goal_id}
