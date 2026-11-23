"""Fail-closed coordinator for one authorized repair and independent post-repair REA.

The default repair adapter uses only loopback Ollama/LFM3; callers may inject a
trusted provider-free adapter for tests or another local runtime. An independent
REA runner is always required. This module never clears HOLD or resumes a task.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from scripts.loop_repair_authorization import authorize_repair, consume_repair_authorization


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=15,
    )
    return completed.stdout.strip()


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason_code": reason,
        "repair_executed": False,
        "hold_clear_authorized": False,
        "resume_authorized": False,
    }


def execute_one_repair(
    evidence: dict[str, Any],
    *,
    token: str,
    repair_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    repo_root: str | Path,
    repository: str = "nonkun12/line-bot",
    rea_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Consume authorization, run one trusted repair, then require independent REA.

    The default adapter is loopback-only and provider-free. An injected adapter
    must follow the same trust boundary; arbitrary model output is
    never accepted as an executable command by this coordinator.
    """
    root = Path(repo_root).resolve()
    if rea_runner is None:
        try:
            from scripts.loop_rea_runner import create_post_repair_rea_runner
            rea_runner = create_post_repair_rea_runner(root)
        except Exception:
            return _blocked("independent_rea_runner_unavailable")
    if repair_executor is None:
        try:
            from scripts.loop_local_repair_adapter import create_local_repair_adapter
            repair_executor = create_local_repair_adapter(root)
        except Exception:
            return _blocked("local_repair_adapter_unavailable")
    try:
        authorization = authorize_repair(evidence)
    except Exception:
        return _blocked("repair_authorization_error")
    if authorization.get("gate") != "PASS":
        return _blocked(str(authorization.get("reason_code", "repair_authorization_blocked")))

    try:
        before_head = _git(root, "rev-parse", "HEAD")
        before_status = _git(root, "status", "--porcelain", "--untracked-files=all")
    except Exception:
        return _blocked("repository_state_unreadable")
    if before_head != evidence.get("base_sha") or before_status:
        return _blocked("repository_not_at_clean_authorized_base")

    try:
        consumed = consume_repair_authorization(
            authorization, token=token, repository=repository
        )
    except Exception:
        return _blocked("repair_authorization_consumption_error")
    if consumed.get("gate") != "PASS":
        return _blocked(str(consumed.get("reason_code", "repair_authorization_not_consumed")))

    request = {
        "task_id": authorization["task_id"],
        "instruction_sha256": authorization["instruction_sha256"],
        # The adapter verifies this exact text against the authorized digest before use.
        "instruction": evidence.get("instruction", ""),
        "allowed_paths": authorization["allowed_paths"],
        "base_sha": authorization["base_sha"],
        "failure_fingerprint": authorization["failure_fingerprint"],
        "repair_attempt": 1,
        "provider_policy": "provider_free_only",
    }
    try:
        repair_result = repair_executor(request)
    except Exception as exc:
        return _blocked("repair_executor_error:" + type(exc).__name__)
    if not isinstance(repair_result, dict) or repair_result.get("status") != "PASS":
        return _blocked("repair_executor_not_pass")

    try:
        after_head = _git(root, "rev-parse", "HEAD")
        changed = _git(root, "diff", "--name-only").splitlines()
        staged = _git(root, "diff", "--cached", "--name-only").splitlines()
        untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
        post_repair_status = _git(root, "status", "--porcelain", "--untracked-files=all")
    except Exception:
        return _blocked("post_repair_repository_state_unreadable")
    allowed = set(authorization["allowed_paths"])
    actual = set(changed + staged + untracked)
    if after_head != before_head:
        return _blocked("repair_changed_git_head")
    if not actual or not actual.issubset(allowed):
        return _blocked("repair_changed_paths_outside_allowlist_or_no_change")

    try:
        post_rea = rea_runner({
            "stage": "POST_REPAIR",
            "task_id": authorization["task_id"],
            "base_sha": before_head,
            "allowed_paths": authorization["allowed_paths"],
            "changed_paths": sorted(actual),
            "repair_attempt": 1,
        })
    except Exception as exc:
        return _blocked("post_repair_rea_error:" + type(exc).__name__)
    if (
        not isinstance(post_rea, dict)
        or post_rea.get("status") != "PASS"
        or post_rea.get("base_sha") != before_head
        or post_rea.get("evaluated_paths") != sorted(actual)
        or post_rea.get("independent") is not True
    ):
        return _blocked("post_repair_rea_not_independent_pass")

    # REA is a read-only verifier. Reject any verifier-side mutation so the
    # verified diff is exactly the diff that remains after independent review.
    try:
        final_head = _git(root, "rev-parse", "HEAD")
        final_status = _git(root, "status", "--porcelain", "--untracked-files=all")
        final_changed = _git(root, "diff", "--name-only").splitlines()
        final_staged = _git(root, "diff", "--cached", "--name-only").splitlines()
        final_untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    except Exception:
        return _blocked("post_rea_repository_state_unreadable")
    final_paths = set(final_changed + final_staged + final_untracked)
    if (
        final_head != before_head
        or final_status != post_repair_status
        or final_paths != actual
        or not final_paths.issubset(allowed)
    ):
        return _blocked("post_rea_repository_state_changed")

    return {
        "status": "REPAIR_VERIFIED",
        "reason_code": "single_repair_and_independent_post_rea_pass",
        "repair_executed": True,
        "repair_attempts": 1,
        "task_id": authorization["task_id"],
        "base_sha": before_head,
        "changed_paths": sorted(actual),
        "post_repair_rea": post_rea,
        "repair_authorization": consumed,
        # A separate, explicit HOLD transition and task re-authorization remain required.
        "hold_clear_authorized": False,
        "resume_authorized": False,
    }
