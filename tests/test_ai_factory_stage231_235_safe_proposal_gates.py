from core.ai_factory_stage231_235_safe_proposal_gates import *


def test_231_freshness_requires_aware_nonfuture_timestamps():
    evidence = [{"evidence_id": "e1", "observed_at": "2026-11-23T10:00:00+09:00"}]
    assert stage231_evidence_freshness(evidence=evidence, evaluated_at="2026-11-23T10:05:00+09:00", max_age_seconds=600)["status"] == "EVIDENCE_FRESH"
    assert stage231_evidence_freshness(evidence=evidence, evaluated_at="2026-11-23T10:20:00+09:00", max_age_seconds=600)["status"] == "EVIDENCE_STALE"
    assert stage231_evidence_freshness(evidence=[{"evidence_id": "e", "observed_at": "2026-11-23T11:00:00"}], evaluated_at="2026-11-23T10:00:00+09:00", max_age_seconds=60)["status"] == "INSUFFICIENT_EVIDENCE"


def test_232_requires_exact_manifest_and_external_signature_confirmation():
    manifest = {"suite": "abc", "dataset": "def"}
    assert stage232_revalidate_evidence(expected_digests=manifest, actual_digests=dict(manifest), signature_verified=True)["status"] == "EVIDENCE_REVALIDATED"
    assert stage232_revalidate_evidence(expected_digests=manifest, actual_digests={"suite": "abc"}, signature_verified=True)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage232_revalidate_evidence(expected_digests=manifest, actual_digests=dict(manifest), signature_verified=False)["status"] == "INSUFFICIENT_EVIDENCE"


def test_233_requires_all_restrictive_policy_controls():
    policy = {"safety_gate": True, "approval_required": True, "auto_execute": False,
              "auto_train": False, "auto_model_mutation": False, "auto_merge": False,
              "auto_deploy": False, "hold_release_allowed": False}
    assert stage233_validate_safety_policy(policy=policy)["status"] == "RESTRICTIVE_SAFETY_POLICY_VALID"
    assert stage233_validate_safety_policy(policy={**policy, "auto_deploy": True})["status"] == "INSUFFICIENT_EVIDENCE"


def test_234_deduplicates_stably_and_rejects_incomplete_identity():
    items = [{"category": "quality", "proposed_action": "inspect slices", "target": "suite-a"},
             {"category": " QUALITY ", "proposed_action": "INSPECT SLICES", "target": "SUITE-A"}]
    result = stage234_deduplicate_candidates(candidates=items)
    assert result["unique_count"] == 1
    assert result["input_count"] == 2
    assert stage234_deduplicate_candidates(candidates=[{"category": "quality"}])["status"] == "INSUFFICIENT_EVIDENCE"


def test_235_only_prepares_review_and_never_authorizes_execution():
    freshness = {"status": "EVIDENCE_FRESH"}
    revalidation = {"status": "EVIDENCE_REVALIDATED"}
    safety = {"status": "RESTRICTIVE_SAFETY_POLICY_VALID"}
    dedupe = {"status": "CANDIDATES_DEDUPLICATED", "unique_candidates": [{"proposal_fingerprint": "f"}]}
    result = stage235_prepare_review_gate(freshness=freshness, revalidation=revalidation, safety=safety, deduplication=dedupe)
    assert result["status"] == "READY_FOR_SEPARATE_HUMAN_REVIEW"
    assert result["task_execution_authorized"] is False
    assert result["experiment_execution_authorized"] is False
    assert result["model_change_authorized"] is False
    assert result["merge_deploy_authorized"] is False
    assert stage235_prepare_review_gate(freshness=freshness, revalidation=revalidation, safety=safety, deduplication=dedupe, held=True)["status"] == "INSUFFICIENT_EVIDENCE"
