from dataclasses import asdict, replace
import hashlib
import json

import pytest

from core.ai_factory_stage186_190_multigeneration_evolution import (
    GenerationSnapshot,
    GeneralizationAuditEvidence,
    LongitudinalEvolutionError,
    RegressionClaim,
    SurvivalLedgerEntry,
    Stage186LongitudinalTrendAnalyzer,
    Stage187GeneralizationAuditor,
    Stage188RegressionAttributor,
    Stage189SurvivalLedger,
    Stage190LongitudinalCertificatePackager,
)

H = "a" * 64
SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == SIGN(digest)


def unsigned_digest(value):
    payload = asdict(value)
    payload.pop("signature")
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")).hexdigest()


def signed(value):
    return replace(value, signature=SIGN(unsigned_digest(value)))


def snapshots():
    rows = []
    parent = H
    for generation in (1, 2, 3):
        row = GenerationSnapshot(
            generation=generation,
            candidate_id="candidate-main",
            artifact_digest=str(generation) * 64,
            evaluation_suite_digest=H,
            evaluator_id=f"evaluator-{generation}",
            trial_id=f"trial-{generation}",
            quality=0.90 + (generation - 1) * 0.01,
            safety=0.99,
            latency_ms=100 - (generation - 1) * 2,
            memory_mb=500 - (generation - 1) * 5,
            executor_id="isolated-executor",
            parent_digest=parent,
            signature="",
        )
        row = signed(row)
        rows.append(row)
        parent = unsigned_digest(row)
    return tuple(rows)


def build_trend(rows=None):
    return Stage186LongitudinalTrendAnalyzer().build(
        rows or snapshots(),
        parent_readiness_digest=H,
        parent_generation=1,
        verify_parent_readiness=lambda digest, generation, candidate:
            digest == H and generation == 1 and candidate == "candidate-main",
        verify_snapshot=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )


def build_pipeline():
    trend = build_trend()
    evidence = signed(GeneralizationAuditEvidence(
        trend_report_digest=trend.report_digest,
        training_dataset_digest="b" * 64,
        holdout_dataset_digest="c" * 64,
        adversarial_suite_digest="d" * 64,
        training_holdout_disjoint=True,
        holdout_never_used_for_training=True,
        contamination_check_passed=True,
        coverage=0.99,
        evaluator_id="holdout-evaluator",
        signature="",
    ))
    audit = Stage187GeneralizationAuditor().build(
        trend, evidence, verify_trend_signature=VERIFY,
        verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
    )
    attribution = Stage188RegressionAttributor().build(
        trend, audit, (), verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )
    entries = (
        signed(SurvivalLedgerEntry(2, "candidate-main", "f" * 64, "strategy-a", "survived", "1" * 64, "")),
        signed(SurvivalLedgerEntry(3, "candidate-main", "2" * 64, "strategy-a", "survived", "3" * 64, "")),
    )
    ledger = Stage189SurvivalLedger().build(
        previous_ledger_digest=H,
        previous_generation=1,
        entries=entries,
        verify_previous_ledger=lambda digest, generation: digest == H and generation == 1,
        verify_entry_signature=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )
    return trend, audit, attribution, ledger


def package(trend, audit, attribution, ledger, **overrides):
    kwargs = dict(
        verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY,
        verify_attribution_signature=VERIFY,
        verify_ledger_signature=VERIFY,
        verify_ledger_entry_signature=VERIFY,
        verify_ledger_predecessor=lambda digest, generation: digest == H and generation == 1,
        verify_certificate_signature=VERIFY,
        sign_certificate=SIGN,
    )
    kwargs.update(overrides)
    return Stage190LongitudinalCertificatePackager().build(
        trend, audit, attribution, ledger, **kwargs
    )


def test_stages_186_to_190_create_signed_review_only_certificate():
    trend, audit, attribution, ledger = build_pipeline()
    cert = package(trend, audit, attribution, ledger)
    assert (cert.first_generation, cert.last_generation) == (1, 3)
    assert cert.parent_readiness_digest == H
    assert cert.ready_for_human_review
    assert cert.certificate_signature == SIGN(cert.certificate_digest)
    assert cert.proposal_only
    assert not cert.weight_mutation_authorized
    assert not cert.generation_advance_authorized
    assert not cert.model_activation_authorized
    assert not cert.production_switch_authorized


