import hashlib
from core.ai_factory_stage301_305_distribution_lineage_readiness import (
 stage301_check_score_distribution,stage302_check_domain_mix_shift,
 stage303_check_missingness_sensitivity,stage304_validate_evidence_lineage,
 stage305_integrate_evidence_readiness)

def h(s): return hashlib.sha256(s.encode()).hexdigest()

def dist():
 return stage301_check_score_distribution(baseline_scores=[.7,.8,.9],candidate_scores=[.71,.8,.89])
def mix():
 return stage302_check_domain_mix_shift(baseline_counts={"a":50,"b":50},candidate_counts={"a":51,"b":49})
def miss():
 return stage303_check_missingness_sensitivity(observed_scores=[.8,.9,.85],missing_fraction=.1,worst_case_score=.5,minimum_adjusted_mean=.7)
def lineage():
 root=h("root"); body={"record_id":"r1","parent_digest":root,"payload":{"event":"sealed"}}
 import json
 digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
 return stage304_validate_evidence_lineage(records=[{**body,"record_digest":digest}],root_digest=root)

def test_301_score_moments_shift_gate():
 assert dist()["status"]=="SCORE_DISTRIBUTION_STABLE"
 assert stage301_check_score_distribution(baseline_scores=[.1,.2,.3],candidate_scores=[.8,.9,1.])["status"]=="SCORE_DISTRIBUTION_SHIFT"
def test_302_domain_mix_shift_gate():
 assert mix()["status"]=="DOMAIN_MIX_STABLE"
 assert stage302_check_domain_mix_shift(baseline_counts={"a":90,"b":10},candidate_counts={"a":10,"b":90})["status"]=="DOMAIN_MIX_SHIFT"
def test_303_missingness_conservative_adjustment():
 assert miss()["status"]=="MISSINGNESS_ROBUST"
 assert stage303_check_missingness_sensitivity(observed_scores=[.6,.6],missing_fraction=.5,worst_case_score=0,minimum_adjusted_mean=.5)["status"]=="MISSINGNESS_SENSITIVE"
def test_304_digest_linked_lineage_and_tamper_rejection():
 assert lineage()["status"]=="EVIDENCE_LINEAGE_VALID"
 x=lineage(); x["record_count"]=99
 assert stage305_integrate_evidence_readiness(distribution_result=dist(),domain_mix_result=mix(),missingness_result=miss(),lineage_result=x)["status"]=="INSUFFICIENT_EVIDENCE"
def test_305_integrates_all_gates_fail_closed():
 result=stage305_integrate_evidence_readiness(distribution_result=dist(),domain_mix_result=mix(),missingness_result=miss(),lineage_result=lineage())
 assert result["status"]=="EVIDENCE_READINESS_PASSED" and result["asi_demonstrated"] is False
 assert stage305_integrate_evidence_readiness(distribution_result=dist(),domain_mix_result=mix(),missingness_result=miss(),lineage_result=lineage(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
