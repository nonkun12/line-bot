from core.ai_factory_stage491_495_failure_analysis import *
def test_491_taxonomy_fail_closed():
 r=[{"failure_id":"f1","category":"test","symptom":"s","evidence_ref":"e","impact":"i"}]
 assert check_failure_taxonomy(r,["test"])["pass"]
 assert not check_failure_taxonomy(r,[])["pass"]
def test_492_cause_evidence_requires_counterevidence_and_confidence():
 a=[{"failure_id":"f1","hypothesis":"h","supporting_evidence":"s","counter_evidence":"c","confidence":0.6}]
 assert check_root_cause_evidence(a)["pass"]
 assert not check_root_cause_evidence([{**a[0],"confidence":2}])["pass"]
def test_493_proposals_are_scope_bounded_and_reviewed():
 p=[{"proposal_id":"p","change_type":"test_only","target_files":["test.py"],"rationale":"r","rollback_plan":"b","test_plan":"t","review_required":True}]
 assert check_repair_proposal_bounds(p,max_scope_files=2,allowed_types=["test_only"])["pass"]
 assert not check_repair_proposal_bounds([{**p[0],"target_files":["a","b","c"]}],max_scope_files=2,allowed_types=["test_only"])["pass"]
def test_494_validation_does_not_consume_approval():
 p=[{"proposal_id":"p"}]
 v={"baseline_ref":"b","test_suite_ref":"t","review_ref":"r","tests_passed":True,"regression_check_passed":True}
 assert check_repair_validation(p,v)["pass"]
 assert not check_repair_validation(p,{**v,"tests_passed":False})["pass"]
def test_495_gate_never_executes_or_authorizes():
 r=evaluate_stages_491_495(failures=[],required_categories=["test"],root_causes=[],proposals=[],max_scope_files=2,allowed_types=["test_only"],validation={},unresolved_holds=[])
 assert r["status"]=="HOLD" and r["repairs_executed"] is False and r["merge_authorized"] is False
