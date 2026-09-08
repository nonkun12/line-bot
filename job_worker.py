"""One-step asynchronous Job worker with bounded development retries."""

from __future__ import annotations

import json

import job_approvals
import job_store
from job_lease import recover_stale_jobs


APPROVAL_NODES = {
    "commit_agent": "commit",
    "deploy_agent": "deploy",
}

_WORKER_GRAPH = None


def _get_worker_graph():
    global _WORKER_GRAPH
    if _WORKER_GRAPH is None:
        from standalone_agent_graph import build_worker_graph
        _WORKER_GRAPH = build_worker_graph()
    return _WORKER_GRAPH


def _thread_id(job_id: int) -> str:
    return f"job-{job_id}"


def _initial_state(job: dict) -> dict:
    return {
        "user_id": job["user_id"],
        "raw_message": job["message"],
        "request_id": _thread_id(job["id"]),
        "agent_results": {},
    }


def _checkpoint_summary(values: dict) -> str:
    payload = {
        "thread_id": values.get("request_id"),
        "intent": values.get("intent"),
        "next_agent": values.get("next_agent"),
        "error": values.get("error"),
        "test_result": values.get("test_result"),
        "final_reply": values.get("final_reply"),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _request_and_wait(job: dict, next_node: str, values: dict) -> dict:
    operation = APPROVAL_NODES[next_node]
    approval = job_approvals.request(job["id"], job["user_id"], operation)
    return {
        "status": "waiting_approval",
        "thread_id": _thread_id(job["id"]),
        "step_name": next_node,
        "next_step": next_node,
        "operation": operation,
        "approval_id": approval["id"],
        "summary": _checkpoint_summary(values),
    }


def execute_one_step(job: dict, graph=None) -> dict:
    """Advance exactly one graph node, enforcing approval before dangerous nodes."""
    graph = graph or _get_worker_graph()
    thread_id = _thread_id(job["id"])
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    has_previous_state = bool(snapshot.values)
    if has_previous_state:
        current_node = snapshot.next[0] if snapshot.next else None
        input_state = None
    else:
        current_node = "supervisor"
        input_state = _initial_state(job)

    if current_node in APPROVAL_NODES:
        operation = APPROVAL_NODES[current_node]
        approval_status = job_approvals.status(job["id"], operation)
        if approval_status != "approved":
            return _request_and_wait(job, current_node, snapshot.values or {})
        if not job_approvals.consume(job["id"], operation):
            return _request_and_wait(job, current_node, snapshot.values or {})

    graph.invoke(input_state, config)
    snapshot = graph.get_state(config)
    values = dict(snapshot.values or {})
    next_nodes = list(snapshot.next or ())

    if not next_nodes:
        return {
            "status": "graph_done",
            "thread_id": thread_id,
            "step_name": current_node or "finalizer",
            "summary": _checkpoint_summary(values),
        }

    next_node = next_nodes[0]
    if next_node in APPROVAL_NODES:
        return _request_and_wait(job, next_node, values)

    # The graph itself performs Test -> Debug. The persistent Job owns the
    # retry budget so the cycle cannot become infinite.
    if current_node == "test_agent" and next_node == "debug_agent":
        test_result = values.get("test_result") or {}
        return {
            "status": "test_failed",
            "thread_id": thread_id,
            "step_name": "test_agent",
            "next_step": next_node,
            "test_result": test_result,
            "summary": _checkpoint_summary(values),
        }

    return {
        "status": "step_completed",
        "thread_id": thread_id,
        "step_name": current_node or "unknown",
        "next_step": next_node,
        "summary": _checkpoint_summary(values),
    }


def _handle_executor_failure(job: dict, exc: Exception):
    retry_count = int(job.get("retry_count") or 0) + 1
    message = str(exc)
    if retry_count <= int(job.get("max_retries") or 0):
        job_store.update_job(
            job["id"], status="pending", last_error=message,
            retry_count=retry_count, clear_claimed_at=True,
        )
        status = "pending"
    else:
        job_store.update_job(
            job["id"], status="failed", last_error=message,
            retry_count=retry_count, clear_claimed_at=True,
        )
        status = "failed"
    job_store.save_checkpoint(
        job["id"], "worker",
        "failed" if status == "failed" else "retry_scheduled",
        message,
    )
    return job_store.get_job(job["id"])


def _handle_test_failure(job: dict, result: dict):
    retry_count = int(job.get("retry_count") or 0) + 1
    summary = result.get("summary", "test failed")
    if retry_count <= int(job.get("max_retries") or 0):
        job_store.update_job(
            job["id"], status="pending", result=summary,
            last_error="automated test failed",
            retry_count=retry_count, clear_claimed_at=True,
        )
        status = "pending"
        checkpoint_status = "test_failed_retry_scheduled"
    else:
        job_store.update_job(
            job["id"], status="failed", result=summary,
            last_error="automated test failed: retry limit reached",
            retry_count=retry_count, clear_claimed_at=True,
        )
        status = "failed"
        checkpoint_status = "test_failed_retry_exhausted"
    job_store.save_checkpoint(job["id"], "test_agent", checkpoint_status, summary)
    return job_store.get_job(job["id"])


def run_once(executor=None):
    """Claim one Job, advance one logical step, and exit."""
    recover_stale_jobs()
    job = job_store.claim_pending_job()
    if job is None:
        return None

    job_id = job["id"]
    job_store.save_checkpoint(job_id, "worker", "started")

    try:
        result = executor(job) if executor is not None else execute_one_step(job)
        status = result.get("status")
        if status == "graph_done":
            job_store.update_job(
                job_id, status="done", result=result.get("summary", ""),
                last_error=None, clear_claimed_at=True,
            )
            checkpoint_status = "completed"
        elif status == "waiting_approval":
            job_store.update_job(
                job_id, status="waiting_approval", result=result.get("summary", ""),
                last_error=None, clear_claimed_at=True,
            )
            checkpoint_status = "waiting_approval"
        elif status == "test_failed":
            return _handle_test_failure(job, result)
        elif status == "step_completed":
            job_store.update_job(
                job_id, status="pending", result=result.get("summary", ""),
                last_error=None, clear_claimed_at=True,
            )
            checkpoint_status = "completed"
        elif status == "failed":
            job_store.update_job(
                job_id, status="failed", result=result.get("summary", ""),
                last_error=result.get("error"), clear_claimed_at=True,
            )
            checkpoint_status = "failed"
        else:
            raise RuntimeError(f"unknown executor status: {status!r}")

        job_store.save_checkpoint(
            job_id, result.get("step_name", "worker"),
            checkpoint_status, result.get("summary"),
        )
        return job_store.get_job(job_id)

    except Exception as exc:
        return _handle_executor_failure(job, exc)


if __name__ == "__main__":
    result = run_once()
    print(result if result is not None else "no pending jobs")
