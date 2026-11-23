from core.ai_factory_stage496_500_safe_repair_validation import (
 check_change_manifest,check_containment,check_repair_outcome,check_test_and_regression_evidence,evaluate_stages_496_500)
def test_496_allowlist_scope():
 assert check_change_manifest({"files":["test.py"]},allowed_paths=["test.py"],max_files=1)["pass"]
 assert not check_change_manifest({"files":["prod.py"]},allowed_paths=["test.py"],max_files=1)["pass"]
def test_497_exact_head_and_validation_refs():
 good={"baseline_sha":"b","candidate_sha":"c","tests_ref":"t","regression_ref":"g","review_ref":"r","tests_passed":True,"regressions_detected":False,"review_complete":True,"head_sha_match":True}
 assert check_test_and_regression_evidence(good)["pass"]
 assert not check_test_and_regression_evidence({**good,"head_sha_match":False})["pass"]
def test_498_containment_fail_closed():
 controls={k:True for k in ("production_unchanged","no_secrets_access","no_permission_changes","no_merge","no_deploy","hold_preserved")}
 controls["external_side_effects"]=False
 assert check_containment(controls)["pass"]
 assert not check_containment({**controls,"hold_preserved":False})["pass"]
def test_499_proposal_only_outcome_contract():
 o={"proposal_id":"p","before_ref":"b","after_ref":"a","outcome_ref":"r","applied":False,"benefit_verified":False}
 assert check_repair_outcome(o)["pass"]
 assert not check_repair_outcome({**o,"applied":True})["pass"]
def test_500_final_gate_hold_and_no_authority():
 args=dict(manifest={"files":["test.py"]},allowed_paths=["test.py"],max_files=1,
 evidence={"baseline_sha":"b","candidate_sha":"c","tests_ref":"t","regression_ref":"g","review_ref":"r","tests_passed":True,"regressions_detected":False,"review_complete":True,"head_sha_match":True},
 containment={k:True for k in ("production_unchanged","no_secrets_access","no_permission_changes","no_merge","no_deploy","hold_preserved")} | {"external_side_effects":False},
 outcome={"proposal_id":"p","before_ref":"b","after_ref":"a","outcome_ref":"r","applied":False,"benefit_verified":False},unresolved_holds=[])
 args["containment"]["external_side_effects"]=False
 r=evaluate_stages_496_500(**args)
 assert r["status"]=="READY_FOR_REVIEW" and r["repair_applied"] is False and r["merge_authorized"] is False
 args["unresolved_holds"]=[{"id":"h"}]
 assert evaluate_stages_496_500(**args)["status"]=="HOLD"
