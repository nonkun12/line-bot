from core.ai_factory_stage356_360_evidence_governance_provenance import *

D="a"*64

def manifest():
    return stage356_validate_evidence_manifest(
        entries=[{"evidence_id":"ev-1","kind":"protocol","sha256":D},
                 {"evidence_id":"ev-2","kind":"results","sha256":"b"*64}],
        required_kinds=["protocol","results"])

def sources():
    return stage357_check_source_declarations(
        sources=[{"source_id":"s1","origin":"dataset-a","collection_method":"export"},
                 {"source_id":"s2","origin":"dataset-b","collection_method":"api"}])

def chain(parent):
    return stage358_check_evidence_chain(parent_result=parent,
        expected_parent_digest=parent["result_digest"],
        child_parent_digest=parent["result_digest"])

def evaluators():
    return stage359_check_evaluator_coverage(
        evaluations=[{"evaluator_id":"e1","verdict":"PASS"},
                     {"evaluator_id":"e2","verdict":"PASS"}])

def test_356_manifest_requires_unique_ids_valid_digests_and_kinds():
    assert manifest()["status"]=="EVIDENCE_MANIFEST_PASSED"
    bad=stage356_validate_evidence_manifest(
        entries=[{"evidence_id":"x","kind":"protocol","sha256":D},
                 {"evidence_id":"x","kind":"results","sha256":D}],
        required_kinds=["protocol","results"])
    assert bad["status"]=="INSUFFICIENT_EVIDENCE"

def test_357_source_declarations_require_minimum_unique_sources():
    assert sources()["status"]=="SOURCE_DECLARATIONS_PASSED"
    one=stage357_check_source_declarations(
        sources=[{"source_id":"s1","origin":"same","collection_method":"export"}],
        minimum_distinct_sources=2)
    assert one["status"]=="SOURCE_DIVERSITY_INSUFFICIENT"

def test_358_evidence_chain_requires_sealed_parent_and_matching_digest():
    parent=manifest()
    assert chain(parent)["status"]=="EVIDENCE_CHAIN_PASSED"
    assert stage358_check_evidence_chain(parent_result=parent,
        expected_parent_digest="c"*64,child_parent_digest=parent["result_digest"])["status"]=="EVIDENCE_CHAIN_BROKEN"
    forged=dict(parent); forged["entry_count"]=99
    assert stage358_check_evidence_chain(parent_result=forged,
        expected_parent_digest=parent["result_digest"],
        child_parent_digest=parent["result_digest"])["status"]=="INSUFFICIENT_EVIDENCE"

def test_359_evaluator_coverage_and_agreement():
    assert evaluators()["status"]=="EVALUATOR_COVERAGE_PASSED"
    split=stage359_check_evaluator_coverage(
        evaluations=[{"evaluator_id":"e1","verdict":"PASS"},
                     {"evaluator_id":"e2","verdict":"FAIL"}],
        minimum_agreement=.75)
    assert split["status"]=="EVALUATOR_DISAGREEMENT"

def test_360_integrated_governance_is_sealed_and_fail_closed():
    parent=manifest()
    out=stage360_integrate_evidence_governance(
        manifest_result=parent,source_result=sources(),chain_result=chain(parent),
        evaluator_result=evaluators())
    assert out["status"]=="EVIDENCE_GOVERNANCE_PASSED"
    assert out["production_readiness_authorized"] is False
    forged=dict(sources()); forged["distinct_source_count"]=100
    assert stage360_integrate_evidence_governance(
        manifest_result=parent,source_result=forged,chain_result=chain(parent),
        evaluator_result=evaluators())["status"]=="INSUFFICIENT_EVIDENCE"
    assert stage360_integrate_evidence_governance(
        manifest_result=parent,source_result=sources(),chain_result=chain(parent),
        evaluator_result=evaluators(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
