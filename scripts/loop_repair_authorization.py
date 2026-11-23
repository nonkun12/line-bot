"""Separate, one-shot authorization for a single bounded repair attempt.

This module is a gate/ledger primitive only. It does not generate or apply patches,
clear HOLD, resume tasks, dispatch workflows, merge, or deploy.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

SAFE_REPAIR_CATEGORIES = frozenset({"test_regression", "timeout", "process_crash"})


def _sha(value: Any, length: int = 40) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _canonical_paths(paths: Any) -> tuple[list[str], str] | None:
    if (
        not isinstance(paths, list) or not paths or len(paths) > 20
        or not all(isinstance(p, str) and p and len(p) <= 240 for p in paths)
        or len(set(paths)) != len(paths)
    ):
        return None
    for path in paths:
        if path.startswith("/") or "\\" in path or ":" in path:
            return None
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return None
        if any(char in part for part in parts for char in "*?[]{}"):
            return None
    canonical = sorted(paths)
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return canonical, digest


def authorize_repair(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate a separately preapproved, task-bound, single repair envelope."""
    blocked = {"gate": "BLOCKED", "execution_authorized": False, "reason_code": "repair_authorization_invalid"}
    if not isinstance(evidence, dict):
        return blocked
    task_id = evidence.get("task_id")
    instruction_sha = evidence.get("instruction_sha256")
    base_sha = evidence.get("base_sha")
    failure_fingerprint = evidence.get("failure_fingerprint")
    paths = _canonical_paths(evidence.get("allowed_paths"))
    if (
        not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id)
        or not _sha(instruction_sha, 64) or not _sha(base_sha)
        or not _sha(failure_fingerprint, 64) or paths is None
        or evidence.get("catalog_repair_approved") is not True
        or evidence.get("execution_approved") is not True
        or evidence.get("held") is not False
        or evidence.get("working_tree_clean") is not True
        or evidence.get("rea_status") != "PRE_REPAIR_PASS"
        or evidence.get("failure_category") not in SAFE_REPAIR_CATEGORIES
        or type(evidence.get("repair_attempts")) is not int
        or evidence.get("repair_attempts") != 0
        or evidence.get("current_head_sha") != base_sha
    ):
        return blocked
    return {
        "gate": "PASS",
        "execution_authorized": True,
        "scope": "one_repair_attempt",
        "reason_code": "separately_preapproved_repair_envelope",
        "task_id": task_id,
        "instruction_sha256": instruction_sha,
        "allowed_paths": paths[0],
        "allowed_paths_sha256": paths[1],
        "base_sha": base_sha,
        "failure_fingerprint": failure_fingerprint,
        "repair_attempts": 1,
    }


def consume_repair_authorization(
    authorization: dict[str, Any], *, token: str, repository: str = "nonkun12/line-bot"
) -> dict[str, Any]:
    """Atomically consume a unique Git ref; a duplicate attempt fails closed."""
    if (
        not isinstance(authorization, dict)
        or authorization.get("gate") != "PASS"
        or authorization.get("execution_authorized") is not True
        or not token
        or repository != "nonkun12/line-bot"
    ):
        return {"gate": "BLOCKED", "reason_code": "repair_authorization_not_consumable"}
    identity = {
        key: authorization.get(key)
        for key in (
            "task_id", "instruction_sha256", "allowed_paths_sha256",
            "base_sha", "failure_fingerprint",
        )
    }
    if not all(isinstance(value, str) and value for value in identity.values()):
        return {"gate": "BLOCKED", "reason_code": "repair_authorization_identity_invalid"}
    marker = hashlib.sha256(
        json.dumps(
            {"repository": repository, **identity},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    ref = f"refs/heads/rsi-repair-consumed/{marker}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/git/refs",
        data=json.dumps({"ref": ref, "sha": identity["base_sha"]}).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "line-bot-rsi-repair-approval-gate",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if (
                response.status != 201 or payload.get("ref") != ref
                or not isinstance(payload.get("object"), dict)
                or payload["object"].get("sha") != identity["base_sha"]
            ):
                return {"gate": "BLOCKED", "reason_code": "repair_ledger_response_invalid"}
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            return {"gate": "BLOCKED", "reason_code": "repair_attempt_already_consumed"}
        return {"gate": "BLOCKED", "reason_code": f"repair_ledger_http_{exc.code}"}
    except Exception as exc:
        return {"gate": "BLOCKED", "reason_code": f"repair_ledger_error:{type(exc).__name__}"}
    return {
        "gate": "PASS",
        "reason_code": "repair_authorization_consumed_once",
        "marker_ref": ref,
        "marker_sha": identity["base_sha"],
    }
