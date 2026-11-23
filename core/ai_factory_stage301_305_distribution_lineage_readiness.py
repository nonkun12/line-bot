"""Stages 301-305: distribution, missingness and evidence-lineage gates.

All observations are caller-supplied. Digests provide integrity linkage only,
not trusted provenance, authentication, causal proof or capability proof.
No stage authorizes execution, experiments, model changes, merge/deploy or HOLD release.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math

_FALSE={"proposal_only":True,"task_execution_authorized":False,
        "experiment_execution_authorized":False,"model_change_authorized":False,
        "merge_deploy_authorized":False,"hold_release_authorized":False}

def _hash(x):
    return sha256(json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _digest(x):
    return isinstance(x,str) and len(x)==64 and all(c in "0123456789abcdef" for c in x)

def _num(x):
    return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)

def _blocked(reason):
    return {"status":"INSUFFICIENT_EVIDENCE","reason":reason,**_FALSE}

def _seal(payload):
    out={**payload,**_FALSE}; out["result_digest"]=_hash(out); return out

def _sealed(x,status):
    if not isinstance(x,Mapping) or x.get("status")!=status or any(x.get(k) is not v for k,v in _FALSE.items()):
        return False
    try: return _digest(x.get("result_digest")) and x["result_digest"]==_hash({k:v for k,v in x.items() if k!="result_digest"})
    except (TypeError,ValueError): return False


def stage301_check_score_distribution(*, baseline_scores: Sequence[float],
                                      candidate_scores: Sequence[float],
                                      maximum_mean_shift: float=0.10,
                                      maximum_variance_shift: float=0.05, held: bool=False):
    """Detect material score-distribution shift using bounded first/second moments."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(baseline_scores,Sequence) or isinstance(baseline_scores,(str,bytes))
        or not isinstance(candidate_scores,Sequence) or isinstance(candidate_scores,(str,bytes))
        or len(baseline_scores)<3 or len(candidate_scores)<3
        or not _num(maximum_mean_shift) or not 0<=maximum_mean_shift<=1
        or not _num(maximum_variance_shift) or not 0<=maximum_variance_shift<=1):
        return _blocked("score samples or shift thresholds are invalid")
    if any(not _num(v) or not 0<=v<=1 for v in list(baseline_scores)+list(candidate_scores)):
        return _blocked("scores must be finite and in [0,1]")
    def moments(xs):
        mean=sum(xs)/len(xs); return mean,sum((x-mean)**2 for x in xs)/len(xs)
    bm,bv=moments(list(baseline_scores)); cm,cv=moments(list(candidate_scores))
    md,vd=abs(cm-bm),abs(cv-bv)
    passed=md<=maximum_mean_shift and vd<=maximum_variance_shift
    return _seal({"status":"SCORE_DISTRIBUTION_STABLE" if passed else "SCORE_DISTRIBUTION_SHIFT",
                  "baseline_count":len(baseline_scores),"candidate_count":len(candidate_scores),
                  "baseline_mean":bm,"candidate_mean":cm,"mean_shift":md,
                  "baseline_variance":bv,"candidate_variance":cv,"variance_shift":vd,
                  "distribution_test_scope":"first and second moments only; not full distribution equivalence"})


