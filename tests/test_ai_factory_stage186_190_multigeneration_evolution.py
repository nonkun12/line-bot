from dataclasses import replace

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
PREVIOUS_DIGEST = "9" * 64
SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == SIGN(digest)


def snapshots():
    return tuple(
        GenerationSnapshot(
            generation=g,
            candidate_id="lineage-main",
            artifact_candidate_id=f"artifact-{g}",
            parent_candidate_id="genesis" if g == 1 else f"artifact-{g - 1}",
            parent_readiness_digest=f"{g:064x}",
            artifact_digest=f"{g + 10:064x}",
            evaluation_suite_digest=H,
            evaluator_id=f"eval-{g}",
            executor_id=f"exec-{g}",
            trial_id=f"trial-{g}",
            quality=.90 + (g - 1) * .01,
            safety=.99,
            latency_ms=100 - (g - 1) * 2,
            memory_mb=500 - (g - 1) * 5,
            signature=f"snapshot-signature-{g}",
        )
        for g in (1, 2, 3)
    )


def verify_snapshot(item):
    return item.signature == f"snapshot-signature-{item.generation}"


def verify_parent_readiness(item):
    return item.parent_readiness_digest == f"{item.generation:064x}"


def verify_ledger_entry(item):
    return item.signature == f"entry-signature-{item.generation}-{item.strategy_id}"


def build_pipeline():
    trend = Stage186LongitudinalTrendAnalyzer().build(
        snapshots(),
        verify_snapshot=verify_snapshot,
        verify_parent_readiness=verify_parent_readiness,
        sign_report=SIGN,
    )
    evidence = GeneralizationAuditEvidence(
        trend_report_digest=trend.report_digest,
        training_dataset_digest="b" * 64,
        holdout_dataset_digest="c" * 64,
        adversarial_suite_digest="d" * 64,
        training_holdout_disjoint=True,
        holdout_never_used_for_training=True,
        contamination_check_passed=True,
        coverage=.99,
        evaluator_id="holdout-evaluator",
        executor_id="holdout-executor",
        trial_id="holdout-trial",
        signature="holdout-signature",
    )
    audit = Stage187GeneralizationAuditor().build(
        trend, evidence, verify_trend_signature=VERIFY,
        verify_evidence=lambda item: item.signature == "holdout-signature", sign_report=SIGN,
    )
    claim = RegressionClaim(
        "unknown", 2, "lineage-main", "e" * 64,
        "diagnostic-evaluator", "diagnostic-executor", "diagnostic-trial", "claim-signature",
    )
    attribution = Stage188RegressionAttributor().build(
        trend, (claim,), verify_trend_signature=VERIFY,
        verify_claim=lambda item: item.signature == "claim-signature", sign_report=SIGN,
    )
    entries = (
        SurvivalLedgerEntry(2, "lineage-main", "f" * 64, "strategy-a", "survived", "1" * 64,
                            "entry-signature-2-strategy-a"),
        SurvivalLedgerEntry(3, "lineage-main", "2" * 64, "strategy-a", "survived", "3" * 64,
                            "entry-signature-3-strategy-a"),
    )
    ledger = Stage189SurvivalLedger().build(
        previous_ledger_digest=PREVIOUS_DIGEST,
        previous_ledger_signature=SIGN(PREVIOUS_DIGEST),
        previous_generation=1,
        entries=entries,
        verify_previous_ledger=VERIFY,
        verify_entry=verify_ledger_entry,
        sign_report=SIGN,
    )
    return trend, audit, attribution, ledger


def certificate_kwargs():
    return dict(
        verify_trend_signature=VERIFY,
        verify_audit_signature=VERIFY,
        verify_attribution_signature=VERIFY,
        verify_ledger_signature=VERIFY,
        verify_ledger_predecessor=VERIFY,
        verify_ledger_entry=verify_ledger_entry,
        sign_certificate=SIGN,
    )


def test_stages_186_to_190_create_non_authorizing_longitudinal_certificate():
    trend, audit, attribution, ledger = build_pipeline()
    cert = Stage190LongitudinalCertificatePackager().build(
        trend, audit, attribution, ledger, **certificate_kwargs()
    )
    assert cert.first_generation == 1 and cert.last_generation == 3
    assert not cert.ready_for_human_review  # unknown causal attribution is unsupported
    assert cert.certificate_signature == SIGN(cert.certificate_digest)
    assert cert.proposal_only
    assert not cert.weight_mutation_authorized
    assert not cert.generation_advance_authorized
    assert not cert.model_activation_authorized
    assert not cert.production_switch_authorized


