import pytest
from core.ai_factory_stage206_210_statistical_rsi_evidence import (
    stage206_paired_estimate, stage207_evaluator_separation, stage208_causal_design,
    stage209_robustness, stage210_rsi_effectiveness,
)

def test_206_positive_paired_signal_and_fail_closed_hold():
    good = stage206_paired_estimate([0.2, .21, .19, .2, .22])
    assert good["positive_gain_supported"] and good["n"] == 5
    assert stage206_paired_estimate([.1]*5, held=True)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage206_paired_estimate([.1]*4)["status"] == "INSUFFICIENT_EVIDENCE"

def test_207_rejects_role_overlap_and_accepts_separate_signers():
    shared = [{"role":"executor","signer_id":"x","signature_valid":True,"artifact_digest":"a","suite_digest":"s"},
               {"role":"evaluator","signer_id":"x","signature_valid":True,"artifact_digest":"a","suite_digest":"s"}]
    assert stage207_evaluator_separation(shared)["status"] == "INSUFFICIENT_EVIDENCE"
    split = [dict(shared[0], signer_id="exec"), dict(shared[1], signer_id="eval")]
    result = stage207_evaluator_separation(split)
    assert result["status"] == "ROLE_SEPARATION_ATTESTED"
    assert result["independence_verified"] is False

def test_208_requires_predeclared_design_and_does_not_claim_causality():
    assert stage208_causal_design([0,0], [.1,.2])["status"] == "INSUFFICIENT_EVIDENCE"
    r = stage208_causal_design([0,0], [.1,.2], randomized=True)
    assert r["difference_in_means"] == pytest.approx(.15)
    assert r["causal_claim_authorized"] is False

def test_209_requires_all_strata_and_safety():
    assert stage209_robustness({"A":.1}, required_strata=["A","B"], safety_by_stratum={"A":.99})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage209_robustness({"A":.1,"B":.2}, required_strata=["A","B"], safety_by_stratum={"A":.99,"B":.98})["status"] == "ROBUSTNESS_SUPPORTED"
    assert stage209_robustness({"A":.1,"B":.2}, required_strata=["A","B"], safety_by_stratum={"A":.99,"B":.8})["status"] == "ROBUSTNESS_NOT_SUPPORTED"

def test_210_requires_all_rsi_gates_and_never_claims_asi():
    r = stage210_rsi_effectiveness(lower_gain_bound=.05, safety_min=.99,
        reproducibility=.95, evaluation_cost_ratio=1, robustness_supported=True)
    assert r["rsi_claim_supported"] and not r["asi_claim_supported"]
    blocked = stage210_rsi_effectiveness(lower_gain_bound=.05, safety_min=.99,
        reproducibility=.95, evaluation_cost_ratio=1, robustness_supported=True, held=True)
    assert blocked["status"] == "INSUFFICIENT_EVIDENCE"
    assert blocked["merge_deploy_authorized"] is False