def stage302_check_domain_mix_shift(*, baseline_counts: Mapping, candidate_counts: Mapping,
                                    maximum_total_variation: float=0.10, held: bool=False):
    """Compare declared domain proportions via total-variation distance."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(baseline_counts,Mapping) or not isinstance(candidate_counts,Mapping)
        or not _num(maximum_total_variation) or not 0<=maximum_total_variation<=1
        or not baseline_counts or set(baseline_counts)!=set(candidate_counts)):
        return _blocked("domain counts or threshold are invalid; domain sets must match")
    for counts in (baseline_counts,candidate_counts):
        if any(not isinstance(k,str) or not k.strip() or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in counts.items()):
            return _blocked("domain counts must be nonnegative integers")
        if sum(counts.values())<=0: return _blocked("domain count totals must be positive")
    bt=sum(baseline_counts.values()); ct=sum(candidate_counts.values())
    rows={k:{"baseline_share":baseline_counts[k]/bt,"candidate_share":candidate_counts[k]/ct} for k in sorted(baseline_counts)}
    tv=sum(abs(v["baseline_share"]-v["candidate_share"]) for v in rows.values())/2
    passed=tv<=maximum_total_variation
    return _seal({"status":"DOMAIN_MIX_STABLE" if passed else "DOMAIN_MIX_SHIFT",
                  "total_variation_distance":tv,"maximum_total_variation":float(maximum_total_variation),
                  "domain_shares":rows,"domain_labels_and_sampling_frames_caller_declared":True})


def stage303_check_missingness_sensitivity(*, observed_scores: Sequence[float],
                                           missing_fraction: float,
                                           worst_case_score: float=0.0,
                                           minimum_adjusted_mean: float=0.50, held: bool=False):
    """Compute conservative mean under a declared worst-case missing-score assumption."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(observed_scores,Sequence) or isinstance(observed_scores,(str,bytes))
        or not observed_scores or any(not _num(v) or not 0<=v<=1 for v in observed_scores)
        or not _num(missing_fraction) or not 0<=missing_fraction<1
        or not _num(worst_case_score) or not 0<=worst_case_score<=1
        or not _num(minimum_adjusted_mean) or not 0<=minimum_adjusted_mean<=1):
        return _blocked("observed scores or missingness assumptions are invalid")
    mean=sum(observed_scores)/len(observed_scores)
    adjusted=(1-missing_fraction)*mean+missing_fraction*worst_case_score
    passed=adjusted>=minimum_adjusted_mean
    return _seal({"status":"MISSINGNESS_ROBUST" if passed else "MISSINGNESS_SENSITIVE",
                  "observed_count":len(observed_scores),"observed_mean":mean,
                  "declared_missing_fraction":float(missing_fraction),
                  "worst_case_score_assumption":float(worst_case_score),
                  "conservative_adjusted_mean":adjusted,"minimum_adjusted_mean":float(minimum_adjusted_mean),
                  "missingness_mechanism_independently_verified":False})


def stage304_validate_evidence_lineage(*, records: Sequence[Mapping], root_digest: str,
                                       held: bool=False):
    """Validate an ordered digest-linked record chain from a declared root."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    if (not isinstance(records,Sequence) or isinstance(records,(str,bytes)) or not records
        or not _digest(root_digest)):
        return _blocked("records or root digest are invalid")
    previous=root_digest; ids=set(); validated=[]
    for index,row in enumerate(records):
        if not isinstance(row,Mapping): return _blocked("each lineage record must be a mapping")
        rid=row.get("record_id"); parent=row.get("parent_digest"); payload=row.get("payload")
        digest=row.get("record_digest")
        if (not isinstance(rid,str) or not rid.strip() or rid in ids or parent!=previous
            or not isinstance(payload,Mapping) or not _digest(digest)):
            return _blocked("record identity, parent, payload or digest is invalid")
        body={"record_id":rid,"parent_digest":parent,"payload":dict(payload)}
        try:\n            expected_digest=_hash(body)\n        except (TypeError, ValueError, OverflowError):\n            return _blocked("record payload is not canonical JSON data")\n        if digest!=expected_digest: return _blocked("record digest does not match canonical record content")
        ids.add(rid); validated.append(digest); previous=digest
    return _seal({"status":"EVIDENCE_LINEAGE_VALID","record_count":len(validated),
                  "root_digest":root_digest,"terminal_digest":previous,
                  "lineage_digest":_hash(validated),"external_custody_or_authenticity_verified":False})


def stage305_integrate_evidence_readiness(*, distribution_result: Mapping,
                                          domain_mix_result: Mapping,
                                          missingness_result: Mapping,
                                          lineage_result: Mapping, held: bool=False):
    """Require all evidence-quality checks; result is review eligibility only."""
    if held is not False: return _blocked("HOLD state must be explicitly false")
    gates=((distribution_result,"SCORE_DISTRIBUTION_STABLE"),
           (domain_mix_result,"DOMAIN_MIX_STABLE"),
           (missingness_result,"MISSINGNESS_ROBUST"),
           (lineage_result,"EVIDENCE_LINEAGE_VALID"))
    if not all(_sealed(x,s) for x,s in gates):
        return _blocked("all four sealed evidence-readiness gates must pass")
    return _seal({"status":"EVIDENCE_READINESS_PASSED",
                  "evidence_digests":[x["result_digest"] for x,_ in gates],
                  "decision_scope":"proposal eligibility for separate independent review only",
                  "capability_gain_proven":False,"recursive_self_improvement_proven":False,
                  "asi_demonstrated":False,"next_step":"ELIGIBLE_FOR_SEPARATE_RESEARCH_REVIEW"})
