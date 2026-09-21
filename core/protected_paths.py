"""Single source of truth for autonomous-development protected paths."""
from __future__ import annotations
from pathlib import PurePosixPath

PROTECTED_PREFIXES = (".github/", ".git/", ".env", "security/", "secrets/")
PROTECTED_FILES = frozenset({
    ".env", ".env.local", ".env.production", "CODEOWNERS", "config.py",
    "pyproject.toml", "poetry.lock", "uv.lock", "requirements.txt", "requirements-dev.txt",
    "core/agent_runtime.py", "core/control_tower.py", "core/execution_safety.py",
    "core/management_safety.py", "core/self_improvement_policy.py", "core/quality_runtime.py",
    "core/specialist_gate.py", "core/self_improvement_handoff.py",
    "core/self_improvement_handoff_store.py", "core/protected_paths.py",
    "core/line_development_runtime.py", "scripts/run_guarded_runtime.py",
    # Legacy/high-impact autonomous-development control paths are kept blocked
    # even when the files are absent on the current branch.
    "line_development.py", "git_safety.py", "patch_validator.py", "render_client.py",
    "scripts/line_development.py", "scripts/git_safety.py", "scripts/patch_validator.py",
    "scripts/render_client.py",
    "scripts/line_development_worker.py", "scripts/line_development_worker_safe.py",
    "scripts/line_development_worker_v2.py", "scripts/nightly_task_worker.py",
    "scripts/nightly_worker.py", "slack_command.py", "app.py", "tests/test_execution_safety.py",
})
HIGH_RISK_PREFIXES = PROTECTED_PREFIXES
HIGH_RISK_FILES = PROTECTED_FILES

def normalize_path(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return PurePosixPath(value).as_posix()

def is_protected(path: str) -> bool:
    normalized = normalize_path(path).rstrip("/")
    if not normalized or normalized == ".":
        return True
    if normalized in PROTECTED_FILES:
        return True
    if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    # A manifest scope that is an ancestor of a protected file must also be
    # protected; otherwise a caller could authorize "core" or "." and reach
    # a protected descendant.
    return any(protected.startswith(normalized + "/") for protected in PROTECTED_FILES)

__all__ = ["PROTECTED_PREFIXES","PROTECTED_FILES","HIGH_RISK_PREFIXES","HIGH_RISK_FILES","normalize_path","is_protected"]