def test_stage186_rejects_gaps_replay_forged_signatures_and_bad_parent_lineage():
    rows = snapshots()
    gap = replace(rows[2], generation=4, artifact_candidate_id="artifact-4",
                  parent_candidate_id="artifact-2", parent_readiness_digest="4" * 64,
                  evaluator_id="eval-4", executor_id="exec-4", trial_id="trial-4")
    with pytest.raises(LongitudinalEvolutionError, match="gaps"):
        Stage186LongitudinalTrendAnalyzer().build(
            (rows[0], rows[2], gap), verify_snapshot=verify_snapshot,
            verify_parent_readiness=verify_parent_readiness, sign_report=SIGN
        )
    replay = (rows[0], replace(rows[1], evaluator_id="eval-1", executor_id="exec-1",
                               trial_id="trial-1"), rows[2])
    with pytest.raises(LongitudinalEvolutionError, match="identities"):
        Stage186LongitudinalTrendAnalyzer().build(
            replay, verify_snapshot=verify_snapshot,
            verify_parent_readiness=verify_parent_readiness, sign_report=SIGN
        )
    forged = (replace(rows[0], signature="forged"), *rows[1:])
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage186LongitudinalTrendAnalyzer().build(
            forged, verify_snapshot=verify_snapshot,
            verify_parent_readiness=verify_parent_readiness, sign_report=SIGN
        )
    with pytest.raises(LongitudinalEvolutionError, match="Stage 185"):
        Stage186LongitudinalTrendAnalyzer().build(
            rows, verify_snapshot=verify_snapshot,
            verify_parent_readiness=lambda item: False, sign_report=SIGN
        )


def test_stage186_consumes_untrusted_iterables_with_a_hard_cap():
    def endless():
        while True:
            yield snapshots()[0]

    with pytest.raises(LongitudinalEvolutionError, match="maximum 32"):
        Stage186LongitudinalTrendAnalyzer().build(
            endless(), verify_snapshot=verify_snapshot,
            verify_parent_readiness=verify_parent_readiness, sign_report=SIGN
        )


def test_stage186_records_quality_safety_latency_and_memory_regressions():
    rows = snapshots()
    regressing = (rows[0], rows[1], replace(rows[2], quality=.70, safety=.80,
                                           latency_ms=200, memory_mb=900))
    report = Stage186LongitudinalTrendAnalyzer().build(
        regressing, verify_snapshot=verify_snapshot,
        verify_parent_readiness=verify_parent_readiness, sign_report=SIGN
    )
    assert set(report.regressions) == {
        "safety_floor", "quality_decline", "safety_decline", "latency_growth", "memory_growth"
    }


def test_stage187_rejects_holdout_leakage_low_coverage_and_forged_signatures():
    trend, _, _, _ = build_pipeline()
    leaked = GeneralizationAuditEvidence(
        trend.report_digest, "b" * 64, "b" * 64, "d" * 64, True, True, True, .99,
        "holdout-evaluator", "holdout-executor", "holdout-trial", "holdout-signature"
    )
    kwargs = dict(
        verify_trend_signature=VERIFY,
        verify_evidence=lambda item: item.signature == "holdout-signature",
        sign_report=SIGN,
    )
    with pytest.raises(LongitudinalEvolutionError, match="distinct"):
        Stage187GeneralizationAuditor().build(trend, leaked, **kwargs)
    low = replace(leaked, holdout_dataset_digest="c" * 64, coverage=.5)
    audit = Stage187GeneralizationAuditor().build(trend, low, **kwargs)
    assert not audit.passed
    with pytest.raises(LongitudinalEvolutionError, match="Stage 186 signature"):
        Stage187GeneralizationAuditor().build(
            replace(trend, signature="forged"), low, **{**kwargs, "verify_trend_signature": VERIFY}
        )
    with pytest.raises(LongitudinalEvolutionError, match="evidence signature"):
        Stage187GeneralizationAuditor().build(
            trend, replace(low, signature="forged"), **kwargs
        )


