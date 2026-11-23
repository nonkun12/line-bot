"""Stages 341-345: replication, leakage, regression and evidence-diversity gates."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
from statistics import mean
import json
import math

_FALSE={"proposal_only":True,"task_execution_authorized":False,"experiment_execution_authorized":False,
        "model_change_authorized":False,"merge_deploy_authorized":False,"hold_release_authorized":False}

def _digest(v):
    return sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,**_FALSE}

def _seal(v):
    out={**v,**_FALSE}; out["result_digest"]=_digest(out); return out

def _valid(v,status):
    if not isinstance(v,Mapping) or v.get("status")!=status or any(v.get(k) is not x for k,x in _FALSE.items()): return False
    try:
        d=v.get("result_digest")
        return isinstance(d,str) and len(d)==64 and d==_digest({k:x for k,x in v.items() if k!="result_digest"})
    except (TypeError,ValueError,OverflowError): return False

def _finite(x):
    return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)


def stage341_check_replication_consistency(*, replication_gains: Mapping,
                                           minimum_replicates: int=3,
                                           maximum_gain_spread: float=.2,
                                           minimum_mean_gain: float=0.0, held: bool=False):
    """Require multiple declared replication results with bounded spread and positive mean."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(replication_gains,Mapping) or isinstance(minimum_replicates,bool)
        or not isinstance(minimum_replicates,int) or minimum_replicates<2
        or len(replication_gains)<minimum_replicates or not _finite(maximum_gain_spread)
        or maximum_gain_spread<0 or not _finite(minimum_mean_gain)):
        return _blocked("replication inputs or thresholds are invalid")
    vals={}
    for k,v in replication_gains.items():
        if not isinstance(k,str) or not k or not _finite(v): return _blocked("replication IDs and gains must be finite")
        vals[k]=float(v)
    spread=max(vals.values())-min(vals.values()); avg=mean(vals.values())
    ok=spread<=maximum_gain_spread and avg>minimum_mean_gain
    return _seal({"status":"REPLICATION_CONSISTENCY_PASSED" if ok else "REPLICATION_CONSISTENCY_FAILED",
                  "replicate_count":len(vals),"mean_gain":avg,"gain_spread":spread,
                  "maximum_gain_spread":float(maximum_gain_spread),"minimum_mean_gain":float(minimum_mean_gain),
                  "replication_independence_authenticated":False})


def stage342_check_benchmark_partition_overlap(*, training_task_ids, evaluation_task_ids,
                                               holdout_task_ids, held: bool=False):
    """Require pairwise-disjoint, nonempty task-ID partitions."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    sets=[]
    for raw in (training_task_ids,evaluation_task_ids,holdout_task_ids):
        if not isinstance(raw,(list,tuple,set)) or not raw or any(not isinstance(x,str) or not x.strip() for x in raw):
            return _blocked("each benchmark partition must contain nonempty string IDs")
        if len(set(raw))!=len(raw): return _blocked("duplicate task IDs within a partition")
        sets.append(set(raw))
    train,evaluate,holdout=sets
    overlaps={"training_evaluation":sorted(train&evaluate),"training_holdout":sorted(train&holdout),
              "evaluation_holdout":sorted(evaluate&holdout)}
    ok=not any(overlaps.values())
    return _seal({"status":"BENCHMARK_PARTITIONS_DISJOINT" if ok else "BENCHMARK_PARTITION_OVERLAP",
                  "partition_sizes":{"training":len(train),"evaluation":len(evaluate),"holdout":len(holdout)},
                  "overlaps":overlaps,"task_identity_proven":False})


def stage343_check_guardrail_noninferiority(*, guardrail_deltas: Mapping,
                                            maximum_allowed_regression: float=0.02,
                                            minimum_guardrails: int=1, held: bool=False):
    """Require each caller-declared guardrail delta to remain above a negative tolerance."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(guardrail_deltas,Mapping) or isinstance(minimum_guardrails,bool)
        or not isinstance(minimum_guardrails,int) or minimum_guardrails<1
        or len(guardrail_deltas)<minimum_guardrails or not _finite(maximum_allowed_regression)
        or maximum_allowed_regression<0):
        return _blocked("guardrail inputs or bounds are invalid")
    deltas={}
    for name,value in guardrail_deltas.items():
        if not isinstance(name,str) or not name or not _finite(value): return _blocked("guardrail deltas must be finite")
        deltas[name]=float(value)
    worst=min(deltas.values())
    ok=worst>=-maximum_allowed_regression
    return _seal({"status":"GUARDRAIL_NONINFERIORITY_PASSED" if ok else "GUARDRAIL_REGRESSION_DETECTED",
                  "guardrail_deltas":dict(sorted(deltas.items())),"worst_delta":worst,
                  "maximum_allowed_regression":float(maximum_allowed_regression),
                  "guardrail_completeness_authenticated":False})


def stage344_check_evidence_source_diversity(*, source_evidence_counts: Mapping,
                                             minimum_sources: int=3,
                                             maximum_source_share: float=.6, held: bool=False):
    """Require a minimum source count and cap each declared source's evidence share."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(source_evidence_counts,Mapping) or isinstance(minimum_sources,bool)
        or not isinstance(minimum_sources,int) or minimum_sources<2 or len(source_evidence_counts)<minimum_sources
        or not _finite(maximum_source_share) or not 0<maximum_source_share<=1):
        return _blocked("source diversity inputs or bounds are invalid")
    counts={}
    for name,count in source_evidence_counts.items():
        if not isinstance(name,str) or not name or isinstance(count,bool) or not isinstance(count,int) or count<=0:
            return _blocked("source names and positive integer counts are required")
        counts[name]=count
    total=sum(counts.values()); shares={k:v/total for k,v in counts.items()}; worst=max(shares.values())
    ok=worst<=maximum_source_share
    return _seal({"status":"EVIDENCE_SOURCE_DIVERSITY_PASSED" if ok else "EVIDENCE_SOURCE_CONCENTRATION_FAILED",
                  "source_count":len(counts),"source_shares":dict(sorted(shares.items())),
                  "maximum_observed_source_share":worst,"maximum_source_share":float(maximum_source_share),
                  "source_independence_authenticated":False})


def stage345_integrate_replication_leakage_regression(*, replication_result: Mapping,
                                                       partition_result: Mapping,
                                                       guardrail_result: Mapping,
                                                       diversity_result: Mapping, held: bool=False):
    if held is not False: return _blocked("HOLD state must be explicitly false")
    gates=((replication_result,"REPLICATION_CONSISTENCY_PASSED"),
           (partition_result,"BENCHMARK_PARTITIONS_DISJOINT"),
           (guardrail_result,"GUARDRAIL_NONINFERIORITY_PASSED"),
           (diversity_result,"EVIDENCE_SOURCE_DIVERSITY_PASSED"))
    if not all(_valid(r,s) for r,s in gates): return _blocked("all four sealed replication/leakage/regression gates must pass")
    return _seal({"status":"REPLICATION_LEAKAGE_REGRESSION_PASSED",
                  "evidence_digests":[r["result_digest"] for r,_ in gates],
                  "decision_scope":"proposal eligibility for separate review only",
                  "independent_replication_proven":False,"benchmark_leakage_absence_proven":False,
                  "guardrail_completeness_proven":False,"source_independence_proven":False,
                  "causal_gain_proven":False,"recursive_self_improvement_proven":False,"asi_demonstrated":False})
