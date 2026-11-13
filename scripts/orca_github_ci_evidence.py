"""Normalize immutable GitHub Actions evidence for Orca improvement cycles.

This module is pure: it performs no network calls, writes, task claims, or
execution. Callers must supply API responses and preserve the returned source
references so every diagnosis can be traced to a workflow run and head SHA.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class EvidenceRejected(ValueError):
    """Raised when GitHub Actions evidence is incomplete or inconsistent."""


def _positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceRejected(f"{field}_invalid")
    return value


def normalize_workflow_run(run: Any, jobs_payload: Any) -> dict[str, Any]:
    """Return a stable, source-linked run summary; never infer missing outcomes."""
    if not isinstance(run, dict) or not isinstance(jobs_payload, dict):
        raise EvidenceRejected("actions_payload_invalid")
    run_id = _positive_id(run.get("id"), "workflow_run_id")
    workflow_id = _positive_id(run.get("workflow_id"), "workflow_id")
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or not _SHA40.fullmatch(head_sha):
        raise EvidenceRejected("head_sha_invalid")
    name = run.get("name")
    event = run.get("event")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if not isinstance(name, str) or not name.strip():
        raise EvidenceRejected("workflow_name_missing")
    if not isinstance(event, str) or not event:
        raise EvidenceRejected("workflow_event_missing")
    if status not in {"queued", "in_progress", "completed"}:
        raise EvidenceRejected("workflow_status_invalid")
    if status == "completed" and conclusion not in {
        "success", "failure", "cancelled", "timed_out", "action_required",
        "neutral", "skipped", "stale", "startup_failure",
    }:
        raise EvidenceRejected("workflow_conclusion_invalid")
    if status != "completed" and conclusion is not None:
        raise EvidenceRejected("incomplete_run_has_conclusion")
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        raise EvidenceRejected("workflow_jobs_missing")
    normalized_jobs = []
    failed_names = []
    for job in jobs:
        if not isinstance(job, dict):
            raise EvidenceRejected("workflow_job_invalid")
        job_id = _positive_id(job.get("id"), "job_id")
        job_name = job.get("name")
        job_status = job.get("status")
        job_conclusion = job.get("conclusion")
        if not isinstance(job_name, str) or not job_name.strip():
            raise EvidenceRejected("job_name_missing")
        if job_status not in {"queued", "in_progress", "completed"}:
            raise EvidenceRejected("job_status_invalid")
        if job_status == "completed" and not isinstance(job_conclusion, str):
            raise EvidenceRejected("job_conclusion_missing")
        if job_status != "completed" and job_conclusion is not None:
            raise EvidenceRejected("incomplete_job_has_conclusion")
        normalized_jobs.append({
            "id": job_id, "name": job_name, "status": job_status,
            "conclusion": job_conclusion,
        })
        if job_status == "completed" and job_conclusion not in {"success", "skipped", "neutral"}:
            failed_names.append(job_name)
    normalized_jobs.sort(key=lambda item: (item["name"], item["id"]))
    failed_names = sorted(set(failed_names))
    signature_input = "|".join((str(workflow_id), event, *failed_names))
    failure_signature = (
        hashlib.sha256(signature_input.encode("utf-8")).hexdigest()
        if failed_names or conclusion == "failure" else None
    )
    return {
        "schema_version": 1,
        "source": {
            "workflow_run_id": run_id,
            "workflow_run_url": f"actions/runs/{run_id}",
            "jobs_url": f"actions/runs/{run_id}/jobs",
            "head_sha": head_sha,
        },
        "workflow": {
            "id": workflow_id, "name": name, "event": event,
            "status": status, "conclusion": conclusion,
        },
        "jobs": normalized_jobs,
        "failed_job_names": failed_names,
        "failure_signature": failure_signature,
        "evidence_status": "complete" if status == "completed" else "incomplete",
    }


def summarize_workflow_runs(runs: Any, jobs_by_run_id: Any) -> dict[str, Any]:
    """Summarize a supplied page of runs; missing per-run jobs block the snapshot."""
    if not isinstance(runs, list) or not isinstance(jobs_by_run_id, dict):
        raise EvidenceRejected("actions_collection_invalid")
    records = []
    for run in runs:
        if not isinstance(run, dict):
            raise EvidenceRejected("workflow_run_invalid")
        run_id = _positive_id(run.get("id"), "workflow_run_id")
        jobs = jobs_by_run_id.get(str(run_id), jobs_by_run_id.get(run_id))
        if jobs is None:
            raise EvidenceRejected("workflow_jobs_evidence_missing")
        records.append(normalize_workflow_run(run, jobs))
    records.sort(key=lambda item: item["source"]["workflow_run_id"])
    signatures = {}
    for record in records:
        signature = record["failure_signature"]
        if signature:
            signatures[signature] = signatures.get(signature, 0) + 1
    return {
        "schema_version": 1,
        "runs_observed": len(records),
        "runs_incomplete": sum(r["evidence_status"] != "complete" for r in records),
        "failure_signature_counts": dict(sorted(signatures.items())),
        "records": records,
    }
