"""Stages 356-360: evidence manifest, source declarations, chain continuity and evaluator coverage."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
import json

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

def _hex_digest(value):
    return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)

def stage356_validate_evidence_manifest(*, entries: list, required_kinds: list, held: bool=False):
    """Require unique evidence IDs, valid digests and declared required evidence kinds."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(entries,list) or not entries or not isinstance(required_kinds,list) or not required_kinds:
        return _blocked("manifest and required evidence kinds must be nonempty lists")
    ids=set()
    kinds=set()
    for entry in entries:
        if not isinstance(entry,Mapping):
            return _blocked("each manifest entry must be a mapping")
        evidence_id=entry.get("evidence_id")
        kind=entry.get("kind")
        digest=entry.get("sha256")
        if not isinstance(evidence_id,str) or not evidence_id.strip() or evidence_id in ids:
            return _blocked("evidence IDs must be nonempty and unique")
        if not isinstance(kind,str) or not kind.strip() or not _hex_digest(digest):
            return _blocked("each entry needs a kind and lowercase SHA-256 digest")
        ids.add(evidence_id)
        kinds.add(kind)
    missing=sorted(set(required_kinds)-kinds)
    ok=not missing
    return _seal({"status":"EVIDENCE_MANIFEST_PASSED" if ok else "EVIDENCE_MANIFEST_INCOMPLETE",
                  "entry_count":len(entries),"missing_required_kinds":missing,
                  "manifest_authenticity_proven":False})

def stage357_check_source_declarations(*, sources: list, minimum_distinct_sources: int=2, held: bool=False):
    """Require unique source IDs and explicit origin/method declarations; independence is not proven."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(sources,list) or not sources or isinstance(minimum_distinct_sources,bool) or not isinstance(minimum_distinct_sources,int) or minimum_distinct_sources<1:
        return _blocked("source declarations or minimum count are invalid")
    ids=set()
    normalized=[]
    for source in sources:
        if not isinstance(source,Mapping):
            return _blocked("each source declaration must be a mapping")
        source_id=source.get("source_id")
        origin=source.get("origin")
        method=source.get("collection_method")
        if not isinstance(source_id,str) or not source_id.strip() or source_id in ids:
            return _blocked("source IDs must be nonempty and unique")
        if not isinstance(origin,str) or not origin.strip() or not isinstance(method,str) or not method.strip():
            return _blocked("each source needs origin and collection method")
        ids.add(source_id)
        normalized.append({"source_id":source_id,"origin":origin.strip(),"collection_method":method.strip()})
    ok=len(ids)>=minimum_distinct_sources
    return _seal({"status":"SOURCE_DECLARATIONS_PASSED" if ok else "SOURCE_DIVERSITY_INSUFFICIENT",
                  "distinct_source_count":len(ids),"minimum_distinct_sources":minimum_distinct_sources,
                  "sources":sorted(normalized,key=lambda x:x["source_id"]),
                  "source_independence_authenticated":False})

def stage358_check_evidence_chain(*, parent_result: Mapping, expected_parent_digest: str,
                                  child_parent_digest: str, held: bool=False):
    """Require a valid sealed parent result and exact declared parent-digest continuity."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _hex_digest(expected_parent_digest) or not _hex_digest(child_parent_digest):
        return _blocked("parent digests must be lowercase SHA-256 values")
    if not isinstance(parent_result,Mapping) or not isinstance(parent_result.get("result_digest"),str):
        return _blocked("sealed parent result is missing")
    actual=parent_result.get("result_digest")
    parent_status=parent_result.get("status")
    if not _sealed(parent_result,parent_status):
        return _blocked("parent result seal is invalid")
    ok=actual==expected_parent_digest==child_parent_digest
    return _seal({"status":"EVIDENCE_CHAIN_PASSED" if ok else "EVIDENCE_CHAIN_BROKEN",
                  "parent_digest":actual,"digest_continuity_match":ok,
                  "chain_of_custody_authenticated":False})

def stage359_check_evaluator_coverage(*, evaluations: list, required_evaluators: int=2,
                                      minimum_agreement: float=1.0, held: bool=False):
    """Require distinct declared evaluator IDs and minimum exact agreement on a common verdict."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(evaluations,list) or not evaluations or isinstance(required_evaluators,bool) or not isinstance(required_evaluators,int) or required_evaluators<1 or isinstance(minimum_agreement,bool) or not isinstance(minimum_agreement,(int,float)) or not 0<minimum_agreement<=1:
        return _blocked("evaluator coverage inputs are invalid")
    ids=set()
    verdicts=[]
    for item in evaluations:
        if not isinstance(item,Mapping):
            return _blocked("each evaluation must be a mapping")
        evaluator=item.get("evaluator_id")
        verdict=item.get("verdict")
        if not isinstance(evaluator,str) or not evaluator.strip() or evaluator in ids or not isinstance(verdict,str) or not verdict.strip():
            return _blocked("evaluator IDs must be unique and verdicts nonempty")
        ids.add(evaluator)
        verdicts.append(verdict.strip())
    if len(ids)<required_evaluators:
        return _blocked("required evaluator count not met")
    counts={value:verdicts.count(value) for value in set(verdicts)}
    agreement=max(counts.values())/len(verdicts)
    ok=agreement>=minimum_agreement
    return _seal({"status":"EVALUATOR_COVERAGE_PASSED" if ok else "EVALUATOR_DISAGREEMENT",
                  "evaluator_count":len(ids),"agreement_ratio":agreement,
                  "verdict_counts":dict(sorted(counts.items())),
                  "evaluator_independence_authenticated":False})

def stage360_integrate_evidence_governance(*, manifest_result: Mapping, source_result: Mapping,
                                           chain_result: Mapping, evaluator_result: Mapping, held: bool=False):
    """Seal the proposal-only evidence governance decision; any missing or forged gate blocks."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates=((manifest_result,"EVIDENCE_MANIFEST_PASSED"),
           (source_result,"SOURCE_DECLARATIONS_PASSED"),
           (chain_result,"EVIDENCE_CHAIN_PASSED"),
           (evaluator_result,"EVALUATOR_COVERAGE_PASSED"))
    if not all(_sealed(result,status) for result,status in gates):
        return _blocked("all four sealed evidence-governance gates must pass")
    return _seal({"status":"EVIDENCE_GOVERNANCE_PASSED",
                  "evidence_digests":[result["result_digest"] for result,_ in gates],
                  "decision_scope":"proposal eligibility for separate review only",
                  "evidence_truth_authenticated":False,"source_independence_proven":False,
                  "evaluator_independence_proven":False,"task_execution_authorized":False,
                  "production_readiness_authorized":False,"asi_demonstrated":False})