def test_stage186_rejects_generation_gap_replay_forgery_and_parent_drift():
    rows = snapshots()
    gap = (rows[0], rows[1], replace(rows[2], generation=4))
    with pytest.raises(LongitudinalEvolutionError, match="contiguous"):
        build_trend(gap)
    replay = (rows[0], replace(rows[1], evaluator_id="evaluator-1"), rows[2])
    with pytest.raises(LongitudinalEvolutionError, match="replayed"):
        build_trend(replay)
    forged = (rows[0], replace(rows[1], signature="forged"), rows[2])
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        build_trend(forged)
    broken_parent = (rows[0], replace(rows[1], parent_digest="e" * 64), rows[2])
    with pytest.raises(LongitudinalEvolutionError, match="parent lineage"):
        build_trend(broken_parent)


def test_stage186_requires_trusted_stage185_lineage_and_independent_executor():
    rows = snapshots()
    with pytest.raises(LongitudinalEvolutionError, match="Stage 185 readiness"):
        Stage186LongitudinalTrendAnalyzer().build(
            rows, parent_readiness_digest=H, parent_generation=1,
            verify_parent_readiness=lambda *_: False, verify_snapshot=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
        )
    same_actor = tuple(replace(row, evaluator_id="isolated-executor") for row in rows)
    with pytest.raises(LongitudinalEvolutionError, match="independent"):
        build_trend(same_actor)


def test_stage186_bounds_iterable_before_materializing():
    consumed = 0

    def oversized():
        nonlocal consumed
        for index in range(100):
            consumed += 1
            yield snapshots()[0]

    with pytest.raises(LongitudinalEvolutionError, match="32-item bound"):
        build_trend(oversized())
    assert consumed == 33


def test_stage186_rejects_invalid_metrics_and_boolean_generation():
    rows = snapshots()
    invalid = (rows[0], rows[1], replace(rows[2], quality=float("nan")))
    with pytest.raises(LongitudinalEvolutionError, match="finite number"):
        build_trend(invalid)
    invalid_generation = (replace(rows[0], generation=True), rows[1], rows[2])
    with pytest.raises(LongitudinalEvolutionError, match="generation number"):
        build_trend(invalid_generation)


