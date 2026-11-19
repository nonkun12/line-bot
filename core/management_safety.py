"""Deterministic safety boundary for Management AI actions.

This module is intentionally independent from LLM output. It validates the
planned scope, actual changed paths, commit/diff identity, test/review evidence,
budgets, and immutable control-plane boundaries before an action can proceed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


CURRENT_POLICY_VERSION = "management-safety-v1"
MAX_TTL_SECONDS = 3600
MAX_DELEGATION_DEPTH = 3
MAX_RETRIES = 3
MAX_BUDGET_CALLS = 20
MAX_BUDGET_UNITS = 100


class GateDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_HUMAN = "needs_human"


@dataclass(frozen=True)
class ManagementPlan:
    task_id: str
    origin: str
    intent: str
    scope_paths: tuple[str, ...]
    max_files: int
    max_changes: int
    rollback_plan: str
    budget_calls: int
    budget_units: int
    ttl_seconds: int
    parent_task: str | None = None
    tainted: bool = False
    delegation_depth: int = 0
    retries: int = 0
    expected_changed_paths: tuple[str, ...] = ()
    expected_diff_hash: str | None = None

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "origin": self.origin,
            "intent": self.intent,
            "scope_paths": sorted(_normalize(path) for path in self.scope_paths),
            "expected_changed_paths": sorted(
                _normalize(path) for path in self.expected_changed_paths
            ),
            "expected_diff_hash": self.expected_diff_hash,
            "max_files": self.max_files,
            "max_changes": self.max_changes,
            "rollback_plan": self.rollback_plan.strip(),
            "budget_calls": self.budget_calls,
            "budget_units": self.budget_units,
            "ttl_seconds": self.ttl_seconds,
            "parent_task": self.parent_task,
            "tainted": self.tainted,
            "delegation_depth": self.delegation_depth,
            "retries": self.retries,
        }

    def plan_hash(self) -> str:
        return _sha256_json(self.canonical_payload())


@dataclass(frozen=True)
class CapabilityGrant:
    issuer: str
    subject: str
    scopes: frozenset[str]
    issued_at: int
    expires_at: int
    parent_task: str
    nonce: str
    one_shot: bool = True

    def is_valid_at(self, now_epoch: int) -> bool:
        return self.expires_at > now_epoch and self.issued_at <= now_epoch

    def attenuate(
        self,
        *,
        subject: str,
        scopes: Iterable[str],
        expires_at: int,
        nonce: str,
    ) -> "CapabilityGrant":
        child_scopes = frozenset(_normalize_scope(scope) for scope in scopes)
        if not child_scopes.issubset(self.scopes):
            raise ValueError("delegated capability exceeds parent scope")
        if expires_at > self.expires_at:
            raise ValueError("delegated capability exceeds parent expiry")
        return CapabilityGrant(
            issuer=self.subject,
            subject=subject,
            scopes=child_scopes,
            issued_at=self.issued_at,
            expires_at=expires_at,
            parent_task=self.parent_task,
            nonce=nonce,
            one_shot=True,
        )


@dataclass(frozen=True)
class ManagementGateInput:
    plan: ManagementPlan
    approved_plan_hash: str
    base_sha: str
    expected_base_sha: str
    head_sha: str
    diff_hash: str
    changed_paths: tuple[str, ...]
    changed_files: int
    changed_lines: int
    tests_passed: bool
    reviewed: bool
    review_sha: str | None
    rollback_verified: bool
    policy_version: str
    current_policy_version: str = CURRENT_POLICY_VERSION
    now_epoch: int = 0
    approval_expires_at: int = 0
    introduces_external_network: bool = False
    introduces_env_reads: bool = False
    changes_dependencies: bool = False
    changes_ci: bool = False
    changes_privileges: bool = False
    changes_secrets: bool = False
    mutates_audit_log: bool = False
    contains_secret_or_pii: bool = False


@dataclass(frozen=True)
class ManagementGateResult:
    decision: GateDecision
    reasons: tuple[str, ...]

    @property
    def allowed(self) -> bool:
        return self.decision is GateDecision.ALLOW


PROTECTED_PREFIXES = (
    ".github/",
    ".git/",
    "security/",
    "secrets/",
)
PROTECTED_FILES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "CODEOWNERS",
        "config.py",
        "pyproject.toml",
        "poetry.lock",
        "uv.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "core/management_safety.py",
        "core/control_tower.py",
        "core/self_improvement_policy.py",
        "core/hermes_advisor.py",
        "core/agent_runtime.py",
        "scripts/line_development_worker_v2.py",
    }
)


def evaluate_management_gate(request: ManagementGateInput) -> ManagementGateResult:
    """Evaluate one proposed integration with fail-closed semantics."""
    reasons: list[str] = []
    human_review_reasons: list[str] = []

    plan = request.plan
    if plan.origin != "trusted":
        human_review_reasons.append("task origin is not trusted")
    if plan.tainted:
        human_review_reasons.append("task or evidence is tainted")
    if request.approved_plan_hash != plan.plan_hash():
        reasons.append("approved plan hash does not match submitted plan")

    if not plan.task_id.strip() or not plan.intent.strip():
        reasons.append("task identity or intent is empty")
    if not plan.scope_paths:
        reasons.append("plan scope is empty")
    if not plan.rollback_plan.strip() or not request.rollback_verified:
        reasons.append("rollback is not verified")

    if plan.max_files < 1 or plan.max_changes < 1:
        reasons.append("plan change bounds are invalid")
    if plan.budget_calls < 1 or plan.budget_calls > MAX_BUDGET_CALLS:
        reasons.append("budget call bound is outside hard limit")
    if plan.budget_units < 1 or plan.budget_units > MAX_BUDGET_UNITS:
        reasons.append("budget unit bound is outside hard limit")
    if plan.ttl_seconds < 1 or plan.ttl_seconds > MAX_TTL_SECONDS:
        reasons.append("task TTL is outside hard limit")
    if plan.delegation_depth < 0 or plan.delegation_depth > MAX_DELEGATION_DEPTH:
        reasons.append("delegation depth exceeds hard limit")
    if plan.retries < 0 or plan.retries > MAX_RETRIES:
        reasons.append("retry count exceeds hard limit")

    normalized_scope = tuple(_normalize(path) for path in plan.scope_paths)
    normalized_expected = tuple(_normalize(path) for path in plan.expected_changed_paths)
    normalized_changed = tuple(_normalize(path) for path in request.changed_paths)
    protected = tuple(path for path in normalized_changed if _is_protected(path))
    protected_scope = tuple(path for path in normalized_scope if _is_protected(path))
    if protected:
        human_review_reasons.append("changed path touches the protected control plane: " + ", ".join(protected))
    if protected_scope:
        human_review_reasons.append("plan scope touches the protected control plane: " + ", ".join(protected_scope))

    out_of_scope = tuple(
        path for path in normalized_changed if not _path_allowed(path, normalized_scope)
    )
    if out_of_scope:
        reasons.append("changed path is outside the approved scope: " + ", ".join(out_of_scope))
    if normalized_expected and set(normalized_changed) != set(normalized_expected):
        reasons.append("actual changed paths do not match the planned changed paths")
    if plan.expected_diff_hash is not None and request.diff_hash != plan.expected_diff_hash:
        reasons.append("actual diff hash does not match the planned diff hash")

    if request.changed_files < 0 or request.changed_lines < 0:
        reasons.append("negative diff statistics are invalid")
    if request.changed_files > plan.max_files:
        reasons.append("changed file count exceeds approved bound")
    if request.changed_lines > plan.max_changes:
        reasons.append("changed line count exceeds approved bound")
    if request.changed_files != len(normalized_changed):
        reasons.append("changed file count does not match changed path list")

    if not request.base_sha or request.base_sha != request.expected_base_sha:
        reasons.append("base SHA is not the approved base")
    if not request.head_sha:
        reasons.append("head SHA is missing")
    if not request.diff_hash:
        reasons.append("diff hash is missing")

    if request.now_epoch <= 0 or request.approval_expires_at <= request.now_epoch:
        reasons.append("approval is expired or missing")
    if request.policy_version != request.current_policy_version:
        reasons.append("policy version is stale")

    if not request.tests_passed:
        reasons.append("tests did not pass")
    if not request.reviewed:
        human_review_reasons.append("independent review is missing")
    elif request.review_sha != request.head_sha:
        reasons.append("review does not match the submitted head SHA")

    if request.introduces_external_network:
        human_review_reasons.append("change introduces new external network access")
    if request.introduces_env_reads:
        human_review_reasons.append("change introduces environment-variable reads")
    if request.changes_dependencies:
        human_review_reasons.append("change modifies dependencies")
    if request.changes_ci:
        human_review_reasons.append("change modifies CI configuration")
    if request.changes_privileges:
        human_review_reasons.append("change modifies privileges")
    if request.changes_secrets:
        human_review_reasons.append("change modifies secrets")
    if request.mutates_audit_log:
        human_review_reasons.append("change can mutate audit history")
    if request.contains_secret_or_pii:
        human_review_reasons.append("secret or PII exposure was detected")

    if reasons:
        return ManagementGateResult(GateDecision.DENY, tuple(reasons + human_review_reasons))
    if human_review_reasons:
        return ManagementGateResult(GateDecision.NEEDS_HUMAN, tuple(human_review_reasons))
    return ManagementGateResult(
        GateDecision.ALLOW,
        (
            "plan, scope, SHA/diff identity, tests, review, rollback, policy, and budgets passed",
        ),
    )


def _is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _path_allowed(path: str, scopes: tuple[str, ...]) -> bool:
    return any(
        path == scope.rstrip("/") or path.startswith(scope.rstrip("/") + "/")
        for scope in scopes
    )


def _normalize(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _normalize_scope(scope: str) -> str:
    value = str(scope).strip().replace("\\", "/")
    return value.rstrip("/") + "/" if value.rstrip("/") else "/"


def _sha256_json(value: Mapping[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CapabilityGrant",
    "CURRENT_POLICY_VERSION",
    "GateDecision",
    "ManagementGateInput",
    "ManagementGateResult",
    "ManagementPlan",
    "evaluate_management_gate",
]
