"""Strict adapter from the five-stage RSI record to Orca's six-stage gate.

The adapter never manufactures independent-review evidence or evaluation
metrics. Those must be supplied by their separate trusted producers.
"""
from __future__ import annotations

import re
from typing import Any

from scripts.orca_rsi_five_stage import RSI_STAGES

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class RSIExecutionAdapterRejected(ValueError):
    """Raised when RSI evidence cannot safely enter the Orca execution gate."""


def to_orca_improvement_candidate(
    cycle: Any,
    *,
    cycle_id: str,
    independent_review_evidence: Any,
    evaluation: Any,
) -> dict[str, Any]:
    """Map completed RSI evidence without asserting approval or execution.

    independent_review_evidence must come from a separate reviewer; it is
    intentionally not inferred from the RSI cycle's own select/evolve stage.
    evaluation must contain independently measured metrics and test/critic
    verdict. The downstream execution gate validates these again.
    """
    if not isinstance(cycle, dict) or cycle.get("schema_version") != 1:
        raise RSIExecutionAdapterRejected("rsi_cycle_missing_or_invalid")
    if cycle.get("completed_stages") != list(RSI_STAGES):
        raise RSIExecutionAdapterRejected("rsi_cycle_incomplete")
    if cycle.get("result") != "PASS":
        raise RSIExecutionAdapterRejected("rsi_cycle_result_not_pass")
    evidence = cycle.get("evidence")
    if (not isinstance(evidence, dict) or set(evidence) != set(RSI_STAGES)
            or any(not isinstance(evidence.get(stage), str) or not evidence[stage].strip()
                   for stage in RSI_STAGES)):
        raise RSIExecutionAdapterRejected("rsi_cycle_evidence_invalid")
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
        raise RSIExecutionAdapterRejected("orca_cycle_id_invalid")
    if (not isinstance(independent_review_evidence, list)
            or not independent_review_evidence
            or any(not isinstance(item, str) or not item.strip()
                   for item in independent_review_evidence)):
        raise RSIExecutionAdapterRejected("independent_review_evidence_missing")
    if not isinstance(evaluation, dict):
        raise RSIExecutionAdapterRejected("independent_evaluation_missing")

    return {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "stage": "evaluated",
        "decision": "accepted_candidate",
        "execution_authorized": False,
        "auto_apply": False,
        "auto_merge": False,
        "auto_deploy": False,
        "evidence": {
            "observed": [evidence["evaluate"]],
            "diagnosed": [evidence["diagnose"]],
            "proposed": [evidence["hypothesize"]],
            "tested": [evidence["experiment"]],
            "reviewed": list(independent_review_evidence),
            "evaluated": [evidence["select_evolve"]],
        },
        "details": {"evaluation": dict(evaluation)},
    }