def test_stage187_rejects_holdout_leakage_forgery_and_non_independent_evaluator():
    trend = build_trend()
    leaked = signed(GeneralizationAuditEvidence(
        trend.report_digest, "b" * 64, "b" * 64, "d" * 64,
        True, True, True, 0.99, "holdout-evaluator", "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="distinct"):
        Stage187GeneralizationAuditor().build(
            trend, leaked, verify_trend_signature=VERIFY,
            verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
        )
    valid = signed(GeneralizationAuditEvidence(
        trend.report_digest, "b" * 64, "c" * 64, "d" * 64,
        True, True, True, 0.99, "evaluator-1", "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="independent"):
        Stage187GeneralizationAuditor().build(
            trend, valid, verify_trend_signature=VERIFY,
            verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
        )
    forged = replace(valid, evaluator_id="holdout-evaluator", signature="forged")
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage187GeneralizationAuditor().build(
            trend, forged, verify_trend_signature=VERIFY,
            verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
        )


def test_stage187_records_low_coverage_as_failed_audit():
    trend = build_trend()
    evidence = signed(GeneralizationAuditEvidence(
        trend.report_digest, "b" * 64, "c" * 64, "d" * 64,
        True, True, True, 0.50, "holdout-evaluator", "",
    ))
    audit = Stage187GeneralizationAuditor().build(
        trend, evidence, verify_trend_signature=VERIFY,
        verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
    )
    assert not audit.passed


def test_stage188_rejects_forged_claim_and_preserves_unknown_as_unsupported():
    trend, audit, _, _ = build_pipeline()
    claim = signed(RegressionClaim(
        "unknown", 2, "candidate-main", "e" * 64, "diagnostician-a", "",
    ))
    report = Stage188RegressionAttributor().build(
        trend, audit, (claim,), verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )
    assert report.unsupported_claim_count == 1
    assert report.supported_categories == ("unknown",)
    forged = replace(claim, signature="forged")
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage188RegressionAttributor().build(
            trend, audit, (forged,), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
            verify_report_signature=VERIFY, sign_report=SIGN,
        )


def test_stage188_rejects_replay_and_evaluator_overlap():
    trend, audit, _, _ = build_pipeline()
    claim = signed(RegressionClaim(
        "candidate_regression", 2, "candidate-main", "e" * 64, "holdout-evaluator", "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="not independent"):
        Stage188RegressionAttributor().build(
            trend, audit, (claim,), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
            verify_report_signature=VERIFY, sign_report=SIGN,
        )
    duplicate = signed(RegressionClaim(
        "candidate_regression", 2, "candidate-main", "e" * 64, "diagnostician-a", "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="replayed"):
        Stage188RegressionAttributor().build(
            trend, audit, (duplicate, duplicate), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
            verify_report_signature=VERIFY, sign_report=SIGN,
        )


def test_stage188_binds_unsupported_claims_and_rejects_their_replay():
    trend, audit, _, _ = build_pipeline()
    unsupported = signed(RegressionClaim(
        "unrecognized-cause", 2, "different-candidate", "e" * 64, "diagnostician-a", "",
    ))
    report = Stage188RegressionAttributor().build(
        trend, audit, (unsupported,), verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )
    assert report.unsupported_claim_count == 1
    assert report.claim_digests == (unsigned_digest(unsupported),)

    with pytest.raises(LongitudinalEvolutionError, match="replayed"):
        Stage188RegressionAttributor().build(
            trend, audit, (unsupported, unsupported), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
            verify_report_signature=VERIFY, sign_report=SIGN,
        )


def test_stage190_rejects_noncanonical_claim_digest_order():
    trend, audit, _, ledger = build_pipeline()
    claims = (
        signed(RegressionClaim(
            "candidate_regression", 2, "candidate-main", "e" * 64, "diagnostician-a", "",
        )),
        signed(RegressionClaim(
            "data_drift", 3, "candidate-main", "f" * 64, "diagnostician-b", "",
        )),
    )
    attribution = Stage188RegressionAttributor().build(
        trend, audit, claims, verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
        verify_report_signature=VERIFY, sign_report=SIGN,
    )
    forged_order = replace(attribution, claim_digests=tuple(reversed(attribution.claim_digests)))
    with pytest.raises(LongitudinalEvolutionError, match="regression claim digest set is invalid"):
        package(trend, audit, forged_order, ledger)


def test_stage190_rejects_unsupported_count_exceeding_bound_claim_digests():
    trend, audit, attribution, ledger = build_pipeline()
    forged = replace(attribution, unsupported_claim_count=1)
    with pytest.raises(LongitudinalEvolutionError, match="unsupported claim count"):
        package(trend, audit, forged, ledger)


def test_stage189_rejects_duplicate_gap_forgery_and_untrusted_predecessor():
    first = signed(SurvivalLedgerEntry(2, "candidate-main", "a" * 64, "s", "survived", "b" * 64, ""))
    duplicate = (first, first)
    kwargs = dict(
        previous_ledger_digest=H, previous_generation=1,
        verify_previous_ledger=lambda digest, generation: digest == H and generation == 1,
        verify_entry_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
    )
    with pytest.raises(LongitudinalEvolutionError, match="duplicate"):
        Stage189SurvivalLedger().build(entries=duplicate, **kwargs)
    gap = (
        first,
        signed(SurvivalLedgerEntry(4, "candidate-main", "c" * 64, "s", "survived", "d" * 64, "")),
    )
    with pytest.raises(LongitudinalEvolutionError, match="gap"):
        Stage189SurvivalLedger().build(entries=gap, **kwargs)
    forged = (replace(first, signature="forged"),)
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage189SurvivalLedger().build(entries=forged, **kwargs)
    with pytest.raises(LongitudinalEvolutionError, match="trusted current checkpoint"):
        Stage189SurvivalLedger().build(
            entries=(first,), **{**kwargs, "verify_previous_ledger": lambda *_: False}
        )


def test_stage189_bounds_iterable_before_materializing():
    consumed = 0

    def oversized():
        nonlocal consumed
        for index in range(200):
            consumed += 1
            yield signed(SurvivalLedgerEntry(
                2, f"candidate-{index}", "a" * 64, f"strategy-{index}",
                "survived", "b" * 64, "",
            ))

    with pytest.raises(LongitudinalEvolutionError, match="128-item bound"):
        Stage189SurvivalLedger().build(
            previous_ledger_digest=H, previous_generation=1, entries=oversized(),
            verify_previous_ledger=lambda *_: True, verify_entry_signature=VERIFY,
            verify_report_signature=VERIFY, sign_report=SIGN,
        )
    assert consumed == 129


def test_stage190_rejects_tampering_forged_signatures_and_untrusted_predecessor():
    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        package(trend, replace(audit, signature="forged"), attribution, ledger)
    changed_entry = replace(ledger.entries[0], outcome="retired_proposal")
    changed_ledger = replace(ledger, entries=(changed_entry, *ledger.entries[1:]))
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        package(trend, audit, attribution, changed_ledger)
    with pytest.raises(LongitudinalEvolutionError, match="trusted current checkpoint"):
        package(
            trend, audit, attribution, ledger,
            verify_ledger_predecessor=lambda *_: False,
        )


def test_stage190_rejects_ledger_lineage_that_skips_first_generation():
    trend, audit, attribution, ledger = build_pipeline()
    wrong_entries = (
        signed(SurvivalLedgerEntry(3, "candidate-main", "f" * 64, "strategy-a", "survived", "1" * 64, "")),
    )
    wrong_ledger = Stage189SurvivalLedger().build(
        previous_ledger_digest=H, previous_generation=2, entries=wrong_entries,
        verify_previous_ledger=lambda *_: True, verify_entry_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN,
    )
    with pytest.raises(LongitudinalEvolutionError, match="starting generation"):
        package(trend, audit, attribution, wrong_ledger)


@pytest.mark.parametrize("stage", range(186, 191))
def test_hold_blocks_every_stage(stage):
    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="HOLD"):
        if stage == 186:
            Stage186LongitudinalTrendAnalyzer().build(
                snapshots(), parent_readiness_digest=H, parent_generation=1,
                verify_parent_readiness=lambda *_: True, verify_snapshot=VERIFY,
                verify_report_signature=VERIFY, sign_report=SIGN, hold_active=True,
            )
        elif stage == 187:
            evidence = signed(GeneralizationAuditEvidence(
                trend.report_digest, "b" * 64, "c" * 64, "d" * 64,
                True, True, True, 0.99, "another-evaluator", "",
            ))
            Stage187GeneralizationAuditor().build(
                trend, evidence, verify_trend_signature=VERIFY,
                verify_evidence_signature=VERIFY, verify_report_signature=VERIFY, sign_report=SIGN, hold_active=True,
            )
        elif stage == 188:
            Stage188RegressionAttributor().build(
                trend, audit, (), verify_trend_signature=VERIFY,
                verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
                verify_report_signature=VERIFY, sign_report=SIGN, hold_active=True,
            )
        elif stage == 189:
            entry = signed(SurvivalLedgerEntry(
                2, "candidate-main", "a" * 64, "s", "survived", "b" * 64, "",
            ))
            Stage189SurvivalLedger().build(
                previous_ledger_digest=H, previous_generation=1, entries=(entry,),
                verify_previous_ledger=lambda *_: True, verify_entry_signature=VERIFY,
                verify_report_signature=VERIFY, sign_report=SIGN, hold_active=True,
            )
        else:
            package(trend, audit, attribution, ledger, hold_active=True)


def test_each_stage_verifies_its_own_output_signature():
    reject = lambda *_: False
    with pytest.raises(LongitudinalEvolutionError, match="signature verification failed"):
        Stage186LongitudinalTrendAnalyzer().build(
            snapshots(), parent_readiness_digest=H, parent_generation=1,
            verify_parent_readiness=lambda *_: True, verify_snapshot=VERIFY,
            verify_report_signature=reject, sign_report=SIGN,
        )

    trend = build_trend()
    evidence = signed(GeneralizationAuditEvidence(
        trend.report_digest, "b" * 64, "c" * 64, "d" * 64,
        True, True, True, 0.99, "holdout-evaluator", "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="signature verification failed"):
        Stage187GeneralizationAuditor().build(
            trend, evidence, verify_trend_signature=VERIFY,
            verify_evidence_signature=VERIFY, verify_report_signature=reject,
            sign_report=SIGN,
        )

    trend, audit, _, _ = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="signature verification failed"):
        Stage188RegressionAttributor().build(
            trend, audit, (), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_claim_signature=VERIFY,
            verify_report_signature=reject, sign_report=SIGN,
        )

    entry = signed(SurvivalLedgerEntry(
        2, "candidate-main", "f" * 64, "strategy-a", "survived", "1" * 64, "",
    ))
    with pytest.raises(LongitudinalEvolutionError, match="signature verification failed"):
        Stage189SurvivalLedger().build(
            previous_ledger_digest=H, previous_generation=1, entries=(entry,),
            verify_previous_ledger=lambda *_: True, verify_entry_signature=VERIFY,
            verify_report_signature=reject, sign_report=SIGN,
        )

    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="signature verification failed"):
        package(trend, audit, attribution, ledger, verify_certificate_signature=reject)
