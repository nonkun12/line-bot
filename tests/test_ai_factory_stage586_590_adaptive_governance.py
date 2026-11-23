import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage586",Path(__file__).parents[1]/"core/ai_factory_stage586_590_adaptive_governance.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"policy_version":"v1","policy_owner_ref":"owner1","policy_change_reason":"quarterly evidence review",
 "change_impact_assessment":{"risk":"bounded"},"affected_capability_refs":["cap1"],"compatibility_checks":{"backward":"pass"},
 "monitoring_signal_refs":["signal1"],"review_interval":"30d","alert_thresholds":{"regression":0.05},
 "escalation_matrix":{"critical":"pause"},"pause_conditions":["guardrail breach"],"recovery_criteria":["review complete"],
 "policy_approval_ref":"approval1","automatic_policy_activation":False,"production_policy_write":False}

def test_complete_governance_plan_still_needs_review():
 x=m.stage_590_governance_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["policy_change_executed"] is False and x["automatic_activation"] is False

def test_missing_approval_blocks():
 x=good();x["policy_approval_ref"]=""
 assert m.validate_adaptive_governance(x)["status"]=="BLOCKED"

def test_automatic_activation_and_production_write_block():
 for field in ("automatic_policy_activation","production_policy_write"):
  x=good();x[field]=True
  assert m.validate_adaptive_governance(x)["status"]=="BLOCKED"

def test_missing_monitoring_and_pause_conditions_block():
 x=good();x["monitoring_signal_refs"]=[];x["pause_conditions"]=[]
 assert m.validate_adaptive_governance(x)["status"]=="BLOCKED"