def test_stage188_keeps_unknown_causes_explicit_but_rejects_forged_or_wrong_lineage_claims():
    trend, _, _, _ = build_pipeline()
    unknown = RegressionClaim(
        "unknown", 2, "lineage-main", "e" * 64,
        "diagnostic-evaluator", "diagnostic-executor", "diagnostic-trial", "claim-signature"
    )
    report = Stage188RegressionAttributor().build(
        trend, (unknown,), verify_trend_signature=VERIFY,
        verify_claim=lambda item: item.signature == "claim-signature", sign_report=SIGN
    )
    assert report.unsupported_claim_count == 1
    assert report.supported_categories == ()
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage188RegressionAttributor().build(
            trend, (replace(unknown, signature="forged"),), verify_trend_signature=VERIFY,
            verify_claim=lambda item: item.signature == "claim-signature", sign_report=SIGN
        )
    with pytest.raises(LongitudinalEvolutionError, match="lineage"):
        Stage188RegressionAttributor().build(
            trend, (replace(unknown, candidate_id="other"),), verify_trend_signature=VERIFY,
            verify_claim=lambda item: True, sign_report=SIGN
        )


def test_stage188_bounds_claim_iterables():
    trend, _, _, _ = build_pipeline()

    def endless():
        while True:
            yield RegressionClaim(
                "unknown", 2, "lineage-main", "e" * 64,
                "evaluator", "executor", "trial", "sig"
            )

    with pytest.raises(LongitudinalEvolutionError, match="maximum 64"):
        Stage188RegressionAttributor().build(
            trend, endless(), verify_trend_signature=VERIFY,
            verify_claim=lambda item: True, sign_report=SIGN
        )


def test_stage189_rejects_duplicates_gaps_forged_predecessor_and_entry_signatures():
    entries = (
        SurvivalLedgerEntry(2, "lineage-main", "a" * 64, "s", "survived", "b" * 64,
                            "entry-signature-2-s"),
        SurvivalLedgerEntry(3, "lineage-main", "c" * 64, "s", "survived", "d" * 64,
                            "entry-signature-3-s"),
    )
    kwargs = dict(
        previous_ledger_digest=PREVIOUS_DIGEST,
        previous_ledger_signature=SIGN(PREVIOUS_DIGEST),
        previous_generation=1,
        verify_previous_ledger=VERIFY,
        verify_entry=verify_ledger_entry,
        sign_report=SIGN,
    )
    with pytest.raises(LongitudinalEvolutionError, match="duplicate"):
        Stage189SurvivalLedger().build(entries=(entries[0], entries[0]), **kwargs)
    with pytest.raises(LongitudinalEvolutionError, match="gaps"):
        Stage189SurvivalLedger().build(
            entries=(entries[0], replace(entries[1], generation=4, signature="entry-signature-4-s")),
            **kwargs
        )
    with pytest.raises(LongitudinalEvolutionError, match="bounded append"):
        Stage189SurvivalLedger().build(
            entries=(replace(entries[0], generation=99, signature="entry-signature-99-s"),), **kwargs
        )
    with pytest.raises(LongitudinalEvolutionError, match="previous ledger signature"):
        Stage189SurvivalLedger().build(
            entries=entries, **{**kwargs, "previous_ledger_signature": "forged"}
        )
    with pytest.raises(LongitudinalEvolutionError, match="entry evidence signature"):
        Stage189SurvivalLedger().build(
            entries=(replace(entries[0], signature="forged"), entries[1]), **kwargs
        )


def test_stage189_bounds_entry_iterables():
    def endless():
        while True:
            yield SurvivalLedgerEntry(2, "lineage-main", "a" * 64, "s", "survived",
                                      "b" * 64, "entry-signature-2-s")

    with pytest.raises(LongitudinalEvolutionError, match="maximum 128"):
        Stage189SurvivalLedger().build(
            previous_ledger_digest=PREVIOUS_DIGEST,
            previous_ledger_signature=SIGN(PREVIOUS_DIGEST),
            previous_generation=1,
            entries=endless(),
            verify_previous_ledger=VERIFY,
            verify_entry=verify_ledger_entry,
            sign_report=SIGN,
        )


def resign_ledger(ledger, entries, previous_generation=None):
    payload = {
        "previous": ledger.previous_ledger_digest,
        "previous_signature": ledger.previous_ledger_signature,
        "previous_generation": ledger.previous_generation if previous_generation is None else previous_generation,
        "entries": [entry.__dict__ for entry in entries],
        "proposal_only": ledger.proposal_only,
    }
    import hashlib
    import json
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()
    return replace(
        ledger, previous_generation=payload["previous_generation"],
        entries=entries, ledger_digest=digest, signature=SIGN(digest)
    )


