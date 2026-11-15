"""Stage 161: verified experimental feedback into the next-generation knowledge ledger.

Only an explicitly invoked Stage 160 execution envelope, whose independent Stage 155
evidence is re-verified by Stage 156, can contribute lessons to the next generation.
This stage never advances, adopts, or activates a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable

from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlan
from .ai_factory_stage155_isolated_merge_experiments import Fitness
from .ai_factory_stage156_authenticated_knowledge_transfer import (
    AuthenticatedKnowledgeTransfer,
    GenerationKnowledge,
    KnowledgeTransferError,
    KnowledgeTransferSnapshot,
    Stage156SignedEvidence,
)
from .ai_factory_stage160_approved_experiment_gate import (
    ApprovedExperimentExecution,
)

_HEX = re.compile(r"[0-9a-f]{64}")


class EvolutionFeedbackError(ValueError):
    """Raised when an experiment result cannot safely re-enter evolution."""


@dataclass(frozen=True)
class EvolutionFeedbackReceipt:
    proposal_id: str
    proposal_digest: str
    source_outcome_digest: str
    knowledge_transfer_id: str
    knowledge_record_digest: str
    feedback_digest: str
    proposed_generation: int
    pending_human_approval: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    auto_adoption_authorized: bool = False
    production_switch_authorized: bool = False


@dataclass(frozen=True)
class EvolutionFeedbackSnapshot:
    receipts: tuple[EvolutionFeedbackReceipt, ...]
    knowledge: KnowledgeTransferSnapshot
    digest: str
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


class VerifiedEvolutionFeedbackLoop:
    """Bridges approved Stage 160 experiments into the authenticated Stage 156 ledger."""

    def __init__(
        self,
        *,
        transfer: AuthenticatedKnowledgeTransfer | None = None,
        max_receipts: int = 128,
    ) -> None:
        if not isinstance(max_receipts, int) or isinstance(max_receipts, bool) or not 1 <= max_receipts <= 4096:
            raise ValueError("max_receipts must be between 1 and 4096")
        if transfer is not None and not isinstance(transfer, AuthenticatedKnowledgeTransfer):
            raise TypeError("transfer must be an AuthenticatedKnowledgeTransfer")
        self._transfer = transfer or AuthenticatedKnowledgeTransfer(max_records=max_receipts)
        self._max_receipts = max_receipts
        self._receipts: list[EvolutionFeedbackReceipt] = []
        self._proposal_ids: set[str] = set()

    def ingest(
        self,
        *,
        execution: ApprovedExperimentExecution,
        plan: MergeEvaluationPlan,
        evidence: Stage156SignedEvidence,
        baseline_fitness: Fitness,
        verify_stage155_evidence: Callable[[Stage156SignedEvidence], bool],
        expected_suite_digest: str,
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> EvolutionFeedbackReceipt:
        if hold_active or kill_switch_active or not budget_available:
            raise EvolutionFeedbackError("HOLD, kill switch, or unavailable budget blocks evolutionary feedback")
        if not isinstance(execution, ApprovedExperimentExecution) or not isinstance(plan, MergeEvaluationPlan):
            raise EvolutionFeedbackError("typed Stage 160 execution envelope and Stage 154 plan are required")
        if (execution.execution_requested_by_explicit_call is not True
                or execution.approval_verified_by_runner is not True
                or execution.proposal_only is not True
                or execution.generation_advanced is not False
                or execution.model_activated is not False
                or execution.production_switch_authorized is not False):
            raise EvolutionFeedbackError("Stage 160 execution envelope lacks explicit approval or safe authority state")
        if (not _valid_digest(execution.proposal_digest)
                or not isinstance(execution.proposal_id, str) or not execution.proposal_id
                or len(execution.proposal_id) > 128):
            raise EvolutionFeedbackError("Stage 160 proposal identity or digest is invalid")
        if (execution.outcome.plan_id != plan.plan_id
                or execution.outcome.recipe_digest != plan.recipe_digest
                or execution.outcome.generation_advanced is not False
                or execution.outcome.model_activated is not False
                or execution.outcome.production_switch_authorized is not False):
            raise EvolutionFeedbackError("Stage 160 outcome does not match the exact non-authoritative plan")
        if execution.proposal_id in self._proposal_ids:
            raise EvolutionFeedbackError("duplicate or replayed approved experiment proposal")
        if len(self._receipts) >= self._max_receipts:
            raise EvolutionFeedbackError("evolution feedback receipt capacity reached")

        try:
            knowledge: GenerationKnowledge = self._transfer.ingest(
                outcome=execution.outcome,
                plan=plan,
                evidence=evidence,
                baseline_fitness=baseline_fitness,
                verify_stage155_evidence=verify_stage155_evidence,
                expected_suite_digest=expected_suite_digest,
                hold_active=hold_active,
                kill_switch_active=kill_switch_active,
                budget_available=budget_available,
            )
        except KnowledgeTransferError as exc:
            raise EvolutionFeedbackError(str(exc)) from exc

        canonical = {
            "proposal_id": execution.proposal_id,
            "proposal_digest": execution.proposal_digest,
            "outcome": execution.outcome.outcome_digest,
            "transfer_id": knowledge.transfer_id,
            "record_digest": knowledge.record_digest,
            "proposed_generation": knowledge.proposed_generation,
        }
        feedback_digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        receipt = EvolutionFeedbackReceipt(
            execution.proposal_id,
            execution.proposal_digest,
            execution.outcome.outcome_digest,
            knowledge.transfer_id,
            knowledge.record_digest,
            feedback_digest,
            knowledge.proposed_generation,
        )
        self._receipts.append(receipt)
        self._proposal_ids.add(execution.proposal_id)
        return receipt

    def snapshot(self) -> EvolutionFeedbackSnapshot:
        knowledge = self._transfer.snapshot()
        payload = {
            "receipts": [x.feedback_digest for x in self._receipts],
            "knowledge": knowledge.digest,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        return EvolutionFeedbackSnapshot(tuple(self._receipts), knowledge, digest)


__all__ = [
    "EvolutionFeedbackError",
    "EvolutionFeedbackReceipt",
    "EvolutionFeedbackSnapshot",
    "VerifiedEvolutionFeedbackLoop",
]
