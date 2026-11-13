"""Finite typed task contracts for the Orca worker boundary.

Queue text is never executable. Only these reviewed task IDs and exact
parameter schemas are recognized. This phase validates/plans tasks only;
there is intentionally no code-writing or subprocess handler.
"""
from __future__ import annotations

from typing import Any


class TaskContractRejected(ValueError):
    """Raised when a queue payload is not in the finite typed allowlist."""


_CONTRACTS = {
    "ai-speaker-empty-transcript-no-brain-call": {
        "task_type": "add_regression_test",
        "target_path": "tests/test_ai_speaker.py",
        "contract_version": 1,
    },
    "recovery-ai-state-isolation": {
        "task_type": "add_regression_test",
        "target_path": "tests/test_recovery_ai.py",
        "contract_version": 1,
    },
    "router-regression-general-request-metadata": {
        "task_type": "add_regression_test",
        "target_path": "tests/test_management_router.py",
        "contract_version": 1,
    },
    "recovery-ai-loop-adapter-durable-state-readback": {
        "task_type": "add_regression_test",
        "target_path": "tests/test_recovery_ai_loop_adapter.py",
        "contract_version": 1,
    },
}


def validate_typed_task(*, task_id: str, payload: Any) -> dict[str, Any]:
    """Validate a catalog-bound task; never interpret free-form instructions."""
    contract = _CONTRACTS.get(task_id) if isinstance(task_id, str) else None
    if contract is None:
        raise TaskContractRejected("task_id_not_in_typed_allowlist")
    if not isinstance(payload, dict) or set(payload) != {
        "task_type", "target_path", "contract_version"
    }:
        raise TaskContractRejected("typed_task_payload_shape_invalid")
    if payload.get("task_type") != contract["task_type"]:
        raise TaskContractRejected("typed_task_type_mismatch")
    if payload.get("target_path") != contract["target_path"]:
        raise TaskContractRejected("typed_task_path_mismatch")
    version = payload.get("contract_version")
    if isinstance(version, bool) or version != contract["contract_version"]:
        raise TaskContractRejected("typed_task_contract_version_mismatch")
    return {
        "task_id": task_id,
        "task_type": contract["task_type"],
        "target_path": contract["target_path"],
        "contract_version": contract["contract_version"],
        "execution_supported": False,
        "status": "BLOCKED_HANDLER_NOT_IMPLEMENTED",
    }
