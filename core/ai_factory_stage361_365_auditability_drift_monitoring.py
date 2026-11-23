"""Stages 361-365: reproducibility declarations, drift bounds, audit continuity and retention checks."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
import json, math

_FLAGS={"proposal_only":True,"task_execution_authorized":False,"experiment_execution_authorized":False,
        "model_change_authorized":False,"merge_deploy_authorized":False,"hold_release_authorized":False}

def _digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,**_FLAGS}

def _seal(value):
    result={**value,**_FLAGS}
    result["result_digest"]=_digest(result)
    return result

def _sealed(value,status):
    if not isinstance(value,Mapping) or value.get("status")!=status:
        return False
    if any(value.get(key) is not flag for key,flag in _FLAGS.items()):
        return False
    try:
        return isinstance(value.get("result_digest"),str) and value["result_digest"]==_digest(
            {key:item for key,item in value.items() if key!="result_digest"})
    except (TypeError,ValueError,OverflowError):
        return False

def _finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)

def stage361_check_reproducibility_declaration(*, required_fields: list, declared_config: Mapping,
                                                held: bool=False):
    """Check presence of required reproducibility fields; declarations are not independently verified."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(required_fields,list) or not required_fields or any(not isinstance(x,str) or not x.strip() for x in required_fields) or len(set(required_fields))!=len(required_fields) or not isinstance(declared_config,Mapping):
        return _blocked("reproducibility declaration inputs are malformed")
    missing=sorted(field for field in required_fields if field not in declared_config or declared_config[field] is None or declared_config[field]=="")
    return _seal({"status":"REPRODUCIBILITY_DECLARATION_PASSED" if not missing else "REPRODUCIBILITY_DECLARATION_INCOMPLETE",
                  "required_field_count":len(required_fields),"missing_fields":missing,
                  "configuration_execution_verified":False})

def stage362_check_metric_drift(*, baseline_metrics: Mapping, current_metrics: Mapping,
                                maximum_absolute_drift: float, required_metrics: list, held: bool=False):
    """Compare finite metric values against an explicit absolute drift ceiling."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(baseline_metrics,Mapping) or not isinstance(current_metrics,Mapping) or not isinstance(required_metrics,list) or not required_metrics or any(not isinstance(x,str) or not x for x in required_metrics) or len(set(required_metrics))!=len(required_metrics) or not _finite(maximum_absolute_drift) or maximum_absolute_drift<0:
        return _blocked("metric drift inputs are malformed")
    deltas={}
    for name in required_metrics:
        before=baseline_metrics.get(name); after=current_metrics.get(name)
        if not _finite(before) or not _finite(after):
            return _blocked("all required metrics need finite baseline and current values")
        deltas[name]=abs(float(after)-float(before))
    ok=all(delta<=maximum_absolute_drift for delta in deltas.values())
    return _seal({"status":"METRIC_DRIFT_WITHIN_BOUND" if ok else "METRIC_DRIFT_EXCEEDED",
                  "absolute_deltas":dict(sorted(deltas.items())),
                  "maximum_absolute_drift":float(maximum_absolute_drift),
                  "metric_semantics_and_measurement_proven":False})

def stage363_check_audit_sequence(*, events: list, required_event_types: list, held: bool=False):
    """Require unique ordered event IDs and declared event-type coverage."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(events,list) or not events or not isinstance(required_event_types,list) or not required_event_types or any(not isinstance(x,str) or not x for x in required_event_types):
        return _blocked("audit sequence inputs are malformed")
    ids=set(); types=set(); previous=-1
    for event in events:
        if not isinstance(event,Mapping):
            return _blocked("each audit event must be a mapping")
        event_id=event.get("event_id"); kind=event.get("event_type"); sequence=event.get("sequence")
        if not isinstance(event_id,str) or not event_id.strip() or event_id in ids or not isinstance(kind,str) or not kind.strip() or isinstance(sequence,bool) or not isinstance(sequence,int) or sequence<=previous:
            return _blocked("event IDs must be unique and sequence numbers strictly increasing")
        ids.add(event_id); types.add(kind); previous=sequence
    missing=sorted(set(required_event_types)-types)
    return _seal({"status":"AUDIT_SEQUENCE_PASSED" if not missing else "AUDIT_SEQUENCE_INCOMPLETE",
                  "event_count":len(events),"missing_event_types":missing,
                  "event_origin_and_completeness_authenticated":False})

def stage364_check_evidence_retention(*, evidence_timestamps: Mapping, retention_seconds: int,
                                     evaluation_timestamp: int, held: bool=False):
    """Check caller-declared evidence timestamps against a deterministic retention window."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(evidence_timestamps,Mapping) or not evidence_timestamps or isinstance(retention_seconds,bool) or not isinstance(retention_seconds,int) or retention_seconds<=0 or isinstance(evaluation_timestamp,bool) or not isinstance(evaluation_timestamp,int):
        return _blocked("retention inputs are malformed")
    ages={}
    for evidence_id,timestamp in evidence_timestamps.items():
        if not isinstance(evidence_id,str) or not evidence_id.strip() or isinstance(timestamp,bool) or not isinstance(timestamp,int) or timestamp<0 or timestamp>evaluation_timestamp:
            return _blocked("evidence timestamps must be valid and not future-dated")
        ages[evidence_id]=evaluation_timestamp-timestamp
    expired=sorted(key for key,age in ages.items() if age>retention_seconds)
    return _seal({"status":"EVIDENCE_RETENTION_PASSED" if not expired else "EVIDENCE_RETENTION_EXPIRED",
                  "evidence_count":len(ages),"expired_evidence_ids":expired,
                  "retention_seconds":retention_seconds,"evaluation_timestamp":evaluation_timestamp,
                  "timestamp_trust_and_storage_retention_authenticated":False})

def stage365_integrate_auditability(*, reproducibility_result: Mapping, drift_result: Mapping,
                                    audit_result: Mapping, retention_result: Mapping, held: bool=False):
    """Require four valid sealed gates; output remains proposal-only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates=((reproducibility_result,"REPRODUCIBILITY_DECLARATION_PASSED"),
           (drift_result,"METRIC_DRIFT_WITHIN_BOUND"),
           (audit_result,"AUDIT_SEQUENCE_PASSED"),
           (retention_result,"EVIDENCE_RETENTION_PASSED"))
    if not all(_sealed(result,status) for result,status in gates):
        return _blocked("all four sealed auditability gates must pass")
    return _seal({"status":"AUDITABILITY_GOVERNANCE_PASSED",
                  "evidence_digests":[result["result_digest"] for result,_ in gates],
                  "decision_scope":"proposal eligibility for separate review only",
                  "reproducibility_proven":False,"drift_measurement_authenticated":False,
                  "audit_log_authenticity_proven":False,"retention_enforcement_proven":False,
                  "task_execution_authorized":False,"production_readiness_authorized":False,
                  "asi_demonstrated":False})
