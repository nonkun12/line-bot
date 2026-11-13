"""Safety-first recursive self-improvement cycle state machine.

This module records proposals and evidence only. It never edits source files,
creates branches/PRs, merges, deploys, or releases Global HOLD.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

_STAGES = ("observed", "diagnosed", "proposed", "tested", "reviewed", "evaluated")
_TERMINAL = {"accepted_candidate", "deferred", "rejected"}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_DEPTH = 10


class ImprovementRejected(ValueError):
    """Raised when a self-improvement transition lacks safe evidence."""


def _utc(value: str) -> str:
    if not isinstance(value, str):
        raise ImprovementRejected("timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ImprovementRejected("timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise ImprovementRejected("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _evidence(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ImprovementRejected(f"{field}_evidence_required")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ImprovementRejected(f"{field}_evidence_invalid")
    return list(dict.fromkeys(value))


def new_cycle(*, observation: str, source_refs: list[str], created_at: str,
              parent_cycle_id: str | None = None, depth: int = 0) -> dict[str, Any]:
    if not isinstance(observation, str) or not observation.strip():
        raise ImprovementRejected("observation_required")
    refs = _evidence(source_refs, "observation")
    if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= _MAX_DEPTH:
        raise ImprovementRejected("recursion_depth_invalid")
    if depth == 0 and parent_cycle_id is not None:
        raise ImprovementRejected("root_cycle_cannot_have_parent")
    if depth > 0 and (not isinstance(parent_cycle_id, str) or not _SHA.fullmatch(parent_cycle_id)):
        raise ImprovementRejected("parent_cycle_id_invalid")
    timestamp = _utc(created_at)
    seed = f"{observation}\n{timestamp}\n{parent_cycle_id or ''}"
    cycle_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1, "cycle_id": cycle_id,
        "parent_cycle_id": parent_cycle_id, "depth": depth,
        "stage": "observed", "observation": observation.strip(),
        "evidence": {"observation": refs}, "created_at": timestamp,
        "decision": None, "execution_authorized": False,
        "auto_apply": False, "auto_merge": False, "auto_deploy": False,
    }


def advance(cycle: dict[str, Any], *, expected_stage: str, next_stage: str,
            evidence_refs: list[str], details: dict[str, Any] | None = None) -> dict[str, Any]:
    if (not isinstance(cycle, dict) or cycle.get("schema_version") != 1
            or not isinstance(cycle.get("evidence"), dict)):
        raise ImprovementRejected("cycle_invalid")
    if cycle.get("stage") in _TERMINAL or cycle.get("stage") != expected_stage:
        raise ImprovementRejected("stage_conflict")
    try:
        current_index = _STAGES.index(expected_stage)
        next_index = _STAGES.index(next_stage)
    except ValueError:
        raise ImprovementRejected("stage_invalid") from None
    if next_index != current_index + 1:
        raise ImprovementRejected("non_sequential_transition")
    refs = _evidence(evidence_refs, next_stage)
    out = copy.deepcopy(cycle)
    out["stage"] = next_stage
    out["evidence"][next_stage] = refs
    if details is not None:
        if not isinstance(details, dict):
            raise ImprovementRejected("details_invalid")
        out.setdefault("details", {})[next_stage] = copy.deepcopy(details)
    return out


def evaluate(cycle: dict[str, Any], *, expected_stage: str, tests_passed: bool,
             critic_verdict: str, baseline_metric: float | int,
             candidate_metric: float | int, metric_evidence_refs: list[str]) -> dict[str, Any]:
    if (not isinstance(cycle, dict) or cycle.get("schema_version") != 1
            or not isinstance(cycle.get("evidence"), dict)):
        raise ImprovementRejected("cycle_invalid")
    if expected_stage != "reviewed" or cycle.get("stage") != "reviewed":
        raise ImprovementRejected("evaluation_requires_reviewed_stage")
    if tests_passed is not True:
        raise ImprovementRejected("tests_not_passed")
    if critic_verdict != "pass":
        raise ImprovementRejected("independent_critic_not_passed")
    if (isinstance(baseline_metric, bool) or not isinstance(baseline_metric, (int, float))
            or isinstance(candidate_metric, bool) or not isinstance(candidate_metric, (int, float))
            or not math.isfinite(baseline_metric) or not math.isfinite(candidate_metric)):
        raise ImprovementRejected("metrics_invalid")
    refs = _evidence(metric_evidence_refs, "metric")
    out = copy.deepcopy(cycle)
    out["stage"] = "evaluated"
    out["evidence"]["evaluated"] = refs
    out["details"] = copy.deepcopy(out.get("details", {}))
    out["details"]["evaluation"] = {
        "baseline_metric": baseline_metric, "candidate_metric": candidate_metric,
        "tests_passed": True, "critic_verdict": "pass",
    }
    out["decision"] = "accepted_candidate" if candidate_metric > baseline_metric else "deferred"
    # Acceptance means eligible for human review only; never execution authorization.
    out["execution_authorized"] = False
    return out


def start_next_cycle(previous: dict[str, Any], *, observation: str,
                     source_refs: list[str], created_at: str) -> dict[str, Any]:
    if not isinstance(previous, dict) or previous.get("stage") != "evaluated":
        raise ImprovementRejected("previous_cycle_not_evaluated")
    depth = previous.get("depth")
    if isinstance(depth, bool) or not isinstance(depth, int) or depth >= _MAX_DEPTH:
        raise ImprovementRejected("recursion_depth_limit_reached")
    return new_cycle(observation=observation, source_refs=source_refs,
                     created_at=created_at, parent_cycle_id=previous["cycle_id"],
                     depth=depth + 1)
