"""Safe repair verification and containment gates for AI Factory stages 496-500."""
from __future__ import annotations__
import hashlib,json,math
from typing import Any,Mapping,Sequence

def _seal(v:Any)->str:
 return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _s(v:Any)->bool:return isinstance(v,str) and bool(v.strip())
def _finite(v:Any)->bool:return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def check_change_manifest(manifest:Mapping[str,Any],*,allowed_paths:Sequence[str],max_files:int)->dict:
 errors=[];paths=manifest.get("files")
 if not isinstance(paths,list) or not paths: errors.append("manifest_files_missing"); paths=[]
 if not isinstance(max_files,int) or isinstance(max_files,bool) or max_files<1: errors.append("manifest_max_files_invalid");limit=1
 else:limit=max_files
 if len(paths)>limit:errors.append("manifest_scope_limit_exceeded")
 allow=set(allowed_paths)
 seen=set()
 for i,p in enumerate(paths):
  if not _s(p):errors.append(f"manifest_path_invalid:{i}")
  elif p in seen:errors.append(f"manifest_path_duplicate:{i}")
  else:seen.add(p)
  if p not in allow:errors.append(f"manifest_path_not_allowlisted:{i}")
 if manifest.get("scope_expanded") is True:errors.append("manifest_scope_expansion_disallowed")
 return {"stage":496,"pass":not errors,"errors":errors,"file_count":len(paths),"limit":limit}

def check_test_and_regression_evidence(evidence:Mapping[str,Any])->dict:
 errors=[]
 for f in ("baseline_sha","candidate_sha","tests_ref","regression_ref","review_ref"):
  if not _s(evidence.get(f)):errors.append(f"evidence_missing:{f}")
 if evidence.get("tests_passed") is not True:errors.append("tests_not_passed")
 if evidence.get("regressions_detected") is not False:errors.append("regressions_not_cleared")
 if evidence.get("review_complete") is not True:errors.append("review_not_complete")
 if evidence.get("head_sha_match") is not True:errors.append("head_sha_mismatch")
 return {"stage":497,"pass":not errors,"errors":errors}

def check_containment(controls:Mapping[str,Any])->dict:
 errors=[]
 expected=("production_unchanged","no_secrets_access","no_permission_changes","no_merge","no_deploy","hold_preserved")
 for f in expected:
  if controls.get(f) is not True:errors.append(f"containment_control_missing:{f}")
 if controls.get("external_side_effects") is not False:errors.append("external_side_effects_not_disallowed")
 return {"stage":498,"pass":not errors,"errors":errors}

def check_repair_outcome(outcome:Mapping[str,Any])->dict:
 errors=[]
 for f in ("proposal_id","before_ref","after_ref","outcome_ref"):
  if not _s(outcome.get(f)):errors.append(f"repair_outcome_missing:{f}")
 if outcome.get("applied") is not False:errors.append("repair_execution_not_allowed")
 if outcome.get("benefit_verified") is not False:errors.append("benefit_claim_not_allowed")
 return {"stage":499,"pass":not errors,"errors":errors}

def evaluate_stages_496_500(*,manifest,allowed_paths,max_files,evidence,containment,outcome,unresolved_holds):
 checks=[check_change_manifest(manifest,allowed_paths=allowed_paths,max_files=max_files),check_test_and_regression_evidence(evidence),check_containment(containment),check_repair_outcome(outcome)]
 hold_errors=[]
 if unresolved_holds:hold_errors.append("unresolved_holds_present")
 checks.append({"stage":500,"pass":not hold_errors,"errors":hold_errors,"hold_count":len(unresolved_holds)})
 passed=all(c["pass"] for c in checks);record={"checks":checks,"pass":passed}
 return {"stage":500,"status":"READY_FOR_REVIEW" if passed else "HOLD","checks":checks,"seal":_seal(record),"repair_applied":False,"benefit_verified":False,"hold_release_authorized":False,"execution_authorized":False,"promotion_authorized":False,"merge_authorized":False,"deployment_authorized":False,"proposal_only":True}
