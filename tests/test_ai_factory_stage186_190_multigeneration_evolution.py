from dataclasses import replace
import pytest

from core.ai_factory_stage186_190_multigeneration_evolution import (
    GenerationSnapshot, GeneralizationAuditEvidence, RegressionClaim, SurvivalLedgerEntry,
    LongitudinalEvolutionError, Stage186LongitudinalTrendAnalyzer, Stage187GeneralizationAuditor,
    Stage188RegressionAttributor, Stage189SurvivalLedger, Stage190LongitudinalCertificatePackager,
)

H = "a" * 64
SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == "signed:" + digest


def snapshots():
    return tuple(GenerationSnapshot(g, "candidate-main", str(i)*64, H, f"eval-{g}", f"trial-{g}",
        .90 + (g-1)*.01, .99, 100 - (g-1)*2, 500 - (g-1)*5, f"snapshot-signature-{g}")
        for i, g in enumerate((1, 2, 3), start=1))


def build_pipeline():
    trend = Stage186LongitudinalTrendAnalyzer().build(
        snapshots(), verify_snapshot=lambda x: x.signature.startswith("snapshot-signature-"),
        sign_report=SIGN)
    evidence = GeneralizationAuditEvidence(trend.report_digest, "b"*64, "c"*64, "d"*64,
        True, True, True, .99, "holdout-evaluator", "holdout-signature")
    audit = Stage187GeneralizationAuditor().build(trend, evidence,
        verify_evidence=lambda x: x.signature == "holdout-signature", sign_report=SIGN)
    claims = (RegressionClaim("unknown", 2, "candidate-main", "e"*64, "diagnostic-eval", "claim-signature"),)
    attribution = Stage188RegressionAttributor().build(trend, claims,
        verify_claim=lambda x: x.signature == "claim-signature", sign_report=SIGN)
    entries = (SurvivalLedgerEntry(2, "candidate-main", "f"*64, "strategy-a", "survived", "1"*64),
               SurvivalLedgerEntry(3, "candidate-main", "2"*64, "strategy-a", "survived", "3"*64))
    ledger = Stage189SurvivalLedger().build(previous_ledger_digest="9"*64, previous_generation=1,
        entries=entries, sign_report=SIGN)
    return trend, audit, attribution, ledger


def test_stages_186_to_190_create_review_only_longitudinal_certificate():
    trend, audit, attribution, ledger = build_pipeline()
    cert = Stage190LongitudinalCertificatePackager().build(trend, audit, attribution, ledger,
        verify_trend_signature=VERIFY, verify_audit_signature=VERIFY,
        verify_attribution_signature=VERIFY, verify_ledger_signature=VERIFY)
    assert cert.first_generation == 1 and cert.last_generation == 3
    assert cert.ready_for_human_review
    assert cert.proposal_only
    assert not cert.weight_mutation_authorized
    assert not cert.generation_advance_authorized
    assert not cert.model_activation_authorized
    assert not cert.production_switch_authorized


def test_stage186_rejects_generation_gaps_replay_and_signature_failure():
    rows = snapshots()
    with pytest.raises(LongitudinalEvolutionError, match="gaps"):
        Stage186LongitudinalTrendAnalyzer().build((rows[0], rows[2]),
            verify_snapshot=lambda x: True, sign_report=SIGN)
    with pytest.raises(LongitudinalEvolutionError, match="identities"):
        Stage186LongitudinalTrendAnalyzer().build((rows[0], replace(rows[1], evaluator_id="eval-1")),
            verify_snapshot=lambda x: True, sign_report=SIGN)
    with pytest.raises(LongitudinalEvolutionError, match="signature"):
        Stage186LongitudinalTrendAnalyzer().build(rows,
            verify_snapshot=lambda x: False, sign_report=SIGN)


def test_stage186_records_quality_safety_latency_and_memory_regressions():
    rows = snapshots()
    regressing = (rows[0], rows[1], replace(rows[2], quality=.70, safety=.80, latency_ms=200, memory_mb=900))
    report = Stage186LongitudinalTrendAnalyzer().build(regressing,
        verify_snapshot=lambda x: True, sign_report=SIGN)
    assert set(report.regressions) == {"safety_floor", "quality_decline", "safety_decline",
                                       "latency_growth", "memory_growth"}


