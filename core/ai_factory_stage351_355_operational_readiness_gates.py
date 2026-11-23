"""Stages 351-355: baseline comparability, resource ceilings, rollback and operational readiness."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
import json, math

_FALSE={"proposal_only":True,"task_execution_authorized":False,"experiment_execution_authorized":False,
        "model_change_authorized":False,"merge_deploy_authorized":False,"hold_release_authorized":False}
def _digest(v): return sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def _blocked(reason): return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,**_FALSE}
def _seal(v):
 out={**v,**_FALSE}; out["result_digest"]=_digest(out); return out
def _valid(v,status):
 if not isinstance(v,Mapping) or v.get("status")!=status or any(v.get(k) is not x for k,x in _FALSE.items()): return False
 try: return isinstance(v.get("result_digest"),str) and v["result_digest"]==_digest({k:x for k,x in v.items() if k!="result_digest"})
 except (TypeError,ValueError,OverflowError): return False
def _finite(x): return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)

def stage351_check_baseline_comparability(*, candidate_protocol_digest: str, baseline_protocol_digest: str,
                                          candidate_metric_digest: str, baseline_metric_digest: str, held: bool=False):
 """Require matching declared protocol and metric digests; hashes are not authenticated."""
 if held is not False: return _blocked("HOLD state must be explicitly false")
 vals=(candidate_protocol_digest,baseline_protocol_digest,candidate_metric_digest,baseline_metric_digest)
 if any(not isinstance(x,str) or len(x)!=64 or any(c not in "0123456789abcdef" for c in x) for x in vals):
  return _blocked("four lowercase SHA-256 digests are required")
 protocol_match=candidate_protocol_digest==baseline_protocol_digest
 metric_match=candidate_metric_digest==baseline_metric_digest
 return _seal({"status":"BASELINE_COMPARABILITY_PASSED" if protocol_match and metric_match else "BASELINE_COMPARABILITY_FAILED",
  "protocol_match":protocol_match,"metric_match":metric_match,"digest_authenticity_proven":False})

def stage352_check_resource_budget(*, observed_usage: Mapping, maximum_budget: Mapping, required_resources: list, held: bool=False):
 """Require finite nonnegative observed usage within declared finite nonnegative ceilings."""
 if held is not False: return _blocked("HOLD state must be explicitly false")
 if not isinstance(observed_usage,Mapping) or not isinstance(maximum_budget,Mapping) or not isinstance(required_resources,list) or not required_resources or any(not isinstance(x,str) or not x for x in required_resources) or len(set(required_resources))!=len(required_resources):
  return _blocked("resource budget inputs are malformed")
 ratios={}
 for name in required_resources:
  used=observed_usage.get(name); limit=maximum_budget.get(name)
  if not _finite(used) or not _finite(limit) or used<0 or limit<=0: return _blocked("each resource needs finite usage and positive ceiling")
  ratios[name]=float(used)/float(limit)
 ok=all(x<=1 for x in ratios.values())
 return _seal({"status":"RESOURCE_BUDGET_PASSED" if ok else "RESOURCE_BUDGET_EXCEEDED",
  "usage_to_budget_ratios":dict(sorted(ratios.items())),"resource_metering_authenticated":False})

def stage353_check_rollback_readiness(*, rollback_artifact_digest: str, restore_test_status: str,
                                      recovery_owner: str, maximum_recovery_minutes: float,
                                      estimated_recovery_minutes: float, held: bool=False):
 """Require declared rollback artifact, successful restore test and bounded recovery estimate."""
 if held is not False: return _blocked("HOLD state must be explicitly false")
 if not isinstance(rollback_artifact_digest,str) or len(rollback_artifact_digest)!=64 or any(c not in "0123456789abcdef" for c in rollback_artifact_digest):
  return _blocked("rollback artifact digest is invalid")
 if restore_test_status not in ("passed","failed") or not isinstance(recovery_owner,str) or not recovery_owner.strip() or not _finite(maximum_recovery_minutes) or not _finite(estimated_recovery_minutes) or maximum_recovery_minutes<=0 or estimated_recovery_minutes<0:
  return _blocked("rollback readiness inputs are invalid")
 ok=restore_test_status=="passed" and estimated_recovery_minutes<=maximum_recovery_minutes
 return _seal({"status":"ROLLBACK_READINESS_PASSED" if ok else "ROLLBACK_READINESS_FAILED",
  "rollback_artifact_digest":rollback_artifact_digest,"restore_test_status":restore_test_status,
  "recovery_owner_declared":True,"estimated_recovery_minutes":float(estimated_recovery_minutes),
  "maximum_recovery_minutes":float(maximum_recovery_minutes),"artifact_existence_and_restore_execution_authenticated":False})

def stage354_check_operational_risk(*, risk_register: Mapping, maximum_residual_severity: int=2,
                                    required_controls: list=None, held: bool=False):
 """Require each declared risk to have mitigation, owner, and residual severity within bound."""
 if held is not False: return _blocked("HOLD state must be explicitly false")
 if required_controls is None: required_controls=["monitoring","incident_response","data_protection"]
 if not isinstance(risk_register,Mapping) or not risk_register or not isinstance(required_controls,list) or not required_controls or any(not isinstance(x,str) or not x for x in required_controls) or isinstance(maximum_residual_severity,bool) or not isinstance(maximum_residual_severity,int) or not 0<=maximum_residual_severity<=5:
  return _blocked("risk register or severity bound is invalid")
 rows={}
 for name,row in risk_register.items():
  if not isinstance(name,str) or not name or not isinstance(row,Mapping) or not isinstance(row.get("owner"),str) or not row["owner"].strip() or not isinstance(row.get("mitigation"),str) or not row["mitigation"].strip() or isinstance(row.get("residual_severity"),bool) or not isinstance(row.get("residual_severity"),int) or not 0<=row["residual_severity"]<=5 or not isinstance(row.get("controls"),list):
   return _blocked("each risk needs owner, mitigation, severity and controls")
  rows[name]={"residual_severity":row["residual_severity"],"missing_controls":sorted(set(required_controls)-set(row["controls"]))}
 ok=all(x["residual_severity"]<=maximum_residual_severity and not x["missing_controls"] for x in rows.values())
 return _seal({"status":"OPERATIONAL_RISK_PASSED" if ok else "OPERATIONAL_RISK_FAILED",
  "risk_summary":dict(sorted(rows.items())),"risk_register_completeness_authenticated":False})

def stage355_integrate_operational_readiness(*, baseline_result: Mapping, budget_result: Mapping,
                                             rollback_result: Mapping, risk_result: Mapping, held: bool=False):
 if held is not False: return _blocked("HOLD state must be explicitly false")
 gates=((baseline_result,"BASELINE_COMPARABILITY_PASSED"),(budget_result,"RESOURCE_BUDGET_PASSED"),
        (rollback_result,"ROLLBACK_READINESS_PASSED"),(risk_result,"OPERATIONAL_RISK_PASSED"))
 if not all(_valid(x,s) for x,s in gates): return _blocked("all four sealed operational-readiness gates must pass")
 return _seal({"status":"OPERATIONAL_READINESS_PASSED","evidence_digests":[x["result_digest"] for x,_ in gates],
  "decision_scope":"proposal eligibility for separate review only","baseline_equivalence_proven":False,
  "resource_measurement_authenticated":False,"rollback_execution_proven":False,"risk_completeness_proven":False,
  "production_readiness_authorized":False,"asi_demonstrated":False})
