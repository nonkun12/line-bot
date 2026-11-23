import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("autonomy",Path(__file__).parents[1]/"core/ai_factory_stage526_530_bounded_autonomy.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_capability_scope_no_grants():
 assert m.capability_scope_check({})["status"]=="BLOCKED"
 ok={"requested_capabilities":["read","propose"],"scope_ref":"s","hold":True}
 assert m.capability_scope_check(ok)["capabilities_granted"]==[]

def test_budget_validation():
 assert m.budget_check({})["status"]=="BLOCKED"
 ok={"task_limit":2,"time_budget_ref":"t","resource_budget_ref":"r","hold":True}
 assert m.budget_check(ok)["budget_enforced"] is False

def test_forbidden_actions_block_without_execution():
 assert m.forbidden_action_check(["deploy","hold_release"])["status"]=="BLOCKED"
 assert m.forbidden_action_check(["read"])["actions_executed"] is False

def test_handoff_and_integrated_gate_fail_closed():
 hand={"handoff_target_ref":"h","handoff_reason_ref":"r","handoff_required":True}
 scope={"requested_capabilities":["read"],"scope_ref":"s","hold":True}
 budget={"task_limit":1,"time_budget_ref":"t","resource_budget_ref":"r","hold":True}
 out=m.autonomy_gate(scope,budget,["read"],hand)
 assert out["status"]=="READY_FOR_REVIEW"
 assert out["autonomy_enabled"] is False and out["capabilities_granted"]==[]
