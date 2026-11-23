from core.ai_factory_stage361_365_auditability_drift_monitoring import *

def reproducibility():
    return stage361_check_reproducibility_declaration(
        required_fields=["code_revision","config_digest","dataset_digest"],
        declared_config={"code_revision":"abc","config_digest":"a"*64,"dataset_digest":"b"*64})

def drift():
    return stage362_check_metric_drift(
        baseline_metrics={"accuracy":.9,"latency":100},
        current_metrics={"accuracy":.89,"latency":102},
        maximum_absolute_drift=3,required_metrics=["accuracy","latency"])

def audit():
    return stage363_check_audit_sequence(
        events=[{"event_id":"e1","event_type":"created","sequence":1},
                {"event_id":"e2","event_type":"reviewed","sequence":2}],
        required_event_types=["created","reviewed"])

def retention():
    return stage364_check_evidence_retention(
        evidence_timestamps={"ev1":900,"ev2":950},retention_seconds=200,evaluation_timestamp=1000)

def test_361_reproducibility_required_fields():
    assert reproducibility()["status"]=="REPRODUCIBILITY_DECLARATION_PASSED"
    assert stage361_check_reproducibility_declaration(
        required_fields=["revision","dataset"],declared_config={"revision":"abc"})["status"]=="REPRODUCIBILITY_DECLARATION_INCOMPLETE"

def test_362_metric_drift_bounds():
    assert drift()["status"]=="METRIC_DRIFT_WITHIN_BOUND"
    assert stage362_check_metric_drift(
        baseline_metrics={"score":.5},current_metrics={"score":.9},
        maximum_absolute_drift=.1,required_metrics=["score"])["status"]=="METRIC_DRIFT_EXCEEDED"

def test_363_audit_sequence_order_and_coverage():
    assert audit()["status"]=="AUDIT_SEQUENCE_PASSED"
    assert stage363_check_audit_sequence(
        events=[{"event_id":"e1","event_type":"created","sequence":2},
                {"event_id":"e2","event_type":"reviewed","sequence":1}],
        required_event_types=["created"])["status"]=="INSUFFICIENT_EVIDENCE"

def test_364_retention_expiry_and_future_timestamp():
    assert retention()["status"]=="EVIDENCE_RETENTION_PASSED"
    assert stage364_check_evidence_retention(
        evidence_timestamps={"old":1},retention_seconds=10,evaluation_timestamp=100)["status"]=="EVIDENCE_RETENTION_EXPIRED"
    assert stage364_check_evidence_retention(
        evidence_timestamps={"future":101},retention_seconds=10,evaluation_timestamp=100)["status"]=="INSUFFICIENT_EVIDENCE"

def test_365_integrated_auditability_fail_closed():
    out=stage365_integrate_auditability(reproducibility_result=reproducibility(),
        drift_result=drift(),audit_result=audit(),retention_result=retention())
    assert out["status"]=="AUDITABILITY_GOVERNANCE_PASSED"
    assert out["production_readiness_authorized"] is False
    forged=dict(drift()); forged["absolute_deltas"]={"accuracy":0}
    assert stage365_integrate_auditability(reproducibility_result=reproducibility(),
        drift_result=forged,audit_result=audit(),retention_result=retention())["status"]=="INSUFFICIENT_EVIDENCE"
    assert stage365_integrate_auditability(reproducibility_result=reproducibility(),
        drift_result=drift(),audit_result=audit(),retention_result=retention(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
