"""Safety policy for AI Secretary self-improvement.

Self-improvement is intentionally stricter than ordinary software work.  This
module is a pure policy boundary: it decides whether a proposed change may
enter the normal autonomous pipeline, requires explicit approval, or must be
rejected outright.  It does not apply changes itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import posixpath


class SelfImprovementDecision(str, Enum):
    AUTONOMOUS_REVIEW = "autonomous_review"
    EXPLICIT_APPROVAL = "explicit_approval"
    REJECT = "reject"


@dataclass(frozen=True)
class SelfImprovementAssessment:
    decision: SelfImprovementDecision
    reasons: tuple[str, ...]
    protected_paths: tuple[str, ...]


HIGH_RISK_PREFIXES = (
    ".github/workflows/",
    "security/",
    "secrets/",
)
HIGH_RISK_FILES = frozenset(
    {
        ".env",
        "config.py",
        "internal_ask_route.py",
        "internal_push_route.py",
        "line_development.py",
        "scripts/line_development_worker_v2.py",
        "core/line_development_runtime.py",
        "core/self_improvement_policy.py",
        "scripts/nightly_task_worker.py",
        "scripts/nightly_worker.py",
    }
)


def assess_self_improvement(paths: list[str] | tuple[str, ...]) -> SelfImprovementAssessment:
    """Assess proposed self-improvement paths before implementation starts."""
    normalized = tuple(_normalize(path) for path in paths if str(path).strip())
    # Absolute paths and traversal above repository root are not a valid
    # autonomous target manifest. Fail closed instead of interpreting them as
    # ordinary relative repository paths.
    if any(path.startswith("/") or path == ".." or path.startswith("../") for path in normalized):
        return SelfImprovementAssessment(
            decision=SelfImprovementDecision.EXPLICIT_APPROVAL,
            reasons=("target manifest contains an absolute or escaping path",),
            protected_paths=tuple(path for path in normalized if path.startswith("/") or path == ".." or path.startswith("../")),
        )
    protected = tuple(path for path in normalized if _is_high_risk(path))

    if protected:
        return SelfImprovementAssessment(
            decision=SelfImprovementDecision.EXPLICIT_APPROVAL,
            reasons=(
                "proposal touches protected control-plane or security files",
                "automatic merge/deploy is not permitted for this proposal",
            ),
            protected_paths=protected,
        )

    if not normalized:
        return SelfImprovementAssessment(
            decision=SelfImprovementDecision.REJECT,
            reasons=("no files were selected",),
            protected_paths=(),
        )

    return SelfImprovementAssessment(
        decision=SelfImprovementDecision.AUTONOMOUS_REVIEW,
        reasons=(
            "selected paths are outside the protected self-improvement surface",
            "branch, tests, review, merge gate, and deploy gate remain mandatory",
        ),
        protected_paths=(),
    )


def _normalize(path: str) -> str:
    """Normalize separators and a leading ./ without stripping filename dots."""
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    # Canonicalize traversal before any protected-path comparison.  A path
    # such as ../core/self_improvement_policy.py must never become an
    # unprotected autonomous target merely because it contains .. segments.
    value = posixpath.normpath(value)
    if value == ".":
        return ""
    return PurePosixPath(value).as_posix()


def _is_high_risk(path: str) -> bool:
    return path in HIGH_RISK_FILES or any(path.startswith(prefix) for prefix in HIGH_RISK_PREFIXES)


__all__ = [
    "SelfImprovementDecision",
    "SelfImprovementAssessment",
    "assess_self_improvement",
    "HIGH_RISK_PREFIXES",
    "HIGH_RISK_FILES",
]