def test_stage187_rejects_holdout_leakage_and_insufficient_coverage():
    trend, _, _, _ = build_pipeline()
    leaked = GeneralizationAuditEvidence(trend.report_digest, "b"*64, "b"*64, "d"*64,
        True, True, True, .99, "eval", "sig")
    with pytest.raises(LongitudinalEvolutionError, match="distinct"):
        Stage187GeneralizationAuditor().build(trend, leaked,
            verify_evidence=lambda x: True, sign_report=SIGN)
    low = replace(leaked, holdout_dataset_digest="c"*64, coverage=.5)
    audit = Stage187GeneralizationAuditor().build(trend, low,
        verify_evidence=lambda x: True, sign_report=SIGN)
    assert not audit.passed


def test_stage188_keeps_unsupported_causes_explicit():
    trend, _, _, _ = build_pipeline()
    rows = (RegressionClaim("invented-cause", 2, "candidate-main", "e"*64, "eval", "sig"),)
    report = Stage188RegressionAttributor().build(trend, rows,
        verify_claim=lambda x: True, sign_report=SIGN)
    assert report.unsupported_claim_count == 1
    assert report.supported_categories == ()


def test_stage189_rejects_replay_duplicates_and_unbounded_generation():
    with pytest.raises(LongitudinalEvolutionError, match="duplicate"):
        Stage189SurvivalLedger().build(previous_ledger_digest="9"*64, previous_generation=1,
            entries=(SurvivalLedgerEntry(2, "c", "a"*64, "s", "survived", "b"*64),
                     SurvivalLedgerEntry(2, "c", "a"*64, "s", "survived", "b"*64)), sign_report=SIGN)
    with pytest.raises(LongitudinalEvolutionError, match="bounded append"):
        Stage189SurvivalLedger().build(previous_ledger_digest="9"*64, previous_generation=1,
            entries=(SurvivalLedgerEntry(99, "c", "a"*64, "s", "survived", "b"*64),), sign_report=SIGN)


def test_stage190_rejects_failed_audit_tampering_and_forged_signature():
    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="audit failed"):
        Stage190LongitudinalCertificatePackager().build(trend, replace(audit, passed=False),
            attribution, ledger, verify_trend_signature=VERIFY, verify_audit_signature=VERIFY,
            verify_attribution_signature=VERIFY, verify_ledger_signature=VERIFY)
    with pytest.raises(LongitudinalEvolutionError, match="Stage 189 signature"):
        Stage190LongitudinalCertificatePackager().build(trend, audit, attribution,
            replace(ledger, signature="forged"), verify_trend_signature=VERIFY,
            verify_audit_signature=VERIFY, verify_attribution_signature=VERIFY,
            verify_ledger_signature=VERIFY)


@pytest.mark.parametrize("stage", range(186, 191))
def test_hold_blocks_all_longitudinal_stages(stage):
    rows = snapshots()
    trend, audit, attribution, ledger = build_pipeline()
    with pytest.raises(LongitudinalEvolutionError, match="HOLD"):
        if stage == 186:
            Stage186LongitudinalTrendAnalyzer().build(rows, verify_snapshot=lambda x: True,
                sign_report=SIGN, hold_active=True)
        elif stage == 187:
            Stage187GeneralizationAuditor().build(trend,
                GeneralizationAuditEvidence(trend.report_digest, "b"*64, "c"*64, "d"*64,
                    True, True, True, .99, "eval", "sig"),
                verify_evidence=lambda x: True, sign_report=SIGN, hold_active=True)
        elif stage == 188:
            Stage188RegressionAttributor().build(trend, (), verify_claim=lambda x: True,
                sign_report=SIGN, hold_active=True)
        elif stage == 189:
            Stage189SurvivalLedger().build(previous_ledger_digest="9"*64, previous_generation=1,
                entries=(SurvivalLedgerEntry(2, "c", "a"*64, "s", "survived", "b"*64),),
                sign_report=SIGN, hold_active=True)
        else:
            Stage190LongitudinalCertificatePackager().build(trend, audit, attribution, ledger,
                verify_trend_signature=VERIFY, verify_audit_signature=VERIFY,
                verify_attribution_signature=VERIFY, verify_ledger_signature=VERIFY, hold_active=True)
