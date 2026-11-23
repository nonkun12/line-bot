from core.ai_factory_stage501_505_repair_candidate_ranking import *
def sample():
 return {"candidate_id":"c1","change_summary":"small fix","evidence_ref":"e","test_plan_ref":"t","rollback_ref":"r","risk_class":"low","estimated_cost":1.2,"expected_impact":0.5,"scope_files":["test.py"]}
def test_501_rank_deterministically():
 out=rank_candidates([sample()],allowed_risk=["low"])
 assert out["result"]["ranked_ids"]==["c1"] and not out["execution_authorized"]
def test_502_conflict_requires_evidence():
 assert not check_repair_conflicts([{"candidate_a":"a","candidate_b":"b","conflict_type":"overlap","evidence_ref":"e"}])["pass"]
def test_503_dependency_cycle_detection():
 assert check_candidate_dependency_graph(["a","b"],[{"from":"a","to":"b"}])["pass"]
 assert not check_candidate_dependency_graph(["a","b"],[{"from":"a","to":"b"},{"from":"b","to":"a"}])["pass"]
def test_504_risk_mitigation_declaration():
 e=[{"candidate_id":"c","risk_class":"low","mitigation_ref":"m","rollback_ref":"r","mitigated":True}]
 assert check_repair_risk_matrix(e,["low"])["pass"]
def test_505_holds_fail_closed_and_no_execution():
 r=evaluate_501_505(candidates=[sample()],allowed_risk=["low"],max_candidates=5,conflicts=[{"candidate_a":"a","candidate_b":"b","conflict_type":"x","evidence_ref":"e"}],nodes=["a"],edges=[],risk_matrix=[{"candidate_id":"c","risk_class":"low","mitigation_ref":"m","rollback_ref":"r","mitigated":True}],risk_levels=["low"],unresolved_holds=[{"hold":"h"}])
 assert r["status"]=="HOLD" and not r["execution_authorized"]
