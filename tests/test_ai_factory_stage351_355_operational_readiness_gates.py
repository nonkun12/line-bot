from core.ai_factory_stage351_355_operational_readiness_gates import *
D="a"*64
def b(): return stage351_check_baseline_comparability(candidate_protocol_digest=D,baseline_protocol_digest=D,candidate_metric_digest="b"*64,baseline_metric_digest="b"*64)
def u(): return stage352_check_resource_budget(observed_usage={"cpu":2,"memory":4},maximum_budget={"cpu":4,"memory":8},required_resources=["cpu","memory"])
def r(): return stage353_check_rollback_readiness(rollback_artifact_digest=D,restore_test_status="passed",recovery_owner="ops",maximum_recovery_minutes=30,estimated_recovery_minutes=10)
def k(): return stage354_check_operational_risk(risk_register={"availability":{"owner":"ops","mitigation":"fail closed","residual_severity":1,"controls":["monitoring","incident_response","data_protection"]}})
def test_351_baseline_protocol_and_metric_must_match():
 assert b()["status"]=="BASELINE_COMPARABILITY_PASSED"
 assert stage351_check_baseline_comparability(candidate_protocol_digest=D,baseline_protocol_digest="c"*64,candidate_metric_digest="b"*64,baseline_metric_digest="b"*64)["status"]=="BASELINE_COMPARABILITY_FAILED"
def test_352_resource_ceiling():
 assert u()["status"]=="RESOURCE_BUDGET_PASSED"
 assert stage352_check_resource_budget(observed_usage={"cpu":9},maximum_budget={"cpu":4},required_resources=["cpu"])["status"]=="RESOURCE_BUDGET_EXCEEDED"
def test_353_rollback_restore_gate():
 assert r()["status"]=="ROLLBACK_READINESS_PASSED"
 assert stage353_check_rollback_readiness(rollback_artifact_digest=D,restore_test_status="failed",recovery_owner="ops",maximum_recovery_minutes=30,estimated_recovery_minutes=10)["status"]=="ROLLBACK_READINESS_FAILED"
def test_354_risk_controls_and_severity():
 assert k()["status"]=="OPERATIONAL_RISK_PASSED"
 assert stage354_check_operational_risk(risk_register={"x":{"owner":"ops","mitigation":"fix","residual_severity":5,"controls":[]}})["status"]=="OPERATIONAL_RISK_FAILED"
def test_355_sealed_operational_gate_fail_closed():
 out=stage355_integrate_operational_readiness(baseline_result=b(),budget_result=u(),rollback_result=r(),risk_result=k())
 assert out["status"]=="OPERATIONAL_READINESS_PASSED" and out["production_readiness_authorized"] is False
 forged=dict(b()); forged["protocol_match"]=False
 assert stage355_integrate_operational_readiness(baseline_result=forged,budget_result=u(),rollback_result=r(),risk_result=k())["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage355_integrate_operational_readiness(baseline_result=b(),budget_result=u(),rollback_result=r(),risk_result=k(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
