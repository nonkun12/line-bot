"""Stages 216-220: aggregate evidence quality, uncertainty, coverage and priority (proposal-only)."""
from __future__ import annotations
from math import sqrt
from typing import Mapping, Sequence

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,"proposal_only":True,
            "task_execution_authorized":False,"feedback_mutation_authorized":False,
            "model_activation_authorized":False,"merge_deploy_authorized":False}

def stage216_integrity(*, total:int, success_count:int, safety_regression_count:int,
                       classifications:Sequence[str], held:bool=False):
    if held: return _blocked("HOLD is active")
    if total<=0 or len(classifications)!=total: return _blocked("total/classification mismatch")
    allowed={"SUCCESS_CONFIRMED","EXPECTED_SUCCESS_NOT_OBSERVED","UNEXPECTED_SUCCESS",
             "EXPECTED_FAILURE_CONFIRMED","SAFETY_REGRESSION"}
    if any(x not in allowed for x in classifications): return _blocked("unknown classification")
    actual_success=classifications.count("SUCCESS_CONFIRMED")
    actual_safety=classifications.count("SAFETY_REGRESSION")
    if success_count!=actual_success or safety_regression_count!=actual_safety:
        return _blocked("aggregate counts do not match raw classifications")
    return {"status":"AGGREGATE_INTEGRITY_VALID","total":total,"success_count":actual_success,
            "safety_regression_count":actual_safety,"proposal_only":True,
            "task_execution_authorized":False,"merge_deploy_authorized":False}

def stage217_wilson_interval(*, successes:int, total:int, z:float=1.96, held:bool=False):
    if held: return _blocked("HOLD is active")
    if total<1 or successes<0 or successes>total or z<=0: return _blocked("invalid sample or parameters")
    p=successes/total; z2=z*z; denom=1+z2/total
    center=(p+z2/(2*total))/denom
    margin=z*sqrt((p*(1-p)+z2/(4*total))/total)/denom
    return {"status":"UNCERTAINTY_ESTIMATE_READY","success_rate":p,
            "wilson_95_lower":max(0.0,center-margin),"wilson_95_upper":min(1.0,center+margin),
            "interval":"Wilson score; nominal 95% for z=1.96","proposal_only":True,
            "task_execution_authorized":False,"merge_deploy_authorized":False}

def stage218_coverage(*, required_strata:Sequence[str], observed_strata:Mapping[str,int], held:bool=False):
    if held: return _blocked("HOLD is active")
    if not required_strata or any(not s for s in required_strata): return _blocked("required strata missing")
    if any(v<0 for v in observed_strata.values()): return _blocked("negative stratum count")
    missing=[s for s in required_strata if observed_strata.get(s,0)==0]
    unexpected=[s for s in observed_strata if s not in required_strata]
    covered=len(required_strata)-len(missing)
    return {"status":"COVERAGE_COMPLETE" if not missing else "COVERAGE_GAPS",
            "required_count":len(required_strata),"covered_count":covered,
            "coverage_rate":covered/len(required_strata),"missing_strata":missing,
            "unexpected_strata":unexpected,"proposal_only":True,
            "task_execution_authorized":False,"merge_deploy_authorized":False}

def stage219_risk_adjusted_score(*, success_rate:float, safety_regressions:int,
                                 coverage_rate:float, uncertainty_width:float, held:bool=False):
    if held: return _blocked("HOLD is active")
    vals=(success_rate,coverage_rate,uncertainty_width)
    if any(not 0<=v<=1 for v in vals) or safety_regressions<0: return _blocked("invalid score inputs")
    # Conservative heuristic only; explicitly not an inferential or causal metric.
    score=max(0.0,min(1.0,success_rate*coverage_rate*(1-uncertainty_width)/(1+safety_regressions)))
    return {"status":"HEURISTIC_SCORE_READY","score":score,"formula":"success_rate * coverage_rate * (1 - uncertainty_width) / (1 + safety_regressions)",
            "interpretation":"heuristic ranking only; not proof of capability or causality",
            "proposal_only":True,"task_execution_authorized":False,"merge_deploy_authorized":False}

def stage220_next_step(*, integrity_valid:bool, lower_bound:float, coverage_rate:float,
                       safety_regressions:int, minimum_lower_bound:float=0.0,
                       minimum_coverage:float=1.0, held:bool=False):
    if held: return _blocked("HOLD is active")
    if any(not 0<=x<=1 for x in (lower_bound,coverage_rate,minimum_lower_bound,minimum_coverage)) or safety_regressions<0:
        return _blocked("invalid gate values")
    checks={"aggregate_integrity":bool(integrity_valid),"positive_confidence_lower_bound":lower_bound>minimum_lower_bound,
            "coverage_sufficient":coverage_rate>=minimum_coverage,"no_safety_regressions":safety_regressions==0}
    if not checks["aggregate_integrity"]: action="REPAIR_EVIDENCE_INTEGRITY"
    elif not checks["coverage_sufficient"]: action="COLLECT_MISSING_STRATA"
    elif not checks["no_safety_regressions"]: action="INVESTIGATE_SAFETY_REGRESSIONS"
    elif not checks["positive_confidence_lower_bound"]: action="COLLECT_MORE_POWERED_EVALUATIONS"
    else: action="PROPOSE_NEXT_CONTROLLED_EVALUATION"
    return {"status":"NEXT_STEP_RECOMMENDATION","checks":checks,"recommended_action":action,
            "proposal_only":True,"task_execution_authorized":False,
            "feedback_mutation_authorized":False,"model_activation_authorized":False,
            "merge_deploy_authorized":False}
