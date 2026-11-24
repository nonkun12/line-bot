from dataclasses import replace
import hashlib
import json
from itertools import repeat
import pytest

from core.ai_factory_stage181_185_intergeneration_evolution import (
    CandidateEvaluation, EvolutionError, Stage181InterGenerationEvaluator,
    Stage182BoundedVariationPlanner, Stage183ParetoDiversitySelector,
    Stage184CohortComposer, Stage185EvolutionReadinessPackager,
    stage185_readiness_verifier,
)

H = "a" * 64


def evidence():
    return (
        CandidateEvaluation("baseline", "1"*64, ("parent-a",), 4, 5, H,
                            "eval-a", "trial-a", .90, .99, 100, 500, "sig-a"),
        CandidateEvaluation("candidate-1", "2"*64, ("parent-a", "parent-b"), 4, 5, H,
                            "eval-b", "trial-b", .94, .995, 95, 490, "sig-b"),
    )


def pipeline():
    report = Stage181InterGenerationEvaluator().build(
        source_generation=4, target_generation=5, baseline_candidate_id="baseline",
        evaluations=evidence(), verify_signature=lambda x: x.signature.startswith("sig-"),
        sign_report=lambda d: "signed:" + d)
    variations = Stage182BoundedVariationPlanner().build(
        report, recipes=(("variant-a", ("candidate-1",), "3"*64, 1),
                         ("variant-b", ("baseline",), "4"*64, 2)),
        sign_report=lambda d: "signed:" + d)
    selection = Stage183ParetoDiversitySelector().build(report, evidence())
    cohort = Stage184CohortComposer().build(
        report, selection, variations, sign_report=lambda d: "signed:" + d)
    return report, selection, variations, cohort


def test_stages_181_to_185_build_signed_human_review_proposal():
    report, selection, variations, cohort = pipeline()
    cert = Stage185EvolutionReadinessPackager().build(
        report, selection, variations, cohort,
        verify_report_signature=lambda d, s: s == "signed:" + d,
        verify_variation_signature=lambda d, s: s == "signed:" + d,
        verify_cohort_signature=lambda d, s: s == "signed:" + d)
    assert report.eligible_candidate_ids == ("candidate-1",)
    assert selection.selected_candidate_ids == ("candidate-1",)
    assert len(variations.proposals) == 2
    assert cert.ready_for_human_review and cert.proposal_only
    assert not cert.weight_mutation_authorized
    assert not cert.generation_advance_authorized
    assert not cert.model_activation_authorized
    assert not cert.production_switch_authorized


def test_stage181_rejects_replay_duplicate_evaluators_and_suite_drift():
    rows = evidence()
    with pytest.raises(EvolutionError, match="replayed"):
        Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
            baseline_candidate_id="baseline", evaluations=(rows[0], replace(rows[1], trial_id="trial-a")),
            verify_signature=lambda x: True, sign_report=lambda d: "signed")
    with pytest.raises(EvolutionError, match="independent evaluator"):
        Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
            baseline_candidate_id="baseline", evaluations=(rows[0], replace(rows[1], evaluator_id="eval-a")),
            verify_signature=lambda x: True, sign_report=lambda d: "signed")
    with pytest.raises(EvolutionError, match="suite drift"):
        Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
            baseline_candidate_id="baseline", evaluations=(rows[0], replace(rows[1], evaluation_suite_digest="b"*64)),
            verify_signature=lambda x: True, sign_report=lambda d: "signed")


def test_stage181_rejects_forged_or_regressing_evidence():
    rows = evidence()
    with pytest.raises(EvolutionError, match="signature"):
        Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
            baseline_candidate_id="baseline", evaluations=rows,
            verify_signature=lambda x: False, sign_report=lambda d: "signed")
    bad = replace(rows[1], safety=.80)
    report = Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
        baseline_candidate_id="baseline", evaluations=(rows[0], bad),
        verify_signature=lambda x: True, sign_report=lambda d: "signed")
    assert report.eligible_candidate_ids == ()


def test_stage182_rejects_unbounded_mutation_and_unknown_parent():
    report, _, _, _ = pipeline()
    with pytest.raises(EvolutionError, match="budget"):
        Stage182BoundedVariationPlanner().build(report,
            recipes=(("bad-variant", ("candidate-1",), "5"*64, 99),),
            sign_report=lambda d: "signed")
    with pytest.raises(EvolutionError, match="parent"):
        Stage182BoundedVariationPlanner().build(report,
            recipes=(("bad-variant", ("unknown",), "5"*64, 1),),
            sign_report=lambda d: "signed")


def test_stage183_requires_exact_stage181_evidence():
    report, _, _, _ = pipeline()
    altered = (evidence()[0], replace(evidence()[1], quality=.99))
    with pytest.raises(EvolutionError, match="differs"):
        Stage183ParetoDiversitySelector().build(report, altered)


def test_stage185_rejects_tampered_selection_and_bad_signature():
    report, selection, variations, cohort = pipeline()
    with pytest.raises(EvolutionError, match="selection digest"):
        Stage185EvolutionReadinessPackager().build(report,
            replace(selection, selected_candidate_ids=("forged",)), variations, cohort,
            verify_report_signature=lambda d, s: True,
            verify_variation_signature=lambda d, s: True,
            verify_cohort_signature=lambda d, s: True)
    with pytest.raises(EvolutionError, match="Stage 182 signature"):
        Stage185EvolutionReadinessPackager().build(report, selection,
            replace(variations, signature="forged"), cohort,
            verify_report_signature=lambda d, s: True,
            verify_variation_signature=lambda d, s: False,
            verify_cohort_signature=lambda d, s: True)


