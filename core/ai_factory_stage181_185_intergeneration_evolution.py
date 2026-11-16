"""Stages 181-185: evidence-bound inter-generation evolutionary proposals.

This module validates supplied evidence and emits proposals only. It never loads,
executes, mutates, merges, registers, or activates model weights.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Callable, Iterable


class EvolutionError(ValueError):
    """Raised when evolutionary evidence is invalid or unsafe."""


_HEX = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _check_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise EvolutionError(f"{label} must be a lowercase SHA-256 digest")


def _check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise EvolutionError(f"{label} is invalid")


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    artifact_digest: str
    parent_ids: tuple[str, ...]
    source_generation: int
    target_generation: int
    evaluation_suite_digest: str
    evaluator_id: str
    trial_id: str
    quality: float
    safety: float
    latency_ms: float
    memory_mb: float
    signature: str


@dataclass(frozen=True)
class InterGenerationReport:
    source_generation: int
    target_generation: int
    evaluation_suite_digest: str
    candidate_digests: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    baseline_candidate_id: str
    eligible_candidate_ids: tuple[str, ...]
    report_digest: str
    signature: str
    proposal_only: bool = True


class Stage181InterGenerationEvaluator:
    """Compare candidates against a frozen baseline using independently signed evidence."""

    def build(
        self,
        *,
        source_generation: int,
        target_generation: int,
        baseline_candidate_id: str,
        evaluations: Iterable[CandidateEvaluation],
        verify_signature: Callable[[CandidateEvaluation], bool],
        sign_report: Callable[[str], str],
        minimum_safety: float = 0.95,
        max_quality_regression: float = 0.01,
        max_safety_regression: float = 0.0,
        max_latency_regression: float = 0.10,
        max_memory_regression: float = 0.10,
        hold_active: bool = False,
    ) -> InterGenerationReport:
        if hold_active:
            raise EvolutionError("HOLD blocks Stage 181")
        if target_generation != source_generation + 1:
            raise EvolutionError("generation must advance exactly one step")
        _check_id(baseline_candidate_id, "baseline candidate id")
        limits = (minimum_safety, max_quality_regression, max_safety_regression,
                  max_latency_regression, max_memory_regression)
        if any(not math.isfinite(x) or x < 0 for x in limits) or minimum_safety > 1:
            raise EvolutionError("invalid comparison thresholds")
        items = tuple(evaluations)
        if len(items) < 2:
            raise EvolutionError("baseline and at least one challenger are required")
        if len({x.candidate_id for x in items}) != len(items):
            raise EvolutionError("duplicate candidate evaluation")
        if len({x.trial_id for x in items}) != len(items):
            raise EvolutionError("replayed evaluation trial")
        if len({x.evaluator_id for x in items}) != len(items):
            raise EvolutionError("independent evaluator identities required")
        suites = {x.evaluation_suite_digest for x in items}
        if len(suites) != 1:
            raise EvolutionError("evaluation suite drift")
        for item in items:
            _check_id(item.candidate_id, "candidate id")
            _check_id(item.evaluator_id, "evaluator id")
            _check_id(item.trial_id, "trial id")
            _check_digest(item.artifact_digest, "candidate artifact")
            _check_digest(item.evaluation_suite_digest, "evaluation suite")
            if item.source_generation != source_generation or item.target_generation != target_generation:
                raise EvolutionError("candidate generation lineage mismatch")
            if not item.parent_ids or len(set(item.parent_ids)) != len(item.parent_ids):
                raise EvolutionError("candidate parent lineage invalid")
            if any(not math.isfinite(v) for v in (item.quality, item.safety, item.latency_ms, item.memory_mb)):
                raise EvolutionError("non-finite evaluation metric")
            if not (0 <= item.quality <= 1 and 0 <= item.safety <= 1 and item.latency_ms >= 0 and item.memory_mb >= 0):
                raise EvolutionError("evaluation metric outside valid range")
            if not item.signature or not verify_signature(item):
                raise EvolutionError("candidate evaluation signature verification failed")
        baseline = next((x for x in items if x.candidate_id == baseline_candidate_id), None)
        if baseline is None:
            raise EvolutionError("baseline candidate evidence missing")
        eligible = []
        for item in items:
            if item.candidate_id == baseline_candidate_id:
                continue
            if (item.safety >= minimum_safety
                and item.quality >= baseline.quality - max_quality_regression
                and item.safety >= baseline.safety - max_safety_regression
                and item.latency_ms <= baseline.latency_ms * (1 + max_latency_regression)
                and item.memory_mb <= baseline.memory_mb * (1 + max_memory_regression)):
                eligible.append(item.candidate_id)
        digests = tuple(sorted(_digest(asdict(x)) for x in items))
        evaluators = tuple(sorted(x.evaluator_id for x in items))
        payload = {"source": source_generation, "target": target_generation, "suite": next(iter(suites)),
                   "candidate_digests": digests, "evaluators": evaluators,
                   "baseline": baseline_candidate_id, "eligible": tuple(sorted(eligible))}
        report_digest = _digest(payload)
        signature = sign_report(report_digest)
        if not isinstance(signature, str) or not signature.strip():
            raise EvolutionError("Stage 181 report signing failed")
        return InterGenerationReport(source_generation, target_generation, next(iter(suites)),
            digests, evaluators, baseline_candidate_id, tuple(sorted(eligible)), report_digest, signature)


@dataclass(frozen=True)
class MutationProposal:
    candidate_id: str
    parent_ids: tuple[str, ...]
    source_generation: int
    target_generation: int
    recipe_digest: str
    deterministic_seed_digest: str
    mutation_budget: int
    proposal_digest: str


@dataclass(frozen=True)
class MutationProposalSet:
    inter_generation_report_digest: str
    proposals: tuple[MutationProposal, ...]
    proposal_set_digest: str
    signature: str
    proposal_only: bool = True


class Stage182BoundedVariationPlanner:
    """Describe bounded variation recipes; never performs parameter or tensor mutation."""

    def build(self, report: InterGenerationReport, *, recipes: Iterable[tuple[str, tuple[str, ...], str, int]],
              sign_report: Callable[[str], str], max_proposals: int = 16,
              max_mutation_budget: int = 3, hold_active: bool = False) -> MutationProposalSet:
        if hold_active:
            raise EvolutionError("HOLD blocks Stage 182")
        _verify_intergeneration_report(report)
        if not 1 <= max_proposals <= 64 or not 1 <= max_mutation_budget <= 8:
            raise EvolutionError("variation bounds are invalid")
        rows = tuple(recipes)
        if not rows or len(rows) > max_proposals:
            raise EvolutionError("variation proposal count outside bounds")
        proposals = []
        for candidate_id, parent_ids, recipe_digest, budget in rows:
            _check_id(candidate_id, "variation candidate id")
            _check_digest(recipe_digest, "variation recipe")
            if candidate_id in {report.baseline_candidate_id, *report.eligible_candidate_ids}:
                raise EvolutionError("variation candidate id collides with evaluated candidate")
            if not parent_ids or len(parent_ids) > 2 or len(set(parent_ids)) != len(parent_ids):
                raise EvolutionError("variation requires one or two distinct parents")
            if not set(parent_ids).issubset({report.baseline_candidate_id, *report.eligible_candidate_ids}):
                raise EvolutionError("variation parent is not an evaluated eligible lineage")
            if not isinstance(budget, int) or not 1 <= budget <= max_mutation_budget:
                raise EvolutionError("mutation budget exceeds bound")
            seed = _digest({"report": report.report_digest, "candidate": candidate_id, "recipe": recipe_digest})
            payload = {"candidate": candidate_id, "parents": parent_ids, "source": report.source_generation,
                       "target": report.target_generation, "recipe": recipe_digest, "seed": seed, "budget": budget}
            proposals.append(MutationProposal(candidate_id, tuple(parent_ids), report.source_generation,
                report.target_generation, recipe_digest, seed, budget, _digest(payload)))
        if len({p.candidate_id for p in proposals}) != len(proposals):
            raise EvolutionError("duplicate variation candidate")
        ordered = tuple(sorted(proposals, key=lambda p: p.candidate_id))
        payload = {"report": report.report_digest, "proposals": [asdict(p) for p in ordered]}
        digest = _digest(payload)
        signature = sign_report(digest)
        if not isinstance(signature, str) or not signature.strip():
            raise EvolutionError("Stage 182 proposal signing failed")
        return MutationProposalSet(report.report_digest, ordered, digest, signature)


@dataclass(frozen=True)
class ParetoSelection:
    inter_generation_report_digest: str
    selected_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    selection_digest: str
    proposal_only: bool = True


class Stage183ParetoDiversitySelector:
    """Select a bounded Pareto frontier; does not promote or activate candidates."""

    def build(self, report: InterGenerationReport, evaluations: Iterable[CandidateEvaluation], *,
              max_selected: int = 8, hold_active: bool = False) -> ParetoSelection:
        if hold_active:
            raise EvolutionError("HOLD blocks Stage 183")
        _verify_intergeneration_report(report)
        if not 1 <= max_selected <= 32:
            raise EvolutionError("selection bound invalid")
        items = {x.candidate_id: x for x in evaluations}
        if len(items) != len(tuple(evaluations)) if not isinstance(evaluations, tuple) else False:
            raise EvolutionError("duplicate selection evidence")
        eligible = [items[x] for x in report.eligible_candidate_ids if x in items]
        if len(eligible) != len(report.eligible_candidate_ids):
            raise EvolutionError("selection evidence missing")
        def dominates(a: CandidateEvaluation, b: CandidateEvaluation) -> bool:
            av = (a.quality, a.safety, -a.latency_ms, -a.memory_mb)
            bv = (b.quality, b.safety, -b.latency_ms, -b.memory_mb)
            return all(x >= y for x, y in zip(av, bv)) and any(x > y for x, y in zip(av, bv))
        frontier = [x for x in eligible if not any(dominates(y, x) for y in eligible if y != x)]
        # Deterministic tie-break; candidate identity never substitutes for evidence.
        frontier.sort(key=lambda x: (-x.safety, -x.quality, x.latency_ms, x.memory_mb, x.candidate_id))
        selected = tuple(x.candidate_id for x in frontier[:max_selected])
        rejected = tuple(sorted(set(report.eligible_candidate_ids) - set(selected)))
        digest = _digest({"report": report.report_digest, "selected": selected, "rejected": rejected})
        return ParetoSelection(report.report_digest, selected, rejected, digest)


@dataclass(frozen=True)
class NextGenerationCohort:
    source_generation: int
    target_generation: int
    selection_digest: str
    mutation_proposal_set_digest: str
    cohort_candidate_ids: tuple[str, ...]
    cohort_digest: str
    signature: str
    proposal_only: bool = True


class Stage184CohortComposer:
    """Compose a bounded, lineage-diverse cohort from selected and proposed candidates."""

    def build(self, report: InterGenerationReport, selection: ParetoSelection,
              variations: MutationProposalSet, *, max_cohort_size: int = 12,
              sign_report: Callable[[str], str], hold_active: bool = False) -> NextGenerationCohort:
        if hold_active:
            raise EvolutionError("HOLD blocks Stage 184")
        _verify_intergeneration_report(report)
        _check_digest(selection.selection_digest, "selection digest")
        _check_digest(variations.proposal_set_digest, "variation set digest")
        if selection.inter_generation_report_digest != report.report_digest:
            raise EvolutionError("selection report lineage mismatch")
        if variations.inter_generation_report_digest != report.report_digest:
            raise EvolutionError("variation report lineage mismatch")
        if not 1 <= max_cohort_size <= 32:
            raise EvolutionError("cohort bound invalid")
        ids = tuple(dict.fromkeys((*selection.selected_candidate_ids,
                                  *(p.candidate_id for p in variations.proposals))))
        if not ids or len(ids) > max_cohort_size:
            raise EvolutionError("cohort size outside bounds")
        proposal = {p.candidate_id: p for p in variations.proposals}
        parents = [proposal[x].parent_ids for x in ids if x in proposal]
        if len(parents) > 1 and len({tuple(sorted(p)) for p in parents}) == 1:
            raise EvolutionError("cohort lacks lineage diversity")
        payload = {"source": report.source_generation, "target": report.target_generation,
                   "selection": selection.selection_digest, "variations": variations.proposal_set_digest,
                   "cohort": ids}
        digest = _digest(payload)
        signature = sign_report(digest)
        if not isinstance(signature, str) or not signature.strip():
            raise EvolutionError("Stage 184 cohort signing failed")
        return NextGenerationCohort(report.source_generation, report.target_generation,
            selection.selection_digest, variations.proposal_set_digest, ids, digest, signature)


@dataclass(frozen=True)
class EvolutionReadinessCertificate:
    source_generation: int
    proposed_generation: int
    inter_generation_report_digest: str
    selection_digest: str
    variation_set_digest: str
    cohort_digest: str
    certificate_digest: str
    ready_for_human_review: bool
    proposal_only: bool = True
    weight_mutation_authorized: bool = False
    generation_advance_authorized: bool = False
    model_activation_authorized: bool = False
    production_switch_authorized: bool = False


class Stage185EvolutionReadinessPackager:
    """Verify signed lineage and package the next-generation proposal for human review."""

    def build(self, report: InterGenerationReport, selection: ParetoSelection,
              variations: MutationProposalSet, cohort: NextGenerationCohort, *,
              verify_report_signature: Callable[[str, str], bool],
              verify_variation_signature: Callable[[str, str], bool],
              verify_cohort_signature: Callable[[str, str], bool],
              hold_active: bool = False) -> EvolutionReadinessCertificate:
        if hold_active:
            raise EvolutionError("HOLD blocks Stage 185")
        _verify_intergeneration_report(report)
        if not verify_report_signature(report.report_digest, report.signature):
            raise EvolutionError("Stage 181 signature verification failed")
        if not verify_variation_signature(variations.proposal_set_digest, variations.signature):
            raise EvolutionError("Stage 182 signature verification failed")
        if not verify_cohort_signature(cohort.cohort_digest, cohort.signature):
            raise EvolutionError("Stage 184 signature verification failed")
        if selection.inter_generation_report_digest != report.report_digest:
            raise EvolutionError("selection lineage mismatch")
        if variations.inter_generation_report_digest != report.report_digest:
            raise EvolutionError("variation lineage mismatch")
        if cohort.selection_digest != selection.selection_digest or cohort.mutation_proposal_set_digest != variations.proposal_set_digest:
            raise EvolutionError("cohort evidence lineage mismatch")
        if (cohort.source_generation, cohort.target_generation) != (report.source_generation, report.target_generation):
            raise EvolutionError("cohort generation mismatch")
        if not cohort.cohort_candidate_ids or not set(cohort.cohort_candidate_ids).issubset(
            set(selection.selected_candidate_ids) | {p.candidate_id for p in variations.proposals}
        ):
            raise EvolutionError("cohort contains unapproved candidate lineage")
        payload = {"report": report.report_digest, "selection": selection.selection_digest,
                   "variations": variations.proposal_set_digest, "cohort": cohort.cohort_digest,
                   "source": report.source_generation, "target": report.target_generation}
        digest = _digest(payload)
        return EvolutionReadinessCertificate(report.source_generation, report.target_generation,
            report.report_digest, selection.selection_digest, variations.proposal_set_digest,
            cohort.cohort_digest, digest, bool(selection.selected_candidate_ids or variations.proposals))


def _verify_intergeneration_report(report: InterGenerationReport) -> None:
    _check_digest(report.evaluation_suite_digest, "evaluation suite")
    _check_digest(report.report_digest, "inter-generation report")
    _check_id(report.signature, "inter-generation signature")
    if not report.proposal_only or report.target_generation != report.source_generation + 1:
        raise EvolutionError("unsafe or non-adjacent inter-generation report")
    payload = {"source": report.source_generation, "target": report.target_generation,
               "suite": report.evaluation_suite_digest, "candidate_digests": report.candidate_digests,
               "evaluators": report.evaluator_ids, "baseline": report.baseline_candidate_id,
               "eligible": report.eligible_candidate_ids}
    if _digest(payload) != report.report_digest:
        raise EvolutionError("inter-generation report digest mismatch")


__all__ = [
    "EvolutionError", "CandidateEvaluation", "InterGenerationReport",
    "Stage181InterGenerationEvaluator", "MutationProposal", "MutationProposalSet",
    "Stage182BoundedVariationPlanner", "ParetoSelection", "Stage183ParetoDiversitySelector",
    "NextGenerationCohort", "Stage184CohortComposer", "EvolutionReadinessCertificate",
    "Stage185EvolutionReadinessPackager",
]
