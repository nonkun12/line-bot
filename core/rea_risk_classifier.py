"""Conservative path-based risk triage; never a semantic security verdict."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

_LOW_DOC_SUFFIXES = {".md", ".rst"}
_HIGH_EXACT = {
    ".github/dependabot.yml", "requirements.txt", "pyproject.toml",
    "poetry.lock", "uv.lock", "package.json", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock",
}
_HIGH_SEGMENTS = {
    "workflows", "secrets", "security", "auth", "permissions", "deploy",
    "deployment", "infrastructure", "migrations",
}
_HIGH_NAMES = {
    "emergency_stop.py", "run_guarded_runtime.py", "run_minimal_autonomous_loop.py",
    "rea_artifact_evaluator.py", "rea_artifact_runtime.py", "rea_control_tower_adapter.py",
    "rea_readonly_scanner.py", "rea_independent_verification.py",
    "rea_independent_verification_client.py", "control_tower_orchestrator.py",
    "control_tower_loop_observer.py", "recovery_ai.py", "recovery_ai_loop_adapter.py",
    "goal_runtime_bridge.py",
}


def classify_changed_paths(paths: object) -> dict[str, Any]:
    """Classify path scope conservatively; unknown or unsafe paths never become LOW."""
    if not isinstance(paths, list) or not paths:
        return {"risk": "UNKNOWN", "reason_code": "changed_paths_missing"}
    normalized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw or raw != raw.strip() or "\\" in raw:
            return {"risk": "HIGH", "reason_code": "changed_path_invalid"}
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in raw.split("/")):
            return {"risk": "HIGH", "reason_code": "changed_path_unsafe"}
        normalized.append(path.as_posix())
    if any(
        path in _HIGH_EXACT
        or PurePosixPath(path).name in _HIGH_NAMES
        or bool(set(PurePosixPath(path).parts) & _HIGH_SEGMENTS)
        or path.startswith(".github/workflows/")
        for path in normalized
    ):
        return {"risk": "HIGH", "reason_code": "sensitive_or_operational_path"}
    if all(
        path.startswith("docs/") or PurePosixPath(path).suffix.lower() in _LOW_DOC_SUFFIXES
        for path in normalized
    ):
        return {"risk": "LOW", "reason_code": "documentation_only"}
    known_suffixes = {
        ".py", ".json", ".yml", ".yaml", ".toml", ".sh", ".js", ".ts",
        ".tsx", ".jsx", ".html", ".css",
    }
    if all(PurePosixPath(path).suffix.lower() in known_suffixes for path in normalized):
        return {"risk": "MEDIUM", "reason_code": "application_or_test_code"}
    return {"risk": "UNKNOWN", "reason_code": "path_type_unclassified"}


__all__ = ["classify_changed_paths"]
