import math
from core.ai_factory_stage226_230_longitudinal_learning_evidence import *


def test_226_validates_chain_and_rejects_replay_or_hold():
    events = [
        {"sequence": 1, "event_id": "e1", "event_digest": "d1", "previous_digest": "GENESIS", "signature_valid": True},
        {"sequence": 2, "event_id": "e2", "event_digest": "d2", "previous_digest": "d1", "signature_valid": True},
    ]
    assert stage226_longitudinal_ledger(events=events)["status"] == "LONGITUDINAL_LEDGER_STRUCTURALLY_VALID"
    assert stage226_longitudinal_ledger(events=[events[0], events[0]])["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage226_longitudinal_ledger(events=events, held=True)["status"] == "INSUFFICIENT_EVIDENCE"


def test_227_requires_known_failure_classes():
    assert stage227_failure_classification(outcomes=[{"failure_reason": "DATA_GAP"}])["failure_counts"]["DATA_GAP"] == 1
    assert stage227_failure_classification(outcomes=[{"failure_reason": "invented"}])["status"] == "INSUFFICIENT_EVIDENCE"


def test_228_compares_only_comparable_finite_hypotheses():
    base = {"suite_id": "s", "dataset_id": "d", "environment_id": "e", "design_id": "r"}
    hs = [dict(base, hypothesis_id="a", gain_lower_bound=.02, safety_score=.97, cost_ratio=1.0),
          dict(base, hypothesis_id="b", gain_lower_bound=.03, safety_score=.90, cost_ratio=1.0)]
    assert stage228_compare_hypotheses(hypotheses=hs)["recommended_hypothesis_id"] == "a"
    assert stage228_compare_hypotheses(hypotheses=[hs[0], dict(hs[1], dataset_id="other")])["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage228_compare_hypotheses(hypotheses=[dict(hs[0], gain_lower_bound=math.nan), hs[1]])["status"] == "INSUFFICIENT_EVIDENCE"


def test_229_flags_coverage_and_rate_imbalance():
    strata = [{"stratum_id": "x", "evaluation_rate": .9, "coverage": .95},
              {"stratum_id": "y", "evaluation_rate": .5, "coverage": .7}]
    result = stage229_evaluation_bias_risk(strata=strata)
    assert result["status"] == "EVALUATION_BIAS_RISK"
    assert set(result["risk_flags"]) == {"UNEQUAL_EVALUATION_RATE", "LOW_STRATUM_COVERAGE"}


def test_230_generates_suggestions_without_authority():
    profile = {"failure_counts": {"DATA_GAP": 2, "SAFETY_REGRESSION": 1}}
    bias = {"status": "EVALUATION_BIAS_RISK", "risk_flags": ["LOW_STRATUM_COVERAGE"]}
    result = stage230_generate_improvement_candidates(failure_profile=profile, bias_assessment=bias)
    assert result["status"] == "IMPROVEMENT_PROPOSALS_READY"
    assert result["task_execution_authorized"] is False
    assert result["model_change_authorized"] is False
    assert stage230_generate_improvement_candidates(failure_profile=profile, bias_assessment=bias, held=True)["status"] == "INSUFFICIENT_EVIDENCE"
