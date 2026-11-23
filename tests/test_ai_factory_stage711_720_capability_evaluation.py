import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage711_720_capability_evaluation.py"
s=importlib.util.spec_from_file_location("stage711",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def good():
 return {"evaluation_ref":"eval","subject_ref":"subject","candidate_ref":"candidate","baseline_ref":"baseline",
 "protocol":{"protocol_ref":"protocol","version_ref":"v1","environment_ref":"env","command_ref":"cmd","owner_ref":"owner","status":"PASS_DECLARED","frozen":True,"execution_performed":False},
 "metrics":[{"metric_ref":"quality","definition_ref":"definition","unit_ref":"score","baseline_value_ref":"base-value","candidate_value_ref":"candidate-value","acceptance_rule_ref":"rule","evidence_ref":"metric-evidence","direction":"HIGHER_IS_BETTER","status":"PASS_DECLARED","baseline_value":0.7,"candidate_value":0.8,"minimum_improvement":0.05,"maximum_regression":0.02,"measurement_executed":False}],
 "datasets":[{"dataset_ref":"dataset","version_ref":"v1","provenance_ref":"provenance","split_ref":"split","license_ref":"license","status":"PASS_DECLARED","data_accessed":False}],
 "runs":[{"run_ref":"run","input_manifest_ref":"input","output_manifest_ref":"output","environment_ref":"env","result_evidence_ref":"result","status":"PASS_DECLARED","executed":False}],
 "replications":[{"replication_ref":"replication","replicator_ref":"replicator","protocol_ref":"protocol","result_evidence_ref":"replication-result","status":"PASS_DECLARED","replication_executed":False,"replicator_independent":True,"replicator_authenticated":False}],
 "regression_checks":[{"check_ref":"regression","metric_ref":"quality","threshold_ref":"threshold","evidence_ref":"regression-evidence","status":"PASS_DECLARED","check_executed":False}],
 "uncertainty":{"method_ref":"method","interval_ref":"interval","assumptions_ref":"assumptions","evidence_ref":"uncertainty-evidence","status":"PASS_DECLARED","computed":False},
 "independent_assessment":{"assessor_ref":"assessor","decision_ref":"decision","evidence_ref":"assessment-evidence","assessed_at":"2026-11-23T11:00:00Z","decision":"ACCEPT_DECLARED","independent":True,"assessor_authenticated":False},
 "limitations":[{"limitation_ref":"limitation","description_ref":"description","impact_ref":"impact","owner_ref":"owner","disposition":"MITIGATION_PLANNED"}],
 "audit_ref":"audit","created_at":"2026-11-23T11:05:00Z","evaluation_executed":False}

def test_complete_record_is_review_only():
 r=m.stage_720_capability_evaluation_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["capability_improvement_verified"] is False
 assert r["general_intelligence_proven"] is False

def test_missing_and_non_object_block():
 x=good(); del x["baseline_ref"]
 assert "baseline_ref" in m.validate_capability_evaluation(x)["missing"]
 assert m.validate_capability_evaluation(None)["status"]=="BLOCKED"

def test_protocol_must_be_frozen_and_not_executed():
 x=good(); x["protocol"]["frozen"]=False
 assert "protocol_not_frozen" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["protocol"]["execution_performed"]=True
 assert "protocol_execution_must_not_be_claimed" in m.validate_capability_evaluation(x)["issues"]

def test_metric_values_must_be_finite_and_declared():
 x=good(); x["metrics"][0]["candidate_value"]=float("nan")
 assert "metric_candidate_value_invalid" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["metrics"][0]["direction"]="UNKNOWN"
 assert "metric_direction_invalid" in m.validate_capability_evaluation(x)["issues"]

def test_dataset_run_and_replication_fail_closed():
 x=good(); x["datasets"][0]["data_accessed"]=True
 assert "dataset_access_must_not_be_claimed" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["runs"][0]["status"]="INCOMPLETE"
 assert "run_not_pass_declared" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["replications"][0]["replicator_independent"]=False
 assert "independent_replication_required" in m.validate_capability_evaluation(x)["issues"]

def test_regression_and_uncertainty_must_pass_declared():
 x=good(); x["regression_checks"][0]["status"]="FAIL_DECLARED"
 assert "regression_not_pass_declared" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["uncertainty"]["computed"]=True
 assert "uncertainty_computation_must_not_be_claimed" in m.validate_capability_evaluation(x)["issues"]

def test_independent_assessment_and_limitations():
 x=good(); x["independent_assessment"]["decision"]="PENDING"
 assert "independent_assessment_not_accepted" in m.validate_capability_evaluation(x)["issues"]
 x=good(); x["limitations"][0]["disposition"]="BLOCKING"
 assert "blocking_limitation_present" in m.validate_capability_evaluation(x)["issues"]

def test_execution_claims_block():
 x=good(); x["evaluation_executed"]=True
 assert "evaluation_execution_must_not_be_claimed" in m.validate_capability_evaluation(x)["issues"]
