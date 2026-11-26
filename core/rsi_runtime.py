"""Single composition root for the durable, fail-closed RSI runtime.

The caller must supply trusted control and signature-verification dependencies.
This module does not start a scheduler, execute experiments, clear HOLD, or
activate models. The returned runtime owns exactly one SQLite EvidenceLedger;
all RSI components receive that same instance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ai_factory_stage165_recursive_evolution_feedback import (
    RecursiveEvolutionFeedbackIntegrator,
)
from .rsi_executor import (
    EvidenceLedger,
    HumanApproval,
    IndependentEvaluation,
    RSIControl,
    RSIError,
    RSIExecutor,
)


@dataclass(frozen=True)
class RSIRuntime:
    """Explicitly owned RSI components sharing one durable evidence ledger."""

    ledger: EvidenceLedger
    executor: RSIExecutor
    recursive_feedback: RecursiveEvolutionFeedbackIntegrator

    def verify_ready(self) -> bool:
        """Recheck the canonical evidence chain; callers must fail closed on False."""
        return self.ledger.verify() is True


def build_rsi_runtime(
    ledger_path: str | Path,
    *,
    control_provider: Callable[[], RSIControl],
    verify_approval: Callable[[HumanApproval], bool],
    verify_evaluation: Callable[[IndependentEvaluation], bool],
    verify_evidence_signature: Callable[[str, str, str], bool],
    executor_id: str,
    max_experiments_per_cycle: int = 4,
    max_feedback_records: int = 512,
) -> RSIRuntime:
    """Construct the single RSI runtime from explicit trusted dependencies.

    A durable absolute filesystem path is required to avoid accidental
    per-working-directory databases or ephemeral in-memory evidence stores.
    No credentials, signing keys, permissive control defaults, or scheduler
    are manufactured here.
    """
    raw_path = str(ledger_path).strip()
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        raise ValueError("RSI evidence ledger must use a durable filesystem path")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("RSI evidence ledger path must be absolute")

    ledger = EvidenceLedger(path)
    if ledger.verify() is not True:
        raise RSIError("RSI evidence ledger integrity verification failed at startup")

    executor = RSIExecutor(
        ledger,
        control_provider=control_provider,
        verify_approval=verify_approval,
        verify_evaluation=verify_evaluation,
        verify_evidence_signature=verify_evidence_signature,
        executor_id=executor_id,
        max_experiments_per_cycle=max_experiments_per_cycle,
    )
    feedback = RecursiveEvolutionFeedbackIntegrator(
        max_records=max_feedback_records,
        ledger=ledger,
    )
    runtime = RSIRuntime(
        ledger=ledger,
        executor=executor,
        recursive_feedback=feedback,
    )
    if runtime.executor.ledger is not runtime.ledger:
        raise RSIError("RSI executor is not bound to the canonical evidence ledger")
    if runtime.verify_ready() is not True:
        raise RSIError("RSI evidence ledger integrity verification failed after startup")
    return runtime


__all__ = ["RSIRuntime", "build_rsi_runtime"]