@pytest.mark.parametrize("stage", range(181, 186))
def test_hold_blocks_every_stage(stage):
    report, selection, variations, cohort = pipeline()
    rows = evidence()
    with pytest.raises(EvolutionError, match="HOLD"):
        if stage == 181:
            Stage181InterGenerationEvaluator().build(source_generation=4, target_generation=5,
                baseline_candidate_id="baseline", evaluations=rows, verify_signature=lambda x: True,
                sign_report=lambda d: "signed", hold_active=True)
        elif stage == 182:
            Stage182BoundedVariationPlanner().build(report,
                recipes=(("x", ("candidate-1",), "5"*64, 1),),
                sign_report=lambda d: "signed", hold_active=True)
        elif stage == 183:
            Stage183ParetoDiversitySelector().build(report, rows, hold_active=True)
        elif stage == 184:
            Stage184CohortComposer().build(report, selection, variations,
                sign_report=lambda d: "signed", hold_active=True)
        else:
            Stage185EvolutionReadinessPackager().build(report, selection, variations, cohort,
                verify_report_signature=lambda d, s: True,
                verify_variation_signature=lambda d, s: True,
                verify_cohort_signature=lambda d, s: True, hold_active=True)



def test_stage181_and_stage182_bound_iterables_before_materialization():
    with pytest.raises(EvolutionError, match="64-item bound"):
        Stage181InterGenerationEvaluator().build(
            source_generation=4, target_generation=5, baseline_candidate_id="baseline",
            evaluations=repeat(evidence()[0]), verify_signature=lambda x: True,
            sign_report=lambda d: "signed:" + d,
        )
    report, _, _, _ = pipeline()
    with pytest.raises(EvolutionError, match="16-item bound"):
        Stage182BoundedVariationPlanner().build(
            report, recipes=repeat(("overflow", ("candidate-1",), "5" * 64, 1)),
            sign_report=lambda d: "signed:" + d,
        )


def test_stage185_signed_checkpoint_verifier_binds_generation_and_candidate():
    report, selection, variations, cohort = pipeline()
    cert = Stage185EvolutionReadinessPackager().build(
        report, selection, variations, cohort,
        verify_report_signature=lambda d, s: s == "signed:" + d,
        verify_variation_signature=lambda d, s: s == "signed:" + d,
        verify_cohort_signature=lambda d, s: s == "signed:" + d,
        sign_certificate=lambda d: "signed:" + d,
    )
    current_checkpoint = lambda d, g, c: (
        d == cert.certificate_digest and g == cert.proposed_generation and c in cert.candidate_ids
    )
    verify_parent = stage185_readiness_verifier(
        cert,
        verify_signature=lambda d, s: s == "signed:" + d,
        verify_current_checkpoint=current_checkpoint,
    )
    assert verify_parent(cert.certificate_digest, cert.proposed_generation, "candidate-1") is True
    assert verify_parent(cert.certificate_digest, cert.proposed_generation + 1, "candidate-1") is False
    assert verify_parent(cert.certificate_digest, cert.proposed_generation, "not-in-certificate") is False
    stale_parent = stage185_readiness_verifier(
        cert,
        verify_signature=lambda d, s: s == "signed:" + d,
        verify_current_checkpoint=lambda *_: False,
    )
    assert stale_parent(cert.certificate_digest, cert.proposed_generation, "candidate-1") is False
    forged = replace(cert, certificate_signature="forged")
    assert stage185_readiness_verifier(
        forged,
        verify_signature=lambda d, s: s == "signed:" + d,
        verify_current_checkpoint=current_checkpoint,
    )(forged.certificate_digest, forged.proposed_generation, "candidate-1") is False


def test_stage185_checkpoint_membership_matches_the_signed_cohort():
    report, selection, variations, cohort = pipeline()
    cohort_ids = ("candidate-1",)
    payload = {
        "source": cohort.source_generation,
        "target": cohort.target_generation,
        "selection": cohort.selection_digest,
        "variations": cohort.mutation_proposal_set_digest,
        "cohort": cohort_ids,
    }
    cohort_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    narrowed_cohort = replace(
        cohort,
        cohort_candidate_ids=cohort_ids,
        cohort_digest=cohort_digest,
        signature="signed:" + cohort_digest,
    )
    cert = Stage185EvolutionReadinessPackager().build(
        report, selection, variations, narrowed_cohort,
        verify_report_signature=lambda d, s: s == "signed:" + d,
        verify_variation_signature=lambda d, s: s == "signed:" + d,
        verify_cohort_signature=lambda d, s: s == "signed:" + d,
        sign_certificate=lambda d: "signed:" + d,
    )
    assert cert.candidate_ids == cohort_ids
    verify_parent = stage185_readiness_verifier(
        cert,
        verify_signature=lambda d, s: s == "signed:" + d,
        verify_current_checkpoint=lambda d, g, c: (
            d == cert.certificate_digest and g == cert.proposed_generation and c in cert.candidate_ids
        ),
    )
    assert verify_parent(cert.certificate_digest, cert.proposed_generation, "candidate-1") is True
    assert verify_parent(cert.certificate_digest, cert.proposed_generation, "variant-a") is False
