"""Stages 221-225: controlled experiment selection and governance (proposal-only)."""
from __future__ import annotations
from typing import Mapping, Sequence

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,"proposal_only":True,
            "experiment_execution_authorized":False,"model_change_authorized":False,
            "merge_deploy_authorized":False}

def stage221_select_experiment(*, candidates:Sequence[Mapping], held:bool=False):
    if held: return _blocked("HOLD is active")
    if not candidates: return _blocked("no experiment candidates")
    eligible=[]
    for c in candidates:
        if not c.get("evidence_complete") or not c.get("safety_approved"): continue
        if not c.get("experiment_id") or not c.get("objective"): continue
        cost=c.get("estimated_cost")
        value=c.get("expected_information_gain")
        if not isinstance(cost,(int,float)) or not isinstance(value,(int,float)) or cost<=0 or value<0: continue
        eligible.append((value/cost,str(c["experiment_id"])))
    if not eligible: return _blocked("no eligible evidence-backed safe candidates")
    eligible.sort(key=lambda x:(-x[0],x[1]))
    return {"status":"EXPERIMENT_PROPOSAL_READY","recommended_experiment_id":eligible[0][1],
            "ranked_candidates":[{"experiment_id":i,"information_gain_per_cost":s} for s,i in eligible],
            "proposal_only":True,"experiment_execution_authorized":False,"merge_deploy_authorized":False}

def stage222_cost_efficiency(*, observed_gain:float, actual_cost:float, budget:float, held:bool=False):
    if held: return _blocked("HOLD is active")
    if observed_gain<0 or actual_cost<=0 or budget<=0: return _blocked("invalid gain/cost/budget")
    if actual_cost>budget: status="BUDGET_EXCEEDED"
    else: status="COST_EFFICIENCY_READY"
    return {"status":status,"gain_per_cost":observed_gain/actual_cost,
            "budget_utilization":actual_cost/budget,"proposal_only":True,
            "experiment_execution_authorized":False,"merge_deploy_authorized":False}

def stage223_persistence(*, window_results:Sequence[Mapping], required_windows:int=3, held:bool=False):
    if held: return _blocked("HOLD is active")
    if required_windows<2 or len(window_results)<required_windows: return _blocked("insufficient longitudinal windows")
    for r in window_results:
        if not r.get("window_id") or not r.get("evidence_digest") or not r.get("signature_valid"):
            return _blocked("unsigned or incomplete window evidence")
        if not isinstance(r.get("gain"),(int,float)) or not isinstance(r.get("safety_score"),(int,float)):
            return _blocked("missing numeric gain or safety score")
        if not 0<=r["safety_score"]<=1: return _blocked("invalid safety score")
    gains=[r["gain"] for r in window_results]
    safe=all(r["safety_score"]>=.95 for r in window_results)
    persistent=all(g>0 for g in gains)
    return {"status":"PERSISTENT_IMPROVEMENT_SUPPORTED" if safe and persistent else "PERSISTENCE_NOT_SUPPORTED",
            "window_count":len(window_results),"minimum_gain":min(gains),"safety_floor_met":safe,
            "all_windows_positive":persistent,"proposal_only":True,
            "experiment_execution_authorized":False,"merge_deploy_authorized":False}

def stage224_regression(*, baseline:Mapping, current:Mapping, max_quality_drop:float=.01,
                        max_safety_drop:float=.0, held:bool=False):
    if held: return _blocked("HOLD is active")
    for key in ("quality","safety"):
        if key not in baseline or key not in current: return _blocked("missing "+key+" metric")
        if not isinstance(baseline[key],(int,float)) or not isinstance(current[key],(int,float)):
            return _blocked("non-numeric "+key+" metric")
    if max_quality_drop<0 or max_safety_drop<0: return _blocked("negative tolerance")
    qdrop=baseline["quality"]-current["quality"]; sdrop=baseline["safety"]-current["safety"]
    regressions=[]
    if qdrop>max_quality_drop: regressions.append("QUALITY_REGRESSION")
    if sdrop>max_safety_drop: regressions.append("SAFETY_REGRESSION")
    return {"status":"REGRESSION_DETECTED" if regressions else "NO_REGRESSION_DETECTED",
            "regressions":regressions,"quality_drop":qdrop,"safety_drop":sdrop,
            "proposal_only":True,"automatic_rollback_authorized":False,
            "experiment_execution_authorized":False,"merge_deploy_authorized":False}

def stage225_independent_evaluation(*, executor_id:str, evaluator_id:str,
                                    evaluation_digest:str, signature_valid:bool,
                                    rubric_version:str, held:bool=False):
    if held: return _blocked("HOLD is active")
    if not all((executor_id,evaluator_id,evaluation_digest,rubric_version)):
        return _blocked("missing evaluator provenance")
    if executor_id==evaluator_id: return _blocked("executor and evaluator must be distinct identities")
    if not signature_valid: return _blocked("evaluation signature not verified")
    return {"status":"INDEPENDENT_EVALUATION_ATTESTED","executor_id":executor_id,
            "evaluator_id":evaluator_id,"evaluation_digest":evaluation_digest,
            "rubric_version":rubric_version,"proposal_only":True,
            "independence_scope":"identity separation only; organizational and methodological independence unproven",
            "experiment_execution_authorized":False,"model_change_authorized":False,
            "merge_deploy_authorized":False}
