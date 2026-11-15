"""Stage 152: evidence-verified meta-learning over evolutionary strategy trials.

Only externally executed, independently evaluated trials enter this bounded,
append-only in-memory ledger. Rankings are advisory and never execute/adopt a strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from threading import RLock
from typing import Callable

from .ai_factory_stage141_evolution import Fitness, dominates
from .ai_factory_stage151_evolutionary_knowledge import StrategyKind, EvolutionStrategyProposal


_DIGEST = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class MetaLearningError(ValueError):
    """Raised when trial evidence is missing, invalid, replayed, or incomparable."""


class TrialOutcome(str, Enum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class StrategyTrialEvidence:
    trial_id: str
    proposal_id: str
    strategy: StrategyKind
    evaluation_suite_digest: str
    evaluator_id: str
    strategy_author_id: str
    execution_receipt_digest: str
    candidate_artifact_digest: str
    parent_artifact_digest: str
    baseline: Fitness
    candidate: Fitness


@dataclass(frozen=True)
class VerifiedStrategyTrial:
    trial_id: str
    proposal_id: str
    strategy: StrategyKind
    outcome: TrialOutcome
    evaluation_suite_digest: str
    evidence_digest: str


@dataclass(frozen=True)
class StrategyEffectiveness:
    strategy: StrategyKind
    trials: int
    improvements: int
    regressions: int
    neutral: int
    success_rate: float
    mean_quality_delta: float
    ranked: bool
    rank: int | None
    execution_authorized: bool = False
    auto_adoption_authorized: bool = False
    model_mutation_authorized: bool = False


@dataclass(frozen=True)
class MetaLearningSnapshot:
    trials: tuple[VerifiedStrategyTrial, ...]
    effectiveness: tuple[StrategyEffectiveness, ...]
    evaluation_suite_digest: str
    digest: str
    recommendation_only: bool = True


class EvolutionaryMetaLearner:
    """Evidence-gated strategy outcome ledger; verifier must be independently trusted."""

    def __init__(
        self,
        verifier: Callable[[StrategyTrialEvidence], bool],
        *,
        max_trials: int = 512,
        min_trials_for_ranking: int = 3,
    ) -> None:
        if not callable(verifier):
            raise ValueError("an independent evidence verifier is required")
        if not isinstance(max_trials, int) or isinstance(max_trials, bool) or not 1 <= max_trials <= 4096:
            raise ValueError("max_trials must be between 1 and 4096")
        if not isinstance(min_trials_for_ranking, int) or isinstance(min_trials_for_ranking, bool) or not 2 <= min_trials_for_ranking <= 100:
            raise ValueError("min_trials_for_ranking must be between 2 and 100")
        self._verifier = verifier
        self._max_trials = max_trials
        self._min_trials = min_trials_for_ranking
        self._trials: list[VerifiedStrategyTrial] = []
        self._trial_ids: set[str] = set()
        self._suite_digest: str | None = None
        self._lock = RLock()

    def record(
        self,
        proposal: EvolutionStrategyProposal,
        evidence: StrategyTrialEvidence,
    ) -> VerifiedStrategyTrial:
        if not isinstance(proposal, EvolutionStrategyProposal) or not isinstance(evidence, StrategyTrialEvidence):
            raise MetaLearningError("typed Stage 151 proposal and trial evidence are required")
        if proposal.execution_authorized or proposal.model_mutation_authorized or proposal.auto_adoption_authorized:
            raise MetaLearningError("proposal contains unexpected execution authority")
        if evidence.proposal_id != proposal.proposal_id or evidence.strategy is not proposal.strategy:
            raise MetaLearningError("trial does not bind the exact strategy proposal")
        if not _ID.fullmatch(evidence.trial_id or "") or not _ID.fullmatch(evidence.evaluator_id or "") or not _ID.fullmatch(evidence.strategy_author_id or ""):
            raise MetaLearningError("invalid trial, evaluator, or author identity")
        if evidence.evaluator_id == evidence.strategy_author_id:
            raise MetaLearningError("strategy author cannot independently evaluate its own trial")
        for value in (evidence.evaluation_suite_digest, evidence.execution_receipt_digest,
                      evidence.candidate_artifact_digest, evidence.parent_artifact_digest):
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise MetaLearningError("all suite, receipt, and artifact digests must be SHA-256 hex")
        if evidence.baseline.evaluation_suite_digest != evidence.evaluation_suite_digest or evidence.candidate.evaluation_suite_digest != evidence.evaluation_suite_digest:
            raise MetaLearningError("baseline and candidate must use the exact frozen evaluation suite")
        try:
            verified = self._verifier(evidence)
        except Exception as exc:
            raise MetaLearningError("independent evidence verification failed closed") from exc
        if verified is not True:
            raise MetaLearningError("trial evidence was not independently authenticated")
        if dominates(evidence.candidate, evidence.baseline):
            outcome = TrialOutcome.IMPROVED
        elif dominates(evidence.baseline, evidence.candidate):
            outcome = TrialOutcome.REGRESSED
        else:
            outcome = TrialOutcome.NEUTRAL
        payload = {
            "trial": evidence.trial_id, "proposal": evidence.proposal_id,
            "strategy": evidence.strategy.value, "outcome": outcome.value,
            "suite": evidence.evaluation_suite_digest,
            "receipt": evidence.execution_receipt_digest,
            "candidate": evidence.candidate_artifact_digest,
            "parent": evidence.parent_artifact_digest,
            "evaluator": evidence.evaluator_id,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = VerifiedStrategyTrial(evidence.trial_id, evidence.proposal_id, evidence.strategy,
                                       outcome, evidence.evaluation_suite_digest, digest)
        with self._lock:
            if evidence.trial_id in self._trial_ids:
                raise MetaLearningError("duplicate trial replay rejected")
            if self._suite_digest is not None and self._suite_digest != evidence.evaluation_suite_digest:
                raise MetaLearningError("evaluation suite drift; start a separately versioned ledger")
            if len(self._trials) >= self._max_trials:
                raise MetaLearningError("trial ledger capacity reached; recording is fail-closed")
            self._suite_digest = evidence.evaluation_suite_digest
            self._trial_ids.add(evidence.trial_id)
            self._trials.append(result)
        return result

    def snapshot(self) -> MetaLearningSnapshot:
        with self._lock:
            trials = tuple(self._trials)
            suite = self._suite_digest or ""
        grouped: dict[StrategyKind, list[VerifiedStrategyTrial]] = {}
        for trial in trials:
            grouped.setdefault(trial.strategy, []).append(trial)
        rows = []
        for strategy, items in grouped.items():
            improved = sum(x.outcome is TrialOutcome.IMPROVED for x in items)
            regressed = sum(x.outcome is TrialOutcome.REGRESSED for x in items)
            neutral = len(items) - improved - regressed
            # No synthetic reward: only observed Pareto improvements count as success.
            rows.append((strategy, len(items), improved, regressed, neutral, improved / len(items)))
        rows.sort(key=lambda x: (-x[5], -x[2], x[3], x[0].value))
        ranked_rows = []
        rank = 0
        for strategy, count, improved, regressed, neutral, rate in rows:
            eligible = count >= self._min_trials
            if eligible:
                rank += 1
            ranked_rows.append(StrategyEffectiveness(
                strategy, count, improved, regressed, neutral, rate, 0.0,
                eligible, rank if eligible else None,
            ))
        payload = {"trials": [x.evidence_digest for x in trials],
                   "suite": suite, "effectiveness": [(x.strategy.value, x.trials, x.improvements,
                   x.regressions, x.neutral, x.success_rate, x.rank) for x in ranked_rows]}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return MetaLearningSnapshot(trials, tuple(ranked_rows), suite, digest)


__all__ = [
    "MetaLearningError", "TrialOutcome", "StrategyTrialEvidence",
    "VerifiedStrategyTrial", "StrategyEffectiveness", "MetaLearningSnapshot",
    "EvolutionaryMetaLearner",
]
