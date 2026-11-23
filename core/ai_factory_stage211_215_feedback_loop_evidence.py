"""Stages 211-215: evidence-linked feedback loop outcome validators (proposal-only)."""
from __future__ import annotations
from typing import Mapping, Sequence

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,"proposal_only":True,
            "feedback_mutation_authorized":False,"model_activation_authorized":False,
            "merge_deploy_authorized":False}

def stage211_linked_outcome(*, proposal_id:str, baseline_digest:str, target_digest:str,
                            evaluation_digest:str, outcome_digest:str, signatures_verified:bool,
                            held:bool=False):
    if held: return _blocked("HOLD is active")
    if not all([proposal_id,baseline_digest,target_digest,evaluation_digest,outcome_digest]):
        return _blocked("missing evidence linkage")
    if baseline_digest==target_digest: return _blocked("baseline and target artifact must differ")
    if not signatures_verified: return _blocked("signature verification not confirmed")
    return {"status":"OUTCOME_LINKAGE_READY","proposal_id":proposal_id,
            "baseline_digest":baseline_digest,"target_digest":target_digest,
            "evaluation_digest":evaluation_digest,"outcome_digest":outcome_digest,
            "proposal_only":True,"feedback_mutation_authorized":False,
            "model_activation_authorized":False,"merge_deploy_authorized":False}

def stage212_outcome_classification(*, expected_success:bool, observed_success:bool,
                                   safety_regression:bool, evidence_complete:bool, held:bool=False):
    if held: return _blocked("HOLD is active")
    if not evidence_complete: return _blocked("outcome evidence incomplete")
    if safety_regression: status="SAFETY_REGRESSION"
    elif expected_success and observed_success: status="SUCCESS_CONFIRMED"
    elif expected_success and not observed_success: status="EXPECTED_SUCCESS_NOT_OBSERVED"
    elif not expected_success and observed_success: status="UNEXPECTED_SUCCESS"
    else: status="EXPECTED_FAILURE_CONFIRMED"
    return {"status":status,"proposal_only":True,"feedback_mutation_authorized":False,
            "merge_deploy_authorized":False}

def stage213_reproducibility(*, runs:Sequence[Mapping], required:int=3, held:bool=False):
    if held: return _blocked("HOLD is active")
    if required<2 or len(runs)<required: return _blocked("insufficient repeated outcome runs")
    for r in runs:
        if not r.get("signature_valid") or not r.get("outcome_digest") or not r.get("environment_digest"):
            return _blocked("unsigned or incomplete repeat-run evidence")
    outcomes={r["outcome_digest"] for r in runs}
    envs={r["environment_digest"] for r in runs}
    reproducible=(len(outcomes)==1 and len(envs)==1)
    return {"status":"REPRODUCIBLE" if reproducible else "NON_REPRODUCIBLE",
            "run_count":len(runs),"outcome_variants":len(outcomes),"environment_variants":len(envs),
            "proposal_only":True,"feedback_mutation_authorized":False,"merge_deploy_authorized":False}

def stage214_feedback_summary(*, classifications:Sequence[str], safety_regression_count:int,
                              total:int, held:bool=False):
    if held: return _blocked("HOLD is active")
    if total<=0 or len(classifications)!=total: return _blocked("count mismatch or empty dataset")
    valid={"SUCCESS_CONFIRMED","EXPECTED_SUCCESS_NOT_OBSERVED","UNEXPECTED_SUCCESS","EXPECTED_FAILURE_CONFIRMED","SAFETY_REGRESSION"}
    if any(c not in valid for c in classifications): return _blocked("unknown classification")
    successes=classifications.count("SUCCESS_CONFIRMED")
    observed=successes/total
    return {"status":"SUMMARY_READY","sample_count":total,"confirmed_success_count":successes,
            "confirmed_success_rate":observed,"safety_regression_count":safety_regression_count,
            "proposal_only":True,"causal_improvement_claim_authorized":False,
            "feedback_mutation_authorized":False,"merge_deploy_authorized":False}

def stage215_feedback_gate(*, linkage_ready:bool, reproducible:bool, success_rate:float,
                          safety_regression_count:int, minimum_success_rate:float=.80, held:bool=False):
    if held: return _blocked("HOLD is active")
    checks={"linked_evidence":bool(linkage_ready),"repeatable":bool(reproducible),
            "success_rate":float(success_rate)>=minimum_success_rate,"no_safety_regressions":safety_regression_count==0}
    passed=all(checks.values())
    return {"status":"FEEDBACK_EVIDENCE_SUPPORTED" if passed else "FEEDBACK_NOT_SUPPORTED",
            "checks":checks,"feedback_evidence_supported":passed,"proposal_only":True,
            "feedback_mutation_authorized":False,"model_activation_authorized":False,
            "merge_deploy_authorized":False}
