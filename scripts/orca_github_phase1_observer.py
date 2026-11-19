"""Read-only Phase 1 observer for the GitHub-native Orca LOOP.

This observer never claims, mutates, or executes tasks. Missing state or
unverifiable inputs are reported as BLOCKED.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Callable


class ObservationError(RuntimeError):
    """Raised when a state snapshot cannot be safely observed."""


def _request_json(
    *,
    token: str,
    repository: str,
    route: str,
    opener: Callable = urllib.request.urlopen,
) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com" + route,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orca-phase1-read-only-observer",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=10) as response:
            raw = response.read(1_000_000)
        value = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ObservationError("github_resource_not_found") from None
        raise ObservationError("github_api_request_rejected") from None
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        raise ObservationError("github_api_unavailable_or_invalid") from None
    if not isinstance(value, dict):
        raise ObservationError("github_api_response_invalid")
    return value


def read_state_snapshot(
    *,
    token: str,
    repository: str,
    branch: str = "orca-state",
    path: str = "state/queue.json",
    opener: Callable = urllib.request.urlopen,
) -> tuple[str, dict[str, Any]]:
    if not token or not repository or "/" not in repository or not branch or not path:
        raise ObservationError("observer_configuration_missing")
    repo = urllib.parse.quote(repository, safe="/")
    ref_name = urllib.parse.quote(branch, safe="")
    ref = _request_json(
        token=token, repository=repository,
        route=f"/repos/{repo}/git/ref/heads/{ref_name}", opener=opener,
    )
    ref_object = ref.get("object")
    ref_sha = ref_object.get("sha") if isinstance(ref_object, dict) else None
    if not isinstance(ref_sha, str) or len(ref_sha) != 40:
        raise ObservationError("state_ref_sha_missing_or_invalid")
    encoded_path = urllib.parse.quote(path, safe="/")
    document = _request_json(
        token=token, repository=repository,
        route=f"/repos/{repo}/contents/{encoded_path}?ref={ref_sha}", opener=opener,
    )
    if document.get("encoding") != "base64" or not isinstance(document.get("content"), str):
        raise ObservationError("state_document_missing_or_invalid")
    try:
        raw = base64.b64decode(document["content"], validate=False)
        state = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise ObservationError("state_document_unreadable") from None
    if not isinstance(state, dict):
        raise ObservationError("state_document_invalid")
    return ref_sha, state


def summarize_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ObservationError("queue_state_missing_or_invalid")
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ObservationError("queue_revision_invalid")
    hold = state.get("global_hold")
    if not isinstance(hold, bool):
        raise ObservationError("global_hold_missing_or_invalid")
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise ObservationError("queue_tasks_invalid")
    if "active_lease" not in state:
        raise ObservationError("active_lease_missing")
    counts: Counter[str] = Counter()
    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ObservationError("queue_task_invalid")
        task_id = task.get("task_id")
        status = task.get("status")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise ObservationError("queue_task_identity_invalid")
        if not isinstance(status, str) or status not in {"queued", "claimed", "done", "failed"}:
            raise ObservationError("queue_task_status_invalid")
        task_ids.add(task_id)
        counts[status] += 1
    lease = state.get("active_lease")
    if counts["claimed"] > 1:
        raise ObservationError("multiple_claimed_tasks")
    if (lease is None) != (counts["claimed"] == 0):
        raise ObservationError("active_lease_mismatch")
    if lease is not None:
        claimed_ids = {task["task_id"] for task in tasks if task["status"] == "claimed"}
        if not isinstance(lease, dict) or not isinstance(lease.get("task_id"), str):
            raise ObservationError("active_lease_invalid")
        if lease["task_id"] not in task_ids or lease["task_id"] not in claimed_ids:
            raise ObservationError("active_lease_invalid")
        if not all(isinstance(lease.get(key), str) and lease[key]
                   for key in ("owner", "run_id", "expires_at")):
            raise ObservationError("active_lease_fields_invalid")
    return {
        "revision": revision,
        "global_hold": hold,
        "task_counts": {key: counts[key] for key in ("queued", "claimed", "done", "failed")},
        "active_lease": lease is not None,
    }


def observe(
    *,
    token: str,
    repository: str,
    branch: str = "orca-state",
    path: str = "state/queue.json",
    opener: Callable = urllib.request.urlopen,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "phase": 1,
        "mode": "read_only_observation",
        "execution_enabled": False,
        "budget_evidence": "MISSING",
    }
    try:
        ref_sha, state = read_state_snapshot(
            token=token, repository=repository, branch=branch, path=path, opener=opener,
        )
        summary = summarize_state(state)
    except ObservationError as exc:
        result.update({
            "observation_status": "BLOCKED",
            "execution_gate": "BLOCKED",
            "reason": str(exc),
        })
    else:
        result.update({
            "observation_status": "OBSERVED",
            "execution_gate": "BLOCKED",
            "reason": "budget_evidence_missing",
            "state_ref_sha": ref_sha,
            "state": summary,
        })
        if summary["global_hold"]:
            result["reason"] = "global_hold_active;budget_evidence_missing"
    return result


def main() -> int:
    result = observe(
        token=os.environ.get("GITHUB_TOKEN", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        branch=os.environ.get("ORCA_STATE_BRANCH", "orca-state"),
        path=os.environ.get("ORCA_STATE_PATH", "state/queue.json"),
    )
    rendered = json.dumps(result, sort_keys=True, ensure_ascii=False)
    print(rendered)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        state = result.get("state", {})
        counts = state.get("task_counts", {})
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("# Orca Phase 1 — read-only observation\n\n")
            summary.write(f"- Observation: **{result['observation_status']}**\n")
            summary.write(f"- Execution gate: **{result['execution_gate']}**\n")
            summary.write(f"- Reason: `{result['reason']}`\n")
            summary.write("- Execution enabled: **false**\n")
            summary.write(f"- Budget evidence: **{result['budget_evidence']}**\n")
            if state:
                summary.write(f"- State revision: {state['revision']}\n")
                summary.write(f"- Global HOLD: **{state['global_hold']}**\n")
                summary.write(f"- Queue counts: {json.dumps(counts, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
