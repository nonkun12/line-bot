import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage571",Path(__file__).parents[1]/"core/ai_factory_stage571_575_capability_diagnostics.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"capability_profile_ref":"profile1","capability_dimensions":["reasoning","coding"],"evaluation_scope":"offline benchmark",
 "baseline_ref":"baseline1","task_cohorts":["easy","hard"],"baseline_method":"stratified_suite",
 "weakness_findings":["tool-use weakness"],"uncertainty_register":{"sample":"small"},"known_limitations":["no live validation"],
 "improvement_hypotheses":["better retrieval improves factuality"],"causal_rationale":"Retrieval adds relevant evidence to responses.",
 "falsification_criteria":["no score gain"],"evaluation_owner":"independent"}

def test_complete_declarations_do_not_authorize_candidate():
 x=m.stage_575_candidate_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["capability_measured"] is False and x["candidate_authorized"] is False

def test_missing_weakness_and_uncertainty_block():
 x=good();x["weakness_findings"]=[];x["uncertainty_register"]={}
 assert m.validate_capability_diagnostics(x)["status"]=="BLOCKED"

def test_unsupported_baseline_method_blocks():
 x=good();x["baseline_method"]="self_report"
 assert m.validate_capability_diagnostics(x)["status"]=="BLOCKED"

def test_empty_falsification_criteria_blocks():
 x=good();x["falsification_criteria"]=[]
 assert m.validate_capability_diagnostics(x)["status"]=="BLOCKED"
