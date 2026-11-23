"""Stages 346-350: perturbation robustness, missingness, uncertainty and metric integrity."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
import json, math

_FALSE={"proposal_only":True,"task_execution_authorized":False,"experiment_execution_authorized":False,
        "model_change_authorized":False,"merge_deploy_authorized":False,"hold_release_authorized":False}

def _digest(v):
    return sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def _blocked(reason): return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,**_FALSE}
def _seal(v):
    out={**v,**_FALSE}; out["result_digest"]=_digest(out); return out
def _valid(v,status):
    if not isinstance(v,Mapping) or v.get("status")!=status or any(v.get(k) is not x for k,x in _FALSE.items()): return False
    try: return isinstance(v.get("result_digest"),str) and v["result_digest"]==_digest({k:x for k,x in v.items() if k!="result_digest"})
    except (TypeError,ValueError,OverflowError): return False
def _finite(x): return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)

def stage346_check_perturbation_robustness(*, reference_scores: Mapping, perturbed_scores: Mapping,
                                           maximum_absolute_change: float=.1, minimum_shared_cases: int=3, held: bool=False):
    """Compare caller-provided paired scores under declared perturbation; no perturbation execution occurs."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if not isinstance(reference_scores,Mapping) or not isinstance(perturbed_scores,Mapping) or not _finite(maximum_absolute_change) or maximum_absolute_change<0 or isinstance(minimum_shared_cases,bool) or not isinstance(minimum_shared_cases,int) or minimum_shared_cases<1:
        return _blocked("robustness inputs or thresholds are invalid")
    if set(reference_scores)!=set(perturbed_scores) or len(reference_scores)<minimum_shared_cases:
        return _blocked("paired case IDs must match and meet minimum count")
    changes={}
    for k,v in reference_scores.items():
        w=perturbed_scores[k]
        if not isinstance(k,str) or not k or not _finite(v) or not _finite(w): return _blocked("case IDs and scores must be finite")
        changes[k]=float(w)-float(v)
    worst=max(abs(x) for x in changes.values())
    return _seal({"status":"PERTURBATION_ROBUSTNESS_PASSED" if worst<=maximum_absolute_change else "PERTURBATION_ROBUSTNESS_FAILED",
                  "case_count":len(changes),"score_changes":dict(sorted(changes.items())),
                  "maximum_absolute_change":worst,"allowed_absolute_change":float(maximum_absolute_change),
                  "perturbations_executed_or_authenticated":False})

def stage347_check_missingness_bounds(*, expected_count: int, observed_count: int, maximum_missing_share: float=.05, held: bool=False):
    """Bound declared missing evidence without assuming missing-at-random."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if any(isinstance(x,bool) or not isinstance(x,int) for x in (expected_count,observed_count)) or expected_count<1 or not 0<=observed_count<=expected_count or not _finite(maximum_missing_share) or not 0<=maximum_missing_share<=1:
        return _blocked("missingness counts or threshold are invalid")
    missing=expected_count-observed_count; share=missing/expected_count
    return _seal({"status":"MISSINGNESS_BOUND_PASSED" if share<=maximum_missing_share else "MISSINGNESS_BOUND_FAILED",
                  "expected_count":expected_count,"observed_count":observed_count,"missing_count":missing,
                  "missing_share":share,"maximum_missing_share":float(maximum_missing_share),
                  "missingness_mechanism_authenticated":False})

def stage348_check_uncertainty_interval(*, lower_bound: float, upper_bound: float, minimum_precision: float=.8, held: bool=False):
    """Require finite ordered interval and minimum declared precision (1 - width)."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if not _finite(lower_bound) or not _finite(upper_bound) or lower_bound>upper_bound or not _finite(minimum_precision) or not 0<=minimum_precision<=1:
        return _blocked("uncertainty interval or precision threshold is invalid")
    width=upper_bound-lower_bound; precision=1.0-width
    ok=width<=1.0-minimum_precision
    return _seal({"status":"UNCERTAINTY_INTERVAL_PASSED" if ok else "UNCERTAINTY_INTERVAL_TOO_WIDE",
                  "lower_bound":float(lower_bound),"upper_bound":float(upper_bound),"interval_width":width,
                  "declared_precision":precision,"minimum_precision":float(minimum_precision),
                  "coverage_and_interval_method_authenticated":False})

def stage349_check_metric_contract(*, declared_metrics: Mapping, observed_metrics: Mapping, required_metrics: list, held: bool=False):
    """Require exact metric keys, direction and unit contract; values are not recalculated."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if not isinstance(declared_metrics,Mapping) or not isinstance(observed_metrics,Mapping) or not isinstance(required_metrics,list) or not required_metrics or any(not isinstance(x,str) or not x for x in required_metrics) or len(set(required_metrics))!=len(required_metrics):
        return _blocked("metric contract inputs are malformed")
    for k in required_metrics:
        for source in (declared_metrics,observed_metrics):
            row=source.get(k)
            if not isinstance(row,Mapping) or set(row)!={"direction","unit"} or row["direction"] not in ("higher_is_better","lower_is_better") or not isinstance(row["unit"],str) or not row["unit"]:
                return _blocked("each required metric needs a valid direction and unit")
    matches={k:declared_metrics[k]==observed_metrics[k] for k in required_metrics}
    ok=all(matches.values())
    return _seal({"status":"METRIC_CONTRACT_MATCHED" if ok else "METRIC_CONTRACT_MISMATCH",
                  "required_metrics":sorted(required_metrics),"matches":matches,
                  "metric_semantics_independently_verified":False})

def stage350_integrate_robustness_uncertainty(*, robustness_result: Mapping, missingness_result: Mapping,
                                               uncertainty_result: Mapping, metric_result: Mapping, held: bool=False):
    if held is not False: return _blocked("HOLD state must be explicitly false")
    gates=((robustness_result,"PERTURBATION_ROBUSTNESS_PASSED"),(missingness_result,"MISSINGNESS_BOUND_PASSED"),
           (uncertainty_result,"UNCERTAINTY_INTERVAL_PASSED"),(metric_result,"METRIC_CONTRACT_MATCHED"))
    if not all(_valid(x,s) for x,s in gates): return _blocked("all four sealed robustness/uncertainty gates must pass")
    return _seal({"status":"ROBUSTNESS_UNCERTAINTY_GATE_PASSED","evidence_digests":[x["result_digest"] for x,_ in gates],
                  "decision_scope":"proposal eligibility for separate review only","statistical_validity_proven":False,
                  "missingness_bias_absent_proven":False,"metric_semantics_authenticated":False,"asi_demonstrated":False})
