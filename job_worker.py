"""One-step asynchronous Job worker with bounded development retries."""

from __future__ import annotations

import json
import os
import socket

import job_approvals
import job_store
from job_lease import recover_stale_jobs
from job_orchestrator import (
    decide_deploy_failure,
    decide_executor_failure,
    decide_test_failure,
    job_time_exceeded,
    test_failure_has_no_progress,
)
from job_workspace import restore_workspace_for_job, workspace_for_job


APPROVAL_NODES = {"merge_agent": "commit", "deploy_agent": "deploy"}
_WORKER_GRAPH = None
WORKER_ID = os.environ.get("JOB_WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"
JOB_LEASE_SECONDS = int(os.environ.get("JOB_LEASE_SECONDS", "300"))


def _get_worker_graph():
    global _WORKER_GRAPH
    if _WORKER_GRAPH is None:
        from standalone_agent_graph import build_worker_graph
        _WORKER_GRAPH = build_worker_graph()
    return _WORKER_GRAPH


def _thread_id(job_id: int) -> str:
    return f"job-{job_id}"


def _initial_state(job: dict, *, branch: str | None = None) -> dict:
    state = {
        "job_id": job["id"],
        "user_id": job["user_id"], "raw_message": job["message"],
        "job_type": job.get("job_type", "ai_task"), "request_id": _thread_id(job["id"]),
        "agent_results": {},
    }
    if job.get("job_type") == "development":
        state["workdir"] = workspace_for_job(job["id"], branch=branch)
    return state


def _resume_workdir(values: dict, job: dict) -> dict:
    """Restore a missing Job worktree from its published Job branch."""
    if job.get("job_type") != "development":
        return values
    current = values.get("workdir")
    if current and os.path.isdir(current):
        return values

    publish_result = values.get("publish_result") or {}
    commit_result = values.get("commit_result") or {}
    branch = (
        (publish_result.get("branch"))
        or ((publish_result.get("pr") or {}).get("head_branch"))
        or (commit_result.get("branch"))
    )
    if not branch:
        return values

    try:
        restored = restore_workspace_for_job(job["id"], branch)
    except Exception as exc:
        values = dict(values)
        values["workdir_restore_error"] = str(exc)
        return values
    restored_values = dict(values)
    restored_values["workdir"] = restored
    return restored_values


def _checkpoint_summary(values: dict) -> str:
    payload = {"thread_id": values.get("request_id"), "job_type": values.get("job_type"),
               "job_id": values.get("job_id"), "workdir": values.get("workdir"),
               "intent": values.get("intent"), "next_agent": values.get("next_agent"),
               "error": values.get("error"), "development_error": values.get("development_error"),
               "workdir_restore_error": values.get("workdir_restore_error"),
               "test_result": values.get("test_result"), "publish_result": values.get("publish_result"),
               "review_result": values.get("review_result"), "merge_result": values.get("merge_result"),
               "deploy_result": values.get("deploy_result"),
               "final_reply": values.get("final_reply")}
    return json.dumps(payload, ensure_ascii=False, default=str)


def _request_and_wait(job: dict, next_node: str, values: dict) -> dict:
    operation = APPROVAL_NODES[next_node]
    existing = job_approvals.get(job["id"], operation)
    approval = job_approvals.request(job["id"], job["user_id"], operation)
    return {"status": "waiting_approval", "thread_id": _thread_id(job["id"]),
            "step_name": next_node, "next_step": next_node, "operation": operation,
            "approval_id": approval["id"], "approval_created": existing is None,
            "summary": _checkpoint_summary(values)}


def execute_one_step(job: dict, graph=None) -> dict:
    if job_time_exceeded(job):
        return {"status": "failed", "thread_id": _thread_id(job["id"]),
                "step_name": "worker", "error": "job total time limit exceeded",
                "summary": "job total time limit exceeded"}

    graph = graph or _get_worker_graph()
    thread_id = _thread_id(job["id"])
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot.values:
        current_node = snapshot.next[0] if snapshot.next else None
        resumed_values = _resume_workdir(dict(snapshot.values), job)
        input_state = None
        if resumed_values != dict(snapshot.values):
            input_state = resumed_values
    else:
        current_node = "development_agent" if job.get("job_type") == "development" else "supervisor"
        input_state = _initial_state(job)

    if current_node in APPROVAL_NODES:
        operation = APPROVAL_NODES[current_node]
        approval_status = job_approvals.status(job["id"], operation)
        if approval_status == "approved":
            if not job_approvals.consume(job["id"], operation):
                return _request_and_wait(job, current_node, snapshot.values or {})
        elif approval_status == "pending":
            return _request_and_wait(job, current_node, snapshot.values or {})
        elif approval_status in {"rejected", "expired"}:
            return {
                "status": "failed", "thread_id": thread_id, "step_name": current_node,
                "error": f"{operation} approval {approval_status}",
                "summary": f"{operation} approval {approval_status}",
            }
        elif job.get("status") == "failed":
            return {
                "status": "failed", "thread_id": thread_id, "step_name": current_node,
                "error": job.get("last_error") or f"{operation} approval terminated the job",
                "summary": job.get("last_error") or f"{operation} approval terminated the job",
            }
        else:
            return _request_and_wait(job, current_node, snapshot.values or {})

    graph.invoke(input_state, config)
    snapshot = graph.get_state(config)
    values = dict(snapshot.values or {})
    next_nodes = list(snapshot.next or ())
    if not next_nodes:
        return {"status": "graph_done", "thread_id": thread_id,
                "step_name": current_node or "finalizer", "summary": _checkpoint_summary(values)}

    next_node = next_nodes[0]
    if next_node in APPROVAL_NODES:
        return _request_and_wait(job, next_node, values)
    if current_node == "development_agent" and values.get("development_error"):
        return {"status": "executor_failed", "thread_id": thread_id, "step_name": current_node,
                "error": values["development_error"], "summary": _checkpoint_summary(values)}
    if current_node == "test_agent" and next_node == "debug_agent":
        return {"status": "test_failed", "thread_id": thread_id, "step_name": "test_agent",
                "next_step": next_node, "test_result": values.get("test_result") or {},
                "summary": _checkpoint_summary(values)}
    if current_node == "publish_agent":
        publish_result = values.get("publish_result") or {}
        if publish_result.get("manual_required"):
            return {"status": "step_completed", "thread_id": thread_id,
                    "step_name": current_node, "next_step": next_node,
                    "summary": _checkpoint_summary(values)}
        if publish_result.get("published") is False:
            return {"status": "publish_failed", "thread_id": thread_id, "step_name": current_node,
                    "error": publish_result.get("error") or "publish failed",
                    "summary": _checkpoint_summary(values)}
    if current_node == "review_agent":
        review_result = values.get("review_result") or {}
        if review_result.get("status") == "pending":
            return {"status": "step_completed", "thread_id": thread_id,
                    "step_name": current_node, "next_step": next_node,
                    "summary": _checkpoint_summary(values)}
        if review_result.get("status") == "failed":
            if review_result.get("ai_review") and review_result.get("retryable") and next_node == "fix_agent":
                return {"status": "step_completed", "thread_id": thread_id,
                        "step_name": current_node, "next_step": next_node,
                        "summary": _checkpoint_summary(values)}
            return {"status": "failed", "thread_id": thread_id,
                    "step_name": current_node,
                    "error": review_result.get("reason") or "review failed",
                    "summary": _checkpoint_summary(values)}
    if current_node == "merge_agent":
        merge_result = values.get("merge_result") or {}
        if merge_result.get("merged") is False:
            return {"status": "executor_failed", "thread_id": thread_id, "step_name": current_node,
                    "error": merge_result.get("error") or "merge failed",
                    "summary": _checkpoint_summary(values)}
    if current_node == "deploy_agent":
        deploy_result = values.get("deploy_result") or {}
        if deploy_result.get("pending"):
            return {"status": "step_completed", "thread_id": thread_id, "step_name": current_node, "next_step": next_node,
                    "summary": _checkpoint_summary(values)}
        if deploy_result.get("deployed") is False:
            return {"status": "deploy_failed", "thread_id": thread_id, "step_name": current_node, "next_step": next_node,
                    "deploy_result": deploy_result, "summary": _checkpoint_summary(values)}
    return {"status": "step_completed", "thread_id": thread_id, "step_name": current_node or "unknown", "next_step": next_node,
            "summary": _checkpoint_summary(values)}


def _owned_update(job_id, **kwargs):
    """Update a Job only while this worker still owns its active lease."""
    return job_store.update_job_owned(job_id, WORKER_ID, **kwargs)


def _apply_retry_decision(job, decision, result, *, checkpoint_prefix):
    status = decision.terminal_status
    updated = _owned_update(job["id"], status=status, result=result.get("summary", ""),
                            last_error=decision.reason, retry_count=decision.retry_count,
                            clear_lease=True)
    if not updated:
        return job_store.get_job(job["id"])
    checkpoint_step = "test_agent" if checkpoint_prefix == "test" else checkpoint_prefix
    job_store.save_checkpoint(job["id"], checkpoint_step,
                              f"{checkpoint_prefix}_{'retry_scheduled' if decision.retry else 'retry_exhausted'}",
                              result.get("summary", ""))
    return job_store.get_job(job["id"])


def _handle_executor_failure(job, exc: Exception):
    return _apply_retry_decision(job, decide_executor_failure(job), {"summary": str(exc)}, checkpoint_prefix="executor")


def _handle_test_failure(job, result: dict):
    if test_failure_has_no_progress(job.get("result"), result.get("summary")):
        updated = _owned_update(job["id"], status="failed", result=result.get("summary", ""),
                                last_error="automated test failed; no progress detected",
                                clear_lease=True)
        if updated:
            job_store.save_checkpoint(job["id"], "test_agent", "no_progress",
                                      result.get("summary", ""))
        return job_store.get_job(job["id"])
    return _apply_retry_decision(job, decide_test_failure(job), result, checkpoint_prefix="test")


def _handle_deploy_failure(job, result: dict):
    return _apply_retry_decision(job, decide_deploy_failure(job), result, checkpoint_prefix="deploy")


def _handle_publish_failure(job, result: dict):
    return _apply_retry_decision(job, decide_executor_failure(job), result, checkpoint_prefix="publish")


def _fail_for_time_limit(job):
    summary = "job total time limit exceeded"
    updated = _owned_update(job["id"], status="failed", result=summary,
                            last_error=summary, clear_lease=True)
    if updated:
        job_store.save_checkpoint(job["id"], "worker", "time_limit_exceeded", summary)
    return job_store.get_job(job["id"])


def run_once(executor=None):
    recover_stale_jobs()
    job = job_store.claim_pending_job(worker_id=WORKER_ID, lease_seconds=JOB_LEASE_SECONDS)
    if job is None:
        return None
    job_id = job["id"]
    job_store.save_checkpoint(job_id, "worker", "started", WORKER_ID)
    try:
        if job_time_exceeded(job):
            return _fail_for_time_limit(job)
        if not job_store.renew_job_lease(job_id, WORKER_ID, lease_seconds=JOB_LEASE_SECONDS):
            return job_store.get_job(job_id)
        result = executor(job) if executor is not None else execute_one_step(job)
        if not job_store.renew_job_lease(job_id, WORKER_ID, lease_seconds=JOB_LEASE_SECONDS):
            job_store.save_checkpoint(job_id, "worker", "lease_lost", "worker lease was lost before result commit")
            return job_store.get_job(job_id)
        status = result.get("status")
        if status == "graph_done":
            updated = _owned_update(job_id, status="done", result=result.get("summary", ""), last_error=None, clear_lease=True)
            checkpoint_status = "completed" if updated else "lease_lost"
        elif status == "waiting_approval":
            updated = _owned_update(job_id, status="waiting_approval", result=result.get("summary", ""),
                                    last_error=None, clear_lease=True)
            if not updated:
                return job_store.get_job(job_id)
            checkpoint_status = "waiting_approval"
            job = job_store.get_job(job_id)
            job["_worker_result"] = {
                "status": status, "operation": result.get("operation"),
                "approval_id": result.get("approval_id"),
                "approval_created": bool(result.get("approval_created")),
                "step_name": result.get("step_name"),
            }
            job_store.save_checkpoint(job_id, result.get("step_name", "worker"), checkpoint_status, result.get("summary"))
            return job
        elif status == "test_failed":
            return _handle_test_failure(job, result)
        elif status == "publish_failed":
            return _handle_publish_failure(job, result)
        elif status == "deploy_failed":
            return _handle_deploy_failure(job, result)
        elif status == "executor_failed":
            return _handle_executor_failure(job, RuntimeError(result.get("error") or result.get("summary") or "worker execution failed"))
        elif status == "step_completed":
            retry_count = 0 if (result.get("step_name") == "test_agent" and result.get("next_step") == "commit_agent") else None
            updated = _owned_update(job_id, status="pending", result=result.get("summary", ""), last_error=None,
                                    retry_count=retry_count, clear_lease=True)
            checkpoint_status = "completed" if updated else "lease_lost"
        elif status == "failed":
            updated = _owned_update(job_id, status="failed", result=result.get("summary", ""),
                                    last_error=result.get("error"), clear_lease=True)
            checkpoint_status = "failed" if updated else "lease_lost"
        else:
            raise RuntimeError(f"unknown executor status: {status!r}")
        job_store.save_checkpoint(job_id, result.get("step_name", "worker"), checkpoint_status, result.get("summary"))
        return job_store.get_job(job_id)
    except Exception as exc:
        return _handle_executor_failure(job, exc)


if __name__ == "__main__":
    result = run_once()
    print(result if result is not None else "no pending jobs")
