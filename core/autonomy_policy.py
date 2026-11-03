"""Deterministic risk policy for reducing routine human approvals.

This policy grants bounded autonomy to reversible, repository-scoped work.
It never grants merge, deployment, secret access, permission changes, or
production-data mutation. A downstream executor must still enforce the
returned path scope and collect independent test/review evidence.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

_AUTO_ROOTS = ("tests/", "uhip/tests/", "docs/", "agents/", "core/", "scripts/")
_PROTECTED_EXACT = frozenset({
    "app.py", "config.py", "db.py", "job_store.py", "job_worker.py",
    "distributed_loop_trigger.py", "line_development.py",
    "app_development.py", "requirements.txt", "render.yaml",
    "Dockerfile", "Procfile",
})
_PROTECTED_PREFIXES = (
    ".github/", "routes/", "migrations/", "secrets/", "deploy/",
    "core/control_tower", "core/task_routing.py", "core/management_bridge.py",
    "core/openclaw_bridge.py", "core/auth/", "core/security/",
)
_PROTECTED_NAME = re.compile(r"(^|[/_.-])(secret|secrets|auth|authentication|token|credential|permission|security|billing|payment|deploy|deployment|migration|database|production|prod)([/_.-]|$)", re.IGNORECASE)
_HIGH_RISK_INSTRUCTION = re.compile(
    r"(?:\bdeploy\b|\bmerge\b|\bpublish\b|\bproduction\b|\bsecret\b|"
    r"\bcredential\b|\bpermission\b|\bdelete\b|\bdrop\b|\bmigration\b|"
    r"デプロイ|本番|秘密|認証情報|権限変更|データ削除|マージ|公開)",
    re.IGNORECASE,
)


def _path_reason(path: object) -> str | None:
    if not isinstance(path, str) or not path or len(path) > 240:
        return "path_invalid"
    if "\\" in path or path.startswith("/") or any(part in {".", ".."} for part in path.split("/")):
        return "path_traversal_or_absolute"
    if any(char in path for char in "*?[]{}"):
        return "path_must_be_explicit"
    normalized = str(PurePosixPath(path))
    if any(part.startswith(".") for part in normalized.split("/")) or not PurePosixPath(normalized).suffix:
        return "hidden_or_non_file_path"
    if _PROTECTED_NAME.search(normalized):
        return "protected_name_requires_human_review"
    if normalized in _PROTECTED_EXACT or any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in _PROTECTED_PREFIXES
    ):
        return "protected_path_requires_human_review"
    if not normalized.startswith(_AUTO_ROOTS):
        return "path_outside_autonomy_allowlist"
    return None


def evaluate_job_autonomy(job: object) -> dict[str, Any]:
    """Return AUTO_APPROVE only for bounded low-risk repository work."""
    if not isinstance(job, dict):
        return {"decision": "HUMAN_REVIEW", "reason": "job_contract_invalid", "risk": "unknown"}
    stage = job.get("stage")
    instruction = job.get("instruction")
    paths = job.get("allowed_paths")
    if stage not in {"requirements", "design", "implementation", "test", "review", "fix", "verify"}:
        return {"decision": "HUMAN_REVIEW", "reason": "stage_not_allowlisted", "risk": "unknown"}
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 5000:
        return {"decision": "HUMAN_REVIEW", "reason": "instruction_invalid", "risk": "unknown"}
    if _HIGH_RISK_INSTRUCTION.search(instruction):
        return {"decision": "HUMAN_REVIEW", "reason": "high_risk_operation", "risk": "high"}
    if not isinstance(paths, list) or not paths or len(paths) > 10:
        return {"decision": "HUMAN_REVIEW", "reason": "path_scope_invalid", "risk": "unknown"}

    reasons = [_path_reason(path) for path in paths]
    if any(reasons):
        return {
            "decision": "HUMAN_REVIEW",
            "reason": next(reason for reason in reasons if reason),
            "risk": "high",
        }
    if stage == "test" and any(not path.startswith(("tests/", "uhip/tests/")) for path in paths):
        return {"decision": "HUMAN_REVIEW", "reason": "test_stage_must_be_test_only", "risk": "medium"}
    if stage in {"requirements", "design", "review", "verify"} and any(
        not path.startswith(("tests/", "uhip/tests/", "docs/")) for path in paths
    ):
        return {"decision": "HUMAN_REVIEW", "reason": "analysis_stage_must_be_read_only_scope", "risk": "medium"}
    if stage in {"implementation", "fix"}:
        has_test_scope = any(
            isinstance(path, str) and path.startswith(("tests/", "uhip/tests/"))
            for path in paths
        )
        if not has_test_scope:
            return {
                "decision": "HUMAN_REVIEW",
                "reason": "code_change_requires_test_scope",
                "risk": "medium",
            }

    risk = "low" if all(path.startswith(("tests/", "uhip/tests/", "docs/")) for path in paths) else "medium"
    return {
        "decision": "AUTO_APPROVE",
        "reason": "bounded_reversible_repository_work",
        "risk": risk,
        "permissions": {
            "execute_scoped_job": True,
            "create_branch_or_draft_pr": True,
            "merge": False,
            "deploy": False,
            "modify_secrets_or_permissions": False,
            "mutate_production_data": False,
            "verify_realpath_within_repository": True,
        },
    }


__all__ = ["evaluate_job_autonomy"]
