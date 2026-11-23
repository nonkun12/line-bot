import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage556",Path(__file__).parents[1]/"core/ai_factory_stage556_560_evaluator_independence.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"evaluator_id":"eval1","evaluator_role":"external","evaluator_method_ref":"method1",
 "conflict_declarations":{"financial":"none_declared"},"access_scope":{"dataset":"read_only"},"blindness_record":"blinded",
 "evaluator_input_refs":["in1"],"evaluator_output_refs":["out1"],"evaluation_trace_refs":["trace1"],
 "reviewer_identity_ref":"reviewer1","review_scope":"independent","review_findings_ref":"findings1"}

def test_complete_declarations_do_not_prove_independence():
 x=m.stage_560_independence_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["independence_established"] is False and x["self_certification_sufficient"] is False

def test_conflicts_and_unblinded_review_block():
 x=good();x["conflict_declarations"]["financial"]="declared"
 assert m.validate_evaluator_independence(x)["status"]=="BLOCKED"
 x=good();x["blindness_record"]="unknown"
 assert m.validate_evaluator_independence(x)["status"]=="BLOCKED"

def test_duplicate_evidence_blocks():
 x=good();x["evaluation_trace_refs"]=["t","t"]
 assert m.validate_evaluator_independence(x)["status"]=="BLOCKED"

def test_missing_reviewer_scope_blocks():
 x=good();x["review_scope"]="unknown"
 assert m.validate_evaluator_independence(x)["status"]=="BLOCKED"
