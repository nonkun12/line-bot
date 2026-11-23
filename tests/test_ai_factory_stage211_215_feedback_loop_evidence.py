from core.ai_factory_stage211_215_feedback_loop_evidence import (
 stage211_linked_outcome,stage212_outcome_classification,stage213_reproducibility,
 stage214_feedback_summary,stage215_feedback_gate)
def test_211_linkage_fail_closed():
 assert stage211_linked_outcome(proposal_id="p",baseline_digest="a",target_digest="b",evaluation_digest="e",outcome_digest="o",signatures_verified=True)["status"]=="OUTCOME_LINKAGE_READY"
 assert stage211_linked_outcome(proposal_id="p",baseline_digest="a",target_digest="a",evaluation_digest="e",outcome_digest="o",signatures_verified=True)["status"]=="INSUFFICIENT_EVIDENCE"
def test_212_classification_and_hold():
 assert stage212_outcome_classification(expected_success=True,observed_success=False,safety_regression=False,evidence_complete=True)["status"]=="EXPECTED_SUCCESS_NOT_OBSERVED"
 assert stage212_outcome_classification(expected_success=True,observed_success=True,safety_regression=True,evidence_complete=True)["status"]=="SAFETY_REGRESSION"
 assert stage212_outcome_classification(expected_success=True,observed_success=True,safety_regression=False,evidence_complete=False)["status"]=="INSUFFICIENT_EVIDENCE"
def test_213_repro_runs():
 runs=[{"signature_valid":True,"outcome_digest":"o","environment_digest":"e"} for _ in range(3)]
 assert stage213_reproducibility(runs=runs)["status"]=="REPRODUCIBLE"
 assert stage213_reproducibility(runs=runs[:2])["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage213_reproducibility(runs=[dict(runs[0],outcome_digest="x"),*runs[1:]])["status"]=="NON_REPRODUCIBLE"
def test_214_summary():
 r=stage214_feedback_summary(classifications=["SUCCESS_CONFIRMED","EXPECTED_FAILURE_CONFIRMED"],safety_regression_count=0,total=2)
 assert r["confirmed_success_rate"]==.5 and r["causal_improvement_claim_authorized"] is False
def test_215_gate():
 assert stage215_feedback_gate(linkage_ready=True,reproducible=True,success_rate=.9,safety_regression_count=0)["feedback_evidence_supported"]
 assert not stage215_feedback_gate(linkage_ready=True,reproducible=True,success_rate=.9,safety_regression_count=1)["feedback_evidence_supported"]
 assert stage215_feedback_gate(linkage_ready=True,reproducible=True,success_rate=.9,safety_regression_count=0,held=True)["status"]=="INSUFFICIENT_EVIDENCE"