def test_stage190_rejects_failed_audit_tampering_forged_signatures_and_bad_predecessor():
    trend, audit, attribution, ledger = build_pipeline()
    failed_payload = {
        "trend": audit.trend_report_digest, "evidence": audit.audit_evidence_digest,
        "passed": False, "coverage": audit.coverage, "proposal_only": audit.proposal_only,
    }
    import hashlib
    import json
    failed_digest = hashlib.sha256(json.dumps(
        failed_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()
    failed_audit = replace(audit, passed=False, audit_digest=failed_digest,
                           signature=SIGN(failed_digest))
    with pytest.raises(LongitudinalEvolutionError, match="audit failed"):
        Stage190LongitudinalCertificatePackager().build(
            trend, failed_audit, attribution, ledger, **certificate_kwargs()
        )
    with pytest.raises(LongitudinalEvolutionError, match="Stage 189 signature"):
        Stage190LongitudinalCertificatePackager().build(
            trend, audit, attribution, replace(ledger, signature="forged"), **certificate_kwargs()
        )
    with pytest.raises(LongitudinalEvolutionError, match="predecessor signature"):
        Stage190LongitudinalCertificatePackager().build(
            trend, audit, attribution, ledger,
            **{**certificate_kwargs(), "verify_ledger_predecessor": lambda digest, signature: False}
        )
    forged_entry_ledger = resign_ledger(
        ledger, (replace(ledger.entries[0], signature="forged"), ledger.entries[1])
    )
    with pytest.raises(LongitudinalEvolutionError, match="entry signature"):
        Stage190LongitudinalCertificatePackager().build(
            trend, audit, attribution, forged_entry_ledger, **certificate_kwargs()
        )


def test_stage190_rejects_candidate_lineage_generation_gaps_and_non_proposal_reports():
    trend, audit, attribution, ledger = build_pipeline()
    wrong_candidate = resign_ledger(
        ledger, (replace(ledger.entries[0], candidate_id="other"), ledger.entries[1])
    )
    with pytest.raises(LongitudinalEvolutionError, match="candidate lineage"):
        Stage190LongitudinalCertificatePackager().build(
            trend, audit, attribution, wrong_candidate, **certificate_kwargs()
        )
    gap_entries = (
        replace(ledger.entries[0], generation=1, signature="entry-signature-1-strategy-a"),
        ledger.entries[1],
    )
    gap_ledger = resign_ledger(ledger, gap_entries, previous_generation=0)
    with pytest.raises(LongitudinalEvolutionError, match="gaps or is incomplete"):
        Stage190LongitudinalCertificatePackager().build(
            trend, audit, attribution, gap_ledger, **certificate_kwargs()
        )
    with pytest.raises(LongitudinalEvolutionError, match="proposal-only"):
        Stage190LongitudinalCertificatePackager().build(
            trend, replace(audit, proposal_only=False), attribution, ledger, **certificate_kwargs()
        )


@pytest.mark.parametrize("stage", range(186, 191))
def test_hold_blocks_all_longitudinal_stages(stage):
    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="HOLD"):
        if stage == 186:
            Stage186LongitudinalTrendAnalyzer().build(
                snapshots(), verify_snapshot=verify_snapshot,
                verify_parent_readiness=verify_parent_readiness, sign_report=SIGN, hold_active=True
            )
        elif stage == 187:
            Stage187GeneralizationAuditor().build(
                trend,
                GeneralizationAuditEvidence(
                    trend.report_digest, "b" * 64, "c" * 64, "d" * 64,
                    True, True, True, .99, "audit-evaluator", "audit-executor",
                    "audit-trial", "sig"
                ),
                verify_trend_signature=VERIFY, verify_evidence=lambda item: True,
                sign_report=SIGN, hold_active=True
            )
        elif stage == 188:
            Stage188RegressionAttributor().build(
                trend, (), verify_trend_signature=VERIFY,
                verify_claim=lambda item: True, sign_report=SIGN, hold_active=True
            )
        elif stage == 189:
            Stage189SurvivalLedger().build(
                previous_ledger_digest=PREVIOUS_DIGEST,
                previous_ledger_signature=SIGN(PREVIOUS_DIGEST),
                previous_generation=1,
                entries=(ledger.entries[0],),
                verify_previous_ledger=VERIFY, verify_entry=verify_ledger_entry,
                sign_report=SIGN, hold_active=True
            )
        else:
            Stage190LongitudinalCertificatePackager().build(
                trend, audit, attribution, ledger, **{**certificate_kwargs(), "hold_active": True}
            )
